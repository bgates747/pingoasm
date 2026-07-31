; =============================================================================
; Current-Pingo interactive Earth Party with eZ80-owned local transforms.
;
; Simulation advances in fixed 4/120-second quanta, independently of Pingo's
; renderer. One asynchronous render may be in flight; changes made meanwhile
; remain dirty and are coalesced into the next absolute-state submission.
; The camera follows the user-controlled Jet. Earth spins about a tilted local
; axis, while four background objects retain constant forward and yaw
; velocities that make closed, unscripted integer orbits.
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
    db "Pingo eZ80 local-transform Earth Party",0

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
    include "earthuv.inc"
    include "crash.inc"
    include "lara.inc"
    include "heavytank.inc"
    include "airliner.inc"

main:
    ld hl,vdp_version
    call printString
    call printNewLine

; Load all RGBA2222 textures sequentially through the common filedata staging
; area. Pingo retains each completed bitmap, so eZ80 RAM holds only one source
; texture at a time.
    ld bc,jet_texture_width
    ld de,jet_texture_height
    ld hl,jet_bmid
    ld ix,jet_texture_size
    ld iy,jet_texture
    ld a,1
    call vdu_load_img

    ld bc,earthuv_texture_width
    ld de,earthuv_texture_height
    ld hl,earthuv_bmid
    ld ix,earthuv_texture_size
    ld iy,earthuv_texture
    ld a,1
    call vdu_load_img

    ld bc,crash_texture_width
    ld de,crash_texture_height
    ld hl,crash_bmid
    ld ix,crash_texture_size
    ld iy,crash_texture
    ld a,1
    call vdu_load_img

    ld bc,lara_texture_width
    ld de,lara_texture_height
    ld hl,lara_bmid
    ld ix,lara_texture_size
    ld iy,lara_texture
    ld a,1
    call vdu_load_img

    ld bc,heavytank_texture_width
    ld de,heavytank_texture_height
    ld hl,heavytank_bmid
    ld ix,heavytank_texture_size
    ld iy,heavytank_texture
    ld a,1
    call vdu_load_img

    ld bc,airliner_texture_width
    ld de,airliner_texture_height
    ld hl,airliner_bmid
    ld ix,airliner_texture_size
    ld iy,airliner_texture
    ld a,1
    call vdu_load_img

; The viewport is deliberately centralized below. At this point dimensions,
; rather than simulation frequency, are the main render-performance control.
    CTB2 tgtbmid,viewport_width,viewport_height
    CCS sid,viewport_width,viewport_height
    SV sid,jet_mid,jet_vertices,jet_vertices_n
    SMVI sid,jet_mid,jet_vertex_indices,jet_indices_n
    STC sid,jet_mid,jet_uvs,jet_uvs_n
    STCI sid,jet_mid,jet_uv_indices,jet_indices_n

    SV sid,earthuv_mid,earthuv_vertices,earthuv_vertices_n
    SMVI sid,earthuv_mid,earthuv_vertex_indices,earthuv_indices_n
    STC sid,earthuv_mid,earthuv_uvs,earthuv_uvs_n
    STCI sid,earthuv_mid,earthuv_uv_indices,earthuv_indices_n

    SV sid,crash_mid,crash_vertices,crash_vertices_n
    SMVI sid,crash_mid,crash_vertex_indices,crash_indices_n
    STC sid,crash_mid,crash_uvs,crash_uvs_n
    STCI sid,crash_mid,crash_uv_indices,crash_indices_n

    SV sid,lara_mid,lara_vertices,lara_vertices_n
    SMVI sid,lara_mid,lara_vertex_indices,lara_indices_n
    STC sid,lara_mid,lara_uvs,lara_uvs_n
    STCI sid,lara_mid,lara_uv_indices,lara_indices_n

    SV sid,heavytank_mid,heavytank_vertices,heavytank_vertices_n
    SMVI sid,heavytank_mid,heavytank_vertex_indices,heavytank_indices_n
    STC sid,heavytank_mid,heavytank_uvs,heavytank_uvs_n
    STCI sid,heavytank_mid,heavytank_uv_indices,heavytank_indices_n

    SV sid,airliner_mid,airliner_vertices,airliner_vertices_n
    SMVI sid,airliner_mid,airliner_vertex_indices,airliner_indices_n
    STC sid,airliner_mid,airliner_uvs,airliner_uvs_n
    STCI sid,airliner_mid,airliner_uv_indices,airliner_indices_n

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
    call init_party_objects
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
    call scene_pose_dirty
    ld b,a
    ld ix,camera_state
    ld a,(ix+p3d_camera_dirty)
    and p3d_camera_dirty_all
    or b
    jr z,mainloop
    call sync_scene_objects
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

