# Regional Bay Area light-flight design

Status: **working specification**. Decisions and measurements are updated as
the regional data, streaming, airport, cockpit, and flight-model experiments
progress.

## Outcome

Build an Agon-side light-flight fixture over a recognizable Bay Area world.
The world spans Suisun Bay through Morgan Hill and the Pacific coast through
terrain east of Mount Diablo. It should support both an exterior aircraft view
and a reduced-viewport 2D cockpit while loading modest terrain containers from
SD according to aircraft position.

This is not a promise of geographic or aerodynamic simulation fidelity. Its
acceptance test is whether the landscape, airports, aircraft response, and
instruments give a convincing and stable sense of flight within measured eZ80,
UART, VDP, and renderer budgets.

## Feature order

1. Qualify flat-pattern rendering on the existing Berkeley fixture.
2. Acquire and manifest regional DEM and categorical land-cover tiles.
3. Establish an indexed mesh-container format and position-driven loader.
4. Add essential airports: KSFO and KOAK.
5. Make KOAK runway 28L the canonical cockpit start.
6. Add secondary airports: KHWD, KSQL, and KCCR.
7. Add the cockpit layout and a deterministic force/inertia flight model.
8. Import selected reusable landmark models only after airport navigation is
   recognizable and stable.

## Regional terrain

The source acquisition must use one documented projected metric grid and
record horizontal CRS, vertical datum, nodata handling, source requests,
timestamps, byte sizes, and SHA-256 checksums. The exact WGS84 acquisition
bounds will be fixed in the regional manifest after authoritative service
queries. They must contain Mount Tamalpais, Yerba Buena and Treasure Islands,
the Bay shoreline, East Bay hills, Mount Diablo plus terrain east of its
summit, Suisun Bay, and Morgan Hill, with enough Pacific water to make the
coast visually legible.

Runtime terrain remains a continuous triangular lattice divided into modest
containers. Adjacent chunks share source samples and one global lattice phase.
Container boundaries must not trigger per-mesh normalization or pattern-phase
seams. A regional integer chunk coordinate plus a floating Pingo origin keeps
eZ80 and protocol values small.

### Horizontal floating origin

Pingo's legacy object command 17 and camera command 25 encode each translation
component as a signed little-endian 16-bit value. Under the accepted 8-metre
Pingo world unit, one raw count is approximately 1/16 metre and the complete
legacy horizontal window is only about four kilometres. Experimental command
52 widens object XYZ to signed 24-bit values in the identical raw unit, but it
does not widen camera or scene translation. Absolute UTM coordinates therefore
never enter either kind of packet.

The regional grid is aligned to 512-metre cells. Aircraft horizontal state is
split into a coarse `(tile_x,tile_y)` and fine east/north offsets from that
cell's centre. Fine position uses the flight model's Q8 translation-count
domain and is normalized to `[-256 m,+256 m)`. One whole cell is exactly 8192
rendered translation counts or `0x200000` position-Q8 units, so the eZ80 rebase
requires only add/subtract and carry logic.

Pingo axes remain X=north and Z=-east. Between rebases the camera receives the
fine position while resident terrain centres are fixed relative to the coarse
cell:

```text
camera_x = fine_north_q8 >> 8
camera_z = -fine_east_q8 >> 8
terrain_x = (terrain_tile_y - coarse_tile_y) * 8192
terrain_z = -(terrain_tile_x - coarse_tile_x) * 8192
```

Crossing a cell boundary changes the coarse coordinate and subtracts exactly
one cell from the corresponding fine coordinate. Velocity, attitude, altitude,
and reconstructed absolute position do not jump. Every resident object is then
reissued once relative to the new coarse centre. A radius-two 5x5 terrain set
has centre translations no larger than 16384 counts and stays comfortably in
the packet range.

The vertical axis does not need this rebase for the current Bay Area envelope.
Terrain and airport vertices share the 608-metre vertical normalization origin;
their object Y translation is `608*16 = 9728` counts, while camera Y remains
absolute altitude in the same 1/16-metre count domain. This keeps surveyed OAK
near zero altitude without losing the signed relief around the shared mesh
origin.

### Distant objects and projection

The regional hierarchy may place selected transition and distant objects
beyond command 17's roughly two-kilometre radius with experimental command 52:

```text
VDU 23,0,0xA0,sid:u16,0x49,52,oid:u16,x:s24le,y:s24le,z:s24le
```

The native conversion remains `signed_raw * (256 / 32767)` Pingo units, so a
sign-extended command-17 value is exactly equivalent. Signed-s24 covers
approximately -524 km through +524 km at terrain scale. The object must
already exist; XYZ commits atomically, while an absent object or truncated
packet preserves the prior state. Aircraft-local terrain can continue using
command 17. Command 52 is for the sparse regional LOD set that genuinely needs
the wider placement and is not a substitute for the floating-origin rules.

Each Pingo control keeps the fixed one-unit near plane and defaults to the
legacy `2500`-unit (20 km) far plane. Experimental command 53 sets a per-control
unsigned world-unit far distance:

```text
VDU 23,0,0xA0,sid:u16,0x49,53,far_units:u16le
```

Accepted distances are `2..65535`; zero, one, or a truncated word preserves
the current setting, and recreating a control restores `2500`. The provisional
regional fixture value is `8000` units (64 km). It should be reduced if a
profile's selected horizon is shorter, because a larger far/near ratio reduces
depth separation. A longer projection never authorizes loading every terrain
family inside it: the scene still admits only 32 active renderables and relies
on sparse view/relief-selected LOD.

The same firmware candidate corrects the old projection coefficients. With a
one-unit near distance, the previous matrix made homogeneous `Z+W` constant
and therefore never rejected finite geometry at the retained far value. The
corrected mapping enforces both boundaries, so the unchanged numeric `2500`
default is now a real 20 km clip rather than bit-exact legacy behavior.

Floating origin remains mandatory for sustained flight even though object
placement is wider. The eZ80 needs exact, drift-free regional arithmetic for
physics, streaming, seams, and collision; command 25 still constrains the
camera; and local camera-relative distances give better depth behavior than
large representable values. Rebase in exact whole-cell increments and use
command 52 only after converting the selected object's regional position to
that current local origin.

Both experimental commands pass the current native userspace bridge,
diagnostic, ASAN, and UBSAN coverage. Command 52's evidence includes signed
endpoints, legacy equivalence, all matrix axes, absent-object handling, and
truncation. Command 53's evidence includes per-control isolation and defaults,
accepted endpoints, invalid/truncated preservation, renderer use, and
recreation reset. The current embedded `esp32dev` firmware also builds at
44,768 bytes RAM and 1,121,389 bytes flash. They remain unpromoted pending
explicit human emulator visual qualification and physical-hardware range,
depth, and presentation qualification.

## Disk streaming

The loader maintains a bounded neighborhood around the aircraft rather than
uploading the region at startup. Its durable contract will be informed by the
AGNB container implementation, but must include:

- a small versioned header and explicit byte counts;
- regional chunk coordinates, local origin, bounds, and LOD;
- vertex, position-index, UV/material-selector, and UV-index sections;
- checksums or other corruption detection before publication;
- deterministic filenames or an index that does not require directory scans;
- transactional load into a free runtime slot, then Pingo mesh/object publish;
- removal/reuse only while no render can observe a partial slot; and
- emulator-visible aircraft chunk, desired set, resident slots, I/O time,
  upload time, and failure reason.

The first policy should be deliberately small: retain the nearest visible
neighborhood, load at most one missing chunk per simulation service pass, and
evict the farthest undesired slot. No elaborate VDP cache is justified until
measured file and UART costs show that a simple slot ring is insufficient.

The initial fixture budget remains explicit even though the Pingo VDU bridge no
longer has a fixed active-object ceiling. The existing 25-slot terrain
neighborhood, six airport components, and one aircraft are a qualified working
set, not a firmware maximum. Larger terrain rings, landmarks, or unusually
partitioned airports require measured registry memory, traversal, culling, and
real-hardware frame time before the manager raises those pools. Inactive stable
slots do not incur renderer traversal.

## Airports

Priority order is KSFO, KOAK, then KHWD, KSQL, and KCCR. Airport generation is
data-driven and separate from terrain generation. Each airport record should
pin identifiers, reference point, field elevation, runway endpoints/heading,
length, width, and source/version.

