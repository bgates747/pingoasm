; Syntax/width harness for fixtures/_common/pingo-wide-translation.inc.
    .assume adl=1
    .org 040000h
    jp start

sid: equ 1731

start:
    ld hl,7
    ld ix,wide_xyz
    call pingo_set_object_xyz_translation_wide
    ret

    include "../fixtures/_common/pingo-wide-translation.inc"

wide_xyz:
    db 000h,080h,0ffh
    db 000h,000h,000h
    db 0ffh,07fh,000h
