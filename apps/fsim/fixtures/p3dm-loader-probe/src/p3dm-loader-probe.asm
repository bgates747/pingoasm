; One-file AGNB 0.3/P3DM streaming publication probe.
;
; This fixture deliberately remains smaller than the accepted Berkeley scene:
; one stable mesh/object slot is established from embedded fallback geometry,
; then tile 0C is read, closed, validated, staged, atomically published, and
; activated.  No command 50 byte is emitted on a pre-publication failure.

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

; Reuse the qualified exact-u16 transport snapshot without copying or editing
; the visually accepted fixture.  P3DM-specific helpers are separate below.
    include "../../berkeley-flight-triangular-dither/src/vdu_pingo.inc"
    include "p3dm-loader.inc"

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

; Load and snapshot the flat-pattern library used by the streamed terrain.
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

; A 4x4 selector bitmap maps face UVs to authored terrain material IDs.
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

; Establish a stable, already-bound mesh slot.  The tiny fallback remains the
; complete resident mesh if file I/O, parsing, bounds, policy, CRC, or index
; validation fails.  It is intentionally inactive during the probe.
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

; Match the accepted Berkeley lighting and camera convention.
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

; The loader reads and closes one deterministic 8.3-safe path before parsing.
; Command 50 is reachable only after the complete validation chain succeeds.
    call initialize_p3dm_request
    call p3dm_load_component
    jp nz,@failed

; The fixture-specific coordinator cross-checks the retained component centre,
; then derives scale and translation from the validated descriptor result. It
; does not trust a compile-time terrain transform after publication.
    call apply_probe_descriptor_transform
    jp nz,@failed
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

; Initialize the reusable loader's caller-owned request block for this one
; Berkeley terrain component. A regional coordinator may replace all of these
; fields between synchronous calls without editing the loader include.
initialize_p3dm_request:
    ld hl,p3dm_filename_buffer
    ld (p3dm_filename_pointer),hl ; ADL24 OK: native 24-bit path pointer
    ld hl,probe_mesh_id
    ld a,l
    ld (p3dm_target_mesh_id),a
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
    ld (p3dm_expected_tile_x),a
    ld a,h
    ld (p3dm_expected_tile_x+1),a
    ld hl,probe_expected_tile_y
    ld a,l
    ld (p3dm_expected_tile_y),a
    ld a,h
    ld (p3dm_expected_tile_y+1),a
    ret

; This isolated scene's coarse reference centre is east=0, north=0 metres.
; For the selected tile, object X = north*16 and object Z = -east*16. The
; exact centre witnesses are fixture policy; a regional coordinator instead
; subtracts its current floating-origin coarse centre before this conversion.
apply_probe_descriptor_transform:
    ld hl,p3dm_center_east_m
    ld de,probe_expected_center_east_m
    call p3dm_compare_fourcc
    jp nz,@bad_result
    ld hl,p3dm_center_north_m
    ld de,probe_expected_center_north_m
    call p3dm_compare_fourcc
    jp nz,@bad_result

; Pingo scale is unsigned Q8.8. model_half_extent_m / 8 therefore becomes
; model_half_extent_m * 32 on the wire; the loader's <=2047 check prevents
; this five-bit shift from overflowing u16.
    P3DM_LD_U16_HL p3dm_model_half_extent_m
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl
    ld a,l
    ld (@scale_x+0),a
    ld (@scale_y+0),a
    ld (@scale_z+0),a
    ld a,h
    ld (@scale_x+1),a
    ld (@scale_y+1),a
    ld (@scale_z+1),a
    ld hl,@scale_command
    ld bc,@scale_command_end-@scale_command
    rst.lil 18h
    jp @scale_command_end
@scale_command:
    db 23,0,0A0h
    dw sid
    db 49h,9
    dw probe_object_id
@scale_x:
    dw 0
@scale_y:
    dw 0
@scale_z:
    dw 0
@scale_command_end:

    P3DM_LD_U16_HL p3dm_center_north_m
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl
    ld a,l
    ld (@translation_x+0),a
    ld a,h
    ld (@translation_x+1),a

    P3DM_LD_U16_HL p3dm_center_east_m
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl
    push hl
    pop de
    ld hl,0
    or a
    sbc hl,de
    ld a,l
    ld (@translation_z+0),a
    ld a,h
    ld (@translation_z+1),a
    ld hl,@translation_command
    ld bc,@translation_command_end-@translation_command
    rst.lil 18h
    jp @translation_command_end
@translation_command:
    db 23,0,0A0h
    dw sid
    db 49h,17
    dw probe_object_id
@translation_x:
    dw 0
@translation_y:
    dw 0
@translation_z:
    dw 0
@translation_command_end:
    xor a
    ret

@bad_result:
    ld a,p3dm_error_policy
    ld (p3dm_last_error),a
    or a
    ret

; A -> two uppercase hexadecimal characters.  This is a diagnostic only; the
; durable result also remains in p3dm_last_error.
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
    db "P3DM probe: read/close/validate/CRC/stage/atomic publish",13,10,0
success_text:
    db "P3DM OK: TRN/L0/00/0C.AGN -> stable mesh slot 1",13,10,0
failure_text:
    db "P3DM FAIL 0x",0

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

probe_expected_center_east_m:
    db 00h,01h,00h,00h       ; +256 m
probe_expected_center_north_m:
    db 00h,0FFh,0FFh,0FFh    ; -256 m

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

; MOS texture staging must be the final application address.  The legacy
; pattern helper loads known-size immutable files here; P3DM uses its own
; bounded reader-owned buffer and never depends on MOS LOAD.
filedata:
