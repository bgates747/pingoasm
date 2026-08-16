"""Elevation- and shape-driven greedy refinement over the CDT.

Garland-Heckbert Algorithm III adapted to a CDT, with two insertion
criteria per triangle:

1. Elevation: the worst-approximated land sample (vertical L-infinity
   error against the plane through the triangle's vertices). Water-class
   samples are excluded: water presents flat, so bathymetry must not
   attract triangles.
2. Shape: any triangle (land or water) whose longest edge exceeds the
   max-edge cap is subdivided at its interior sample nearest the centroid.
   This kills the boundary-vertex fans that constrained polygons with
   empty interiors otherwise produce -- long thin triangles are hostile to
   a fixed-point scanline rasterizer -- and bounds triangle extent for the
   future hex-cutting stage.

All candidate positions are working-grid cell centers (odd doubled
coordinates), strictly interior to their triangle, so insertion never
touches a constrained edge. Elevation repairs take priority; shape repairs
run when no elevation error remains above tolerance.
"""

from __future__ import annotations

import heapq
import math

import numpy as np

from cdt import CDT
from rasters import CLASS_WATER

_BAND_CELLS = 4_000_000
_METRES_PER_UNIT = 15.0  # one doubled working-grid unit


class Refiner:
    def __init__(
        self,
        tri: CDT,
        dem: np.ndarray,
        classes: np.ndarray,
        vertex_z,
        max_edge_m: float = 0.0,
    ) -> None:
        self.tri = tri
        self.dem = dem
        self.land = classes != CLASS_WATER
        self.vertex_z = vertex_z
        self.rows, self.cols = dem.shape
        self.error_heap: list[tuple[float, int, int]] = []
        self.shape_heap: list[tuple[int, int, int]] = []
        self.error_cand: dict[int, tuple[float, int, int]] = {}
        self.shape_cand: dict[int, tuple[int, int, int]] = {}
        self.seq = 0
        self.max_edge_units2 = (
            (max_edge_m / _METRES_PER_UNIT) ** 2 if max_edge_m > 0 else 0.0
        )
        self.uncappable = 0

    def scan_triangle(self, tid: int) -> None:
        """Cache the elevation and shape candidates of one alive triangle."""

        v0, v1, v2 = (self.tri.pts[v] for v in self.tri.tri_v[tid])
        z0, z1, z2 = (self.vertex_z[v] for v in self.tri.tri_v[tid])
        edge_pairs = ((v0, v1), (v1, v2), (v2, v0))
        edge_len2 = [
            (b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2 for a, b in edge_pairs
        ]
        longest2 = max(edge_len2)
        want_shape = (
            self.max_edge_units2 > 0 and longest2 > self.max_edge_units2
        )
        shape_point = None
        if want_shape:
            # Split the longest edge at its exactly-collinear lattice
            # point nearest the midpoint. Constrained edges stay
            # geometrically identical (the point is on the segment), so
            # boundaries never move. Corner-corner and center-center
            # edges always admit such a point (both deltas even).
            ea, eb = edge_pairs[edge_len2.index(longest2)]
            dx = eb[0] - ea[0]
            dy = eb[1] - ea[1]
            g = math.gcd(abs(dx), abs(dy))
            if g >= 2:
                k = g // 2
                shape_point = (
                    ea[0] + (dx // g) * k,
                    ea[1] + (dy // g) * k,
                )
        min_x = min(v0[0], v1[0], v2[0])
        max_x = max(v0[0], v1[0], v2[0])
        min_y = min(v0[1], v1[1], v2[1])
        max_y = max(v0[1], v1[1], v2[1])
        c0 = max((min_x + (1 - min_x % 2)) // 2, 0)
        c1 = min((max_x - (1 - max_x % 2)) // 2, self.cols - 1)
        r0 = max((min_y + (1 - min_y % 2)) // 2, 0)
        r1 = min((max_y - (1 - max_y % 2)) // 2, self.rows - 1)
        if c1 < c0 or r1 < r0:
            self._push_shape(tid, want_shape, longest2, shape_point, None)
            return
        area2 = float(
            (v1[0] - v0[0]) * (v2[1] - v0[1])
            - (v1[1] - v0[1]) * (v2[0] - v0[0])
        )
        centroid_x = (v0[0] + v1[0] + v2[0]) / 3.0
        centroid_y = (v0[1] + v1[1] + v2[1]) / 3.0
        band_rows = max(1, _BAND_CELLS // max(1, c1 - c0 + 1))
        best_err = -1.0
        best_err_at = None
        best_dist = None
        best_dist_at = None
        px = 2 * np.arange(c0, c1 + 1, dtype=np.int64) + 1
        for band0 in range(r0, r1 + 1, band_rows):
            band1 = min(band0 + band_rows - 1, r1)
            py = 2 * np.arange(band0, band1 + 1, dtype=np.int64) + 1
            gx = px[None, :]
            gy = py[:, None]
            e0 = (v2[0] - v1[0]) * (gy - v1[1]) - (v2[1] - v1[1]) * (
                gx - v1[0]
            )
            e1 = (v0[0] - v2[0]) * (gy - v2[1]) - (v0[1] - v2[1]) * (
                gx - v2[0]
            )
            e2 = (v1[0] - v0[0]) * (gy - v0[1]) - (v1[1] - v0[1]) * (
                gx - v0[0]
            )
            inside = (e0 > 0) & (e1 > 0) & (e2 > 0)
            if not inside.any():
                continue
            if want_shape and shape_point is None:
                dist = (gx - centroid_x) ** 2 + (gy - centroid_y) ** 2
                dist = np.where(inside, dist, np.inf)
                flat = int(dist.argmin())
                value = float(dist.flat[flat])
                if best_dist is None or value < best_dist:
                    r_local, c_local = divmod(flat, dist.shape[1])
                    best_dist = value
                    best_dist_at = (
                        int(2 * (c0 + c_local) + 1),
                        int(2 * (band0 + r_local) + 1),
                    )
            landward = inside & self.land[band0 : band1 + 1, c0 : c1 + 1]
            if not landward.any():
                continue
            dem = self.dem[band0 : band1 + 1, c0 : c1 + 1]
            plane = (
                e0.astype(np.float64) * z0
                + e1.astype(np.float64) * z1
                + e2.astype(np.float64) * z2
            ) / area2
            err = np.abs(dem - plane)
            err = np.where(landward & np.isfinite(dem), err, -1.0)
            flat = int(err.argmax())
            value = float(err.flat[flat])
            if value > best_err:
                r_local, c_local = divmod(flat, err.shape[1])
                best_err = value
                best_err_at = (
                    int(2 * (c0 + c_local) + 1),
                    int(2 * (band0 + r_local) + 1),
                )
        if best_err_at is not None and best_err >= 0:
            self.error_cand[tid] = (best_err, *best_err_at)
            heapq.heappush(self.error_heap, (-best_err, self.seq, tid))
            self.seq += 1
        self._push_shape(tid, want_shape, longest2, shape_point, best_dist_at)

    def _push_shape(
        self, tid, want_shape, longest2, shape_point, interior_point
    ) -> None:
        if not want_shape:
            return
        target = shape_point if shape_point is not None else interior_point
        if target is None:
            self.uncappable += 1
            return
        self.shape_cand[tid] = (longest2, *target)
        heapq.heappush(self.shape_heap, (-longest2, self.seq, tid))
        self.seq += 1

    def drain_dirty(self) -> None:
        dirty = self.tri.dirty
        self.tri.dirty = []
        for tid in dirty:
            if self.tri.alive[tid]:
                self.scan_triangle(tid)

    def _pop_error(self, tolerance_m: float):
        while self.error_heap:
            neg_err, _, tid = heapq.heappop(self.error_heap)
            if not self.tri.alive[tid]:
                continue
            entry = self.error_cand.get(tid)
            if entry is None or entry[0] != -neg_err:
                continue
            if entry[0] <= tolerance_m:
                heapq.heappush(self.error_heap, (neg_err, self.seq, tid))
                self.seq += 1
                return None
            return (*entry, tid)
        return None

    def _pop_shape(self):
        while self.shape_heap:
            neg_edge2, _, tid = heapq.heappop(self.shape_heap)
            if not self.tri.alive[tid]:
                continue
            entry = self.shape_cand.get(tid)
            if entry is None or entry[0] != -neg_edge2:
                continue
            return (*entry, tid)
        return None

    def run(
        self,
        tolerance_m: float,
        max_points: int,
        log=None,
    ) -> dict:
        self.drain_dirty()
        inserted_error = 0
        inserted_shape = 0
        worst_seen = 0.0
        while inserted_error + inserted_shape < max_points:
            entry = self._pop_error(tolerance_m)
            if entry is not None:
                worst_seen = entry[0]
                point = (entry[1], entry[2])
                hint = entry[3]
                inserted_error += 1
            else:
                shape_entry = self._pop_shape()
                if shape_entry is None:
                    break
                point = (shape_entry[1], shape_entry[2])
                hint = shape_entry[3]
                inserted_shape += 1
            self.tri.insert_point(point, hint=hint)
            self.vertex_z.extend_to(len(self.tri.pts))
            self.drain_dirty()
            total = inserted_error + inserted_shape
            if log is not None and total % 5000 == 0:
                log(total, worst_seen)
        remaining = 0.0
        for neg_err, _, tid in self.error_heap:
            if self.tri.alive[tid]:
                entry = self.error_cand.get(tid)
                if entry is not None and entry[0] == -neg_err:
                    remaining = max(remaining, entry[0])
        return {
            "inserted": inserted_error + inserted_shape,
            "inserted_error": inserted_error,
            "inserted_shape": inserted_shape,
            "worst_remaining_m": remaining,
            "uncappable": self.uncappable,
        }


class VertexZ:
    """Vertex elevations: clamped bilinear DEM samples in doubled coords."""

    def __init__(self, tri: CDT, dem: np.ndarray) -> None:
        self.tri = tri
        self.dem = dem
        self.rows, self.cols = dem.shape
        self.values: list[float] = []
        self.extend_to(len(tri.pts))

    def __getitem__(self, vid: int) -> float:
        return self.values[vid]

    def extend_to(self, count: int) -> None:
        while len(self.values) < count:
            vid = len(self.values)
            x, y = self.tri.pts[vid]
            self.values.append(self._sample(x, y))

    def _sample(self, x: int, y: int) -> float:
        gx = x / 2.0 - 0.5
        gy = y / 2.0 - 0.5
        c0 = int(np.floor(gx))
        r0 = int(np.floor(gy))
        fx = gx - c0
        fy = gy - r0
        c0 = min(max(c0, 0), self.cols - 1)
        r0 = min(max(r0, 0), self.rows - 1)
        c1 = min(c0 + 1, self.cols - 1)
        r1 = min(r0 + 1, self.rows - 1)
        v00 = float(self.dem[r0, c0])
        v01 = float(self.dem[r0, c1])
        v10 = float(self.dem[r1, c0])
        v11 = float(self.dem[r1, c1])
        samples = [v00, v01, v10, v11]
        finite = [s for s in samples if np.isfinite(s)]
        if not finite:
            return 0.0
        fill = finite[0]
        v00, v01, v10, v11 = (s if np.isfinite(s) else fill for s in samples)
        z = (
            v00 * (1 - fx) * (1 - fy)
            + v01 * fx * (1 - fy)
            + v10 * (1 - fx) * fy
            + v11 * fx * fy
        )
        # Below-sea-level cells are bathymetry or coastal noise; the visual
        # sea surface sits at zero.
        return max(z, 0.0)
