; ============ INPUTAIR.INC ============
throttle: dl 0x000000 ; unsigned 8-bit integer 255 = 100% throttle

; ============ KEYBOARD INPUT ============
do_input:
; reset control object movement and rotation deltas
    ld hl,0

    ld (objdx),hl
    ld (objdy),hl
    ld (objdz),hl

    ld (objdrx),hl
    ld (objdry),hl
    ld (objdrz),hl

; get user keyboard input
	; MOSCALL mos_getkbmap
    ld ix,keyboard_masks

; ------ QUIT ------
; 113 Escape
    bit 0,(ix+14)
	jp nz,main_end

; ------ RENDERING OPTIONS ------
; 99 Space cycle through dithering types
    bit 2,(ix+12)
    call nz,cycle_dithering

; ------ THROTTLE CONTROL ------
; 34 W increase throttle
    bit 1,(ix+4)
    jr z,@W
    ld hl,(throttle)
    inc hl
    ld a,h
    and h
    jp z,@notmax
    ld hl,255 ; throttle 100%
@notmax:
    ld (throttle),hl
@W: 

; 82 S decrease throttle
    bit 1,(ix+10)
    jr z,@S
    ld hl,(throttle)
    dec hl
    ld a,h
    and h
    jp z,@notmin
    ld hl,0 ; throttle 0%
@notmin:
    ld (throttle),hl
@S:

    ld de,(throttle)
    ld hl,0
    xor a ; clear carry
    sbc hl,de ; subtract throttle from 0
    ld (objdz),hl


; ------ ROTATE OBJECT ------
; rotate object pitch axis
; 58 Up pitch down
    bit 1,(ix+7)
    jr z,@Up
    ld hl,-objdr
    ld (objdrx),hl
    xor a
@Up:
; 42 Down pitch up
    bit 1,(ix+5)
    jr z,@Down
    ld hl,(objdrx)
    ld de,objdr
    add hl,de 
    ld (objdrx),hl
    xor a
@Down:

; rotate object roll axis
; 26 Left roll left
    bit 1,(ix+3)
    jr z,@Left
    ld hl,objdr*2 
    ld (objdrz),hl
    xor a
@Left:
; 122 Right roll right
    bit 1,(ix+15)
    jr z,@Right
    ld hl,(objdrz)
    ld de,-objdr*2 
    add hl,de 
    ld (objdrz),hl
    xor a
@Right:

; yaw controls
; 66 A yaw left
    bit 1,(ix+8)
    jr z,@A
    ld hl,objdr
    ld (objdry),hl
    xor a
@A:
; 51 D yaw right
    bit 2,(ix+6)
    jr z,@D
    ld hl,(objdry)
    ld de,-objdr
    add hl,de 
    ld (objdry),hl
@D:

    call rotate_object_loc
    call move_object_loc

    ld hl,oid
    call cto ; camera track object

    ; call printNewLine
    ; ld a,(dithering_type)
    ; ld hl,0
    ; ld l,a
    ; call printDec

    jp rendbmp


; ; controls not defined for now
; ; move object y axis
; ; 64 PgUp move up
;     bit 7,(ix+7)
;     jr z,@PgUp
;     ld hl,objd
;     ld (objdy),hl
;     xor a
; @PgUp:
; ; 79 PgDn move down
;     bit 6,(ix+9)
;     jr z,@PgDn
;     ld hl,(objdy)
;     ld de,-objd
;     add hl,de 
;     ld (objdy),hl
;     xor a
; @PgDn:


; ; controls not defined for now
; ; 17 Q 
;     bit 0,(ix+2)
;     jr z,@Q

;     xor a
; @Q:
; ; 35 E 
;     bit 2,(ix+4)
;     jr z,@E

;     xor a
; @E:

3dview_bmid: equ 258
3dview_width: equ 320
3dview_height: equ 148
3dview_size: equ 3dview_width*3dview_height
3dview_file: db "fs3d.rgba2",0
3dview_x: equ 0
3dview_y: equ 0

panel_bmid: equ 259
panel_width: equ 320
panel_height: equ 92
panel_size: equ panel_width*panel_height
panel_file: db "fspanel.rgba2",0
panel_x: equ 0
panel_y: equ 148

app_special_init:
; load 3d viewport image to a buffer and make it a bitmap
    ld bc,3dview_width
    ld de,3dview_height
    ld hl,3dview_bmid
    ld ix,3dview_size
    ld iy,3dview_file
    ld a,1 ; rgba2
    call vdu_load_img

; load instrument panel image to a buffer and make it a bitmap
    ld bc,panel_width
    ld de,panel_height
    ld hl,panel_bmid
    ld ix,panel_size
    ld iy,panel_file
    ld a,1 ; rgba2
    call vdu_load_img

; draw instrument panel in both image buffers
    ld hl,panel_bmid
    call vdu_buff_select
    call vdu_clg
    ld bc,panel_x
    ld de,panel_y
    call vdu_plot_bmp
    call vdu_flip
    call vdu_clg
    ld bc,panel_x
    ld de,panel_y
    call vdu_plot_bmp

; set graphics viewport to 3d view
    ld bc,3dview_x
    ld de,3dview_y
    ld ix,3dview_x+3dview_width-1
    ld iy,3dview_y+3dview_height-1
    call vdu_set_gfx_viewport
    ret

app_special_render:
    RENDBMP sid, tgtbmid
dispbmp:
    call vdu_clg ; clear screen
    ld hl,3dview_bmid
    call vdu_buff_select
    ld bc,3dview_x
    ld de,3dview_y
    call vdu_plot_bmp
    DISPBMP tgtbmid, cstx, csty ; plot render target bitmap
    call vdu_flip ; flip the screen buffer
    ret


sid: equ 100
mid: equ 1
oid: equ 1
obj_scale: equ 256
objbmid: equ 256
tgtbmid: equ 257

cstw: equ 320
csth: equ 148
cstx: equ 0
csty: equ 0

camd: equ 32*1 ; 32767/256 * bar
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

objd: equ 32*1 ; 32767/256 * bar
objx: dl 0*objd
objy: dl 0 ; -42 ; -1/3*objd
objz: dl -20*objd

objdx: dl 0x000000
objdy: dl 0x000000
objdz: dl 0x000000

dithering_type: db 0x00 ; 0=none, 1=bayer ordered matrix, 2=floyd-steinberg