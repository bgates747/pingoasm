keyboard_masks: ds 16 ; 16 bytes for the keyboard masks 

; check system virtual keyboard map for keys down and or them with local keyboard masks
; inputs: none
; outputs: none
; clobbers: a, b, ix, iy
set_keys:
    MOSCALL mos_getkbmap ; ix points to the virtual keyboard map
    ld iy,keyboard_masks 
    ld b,16 ; loop counter
@loop:
    ld a,(ix)
    or (iy)
    ld (iy),a
    inc ix
    inc iy
    djnz @loop
    ret

; reset the local keyboard masks to zero
; inputs: none
; outputs: none
; clobbers: a, b, iy
reset_keys:
    ld iy,keyboard_masks
    xor a
    ld b,16 ; loop counter
@loop:
    ld (iy),a
    inc iy
    djnz @loop
    ret