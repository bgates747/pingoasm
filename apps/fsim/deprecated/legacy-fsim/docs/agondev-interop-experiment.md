# AgonDev C/assembly interoperability experiment

Status: **host- and headless-target-qualified standalone probe plus a four-mode
terrain-policy sibling; physical-hardware and production-integration decisions
remain open; no accepted terrain fixture is replaced**

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
expression. This standalone MOSlet was not timed; the production-shaped
sibling measurements below supersede that open question. That is consistent
with the experiment's purpose: test C for maintainability in orchestration,
not as a replacement for compact or timing-critical assembly.

The remaining gates are full-pipeline and physical-hardware measurements
before any production integration decision.

## Continuing implementation sequence

`E1` in `docs/todo.md` remains the sole unfinished-work queue. This section is
the durable execution design for that item, not another checklist. It is
updated whenever measurement invalidates an assumption below.

### Phase 1: measure the accepted assembly fixture

The accepted regular-LOD fixture remains the control. Before introducing C,
record three separate costs so a policy-language experiment is not credited or
blamed for unrelated work:

1. cold fill from the first terrain publication through the complete Marina
   radius-five endpoint;
2. steady rendering after convergence at the fixed initial pose; and
3. one adjacent-cell handoff, divided into plan selection, file validation and
   upload, inactive staging, atomic commit, and post-transition convergence.

The benchmark must report both simulated time (vblanks/render sequence) and
host wall time. It also records command-50 publication count and bytes, active
object/triangle counts, renderer traversal/rasterization diagnostics, group
count, maximum staged side, and any frame in which old coverage is replaced.
Existing deterministic headless/debugger hooks are preferred over new target
instrumentation. If an unmeasured interval remains, add a sibling diagnostic
build rather than perturbing the accepted binary.

The first accepted-binary baseline is now recorded under ignored evidence at
`build/evidence/regular-lod-runtime-benchmark-v3/`. Its checksum-bound report
has SHA-256
`0b625e754b6bfd0d5c7bf1aea400ccaee54435a5706f641c876f677eb6d270ae`.
It uses three distinct emulator processes with identical program, symbols,
VDP, MOS, emulator, and input-proxy identities: one stationary run, one
unprofiled handoff run, and one debugger-profiled selector run. The report
fails closed on identity drift and explicitly labels itself a partial
accepted-assembly baseline rather than a completed Phase 1 qualification.
The final analyzer recheck of those immutable run directories is
`build/evidence/regular-lod-runtime-benchmark-v5/` with report SHA-256
`202313f95f9eb14d6caa45d984c164752d59f21a1466b78eb25b17985d687ddb`;
it additionally binds the profiled call target to the checksum-verified symbol
file and the call instruction in the executable.

At the Marina radius-five cold endpoint the fixture published 227 records,
787,192 container bytes and 764,288 DATA bytes, representing 28,232 vertices
and 48,364 runtime triangles. Three hundred unchanged steady frames at the
fixed pose had a median renderer time of 1,309 microseconds; their complete
non-timing diagnostics and the endpoint/final color and depth hashes were
identical. Four northward handoffs selected 29, 21, 17, and 17 coverage groups,
published 130 inactive replacements carrying 240,304 DATA bytes, and retained
the exact final owner set. The existing assembly selector was called 84 times;
call-through-return cost ranged from 3,881 to 14,682 guest cycles with a median
of 8,375.5 cycles.

A separate complete cold-load profile now binds all 227 records and their
787,192 container / 764,288 DATA bytes to nine unique debugger boundaries and
the exact manifest/publication order. Its pinned-input report is
`build/evidence/regular-lod-cold-load-cycle-profile-v1/regular-lod-cold-load-cycle-profile.json`
(SHA-256
`0943a80c13f085e18d0b7a1416ca1b4dcc512060c5fc21ddcca3093ba5db1e00`).
The measured guest totals are 260,907 cycles for the FatFS/container call,
387,855,886 for validation/index/CRC, 5,542,107 for reflected-Z/winding
conversion, 177,922,503 for VDU upload/staging, and 979,051 for command-50
enqueue: 572,560,454 cycles in those spans. Validation accounts for 67.7406
percent and upload/staging for 31.0749 percent. This makes the next optimization
target much clearer than selector timing alone.

