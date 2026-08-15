; Isolated visual probe for selected-record AGNB family loading.
;
; The on-disk family is deliberately larger than p3dm_file_buffer. The L0
; record for tile (4,1) appears after several siblings, so a successful frame
; proves that the loader sought over unmatched DATA and published one record.

mos_getkey: equ 00h
mos_load: equ 01h
mos_sysvars: equ 08h
sysvar_time: equ 00h
p3dm_mirror_z_on_load: equ 0
    MACRO MOSCALL function
        ld a,function
        rst.lil 08h
    ENDMACRO

    .assume adl=1
    .org 040000h
    jp start
    .align 64
    .db "MOS",0,1

start:
    push af
    push bc
    push de
    push ix
    push iy
    call main
    pop iy
    pop ix
    pop de
    pop bc
    pop af
    ld hl,0
    ret

    include "../../berkeley-flight-triangular-dither/src/vdu_pingo.inc"
    include "../../p3dm-loader-probe/src/p3dm-loader.inc"
    include "nested-agnb-loader.inc"

    MACRO OT SID, OID, X, Y, Z
        ld hl,@beg
        ld bc,@end-@beg
        rst.lil 18h
        jp @end
@beg:
        db 23,0,0A0h
        dw SID
        db 49h,17
        dw OID,X,Y,Z
@end:
    ENDMACRO

main:
    ld hl,title
    call printString

; Load the accepted terrain pattern library and selector texture.
    ld hl,pingo_flat_patterns_buffer_id
    ld ix,pingo_flat_patterns_bytes
    ld iy,terrain_patterns_file
    call vdu_load_buffer_from_file
    ld hl,pingo_flat_patterns_buffer_id
    call vdu_consolidate_buffer
    ld hl,pingo_flat_lookup_buffer_id
    ld ix,pingo_flat_lookup_bytes
    ld iy,terrain_pattern_lookup_file
    call vdu_load_buffer_from_file
    ld hl,pingo_flat_lookup_buffer_id
    call vdu_consolidate_buffer
    ld bc,4
    ld de,4
    ld hl,terrain_bmid
    ld ix,16
    ld iy,terrain_texture
    ld a,1
    call vdu_load_img
    CTB2 tgtbmid,viewport_width,viewport_height
    CCS sid,viewport_width,viewport_height
    call pingo_bind_flat_pattern_library

; Establish the stable target before disk I/O. A failed family selection leaves
; this complete fallback mesh inactive and emits no command 50.
    SV sid,probe_mesh_id,placeholder_vertices,placeholder_vertices_n
    SMVI sid,probe_mesh_id,placeholder_indices,placeholder_indices_n
    STC sid,probe_mesh_id,placeholder_uvs,placeholder_uvs_n
    STCI sid,probe_mesh_id,placeholder_uv_indices,placeholder_indices_n
    ld hl,probe_mesh_id
    ld a,pingo_shading_flat_pattern
    call pingo_set_mesh_shading_mode
    ld hl,probe_mesh_id
    ld a,pingo_mesh_illumination_scene
    call pingo_set_mesh_illumination_mode
    CO sid,probe_object_id,probe_mesh_id,terrain_bmid
    ld hl,probe_object_id
    xor a
    call pingo_set_object_active

    ld bc,0
    ld de,16384
    ld iy,-28377
    call pingo_set_light_direction
    ld a,95
    call pingo_set_ambient_light
    ld bc,0
    ld de,-1144
    ld iy,16384
    call scdabs
    ld bc,0
    ld de,0
    ld iy,0
    call scrabs
    ld a,8+128
    call vdu_set_screen_mode
    xor a
    call vdu_set_scaling
    call vdu_clg
    call cursor_off

    call initialize_agnb_request
    call agnb_load_selected_component
    jp nz,@failed

; The selected source tile uses a 768 m normalization witness and is centered
; at east +256 m, north -256 m relative to this probe's coarse origin.
    SO sid,probe_object_id,24576,24576,24576
    OT sid,probe_object_id,-4096,0,-4096
    ld hl,probe_object_id
    ld a,1
    call pingo_set_object_active
    RENDBMP sid,tgtbmid
    call vdu_clg
    DISPBMP tgtbmid,0,0
    call vdu_flip
    ld hl,success_text
    call printString
@wait:
    MOSCALL mos_getkey
    cp 27
    jr nz,@wait
    jr @exit

@failed:
    push af
    ld hl,failure_text
    call printString
    pop af
    call print_hex_byte
    call printNewLine
    MOSCALL mos_getkey

@exit:
    xor a
    call vdu_set_screen_mode
    ld a,1
    call vdu_set_scaling
    call cursor_on
    ret

initialize_agnb_request:
    ld hl,agnb_family_path
    ld (p3dm_filename_pointer),hl ; ADL24 OK: native 24-bit path pointer
    ld hl,probe_mesh_id
    ld a,l
    ld (p3dm_target_mesh_id+0),a
    ld a,h
    ld (p3dm_target_mesh_id+1),a
    xor a
    ld (p3dm_expected_layer),a
    ld (p3dm_expected_lod),a
    ld (p3dm_expected_illumination),a
    ld (p3dm_expected_material_set),a
    ld a,pingo_shading_flat_pattern
    ld (p3dm_expected_shading),a
    ld hl,probe_expected_tile_x
    ld a,l
    ld (p3dm_expected_tile_x+0),a
    ld a,h
    ld (p3dm_expected_tile_x+1),a
    ld hl,probe_expected_tile_y
    ld a,l
    ld (p3dm_expected_tile_y+0),a
    ld a,h
    ld (p3dm_expected_tile_y+1),a
    ret

print_hex_byte:
    push af
    rra
    rra
    rra
    rra
    and 0Fh
    call print_hex_nibble
    pop af
    and 0Fh
print_hex_nibble:
    add a,'0'
    cp '9'+1
    jr c,@emit
    add a,'A'-'9'-1
@emit:
    rst.lil 10h
    ret

title:
    db "Nested AGNB probe: seek-select one P3DM record",13,10,0
success_text:
    db "AGNB OK: record 6 from RGN/00/00.AGN",13,10,0
failure_text:
    db "AGNB FAIL 0x",0

sid: equ 1731
tgtbmid: equ 257
terrain_bmid: equ 256
viewport_width: equ 320
viewport_height: equ 240
p3dm_stage_buffer_id: equ 07400h
probe_mesh_id: equ 1
probe_object_id: equ 1
probe_expected_tile_x: equ 4
probe_expected_tile_y: equ 1

agnb_family_path: db "RGN/00/00.AGN",0
terrain_texture: db "terrain-material-ids.rgba2",0
terrain_patterns_file: db "terrain-patterns.rgba2",0
terrain_pattern_lookup_file: db "terrain-pattern-lookup.bin",0

placeholder_vertices_n: equ 3
placeholder_vertices:
    dw -32767,0,-32767
    dw 32767,0,-32767
    dw 0,0,32767
placeholder_indices_n: equ 3
placeholder_indices:
    dw 0,2,1
placeholder_uvs_n: equ 1
placeholder_uvs:
    dw 0,65535
placeholder_uv_indices:
    dw 0,0,0

filedata:
