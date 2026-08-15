; =============================================================================
; Position-driven regular hierarchy provider for the universal terrain manager.
;
; Detailed TRH/L0 cells retain stable slots 0..90.  Generated hierarchy leaves
; are exact (lod, anchor_q, anchor_offset_row) identities and use a protected
; dynamic pool in slots 91..254.  A new plan first preserves every matching
; resident identity (active or inactive), then assigns unused pool slots.  The
; shared manager still owns publication, retry, activation and rebase ordering.
;
; Every radius-five disk maps bijectively onto the first 91 slots through
;
;     slot = (5*q + 11*r) mod 91.
;
; The kernel basis (11,-5),(5,6) has determinant 91 and minimum non-zero hex
; distance 11.  Therefore no difference between two cells in one radius-five
; disk (maximum distance 10) can be in the kernel.  Smaller disks inherit the
; same injectivity, and normalizing negative residues makes the mapping global.
; =============================================================================

hex_provider_q_max: equ 213
hex_provider_even_rows: equ 235
hex_provider_odd_rows: equ 234
hex_provider_cell_id_pair_stride: equ 469
hex_provider_terrain_y_count: equ 9728
hex_provider_object_scale_q8_8: equ 32768
hex_provider_hysteresis_count: equ 256
hex_provider_vertical_exit_first: equ 4657
hex_provider_tip_exit_first: equ 5377
hex_provider_sloped_normal_squared: equ 4146176
hex_provider_sloped_hysteresis: equ 521271
hex_provider_sloped_exit_first: equ 9532472

regular_provider_near_slot_count: equ 91
regular_provider_coarse_slot_first: equ 91
regular_provider_coarse_slot_count: equ 164
regular_provider_plan_max: equ regular_lod_phase_maximum_records
regular_provider_plan_record_lod: equ 0
regular_provider_plan_record_q: equ 1
regular_provider_plan_record_row: equ 3
regular_provider_plan_record_slot: equ 5
regular_provider_plan_record_bytes: equ 6
regular_provider_unassigned_slot: equ 0ffh
regular_provider_error_plan: equ 031h
.if terrain_manager_group_staging
regular_transition_owner_count: equ 250
regular_transition_near_owner_count: equ 91
regular_transition_coarse_owner_count: equ 159
regular_transition_state_idle: equ 0
regular_transition_state_wait_rebase: equ 1
regular_transition_state_select: equ 2
regular_transition_state_stage: equ 3
regular_transition_state_commit: equ 4
regular_transition_state_error: equ 5
regular_transition_processed_bytes: equ 5
.endif

    MACRO HEX_PROVIDER_LOAD_U16_HL ADDRESS
        ld hl,0
        ld a,(ADDRESS)
        ld l,a
        ld a,(ADDRESS+1)
        ld h,a
    ENDMACRO

    MACRO HEX_PROVIDER_LOAD_U16_DE ADDRESS
        ld de,0
        ld a,(ADDRESS)
        ld e,a
        ld a,(ADDRESS+1)
        ld d,a
    ENDMACRO

    MACRO HEX_PROVIDER_STORE_U16_HL ADDRESS
        ld a,l
        ld (ADDRESS),a
        ld a,h
        ld (ADDRESS+1),a
    ENDMACRO

    MACRO HEX_PROVIDER_LOAD_CAMERA_HL OFFSET
        ld hl,0
        ld l,(ix+OFFSET)
        ld h,(ix+OFFSET+1)
    ENDMACRO

    MACRO HEX_PROVIDER_STORE_CAMERA_HL OFFSET
        ld (ix+OFFSET),l
        ld (ix+OFFSET+1),h
    ENDMACRO

; Before the first plan exists (manager initialization), report the complete
; near disk.  Thereafter report the cached dense near+coarse desired count.
terrain_provider_ring_count:
    ld b,a
    ld a,(regular_provider_plan_valid)
    or a
    ld a,b
    jr z,regular_provider_near_ring_count
    ld a,(regular_provider_desired_count)
    ret

regular_provider_near_ring_count:
    ld hl,hex_provider_ring_counts
    ld de,0
    ld e,a
    add hl,de
    ld a,(hl)
    ret

; Input A is an ordinal in the current complete disk.  Output is the shared
; candidate request block.  Carry means the bounded regional corpus clips the
; requested cell.  The ordering is centre first, then clockwise rings, each
; beginning at the northwestern cell; it is byte-identical to disk_offsets().
terrain_provider_desired_at:
    push af
    ld a,(terrain_manager_current_ring)
    call regular_provider_near_ring_count
    ld b,a
    pop af
    cp b
    jr c,regular_provider_near_desired_at
    sub b
    jp regular_provider_coarse_desired_at

regular_provider_near_desired_at:
.if terrain_manager_group_staging
    ld (regular_provider_near_ordinal),a
    call regular_provider_build_near_candidate
    ret c
    ld a,(regular_provider_near_ordinal)
    call regular_provider_near_slot_pointer
    ld a,(hl)
    cp regular_provider_unassigned_slot
    jr z,@outside
    ld (terrain_manager_candidate_slot),a
    xor a
    ld (terrain_manager_candidate_lod),a
    or a
    ret
@outside:
    scf
    ret

; Build only the bounded L0 identity for one canonical disk ordinal.  Physical
; ownership is deliberately separate: after the first coverage handoff a near
; cell may occupy any one of the 255 manager slots.
regular_provider_build_near_candidate:
.endif
    ld hl,0
    ld l,a
    add hl,hl
    ld de,hex_provider_disk_offsets
    add hl,de
    push hl
    pop ix

    HEX_PROVIDER_LOAD_U16_HL terrain_manager_origin_q
    ld de,0
    ld e,(ix+0)
    bit 7,e
    jr z,@q_extended
    ld d,0ffh
@q_extended:
    add.s hl,de
    HEX_PROVIDER_STORE_U16_HL terrain_manager_candidate_q

    HEX_PROVIDER_LOAD_U16_HL terrain_manager_origin_r
    ld de,0
    ld e,(ix+1)
    bit 7,e
    jr z,@r_extended
    ld d,0ffh
@r_extended:
    add.s hl,de
    HEX_PROVIDER_STORE_U16_HL terrain_manager_candidate_r

    call hex_provider_validate_candidate
    ret c
.if terrain_manager_group_staging
    xor a
    ld (terrain_manager_candidate_lod),a
    or a
    ret
.else
    call hex_provider_compute_candidate_slot
    xor a
    ld (terrain_manager_candidate_lod),a
    or a
    ret
.endif

; A is a dense coarse ordinal in the current mutable plan.  Manager q/r retain
; anchor q/offset-row so identity comparisons and paths require no side table.
regular_provider_coarse_desired_at:
    ld b,a
    ld a,(regular_provider_plan_count)
    cp b
    jr z,@outside
    jr c,@outside
    ld a,b
    call regular_provider_plan_pointer
    push hl
    pop ix
    ld a,(ix+regular_provider_plan_record_lod)
    ld (terrain_manager_candidate_lod),a
    ld a,(ix+regular_provider_plan_record_q+0)
    ld (terrain_manager_candidate_q+0),a
    ld a,(ix+regular_provider_plan_record_q+1)
    ld (terrain_manager_candidate_q+1),a
    ld a,(ix+regular_provider_plan_record_row+0)
    ld (terrain_manager_candidate_r+0),a
    ld a,(ix+regular_provider_plan_record_row+1)
    ld (terrain_manager_candidate_r+1),a
    ld a,(ix+regular_provider_plan_record_slot)
    cp regular_provider_unassigned_slot
    jr z,@outside
    ld (terrain_manager_candidate_slot),a
    or a
    ret
@outside:
    scf
    ret

; A=0..158 -> HL=&plan[A*6].
regular_provider_plan_pointer:
    ld hl,0
    ld l,a
    add hl,hl                           ; 2A
    push hl
    add hl,hl                           ; 4A
    pop de
    add hl,de                           ; 6A
    ld de,regular_provider_plan
    add hl,de
    ret

; Rebuild the dense hierarchy leaf plan for the live origin/radius.  Static
; profiles are translation-independent; absolute anchors are resolved here and
; empty nodes beyond the bounded Bay Area corpus are omitted before allocation.
terrain_provider_prepare_plan:
.if terrain_manager_group_staging
    ld a,(regular_transition_build_target)
    or a
    jr nz,@target_build
    ld a,(regular_provider_unified_slots)
    or a
    jp nz,@failed
    call regular_provider_initialize_split_near_slots
@target_build:
    xor a
    ld (regular_provider_phase_source_ordinal),a
.endif
    xor a
    ld (regular_provider_plan_valid),a
    ld (regular_provider_plan_count),a
    call regular_provider_compute_origin_offset_row
    call regular_provider_select_phase_profile
    jp c,@failed
@record:
    ld a,(regular_provider_phase_remaining)
    or a
    jp z,@allocate
    dec a
    ld (regular_provider_phase_remaining),a

    ld hl,(regular_provider_phase_pointer) ; ADL24: generated profile pointer
    push hl
    pop ix
    ld a,(ix+regular_lod_phase_record_lod)
    ld (regular_provider_build_lod),a
.if terrain_manager_group_staging
    ld a,(regular_provider_phase_source_ordinal)
    ld (regular_provider_build_source_ordinal),a
.endif

    HEX_PROVIDER_LOAD_U16_HL terrain_manager_origin_q
    ld de,0
    ld e,(ix+regular_lod_phase_record_anchor_q_offset)
    bit 7,e
    jr z,@q_extended
    ld d,0ffh
@q_extended:
    add.s hl,de
    HEX_PROVIDER_STORE_U16_HL regular_provider_build_q

    HEX_PROVIDER_LOAD_U16_HL regular_provider_origin_offset_row
    ld de,0
    ld e,(ix+regular_lod_phase_record_anchor_offset_row_offset)
    bit 7,e
    jr z,@row_extended
    ld d,0ffh
@row_extended:
    add.s hl,de
    HEX_PROVIDER_STORE_U16_HL regular_provider_build_row

    ld hl,(regular_provider_phase_pointer) ; ADL24: generated profile pointer
    ld de,regular_lod_phase_record_bytes
    add hl,de
    ld (regular_provider_phase_pointer),hl ; ADL24: generated profile pointer
.if terrain_manager_group_staging
    ld hl,regular_provider_phase_source_ordinal
    inc (hl)
