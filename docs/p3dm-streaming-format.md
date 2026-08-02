# P3DM terrain-streaming format

Status: **provisional implemented format**, AGNB version 0.3, P3DM layout 1.
The Python writer/parser and corruption tests live in
`src/pingo_terrain/p3dm.py` and `tests/test_p3dm.py`. The VDP import command is
experimental until emulator and hardware qualification.

## File granularity and paths

Each file contains exactly one independently loadable terrain, airport, or
landmark component. A regional mega-container is deliberately excluded: one
component per file permits an exact FatFS open/read/close operation with no
directory scan or unimplemented AGNB seek/skip dependency.

Runtime paths use 8.3-safe deterministic components:

```text
WORLD.PTI
TRN/L0/HH/LL.AGN       terrain tile, id = tile_y * columns + tile_x
APT/KOAK/Pnn.AGN       airport pavement component/group
APT/KOAK/Mnn.AGN       paired airport marking component/group
LMK/...                later landmark component
```

The regional index pins the UTM origin, lattice/chunk dimensions, component
availability, exact file sizes and hashes, and airport activation circles.
Terrain, airport, and landmark slots are separate pools. Terrain eviction can
therefore never make a nearby airport disappear.

The Bay Area proof uses integer horizontal origin E 521,728 m, N 4,100,096 m
in EPSG:32610 and a shared 608.0 m vertical model origin. `model_half_extent_m`
is the exact uniform normalization witness: every signed position decodes as
`component_origin + raw * model_half_extent_m / 32767`. The index supplies the
component origin and exact Q8.8 object scale. A component whose required
integer half extent exceeds 2,047 m must be spatially partitioned; it may not
overflow Pingo's unsigned object-scale packet.

## RIFF/AGNB envelope

All integers are little-endian. Every RIFF chunk has an eight-byte FourCC/u32
header and zero padding through the next four-byte boundary; its declared size
excludes the header and padding.

```text
RIFF <u32 file_size_minus_8> AGNB
  VERS size=2
    u8 major = 0
    u8 minor = 3
  LIST type=BUFR
    BHDR size=2
      u16 fixed_staging_buffer_id       # 0xffff is forbidden
    P3DM size=36
      u8  layout_version = 1
      u8  layer_kind                    # 0 terrain, 1 pavement,
                                        # 2 marking, 3 landmark
      u8  lod
      u8  shading_mode                  # 1 solid-flat, 2 flat-pattern
      u8  illumination                  # 0 scene, 1 self
      u8  material_set                  # 0 terrain selector, 1 solid palette
      i16 tile_x
      i16 tile_y
      i32 center_east_m                 # relative to regional UTM origin
      i32 center_north_m                # relative to regional UTM origin
      i16 minimum_elevation_dm          # NAVD88
      i16 maximum_elevation_dm          # NAVD88
      u16 model_half_extent_m            # padded normalization witness
      u16 vertex_count V
      u16 position_index_count I
      u16 uv_count U
      u16 uv_index_count T
      u32 data_crc32
    DATA size = 6V + 2I + 4U + 2T
      i16 positions[3V]
      u16 position_indices[I]
      u16 uvs[2U]
      u16 uv_indices[T]
```

The reader requires exactly `VERS`, then one `LIST BUFR` containing exactly
`BHDR`, `P3DM`, and `DATA` in that order. RIFF/file equality, every nested
boundary, zero padding, descriptor size, exact DATA size, CRC32, counts,
indices, and rendering policy are validated before publication.

`I` is at least three and divisible by three; `T` equals `I`; all indices are
in range. Every triangle repeats one UV selector index three times. P3DM is a
flat-face format and cannot silently turn into an interpolated texture path.

## Enforced layer policy

The loader rejects, rather than obeys, a component whose descriptor violates
the accepted aesthetic/performance policy:

| Layer | Shading | Illumination | Material set |
| --- | --- | --- | --- |
| terrain | mode 2 flat-pattern | scene | 4×4 terrain selector |
| airport pavement | mode 1 solid-flat | self | native solid palette |
| airport marking | mode 1 solid-flat | self | native solid palette |
| airport structure | mode 2 flat-pattern | self | fixed sparse gray pattern |
| landmark | mode 1 solid-flat initially | scene or explicit self | native solid palette |

Airport property surfaces and markings are thus outside the terrain dither
lookup by construction. The stitched corpus partitions terrain, airport base,
pavement, and markings into mutually exclusive faces; it does not use a
coplanar or slightly raised overlay.

