; =============================================================================
; Arbitrary-position loose-L0 terrain streaming for the regional camera.
;
; One 8x4 rectangle occupies all 32 stable Pingo object slots.  Any eight
; consecutive X cells and four consecutive Y cells have unique residues, so
; slot = (tile_y & 3)*8 + (tile_x & 7) is collision-free for the whole window.
; The rectangle retains fixture 3's useful start footprint: two cells west,
; five east, two south, and one north of the camera's coarse cell.
; =============================================================================

terrain_slot_count: equ 32
terrain_mesh_base: equ 1
terrain_object_base: equ 1
regional_grid_columns: equ 201
regional_grid_rows: equ 252
regional_grid_max_x: equ regional_grid_columns-1
regional_grid_max_y: equ regional_grid_rows-1
regional_terrain_y_count: equ 9728
regional_terrain_scale_q8_8: equ 24576
regional_cell_counts: equ 8192
regional_half_cell_counts: equ 4096
regional_z_low: equ regional_frame_z_bias-regional_half_cell_counts
regional_z_high: equ regional_frame_z_bias+regional_half_cell_counts
regional_negative_half_high: equ 0f0h

    MACRO REGIONAL_STORE_U16_HL ADDRESS
        ld a,l
        ld (ADDRESS),a
        ld a,h
        ld (ADDRESS+1),a
    ENDMACRO

regional_streaming_initialize:
    ld a,regional_start_tile_x
    ld (regional_coarse_x),a
    ld a,regional_start_tile_y
    ld (regional_coarse_y),a
    xor a
    ld (regional_scan_cursor),a
    ld (regional_last_error),a
    ld (regional_origin_dirty),a
    ld (regional_rebased_this_step),a
    ld hl,p3dm_filename_buffer
    ld (p3dm_filename_pointer),hl ; ADL24 OK: native 24-bit path pointer

    ld hl,regional_slot_tile_x
    ld b,terrain_slot_count*2
    ld a,0ffh
@clear_tiles:
    ld (hl),a
    inc hl
    djnz @clear_tiles
    ld hl,regional_slot_active
    ld b,terrain_slot_count
    xor a
@clear_active:
    ld (hl),a
    inc hl
    djnz @clear_active
    ret

; Current cell is the first-frame disk/publication barrier.  The other 31
; cells arrive one at a time after ordinary render completions.
regional_streaming_load_startup:
    ld a,(regional_coarse_x)
    ld (regional_desired_x),a
    ld a,(regional_coarse_y)
    ld (regional_desired_y),a
    call regional_compute_direct_slot
    jp regional_load_desired_terrain

; Reposition after a floating-origin change, then publish at most one missing
; component.  Failed reads retain the old complete mesh and will be retried
; when the scan returns to that desired cell.
regional_streaming_service_one:
    ld a,(regional_origin_dirty)
    or a
    call nz,regional_reposition_all
    ld a,terrain_slot_count
    ld (regional_scan_remaining),a
@scan:
    ld a,(regional_scan_cursor)
    ld e,a
    inc a
    cp terrain_slot_count
    jr c,@cursor_ready
    xor a
@cursor_ready:
    ld (regional_scan_cursor),a

    ld hl,0
    ld l,e
    add hl,hl
    ld de,regional_desired_offsets
    add hl,de
    push hl
    pop ix
    ld a,(regional_coarse_x)
    ld c,(ix+0)
    add a,c
    ld (regional_desired_x),a
    cp regional_grid_columns
    jr nc,@next
    ld a,(regional_coarse_y)
    ld c,(ix+1)
    add a,c
    ld (regional_desired_y),a
    cp regional_grid_rows
    jr nc,@next

    call regional_compute_direct_slot
    call regional_slot_matches_desired
    jr z,@next
    jp regional_load_desired_terrain
@next:
    ld hl,regional_scan_remaining
    dec (hl)
    jr nz,@scan
    xor a
    ret