.endif
    call regular_provider_validate_build_record
    jp c,@record
    call regular_provider_append_build_record
    jr c,@failed
    jp @record

@allocate:
.if terrain_manager_group_staging
    ld a,(regular_transition_build_target)
    or a
    jr nz,@target_mappings
.endif
    call regular_provider_reconcile_slots
    jr c,@failed
.if terrain_manager_group_staging
    jr @allocated
@target_mappings:
    call regular_transition_prepare_target_mappings
    jr c,@failed
@allocated:
.endif
    ld a,(terrain_manager_current_ring)
    call regular_provider_near_ring_count
    ld b,a
    ld a,(regular_provider_plan_count)
    add a,b
    jr c,@failed
    ld (regular_provider_desired_count),a
.if terrain_manager_group_staging
; Cold split fill counts near owners during table initialization; target-map
; construction counts both classes itself.
    ld a,(regular_transition_build_target)
    or a
    jr nz,@endpoint_ready
    ld a,(regular_provider_endpoint_count)
    ld b,a
    ld a,(regular_provider_plan_count)
    add a,b
    ld (regular_provider_endpoint_count),a
@endpoint_ready:
.endif
    ld a,1
    ld (regular_provider_plan_valid),a
    xor a
    ret
@failed:
    ld a,regular_provider_error_plan
    scf
    ret

regular_provider_compute_origin_offset_row:
    HEX_PROVIDER_LOAD_U16_HL terrain_manager_origin_q
    srl h
    rr l
    push hl
    HEX_PROVIDER_LOAD_U16_HL terrain_manager_origin_r
    pop de
    add.s hl,de
    HEX_PROVIDER_STORE_U16_HL regular_provider_origin_offset_row
    ret

; Select profile index ring*32 + (q&7)*4 + (offset_row&3), then cache
; its count and first static three-byte record pointer.
regular_provider_select_phase_profile:
    ld hl,0
    ld a,(terrain_manager_current_ring)
    ld l,a
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl                           ; ring * 32
    ld de,0
    ld a,(terrain_manager_origin_q)
    and 7
    add a,a
    add a,a
    ld e,a
    add hl,de
    ld a,(regular_provider_origin_offset_row)
    and 3
    ld e,a
    add hl,de

    push hl
    add hl,hl                           ; 2 * index
    pop de
    add hl,de                           ; 3 * index (one dl pointer)
    ld de,regular_lod_phase_offsets
    add hl,de
    ld a,(hl)
    ld (regular_provider_phase_pointer+0),a
    inc hl
    ld a,(hl)
    ld (regular_provider_phase_pointer+1),a
    inc hl
    ld a,(hl)
    ld (regular_provider_phase_pointer+2),a
    ld hl,(regular_provider_phase_pointer) ; ADL24: generated profile pointer
    ld a,(hl)
    cp regular_provider_plan_max+1
    jr nc,@bad
    ld (regular_provider_phase_remaining),a
    inc hl
    ld (regular_provider_phase_pointer),hl ; ADL24: first profile record
    or a
    ret
@bad:
    scf
    ret

; At least one bounded cell must exist in the aligned hierarchy node.  L8/L4
; and L2 anchors cannot hit the alternating-row corner hole; for L1 reject the
; sole impossible identity q=odd,row=234 as well as ordinary outer bounds.
regular_provider_validate_build_record:
    ld a,(regular_provider_build_q+1)
    or a
    jr nz,@outside
    ld a,(regular_provider_build_q)
    cp regular_corpus_region_q_max+1
    jr nc,@outside
    ld b,a
    ld a,(regular_provider_build_row+1)
    or a
    jr nz,@outside
    ld a,(regular_provider_build_row)
    cp regular_corpus_region_even_rows
    jr nc,@outside
    cp regular_corpus_region_odd_rows
    jr c,@inside
    ld a,(regular_provider_build_lod)
    cp regular_corpus_l1_lod
    jr nz,@inside
    bit 0,b
    jr nz,@outside
@inside:
    or a
    ret
@outside:
    scf
    ret

regular_provider_append_build_record:
    ld a,(regular_provider_plan_count)
    cp regular_provider_plan_max
    jr nc,@full
    push af
    call regular_provider_plan_pointer
    push hl
    pop ix
    ld a,(regular_provider_build_lod)
    ld (ix+regular_provider_plan_record_lod),a
    ld a,(regular_provider_build_q+0)
    ld (ix+regular_provider_plan_record_q+0),a
    ld a,(regular_provider_build_q+1)
    ld (ix+regular_provider_plan_record_q+1),a
    ld a,(regular_provider_build_row+0)
    ld (ix+regular_provider_plan_record_row+0),a
    ld a,(regular_provider_build_row+1)
    ld (ix+regular_provider_plan_record_row+1),a
    ld (ix+regular_provider_plan_record_slot),regular_provider_unassigned_slot
.if terrain_manager_group_staging
    pop af
    push af
    ld hl,0
    ld l,a
    ld de,regular_provider_plan_source_ordinals
    add hl,de
    ld a,(regular_provider_build_source_ordinal)
    ld (hl),a
.endif
    pop af
    inc a
    ld (regular_provider_plan_count),a
    or a
    ret
@full:
    scf
    ret

; Protect every resident identity retained by the new plan before assigning any
; newcomer.  Inactive cached residents are protected just like active ones.
; Remaining records take the lowest unclaimed coarse slot. The fixture marks
; origin_dirty after this succeeds; its deferred-rebase policy repositions
; stale active identities as temporary fallback geometry. Desired ordinals put
; every near L0 cell first, so successful detail publication precedes any
; newcomer that can reuse a stale coarse slot. Ordinary stale eviction begins
; only after the complete desired plan is active.
regular_provider_reconcile_slots:
    ld hl,regular_provider_claimed_slots
    ld b,regular_provider_coarse_slot_count
    xor a
@clear:
    ld (hl),a
    inc hl
    djnz @clear
    xor a
    ld (regular_provider_plan_index),a

@preserve_plan:
    ld a,(regular_provider_plan_index)
    ld b,a
    ld a,(regular_provider_plan_count)
    cp b
    jp z,@assign_begin
    ld a,b
    call regular_provider_plan_pointer
    push hl
    pop ix
    ld a,regular_provider_coarse_slot_first
    ld (regular_provider_scan_slot),a
@preserve_slot:
    ld a,(regular_provider_scan_slot)
    call terrain_manager_slot_flags_pointer
    ld a,(hl)
    and terrain_manager_flag_resident
    jr z,@preserve_advance

    ld a,(regular_provider_scan_slot)
    call terrain_manager_slot_lod_pointer
    ld a,(ix+regular_provider_plan_record_lod)
    cp (hl)
    jr nz,@preserve_advance
    ld a,(regular_provider_scan_slot)
    call terrain_manager_slot_q_pointer
    ld a,(ix+regular_provider_plan_record_q+0)
    cp (hl)
    jr nz,@preserve_advance
    inc hl
    ld a,(ix+regular_provider_plan_record_q+1)
    cp (hl)
    jr nz,@preserve_advance
    ld a,(regular_provider_scan_slot)
    call terrain_manager_slot_r_pointer
    ld a,(ix+regular_provider_plan_record_row+0)
    cp (hl)
    jr nz,@preserve_advance
    inc hl
    ld a,(ix+regular_provider_plan_record_row+1)
    cp (hl)
    jr nz,@preserve_advance

    ld a,(regular_provider_scan_slot)
    ld (ix+regular_provider_plan_record_slot),a
    sub regular_provider_coarse_slot_first
    call regular_provider_claimed_pointer
    ld (hl),1
    jr @preserve_next_plan

@preserve_advance:
    ld a,(regular_provider_scan_slot)
    inc a
    cp terrain_manager_slot_count
    jr nc,@preserve_next_plan
    ld (regular_provider_scan_slot),a
    jr @preserve_slot
@preserve_next_plan:
    ld a,(regular_provider_plan_index)
    inc a
    ld (regular_provider_plan_index),a
    jp @preserve_plan

@assign_begin:
    xor a
    ld (regular_provider_plan_index),a
@assign_plan:
    ld a,(regular_provider_plan_index)
    ld b,a
    ld a,(regular_provider_plan_count)
    cp b
    jr z,@done
    ld a,b
    call regular_provider_plan_pointer
    push hl
    pop ix
    ld a,(ix+regular_provider_plan_record_slot)
    cp regular_provider_unassigned_slot
    jr nz,@assign_next_plan
; Prefer an inactive (or wholly unused) unclaimed slot.  During the deferred
; old-plan handoff, an unclaimed slot can still own visible fallback terrain.
; Publishing a newcomer into such a slot replaces the mesh beneath that live
; object before convergence and produces an apparent world-position snap.
; Only fall back to an active stale slot when the 164-slot pool has no inactive
; candidate.  The initial Marina northbound transition fits completely; some
; denser hierarchy phases still require a future coverage-aware handoff.
    xor a
    ld (regular_provider_pool_index),a
@find_inactive:
    ld a,(regular_provider_pool_index)
    cp regular_provider_coarse_slot_count
    jr nc,@find_any_begin
    call regular_provider_claimed_pointer
    ld a,(hl)
    or a
    jr nz,@inactive_advance
    ld a,(regular_provider_pool_index)
    add a,regular_provider_coarse_slot_first
    call terrain_manager_slot_flags_pointer
    ld a,(hl)
    and terrain_manager_flag_active
    jr z,@claim
@inactive_advance:
    ld a,(regular_provider_pool_index)
    inc a
    ld (regular_provider_pool_index),a
    jr @find_inactive
@find_any_begin:
    xor a
    ld (regular_provider_pool_index),a
@find_any:
    ld a,(regular_provider_pool_index)
    cp regular_provider_coarse_slot_count
    jr nc,@no_slot
    call regular_provider_claimed_pointer
    ld a,(hl)
    or a
    jr z,@claim
    ld a,(regular_provider_pool_index)
    inc a
    ld (regular_provider_pool_index),a
    jr @find_any
@claim:
    ld a,(regular_provider_pool_index)
    call regular_provider_claimed_pointer
    ld (hl),1
    ld a,(regular_provider_pool_index)
    add a,regular_provider_coarse_slot_first
    ld (ix+regular_provider_plan_record_slot),a
@assign_next_plan:
    ld a,(regular_provider_plan_index)
    inc a
    ld (regular_provider_plan_index),a
    jp @assign_plan
@done:
    or a
    ret