The native solid-palette material set uses an 8x8 raw opaque color cube in
row-major six-bit color order (`pixel = 0xC0 | selector`). Runway/taxiway
pavement selects dark-gray cell 21/`0xD5`; source-identified ramps/aprons select
light-gray cell 42/`0xEA`; residual airport-property ground selects muted-green
cell 25/`0xD9`; and all markings select pure-white cell 63/`0xFF`. Every group
keeps the pavement and markings for a runway together, and startup waits for
the complete replacement patch before activating an airport scene. Terminal
structures remain outside this ground material contract. A mapping-derived
airport structure instead uses a fixed 4×4 pattern containing thirteen
dark-gray `0xD5` pixels and three nonadjacent light-gray `0xEA` pixels. It has
one self-illuminated band, deterministic phase, and no illumination-dependent
density change.

## Runtime publication contract

This section defines the component and publication mechanisms used by the
authoritative terrain manager specified in `docs/terrain-scene-design.md`.
P3DM/AGNB loading is not itself a complete terrain manager. Fixture-local
coordinators currently demonstrate loose-file, airport-pair, and family-LOD
cases, but they must converge on that single manager rather than becoming
parallel public interfaces.

The eZ80 loader has one read request and bounded fixed slot pools. It reads and
CRC-validates one complete component into RAM while a render may be in flight.
It publishes only after the `P3DR` completion barrier:

```text
IDLE -> READING -> READY -> VDP upload/consolidate -> atomic mesh replace
     -> transform/activate stable object slot -> next render -> IDLE
```

Publication uses experimental Pingo subcommand 50. The command converts and
validates the complete consolidated DATA block into private mesh arrays, then
swaps all four arrays together. Missing input, malformed counts, invalid
indices, truncation, or any allocation failure leaves the resident mesh
unchanged. The generic staging buffer is not the mesh's lifetime owner.

Objects remain bound to stable mesh-map entries. Slot reuse therefore needs no
object delete or rebind. An object-active command skips empty slots; the KOAK
28L start preloads required pavement and marking slots before its first render.

At most one component is published per foreground service pass. An I/O or
upload failure retains the old resident component and records a retry/backoff
reason. The current and predicted next-path terrain cells are never eviction
victims.

### Floating-origin publication

The world index uses an integer 512-metre grid. Horizontal aircraft state is a
coarse cell plus fine east/north Q8 translation counts from that cell centre;
the fine interval is `[-256 m,+256 m)`. A cell crossing rebases by exactly
8192 rendered translation counts without changing reconstructed UTM position.

For a component whose P3DM centre is relative to the regional UTM origin, the
runtime transform is computed in metres before conversion to the signed Pingo
packet:

```text
coarse_east  = coarse_tile_x * 512 + 256
coarse_north = coarse_tile_y * 512 + 256
object_x     = round((center_north - coarse_north) * 16)
object_z     = round((coarse_east - center_east) * 16)
```

Regular terrain centres make these simply `(tile_y-coarse_y)*8192` and
`-(tile_x-coarse_x)*8192`. Airport and landmark centres use their descriptor's
explicit offsets. All active component transforms are reissued after a coarse
cell change. With the shared 608-metre vertical mesh origin, terrain and
airport object Y is 9728 counts; camera Y is absolute MSL-like altitude in the
same 1/16-metre packet domain. The FAA-versus-NAVD88 datum distinction remains
recorded rather than silently equated.

`src/pingo_terrain/streaming.py` is currently the executable host reference for
coordinate round trips, rebase continuity, deterministic path generation,
one-load-per-pass slot publication, abort retention, look-ahead ordering, and
the 32-object scene budget. Its proven behavior is input to the common eZ80
manager; it is not authorization for each fixture to translate the reference
independently.

The initial 25-slot eZ80 implementation may use a direct-mapped toroidal ring
instead of a general victim search:

```text
slot = (tile_y mod 5) * 5 + (tile_x mod 5)
```

Every tile in one complete radius-two 5x5 neighborhood has a distinct residue
pair, so the mapping is collision-free for the desired set. The caller scans
the already priority-sorted desired tiles and transactionally replaces the
first mismatched slot; after all desired tiles are resident it deactivates one
obsolete edge slot per pass. `DirectMappedTerrainRing` tests injection,
one-operation publication, failure retention, five-slot edge replacement, and
world-edge deactivation.

## Initial budget

The 32 Berkeley triangular chunks measure 83–85 vertices and 381–405 indices.
Their P3DM DATA payloads are 2,086–2,194 bytes, mean 2,122 bytes. The UART-only
floor for the mean block at 1.152 Mbaud 8N1 is about 18.4 ms. Plan for a 20–35
ms publication stall until hardware measurement. A 512 m tile gives roughly
8.5 seconds of notice at 60 m/s, so early velocity/view look-ahead matters more
than an elaborate VDP cache.
