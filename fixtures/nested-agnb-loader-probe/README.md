# Nested AGNB selected-record loader probe

This isolated J1 fixture selects one P3DM record from an ordinary ten-record
AGNB 0.3 family without modifying the accepted loose KOAK runtime. Its runtime
path is:

```text
RGN/00/00.AGN
```

The generated family is 21,904 bytes, deliberately larger than the legacy
16,384-byte whole-file window. The requested terrain record is wire index 6,
with LIST offset 13,152 and DATA offset 13,228. The executable host reference
reads only 2,992 bytes while scanning all ten descriptors and validating the
selected 2,110-byte DATA payload.

The fixture creates an inactive stable mesh/object first. It then calls
`agnb_load_selected_component`, which opens and scans the family with FatFS
absolute seeks, closes it, reuses the complete P3DM policy/count/index/CRC
validator, and reaches staging plus atomic command 50 only on success. The
selected object is transformed and activated afterward. Escape exits.

Build from the repository root:

```text
.venv/bin/python scripts/build_nested_agnb_loader_probe.py
```

Run the focused host/source/assembly suite and explicit width audit:

```text
PYTHONPYCACHEPREFIX=/tmp/pingo-terrain-pycache \
  .venv/bin/python -m unittest -v tests.test_nested_agnb_loader

.venv/bin/python scripts/audit_adl_width.py --follow-includes \
  --show-review --fail-review \
  fixtures/nested-agnb-loader-probe/src/nested-agnb-loader-probe.asm
```

The unattended capture helper uses dummy video/audio drivers and always stops
its emulator process after collecting the diagnostic frame:

```text
.venv/bin/python scripts/capture_nested_agnb_loader_probe.py \
  --output /tmp/pingo-nested-agnb-loader-capture
```

The 2026-08-02 automated run published 26,037 matching color/depth pixels;
RGBA2222 SHA-256 was
`0a213e3534353f07431aa14d07f709c6ce14d8893802d22ac3987ba1f4deb3bd`.

The normative wire, state and failure contract is
[`docs/nested-agnb-loader.md`](../../docs/nested-agnb-loader.md). This fixture
has not yet passed the project's required human emulator gate.