@no_slot:
    scf
    ret

; A=0..163 -> HL=&claimed[A].
regular_provider_claimed_pointer:
    ld hl,0
    ld l,a
    ld de,regular_provider_claimed_slots
    add hl,de
    ret

.if terrain_manager_group_staging
; -----------------------------------------------------------------------------
; Unified full-owner plan maps.  Recipe ordinals always address the unbounded
; source profile.  Bounded edge clipping is represented only by 0xff map
; entries; dense-plan omission must never shift a recipe identity.

; A=near ordinal 0..90 -> HL=&authoritative physical slot.
regular_provider_near_slot_pointer:
    ld hl,0
    ld l,a
    ld de,regular_provider_near_slots
    add hl,de
    ret

; A=near ordinal 0..90 -> HL=&bounded-valid byte.
regular_provider_near_valid_pointer:
    ld hl,0
    ld l,a
    ld de,regular_provider_near_valid
    add hl,de
    ret

; A=coarse source ordinal 0..158 -> HL=&target dense index or 0xff.
regular_transition_template_pointer:
    ld hl,0
    ld l,a
    ld de,regular_transition_target_template_to_dense
    add hl,de
    ret

; A=full owner ordinal 0..249 -> HL=&old physical slot or 0xff.
regular_transition_old_slot_pointer:
    ld hl,0
    ld l,a
    ld de,regular_transition_old_slot_by_ordinal
    add hl,de
    ret

; Cold start deliberately reproduces the accepted split allocation.  It also
; materializes the near owner table which subsequent full-owner handoffs keep
; authoritative even when near cells migrate outside slots 0..90.
regular_provider_initialize_split_near_slots:
    xor a
    ld (regular_provider_near_ordinal),a
    ld (regular_provider_endpoint_count),a
    ld (regular_provider_unified_slots),a
    ld (regular_transition_state),a
    ld a,(terrain_manager_current_ring)
    call regular_provider_near_ring_count
    ld (regular_provider_endpoint_near_limit),a
@next:
    ld a,(regular_provider_near_ordinal)
    call regular_provider_build_near_candidate
    jr c,@clipped
    call hex_provider_compute_candidate_slot
    ld a,(terrain_manager_candidate_slot)
    ld b,a
    ld a,(regular_provider_near_ordinal)
    call regular_provider_near_slot_pointer
    ld (hl),b
    ld a,(regular_provider_near_ordinal)
    call regular_provider_near_valid_pointer
    ld (hl),1
    ld a,(regular_provider_near_ordinal)
    ld b,a
    ld a,(regular_provider_endpoint_near_limit)
    cp b
    jr z,@advance
    jr c,@advance
    ld hl,regular_provider_endpoint_count
    inc (hl)
    jr @advance
@clipped:
    ld a,(regular_provider_near_ordinal)
    call regular_provider_near_slot_pointer
    ld (hl),regular_provider_unassigned_slot
    ld a,(regular_provider_near_ordinal)
    call regular_provider_near_valid_pointer
    ld (hl),0
@advance:
    ld a,(regular_provider_near_ordinal)
    inc a
    ld (regular_provider_near_ordinal),a
    cp regular_provider_near_slot_count
    jr c,@next
    xor a
    ret

; Snapshot the complete old endpoint before target-plan construction overwrites
; the mutable dense records.  The table remains source-ordinal keyed at corpus
; edges, and already-unified near slots are copied verbatim.
regular_transition_snapshot_old_slots:
    ld hl,regular_transition_old_slot_by_ordinal
    ld b,regular_transition_owner_count
    ld a,regular_provider_unassigned_slot
@clear:
    ld (hl),a
    inc hl
    djnz @clear

    xor a
    ld (regular_provider_near_ordinal),a
@near:
    ld a,(regular_provider_near_ordinal)
    call regular_provider_near_valid_pointer
    ld a,(hl)
    or a
    jr z,@near_advance
    ld a,(regular_provider_near_ordinal)
    call regular_provider_near_slot_pointer
    ld b,(hl)
    ld a,(regular_provider_near_ordinal)
    call regular_transition_old_slot_pointer
    ld (hl),b
@near_advance:
    ld a,(regular_provider_near_ordinal)
    inc a
    ld (regular_provider_near_ordinal),a
    cp regular_transition_near_owner_count
    jr c,@near

    xor a
    ld (regular_provider_plan_index),a
@coarse:
    ld a,(regular_provider_plan_index)
    ld b,a
    ld a,(regular_provider_plan_count)
    cp b
    jr z,@done
    ld a,b
    ld hl,0
    ld l,a
    ld de,regular_provider_plan_source_ordinals
    add hl,de
    ld a,(hl)
    add a,regular_transition_near_owner_count
    call regular_transition_old_slot_pointer
    push hl
    ld a,(regular_provider_plan_index)
    call regular_provider_plan_pointer
    push hl
    pop ix
    pop hl
    ld a,(ix+regular_provider_plan_record_slot)
    ld (hl),a
    ld a,(regular_provider_plan_index)
    inc a
    ld (regular_provider_plan_index),a
    jr @coarse
@done:
    ret

; Return carry clear/A=slot for an exact active resident candidate, or carry
; set if the identity is new.  Shared owners thereby retain their actual
; physical slots without relying on the retired near/coarse split.
regular_transition_find_active_candidate:
    xor a
    ld (regular_provider_scan_slot),a
@scan:
    ld a,(regular_provider_scan_slot)
    call terrain_manager_slot_flags_pointer
    ld a,(hl)
    and terrain_manager_flag_resident+terrain_manager_flag_active
    cp terrain_manager_flag_resident+terrain_manager_flag_active
    jp nz,@advance
    ld a,(regular_provider_scan_slot)
    ld (terrain_manager_candidate_slot),a
    call terrain_manager_slot_matches_candidate
    jr nz,@advance
    ld a,(regular_provider_scan_slot)
    or a
    ret
@advance:
    ld a,(regular_provider_scan_slot)
    inc a
    ld (regular_provider_scan_slot),a
    cp terrain_manager_slot_count
    jr c,@scan
    scf
    ret

; Build bounded target maps and preserve only exact shared owner identities.
; New owners intentionally remain unassigned until their coverage group stages.
regular_transition_prepare_target_mappings:
    ld hl,regular_transition_target_template_to_dense
    ld b,regular_transition_coarse_owner_count
    ld a,regular_provider_unassigned_slot
@clear_templates:
    ld (hl),a
    inc hl
    djnz @clear_templates
    ld hl,regular_provider_near_slots
    ld b,regular_transition_near_owner_count
@clear_near_slots:
    ld (hl),a
    inc hl
    djnz @clear_near_slots
    ld hl,regular_provider_near_valid
    ld b,regular_transition_near_owner_count
    xor a
@clear_near_valid:
    ld (hl),a
    inc hl
    djnz @clear_near_valid
    ld (regular_provider_endpoint_count),a
    ld (regular_provider_near_ordinal),a

@near:
    ld a,(regular_provider_near_ordinal)
    call regular_provider_build_near_candidate
    jr c,@near_advance
    ld a,(regular_provider_near_ordinal)
    call regular_provider_near_valid_pointer
    ld (hl),1
    ld hl,regular_provider_endpoint_count
    inc (hl)
    call regular_transition_find_active_candidate
    jr c,@near_advance
    ld b,a
    ld a,(regular_provider_near_ordinal)
    call regular_provider_near_slot_pointer
    ld (hl),b
@near_advance:
    ld a,(regular_provider_near_ordinal)
    inc a
    ld (regular_provider_near_ordinal),a
    cp regular_transition_near_owner_count
    jr c,@near

    xor a
    ld (regular_provider_plan_index),a
@coarse:
    ld a,(regular_provider_plan_index)
    ld b,a
    ld a,(regular_provider_plan_count)
    cp b
    jr z,@done
    ld a,(regular_provider_plan_index)
    ld hl,0
    ld l,a
    ld de,regular_provider_plan_source_ordinals
    add hl,de
    ld a,(hl)
    call regular_transition_template_pointer
    ld a,(regular_provider_plan_index)
    ld (hl),a

    call regular_provider_plan_pointer
    push hl
    pop ix
    ld a,(ix+regular_provider_plan_record_lod)
    ld (terrain_manager_candidate_lod),a
    ld a,(ix+regular_provider_plan_record_q+0)
    ld (terrain_manager_candidate_q+0),a
    ld a,(ix+regular_provider_plan_record_q+1)
    ld (terrain_manager_candidate_q+1),a
    ld a,(ix+regular_provider_plan_record_row+0)
    ld (terrain_manager_candidate_r+0),a
    ld a,(ix+regular_provider_plan_record_row+1)
    ld (terrain_manager_candidate_r+1),a
    ld hl,regular_provider_endpoint_count
    inc (hl)
    call regular_transition_find_active_candidate
    jr c,@coarse_advance
    ld (ix+regular_provider_plan_record_slot),a
@coarse_advance:
    ld a,(regular_provider_plan_index)
    inc a
    ld (regular_provider_plan_index),a
    jr @coarse
@done:
    or a
    ret

; Select one of 32 old phases and six exact step directions.  Each directory
; entry is a native 24-bit pointer to group_count followed by packed groups.
regular_transition_select_recipe:
    ld hl,0
    ld a,(regular_transition_old_phase_q)
    ld l,a
    add hl,hl
    add hl,hl                           ; q * 4
    ld de,0
    ld a,(regular_transition_old_phase_row)
    ld e,a
    add hl,de
    push hl
    add hl,hl                           ; phase * 2
    pop de
    add hl,de                           ; phase * 3
    add hl,hl                           ; phase * 6
    ld de,0
    ld a,(regular_transition_direction)
    ld e,a
    add hl,de                           ; phase * 6 + direction
    push hl
    add hl,hl
    pop de
    add hl,de                           ; native dl directory byte offset
    ld de,regular_lod_transition_offsets
    add hl,de
    ld a,(hl)
    ld (regular_transition_recipe_pointer+0),a
    inc hl
    ld a,(hl)
    ld (regular_transition_recipe_pointer+1),a
    inc hl
    ld a,(hl)
    ld (regular_transition_recipe_pointer+2),a
    ld hl,(regular_transition_recipe_pointer)
    ld a,(hl)
    cp regular_lod_transition_maximum_groups+1
    jr nc,@bad
    ld (regular_transition_group_count),a
    inc hl
    ld (regular_transition_groups_pointer),hl
    ld hl,regular_transition_processed_groups
    ld b,regular_transition_processed_bytes
    xor a
@clear:
    ld (hl),a
    inc hl
    djnz @clear
    ld (regular_transition_processed_count),a
    or a
    ret
@bad:
    scf
    ret

terrain_provider_begin_transition:
    call terrain_provider_transition_busy
    or a
    jr nz,regular_transition_begin_busy
    ld a,(terrain_manager_current_ring)
    cp regular_lod_transition_near_radius
    jr nz,regular_transition_begin_failed
    call regular_transition_snapshot_old_slots
    ld a,1
    ld (regular_transition_build_target),a
    call terrain_provider_prepare_plan
    push af
    xor a
    ld (regular_transition_build_target),a
    pop af
    jr c,regular_transition_begin_failed
    call regular_transition_select_recipe
    jr c,regular_transition_begin_failed
    REGULAR_POLICY_BEGIN_TRANSITION
    ld a,1
    ld (regular_provider_unified_slots),a
    ld a,regular_transition_state_wait_rebase
    ld (regular_transition_state),a
    xor a
    ret
regular_transition_begin_failed:
    ld a,regular_transition_state_error
    ld (regular_transition_state),a
    ld a,regular_provider_error_plan
    scf
    ret
regular_transition_begin_busy:
    ld a,regular_provider_error_plan
    scf
    ret

terrain_provider_transition_busy:
    ld a,(regular_transition_state)
    or a
    ret

terrain_provider_ring_change_allowed:
    ld a,(regular_provider_unified_slots)
    or a
    ret

; Reset provider-private ownership after the manager has deactivated and
; forgotten every slot.  This is the only legal route from unified arbitrary
; slots back to the deterministic cold split allocator.  It deliberately does
; not touch camera or regional origin state; the fixture resubmits that origin
; as the newly initialized manager's first origin.
terrain_provider_reset_for_cold_restart:
    call terrain_provider_transition_busy
    or a
    jr nz,@busy
    xor a
    ld (regular_provider_plan_valid),a
    ld (regular_provider_plan_count),a
    ld (regular_provider_desired_count),a
    ld (regular_provider_endpoint_count),a
    ld (regular_provider_endpoint_near_limit),a
    ld (regular_provider_unified_slots),a
    ld (regular_transition_build_target),a
    ld (regular_transition_state),a
    ret
@busy:
    ld a,regular_provider_error_plan
    scf
    ret

; Return NZ when A's full owner ordinal exists in the bounded target endpoint.
regular_transition_target_owner_present:
    cp regular_transition_near_owner_count
    jr nc,@coarse
    call regular_provider_near_valid_pointer
    ld a,(hl)
    or a
    ret
@coarse:
    sub regular_transition_near_owner_count
    call regular_transition_template_pointer
    ld a,(hl)
    cp regular_provider_unassigned_slot
    ret

; Return NZ when group index A is already committed/edge-empty, Z otherwise.
regular_transition_group_is_processed:
    ld (regular_transition_group_checked_index),a
    and 7
    ld hl,0
    ld l,a
    ld de,regular_transition_bit_masks
    add hl,de
    ld b,(hl)
    ld a,(regular_transition_group_checked_index)
    srl a
    srl a
    srl a
    ld hl,0
    ld l,a
    ld de,regular_transition_processed_groups
    add hl,de
    ld a,(hl)
    and b
    ret

regular_transition_mark_selected_processed:
    ld a,(regular_transition_selected_index)
    ld (regular_transition_group_checked_index),a
    and 7
    ld hl,0
    ld l,a
    ld de,regular_transition_bit_masks
    add hl,de
    ld b,(hl)
    ld a,(regular_transition_group_checked_index)
    srl a
    srl a
    srl a
    ld hl,0
    ld l,a
    ld de,regular_transition_processed_groups
    add hl,de
    ld a,(hl)
    or b
    ld (hl),a
    ld hl,regular_transition_processed_count
    inc (hl)
    ret

; Inspect every pending recipe component and choose a currently feasible group
; by the host-proven shrink-first order: maximum retiring-entering, then fewer
; entering, then more retiring, then source order.  Counts are edge-filtered
; through the source-ordinal maps before capacity is tested.
regular_transition_select_feasible_group:
    REGULAR_POLICY_SELECT_DISPATCH
regular_transition_select_feasible_group_asm:
    ld hl,(regular_transition_groups_pointer)
    ld (regular_transition_scan_group_pointer),hl
    xor a
    ld (regular_transition_scan_group_index),a
    ld a,regular_provider_unassigned_slot
    ld (regular_transition_selected_index),a
    xor a
    ld (regular_transition_selected_score),a

@group:
    ld a,(regular_transition_scan_group_index)
    ld b,a
    ld a,(regular_transition_group_count)
    cp b
    jp z,@selected
    ld hl,(regular_transition_scan_group_pointer)
    push hl
    pop ix
    ld a,(ix+regular_lod_transition_group_retiring_count)
    ld (regular_transition_raw_retire_count),a
    ld a,(ix+regular_lod_transition_group_entering_count)
    ld (regular_transition_raw_enter_count),a
    ld a,(regular_transition_scan_group_index)
    call regular_transition_group_is_processed
    jp nz,@advance

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
    jr z,@score
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

@score:
; With 255 slots, CPL(active_count) is the exact inactive capacity.
    ld a,(terrain_manager_active_count)
    cpl
    ld b,a
    ld a,(regular_transition_actual_enter_count)
    cp b
    jr c,@feasible
    jr z,@feasible
    jr @advance
@feasible:
    ld a,(regular_transition_actual_retire_count)
    ld b,a
    ld a,(regular_transition_actual_enter_count)
    ld c,a
    ld a,b
    sub c
    add a,16
    ld (regular_transition_candidate_score),a
    ld b,a
    ld a,(regular_transition_selected_index)
    cp regular_provider_unassigned_slot
    jr z,@choose
    ld a,(regular_transition_selected_score)
    cp b
    jr c,@choose
    jr nz,@advance
    ld a,(regular_transition_actual_enter_count)
    ld b,a
    ld a,(regular_transition_selected_enter_count)
    cp b
    jr nc,@tie_enter
    jr @advance
@tie_enter:
    jr nz,@choose
    ld a,(regular_transition_actual_retire_count)
    ld b,a
    ld a,(regular_transition_selected_retire_count)
    cp b
    jr c,@choose
    jr @advance
@choose:
    ld a,(regular_transition_scan_group_index)
    ld (regular_transition_selected_index),a
    ld hl,(regular_transition_scan_group_pointer)
    ld (regular_transition_selected_pointer),hl
    ld a,(regular_transition_candidate_score)
    ld (regular_transition_selected_score),a
    ld a,(regular_transition_actual_retire_count)
    ld (regular_transition_selected_retire_count),a
    ld a,(regular_transition_actual_enter_count)
    ld (regular_transition_selected_enter_count),a

@advance:
    ld hl,(regular_transition_scan_group_pointer)
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
    ld (regular_transition_scan_group_pointer),hl
    ld hl,regular_transition_scan_group_index
    inc (hl)
    jp @group

@selected:
    ld a,(regular_transition_selected_index)
    cp regular_provider_unassigned_slot
    jr z,@none
    or a
    ret
@none:
    scf
    ret

; Materialize the selected edge-filtered group into bounded slot/ordinal lists.
regular_transition_prepare_selected_group:
    xor a
    ld (regular_transition_actual_retire_count),a
    ld (regular_transition_actual_enter_count),a
    ld (regular_transition_stage_index),a
    ld a,regular_provider_unassigned_slot
    ld (regular_transition_stage_pending_slot),a
    ld hl,(regular_transition_selected_pointer)
    push hl
    pop ix
    ld a,(ix+regular_lod_transition_group_retiring_count)
    ld (regular_transition_raw_retire_count),a
    ld a,(ix+regular_lod_transition_group_entering_count)
    ld (regular_transition_raw_enter_count),a
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
    ld b,a
    ld a,(regular_transition_actual_retire_count)
    ld hl,0
    ld l,a
    ld de,regular_transition_retire_slots
    add hl,de
    ld (hl),b
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
    jr z,@ready
    ld hl,(regular_transition_scan_ordinal_pointer)
    ld a,(hl)
    inc hl
    ld (regular_transition_scan_ordinal_pointer),hl
    ld b,a
    call regular_transition_target_owner_present
    jr z,@new_next
    ld a,(regular_transition_actual_enter_count)
    ld hl,0
    ld l,a
    ld de,regular_transition_enter_ordinals
    add hl,de
    ld (hl),b
    ld hl,regular_transition_actual_enter_count
    inc (hl)
@new_next:
    ld hl,regular_transition_scan_remaining
    dec (hl)
    jr @new

@ready:
    ld a,(regular_transition_actual_retire_count)
    ld b,a
    ld a,(regular_transition_actual_enter_count)
    or b
    jr nz,@nonempty
    call regular_transition_mark_selected_processed
    ld a,regular_transition_state_select
    ld (regular_transition_state),a
    xor a
    ret
@nonempty:
    ld a,(regular_transition_actual_enter_count)
    or a
    ld a,regular_transition_state_commit
    jr z,@state
    ld a,regular_transition_state_stage
@state:
    ld (regular_transition_state),a
    xor a
    ret

; Load one target identity from its stable full-owner source ordinal.
regular_transition_build_enter_candidate:
    cp regular_transition_near_owner_count
    jr nc,@coarse
    ld (regular_provider_near_ordinal),a
    jp regular_provider_build_near_candidate
@coarse:
    sub regular_transition_near_owner_count
    call regular_transition_template_pointer
    ld a,(hl)
    cp regular_provider_unassigned_slot
    jr z,@bad
    call regular_provider_plan_pointer
    push hl
    pop ix
    ld a,(ix+regular_provider_plan_record_lod)
    ld (terrain_manager_candidate_lod),a
    ld a,(ix+regular_provider_plan_record_q+0)
    ld (terrain_manager_candidate_q+0),a
    ld a,(ix+regular_provider_plan_record_q+1)
    ld (terrain_manager_candidate_q+1),a
    ld a,(ix+regular_provider_plan_record_row+0)
    ld (terrain_manager_candidate_r+0),a
    ld a,(ix+regular_provider_plan_record_row+1)
    ld (terrain_manager_candidate_r+1),a
    or a
    ret
@bad:
    scf
    ret

