; =============================================================================
; KOAK regional terrain coordinator.
;
; Twenty-five stable terrain slots form a direct-mapped 5x5 ring. One missing
; component may be read, validated, and published between completed renders.
; Horizontal aircraft state uses a 512 m coarse cell plus signed 16.8 fine
; Pingo X/Z coordinates; Y remains absolute.
; =============================================================================

terrain_slot_count: equ 25
terrain_mesh_base: equ 1
terrain_object_base: equ 1
airport_pavement_mesh_id: equ 101
airport_marking_mesh_id: equ 102
airport_pavement_object_id: equ 101
airport_marking_object_id: equ 102

regional_start_tile_x: equ 94
regional_start_tile_y: equ 146
regional_proof_min_x: equ 89
regional_proof_max_x: equ 97
regional_proof_min_y: equ 142
regional_proof_max_y: equ 150
regional_tile_position_q8_high: equ 020h
regional_half_tile_q8_high: equ 010h
regional_negative_half_tile_q8_high: equ 0F0h
regional_terrain_y_count: equ 9728
regional_terrain_scale_q8_8: equ 24576
koak_group0_scale_q8_8: equ 53056

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
    ld (streaming_scan_cursor),a
    ld (streaming_last_error),a
    ld (streaming_scene_dirty),a
    ld (streaming_airport_pair_loaded),a
    inc a
    ld (streaming_origin_dirty),a
    ld hl,p3dm_filename_buffer
    ld (p3dm_filename_pointer),hl ; ADL24 OK: native 24-bit path pointer

    ld hl,streaming_slot_tile_x
    ld b,terrain_slot_count*2
    ld a,0FFh
@clear_tiles:
    ld (hl),a
    inc hl
    djnz @clear_tiles
    ld hl,streaming_slot_active
    ld b,terrain_slot_count
    xor a
@clear_active:
    ld (hl),a
    inc hl
    djnz @clear_active
    ret

; The current tile and paired KOAK hard surfaces are a first-frame barrier.
; Both airport meshes remain inactive unless both complete synchronous loads
; succeed. Return Z on success, NZ with p3dm/streaming_last_error retained.
streaming_load_startup:
    ld a,regional_start_tile_x
    ld (streaming_desired_x),a
    ld a,regional_start_tile_y
    ld (streaming_desired_y),a
    call streaming_compute_direct_slot
    call streaming_load_desired_terrain
    ret nz

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
    ld hl,p3dm_filename_buffer
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

; Perform at most one disk/publication operation. Resident entries are skipped
; in the canonical northwest-biased order generated with this fixture.
streaming_service_one:
    ld a,(streaming_origin_dirty)
    or a
    call nz,streaming_reposition_all
    ld a,terrain_slot_count
    ld (streaming_scan_remaining),a
@scan:
    ld a,(streaming_scan_cursor)
    ld e,a
    inc a
    cp terrain_slot_count
    jr c,@cursor_ready
    xor a
@cursor_ready:
    ld (streaming_scan_cursor),a

    ld hl,0
    ld l,e
    add hl,hl
    ld de,streaming_desired_offsets
    add hl,de
    push hl
    pop ix
    ld a,(streaming_coarse_x)
    ld c,(ix+0)
    add a,c
    ld (streaming_desired_x),a
    ld a,(streaming_coarse_y)
    ld c,(ix+1)
    add a,c
    ld (streaming_desired_y),a

; The generated proof is deliberately bounded. Missing outer-world terrain is
; represented by the sky/neutral-ground fallback rather than repeated I/O.
    ld a,(streaming_desired_x)
    cp regional_proof_min_x
    jr c,@next
    cp regional_proof_max_x+1
    jr nc,@next
    ld a,(streaming_desired_y)
    cp regional_proof_min_y
    jr c,@next
    cp regional_proof_max_y+1
    jr nc,@next

    call streaming_compute_direct_slot
    call streaming_slot_matches_desired
    jr z,@next
    call streaming_load_desired_terrain
    ret
@next:
    ld hl,streaming_scan_remaining
    dec (hl)
    jr nz,@scan
    xor a
    ret

; slot = (tile_y mod 5)*5 + tile_x mod 5. Regional coordinates fit in u8.
streaming_compute_direct_slot:
    ld a,(streaming_desired_x)
    call streaming_modulo_five
    ld (streaming_residue_x),a
    ld a,(streaming_desired_y)
    call streaming_modulo_five
    ld e,a
    ld d,5
    mlt de
    ld a,(streaming_residue_x)
    add a,e
    ld (streaming_desired_slot),a
    ret

streaming_modulo_five:
@loop:
    cp 5
    ret c
    sub 5
    jr @loop

streaming_slot_matches_desired:
    ld a,(streaming_desired_slot)
    ld hl,0
    ld l,a
    ld de,streaming_slot_tile_x
    add hl,de
    ld a,(streaming_desired_x)
    cp (hl)
    ret nz
    ld a,(streaming_desired_slot)
    ld hl,0
    ld l,a
    ld de,streaming_slot_tile_y
    add hl,de
    ld a,(streaming_desired_y)
    cp (hl)
    ret nz
    ld a,(streaming_desired_slot)
    ld hl,0
    ld l,a
    ld de,streaming_slot_active
    add hl,de
    ld a,(hl)
    cp 1
    ret

streaming_load_desired_terrain:
    call streaming_build_terrain_path
    ld a,(streaming_desired_slot)
    add a,terrain_mesh_base
    ld l,a
    ld h,0
    call streaming_store_target_mesh_hl
    xor a
    ld (p3dm_expected_layer),a
    ld (p3dm_expected_lod),a
    ld (p3dm_expected_illumination),a
    ld (p3dm_expected_material_set),a
    ld a,pingo_shading_flat_pattern
    ld (p3dm_expected_shading),a
    ld hl,0
    ld a,(streaming_desired_x)
    ld l,a
    STREAM_ST_U16_HL p3dm_expected_tile_x
    ld hl,0
    ld a,(streaming_desired_y)
    ld l,a
    STREAM_ST_U16_HL p3dm_expected_tile_y
    call p3dm_load_component
    jr nz,streaming_record_load_error

    ld a,(streaming_desired_slot)
    add a,terrain_object_base
    ld l,a
    ld h,0
    ld de,regional_terrain_scale_q8_8
    call pingo_set_object_uniform_scale
    call streaming_position_desired_terrain
    ld a,(streaming_desired_slot)
    add a,terrain_object_base
    ld l,a
    ld h,0
    ld a,1
    call pingo_set_object_active
    call streaming_commit_desired_slot
    ld a,1
    ld (streaming_scene_dirty),a
    xor a
    ret

streaming_record_load_error:
    ld (streaming_last_error),a
    or a
    ret

streaming_commit_desired_slot:
    ld a,(streaming_desired_slot)
    ld hl,0
    ld l,a
    ld de,streaming_slot_tile_x
    add hl,de
    ld a,(streaming_desired_x)
    ld (hl),a
    ld a,(streaming_desired_slot)
    ld hl,0
    ld l,a
    ld de,streaming_slot_tile_y
    add hl,de
    ld a,(streaming_desired_y)
    ld (hl),a
    ld a,(streaming_desired_slot)
    ld hl,0
    ld l,a
    ld de,streaming_slot_active
    add hl,de
    ld (hl),1
    ret

; Produce TRN/L0/HH/LL.AGN using tile_id = tile_y*201 + tile_x.
streaming_build_terrain_path:
    ld de,0
    ld a,(streaming_desired_y)
    ld e,a
    ld d,201
    mlt de
    ld hl,0
    ld a,(streaming_desired_x)
    ld l,a
    add hl,de
    ld a,h
    ld de,p3dm_filename_buffer+7
    call streaming_store_hex_byte
    ld a,l
    ld de,p3dm_filename_buffer+10
    call streaming_store_hex_byte
    ld hl,p3dm_filename_buffer
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

; Position the just-loaded desired terrain tile relative to the current coarse
; cell. Inputs are retained streaming_desired_{x,y,slot}.
streaming_position_desired_terrain:
    ld a,(streaming_desired_y)
    ld c,a
    ld a,(streaming_coarse_y)
    ld b,a
    ld a,c
    sub b
    call streaming_delta_to_count
    push hl
    pop bc
    ld a,(streaming_coarse_x)
    ld hl,streaming_desired_x
    sub (hl)                       ; BC still owns the completed X transform
    call streaming_delta_to_count
    push hl
    pop iy
    ld a,(streaming_desired_slot)
    add a,terrain_object_base
    ld l,a
    ld h,0
    ld de,regional_terrain_y_count
    jp sodabs

; Signed byte A (-3..3) -> signed word A*8192 in HL.
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

; Reissue every resident world transform after a horizontal coarse-cell shift.
streaming_reposition_all:
    xor a
    ld (streaming_origin_dirty),a
    ld (streaming_reposition_index),a
@next:
    ld a,(streaming_reposition_index)
    ld hl,0
    ld l,a
    ld de,streaming_slot_active
    add hl,de
    ld a,(hl)
    or a
    jr z,@advance

    ld a,(streaming_reposition_index)
    ld hl,0
    ld l,a
    ld de,streaming_slot_tile_x
    add hl,de
    ld a,(hl)
    ld (streaming_desired_x),a
    ld a,(streaming_reposition_index)
    ld hl,0
    ld l,a
    ld de,streaming_slot_tile_y
    add hl,de
    ld a,(hl)
    ld (streaming_desired_y),a
    ld a,(streaming_reposition_index)
    ld (streaming_desired_slot),a
    call streaming_resident_within_transform_window
    jr nz,@deactivate
    call streaming_position_desired_terrain
    jr @advance
@deactivate:
    ld a,(streaming_reposition_index)
    add a,terrain_object_base
    ld l,a
    ld h,0
    xor a
    call pingo_set_object_active
    ld a,(streaming_reposition_index)
    ld hl,0
    ld l,a
    ld de,streaming_slot_active
    add hl,de
    xor a
    ld (hl),a
@advance:
    ld a,(streaming_reposition_index)
    inc a
    ld (streaming_reposition_index),a
    cp terrain_slot_count
    jr c,@next
    call streaming_reposition_airport
    ld a,1
    ld (streaming_scene_dirty),a
    ret

; Z when both tile deltas remain in the signed +/-3-cell packet window.
streaming_resident_within_transform_window:
    ld a,(streaming_desired_x)
    ld c,a
    ld a,(streaming_coarse_x)
    sub c
    add a,3
    cp 7
    jr nc,@outside
    ld a,(streaming_desired_y)
    ld c,a
    ld a,(streaming_coarse_y)
    sub c
    add a,3
    cp 7
    jr nc,@outside
    xor a
    ret
@outside:
    ld a,1
    or a
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

; Generated order for velocity east<0, north>0: current, predicted northwest,
; then Chebyshev distance/forward bias/Manhattan/tile identity.
streaming_desired_offsets:
    db 0,0,  -1,1,  -1,0,  0,1,  -1,-1
    db 1,1,  0,-1,  1,0,  1,-1,  -2,2
    db -2,1,  -1,2,  -2,0,  0,2,  -2,-1
    db 1,2,  -2,-2,  2,2,  -1,-2,  2,1
    db 0,-2,  2,0,  1,-2,  2,-1,  2,-2

streaming_coarse_x: db regional_start_tile_x
streaming_coarse_y: db regional_start_tile_y
streaming_desired_x: db 0
streaming_desired_y: db 0
streaming_desired_slot: db 0
streaming_residue_x: db 0
streaming_scan_cursor: db 0
streaming_scan_remaining: db 0
streaming_reposition_index: db 0
streaming_origin_dirty: db 0
streaming_rebased_this_step: db 0
streaming_scene_dirty: db 0
streaming_airport_pair_loaded: db 0
streaming_last_error: db 0
streaming_slot_tile_x: ds terrain_slot_count
streaming_slot_tile_y: ds terrain_slot_count
streaming_slot_active: ds terrain_slot_count
