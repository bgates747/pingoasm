"""Class-boundary polylines: extraction, Visvalingam simplification, repair.

Boundaries live on the working-grid corner lattice ((H+1) x (W+1) corners
for an H x W class grid). Chains run junction-to-junction (or to the domain
frame) and are simplified once, globally, before any triangulation, so every
downstream consumer sees one authoritative simplified boundary. All
geometry is integer; effective areas use doubled (cross-product) units.
"""

from __future__ import annotations

import heapq

import numpy as np


def _orient(ax, ay, bx, by, cx, cy):
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def extract_boundary_edges(classes: np.ndarray) -> np.ndarray:
    """Return (E, 2) corner-id pairs separating differing class cells."""

    rows, cols = classes.shape
    stride = cols + 1
    vertical = np.nonzero(classes[:, 1:] != classes[:, :-1])
    v_r = vertical[0].astype(np.int64)
    v_c = vertical[1].astype(np.int64) + 1
    v_a = v_r * stride + v_c
    v_b = (v_r + 1) * stride + v_c
    horizontal = np.nonzero(classes[1:, :] != classes[:-1, :])
    h_r = horizontal[0].astype(np.int64) + 1
    h_c = horizontal[1].astype(np.int64)
    h_a = h_r * stride + h_c
    h_b = h_r * stride + h_c + 1
    return np.stack(
        [np.concatenate([v_a, h_a]), np.concatenate([v_b, h_b])], axis=1
    )


