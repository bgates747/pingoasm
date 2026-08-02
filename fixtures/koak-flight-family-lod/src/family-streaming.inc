; =============================================================================
; Fixed-west nested-family LOD coordinator.
;
; This sibling fixture proves one complete (23,36)->(22,36) handoff without
; modifying the accepted loose 5x5 KOAK runtime. Generated family-plan.inc is
; the sole source of component identities, centres, scales, and swap IDs.
; =============================================================================

terrain_slot_count: equ 37
airport_pavement_mesh_id: equ 101
airport_marking_mesh_id: equ 102
airport_pavement_object_id: equ 101
airport_marking_object_id: equ 102

regional_start_tile_x: equ 94
regional_start_tile_y: equ 146
regional_family_west_boundary_x: equ 92
regional_tile_position_q8_high: equ 020h
regional_half_tile_q8_high: equ 010h
regional_negative_half_tile_q8_high: equ 0F0h
regional_terrain_y_count: equ 9728
koak_group0_scale_q8_8: equ 53056

family_entry_slot: equ 0
family_entry_family_id: equ 1
family_entry_lod: equ 3
family_entry_tile_x: equ 4
family_entry_tile_y: equ 6
family_entry_center_east_counts: equ 8
family_entry_center_north_counts: equ 11
family_entry_scale: equ 14
family_entry_activate: equ 16

    include "../tgt/family-plan.inc"

    MACRO STREAM_ST_U16_HL ADDRESS
        ld a,l
        ld (ADDRESS),a
        ld a,h
        ld (ADDRESS+1),a
    ENDMACRO

    MACRO STREAM_LD_U16_HL ADDRESS
        ld hl,0
        ld a,(ADDRESS)
        ld l,a
        ld a,(ADDRESS+1)
        ld h,a
    ENDMACRO

streaming_initialize:
    ld a,regional_start_tile_x
    ld (streaming_coarse_x),a
    ld a,regional_start_tile_y
    ld (streaming_coarse_y),a
    xor a
    ld (family_plan_cursor),a
    ld (family_error_hold),a
    ld (family_swap_complete),a
    ld (streaming_last_error),a
    ld (streaming_scene_dirty),a
    ld (streaming_airport_pair_loaded),a
    inc a
    ld (streaming_origin_dirty),a
    ld hl,family_path_buffer
    ld (p3dm_filename_pointer),hl ; ADL24 OK: native 24-bit path pointer
    ret

; First-frame barrier: all eight current-family L0 strips and the KOAK hard
; surfaces. D1/D2 and the complete inactive next bank then arrive one record
; per ordinary render-idle service pass.
streaming_load_startup:
@near:
    ld a,(family_plan_cursor)
    cp family_plan_boot_count
    jr nc,@airports
    call family_load_current_entry
    ret nz
    jr @near

@airports:
    ld hl,koak_pavement_path
    ld (p3dm_filename_pointer),hl ; ADL24 OK: native 24-bit path pointer
    ld hl,airport_pavement_mesh_id
    call streaming_request_airport_pavement
    call p3dm_load_component
    jp nz,streaming_record_load_error
    ld hl,airport_pavement_object_id
    ld de,koak_group0_scale_q8_8
    call pingo_set_object_uniform_scale

    ld hl,koak_marking_path
    ld (p3dm_filename_pointer),hl ; ADL24 OK: native 24-bit path pointer
    ld hl,airport_marking_mesh_id
    call streaming_request_airport_marking
    call p3dm_load_component
    jp nz,streaming_record_load_error
    ld hl,airport_marking_object_id
    ld de,koak_group0_scale_q8_8
    call pingo_set_object_uniform_scale

    ld a,1
    ld (streaming_airport_pair_loaded),a
    call streaming_reposition_airport
    ld hl,family_path_buffer
    ld (p3dm_filename_pointer),hl ; ADL24 OK: native 24-bit path pointer
    xor a
    ret

streaming_request_airport_pavement:
    call streaming_store_target_mesh_hl
    ld a,1
    ld (p3dm_expected_layer),a
    jr streaming_request_airport_common

