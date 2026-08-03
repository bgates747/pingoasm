; =============================================================================
; Stable Pingo terrain slots for the reusable-manager survey fixture.
;
; The fixture reserves the complete radius-five axial hex disk, but
; every slot starts inactive.  Runtime-patched packets keep mesh and object
; identifiers genuinely 16-bit; the setup loop must not silently become an
; eight-bit-ID implementation merely because this first pool begins at one.
; Command 50 can subsequently replace each placeholder mesh atomically.
; =============================================================================

    MACRO MANAGER_SCENE_STORE_U16_HL ADDRESS
        ld a,l
        ld (ADDRESS),a
        ld a,h
        ld (ADDRESS+1),a
    ENDMACRO

    MACRO MANAGER_SCENE_LOAD_U16_HL ADDRESS
        ld hl,0
        ld a,(ADDRESS)
        ld l,a
        ld a,(ADDRESS+1)
        ld h,a
    ENDMACRO

    MACRO MANAGER_SCENE_LOAD_U16_DE ADDRESS
        ld de,0
        ld a,(ADDRESS)
        ld e,a
        ld a,(ADDRESS+1)
        ld d,a
    ENDMACRO

manager_survey_establish_scene_slots:
    ld hl,manager_survey_mesh_base
    MANAGER_SCENE_STORE_U16_HL terrain_scene_next_mesh_id
    ld hl,manager_survey_object_base
    MANAGER_SCENE_STORE_U16_HL terrain_scene_next_object_id
    ld a,manager_survey_slot_count
    ld (terrain_scene_slots_remaining),a
@next:
    MANAGER_SCENE_LOAD_U16_HL terrain_scene_next_mesh_id
    call terrain_scene_define_placeholder_mesh

    MANAGER_SCENE_LOAD_U16_HL terrain_scene_next_mesh_id
    ld a,pingo_shading_flat_pattern
    call pingo_set_mesh_shading_mode
    MANAGER_SCENE_LOAD_U16_HL terrain_scene_next_mesh_id
    ld a,pingo_mesh_illumination_scene
    call pingo_set_mesh_illumination_mode

    MANAGER_SCENE_LOAD_U16_HL terrain_scene_next_object_id
    MANAGER_SCENE_LOAD_U16_DE terrain_scene_next_mesh_id
    ld bc,terrain_bmid
    call pingo_create_object_runtime
    MANAGER_SCENE_LOAD_U16_HL terrain_scene_next_object_id
    xor a
    call pingo_set_object_active

    call terrain_scene_advance_mesh_id
    call terrain_scene_advance_object_id
    ld hl,terrain_scene_slots_remaining
    dec (hl)
    jr nz,@next
    ret

terrain_scene_advance_mesh_id:
    ld hl,terrain_scene_next_mesh_id
    inc (hl)
    ret nz
    inc hl
    inc (hl)
    ret

terrain_scene_advance_object_id:
    ld hl,terrain_scene_next_object_id
    inc (hl)
    ret nz
    inc hl
    inc (hl)
    ret

; Input HL is one exact mesh ID.  Each definition command consumes a patched
; two-byte ID and then its fixed placeholder payload.
terrain_scene_define_placeholder_mesh:
    MANAGER_SCENE_STORE_U16_HL terrain_scene_definition_mesh_id
    call terrain_scene_define_vertices
    call terrain_scene_define_position_indices
    call terrain_scene_define_uvs
    jp terrain_scene_define_uv_indices

terrain_scene_patch_definition_id:
    MANAGER_SCENE_LOAD_U16_HL terrain_scene_definition_mesh_id
    ld a,l
    ld (terrain_scene_packet_mesh_id),a
    ld a,h
    ld (terrain_scene_packet_mesh_id+1),a
    ret

terrain_scene_define_vertices:
    call terrain_scene_patch_definition_id
    ld a,1
    ld (terrain_scene_packet_subcommand),a
    ld a,3
    ld (terrain_scene_packet_count),a
    xor a
    ld (terrain_scene_packet_count+1),a
    ld hl,terrain_scene_packet
    ld bc,terrain_scene_packet_end-terrain_scene_packet
    rst.lil 18h
    ld hl,terrain_scene_placeholder_vertices
    ld bc,terrain_scene_placeholder_vertices_end-terrain_scene_placeholder_vertices
    rst.lil 18h
    ret

terrain_scene_define_position_indices:
    call terrain_scene_patch_definition_id
    ld a,2
    ld (terrain_scene_packet_subcommand),a
    ld a,3
    ld (terrain_scene_packet_count),a
    xor a
    ld (terrain_scene_packet_count+1),a
    ld hl,terrain_scene_packet
    ld bc,terrain_scene_packet_end-terrain_scene_packet
    rst.lil 18h
    ld hl,terrain_scene_placeholder_indices
    ld bc,terrain_scene_placeholder_indices_end-terrain_scene_placeholder_indices
    rst.lil 18h
    ret

terrain_scene_define_uvs:
    call terrain_scene_patch_definition_id
    ld a,3
    ld (terrain_scene_packet_subcommand),a
    ld a,1
    ld (terrain_scene_packet_count),a
    xor a
    ld (terrain_scene_packet_count+1),a
    ld hl,terrain_scene_packet
    ld bc,terrain_scene_packet_end-terrain_scene_packet
    rst.lil 18h
    ld hl,terrain_scene_placeholder_uvs
    ld bc,terrain_scene_placeholder_uvs_end-terrain_scene_placeholder_uvs
    rst.lil 18h
    ret

terrain_scene_define_uv_indices:
    call terrain_scene_patch_definition_id
    ld a,4
    ld (terrain_scene_packet_subcommand),a
    ld a,3
    ld (terrain_scene_packet_count),a
    xor a
    ld (terrain_scene_packet_count+1),a
    ld hl,terrain_scene_packet
    ld bc,terrain_scene_packet_end-terrain_scene_packet
    rst.lil 18h
    ld hl,terrain_scene_placeholder_uv_indices
    ld bc,terrain_scene_placeholder_uv_indices_end-terrain_scene_placeholder_uv_indices
    rst.lil 18h
    ret

; Subcommands 1..4 share the same wire prefix.  The count is patched to three
; for vertices and index arrays, and one for the single placeholder UV.
terrain_scene_packet:
    db 23,0,0A0h
    dw sid
    db 049h
terrain_scene_packet_subcommand:
    db 0
terrain_scene_packet_mesh_id:
    dw 0
terrain_scene_packet_count:
    dw 3
terrain_scene_packet_end:

terrain_scene_placeholder_vertices:
    dw -1,0,-1
    dw 1,0,-1
    dw 0,0,1
terrain_scene_placeholder_vertices_end:
terrain_scene_placeholder_indices:
    dw 0,1,2
terrain_scene_placeholder_indices_end:
terrain_scene_placeholder_uvs:
    dw 0,0
terrain_scene_placeholder_uvs_end:
terrain_scene_placeholder_uv_indices:
    dw 0,0,0
terrain_scene_placeholder_uv_indices_end:

terrain_scene_definition_mesh_id: dw 0
terrain_scene_next_mesh_id: dw 0
terrain_scene_next_object_id: dw 0
terrain_scene_slots_remaining: db 0
