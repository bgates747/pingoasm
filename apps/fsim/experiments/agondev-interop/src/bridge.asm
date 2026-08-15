; FSIM AgonDev C/assembly ABI probe.
;
; Every C argument up to 24 bits occupies a three-byte caller-owned slot.
; After this conventional IX frame, argument starts are IX+6 and IX+9.

    .assume adl=1
    .section .text

    .global _asm_stamp_state
    .global _asm_policy_round_trip
    .global _asm_select_feasible_group
    .global _asm_return_u16
    .global _asm_return_u24
    .extern _interop_choose_action

    .equ interop_asm_stamp_offset, 10
    .equ interop_group_retiring_offset, 0
    .equ interop_group_entering_offset, 1
    .equ interop_group_processed_offset, 2
    .equ interop_group_bytes, 3
    .equ interop_group_max_count_plus_one, 9
    .equ interop_group_max_side_plus_one, 15
    .equ interop_group_score_bias, 16
    .equ interop_group_none, 0xff

    .equ asm_select_selected_index, -1
    .equ asm_select_selected_score, -2
    .equ asm_select_selected_entering, -3
    .equ asm_select_selected_retiring, -4
    .equ asm_select_source_index, -5
    .equ asm_select_remaining, -6
    .equ asm_select_free_slots, -7
    .equ asm_select_local_bytes, 7

; void asm_stamp_state(interop_probe_state *state, uint8_t stamp)
_asm_stamp_state:
    push ix
    ld ix,0
    add ix,sp
    ld hl,(ix+6)
    ld a,(ix+9)
    ld de,interop_asm_stamp_offset
    add hl,de
    ld (hl),a
    ld sp,ix
    pop ix
    ret

; uint8_t asm_policy_round_trip(const interop_probe_state *state)
;
; Republish the pointer as one three-byte C argument. The caller removes that
; slot. interop_choose_action returns uint8_t in A, which POP/IX teardown leave
; unchanged for our own C caller.
_asm_policy_round_trip:
    push ix
    ld ix,0
    add ix,sp
    ld hl,(ix+6)
    push hl
    call _interop_choose_action
    pop hl
    ld sp,ix
    pop ix
    ret

; uint8_t asm_select_feasible_group(const interop_group_record *groups,
;                                   uint8_t group_count,
;                                   uint8_t free_slots)
;
; The three C arguments begin at IX+6, IX+9, and IX+12. IY walks fixed
; three-byte records. Locals retain the best lexicographic key; exact ties do
; not replace it, preserving source order. Invalid count-domain records are
; skipped before the biased byte score is formed.
_asm_select_feasible_group:
    push ix
    ld ix,0
    add ix,sp
    ld hl,-asm_select_local_bytes
    add hl,sp
    ld sp,hl

    ld (ix+asm_select_selected_index),interop_group_none
    xor a
    ld (ix+asm_select_selected_score),a
    ld (ix+asm_select_selected_entering),a
    ld (ix+asm_select_selected_retiring),a
    ld (ix+asm_select_source_index),a

    ld iy,(ix+6)
    ld a,(ix+9)
    cp a,interop_group_max_count_plus_one
    jr nc,.asm_select_done
    ld (ix+asm_select_remaining),a
    ld a,(ix+12)
    ld (ix+asm_select_free_slots),a

    push iy
    pop hl
    ld de,0
    or a,a
    sbc hl,de
    jr z,.asm_select_done

.asm_select_group:
    ld a,(ix+asm_select_remaining)
    or a,a
    jr z,.asm_select_done
    ld a,(iy+interop_group_processed_offset)
    or a,a
    jr nz,.asm_select_advance

    ld e,(iy+interop_group_entering_offset)
    ld a,e
    cp a,interop_group_max_side_plus_one
    jr nc,.asm_select_advance
    ld d,(iy+interop_group_retiring_offset)
    ld a,d
    cp a,interop_group_max_side_plus_one
    jr nc,.asm_select_advance
    ld a,(ix+asm_select_free_slots)
    cp a,e
    jr c,.asm_select_advance

    ld a,d
    sub a,e
    add a,interop_group_score_bias
    ld b,a
    ld a,(ix+asm_select_selected_index)
    cp a,interop_group_none
    jr z,.asm_select_choose
    ld a,(ix+asm_select_selected_score)
    cp a,b
    jr c,.asm_select_choose
    jr nz,.asm_select_advance
    ld a,(ix+asm_select_selected_entering)
    cp a,e
    jr c,.asm_select_advance
    jr nz,.asm_select_choose
    ld a,(ix+asm_select_selected_retiring)
    cp a,d
    jr c,.asm_select_choose
    jr .asm_select_advance

.asm_select_choose:
    ld a,(ix+asm_select_source_index)
    ld (ix+asm_select_selected_index),a
    ld a,b
    ld (ix+asm_select_selected_score),a
    ld a,e
    ld (ix+asm_select_selected_entering),a
    ld a,d
    ld (ix+asm_select_selected_retiring),a

.asm_select_advance:
    lea iy,iy+interop_group_bytes
    inc (ix+asm_select_source_index)
    dec (ix+asm_select_remaining)
    jr .asm_select_group

.asm_select_done:
    ld a,(ix+asm_select_selected_index)
    ld sp,ix
    pop ix
    ret

; uint16_t asm_return_u16(void) -- returned in HL, with UHL cleared.
_asm_return_u16:
    ld hl,0x00beef
    ret

; uint24_t asm_return_u24(void) -- returned in UHL.
_asm_return_u24:
    ld hl,0xabcdef
    ret
