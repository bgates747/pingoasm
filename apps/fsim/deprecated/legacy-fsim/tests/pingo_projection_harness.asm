; Syntax/width harness for fixtures/_common/pingo-projection.inc.
    .assume adl=1
    .org 040000h
    jp start

sid: equ 1731

start:
    ld hl,8000
    call pingo_set_projection_far_units
    ret

    include "../fixtures/_common/pingo-projection.inc"
