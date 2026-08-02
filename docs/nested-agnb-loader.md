# Bounded nested-AGNB selected-record loader

Status: **implemented isolated eZ80 fixture, executable host reference and
automated silent-emulator proof; not yet integrated into the KOAK runtime or
human-qualified**. The implementation is deliberately separate from the
proven loose-file loader.

## Scope and wire contract

The loader accepts an ordinary multi-record AGNB 0.3 family:

```text
RIFF AGNB
  VERS 0,3
  LIST BUFR  BHDR P3DM DATA
  LIST BUFR  BHDR P3DM DATA
  ...
```

Each `LIST BUFR` retains the exact layout-1 `BHDR`/`P3DM`/`DATA` contract in
[`p3dm-streaming-format.md`](p3dm-streaming-format.md). Selection uses the
caller's existing request fields: layer, LOD, shading, illumination, material
set, and signed tile X/Y. The comparison is exact over the descriptor's wire
bytes. Centre, elevation, half extent, counts and CRC are results, not search
keys; the existing full P3DM validator checks them after selection.

The current bounded domain is explicit:

| Quantity | Bound |
| --- | ---: |
| family bytes | 100 through `0x00ffffff` |
| LIST records | 1 through 16 |
| fixed bytes read per scan record | 76 |
| selected DATA | 0 through 16,284 bytes before semantic count checks |
| DATA alignment | zero-filled through a four-byte boundary |
| staging buffer | caller fixture's fixed `0x7400`; `0xffff` remains forbidden |

Every record prefix must be exactly `LIST BUFR`, `BHDR size=2`, `P3DM
size=36`, layout 1, then `DATA`. Its LIST payload size must equal
`68 + align4(DATA size)`. The computed next offset must remain within the
physical RIFF boundary. These checks occur even for unmatched records, so a
corrupt sibling cannot redirect a seek into another DATA block or beyond the
file. Zero to three trailing DATA pad bytes are read separately and must be
zero.

The file's fourth size byte must be zero because the eZ80 implementation keeps
logical offsets in native u24 storage. `ffs_flseek` receives that u24 offset in
`DEU:DE` with `C=0`. This still exceeds the largest planned regional family by
more than two orders of magnitude while making overflow behavior simple and
auditable.

## Bounded read and publication state

`agnb_load_selected_component` performs one synchronous transaction:

```text
IDLE
  -> open / READING
  -> read 24-byte RIFF/VERS prefix
  -> seek/read each 76-byte LIST prefix and its 0..3 pad bytes
  -> reject no match, duplicate match, record overflow, or malformed boundary
  -> seek/re-read the selected prefix
  -> seek/read only selected aligned DATA
  -> close / CLOSED
  -> reconstruct canonical one-record image in p3dm_file_buffer
  -> existing structure/policy/count/index/padding/CRC validation / VALIDATED
  -> existing 0x7400 upload and consolidate / STAGED
  -> existing atomic command-50 replacement / PUBLISHED
```

The synthetic image preserves the original 24-byte `RIFF AGNB`/`VERS` prefix
and chosen LIST bytes, then rewrites only its RIFF and LIST sizes for the
single-record view. The complete existing `p3dm_validate_container` routine is
therefore the sole authority for mesh policy, `6V+2I+4U+2T`, index bounds,
flat-selector triples, signed elevation ordering, normalization bounds, exact
DATA length and reflected ISO-HDLC CRC32. The new scanner does not duplicate a
weaker mesh validator.

For `N` records and selected aligned payload `D`, the normal read ceiling is:

```text
24 + 76*N + sum(record padding) + 76 + D
```

The deterministic fixture is a 21,904-byte ten-record family. Record 6 has a
2,110-byte DATA payload, and the host reference reads 2,992 bytes total
(13.66% of the family). The eZ80 uses the same operation sequence and never
requests an unmatched DATA span.

The family is always closed before validation or publication. A scan/read/seek
failure is retained as the primary result even if close also fails; a close
failure is reported when all earlier I/O succeeded. No command 50 is emitted
for a pre-publication failure, so the already-bound resident mesh remains
unchanged. Transform and activation remain coordinator-owned and occur only
after `p3dm_state_published`.

This isolated version scans on every request. A regional coordinator may later
cache the ten `(LIST offset, length)` pairs for a relevant open family, but
cache invalidation and family lifetime are intentionally outside this loader's
first correctness proof.

## Failure contract

Errors `1..11` retain the loose loader's existing meaning: open, read, close,
file size, structure, policy, counts, bounds, CRC, indices and premature EOF.
The nested scanner adds:

| Error | Meaning |
| ---: | --- |
| 12 | FatFS absolute seek failed |
| 13 | no descriptor matched the caller's identity |
| 14 | more than one descriptor matched the identity |
| 15 | a seventeenth LIST would exceed the fixed scanner bound |

On `NZ`, A and `p3dm_last_error` carry the same nonzero error and the loader
state never reaches `p3dm_state_validated`. On `Z`, command 50 has been sent,
`p3dm_last_error` is zero, and the state is `p3dm_state_published`.

## Fixed-width safety and evidence

All file positions and FatFS byte-count/pointer fields are declared `dl` and
carry local `ADL24 OK` annotations. Exact u16 sizes, IDs and counts use the
existing bytewise `P3DM_LD_U16_*`/`P3DM_ST_U16_HL` macros. RIFF u32 fields are
checked bytewise before any deliberate low-u24 read. No unsuffixed ADL load or
store targets a `dw` field.

The focused suite covers bounded middle-record selection from a family larger
than 16 KiB, selected CRC corruption, unmatched nonzero padding, contradictory
LIST length, missing and duplicate identities, the 16-record ceiling,
close-before-publication source ordering, full include-closure width audit and
isolated `ez80asm` assembly. Build artifacts and exact hashes are recorded in
`fixtures/nested-agnb-loader-probe/tgt/probe.json`.

A silent bespoke-emulator run with dummy video/audio drivers exercised the
actual MOS `ffs_flseek` path and current diagnostic Pingo VDP. It published
sequence 0 with 26,037 populated RGBA2222 pixels and exactly 26,037 populated
depth pixels. The binary SHA-256 was
`af2c9ef6de7c6f333899d911422196b55f55da14e1f59a109ff561e90da55004`;
the frame SHA-256 was
`0a213e3534353f07431aa14d07f709c6ce14d8893802d22ac3987ba1f4deb3bd`.
Session evidence is retained under
`/tmp/pingo-nested-agnb-loader-capture-20260802-a`; the emulator process was
stopped cleanly. This is automated implementation evidence and does not waive
the project's explicit human emulator gate.

This establishes the nested-selection mechanism only. Integration with family
slot planning, render-idle scheduling, offset caching, latency diagnostics and
activation-atomic LOD swaps remains part of the broader J1 runtime gate. No
emulator result is claimed until the Author explicitly qualifies the fixture.