Reproduce that fresh-process profile with:

```bash
.venv/bin/python -B scripts/profile_regular_lod_cold_load.py \
  --output build/evidence/regular-lod-cold-load-cycle-profile
```

These measurements are emulator evidence, not hardware latency. The cold-load
profile excludes renderer and native-VDP time, host wall time, and physical SD
latency; complete origin-to-convergence cycles likewise remain unmeasured and
therefore remain in Phase 1.

The first optimization sibling now replaces only the hash-pinned bitwise CRC
body with the same reflected CRC-32/ISO-HDLC polynomial held low-to-high in
`L/H/E/D`. It changes no container layout, index validation, error ordering,
fixed-point operation, VDU packet, accepted source, accepted binary, launcher,
or installed fixture. Its deterministic build receipt is
`build/evidence/regular-lod-crc-register-sibling-build-v1/BUILD.json`
(SHA-256
`721fee2fd53adef80ab7fd0028383d7e4294d4967cf858dff6e50ce18e42151e`);
the 142,750-byte candidate hashes to
`a4a88621ee4ed3af42ad6006bebf5e48037d19ad4375568b3b9032594f139992`.

One exhaustive fresh-process accepted/candidate pair profiled every boundary
for all 227 records. CRC cycles fell from 377,749,180 to 159,093,967
(-57.8837 percent), validation fell from 387,944,795 to 169,289,522
(-56.3625 percent), and the five measured cold phases fell from 570,523,534 to
352,596,922 (-38.1977 percent). All stored and register CRC bytes, buffer-
relative final pointers, publication order and shapes, and the cold endpoint
were exact. Separate guest runs proved DATA corruption still returns error 9
before publication and an invalid index with a recomputed valid CRC still
returns error 10 before CRC execution. The report is
`build/evidence/regular-lod-crc-register-sibling-profile-v1/regular-lod-crc-register-sibling-profile.json`
(SHA-256
`1dabb773a61e5e6be5355ddb33a99e13b63a27fd4459c577e25d2b1ae33b3d2e`).
Timing repeatability is not claimed from this single expensive paired run; the
candidate remains an isolated sibling until repeated emulator and physical-
hardware timing qualify it.

Rebuild and reprofile the sibling with:

```bash
.venv/bin/python -B scripts/build_regular_lod_crc_register_sibling.py \
  --output build/evidence/regular-lod-crc-register-sibling-build-repro
.venv/bin/python -B scripts/profile_regular_lod_crc_register_sibling.py \
  --build build/evidence/regular-lod-crc-register-sibling-build-repro \
  --output build/evidence/regular-lod-crc-register-sibling-profile-repro \
  --repeats 1 --timeout 900
```

The remaining upload/staging span is mostly the UART serialization floor. The
pinned Console8 MOS polls UART `TEMT` for each byte. A second temporary-mirror
sibling therefore replaces only the DATA block write with an application-local
CTS+`THRE` sender; clear, header, consolidate, and command-50 traffic retain the
accepted RST18 path. Its deterministic build receipt is
`build/evidence/regular-lod-uart-thre-sibling-build-v1/BUILD.json` (SHA-256
`cee0eb757020ad2dd7ffa9636b7ac9555fbc54687c1de00b613f7bfb9a389481`),
and its 142,828-byte binary hashes to
`65843171996faa8916f17f7d05eeaabe328b292eca625f17025876f64bdeb7eb`.

All 227 host transcripts and both fresh guest endpoints are exact. In one
exhaustive pair, the completion-equivalent upload span through the following
consolidate command fell from 160,144,209 to 129,219,396 cycles (-19.3106
percent), while all five measured cold phases fell from 554,781,476 to
523,855,936 (-5.5744 percent). The narrower sender-return span is not a valid
completion comparison because THRE may leave one byte queued; the report labels
it diagnostic only. The checksum-bound live report is
`build/evidence/regular-lod-uart-thre-sibling-profile-v1/regular-lod-uart-thre-sibling-profile.json`
(SHA-256
`0136fea7e41615c0eaff14dc7480ca7a3c68e5ae2f7e8a0a3832f30c3f574921`).

This direct path is deliberately nonportable. It depends on private
`_serialFlags` at `0x0bc32d`, the old Console8 GPIO-PD3 active-low CTS wiring,
stable UART configuration, and no competing UART writer. Runtime guards catch
configuration drift only inside the exact pinned MOS image; they do not identify
another MOS. The sibling must never run or deploy with a different MOS, and a
MOS-side THRE correction is preferred before any promotion. Timing
repeatability and exact-image physical qualification remain open.

Rebuild and reprofile into absent output directories with:

```bash
.venv/bin/python -B scripts/build_regular_lod_uart_thre_sibling.py \
  --output build/evidence/regular-lod-uart-thre-sibling-build-repro
.venv/bin/python -B scripts/profile_regular_lod_uart_thre_sibling.py \
  --build build/evidence/regular-lod-uart-thre-sibling-build-repro \
  --output build/evidence/regular-lod-uart-thre-sibling-profile-repro \
  --repeats 1 --timeout 900
```

The preferred MOS-side hypothesis is also qualified without installing or
distributing a patched firmware blob. A third builder changes the one uniquely
pinned byte in the old Console8 UART0 TX loop from `AND 0x40` (TEMT) to
`AND 0x20` (THRE), proves every other MOS byte unchanged, and runs the
unmodified accepted P3DRGL fixture. The 81,072-byte candidate MOS hashes to
`c8c347a7c04af35d6be51e0c85c5b50e689d923da39992d42880f4e88eba968c`;
its deterministic build receipt hashes to
`e4933d87de5207bd133ee388b7b1d24df130214f2921bb943ba742da30cb522d`.

Because this MOS-wide change affects every RST18 caller, ordinary call-return
spans do not leave equivalent transmitter state. The normative fresh pair uses
only read, upload-entry, and pre-render-submit breakpoints. For each record the
nth VDP publication must appear before its matching submit marker. Across all
227 records, upload-entry through publication-complete submit fell from
183,227,523 to 160,441,375 cycles (-12.4360 percent); read through the same
submit fell from 576,792,670 to 554,004,657 (-3.9508 percent). All four
normative/diagnostic runs retained the exact application, corpus, 227
publications, sequence-226 endpoint, and bounded stable shutdown tails. The
report is
`build/evidence/regular-lod-mos-uart-thre-sibling-profile-v1/regular-lod-mos-uart-thre-sibling-profile.json`
(SHA-256
`cd98b073f321e46b8e468359b8e5ef5ec944110f13789172e44e73c72e71493e`).
The diagnostic phase spans are explicitly non-completion-equivalent.

This is evidence for rebuilding the older pinned Console8 MOS in its owning
repository, not provenance for the historical binary and not permission to
install the patched image. The current reference MOS source already uses its
THRE constant. A source-level MOS build, repeated timing, CTS/FIFO stress, and
physical hardware qualification remain required before replacing the pinned
emulator image.

Reproduce the ignored binary proof and four-run profile with:

```bash
.venv/bin/python -B scripts/build_regular_lod_mos_uart_thre_sibling.py \
  --output build/evidence/regular-lod-mos-uart-thre-sibling-build-repro
.venv/bin/python -B scripts/profile_regular_lod_mos_uart_thre_sibling.py \
  --build build/evidence/regular-lod-mos-uart-thre-sibling-build-repro \
  --output build/evidence/regular-lod-mos-uart-thre-sibling-profile-repro \
  --timeout 900
```