; Exact inactive cache hits are preferred; otherwise retain the first inactive
; non-staged physical slot.  Active predecessors are never offered to command
; 50, even when their group is selected for the subsequent atomic commit.
regular_transition_find_staging_slot:
    ld a,regular_provider_unassigned_slot
    ld (regular_transition_fallback_slot),a
    xor a
    ld (regular_provider_scan_slot),a
@scan:
    ld a,(regular_provider_scan_slot)
    call terrain_manager_slot_flags_pointer
    ld a,(hl)
    and terrain_manager_flag_active+terrain_manager_flag_staged
    jr nz,@advance
    ld a,(regular_transition_fallback_slot)
    cp regular_provider_unassigned_slot
    jr nz,@match
    ld a,(regular_provider_scan_slot)
    ld (regular_transition_fallback_slot),a
@match:
    ld a,(regular_provider_scan_slot)
    ld (terrain_manager_candidate_slot),a
    call terrain_manager_slot_matches_candidate
    jr z,@found
@advance:
    ld a,(regular_provider_scan_slot)
    inc a
    ld (regular_provider_scan_slot),a
    cp terrain_manager_slot_count
    jr c,@scan
    ld a,(regular_transition_fallback_slot)
    cp regular_provider_unassigned_slot
    jr z,@none
    ld (terrain_manager_candidate_slot),a
    or a
    ret
@found:
    ld a,(regular_provider_scan_slot)
    ld (terrain_manager_candidate_slot),a
    or a
    ret
@none:
    scf
    ret

; Record a successfully staged physical slot into the authoritative target map.
regular_transition_assign_enter_slot:
    ld b,a                              ; B=physical slot
    ld a,(regular_transition_stage_index)
    ld hl,0
    ld l,a
    ld de,regular_transition_enter_ordinals
    add hl,de
    ld a,(hl)
    cp regular_transition_near_owner_count
    jr nc,@coarse
    call regular_provider_near_slot_pointer
    ld (hl),b
    ret
@coarse:
    sub regular_transition_near_owner_count
    call regular_transition_template_pointer
    ld a,(hl)
    call regular_provider_plan_pointer
    ld de,regular_provider_plan_record_slot
    add hl,de
    ld (hl),b
    ret

regular_transition_service_stage:
    ld a,(regular_transition_stage_index)
    ld hl,0
    ld l,a
    ld de,regular_transition_enter_ordinals
    add hl,de
    ld a,(hl)
    call regular_transition_build_enter_candidate
    jr c,@bad
    ld a,(regular_transition_stage_pending_slot)
    cp regular_provider_unassigned_slot
    jr nz,@slot_ready
    call regular_transition_find_staging_slot
    jr c,@bad
    ld a,(terrain_manager_candidate_slot)
    ld (regular_transition_stage_pending_slot),a
@slot_ready:
    ld (terrain_manager_candidate_slot),a
    call terrain_manager_candidate_retry_ready
    jr nz,@idle
    call terrain_manager_stage_candidate
    ret c
    ld a,(regular_transition_stage_index)
    ld hl,0
    ld l,a
    ld de,regular_transition_enter_slots
    add hl,de
    ld a,(terrain_manager_candidate_slot)
    ld (hl),a
    call regular_transition_assign_enter_slot
    ld hl,regular_transition_stage_index
    inc (hl)
    ld a,regular_provider_unassigned_slot
    ld (regular_transition_stage_pending_slot),a
    ld a,(regular_transition_actual_enter_count)
    ld b,a
    ld a,(regular_transition_stage_index)
    cp b
    jr nz,@idle
    ld a,regular_transition_state_commit
    ld (regular_transition_state),a
@idle:
    xor a
    ret
@bad:
    ld a,regular_provider_error_plan
    scf
    ret

regular_transition_service_commit:
    ld ix,regular_transition_retire_slots
    ld a,(regular_transition_actual_retire_count)
    ld b,a
    ld iy,regular_transition_enter_slots
    ld a,(regular_transition_actual_enter_count)
    ld c,a
    call terrain_manager_commit_staged_group
    ret c
    call regular_transition_mark_selected_processed
    ld a,regular_transition_state_select
    ld (regular_transition_state),a
    xor a
    ret

regular_transition_finish:
    ld a,(terrain_manager_staged_count)
    or a
    jr nz,@bad
    ld a,(terrain_manager_active_count)
    ld b,a
    ld a,(regular_provider_endpoint_count)
    cp b
    jr nz,@bad
    xor a
    ld (regular_transition_state),a
    ld (terrain_manager_scan_cursor),a
    ld (terrain_manager_converged),a
    ret
@bad:
    ld a,regular_transition_state_error
    ld (regular_transition_state),a
    ld a,regular_provider_error_plan
    scf
    ret

; Sole manager-idle dispatcher while a transaction exists.  Target records may
; be built immediately, but each tick performs at most one mesh publication or
; one atomic group commit; no render can interleave within the commit routine.
terrain_provider_service_transition:
    ld a,(regular_transition_state)
    cp regular_transition_state_wait_rebase
    jr nz,@select
    ld a,regular_transition_state_select
    ld (regular_transition_state),a
    xor a
    ret
@select:
    cp regular_transition_state_select
    jr nz,@stage
    ld a,(regular_transition_processed_count)
    ld b,a
    ld a,(regular_transition_group_count)
    cp b
    jp z,regular_transition_finish
    call regular_transition_select_feasible_group
    ret c
    jp regular_transition_prepare_selected_group
@stage:
    cp regular_transition_state_stage
    jp z,regular_transition_service_stage
    cp regular_transition_state_commit
    jp z,regular_transition_service_commit
    ld a,regular_provider_error_plan
    scf
    ret
.endif

; q must be 0..213.  offset_row=r+floor(q/2) must lie in the alternating
; 235/234-row bounded columns used by cell_id in hex_terrain.py.
hex_provider_validate_candidate:
    ld a,(terrain_manager_candidate_q+1)
    or a
    jr nz,@outside
    ld a,(terrain_manager_candidate_q)
    cp hex_provider_q_max+1
    jr nc,@outside
    ld c,a
    srl a
    ld de,0
    ld e,a
    HEX_PROVIDER_LOAD_U16_HL terrain_manager_candidate_r
    add.s hl,de
    ld a,h
    or a
    jr nz,@outside
    ld a,c
    and 1
    ld a,l
    jr nz,@odd
    cp hex_provider_even_rows
    jr @result
@odd:
    cp hex_provider_odd_rows
@result:
    jr nc,@outside
.if hex_provider_fixture_bounds_enabled
    call hex_provider_validate_fixture_bounds
    ret
.else
    or a
    ret
.endif
@outside:
    scf
    ret

.if hex_provider_fixture_bounds_enabled
; Restrict a bounded experimental corpus to one complete axial disk.  The
; manager treats clipped non-centre desired ordinals as ordinary corpus edges,
; while apply_origin_step uses the same hook to prevent rebasing outside the
; files that actually exist.
hex_provider_validate_fixture_bounds:
    HEX_PROVIDER_LOAD_U16_HL terrain_manager_candidate_q
    ld de,hex_provider_fixture_center_q
    or a
    sbc.s hl,de
    HEX_PROVIDER_STORE_U16_HL hex_provider_delta_q
    call hex_provider_abs_hl
    HEX_PROVIDER_STORE_U16_HL hex_provider_max_distance

    HEX_PROVIDER_LOAD_U16_HL terrain_manager_candidate_r
    ld de,hex_provider_fixture_center_r
    or a
    sbc.s hl,de
    HEX_PROVIDER_STORE_U16_HL hex_provider_delta_r
    call hex_provider_abs_hl
    call hex_provider_max_with_hl

    HEX_PROVIDER_LOAD_U16_HL hex_provider_delta_q
    HEX_PROVIDER_LOAD_U16_DE hex_provider_delta_r
    add.s hl,de
    call hex_provider_abs_hl
    call hex_provider_max_with_hl

    HEX_PROVIDER_LOAD_U16_HL hex_provider_max_distance
    ld a,h
    or a
    jr nz,@outside
    ld a,l
    cp hex_provider_fixture_radius+1
    jr nc,@outside
    or a
    ret
@outside:
    scf
    ret
.endif

; The validated-corpus intermediate range is -106..2574, safely inside s16.
hex_provider_compute_candidate_slot:
    HEX_PROVIDER_LOAD_U16_HL terrain_manager_candidate_q
    push hl
    add.s hl,hl                         ; 2q
    add.s hl,hl                         ; 4q
    pop de
    add.s hl,de                         ; 5q
    HEX_PROVIDER_STORE_U16_HL hex_provider_slot_accumulator

    HEX_PROVIDER_LOAD_U16_DE terrain_manager_candidate_r
    ld hl,0
    ld b,11
@times_eleven:
    add.s hl,de
    djnz @times_eleven
    HEX_PROVIDER_LOAD_U16_DE hex_provider_slot_accumulator
    add.s hl,de
@normalize_negative:
    bit 7,h
    jr z,@reduce_positive
    ld de,91
    add.s hl,de
    jr @normalize_negative
@reduce_positive:
    ld de,91
    or a
    sbc.s hl,de
    jr c,@restored
    jr @reduce_positive
@restored:
    add.s hl,de
    ld a,l
    ld (terrain_manager_candidate_slot),a
    ret

; Load, validate, CRC-check, stage, and atomically publish one candidate mesh.
; The manager activates only after this and the placement hook both succeed.
terrain_provider_load_candidate:
    ld a,(terrain_manager_candidate_lod)
    or a
    jp nz,regular_provider_load_coarse_candidate

regular_provider_load_near_candidate:
    call hex_provider_build_path
    HEX_PROVIDER_LOAD_U16_HL terrain_manager_work_mesh_id
    HEX_PROVIDER_STORE_U16_HL p3dm_target_mesh_id
    xor a
    ld (p3dm_expected_layer),a
    ld (p3dm_expected_lod),a
    ld (p3dm_expected_illumination),a
    ld (p3dm_expected_material_set),a
    ld a,pingo_shading_flat_pattern
    ld (p3dm_expected_shading),a
    HEX_PROVIDER_LOAD_U16_HL terrain_manager_candidate_q
    HEX_PROVIDER_STORE_U16_HL p3dm_expected_tile_x
    HEX_PROVIDER_LOAD_U16_HL terrain_manager_candidate_r
    HEX_PROVIDER_STORE_U16_HL p3dm_expected_tile_y
    call p3dm_load_component
    ret nz
    HEX_PROVIDER_LOAD_U16_HL terrain_manager_work_object_id
    ld de,hex_provider_object_scale_q8_8
    call pingo_set_object_uniform_scale
    xor a
    ret

