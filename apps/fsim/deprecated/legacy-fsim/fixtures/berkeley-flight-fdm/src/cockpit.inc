; Static 320x92 cockpit overlay and reduced 320x148 exterior viewport.

cockpit_bmid: equ 258
cockpit_width: equ 320
cockpit_height: equ 92
cockpit_bytes: equ cockpit_width*cockpit_height
cockpit_x: equ 0
cockpit_y: equ 148

cockpit_load:
    ld bc,cockpit_width
    ld de,cockpit_height
    ld hl,cockpit_bmid
    ld ix,cockpit_bytes
    ld iy,cockpit_file
    ld a,1
    jp vdu_load_img

; Paint the authored panel once into both physical screen buffers, then clip
; all later clears/backdrop plots/Pingo composites to the upper exterior view.
cockpit_init:
    call vdu_clg
    DISPBMP cockpit_bmid,cockpit_x,cockpit_y
    call vdu_flip
    call vdu_clg
    DISPBMP cockpit_bmid,cockpit_x,cockpit_y
    ld hl,@viewport
    ld bc,@viewport_end-@viewport
    rst.lil 18h
    ret
@viewport:
    db 24
    dw 0,viewport_height-1,viewport_width-1,0
@viewport_end:
