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

vdp_version: db "ScratchPingo 3D 2.10.0 Alpha 7",0
push_a_button: db "Press any key to continue.",0

; application includes
    include "input.inc"
    include "timer.inc"
    include "vdu_pingo.inc"
; end application includes

; control includes
    include "inputair.inc"
; end control includes

; model includes
    include "jet.inc"
    include "koak28lr.inc"
    ; include "cyl.inc"
; end model includes

main:
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
    ld bc,jet_texture_width
    ld de,jet_texture_height
    ld hl,jet_bmid
    ld ix,jet_texture_size
    ld iy,jet_texture
    ld a,1 ; rgba2222
    call vdu_load_img

    call app_special_images

; create render target bitmap rgba2222 format
ctb2:
    CTB2 tgtbmid, cstw, csth
; create control structure
ccs:
    CCS sid, cstw, csth

; create mesh vertices
svjet:
    SV sid, jet_mid, jet_vertices, jet_vertices_n
; create mesh vertex indices
smvijet:
    SMVI sid, jet_mid, jet_vertex_indices, jet_indices_n
; create texture coordinates
stcjet:
    STC sid, jet_oid, jet_uvs, jet_uvs_n
; create texture coordinate indices
stcijet:
    STCI sid, jet_oid, jet_uv_indices, jet_indices_n
; create object
cojet:
    CO sid, jet_oid, jet_mid, jet_bmid
; set object scale
sojet:
    SO sid, jet_oid, jet_obj_scale, jet_obj_scale, jet_obj_scale

; create mesh vertices
svkoak28lr:
    SV sid, koak28lr_mid, koak28lr_vertices, koak28lr_vertices_n
; create mesh vertex indices
smvikoak28lr:
    SMVI sid, koak28lr_mid, koak28lr_vertex_indices, koak28lr_indices_n
; ; create texture coordinates
; stckoak28lr:
;     STC sid, koak28lr_oid, koak28lr_uvs, koak28lr_uvs_n
; ; create texture coordinate indices
; stcikoak28lr:
;     STCI sid, koak28lr_oid, koak28lr_uv_indices, koak28lr_indices_n
; create object
cokoak28lr:
    CO sid, koak28lr_oid, koak28lr_mid, 0
; set object scale
sokoak28lr:
    SO sid, koak28lr_oid, koak28lr_obj_scale, koak28lr_obj_scale, koak28lr_obj_scale

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

; call app special init
    call app_special_init

; set initial object position
    ; call move_jet_object
    ld hl,jet_oid
    ld bc,(jet_objx)
    ld de,(jet_objy)
    ld iy,(jet_objz)
    call sodabs

; set initial object position
    ; call move_jet_object
    ld hl,koak28lr_oid
    ld bc,(koak28lr_objx)
    ld de,(koak28lr_objy)
    ld iy,(koak28lr_objz)
    call sodabs

; set initial camera position
    ; call move_camera
    ld bc,(camx)
    ld de,(camy)
    ld iy,(camz)
    call scdabs

; initialize main loop timer
main_loop_timer_reset: equ 12 ; 120ths of a second
    ld hl,main_loop_timer_reset
    call tmr_main_loop_set

; render inital scene
    jp rendbmp

mainloop:
    call reset_keys

waitloop:
    call set_keys
    call tmr_main_loop_get
    jp z, do_input
    jp m, do_input
    jp waitloop

rendbmp:
    call app_special_render

no_move:
    ld hl,main_loop_timer_reset
    call tmr_main_loop_set
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
