; Fixed-address AgonDev policy client for the experimental regular-LOD sibling.
;
; The accepted P3DRGL appliance does not include this file.  The P3DRGLC
; sibling supplies the generated module ABI and exactly one mode include before
; this common implementation.  The available modes are:
;   0 = ASM_ONLY, 1 = DUAL_STRICT, 2 = C_GUARDED, 3 = ASM_CACHED.
;
; Assembly remains authoritative for edge filtering, identities, slots, I/O,
; and transition state.  DUAL_STRICT runs the accepted selector as an oracle;
; C_GUARDED retains it only as a fault fallback.  C receives only bounded
; {retiring,entering,source} records.

regular_policy_mode_asm_only: equ 0
regular_policy_mode_dual_strict: equ 1
regular_policy_mode_c_guarded: equ 2
regular_policy_mode_asm_cached: equ 3

regular_policy_begin_transition:
    REGULAR_POLICY_BEGIN_ROUTINE
regular_policy_select_feasible_group:
    REGULAR_POLICY_SELECT_ROUTINE

regular_policy_module_status_unavailable: equ 0
regular_policy_module_status_ready: equ 1
regular_policy_module_status_mos_no_carry: equ 2
regular_policy_module_status_mos_error: equ 3
regular_policy_module_status_header: equ 4
regular_policy_module_status_crc: equ 5

; Load the separate, freestanding policy image before any scene resource uses
; MOS LOAD.  A missing or malformed capability is fail-soft: selector calls
; retain the assembly result and never jump into the module.
regular_policy_initialize:
    xor a
    ld (regular_policy_module_status),a
    ld (regular_policy_qualification_failure),a
    ld (regular_policy_selector_calls+0),a
    ld (regular_policy_selector_calls+1),a
    ld (regular_policy_selector_calls+2),a
    ld (regular_policy_selector_matches+0),a
    ld (regular_policy_selector_matches+1),a
    ld (regular_policy_selector_matches+2),a

; ASM_CACHED returns here.  The other profiles fall through to the exact
; historical module load/qualification path.  Keeping this mode hook in the
; profile include makes module independence a static build property.
    REGULAR_POLICY_MODULE_INITIALIZE

; Clear the exact claimed image first.  A short or failed MOS read cannot leave
; a previous module instance looking valid.
    ld hl,fsim_regular_policy_load_address
    ld bc,fsim_regular_policy_image_bytes
@clear:
    xor a
    ld (hl),a
    inc hl
    dec bc
    ld a,b
    or c
    jr nz,@clear

    ld hl,regular_policy_filename
    ld de,fsim_regular_policy_load_address
    ld bc,fsim_regular_policy_image_bytes
    MOSCALL mos_load
; MOS LOAD reports a successful FatFS read with carry set and A=0.
    jr nc,@mos_no_carry
    or a
    jr nz,@mos_error

; Compare every byte of the generated 32-byte header, including exact image
; size, load/entry addresses, ABI limits, and distinct NONE/INVALID returns.
    ld hl,fsim_regular_policy_load_address
    ld de,regular_policy_expected_header
    ld b,fsim_regular_policy_header_bytes
@header:
    ld a,(de)
    cp (hl)
    jr nz,@bad_header
    inc de
    inc hl
    djnz @header
    call regular_policy_validate_crc32
    jr nz,@bad_crc
    ld a,regular_policy_module_status_ready
    ld (regular_policy_module_status),a
    xor a
    ret

@mos_no_carry:
    ld a,regular_policy_module_status_mos_no_carry
    jr @unavailable
@mos_error:
    ld a,regular_policy_module_status_mos_error
    jr @unavailable
@bad_header:
    ld a,regular_policy_module_status_header
    jr @unavailable
@bad_crc:
    ld a,regular_policy_module_status_crc
@unavailable:
    ld (regular_policy_module_status),a
    xor a
    ret

; Reflected CRC-32/ISO-HDLC over the exact generated module image.
regular_policy_validate_crc32:
    ld a,0FFh
    ld (regular_policy_crc_value+0),a
    ld (regular_policy_crc_value+1),a
    ld (regular_policy_crc_value+2),a
    ld (regular_policy_crc_value+3),a
    ld ix,fsim_regular_policy_load_address
    ld bc,fsim_regular_policy_image_bytes
@byte:
    ld a,b
    or c
    jr z,@finish
    push bc
    ld a,(ix)
    inc ix
    ld hl,regular_policy_crc_value
    xor (hl)
    ld (hl),a
    ld b,8
@bit:
    ld hl,regular_policy_crc_value+3
    srl (hl)
    dec hl
    rr (hl)
    dec hl
    rr (hl)
    dec hl
    rr (hl)
    jr nc,@no_polynomial
    ld a,(regular_policy_crc_value+0)
    xor 020h
    ld (regular_policy_crc_value+0),a
    ld a,(regular_policy_crc_value+1)
    xor 083h
    ld (regular_policy_crc_value+1),a
    ld a,(regular_policy_crc_value+2)
    xor 0B8h
    ld (regular_policy_crc_value+2),a
    ld a,(regular_policy_crc_value+3)
    xor 0EDh
    ld (regular_policy_crc_value+3),a
@no_polynomial:
    djnz @bit
    pop bc
    dec bc
    jr @byte
@finish:
    ld b,4
    ld hl,regular_policy_crc_value
@complement:
    ld a,(hl)
    cpl
    ld (hl),a
    inc hl
    djnz @complement
    ld a,(regular_policy_crc_value+0)
    cp fsim_regular_policy_crc32_0
    ret nz
    ld a,(regular_policy_crc_value+1)
    cp fsim_regular_policy_crc32_1
    ret nz
    ld a,(regular_policy_crc_value+2)
    cp fsim_regular_policy_crc32_2
    ret nz
    ld a,(regular_policy_crc_value+3)
    cp fsim_regular_policy_crc32_3
    ret

; Edge filtering is invariant throughout one transition: old/target identity
; maps change only at complete group commits, and membership counts are based
; on identity presence rather than physical slot assignment.  Compute the
; complete indexed descriptor view once immediately after recipe selection.
; ASM_ONLY and an unavailable C mode skip the work entirely.  ASM_CACHED emits
; its unconditional sibling entry through its mode-only routine macro.
regular_policy_prepare_cached_descriptors:
    xor a
    ld (regular_policy_descriptors_ready),a
    ld a,(regular_policy_module_status)
    cp regular_policy_module_status_ready
    jr nz,@skip
    call regular_policy_build_all_descriptors
    ret c
    ld a,1
    ld (regular_policy_descriptors_ready),a
@skip:
    xor a
    ret

regular_policy_build_all_descriptors:
    ld hl,(regular_transition_groups_pointer)
    ld (regular_policy_scan_group_pointer),hl
    ld hl,regular_policy_all_descriptors
    ld (regular_policy_descriptor_pointer),hl
    xor a
    ld (regular_policy_source_index),a
@group:
    ld a,(regular_policy_source_index)
    ld b,a
    ld a,(regular_transition_group_count)
    cp b
    jp z,@done
    ld hl,(regular_policy_scan_group_pointer)
    push hl
    pop ix
    ld a,(ix+regular_lod_transition_group_retiring_count)
    ld (regular_transition_raw_retire_count),a
    ld a,(ix+regular_lod_transition_group_entering_count)
    ld (regular_transition_raw_enter_count),a
    xor a
    ld (regular_transition_actual_retire_count),a
    ld (regular_transition_actual_enter_count),a
    push ix
    pop hl
    ld de,regular_lod_transition_group_ordinals
    add hl,de
    ld (regular_transition_scan_ordinal_pointer),hl
    ld a,(regular_transition_raw_retire_count)
    ld (regular_transition_scan_remaining),a
@old:
    ld a,(regular_transition_scan_remaining)
    or a
    jr z,@new_begin
    ld hl,(regular_transition_scan_ordinal_pointer)
    ld a,(hl)
    inc hl
    ld (regular_transition_scan_ordinal_pointer),hl
    call regular_transition_old_slot_pointer
    ld a,(hl)
    cp regular_provider_unassigned_slot
    jr z,@old_next
    ld hl,regular_transition_actual_retire_count
    inc (hl)
@old_next:
    ld hl,regular_transition_scan_remaining
    dec (hl)
    jr @old
@new_begin:
    ld a,(regular_transition_raw_enter_count)
    ld (regular_transition_scan_remaining),a
