; Mode-3-only native descriptor policy.  Each body is emitted through its own
; profile macro because ez80asm intentionally forbids global labels inside a
; macro definition.  The common client supplies the four entry labels; all
; historical profiles expand these bodies to aligned no-ops.

; Construct the identical transition-invariant record array without loading
; or consulting CPOLICY.  A construction fault is latched for evidence, then
; leaves the cache unavailable so all later selections safely reach the
; accepted recomputing selector.
    MACRO REGULAR_POLICY_ASM_CACHED_PREPARE_ROUTINE
    xor a
    ld (regular_policy_descriptors_ready),a
    call regular_policy_build_all_descriptors
    jr c,@failed
    ld a,1
    ld (regular_policy_descriptors_ready),a
    xor a
    ret
@failed:
    ld a,1
    ld (regular_policy_qualification_failure),a
    xor a
    ret

    ENDMACRO

; Hold every architectural input and postcondition equal to C_GUARDED: the
; same cache, pending-record packer, independent result validator, and
; accepted-field installer.  Only the policy scan and calling convention
; differ.  No instruction on this path calls 070020h.
    MACRO REGULAR_POLICY_ASM_CACHED_SELECT_ROUTINE
    ld a,(regular_policy_qualification_failure)
    or a
    jp nz,regular_transition_select_feasible_group_asm
    ld a,(regular_policy_descriptors_ready)
    or a
    jr z,@fallback
    call regular_policy_pack_pending_descriptors
    jr c,@fallback
    call regular_policy_call_asm_cached
    call regular_policy_revalidate_c_result
    jr c,@fallback
    call regular_policy_apply_c_result
    ret
@fallback:
    jp regular_policy_candidate_failed_fallback

    ENDMACRO

; Count one native policy dispatch using the same evidence counter as the C
; call.  The selected source (or the shared FF/FE sentinel) enters the exact
; same result slot so revalidation and installation are byte-identical.
    MACRO REGULAR_POLICY_ASM_CACHED_CALL_ROUTINE
    ld hl,(regular_policy_selector_calls)
    inc hl
    ld (regular_policy_selector_calls),hl
    call regular_policy_select_cached_descriptors_asm
    ld (regular_policy_c_result),a
    ret

    ENDMACRO

; Select directly from the bounded, pending-only ABI records.
;
; Valid input is checked against the same contract as CPOLICY: at most 38
; records, side counts at most 14, source indices below 38, and unique strictly
; increasing source indices.  The fixed array makes a null pointer impossible.
; For valid input the order is exactly shrink-first, fewer entering, more
; retiring, then lower source.  Because sources are strictly increasing, an
; exact metric tie retains the incumbent and is therefore the lowest source.
    MACRO REGULAR_POLICY_ASM_CACHED_NATIVE_ROUTINE
    ld a,(regular_policy_descriptor_count)
    cp fsim_regular_policy_max_descriptors+1
    jr c,@count_valid
@invalid:
    ld a,fsim_regular_policy_invalid
    ret
@count_valid:
    ld b,a
    ld ix,regular_policy_descriptors
    ld a,(terrain_manager_active_count)
    cpl
    ld c,a
    ld a,fsim_regular_policy_no_selection
    ld (regular_policy_asm_result),a
    xor a
    ld (regular_policy_asm_no_selection),a
    ld (regular_transition_selected_score),a
    ld (regular_transition_selected_enter_count),a
    ld (regular_transition_selected_retire_count),a
    ld d,a
    ld e,a
    ld a,b
    or a
    jr nz,@record
    ld a,(regular_policy_asm_result)
    ret

@record:
    ld a,(ix+fsim_regular_policy_descriptor_retiring_offset)
    cp fsim_regular_policy_max_side+1
    jr nc,@invalid
    ld h,a
    ld a,(ix+fsim_regular_policy_descriptor_entering_offset)
    cp fsim_regular_policy_max_side+1
    jr nc,@invalid
    ld l,a
    ld a,(ix+fsim_regular_policy_descriptor_source_index_offset)
    cp fsim_regular_policy_max_descriptors
    jr nc,@invalid
    ld a,e
    or a
    jr z,@source_valid
    ld a,d
    cp (ix+fsim_regular_policy_descriptor_source_index_offset)
    jr nc,@invalid
@source_valid:
    ld d,(ix+fsim_regular_policy_descriptor_source_index_offset)
    ld e,1

; A descriptor remains semantically valid when infeasible; it simply cannot
; win this selection.
    ld a,l
    cp c
    jr c,@feasible
    jr z,@feasible
    jr @advance
@feasible:
    ld a,h
    sub l
    add a,16
    ld (regular_transition_candidate_score),a
    ld a,(regular_policy_asm_result)
    cp fsim_regular_policy_no_selection
    jr z,@choose

    ld a,(regular_transition_candidate_score)
    ld h,a
    ld a,(regular_transition_selected_score)
    cp h
    jr c,@choose
    jr nz,@advance
    ld a,(ix+fsim_regular_policy_descriptor_entering_offset)
    ld h,a
    ld a,(regular_transition_selected_enter_count)
    cp h
    jr c,@advance
    jr nz,@choose
    ld a,(ix+fsim_regular_policy_descriptor_retiring_offset)
    ld h,a
    ld a,(regular_transition_selected_retire_count)
    cp h
    jr c,@choose
    jr @advance

@choose:
    ld a,(ix+fsim_regular_policy_descriptor_source_index_offset)
    ld (regular_policy_asm_result),a
    ld a,(regular_transition_candidate_score)
    ld (regular_transition_selected_score),a
    ld a,(ix+fsim_regular_policy_descriptor_entering_offset)
    ld (regular_transition_selected_enter_count),a
    ld a,(ix+fsim_regular_policy_descriptor_retiring_offset)
    ld (regular_transition_selected_retire_count),a

@advance:
    lea ix,ix+fsim_regular_policy_descriptor_bytes
    dec b
    jp nz,@record
    ld a,(regular_policy_asm_result)
    ret

    ENDMACRO