; ---------------------------------------------------------------------------
; Persistent autonomous scene objects
; ---------------------------------------------------------------------------

; Portable initialization record. Its first four words deliberately match the
; tuple consumed by p3d_object_init16.
party_config_position: equ 8
party_config_euler: equ 14
party_config_scale: equ 20
party_config_linear: equ 22
party_config_angular: equ 28
party_config_size: equ 34

    MACRO PARTY_COPY_CONFIG_WORD SOURCE_OFFSET, DESTINATION_OFFSET
        ld l,(iy+SOURCE_OFFSET)
        ld h,(iy+SOURCE_OFFSET+1)
        ld (ix+DESTINATION_OFFSET),l
        ld (ix+DESTINATION_OFFSET+1),h
    ENDMACRO

; IX selects one state and IY its immutable initialization record.
init_party_object:
    call p3d_object_init16
    PARTY_COPY_CONFIG_WORD party_config_position+p3d_vec3_x,p3d_object_world_position+p3d_vec3_x
    PARTY_COPY_CONFIG_WORD party_config_position+p3d_vec3_y,p3d_object_world_position+p3d_vec3_y
    PARTY_COPY_CONFIG_WORD party_config_position+p3d_vec3_z,p3d_object_world_position+p3d_vec3_z
    PARTY_COPY_CONFIG_WORD party_config_euler+p3d_vec3_x,p3d_object_pingo_rotation+p3d_vec3_x
    PARTY_COPY_CONFIG_WORD party_config_euler+p3d_vec3_y,p3d_object_pingo_rotation+p3d_vec3_y
    PARTY_COPY_CONFIG_WORD party_config_euler+p3d_vec3_z,p3d_object_pingo_rotation+p3d_vec3_z
    PARTY_COPY_CONFIG_WORD party_config_scale,p3d_object_scale+p3d_vec3_x
    PARTY_COPY_CONFIG_WORD party_config_scale,p3d_object_scale+p3d_vec3_y
    PARTY_COPY_CONFIG_WORD party_config_scale,p3d_object_scale+p3d_vec3_z
    PARTY_COPY_CONFIG_WORD party_config_linear+p3d_vec3_x,p3d_object_local_linear_velocity+p3d_vec3_x
    PARTY_COPY_CONFIG_WORD party_config_linear+p3d_vec3_y,p3d_object_local_linear_velocity+p3d_vec3_y
    PARTY_COPY_CONFIG_WORD party_config_linear+p3d_vec3_z,p3d_object_local_linear_velocity+p3d_vec3_z
    PARTY_COPY_CONFIG_WORD party_config_angular+p3d_vec3_x,p3d_object_local_angular_velocity+p3d_vec3_x
    PARTY_COPY_CONFIG_WORD party_config_angular+p3d_vec3_y,p3d_object_local_angular_velocity+p3d_vec3_y
    PARTY_COPY_CONFIG_WORD party_config_angular+p3d_vec3_z,p3d_object_local_angular_velocity+p3d_vec3_z
    lea iy,iy+party_config_euler
    lea ix,ix+p3d_object_orientation
    call p3d_mat3_from_euler16
    lea ix,ix-p3d_object_orientation
    ld iy,object_packet
    jp p3d_object_sync16