regular_provider_load_coarse_candidate:
    call regular_provider_build_coarse_path
    HEX_PROVIDER_LOAD_U16_HL terrain_manager_work_mesh_id
    HEX_PROVIDER_STORE_U16_HL p3dm_target_mesh_id
    xor a
    ld (p3dm_expected_layer),a
    ld (p3dm_expected_illumination),a
    ld (p3dm_expected_material_set),a
    ld a,(terrain_manager_candidate_lod)
    ld (p3dm_expected_lod),a
    ld a,pingo_shading_flat_pattern
    ld (p3dm_expected_shading),a
    HEX_PROVIDER_LOAD_U16_HL terrain_manager_candidate_q
    HEX_PROVIDER_STORE_U16_HL p3dm_expected_tile_x
    HEX_PROVIDER_LOAD_U16_HL terrain_manager_candidate_r
    HEX_PROVIDER_STORE_U16_HL p3dm_expected_tile_y
    call p3dm_load_component
    ret nz
    call regular_provider_cache_loaded_center
    ret nz
    call regular_provider_candidate_scale
    ex de,hl
    HEX_PROVIDER_LOAD_U16_HL terrain_manager_work_object_id
    call pingo_set_object_uniform_scale
    xor a
    ret

; Produce TRH/L0/HH/LL.AGN.  The dense ID is
; floor(q/2)*470 + r + (235 when q is odd).
hex_provider_build_path:
    ld a,(terrain_manager_candidate_q)
    ld c,a
    srl a
    ld e,a
    ld d,235
    mlt de                               ; DE = floor(q/2)*235
    push de
    pop hl
    add.s hl,hl                         ; HL = floor(q/2)*470
    HEX_PROVIDER_LOAD_U16_DE terrain_manager_candidate_r
    add.s hl,de
    bit 0,c
    jr z,@id_ready
    ld de,235
    add.s hl,de
@id_ready:
    ld a,h
    ld de,regular_provider_near_filename+7
    call hex_provider_store_hex_byte
    ld a,l
    ld de,regular_provider_near_filename+10
    call hex_provider_store_hex_byte
    ld hl,regular_provider_near_filename
    ld (p3dm_filename_pointer),hl       ; ADL24 OK: native path pointer
    ret

; Produce RGL/L{8,4,2,1}/QQ/RR.AGN from the exact hierarchy identity.
regular_provider_build_coarse_path:
    ld a,(terrain_manager_candidate_lod)
    cp regular_corpus_l8_lod
    ld a,'8'
    jr z,@level
    ld a,(terrain_manager_candidate_lod)
    cp regular_corpus_l4_lod
    ld a,'4'
    jr z,@level
    ld a,(terrain_manager_candidate_lod)
    cp regular_corpus_l2_lod
    ld a,'2'
    jr z,@level
    ld a,'1'
@level:
    ld (regular_provider_coarse_filename+5),a
    ld a,(terrain_manager_candidate_q)
    ld de,regular_provider_coarse_filename+7
    call hex_provider_store_hex_byte
    ld a,(terrain_manager_candidate_r)
    ld de,regular_provider_coarse_filename+10
    call hex_provider_store_hex_byte
    ld hl,regular_provider_coarse_filename
    ld (p3dm_filename_pointer),hl       ; ADL24 OK: native path pointer
    ret

; Scale is H/8 in Q8.8 and therefore is selected by hierarchy level.
regular_provider_candidate_scale:
    ld a,(terrain_manager_candidate_lod)
    cp regular_corpus_l8_lod
    ld hl,regular_corpus_l8_object_scale_q8_8
    ret z
    cp regular_corpus_l4_lod
    ld hl,regular_corpus_l4_object_scale_q8_8
    ret z
    ld hl,regular_corpus_l2_object_scale_q8_8
    ret

; Cache the successful descriptor's actual centre, not a theoretical full-node
; centre: boundary records are clipped and have different centres.  Corpus
; offsets are nonnegative and below 2^19 metres, so metre*16 is exact s24.
regular_provider_cache_loaded_center:
    ld a,(p3dm_center_east_m+3)
    or a
    jp nz,@bad
    ld a,(p3dm_center_east_m+2)
    and 0f8h
    jp nz,@bad
    ld a,(p3dm_center_east_m+0)
    ld (regular_provider_center_work+0),a
    ld a,(p3dm_center_east_m+1)
    ld (regular_provider_center_work+1),a
    ld a,(p3dm_center_east_m+2)
    ld (regular_provider_center_work+2),a
    ld hl,(regular_provider_center_work) ; ADL24: exact east metre offset
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl
    ld (regular_provider_center_work),hl ; ADL24: exact east count
    ld a,(terrain_manager_candidate_slot)
    ld de,regular_provider_center_east_counts
    call regular_provider_center_pointer
    call regular_provider_store_center_work

    ld a,(p3dm_center_north_m+3)
    or a
    jp nz,@bad
    ld a,(p3dm_center_north_m+2)
    and 0f8h
    jp nz,@bad
    ld a,(p3dm_center_north_m+0)
    ld (regular_provider_center_work+0),a
    ld a,(p3dm_center_north_m+1)
    ld (regular_provider_center_work+1),a
    ld a,(p3dm_center_north_m+2)
    ld (regular_provider_center_work+2),a
    ld hl,(regular_provider_center_work) ; ADL24: exact north metre offset
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl
    ld (regular_provider_center_work),hl ; ADL24: exact north count
    ld a,(terrain_manager_candidate_slot)
    ld de,regular_provider_center_north_counts
    call regular_provider_center_pointer
    call regular_provider_store_center_work
    xor a
    ret
@bad:
    ld a,regular_provider_error_plan
    or a
    ret

; A=coarse slot, DE=array base -> HL=&array[(slot-91)*3].
regular_provider_center_pointer:
.if terrain_manager_group_staging
; Unified handoff slots are physical object slots, not coarse-pool ordinals.
.else
    sub regular_provider_coarse_slot_first
.endif
    ld hl,0
    ld l,a
    push hl
    add hl,hl
    pop bc
    add hl,bc
    add hl,de
    ret

regular_provider_store_center_work:
    ld a,(regular_provider_center_work+0)
    ld (hl),a
    inc hl
    ld a,(regular_provider_center_work+1)
    ld (hl),a
    inc hl
    ld a,(regular_provider_center_work+2)
    ld (hl),a
    ret

hex_provider_store_hex_byte:
    push af
    rra
    rra
    rra
    rra
    and 00fh
    call hex_provider_hex_nibble
    ld (de),a
    inc de
    pop af
    and 00fh
    call hex_provider_hex_nibble
    ld (de),a
    ret

hex_provider_hex_nibble:
    add a,'0'
    cp '9'+1
    ret c
    add a,'A'-'9'-1
    ret

; Place one candidate relative to the current axial origin using command 52.
; The table domain is exactly the desired radius-five disk.  An out-of-domain
; request is a manager/provider contract violation and fails without emitting.
terrain_provider_position_candidate:
    ld a,(terrain_manager_candidate_lod)
    or a
    jp nz,regular_provider_position_coarse_candidate

regular_provider_position_near_candidate:
    call hex_provider_q_delta_index
    jr c,@bad_delta
    push af
    ld de,hex_provider_q_x_counts
    call hex_provider_table_pointer
    ld de,hex_provider_q_x_count
    call hex_provider_copy_dl
    pop af
    ld de,hex_provider_q_z_counts
    call hex_provider_table_pointer
    ld de,hex_provider_q_z_count
    call hex_provider_copy_dl

    call hex_provider_r_delta_index
    jr c,@bad_delta
    ld de,hex_provider_r_x_counts
    call hex_provider_table_pointer
    ld de,hex_provider_r_x_count
    call hex_provider_copy_dl

    ld hl,(hex_provider_q_x_count)      ; ADL24 OK: signed command-52 count
    ld de,(hex_provider_r_x_count)      ; ADL24 OK: signed command-52 count
    add hl,de
    ld (hex_provider_translation+0),hl  ; ADL24 OK: exact signed-24 X field
    ld hl,hex_provider_terrain_y_count
    ld (hex_provider_translation+3),hl  ; ADL24 OK: exact signed-24 Y field
    ld hl,(hex_provider_q_z_count)      ; ADL24 OK: signed command-52 count
    ld (hex_provider_translation+6),hl  ; ADL24 OK: exact signed-24 Z field
    HEX_PROVIDER_LOAD_U16_HL terrain_manager_work_object_id
    ld ix,hex_provider_translation
    call pingo_set_object_xyz_translation_wide
    xor a
    ret
@bad_delta:
    ld a,1
    or a
    ret

; Actual descriptor centres are relative to REGIONAL_ORIGIN.  The live axial
; cell centre is (256+480q, 256+275q+550r) metres from that same origin, hence
; counts east=4096+7680q and north=4096+4400q+8800r. Pingo local X is north;
; this fixture corrects the legacy corpus reflection so local Z is east.
regular_provider_position_coarse_candidate:
    call regular_provider_refresh_origin_counts
    ld a,(terrain_manager_candidate_slot)
    ld de,regular_provider_center_north_counts
    call regular_provider_load_cached_center
    ld de,(regular_provider_origin_north_count) ; ADL24: exact origin count
    or a
    sbc hl,de
    ld (regular_provider_translation+0),hl ; ADL24: exact local X
    ld hl,hex_provider_terrain_y_count
    ld (regular_provider_translation+3),hl ; ADL24: exact local Y
    ld a,(terrain_manager_candidate_slot)
    ld de,regular_provider_center_east_counts
    call regular_provider_load_cached_center
    ld de,(regular_provider_origin_east_count) ; ADL24: exact origin count
    or a
    sbc hl,de
    ld (regular_provider_translation+6),hl ; ADL24: exact local Z
    HEX_PROVIDER_LOAD_U16_HL terrain_manager_work_object_id
    ld ix,regular_provider_translation
    call pingo_set_object_xyz_translation_wide
    xor a
    ret

regular_provider_load_cached_center:
    call regular_provider_center_pointer
    ld a,(hl)
    ld (regular_provider_center_work+0),a
    inc hl
    ld a,(hl)
    ld (regular_provider_center_work+1),a
    inc hl
    ld a,(hl)
    ld (regular_provider_center_work+2),a
    ld hl,(regular_provider_center_work) ; ADL24: exact cached count
    ret

regular_provider_refresh_origin_counts:
    HEX_PROVIDER_LOAD_U16_HL terrain_manager_origin_q
    ld de,7680
    call hex_provider_umul24
    ld de,4096
    add hl,de
    ld (regular_provider_origin_east_count),hl ; ADL24: exact east count

; offset_row is nonnegative throughout the bounded corpus, unlike signed axial
; r at the southeastern edge.  north=256+550*offset_row+275*(q&1) metres.
    HEX_PROVIDER_LOAD_U16_HL regular_provider_origin_offset_row
    ld de,8800
    call hex_provider_umul24
    ld de,4096
    add hl,de
    ld a,(terrain_manager_origin_q)
    and 1
    jr z,@north_ready
    ld de,4400
    add hl,de
@north_ready:
    ld (regular_provider_origin_north_count),hl ; ADL24: exact north count
    ret

hex_provider_q_delta_index:
    HEX_PROVIDER_LOAD_U16_HL terrain_manager_candidate_q
    HEX_PROVIDER_LOAD_U16_DE terrain_manager_origin_q
    or a
    sbc.s hl,de
    jr hex_provider_delta_index

hex_provider_r_delta_index:
    HEX_PROVIDER_LOAD_U16_HL terrain_manager_candidate_r
    HEX_PROVIDER_LOAD_U16_DE terrain_manager_origin_r
    or a
    sbc.s hl,de
hex_provider_delta_index:
; Desired L0 cells occupy delta -5..+5. During a one-cell rebase the preceding
; plan's outer fringe reaches exactly -6 or +6 and must remain positionable
; until all replacement detail is active.
    ld de,6
    add.s hl,de
    ld a,h
    or a
    jr nz,@outside
    ld a,l
    cp 13
    jr nc,@outside
    or a
    ret
@outside:
    scf
    ret

; Input A=0..12 and DE=table. Output HL=&table[A*3].
hex_provider_table_pointer:
    ld hl,0
    ld l,a
    ld bc,0
    ld c,a
    add hl,hl
    add hl,bc
    add hl,de
    ret

; Copy one exact three-byte signed count from HL to DE.
hex_provider_copy_dl:
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
    ret

; Return Z exactly when candidate lies in the current complete axial disk.
terrain_provider_candidate_is_desired:
    ld a,(terrain_manager_candidate_lod)
    or a
    jr z,regular_provider_near_candidate_is_desired
    ld a,(regular_provider_plan_valid)
    or a
    jr z,@stale
    xor a
    ld (regular_provider_plan_index),a
@scan:
    ld a,(regular_provider_plan_index)
    ld b,a
    ld a,(regular_provider_plan_count)
    cp b
    jr z,@stale
    ld a,b
    call regular_provider_plan_pointer
    push hl
    pop ix
    ld a,(terrain_manager_candidate_lod)
    cp (ix+regular_provider_plan_record_lod)
    jr nz,@next
    ld a,(terrain_manager_candidate_q+0)
    cp (ix+regular_provider_plan_record_q+0)
    jr nz,@next
    ld a,(terrain_manager_candidate_q+1)
    cp (ix+regular_provider_plan_record_q+1)
    jr nz,@next
    ld a,(terrain_manager_candidate_r+0)
    cp (ix+regular_provider_plan_record_row+0)
    jr nz,@next
    ld a,(terrain_manager_candidate_r+1)
    cp (ix+regular_provider_plan_record_row+1)
    jr nz,@next
    ld a,(terrain_manager_candidate_slot)
    cp (ix+regular_provider_plan_record_slot)
    jr nz,@next
    xor a
    ret
@next:
    ld a,(regular_provider_plan_index)
    inc a
    ld (regular_provider_plan_index),a
    jr @scan
@stale:
    ld a,1
    or a
    ret

regular_provider_near_candidate_is_desired:
    HEX_PROVIDER_LOAD_U16_HL terrain_manager_candidate_q
    HEX_PROVIDER_LOAD_U16_DE terrain_manager_origin_q
    or a
    sbc.s hl,de
    HEX_PROVIDER_STORE_U16_HL hex_provider_delta_q
    call hex_provider_abs_hl
    HEX_PROVIDER_STORE_U16_HL hex_provider_max_distance

    HEX_PROVIDER_LOAD_U16_HL terrain_manager_candidate_r
    HEX_PROVIDER_LOAD_U16_DE terrain_manager_origin_r
    or a
    sbc.s hl,de
    HEX_PROVIDER_STORE_U16_HL hex_provider_delta_r
    call hex_provider_abs_hl
    call hex_provider_max_with_hl

    HEX_PROVIDER_LOAD_U16_HL hex_provider_delta_q
    HEX_PROVIDER_LOAD_U16_DE hex_provider_delta_r
    add.s hl,de
    call hex_provider_abs_hl
    call hex_provider_max_with_hl

    ld a,(hex_provider_max_distance+1)
    or a
    jr nz,@stale
    ld a,(terrain_manager_current_ring)
    inc a
    ld b,a
    ld a,(hex_provider_max_distance)
    cp b
    jr c,@desired
@stale:
    ld a,1
    or a
    ret
@desired:
    xor a
    ret

; Normalize the mutable camera position into the manager's proposed axial
; origin.  IX is opaque to the manager but is the fixture's p3d camera state
; here.  The closed hex has Pingo-local corners
;
;   (x,z) = (0,-5120),(4400,-2560),(4400,2560),
;           (0,5120),(-4400,2560),(-4400,-2560).
;
; Hence the sloped half-plane witness is exactly
;
;   1024*abs(x) + 1760*abs(z) <= 9,011,200.
;
; Both (0,5120) and (4400,2560) evaluate to 9,011,200.  Rebase does not occur
; on that ownership boundary.  The current origin retains a fixed 256-count
; (16 m) outward band.  For each sloped edge the exact integer witness is
;
;   round(256*sqrt(1024^2+1760^2)) = 521,271,
;   retained half-plane RHS = 9,532,471.
;
; The expanded vertical and tip quick bounds are respectively 4,656 and
; 5,376 counts.  Exact outer-limit ties retain the current origin; the first
; integer beyond a limit selects a neighbor.  The branch order below gives
; corners a deterministic vertical-before-sloped tie rule.  After a rebase,
; applying the same expanded hex around the new origin supplies the symmetric
; deadband, so boundary jitter cannot immediately select the old origin.
; Axis checks reduce arbitrarily displaced signed-word inputs before the
; multiplication, so each unsigned product and sum fits in 24 bits.
terrain_provider_normalize_position:
    push iy
.if terrain_manager_group_staging
    call terrain_provider_transition_busy
    or a
    jr z,@transition_idle
    pop iy
    or a
    ret
@transition_idle:
; Recipes are qualified only for a complete radius-five endpoint.  Cold fill,
; stale retirement, or a pre-unified smaller-ring view leaves camera motion in
; local coordinates until an exact endpoint is active; it cannot start from a
; partial owner snapshot.
    ld a,(terrain_manager_current_ring)
    cp regular_lod_transition_near_radius
    jr nz,@transition_deferred
    ld a,(regular_provider_plan_valid)
    or a
    jr z,@transition_deferred
    ld a,(terrain_manager_converged)
    or a
    jr z,@transition_deferred
    ld a,(regular_provider_endpoint_count)
    ld b,a
    ld a,(terrain_manager_active_count)
    cp b
    jr nz,@transition_deferred
    ld a,(terrain_manager_staged_count)
    or a
    jr z,@transition_ready
@transition_deferred:
    pop iy
    xor a
    ret
@transition_ready:
.endif
    xor a
    ld (hex_provider_origin_changed),a
@again:
    HEX_PROVIDER_LOAD_CAMERA_HL p3d_camera_world_position+p3d_vec3_x
    HEX_PROVIDER_STORE_U16_HL hex_provider_local_x
    call hex_provider_abs_hl
    HEX_PROVIDER_STORE_U16_HL hex_provider_abs_x
    ld de,hex_provider_vertical_exit_first
    or a
    sbc.s hl,de
    jr nc,@outside_vertical

    HEX_PROVIDER_LOAD_CAMERA_HL p3d_camera_world_position+p3d_vec3_z
    HEX_PROVIDER_STORE_U16_HL hex_provider_local_z
    call hex_provider_abs_hl
    HEX_PROVIDER_STORE_U16_HL hex_provider_abs_z
    ld de,hex_provider_tip_exit_first
    or a
    sbc.s hl,de
    jr nc,@outside_sloped

    HEX_PROVIDER_LOAD_U16_HL hex_provider_abs_x
    ld de,1024
    call hex_provider_umul24
    ld (hex_provider_halfplane_term),hl ; ADL24 OK: exact unsigned product
    HEX_PROVIDER_LOAD_U16_HL hex_provider_abs_z
    ld de,1760
    call hex_provider_umul24
    ld de,(hex_provider_halfplane_term) ; ADL24 OK: exact unsigned product
    add hl,de
    ld de,hex_provider_sloped_exit_first ; first value outside retention band
    or a
    sbc hl,de
    jr nc,@outside_sloped
    jr @normalized

@outside_vertical:
    ld a,(hex_provider_local_x+1)
    bit 7,a
    ld a,0                             ; north: origin (0,+1)
    jr z,@apply
    ld a,1                             ; south: origin (0,-1)
    jr @apply

@outside_sloped:
    ld a,(hex_provider_local_z+1)
    bit 7,a
    jr nz,@west
    ld a,(hex_provider_local_x+1)
    bit 7,a
    ld a,2                             ; northeast/east: (+1,0)
    jr z,@apply
    ld a,3                             ; southeast/east: (+1,-1)
    jr @apply
@west:
    ld a,(hex_provider_local_x+1)
    bit 7,a
    ld a,4                             ; northwest/west: (-1,+1)
    jr z,@apply
    ld a,5                             ; southwest/west: (-1,0)

@apply:
.if terrain_manager_group_staging
    ld (regular_transition_direction),a
    ld a,(terrain_manager_origin_q)
    and 7
    ld (regular_transition_old_phase_q),a
    ld a,(regular_provider_origin_offset_row)
    and 3
    ld (regular_transition_old_phase_row),a
    ld a,(regular_transition_direction)
