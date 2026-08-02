# Triangular-lattice terrain experiment

Status: **approved alternate visualization experiment**. The existing
relief-aware rectangular-grid triangulation remains the proven control and is
not replaced.

The Author subsequently accepted the triangular fixture as the more pleasing
terrain topology. Its common padded-extent correction eliminated the observed
chunk seams. The rectangular topology remains available as a regression
control rather than being overwritten.

## Purpose

The rectangular DEM grid necessarily exposes traces of its bisected quads.
Even relief-aware diagonal selection can leave terrain with an artificial
two-triangle cadence. This experiment resamples the same source data onto a
regular triangular lattice. Every interior vertex has six neighbors, giving
the mesh hexagonal connectivity, and every face is equilateral in horizontal
plan view before elevation is applied.

The expected visual benefit is more isotropic relief, silhouettes, and
lighting. The lattice has three evenly distributed edge directions instead of
the rectangular grid's axes plus selected diagonals. It is still an ordinary
triangle mesh and requires no new Pingo primitive.

## Construction

Rows alternate between zero and half-spacing horizontal offsets. Vertical row
spacing is `sqrt(3) / 2` times horizontal spacing:

```text
o---o---o---o
  o---o---o---o
o---o---o---o
```

DEM elevation is bilinearly sampled at each lattice vertex. Each triangle is
assigned the predominant NLCD category using the same projected-raster method
and the same restrained natural material palette as the control scene.

The control grid samples at 40 metre intervals. A triangular lattice allocates
`sqrt(3) / 2 * spacing^2` plan area per vertex, so equal vertex density uses:

```text
triangular spacing = square spacing * sqrt(2 / sqrt(3))
```

This is approximately 42.98 metres for the current 40 metre control spacing.
The generated lattice is centered within the DEM. Complete equilateral cells
are retained; narrow unmatched perimeter margins are allowed rather than
introducing irregular boundary triangles. They must be reported in generator
metadata and considered when comparing coastlines at the extreme boundary.

## Pingo chunk partitioning

The runtime fixture constructs one continuous lattice over the complete active
region and assigns whole triangles to 512 metre render chunks by centroid.
Lattice phase must never restart at a chunk boundary. A boundary triangle may
therefore extend beyond the nominal bounds of the object that owns it.

PingoASM's mature mesh writer implicitly normalizes an entire mesh whenever any
coordinate exceeds `[-1,+1]`. Letting boundary vertices exceed that range while
retaining the ordinary object scale causes every affected chunk to acquire a
different physical size and opens gaps nearly one triangle wide.

The triangular fixture prevents that behavior by using one common padded local
half-extent for every chunk:

```text
padded half-extent = chunk width / 2 + triangular spacing
```

Horizontal vertex coordinates are divided by that extent, the generator
asserts that every complete vertex remains within `[-1,+1]`, and every object
receives the same compensating horizontal scale. This preserves world-space
positions while retaining whole triangles and independent chunk culling.
Per-mesh normalization is forbidden for partitioned terrain.

## Controlled comparison

Both scenes use identical:

- 3DEP DEM and NLCD source rasters;
- horizontal and vertical scale;
- elevation midpoint and lack of vertical exaggeration;
- natural NLCD material colors;
- camera, lighting, world, and Workbench display settings; and
- predominant-category face classification.

The files are deliberately separate:

- `build/visualization/berkeley-terrain.blend` — relief-aware rectangular
  control;
- `build/visualization/berkeley-terrain-triangular.blend` — triangular-lattice
  alternate.

The first comparison should examine visible diagonal cadence, recognizable
features, ridge silhouettes, flat-area material boundaries, distant shimmer,
and vertex/face counts. No Pingo fixture changes follow merely from a favorable
Blender result; the alternate must first be evaluated against the control.
