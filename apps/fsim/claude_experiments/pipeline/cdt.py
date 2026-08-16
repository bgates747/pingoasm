"""Deterministic integer constrained Delaunay triangulation.

Coordinates are doubled working-grid units so that both corner-lattice
points (even) and cell-center points (odd) are exact integers; all
orientation and in-circle predicates evaluate exactly in unbounded Python
integers. The domain is the closed rectangle [0, 2W] x [0, 2H] initialized
as two triangles; every later point lies inside or on the frame.

Triangles are append-only: any structural change kills the old ids and
allocates fresh ones, so consumers (the refinement heap) can treat a
triangle id as an immutable snapshot. `dirty` accumulates newly created
alive triangle ids for the consumer to drain.
"""

from __future__ import annotations

_KEY_SHIFT = 32


def _edge_key(a: int, b: int) -> int:
    return (a << _KEY_SHIFT) | b if a < b else (b << _KEY_SHIFT) | a


class CrossingError(RuntimeError):
    """A constraint segment crosses an existing constrained edge."""


class CDT:
    def __init__(self, width_units: int, height_units: int) -> None:
        w2, h2 = 2 * width_units, 2 * height_units
        self.pts: list[tuple[int, int]] = [
            (0, 0), (w2, 0), (w2, h2), (0, h2)
        ]
        self.point_index: dict[tuple[int, int], int] = {
            p: i for i, p in enumerate(self.pts)
        }
        self.tri_v: list[tuple[int, int, int]] = []
        self.tri_n: list[list[int]] = []
        self.alive: list[bool] = []
        self.vert_tri: list[int] = [-1, -1, -1, -1]
        self.constrained: set[int] = set()
        self.dirty: list[int] = []
        t0 = self._new_tri(0, 1, 2, [-1, 1, -1])
        t1 = self._new_tri(0, 2, 3, [-1, -1, 0])
        assert (t0, t1) == (0, 1)

    # -- primitives --------------------------------------------------------

    def orient(self, a: int, b: int, c: int) -> int:
        pa, pb, pc = self.pts[a], self.pts[b], self.pts[c]
        return (pb[0] - pa[0]) * (pc[1] - pa[1]) - (pb[1] - pa[1]) * (
            pc[0] - pa[0]
        )

    def _incircle(self, a: int, b: int, c: int, d: int) -> int:
        """> 0 iff d is strictly inside the circumcircle of ccw (a, b, c)."""

        ax, ay = self.pts[a]
        bx, by = self.pts[b]
        cx, cy = self.pts[c]
        dx, dy = self.pts[d]
        adx, ady = ax - dx, ay - dy
        bdx, bdy = bx - dx, by - dy
        cdx, cdy = cx - dx, cy - dy
        ad2 = adx * adx + ady * ady
        bd2 = bdx * bdx + bdy * bdy
        cd2 = cdx * cdx + cdy * cdy
        return (
            adx * (bdy * cd2 - cdy * bd2)
            - ady * (bdx * cd2 - cdx * bd2)
            + ad2 * (bdx * cdy - cdx * bdy)
        )

    def _new_tri(self, a: int, b: int, c: int, neighbors: list[int]) -> int:
        tid = len(self.tri_v)
        self.tri_v.append((a, b, c))
        self.tri_n.append(neighbors)
        self.alive.append(True)
        for v in (a, b, c):
            self.vert_tri[v] = tid
        self.dirty.append(tid)
        return tid

    def _kill(self, tid: int) -> None:
        self.alive[tid] = False

    def _neighbor_index(self, tid: int, a: int, b: int) -> int:
        """Index i such that edge (v_{i+1}, v_{i+2}) of tid is {a, b}."""

        v = self.tri_v[tid]
        for i in range(3):
            e1, e2 = v[(i + 1) % 3], v[(i + 2) % 3]
            if (e1 == a and e2 == b) or (e1 == b and e2 == a):
                return i
        raise KeyError((tid, a, b))

    def _link(self, tid: int, other: int, a: int, b: int) -> None:
        """Point `other`'s slot across edge {a, b} at tid."""

        if other == -1:
            return
        self.tri_n[other][self._neighbor_index(other, a, b)] = tid

    # -- point insertion ---------------------------------------------------

    def locate(
        self, p: tuple[int, int], hint: int
    ) -> tuple[str, int, int]:
        """Locate p: ('in', tid, -1) | ('edge', tid, i) | ('vertex', vid, -1)."""

        px, py = p
        t = hint
        if t < 0 or not self.alive[t]:
            t = next(i for i in range(len(self.alive) - 1, -1, -1)
                     if self.alive[i])
        steps = 0
        limit = 4 * len(self.tri_v) + 16
        while True:
            steps += 1
            if steps > limit:
                return self._locate_exhaustive(p)
            v = self.tri_v[t]
            zero_at = -1
            zero_count = 0
            moved = False
            for i in range(3):
                a, b = v[(i + 1) % 3], v[(i + 2) % 3]
                pa, pb = self.pts[a], self.pts[b]
                o = (pb[0] - pa[0]) * (py - pa[1]) - (pb[1] - pa[1]) * (
                    px - pa[0]
                )
                if o < 0:
                    nxt = self.tri_n[t][i]
                    if nxt == -1:
                        raise ValueError(f"point outside domain: {p}")
                    t = nxt
                    moved = True
                    break
                if o == 0:
                    zero_at = i
                    zero_count += 1
            if moved:
                continue
            if zero_count == 0:
                return ("in", t, -1)
            if zero_count == 1:
                return ("edge", t, zero_at)
            for vid in v:
                if self.pts[vid] == p:
                    return ("vertex", vid, -1)
            raise ValueError(f"degenerate location for {p}")

    def _locate_exhaustive(self, p: tuple[int, int]) -> tuple[str, int, int]:
        px, py = p
        for t in range(len(self.tri_v)):
            if not self.alive[t]:
                continue
            v = self.tri_v[t]
            zero_at = -1
            zero_count = 0
            inside = True
            for i in range(3):
                a, b = v[(i + 1) % 3], v[(i + 2) % 3]
                pa, pb = self.pts[a], self.pts[b]
                o = (pb[0] - pa[0]) * (py - pa[1]) - (pb[1] - pa[1]) * (
                    px - pa[0]
                )
                if o < 0:
                    inside = False
                    break
                if o == 0:
                    zero_at = i
                    zero_count += 1
            if not inside:
                continue
            if zero_count == 0:
                return ("in", t, -1)
            if zero_count == 1:
                return ("edge", t, zero_at)
            for vid in v:
                if self.pts[vid] == p:
                    return ("vertex", vid, -1)
        raise ValueError(f"point not located: {p}")

    def insert_point(self, p: tuple[int, int], hint: int = -1) -> int:
        existing = self.point_index.get(p)
        if existing is not None:
            return existing
        kind, t, i = self.locate(p, hint)
        if kind == "vertex":
            return t
        vid = len(self.pts)
        self.pts.append(p)
        self.point_index[p] = vid
        self.vert_tri.append(-1)
        if kind == "in":
            self._split_interior(t, vid)
        else:
            self._split_edge(t, i, vid)
        return vid

    def _split_interior(self, t: int, p: int) -> None:
        a, b, c = self.tri_v[t]
        na, nb, nc = self.tri_n[t]
        self._kill(t)
        t0 = self._new_tri(a, b, p, [-1, -1, nc])
        t1 = self._new_tri(b, c, p, [-1, t0, na])
        t2 = self._new_tri(c, a, p, [t0, t1, nb])
        self.tri_n[t0][0] = t1
        self.tri_n[t0][1] = t2
        self.tri_n[t1][0] = t2
        self._link(t0, nc, a, b)
        self._link(t1, na, b, c)
        self._link(t2, nb, c, a)
        self._legalize(t0, 2)
        self._legalize(t1, 2)
        self._legalize(t2, 2)

    def _split_edge(self, t: int, i: int, p: int) -> None:
        v = self.tri_v[t]
        c, a, b = v[i], v[(i + 1) % 3], v[(i + 2) % 3]
        u = self.tri_n[t][i]
        nbc = self.tri_n[t][(i + 1) % 3]
        nca = self.tri_n[t][(i + 2) % 3]
        was_constrained = _edge_key(a, b) in self.constrained
        if was_constrained:
            self.constrained.discard(_edge_key(a, b))
            self.constrained.add(_edge_key(a, p))
            self.constrained.add(_edge_key(p, b))
        self._kill(t)
        t0 = self._new_tri(a, p, c, [-1, nca, -1])
        t1 = self._new_tri(p, b, c, [nbc, t0, -1])
        self.tri_n[t0][0] = t1
        self._link(t0, nca, c, a)
        self._link(t1, nbc, b, c)
        if u == -1:
            self._legalize(t0, 1)
            self._legalize(t1, 0)
            return
        j = self._neighbor_index(u, a, b)
        d = self.tri_v[u][j]
        ndb = self.tri_n[u][self._neighbor_index_of_vertex(u, a)]
        nad = self.tri_n[u][self._neighbor_index_of_vertex(u, b)]
        self._kill(u)
        u0 = self._new_tri(b, p, d, [-1, ndb, t1])
        u1 = self._new_tri(p, a, d, [nad, u0, t0])
        self.tri_n[u0][0] = u1
        self.tri_n[t1][2] = u0
        self.tri_n[t0][2] = u1
        self._link(u0, ndb, d, b)
        self._link(u1, nad, a, d)
        self._legalize(t0, 1)
        self._legalize(t1, 0)
        self._legalize(u0, 1)
        self._legalize(u1, 0)

    def _neighbor_index_of_vertex(self, tid: int, v: int) -> int:
        t = self.tri_v[tid]
        for i in range(3):
            if t[i] == v:
                return i
        raise KeyError((tid, v))

    def _legalize(self, t: int, i: int) -> None:
        stack = [(t, i)]
        while stack:
            t, i = stack.pop()
            if not self.alive[t]:
                continue
            v = self.tri_v[t]
            p, a, b = v[i], v[(i + 1) % 3], v[(i + 2) % 3]
            if _edge_key(a, b) in self.constrained:
                continue
            u = self.tri_n[t][i]
            if u == -1:
                continue
            j = self._neighbor_index(u, a, b)
            d = self.tri_v[u][j]
            if self._incircle(p, a, b, d) <= 0:
                continue
            npa = self.tri_n[t][self._neighbor_index_of_vertex(t, b)]
            nbp = self.tri_n[t][self._neighbor_index_of_vertex(t, a)]
            nad = self.tri_n[u][self._neighbor_index_of_vertex(u, b)]
            ndb = self.tri_n[u][self._neighbor_index_of_vertex(u, a)]
            self._kill(t)
            self._kill(u)
            t2 = self._new_tri(p, a, d, [nad, -1, npa])
            u2 = self._new_tri(p, d, b, [ndb, nbp, t2])
            self.tri_n[t2][1] = u2
            self._link(t2, nad, a, d)
            self._link(t2, npa, p, a)
            self._link(u2, ndb, d, b)
            self._link(u2, nbp, b, p)
            stack.append((t2, 0))
            stack.append((u2, 0))

    # -- constraint segments -----------------------------------------------

    def _incident_triangles(self, v: int) -> list[int]:
        seed = self.vert_tri[v]
        if seed < 0 or not self.alive[seed]:
            seed = next(
                t for t in range(len(self.tri_v))
                if self.alive[t] and v in self.tri_v[t]
            )
        seen = {seed}
        stack = [seed]
        out = []
        while stack:
            t = stack.pop()
            out.append(t)
            for n in self.tri_n[t]:
                if n != -1 and n not in seen and self.alive[n] and (
                    v in self.tri_v[n]
                ):
                    seen.add(n)
                    stack.append(n)
        return out

    def insert_segment(self, va: int, vb: int) -> None:
        while va != vb:
            va = self._insert_subsegment(va, vb)

    def _insert_subsegment(self, va: int, vb: int) -> int:
        """Constrain from va toward vb; return the vertex reached."""

        pa = self.pts[va]
        pb = self.pts[vb]

        def seg_orient(vx: int) -> int:
            px = self.pts[vx]
            return (pb[0] - pa[0]) * (px[1] - pa[1]) - (
                pb[1] - pa[1]
            ) * (px[0] - pa[0])

        def on_open_segment(vx: int) -> bool:
            px = self.pts[vx]
            dot = (px[0] - pa[0]) * (pb[0] - pa[0]) + (
                px[1] - pa[1]
            ) * (pb[1] - pa[1])
            length2 = (pb[0] - pa[0]) ** 2 + (pb[1] - pa[1]) ** 2
            return 0 < dot < length2

        start = None
        for t in self._incident_triangles(va):
            k = self._neighbor_index_of_vertex(t, va)
            x = self.tri_v[t][(k + 1) % 3]
            y = self.tri_v[t][(k + 2) % 3]
            if x == vb or y == vb:
                self.constrained.add(_edge_key(va, vb))
                return vb
            ox, oy = seg_orient(x), seg_orient(y)
            if ox == 0 and on_open_segment(x):
                self.constrained.add(_edge_key(va, x))
                return x
            if oy == 0 and on_open_segment(y):
                self.constrained.add(_edge_key(va, y))
                return y
            # For a ccw triangle (va, x, y), x lies on the negative side of
            # the segment direction and y on the positive side when the
            # segment exits through edge (x, y).
            if ox < 0 and oy > 0:
                px, py = self.pts[x], self.pts[y]
                forward = (py[0] - px[0]) * (pb[1] - px[1]) - (
                    py[1] - px[1]
                ) * (pb[0] - px[0])
                if forward <= 0:
                    start = (t, x, y)
                    break
        if start is None:
            raise ValueError(
                f"no marching start from vertex {va} toward {vb}"
            )

        t, x, y = start
        if _edge_key(x, y) in self.constrained:
            raise CrossingError((va, vb, x, y))
        crossed = [t]
        negative = [x]
        positive = [y]
        end = vb
        current = self.tri_n[t][self._neighbor_index(t, x, y)]
        while True:
            if current == -1:
                raise ValueError("constraint march left the domain")
            crossed.append(current)
            j = self._neighbor_index(current, x, y)
            w = self.tri_v[current][j]
            if w == vb:
                break
            o = seg_orient(w)
            if o == 0:
                end = w
                break
            if o > 0:
                positive.append(w)
                y = w
            else:
                negative.append(w)
                x = w
            if _edge_key(x, y) in self.constrained:
                raise CrossingError((va, vb, x, y))
            current = self.tri_n[current][
                self._neighbor_index(current, x, y)
            ]

        # Record the cavity boundary: every un-crossed edge of a crossed
        # triangle, directed as that triangle sees it, with its outside
        # neighbor.
        crossed_set = set(crossed)
        boundary: dict[tuple[int, int], int] = {}
        for tid in crossed:
            v = self.tri_v[tid]
            for i in range(3):
                n = self.tri_n[tid][i]
                if n in crossed_set:
                    continue
                e1, e2 = v[(i + 1) % 3], v[(i + 2) % 3]
                boundary[(e1, e2)] = n
        for tid in crossed:
            self._kill(tid)

        new_tris: list[tuple[int, int, int]] = []

        def triangulate(base_a: int, base_b: int, chain: list[int]) -> None:
            if not chain:
                return
            c = chain[0]
            best = 0
            for k in range(1, len(chain)):
                if self._incircle(base_a, base_b, c, chain[k]) > 0:
                    c = chain[k]
                    best = k
            triangulate(base_a, c, chain[:best])
            triangulate(c, base_b, chain[best + 1:])
            new_tris.append((base_a, base_b, c))

        triangulate(va, end, positive)
        triangulate(end, va, list(reversed(negative)))

        edge_owner: dict[tuple[int, int], int] = {}
        created = []
        for a, b, c in new_tris:
            tid = self._new_tri(a, b, c, [-1, -1, -1])
            created.append(tid)
            edge_owner[(a, b)] = tid
            edge_owner[(b, c)] = tid
            edge_owner[(c, a)] = tid
        for tid in created:
            a, b, c = self.tri_v[tid]
            for i, (e1, e2) in enumerate(((b, c), (c, a), (a, b))):
                partner = edge_owner.get((e2, e1))
                if partner is not None:
                    self.tri_n[tid][i] = partner
                    continue
                outside = boundary.get((e1, e2), boundary.get((e2, e1)))
                if outside is None:
                    raise RuntimeError("cavity edge without outside triangle")
                self.tri_n[tid][i] = outside
                if outside != -1:
                    self.tri_n[outside][
                        self._neighbor_index(outside, e1, e2)
                    ] = tid
        self.constrained.add(_edge_key(va, end))
        return end

    # -- queries -----------------------------------------------------------

    def alive_triangles(self) -> list[int]:
        return [t for t in range(len(self.tri_v)) if self.alive[t]]

    def region_labels(self) -> dict[int, int]:
        """Label alive triangles by flood fill across unconstrained edges."""

        labels: dict[int, int] = {}
        next_label = 0
        for seed in range(len(self.tri_v)):
            if not self.alive[seed] or seed in labels:
                continue
            stack = [seed]
            labels[seed] = next_label
            while stack:
                t = stack.pop()
                v = self.tri_v[t]
                for i in range(3):
                    n = self.tri_n[t][i]
                    if n == -1 or n in labels or not self.alive[n]:
                        continue
                    a, b = v[(i + 1) % 3], v[(i + 2) % 3]
                    if _edge_key(a, b) in self.constrained:
                        continue
                    labels[n] = next_label
                    stack.append(n)
            next_label += 1
        return labels
