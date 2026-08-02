# P3DM loader probe

This distinct fixture proves the first eZ80 side of J1 without modifying the
visually accepted `berkeley-flight-triangular-dither` fixture. It reads exactly
one deterministic path:

```text
TRN/L0/00/0C.AGN
```

The selected component is Berkeley triangular-lattice tile 12 (row 1, column
4), using staging buffer `0x7400`, stable mesh/object slot 1, flat-pattern
shading, and scene illumination. The fixture chooses those values; the loader
does not hard-code them.

The eZ80 opens, completely reads, and closes the file before validation. It
then requires the exact RIFF/AGNB 0.3 `VERS` / `LIST BUFR` / `BHDR` / `P3DM` /
`DATA` structure, physical and nested size equality, zero padding, the
caller-selected render policy and component identity, nonempty and consistent counts, exact
`6V+2I+4U+2T`, signed elevation ordering, in-range position/UV indices, one
repeated UV selector per triangle, `1 <= model_half_extent_m <= 2047`, and
reflected ISO-HDLC CRC32. Only the DATA payload is uploaded. Pingo command 50
uses the caller's mesh ID and is unreachable on any pre-publication failure.

An embedded triangle first establishes real resident geometry in a stable
mesh slot, and the object binds that slot before disk I/O. Command 50 therefore
retains Pingo's transactional old-or-new publication guarantee. The caller
applies the tile transform and command 51 activation only after publication.

The complete-file validation window is 16,384 bytes. That admits all current
Bay Area proof records, including the 14,120-byte KSFO markings component,
while keeping parsing fail-closed and entirely ahead of VDP publication.

## Integration contract

Before each synchronous `p3dm_load_component` call, the coordinator writes:

- a NUL-terminated 8.3-safe path into the 64-byte writable
  `p3dm_filename_buffer`, or points the 24-bit `p3dm_filename_pointer` at an
  equivalent lifetime-stable buffer;
- `p3dm_target_mesh_id` (u16); and
- expected layer, LOD, shading, illumination, material-set bytes plus expected
  tile X/Y signed i16 values (compared as exact two's-complement bytes).

The stable mesh must already exist and be bound to an inactive object. On
return, `Z` means command 50 was sent and `p3dm_loader_state` is
`p3dm_state_published`; `NZ` means no command 50 was sent and A plus
`p3dm_last_error` identify the failure. The coordinator may consume results
only for a request whose state reached `p3dm_state_validated` or later:
validated signed i16 tile X/Y, signed i32 centre east/north metres, signed i16 minimum and
maximum elevation decimetres, u16 model half-extent metres, and all four u16
mesh counts. Transform derivation belongs to the coordinator; terrain may
cross-check its expected grid centres but the loader does not invent them.

KOAK P00/M00 is deliberately not faked as a single-file transaction. A
coordinator must load P00 into its inactive stable slot, then M00 into its
inactive stable slot, treat that sequence as a barrier, and activate both
airport objects only if both calls succeed. Failure leaves the previously
resident pair inactive/unchanged.

Build with:

```bash
.venv/bin/python scripts/build_p3dm_loader_probe.py
```

Audit the complete assembly include closure with:

```bash
.venv/bin/python scripts/audit_adl_width.py --follow-includes \
  --show-review --fail-review \
  fixtures/p3dm-loader-probe/src/p3dm-loader-probe.asm
```

The capture helper performs the silent bespoke-firmware qualification:

```bash
.venv/bin/python scripts/capture_p3dm_loader_probe.py --output /tmp/p3dm-loader
```

Emulator-coupled fixture, profile, and bespoke-firmware work remains
uncommitted until human validation.
