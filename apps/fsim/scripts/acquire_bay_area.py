#!/usr/bin/env python3
"""Acquire and checksum the regional Bay Area 3DEP/NLCD source corpus."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ElementTree


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pingo_terrain.geotiff import (  # noqa: E402
    sha256_file,
    summarize_raster,
    validate_geotiff,
)
from pingo_terrain.usgs_acquisition import (  # noqa: E402
    COVERAGE_REFERENCES_WGS84,
    DEM_GRID,
    NLCD_COVERAGE,
    NLCD_GRID,
    NLCD_TIME,
    NLCD_WCS,
    REGION_ID,
    REQUESTED_WGS84_BOUNDS,
    RETRIEVAL_DATE,
    THREE_DEP_SERVICE,
    USER_AGENT,
    RasterTile,
    acquisition_plan,
    download_tile,
    read_source_query_summary,
    source_query_url,
)


DEFAULT_DOWNLOAD_ROOT = PROJECT_ROOT / "data" / "downloads" / REGION_ID
DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "manifests" / f"{REGION_ID}-{RETRIEVAL_DATE}.json"
NLCD_CODES = {11, 12, 21, 22, 23, 24, 31, 41, 42, 43, 51, 52, 71, 72, 73, 74, 81, 82, 90, 95}


def _metadata_requests() -> tuple[tuple[str, str, Callable[[Path], object]], ...]:
    capabilities_url = NLCD_WCS + "?" + urlencode(
        {"service": "WCS", "version": "1.0.0", "request": "GetCapabilities"}
    )
    description_url = NLCD_WCS + "?" + urlencode(
        {
            "service": "WCS",
            "version": "1.0.0",
            "request": "DescribeCoverage",
            "coverage": NLCD_COVERAGE,
        }
    )

    def service_json(path: Path) -> object:
        payload = json.loads(path.read_text(encoding="utf-8"))
        expected = {
            "pixelType": "F32",
            "maxImageWidth": 8000,
            "maxImageHeight": 8000,
        }
        wrong = [f"{key}={payload.get(key)!r}" for key, value in expected.items() if payload.get(key) != value]
        if wrong:
            raise ValueError("unexpected 3DEP service metadata: " + ", ".join(wrong))
        return {
            "service_version": payload.get("currentVersion"),
            "pixel_type": payload["pixelType"],
            "max_image_width": payload["maxImageWidth"],
            "max_image_height": payload["maxImageHeight"],
            "max_download_image_count": payload.get("maxDownloadImageCount"),
            "description": payload.get("description"),
            "copyright_text": payload.get("copyrightText"),
        }

    def source_json(path: Path) -> object:
        summary = read_source_query_summary(path)
        if summary["exceeded_transfer_limit"]:
            raise ValueError("3DEP source query exceeded its transfer limit")
        if summary["vertical_datums"] != ["North American Vertical Datum of 1988 (NAVD 88)"]:
            raise ValueError(f"unexpected 3DEP vertical datums: {summary['vertical_datums']}")
        return summary

    def capabilities_xml(path: Path) -> object:
        root = ElementTree.fromstring(path.read_bytes())
        text = " ".join(root.itertext())
        element_names = {element.tag.rsplit("}", 1)[-1] for element in root.iter()}
        if NLCD_COVERAGE not in text or "GetCoverage" not in element_names:
            raise ValueError("NLCD WCS capabilities omit expected coverage/operation")
        # Output formats are advertised by DescribeCoverage in WCS 1.0.0, not
        # by this service's GetCapabilities document.
        return {"root": root.tag, "coverage": NLCD_COVERAGE, "operation": "GetCoverage"}

    def description_xml(path: Path) -> object:
        root = ElementTree.fromstring(path.read_bytes())
        text = " ".join(root.itertext())
        required = (NLCD_COVERAGE, "EPSG:5070", "2025-01-01T00:00:00.000Z", "30.0 0.0", "0.0 -30.0")
        if any(item not in text for item in required):
            raise ValueError("NLCD DescribeCoverage omits expected CRS/time/grid facts")
        return {
            "root": root.tag,
            "coverage": NLCD_COVERAGE,
            "crs": "EPSG:5070",
            "available_through": "2025-01-01T00:00:00.000Z",
            "native_pixel_size_metres": 30,
            "native_boundary_origin": [-2415585.0, 164805.0],
            "default_interpolation": "nearest neighbor",
        }

    return (
        ("3dep-service.json", THREE_DEP_SERVICE + "?f=pjson", service_json),
        ("3dep-source-records.json", source_query_url(), source_json),
        ("nlcd-wcs-capabilities.xml", capabilities_url, capabilities_xml),
        ("nlcd-wcs-description.xml", description_url, description_xml),
    )


def _download_metadata(
    name: str,
    url: str,
    validator: Callable[[Path], object],
    directory: Path,
    retries: int,
) -> tuple[dict[str, object], int]:
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / name
    partial = destination.with_suffix(destination.suffix + ".part")
    if destination.is_file():
        try:
            details = validator(destination)
            return {
                "local_path": str(destination.relative_to(PROJECT_ROOT)),
                "request_url": url,
                "byte_size": destination.stat().st_size,
                "sha256": sha256_file(destination),
                "validated_details": details,
            }, 0
        except (OSError, ValueError, ElementTree.ParseError):
            pass
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            if partial.exists():
                partial.unlink()
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=180.0) as response, partial.open("wb") as output:
                if response.status != 200:
                    raise OSError(f"HTTP status {response.status}")
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            details = validator(partial)
            partial.replace(destination)
            return {
                "local_path": str(destination.relative_to(PROJECT_ROOT)),
                "request_url": url,
                "byte_size": destination.stat().st_size,
                "sha256": sha256_file(destination),
                "validated_details": details,
            }, attempt
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, ElementTree.ParseError) as error:
            last_error = error
            if partial.exists():
                partial.unlink()
            if attempt >= retries:
                break
            delay = min(2**attempt, 16)
            print(f"retry metadata/{name} {attempt + 1}/{retries}: {error}; waiting {delay}s", flush=True)
            time.sleep(delay)
    raise RuntimeError(f"failed metadata/{name} after {retries + 1} attempts") from last_error


def _inspect_tile(tile: RasterTile, path: Path, retries: int) -> dict[str, object]:
    metadata = validate_geotiff(path, tile.expectation, tolerance=0.02)
    summary = summarize_raster(metadata)
    if summary.valid_count == 0:
        raise ValueError(f"{tile.grid.dataset_id}/{tile.id} contains no valid samples")
    if tile.grid is DEM_GRID:
        if summary.minimum is None or summary.maximum is None or summary.minimum < -500 or summary.maximum > 5000:
            raise ValueError(f"implausible Bay Area elevation range {summary.minimum}..{summary.maximum}")
    else:
        unexpected = set(summary.observed_values or ()) - NLCD_CODES
        if unexpected:
            raise ValueError(f"unexpected NLCD class codes {sorted(unexpected)}")
    return {
        "id": tile.id,
        "local_path": str(path.relative_to(PROJECT_ROOT)),
        "request_url": tile.request_url,
        "bbox": list(tile.bounds.tuple),
        "width": tile.width,
        "height": tile.height,
        "accepted_geotiff_metadata": {
            "byte_order": "little" if metadata.byte_order == "<" else "big",
            "epsg": metadata.epsg,
            "bbox": list(metadata.bbox),
            "pixel_size_metres": [metadata.pixel_size_x, metadata.pixel_size_y],
            "bits_per_sample": metadata.bits_per_sample,
            "sample_format": metadata.sample_format,
            "nodata": metadata.nodata,
            "storage": metadata.storage,
            "block_size_pixels": [metadata.block_width, metadata.block_height],
        },
        "byte_size": path.stat().st_size,
        "sha256": sha256_file(path),
        "download_retries": retries,
        "valid_cells": summary.valid_count,
        "nodata_cells": summary.nodata_count,
        "minimum": summary.minimum,
        "maximum": summary.maximum,
        **({"observed_classes": list(summary.observed_values or ())} if tile.grid is NLCD_GRID else {}),
    }


def _dataset_manifest(grid: object, tiles: list[dict[str, object]]) -> dict[str, object]:
    total_valid = sum(int(tile["valid_cells"]) for tile in tiles)
    total_nodata = sum(int(tile["nodata_cells"]) for tile in tiles)
    minima = [tile["minimum"] for tile in tiles if tile["minimum"] is not None]
    maxima = [tile["maximum"] for tile in tiles if tile["maximum"] is not None]
    base: dict[str, object] = {
        "id": grid.dataset_id,
        "crs": f"EPSG:{grid.epsg}",
        "bbox": list(grid.bounds.tuple),
        "width": grid.width,
        "height": grid.height,
        "pixel_size_metres": [grid.pixel_size, grid.pixel_size],
        "tile_edge_limit_pixels": 2048,
        "tile_count": len(tiles),
        "format": (
            "GeoTIFF, uncompressed, single-band float32"
            if grid is DEM_GRID
            else "GeoTIFF, uncompressed, single-band uint8 categorical"
        ),
        "nodata": grid.nodata,
        "total_byte_size": sum(int(tile["byte_size"]) for tile in tiles),
        "total_cells": grid.width * grid.height,
        "valid_cells": total_valid,
        "nodata_cells": total_nodata,
        "minimum": min(minima),
        "maximum": max(maxima),
        "download_retries": sum(int(tile["download_retries"]) for tile in tiles),
        "tiles": tiles,
    }
    if grid is DEM_GRID:
        base.update(
            {
                "role": "bare-earth elevation",
                "provider": "U.S. Geological Survey, The National Map, 3D Elevation Program",
                "product": "3DEP Bare Earth DEM Dynamic service resampled to a 10 metre working grid",
                "service": "ArcGIS ImageServer exportImage",
                "service_url": THREE_DEP_SERVICE,
                "interpolation": "bilinear",
                "vertical_datum": "North American Vertical Datum of 1988 (NAVD 88), as reported by all intersecting non-overview source records",
                "license_status": "USGS public-domain data; no use restrictions stated by 3DEP",
            }
        )
    else:
        observed = sorted({value for tile in tiles for value in tile.get("observed_classes", [])})
        base.update(
            {
                "role": "categorical land cover",
                "provider": "U.S. Geological Survey EROS / Multi-Resolution Land Characteristics Consortium",
                "product": "Annual NLCD CONUS Collection 1.2 Land Cover, 2025",
                "product_url": "https://www.usgs.gov/centers/eros/science/usgs-eros-archive-land-cover-annual-nlcd-collection-1-land-cover",
                "service": "GeoServer WCS 1.0.0",
                "service_url": NLCD_WCS,
                "coverage": NLCD_COVERAGE,
                "time": NLCD_TIME,
                "grid_alignment": "Bounds are exact 30 metre multiples from native boundary origin (-2415585, 164805).",
                "interpolation": "nearest neighbor (categorical)",
                "observed_classes": observed,
                "license_status": "USGS public-domain data",
            }
        )
    return base


def _airport_source_note() -> dict[str, object]:
    return {
        "scope": "Cross-reference only; airport data is not ingested as terrain and no airport mesh is generated by this acquisition.",
        "authoritative_manifest": "data/manifests/faa-nasr-airports-2026-07-09.json",
        "airport_priority": ["KSFO", "KOAK", "KHWD", "KSQL", "KCCR"],
        "canonical_start": "KOAK runway end 28L; use the physical/displaced-threshold and surveyed-source semantics pinned by the authoritative airport manifest.",
        "rendering_policy": "Airport hard surfaces and markings are a separate streamable container/layer in ordinary solid-flat mode 1, initially self illuminated; they never use terrain dithering mode 2.",
    }


def _manifest(
    dataset_entries: list[dict[str, object]],
    evidence: list[dict[str, object]],
    failed_attempts: list[str],
) -> dict[str, object]:
    return {
        "manifest_version": 2,
        "region_id": REGION_ID,
        "retrieved": RETRIEVAL_DATE,
        "description": "Regional Bay Area terrain sources from Pacific water through Mount Diablo and Suisun Bay through Morgan Hill.",
        "requested_wgs84_bbox": {"crs": "EPSG:4326", **asdict(REQUESTED_WGS84_BOUNDS)},
        "coverage_reference_points_wgs84": [
            {"name": name, "longitude": point[0], "latitude": point[1]}
            for name, point in COVERAGE_REFERENCES_WGS84.items()
        ],
        "projected_envelope_derivation": {
            "tool": "PROJ cs2cs 9.1.1, dense WGS84 perimeter sampling",
            "raw_utm10_envelope": [521889.60, 4100448.28, 624488.31, 4228932.08],
            "raw_conus_albers_envelope": [-2325720.25, 1858305.62, -2193922.75, 2009670.40],
            "policy": "Expand outward to complete native working-grid cells; never crop the requested WGS84 rectangle.",
        },
        "tile_policy": {
            "maximum_width_pixels": 2048,
            "maximum_height_pixels": 2048,
            "ordering": "north-to-south rows, west-to-east columns",
            "reason": "Bound each request and retry independently, remain far below the 3DEP service 8000x8000 limit, and avoid one fragile regional export.",
        },
        "runtime_note": "This manifest pins acquisition inputs only. It contains no mosaics, normalized derivatives, terrain meshes, or airport meshes.",
        "service_evidence": evidence,
        "datasets": dataset_entries,
        "acquisition_outcome": {
            "accepted_tile_count": sum(int(item["tile_count"]) for item in dataset_entries),
            "total_byte_size": sum(int(item["total_byte_size"]) for item in dataset_entries),
            "download_retries": sum(int(item["download_retries"]) for item in dataset_entries),
            "failed_attempts": failed_attempts,
        },
        "future_airport_layer_source": _airport_source_note(),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-root", type=Path, default=DEFAULT_DOWNLOAD_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--retries", type=int, default=5)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan-only", action="store_true")
    mode.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.workers < 1 or args.workers > 8:
        raise SystemExit("--workers must be between 1 and 8")
    if args.retries < 0 or args.retries > 10:
        raise SystemExit("--retries must be between 0 and 10")
    pinned_manifest: dict[str, object] | None = None
    if args.manifest.is_file():
        pinned_manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    elif args.validate_only:
        raise SystemExit(f"checksum manifest is missing: {args.manifest}")
    tiles = acquisition_plan()
    print(
        f"region {REQUESTED_WGS84_BOUNDS.tuple}: "
        f"{sum(tile.grid is DEM_GRID for tile in tiles)} DEM + "
        f"{sum(tile.grid is NLCD_GRID for tile in tiles)} NLCD tiles",
        flush=True,
    )
    print(
        f"DEM {DEM_GRID.width}x{DEM_GRID.height} EPSG:{DEM_GRID.epsg}; "
        f"NLCD {NLCD_GRID.width}x{NLCD_GRID.height} EPSG:{NLCD_GRID.epsg}",
        flush=True,
    )
    if args.plan_only:
        for tile in tiles:
            print(f"{tile.grid.dataset_id}/{tile.id} {tile.width}x{tile.height} {tile.bounds.tuple}")
        return 0

    failures: list[str] = []
    retry_counts: dict[tuple[str, str], int] = {}
    if not args.validate_only:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(
                    download_tile,
                    tile,
                    args.download_root,
                    retries=args.retries,
                    progress=lambda message: print(message, flush=True),
                ): tile
                for tile in tiles
            }
            for completed, future in enumerate(as_completed(futures), 1):
                tile = futures[future]
                try:
                    path, retries = future.result()
                    retry_counts[(tile.grid.dataset_id, tile.id)] = retries
                    print(
                        f"[{completed:02d}/{len(tiles)}] accepted "
                        f"{tile.grid.dataset_id}/{tile.id} {path.stat().st_size} bytes",
                        flush=True,
                    )
                except Exception as error:  # report every failed tile after peer jobs settle
                    failures.append(f"{tile.grid.dataset_id}/{tile.id}: {error}")
                    print(f"FAILED {failures[-1]}", file=sys.stderr, flush=True)
        if failures:
            print("No manifest written because one or more tiles failed.", file=sys.stderr)
            return 1

    evidence: list[dict[str, object]] = []
    metadata_directory = args.download_root / "service-evidence"
    for name, url, validator in _metadata_requests():
        destination = metadata_directory / name
        if args.validate_only:
            if not destination.is_file():
                raise SystemExit(f"missing service evidence: {destination}")
            details = validator(destination)
            retries = 0
            item = {
                "local_path": str(destination.relative_to(PROJECT_ROOT)),
                "request_url": url,
                "byte_size": destination.stat().st_size,
                "sha256": sha256_file(destination),
                "validated_details": details,
            }
        else:
            item, retries = _download_metadata(name, url, validator, metadata_directory, args.retries)
        item["id"] = name.rsplit(".", 1)[0]
        item["download_retries"] = retries
        evidence.append(item)
        print(f"accepted service-evidence/{name} {item['byte_size']} bytes", flush=True)

    per_dataset: dict[str, list[dict[str, object]]] = {DEM_GRID.dataset_id: [], NLCD_GRID.dataset_id: []}
    for index, tile in enumerate(tiles, 1):
        path = args.download_root / tile.relative_path
        if not path.is_file():
            raise SystemExit(f"missing tile: {path}")
        record = _inspect_tile(tile, path, retry_counts.get((tile.grid.dataset_id, tile.id), 0))
        per_dataset[tile.grid.dataset_id].append(record)
        print(f"[{index:02d}/{len(tiles)}] summarized {tile.grid.dataset_id}/{tile.id}", flush=True)

    dataset_entries = [
        _dataset_manifest(DEM_GRID, per_dataset[DEM_GRID.dataset_id]),
        _dataset_manifest(NLCD_GRID, per_dataset[NLCD_GRID.dataset_id]),
    ]
    manifest = _manifest(dataset_entries, evidence, failures)
    if pinned_manifest is not None and manifest != pinned_manifest:
        raise SystemExit(
            "accepted files or acquisition plan differ from the existing checksum "
            f"manifest: {args.manifest}; refusing to repin automatically"
        )
    if args.validate_only:
        print(f"validated pinned manifest {args.manifest}", flush=True)
        return 0
    if pinned_manifest is None:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        f"accepted {args.manifest}: {manifest['acquisition_outcome']['accepted_tile_count']} tiles, "
        f"{manifest['acquisition_outcome']['total_byte_size']} bytes",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
