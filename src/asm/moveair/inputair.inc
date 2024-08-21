; ============ INPUTAIR.INC ============
throttle: dl 0x000000 ; unsigned 8-bit integer 255 = 100% throttle

; ============ KEYBOARD INPUT ============
get_input:

; get user keyboard input
	MOSCALL mos_getkbmap

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