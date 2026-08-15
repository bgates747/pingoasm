; =============================================================================
; Topology-neutral Pingo terrain residency manager (ADL=1).
;
; Required compile-time constants:
;   terrain_manager_slot_count       1..255 (91 for radius-five hex)
;   terrain_manager_max_ring
;   terrain_manager_initial_ring
;   terrain_manager_mesh_id_base     exact u16
;   terrain_manager_object_id_base   exact u16
;   terrain_manager_defer_stale_rebase
;       0 retires stale active objects during the origin transaction.
;       1 repositions and retains them until the complete desired plan is
;       active, then lets ordinary stale eviction retire them.
;   terrain_manager_group_staging
;       0 omits the experimental coverage-group staging API and storage.
;       1 assembles load-without-activate and atomic group-commit support.
;
; Required provider hooks:
;   terrain_provider_ring_count
;       A=ring -> A=count (1..slot_count).
;   terrain_provider_desired_at
;       A=ordinal. Fills candidate_q/r (s16), candidate_slot (u8), and
;       candidate_lod (u8). Carry set means clipped/outside the corpus.
;       Slots must be injective over every desired set and stable per world cell.
;   terrain_provider_load_candidate
;       Reads candidate fields and work_mesh_id. Performs one complete validated
;       P3DM/AGNB publication; Z/A=0 success, NZ/A=error. Failure must retain the
;       old mesh/object exactly.
;   terrain_provider_position_candidate
;       Reads candidate fields, current origin and work_object_id. Publishes the
;       command-52 transform; Z/A=0 success, NZ/A=error.
;   terrain_provider_candidate_is_desired
;       Reads candidate fields/current origin/ring; Z desired, NZ stale.
;   terrain_provider_normalize_position
;       IX is opaque mutable application position state. The manager seeds
;       proposed_origin_q/r. Provider may normalize local X/Z, writes proposed
;       q/r, marks application position dirty, and returns carry iff origin moved.
; When terrain_manager_group_staging=1:
;   terrain_provider_transition_busy     A=0 idle/A!=0 owns manager service
;   terrain_provider_ring_change_allowed A=0 allowed/A!=0 reject unchanged
;   terrain_provider_service_transition only while no render is in flight
;
; Required VDU helper: pingo_set_object_active (HL=u16 object ID, A=0/1).
;
; Public API:
;   terrain_manager_initialize
;   terrain_manager_submit_origin       BC=s16 q, DE=s16 r
;   terrain_manager_update_position     IX=opaque mutable position state;
;                                       A=0 unchanged/A=1 rebased, carry=error
;   terrain_manager_set_ring            A=ring
;   terrain_manager_service_idle        only while no render is in flight
;   terrain_manager_stage_candidate     load/position one inactive candidate
;                                       without making it visible
;   terrain_manager_commit_staged_group IX=retiring u8 slots, B=count;
;                                       IY=entering u8 slots, C=count;
;                                       only while no render is in flight
;   terrain_manager_query               IX=status
;   terrain_manager_shutdown_idle       only while no render is in flight
;
; service_idle performs one load, activation, deactivation, or atomic all-active
; origin-reposition transaction. Carry clear returns A=operation; carry set
; returns A=error. Every dw below is accessed bytewise.
; =============================================================================

terrain_manager_state_uninitialized: equ 0
terrain_manager_state_ready:         equ 1
terrain_manager_state_error:         equ 2
terrain_manager_state_shutdown:      equ 3

terrain_manager_operation_none:       equ 0
terrain_manager_operation_load:       equ 1
terrain_manager_operation_activate:   equ 2
terrain_manager_operation_deactivate: equ 3
terrain_manager_operation_rebase:     equ 4
terrain_manager_operation_shutdown:   equ 5
terrain_manager_operation_stage:      equ 6
terrain_manager_operation_group:      equ 7

terrain_manager_flag_resident: equ 1
terrain_manager_flag_active:   equ 2
terrain_manager_flag_staged:   equ 4

terrain_manager_error_config:   equ 020h
terrain_manager_error_ring:     equ 021h
terrain_manager_error_origin:   equ 022h
terrain_manager_error_provider: equ 023h
terrain_manager_error_position: equ 024h
terrain_manager_error_slot:     equ 025h
terrain_manager_error_group:    equ 026h
terrain_manager_retry_max:      equ 5

    MACRO TERRAIN_MANAGER_STORE_U16_HL ADDRESS
        ld a,l
        ld (ADDRESS+0),a
        ld a,h
        ld (ADDRESS+1),a
    ENDMACRO

    MACRO TERRAIN_MANAGER_LOAD_U16_HL ADDRESS
        ld hl,0
        ld a,(ADDRESS+0)
        ld l,a
        ld a,(ADDRESS+1)
        ld h,a
    ENDMACRO

    MACRO TERRAIN_MANAGER_STORE_U16_BC ADDRESS
        ld a,c
        ld (ADDRESS+0),a
        ld a,b
        ld (ADDRESS+1),a
    ENDMACRO

    MACRO TERRAIN_MANAGER_STORE_U16_DE ADDRESS
        ld a,e
        ld (ADDRESS+0),a
        ld a,d
        ld (ADDRESS+1),a
    ENDMACRO

terrain_manager_initialize:
    ld a,terrain_manager_state_uninitialized
    ld (terrain_manager_state),a
    xor a
    ld (terrain_manager_last_operation),a
    ld (terrain_manager_last_error),a
    ld (terrain_manager_origin_valid),a
    ld (terrain_manager_origin_dirty),a
    ld (terrain_manager_converged),a
    ld (terrain_manager_resident_count),a
    ld (terrain_manager_active_count),a
.if terrain_manager_group_staging
    ld (terrain_manager_staged_count),a
