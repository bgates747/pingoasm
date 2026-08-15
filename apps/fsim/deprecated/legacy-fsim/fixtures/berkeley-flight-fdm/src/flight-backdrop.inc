; =============================================================================
; Cheap attitude-aware horizon fallback.
;
; Pingo clears untouched RGBA2222 target pixels to transparent.  Immediately
; before compositing that target, the eZ80 paints the reduced graphics
; viewport with two sky triangles and a large, roll-rotated two-triangle
; neutral-ground quad.  Terrain therefore overlays a coherent fallback rather
; than exposing black wherever chunks are unloaded, culled, or beyond range.
; =============================================================================

backdrop_plot_move_absolute: equ 04h
backdrop_plot_triangle_absolute: equ 55h
backdrop_sky_colour: equ 47       ; logical 47 -> Agon64 RGB(170,170,255)
backdrop_ground_colour: equ 8     ; logical 8 -> Agon64 RGB(85,85,85)
backdrop_center_x: equ 160
backdrop_center_y: equ 74

    MACRO BACKDROP_STORE_HL16 target
        ld a,l
        ld (target),a
        ld a,h
        ld (target+1),a
    ENDMACRO

    MACRO BACKDROP_LOAD_HL16 source
        ld a,(source)
        ld l,a
        ld a,(source+1)
        ld h,a
    ENDMACRO

    MACRO BACKDROP_LOAD_DE16 source
        ld a,(source)
        ld e,a
        ld a,(source+1)
        ld d,a
    ENDMACRO

; Derive the view-relative attitude from the retained local-to-world matrix.
; The exported Euler triple is allowed to choose an equivalent +/-180-degree
; branch; using those words independently would make a shallow pitch look
; inverted.  The world-up row is branch-free: forward elevation is
; asin(-r1c2), and screen roll is atan2(r1c0,r1c1).
backdrop_extract_attitude:
    ld l,(ix+p3d_mat3_r1c2)
    ld h,(ix+p3d_mat3_r1c2+1)
    ld a,h
    cp 080h
    jr nz,@negate_pitch
    ld a,l
    or a
    jr nz,@negate_pitch
    ld hl,32767
    jr @pitch_ready
@negate_pitch:
    xor a
    sub l
    ld l,a
    ld a,0
    sbc a,h
    ld h,a
@pitch_ready:
    call p3d_asin16
    BACKDROP_STORE_HL16 backdrop_pitch_word

    ld l,(ix+p3d_mat3_r1c0)
    ld h,(ix+p3d_mat3_r1c0+1)
    ld e,(ix+p3d_mat3_r1c1)
    ld d,(ix+p3d_mat3_r1c1+1)
    call p3d_atan2_16
    BACKDROP_STORE_HL16 backdrop_roll_word
    ret

draw_flight_backdrop:
    ld ix,object_state+p3d_object_orientation
    call backdrop_extract_attitude

; Pitch maps approximately +/-90 degrees to +/-128 pixels.  Positive aircraft
; pitch moves the visual horizon down, exposing more sky.
    BACKDROP_LOAD_HL16 backdrop_pitch_word
    ld a,6
@pitch_shift:
    sra h
    rr l
    dec a
    jr nz,@pitch_shift
    ld de,backdrop_center_y
    add.s hl,de
    BACKDROP_STORE_HL16 backdrop_horizon_y

; Horizon direction is (cos roll, sin roll), scaled to radius 512 by >>6.
    BACKDROP_LOAD_HL16 backdrop_roll_word
    call p3d_sincos16
    ld h,b
    ld l,c
    call backdrop_shift_hl_6
    BACKDROP_STORE_HL16 backdrop_sin_r512
    ld h,d
    ld l,e
    call backdrop_shift_hl_6
    BACKDROP_STORE_HL16 backdrop_cos_r512

; h0 = center - direction, h1 = center + direction.
    BACKDROP_LOAD_HL16 backdrop_cos_r512
    ld de,backdrop_center_x
    ex de,hl
    or a
    sbc.s hl,de
    BACKDROP_STORE_HL16 backdrop_h0_x
    BACKDROP_LOAD_HL16 backdrop_cos_r512
    ld de,backdrop_center_x
    add.s hl,de
    BACKDROP_STORE_HL16 backdrop_h1_x

    BACKDROP_LOAD_HL16 backdrop_sin_r512
    BACKDROP_LOAD_DE16 backdrop_horizon_y
    ex de,hl
    or a
    sbc.s hl,de
    BACKDROP_STORE_HL16 backdrop_h0_y
    BACKDROP_LOAD_HL16 backdrop_sin_r512
    BACKDROP_LOAD_DE16 backdrop_horizon_y
    add.s hl,de
    BACKDROP_STORE_HL16 backdrop_h1_y

; Downward normal is (-sin,cos).  Doubling the radius-512 values gives a
; 1024-pixel-deep quad, safely larger than the complete 320x148 viewport.
    BACKDROP_LOAD_HL16 backdrop_sin_r512
    add.s hl,hl
    xor a
    sub l
    ld l,a
    ld a,0
    sbc a,h
    ld h,a
    BACKDROP_STORE_HL16 backdrop_down_x
    BACKDROP_LOAD_HL16 backdrop_cos_r512
    add.s hl,hl
    BACKDROP_STORE_HL16 backdrop_down_y

; g0/g1 are the far-ground partners of h0/h1.
    BACKDROP_LOAD_HL16 backdrop_h0_x
    BACKDROP_LOAD_DE16 backdrop_down_x
    add.s hl,de
    BACKDROP_STORE_HL16 backdrop_g0_x
    BACKDROP_LOAD_HL16 backdrop_h0_y
    BACKDROP_LOAD_DE16 backdrop_down_y
    add.s hl,de
    BACKDROP_STORE_HL16 backdrop_g0_y
    BACKDROP_LOAD_HL16 backdrop_h1_x
    BACKDROP_LOAD_DE16 backdrop_down_x
    add.s hl,de
    BACKDROP_STORE_HL16 backdrop_g1_x
    BACKDROP_LOAD_HL16 backdrop_h1_y
    BACKDROP_LOAD_DE16 backdrop_down_y
    add.s hl,de
    BACKDROP_STORE_HL16 backdrop_g1_y

    call backdrop_patch_ground_packet
    ld hl,backdrop_packet
    ld bc,backdrop_packet_end-backdrop_packet
    rst.lil 18h
    ret

backdrop_shift_hl_6:
    ld a,6
@loop:
    sra h
    rr l
    dec a
    jr nz,@loop
    ret

; Every target below is an exact two-byte VDU field.  Patch bytes explicitly:
; an unsuffixed ADL store from HL would write three bytes and corrupt the next
; plot command.
backdrop_patch_ground_packet:
    ld a,(backdrop_h0_x)
    ld (backdrop_t0_x0),a
    ld (backdrop_t1_x0),a
    ld a,(backdrop_h0_x+1)
    ld (backdrop_t0_x0+1),a
    ld (backdrop_t1_x0+1),a
    ld a,(backdrop_h0_y)
    ld (backdrop_t0_y0),a
    ld (backdrop_t1_y0),a
    ld a,(backdrop_h0_y+1)
    ld (backdrop_t0_y0+1),a
    ld (backdrop_t1_y0+1),a

    ld a,(backdrop_h1_x)
    ld (backdrop_t0_x1),a
    ld a,(backdrop_h1_x+1)
    ld (backdrop_t0_x1+1),a
    ld a,(backdrop_h1_y)
    ld (backdrop_t0_y1),a
    ld a,(backdrop_h1_y+1)
    ld (backdrop_t0_y1+1),a

    ld a,(backdrop_g1_x)
    ld (backdrop_t0_x2),a
    ld (backdrop_t1_x1),a
    ld a,(backdrop_g1_x+1)
    ld (backdrop_t0_x2+1),a
    ld (backdrop_t1_x1+1),a
    ld a,(backdrop_g1_y)
    ld (backdrop_t0_y2),a
    ld (backdrop_t1_y1),a
    ld a,(backdrop_g1_y+1)
    ld (backdrop_t0_y2+1),a
    ld (backdrop_t1_y1+1),a

    ld a,(backdrop_g0_x)
    ld (backdrop_t1_x2),a
    ld a,(backdrop_g0_x+1)
    ld (backdrop_t1_x2+1),a
    ld a,(backdrop_g0_y)
    ld (backdrop_t1_y2),a
    ld a,(backdrop_g0_y+1)
    ld (backdrop_t1_y2+1),a
    ret

; Static sky rectangle, then the dynamic ground quad.  Each filled triangle
; consumes the preceding two graphics-cursor positions plus its final point.
backdrop_packet:
    db 18,0,backdrop_sky_colour
    db 25,backdrop_plot_move_absolute
    dw 0,0
    db 25,backdrop_plot_move_absolute
    dw viewport_width-1,0
    db 25,backdrop_plot_triangle_absolute
    dw viewport_width-1,viewport_height-1
    db 25,backdrop_plot_move_absolute
    dw 0,0
    db 25,backdrop_plot_move_absolute
    dw viewport_width-1,viewport_height-1
    db 25,backdrop_plot_triangle_absolute
    dw 0,viewport_height-1

    db 18,0,backdrop_ground_colour
    db 25,backdrop_plot_move_absolute
backdrop_t0_x0: dw 0
backdrop_t0_y0: dw 0
    db 25,backdrop_plot_move_absolute
backdrop_t0_x1: dw 0
backdrop_t0_y1: dw 0
    db 25,backdrop_plot_triangle_absolute
backdrop_t0_x2: dw 0
backdrop_t0_y2: dw 0
    db 25,backdrop_plot_move_absolute
backdrop_t1_x0: dw 0
backdrop_t1_y0: dw 0
    db 25,backdrop_plot_move_absolute
backdrop_t1_x1: dw 0
backdrop_t1_y1: dw 0
    db 25,backdrop_plot_triangle_absolute
backdrop_t1_x2: dw 0
backdrop_t1_y2: dw 0
backdrop_packet_end:

backdrop_horizon_y: dw 0
backdrop_pitch_word: dw 0
backdrop_roll_word: dw 0
backdrop_sin_r512: dw 0
backdrop_cos_r512: dw 0
backdrop_h0_x: dw 0
backdrop_h0_y: dw 0
backdrop_h1_x: dw 0
backdrop_h1_y: dw 0
backdrop_down_x: dw 0
backdrop_down_y: dw 0
backdrop_g0_x: dw 0
backdrop_g0_y: dw 0
backdrop_g1_x: dw 0
backdrop_g1_y: dw 0