streaming_request_airport_marking:
    call streaming_store_target_mesh_hl
    ld a,2
    ld (p3dm_expected_layer),a
streaming_request_airport_common:
    xor a
    ld (p3dm_expected_lod),a
    ld a,pingo_shading_flat_palette
    ld (p3dm_expected_shading),a
    ld a,pingo_mesh_illumination_self
    ld (p3dm_expected_illumination),a
    ld a,1
    ld (p3dm_expected_material_set),a
    ld hl,91
    STREAM_ST_U16_HL p3dm_expected_tile_x
    ld hl,145
    STREAM_ST_U16_HL p3dm_expected_tile_y
    ret

streaming_store_target_mesh_hl:
    STREAM_ST_U16_HL p3dm_target_mesh_id
    ret

; Rendering is idle at every call site. Rebase all resident entries first,
; perform the disk-free atomic swap if the aircraft crossed west, otherwise
; publish at most one selected nested record.
streaming_service_one:
    ld a,(streaming_origin_dirty)
    or a
    call nz,family_reposition_all
    call family_maybe_swap
    ld a,(family_error_hold)
    or a
    ret nz
    ld a,(family_plan_cursor)
    cp family_plan_total_count
    ret nc
    call family_load_current_entry
    ret

family_load_current_entry:
    ld a,(family_plan_cursor)
    call family_plan_pointer_a
    call family_initialize_request_ix
    call agnb_load_selected_component
    jr nz,streaming_record_load_error_hold

; The selected descriptor has passed the exact loader. Re-resolve the generated
; entry because the loader is free to clobber IX.
    ld a,(family_plan_cursor)
    call family_plan_pointer_a
    ld a,(ix+family_entry_activate)
    ld (family_entry_activate_latched),a
    ld hl,0
    ld l,(ix+family_entry_slot)
    ld de,0
    ld e,(ix+family_entry_scale)
    ld d,(ix+family_entry_scale+1)
    call pingo_set_object_uniform_scale
    call family_position_entry_ix
    ld a,(family_entry_activate_latched)
    or a
    jr z,@resident
    ld hl,0
    ld a,(family_position_slot)
    ld l,a
    ld a,1
    call pingo_set_object_active
@resident:
    ld a,(family_plan_cursor)
    inc a
    ld (family_plan_cursor),a
    ld a,1
    ld (streaming_scene_dirty),a
    ld a,'.'
    rst.lil 10h
    xor a
    ret

streaming_record_load_error_hold:
    ld (streaming_last_error),a
    ld a,1
    ld (family_error_hold),a
    ld a,(streaming_last_error)
    or a
    ret

streaming_record_load_error:
    ld (streaming_last_error),a
    or a
    ret

; A indexes one exact 17-byte generated record and returns IX. The nested
; loader selects by the complete descriptor identity, not physical LIST order.
family_plan_pointer_a:
    ld de,0                   ; ADL24: MLT changes only DE[15:0]
    ld e,a
    ld d,family_plan_entry_size
    mlt de
    ld hl,family_plan_table
    add hl,de
    push hl
    pop ix
    ret

family_initialize_request_ix:
    call family_build_path_ix
    ld hl,0
    ld l,(ix+family_entry_slot)
    call streaming_store_target_mesh_hl
    xor a
    ld (p3dm_expected_layer),a
    ld (p3dm_expected_illumination),a
    ld (p3dm_expected_material_set),a
    ld a,pingo_shading_flat_pattern
    ld (p3dm_expected_shading),a
    ld a,(ix+family_entry_lod)
    ld (p3dm_expected_lod),a
    ld a,(ix+family_entry_tile_x)
    ld (p3dm_expected_tile_x),a
    ld a,(ix+family_entry_tile_x+1)
    ld (p3dm_expected_tile_x+1),a
    ld a,(ix+family_entry_tile_y)
    ld (p3dm_expected_tile_y),a
    ld a,(ix+family_entry_tile_y+1)
    ld (p3dm_expected_tile_y+1),a
    ret