@new:
    ld a,(regular_transition_scan_remaining)
    or a
    jr z,@append
    ld hl,(regular_transition_scan_ordinal_pointer)
    ld a,(hl)
    inc hl
    ld (regular_transition_scan_ordinal_pointer),hl
    call regular_transition_target_owner_present
    jr z,@new_next
    ld hl,regular_transition_actual_enter_count
    inc (hl)
@new_next:
    ld hl,regular_transition_scan_remaining
    dec (hl)
    jr @new
@append:
    ld a,(regular_policy_source_index)
    cp fsim_regular_policy_max_descriptors
    jr nc,@bad
    ld hl,(regular_policy_descriptor_pointer)
    ld a,(regular_transition_actual_retire_count)
    cp fsim_regular_policy_max_side+1
    jr nc,@bad
    ld (hl),a
    inc hl
    ld a,(regular_transition_actual_enter_count)
    cp fsim_regular_policy_max_side+1
    jr nc,@bad
    ld (hl),a
    inc hl
    ld a,(regular_policy_source_index)
    ld (hl),a
    inc hl
    ld (regular_policy_descriptor_pointer),hl
@advance:
    ld hl,(regular_policy_scan_group_pointer)
    push hl
    pop ix
    ld a,(ix+regular_lod_transition_group_retiring_count)
    ld b,a
    ld a,(ix+regular_lod_transition_group_entering_count)
    add a,b
    add a,regular_lod_transition_group_ordinals
    ld de,0
    ld e,a
    add hl,de
    ld (regular_policy_scan_group_pointer),hl
    ld hl,regular_policy_source_index
    inc (hl)
    jp @group
@done:
    xor a
    ret
@bad:
    scf
    ret

; DUAL_STRICT runs the accepted oracle and compares C over a cheaply packed
; pending view.  Assembly controls the result; any discrepancy stops before
; prepare/stage.  The public mode include aliases its selector to this routine.
regular_policy_select_dual_strict:
    ld a,(regular_policy_module_status)
    cp regular_policy_module_status_ready
    jp nz,regular_transition_select_feasible_group_asm
    ld a,(regular_policy_descriptors_ready)
    or a
    jr z,@strict_failed
    call regular_transition_select_feasible_group_asm
    ld a,0
    adc a,0
    ld (regular_policy_asm_no_selection),a
    ld a,(regular_transition_selected_index)
    ld (regular_policy_asm_result),a
    call regular_policy_pack_pending_descriptors
    jr c,@strict_failed
    call regular_policy_call_c
    call regular_policy_revalidate_c_result
    jr c,@strict_failed
    ld a,(regular_policy_c_result)
    ld b,a
    ld a,(regular_policy_asm_result)
    cp b
    jr nz,@strict_failed
    ld hl,(regular_policy_selector_matches)
    inc hl
    ld (regular_policy_selector_matches),hl
    jp regular_policy_return_saved_asm
@strict_failed:
    ld a,1
    ld (regular_policy_qualification_failure),a
    ld a,regular_transition_state_error
    ld (regular_transition_state),a
    ld a,regular_provider_error_plan
    scf
    ret

; C_GUARDED does not execute the assembly oracle on its healthy path.  It
; independently validates and installs the returned source group.  A missing
; capability or malformed/infeasible C answer latches a failed qualification
; and falls back to the accepted assembly selector before any staging begins.
regular_policy_select_c_guarded:
    REGULAR_POLICY_C_GUARDED_LATCH_CHECK
    ld a,(regular_policy_module_status)
    cp regular_policy_module_status_ready
    jp nz,regular_transition_select_feasible_group_asm
    ld a,(regular_policy_descriptors_ready)
    or a
    jr z,regular_policy_candidate_failed_fallback
    call regular_policy_pack_pending_descriptors
    jr c,regular_policy_candidate_failed_fallback
    call regular_policy_call_c
    call regular_policy_revalidate_c_result
    jr c,regular_policy_candidate_failed_fallback
    call regular_policy_apply_c_result
    ret

regular_policy_candidate_failed_fallback:
    ld a,1
    ld (regular_policy_qualification_failure),a
    jp regular_transition_select_feasible_group_asm

; Only ASM_CACHED expands these four entry bodies into code.  Historical
; profiles retain the labels as zero-byte aliases, preserving every existing
; instruction and data address while keeping mode-only code out of the image.
regular_policy_prepare_cached_descriptors_asm_cached:
    REGULAR_POLICY_ASM_CACHED_PREPARE_ROUTINE
