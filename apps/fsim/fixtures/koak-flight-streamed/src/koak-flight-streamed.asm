; KOAK 28L light-flight fixture with position-driven regional terrain.

mos_getkey: equ 00h
mos_load: equ 01h
mos_sysvars: equ 08h
mos_getkbmap: equ 1Eh
mos_setkbvector: equ 1Dh
sysvar_time: equ 00h
sysvar_gp: equ 037h
    MACRO MOSCALL function
        ld a,function
        rst.lil 08h
    ENDMACRO

sid: equ 1731
tgtbmid: equ 257
terrain_bmid: equ 256
airport_bmid: equ 259
aircraft_bmid: equ 260
aircraft_mesh_id: equ 201
aircraft_object_id: equ 201
p3dm_stage_buffer_id: equ 07400h
p3dm_mirror_z_on_load: equ 0

viewport_width: equ 320
viewport_height: equ 148
viewport_x: equ 0
viewport_y: equ 0
simulation_step_ticks: equ 4
simulation_max_steps_per_pass: equ 4
simulation_max_backlog_ticks: equ 32

; These values avoid a transient Berkeley trim before the explicit KOAK state
; initializes the same reference point and runway support policy.
obj_initial_x: equ 3088
obj_initial_y: equ 44
obj_initial_z: equ 2181
obj_ground_y: equ 44
obj_scale: equ 256

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
    pop iy
    pop ix
    pop de
    pop bc
    pop af
    ld hl,0
    ret

; Qualified client-side components are reused by include, never copied into or
; edited inside the visually accepted Berkeley fixture.
    include "../../berkeley-flight-fdm/src/input.inc"
    include "../../berkeley-flight-fdm/src/timer.inc"
    include "../../berkeley-flight-fdm/src/vdu_pingo.inc"
    include "../../berkeley-flight-fdm/src/agon/3d.inc"
    include "../../berkeley-flight-fdm/src/agon/3d_sincos_table.inc"
    include "../../berkeley-flight-fdm/src/flight-input.inc"
    include "flight-backdrop.inc"
    include "../../berkeley-flight-fdm/src/cockpit.inc"
    include "../../berkeley-flight-fdm/src/render-async.inc"
    include "streaming-vdu.inc"
    include "../../p3dm-loader-probe/src/p3dm-loader.inc"
    include "../../_common/aircraft-view.inc"
    include "../../../build/aircraft/pingoasm-jet/jet-view.inc"
    include "regional-streaming.inc"
    include "streaming-scene.inc"

main:
    ld hl,title
    call printString
    call load_scene_resources
    CTB2 tgtbmid,viewport_width,viewport_height
    CCS sid,viewport_width,viewport_height
    call pingo_bind_flat_pattern_library
    call streaming_establish_scene_slots

; Morning light from due east makes the hills' west faces visibly darker.
    ld bc,0
    ld de,16384
    ld iy,-28377
    call pingo_set_light_direction
    ld a,95
    call pingo_set_ambient_light

    ld a,8+128
    call vdu_set_screen_mode
    xor a
    call vdu_set_scaling
    call cockpit_init
    call cursor_off

    call flight_model_init
    call koak_flight_initial_state
    call initialize_koak_camera
    call streaming_initialize

; Create the retained exterior object at its real scale and pose, then hide it
; before the first cockpit render. It will never need to be recreated.
    call sync_aircraft_state
    ld hl,aircraft_object_id
    xor a
    call pingo_set_object_active
    xor a
    ld (aircraft_view_visibility_dirty),a

; Current terrain plus paired KOAK pavement/markings are a hard startup gate.
; Both airport objects remain inactive on either component failure.
    call streaming_load_startup
    jp nz,@startup_failed
    call sync_camera_state

    MOSCALL mos_sysvars
    ld (sysvars_pointer),ix ; ADL24 OK: native MOS sysvars pointer
    call wait_for_setup_barrier
    call initialize_simulation_clock
    call reset_keys
    call initialize_render_state
    call install_render_callback
    call enable_render_notifications
    ei
    xor a
    ld (streaming_scene_dirty),a
    call submit_current_render

@loop:
    call set_keys
    call latch_exit_request
    ld a,(exit_requested)
    or a
    jr nz,@service
    call accumulate_simulation_time
    call run_simulation_batch
@service:
    ld a,(completion_ready)
    or a
    call nz,consume_render_completion
    ld a,(render_in_flight)
    or a
    jr nz,@loop
    ld a,(exit_requested)
    or a
    jr nz,@exit

; Rendering is idle here. Service at most one disk component, then publish
; pose, camera and visibility in the order required by cockpit/chase changes.
    call streaming_service_one
    call publish_render_idle_state
    xor a
    ld (streaming_scene_dirty),a
    call submit_current_render
    jr @loop

@exit:
    call disable_render_notifications
    call remove_render_callback
    xor a
    call vdu_set_screen_mode
    ld a,1
    call vdu_set_scaling
    call cursor_on
    ret

@startup_failed:
    ld (startup_error),a
    xor a
    call vdu_set_screen_mode
    ld a,1
    call vdu_set_scaling
    call cursor_on
    ld hl,startup_failure_text
    call printString
    ld a,(startup_error)
    call print_hex_byte
    call printNewLine
    ret

load_scene_resources:
    ld hl,pingo_flat_patterns_buffer_id
    ld ix,pingo_flat_patterns_bytes
    ld iy,terrain_patterns_file
    call vdu_load_buffer_from_file
    ld hl,pingo_flat_patterns_buffer_id
    call vdu_consolidate_buffer
    ld hl,pingo_flat_lookup_buffer_id
    ld ix,pingo_flat_lookup_bytes
    ld iy,terrain_pattern_lookup_file
    call vdu_load_buffer_from_file
    ld hl,pingo_flat_lookup_buffer_id
    call vdu_consolidate_buffer

    ld bc,4
    ld de,4
    ld hl,terrain_bmid
    ld ix,16
    ld iy,terrain_texture
    ld a,1
    call vdu_load_img
    ld bc,8
    ld de,8
    ld hl,airport_bmid
    ld ix,64
    ld iy,airport_texture
    ld a,1
    call vdu_load_img
    ld bc,aircraft_jet_texture_width
    ld de,aircraft_jet_texture_height
    ld hl,aircraft_bmid
    ld ix,aircraft_jet_texture_size
    ld iy,aircraft_jet_texture
    ld a,1
    call vdu_load_img
    jp cockpit_load

initialize_koak_camera:
    ld ix,camera_state
    ld iy,camera_initial_position
    ld hl,sid
    call p3d_camera_init16
    jp aircraft_view_init

sync_aircraft_state:
    ld ix,object_state
    ld iy,object_packet
    jp p3d_object_sync16

publish_render_idle_state:
    ld a,(aircraft_view_mode)
    or a
    call nz,sync_aircraft_state
    call sync_camera_state
    ld a,(aircraft_view_visibility_dirty)
    or a
    ret z
    ld hl,aircraft_object_id
    ld a,(aircraft_view_aircraft_active)
    call pingo_set_object_active
    xor a
    ld (aircraft_view_visibility_dirty),a
    ld a,1
    ld (streaming_scene_dirty),a
    ret

sync_camera_state:
    ld ix,camera_state
    bit 0,(ix+p3d_camera_dirty)
    jr z,@rotation
    ld c,(ix+p3d_camera_world_position+0)
    ld b,(ix+p3d_camera_world_position+1)
    ld e,(ix+p3d_camera_world_position+2)
    ld d,(ix+p3d_camera_world_position+3)
    ld l,(ix+p3d_camera_world_position+4)
    ld h,(ix+p3d_camera_world_position+5)
    push hl
    pop iy
    push ix
    call scdabs
    pop ix
    res 0,(ix+p3d_camera_dirty)
@rotation:
    bit 1,(ix+p3d_camera_dirty)
    ret z
    ld c,(ix+p3d_camera_pingo_rotation+0)
    ld b,(ix+p3d_camera_pingo_rotation+1)
    ld e,(ix+p3d_camera_pingo_rotation+2)
    ld d,(ix+p3d_camera_pingo_rotation+3)
    ld l,(ix+p3d_camera_pingo_rotation+4)
    ld h,(ix+p3d_camera_pingo_rotation+5)
    push hl
    pop iy
    push ix
    call scrabs
    pop ix
    res 1,(ix+p3d_camera_dirty)
    ret

initialize_simulation_clock:
    call timestamp_tick
    ld hl,0
    ld (simulation_accumulator),hl ; ADL24 OK: exact dl accumulator
    ret

accumulate_simulation_time:
    call timestamp_tick
    ld de,(simulation_accumulator) ; ADL24 OK: exact dl accumulator
    add hl,de
    ld de,simulation_max_backlog_ticks+1
    or a
    sbc hl,de
    jr c,@below
    ld hl,simulation_max_backlog_ticks
    ld (simulation_accumulator),hl ; ADL24 OK: exact dl accumulator
    ret
@below:
    add hl,de
    ld (simulation_accumulator),hl ; ADL24 OK: exact dl accumulator
    ret

run_simulation_batch:
    ld a,simulation_max_steps_per_pass
    ld (simulation_steps_remaining),a
@next:
    call take_simulation_step
    ret c
    call flight_model_step
    jr c,@arithmetic_failure
    call streaming_rebase_flight
    call aircraft_view_handle_toggle
    call aircraft_view_update_camera
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
@arithmetic_failure:
    ld a,1
    ld (exit_requested),a
    ret

take_simulation_step:
    ld hl,(simulation_accumulator) ; ADL24 OK: exact dl accumulator
    ld de,simulation_step_ticks
    or a
    sbc hl,de
    ret c
    ld (simulation_accumulator),hl ; ADL24 OK: exact dl accumulator
    or a
    ret

latch_exit_request:
    ld ix,keyboard_masks
    bit 0,(ix+14)
    ret z
    ld a,1
    ld (exit_requested),a
    ret

; A -> two uppercase hexadecimal digits. Useful when startup fails on hardware.
print_hex_byte:
    push af
    rra
    rra
    rra
    rra
    and 0fh
    call print_hex_nibble
    pop af
    and 0fh
print_hex_nibble:
    add a,'0'
    cp '9'+1
    jr c,@emit
    add a,'A'-'9'-1
@emit:
    rst.lil 10h
    ret

title:
    db "KOAK 28L streamed flight: W/S throttle, arrows pitch/roll, A/D rudder, V view",13,10,0
startup_failure_text:
    db "P3DM startup error ",0

object_ids: dw sid,aircraft_object_id,aircraft_mesh_id,aircraft_bmid
camera_initial_position: dw 3106,64,2226
object_state: ds p3d_object_size
camera_state: ds p3d_camera_size
object_packet: ds p3d_pingo_update_packet_size
simulation_accumulator: dl 0
simulation_steps_remaining: db 0
startup_error: db 0

terrain_texture: db "MATID.RG2",0
terrain_patterns_file: db "PATTERN.RG2",0
terrain_pattern_lookup_file: db "PATLUT.BIN",0
airport_texture: db "APT/SOLID64.RG2",0
cockpit_file: db "PANEL.RG2",0

; MOS resource loading must be the final application address. Nothing may be
; assembled after this label because the largest resource overwrites onward.
filedata:
