# Hexagonal terrain-cell proposal

Status: **proposed alternate streaming topology**. The accepted rectangular
regional loader remains the working control. This proposal does not authorize a
second fixture-local terrain coordinator: rectangular and hexagonal cells must
both be policies of the authoritative terrain manager specified in
`docs/terrain-scene-design.md`. J1 remains the sole actionable work item.

## Scope and terminology

This proposal makes the **streaming, residency, and whole-object culling cells
themselves hexagonal**. It is distinct from merely placing a triangular vertex
lattice inside rectangular chunks.

The two ideas are complementary:

1. The triangular lattice defines elevation vertices and equilateral triangle
   faces.
2. The hexagonal cell defines which faces form one independently loadable P3DM
   terrain component and one Pingo object.

A regular hexagonal tiling gives every interior cell six equivalent neighbors.
The resulting world has no privileged rectangular diagonal, and distance rings
around a camera are isotropic in the topology actually used by the loader.

## Expected benefits

The proposed topology should provide:

1. six equal neighbor directions instead of four cardinal neighbors plus four
   longer diagonals;
2. more uniform visual detail and streaming notice around a moving aircraft;
3. natural disks, rings, forward wedges, and velocity-biased resident sets;
4. less visible square-grid structure in silhouettes, lighting, material
   boundaries, and the advancing terrain horizon;
5. LOD bands based on one exact hex distance rather than rectangular Manhattan
   or Chebyshev approximations; and
6. cell edges aligned with the already preferred equilateral-triangle terrain
   lattice.

Pingo still receives ordinary triangle meshes. No hexagon primitive or
rasterizer change is implied. Whole-object culling remains AABB-based, so a
hexagonal mesh retains some empty space in its rectangular bounding box; the
proposal concerns terrain organization, not a new culling volume.

## Coordinate system

The candidate uses signed axial coordinates `(q,r)` with the implicit cube
coordinate:

```text
s = -q-r
```

The six neighbors are fixed axial offsets:

```text
(+1, 0)  (+1,-1)  (0,-1)
(-1, 0)  (-1,+1)  (0,+1)
```

The provisional orientation is **flat-top**, because it provides a direct
east/west neighbor axis useful to the current UTM-aligned Bay Area world. For
hex side length `a`, ideal projected centres relative to an origin are:

```text
east  = (3/2 * a) * q
north = (sqrt(3) * a) * (r + q/2)
```

Orientation and side length remain profile values until a controlled visual
comparison is accepted. A pointy-top provider uses the corresponding rotated
basis without changing manager semantics.

Runtime placement must not accumulate floating-point or repeated-step error.
The corpus manifest stores two prequantized integer basis vectors in the
authoritative 1/16-metre translation-count domain. A centre is always rebuilt
directly from `(q,r)` and those vectors:

```text
centre = regional_origin + q*basis_q + r*basis_r
```

The small geometric distortion introduced by quantizing each basis once is
bounded and recorded. Repeated movement, eviction, reload, and rebasing cannot
accumulate further drift.

World position converts to fractional axial coordinates through the inverse
basis. Cell selection uses standard cube rounding: round fractional `q`, `r`,
and `s`, then correct the component with the largest rounding error so the
integer result still satisfies `q+r+s=0`. Exact boundary ties use one specified
lexicographic rule. A small hysteresis band prevents selection chatter while a
camera follows an edge.

Hex distance is:

```text
distance(a,b) = max(abs(dq), abs(dr), abs(ds))
```

Neighbor walks, rings, disks, LOD thresholds, collision candidate expansion,
and streaming priority all use this same definition.

## Cell dimensions

Hex size must be compared by area and mesh density, not merely by one diameter.
A regular hexagon of side length `a` has:

```text
area = 3*sqrt(3)/2 * a^2
```

Two useful first controls are:

1. `a = 256 m`, giving a 512 m vertex-to-vertex width but only about
   170,267 square metres per cell; and
