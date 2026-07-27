; =============================================================================
; TurboVega-compatible move-object controls.
; Key mapping adapted from pingoasm apps/_common/inputobj.inc.
; Uses only absolute TurboVega commands 13 and 17.
; =============================================================================

update_object_from_keys:
; Return A=0 when nothing changed and A=1 after sending a changed transform.
    xor a

; W/S: translate Z.
    bit 1,(ix+4)
    jr z,@not_w
    ld hl,(objz)
    ld de,-objz_limit
    or a
    sbc hl,de
    jr z,@not_w
    ld hl,(objz)
    ld de,-objd
    add hl,de
    ld (objz),hl
    ld a,1
@not_w:
    bit 1,(ix+10)
    jr z,@not_s
    ld hl,(objz)
    ld de,objz_limit
    or a
    sbc hl,de
    jr z,@not_s
    ld hl,(objz)
    ld de,objd
    add hl,de
    ld (objz),hl
    ld a,1
@not_s:

; A/D: translate X.
    bit 1,(ix+8)
    jr z,@not_a
    ld hl,(objx)
    ld de,-objd
    add hl,de
    ld (objx),hl
    ld a,1
@not_a:
    bit 2,(ix+6)
    jr z,@not_d
    ld hl,(objx)
    ld de,objd
    add hl,de
    ld (objx),hl
    ld a,1
@not_d:

; Page Up/Page Down: translate Y.
    bit 7,(ix+7)
    jr z,@not_pgup
    ld hl,(objy)
    ld de,objd
    add hl,de
    ld (objy),hl
    ld a,1
@not_pgup:
    bit 6,(ix+9)
    jr z,@not_pgdn
    ld hl,(objy)
    ld de,-objd
    add hl,de
    ld (objy),hl
    ld a,1
@not_pgdn:

; Q/E: rotate Z.
    bit 0,(ix+2)
    jr z,@not_q
    ld hl,(objrz)
    ld de,objdr
    add hl,de
    ld (objrz),hl
    ld a,1
@not_q:
    bit 2,(ix+4)
    jr z,@not_e
    ld hl,(objrz)
    ld de,-objdr
    add hl,de
    ld (objrz),hl
    ld a,1
@not_e:

; Up/Down: rotate X.
    bit 1,(ix+7)
    jr z,@not_up
    ld hl,(objrx)
    ld de,-objdr
    add hl,de
    ld (objrx),hl
    ld a,1
@not_up:
    bit 1,(ix+5)
    jr z,@not_down
    ld hl,(objrx)
    ld de,objdr
    add hl,de
    ld (objrx),hl
    ld a,1
@not_down:

; Left/Right: rotate Y.
    bit 1,(ix+3)
    jr z,@not_left
    ld hl,(objry)
    ld de,objdr
    add hl,de
    ld (objry),hl
    ld a,1
@not_left:
    bit 1,(ix+15)
    jr z,@not_right
    ld hl,(objry)
    ld de,-objdr
    add hl,de
    ld (objry),hl
    ld a,1
@not_right:

; Send the accumulated absolute transform through TurboVega commands 13 and 17.
    or a
    ret z
    push af

    ld hl,oid
    ld bc,(objrx)
    ld de,(objry)
    ld iy,(objrz)
    call sorabs

    ld hl,oid
    ld bc,(objx)
    ld de,(objy)
    ld iy,(objz)
    call sodabs
    pop af
    ret
