# Pingo terrain scene design

This is the normative design specification for Pingo terrain scenes. It owns
the accepted coordinate scale, mesh/chunk representation, camera relationship,
floating-origin behavior, elevation policy, and cockpit composition. Dated
development logs retain research and decision provenance; implementation
experiments must conform to this document or explicitly amend it.

## Coordinate contract

One Pingo internal world unit represents **8 metres**. Aircraft, terrain,
runways, water, scenery, cameras, and velocities share this physical scale.
Terrain is not scaled independently from aircraft to make either easier to
render.

Pingo wire conversions are part of the design constraint. The established
commands remain the compatibility baseline; two experimental commands extend
only the ranges needed by regional terrain:

1. Mesh positions are signed 16-bit normalized values mapping approximately
   to `-1.0..+1.0` before object transforms.
2. Object and scene scale use unsigned Q8.8 values; wire value `256` is
   internal scale `1.0`.
3. Legacy object command 17, camera command 25, and scene command 37 encode
   XYZ translation as signed little-endian 16-bit raw values. Commands 14–16,
   22–24, and 34–36 apply the same encoding one axis at a time. The native
   conversion is `signed_raw * (256 / 32767)` internal units, giving roughly
   `-256..+256` internal units.
4. At 8 metres per internal unit, that legacy translation window is
   approximately 4.096 km edge to edge and one raw count is approximately
   6.25 cm.
5. Experimental object command 52 accepts signed little-endian 24-bit X, Y,
   and Z values in exactly the same raw unit as command 17. Sign-extending a
   command-17 value therefore preserves its transform. Its full object-only
   range is approximately -524 km through +524 km at terrain scale. It does
   not define a wide camera or scene transform.
6. Perspective near distance remains fixed at `1` internal unit. Every Pingo
   control defaults to a far distance of `2500` internal units. Experimental
   command 53 changes that control's far distance with one unsigned 16-bit
   world-unit value; accepted values are `2..65535`. Values zero or one and a
   truncated word preserve the previous setting. Deleting and recreating a
   control restores `2500`.

Source datasets retain metre-based coordinates and elevations through offline
processing. Conversion to Pingo units occurs at the generated-scene boundary;
the compiler must record both physical and Pingo values in its manifest.

## Aircraft scale

The accepted first aircraft is the existing PingoASM Jet. Its generated mesh
has an approximately 1.78-unit longitudinal span at object scale `256`
(`1.0`), which represents approximately 14.2 metres under this contract. Keep
that scale as the baseline rather than enlarging the aircraft relative to the
world.

Other aircraft importers should normalize their source geometry and select an
object scale that reproduces the model's intended physical dimensions at 8
metres per unit. A profile must state the authoritative real or chosen
dimensions used for that conversion.

## Third-person camera

Showcase the aircraft through camera composition rather than nonphysical
scale. The initial chase-camera envelope is:

1. distance behind the aircraft: 5–8 internal units (40–64 m);
2. height above the aircraft: 1.5–3 internal units (12–24 m); and
3. aim target: at or slightly above/ahead of the aircraft origin.

Exact distance, elevation, damping, and field of view are fixture profile
parameters and require visual qualification. Camera motion and aircraft
simulation remain eZ80-owned absolute state. The chase camera must not change
terrain or aircraft physical scale.

## First-person cockpit

The accepted first-person design uses Pingo for the exterior view and a 2D VDP
cockpit/instrument overlay. The aircraft exterior is not rendered around the
camera in first-person mode.

The initial panel source is the vendored 320×92 RGBA artwork at
`assets/cockpit/fsimpanel.png`. It originated in PingoASM's historical flight
simulator work; see the adjacent provenance record. Its dimensions naturally
pair with the preserved 320×148 exterior-view layout, although the final
terrain fixture must compare that historical split with the authoritative
TODO's proposed 320×120 half-screen terrain benchmark and a correspondingly
larger instrument region. The source PNG remains authoritative; RGBA2222 and
other runtime encodings are generated outputs.

Pingo's fixed near plane is 1 internal unit, or 8 m under this contract. That
is unsuitable for cockpit geometry surrounding the camera but does not affect
the accepted 2D overlay. A future 3D cockpit requires an explicitly qualified
configurable near plane or separate projection/pass; it must not shrink the
entire world scale as a workaround.

## Terrain chunk geometry

Terrain is a regular projected height grid partitioned into independently
culled square chunks. Each chunk is one Pingo object bound to one selected LOD
mesh. Mesh coordinates are local to the chunk and centered around its origin.
Object translation locates the chunk in the current floating world.

Every height sample is a mesh vertex, never a face-center value. Grid cells are
exported as explicit triangles for Pingo. For each cell, the compiler selects
the diagonal with the smaller endpoint elevation difference; exact ties use a
stable checkerboard-parity choice. This relief-aware rule is deterministic
across builds and chunks, preserves all source samples, and avoids systematic
diagonal bias on level terrain.

For a mesh whose X and Z coordinates span `-1..+1`, object scale is half the
chunk's width in internal units. Initial candidate widths are:

| Role | Physical width | Internal width | Object scale |
|---|---:|---:|---:|
| Near/small candidate | 256 m | 32 | 16 (`4096` wire) |
| Standard baseline | 512 m | 64 | 32 (`8192` wire) |
| Coarse far candidate | 1,024 m | 128 | 64 (`16384` wire) |

The standard first experiment uses **512 m chunks**. Candidate dimensions do
not authorize mixing different physical chunk footprints merely to implement
LOD. Prefer several mesh densities over one fixed 512 m footprint so an
object's bounds and placement remain stable as its mesh is rebound. Larger far
footprints are a separate horizon/storage experiment.

Each standard chunk should initially generate at least full, half, and quarter
sample-density meshes from the same filtered elevation source. Exact grid
dimensions and switching distances are benchmark outputs, not fixed here.
Neighboring full-detail chunks share exact edge samples. The first mixed-LOD
experiment uses skirts; more exact edge stitching remains a later option.

## Elevation

Horizontal distances remain physically correct. Baseline elevation is
**1.0× source relief**. Profiles may request a visual experiment at **1.25×**;
values above **1.5×** require an explicit specification amendment and must not
apply to runway grading without separate treatment.

Chunks encode Y relative to a documented shared regional elevation origin,
not as unexamined absolute elevation above sea level. The compiler records the
source vertical datum, regional origin, exaggeration, quantization error, and
minimum/maximum physical and Pingo elevations. Ellipsoid height, orthometric
height, and model-world height are never treated as interchangeable.

## Floating local origin

Long-range simulation coordinates belong to the eZ80 application in an exact
domain wider than either Pingo translation packet. Pingo receives camera,
aircraft, and active scenery positions relative to a movable local origin.
Command 52 lets distant terrain objects remain relative to that origin beyond
the legacy two-kilometre radius, but it does not remove the need for rebasing:
the camera remains on legacy command 25, fixed-point flight integration and
chunk selection need a stable exact regional domain, and unnecessarily large
camera-relative distances worsen depth separation even when the packet can
represent them.

1. Recenter only in exact whole-chunk increments.
2. Rebase the camera, aircraft, all active terrain chunks, and every other
   world object together.
3. Publish the new absolute relative state only while no render is in flight.
4. Keep source/regional coordinates unchanged by a rebase.
5. Use integer or otherwise exactly specified regional arithmetic so repeated
   rebasing cannot accumulate visible drift or open seams.
6. Apply hysteresis so neither origin shifts nor LOD thresholds chatter.

The first static terrain qualification may omit rebasing. Any moving flight
fixture that can reach the local camera-coordinate boundary must implement it.
Wide object placement may reduce rebase frequency or retain selected distant
relief; it must not be used to send absolute projected source coordinates.

## Rendering and LOD policy

Whole-object AABB frustum rejection is the reason for chunking. Retained chunks
use distance-selected discrete LOD with hysteresis; chunks beyond the supported
terrain horizon are absent rather than submitted at full detail. A coarse
horizon belt may be generated separately to prevent a visible world edge.

Regional profiles may use command 53 to set the shortest far plane that
contains their selected horizon. The provisional Bay Area value is `8000`
internal units (64 km), compared with the legacy numeric `2500`-unit (20 km)
default. The candidate projection-matrix correction now genuinely clips at
that distance; old firmware retained the number but could not reject finite
geometry at its nominal far plane. Extending the far plane does not authorize filling that volume
with terrain; sparse LOD selection and whole-object culling remain mandatory.

The first implementation qualifies static LOD assignments before dynamic
switching. Rebinding an existing Pingo object ID to a preloaded mesh is a
candidate inferred from current firmware, not yet part of the public client
contract. It requires native and visual tests for transform preservation,
texture validity, allocation stability, and mutation only while rendering is
idle. If it fails those gates, the firmware design should add an explicit
visibility or mesh-selection operation rather than overloading scale or moving
unused objects arbitrarily far away.

## Shading and overlays

Annual NLCD semantic classes select the terrain color families. Pingo scene
lighting supplies the primary slope cue. Any deterministic color variation is
bounded and must not create frame-to-frame shimmer or obscure land-cover
meaning.

Baseline terrain uses Pingo flat-palette shading: each triangle's projected
footprint votes over covered NLCD pixel centers, deterministic ties select the
lowest class code, and a centroid lookup handles footprints containing no
pixel center. The winning semantic class maps to one canonical 8×8 Agon
palette cell, and all three encoded UV corners select that same cell. Thus the
rasterizer performs no perspective texture adjustment for baseline terrain.

Water, major roads, and runways are sparse separate meshes conformed to the
terrain or placed through one documented surface hierarchy. They are not
aerial-image textures. Runway pavement, markings, and terrain grading remain
physically consistent with the 8 m/unit world. Coplanar overlays and arbitrary
offsets that produce z-fighting are not acceptable.

## Initial qualification matrix

The first terrain benchmark compares:

1. a single-mesh control;
2. 512 m chunks at one static detail level; and
3. 512 m chunks using preselected full/half/quarter detail.

It records objects retained and frustum-rejected, submitted triangles,
renderer time, mesh and manifest bytes, Pingo-owned allocation/PSRAM use,
visible cracks, horizon stability, and low-altitude motion cues. Emulator
images establish deterministic correctness; physical Agon hardware remains
the performance and presentation ground truth.

Commands 52 and 53 currently exist only as experimental firmware work. Their
native userspace bridge, diagnostic, and sanitizer coverage passes, including
wide signed endpoints and legacy equivalence for command 52, and per-control
defaults, accepted endpoints, invalid/truncated preservation, renderer use,
and recreation reset for command 53. The functional renderer witness is clear
at 2,500 units and visible at 8,000 for geometry around 3,128 units away. The
current `esp32dev` firmware build
passes at 44,768 bytes RAM and 1,121,389 bytes flash. They are not yet a
promoted public client contract. A candidate must still pass explicit human
emulator visual qualification and physical-hardware range, depth, and
presentation qualification before this design may depend on them outside
experimental fixtures.