2. equal area with the current 512×512 m square, giving
   `a = sqrt(2*512^2/(3*sqrt(3)))`, approximately 317.7 m.

The equal-area candidate is the fairer object-count and triangle-budget
comparison. Its ideal east/west centre spacing is about 476.5 m and its row
spacing about 550.2 m. Final basis values must be stated as exact integer
translation counts in the corpus profile rather than recomputed from these
rounded descriptive values.

## Mesh construction and seams

The hex boundaries and terrain faces should come from one regional triangular
lattice whose phase never restarts at a cell boundary. Hex side length is an
integer number of triangular-lattice edge steps. Every perimeter therefore
follows lattice edges rather than cutting arbitrary triangles.

The compiler assigns every triangle to exactly one axial cell. Neighboring
components duplicate their shared boundary vertices, but those vertices are
sampled through the same canonical global lattice keys and must encode
byte-identical world positions and elevations. Three cells meeting at a corner
share the same canonical corner sample. Per-component normalization is
forbidden; all cells in a profile use one documented padded extent and object
scale so independent meshes reproduce exact regional positions.

This construction avoids both failure modes seen in earlier experiments:

1. diagonally bisected rectangular quads do not reappear inside the cell; and
2. independently normalized boundary meshes cannot acquire different physical
scales and open seams.

Same-LOD neighbors should join exactly. Mixed-LOD cells initially retain the
accepted skirt policy, generalized to six edges. A future stitch pattern must
be indexed by the six edge directions and neighbor LOD delta; it cannot assume
north, south, east, and west edges.

Airport property patches are a second kind of seam and must be compiled, not
hidden by draw order. An airport's projected property polygon cuts a true hole
from every terrain cell it intersects. The airport compiler and terrain
compiler share canonical boundary keys, so the replacement patch and retained
terrain encode byte-identical positions around the complete property outline.
The polygon may cross any number of hex cells; it does not become hexagonal and
does not inherit cell boundaries as its visual boundary.

The airport side may use a denser constrained triangulation than the regional
terrain. Boundary segments are subdivided wherever either mesh requires a
vertex, and those subdivisions are propagated into the adjacent coarse terrain
triangles before triangulation. The airport interior is graded from pinned
runway/field elevations while its perimeter takes the canonical terrain edge
elevations. A compiler-defined transition region inside the property reconciles
the two without cracks, vertical skirts, T-junctions, or overlapping coplanar
faces. Relief-aware triangulation remains required on the retained terrain.

## Resident windows and object budget

A complete radius-`k` hex disk contains:

```text
N(k) = 1 + 3*k*(k+1)
```

The first useful sizes are:

| Radius | Terrain cells | Operational implication |
|---:|---:|---|
| 0 | 1 | trivial |
| 1 | 7 | small local neighborhood |
| 2 | 19 | useful conservative baseline |
| 3 | 37 | first substantially broader complete disk |
| 4 | 61 | expensive unless LOD and culling measurements justify it |

The Pingo VDU bridge now traverses the complete `uint16_t` object registry
directly and has no fixed active-object ceiling. Scene size is consequently a
manager policy and performance budget, not a firmware array bound. Radius 3 is
the first important complete-disk candidate; radius 4 must not be selected
merely because its 61 cells fit within a convenient round number. The chosen
terrain and non-terrain pool budgets must be based on object-registry memory,
per-object traversal, culling effectiveness, triangle load, and measured
real-hardware frame time.

Directional look-ahead does not require an asymmetric hard-coded cell table.
The manager begins with a complete inner disk, then scores optional outer-ring
cells by distance, view direction, velocity, altitude, and time to boundary.
Changing heading changes priority, not topology or cell identity.

## Residency and stable slots

Axial coordinates are the durable terrain identity. A corpus gives them a
bounded deterministic file ID through its manifest; invalid cells outside the
regional coverage polygon are explicitly absent rather than inferred through a
directory scan. P3DM `tile_x` and `tile_y` fields carry signed axial `q` and
`r` for a hex-topology corpus, with the manifest declaring that interpretation.

