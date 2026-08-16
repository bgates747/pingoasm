"""Raster acquisition for the feature-aware mesh experiment.

Builds two aligned numpy grids over the manifest's UTM10N footprint at a
30 m working step: a float32 elevation grid subsampled from the 10 m 3DEP
mosaic, and a uint8 three-class grid (0 green, 1 developed, 2 water) sampled
from the 30 m NLCD mosaic through a cs2cs-derived EPSG:32610->5070 lattice.

Runs on system python3 + numpy (documented deviation from the application
venv: this is experiment tooling, not an application build product). Reads
the application's dependency-free GeoTIFF metadata parser read-only.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np

EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
APPLICATION_ROOT = EXPERIMENT_ROOT.parent / "application"
sys.path.insert(0, str(APPLICATION_ROOT / "src"))

from pingo_terrain.geotiff import read_geotiff_metadata  # noqa: E402

MANIFEST_PATH = (
    APPLICATION_ROOT / "data" / "manifests" / "bay-area-2026-08-02.json"
)
DOWNLOAD_ROOT = APPLICATION_ROOT / "data" / "downloads"

WORK_STEP_M = 30.0
CLASS_GREEN = 0
CLASS_DEVELOPED = 1
CLASS_WATER = 2
NLCD_WATER = 11
NLCD_DEVELOPED = frozenset({21, 22, 23, 24})


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text())


def _dataset(manifest: dict, dataset_id: str) -> dict:
    for dataset in manifest["datasets"]:
        if dataset["id"] == dataset_id:
            return dataset
    raise KeyError(dataset_id)


def _read_tile_array(path: Path) -> tuple[object, np.ndarray]:
    """Materialize one validated uncompressed TIFF as a 2-D numpy array."""

    metadata = read_geotiff_metadata(path)
    if metadata.bits_per_sample == 8:
        dtype = np.dtype(metadata.byte_order + "u1")
    elif metadata.bits_per_sample == 32:
        dtype = np.dtype(metadata.byte_order + "f4")
    else:
        raise ValueError(f"unsupported sample width in {path}")
    out = np.empty((metadata.height, metadata.width), dtype=dtype)
    blocks_across = math.ceil(metadata.width / metadata.block_width)
    with path.open("rb") as handle:
        for index, (offset, size) in enumerate(
            zip(metadata.block_offsets, metadata.block_byte_counts)
        ):
            handle.seek(offset)
            payload = handle.read(size)
            if len(payload) != size:
                raise ValueError(f"truncated block {index} in {path}")
            block_row = index // blocks_across
            block_col = index % blocks_across
            row0 = block_row * metadata.block_height
            col0 = block_col * metadata.block_width
            rows = min(metadata.block_height, metadata.height - row0)
            cols = min(metadata.block_width, metadata.width - col0)
            data = np.frombuffer(payload, dtype=dtype)
            if data.size == metadata.block_height * metadata.block_width:
                block = data.reshape(metadata.block_height, metadata.block_width)
            elif data.size == rows * metadata.block_width:
                # Final strip: rows truncated, full block width.
                block = data.reshape(rows, metadata.block_width)
            else:
                raise ValueError(f"unexpected block payload in {path}")
            out[row0 : row0 + rows, col0 : col0 + cols] = block[:rows, :cols]
    return metadata, out


class MosaicArray:
    """One contiguous numpy mosaic assembled from manifest tiles."""

    def __init__(self, manifest: dict, dataset_id: str) -> None:
        dataset = _dataset(manifest, dataset_id)
        self.west, self.south, self.east, self.north = map(
            float, dataset["bbox"]
        )
        self.step_x, self.step_y = map(float, dataset["pixel_size_metres"])
        self.nodata = dataset.get("nodata")
        self.width = int(dataset["width"])
        self.height = int(dataset["height"])
        first = read_geotiff_metadata(
            APPLICATION_ROOT / dataset["tiles"][0]["local_path"]
        )
        fill = self.nodata if self.nodata is not None else 0
        self.values = np.full(
            (self.height, self.width),
            fill,
            dtype=np.uint8 if first.bits_per_sample == 8 else np.float32,
        )
        for item in dataset["tiles"]:
            metadata, tile = _read_tile_array(
                APPLICATION_ROOT / item["local_path"]
            )
            col0 = round((metadata.origin_x - self.west) / self.step_x)
            row0 = round((self.north - metadata.origin_y) / self.step_y)
            self.values[
                row0 : row0 + metadata.height, col0 : col0 + metadata.width
            ] = tile

    def lookup_nearest(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Vectorized nearest-pixel lookup at projected coordinates."""

        col = np.clip(
            np.floor((x - self.west) / self.step_x).astype(np.int64),
            0,
            self.width - 1,
        )
        row = np.clip(
            np.floor((self.north - y) / self.step_y).astype(np.int64),
            0,
            self.height - 1,
        )
        return self.values[row, col]