.endif
    call hex_provider_apply_origin_step
    jr nz,@normalized                  ; bounded coverage edge
.if terrain_manager_group_staging
; One canonical recipe covers exactly one adjacent move.  Large local camera
; displacement catches up one transaction at a time after each handoff.
    jr @normalized
.else
    jp @again
.endif

@normalized:
    ld a,(hex_provider_origin_changed)
    or a
    jr z,@unchanged
    ld a,(ix+p3d_camera_dirty)
    or p3d_camera_dirty_position
    ld (ix+p3d_camera_dirty),a
    pop iy
    scf
    ret
@unchanged:
    pop iy
    or a
    ret

; Input A selects one record in dq,dr,origin-local-X,origin-local-Z order.
; Return Z after applying it, or NZ if the proposed origin leaves coverage.
hex_provider_apply_origin_step:
    ld hl,0
    ld l,a
    add hl,hl                         ; 2*n
    ld de,0
    ld e,a
    add hl,de                         ; 3*n
    add hl,hl                         ; 6*n
    ld de,hex_provider_origin_steps
    add hl,de
    push hl
    pop iy

    HEX_PROVIDER_LOAD_U16_HL terrain_manager_proposed_origin_q
    ld de,0
    ld e,(iy+0)
    bit 7,e
    jr z,@q_extended
    ld d,0ffh
@q_extended:
    add.s hl,de
    HEX_PROVIDER_STORE_U16_HL terrain_manager_candidate_q
    HEX_PROVIDER_LOAD_U16_HL terrain_manager_proposed_origin_r
    ld de,0
    ld e,(iy+1)
    bit 7,e
    jr z,@r_extended
    ld d,0ffh
@r_extended:
    add.s hl,de
    HEX_PROVIDER_STORE_U16_HL terrain_manager_candidate_r
    call hex_provider_validate_candidate
    jr c,@edge

    HEX_PROVIDER_LOAD_U16_HL terrain_manager_candidate_q
    HEX_PROVIDER_STORE_U16_HL terrain_manager_proposed_origin_q
    HEX_PROVIDER_LOAD_U16_HL terrain_manager_candidate_r
    HEX_PROVIDER_STORE_U16_HL terrain_manager_proposed_origin_r

    HEX_PROVIDER_LOAD_CAMERA_HL p3d_camera_world_position+p3d_vec3_x
    ld de,0
    ld e,(iy+2)
    ld d,(iy+3)
    or a
    sbc.s hl,de
    HEX_PROVIDER_STORE_CAMERA_HL p3d_camera_world_position+p3d_vec3_x
    HEX_PROVIDER_LOAD_CAMERA_HL p3d_camera_world_position+p3d_vec3_z
    ld de,0
    ld e,(iy+4)
    ld d,(iy+5)
    or a
    sbc.s hl,de
    HEX_PROVIDER_STORE_CAMERA_HL p3d_camera_world_position+p3d_vec3_z
    ld a,1
    ld (hex_provider_origin_changed),a
    xor a
    ret
@edge:
    ld a,1
    or a
    ret

hex_provider_abs_hl:
    bit 7,h
    ret z
    ld de,0
    ex de,hl
    or a
    sbc.s hl,de
    ret

hex_provider_max_with_hl:
    HEX_PROVIDER_LOAD_U16_DE hex_provider_max_distance
    push hl
    or a
    sbc.s hl,de
    pop hl
    ret c
    HEX_PROVIDER_STORE_U16_HL hex_provider_max_distance
    ret

; Proven arith24 unsigned multiply, kept local because the complete donor file
; also contains unrelated routines with additional library dependencies.
; Input HL*DE -> HL; preserves AF, BC, DE.
hex_provider_umul24:
    push de
    push bc
    push af
    push hl
    pop bc
    ld a,24
    ld hl,0
@loop:
    add hl,hl
    ex de,hl
    add hl,hl
    ex de,hl
    jr nc,@no_add
    add hl,bc
@no_add:
    dec a
    jr nz,@loop
    pop af
    pop bc
    pop de
    ret

hex_provider_ring_counts:
    db 1,7,19,37,61,91

; Centre, then clockwise rings with a deterministic northwest start.
hex_provider_disk_offsets:
    db 0,0, -1,1, 0,1, 1,0, 1,-1, 0,-1, -1,0
    db -2,2, -1,2, 0,2, 1,1, 2,0, 2,-1, 2,-2
    db 1,-2, 0,-2, -1,-1, -2,0, -2,1, -3,3, -2,3
    db -1,3, 0,3, 1,2, 2,1, 3,0, 3,-1, 3,-2
    db 3,-3, 2,-3, 1,-3, 0,-3, -1,-2, -2,-1, -3,0
    db -3,1, -3,2, -4,4, -3,4, -2,4, -1,4, 0,4
    db 1,3, 2,2, 3,1, 4,0, 4,-1, 4,-2, 4,-3
    db 4,-4, 3,-4, 2,-4, 1,-4, 0,-4, -1,-3, -2,-2
    db -3,-1, -4,0, -4,1, -4,2, -4,3, -5,5, -4,5
    db -3,5, -2,5, -1,5, 0,5, 1,4, 2,3, 3,2
    db 4,1, 5,0, 5,-1, 5,-2, 5,-3, 5,-4, 5,-5
    db 4,-5, 3,-5, 2,-5, 1,-5, 0,-5, -1,-4, -2,-3
    db -3,-2, -4,-1, -5,0, -5,1, -5,2, -5,3, -5,4

; Index -6..+6. Each entry is one exact signed 24-bit translation count. The
; outer pair exists solely for conservative old-plan retention during rebase.
hex_provider_q_x_counts:
    dl -26400,-22000,-17600,-13200,-8800,-4400,0
    dl 4400,8800,13200,17600,22000,26400
hex_provider_q_z_counts:
    dl -46080,-38400,-30720,-23040,-15360,-7680,0
    dl 7680,15360,23040,30720,38400,46080
hex_provider_r_x_counts:
    dl -52800,-44000,-35200,-26400,-17600,-8800,0
    dl 8800,17600,26400,35200,44000,52800

; dq,dr and corresponding origin-centre displacement in Pingo local X/Z.
hex_provider_origin_steps:
    db 0,1
    dw 8800,0
    db 0,-1
    dw -8800,0
    db 1,0
    dw 4400,7680
    db 1,-1
    dw -4400,7680
    db -1,1
    dw 4400,-7680
    db -1,0
    dw -4400,-7680

hex_provider_slot_accumulator: dw 0
hex_provider_delta_q: dw 0
hex_provider_delta_r: dw 0
hex_provider_max_distance: dw 0
hex_provider_local_x: dw 0
hex_provider_local_z: dw 0
hex_provider_abs_x: dw 0
hex_provider_abs_z: dw 0
hex_provider_halfplane_term: dl 0
hex_provider_origin_changed: db 0
hex_provider_q_x_count: dl 0
hex_provider_q_z_count: dl 0
hex_provider_r_x_count: dl 0
hex_provider_translation: ds 9

regular_provider_near_filename:
    db "TRH/L0/00/00.AGN",0
regular_provider_coarse_filename:
    db "RGL/L8/00/00.AGN",0
regular_provider_plan_valid: db 0
regular_provider_plan_count: db 0
regular_provider_desired_count: db 1
regular_provider_origin_offset_row: dw 0
regular_provider_phase_remaining: db 0
regular_provider_phase_pointer: dl 0
regular_provider_build_lod: db 0
regular_provider_build_q: dw 0
regular_provider_build_row: dw 0
regular_provider_plan_index: db 0
regular_provider_scan_slot: db 0
regular_provider_pool_index: db 0
regular_provider_center_work: dl 0
regular_provider_origin_east_count: dl 0
regular_provider_origin_north_count: dl 0
regular_provider_translation: ds 9
regular_provider_plan: ds regular_provider_plan_max*regular_provider_plan_record_bytes
regular_provider_claimed_slots: ds regular_provider_coarse_slot_count
.if terrain_manager_group_staging
regular_provider_near_ordinal: db 0
regular_provider_near_slots: ds regular_provider_near_slot_count
regular_provider_near_valid: ds regular_provider_near_slot_count
regular_provider_plan_source_ordinals: ds regular_provider_plan_max
regular_provider_phase_source_ordinal: db 0
regular_provider_build_source_ordinal: db 0
regular_provider_endpoint_count: db 0
regular_provider_endpoint_near_limit: db 0
regular_provider_unified_slots: db 0

regular_transition_state: db 0
regular_transition_build_target: db 0
regular_transition_direction: db 0
regular_transition_old_phase_q: db 0
regular_transition_old_phase_row: db 0
regular_transition_recipe_pointer: dl 0
regular_transition_groups_pointer: dl 0
regular_transition_scan_group_pointer: dl 0
regular_transition_selected_pointer: dl 0
regular_transition_scan_ordinal_pointer: dl 0
regular_transition_group_count: db 0
regular_transition_processed_count: db 0
regular_transition_scan_group_index: db 0
regular_transition_selected_index: db 0
regular_transition_group_checked_index: db 0
regular_transition_raw_retire_count: db 0
regular_transition_raw_enter_count: db 0
regular_transition_actual_retire_count: db 0
regular_transition_actual_enter_count: db 0
regular_transition_selected_retire_count: db 0
regular_transition_selected_enter_count: db 0
regular_transition_selected_score: db 0
regular_transition_candidate_score: db 0
regular_transition_scan_remaining: db 0
regular_transition_stage_index: db 0
regular_transition_stage_pending_slot: db 0
regular_transition_fallback_slot: db 0
regular_transition_processed_groups: ds regular_transition_processed_bytes
regular_transition_bit_masks: db 1,2,4,8,16,32,64,128
regular_transition_retire_slots: ds regular_lod_transition_maximum_retiring
regular_transition_enter_ordinals: ds regular_lod_transition_maximum_entering
regular_transition_enter_slots: ds regular_lod_transition_maximum_entering
regular_transition_old_slot_by_ordinal: ds regular_transition_owner_count
regular_transition_target_template_to_dense: ds regular_transition_coarse_owner_count
.endif
.if terrain_manager_group_staging
regular_provider_center_east_counts: ds terrain_manager_slot_count*3
regular_provider_center_north_counts: ds terrain_manager_slot_count*3
.else
regular_provider_center_east_counts: ds regular_provider_coarse_slot_count*3
regular_provider_center_north_counts: ds regular_provider_coarse_slot_count*3
.endif
