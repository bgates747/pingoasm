; =============================================================================
; Stable nested-family mixed-LOD scene slots.
;
; Every slot begins as a real but inactive placeholder mesh. Command 50 can
; therefore replace complete geometry atomically without changing object IDs
; or texture bindings. A failed import leaves the prior resident mesh intact.
; =============================================================================

    MACRO ESTABLISH_TERRAIN_SLOT SLOT
        SV sid,SLOT,stream_placeholder_vertices,stream_placeholder_vertices_n
        SMVI sid,SLOT,stream_placeholder_indices,stream_placeholder_indices_n
        STC sid,SLOT,stream_placeholder_uvs,stream_placeholder_uvs_n
        STCI sid,SLOT,stream_placeholder_uv_indices,stream_placeholder_indices_n
        ld hl,SLOT
        ld a,pingo_shading_flat_pattern
        call pingo_set_mesh_shading_mode
        ld hl,SLOT
        ld a,pingo_mesh_illumination_scene
        call pingo_set_mesh_illumination_mode
        CO sid,SLOT,SLOT,terrain_bmid
        ld hl,SLOT
        xor a
        call pingo_set_object_active
    ENDMACRO

    MACRO ESTABLISH_AIRPORT_SLOT SLOT
        SV sid,SLOT,stream_placeholder_vertices,stream_placeholder_vertices_n
        SMVI sid,SLOT,stream_placeholder_indices,stream_placeholder_indices_n
        STC sid,SLOT,stream_placeholder_uvs,stream_placeholder_uvs_n
        STCI sid,SLOT,stream_placeholder_uv_indices,stream_placeholder_indices_n
        ld hl,SLOT
        ld a,pingo_shading_flat_palette
        call pingo_set_mesh_shading_mode
        ld hl,SLOT
        ld a,pingo_mesh_illumination_self
        call pingo_set_mesh_illumination_mode
        CO sid,SLOT,SLOT,airport_bmid
        ld hl,SLOT
        xor a
        call pingo_set_object_active
    ENDMACRO

streaming_establish_scene_slots:
    ESTABLISH_TERRAIN_SLOT 1
    ESTABLISH_TERRAIN_SLOT 2
    ESTABLISH_TERRAIN_SLOT 3
    ESTABLISH_TERRAIN_SLOT 4
    ESTABLISH_TERRAIN_SLOT 5
    ESTABLISH_TERRAIN_SLOT 6
    ESTABLISH_TERRAIN_SLOT 7
    ESTABLISH_TERRAIN_SLOT 8
    ESTABLISH_TERRAIN_SLOT 9
    ESTABLISH_TERRAIN_SLOT 10
    ESTABLISH_TERRAIN_SLOT 11
    ESTABLISH_TERRAIN_SLOT 12
    ESTABLISH_TERRAIN_SLOT 13
    ESTABLISH_TERRAIN_SLOT 14
    ESTABLISH_TERRAIN_SLOT 15
    ESTABLISH_TERRAIN_SLOT 16
    ESTABLISH_TERRAIN_SLOT 17
    ESTABLISH_TERRAIN_SLOT 18
    ESTABLISH_TERRAIN_SLOT 19
    ESTABLISH_TERRAIN_SLOT 20
    ESTABLISH_TERRAIN_SLOT 21
    ESTABLISH_TERRAIN_SLOT 22
    ESTABLISH_TERRAIN_SLOT 23
    ESTABLISH_TERRAIN_SLOT 24
    ESTABLISH_TERRAIN_SLOT 25
    ESTABLISH_TERRAIN_SLOT 26
    ESTABLISH_TERRAIN_SLOT 27
    ESTABLISH_TERRAIN_SLOT 28
    ESTABLISH_TERRAIN_SLOT 29
    ESTABLISH_TERRAIN_SLOT 30
    ESTABLISH_TERRAIN_SLOT 31
    ESTABLISH_TERRAIN_SLOT 32
    ESTABLISH_TERRAIN_SLOT 33
    ESTABLISH_TERRAIN_SLOT 34
    ESTABLISH_TERRAIN_SLOT 35
    ESTABLISH_TERRAIN_SLOT 36
    ESTABLISH_TERRAIN_SLOT 37

    ESTABLISH_AIRPORT_SLOT airport_pavement_mesh_id
    ESTABLISH_AIRPORT_SLOT airport_marking_mesh_id

; The aircraft mesh is static. p3d_object_sync16 creates its retained object
; once after the flight state has supplied the canonical KOAK pose and scale.
    SV sid,aircraft_mesh_id,aircraft_jet_vertices,aircraft_jet_vertices_n
    SMVI sid,aircraft_mesh_id,aircraft_jet_vertex_indices,aircraft_jet_indices_n
    STC sid,aircraft_mesh_id,aircraft_jet_uvs,aircraft_jet_uvs_n
    STCI sid,aircraft_mesh_id,aircraft_jet_uv_indices,aircraft_jet_indices_n
    ld hl,aircraft_mesh_id
    ld a,pingo_shading_flat_palette
    call pingo_set_mesh_shading_mode
    ld hl,aircraft_mesh_id
    ld a,pingo_mesh_illumination_scene
    call pingo_set_mesh_illumination_mode
    ret

stream_placeholder_vertices_n: equ 3
stream_placeholder_indices_n: equ 3
stream_placeholder_uvs_n: equ 1
stream_placeholder_vertices:
    dw -1,0,-1
    dw 1,0,-1
    dw 0,0,1
stream_placeholder_indices:
    dw 0,1,2
stream_placeholder_uvs:
    dw 0,0
stream_placeholder_uv_indices:
    dw 0,0,0

