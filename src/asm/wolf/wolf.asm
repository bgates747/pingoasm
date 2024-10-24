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

vdp_version: db "pingo3Dbrg2.9.2Alpha2",0
push_a_button: db "Press any key to continue.",0

    include "vdu_pingo.inc"

; control includes
    include "inputcam.inc"
    ; include "inputobj.inc"
; end control includes

; model includes
    include "wolf.inc"
; end model includes

sid: equ 100
mid: equ 1
oid: equ 1
scale_factor: equ 128
obj_scale: equ 256*scale_factor
objbmid: equ 256
tgtbmid: equ 257

cstw: equ 240 ; 256
csth: equ 160 ; 128
cstx: equ 40  ; 32
csty: equ 32  ; 20

camd: equ 4*scale_factor ; 32767/256 * bar
camx: dl  0*camd
camy: dl  0*camd
camz: dl  0*camd

camdx: dl 0x000000
camdy: dl 0x000000
camdz: dl 0x000000

camdr: equ 91*5 ; 32767/360*foo
camrx: dl 0x000000
camry: dl 0x000000
camrz: dl 0x000000

camdrx: dl 0x000000
camdry: dl 0x000000
camdrz: dl 0x000000

objdr: equ 91*5 ; 32767/360*foo
objdrx: dl 0
objdry: dl 0
objdrz: dl 0

objrx: dl 0
objry: dl 0
objrz: dl 0

objd: equ 4*scale_factor ; 32767/256 * foo
objx: dl 0*objd
objy: dl 0*objd
objz: dl -10*objd

objdx: dl 0x000000
objdy: dl 0x000000
objdz: dl 0x000000

filetype: equ 0 ; rgba8

dithering_type: db 0x00 ; 0=none, 1=bayer ordered matrix, 2=floyd-steinberg

main:
; print version
    ld hl,vdp_version
    call printString
    call printNewLine
    
; wait for keypress
    ld hl,push_a_button
    call printString
    call waitKeypress

; load image file to a buffer and make it a bitmap
    ld a,filetype
    ld bc,model_texture_width
    ld de,model_texture_height
    ld hl,objbmid
    ld ix,model_texture_size
    ld iy,model_texture
    call vdu_load_img
    
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
    STC sid, oid, model_uvs, model_uvs_n

; create texture coordinate indices
stci:
    STCI sid, oid, model_uv_indices, model_indices_n

; ; create normals
; sn:
;     SN sid, mid, model_normals, model_normals_n

; ; create normal indices
; smni:
;     SMNI sid, mid, model_normal_indices, model_indices_n

; create render target bitmap
ctb:
    CTB tgtbmid, cstw, csth

; create object
co:
    CO sid, oid, mid, objbmid

; set object scale
so:
    SO sid, oid, obj_scale, obj_scale, obj_scale

; set dithering type
    ld a,(dithering_type)
    ld hl,sid
    call vdu_set_dither

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


; set initial object position
    ; call move_object
    ld hl,oid
    ld bc,(objx)
    ld de,(objy)
    ld iy,(objz)
    call sodabs

; set initial camera position
    ; call move_camera
    ld bc,(camx)
    ld de,(camy)
    ld iy,(camz)
    call scdabs

; render inital scene
    call vdu_cls
    jp rendbmp

mainloop:
    call vdu_cls

    ld hl,0
    ld (objdx),hl
    ld (objdy),hl
    ld (objdz),hl

    ld (objdrx),hl
    ld (objdry),hl
    ld (objdrz),hl

    ld (camdx),hl
    ld (camdy),hl
    ld (camdz),hl

    ld (camdrx),hl
    ld (camdry),hl
    ld (camdrz),hl

    jp get_input

rendbmp:
    RENDBMP sid, tgtbmid

dispbmp:
    DISPBMP tgtbmid, cstx, csty

    ; call vdu_vblank
    call vdu_flip

no_move:

    jp mainloop

main_end:
; exit program gracefully
    xor a ; 640x480x16 single-buffered
    call vdu_set_screen_mode
    ld a,1 ; scaling on
    call vdu_set_scaling
    call cursor_on
    ret

filedata: ; no need to allocate space here if this is the final address label of the application