The current rectangular modulo mapping is not part of the hex contract. The
common terrain manager maintains an explicit bounded mapping from resident
axial cell to stable terrain slot. Desired cells keep their slots; incoming
cells take inactive or evictable slots only at the render-idle barrier. Slot
choice is deterministic for a given desired-set order, and a failed load keeps
the old complete mesh until policy permits retry or deactivation.

Terrain, airport surface components, landmarks, and other layers retain
separate slot pools. Removing the old firmware ceiling does not authorize
terrain to consume every practical object; configured pool budgets are
validated during manager initialization. An airport replacement patch also
retains explicit dependencies on every clipped terrain component it supersedes,
so publication cannot briefly show both surfaces or neither surface.

## Floating origin

The coarse regional origin becomes an axial cell plus an exact local planar
offset. When the manager accepts a new origin cell, it subtracts the exact
integer basis-vector displacement between old and new centres from the camera,
aircraft, and every managed object while no render is in flight.

Reconstruction is always:

```text
regional_position = origin + q*basis_q + r*basis_r + local_offset
```

Crossing a hex boundary may change one or two axial components, but it is one
transactional origin change. The manager uses cube rounding and hysteresis to
avoid oscillation at edges and three-cell corners. Flight dynamics and source
UTM coordinates remain unchanged by the render-frame rebase.

## Other world layers

Airports, runways, landmarks, water, and collision data remain authored in
projected physical coordinates. They need not be cut into hexagons merely
because terrain is. Their providers query the manager's current regional
position and intersect their own bounds with the desired terrain neighborhood
or activation range.

Airports are nevertheless a normative exception to independent overlay
geometry. Each airport owns a pinned, versioned property outline. At corpus
compile time that outline replaces the terrain elevation and land-use faces
inside it; it is not rendered over an intact coplanar terrain surface. The
replacement domain contains, in order of ownership:

1. graded airport earth or other residual property surface;
2. pavement polygons for runways, taxiways, and aprons; and
3. runway/taxiway markings cut into the pavement triangulation.

These layers are polygon partitions, not coincident faces. A point in the
property has one visible surface owner. Pavement removes the airport-base faces
beneath it, and markings remove the pavement faces beneath them. This prevents
z-fighting at both the terrain/property boundary and inside the airport.

All visible airport faces use Pingo solid-flat shading with native palette
selectors, self illumination, and no flat-pattern lookup. Scene illumination
therefore cannot turn an airport color into a dither pattern. The deliberately
crisp, limited pavement and marking palette is a navigation aid: at the target
viewport resolution airports must remain distinguishable from the surrounding
dithered terrain at flight distance.

The default airport property palette and classification precedence are:

| Surface role | RGB2 | Selector/pixel | Default use |
| --- | --- | --- | --- |
| marking white | `(3,3,3)` | `63` / `0xFF` | all runway and taxiway markings |
| pavement dark gray | `(1,1,1)` | `21` / `0xD5` | runways and taxiways |
| ramp light gray | `(2,2,2)` | `42` / `0xEA` | positively identified ramps and aprons |
| residual muted green | `(1,2,1)` | `25` / `0xD9` | every other airport-property ground face |

The muted green deliberately uses a two-thirds green channel rather than full
green and lifts red/blue one step so it is neither blackish nor a saturated
terrain green. Ramp gray is used only where source data supports the
classification; the compiler must not invent ramp coverage merely to add
visual variety. These exact selectors are the deterministic first candidate
and still require emulator and hardware visual acceptance.

Terminal and other airport structures are not ground-palette roles, but a
separate simplified structure provider may emit them when mapping data supplies
an attributable building footprint. Explicit height is preferred, then a
documented `building:levels` conversion; a missing height may use one pinned,
conservative airport-structure default only when the footprint's terminal or
airport-building classification is unambiguous. No footprint means no invented
building.