The two independently qualified changes were then measured together without
creating a third code patch. The control combines the accepted 142,763-byte
P3DRGL program (`27f09db1eb0b0eec702aad5c17f35e68922f154a6c3391370d07a76027cc57bf`),
its symbols (`e4339e00adfdbd16969a6c77a76a77b00b4534ff3c572cf67395269d470670ce`),
and the pinned TEMT MOS
(`5fbacb749ee037f0428aeac39817b5a6d465adc020f92d4020bb7dcb046d39fe`).
The candidate combines the already-qualified register-held-CRC program
(`a4a88621ee4ed3af42ad6006bebf5e48037d19ad4375568b3b9032594f139992`),
its shifted symbols
(`ca1d7e0324388a71ffd74b6b55c9fc000000bc8fc136a88505c64b85ab13efbd`),
and the already-qualified one-byte THRE MOS
(`c8c347a7c04af35d6be51e0c85c5b50e689d923da39992d42880f4e88eba968c`).
The profiler pins both BUILD receipts and artifacts, resolves and verifies the
two program layouts independently, and proves that the candidate still uses
the ordinary three-RST18 upload path.

Four fresh emulator processes make the method and component pairing explicit:

| Run | Program | MOS | Breakpoints and purpose |
| --- | --- | --- | --- |
| Normative control | Accepted | TEMT control | Read, upload-entry, and matching submit only; publication-complete timing |
| Normative candidate | Register-held CRC | THRE candidate | Independently shifted read, upload-entry, and submit sites; publication-complete timing |
| Diagnostic control | Accepted | TEMT control | Five ordinary loader call/return spans; attribution only |
| Diagnostic candidate | Register-held CRC | THRE candidate | Five ordinary loader call/return spans; attribution only |

Each run revalidates the exact 227-file corpus before and after execution. Each
normative run records 681 ordered states and requires the exact nth VDP
publication marker to lie after upload entry and before its matching pinned
submit breakpoint. The exact 227-publication stream, sequence-226 endpoint,
and bounded mutation-free shutdown tail match in every run.

The publication-complete combined results are:

| Interval | Records | Control cycles | Candidate cycles | Delta cycles | Change |
| --- | ---: | ---: | ---: | ---: | ---: |
| Upload entry to matched submit | Loop 1--226 | 183,463,896 | 165,044,592 | -18,419,304 | -10.039743187400752% |
| Read entry to matched submit | Loop 1--226 | 575,316,551 | 339,189,102 | -236,127,449 | -41.043048142725866% |
| Upload entry to matched submit | All 227 | 184,209,569 | 165,874,159 | -18,335,410 | -9.953560012943736% |
| Read entry to matched submit | All 227 | 577,773,621 | 340,780,215 | -236,993,406 | -41.01838460361277% |

The separate diagnostic pair measured read-container at 260,752 versus
260,752 cycles (0 percent), validation at 387,855,111 versus 169,197,865
(-56.376012536289615 percent), mirror conversion at 5,542,107 versus 5,541,952
(-0.002796770253623757 percent), upload at 177,166,791 versus 157,716,944
(-10.978269059464987 percent), and command 50 at 979,334 versus 867,367
(-11.432973837322098 percent). The sum of those five spans is 571,804,095
versus 333,584,880 cycles (-41.66098443208946 percent). Every diagnostic
number, including that sum, is non-completion-equivalent because the MOS-wide
THRE change can leave a different transmitter state at an ordinary return.
They are attribution aids only, and the aggregate is not an additive
decomposition of the independently measured CRC and UART effects.

The checksum-bound report is
`build/evidence/regular-lod-crc-mos-uart-thre-combined-profile-v1/regular-lod-crc-mos-uart-thre-combined-profile.json`
(SHA-256
`e1cebf288d4fea4ebaf1674ad080715d75bda04a217f3c75daa89ccf4fa15c08`).
Reproduce it into an absent output directory with:

```bash
.venv/bin/python -B scripts/profile_regular_lod_crc_mos_uart_thre_combined.py \
  --output build/evidence/regular-lod-crc-mos-uart-thre-combined-profile-repro \
  --timeout 900
```

This is one fresh control/candidate pair in an emulator, not a repeatability or
hardware result. THRE means that the UART can accept another byte, not that the
transmitter is idle. The CRC sibling remains isolated and unpromoted, and the
derived MOS blob must not be installed or distributed. Promotion requires a
normal source rebuild in the MOS-owning repository, repeated measurements,
physical CTS/FIFO stress and timing qualification, and end-to-end hardware
presentation evidence.

### Nibble-table CRC follow-up

The next isolated CRC sibling replaces only the same hash-pinned validation
body with a 16-entry, 64-byte reflected CRC-32/ISO-HDLC nibble table. Two
unrolled nibble passes use eight `RRD` operations per DATA byte while keeping
the accepted loader, error order, math, protocol, launcher, and artifacts
unchanged. Its 142,988-byte program hashes to
`ae0a45869dde58e44bcdad82e0294c937c1ff81df1ce4aba142d2e60983812c8`;
the 90,683-byte BUILD receipt hashes to
`81158c512d31cfd0c7cd85af30e747953d7e4e8d73f9665f439a7cf56cb481d1`.
Host qualification covers deterministic CRC vectors, `123456789`, all 227
regular-view records / 764,288 DATA bytes, one deterministic bit corruption per
record, and the accepted padding/index/UV/CRC/descriptor-publication
precedence.

The live profile compares the already-qualified register CRC and nibble CRC
under the exact same THRE MOS. The direct entry-to-caller-post CRC boundary
fell from 159,091,349 to 99,457,317 guest cycles across all 227 records
(-59,634,032, -37.4841 percent). At the stricter publication-complete boundary,
read-to-own-submit fell from 338,969,553 to 277,614,315 cycles (-18.1005
percent), while upload-to-own-submit fell from 164,061,159 to 162,336,096
(-1.0515 percent). Every stored CRC, final buffer-relative `IX`, publication
shape/order, and sequence-226 endpoint matched. Candidate-only guest negatives
proved corrupt DATA returns error 9 with zero publication and a bad index with
a recomputed valid CRC returns error 10 before CRC entry, also with zero
publication.

The attempt history is part of the evidence. The first immutable attempt
stopped at record 8 because the strict gate saw submit with eight completed
publications before the ninth publication marker; the late marker remained in
the raw log. A single retry completed all four positive processes, then the old
shutdown-tail analyzer rejected render sequence 227 when `out` changed from 0
to 1. `out` is required timing/overhead accounting, not retained scene state;
the validator now still requires and records it but excludes it from structural
tail equality. All structural counters were identical. The finalizer
hash-revalidated the failed attempt and all 28 retry artifacts, reparsed the
four positive logs, and launched only the two missing negative processes. It
does not claim that all six successful runs came from one uninterrupted
invocation.

The final live report is
`build/evidence/regular-lod-crc-nibble-thre-sibling-profile-v3/regular-lod-crc-nibble-thre-sibling-profile.json`
(SHA-256
`fab87d454970f4ee8dccd9124af261c0c92cd927e896770ef3e2471dff706829`).
A separate read-only analyzer pins that report and the accepted+TEMT combined
baseline report, rehashes and reparses only their two relevant normative raw
logs, and proves identical emulator, VDP, manifests, 227-record identities,
logical method/boundaries, publication semantics, and endpoint. The cumulative
completion-equivalent read-to-publication-complete-own-submit total fell from
577,773,621 to 277,614,315 cycles for all 227 records (-300,159,306,
-51.9510 percent), and from 575,316,551 to 276,165,167 for loop records 1--226
(-299,151,384, -51.9977 percent). Its deterministic receipt is
`build/evidence/regular-lod-crc-nibble-cumulative-analysis-v1/regular-lod-crc-nibble-cumulative-analysis.json`
(9,596 bytes, SHA-256
`5ca055ea0194102bd1a8d46464c08c5122c0de0ba030c45a70113dc4e11687e7`),
generated by analyzer
`7088b0deb44da0c0e8d059f15d30e7b47bb2a3bda38eb528d87798b2befd2c3b`.
This cross-report result changes both CRC and MOS components and is not one
fresh pair.

