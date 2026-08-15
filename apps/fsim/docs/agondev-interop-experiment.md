# AgonDev C/assembly interoperability experiment

Status: **host- and headless-target-qualified standalone probe with a bounded
terrain-policy A/B; physical-hardware and integrated-fixture decisions remain
open; no accepted terrain fixture is replaced**

The authoritative unfinished work item is `E1` in `docs/todo.md`. This
document fixes the design and evidence contract; it is not a second task list.

## Purpose

The regular terrain manager has reached the point where ownership planning,
slot allocation, and coverage-group handoff form a substantial state machine.
C may make that policy layer easier to inspect and maintain, but it is not a
replacement for the project's qualified eZ80 mathematics or low-level I/O.

This experiment establishes a narrow, measurable C/assembly seam before any
terrain code is moved. Its first artifact is a standalone MOS-loadable probe,
not a new FSIM launcher entry and not a modification of the accepted regular
LOD appliance.

## Ownership boundary

C may own topology-neutral orchestration:

- desired-owner and transition-plan construction;
- slot and identity bookkeeping;
- loader and handoff state-machine decisions;
- collision broad-phase policy; and
- sequencing of future flight-model operations.

Assembly continues to own:

- all fixed-point, vector, matrix, force, inertia, and coordinate mathematics;
- exact-width MOS and VDP packet construction;
- P3DM byte and buffer mechanisms already qualified in assembly;
- render/interrupt boundaries; and
- any loop shown by measurement to need a hand-written implementation.

C calls those operations through small audited wrappers. Important arithmetic
must not silently become a compiler helper or an AgonDev fixed-point-library
call. The first probe deliberately contains policy comparisons and byte-field
access only.

## Authoritative inputs

The compiler, assembler, linker, headers, libraries, and program-name tool are
read from the local AgonDev checkout at `/home/smith/Agon/agondev`, overridable
through one explicit `AGONDEV_ROOT` setting. The checkout is a read-only input
and is never vendored or modified by FSIM.

`/home/smith/Agon/mystuff/mos-agondev` is the worked ABI reference. Its MOS
port proves the compiler's eZ80 data model and records the relevant calling
convention:

- `char` is one byte, `short` two, and `int`, pointers, and `size_t` three;
- arguments no wider than 24 bits occupy caller-cleaned three-byte stack slots
  in reverse order;
- after the ordinary `push ix; ld ix,0; add ix,sp` frame, slots begin at
  `IX+6`, `IX+9`, `IX+12`, and so on;
- an 8-bit return is in `A`, a 16-bit return is in `HL`, and 24-bit values and
  pointers use `UHL`; and
- C symbols have one leading underscore in GNU assembly.

The experiment pins these assumptions with compiler assertions, object-symbol
inspection, generated assembly, and final-link inspection rather than relying
on prose alone.

## Repository and build layout

Tracked sources live under:

```text
experiments/agondev-interop/
├── AgonDev.mk.in
├── CMakeLists.txt.in
├── CMakePresets.json.in
├── README.md
├── PROVENANCE.json
├── include/
└── src/
```

All objects, generated assembly, maps, manifests, ELF files, and MOS binaries
live under ignored `build/experiments/agondev-interop/`. The experiment must
not write into the AgonDev checkout or its own tracked source directory.

AgonDev's Make-based application contract remains the real build. There is no
discoverable tracked `CMakeLists.txt` or `CMakePresets.json`: the maintained
FSIM builder materializes those files from `.in` templates only under ignored
`build/`. That generated project has `LANGUAGES NONE`; its ordinary/default
configure keeps the experiment disabled and performs no compiler test. An
explicit `agondev` preset only adds a custom target that invokes the same FSIM
builder. Therefore opening FSIM or the tracked experiment in a CMake-aware
editor discovers nothing new to configure, select, or fail.

## Probe and bounded policy contract

The standalone program performs both call directions:

1. C passes a pointer and byte argument to a GNU-assembly routine, which writes
   one explicitly located byte in shared state.
2. C calls an assembly trampoline with a state pointer.
3. The trampoline republishes that pointer in one three-byte C argument slot,
   calls a C policy function, cleans the caller-owned slot, and returns the
   C function's 8-bit result unchanged in `A`.
4. The C entry checks the write and several policy outcomes and emits one short
   pass/fail line through MOS.

