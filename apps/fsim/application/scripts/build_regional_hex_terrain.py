#!/usr/bin/env python3
"""Build the deterministic Bay Area N=5 hexagonal P3DM terrain corpus."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

import build_regional_terrain as rectangular


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "build/p3dm/bay-area-hex-full-l0"
CAMPANILE_CELL = (90, 121)
CAMPANILE_UTM = (565_276.625, 4_191_883.9375)

sys.path.insert(0, str(ROOT / "src"))

from pingo_terrain.hex_terrain import (  # noqa: E402
    COUNTS_PER_METRE,
    HEX_AREA_M2,
    HEX_BASIS_Q_EAST_M,
    HEX_BASIS_Q_NORTH_M,
    HEX_BASIS_R_EAST_M,
    HEX_BASIS_R_NORTH_M,
    HEX_CELL_COUNT,
    HEX_MODEL_HALF_EXTENT_M,
    HEX_OBJECT_SCALE_Q8_8,
    HEX_ORIGIN_EAST_M,
    HEX_ORIGIN_NORTH_M,
    HEX_Q_MAX,
    HEX_SIDE_M,
    HEX_SIDE_STEPS,
    HEX_TERRAIN_Y_COUNT,
    BuiltHexTerrainCell,
    HexCell,
    build_hex_terrain_cell,
    disk_offsets,
    hex_topology,
    iter_cells,
)
from pingo_terrain.materials import BERKELEY_TERRAIN_MATERIALS  # noqa: E402
from pingo_terrain.p3dm import make_container, make_data, parse_container  # noqa: E402
from pingo_terrain.regional_raster import RasterMosaic  # noqa: E402
from pingo_terrain.regional_terrain import (  # noqa: E402
    REGIONAL_EPSG,
    REGIONAL_ORIGIN_EAST_M,
    REGIONAL_ORIGIN_NORTH_M,
    REGIONAL_VERTICAL_ORIGIN_M,
    SKIRT_DEPTH_M,
    predominant_category,
)


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--selection",
        choices=("campanile-r5", "full"),
        default="full",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--budget-only", action="store_true")
    parser.add_argument("--skip-source-hash", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def selected_cells(selection: str) -> tuple[HexCell, ...]:
    if selection == "full":
        return tuple(iter_cells())
    if selection != "campanile-r5":
        raise ValueError(f"unknown hex selection: {selection}")
    q0, r0 = CAMPANILE_CELL
    return tuple(HexCell(q0 + dq, r0 + dr) for dq, dr in disk_offsets(5))


def record_path(cell: HexCell) -> Path:
    cell_id = cell.cell_id
    return Path("TRH/L0") / f"{cell_id >> 8:02X}" / f"{cell_id & 0xFF:02X}.AGN"


def corpus_budget(cell_count: int) -> dict[str, int | float]:
    topology = hex_topology(*CAMPANILE_CELL)
    surface_vertices = len(topology.keys)
    boundary_vertices = len(
        {index for edge in topology.boundary_edges for index in edge[:2]}
    )
    surface_triangles = len(topology.faces)
    skirt_triangles = len(topology.boundary_edges) * 2
    vertices = surface_vertices + boundary_vertices
    triangles = surface_triangles + skirt_triangles
    data_bytes = 6 * vertices + 4 * triangles * 3 + 4 * 16
    container_bytes = data_bytes + 100 + (-data_bytes % 4)
    return {
        "cells": cell_count,
        "surface_vertices_per_cell": surface_vertices,
        "vertices_per_cell": vertices,
        "surface_triangles_per_cell": surface_triangles,
        "skirt_triangles_per_cell": skirt_triangles,
        "triangles_per_cell": triangles,
        "data_bytes_per_cell": data_bytes,
        "container_bytes_per_cell": container_bytes,
        "vertices": vertices * cell_count,
        "triangles": triangles * cell_count,
        "data_bytes": data_bytes * cell_count,
        "container_bytes": container_bytes * cell_count,
    }


def build_signature(manifest_bytes: bytes, selection: str) -> str:
    digest = hashlib.sha256()
    digest.update(manifest_bytes)
    for path in (
        Path(__file__),
        ROOT / "scripts/build_regional_terrain.py",
        ROOT / "src/pingo_terrain/hex_terrain.py",
        ROOT / "src/pingo_terrain/regional_raster.py",
        ROOT / "src/pingo_terrain/regional_terrain.py",
        ROOT / "src/pingo_terrain/p3dm.py",
        ROOT / "src/pingo_terrain/materials.py",
    ):
        digest.update(path.read_bytes())
    digest.update(selection.encode("ascii"))
    return digest.hexdigest()


def build_one(
    cell: HexCell,
    dem: RasterMosaic,
    nlcd: RasterMosaic,
    transformer: rectangular.CoordinateTransformer,
) -> tuple[BuiltHexTerrainCell, bool, bool, int, int]:
    topology = hex_topology(cell.q, cell.r)
    elevations: list[float] = []
    dem_edge_padded = False
    for east, north in topology.points:
        sample = dem.sample_bilinear(east, north)
        if sample.value is None:
            raise ValueError(f"DEM nodata at hex vertex {east},{north}")
        elevations.append(float(sample.value))
        dem_edge_padded |= sample.edge_padded

    projected = transformer.transform(topology.points)
    materials: list[int] = []
    nlcd_edge_padded = False
    fallback_faces = 0
    nodata_touched_faces = 0
    for face in topology.faces:
        triangle = tuple(projected[index] for index in face)
        west = min(point[0] for point in triangle)
        south = min(point[1] for point in triangle)
        east = max(point[0] for point in triangle)
        north = max(point[1] for point in triangle)
        if (
            west < nlcd.west
            or east > nlcd.east
            or south < nlcd.south
            or north > nlcd.north
        ):
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
        average_elevation = sum(elevations[index] for index in face) / 3
        if category not in rectangular.NLCD_TO_MATERIAL:
            fallback_faces += 1
            material = (
                rectangular.WATER_MATERIAL
                if average_elevation <= 3.0
                else rectangular.UNKNOWN_LAND_MATERIAL
            )
        else:
            material = rectangular.NLCD_TO_MATERIAL[category]
        if saw_nodata or centroid_witness["nodata"]:
            nodata_touched_faces += 1
        materials.append(material)

    return (
        build_hex_terrain_cell(
            cell.q,
            cell.r,
            elevations_m=elevations,
            surface_materials=materials,
        ),
        dem_edge_padded,
        nlcd_edge_padded,
        fallback_faces,
        nodata_touched_faces,
    )


def record_for(
    cell: HexCell,
    built: BuiltHexTerrainCell,
    relative: Path,
    container: bytes,
    *,
    dem_edge_padded: bool,
    nlcd_edge_padded: bool,
    fallback_faces: int,
    nodata_touched_faces: int,
) -> dict:
    data = make_data(built.tile)
    return {
        "cell_id": cell.cell_id,
        "q": cell.q,
        "r": cell.r,
        "offset_row": cell.offset_row,
        "lod": 0,
        "path": relative.as_posix(),
        "bytes": len(container),
        "sha256": rectangular.sha256_bytes(container),
        "data_bytes": len(data),
        "data_sha256": rectangular.sha256_bytes(data),
        "vertices": len(built.tile.positions),
        "surface_vertices": built.surface_vertex_count,
        "triangles": len(built.tile.position_indices) // 3,
        "surface_triangles": built.surface_triangle_count,
        "skirt_triangles": built.skirt_triangle_count,
        "surface_minimum_elevation_m": round(
            built.surface_minimum_elevation_m, 6
        ),
        "surface_maximum_elevation_m": round(
            built.surface_maximum_elevation_m, 6
        ),
        "mesh_minimum_elevation_m": round(built.mesh_minimum_elevation_m, 6),
        "maximum_elevation_dm": built.tile.meta.maximum_elevation_dm,
        "material_histogram": {
            str(material): count for material, count in built.material_histogram
        },
        "edge_padding": {
            "dem": dem_edge_padded,
            "nlcd": nlcd_edge_padded,
            "any": dem_edge_padded or nlcd_edge_padded,
        },
        "nlcd_fallback_faces": fallback_faces,
        "nlcd_nodata_touched_faces": nodata_touched_faces,
    }


def load_reusable(
    output: Path,
    state_path: Path,
    relative: Path,
    signature: str,
    cell: HexCell,
) -> dict | None:
    if not state_path.is_file():
        return None
    state = json.loads(state_path.read_text(encoding="utf-8"))
    record = state.get("record")
    destination = output / relative
    if state.get("build_signature") != signature or not isinstance(record, dict):
        return None
    if record.get("path") != relative.as_posix() or not destination.is_file():
        return None
    container = destination.read_bytes()
    if rectangular.sha256_bytes(container) != record.get("sha256"):
        return None
    parsed = parse_container(container)
    if (parsed.meta.tile_x, parsed.meta.tile_y, parsed.meta.lod) != (
        cell.q,
        cell.r,
        0,
    ):
        return None
    return record


def canonical_start() -> dict:
    cell = HexCell(*CAMPANILE_CELL)
    center_east, center_north = cell.center_m
    east_count = round((CAMPANILE_UTM[0] - center_east) * COUNTS_PER_METRE)
    north_count = round((CAMPANILE_UTM[1] - center_north) * COUNTS_PER_METRE)
    return {
        "name": "Sather Tower / the Campanile",
        "source": "accepted rectangular-survey projected/count witness",
        "easting_m": CAMPANILE_UTM[0],
        "northing_m": CAMPANILE_UTM[1],
        "q": cell.q,
        "r": cell.r,
        "cell_id": cell.cell_id,
        "cell_center_easting_m": center_east,
        "cell_center_northing_m": center_north,
        "fine_east_count": east_count,
        "fine_north_count": north_count,
        "pingo_x_count": north_count,
        "pingo_z_count": -east_count,
        "pingo_y_count": 3496,
        "rotation": [0, 0, 0],
    }


def main() -> int:
    args = arguments()
    cells = selected_cells(args.selection)
    budget = corpus_budget(len(cells))
    if args.budget_only:
        print(json.dumps({"selection": args.selection, "budget": budget}, indent=2))
        return 0

    manifest_bytes = rectangular.SOURCE_MANIFEST.read_bytes()
    source_manifest = json.loads(manifest_bytes)
    if not args.skip_source_hash:
        rectangular.verify_sources(source_manifest)
    datasets = {item["id"]: item for item in source_manifest["datasets"]}
    dem = RasterMosaic(ROOT, datasets[rectangular.DEM_DATASET_ID])
    nlcd = RasterMosaic(ROOT, datasets[rectangular.NLCD_DATASET_ID])
    signature = build_signature(manifest_bytes, args.selection)
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    state_root = output / ".state"
    records: list[dict] = []

    with rectangular.CoordinateTransformer() as transformer:
        for completed, cell in enumerate(cells, 1):
            relative = record_path(cell)
            state_path = state_root / f"L0-{cell.cell_id:05d}.json"
            record = None
            if not args.no_resume:
                record = load_reusable(output, state_path, relative, signature, cell)
            if record is None:
                built, dem_padded, nlcd_padded, fallback, nodata = build_one(
                    cell, dem, nlcd, transformer
                )
                container = make_container(built.tile)
                if parse_container(container) != built.tile:
                    raise ValueError(f"P3DM round trip changed hex cell {cell}")
                rectangular.atomic_write(output / relative, container)
                record = record_for(
                    cell,
                    built,
                    relative,
                    container,
                    dem_edge_padded=dem_padded,
                    nlcd_edge_padded=nlcd_padded,
                    fallback_faces=fallback,
                    nodata_touched_faces=nodata,
                )
                rectangular.atomic_write(
                    state_path,
                    (json.dumps(
                        {"build_signature": signature, "record": record},
                        sort_keys=True,
                    ) + "\n").encode("utf-8"),
                )
            records.append(record)
            if completed == len(cells) or completed % 100 == 0:
                print(
                    f"REGIONAL_HEX_PROGRESS records={completed}/{len(cells)}",
                    flush=True,
                )

    world = {
        "schema": "pingo-terrain-regional-hex-corpus-v1",
        "selection": args.selection,
        "build_signature": signature,
        "source_manifest": str(rectangular.SOURCE_MANIFEST.relative_to(ROOT)),
        "source_manifest_sha256": rectangular.sha256_bytes(manifest_bytes),
        "source_crs": f"EPSG:{REGIONAL_EPSG}",
        "source_vertical_datum": datasets[rectangular.DEM_DATASET_ID]["vertical_datum"],
        "coverage": {
            "policy": "centres in staggered columns covering the aligned rectangular control",
            "q_min": 0,
            "q_max": HEX_Q_MAX,
            "cells": HEX_CELL_COUNT,
            "selection_cells": len(cells),
        },
        "topology": {
            "kind": "flat-top hexagonal streaming cells on one exact triangular lattice",
            "side_m": HEX_SIDE_M,
            "side_steps": HEX_SIDE_STEPS,
            "area_m2": HEX_AREA_M2,
            "square_512m_area_ratio": HEX_AREA_M2 / 512**2,
            "origin_center_m": [HEX_ORIGIN_EAST_M, HEX_ORIGIN_NORTH_M],
            "basis_q_m": [HEX_BASIS_Q_EAST_M, HEX_BASIS_Q_NORTH_M],
            "basis_r_m": [HEX_BASIS_R_EAST_M, HEX_BASIS_R_NORTH_M],
            "boundary_policy": "six straight sides; each runtime side is five collinear lattice edges",
            "same_lod_seam_policy": "shared projected 1/16-metre keys and exact Pingo transform reconstruction",
            "skirt_depth_m": SKIRT_DEPTH_M,
            "ring_cell_counts_0_through_5": [1, 7, 19, 37, 61, 91],
        },
        "normalization": {
            "pingo_x": "UTM northing",
            "pingo_y": "source elevation minus regional vertical origin",
            "pingo_z": "negative UTM easting",
            "metres_per_pingo_unit": 8,
            "counts_per_metre": COUNTS_PER_METRE,
            "vertical_origin_m": REGIONAL_VERTICAL_ORIGIN_M,
            "model_half_extent_m": HEX_MODEL_HALF_EXTENT_M,
            "object_scale_q8_8": HEX_OBJECT_SCALE_Q8_8,
            "object_translation_y_count": HEX_TERRAIN_Y_COUNT,
        },
        "path_equation": "TRH/L0/{cell_id >> 8:02X}/{cell_id & 255:02X}.AGN",
        "cell_id_equation": "floor(q/2)*469 + (235 if q odd else 0) + r + floor(q/2)",
        "stage_buffer_id": 0x7400,
        "material_vocabulary": [asdict(item) for item in BERKELEY_TERRAIN_MATERIALS],
        "canonical_start": canonical_start(),
        "review_artifact": {
            "required": True,
            "path": "build/visualization/bay-area-hex-overview.blend",
            "role": "full-coverage topology/material/elevation review LOD",
        },
        "budget": budget,
        "records": sorted(records, key=lambda item: item["cell_id"]),
        "statistics": {
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
    rectangular.atomic_write(
        output / "WORLD.json",
        (json.dumps(world, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    print(
        "REGIONAL_HEX_TERRAIN",
        f"selection={args.selection}",
        f"cells={len(cells)}",
        f"bytes={world['statistics']['container_bytes']}",
        f"output={output}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
