# ADL=1 Fixed-Width Donor Audit

Date: 2026-08-02

## Result

The audited donor snapshot contains **no demonstrated unabsorbed third-byte
write** in the selected code. Its apparent writes to `dw` fields are mostly a
deliberate packet-building idiom: an unsuffixed ADL-mode `ld (nn),rr` writes
three bytes, with the extra byte overwritten by the next field, explicitly
repaired, or deposited in a byte after `@end` that is not transmitted.

One interface remains too implicit to copy unchanged: five content-distinct
versions (seven physical copies) of `vdu_load_buffer` save and reload `BC`
through `@length: dw 0` plus an excluded pad byte. This preserves `BCU`, even
though the VDU wire field is only 16 bits. Every audited caller currently
supplies a block no larger than 8192 bytes, so this is not a reproduced bug;
it is an undocumented upper-byte precondition that should be made explicit or
removed in reusable code.

## Scope and counting

Recursively scanned assembly (`*.asm`, `*.inc`) under:

- `pingoasm/tests/apps/_common`
- `pingoasm/apps/earth-party-flat`
- `pingoasm/tests/apps/moveair-local`
- `pingoasm/tests/apps/movefsim`
- `agon-utils/examples/agnb`

The scan selected unsuffixed memory/register loads whose register operand was
`HL`, `BC`, `DE`, `IX`, `IY`, or `SP`. It found 1,114 instruction sites after
SHA-256 content deduplication: 112 physical source files collapsed to 74
unique-content representatives. This avoids multiplying findings from vendored
copies. The lexical declaration buckets were:

| Declared target | Sites | Interpretation |
| --- | ---: | --- |
| `dw` | 295 | 290 stores, 5 loads; packet packing except for the length contract below |
| `dw24` | 17 | native 24-bit storage |
| `dl` | 481 | native 24-bit storage |
| `db` | 9 | intentional adjacent-byte packing |
| `ds` | 35 | storage of at least three bytes in the audited cases |
| `blkb` | 16 | storage of at least six bytes in the audited cases |
| external, `equ`, or indirect | 261 | resolved by inspecting the pointee/calling contract where relevant |

This is an instruction-site inventory, not a proof generated from assembled
addresses. The semantic classifications below were made by inspecting packet
boundaries, repairs, declarations, and call sites.

## Exact evidence

### Deliberate packed packet writes

- `pingoasm/apps/earth-party-flat/src/vdu_pingo.inc:206-221` stores camera
  `x/y/z` with `BC/DE/IY`. Each store overwrites the prior upper byte; the last
  upper byte lands in the padding byte at `@end`, excluded by `@end-@beg`.
- `pingoasm/apps/earth-party-flat/src/vdu_pingo.inc:333-345` writes a mesh ID
  to `dw`, then restores the mode byte with `ld (@mode),a`.
- `pingoasm/apps/earth-party-flat/src/vdu_pingo.inc:459-475` writes a buffer
  ID and explicitly repairs the command byte at `@bufferId+2`. This is the
  required pattern when a third byte would otherwise corrupt the packet.
- `pingoasm/apps/earth-party-flat/src/vdu_pingo.inc:509-516` lets the upper
  byte of `HL` land in an excluded pad after the bitmap-select packet.
- `pingoasm/apps/earth-party-flat/src/vdu_pingo.inc:527-538` chains width and
  height stores, then restores the format byte.
- `pingoasm/apps/earth-party-flat/src/vdu_pingo.inc:547-570` and `:603-608`
  repair both command bytes overwritten by buffer-ID stores.
- `pingoasm/apps/earth-party-flat/src/agon/vdu_plot.inc:203-221` restores the
  second plot opcode after the `y0` store overwrites it.
- `pingoasm/apps/earth-party-flat/src/agon/vdu_sound.inc:324-352` restores the
  sound opcodes overwritten by the buffer-ID and sample-rate stores and ends
  with excluded padding.
- `pingoasm/apps/earth-party-flat/src/agon/vdu_buffered_api.inc:11-28`,
  `:261-285`, `:292-304`, and `:311-323` show the same three accepted forms:
  explicit repair, chained overwrite, and excluded final padding.
- `pingoasm/apps/earth-party-flat/src/agon/vdu_fonts.inc:11-20` and `:26-44`
  explicitly restore fields after the wide stores.