.endif
    ld (terrain_manager_scan_cursor),a
    ld (terrain_manager_eviction_cursor),a
    ld (terrain_manager_generation+0),a
    ld (terrain_manager_generation+1),a

; Slot indexes and loop bounds are deliberately u8.
    ld hl,terrain_manager_slot_count
    ld de,1
    or a
    sbc hl,de
    jp c,terrain_manager_bad_config
    ld hl,terrain_manager_slot_count
    ld de,256
    or a
    sbc hl,de
    jp nc,terrain_manager_bad_config
    ld a,terrain_manager_initial_ring
    cp terrain_manager_max_ring+1
    jp nc,terrain_manager_bad_config
    ld (terrain_manager_current_ring),a
    call terrain_provider_ring_count
    or a
    jp z,terrain_manager_bad_config
    ld b,terrain_manager_slot_count
    cp b
    jr c,@count_ok
    jp nz,terrain_manager_bad_config
@count_ok:
    ld (terrain_manager_desired_count),a

; Inclusive mesh/object ID ranges must remain within uint16_t.
    ld hl,terrain_manager_mesh_id_base
    ld de,terrain_manager_slot_count-1
    add hl,de
    ld de,65536
    or a
    sbc hl,de
    jp nc,terrain_manager_bad_config
    ld hl,terrain_manager_object_id_base
    ld de,terrain_manager_slot_count-1
    add hl,de
    ld de,65536
    or a
    sbc hl,de
    jp nc,terrain_manager_bad_config

    ld hl,terrain_manager_slot_storage
    ld bc,terrain_manager_slot_storage_end-terrain_manager_slot_storage
@clear:
    ld (hl),0
    inc hl
    dec bc
    ld a,b
    or c
    jr nz,@clear
    ld a,0ffh
    ld (terrain_manager_last_slot),a
    ld a,terrain_manager_state_ready
    ld (terrain_manager_state),a
    xor a
    ret

terrain_manager_bad_config:
    ld a,terrain_manager_error_config
    ld (terrain_manager_last_error),a
    ld a,terrain_manager_state_error
    ld (terrain_manager_state),a
    ld a,terrain_manager_error_config
    scf
    ret

terrain_manager_submit_origin:
    ld a,(terrain_manager_state)
    cp terrain_manager_state_ready
    jp nz,terrain_manager_not_ready
    ld a,(terrain_manager_origin_valid)
    or a
    jr z,@first
    ld a,c
    ld hl,terrain_manager_origin_q
    cp (hl)
    jr nz,@changed
    ld a,b
    inc hl
    cp (hl)
    jr nz,@changed
    ld a,e
    ld hl,terrain_manager_origin_r
    cp (hl)
    jr nz,@changed
    ld a,d
    inc hl
    cp (hl)
    jr z,@unchanged
@changed:
.if terrain_manager_group_staging
; Once a staged profile has an origin, adjacent moves must flow through the
; provider's one-step recipe transaction.  Teleports/radius cold restarts use
; shutdown -> initialize -> first submit; mutating this public origin in place
; would desynchronize the authoritative owner map.
    jp terrain_manager_bad_group
.endif
    TERRAIN_MANAGER_STORE_U16_BC terrain_manager_origin_q
    TERRAIN_MANAGER_STORE_U16_DE terrain_manager_origin_r
    ld a,1
    ld (terrain_manager_origin_dirty),a
    xor a
    ld (terrain_manager_converged),a
    ld (terrain_manager_scan_cursor),a
    or a
    ret
@first:
    TERRAIN_MANAGER_STORE_U16_BC terrain_manager_origin_q
    TERRAIN_MANAGER_STORE_U16_DE terrain_manager_origin_r
    ld a,1
    ld (terrain_manager_origin_valid),a
    xor a
    ld (terrain_manager_origin_dirty),a
    ld (terrain_manager_converged),a
    ld (terrain_manager_scan_cursor),a
@unchanged:
    or a
    ret

terrain_manager_update_position:
    ld a,(terrain_manager_state)
    cp terrain_manager_state_ready
    jp nz,terrain_manager_not_ready
    ld a,(terrain_manager_origin_valid)
    or a
    jp z,terrain_manager_bad_origin
.if terrain_manager_group_staging
; One coverage recipe owns one adjacent origin step.  While its replacement
; groups are staged, camera motion remains local and cannot overwrite either
; the old-owner snapshot or the target plan.
    call terrain_provider_transition_busy
    or a
    jr z,@transition_idle
    xor a
    ret
@transition_idle:
    ld a,(terrain_manager_converged)
    or a
    jr nz,@endpoint_ready
    xor a
    ret
@endpoint_ready:
.endif
    ld a,(terrain_manager_origin_q+0)
    ld (terrain_manager_proposed_origin_q+0),a
    ld a,(terrain_manager_origin_q+1)
    ld (terrain_manager_proposed_origin_q+1),a
    ld a,(terrain_manager_origin_r+0)
    ld (terrain_manager_proposed_origin_r+0),a
    ld a,(terrain_manager_origin_r+1)
    ld (terrain_manager_proposed_origin_r+1),a
    call terrain_provider_normalize_position
    jr c,@changed
    xor a
    ret
@changed:
    ld a,(terrain_manager_proposed_origin_q+0)
    ld (terrain_manager_origin_q+0),a
    ld a,(terrain_manager_proposed_origin_q+1)
    ld (terrain_manager_origin_q+1),a
    ld a,(terrain_manager_proposed_origin_r+0)
    ld (terrain_manager_origin_r+0),a
    ld a,(terrain_manager_proposed_origin_r+1)
    ld (terrain_manager_origin_r+1),a
    ld a,1
    ld (terrain_manager_origin_dirty),a
    xor a
    ld (terrain_manager_converged),a
    ld (terrain_manager_scan_cursor),a
    ld a,1
    or a
    ret