; Collision-free for an exact eight-by-four consecutive-cell rectangle.
regional_compute_direct_slot:
    ld a,(regional_desired_x)
    and 7
    ld c,a
    ld a,(regional_desired_y)
    and 3
    add a,a
    add a,a
    add a,a
    add a,c
    ld (regional_desired_slot),a
    ret

regional_slot_matches_desired:
    ld a,(regional_desired_slot)
    ld hl,0
    ld l,a
    ld de,regional_slot_tile_x
    add hl,de
    ld a,(regional_desired_x)
    cp (hl)
    ret nz
    ld a,(regional_desired_slot)
    ld hl,0
    ld l,a
    ld de,regional_slot_tile_y
    add hl,de
    ld a,(regional_desired_y)
    cp (hl)
    ret nz
    ld a,(regional_desired_slot)
    ld hl,0
    ld l,a
    ld de,regional_slot_active
    add hl,de
    ld a,(hl)
    cp 1
    ret

regional_load_desired_terrain:
    call regional_build_terrain_path
    ld a,(regional_desired_slot)
    add a,terrain_mesh_base
    ld l,a
    ld h,0
    REGIONAL_STORE_U16_HL p3dm_target_mesh_id
    xor a
    ld (p3dm_expected_layer),a
    ld (p3dm_expected_lod),a
    ld (p3dm_expected_illumination),a
    ld (p3dm_expected_material_set),a
    ld a,pingo_shading_flat_pattern
    ld (p3dm_expected_shading),a
    ld hl,0
    ld a,(regional_desired_x)
    ld l,a
    REGIONAL_STORE_U16_HL p3dm_expected_tile_x
    ld hl,0
    ld a,(regional_desired_y)
    ld l,a
    REGIONAL_STORE_U16_HL p3dm_expected_tile_y
    call p3dm_load_component
    jr nz,regional_record_load_error

    ld a,(regional_desired_slot)
    add a,terrain_object_base
    ld l,a
    ld h,0
    ld de,regional_terrain_scale_q8_8
    call pingo_set_object_uniform_scale
    call regional_position_desired_terrain
    ld a,(regional_desired_slot)
    add a,terrain_object_base
    ld l,a
    ld h,0
    ld a,1
    call pingo_set_object_active
    call regional_commit_desired_slot
    xor a
    ret

regional_record_load_error:
    ld (regional_last_error),a
    or a
    ret

regional_commit_desired_slot:
    ld a,(regional_desired_slot)
    ld hl,0
    ld l,a
    ld de,regional_slot_tile_x
    add hl,de
    ld a,(regional_desired_x)
    ld (hl),a
    ld a,(regional_desired_slot)
    ld hl,0
    ld l,a
    ld de,regional_slot_tile_y
    add hl,de
    ld a,(regional_desired_y)
    ld (hl),a
    ld a,(regional_desired_slot)
    ld hl,0
    ld l,a
    ld de,regional_slot_active
    add hl,de
    ld (hl),1
    ret

; Produce TRN/L0/HH/LL.AGN for tile_id = tile_y*201 + tile_x.
regional_build_terrain_path:
    ld de,0
    ld a,(regional_desired_y)
    ld e,a
    ld d,regional_grid_columns
    mlt de
    ld hl,0
    ld a,(regional_desired_x)
    ld l,a
    add hl,de
    ld a,h
    ld de,p3dm_filename_buffer+7
    call regional_store_hex_byte
    ld a,l
    ld de,p3dm_filename_buffer+10
    call regional_store_hex_byte
    ld hl,p3dm_filename_buffer
    ld (p3dm_filename_pointer),hl ; ADL24 OK: native 24-bit path pointer
    ret

regional_store_hex_byte:
    push af
    rra
    rra
    rra
    rra
    and 00fh
    call regional_hex_nibble
    ld (de),a
    inc de
    pop af
    and 00fh
    call regional_hex_nibble
    ld (de),a
    ret

regional_hex_nibble:
    add a,'0'
    cp '9'+1
    ret c
    add a,'A'-'9'-1
    ret

