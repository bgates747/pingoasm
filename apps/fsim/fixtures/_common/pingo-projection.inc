; =============================================================================
; Experimental Pingo command 53 client.
;
; Inputs:
;   HL = projection far distance in Pingo scene units (2..65535)
;
; Values 0 and 1 are consumed but rejected by the VDP, preserving the current
; setting.  Copy the two-byte value bytewise so ADL mode cannot widen the
; packet field into the following command stream.
; Clobbers AF, BC, HL.
; =============================================================================

pingo_set_projection_far_units:
    ld a,l
    ld (@far_units),a
    ld a,h
    ld (@far_units+1),a

    ld hl,@command
    ld bc,@command_end-@command
    rst.lil 18h
    ret

@command:
    db 23,0,0A0h
    dw sid
    db 049h,53
@far_units:
    dw 0
@command_end:
