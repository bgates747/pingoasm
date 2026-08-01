; =============================================================================
; Current-Pingo moveair Jet client with eZ80-owned object-local transforms.
;
; Simulation advances in fixed 4/120-second quanta, independently of Pingo's
; renderer. One asynchronous render may be in flight; changes made meanwhile
; remain dirty and are coalesced into the next absolute-state submission.
; =============================================================================

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
    db "Pingo eZ80 local-transform moveair Jet",0

; Application support.
    include "input.inc"
    include "timer.inc"
    include "vdu_pingo.inc"
    include "agon/3d.inc"
    include "agon/3d_sincos_table.inc"
    include "inputair-local.inc"
    include "camera-follow.inc"
    include "render-async.inc"
    include "jet.inc"

main:
    ld hl,vdp_version
    call printString
    call printNewLine

; Load the Jet's RGBA2222 texture.
    ld bc,model_texture_width
    ld de,model_texture_height
    ld hl,objbmid
    ld ix,model_texture_size
    ld iy,model_texture
    ld a,1
    call vdu_load_img

; The viewport is deliberately centralized below. At this point dimensions,
; rather than simulation frequency, are the main render-performance control.
    CTB2 tgtbmid,viewport_width,viewport_height
    CCS sid,viewport_width,viewport_height
    SV sid,mid,model_vertices,model_vertices_n
    SMVI sid,mid,model_vertex_indices,model_indices_n
    STC sid,mid,model_uvs,model_uvs_n
    STCI sid,mid,model_uv_indices,model_indices_n

; 320x240x64 double-buffered display; the Pingo viewport may be tuned
; independently by changing the constants at the end of this file.
    ld a,8+128
    call vdu_set_screen_mode
    ld hl,@display_setup
    ld bc,@display_setup_end-@display_setup
    rst.lil 18h
    jr @display_setup_end
@display_setup:
    db 23,0,0C0h,0
    db 17,20+128
    db 18,0,20+128
@display_setup_end:

    call app_special_init
    call init_object_state
    call init_camera_tracking

; Fence all asynchronous scene construction before enabling completion
; records, then prime the fixed-step clock so MOS uptime is never backlog.
    MOSCALL mos_sysvars
    ld (sysvars_pointer),ix
    call wait_for_setup_barrier
    call initialize_simulation_clock
    call reset_keys
    call initialize_render_state

    call install_render_callback
    call enable_render_notifications
    ei

; The complete initial object and camera states were synchronized during
; initialization. Submit one unconditional render so a static scene appears.
    call submit_current_render

mainloop:
    call set_keys
    call latch_exit_request

; Once exit is requested, stop advancing the world but remain resident until
; the outstanding callback has been consumed.
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

; If a long stall left more simulation work than one foreground batch may
; perform, catch up completely before committing a new render snapshot.
    ld hl,(simulation_accumulator)
    ld de,simulation_step_ticks
    or a
    sbc hl,de
    jr nc,mainloop

; Only synchronize world state when the renderer is idle. The object and
; camera helpers clear submitted dirty bits; motion during the new in-flight
; render sets them again for the following submission.
    ld ix,object_state
    ld a,(ix+p3d_object_dirty)
    and p3d_object_dirty_pose
    ld b,a
    ld ix,camera_state
    ld a,(ix+p3d_camera_dirty)
    and p3d_camera_dirty_all
    or b
    jr z,mainloop
    ld iy,object_packet
    ld ix,object_state
    call p3d_object_sync16
    call sync_camera_state
    call submit_current_render
    jr mainloop

main_end:
; No render remains in flight here. Stop the callback producer before removing
; MOS's callback vector, so no interrupt can target code after this returns.
    call disable_render_notifications
    call remove_render_callback

    xor a
    call vdu_set_screen_mode
    ld a,1
    call vdu_set_scaling
    call cursor_on
    ret

app_special_init:
    call vdu_clg
    call vdu_flip
    call vdu_clg
    call cursor_off
    ret

; ---------------------------------------------------------------------------
; Fixed-step scheduler
; ---------------------------------------------------------------------------

; Prime timestamp_now and discard the first uptime-sized delta.
initialize_simulation_clock:
    call timestamp_tick
    ld hl,0
    ld (simulation_accumulator),hl
    ret

; Add full 24-bit elapsed MOS time and clamp runaway backlog. The clamp avoids
; an unresponsive catch-up spiral after a debugger stop or exceptional stall.
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

; Perform at most four quanta per foreground pass. Each quantum is integrated
; separately because intrinsic rotation followed by local translation is not
; equivalent to one larger update.
run_simulation_batch:
    ld a,simulation_max_steps_per_pass
    ld (simulation_steps_remaining),a
@next:
    ld a,(exit_requested)
    or a
    ret nz
    call take_simulation_step
    ret c
    call simulate_object_step
    call update_camera_tracking

; A latched tap is consumed exactly once. Re-sampling immediately makes held
; keys active on every caught-up quantum.
    call reset_keys
    call set_keys
    call latch_exit_request
    ld a,(exit_requested)
    or a
    ret nz

    ld hl,simulation_steps_remaining
    dec (hl)
    jr nz,@next
    ret

; Carry means fewer than four MOS ticks are accumulated.
take_simulation_step:
    ld hl,(simulation_accumulator)
    ld de,simulation_step_ticks
    or a
    sbc hl,de
    ret c
    ld (simulation_accumulator),hl
    or a
    ret

latch_exit_request:
    ld ix,keyboard_masks
    bit 0,(ix+14)
    ret z
    ld a,1
    ld (exit_requested),a
    ret

; ---------------------------------------------------------------------------
; Stable IDs, viewport, simulation rates, and authoritative object state
; ---------------------------------------------------------------------------

; Use a scene ID distinct from the historical clients so a persistent VDP
; cannot confuse this command-41 registration with older scene state.
sid: equ 1361
mid: equ 1
oid: equ 1
objbmid: equ 256
tgtbmid: equ 257

; Initial behavioral baseline. Reduce these together to trade image area for
; render cadence while leaving the 30 Hz world simulation unchanged.
viewport_width: equ 320
viewport_height: equ 240
viewport_x: equ 0
viewport_y: equ 0

obj_scale: equ 256
obj_initial_x: equ 0
obj_initial_y: equ 0
obj_initial_z: equ -640

; A fixed world-space observer tracks the Jet. Upright roll matches an R/C
; pilot standing in the world; change this equate to
; p3d_camera_roll_continuous to carry the view smoothly over a pole and emerge
; with the horizon inverted.
camera_tracking_roll_policy: equ p3d_camera_roll_upright

camera_initial_position:
    dw 0,0,0

simulation_step_ticks: equ 4
simulation_rate_basis_ticks: equ 128
simulation_max_steps_per_pass: equ 4
simulation_max_backlog_ticks: equ 32

; Per-128-tick rates are intentionally divisible by 32, so conversion to one
; four-tick quantum is a compile-time shift with no run-time multiply.
object_linear_rate_128: equ 352
object_angular_rate_128: equ 4864
object_linear_step: equ object_linear_rate_128 >> 5
object_angular_step: equ object_angular_rate_128 >> 5
object_air_speed_limit: equ 255

object_ids:
    dw sid,oid,mid,objbmid

object_state:
    ds p3d_object_size

object_packet:
    ds p3d_pingo_update_packet_size

camera_state:
    ds p3d_camera_size

simulation_accumulator:
    dl 0

simulation_steps_remaining:
    db 0

filedata:
; MOS loads the model texture beginning at this final address.