def build_chains(
    edges: np.ndarray, corner_stride: int
) -> list[tuple[np.ndarray, bool]]:
    """Split the boundary edge graph into junction-to-junction chains.

    Returns (coords, closed) pairs where coords is an (n, 2) integer corner
    coordinate array (x=column, y=row). Closed rings are implicitly closed
    (first point not repeated).
    """

    ids = np.concatenate([edges[:, 0], edges[:, 1]])
    nbrs = np.concatenate([edges[:, 1], edges[:, 0]])
    order = np.argsort(ids, kind="stable")
    ids_sorted = ids[order]
    nbrs_sorted = nbrs[order]
    unique_ids, start_index = np.unique(ids_sorted, return_index=True)
    counts = np.diff(np.append(start_index, ids_sorted.size))
    indptr = {int(node): (int(s), int(c)) for node, s, c in zip(
        unique_ids, start_index, counts
    )}
    degree = {int(node): int(c) for node, c in zip(unique_ids, counts)}
    visited = np.zeros(nbrs_sorted.size, dtype=bool)

    def slot(node: int, neighbor: int) -> int:
        start, count = indptr[node]
        for i in range(start, start + count):
            if nbrs_sorted[i] == neighbor and not visited[i]:
                return i
        for i in range(start, start + count):
            if nbrs_sorted[i] == neighbor:
                return i
        raise KeyError((node, neighbor))

    def take(node: int, neighbor: int) -> None:
        visited[slot(node, neighbor)] = True
        visited[slot(neighbor, node)] = True

    def edge_used(node: int, neighbor: int) -> bool:
        start, count = indptr[node]
        free = 0
        for i in range(start, start + count):
            if nbrs_sorted[i] == neighbor and not visited[i]:
                free += 1
        return free == 0

    chains: list[tuple[list[int], bool]] = []
    junctions = [n for n in map(int, unique_ids) if degree[n] != 2]
    for node in junctions:
        start, count = indptr[node]
        for i in range(start, start + count):
            if visited[i]:
                continue
            neighbor = int(nbrs_sorted[i])
            chain = [node, neighbor]
            take(node, neighbor)
            prev, current = node, neighbor
            while degree[current] == 2:
                start_c, count_c = indptr[current]
                nxt = None
                for j in range(start_c, start_c + count_c):
                    candidate = int(nbrs_sorted[j])
                    if candidate != prev and not visited[j]:
                        nxt = candidate
                        break
                if nxt is None:
                    break
                take(current, nxt)
                chain.append(nxt)
                prev, current = current, nxt
            if chain[0] == chain[-1]:
                # Junction-anchored loop: store as a ring without the
                # duplicate closing point.
                chains.append((chain[:-1], True))
            else:
                chains.append((chain, False))
    # Remaining unvisited edges form closed rings of degree-2 corners.
    for e in range(edges.shape[0]):
        a, b = int(edges[e, 0]), int(edges[e, 1])
        if edge_used(a, b):
            continue
        chain = [a, b]
        take(a, b)
        prev, current = a, b
        while current != a:
            start_c, count_c = indptr[current]
            nxt = None
            for j in range(start_c, start_c + count_c):
                candidate = int(nbrs_sorted[j])
                if candidate != prev and not visited[j]:
                    nxt = candidate
                    break
            if nxt is None:
                break
            take(current, nxt)
            if nxt == a:
                prev, current = current, nxt
                break
            chain.append(nxt)
            prev, current = current, nxt
        chains.append((chain, True))

    out = []
    for chain, closed in chains:
        arr = np.asarray(chain, dtype=np.int64)
        coords = np.stack([arr % corner_stride, arr // corner_stride], axis=1)
        out.append((coords, closed))
    return out


def ring_area2(coords: np.ndarray) -> int:
    """Doubled signed shoelace area of an implicitly closed ring."""

    x = coords[:, 0]
    y = coords[:, 1]
    return int(
        np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y, dtype=np.int64)
    )


def simplify_visvalingam(
    coords: np.ndarray,
    area2_threshold: int,
    anchors: set[int],
    closed: bool,
) -> np.ndarray:
    """Repeatedly eliminate the least-effective-area point.

    Returns indices (into coords) of the surviving points, in order.
    Anchored indices are never eliminated. Effective areas are clamped
    monotonic so elimination order is stable.
    """

    n = coords.shape[0]
    if n <= 2:
        return np.arange(n, dtype=np.int64)
    prev = np.arange(-1, n - 1, dtype=np.int64)
    nxt = np.arange(1, n + 1, dtype=np.int64)
    if closed:
        prev[0] = n - 1
        nxt[n - 1] = 0
    alive = np.ones(n, dtype=bool)
    stamp = np.zeros(n, dtype=np.int64)

    def area2_at(i: int) -> int:
        p, q = int(prev[i]), int(nxt[i])
        if p < 0 or q >= n:
            return 1 << 62
        a = coords[p]
        b = coords[i]
        c = coords[q]
        return abs(int(
            (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        ))

    heap: list[tuple[int, int, int, int]] = []
    seq = 0
    for i in range(n):
        if i in anchors or (not closed and (i == 0 or i == n - 1)):
            continue
        heap.append((area2_at(i), seq, i, 0))
        seq += 1
    heapq.heapify(heap)
    floor_area = 0
    while heap:
        area2, _, i, s = heapq.heappop(heap)
        if not alive[i] or s != stamp[i]:
            continue
        effective = max(area2, floor_area)
        if effective >= area2_threshold:
            break
        floor_area = effective
        alive[i] = False
        p, q = int(prev[i]), int(nxt[i])
        nxt[p] = q
        prev[q] = p
        for j in (p, q):
            if not alive[j] or j in anchors:
                continue
            if not closed and (j == 0 or j == n - 1):
                continue
            stamp[j] += 1
            heapq.heappush(heap, (area2_at(j), seq, j, int(stamp[j])))
            seq += 1
    return np.nonzero(alive)[0].astype(np.int64)


class Chain:
    """One boundary chain with original points and surviving indices."""

    __slots__ = ("orig", "kept", "closed")

    def __init__(self, orig: np.ndarray, kept: np.ndarray, closed: bool):
        self.orig = orig
        self.kept = kept
        self.closed = closed

    def points(self) -> np.ndarray:
        return self.orig[self.kept]

    def segments(self):
        pts = self.points()
        count = pts.shape[0]
        limit = count if self.closed else count - 1
        for j in range(limit):
            yield j, pts[j], pts[(j + 1) % count]

    def split_segment(self, j: int) -> bool:
        """Re-add the middle original point inside surviving segment j."""

        count = self.kept.shape[0]
        lo = int(self.kept[j])
        hi = int(self.kept[(j + 1) % count])
        if self.closed and j == count - 1:
            hi += self.orig.shape[0]
        if hi - lo <= 1:
            return False
        mid = ((lo + hi) // 2) % self.orig.shape[0]
        insert_at = j + 1
        self.kept = np.insert(self.kept, insert_at, mid)
        return True

    def straighten(self, eps_units: float) -> None:
        """Drop kept points deviating less than eps from straight.

        A Douglas-Peucker pass over the surviving polyline. Visvalingam's
        area threshold permits metre-scale wiggles over kilometre
        baselines; the CDT then builds kilometre-long, metre-thin wedges
        along such runs, which are both rasterization poison and too thin
        to contain any interior refinement sample. Bounding deviation
        (not area) removes them at the source. Ring anchors (first point
        and its opposite) stay fixed.
        """

        pts = self.points()
        count = pts.shape[0]
        if count <= 2:
            return
        eps2_num = eps_units * eps_units
        keep = np.zeros(count, dtype=bool)

        def recurse(i0: int, i1: int) -> None:
            keep[i0] = True
            keep[i1 % count] = True
            stack = [(i0, i1)]
            while stack:
                a, b = stack.pop()
                if b - a < 2:
                    continue
                pa = pts[a % count]
                pb = pts[b % count]
                dx = int(pb[0] - pa[0])
                dy = int(pb[1] - pa[1])
                length2 = dx * dx + dy * dy
                worst = -1.0
                worst_at = -1
                for k in range(a + 1, b):
                    pk = pts[k % count]
                    cross = dx * int(pk[1] - pa[1]) - dy * int(
                        pk[0] - pa[0]
                    )
                    deviation2 = (
                        float(cross * cross) / length2 if length2 else 0.0
                    )
                    if deviation2 > worst:
                        worst = deviation2
                        worst_at = k
                if worst > eps2_num:
                    keep[worst_at % count] = True
                    stack.append((a, worst_at))
                    stack.append((worst_at, b))

        if self.closed:
            half = count // 2
            recurse(0, half)
            recurse(half, count)
        else:
            recurse(0, count - 1)
        self.kept = self.kept[np.nonzero(keep)[0]]


def simplify_chains(
    chains: list[tuple[np.ndarray, bool]],
    area2_threshold: int,
    min_ring_area2: int,
) -> list[Chain]:
    out: list[Chain] = []
    for coords, closed in chains:
        if closed:
            if abs(ring_area2(coords)) < min_ring_area2:
                continue
            order = np.lexsort((coords[:, 1], coords[:, 0]))
            anchor_low = int(order[0])
            anchor_high = int(order[-1])
            rolled = np.roll(coords, -anchor_low, axis=0)
            high = (anchor_high - anchor_low) % coords.shape[0]
            kept = simplify_visvalingam(
                rolled, area2_threshold, {0, high}, closed=True
            )
            out.append(Chain(rolled, kept, closed=True))
        else:
            kept = simplify_visvalingam(
                coords, area2_threshold, set(), closed=False
            )
            out.append(Chain(coords, kept, closed=False))
    return out


def repair_crossings(chains: list[Chain], bucket: int = 16) -> int:
    """Split simplified segments until no two constraints properly cross.

    Original staircase chains never cross, so re-adding original points
    converges. Returns the number of splits applied.
    """

    splits = 0
    for _ in range(64):
        segments = []
        for ci, chain in enumerate(chains):
            for j, a, b in chain.segments():
                segments.append((ci, j, a, b))
        grid: dict[tuple[int, int], list[int]] = {}
        for index, (_, _, a, b) in enumerate(segments):
            x0, x1 = sorted((int(a[0]), int(b[0])))
            y0, y1 = sorted((int(a[1]), int(b[1])))
            for gx in range(x0 // bucket, x1 // bucket + 1):
                for gy in range(y0 // bucket, y1 // bucket + 1):
                    grid.setdefault((gx, gy), []).append(index)
        conflicts = set()
        for members in grid.values():
            for i in range(len(members)):
                for k in range(i + 1, len(members)):
                    s, t = segments[members[i]], segments[members[k]]
                    if _proper_cross(s[2], s[3], t[2], t[3]):
                        conflicts.add((members[i], members[k]))
        if not conflicts:
            return splits
        split_targets = set()
        for i, k in sorted(conflicts):
            for index in (i, k):
                ci, j, a, b = segments[index]
                split_targets.add((ci, j, int(a[0]), int(a[1])))
        # Apply splits per chain from the highest segment index down so
        # earlier indices stay valid.
        by_chain: dict[int, list[int]] = {}
        for ci, j, _, _ in split_targets:
            by_chain.setdefault(ci, []).append(j)
        progressed = False
        for ci, indices in sorted(by_chain.items()):
            for j in sorted(set(indices), reverse=True):
                if chains[ci].split_segment(j):
                    splits += 1
                    progressed = True
        if not progressed:
            raise RuntimeError("crossing repair cannot progress")
    raise RuntimeError("crossing repair did not converge")


def _proper_cross(a, b, c, d) -> bool:
    ax, ay = int(a[0]), int(a[1])
    bx, by = int(b[0]), int(b[1])
    cx, cy = int(c[0]), int(c[1])
    dx, dy = int(d[0]), int(d[1])
    if (ax, ay) in ((cx, cy), (dx, dy)) or (bx, by) in ((cx, cy), (dx, dy)):
        return False
    d1 = _orient(cx, cy, dx, dy, ax, ay)
    d2 = _orient(cx, cy, dx, dy, bx, by)
    d3 = _orient(ax, ay, bx, by, cx, cy)
    d4 = _orient(ax, ay, bx, by, dx, dy)
    if d1 == 0 and d2 == 0:
        # Collinear: conflict when the 1-D projections overlap beyond a
        # shared endpoint (already excluded above).
        if ax == bx:
            lo1, hi1 = sorted((ay, by))
            lo2, hi2 = sorted((cy, dy))
        else:
            lo1, hi1 = sorted((ax, bx))
            lo2, hi2 = sorted((cx, dx))
        return max(lo1, lo2) < min(hi1, hi2)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and (
        d1 != 0 and d2 != 0 and d3 != 0 and d4 != 0
    )