- `agon-utils/examples/agnb/api/agnb_dependencies.inc:100-110` documents the
  excluded-pad form directly; `:128-145` does likewise for the final `DEU`
  byte of a sample-rate store.

The nine stores lexically aimed at `db` fields are also intentional packing.
For example, `_common/vdu_pingo.inc:1034-1045` writes `BC` over cursor `x`,
`y`, and an excluded pad. Font width/height and similar byte pairs use the
same idea.

### Native 24-bit state

- `pingoasm/tests/apps/moveair-local/src/jet.asm:146`, `:199-217`, and
  `:251-256` access `simulation_accumulator`, declared with `dl` at `:326`.
- `pingoasm/apps/earth-party-flat/src/earth-party.asm:327`, `:579-597`, and
  `:633-638` use the analogous native 24-bit accumulator.
- `pingoasm/apps/earth-party-flat/src/agon/timer.inc:293-295` declares its
  timestamp with `dl`; timer records addressed through `IY` contain explicit
  three-byte fields at offsets 0 and 3.
- AGNB's generated loose-image records are native 24-bit throughout:
  `images/loose/src/asm/images.inc:3-8` gives each field a stride of three and
  `:264-265` begins a table of `dl` records. Therefore the indirect loads in
  `images/loose/src/asm/app.asm:108-111` are safe 24-bit loads.

AGNB's 16-bit metadata reads are deliberately normalized after an ADL
three-byte read. For example, `api/agnb_api.inc:938-941` loads a two-byte
buffer ID and then uses `dec hl` / `inc.s hl` to clear `HLU`. The behavior and
toolchain caveat are documented in `examples/agnb/docs/ez80_hacks.md:8-61`.

### The unresolved reusable contract

The five unique implementations are:

- `agon-utils/examples/agnb/api/agnb_dependencies.inc:49-68`
- `agon-utils/examples/agnb/audio/src/asm/includes.inc:212-232`
  (content-identical to the container-image copy)
- `agon-utils/examples/agnb/images/loose/src/asm/includes.inc:215-235`
- `agon-utils/examples/agnb/images/loose/src/asm/vdu.inc:308-328`
- `pingoasm/apps/earth-party-flat/src/agon/vdu.inc:494-517`
  (content-identical to the `moveair-local` copy)

Each performs both:

```asm
    ld (@length),bc
    ; ...
    ld bc,(@length)
```

where `@length` is declared `dw` and immediately followed by an excluded pad.
Thus it is physically safe but preserves all 24 bits. The API comment only
says `BC=length`; it does not state that `BCU` must be zero even though the
wire packet carries a 16-bit length.

For a reusable exact-width helper, prefer:

```asm
    ld a,c
    ld (@length),a
    ld a,b
    ld (@length+1),a

    ; Later: reload a zero-extended uint16.
    ld bc,0
    ld a,(@length)
    ld c,a
    ld a,(@length+1)
    ld b,a
```

Alternatively, retain the packed scratch byte but document and enforce
`BCU=0` and `BC <= 65535` at the entry point.

## Import policy

1. In ADL=1, `dw` controls allocation only. It does not make an unsuffixed
   wide-register memory `ld` operate on two bytes.
2. Use bytewise access for protocol `uint16` fields by default. Use native
   unsuffixed wide loads/stores for `dl`, `dw24`, pointers, and documented
   three-byte work fields.
3. A packed packet store is acceptable only when every upper byte is accounted
   for: overwritten by the next store, repaired before transmission, or placed
   in an allocated pad outside the transmitted `[begin,end)` range.
4. A three-byte read used as `uint16` must have a readable byte at `+2` and
   must explicitly normalize the upper byte. The `dec rr` / `inc.s rr` idiom
   is valid for the Agon toolchain, but bytewise reads are clearer at exact
   two-byte boundaries.
5. Annotate intentional cases locally with the checker-recognized form, for
   example `; ADL24 OK: packed +2 byte is repaired below` or `; ADL24 OK: dl
   state is natively 24-bit`. This makes review and lint suppressions auditable.
6. CI should flag unsuffixed memory/wide-register `ld` instructions unless the
   target is proven at least three bytes or carries an intentional annotation.
7. Packet tests should seed all register upper bytes to non-zero canaries and
   compare the complete transmitted byte stream, including the byte just after
   the declared packet.

No files in `pingoasm` were modified during this audit.
