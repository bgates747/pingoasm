; Runtime-variable Pingo helpers used by the regional slot coordinator.
; Every packet field is an exact little-endian u16 and is patched bytewise.

; Inputs: HL=object ID, DE=mesh ID, BC=bitmap ID.
pingo_create_object_runtime:
    ld a,l
    ld (@oid),a
    ld a,h
    ld (@oid+1),a
    ld a,e
    ld (@mid),a
    ld a,d
    ld (@mid+1),a
    ld a,c
    ld (@bmid),a
    ld a,b
    ld (@bmid+1),a
    ld hl,@command
    ld bc,@command_end-@command
    rst.lil 18h
    ret
@command:
    db 23,0,0A0h
    dw sid
    db 049h,5
@oid:  dw 0
@mid:  dw 0
@bmid: dw 0
@command_end:

; Inputs: HL=object ID, DE=uniform unsigned Q8.8 scale.
pingo_set_object_uniform_scale:
    ld a,l
    ld (@oid),a
    ld a,h
    ld (@oid+1),a
    ld a,e
    ld (@sx),a
    ld (@sy),a
    ld (@sz),a
    ld a,d
    ld (@sx+1),a
    ld (@sy+1),a
    ld (@sz+1),a
    ld hl,@command
    ld bc,@command_end-@command
    rst.lil 18h
    ret
@command:
    db 23,0,0A0h
    dw sid
    db 049h,9
@oid: dw 0
@sx:  dw 0
@sy:  dw 0
@sz:  dw 0
@command_end:
