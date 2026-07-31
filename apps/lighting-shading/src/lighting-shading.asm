; Pingo scene-lighting and mesh-local shading visual qualification fixture.

mos_load: equ 01h
mos_sysvars: equ 08h
mos_getkbmap: equ 1Eh
sysvar_time: equ 00h
sysvar_keyascii: equ 05h

    MACRO MOSCALL function
        ld a,function
        rst.lil 08h
    ENDMACRO

    .assume adl=1
    .org 0x040000
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

    include "vdu_pingo.inc"
    include "textured-cube.inc"
    include "flat-cube.inc"

sid: equ 1400
textured_mid: equ 1
flat_mid: equ 2
textured_oid: equ 1
flat_oid: equ 2
; Compatibility alias used only by unused legacy routines in vdu_pingo.inc.
oid: equ textured_oid
textured_bmid: equ 1248
flat_bmid: equ 1249
panel_default_bmid: equ 1250
panel_side_bmid: equ 1251
panel_overdrive_bmid: equ 1252
panel_native_bmid: equ 1253

panel_width: equ 160
panel_height: equ 120
cube_scale: equ 640
cube_left_x: equ -480
cube_right_x: equ 480
camera_z: equ 3200
cube_rotation_x: equ 2500
cube_rotation_y: equ 4000

main:
    call load_textures
    call create_scene

    ld a,8+128
    call vdu_set_screen_mode
    xor a
    call vdu_set_scaling
    call cursor_off
    call vdu_clg
    call vdu_flip
    call vdu_clg

    ; Panel 1: untouched firmware lighting defaults.
    RENDBMP sid,panel_default_bmid

    ; Panel 2: unit-intensity light arriving from +X.
    ld bc,32767
    ld de,0
    ld iy,0
    call pingo_set_light_direction
    ld a,pingo_light_unity
    call pingo_set_light_intensity
    xor a
    call pingo_set_ambient_light
    RENDBMP sid,panel_side_bmid

    ; Panel 3: restore the default direction, then overdrive it with ambient.
    ld bc,0
    ld de,32767
    ld iy,-32767
    call pingo_set_light_direction
    ld a,255
    call pingo_set_light_intensity
    ld a,64
    call pingo_set_ambient_light
    RENDBMP sid,panel_overdrive_bmid

    ; Panel 4: stored light state remains, but native texture colors bypass it.
    ld a,pingo_illumination_off
    call pingo_set_illumination_enabled
    RENDBMP sid,panel_native_bmid

    ; Restore defaults before leaving the fixture resident in VDP memory.
    ld a,pingo_illumination_on
    call pingo_set_illumination_enabled
    ld a,pingo_light_unity
    call pingo_set_light_intensity
    xor a
    call pingo_set_ambient_light

    call vdu_clg
    DISPBMP panel_default_bmid,0,0
    DISPBMP panel_side_bmid,160,0
    DISPBMP panel_overdrive_bmid,0,120
    DISPBMP panel_native_bmid,160,120
    call vdu_flip
    call waitKeypress

    xor a
    call vdu_set_screen_mode
    ld a,1
    call vdu_set_scaling
    call cursor_on
    ret

load_textures:
    ld bc,textured_cube_texture_width
    ld de,textured_cube_texture_height
    ld hl,textured_bmid
    ld ix,textured_cube_texture_size
    ld iy,textured_cube_texture
    ld a,1
    call vdu_load_img

    ld bc,flat_cube_texture_width
    ld de,flat_cube_texture_height
    ld hl,flat_bmid
    ld ix,flat_cube_texture_size
    ld iy,flat_cube_texture
    ld a,1
    jp vdu_load_img

create_scene:
    CTB2 panel_default_bmid,panel_width,panel_height
    CTB2 panel_side_bmid,panel_width,panel_height
    CTB2 panel_overdrive_bmid,panel_width,panel_height
    CTB2 panel_native_bmid,panel_width,panel_height
    CCS sid,panel_width,panel_height

    SV sid,textured_mid,textured_cube_vertices,textured_cube_vertices_n
    SMVI sid,textured_mid,textured_cube_vertex_indices,textured_cube_indices_n
    STC sid,textured_mid,textured_cube_uvs,textured_cube_uvs_n
    STCI sid,textured_mid,textured_cube_uv_indices,textured_cube_indices_n
    CO sid,textured_oid,textured_mid,textured_bmid
    SO sid,textured_oid,cube_scale,cube_scale,cube_scale
    ld hl,textured_mid
    ld a,pingo_shading_textured
    call pingo_set_mesh_shading_mode

    SV sid,flat_mid,flat_cube_vertices,flat_cube_vertices_n
    SMVI sid,flat_mid,flat_cube_vertex_indices,flat_cube_indices_n
    STC sid,flat_mid,flat_cube_uvs,flat_cube_uvs_n
    STCI sid,flat_mid,flat_cube_uv_indices,flat_cube_indices_n
    CO sid,flat_oid,flat_mid,flat_bmid
    SO sid,flat_oid,cube_scale,cube_scale,cube_scale
    ld hl,flat_mid
    ld a,pingo_shading_flat_palette
    call pingo_set_mesh_shading_mode

    ld hl,textured_oid
    ld bc,cube_left_x
    ld de,0
    ld iy,0
    call sodabs
    ld hl,flat_oid
    ld bc,cube_right_x
    ld de,0
    ld iy,0
    call sodabs

    ld hl,textured_oid
    ld bc,cube_rotation_x
    ld de,cube_rotation_y
    ld iy,0
    call sorabs
    ld hl,flat_oid
    ld bc,cube_rotation_x
    ld de,cube_rotation_y
    ld iy,0
    call sorabs

    ; Canonical camera pose: +Z position, looking down -Z at the scene.
    ld bc,0
    ld de,0
    ld iy,camera_z
    jp scdabs

; The monolithic historical helper retains unused interactive-motion routines.
; They refer to these application-owned values even though this fixture never
; calls them. Keep the compatibility storage local until that helper is split.
dithering_type: db 0
objx: dl 0
objy: dl 0
objz: dl 0
objdx: dl 0
objdy: dl 0
objdz: dl 0
objrx: dl 0
objry: dl 0
objrz: dl 0
objdrx: dl 0
objdry: dl 0
objdrz: dl 0
camx: dl 0
camy: dl 0
camz: dl 0
camdx: dl 0
camdy: dl 0
camdz: dl 0
camrx: dl 0
camry: dl 0
camrz: dl 0
camdrx: dl 0
camdry: dl 0
camdrz: dl 0

filedata:
    ; MOS loads each texture into free RAM beginning at this final label.
