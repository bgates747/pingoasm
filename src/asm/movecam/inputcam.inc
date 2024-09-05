
; ============ KEYBOARD INPUT ============
do_input:
; reset control object movement and rotation deltas
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

; ------ MOVE CAMERA ------
    ld a,1 ; we set a to zero if a camera movement key is pressed
; move camera z axis
; 34 W move forward
    bit 1,(ix+4)
    jr z,@W
    ld hl,camd
    ld (camdz),hl
    xor a
@W: 
; 82 S move backward
    bit 1,(ix+10)
    jr z,@S
    ld hl,(camdz)
    ld de,-camd
    add hl,de 
    ld (camdz),hl
    xor a
@S:

; move camera x axis
; 66 A move left
    bit 1,(ix+8)
    jr z,@A
    ld hl,camd
    ld (camdx),hl
    xor a
@A:
; 51 D move right
    bit 2,(ix+6)
    jr z,@D
    ld hl,(camdx)
    ld de,-camd 
    add hl,de 
    ld (camdx),hl
    xor a
@D:

; move camera y axis
; 64 PgUp move up
    bit 7,(ix+7)
    jr z,@PgUp
    ld hl,-camd
    ld (camdy),hl
    xor a
@PgUp:
; 79 PgDn move down
    bit 6,(ix+9)
    jr z,@PgDn
    ld hl,(camdy)
    ld de,camd
    add hl,de 
    ld (camdy),hl
    xor a
@PgDn:

; ------ ROTATE CAMERA ------
; rotate camera z axis
; 17 Q roll left
    bit 0,(ix+2)
    jr z,@Q
    ld hl,-camdr 
    ld (camdrz),hl
    xor a
@Q:
; 35 E roll right
    bit 2,(ix+4)
    jr z,@E
    ld hl,(camdrz)
    ld de,camdr 
    add hl,de 
    ld (camdrz),hl
    xor a
@E:

; rotate camera x axis
; TODO: THIS SEEMS TO ORBIT THE CAMERA AROUND THE OBJECT
; ABOUT THE WORLD X-AXIS
; 58 Up tilt down
    bit 1,(ix+7)
    jr z,@Up
    ld hl,camdr
    ld (camdrx),hl
    xor a
@Up:
; 42 Down tilt up
    bit 1,(ix+5)
    jr z,@Down
    ld hl,(camdrx)
    ld de,-camdr
    add hl,de 
    ld (camdrx),hl
    xor a
@Down:

; rotate camera y axis
; 26 Left pan left
    bit 1,(ix+3)
    jr z,@Left
    ld hl,-camdr
    ld (camdry),hl
    xor a
@Left:
; 122 Right pan right
    bit 1,(ix+15)
    jr z,@Right
    ld hl,(camdry)
    ld de,camdr
    add hl,de 
    ld (camdry),hl
    xor a
@Right:

    and a ; zero means we need to rotate and or move the camera
    jp nz,no_move

    call rotate_camera_loc
    call move_camera_loc

    ; call printNewLine
    ; ld a,(dithering_type)
    ; ld hl,0
    ; ld l,a
    ; call printDec

    jp rendbmp

app_special_images:

    ret

app_special_init:
; clear the screen twice to set both buffers to background color
    call vdu_clg
    call vdu_flip
    call vdu_clg
    ret

app_special_render:
    RENDBMP sid, tgtbmid
dispbmp:
    call vdu_clg ; clear screen
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
csth: equ 240
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