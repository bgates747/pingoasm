; =============================================================================
; Experimental Pingo command 52 client.
;
; Inputs:
;   HL = existing object ID
;   IX = pointer to nine exact little-endian signed-24 bytes: X, Y, Z
;
; The 24-bit fields use the same raw translation-count unit as legacy command
; 17. Packet fields are copied bytewise so ADL mode cannot widen a two-byte ID
; or overlap adjacent three-byte coordinates.
; Clobbers AF, BC, HL; preserves IX.
; =============================================================================

pingo_set_object_xyz_translation_wide:
    ld a,l
    ld (@oid),a
    ld a,h
    ld (@oid+1),a

    ld a,(ix+0)
    ld (@x+0),a
    ld a,(ix+1)
    ld (@x+1),a
    ld a,(ix+2)
    ld (@x+2),a
    ld a,(ix+3)
    ld (@y+0),a
    ld a,(ix+4)
    ld (@y+1),a
    ld a,(ix+5)
    ld (@y+2),a
    ld a,(ix+6)
    ld (@z+0),a
    ld a,(ix+7)
    ld (@z+1),a
    ld a,(ix+8)
    ld (@z+2),a

    ld hl,@command
    ld bc,@command_end-@command
    rst.lil 18h
    ret

@command:
    db 23,0,0A0h
    dw sid
    db 049h,52
@oid:
    dw 0
@x:
    db 0,0,0
@y:
    db 0,0,0
@z:
    db 0,0,0
@command_end:
