# FSIM AgonDev interoperability probe

This isolated MOS application proves the C/assembly boundary proposed in
[`docs/agondev-interop-experiment.md`](../../docs/agondev-interop-experiment.md).
It does not replace or link into the accepted regular-LOD fixture.

The real build is the stock AgonDev application pipeline. Run it only through
the project interpreter so staging, provenance checks, static ABI inspection,
and the generated receipt remain identical:

```bash
.venv/bin/python scripts/build_agondev_interop.py
```

Generated inputs, objects, maps, ELF inspection image, MOS binary, generated
CMake wrapper, and receipt are written to:

```text
build/experiments/agondev-interop/
```

The runnable program is
`build/experiments/agondev-interop/project/bin/fsim-agondev-interop.bin`.
It prints either
`FSIM AGONDEV INTEROP PASS` or `FSIM AGONDEV INTEROP FAIL` and returns to its
caller through AgonDev's stock application CRT.

Run the explicit isolated target gate with:

```bash
.venv/bin/python scripts/qualify_agondev_interop_headless.py --show-output
```

This uses a temporary read-only host filesystem and the pinned command-line
emulator/stock MOS. It does not use or modify FSIM's graphical emulator
profile. Qualification requires both the PASS line and the MOS prompt that
appears after it; the raw transcript and report remain under ignored
`build/experiments/agondev-interop/headless/`.

## CMake isolation

This tracked directory intentionally contains no `CMakeLists.txt` and no
`CMakePresets.json`, so IDE discovery cannot mistake the eZ80 experiment for a
normal host CMake project. The Python builder emits an ignored wrapper under
`build/experiments/agondev-interop/cmake-source/`.

After staging or building, configure the generated wrapper explicitly:

```bash
cmake --preset default \
  -S build/experiments/agondev-interop/cmake-source
cmake --preset agondev \
  -S build/experiments/agondev-interop/cmake-source
```

Run the explicit build preset from the generated source directory:

```bash
cd build/experiments/agondev-interop/cmake-source
cmake --build --preset agondev
```

The default preset has no languages and does not inspect AgonDev. The explicit
`agondev` preset calls the same Python builder shown above.

## Numerical boundary

The probe contains no fixed-point implementation. C performs byte-field
validation and policy comparisons. Assembly owns ABI trampolines and the
reference selector. The bounded A/B compares C and assembly implementations of
coverage-group selection only. Any later integrated terrain experiment must
continue to call the already-qualified assembly mathematics rather than
compiler or AgonDev fixed-point helpers.
