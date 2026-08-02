# KOAK nested-family LOD flight fixture

Status: live fixed-west integration witness, 2026-08-02. This sibling fixture
combines the deterministic KOAK 28L light-flight application with selected
records from regional multi-record AGNB families. It leaves the accepted loose
5×5 KOAK fixture unchanged.

The deliberately narrow proof covers one natural westbound handoff from family
`(23,36)` to `(22,36)`. It exercises the selected-record loader, two L0 banks,
D1/D2 plan repair, floating-origin rebasing, stable Pingo object identities,
and an activation transaction between completed renders. It is not yet a
general rolling regional coordinator.

## Build

From the repository root, after building the accepted regional/KOAK inputs:

```text
.venv/bin/python scripts/build_koak_family_lod.py
```

The builder generates `tgt/family-plan.inc` and `tgt/family-plan.json`, builds
the 20 required ten-record families from the pinned 3DEP/NLCD sources, installs
the accepted pattern, cockpit, aircraft, and KOAK hard-surface resources, and
assembles the ignored proof at:

```text
build/p3dm/bay-area-koak-family-proof/
```

`FAMILY.json` binds every output by length and SHA-256. The current proof has a
56,425-byte `P3DLOD.BIN` with SHA-256
`fa41b2adca0da781441d6ded66e4460e68d713b9d38869d57376581956714cbb`,
37 terrain load requests, 20 families totalling 1,785,012 bytes, 37 resident
terrain slots, and 24 active terrain objects in either steady plan.

## Runtime contract

The first-frame barrier loads and activates current-family L0 slots `1..8`,
then loads KOAK pavement and markings as stable objects `101` and `102`. Each
later render-idle service pass may publish at most one selected family record:

- current D1 slots `17..24` and D2 slots `29..36` become active after their
  successful publication;
- next-family L0 slots `9..16`, four missing D1 slots `25..28`, and one missing
  D2 slot `37` are published inactive; and
- a failed selected read does not advance the plan cursor and places streaming
  in an error hold without replacing or activating a partial bank.

Every family request is selected by the complete P3DM descriptor identity, not
by trusting physical LIST order. The target scans each fixed 76-byte LIST
prefix, validates sibling bounds and padding, seeks over unmatched DATA with
MOS `ffs_flseek`, re-reads the sole match, and reads only that aligned DATA into
the 16 KiB staging window. It then reuses the exact one-record validator, CRC,
upload, and atomic command-50 publication path. The generated `record_index`
remains a host-side layout witness; the eZ80 match is descriptor-based.

After all 37 terrain objects are resident, crossing west of coarse X `92`
performs one disk-free command-51 transaction: 13 outgoing objects are
deactivated, then 13 resident replacements are activated. No mesh publication
or render is allowed inside that group. The aircraft remains object `201`; the
24 terrain objects, two airport objects, and chase aircraft use 27 of Pingo's
32 active-renderable slots.

## Headless qualification

The basic startup/publication capture is:

```text
.venv/bin/python scripts/capture_koak_family_lod.py \
  --output /tmp/pingo-koak-family-lod-capture
```

The natural transition driver switches to chase view, holds W, applies the
same delayed eight-vblank takeoff pulse as the qualified KOAK flight, and lets
the flight model cross the family boundary. It rejects use of the F12 test key:

```text
.venv/bin/python scripts/trace_koak_family_transition.py \
  --output /tmp/pingo-koak-family-transition
```

Both drivers require the diagnostic native VDP. The transition driver also
requires `PINGO_POSE` records, which exist only when the VDP is built with
`PINGO_RENDER_DIAGNOSTICS=1` (`DIAGNOSTICS=1` in the userspace Makefile). The
production build therefore carries no pose-log traffic. The diagnostic records
bind exactly one aircraft and camera translation to each bracketing render and
make the expected floating-origin wrap distinguishable from a camera jump.

The canonical silent run is retained at
`/tmp/pingo-koak-family-transition-20260802-f-placement-validated`. Its v2
report SHA-256 is
`877114ade487803fc9565537c0c744ed5e6b03f520af7d7e79ee82a1b5a429d3`;
the log SHA-256 is
`8c577e6ecc1449b3671c4be80a289b04f0b209ad7d1f7f7da068f096498fafda`.
Natural input reached the later debugger snapshot at coarse cell `[91,148]`
after horizontal displacements `[624.188720703125,1631.052978515625]` metres.
All 37 terrain meshes and both airport meshes published exactly once, the
largest recorded VDP publication was 57 microseconds, the plan cursor reached
37 with no loader error, and the final plan had exactly 24 active terrain
slots.

The exact 26-command swap lies between consecutive renders 1192 and 1193 with
no interleaved render or mesh publication. Before the swap, exactly 37
command-52 placements occur in generated plan order. Combining each raw
translation with its generated component centre reconstructs the same
swap-time coarse cell `[91,147]`, centre `[749568,1208320]`, and terrain Y
`9728` for every resident slot. The debugger snapshot later reaches `[91,148]`;
this one-shot fixed-west fixture makes no subsequent north-family handoff claim.

Across the bracketing renders the aircraft and camera both change by
`[7,11,-8173]` raw counts: the expected `[0,0,-8192]` cell rebase plus natural
motion `[7,11,19]`. Their chase offset remains exactly `[-107,37,-277]` and the
aircraft is active in both frames. The pre/post frames contain 19,459 and 21,136
matching nonzero color/depth pixels; their RGBA2222 hashes are respectively
`97cc37ca562ec9b3424a050dbf1a94ce52c64283c728b34fe565f5eeb551bfdd`
and `c87cde45e65783f6cd9859ae0ad8d75c0559a9e76bbc6d018b0c00af671b3915`.
Both captured images were independently inspected as coherent and nonblank.

That is a structural atomicity and pose-coherence result. It proves that no
partially swapped scene was submitted; it does **not** prove an imperceptible
LOD change, absence of a visible pop, or acceptable cross-LOD seams. The two
frames differ, as a moving camera and LOD replacement require. Human visual
seam/pop review, complete SD I/O latency measurement, arbitrary-direction
rolling-family logic, integrated failure injection, and physical-hardware
range/depth/performance qualification remain open.