terrain_manager_set_ring:
    ld b,a
    ld a,(terrain_manager_state)
    cp terrain_manager_state_ready
    jp nz,terrain_manager_not_ready
.if terrain_manager_group_staging
    push bc
    call terrain_provider_transition_busy
    or a
    pop bc
    jp nz,terrain_manager_bad_group
    push bc
    call terrain_provider_ring_change_allowed
    or a
    pop bc
    jp nz,terrain_manager_bad_group
.endif
    ld a,b
    cp terrain_manager_max_ring+1
    jr nc,terrain_manager_bad_ring
    ld (terrain_manager_current_ring),a
    xor a
    ld (terrain_manager_converged),a
    ld (terrain_manager_scan_cursor),a
    or a
    ret

terrain_manager_not_ready:
    ld a,terrain_manager_error_config
    ld (terrain_manager_last_error),a
    scf
    ret
terrain_manager_bad_ring:
    ld a,terrain_manager_error_ring
    ld (terrain_manager_last_error),a
    scf
    ret
terrain_manager_bad_origin:
    ld a,terrain_manager_error_origin
    ld (terrain_manager_last_error),a
    scf
    ret

terrain_manager_service_idle:
    ld a,(terrain_manager_state)
    cp terrain_manager_state_ready
    jp nz,terrain_manager_not_ready
    ld a,(terrain_manager_origin_valid)
    or a
    jp z,terrain_manager_bad_origin
    xor a
    ld (terrain_manager_last_operation),a
    ld (terrain_manager_converged),a
    ld a,(terrain_manager_origin_dirty)
    or a
    jp nz,terrain_manager_reposition_active
.if terrain_manager_group_staging
; Staged ownership is intentionally invisible to ordinary convergence.  The
; provider is the sole dispatcher until every atomic coverage group commits;
; otherwise the regular scanner could activate a partial group or evict its
; still-visible predecessor.
    call terrain_provider_transition_busy
    or a
    jp nz,terrain_provider_service_transition
    ld a,(terrain_manager_staged_count)
    or a
    jp nz,terrain_manager_bad_group
.endif

    ld a,(terrain_manager_current_ring)
    call terrain_provider_ring_count
    or a
    jr z,terrain_manager_provider_error
    ld b,terrain_manager_slot_count
    cp b
    jr c,@count_ok
    jr nz,terrain_manager_provider_error
@count_ok:
    ld (terrain_manager_desired_count),a
    ld (terrain_manager_scan_remaining),a
@scan:
    ld a,(terrain_manager_scan_cursor)
    ld b,a
    ld a,(terrain_manager_desired_count)
    cp b
    jr nz,@cursor_ok
    ld b,0
@cursor_ok:
    ld a,b
    ld (terrain_manager_candidate_ordinal),a
    inc a
    ld b,a
    ld a,(terrain_manager_desired_count)
    cp b
    jr nz,@save_cursor
    ld b,0
@save_cursor:
    ld a,b
    ld (terrain_manager_scan_cursor),a
    ld a,(terrain_manager_candidate_ordinal)
    call terrain_provider_desired_at
    jr nc,@candidate_ready
; Ordinal zero is the origin itself.  Clipping it is an invalid submitted
; origin, whereas clipped non-centre ordinals are ordinary corpus edges.
    ld a,(terrain_manager_candidate_ordinal)
    or a
    jp z,terrain_manager_bad_origin
    jr @next
@candidate_ready:
    ld a,(terrain_manager_candidate_slot)
    cp terrain_manager_slot_count
    jr nc,terrain_manager_bad_provider_slot
    call terrain_manager_slot_matches_candidate
    jr nz,@missing
    call terrain_manager_candidate_active
    jp nz,terrain_manager_activate_candidate
    jr @next
@missing:
    call terrain_manager_candidate_retry_ready
    jp z,terrain_manager_load_candidate
@next:
    ld hl,terrain_manager_scan_remaining
    dec (hl)
    jr nz,@scan
    jp terrain_manager_deactivate_one_stale

terrain_manager_provider_error:
    ld a,terrain_manager_error_provider
    ld (terrain_manager_last_error),a
    scf
    ret
terrain_manager_bad_provider_slot:
    ld a,terrain_manager_error_slot
    ld (terrain_manager_last_error),a
    scf
    ret

; Z means the checked slot contains the exact candidate q/r/lod.
terrain_manager_slot_matches_candidate:
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_flags_pointer
    ld a,(hl)
    and terrain_manager_flag_resident
    jr z,@different
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_q_pointer
    ld a,(terrain_manager_candidate_q+0)
    cp (hl)
    jr nz,@different
    inc hl
    ld a,(terrain_manager_candidate_q+1)
    cp (hl)
    jr nz,@different
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_r_pointer
    ld a,(terrain_manager_candidate_r+0)
    cp (hl)
    jr nz,@different
    inc hl
    ld a,(terrain_manager_candidate_r+1)
    cp (hl)
    jr nz,@different
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_lod_pointer
    ld a,(terrain_manager_candidate_lod)
    cp (hl)
    ret
@different:
    ld a,1
    or a
    ret

; Z means active; NZ means inactive.
terrain_manager_candidate_active:
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_flags_pointer
    ld a,(hl)
    and terrain_manager_flag_active
    cp terrain_manager_flag_active
    ret

; Z means retry now. A nonzero bounded countdown is decremented per visit.
terrain_manager_candidate_retry_ready:
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_retry_pointer
    ld a,(hl)
    or a
    ret z
    dec (hl)
    ld a,1
    or a
    ret

