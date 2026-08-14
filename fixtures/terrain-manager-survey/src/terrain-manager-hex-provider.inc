; =============================================================================
; Bay Area flat-top axial-hex provider for the universal terrain manager.
;
; This file owns topology and corpus policy only.  The shared manager owns
; desired-set traversal, resident state, bounded publication, activation, and
; shutdown.  Axial q/r remain signed u16 in every manager/P3DM field.
;
; Every radius-five disk maps bijectively onto the 91 stable slots through
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

; Input A is a qualified ring 0..5.  Output A is its complete disk count.
terrain_provider_ring_count:
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
    call hex_provider_compute_candidate_slot
    xor a
    ld (terrain_manager_candidate_lod),a
    or a
    ret

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

; Produce TRH/L0/HH/LL.AGN.  The dense ID is
; floor(q/2)*470 + r + (235 when q is odd).
hex_provider_build_path:
.if hex_provider_natural_namespace
    ld a,'N'
    ld (p3dm_filename_buffer+0),a
    ld a,'A'
    ld (p3dm_filename_buffer+1),a
    ld a,'T'
    ld (p3dm_filename_buffer+2),a
.else
    ld a,'H'
    ld (p3dm_filename_buffer+2),a
.endif
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
    ld de,p3dm_filename_buffer+7
    call hex_provider_store_hex_byte
    ld a,l
    ld de,p3dm_filename_buffer+10
    call hex_provider_store_hex_byte
    ld hl,p3dm_filename_buffer
    ld (p3dm_filename_pointer),hl       ; ADL24 OK: native path pointer
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
    ld de,5
    add.s hl,de
    ld a,h
    or a
    jr nz,@outside
    ld a,l
    cp 11
    jr nc,@outside
    or a
    ret
@outside:
    scf
    ret

; Input A=0..10 and DE=table.  Output HL=&table[A*3].
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
    jr z,@west
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
    call hex_provider_apply_origin_step
    jr nz,@normalized                  ; bounded coverage edge
    jp @again

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

; Index -5..+5.  Each entry is one exact signed 24-bit translation count.
hex_provider_q_x_counts:
    dl -22000,-17600,-13200,-8800,-4400,0,4400,8800,13200,17600,22000
hex_provider_q_z_counts:
    dl 38400,30720,23040,15360,7680,0,-7680,-15360,-23040,-30720,-38400
hex_provider_r_x_counts:
    dl -44000,-35200,-26400,-17600,-8800,0,8800,17600,26400,35200,44000

; dq,dr and corresponding origin-centre displacement in Pingo local X/Z.
hex_provider_origin_steps:
    db 0,1
    dw 8800,0
    db 0,-1
    dw -8800,0
    db 1,0
    dw 4400,-7680
    db 1,-1
    dw -4400,-7680
    db -1,1
    dw 4400,7680
    db -1,0
    dw -4400,7680

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