It then performs the first bounded terrain-policy A/B. C and GNU assembly each
select one already edge-filtered coverage group using the accepted regular-LOD
ordering: skip processed or capacity-infeasible groups; maximize
`retiring-entering`; then prefer fewer entering owners, more retiring owners,
and finally source order. The target compares both implementations across
empty, corrupt, processed, infeasible, primary-score, tie, and source-order
cases. This is deliberately policy over byte counts—not fixed-point terrain
mathematics—and it does not alter the accepted runtime manager.

Shared state uses byte fields and little-endian byte arrays only. Static
assertions pin every offset and the total structure size. This avoids asking
either compiler to infer a packed 16- or 24-bit memory access at the boundary.

## Qualification contract

Host qualification must establish all of the following before target review:

1. Default CMake configuration succeeds with the experiment disabled.
2. The explicit AgonDev preset configures and invokes the same canonical build
   script as the command line.
3. Compiler static assertions prove the expected type and structure layout.
4. Object symbols prove C references the assembly entry points and assembly
   references the C callback; disassembly proves the callback call remains.
5. The final ELF is an ADL eZ80 application at the intended load address, has
   no unresolved symbols, and produces a deterministic MOS binary.
6. The link contains no multiplication, division, floating-point, or fixed-
   point helper selected by the probe's policy code.
7. A checksum-bound generated receipt identifies every source, tool, and
   output used by the evidence.

Automated target qualification runs the MOSlet through the pinned Fab CLI and
stock platform MOS in a temporary read-only host filesystem. It requires the
PASS marker and a second MOS prompt after PASS, proving the CRT returned to its
caller. Physical-hardware execution remains a separate human gate. Neither
gate by itself authorizes replacing the accepted assembly manager or moving
mathematical primitives into C.

## Qualified artifact and evidence

The current probe builds with pinned AgonDev commit
`b67ab2444a63267a42193f204889d466765d8dd2`. Its MOS binary is 2,427 bytes,
starts with `C3 45 00 04`, contains the `MOS 00 01` application header at
offset `0x40`, and has SHA-256
`b77cdbec7e388e69a44785971330571a500a8a24ba98bf5507ffc4c35d50af89`.
The inspection ELF is ADL eZ80 with CRT entry `0x040045`.

An independent staging directory reproduced the exact binary and ELF. Static
inspection proves the assembly exports, assembly-to-C callback relocation,
three-slot policy selector ABI, byte-state write, 8/16/24-bit return witnesses,
balanced caller cleanup, and exact ELF-to-runnable image identity. The only
external C helpers are `__frameset`, `__frameset0`, and `_putch`; no multiply,
divide, remainder, floating-point, fixed-point, or conversion helper is
selected. The generated default and explicit CMake presets both configure
successfully; the default does no toolchain work and the explicit target
invokes the project `.venv` and canonical builder.

The checksum-bound ignored receipt is
`build/experiments/agondev-interop/BUILD.json`. It records semantic SHA-256
`84b8e642d24e9269cc9ee99803cce666b098c40f0ef8588e79fe75b05d4bdb38`.
Verify-only rechecks that receipt, every tracked and staged input, toolchain and
ABI reference, ELF image, and output hash without rewriting it. A build that
skips the independent rebuild can emit only an explicitly unqualified
`LOCAL-BUILD.json`.

The isolated headless run emitted exactly one PASS marker and returned to a
second MOS prompt. Its checksum-bound ignored evidence is
`build/experiments/agondev-interop/headless/HEADLESS.json`, semantic SHA-256
`dc8a8f103097bc5d0421f9d14f303c8bf2fe9e6b8b1a8651d2f238e9b130ab4b`;
the raw 228-byte transcript hashes to
`55ca85e5038f504a43fd98965d953d9601901fb5e5b8bceaf4845fc2edf5e888`.

This first comparison does not show a code-size win. `nm -S` reports the C
selector at 208 bytes; the assembly reference spans 170 bytes from its exported
entry to the next exported routine. C therefore costs 38 bytes (about 22%) for
this small operation, in exchange for a substantially more direct policy
expression. Execution time has not yet been measured. That is consistent with
the experiment's purpose: test C for maintainability in orchestration, not as a
replacement for compact or timing-critical assembly.

The remaining gates are physical-hardware execution and a measured sibling
terrain-fixture experiment before any production integration decision.
