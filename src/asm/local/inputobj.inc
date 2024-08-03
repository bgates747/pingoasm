
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
; TODO: THIS SEEMS TO ORBIT THE OBJECT AROUND THE OBJECT
; ABOUT THE WORLD X-AXIS
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

    jp get_input_return