; Translate one resident tile relative to the floating camera cell.  A shared
; +12288 Z frame bias keeps the asymmetric -2..+5 east/west rectangle inside
; legacy signed-word object transforms while preserving exact relative pose.
regional_position_desired_terrain:
    ld a,(regional_desired_y)
    ld c,a
    ld a,(regional_coarse_y)
    ld b,a
    ld a,c
    sub b
    call regional_delta_to_count
    push hl
    pop bc

    ld a,(regional_coarse_x)
    ld hl,regional_desired_x
    sub (hl)                       ; BC still owns the completed X transform
    call regional_delta_to_count
    ld de,regional_frame_z_bias
    add.s hl,de
    push hl
    pop iy

    ld a,(regional_desired_slot)
    add a,terrain_object_base
    ld l,a
    ld h,0
    ld de,regional_terrain_y_count
    jp sodabs

; Signed byte A -> signed word A*8192.  Runtime callers constrain A to the
; small rolling-window deltas before invoking this helper.
regional_delta_to_count:
    ld l,a
    ld h,0
    bit 7,l
    jr z,@extended
    ld h,0ffh
@extended:
    ld a,13
@shift:
    add.s hl,hl
    dec a
    jr nz,@shift
    ret

; Reissue all resident transforms after a coarse-cell shift.  A prior-window
; tile outside the new exact rectangle is deactivated so it cannot linger at
; an accidentally representable but no-longer-desired position.
regional_reposition_all:
    xor a
    ld (regional_origin_dirty),a
    ld (regional_reposition_index),a
@next:
    ld a,(regional_reposition_index)
    ld hl,0
    ld l,a
    ld de,regional_slot_active
    add hl,de
    ld a,(hl)
    or a
    jr z,@advance

    ld a,(regional_reposition_index)
    ld hl,0
    ld l,a
    ld de,regional_slot_tile_x
    add hl,de
    ld a,(hl)
    ld (regional_desired_x),a
    ld a,(regional_reposition_index)
    ld hl,0
    ld l,a
    ld de,regional_slot_tile_y
    add hl,de
    ld a,(hl)
    ld (regional_desired_y),a
    ld a,(regional_reposition_index)
    ld (regional_desired_slot),a
    call regional_resident_in_window
    jr nz,@deactivate
    call regional_position_desired_terrain
    jr @advance
@deactivate:
    ld a,(regional_reposition_index)
    add a,terrain_object_base
    ld l,a
    ld h,0
    xor a
    call pingo_set_object_active
    ld a,(regional_reposition_index)
    ld hl,0
    ld l,a
    ld de,regional_slot_active
    add hl,de
    xor a
    ld (hl),a
@advance:
    ld a,(regional_reposition_index)
    inc a
    ld (regional_reposition_index),a
    cp terrain_slot_count
    jr c,@next
    ret

; Z when desired-coarse is X [-2,+5] and Y [-2,+1].
regional_resident_in_window:
    ld a,(regional_desired_x)
    ld c,a
    ld a,(regional_coarse_x)
    ld b,a
    ld a,c
    sub b
    add a,2
    cp 8
    jr nc,@outside
    ld a,(regional_desired_y)
    ld c,a
    ld a,(regional_coarse_y)
    ld b,a
    ld a,c
    sub b
    add a,2
    cp 4
    jr nc,@outside
    xor a
    ret
@outside:
    ld a,1
    or a
    ret

; Keep camera X canonical in [-4096,+4096) and biased local Z in
; [8192,16384).  Coarse Y follows north/south X; coarse X runs opposite Pingo
; Z because positive Z is west.  At the corpus edge, clamp locally rather than
; permitting an unsigned coarse-cell wrap.
regional_streaming_rebase_camera:
    xor a
    ld (regional_rebased_this_step),a

    SURVEY_LOAD_HL camera_state+p3d_camera_world_position+p3d_vec3_x
    bit 7,h
    jr nz,@x_negative
    ld a,h
    cp regional_half_cell_counts >> 8
    jr c,@z
    ld a,(regional_coarse_y)
    cp regional_grid_max_y
    jr nc,@x_high_edge
    ld de,-regional_cell_counts
    add.s hl,de
    SURVEY_STORE_HL camera_state+p3d_camera_world_position+p3d_vec3_x
    ld hl,regional_coarse_y
    inc (hl)
    jr @mark_x
