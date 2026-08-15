# Regional LOD family bundles

Status: **executable host prototype with experimental firmware support; not
yet an eZ80 or promoted firmware contract**. The implementation and focused
tests are `src/pingo_terrain/regional_lod.py` and
`tests/test_regional_lod.py`. They do not alter the proven 512 m compiler or
the active KOAK fixture.

**Superseding status, later on 2026-08-02:** the host prototype now has a
separate live eZ80 integration fixture for one fixed westbound transition. The
opening status and later promotion checklist are retained as the chronology
that led to it; see [Live fixed-west integration](#live-fixed-west-integration)
for what is now proved and what remains open.

## Recommendation

Package the complete aligned world as 3,213 four-by-four-cell terrain
families. Each family is one ordinary multi-record AGNB 0.3 file covering up
to 2,048 by 2,048 metres. It contains:

| Tier | Records in a full family | Footprint per record | Lattice | Use |
| --- | ---: | ---: | ---: | --- |
| near | 8 | 1,024 × 512 m | L0, 68.77 m | current family only |
| transition | 1 | 2,048 × 2,048 m | L1, 137.54 m | eight immediate neighbors |
| distant | 1 | 2,048 × 2,048 m | L2, 275.09 m | sparse view/relief-selected terrain |

The near strips retain the current 16 KiB staging ceiling while halving the
active objects required to cover a complete 2 km family. The L1 ring prevents
an L0/L2 jump at the current-family boundary. Distant L2 objects are selected
for projected importance rather than trying to carpet every square kilometre
inside the far plane. Unselected terrain degrades to the existing
attitude-derived neutral-ground backdrop.

This is a better first regional hierarchy than storing three versions of all
50,652 cells. It preserves exact near terrain everywhere, retains a bounded
transactional load, and gives whole-object frustum culling useful component
sizes at every tier.

## Grid and 8.3 identity

The 201 by 252 base grid groups into 51 by 63 families:

```text
super_x = tile_x / 4
super_y = tile_y / 4
super_id = super_y * 51 + super_x
path = RGN/{super_id >> 8:02X}/{super_id & 255:02X}.AGN
```

KOAK base cell `(94,146)` belongs to supertile `(23,36)`, ID `0x0743`, at
`RGN/07/43.AGN`. The easternmost base column does not disappear merely because
201 is not divisible by four. Its 63 residual families are 512 by 2,048 m and
contain four near strips plus D1 and D2 records. The last family is
`RGN/0C/8C.AGN`.

P3DM `tile_x` and `tile_y` are the component rectangle's southwest base-cell
coordinate. The explicit P3DM centre remains the authoritative object origin.
A regional loader must not infer a 512 m footprint merely from those two
fields.

## AGNB layout and selected-record loading

No new archive format is necessary. AGNB already permits multiple
`LIST BUFR` records, so one family is:

```text
RIFF AGNB
  VERS 0,3
  LIST BUFR  BHDR P3DM DATA     # D2; first because distant opens are common
  LIST BUFR  BHDR P3DM DATA     # D1
  LIST BUFR  BHDR P3DM DATA     # N00
  ...                            # N01 through N07
```

Each nested record is byte-for-byte the existing BHDR/P3DM/DATA contract and
retains its own exact DATA length and CRC32. All records may name the same
generic VDP staging buffer because only one publication is in progress. The
host parser reconstructs and validates each record with the existing P3DM
parser; corruption cannot turn one nested payload into a trusted mesh.

The eZ80 must not read a roughly 90 KiB family into RAM. It should:

1. open the deterministic family path and validate RIFF, AGNB, VERS, and the
   enclosing file boundary;
2. scan `LIST BUFR` headers and their fixed P3DM descriptors, seeking over
   unmatched DATA chunks;
3. cache the ten LIST offsets while the current family remains relevant;
4. seek to the selected record, validate its fixed descriptor, read and CRC
   only that DATA into the existing staging window; and
5. retain the current transactional command-50 publication barrier.

Ten cached u24 LIST offsets and lengths need only 60 bytes. A missing or bad
record leaves the old stable slot active exactly as the loose-file loader does.
The family order makes a D2 or D1 request discoverable before any near DATA.

**Implemented-loader note:** steps 1, 2, 4, and 5 above are now exercised on
the eZ80. The bounded loader scans each 76-byte LIST prefix, matches the
complete requested descriptor identity, validates every sibling boundary and
pad, re-reads the sole match, and seeks only its aligned DATA into the existing
staging window. It reconstructs a one-record AGNB view and delegates exact
policy/count/index/CRC checks plus command-50 publication to the proven P3DM
path. It currently scans on every request; the proposed 60-byte offset cache is
an optional measured optimization, not part of the correctness proof.

## Scene allocation and transition

The executable reference uses this steady-state allocation:

| Active object class | Normal count | Worst airport-area count |
| --- | ---: | ---: |
| current-family L0 strips | 8 | 8 |
| neighboring-family D1 ring | 8 | 8 |
| view/relief-selected D2 | 8 | 8 |
| airport hard surfaces | 2 | 6 |
| aircraft | 1 | 1 |
| optional landmark | 0 | 1 |
| **total** | **27** | **32** |

Inactive preload objects do not enter Pingo's 32-renderable scene. Two banks
of eight near slots allow a complete next family to be read before crossing a
2 km boundary. At the render-idle barrier, the client deactivates the next
family's D1 object and activates its eight L0 strips, deactivates the old eight
L0 strips and activates the old family's D1 object, then repairs the sparse D2
set before submitting another frame. No submitted frame should contain both
coincident representations.

At 60 m/s, one 2,048 m family takes 34.13 seconds to cross. Eight mean near
uploads have a combined UART-only floor of 593 ms, so even a conservative
one-family lookahead has ample margin. Publication remains limited to one
component per foreground pass; no simulation tick is required to absorb an
entire family.

The D2 selector is deliberately sparse. It first favors the forward view and
then uses only precomputed numerical relief, horizon-envelope, projected-error,
and categorical-boundary metadata defined by
`docs/distant-terrain-mathematical-lod.md`. A named feature such as Mount
Diablo is a human review witness, never selector input. A D2 island terminates
in a skirt over the neutral backdrop; it is not allowed to touch L0 directly.

## Lattice and seam policy

All three tiers use the existing regional lattice origin and exact projected-
micrometre clipping. The new rectangular topology code changes only the clip
rectangle; heights are still sampled at vertices and materials still come
from predominant NLCD categories per face.

The accepted seam rules remain:

1. equal-LOD neighbors share exact boundary planes and samples;
2. rendered adjacent terrain differs by at most one lattice LOD;
3. every component owns an outward 64 m downward skirt in its boundary face's
   material; and
4. a family swap is activation-atomic at the next render barrier.

Nested lattice points do not make every independently clipped cross-LOD edge
intersection identical. Skirts remain necessary. The 64 m depth is still a
provisional aesthetic bound: a full build must measure L0/L1 and L1/L2 edge
error in the Mount Diablo relief and deepen the skirt, within the component's
normalization floor, if the measured error plus quantization margin exceeds
64 m.

Near strips retain the proven 768 m uniform half extent and Q8.8 object scale
24,576. Full D1/D2 supertiles use a 1,024 m uniform half extent and scale
32,768. That encloses the 2,048 m horizontal footprint and all pinned vertical
relief while remaining below the loader's 2,047 m half-extent limit.

## Exact corpus and UART budget

The topology-only budget traverses every family and is exact for P3DM counts,
DATA sizes, RIFF padding, and bundle bytes; it does not estimate from the KOAK
sample.

| Tier | Records | DATA bytes | Mean DATA | Maximum DATA | Mean UART floor | Maximum UART floor |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| near L0 strips | 25,452 | 217,347,792 | 8,539.52 | 8,986 | 74.13 ms | 78.00 ms |
| transition D1 | 3,213 | 44,615,952 | 13,886.07 | 14,572 | 120.54 ms | 126.49 ms |
| distant D2 | 3,213 | 16,597,020 | 5,165.58 | 5,440 | 44.84 ms | 47.22 ms |
| **total** | **31,878** | **278,560,764** | — | — | — | — |

All selected records fit the existing 16,384-byte staging window. Complete
multi-record files total 281,094,152 bytes (268.07 MiB). Compared with the
three-loose-LOD proposal's 151,956 files and 450,781,012 bytes, this reduces
file count by 97.89%, selectable record count by 79.02%, and bytes by 37.64%.
It costs only 4.15% more bytes than storing loose L0 alone while also providing
the complete L1 transition and L2 distant layers.

The file-count reduction matters even more on an SD card with large FAT
clusters. The loose corpus would allocate at least 4,979,294,208 bytes if each
small file occupies one 32 KiB cluster. Family sizes are 29,804 through 90,452
bytes. The bundled corpus allocates 286,846,976 bytes with 4 KiB clusters or
311,721,984 bytes with 32 KiB clusters. The target card's actual cluster size
should still be recorded before deployment.

## Real pinned-raster proof

The module built supertile `(23,36)` directly from the checksum-verified 42
USGS 3DEP and nine NLCD source tiles. Two independent runs produced the same
90,136-byte `RGN/07/43.AGN` with SHA-256
`64a674261e6baad3507145824699ef363463b94c94dc716eccbd76ef728765f7`.
It has ten round-tripped records; D2 is 5,314 DATA bytes, D1 is 14,572, and the
eight near records are 8,248 through 8,890 bytes. The ignored proof lives under
`/tmp/pingo-terrain-regional-lod-proof-verified`, not in an active fixture.

Commands:

```text
.venv/bin/python -m pingo_terrain.regional_lod budget
.venv/bin/python -m pingo_terrain.regional_lod proof \
  --project-root /home/smith/Agon/mystuff/pingoasm/apps/fsim \
  --output-root /tmp/pingo-terrain-regional-lod-proof-verified
```

## Experimental Pingo range extensions

The hierarchy uncovers two firmware boundaries that the 512 m proof does not.
Legacy object command 17 encodes each translation component as a signed
little-endian 16-bit raw value. Its conversion is:

```text
Pingo translation = signed_raw * (256.0 / 32767.0)
```

The resulting object-origin radius is only about 2,048 m at the accepted
eight-metres-per-unit terrain scale. Even the positive-side centre of an
immediate 2 km neighbor requires raw count `+32768`, one beyond the signed-word
maximum. More important, KOAK to Mount Diablo is about 31.2 km.

Experimental command 52 is now implemented for wide object placement:

```text
VDU 23,0,0xA0,sid:u16,0x49,52,oid:u16,x:s24le,y:s24le,z:s24le
```

Each coordinate is signed two's-complement little-endian and uses exactly the
same raw unit as command 17. Sign-extending a legacy word therefore produces
the same native transform. The s24 range is -8,388,608 through +8,388,607,
approximately -524 km through +524 km at terrain scale. All three axes update
atomically on an existing object; an absent object or truncated packet
preserves accepted scene state. The command is deliberately object-only. The
camera remains local and continues to use legacy signed-word command 25; no
wide camera or scene command exists without a demonstrated caller.

The second boundary is projection. Every Pingo control retains a fixed
one-unit near plane and defaults to the legacy 2,500-unit far plane, or 20 km
at terrain scale. Experimental command 53 changes only the addressed control:

```text
VDU 23,0,0xA0,sid:u16,0x49,53,far_units:u16le
```

`far_units` is a direct distance in Pingo world units, not a translation raw
count. Values `2..65535` are accepted; zero, one, or a truncated word preserves
the prior value. A recreated control returns to `2500`. The provisional Bay
Area setting is `8000` units (64 km), enough to retain selected Mount Diablo
relief from KOAK. The protocol maximum is about 524 km at terrain scale, but
the shortest useful far distance should be chosen because increasing the
far/near ratio reduces depth separation even with Pingo's 32-bit depth buffer.

This candidate also repairs the perspective matrix: the old near-one form made
`Z+W` identically one, so no finite point could cross the nominal far plane.
The numeric default remains `2500`, but corrected firmware now enforces it and
therefore changes rendering for legacy geometry farther than 20 km.

Wide placement complements rather than replaces the floating origin. Flight
state and source coordinates remain in the eZ80's exact regional domain, the
camera still has the legacy local range, chunk arithmetic and seams must not
accumulate rebase error, and a far-reaching packet is no reason to render or
depth-test the complete region. Command 52 lets a sparse set of distant
objects coexist with local camera/aircraft state; command 53 merely makes the
selected horizon projectable.

Current native evidence covers signed-s24 endpoints, command-17 equivalence,
all three matrix axes, absent-object and truncation behavior, and diagnostic
raw witnesses for command 52. Command 53 has native coverage for per-control
isolation, the `2500` default, both accepted endpoints, invalid and truncated
preservation, renderer use, diagnostics, teardown, and recreation. The normal
userspace, diagnostic, ASAN, and UBSAN test paths pass. This is implementation
evidence, not promotion. The current `esp32dev` build also passes at 44,768
bytes RAM and 1,121,389 bytes flash. Explicit human emulator visual
qualification and physical-hardware range/depth qualification remain required.

## Promotion boundary

The next regional runtime can adopt this format after four independent gates:

1. experimental commands 52 and 53 pass explicit human emulator qualification
   and physical-hardware range and depth qualification; the completed native,
   sanitizer, and embedded-build evidence does not waive those gates;
2. the eZ80 loader selects one nested LIST without reading the complete bundle
   and retains transactional failure behavior;
3. the current-family activation swap shows no overlap, hole, or stale object
   in a diagnostic trace; and
4. Mount Diablo mixed-LOD seams and distant relief pass visual review.

Until then, the loose KOAK corpus remains the integration oracle and this
prototype remains an alternative whole-region packaging design.

## Live fixed-west integration

The sibling `fixtures/koak-flight-family-lod` fixture now closes the earlier
loader/activation integration gap for one deliberately fixed route. Its
generated plan covers the natural `(23,36)` to `(22,36)` westbound handoff with
20 ten-record family files and 37 stable terrain slots:

| Load phase | Slots | Initially active |
| --- | --- | ---: |
| current-family L0 | `1..8` | 8 |
| current-plan D1 | `17..24` | 8 |
| current-plan D2 | `29..36` | 8 |
| next-family L0 bank | `9..16` | 0 |
| next-plan D1/D2 delta | `25..28,37` | 0 |

The first eight L0 records and KOAK hard surfaces form the first-frame barrier.
Thereafter, one ordinary render-idle pass selects, validates, uploads, and
publishes at most one nested family record. Only a successful publication
advances the generated plan cursor; inactive next-bank objects are positioned
and rebased while remaining outside the active-renderable budget. Once all 37
are resident, the west-boundary service deactivates 13 outgoing objects and
then activates 13 resident replacements without disk I/O before the next render
is submitted. Both plans contain 24 active terrain objects.

The canonical natural-flight trace is retained at
`/tmp/pingo-koak-family-transition-20260802-f-placement-validated`. It used
fixture binary SHA-256
`fa41b2adca0da781441d6ded66e4460e68d713b9d38869d57376581956714cbb`
and reached the later debugger snapshot at coarse cell `[91,148]` with cursor
`37/37`, no error, swap complete, and the exact next-plan set of 24 terrain
slots. All 37 terrain meshes and both airport meshes published exactly once;
the largest VDP publication record was 57 microseconds. The exact 26 command-51
changes form one contiguous group between consecutive completed renders 1192
and 1193, with no interleaved render or mesh publication.

Compile-gated `PINGO_POSE` diagnostics bind aircraft and camera state to those
two renders. Both receive `[7,11,-8173]` raw counts across the cell wrap and
retain the chase offset `[-107,37,-277]`, so the large local-coordinate change
is a coherent floating-origin rebase rather than a camera teleport. The report
SHA-256 is
`877114ade487803fc9565537c0c744ed5e6b03f520af7d7e79ee82a1b5a429d3`.

The v2 report also proves placement rather than inferring it from activation.
Exactly 37 command-52 records occur in generated slot order before the swap;
every raw translation and generated centre reconstructs coarse cell `[91,147]`,
coarse centre `[749568,1208320]`, and terrain Y `9728`. The later debugger
snapshot at `[91,148]` occurs after the fixed west handoff; this fixture claims
no following north-family handoff.

This supersedes promotion items 2 and 3 above at the automated fixed-route
implementation level. It does not waive their broader generalization or human
gates. Independent inspection found the two bracketing frames coherent and
nonblank, but their different hashes and coverage are expected and do not prove
an invisible handoff. The current remaining gates are:

1. human emulator review of L0/L1/L2 seams, silhouettes, and visible pop,
   including high-relief Mount Diablo cases;
2. physical-hardware range, depth, SD throughput, and sustained frame-rate
   qualification for experimental commands 52 and 53 and the combined scene;
3. complete seek/read/validate/upload latency measurements on representative
   SD media—the 57-microsecond diagnostic is only VDP publication time;
4. rolling plan generation, slot reuse, and preload timing for arbitrary
   cardinal/diagonal transitions rather than one pinned westward pair; and
5. an integrated injected-read/CRC failure proof that preserves the visible
   plan and demonstrates a deliberate retry or recovery policy.