No sibling is promoted. Repeatability remains open; Fab models `RRD` as four
cycles while UM0077 lists five on hardware. The candidate keeps BC, DE, HL,
and IX live through its inner body, so every asynchronous handler must continue
to preserve those registers. Promotion also requires a normal source rebuild
of the MOS THRE change, physical CRC timing, CTS/FIFO/UART stress, and complete
hardware presentation. THRE still means that the UART can accept another byte,
not that the transmitter is idle.

### Phase 2: isolate one production-shaped C seam

The first integration candidate is only
`regular_transition_select_feasible_group`. Assembly continues to edge-filter
source ordinals and produce a bounded descriptor for each pending group. Each
descriptor contains byte counts and source order; C selects one descriptor and
returns its source index. Assembly revalidates that answer before staging,
continues to own every identity/slot map and all I/O, and retains its accepted
selector as a fallback and A/B oracle.

AgonDev ELF objects cannot be linked directly into the accepted `ez80asm` flat
binary. The sibling therefore uses a separately linked, freestanding
fixed-address policy module. Its generated ABI includes a signature, version,
exact entry address, byte-size/hash receipt, and an assembly include generated
from the link map. Startup verifies the module before the first call; absence
or mismatch selects the assembly fallback without changing the world state.

The fixed module contract is reserved at `0x070000..0x07ffff`, with a
32-byte `FSIMCPOL` header and its selector entry at `0x070020`. The accepted
fixture currently ends at `0x062dab`; its largest file-data resource is 2,016
bytes, leaving more than 51 KiB before the module. The sibling builder proves
the actual program, resource/P3DM staging, module, and resident-launcher bounds
on every build. This static audit does not claim a measured dynamic stack
high-water mark; that remains part of the physical-hardware gate. The
module is a separate `CPOLICY.BIN`, loaded before ordinary fixture resources,
so omitted and deliberately corrupt modules can exercise the real assembly
fallback. It is not a second MOS application and contains no CRT, data, BSS,
MOS, VDP, floating-point, fixed-point, multiply, or divide dependency.

Its byte-only call contract is
`select(descriptor_pointer, descriptor_count, free_slots)`, where a descriptor
is `{retiring, entering, source_index}`, the count is at most 38, and each side
is at most 14. Source indices are `0..37`; `0xff` means no feasible group and
`0xfe` is reserved for invalid input. Assembly prevalidates and revalidates the
view, so C never owns a terrain identity or pointer.

The deterministic module qualifies at 301 bytes, ending at `0x07012d`.
Its selector is 255 bytes; the only compiler dependency is the exact 14-byte
`__frameset` member extracted from the pinned AgonDev `libagon.a` into the
ignored build tree. No third-party runtime source is copied into FSIM.
The pinned checkout exposes no root `LICENSE`, `COPYING`, or `NOTICE`; its
licensing status is therefore recorded as unknown and the archive is treated
only as a required local build input, never redistributed by this repository.
`CPOLICY.BIN` has SHA-256
`8c73781f71e9b335408659047047df6fb760f43bea0e67fc0580b7da32b78c71`
and CRC-32 `be23558a`. The ELF has one allocated executable section, no data or
BSS, no unresolved symbol, and its extracted load image is byte-identical to
the generated local runtime binary. Its authoritative ignored receipt is
`build/experiments/agondev-regular-policy/BUILD.json` (SHA-256
`9a397ce8c7a088486b5e1e13be989dbeb265cb1134cc8c723771a4fbd3f93845`).

Build it with:

```bash
.venv/bin/python -B scripts/build_agondev_regular_policy.py
```

Use the same command with `--verify-only` for a byte-preserving recheck of the
staged sources, module, ELF image, generated import include, and receipt.

No accepted launcher entry or fixture is overwritten. Source, module builder,
sibling fixture, and evidence use distinct names, and all generated ELF/raw
images remain under ignored `build/`.

### Phase 3: semantic and performance A/B

The sibling has four compile-time profiles over one production-shaped seam:

- `ASM_ONLY` retains the accepted recomputing selector;
- `DUAL_STRICT` compares C with the accepted assembly oracle and lets only the
  oracle control the transition;
- `C_GUARDED` uses a revalidated C result, latching any module/result fault to
  the accepted assembly fallback for the rest of the run; and
- `ASM_CACHED` uses native assembly over the same once-per-transition cache and
  packed three-byte descriptor view as C, without loading `CPOLICY.BIN`.

Host tests cover the bounded descriptor/count rules, ordering, malformed and
no-result sentinels, and a mirror of the selector over the generated recipes.
They do not claim exhaustive execution of the compiled C image. Live target
tests supply complementary evidence over cold Marina startup, the four-north
route, all six adjacent directions, and one clipped regional edge.

The accepted `P3DRGL.BIN` remains byte-exact at SHA-256
`27f09db1eb0b0eec702aad5c17f35e68922f154a6c3391370d07a76027cc57bf`.
Its tracked listing and symbols intentionally remain the frozen accepted-binary
debug sidecars because the accepted baseline and cold-load evidence hash them.
The new zero-byte policy hooks leave the executable exact but add label text to
a fresh listing/symbol emission. The sibling builder independently rebuilds
and checks the executable; replacing those accepted sidecars would require a
corresponding baseline-evidence recapture.
The mode binaries are:

- `ASM_ONLY`: 144,172 bytes, SHA-256
  `ca85793ca3687e1ac8657d1dae5e44ab0e7d1ecbffa4425632030aec6d06d836`;
- `DUAL_STRICT`: 144,177 bytes, SHA-256
  `fa463e862f1bb0602f7e67ff8855ac20aa5c2974dc87408007a1914fd700cc07`;
- latched `C_GUARDED`: 144,184 bytes, SHA-256
  `ed117101bc1ac1bb64a9e1ffd2726c8ba031f2f021bcdb8b9850312f37d817d5`;
  and
- `ASM_CACHED`: 144,465 bytes, SHA-256
  `8c7adb63717a17730e63e8fa48a1fc323f743c240db8de0caf1c0cd5738ca3a9`.

The sibling's actual resource staging ends at `0x063b11`, below the module at
`0x070000..0x07012c`. Its builder rebuilds and checksum-checks the current
accepted include closure, pins the selected mode source/include and module
receipt, and verifies both 114-byte descriptor-buffer spans plus the static
program/resource/module/launcher bounds. The refreshed canonical dual receipt
has SHA-256
`d956379e841e7730fe1c18b8351b0f16f7c64edbf1d9b0f6849d7a9bb6fa05e4`.

Build the canonical dual sibling before using the live qualifiers; this also
regenerates the ignored listing and symbol file that their default paths use:

```bash
.venv/bin/python -B scripts/build_regular_lod_c_policy_survey.py \
  --skip-module-build --policy-mode dual-strict
```

The exact all-neighbor and clipped-edge gates are:

```bash
.venv/bin/python -B scripts/qualify_regular_lod_c_policy_six_directions.py \
  --expected-policy-mode dual-strict \
  --output build/evidence/regular-lod-c-policy-six-directions-dual
.venv/bin/python -B scripts/qualify_regular_lod_c_policy_regional_edge.py \
  --policy-mode dual-strict \
  --output build/evidence/regular-lod-c-policy-regional-edge-dual
.venv/bin/python -B scripts/qualify_regular_lod_c_policy_fault_latch.py \
  --output build/evidence/regular-lod-c-policy-fault-latch
```

An explicitly built guarded binary and symbols can be passed to the first
command with `--program`, `--symbols`, and
`--expected-policy-mode c-guarded`; the edge qualifier builds its requested
mode in a private scratch tree itself.

Fresh four-north runs cover the same 29, 21, 17, and 17 groups in every mode.
`DUAL_STRICT` made 84 C calls and matched the oracle 84 times. Healthy
`C_GUARDED` made 84 C calls without invoking the oracle. `ASM_CACHED` made no C
call and staged no module. All reached the exact same final owner/slot state;
none replaced an active mesh or rendered inside a group commit. Omitting the
module, corrupting its header, and corrupting only its body produced distinct
status codes 3, 4, and 5 and retained the assembly fallback. A scratch-only
fault gate then forced the first C result to invalid `0xfe`: it observed one C
call and one candidate fallback, latched failure before staging, routed the
remaining 25 groups through accepted assembly, and still reached the exact
129-owner clipped-edge endpoint without an active replacement or render inside
a commit. Two runs shared deterministic-live SHA-256
`67e2e280e88b87357d69ffba8d3385ea8ea6f409c9722fc49bdc39f2f17fae59`;
the primary report is
`build/evidence/regular-lod-c-policy-fault-latch-v3/regular-lod-c-policy-fault-latch.json`
(SHA-256
`cfe576f73a0827456955b511baf753879d13112ab75ba718ab56c661162985e3`).

All six directions passed in fresh processes for both dual and guarded modes.
The direction group counts are north/south/northeast/southeast/northwest/
southwest = 29/17/26/15/20/22. The normalized dual report is
`build/evidence/regular-lod-c-policy-six-directions-dual-v4/regular-lod-c-policy-six-directions.json`
(SHA-256
`12c9545edce65010e32fc4d57fae475c858500f75b2125ce63851c30cb88f636`);
the guarded report is
`build/evidence/regular-lod-c-policy-six-directions-guarded-v1/matrix/regular-lod-c-policy-six-directions.json`
(SHA-256
`a8512452f52726b9a5b7aa088ed0aa05f8dc8821175ac305c8781114f9c3043f`).

The western clipped-edge witness `(0,117) -> (1,117)` also passed both modes.
It scans 159 source ordinals for a 129-owner endpoint, selects all 26 raw recipe
groups including 11 clipped-empty no-ops, commits 15 nonempty groups, and ends
with an identical owner/slot/transform hash. Its dual and guarded reports have
SHA-256
`fcdac36357a112f13fd77c439a6e34fce9a3081bc52eaac3db92eb080107283c`
and
`1fa4b6f434c40673a83341518c84ad70d1fd25b3ee872dc8febe532855678b4b`,
respectively.

The architecture-matched cycle comparison is
`build/evidence/regular-lod-policy-selector-ab-v3.json` (SHA-256
`c90e87adeaa9c853c0b4efb044ebe2ab3551cb89c5051b7bfcda50a862aba479`).
Across 84 selector calls, accepted assembly used 736,928 guest cycles with a
median of 8,375.5; guarded C used 484,496 with a median of 5,454.5; and cached
assembly used 438,539 with a median of 4,926.0. Holding the cache and packed
descriptor architecture fixed, cached assembly used 9.486 percent fewer total
selector-call cycles than guarded C and 40.491 percent fewer than the accepted
selector. Three independent current runs per candidate bound total-cycle
variation to 0.030 percent for guarded C and 0.039 percent for cached assembly.
This isolates the main lesson: most of the earlier C win came from caching the
edge topology, while native assembly remains faster at the tiny selector once
the data path is equal.

The resident-image comparison is 142,763 bytes for accepted assembly, 144,485
for guarded C including its 301-byte module, and 144,465 for `ASM_CACHED`.
`ASM_CACHED` still links unreachable common module-loader, CRC, and C-call
routines, so its 20-byte advantage over guarded C is a profile-specific image
witness, not an optimized native-only size claim.

These runs intentionally measure guest cycles only from the selector call site
through its return. The once-per-transition cache build, complete handoff,
SD/FatFS latency, validation, UART/VDP staging, renderer time, and physical
hardware are outside that span. Full-pipeline timing and human gates therefore
remain open; every sibling mode is still evidence rather than a launcher or
production choice.

Promotion requires exact owner/slot/transform equivalence, no active mesh
overwrite, no render inside a commit, and no new compiler arithmetic helper.
Report module bytes, selector bytes, call frequency, target elapsed time, total
handoff time, steady frame rate, and SD/VDP traffic separately. C is useful
only if the policy is materially easier to maintain without a meaningful
runtime regression. Failure is retained as evidence and the accepted assembly
fixture remains unchanged.

### Phase 4: human gates

The standalone program and any visually meaningful sibling fixture still need
physical-hardware confirmation. That gate can wait while the isolated host and
headless measurements proceed; it does not block reversible implementation or
evidence gathering.