; Transaction order is load -> command-52 placement -> activation -> commit.
terrain_manager_load_candidate:
    call terrain_manager_prepare_work_ids
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_flags_pointer
    ld a,(hl)
    ld (terrain_manager_previous_flags),a
    call terrain_provider_load_candidate
    or a
    jp nz,terrain_manager_record_load_failure
    call terrain_provider_position_candidate
    or a
    jr nz,terrain_manager_record_position_failure
    TERRAIN_MANAGER_LOAD_U16_HL terrain_manager_work_object_id
    ld a,1
    call pingo_set_object_active
    call terrain_manager_commit_candidate
    ld a,terrain_manager_operation_load
    call terrain_manager_record_success
    ld a,terrain_manager_operation_load
    or a
    ret

; A loader failure records bounded exponential retry state but does not touch
; resident identity, flags, transform, activation, or counts.
terrain_manager_record_load_failure:
    ld (terrain_manager_last_error),a
    push af
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_error_pointer
    pop af
    ld (hl),a
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_failures_pointer
    ld a,(hl)
    cp terrain_manager_retry_max
    jr nc,@count_ready
    inc (hl)
@count_ready:
    ld b,(hl)
    ld a,1
@backoff:
    add a,a
    djnz @backoff
    ld b,a
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_retry_pointer
    ld (hl),b
    xor a
    ld (terrain_manager_converged),a
    ld a,(terrain_manager_last_error)
    scf
    ret

; Command 50 cannot be rolled back after a later placement failure. Fail closed
; by deactivating and invalidating the affected stable slot.
terrain_manager_record_position_failure:
    or a
    jr nz,@error_ready
    ld a,terrain_manager_error_position
@error_ready:
    ld (terrain_manager_last_error),a
    push af
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_error_pointer
    pop af
    ld (hl),a
    TERRAIN_MANAGER_LOAD_U16_HL terrain_manager_work_object_id
    xor a
    call pingo_set_object_active
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_flags_pointer
    xor a
    ld (hl),a
    ld a,(terrain_manager_previous_flags)
    bit 0,a
    call nz,terrain_manager_decrement_resident_count
    ld a,(terrain_manager_previous_flags)
    bit 1,a
    call nz,terrain_manager_decrement_active_count
    ld a,(terrain_manager_last_error)
    scf
    ret

terrain_manager_activate_candidate:
    call terrain_manager_prepare_work_ids
; An inactive cached slot may have missed an origin transaction.
    call terrain_provider_position_candidate
    or a
    jr nz,terrain_manager_record_activation_position_failure
    TERRAIN_MANAGER_LOAD_U16_HL terrain_manager_work_object_id
    ld a,1
    call pingo_set_object_active
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_flags_pointer
    ld a,(hl)
    or terrain_manager_flag_active
    ld (hl),a
    ld hl,terrain_manager_active_count
    inc (hl)
    call terrain_manager_clear_candidate_failure
    ld a,terrain_manager_operation_activate
    call terrain_manager_record_success
    ld a,terrain_manager_operation_activate
    or a
    ret

; No mesh was published on the cached-activation path, so a placement failure
; must leave the resident/inactive slot and both counts untouched.
terrain_manager_record_activation_position_failure:
    or a
    jr nz,@error_ready
    ld a,terrain_manager_error_position
@error_ready:
    ld (terrain_manager_last_error),a
    push af
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_error_pointer
    pop af
    ld (hl),a
    xor a
    ld (terrain_manager_converged),a
    ld a,(terrain_manager_last_error)
    scf
    ret

.if terrain_manager_group_staging
; Publish one candidate only into an object slot which is both inactive and not
; already reserved by the current staged group.  Exact inactive cache hits need
; only placement; every other candidate follows validated command-50 load then
; placement.  Neither path activates the object.  The provider may therefore
; prepare a complete coverage replacement while the old group remains visible.
terrain_manager_stage_candidate:
    ld a,(terrain_manager_state)
    cp terrain_manager_state_ready
    jp nz,terrain_manager_not_ready
    ld a,(terrain_manager_origin_valid)
    or a
    jp z,terrain_manager_bad_origin
    call terrain_manager_prepare_work_ids
    ld a,(terrain_manager_candidate_slot)
    cp terrain_manager_slot_count
    jp nc,terrain_manager_bad_provider_slot
    call terrain_manager_slot_flags_pointer
    ld a,(hl)
    ld (terrain_manager_previous_flags),a
    and terrain_manager_flag_active+terrain_manager_flag_staged
    jp nz,terrain_manager_bad_provider_slot
    call terrain_manager_slot_matches_candidate
    jr nz,@load

; A validated inactive cache hit has no command-50 failure boundary.  Position
; first, then reserve it for the group.
    call terrain_provider_position_candidate
    or a
    jp nz,terrain_manager_record_activation_position_failure
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_flags_pointer
    ld (hl),terrain_manager_flag_resident+terrain_manager_flag_staged
    ld hl,terrain_manager_staged_count
    inc (hl)
    call terrain_manager_clear_candidate_failure
    ld a,terrain_manager_operation_stage
    call terrain_manager_record_success
    ld a,terrain_manager_operation_stage
    or a
    ret

@load:
    call terrain_provider_load_candidate
    or a
    jp nz,terrain_manager_record_load_failure
    call terrain_provider_position_candidate
    or a
    jp nz,terrain_manager_record_position_failure
    call terrain_manager_commit_staged_candidate
    ld a,terrain_manager_operation_stage
    call terrain_manager_record_success
    ld a,terrain_manager_operation_stage
    or a
    ret