init_party_objects:
; The two coarse Euler components produce a stable 23.69-degree obliquity.
; Local +Y (the north-pole axis) points toward world -X and +Z: screen-left
; and toward the camera. Persistent local-Y spin therefore remains axial.
    ld ix,earth_state
    ld iy,earth_config
    call init_party_object

; Each orbiter starts on a cardinal point with local -Z tangent to the track.
; Rotation precedes translation in p3d_object_step16. A +256 yaw and -123
; forward step close every pose byte after 128 ticks (4.267 seconds), while
; the integer radius remains 2500.0..2516.1.
    ld ix,crash_state
    ld iy,crash_config
    call init_party_object
    ld ix,lara_state
    ld iy,lara_config
    call init_party_object
    ld ix,heavytank_state
    ld iy,heavytank_config
    call init_party_object
    ld ix,airliner_state
    ld iy,airliner_config
    call init_party_object
    ret

; Advance every autonomous body once per fixed quantum. Nonzero persistent
; velocity makes this independent of keyboard state and render cadence.
simulate_party_step:
    call simulate_earth_spin
    ld ix,crash_state
    call p3d_object_step16
    ld ix,lara_state
    call p3d_object_step16
    ld ix,heavytank_state
    call p3d_object_step16
    ld ix,airliner_state
    jp p3d_object_step16

; Spin Earth from a fixed tilted basis rather than repeatedly round-tripping
; that basis through coarse Euler words. The ordinary object step is exact for
; the pure-Y orbiters, but its intentional matrix/Euler reconciliation would
; slowly precess a compound tilted axis. The retained angular velocity still
; owns the rate; setting it to zero stops this integrator.
simulate_earth_spin:
    ld ix,earth_state
    ld e,(ix+p3d_object_local_angular_velocity+p3d_vec3_y)
    ld d,(ix+p3d_object_local_angular_velocity+p3d_vec3_y+1)
    ld a,d
    or e
    ret z
    ld a,(earth_spin_phase)
    ld l,a
    ld a,(earth_spin_phase+1)
    ld h,a
    add.s hl,de
    ld a,l
    ld (earth_spin_phase),a
    ld a,h
    ld (earth_spin_phase+1),a
    push hl

; Restore the immutable obliquity matrix, then apply the complete accumulated
; local-Y phase in one operation. This prevents time-dependent axis drift.
    ld hl,earth_base_orientation
    ld de,earth_state+p3d_object_orientation
    ld bc,p3d_mat3_size
    ldir
    pop hl
    ld ix,earth_state+p3d_object_orientation
    call p3d_mat3_rotate_local_y16
    ret c
    ld iy,earth_state+p3d_object_pingo_rotation
    call p3d_mat3_to_euler16
    ret c
    ld ix,earth_state
    ld a,(ix+p3d_object_dirty)
    or p3d_object_dirty_rotation
    ld (ix+p3d_object_dirty),a
    or a
    ret

; Return A nonzero when any object has an unsent absolute pose component.
scene_pose_dirty:
    ld ix,object_state
    ld a,(ix+p3d_object_dirty)
    and p3d_object_dirty_pose
    ld b,a
    ld ix,earth_state
    ld a,(ix+p3d_object_dirty)
    and p3d_object_dirty_pose
    or b
    ld b,a
    ld ix,crash_state
    ld a,(ix+p3d_object_dirty)
    and p3d_object_dirty_pose
    or b
    ld b,a
    ld ix,lara_state
    ld a,(ix+p3d_object_dirty)
    and p3d_object_dirty_pose
    or b
    ld b,a
    ld ix,heavytank_state
    ld a,(ix+p3d_object_dirty)
    and p3d_object_dirty_pose
    or b
    ld b,a
    ld ix,airliner_state
    ld a,(ix+p3d_object_dirty)
    and p3d_object_dirty_pose
    or b
    ret

