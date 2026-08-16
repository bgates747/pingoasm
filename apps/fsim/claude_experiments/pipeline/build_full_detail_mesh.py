"""Build the feature-aware full-detail Bay Area mesh and export it as OBJ.

Pipeline (stage 1 of the terrain-appearance effort): three-class raster ->
shared boundary polylines -> global Visvalingam simplification -> integer
constrained Delaunay triangulation -> elevation-driven greedy refinement ->
per-region material assignment -> OBJ/MTL with the three Agon solid colors.

Deliberately runs on system python3 + numpy; see pipeline/README.md.

Usage:
    python3 build_full_detail_mesh.py [--crop C0,R0,C1,R1] [--tol M]
        [--max-points N] [--vw-area CELLS2] [--min-ring-area CELLS2]
        [--majority ITERATIONS] [--out NAME]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import boundaries
import rasters
from cdt import CDT
from refine import Refiner, VertexZ

BUILD_ROOT = Path(__file__).resolve().parents[1] / "build" / "full-detail"

# Three-class presentation colors from the application's authored Agon
# solid materials (materials.py): water palette 20, developed palette 7,
# green palette 21.
MATERIAL_NAMES = ("green", "developed", "water")
MATERIAL_RGB = ((0, 170, 85), (170, 170, 170), (0, 85, 255))


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def load_grids(cache_dir: Path, majority_iterations: int) -> dict:
    dem_path = cache_dir / "dem.npy"
    class_path = cache_dir / f"classes-m{majority_iterations}.npy"
    meta_path = cache_dir / "grid.json"
    if dem_path.exists() and class_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        meta["dem"] = np.load(dem_path)
        meta["classes"] = np.load(class_path)
        return meta
    log("building working grids from GeoTIFF mosaics...")
    grids = rasters.build_working_grids()
    log(
        f"grids ready: {grids['dem'].shape[1]}x{grids['dem'].shape[0]} "
        f"cells at {grids['step']:.0f} m"
    )
    grids["classes"] = rasters.majority_filter(
        grids["classes"], majority_iterations
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.save(dem_path, grids["dem"])
    np.save(class_path, grids["classes"])
    meta = {
        key: grids[key] for key in ("west", "south", "east", "north", "step")
    }
    meta_path.write_text(json.dumps(meta))
    grid_meta = dict(meta)
    grid_meta["dem"] = grids["dem"]
    grid_meta["classes"] = grids["classes"]
    return grid_meta


def frame_chains(width: int, height: int, chain_list) -> list[np.ndarray]:
    """Domain-frame constraint chains, split at boundary-chain endpoints."""

    on_side: dict[str, set[tuple[int, int]]] = {
        "top": set(),
        "bottom": set(),
        "left": set(),
        "right": set(),
    }
    for chain in chain_list:
        pts = chain.points()
        for point in (pts[0], pts[-1]):
            x, y = int(point[0]), int(point[1])
            if y == 0:
                on_side["top"].add((x, y))
            if y == height:
                on_side["bottom"].add((x, y))
            if x == 0:
                on_side["left"].add((x, y))
            if x == width:
                on_side["right"].add((x, y))
    sides = {
        "top": ((0, 0), (width, 0), 0),
        "right": ((width, 0), (width, height), 1),
        "bottom": ((width, height), (0, height), 0),
        "left": ((0, height), (0, 0), 1),
    }
    out = []
    for name, (start, end, axis) in sides.items():
        points = {start, end} | on_side[name]
        reverse = (end[axis] - start[axis]) < 0
        ordered = sorted(points, key=lambda p: p[axis], reverse=reverse)
        out.append(np.asarray(ordered, dtype=np.int64))
    return out


def build_mesh(args: argparse.Namespace) -> None:
    cache_dir = BUILD_ROOT / "cache"
    grids = load_grids(cache_dir, args.majority)
    dem = grids["dem"]
    classes = grids["classes"]
    if args.crop:
        c0, r0, c1, r1 = (int(v) for v in args.crop.split(","))
        dem = dem[r0:r1, c0:c1].copy()
        classes = classes[r0:r1, c0:c1].copy()
        origin_west = grids["west"] + c0 * grids["step"]
        origin_north = grids["north"] - r0 * grids["step"]
    else:
        origin_west = grids["west"]
        origin_north = grids["north"]
    rows, cols = classes.shape
    step = grids["step"]
    log(f"working extent {cols}x{rows} cells ({cols*step/1000:.1f} x "
        f"{rows*step/1000:.1f} km)")

    log("extracting class boundaries...")
    edges = boundaries.extract_boundary_edges(classes)
    log(f"boundary lattice edges: {edges.shape[0]}")
    raw_chains = boundaries.build_chains(edges, cols + 1)
    log(f"chains: {len(raw_chains)}")
    area2_threshold = int(round(2 * args.vw_area))
    min_ring_area2 = int(round(2 * args.min_ring_area))
    chains = boundaries.simplify_chains(
        raw_chains, area2_threshold, min_ring_area2
    )
    if args.dp_eps > 0:
        for chain in chains:
            chain.straighten(args.dp_eps)
    total_kept = sum(c.kept.shape[0] for c in chains)
    total_orig = sum(c.orig.shape[0] for c in chains)
    log(
        f"simplified: {len(chains)} chains, {total_kept} of "
        f"{total_orig} points kept"
    )
    splits = boundaries.repair_crossings(chains)
    log(f"crossing repair splits: {splits}")

    log("building constrained triangulation...")
    tri = CDT(cols, rows)
    hint = 0

    def insert_chain(points: np.ndarray) -> list[int]:
        nonlocal hint
        ids = []
        for x, y in points:
            vid = tri.insert_point((2 * int(x), 2 * int(y)), hint)
            hint = tri.vert_tri[vid]
            ids.append(vid)
        return ids

    frames = frame_chains(cols, rows, chains)
    frame_ids = [insert_chain(chain) for chain in frames]
    chain_ids = [insert_chain(chain.points()) for chain in chains]
    log(f"constraint vertices inserted: {len(tri.pts)}")
    for ids in frame_ids + chain_ids:
        for a, b in zip(ids, ids[1:]):
            if a != b:
                tri.insert_segment(a, b)
    for chain, ids in zip(chains, chain_ids):
        if chain.closed and len(ids) > 2 and ids[-1] != ids[0]:
            tri.insert_segment(ids[-1], ids[0])
    log(
        f"constraints inserted: {len(tri.constrained)} edges, "
        f"{sum(tri.alive)} triangles"
    )

    log("refining against elevation and shape...")
    vertex_z = VertexZ(tri, dem)
    refiner = Refiner(
        tri, dem, classes, vertex_z, max_edge_m=args.max_edge
    )
    stats = refiner.run(
        args.tol,
        args.max_points,
        log=lambda n, err: log(
            f"  inserted {n} points, current worst {err:.1f} m"
        ),
    )
    log(
        f"refinement done: {stats['inserted_error']} error + "
        f"{stats['inserted_shape']} shape points, worst remaining "
        f"{stats['worst_remaining_m']:.1f} m, {stats['uncappable']} "
        f"uncappable, {sum(tri.alive)} triangles"
    )

    log("assigning region materials...")
    labels = tri.region_labels()
    region_votes: dict[int, np.ndarray] = {}
    for tid, label in labels.items():
        v0, v1, v2 = (tri.pts[v] for v in tri.tri_v[tid])
        cx = (v0[0] + v1[0] + v2[0]) / 6.0
        cy = (v0[1] + v1[1] + v2[1]) / 6.0
        col = min(max(int(cx), 0), cols - 1)
        row = min(max(int(cy), 0), rows - 1)
        area2 = abs(
            (v1[0] - v0[0]) * (v2[1] - v0[1])
            - (v1[1] - v0[1]) * (v2[0] - v0[0])
        )
        votes = region_votes.setdefault(label, np.zeros(3, dtype=np.int64))
        votes[classes[row, col]] += area2
    region_class = {
        label: int(votes.argmax()) for label, votes in region_votes.items()
    }
    counts = np.zeros(3, dtype=np.int64)
    for label in labels.values():
        counts[region_class[label]] += 1
    log(
        f"regions: {len(region_class)}; triangles by class "
        f"green={counts[0]} developed={counts[1]} water={counts[2]}"
    )

    out_dir = BUILD_ROOT
    out_dir.mkdir(parents=True, exist_ok=True)
    obj_path = out_dir / f"{args.out}.obj"
    mtl_path = out_dir / f"{args.out}.mtl"
    log(f"writing {obj_path} ...")
    export_obj(
        obj_path, mtl_path, tri, vertex_z, labels, region_class, step
    )
    receipt = {
        "generated_by": "claude_experiments/pipeline/build_full_detail_mesh.py",
        "origin_utm10": [origin_west, origin_north],
        "step_m": step,
        "crop": args.crop,
        "parameters": {
            "majority_iterations": args.majority,
            "vw_area_cells2": args.vw_area,
            "dp_eps_cells": args.dp_eps,
            "min_ring_area_cells2": args.min_ring_area,
            "tolerance_m": args.tol,
            "max_points": args.max_points,
            "max_edge_m": args.max_edge,
        },
        "vertices": len(tri.pts),
        "triangles": int(sum(tri.alive)),
        "boundary_edges": int(edges.shape[0]),
        "chains": len(chains),
        "refinement": stats,
        "triangles_by_class": {
            name: int(counts[i]) for i, name in enumerate(MATERIAL_NAMES)
        },
    }
    (out_dir / f"{args.out}.json").write_text(json.dumps(receipt, indent=2))
    log("done")


def export_obj(
    obj_path: Path,
    mtl_path: Path,
    tri: CDT,
    vertex_z,
    labels: dict[int, int],
    region_class: dict[int, int],
    step: float,
) -> None:
    """OBJ with Y-up so Blender's importer restores east/north/up axes."""

    half = step / 2.0
    with mtl_path.open("w") as mtl:
        for name, rgb in zip(MATERIAL_NAMES, MATERIAL_RGB):
            r, g, b = (component / 255.0 for component in rgb)
            mtl.write(
                f"newmtl {name}\nKd {r:.4f} {g:.4f} {b:.4f}\n"
                f"Ka 0 0 0\nKs 0 0 0\nd 1\nillum 1\n"
            )
    faces_by_class: list[list[tuple[int, int, int]]] = [[], [], []]
    for tid, label in labels.items():
        v0, v1, v2 = tri.tri_v[tid]
        # CDT ccw is clockwise in east/north space; swap for up normals.
        faces_by_class[region_class[label]].append((v0, v2, v1))
    with obj_path.open("w") as obj:
        obj.write(f"mtllib {mtl_path.name}\n")
        max_y = max(p[1] for p in tri.pts)
        for vid, (x, y) in enumerate(tri.pts):
            east = x * half
            north = (max_y - y) * half
            obj.write(f"v {east:.2f} {vertex_z[vid]:.2f} {-north:.2f}\n")
        for class_id, name in enumerate(MATERIAL_NAMES):
            faces = faces_by_class[class_id]
            if not faces:
                continue
            obj.write(f"usemtl {name}\n")
            for a, b, c in faces:
                obj.write(f"f {a + 1} {b + 1} {c + 1}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crop", default=None,
                        help="C0,R0,C1,R1 working-cell crop for debug runs")
    parser.add_argument("--tol", type=float, default=60.0,
                        help="vertical L-infinity tolerance in metres")
    parser.add_argument("--max-points", type=int, default=600_000)
    parser.add_argument("--max-edge", type=float, default=1200.0,
                        help="subdivide triangles with edges longer than "
                        "this many metres (0 disables)")
    parser.add_argument("--vw-area", type=float, default=3.0,
                        help="Visvalingam effective-area threshold, cells^2")
    parser.add_argument("--dp-eps", type=float, default=1.5,
                        help="post-VW Douglas-Peucker deviation floor in "
                        "cells (0 disables)")
    parser.add_argument("--min-ring-area", type=float, default=12.0,
                        help="drop closed rings smaller than this, cells^2")
    parser.add_argument("--majority", type=int, default=2,
                        help="3x3 majority-filter iterations")
    parser.add_argument("--out", default="bay-area-full-detail")
    build_mesh(parser.parse_args())


if __name__ == "__main__":
    main()
