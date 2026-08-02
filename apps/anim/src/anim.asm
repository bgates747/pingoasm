; =============================================================================
; Rigid Lara sampled animation using the current eZ80-owned Pingo contract.
;
; The modern Earth Party support snapshots provide input sampling, fixed-time
; measurement, absolute object state, and one-render-in-flight completion.
; Lara-specific playback and view policy live only in lara-animation.inc.
; =============================================================================

mos_getkey:         equ 00h
mos_load:           equ 01h
mos_sysvars:        equ 08h
mos_getkbmap:       equ 1Eh
mos_setkbvector:    equ 1Dh
sysvar_time:        equ 00h
sysvar_gp:          equ 037h

    MACRO MOSCALL function
        ld a,function
        rst.lil 08h
    ENDMACRO

    .assume adl=1
    .org 040000h

    jp start

    .align 64
    .db "MOS",0,1

start:
    push af
    push bc
    push de
    push ix
    push iy
    call main

exit:
    pop iy
    pop ix
    pop de
    pop bc
    pop af
    ld hl,0
    ret

vdp_version:
    db "Pingo eZ80 rigid Lara animation",0

startup_controls:
    db "W forward  A/D strafe  Left/Right turn",13,10
    db "PgUp/PgDn camera height  P pause  R reset/hold",13,10
    db "Escape exits",13,10
    db "Loading Lara assets...",13,10,0

start_prompt:
    db 13,10,"Ready. Press any key to begin.",13,10,0

waitKeypress:
    MOSCALL mos_getkey
    ret

; Qualified support snapshots and generated animation assets.
    include "input.inc"
    include "timer.inc"
    include "vdu_pingo.inc"
    include "agon/3d.inc"
    include "agon/3d_sincos_table.inc"
    include "render-async.inc"
    include "lara-meshes.inc"
    include "lara-poses.inc"
    include "lara-animation.inc"

main:
    ld hl,vdp_version
    call printString
    call printNewLine
    ld hl,startup_controls
    call printString

; The texture is the only runtime file staged through eZ80 RAM. Geometry and
; animation samples are compiled into anim.bin.
    ld bc,lara_texture_width
    ld de,lara_texture_height
    ld hl,lara_texture_bmid
    ld ix,lara_texture_size
    ld iy,lara_texture
    ld a,1
    call vdu_load_img

    CTB2 tgtbmid,viewport_width,viewport_height
    CCS sid,viewport_width,viewport_height
    call lara_upload_meshes

    ld hl,start_prompt
    call printString
    call waitKeypress
    call lara_wait_for_keys_released

; Match the qualified 320x240 double-buffered application display.
    ld a,8+128
    call vdu_set_screen_mode
    ld hl,@display_setup
    ld bc,@display_setup_end-@display_setup
    rst.lil 18h
    jr @display_setup_end
@display_setup:
    db 23,0,0C0h,0
    db 17,16+128
    db 18,0,16+128
@display_setup_end:

    call vdu_clg
    call vdu_flip
    call vdu_clg
    call cursor_off

; Initial object create/scale/pose plus scene and camera state are ordinary
; asynchronous VDU traffic and are fenced below before rendering begins.
    call lara_animation_initialize
    MOSCALL mos_sysvars
    ld (sysvars_pointer),ix
    call wait_for_setup_barrier
    call initialize_simulation_clock
    call reset_keys
    call initialize_render_state

    call install_render_callback
    call enable_render_notifications
    ei
    call submit_current_render
    call lara_render_submitted

mainloop:
    call set_keys

; Escape is latched by the qualified callback. Stop advancing immediately,
; but remain resident until any in-flight render has completed.
    ld a,(exit_requested)
    or a
    jr nz,@service_render

    call accumulate_simulation_time
    call run_simulation_batch

@service_render:
    ld a,(completion_ready)
    or a
    call nz,consume_render_completion

    ld a,(render_in_flight)
    or a
    jr nz,mainloop

    ld a,(exit_requested)
    or a
    jr nz,main_end

; Finish bounded catch-up before publishing one newest-pose snapshot.
    ld hl,(simulation_accumulator)
    ld de,simulation_step_ticks
    or a
    sbc hl,de
    jr nc,mainloop

    call lara_scene_dirty
    or a
    jr z,mainloop
    call lara_sync_scene
    call submit_current_render
    call lara_render_submitted
    jr mainloop

main_end:
    call disable_render_notifications
    call lara_release_resources
    call wait_for_setup_barrier
    call remove_render_callback

    xor a
    call vdu_set_screen_mode
    ld a,1
    call vdu_set_scaling
    call cursor_on
    ret

; ---------------------------------------------------------------------------
; Fixed 30 Hz scheduler copied from the modern Earth Party application idiom.
; ---------------------------------------------------------------------------

initialize_simulation_clock:
    call timestamp_tick
    ld hl,0
    ld (simulation_accumulator),hl
    ret

accumulate_simulation_time:
    call timestamp_tick
    ld de,(simulation_accumulator)
    add hl,de
    ld de,simulation_max_backlog_ticks+1
    or a
    sbc hl,de
    jr c,@below_limit
    ld hl,simulation_max_backlog_ticks
    ld (simulation_accumulator),hl
    ret
@below_limit:
    add hl,de
    ld (simulation_accumulator),hl
    ret

run_simulation_batch:
    ld a,simulation_max_steps_per_pass
    ld (simulation_steps_remaining),a
@next:
    ld a,(exit_requested)
    or a
    ret nz
    call take_simulation_step
    ret c
    call lara_animation_step

; Consume latched taps once per simulation quantum, then immediately resample
; so held keys remain visible to the following catch-up quantum.
    call reset_keys
    call set_keys

    ld hl,simulation_steps_remaining
    dec (hl)
    jr nz,@next
    ret

take_simulation_step:
    ld hl,(simulation_accumulator)
    ld de,simulation_step_ticks
    or a
    sbc hl,de
    ret c
    ld (simulation_accumulator),hl
    or a
    ret

; ---------------------------------------------------------------------------
; Global buffer IDs, viewport, and scheduler bounds.
; MID/OID values 1..15 are local to this Pingo control and generated with the
; mesh/pose data; they are not members of the global buffer namespace.
; ---------------------------------------------------------------------------

viewport_x: equ 0
viewport_y: equ 0

simulation_step_ticks: equ 4
simulation_max_steps_per_pass: equ 4
simulation_max_backlog_ticks: equ 32

simulation_accumulator:
    dl 0

simulation_steps_remaining:
    db 0

filedata:
; MOS loads Lara.rgba2 beginning at this final application address.
