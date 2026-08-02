#!/usr/bin/env python3
"""Build deterministic Bay Area triangular terrain as AGNB/P3DM records.

The default is intentionally a small KOAK runway-start neighborhood.  Use
``--selection corridor`` for the KOAK--Berkeley--Mount Diablo proof or
``--selection full`` only after reviewing ``--budget-only`` output.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Iterable


ROOT = Path(__file__).resolve().parent.parent
SOURCE_MANIFEST = ROOT / "data/manifests/bay-area-2026-08-02.json"
DEFAULT_OUTPUT = ROOT / "build/p3dm/bay-area-koak-proof"

sys.path.insert(0, str(ROOT / "src"))

from pingo_terrain.geotiff import sha256_file  # noqa: E402
from pingo_terrain.materials import BERKELEY_TERRAIN_MATERIALS  # noqa: E402
from pingo_terrain.p3dm import make_container, make_data, parse_container  # noqa: E402
from pingo_terrain.regional_raster import RasterMosaic  # noqa: E402
from pingo_terrain.regional_terrain import (  # noqa: E402
    CHUNK_WIDTH_M,
    LODS,
    MODEL_HALF_EXTENT_M,
    REGIONAL_EPSG,
    REGIONAL_ORIGIN_EAST_M,
    REGIONAL_ORIGIN_NORTH_M,
    REGIONAL_VERTICAL_ORIGIN_M,
    SKIRT_DEPTH_M,
    SKIRT_FLOOR_ELEVATION_M,
    BuiltTerrainTile,
    WorldGrid,
    build_terrain_tile,
    predominant_category,
    triangular_topology,
)


DEM_DATASET_ID = "usgs-3dep-10m-utm10n"
NLCD_DATASET_ID = "usgs-annual-nlcd-2025-epsg5070"
NLCD_TO_MATERIAL = {
    item.nlcd_category: item.material_id for item in BERKELEY_TERRAIN_MATERIALS
}
UNKNOWN_LAND_MATERIAL = NLCD_TO_MATERIAL[24]
WATER_MATERIAL = NLCD_TO_MATERIAL[11]

# FAA physical threshold for KOAK 28L, converted to EPSG:32610 with PROJ
# 9.1.1. The WGS84 source coordinate and elevation remain in the manifest.
KOAK_START = {
    "airport_icao": "KOAK",
    "runway_end_id": "28L",
    "threshold_wgs84": [-122.2060093, 37.72227386],
    "threshold_easting_m": 569_972.905707,
    "threshold_northing_m": 4_175_298.105204,
    "surface_elevation_m": 2.49936,
    "initial_clearance_m": 1.5,
    "heading_true_deg": 292.163062,
}

CAMPANILE_UTM = (565_276.64, 4_191_883.96)
MOUNT_DIABLO_UTM = (595_484.82, 4_193_234.01)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--selection",
        choices=("koak-proof", "corridor", "full"),
        default="koak-proof",
        help="tile selection (default: koak-proof)",
    )
    parser.add_argument(
        "--lods",
        default="0,1,2",
        help="comma-separated LODs from 0,1,2 (default: 0,1,2)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"output root (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--budget-only",
        action="store_true",
        help="derive counts and byte budgets without reading source rasters",
    )
    parser.add_argument(
        "--skip-source-hash",
        action="store_true",
        help="skip the normal checksum verification pass (development only)",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="regenerate records instead of reusing verified build state",
    )
    return parser.parse_args()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def parse_lods(text: str) -> tuple[int, ...]:
    try:
        lods = tuple(sorted(set(int(item) for item in text.split(","))))
    except ValueError as error:
        raise ValueError("--lods must contain comma-separated integers") from error
    if not lods or any(lod not in range(len(LODS)) for lod in lods):
        raise ValueError("--lods must select one or more of 0,1,2")
    return lods


def distance_to_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    px, py = point
    ax, ay = start
    bx, by = end
    dx, dy = bx - ax, by - ay
    denominator = dx * dx + dy * dy
    if denominator == 0.0:
        return math.hypot(px - ax, py - ay)
    position = min(1.0, max(0.0, ((px - ax) * dx + (py - ay) * dy) / denominator))
    return math.hypot(px - (ax + position * dx), py - (ay + position * dy))


def selected_tiles(grid: WorldGrid, selection: str) -> tuple[tuple[int, int], ...]:
    if selection == "koak-proof":
        # Nine square chunks on each axis include the complete 28L runway and
        # enough approach/airport context for the first streaming fixture.
        return tuple((x, y) for y in range(142, 151) for x in range(89, 98))
    if selection == "full":
        return tuple(
            (x, y) for y in range(grid.rows) for x in range(grid.columns)
        )
    if selection != "corridor":
        raise ValueError(f"unknown terrain selection: {selection}")
    route = (
        (KOAK_START["threshold_easting_m"], KOAK_START["threshold_northing_m"]),
        CAMPANILE_UTM,
        MOUNT_DIABLO_UTM,
    )
    half_width_m = 1_536.0
    selected: list[tuple[int, int]] = []
    for y in range(grid.rows):
        for x in range(grid.columns):
            west, south, east, north = grid.tile_bounds(x, y)
            center = ((west + east) / 2.0, (south + north) / 2.0)
            distance = min(
                distance_to_segment(center, start, end)
                for start, end in zip(route, route[1:])
            )
            # Admit cells touched by the corridor rather than only centers
            # strictly inside it.
            if distance <= half_width_m + CHUNK_WIDTH_M / math.sqrt(2.0):
                selected.append((x, y))
    return tuple(selected)


def record_path(grid: WorldGrid, lod: int, tile_x: int, tile_y: int) -> Path:
    tile_id = grid.tile_id(tile_x, tile_y)
    return Path("TRN") / f"L{lod}" / f"{tile_id >> 8:02X}" / f"{tile_id & 0xFF:02X}.AGN"


def topology_budget(grid: WorldGrid, tiles: Iterable[tuple[int, int]], lods: Iterable[int]) -> dict:
    rows = []
    totals = Counter()
    for lod in lods:
        counts = Counter()
        data_sizes: list[int] = []
        for tile_x, tile_y in tiles:
            topology = triangular_topology(grid, tile_x, tile_y, lod)
            surface_vertices = len(topology.points)
            boundary_vertices = len(
                {index for edge in topology.boundary_edges for index in edge[:2]}
            )
            surface_triangles = len(topology.faces)
            skirt_triangles = len(topology.boundary_edges) * 2
            vertices = surface_vertices + boundary_vertices
            triangles = surface_triangles + skirt_triangles
            indices = triangles * 3
            data_bytes = 6 * vertices + 4 * indices + 4 * 16
            container_bytes = data_bytes + 100 + (-data_bytes % 4)
            data_sizes.append(data_bytes)
            counts.update(
                records=1,
                surface_vertices=surface_vertices,
                vertices=vertices,
                surface_triangles=surface_triangles,
                skirt_triangles=skirt_triangles,
                triangles=triangles,
                data_bytes=data_bytes,
                # Fixed RIFF/AGNB structure plus DATA's four-byte padding.
                container_bytes=container_bytes,
            )
        row = {
            "lod": lod,
            **counts,
            "data_bytes_min": min(data_sizes),
            "data_bytes_max": max(data_sizes),
            "data_bytes_mean": sum(data_sizes) / len(data_sizes),
        }
        rows.append(row)
        totals.update(counts)
    return {"lods": rows, "totals": dict(totals)}


class CoordinateTransformer:
    """One persistent PROJ process; avoids a process launch per terrain tile."""

    def __init__(self) -> None:
        self._process = subprocess.Popen(
            ["cs2cs", "-f", "%.9f", "EPSG:32610", "EPSG:5070"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def transform(
        self, points: Iterable[tuple[float, float]]
    ) -> tuple[tuple[float, float], ...]:
        points = tuple(points)
        assert self._process.stdin is not None
        assert self._process.stdout is not None
        for east, north in points:
            self._process.stdin.write(f"{east:.9f} {north:.9f}\n")
        self._process.stdin.flush()
        result = []
        for _ in points:
            line = self._process.stdout.readline()
            if not line:
                raise RuntimeError("cs2cs ended before returning every coordinate")
            fields = line.split()
            if len(fields) < 2 or fields[0] == "*" or fields[1] == "*":
                raise ValueError(f"cs2cs rejected terrain coordinate: {line.strip()}")
            result.append((float(fields[0]), float(fields[1])))
        return tuple(result)

    def close(self) -> None:
        if self._process.stdin is not None:
            self._process.stdin.close()
        stderr = self._process.stderr.read() if self._process.stderr is not None else ""
        return_code = self._process.wait()
        if return_code or stderr.strip():
            raise RuntimeError(
                f"cs2cs exited {return_code}: {stderr.strip() or 'no diagnostic'}"
            )

    def __enter__(self) -> CoordinateTransformer:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if exc_type is None:
            self.close()
        else:
            self._process.terminate()
            self._process.wait()


def verify_sources(manifest: dict) -> None:
    for dataset in manifest["datasets"]:
        for tile in dataset["tiles"]:
            path = ROOT / tile["local_path"]
            actual_size = path.stat().st_size
            if actual_size != tile["byte_size"]:
                raise ValueError(
                    f"source size changed for {path}: {actual_size}, expected {tile['byte_size']}"
                )
            actual_hash = sha256_file(path)
            if actual_hash != tile["sha256"]:
                raise ValueError(f"source SHA-256 changed for {path}")


def build_signature(manifest_bytes: bytes, selection: str, lods: tuple[int, ...]) -> str:
    digest = hashlib.sha256()
    digest.update(manifest_bytes)
    for path in (
        Path(__file__),
        ROOT / "src/pingo_terrain/regional_raster.py",
        ROOT / "src/pingo_terrain/regional_terrain.py",
        ROOT / "src/pingo_terrain/p3dm.py",
        ROOT / "src/pingo_terrain/materials.py",
    ):
        digest.update(path.read_bytes())
    digest.update(
        json.dumps(
            {"selection": selection, "lods": lods}, sort_keys=True
        ).encode("ascii")
    )
    return digest.hexdigest()


def tile_record(
    grid: WorldGrid,
    built: BuiltTerrainTile,
    relative_path: Path,
    container: bytes,
    *,
    dem_edge_padded: bool,
    nlcd_edge_padded: bool,
    nlcd_fallback_faces: int,
    nlcd_nodata_touched_faces: int,
) -> dict:
    tile = built.tile
    data = make_data(tile)
    tile_id = grid.tile_id(tile.meta.tile_x, tile.meta.tile_y)
    return {
        "tile_id": tile_id,
        "tile_x": tile.meta.tile_x,
        "tile_y": tile.meta.tile_y,
        "lod": tile.meta.lod,
        "path": relative_path.as_posix(),
        "bytes": len(container),
        "sha256": sha256_bytes(container),
        "data_bytes": len(data),
        "data_sha256": sha256_bytes(data),
        "vertices": len(tile.positions),
        "surface_vertices": built.surface_vertex_count,
        "triangles": len(tile.position_indices) // 3,
        "surface_triangles": built.surface_triangle_count,
        "skirt_triangles": built.skirt_triangle_count,
        "surface_minimum_elevation_m": round(
            built.surface_minimum_elevation_m, 6
        ),
        "surface_maximum_elevation_m": round(
            built.surface_maximum_elevation_m, 6
        ),
        "mesh_minimum_elevation_m": round(built.mesh_minimum_elevation_m, 6),
        "clamped_skirt_vertices": built.clamped_skirt_vertices,
        "maximum_elevation_dm": tile.meta.maximum_elevation_dm,
        "material_histogram": {
            str(material): count for material, count in built.material_histogram
        },
        "edge_padding": {
            "dem": dem_edge_padded,
            "nlcd": nlcd_edge_padded,
            "any": dem_edge_padded or nlcd_edge_padded,
        },
        "nlcd_fallback_faces": nlcd_fallback_faces,
        "nlcd_nodata_touched_faces": nlcd_nodata_touched_faces,
    }


def load_reusable_record(
    output: Path,
    state_path: Path,
    relative_path: Path,
    signature: str,
    *,
    tile_x: int,
    tile_y: int,
    lod: int,
) -> dict | None:
    if not state_path.exists():
        return None
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("build_signature") != signature:
        return None
    record = state.get("record")
    if not isinstance(record, dict) or record.get("path") != relative_path.as_posix():
        return None
    destination = output / relative_path
    if not destination.exists():
        return None
    container = destination.read_bytes()
    if sha256_bytes(container) != record.get("sha256"):
        return None
    parsed = parse_container(container)
    if (
        parsed.meta.tile_x,
        parsed.meta.tile_y,
        parsed.meta.lod,
    ) != (tile_x, tile_y, lod):
        return None
    return record


def build_one(
    grid: WorldGrid,
    dem: RasterMosaic,
    nlcd: RasterMosaic,
    transformer: CoordinateTransformer,
    tile_x: int,
    tile_y: int,
    lod: int,
) -> tuple[BuiltTerrainTile, bool, bool, int, int]:
    topology = triangular_topology(grid, tile_x, tile_y, lod)
    elevations: list[float] = []
    dem_edge_padded = False
    for east, north in topology.points:
        sample = dem.sample_bilinear(east, north)
        if sample.value is None:
            raise ValueError(f"DEM nodata at terrain vertex {east},{north}")
        elevations.append(float(sample.value))
        dem_edge_padded |= sample.edge_padded

    projected = transformer.transform(topology.points)
    materials: list[int] = []
    nlcd_edge_padded = False
    nlcd_fallback_faces = 0
    nlcd_nodata_touched_faces = 0
    for face in topology.faces:
        triangle = tuple(projected[index] for index in face)
        west = min(point[0] for point in triangle)
        south = min(point[1] for point in triangle)
        east = max(point[0] for point in triangle)
        north = max(point[1] for point in triangle)
        if west < nlcd.west or east > nlcd.east or south < nlcd.south or north > nlcd.north:
            nlcd_edge_padded = True

        centroid_witness = {"edge": False, "nodata": False}

        def centroid_lookup(x: float, y: float) -> int | None:
            sample = nlcd.sample_nearest(x, y, clamp=True)
            centroid_witness["edge"] |= sample.edge_padded
            centroid_witness["nodata"] |= sample.nodata
            return None if sample.value is None else int(sample.value)

        category, saw_nodata = predominant_category(
            triangle,
            nlcd.cells_in_bbox(west, south, east, north),
            centroid_lookup=centroid_lookup,
        )
        nlcd_edge_padded |= centroid_witness["edge"]
        average_elevation = sum(elevations[index] for index in face) / 3.0
        if category not in NLCD_TO_MATERIAL:
            nlcd_fallback_faces += 1
            material = WATER_MATERIAL if average_elevation <= 3.0 else UNKNOWN_LAND_MATERIAL
        else:
            material = NLCD_TO_MATERIAL[category]
        if saw_nodata or centroid_witness["nodata"]:
            nlcd_nodata_touched_faces += 1
        materials.append(material)
    built = build_terrain_tile(
        grid,
        tile_x,
        tile_y,
        lod,
        elevations_m=elevations,
        surface_materials=materials,
    )
    return (
        built,
        dem_edge_padded,
        nlcd_edge_padded,
        nlcd_fallback_faces,
        nlcd_nodata_touched_faces,
    )


def start_metadata(grid: WorldGrid, airport_index: dict | None) -> dict:
    source = KOAK_START
    source_reference = "embedded FAA/PROJ build witness"
    if airport_index is not None:
        canonical = airport_index["canonical_start"]
        absolute = canonical["surface_position_absolute_utm_m"]
        easting, northing, elevation = map(float, absolute)
        source = {
            "airport_icao": canonical["airport_icao"],
            "runway_end_id": canonical["runway_end_id"],
            "surface_elevation_m": elevation,
            "initial_clearance_m": canonical["initial_clearance_m"],
            "heading_true_deg": canonical["heading_true_deg_from_threshold_centerline"],
            "heading_grid_deg": canonical["heading_grid_deg_from_projected_centerline"],
        }
        source_reference = "AIRPORTS.json canonical_start"
    else:
        easting = float(KOAK_START["threshold_easting_m"])
        northing = float(KOAK_START["threshold_northing_m"])
    tile_x = math.floor((easting - grid.origin_east_m) / grid.chunk_width_m)
    tile_y = math.floor((northing - grid.origin_north_m) / grid.chunk_width_m)
    west, south, east, north = grid.tile_bounds(tile_x, tile_y)
    center_east = (west + east) / 2.0
    center_north = (south + north) / 2.0
    fine_north_m = northing - center_north
    fine_east_m = easting - center_east
    return {
        **source,
        "source": source_reference,
        "threshold_easting_m": easting,
        "threshold_northing_m": northing,
        "coarse_tile_x": tile_x,
        "coarse_tile_y": tile_y,
        "coarse_tile_id": grid.tile_id(tile_x, tile_y),
        "coarse_center_easting_m": center_east,
        "coarse_center_northing_m": center_north,
        "fine_north_m": fine_north_m,
        "fine_east_m": fine_east_m,
        "pingo_x_count": round(fine_north_m * 16.0),
        "pingo_z_count": round(-fine_east_m * 16.0),
        "surface_pingo_y_count": round(float(source["surface_elevation_m"]) * 16.0),
        "initial_pingo_y_count": round(
            (float(source["surface_elevation_m"]) + float(source["initial_clearance_m"]))
            * 16.0
        ),
    }


def main() -> int:
    arguments = parse_arguments()
    lods = parse_lods(arguments.lods)
    grid = WorldGrid()
    tiles = selected_tiles(grid, arguments.selection)
    budget = topology_budget(grid, tiles, lods)
    if arguments.budget_only:
        print(json.dumps({"selection": arguments.selection, "tiles": len(tiles), **budget}, indent=2, sort_keys=True))
        return 0

    manifest_bytes = SOURCE_MANIFEST.read_bytes()
    source_manifest = json.loads(manifest_bytes)
    if not arguments.skip_source_hash:
        verify_sources(source_manifest)
    datasets = {item["id"]: item for item in source_manifest["datasets"]}
    dem = RasterMosaic(ROOT, datasets[DEM_DATASET_ID])
    nlcd = RasterMosaic(ROOT, datasets[NLCD_DATASET_ID])
    signature = build_signature(manifest_bytes, arguments.selection, lods)
    output = arguments.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    airport_index_path = output / "AIRPORTS.json"
    airport_index = (
        json.loads(airport_index_path.read_text(encoding="utf-8"))
        if airport_index_path.exists()
        else None
    )
    state_root = output / ".state"
    records: list[dict] = []
    record_total = len(tiles) * len(lods)
    completed = 0
    with CoordinateTransformer() as transformer:
        for lod in lods:
            for tile_x, tile_y in tiles:
                tile_id = grid.tile_id(tile_x, tile_y)
                relative = record_path(grid, lod, tile_x, tile_y)
                state_path = state_root / f"L{lod}-{tile_id:05d}.json"
                record = None
                if not arguments.no_resume:
                    record = load_reusable_record(
                        output,
                        state_path,
                        relative,
                        signature,
                        tile_x=tile_x,
                        tile_y=tile_y,
                        lod=lod,
                    )
                if record is None:
                    (
                        built,
                        dem_padded,
                        nlcd_padded,
                        fallback_faces,
                        nodata_touched_faces,
                    ) = build_one(grid, dem, nlcd, transformer, tile_x, tile_y, lod)
                    container = make_container(built.tile)
                    if parse_container(container) != built.tile:
                        raise ValueError(f"P3DM round trip changed L{lod} tile {tile_id}")
                    atomic_write(output / relative, container)
                    record = tile_record(
                        grid,
                        built,
                        relative,
                        container,
                        dem_edge_padded=dem_padded,
                        nlcd_edge_padded=nlcd_padded,
                        nlcd_fallback_faces=fallback_faces,
                        nlcd_nodata_touched_faces=nodata_touched_faces,
                    )
                    atomic_write(
                        state_path,
                        (json.dumps({"build_signature": signature, "record": record}, sort_keys=True) + "\n").encode("utf-8"),
                    )
                records.append(record)
                completed += 1
                if completed == record_total or completed % 25 == 0:
                    print(f"REGIONAL_TERRAIN_PROGRESS records={completed}/{record_total}", flush=True)

    source_dem = datasets[DEM_DATASET_ID]
    source_west, source_south, source_east, source_north = source_dem["bbox"]
    world = {
        "schema": "pingo-terrain-regional-corpus-v1",
        "selection": arguments.selection,
        "build_signature": signature,
        "source_manifest": str(SOURCE_MANIFEST.relative_to(ROOT)),
        "source_manifest_sha256": sha256_bytes(manifest_bytes),
        "source_crs": f"EPSG:{REGIONAL_EPSG}",
        "source_vertical_datum": source_dem["vertical_datum"],
        "world_grid": {
            "origin_easting_m": grid.origin_east_m,
            "origin_northing_m": grid.origin_north_m,
            "chunk_width_m": grid.chunk_width_m,
            "columns": grid.columns,
            "rows": grid.rows,
            "east_m": grid.east_m,
            "north_m": grid.north_m,
            "tile_x_direction": "east",
            "tile_y_direction": "north",
            "tile_id_equation": "tile_y * 201 + tile_x",
            "object_pingo_x_count_equation": "(tile_y - coarse_tile_y) * 8192",
            "object_pingo_z_count_equation": "-(tile_x - coarse_tile_x) * 8192",
        },
        "normalization": {
            "pingo_x": "UTM northing",
            "pingo_y": "source elevation minus regional vertical origin",
            "pingo_z": "negative UTM easting",
            "metres_per_pingo_unit": 8,
            "counts_per_metre": 16,
            "vertical_origin_m": REGIONAL_VERTICAL_ORIGIN_M,
            "model_half_extent_m": MODEL_HALF_EXTENT_M,
            "object_scale_q8_8": MODEL_HALF_EXTENT_M * 32,
            "object_translation_y_count": round(REGIONAL_VERTICAL_ORIGIN_M * 16),
            "floating_origin_axes": ["pingo_x_north", "pingo_z_west"],
            "absolute_axis": "pingo_y_up; never changed by horizontal rebasing",
        },
        "source_coverage_padding": {
            "policy": "clamp to nearest source pixel and flag every affected record",
            "west_m": source_west - grid.origin_east_m,
            "south_m": source_south - grid.origin_north_m,
            "east_m": grid.east_m - source_east,
            "north_m": grid.north_m - source_north,
        },
        "topology": {
            "kind": "global hex-offset triangular lattice clipped to exact 512 m tile planes",
            "same_lod_seam_policy": "canonical 1 micrometre shared edge intersections reconstruct identical projected samples",
            "mixed_lod_seam_policy": "nonoverlapping exact tile planes plus 64 m downward boundary skirts; adjacent LOD delta limited to one",
            "skirt_depth_m": SKIRT_DEPTH_M,
            "skirt_floor_elevation_m": SKIRT_FLOOR_ELEVATION_M,
            "lods": [asdict(LODS[lod]) for lod in lods],
        },
        "material_vocabulary": [asdict(item) for item in BERKELEY_TERRAIN_MATERIALS],
        "fallback_material_policy": {
            "nlcd_nodata_at_or_below_3m": WATER_MATERIAL,
            "other_missing_or_unknown": UNKNOWN_LAND_MATERIAL,
        },
        "path_equation": "TRN/L{lod}/{tile_id >> 8:02X}/{tile_id & 255:02X}.AGN",
        "stage_buffer_id": 0x7400,
        "airport_index": (
            {
                "path": "AIRPORTS.json",
                "sha256": sha256_file(airport_index_path),
                "contract": "airport records own component paths and canonical KOAK start",
            }
            if airport_index is not None
            else None
        ),
        "canonical_start": start_metadata(grid, airport_index),
        "budget": budget,
        "records": sorted(records, key=lambda item: (item["lod"], item["tile_id"])),
        "statistics": {
            "selected_tiles": len(tiles),
            "records": len(records),
            "container_bytes": sum(item["bytes"] for item in records),
            "data_bytes": sum(item["data_bytes"] for item in records),
            "vertices": sum(item["vertices"] for item in records),
            "triangles": sum(item["triangles"] for item in records),
            "edge_padded_records": sum(item["edge_padding"]["any"] for item in records),
            "maximum_elevation_dm_min": min(item["maximum_elevation_dm"] for item in records),
            "maximum_elevation_dm_max": max(item["maximum_elevation_dm"] for item in records),
        },
    }
    atomic_write(
        output / "WORLD.json",
        (json.dumps(world, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    print(
        "REGIONAL_TERRAIN",
        f"selection={arguments.selection}",
        f"tiles={len(tiles)}",
        f"records={len(records)}",
        f"bytes={world['statistics']['container_bytes']}",
        f"output={output}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