KOAK runway 28L is the canonical initial condition. The startup transform must
derive from the pinned runway threshold and centerline: never encode a guessed
coordinate or heading. The default cockpit view looks along the runway, with a
small above-surface clearance if the first collision model cannot yet support
wheel contact. An exterior view is still required for the aircraft model.

The first visual layer includes runway pavement polygons plus restrained
threshold, centerline, and edge cues that survive at 320-pixel-class viewport
resolution. Taxiways and aprons are optional second-pass geometry. Each pinned
airport property is a terrain-replacement patch: its projected outline cuts the
regional terrain, shares a conforming boundary triangulation with it, and owns
the elevation and semantic surface inside. Airport base, pavement, and marking
polygons are mutually exclusive face partitions. Small-offset and coplanar
overlays are rejected because they produce z-fighting and can disagree with
collision or runway support.

Airport hard surfaces are an explicit exception to patterned terrain. Pavement
and markings begin in Pingo solid-flat shading mode 1 with self illumination,
using pure white markings (`0xFF`), dark-gray runway/taxiway pavement (`0xD5`),
light-gray source-identified ramps/aprons (`0xEA`), and muted-green residual
airport ground (`0xD9`). They do not enter the terrain dither lookup and do not
vary with the scene sun. This is the accepted baseline because the airports
must stand out at flight distance. A later lit or dithered airport treatment is
an optional comparison, not a prerequisite.

Terminal and other airport structures are a separate simplified provider, not
another ground color. Mapping-derived footprints may produce wall-and-roof
meshes when their airport-building classification is attributable; mapped
height or levels determine height before a pinned conservative default. No
footprint means no invented building, and a footprint alone does not authorize
gates, roof furniture, or facade detail.

The first structure material is a fixed self-lit 4×4 pattern of thirteen dark
gray `0xD5` pixels and three nonadjacent light gray `0xEA` pixels. This sparse
dither reads as a quiet intermediate gray and does not change with scene
illumination. Structures omit coplanar bottom faces and conform their bases to
the airport property surface retained beneath them.

## Cockpit and flight dynamics

The vendored `assets/cockpit/fsimpanel.png` is the authored source for a 2D
panel. The 3D target should shrink to the unobscured upper viewport instead of
rendering full-screen pixels that the panel immediately covers. Exterior view
remains available so the existing aircraft models are not wasted. The exact
vendored Jet, Q8.8 physical scale, cockpit/chase local offsets, P3D look-at
policy, V-key edge latch, fallback-horizon source, and 27/28-object budget are
fixed in `docs/aircraft-exterior-view.md`.

The eZ80 flight state uses explicit fixed-point vectors:

```text
forces -> acceleration -> velocity -> world position
controls + stability -> angular acceleration -> angular velocity -> attitude
```

The first model needs thrust, gravity, lift, drag, and simple pitch/roll/yaw
control moments. It should reuse qualified fixed-point, vector, matrix, and
sine/cosine routines from PingoASM rather than introduce an unrelated math
stack. Every integration step is fixed-duration, bounded, and deterministic.
Ground collision may initially clamp to a conservative regional height query;
aerodynamic stalls, winds, and landing-gear dynamics are later refinements.

Panel instruments should be derived from the same state: airspeed, altitude,
vertical speed, heading, bank/pitch attitude, and throttle. Instrument updates
may run more slowly than the simulation and render cadence.

## Landmark-model pipeline

Landmarks follow airports. Candidate models must have recorded source and
redistribution terms. Offline processing will:

1. establish geographic placement and a stable physical scale;
2. remove invisible/interior detail and decimate to a silhouette budget;
3. triangulate deterministically;
4. analyze existing material names or texture coverage to assign a small
   authored face-color vocabulary;
5. remove runtime image-texture dependence;
6. partition or bind the model to the regional container index; and
7. validate winding, bounds, index ranges, colors, and rendered recognition.

Landmarks that cannot remain recognizable after simplification and flat
shading should not consume runtime slots merely because a detailed source model
exists.

## Qualification evidence

Record exact data and executable hashes, container and resident byte counts,
per-chunk MOS load and VDU upload time, streaming decisions, render diagnostics,
deterministic target hashes/screenshots, flight-state traces, and physical
hardware cadence. Keep malformed/truncated container tests and forced I/O
failure tests separate from visual acceptance.