def _cs2cs_lattice(
    xs: np.ndarray, ys: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Transform a UTM10N lattice to EPSG:5070 with one cs2cs process."""

    grid_x, grid_y = np.meshgrid(xs, ys)
    lines = "\n".join(
        f"{x:.3f} {y:.3f}" for x, y in zip(grid_x.ravel(), grid_y.ravel())
    )
    result = subprocess.run(
        ["cs2cs", "-f", "%.4f", "EPSG:32610", "EPSG:5070"],
        input=lines,
        capture_output=True,
        text=True,
        check=True,
    )
    out = np.array(
        [line.split()[:2] for line in result.stdout.strip().splitlines()],
        dtype=np.float64,
    )
    shape = grid_x.shape
    return out[:, 0].reshape(shape), out[:, 1].reshape(shape)


def _bilinear_expand(
    lattice: np.ndarray,
    lattice_step: int,
    rows: int,
    cols: int,
) -> np.ndarray:
    """Bilinearly interpolate a coarse per-lattice grid to (rows, cols)."""

    r = np.arange(rows, dtype=np.float64) / lattice_step
    c = np.arange(cols, dtype=np.float64) / lattice_step
    r0 = np.minimum(r.astype(np.int64), lattice.shape[0] - 2)
    c0 = np.minimum(c.astype(np.int64), lattice.shape[1] - 2)
    fr = (r - r0)[:, None]
    fc = (c - c0)[None, :]
    v00 = lattice[np.ix_(r0, c0)]
    v01 = lattice[np.ix_(r0, c0 + 1)]
    v10 = lattice[np.ix_(r0 + 1, c0)]
    v11 = lattice[np.ix_(r0 + 1, c0 + 1)]
    return (
        v00 * (1 - fr) * (1 - fc)
        + v01 * (1 - fr) * fc
        + v10 * fr * (1 - fc)
        + v11 * fr * fc
    )


def build_working_grids() -> dict:
    """Return the aligned working-resolution elevation and class grids."""

    manifest = load_manifest()
    dem_dataset = _dataset(manifest, "usgs-3dep-10m-utm10n")
    west, south, east, north = map(float, dem_dataset["bbox"])
    cols = int((east - west) // WORK_STEP_M)
    rows = int((north - south) // WORK_STEP_M)

    dem10 = MosaicArray(manifest, "usgs-3dep-10m-utm10n")
    # Working sample (r, c) center sits at the 10 m sample (3r+1, 3c+1).
    dem = dem10.values[1 : 3 * rows : 3, 1 : 3 * cols : 3].astype(np.float32)
    nodata = dem_dataset.get("nodata")
    if nodata is not None:
        dem[dem == nodata] = np.nan
    del dem10

    nlcd = MosaicArray(manifest, "usgs-annual-nlcd-2025-epsg5070")
    lattice_step = 8
    lat_cols = np.arange(0, cols + lattice_step, lattice_step)
    lat_rows = np.arange(0, rows + lattice_step, lattice_step)
    lat_x = west + (lat_cols + 0.5) * WORK_STEP_M
    lat_y = north - (lat_rows + 0.5) * WORK_STEP_M
    albers_x, albers_y = _cs2cs_lattice(lat_x, lat_y)
    full_x = _bilinear_expand(albers_x, lattice_step, rows, cols)
    full_y = _bilinear_expand(albers_y, lattice_step, rows, cols)
    nlcd_values = nlcd.lookup_nearest(full_x, full_y)
    del full_x, full_y, nlcd

    classes = np.full((rows, cols), CLASS_GREEN, dtype=np.uint8)
    classes[np.isin(nlcd_values, tuple(NLCD_DEVELOPED))] = CLASS_DEVELOPED
    classes[nlcd_values == NLCD_WATER] = CLASS_WATER
    unknown = (nlcd_values == 0) | (nlcd_values == 250)
    classes[unknown & (np.nan_to_num(dem, nan=-1.0) < 0.0)] = CLASS_WATER

    return {
        "west": west,
        "south": south,
        "east": east,
        "north": north,
        "step": WORK_STEP_M,
        "dem": dem,
        "classes": classes,
    }


def majority_filter(classes: np.ndarray, iterations: int) -> np.ndarray:
    """3x3 majority vote per cell; ties keep the current class."""

    out = classes
    for _ in range(iterations):
        padded = np.pad(out, 1, mode="edge")
        counts = np.zeros((3,) + out.shape, dtype=np.uint8)
        for dr in range(3):
            for dc in range(3):
                window = padded[dr : dr + out.shape[0], dc : dc + out.shape[1]]
                for value in (CLASS_GREEN, CLASS_DEVELOPED, CLASS_WATER):
                    counts[value] += window == value
        best = counts.argmax(axis=0).astype(np.uint8)
        best_count = counts.max(axis=0)
        current_count = np.take_along_axis(
            counts, out[None].astype(np.int64), axis=0
        )[0]
        out = np.where(best_count > current_count, best, out)
    return out
