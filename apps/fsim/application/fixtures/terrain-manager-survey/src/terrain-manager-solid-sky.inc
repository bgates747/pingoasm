; =============================================================================
; Fixed full-frame sky clear for terrain-manager camera fixtures.
;
; Pingo clears untouched target pixels to transparent before each render.  The
; completed target is composited over this solid canvas clear, so missing
; scenery reveals one stable sky colour.  This deliberately has no horizon,
; ground proxy, pitch, roll, or other camera-attitude dependency.
; =============================================================================

terrain_sky_plot_move_absolute: equ 04h
terrain_sky_plot_triangle_absolute: equ 55h
terrain_sky_colour: equ 47

; render-async.inc retains this historical callback name.  For this fixture it
; means only "clear the visible render area before compositing the target".
draw_flight_backdrop:
    ld hl,terrain_sky_clear_packet
    ld bc,terrain_sky_clear_packet_end-terrain_sky_clear_packet
    rst.lil 18h
    ret

terrain_sky_clear_packet:
    db 18,0,terrain_sky_colour
    db 25,terrain_sky_plot_move_absolute
    dw 0,0
    db 25,terrain_sky_plot_move_absolute
    dw viewport_width-1,0
    db 25,terrain_sky_plot_triangle_absolute
    dw viewport_width-1,viewport_height-1
    db 25,terrain_sky_plot_move_absolute
    dw 0,0
    db 25,terrain_sky_plot_move_absolute
    dw viewport_width-1,viewport_height-1
    db 25,terrain_sky_plot_triangle_absolute
    dw 0,viewport_height-1
terrain_sky_clear_packet_end:

; The superseded attitude backdrop occupied 704 more assembled bytes at this
; include boundary.  Preserve that space so the large generated hierarchy and
; manager retain their established debugger/listing addresses while this
; presentation experiment is under human review.
terrain_sky_compatibility_reserve_bytes: equ 704
    ds terrain_sky_compatibility_reserve_bytes
