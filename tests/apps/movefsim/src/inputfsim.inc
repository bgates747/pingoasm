; ============ INPUTFSIM.INC ============
throttle: dl 0x000000 ; unsigned 8-bit integer 255 = 100% throttle

; ============ KEYBOARD INPUT ============
do_input:
; reset control camera movement and rotation deltas
    ld hl,0

    ld (camdx),hl
    ld (camdy),hl
    ld (camdz),hl

    ld (camdrx),hl
    ld (camdry),hl
    ld (camdrz),hl

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

    ld hl,(throttle)
    add hl,hl
    ld (camdz),hl


; ------ ROTATE camera ------
; rotate camera pitch axis
; 58 Up pitch down
    bit 1,(ix+7)
    jr z,@Up
    ld hl,camdr
    ld (camdrx),hl
    xor a
@Up:
; 42 Down pitch up
    bit 1,(ix+5)
    jr z,@Down
    ld hl,(camdrx)
    ld de,-camdr
    add hl,de 
    ld (camdrx),hl
    xor a
@Down:

; rotate camera roll axis
; 26 Left roll left
    bit 1,(ix+3)
    jr z,@Left
    ld hl,-camdr*2 
    ld (camdrz),hl
    xor a
@Left:
; 122 Right roll right
    bit 1,(ix+15)
    jr z,@Right
    ld hl,(camdrz)
    ld de,camdr*2 
    add hl,de 
    ld (camdrz),hl
    xor a
@Right:

; yaw controls
; 66 A yaw left
    bit 1,(ix+8)
    jr z,@A
    ld hl,-camdr
    ld (camdry),hl
    xor a
@A:
; 51 D yaw right
    bit 2,(ix+6)
    jr z,@D
    ld hl,(camdry)
    ld de,camdr
    add hl,de 
    ld (camdry),hl
@D:

    call rotate_camera_loc
    call move_camera_loc

    jp rendbmp

panel_bmid: equ 259
panel_width: equ 320
panel_height: equ 92
panel_size: equ panel_width*panel_height
panel_file: db "fsimpanel.rgba2",0
panel_x: equ 0
panel_y: equ 148

app_special_images:
; load instrument panel image to a buffer and make it a bitmap
    ld bc,panel_width
    ld de,panel_height
    ld hl,panel_bmid
    ld ix,panel_size
    ld iy,panel_file
    ld a,1 ; rgba2
    call vdu_load_img

    ret

app_special_init:
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
    ld bc,0
    ld de,0
    ld ix,320-1
    ld iy,148-1
    call vdu_set_gfx_viewport
    ret

app_special_render:
    ld hl,panel_bmid
    call vdu_buff_select
    call vdu_clg
    ld bc,panel_x
    ld de,panel_y
    call vdu_plot_bmp
    RENDBMP sid, tgtbmid
dispbmp:
    DISPBMP tgtbmid, cstx, csty ; plot render target bitmap
    call vdu_flip ; flip the screen buffer
    ret

sid: equ 100
tgtbmid: equ 257

cstw: equ 320
csth: equ 148
cstx: equ 0
csty: equ 0

camd: equ 32*1 ; 32767/256 * bar
camx: dl  0*camd
camy: dl  -2*camd
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

dithering_type: db 0x00 ; 0=none, 1=bayer ordered matrix, 2=floyd-steinberg