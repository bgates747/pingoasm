; Thirty-two stable terrain-only scene slots.  The 8x4 rolling window uses
; every active-renderable object and leaves backdrop painting outside Pingo.

    MACRO REGIONAL_ESTABLISH_TERRAIN_SLOT SLOT
        SV sid,SLOT,regional_placeholder_vertices,regional_placeholder_vertices_n
        SMVI sid,SLOT,regional_placeholder_indices,regional_placeholder_indices_n
        STC sid,SLOT,regional_placeholder_uvs,regional_placeholder_uvs_n
        STCI sid,SLOT,regional_placeholder_uv_indices,regional_placeholder_indices_n
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

regional_establish_scene_slots:
    REGIONAL_ESTABLISH_TERRAIN_SLOT 1
    REGIONAL_ESTABLISH_TERRAIN_SLOT 2
    REGIONAL_ESTABLISH_TERRAIN_SLOT 3
    REGIONAL_ESTABLISH_TERRAIN_SLOT 4
    REGIONAL_ESTABLISH_TERRAIN_SLOT 5
    REGIONAL_ESTABLISH_TERRAIN_SLOT 6
    REGIONAL_ESTABLISH_TERRAIN_SLOT 7
    REGIONAL_ESTABLISH_TERRAIN_SLOT 8
    REGIONAL_ESTABLISH_TERRAIN_SLOT 9
    REGIONAL_ESTABLISH_TERRAIN_SLOT 10
    REGIONAL_ESTABLISH_TERRAIN_SLOT 11
    REGIONAL_ESTABLISH_TERRAIN_SLOT 12
    REGIONAL_ESTABLISH_TERRAIN_SLOT 13
    REGIONAL_ESTABLISH_TERRAIN_SLOT 14
    REGIONAL_ESTABLISH_TERRAIN_SLOT 15
    REGIONAL_ESTABLISH_TERRAIN_SLOT 16
    REGIONAL_ESTABLISH_TERRAIN_SLOT 17
    REGIONAL_ESTABLISH_TERRAIN_SLOT 18
    REGIONAL_ESTABLISH_TERRAIN_SLOT 19
    REGIONAL_ESTABLISH_TERRAIN_SLOT 20
    REGIONAL_ESTABLISH_TERRAIN_SLOT 21
    REGIONAL_ESTABLISH_TERRAIN_SLOT 22
    REGIONAL_ESTABLISH_TERRAIN_SLOT 23
    REGIONAL_ESTABLISH_TERRAIN_SLOT 24
    REGIONAL_ESTABLISH_TERRAIN_SLOT 25
    REGIONAL_ESTABLISH_TERRAIN_SLOT 26
    REGIONAL_ESTABLISH_TERRAIN_SLOT 27
    REGIONAL_ESTABLISH_TERRAIN_SLOT 28
    REGIONAL_ESTABLISH_TERRAIN_SLOT 29
    REGIONAL_ESTABLISH_TERRAIN_SLOT 30
    REGIONAL_ESTABLISH_TERRAIN_SLOT 31
    REGIONAL_ESTABLISH_TERRAIN_SLOT 32
    ret

regional_placeholder_vertices_n: equ 3
regional_placeholder_indices_n: equ 3
regional_placeholder_uvs_n: equ 1
regional_placeholder_vertices:
    dw -1,0,-1
    dw 1,0,-1
    dw 0,0,1
regional_placeholder_indices:
    dw 0,1,2
regional_placeholder_uvs:
    dw 0,0
regional_placeholder_uv_indices:
    dw 0,0,0
