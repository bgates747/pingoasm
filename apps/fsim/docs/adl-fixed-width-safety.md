# ADL Fixed-Width Memory Safety

Status: accepted project rule and executable audit, 2026-08-02

## Invariant

In `.assume adl=1`, unsuffixed memory transfers involving `BC`, `DE`, `HL`,
`IX`, `IY`, or `SP` are 24-bit operations. `dw` allocates two bytes but has no
effect on instruction width. Every load and store must therefore be classified
by the width of the pointed-to storage, not by the source declaration's visual
appearance.

New code uses bytewise little-endian access for exact `u16` fields. Native
unsuffixed multibyte access is reserved for `dl`/`dw24`, pointers, timers,
fixed-point values, and explicitly three-byte work storage. A deliberate
packed access must account for byte `+2` and carry a local
`ADL24 OK: <reason>` annotation.

Short-data suffixes are not the general solution. `.SIS`/`.SIL` operate the
data block in Z80 mode and address memory through MBASE; `.SIL` can contain a
long address in the instruction stream and still replace its upper byte with
MBASE at execution. Byte operations preserve the arbitrary 24-bit address and
cannot touch a third data byte.

The reusable Agon rule and exact store/load examples are maintained in
`~/Agon/mystuff/agon-dev-env/codex/assembly.md`. The authoritative processor
reference is local Zilog manual
`~/Agon/docs/UM0077-eZ80-CPU-User-Manual.pdf`, especially “Opcode Suffixes for
Memory Mode Control” and “Risks with Using the .SIL Suffix.”

## Failure that established the rule

The patterned Berkeley fixture originally patched this command in place:

```asm
    ld (@bufferId),hl
@bufferId: dw 0
    db 14               ; consolidate
```

The ADL store wrote `L`, `H`, and `HLU`. With `HLU=0`, command 14 became
command 0, so subsequent command bytes were parsed as a buffered upload. That
desynchronized resource setup and produced the observed early VDP failure.
Restoring command byte 14 proved the diagnosis; the final repair now writes
the two buffer-ID bytes individually and never touches the opcode.

## Local remediation

The three preserved Berkeley fixture helpers were audited independently.
Their app-local `vdu_pingo.inc` snapshots contained 25 packed word accesses
each, plus the dither fixture's consolidate access. All were replaced with
exact two-byte stores, including camera/object coordinates, mesh IDs, bitmap
IDs and dimensions, and upload packet IDs. This removes reliance on chained
overwrites, upper-register contents, excluded padding, and later repair.

Two additional reusable hazards were removed from all three vendored `agon`
snapshots:

- `LD_HL_mn`, `LD_BC_mn`, `LD_DE_mn`, `LD_IX_mn`, and `LD_IY_mn` now read two
  bytes individually and explicitly zero the destination upper byte. Their old
  implementation read byte `addr+2` and normalized the result afterward.
- `vdu_load_buffer` now stores and reloads its 16-bit length bytewise with a
  zeroed `BCU`. Its old `dw` plus excluded-pad implementation silently carried
  the caller's `BCU` into the 24-bit MOS send length.

The broader read-only donor inspection is recorded in
[`adl-fixed-width-donor-audit.md`](adl-fixed-width-donor-audit.md). It covered
112 physical files, 74 unique source contents, and 1,114 unsuffixed wide
memory-access sites across the relevant PingoASM and AGNB paths. Its 290 direct
`dw` stores were accounted for as chained packet packing, explicit repair, or
excluded padding; five `dw` loads exposed the reusable length contract above.
PingoASM was not modified.

## Executable guard

Run the checker over an entry assembly file's actual include closure:

```bash
.venv/bin/python scripts/audit_adl_width.py --follow-includes \
  --show-review --fail-review \
  fixtures/berkeley-flight-triangular-dither/src/berkeley-flight-triangular-dither.asm
```

The checker resolves local and unique cross-include storage declarations,
fails a 24-bit access to named `dw` or shorter storage, and inventories
register-indirect or unresolved targets. An intentional indirect/native
24-bit operation must be reviewed and annotated with a nonempty reason. The
regression suite contains positive and negative checker fixtures and audits the
approved dither scene on every run.

The checker is deliberately conservative rather than a complete assembler. It
does not infer arbitrary pointer pointees or prove packet control flow. Those
cases remain human-reviewed contracts, made visible by `--fail-review`.

## Acceptance evidence

The approved dither fixture's include closure contains 41 files and 23
wide-register memory accesses: 21 resolve to native 24-bit storage and two are
reviewed register-indirect native 24-bit fields. It has zero definite overruns
and zero unreviewed accesses.

All three fixture sources assemble after the remediation. A silent headless
capture of the rebuilt dither fixture produced RGBA2222 SHA-256
`b234d54e166ce74e40f39bdb3ae25836efbfda1003706629e48e89e54320f86c`,
bit-for-bit identical to the visually approved pre-remediation frame. Evidence
is retained at `/tmp/pingo-terrain-adl-u16-capture-20260802` for this session.

## Arithmetic-width extension: `MLT` does not clear the upper byte

The memory-transfer rule above is necessary but not sufficient. UM0077's
`MLT rr` definition is explicitly an 8-bit by 8-bit multiply with a 16-bit
result regardless of ADL mode: only `rr[15:0]` is replaced. In ADL mode the
long register's upper byte is therefore not initialized by `MLT`. A later
unsuffixed 24-bit operation can consume stale `BCU`, `DEU`, or `HLU` even when
the multiplication itself produced the expected low word.

The first family-LOD coordinator exposed this exact pattern. Its table lookup
formed `DE = index * 17` with `MLT DE`, then used unsuffixed `ADD HL,DE` to make
a 24-bit pointer. Assigning only `D` and `E` did not define `DEU`. The accepted
form clears the complete ADL register before filling the multiplier bytes:

```asm
    ld de,0
    ld e,a
    ld d,family_plan_entry_size
    mlt de
    ld hl,family_plan_table
    add hl,de
```

This establishes an additional audit rule for all new and reused assembly:

1. inventory every `MLT BC`, `MLT DE`, `MLT HL`, and `MLT SP`;
2. trace each result to its next full-register initialization;
3. if the result reaches long arithmetic, an address calculation, a pointer,
   or an unsuffixed long store, prove the upper byte was initialized first; and
4. prefer a full-register zero immediately before loading the two multiplier
   bytes, so the proof is local and survives caller changes.

A short-mode arithmetic suffix is not evidence that a later long consumer is
safe. The upper byte must still be initialized before the value crosses into a
24-bit operation. `scripts/audit_adl_width.py` now implements the conservative,
straight-line high-confidence form of this rule. Within one local scope it
tracks whether a full 24-bit pair load established a zero upper byte, records a
subsequent `MLT rr`, recognizes the established short `INC`/`DEC` normalization
idiom, and reports `upper-byte-address` if that product reaches an unsuffixed
24-bit `ADD HL,rr` with no upper-byte proof. State is discarded at nonlocal
scope and control-flow/exchange boundaries rather than guessed across them.

Focused checker tests cover the stale-upper failure, explicit full-register
zeroing, a genuinely short add, and short normalization before a later long
add. The family fixture also retains its local source-order regression, and its
complete include closure now has zero definite audit hazards. This is not a
general control-flow/dataflow proof: aliases, branches, macros with nonlocal
effects, and other long consumers still require the mandatory manual MLT audit
above.
