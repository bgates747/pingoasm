# Regular-LOD C-policy sibling

This fixture changes only the bounded coverage-group selector used by the
accepted regular hierarchy manager. It is an experimental sibling, not an FSIM
launcher entry and not a replacement for `P3DRGL.BIN`. Fixed-point,
coordinates, ownership maps, P3DM loading, MOS/VDP packets, staging, and atomic
commits remain in the qualified assembly runtime.

Build the accepted hierarchy first by following
[`../terrain-manager-regular-lod-survey/README.md`](../terrain-manager-regular-lod-survey/README.md).
Then build the fixed AgonDev module and the canonical guarded-C sibling:

```bash
.venv/bin/python -B scripts/build_agondev_regular_policy.py
.venv/bin/python -B scripts/build_regular_lod_c_policy_survey.py \
  --skip-module-build --policy-mode c-guarded
```

The first command writes the qualified local `CPOLICY.BIN` and ELF evidence
under ignored `build/experiments/agondev-regular-policy/`. The second writes the
small target binary and checksum receipt here, installs `P3DRGLC.BIN` plus the
module beside the ignored hierarchy, and regenerates the ignored `.lst` and
`.symbols` sidecars required by live qualifiers. Nothing writes into the local
AgonDev checkout.

Available build modes are `asm-only`, `dual-strict`, and `c-guarded`.
`C_GUARDED` is the canonical application: it uses the revalidated C result and
permanently falls back to the accepted assembly selector after any fault.
`DUAL_STRICT` is the diagnostic oracle mode: C must match assembly and only the
assembly result controls the transition.

The active correctness gates are the focused tests and qualification scripts
documented by the application [README](../../README.md) and
[TODO](../../TODO.md). They cover four north crossings, all six directions, a
clipped regional edge, module absence/header/CRC rejection, and an injected
invalid-result latch. The canonical `C_GUARDED` image was interactively
exercised and accepted in the emulator on 2026-08-15. Physical-hardware
execution and timing remain explicit human gates; optimization is deliberately
deferred until application behavior is complete.
