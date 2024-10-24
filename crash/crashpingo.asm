mos_load:			    EQU	01h
mos_sysvars:		    EQU	08h
mos_getkbmap:		    EQU	1Eh
sysvar_time:			EQU	00h	; 4: Clock timer in centiseconds (incremented by 2 every VBLANK)
sysvar_keyascii:		EQU	05h	; 1: ASCII keycode, or 0 if no key is pressed

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
    ; ld hl,str_program_end
    ; call printString

    pop iy 
    pop ix
    pop de
    pop bc
    pop af
    ld hl,0

    ret 

    include "pingo.inc"
    include "input.inc"
    include "crashpingo.inc"

sid: equ 100
mid: equ 1
oid: equ 1
obj_scale: equ 256
objbmid: equ 256
tgtbmid: equ 257

cstw: equ 256
csth: equ 192
cstx: equ 32
csty: equ 40

camd: equ 32 ; 32768/1024
camx: dl 0*camd
camy: dl 0*camd
camz: dl -24*camd

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

filetype: equ 0 ; rgba8

dithering_type: db 0x00 ; 0=none, 1=bayer ordered matrix, 2=floyd-steinberg

main:
    ld a,8+128 ; 320x240x64 double-buffered
    call vdu_set_screen_mode

; load image file to a buffer and make it a bitmap
    ld a,filetype
    ld bc,model_texture_width
    ld de,model_texture_height
    ld hl,objbmid
    ld ix,model_texture_size
    ld iy,model_texture
    call vdu_load_img
    
ccs:
    CCS sid, cstw, csth

sv:
    SV sid, mid, model_vertices, model_vertices_n

smvi:
    SMVI sid, mid, model_vertex_indices, model_indices_n

stc:
    STC sid, mid, model_uvs, model_uvs_n

stci:
    STCI sid, mid, model_uv_indices, model_indices_n

ctb:
    CTB tgtbmid, cstw, csth

co:
    CO sid, oid, mid, objbmid

so:
    SO sid, oid, obj_scale, obj_scale, obj_scale

; set dithering type
    ld a,(dithering_type)
    ld hl,sid
    call vdu_set_dither

preloop:
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

mainloop:
    call vdu_cls

    ld hl,0
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
get_input_return:

    ; call rotate_object
    call rotate_camera
    call move_camera

    call printNewLine
    ld a,(dithering_type)
    ld hl,0
    ld l,a
    call printDec

rendbmp:
    RENDBMP sid, tgtbmid

dispbmp:
    DISPBMP tgtbmid, cstx, csty

    call vdu_vblank
    call vdu_flip

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