
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