; Coalesce and emit all pending absolute commands while the renderer is idle.
sync_scene_objects:
    ld iy,object_packet
    ld ix,object_state
    call p3d_object_sync16
    ld ix,earth_state
    call p3d_object_sync16
    ld ix,crash_state
    call p3d_object_sync16
    ld ix,lara_state
    call p3d_object_sync16
    ld ix,heavytank_state
    call p3d_object_sync16
    ld ix,airliner_state
    jp p3d_object_sync16

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
    call simulate_party_step
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
sid: equ 1362
tgtbmid: equ 257

jet_mid: equ 1
jet_oid: equ 1
jet_bmid: equ 256
earthuv_mid: equ 2
earthuv_oid: equ 2
earthuv_bmid: equ 258
crash_mid: equ 3
crash_oid: equ 3
crash_bmid: equ 259
lara_mid: equ 4
lara_oid: equ 4
lara_bmid: equ 260
heavytank_mid: equ 5
heavytank_oid: equ 5
heavytank_bmid: equ 261
airliner_mid: equ 6
airliner_oid: equ 6
airliner_bmid: equ 262

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

earth_x: equ 0
earth_y: equ 0
earth_z: equ -4200
earth_scale: equ 1280
earth_tilt_x: equ 1536
earth_tilt_z: equ 1536
earth_spin_step: equ 128

orbit_center_z: equ earth_z
orbit_radius: equ 2500
orbiter_scale: equ 896
orbit_forward_step: equ -123
orbit_yaw_step: equ 256

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
    dw sid,jet_oid,jet_mid,jet_bmid

earth_config:
    dw sid,earthuv_oid,earthuv_mid,earthuv_bmid
    dw earth_x,earth_y,earth_z
    dw earth_tilt_x,0,earth_tilt_z
    dw earth_scale
    dw 0,0,0
    dw 0,earth_spin_step,0

crash_config:
    dw sid,crash_oid,crash_mid,crash_bmid
    dw 0,0,orbit_center_z+orbit_radius
    dw -16384,-8064,-16384
    dw orbiter_scale
    dw 0,0,orbit_forward_step
    dw 0,orbit_yaw_step,0

lara_config:
    dw sid,lara_oid,lara_mid,lara_bmid
    dw orbit_radius,0,orbit_center_z
    dw 0,-128,0
    dw orbiter_scale
    dw 0,0,orbit_forward_step
    dw 0,orbit_yaw_step,0

heavytank_config:
    dw sid,heavytank_oid,heavytank_mid,heavytank_bmid
    dw 0,0,orbit_center_z-orbit_radius
    dw 0,8064,0
    dw orbiter_scale
    dw 0,0,orbit_forward_step
    dw 0,orbit_yaw_step,0

airliner_config:
    dw sid,airliner_oid,airliner_mid,airliner_bmid
    dw -orbit_radius,0,orbit_center_z
    dw -16384,128,-16384
    dw orbiter_scale
    dw 0,0,orbit_forward_step
    dw 0,orbit_yaw_step,0

; Coarse phase-aligned Rz(1536)*Rx(1536) basis. Its local +Y column is
; (-9102,30006,9512): screen-left, mostly up, and toward the camera.
earth_base_orientation:
    dw 31356,-9102,2761
    dw 9512,30006,-9102
    dw 0,9512,31356

object_state:
    ds p3d_object_size
earth_state:
    ds p3d_object_size
crash_state:
    ds p3d_object_size
lara_state:
    ds p3d_object_size
heavytank_state:
    ds p3d_object_size
airliner_state:
    ds p3d_object_size

object_packet:
    ds p3d_pingo_update_packet_size

camera_state:
    ds p3d_camera_size

simulation_accumulator:
    dl 0

simulation_steps_remaining:
    db 0

earth_spin_phase:
    dw 0

filedata:
; MOS loads the model texture beginning at this final address.