regular_policy_select_asm_cached:
    REGULAR_POLICY_ASM_CACHED_SELECT_ROUTINE
regular_policy_call_asm_cached:
    REGULAR_POLICY_ASM_CACHED_CALL_ROUTINE
regular_policy_select_cached_descriptors_asm:
    REGULAR_POLICY_ASM_CACHED_NATIVE_ROUTINE

regular_policy_return_saved_asm:
    ld a,(regular_policy_asm_result)
    ld b,a
    ld a,(regular_policy_asm_no_selection)
    or a
    ld a,b
    jr nz,@none
    or a
    ret
@none:
    scf
    ret

; Copy only currently pending indexed descriptors into the C ABI buffer.
; Processed groups change after commits; their precomputed counts do not.
regular_policy_pack_pending_descriptors:
    ld hl,regular_policy_all_descriptors
    ld (regular_policy_all_descriptor_pointer),hl
    ld hl,regular_policy_descriptors
    ld (regular_policy_descriptor_pointer),hl
    xor a
    ld (regular_policy_descriptor_count),a
    ld (regular_policy_source_index),a
@group:
    ld a,(regular_policy_source_index)
    ld b,a
    ld a,(regular_transition_group_count)
    cp b
    jr z,@done
    ld a,(regular_policy_source_index)
    call regular_transition_group_is_processed
    jr nz,@advance
    ld a,(regular_policy_descriptor_count)
    cp fsim_regular_policy_max_descriptors
    jr nc,@bad
    ld hl,(regular_policy_all_descriptor_pointer)
    ld de,(regular_policy_descriptor_pointer)
    ld a,(hl)
    ld (de),a
    inc hl
    inc de
    ld a,(hl)
    ld (de),a
    inc hl
    inc de
    ld a,(hl)
    ld (de),a
    inc de
    ld (regular_policy_descriptor_pointer),de
    ld hl,regular_policy_descriptor_count
    inc (hl)
@advance:
    ld hl,(regular_policy_all_descriptor_pointer)
    ld de,fsim_regular_policy_descriptor_bytes
    add hl,de
    ld (regular_policy_all_descriptor_pointer),hl
    ld hl,regular_policy_source_index
    inc (hl)
    jr @group
@done:
    xor a
    ret
@bad:
    scf
    ret

; Three arguments occupy caller-cleaned three-byte slots in reverse order.
; The fixed AgonDev entry returns its byte result in A.
regular_policy_call_c:
    ld hl,(regular_policy_selector_calls)
    inc hl
    ld (regular_policy_selector_calls),hl
    push ix
    push iy
    ld hl,0
    ld a,(terrain_manager_active_count)
    cpl
    ld l,a
    push hl
    ld hl,0
    ld a,(regular_policy_descriptor_count)
    ld l,a
    push hl
    ld hl,regular_policy_descriptors
    push hl
    call fsim_regular_policy_entry_address
    ld (regular_policy_c_result),a
    pop hl
    pop hl
    pop hl
    pop iy
    pop ix
    ret

; Reject INVALID, an infeasible selected source, a source absent from the exact
; pending buffer, or NONE while any pending descriptor is feasible.  This is
; an independent bounds/capacity gate, not a second policy implementation.
regular_policy_revalidate_c_result:
    ld a,(regular_policy_c_result)
    cp fsim_regular_policy_invalid
    jr z,@bad
    cp fsim_regular_policy_no_selection
    jr z,@none
    ld b,a
    ld hl,regular_policy_descriptors
    ld a,(regular_policy_descriptor_count)
    ld c,a
@selected_scan:
    ld a,c
    or a
    jr z,@bad
    push hl
    pop ix
    ld a,(ix+fsim_regular_policy_descriptor_source_index_offset)
    cp b
    jr z,@selected_found
    ld de,fsim_regular_policy_descriptor_bytes
    add hl,de
    dec c
    jr @selected_scan
@selected_found:
    ld a,(terrain_manager_active_count)
    cpl
    ld b,a
    ld a,(ix+fsim_regular_policy_descriptor_entering_offset)
    cp b
    jr c,@selected_valid
    jr z,@selected_valid
    jr @bad
