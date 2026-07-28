; =============================================================================
; Standalone TurboVega-surface textured-heavy-tank regression fixture.
; Adapted from pingoasm apps/moveobj/src/cube.asm.
; =============================================================================

mos_load:			    EQU	01h
mos_sysvars:		    EQU	08h
mos_getkbmap:		    EQU	1Eh
sysvar_time:			EQU	00h
sysvar_keyascii:		EQU	05h

	MACRO	MOSCALL	function
			LD	A, function
			RST.LIL	08h
	ENDMACRO

    .assume adl=1
    .org 0x040000

    jp start

    .align 64
    .db "MOS"
    .db 00h
    .db 01h

start:
    push af
    push bc
    push de
    push ix
    push iy

    call main

exit:
    pop iy
    pop ix
    pop de
    pop bc
    pop af
    ld hl,0

    ret

vdp_version: db "Pingo TurboVega heavytank regression",0
push_a_button: db "Press any key to continue.",0

; application includes
    include "vdu_tv.inc"
    include "inputobj.inc"
; end application includes

; model includes
    include "heavytank.inc"
; end model includes

sid: equ 300
mid: equ 1
oid: equ 1
obj_scale: equ 5*256
objbmid: equ 256
tgtbmid: equ 257

cstw: equ 320
csth: equ 240
cstx: equ 0
csty: equ 0

camx: dl 0
camy: dl 0
camz: dl 25*128
camdx: dl 0
camdy: dl 0
camdz: dl 0
camrx: dl 0
camry: dl 0
camrz: dl 0
camdrx: dl 0
camdry: dl 0
camdrz: dl 0

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

objd: equ 32
objdr: equ 91*5
objz_limit: equ 10*128

main:
    call reset_object_state

; print version
    ld hl,vdp_version
    call printString
    call printNewLine

; ; TODO: fix this
; ; wait for keypress
;     ld hl,push_a_button
;     call printString
;     call waitKeypress

; load texture file to a buffer and make it a bitmap
    ld bc,model_texture_width
    ld de,model_texture_height
    ld hl,objbmid
    ld ix,model_texture_size
    ld iy,model_texture
    ld a,0 ; RGBA8888
    call vdu_load_img

; create render target bitmap RGBA8888 format
ctb:
    CTB tgtbmid, cstw, csth

; create control structure
ccs:
    CCS sid, cstw, csth

; create mesh vertices
sv:
    SV sid, mid, model_vertices, model_vertices_n

; create mesh vertex indices
smvi:
    SMVI sid, mid, model_vertex_indices, model_indices_n

; create texture coordinates
stc:
    STC sid, mid, model_uvs, model_uvs_n

; create texture coordinate indices
stci:
    STCI sid, mid, model_uv_indices, model_indices_n

; ; create normals
; sn:
;     SN sid, mid, model_normals, model_normals_n

; ; create normal indices
; smni:
;     SMNI sid, mid, model_normal_indices, model_indices_n

; create object
co:
    CO sid, oid, mid, objbmid

; set object scale
so:
    SO sid, oid, obj_scale, obj_scale, obj_scale

preloop:
    ld a,8+128 ; 320x240x64 double-buffered
    call vdu_set_screen_mode
    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    jp @end
@beg:
;   940 VDU 23, 0, &C0, 0: REM Normal coordinates
    db 23,0,$C0,0
;   960 VDU 17,20+128 : REM set text background color to lighter azure
    db 17,20+128
;   970 VDU 18, 0, 20+128 : REM set gfx background color to lighter azure
    db 18,0,20+128
@end:

    call vdu_clg
    call vdu_flip
    call vdu_clg
    call cursor_off

; set initial object position
    ld hl,oid
    ld bc,(objx)
    ld de,(objy)
    ld iy,(objz)
    call sodabs

; reset object rotation, including when re-running against a resident control
    ld hl,oid
    ld bc,(objrx)
    ld de,(objry)
    ld iy,(objrz)
    call sorabs

; set initial camera position
    ld bc,(camx)
    ld de,(camy)
    ld iy,(camz)
    call scdabs

    call render_frame
    jr main_loop

render_frame:
    RENDBMP sid, tgtbmid
    call vdu_clg
    DISPBMP tgtbmid, cstx, csty
    call vdu_flip
    ret

main_loop:
    call wait_frame_tick
    MOSCALL mos_getkbmap

; Escape exits.
    bit 0,(ix+14)
    jr nz,main_end

    call update_object_from_keys
    or a
    jr z,main_loop
    call render_frame
    jr main_loop

main_end:
; exit program gracefully
    xor a ; 640x480x16 single-buffered
    call vdu_set_screen_mode
    ld a,1 ; scaling on
    call vdu_set_scaling
    call cursor_on
    ret

wait_frame_tick:
    MOSCALL mos_sysvars
    ld hl,(ix+sysvar_time)
    ld (frame_time),hl
@wait:
    MOSCALL mos_sysvars
    ld hl,(ix+sysvar_time)
    ld de,(frame_time)
    or a
    sbc hl,de
    ld de,input_tick_interval
    or a
    sbc hl,de
    jr c,@wait
    ret

; MOS time advances at 120 Hz.  Ten input updates per second is responsive
; without hammering the serial link while a key is held.
input_tick_interval: equ 12
frame_time: dl 0

reset_object_state:
    ld hl,0
    ld (objx),hl
    ld (objy),hl
    ld (objz),hl
    ld (objrx),hl
    ld (objry),hl
    ld (objrz),hl
    ld (objdx),hl
    ld (objdy),hl
    ld (objdz),hl
    ld (objdrx),hl
    ld (objdry),hl
    ld (objdrz),hl
    ret

filedata: ; no need to allocate space here if this is the final address label of the application
