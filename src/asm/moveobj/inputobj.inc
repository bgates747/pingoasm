
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

; ------ MOVE OBJECT ------
    ld a,1 ; we set a to zero if a object movement key is pressed
; move object z axis
; 34 W move forward
    bit 1,(ix+4)
    jr z,@W
    ld hl,-objd
    ld (objdz),hl
    xor a
@W: 
; 82 S move backward
    bit 1,(ix+10)
    jr z,@S
    ld hl,(objdz)
    ld de,objd
    add hl,de 
    ld (objdz),hl
    xor a
@S:

; move object x axis
; 66 A move left
    bit 1,(ix+8)
    jr z,@A
    ld hl,-objd
    ld (objdx),hl
    xor a
@A:
; 51 D move right
    bit 2,(ix+6)
    jr z,@D
    ld hl,(objdx)
    ld de,objd 
    add hl,de 
    ld (objdx),hl
    xor a
@D:

; move object y axis
; 64 PgUp move up
    bit 7,(ix+7)
    jr z,@PgUp
    ld hl,objd
    ld (objdy),hl
    xor a
@PgUp:
; 79 PgDn move down
    bit 6,(ix+9)
    jr z,@PgDn
    ld hl,(objdy)
    ld de,-objd
    add hl,de 
    ld (objdy),hl
    xor a
@PgDn:

; ------ ROTATE OBJECT ------
; rotate object z axis
; 17 Q roll left
    bit 0,(ix+2)
    jr z,@Q
    ld hl,objdr 
    ld (objdrz),hl
    xor a
@Q:
; 35 E roll right
    bit 2,(ix+4)
    jr z,@E
    ld hl,(objdrz)
    ld de,-objdr 
    add hl,de 
    ld (objdrz),hl
    xor a
@E:

; rotate object x axis
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

; rotate object y axis
; 26 Left yaw left
    bit 1,(ix+3)
    jr z,@Left
    ld hl,objdr
    ld (objdry),hl
    xor a
@Left:
; 122 Right yaw right
    bit 1,(ix+15)
    jr z,@Right
    ld hl,(objdry)
    ld de,-objdr
    add hl,de 
    ld (objdry),hl
    xor a
@Right:

    and a ; zero means we need to rotate and or move the camera
    jp nz,no_move

    call rotate_object_loc
    call move_object_loc

    ; call rotate_object_abs
    ; call move_object_abs

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