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
    ; include "inputcam.inc"
    ; include "inputobj.inc"
    include "inputair.inc"; end control includes

; model includes
;    ; include "jet.inc"
;    ; include "airliner.inc"
;    ; include "crash.inc"
;    ; include "LaraCroft.inc"
;    ; include "cube.inc"
;    ; include "tri.inc"
;    ; include "heavytank.inc"
    include "wolf_map.inc"
    ; include "earthuv.inc"
; end model includes

; placeholder includes
    ; include "koak.inc"
    ; include "manhattan.inc"
    ; include "navball.inc"
    ; include "viking_mod.inc"
    ; include "ship.inc"
    ; include "checkerboard.inc"
    ; include "trirainbow.inc"
    ; include "cow.inc"
    ; include "middle_harbor_drone.inc"
    ; include "equirectangular.inc"
    ; include "runway_numbers.inc"
    ; include "t38.inc"
; end placeholder includes

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
    ld bc,model_texture_width
    ld de,model_texture_height
    ld hl,objbmid
    ld ix,model_texture_size
    ld iy,model_texture
    call vdu_load_img_rgba2_to_8
    
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

; call app special init
    call app_special_init

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