@x_high_edge:
    ld hl,regional_half_cell_counts-1
    SURVEY_STORE_HL camera_state+p3d_camera_world_position+p3d_vec3_x
    jr @z
@x_negative:
    ld a,h
    cp regional_negative_half_high
    jr nc,@z
    ld a,(regional_coarse_y)
    or a
    jr z,@x_low_edge
    ld de,regional_cell_counts
    add.s hl,de
    SURVEY_STORE_HL camera_state+p3d_camera_world_position+p3d_vec3_x
    ld hl,regional_coarse_y
    dec (hl)
    jr @mark_x
@x_low_edge:
    ld hl,-regional_half_cell_counts
    SURVEY_STORE_HL camera_state+p3d_camera_world_position+p3d_vec3_x
    jr @z
@mark_x:
    ld a,1
    ld (regional_rebased_this_step),a

@z:
    SURVEY_LOAD_HL camera_state+p3d_camera_world_position+p3d_vec3_z
    bit 7,h
    jr nz,@z_low
    ld a,h
    cp regional_z_high >> 8
    jr nc,@z_high
    cp regional_z_low >> 8
    jr c,@z_low
    jr @done_axes
@z_high:
    ld a,(regional_coarse_x)
    or a
    jr z,@z_high_edge
    ld de,-regional_cell_counts
    add.s hl,de
    SURVEY_STORE_HL camera_state+p3d_camera_world_position+p3d_vec3_z
    ld hl,regional_coarse_x
    dec (hl)
    jr @mark_z
@z_high_edge:
    ld hl,regional_z_high-1
    SURVEY_STORE_HL camera_state+p3d_camera_world_position+p3d_vec3_z
    jr @done_axes
@z_low:
    ld a,(regional_coarse_x)
    cp regional_grid_max_x
    jr nc,@z_low_edge
    ld de,regional_cell_counts
    add.s hl,de
    SURVEY_STORE_HL camera_state+p3d_camera_world_position+p3d_vec3_z
    ld hl,regional_coarse_x
    inc (hl)
    jr @mark_z
@z_low_edge:
    ld hl,regional_z_low
    SURVEY_STORE_HL camera_state+p3d_camera_world_position+p3d_vec3_z
    jr @done_axes
@mark_z:
    ld a,1
    ld (regional_rebased_this_step),a

@done_axes:
    ld a,(regional_rebased_this_step)
    or a
    ret z
    ld (regional_origin_dirty),a
    ld ix,camera_state
    ld a,(ix+p3d_camera_dirty)
    or p3d_camera_dirty_position
    ld (ix+p3d_camera_dirty),a
    ret

; Current and eastward cells arrive first for the initial due-east view.  The
; complete table is the Cartesian product X [-2,+5], Y [-2,+1].
regional_desired_offsets:
    db 0,0,  1,0,  2,0,  3,0,  4,0,  5,0,  -1,0,  -2,0
    db 0,1,  1,1,  2,1,  3,1,  4,1,  5,1,  -1,1,  -2,1
    db 0,-1, 1,-1, 2,-1, 3,-1, 4,-1, 5,-1, -1,-1, -2,-1
    db 0,-2, 1,-2, 2,-2, 3,-2, 4,-2, 5,-2, -1,-2, -2,-2

regional_coarse_x: db regional_start_tile_x
regional_coarse_y: db regional_start_tile_y
regional_desired_x: db 0
regional_desired_y: db 0
regional_desired_slot: db 0
regional_scan_cursor: db 0
regional_scan_remaining: db 0
regional_reposition_index: db 0
regional_origin_dirty: db 0
regional_rebased_this_step: db 0
regional_last_error: db 0
regional_slot_tile_x: ds terrain_slot_count
regional_slot_tile_y: ds terrain_slot_count
regional_slot_active: ds terrain_slot_count