; Commit identity and residency for a successfully loaded inactive candidate.
; Active ownership is deliberately untouched until the complete group commit.
terrain_manager_commit_staged_candidate:
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_q_pointer
    ld a,(terrain_manager_candidate_q+0)
    ld (hl),a
    inc hl
    ld a,(terrain_manager_candidate_q+1)
    ld (hl),a
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_r_pointer
    ld a,(terrain_manager_candidate_r+0)
    ld (hl),a
    inc hl
    ld a,(terrain_manager_candidate_r+1)
    ld (hl),a
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_lod_pointer
    ld a,(terrain_manager_candidate_lod)
    ld (hl),a

    ld a,(terrain_manager_previous_flags)
    and terrain_manager_flag_resident
    jr nz,@resident_counted
    ld hl,terrain_manager_resident_count
    inc (hl)
@resident_counted:
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_flags_pointer
    ld (hl),terrain_manager_flag_resident+terrain_manager_flag_staged
    ld hl,terrain_manager_staged_count
    inc (hl)
    call terrain_manager_clear_candidate_failure
    ret

; Atomically, from the renderer's point of view, exchange one complete coverage
; group. Inputs are IX=retiring u8 slot list/B=count and IY=entering u8 slot
; list/C=count. The caller guarantees no render is in flight and submits none
; until this routine returns. Full preflight occurs before the first command 51;
; after it succeeds the old side is retired before the staged side is exposed.
terrain_manager_commit_staged_group:
    ld a,(terrain_manager_state)
    cp terrain_manager_state_ready
    jp nz,terrain_manager_not_ready
    ld a,(terrain_manager_origin_valid)
    or a
    jp z,terrain_manager_bad_origin
    ld (terrain_manager_group_retire_pointer),ix ; ADL24: native list pointer
    ld a,b
    ld (terrain_manager_group_retire_count),a
    ld (terrain_manager_group_enter_pointer),iy  ; ADL24: native list pointer
    ld a,c
    ld (terrain_manager_group_enter_count),a
    call terrain_manager_validate_staged_group
    ret c

    ld a,(terrain_manager_group_retire_count)
    ld (terrain_manager_group_remaining),a
    ld ix,(terrain_manager_group_retire_pointer) ; ADL24: native list pointer
@retire:
    ld a,(terrain_manager_group_remaining)
    or a
    jr z,@enter_begin
    ld a,(ix)
    inc ix
    ld (terrain_manager_group_retire_pointer),ix ; ADL24: advanced list pointer
    ld (terrain_manager_candidate_slot),a
    call terrain_manager_load_candidate_from_slot
    call terrain_manager_prepare_work_ids
    TERRAIN_MANAGER_LOAD_U16_HL terrain_manager_work_object_id
    xor a
    call pingo_set_object_active
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_flags_pointer
    ld (hl),terrain_manager_flag_resident
    call terrain_manager_decrement_active_count
    ld ix,(terrain_manager_group_retire_pointer) ; ADL24: native list pointer
    ld hl,terrain_manager_group_remaining
    dec (hl)
    jr @retire

@enter_begin:
    ld a,(terrain_manager_group_enter_count)
    ld (terrain_manager_group_remaining),a
    ld iy,(terrain_manager_group_enter_pointer)  ; ADL24: native list pointer
@enter:
    ld a,(terrain_manager_group_remaining)
    or a
    jr z,@committed
    ld a,(iy)
    inc iy
    ld (terrain_manager_group_enter_pointer),iy  ; ADL24: advanced list pointer
    ld (terrain_manager_candidate_slot),a
    call terrain_manager_load_candidate_from_slot
    call terrain_manager_prepare_work_ids
    TERRAIN_MANAGER_LOAD_U16_HL terrain_manager_work_object_id
    ld a,1
    call pingo_set_object_active
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_flags_pointer
    ld (hl),terrain_manager_flag_resident+terrain_manager_flag_active
    ld hl,terrain_manager_active_count
    inc (hl)
    ld hl,terrain_manager_staged_count
    dec (hl)
    ld iy,(terrain_manager_group_enter_pointer)  ; ADL24: native list pointer
    ld hl,terrain_manager_group_remaining
    dec (hl)
    jr @enter

@committed:
    ld a,terrain_manager_operation_group
    call terrain_manager_record_success
    ld a,terrain_manager_operation_group
    or a
    ret

; Validate every group list, its exact slot flags, uniqueness, staged count, and
; resulting active-count bound before emitting any VDP command. A failure leaves
; the old group active and every entering mesh staged but invisible.
terrain_manager_validate_staged_group:
    ld hl,terrain_manager_group_seen_slots
    ld b,32
    xor a
@clear_seen:
    ld (hl),a
    inc hl
    djnz @clear_seen

    ld a,(terrain_manager_group_retire_count)
    ld b,a
    ld a,(terrain_manager_group_enter_count)
    or b
    jp z,terrain_manager_bad_group
    ld a,(terrain_manager_staged_count)
    ld b,a
    ld a,(terrain_manager_group_enter_count)
    cp b
    jp nz,terrain_manager_bad_group

; Prove 0 <= active-retiring+entering <= configured capacity in 24-bit
; arithmetic so the 255-slot profile never turns 256 into zero.
    ld hl,0
    ld a,(terrain_manager_active_count)
    ld l,a
    ld de,0
    ld a,(terrain_manager_group_retire_count)
    ld e,a
    or a
    sbc hl,de
    jp c,terrain_manager_bad_group
    ld de,0
    ld a,(terrain_manager_group_enter_count)
    ld e,a
    add hl,de
    ld de,terrain_manager_slot_count+1
    or a
    sbc hl,de
    jp nc,terrain_manager_bad_group

    ld ix,(terrain_manager_group_retire_pointer) ; ADL24: native list pointer
    ld a,(terrain_manager_group_retire_count)
    ld (terrain_manager_group_remaining),a