@selected_valid:
    push ix
    pop hl
    ld (regular_policy_c_descriptor_pointer),hl
    xor a
    ret
@none:
    ld hl,regular_policy_descriptors
    ld a,(regular_policy_descriptor_count)
    ld c,a
    ld a,(terrain_manager_active_count)
    cpl
    ld b,a
@none_scan:
    ld a,c
    or a
    jr z,@valid_none
    push hl
    pop ix
    ld a,(ix+fsim_regular_policy_descriptor_entering_offset)
    cp b
    jr c,@bad
    jr z,@bad
    ld de,fsim_regular_policy_descriptor_bytes
    add hl,de
    dec c
    jr @none_scan
@valid_none:
    xor a
    ret
@bad:
    scf
    ret

; Install one independently revalidated C result into the accepted selector's
; output fields.  The subsequent prepare routine re-materializes both owner
; lists, so no C-owned pointer or count enters staging.
regular_policy_apply_c_result:
    ld a,(regular_policy_c_result)
    cp fsim_regular_policy_no_selection
    jr z,@none
    ld (regular_transition_selected_index),a
    ld b,a
    ld hl,(regular_transition_groups_pointer)
@pointer:
    ld a,b
    or a
    jr z,@pointer_ready
    push hl
    pop ix
    ld a,(ix+regular_lod_transition_group_retiring_count)
    ld c,a
    ld a,(ix+regular_lod_transition_group_entering_count)
    add a,c
    add a,regular_lod_transition_group_ordinals
    ld de,0
    ld e,a
    add hl,de
    dec b
    jr @pointer
@pointer_ready:
    ld (regular_transition_selected_pointer),hl
    ld hl,(regular_policy_c_descriptor_pointer)
    push hl
    pop ix
    ld a,(ix+fsim_regular_policy_descriptor_retiring_offset)
    ld (regular_transition_selected_retire_count),a
    ld b,a
    ld a,(ix+fsim_regular_policy_descriptor_entering_offset)
    ld (regular_transition_selected_enter_count),a
    ld c,a
    ld a,b
    sub c
    add a,16
    ld (regular_transition_selected_score),a
    ld a,(regular_policy_c_result)
    or a
    ret
@none:
    ld a,fsim_regular_policy_no_selection
    ld (regular_transition_selected_index),a
    scf
    ret

regular_policy_filename:
    db "CPOLICY.BIN",0
regular_policy_expected_header:
    db fsim_regular_policy_signature_0
    db fsim_regular_policy_signature_1
    db fsim_regular_policy_signature_2
    db fsim_regular_policy_signature_3
    db fsim_regular_policy_signature_4
    db fsim_regular_policy_signature_5
    db fsim_regular_policy_signature_6
    db fsim_regular_policy_signature_7
    db fsim_regular_policy_format_version
    db fsim_regular_policy_abi_version
    db fsim_regular_policy_header_bytes
    db fsim_regular_policy_descriptor_bytes
    db fsim_regular_policy_max_descriptors
    db fsim_regular_policy_max_side
    db fsim_regular_policy_no_selection
    db fsim_regular_policy_invalid
    dl fsim_regular_policy_entry_address
    db 0
    dl fsim_regular_policy_image_bytes
    db 0
    dl fsim_regular_policy_load_address
    db 0
    dl fsim_regular_policy_limit_exclusive
    db 0

regular_policy_module_status: db 0
regular_policy_qualification_failure: db 0
regular_policy_asm_no_selection: db 0
regular_policy_asm_result: db fsim_regular_policy_no_selection
regular_policy_c_result: db fsim_regular_policy_invalid
regular_policy_descriptor_count: db 0
regular_policy_source_index: db 0
regular_policy_scan_group_pointer: dl 0
regular_policy_descriptor_pointer: dl 0
regular_policy_c_descriptor_pointer: dl 0
regular_policy_selector_calls: dl 0
regular_policy_selector_matches: dl 0
regular_policy_crc_value: ds 4
regular_policy_descriptors_ready: db 0
regular_policy_all_descriptor_pointer: dl 0
regular_policy_all_descriptors:
    ds fsim_regular_policy_max_descriptors*fsim_regular_policy_descriptor_bytes
regular_policy_descriptors:
    ds fsim_regular_policy_max_descriptors*fsim_regular_policy_descriptor_bytes