; RGN/HH/LL.AGN from the generated u16 row-major family ID.
family_build_path_ix:
    ld a,(ix+family_entry_family_id+1)
    ld de,family_path_buffer+4
    call streaming_store_hex_byte
    ld a,(ix+family_entry_family_id)
    ld de,family_path_buffer+7
    call streaming_store_hex_byte
    ld hl,family_path_buffer
    ld (p3dm_filename_pointer),hl ; ADL24 OK: native 24-bit path pointer
    ret

; Inputs: A=byte, DE=two-character destination.
streaming_store_hex_byte:
    push af
    rra
    rra
    rra
    rra
    and 00Fh
    call streaming_hex_nibble
    ld (de),a
    inc de
    pop af
    and 00Fh
    call streaming_hex_nibble
    ld (de),a
    ret

streaming_hex_nibble:
    add a,'0'
    cp '9'+1
    ret c
    add a,'A'-'9'-1
    ret

; Position one generated component relative to the current 512 m coarse cell.
; IX points at its exact entry. Command 52 consumes signed s24 raw counts.
family_position_entry_ix:
    ld a,(ix+family_entry_slot)
    ld (family_position_slot),a

    ld a,(streaming_coarse_y)
    call family_coarse_center_counts_a
    ld de,(ix+family_entry_center_north_counts) ; ADL24 OK: generated dl field
    ex de,hl
    or a
    sbc hl,de
    ld (family_position_xyz+0),hl ; ADL24 OK: exact signed dl coordinate

    ld hl,regional_terrain_y_count
    ld (family_position_xyz+3),hl ; ADL24 OK: exact signed dl coordinate

    ld a,(streaming_coarse_x)
    call family_coarse_center_counts_a
    ld de,(ix+family_entry_center_east_counts) ; ADL24 OK: generated dl field
    or a
    sbc hl,de
    ld (family_position_xyz+6),hl ; ADL24 OK: exact signed dl coordinate

    ld hl,0
    ld a,(family_position_slot)
    ld l,a
    ld ix,family_position_xyz
    jp pingo_set_object_xyz_translation_wide

; A=base tile coordinate -> region-relative centre in translation counts:
; A*512*16 + 256*16 = A*8192 + 4096.
family_coarse_center_counts_a:
    ld hl,0
    ld l,a
    ld a,13
@shift:
    add hl,hl
    dec a
    jr nz,@shift
    ld de,4096
    add hl,de
    ret

family_reposition_all:
    xor a
    ld (streaming_origin_dirty),a
    ld (family_reposition_index),a
@next:
    ld a,(family_reposition_index)
    ld b,a
    ld a,(family_plan_cursor)
    cp b
    jr z,@airport
    ld a,b
    call family_plan_pointer_a
    call family_position_entry_ix
    ld a,(family_reposition_index)
    inc a
    ld (family_reposition_index),a
    jr @next
@airport:
    call streaming_reposition_airport
    ld a,1
    ld (streaming_scene_dirty),a
    ret

; No disk I/O is permitted here. All thirteen deactivations precede all
; thirteen activations, and the next render is submitted only after return.
family_maybe_swap:
    ld a,(family_swap_complete)
    or a
    ret nz
    ld a,(family_plan_cursor)
    cp family_plan_total_count
    ret nz
    ld a,(streaming_coarse_x)
    cp regional_family_west_boundary_x
    ret nc

    ld ix,family_swap_deactivate_ids
    ld a,family_swap_deactivate_count
    ld (family_swap_remaining),a
@deactivate:
    ld hl,0
    ld l,(ix+0)
    xor a
    call pingo_set_object_active
    inc ix
    ld hl,family_swap_remaining
    dec (hl)
    jr nz,@deactivate

    ld ix,family_swap_activate_ids
    ld a,family_swap_activate_count
    ld (family_swap_remaining),a