@retire:
    ld a,(terrain_manager_group_remaining)
    or a
    jr z,@enter_begin
    ld a,(ix)
    cp terrain_manager_slot_count
    jp nc,terrain_manager_bad_group
    push ix
    call terrain_manager_group_mark_slot
    pop ix
    jp c,terrain_manager_bad_group
    ld a,(ix)
    call terrain_manager_slot_flags_pointer
    ld a,(hl)
    and terrain_manager_flag_resident+terrain_manager_flag_active+terrain_manager_flag_staged
    cp terrain_manager_flag_resident+terrain_manager_flag_active
    jp nz,terrain_manager_bad_group
    inc ix
    ld hl,terrain_manager_group_remaining
    dec (hl)
    jr @retire

@enter_begin:
    ld iy,(terrain_manager_group_enter_pointer)  ; ADL24: native list pointer
    ld a,(terrain_manager_group_enter_count)
    ld (terrain_manager_group_remaining),a
@enter:
    ld a,(terrain_manager_group_remaining)
    or a
    jr z,@ok
    ld a,(iy)
    cp terrain_manager_slot_count
    jp nc,terrain_manager_bad_group
    push iy
    call terrain_manager_group_mark_slot
    pop iy
    jp c,terrain_manager_bad_group
    ld a,(iy)
    call terrain_manager_slot_flags_pointer
    ld a,(hl)
    and terrain_manager_flag_resident+terrain_manager_flag_active+terrain_manager_flag_staged
    cp terrain_manager_flag_resident+terrain_manager_flag_staged
    jp nz,terrain_manager_bad_group
    inc iy
    ld hl,terrain_manager_group_remaining
    dec (hl)
    jr @enter
@ok:
    or a
    ret

; A=slot. Carry set means the slot was already present in either list.
terrain_manager_group_mark_slot:
    push bc
    push de
    push hl
    ld (terrain_manager_group_checked_slot),a
    and 7
    ld de,0
    ld e,a
    ld hl,terrain_manager_group_bit_masks
    add hl,de
    ld a,(hl)
    ld (terrain_manager_group_bit_mask),a
    ld a,(terrain_manager_group_checked_slot)
    srl a
    srl a
    srl a
    ld de,0
    ld e,a
    ld hl,terrain_manager_group_seen_slots
    add hl,de
    ld a,(terrain_manager_group_bit_mask)
    ld b,a
    ld a,(hl)
    and b
    jr nz,@duplicate
    ld a,(hl)
    or b
    ld (hl),a
    pop hl
    pop de
    pop bc
    or a
    ret
@duplicate:
    pop hl
    pop de
    pop bc
    scf
    ret

terrain_manager_bad_group:
    ld a,terrain_manager_error_group
    ld (terrain_manager_last_error),a
    scf
    ret
.endif

terrain_manager_commit_candidate:
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_q_pointer
    ld a,(terrain_manager_candidate_q+0)
    ld (hl),a
    inc hl
    ld a,(terrain_manager_candidate_q+1)
    ld (hl),a
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_r_pointer
    ld a,(terrain_manager_candidate_r+0)
    ld (hl),a
    inc hl
    ld a,(terrain_manager_candidate_r+1)
    ld (hl),a
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_lod_pointer
    ld a,(terrain_manager_candidate_lod)
    ld (hl),a

    ld a,(terrain_manager_previous_flags)
    bit 0,a
    jr nz,@resident_counted
    ld hl,terrain_manager_resident_count
    inc (hl)
@resident_counted:
    ld a,(terrain_manager_previous_flags)
    bit 1,a
    jr nz,@active_counted
    ld hl,terrain_manager_active_count
    inc (hl)
@active_counted:
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_flags_pointer
    ld (hl),terrain_manager_flag_resident+terrain_manager_flag_active
    call terrain_manager_clear_candidate_failure
    ret

terrain_manager_clear_candidate_failure:
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_error_pointer
    ld (hl),0
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_failures_pointer
    ld (hl),0
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_retry_pointer
    ld (hl),0
    ret

; Once every desired component is active, deactivate at most one stale object.
; Its validated mesh remains cached and can later be reactivated without I/O.
terrain_manager_deactivate_one_stale:
    ld a,terrain_manager_slot_count
    ld (terrain_manager_eviction_remaining),a
@scan:
    ld a,(terrain_manager_eviction_cursor)
    ld b,a
    inc a
    cp terrain_manager_slot_count
    jr c,@cursor_ready
    xor a
@cursor_ready:
    ld (terrain_manager_eviction_cursor),a
    ld a,b
    call terrain_manager_slot_flags_pointer
    ld a,(hl)
    and terrain_manager_flag_active
    jr z,@next
    ld a,b
    ld (terrain_manager_candidate_slot),a
    call terrain_manager_load_candidate_from_slot
    call terrain_provider_candidate_is_desired
    jr z,@next
    call terrain_manager_prepare_work_ids
    TERRAIN_MANAGER_LOAD_U16_HL terrain_manager_work_object_id
    xor a
    call pingo_set_object_active
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_flags_pointer
    ld a,(hl)
    and terrain_manager_flag_resident
    ld (hl),a
    call terrain_manager_decrement_active_count
    ld a,terrain_manager_operation_deactivate
    call terrain_manager_record_success
    ld a,terrain_manager_operation_deactivate
    or a
    ret
@next:
    ld hl,terrain_manager_eviction_remaining
    dec (hl)
    jr nz,@scan
    ld a,1
    ld (terrain_manager_converged),a
    xor a
    ld (terrain_manager_last_operation),a
    ret