The first structure material is a fixed sparse 4×4 dither between dark gray
`0xD5` and light gray `0xEA`: thirteen dark pixels and three light pixels,
distributed without adjacent light pixels. Its average channel value is
`1.1875` in RGB2 (about 101/255), visibly between the two ground grays while
remaining much quieter than patterned terrain. The pattern is self-illuminated
and does not change illumination bands, so scene lighting cannot make the
dither denser or obscure the airport silhouette. Exact phase is deterministic
and the pattern still requires visual acceptance.

Structure meshes initially comprise walls and a simplified roof, with no
coplanar bottom face. Their bases conform to the graded airport property
surface, which remains the ground owner beneath them. Mapping-derived collision
boxes are separate conservative metadata. More detailed terminal modeling,
roof furniture, gates, and facade textures remain out of scope.

Airport collision and support data use the same replacement-domain geometry
and grading solution. The visual mesh, runway support plane, and terrain-height
query must not disagree about which surface owns a point. Landmarks and water
remain independent providers unless a later specification gives them an
equivalent replacement-domain contract.

Terrain-height and collision queries use the containing axial cell plus the
six neighbors when a swept proxy or runway footprint approaches an edge.
Broad-phase metadata such as maximum terrain elevation is indexed by axial
cell and hex rings, allowing the same conservative look-ahead proposed for the
rectangular corpus.

## Authoritative-manager integration

Hex topology is a manager provider, not a new loader. It supplies:

1. projected-position to axial-cell conversion and deterministic rounding;
2. axial centre reconstruction from exact basis vectors;
3. six-neighbor, ring, disk, and distance operations;
4. bounded corpus identity and path lookup;
5. desired-set generation and directional priority; and
6. cell bounds for culling metadata, collision candidates, and layer queries.

The common manager continues to own P3DM/AGNB validation, residency, stable
slots, render-idle publication, origin transactions, error state, and teardown.
The rectangular provider must first reproduce the accepted regional trace
through that same interface. Hex work must not begin by copying the current
regional-camera coordinator.

## Proposed evaluation sequence

J1 owns this sequence; it is not a second actionable checklist.

1. Consolidate the existing rectangular regional behavior into the common
   manager and reproduce the accepted cold-load and boundary-crossing traces.
2. Implement host-only axial math, cube rounding, ring enumeration, exact
   basis reconstruction, corpus identity, and boundary tests.
3. Generate a separate Berkeley-area equal-area hex corpus from the existing
   DEM/NLCD sources without overwriting the rectangular control.
4. Compare rectangular 8×4, hex radius 2, and hex radius 3 using the same
   camera, shading, relief, source coverage, approximate triangle budget, and
   explicitly reserved non-terrain pools.
5. Generate at least KOAK as a constrained airport-property replacement and
   qualify its boundary against every intersected cell and LOD.
6. Qualify six-edge seams, all six boundary crossings, corner hysteresis,
   missing/corrupt component behavior, airport/terrain atomic publication,
   and sustained arbitrary travel in the emulator and on physical hardware.
7. Promote hex topology to the runtime baseline only if it improves visual
   structure and streaming behavior without unacceptable memory, publication,
   traversal, or frame-time cost.

## Acceptance evidence

An accepted hex topology must retain:

1. byte-identical shared-edge positions at all six edges and three-cell
   corners;
2. no visible seams under flat-pattern shading and normal camera motion;
3. deterministic position-to-cell selection at edges and corners;
4. exact regional-coordinate reconstruction through repeated arbitrary
   rebases;
5. bounded, deterministic residency and failure behavior;
6. comparable or better triangle/object/frame-time measurements than the
   equal-area rectangular control;
7. no overlapping terrain/airport, airport/pavement, or pavement/marking faces;
8. crack-free, T-junction-free property seams at every intersected cell and
   qualified LOD, with one visual and collision owner for every property point;
9. solid-flat, self-illuminated, non-dithered airport rendering that remains
   legible against dithered terrain; and
10. explicit human visual acceptance before replacing the rectangular control.

Until those gates pass, the current rectangular corpus and loader remain the
known working baseline.