@activate:
    ld hl,0
    ld l,(ix+0)
    ld a,1
    call pingo_set_object_active
    inc ix
    ld hl,family_swap_remaining
    dec (hl)
    jr nz,@activate

    ld a,1
    ld (family_swap_complete),a
    ld (streaming_scene_dirty),a
    ld a,'S'
    rst.lil 10h
    xor a
    ret

; Signed byte A -> signed word A*8192 in HL for the retained KOAK transform.
streaming_delta_to_count:
    ld l,a
    ld h,0
    bit 7,l
    jr z,@extended
    ld h,0FFh
@extended:
    ld a,13
@shift:
    add.s hl,hl
    dec a
    jr nz,@shift
    ret

; KOAK group 0 remains active while its known transform is representable.
streaming_reposition_airport:
    ld a,(streaming_airport_pair_loaded)
    or a
    ret z
    ld a,(streaming_coarse_x)
    cp 87
    jr c,@inactive
    cp 95
    jr nc,@inactive
    ld a,(streaming_coarse_y)
    cp 142
    jr c,@inactive
    cp 150
    jr nc,@inactive

; X = -8176 - (coarse_y-146)*8192.
    ld a,(streaming_coarse_y)
    sub regional_start_tile_y
    neg
    call streaming_delta_to_count
    ld de,-8176
    add.s hl,de
    push hl
    pop bc
; Z = 26816 + (coarse_x-94)*8192.
    ld a,(streaming_coarse_x)
    sub regional_start_tile_x
    call streaming_delta_to_count
    ld de,26816
    add.s hl,de
    push hl
    pop iy
    ld hl,airport_pavement_object_id
    ld de,regional_terrain_y_count
    push bc
    push iy
    call sodabs
    pop iy
    pop bc
    ld hl,airport_marking_object_id
    ld de,regional_terrain_y_count
    call sodabs
    ld hl,airport_pavement_object_id
    ld a,1
    call pingo_set_object_active
    ld hl,airport_marking_object_id
    ld a,1
    call pingo_set_object_active
    ret
@inactive:
    ld hl,airport_pavement_object_id
    xor a
    call pingo_set_object_active
    ld hl,airport_marking_object_id
    xor a
    jp pingo_set_object_active

; Normalize flight X/Z after each fixed simulation quantum. The half-cell
; convention is [-0x100000,+0x100000); one complete cell is 0x200000.
streaming_rebase_flight:
    xor a
    ld (streaming_rebased_this_step),a
    ld a,(flight_position_x_q8+2)
    bit 7,a
    jr nz,@x_negative
    cp regional_half_tile_q8_high
    jr c,@z
    sub regional_tile_position_q8_high
    ld (flight_position_x_q8+2),a
    ld hl,streaming_coarse_y
    inc (hl)
    jr @mark_x
@x_negative:
    cp regional_negative_half_tile_q8_high
    jr nc,@z
    add a,regional_tile_position_q8_high
    ld (flight_position_x_q8+2),a
    ld hl,streaming_coarse_y
    dec (hl)
@mark_x:
    ld a,1
    ld (streaming_rebased_this_step),a
@z:
    ld a,(flight_position_z_q8+2)
    bit 7,a
    jr nz,@z_negative
    cp regional_half_tile_q8_high
    jr c,@done_axes
; Positive Pingo Z is west, hence tile_x decreases.
    sub regional_tile_position_q8_high
    ld (flight_position_z_q8+2),a
    ld hl,streaming_coarse_x
    dec (hl)
    jr @mark_z
@z_negative:
    cp regional_negative_half_tile_q8_high
    jr nc,@done_axes
; Negative Pingo Z is east, hence tile_x increases.
    add a,regional_tile_position_q8_high
    ld (flight_position_z_q8+2),a
    ld hl,streaming_coarse_x
    inc (hl)
@mark_z:
    ld a,1
    ld (streaming_rebased_this_step),a
@done_axes:
    ld a,(streaming_rebased_this_step)
    or a
    ret z
    ld (streaming_origin_dirty),a
    call flight_publish_position
    ret

; Override the preserved Berkeley trim with a stationary, supported KOAK 28L
; start and initialize the retained local-to-world matrix at the runway yaw.
koak_flight_initial_state:
    ld ix,object_state
; The aircraft reference is 1.25 m below and 3 m aft of the authored cockpit
; eye. At the runway heading this position makes aircraft_view_init publish
; the canonical 28L camera witness (3106,64,2226) exactly.
    ld hl,3088
    ld (ix+p3d_object_world_position+p3d_vec3_x),l
    ld (ix+p3d_object_world_position+p3d_vec3_x+1),h
    ld hl,44
    ld (ix+p3d_object_world_position+p3d_vec3_y),l
    ld (ix+p3d_object_world_position+p3d_vec3_y+1),h
    ld hl,2181
    ld (ix+p3d_object_world_position+p3d_vec3_z),l
    ld (ix+p3d_object_world_position+p3d_vec3_z+1),h
    xor a
    ld (ix+p3d_object_pingo_rotation+p3d_vec3_x),a
    ld (ix+p3d_object_pingo_rotation+p3d_vec3_x+1),a
    ld hl,-14411
    ld (ix+p3d_object_pingo_rotation+p3d_vec3_y),l
    ld (ix+p3d_object_pingo_rotation+p3d_vec3_y+1),h
    xor a
    ld (ix+p3d_object_pingo_rotation+p3d_vec3_z),a
    ld (ix+p3d_object_pingo_rotation+p3d_vec3_z+1),a
    ld a,p3d_object_dirty_all
    ld (ix+p3d_object_dirty),a
    ld hl,aircraft_jet_object_scale_q8_8
    ld (ix+p3d_object_scale+p3d_vec3_x),l
    ld (ix+p3d_object_scale+p3d_vec3_x+1),h
    ld (ix+p3d_object_scale+p3d_vec3_y),l
    ld (ix+p3d_object_scale+p3d_vec3_y+1),h
    ld (ix+p3d_object_scale+p3d_vec3_z),l
    ld (ix+p3d_object_scale+p3d_vec3_z+1),h
    lea iy,ix+p3d_object_pingo_rotation
    lea ix,ix+p3d_object_orientation
    call p3d_mat3_from_euler16

    ld hl,flight_position_x_q8
    ld b,12
    xor a
@clear_positions:
    ld (hl),a
    inc hl
    djnz @clear_positions
    ld hl,3088
    STREAM_ST_U16_HL flight_position_x_q8+1
    ld hl,44
    STREAM_ST_U16_HL flight_position_y_q8+1
    STREAM_ST_U16_HL flight_ground_y_q8+1
    ld hl,2181
    STREAM_ST_U16_HL flight_position_z_q8+1
    ld hl,flight_velocity_q8
    ld b,p3d_vec3_size
    xor a
@clear_velocity:
    ld (hl),a
    inc hl
    djnz @clear_velocity
    xor a
    ld (flight_airspeed_q8),a
    ld (flight_airspeed_q8+1),a
    ld (flight_lift_q8),a
    ld (flight_lift_q8+1),a
    ld (flight_thrust_q8),a
    ld (flight_thrust_q8+1),a
    ld (flight_throttle),a
    ld a,flight_flag_on_ground
    ld (flight_flags),a
    or a
    ret


koak_pavement_path: db "APT/KOAK/P00.AGN",0
koak_marking_path: db "APT/KOAK/M00.AGN",0
family_path_buffer: db "RGN/00/00.AGN",0

streaming_coarse_x: db regional_start_tile_x
streaming_coarse_y: db regional_start_tile_y
streaming_origin_dirty: db 0
streaming_rebased_this_step: db 0
streaming_scene_dirty: db 0
streaming_airport_pair_loaded: db 0
streaming_last_error: db 0
family_plan_cursor: db 0
family_reposition_index: db 0
family_error_hold: db 0
family_swap_complete: db 0
family_swap_remaining: db 0
family_position_slot: db 0
family_entry_activate_latched: db 0
family_position_xyz: dl 0,0,0