; A rebase is one render-idle transaction. Inactive cached entries are placed
; immediately before reactivation, so only active entries need work here.
; Providers with a positionable fallback fringe may retain stale actives until
; the desired plan converges. This makes the existing post-scan stale eviction
; a conservative old-plan -> complete-new-plan handoff rather than a hole.
terrain_manager_reposition_active:
    xor a
    ld (terrain_manager_reposition_index),a
@next:
    ld a,(terrain_manager_reposition_index)
    call terrain_manager_slot_flags_pointer
    ld a,(hl)
    and terrain_manager_flag_active
    jr z,@advance
    ld a,(terrain_manager_reposition_index)
    ld (terrain_manager_candidate_slot),a
    call terrain_manager_load_candidate_from_slot
.if terrain_manager_defer_stale_rebase
; Keep the complete preceding plan visible while replacements publish. Every
; active fallback is moved into the new floating-origin frame, including
; identities outside the new desired plan. Ordinary convergence will retire
; them only after every desired identity is active.
    call terrain_manager_prepare_work_ids
    call terrain_provider_position_candidate
    or a
    jr nz,@failed
.else
; Old edge cells can fall outside the new desired set (and outside a
; provider's bounded placement domain).  Retire them inside this same
; render-idle transaction; only overlapping residents need command 52.
    call terrain_provider_candidate_is_desired
    jr nz,@deactivate
    call terrain_manager_prepare_work_ids
    call terrain_provider_position_candidate
    or a
    jr nz,@failed
    jr @advance
@deactivate:
    call terrain_manager_prepare_work_ids
    TERRAIN_MANAGER_LOAD_U16_HL terrain_manager_work_object_id
    xor a
    call pingo_set_object_active
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_flags_pointer
    ld a,(hl)
    and terrain_manager_flag_resident
    ld (hl),a
    call terrain_manager_decrement_active_count
.endif
@advance:
    ld a,(terrain_manager_reposition_index)
    inc a
    ld (terrain_manager_reposition_index),a
    cp terrain_manager_slot_count
    jr c,@next
    xor a
    ld (terrain_manager_origin_dirty),a
    ld a,terrain_manager_operation_rebase
    call terrain_manager_record_success
    ld a,terrain_manager_operation_rebase
    or a
    ret
@failed:
    ld (terrain_manager_last_error),a
    scf
    ret

terrain_manager_query:
    ld ix,terrain_manager_status
    xor a
    ret

terrain_manager_shutdown_idle:
    ld a,(terrain_manager_state)
    cp terrain_manager_state_ready
    jr nz,@finish
    xor a
    ld (terrain_manager_reposition_index),a
@next:
    ld a,(terrain_manager_reposition_index)
    call terrain_manager_slot_flags_pointer
    ld a,(hl)
    and terrain_manager_flag_active
    jr z,@advance
    ld a,(terrain_manager_reposition_index)
    ld (terrain_manager_candidate_slot),a
    call terrain_manager_prepare_work_ids
    TERRAIN_MANAGER_LOAD_U16_HL terrain_manager_work_object_id
    xor a
    call pingo_set_object_active
@advance:
    ld a,(terrain_manager_reposition_index)
    inc a
    ld (terrain_manager_reposition_index),a
    cp terrain_manager_slot_count
    jr c,@next
@finish:
    ld hl,terrain_manager_slot_storage
    ld bc,terrain_manager_slot_storage_end-terrain_manager_slot_storage
@clear:
    ld (hl),0
    inc hl
    dec bc
    ld a,b
    or c
    jr nz,@clear
    xor a
    ld (terrain_manager_resident_count),a
    ld (terrain_manager_active_count),a
.if terrain_manager_group_staging
    ld (terrain_manager_staged_count),a
.endif
    ld (terrain_manager_converged),a
    ld (terrain_manager_origin_valid),a
    ld a,terrain_manager_state_shutdown
    ld (terrain_manager_state),a
    ld a,terrain_manager_operation_shutdown
    call terrain_manager_record_success
    ld a,terrain_manager_operation_shutdown
    or a
    ret

terrain_manager_prepare_work_ids:
    ld de,0
    ld a,(terrain_manager_candidate_slot)
    ld e,a
    ld hl,terrain_manager_mesh_id_base
    add hl,de
    TERRAIN_MANAGER_STORE_U16_HL terrain_manager_work_mesh_id
    ld hl,terrain_manager_object_id_base
    add hl,de
    TERRAIN_MANAGER_STORE_U16_HL terrain_manager_work_object_id
    ret

terrain_manager_load_candidate_from_slot:
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_q_pointer
    ld a,(hl)
    ld (terrain_manager_candidate_q+0),a
    inc hl
    ld a,(hl)
    ld (terrain_manager_candidate_q+1),a
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_r_pointer
    ld a,(hl)
    ld (terrain_manager_candidate_r+0),a
    inc hl
    ld a,(hl)
    ld (terrain_manager_candidate_r+1),a
    ld a,(terrain_manager_candidate_slot)
    call terrain_manager_slot_lod_pointer
    ld a,(hl)
    ld (terrain_manager_candidate_lod),a
    ret

terrain_manager_record_success:
    ld (terrain_manager_last_operation),a
    xor a
    ld (terrain_manager_last_error),a
    ld (terrain_manager_converged),a
    ld a,(terrain_manager_candidate_slot)
    ld (terrain_manager_last_slot),a
    ld a,(terrain_manager_candidate_q+0)
    ld (terrain_manager_last_q+0),a
    ld a,(terrain_manager_candidate_q+1)
    ld (terrain_manager_last_q+1),a
    ld a,(terrain_manager_candidate_r+0)
    ld (terrain_manager_last_r+0),a
    ld a,(terrain_manager_candidate_r+1)
    ld (terrain_manager_last_r+1),a
    TERRAIN_MANAGER_LOAD_U16_HL terrain_manager_generation
    inc.s hl
    TERRAIN_MANAGER_STORE_U16_HL terrain_manager_generation
    ret

terrain_manager_decrement_resident_count:
    ld a,(terrain_manager_resident_count)
    or a
    ret z
    dec a
    ld (terrain_manager_resident_count),a
    ret

terrain_manager_decrement_active_count:
    ld a,(terrain_manager_active_count)
    or a
    ret z
    dec a
    ld (terrain_manager_active_count),a
    ret

.if terrain_manager_group_staging
terrain_manager_decrement_staged_count:
    ld a,(terrain_manager_staged_count)
    or a
    ret z
    dec a
    ld (terrain_manager_staged_count),a
    ret
.endif

; A=checked slot -> HL=native pointer.
terrain_manager_slot_q_pointer:
    ld hl,0
    ld l,a
    add hl,hl
    ld de,terrain_manager_resident_q
    add hl,de
    ret
terrain_manager_slot_r_pointer:
    ld hl,0
    ld l,a
    add hl,hl
    ld de,terrain_manager_resident_r
    add hl,de
    ret
terrain_manager_slot_flags_pointer:
    ld hl,0
    ld l,a
    ld de,terrain_manager_resident_flags
    add hl,de
    ret
terrain_manager_slot_lod_pointer:
    ld hl,0
    ld l,a
    ld de,terrain_manager_resident_lod
    add hl,de
    ret
terrain_manager_slot_error_pointer:
    ld hl,0
    ld l,a
    ld de,terrain_manager_slot_error
    add hl,de
    ret
terrain_manager_slot_failures_pointer:
    ld hl,0
    ld l,a
    ld de,terrain_manager_slot_failures
    add hl,de
    ret
terrain_manager_slot_retry_pointer:
    ld hl,0
    ld l,a
    ld de,terrain_manager_slot_retry
    add hl,de
    ret

; Public 19-byte query/status ABI.
terrain_manager_status:
terrain_manager_state:          db terrain_manager_state_uninitialized ; +0
terrain_manager_current_ring:   db terrain_manager_initial_ring        ; +1
terrain_manager_desired_count:  db 0                                   ; +2
terrain_manager_resident_count: db 0                                   ; +3
terrain_manager_active_count:   db 0                                   ; +4
terrain_manager_converged:      db 0                                   ; +5
terrain_manager_last_operation: db terrain_manager_operation_none      ; +6
terrain_manager_last_error:     db 0                                   ; +7
terrain_manager_origin_q:       dw 0                                   ; +8
terrain_manager_origin_r:       dw 0                                   ; +10
terrain_manager_last_slot:      db 0ffh                                ; +12
terrain_manager_last_q:         dw 0                                   ; +13
terrain_manager_last_r:         dw 0                                   ; +15
terrain_manager_generation:     dw 0                                   ; +17
terrain_manager_status_end:

terrain_manager_status_state:          equ 0
terrain_manager_status_ring:           equ 1
terrain_manager_status_desired_count:  equ 2
terrain_manager_status_resident_count: equ 3
terrain_manager_status_active_count:   equ 4
terrain_manager_status_converged:      equ 5
terrain_manager_status_last_operation: equ 6
terrain_manager_status_last_error:     equ 7
terrain_manager_status_origin_q:       equ 8
terrain_manager_status_origin_r:       equ 10
terrain_manager_status_last_slot:      equ 12
terrain_manager_status_last_q:         equ 13
terrain_manager_status_last_r:         equ 15
terrain_manager_status_generation:     equ 17
terrain_manager_status_size:           equ 19

; Provider-visible transaction workspace.
terrain_manager_proposed_origin_q: dw 0
terrain_manager_proposed_origin_r: dw 0
terrain_manager_candidate_q:       dw 0
terrain_manager_candidate_r:       dw 0
terrain_manager_candidate_slot:    db 0
terrain_manager_candidate_lod:     db 0
terrain_manager_work_mesh_id:      dw 0
terrain_manager_work_object_id:    dw 0

; Private core state.
terrain_manager_origin_valid:       db 0
terrain_manager_origin_dirty:       db 0
terrain_manager_scan_cursor:        db 0
terrain_manager_scan_remaining:     db 0
terrain_manager_eviction_cursor:    db 0
terrain_manager_eviction_remaining: db 0
terrain_manager_reposition_index:   db 0
terrain_manager_candidate_ordinal:  db 0
terrain_manager_previous_flags:     db 0
.if terrain_manager_group_staging
terrain_manager_staged_count:       db 0
terrain_manager_group_retire_count: db 0
terrain_manager_group_enter_count:  db 0
terrain_manager_group_remaining:    db 0
terrain_manager_group_checked_slot: db 0
terrain_manager_group_bit_mask:     db 0
terrain_manager_group_retire_pointer: dl 0
terrain_manager_group_enter_pointer:  dl 0
terrain_manager_group_seen_slots:   ds 32
terrain_manager_group_bit_masks:
    db 1,2,4,8,16,32,64,128
.endif

; Nine bytes per slot; exactly 819 bytes for the first 91-slot hex provider.
terrain_manager_slot_storage:
terrain_manager_resident_q:     ds terrain_manager_slot_count*2
terrain_manager_resident_r:     ds terrain_manager_slot_count*2
terrain_manager_resident_flags: ds terrain_manager_slot_count
terrain_manager_resident_lod:   ds terrain_manager_slot_count
terrain_manager_slot_error:     ds terrain_manager_slot_count
terrain_manager_slot_failures:  ds terrain_manager_slot_count
terrain_manager_slot_retry:     ds terrain_manager_slot_count
terrain_manager_slot_storage_end:
