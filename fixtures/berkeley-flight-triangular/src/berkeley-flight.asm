; Self-lit triangular-lattice Berkeley free-flight fixture.

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

    include "input.inc"
    include "timer.inc"
    include "vdu_pingo.inc"
    include "agon/3d.inc"
    include "agon/3d_sincos_table.inc"
    include "flight-input.inc"
    include "render-async.inc"

waitKeypress:
    MOSCALL mos_getkey
    ret

    MACRO OT SID, OID, X, Y, Z
        ld hl,@beg
        ld bc,@end-@beg
        rst.lil 18h
        jp @end
@beg:
        db 23,0,0A0h
        dw SID
        db 49h,17
        dw OID,X,Y,Z
@end:
    ENDMACRO

main:
    ld hl,title
    call printString
    ld bc,8
    ld de,8
    ld hl,terrain_bmid
    ld ix,64
    ld iy,terrain_texture
    ld a,1
    call vdu_load_img
    CTB2 tgtbmid,viewport_width,viewport_height
    CCS sid,viewport_width,viewport_height
    call terrain_load_meshes
    call terrain_create_objects
; Due-east sun, 30 degrees above the horizon. In this terrain frame +Y is up
; and -Z is east: (0, sin(30), -cos(30)) in signed Q15 ratios.
    ld bc,0
    ld de,16384
    ld iy,-28377
    call pingo_set_light_direction
; Pingo light unity is 127; 95 is the nearest encoded 75 percent ambient.
    ld a,95
    call pingo_set_ambient_light
    call waitKeypress
    ld a,8+128
    call vdu_set_screen_mode
    xor a
    call vdu_set_scaling
    call app_special_init
    call init_object_state
    call init_flight_camera
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
    ld ix,camera_state
    ld a,(ix+p3d_camera_dirty)
    and p3d_camera_dirty_all
    jr z,@loop
    call sync_camera_state
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

init_flight_camera:
    ld ix,camera_state
    ld iy,camera_initial_position
    ld hl,sid
    call p3d_camera_init16
    call copy_flight_to_camera
    jp sync_camera_state

copy_flight_to_camera:
    ld ix,object_state
    ld iy,camera_state
    ld bc,6
    lea hl,ix+p3d_object_world_position
    lea de,iy+p3d_camera_world_position
    ldir
    ld bc,6
    lea hl,ix+p3d_object_pingo_rotation
    lea de,iy+p3d_camera_pingo_rotation
    ldir
    ld a,(iy+p3d_camera_dirty)
    or p3d_camera_dirty_all
    ld (iy+p3d_camera_dirty),a
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
    ld (simulation_accumulator),hl
    ret
accumulate_simulation_time:
    call timestamp_tick
    ld de,(simulation_accumulator)
    add hl,de
    ld de,simulation_max_backlog_ticks+1
    or a
    sbc hl,de
    jr c,@below
    ld hl,simulation_max_backlog_ticks
    ld (simulation_accumulator),hl
    ret
@below:
    add hl,de
    ld (simulation_accumulator),hl
    ret
run_simulation_batch:
    ld a,simulation_max_steps_per_pass
    ld (simulation_steps_remaining),a
@next:
    call take_simulation_step
    ret c
    call simulate_object_step
    call copy_flight_to_camera
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
app_special_init:
    call vdu_clg
    call vdu_flip
    call vdu_clg
    call cursor_off
    ret

title: db "Berkeley triangular terrain (self-lit): W/S throttle, arrows pitch/roll, A/D yaw",13,10,"Press any key.",13,10,0
sid: equ 1731
tgtbmid: equ 257
terrain_bmid: equ 256
viewport_width: equ 320
viewport_height: equ 240
viewport_x: equ 0
viewport_y: equ 0
simulation_step_ticks: equ 4
simulation_max_steps_per_pass: equ 4
simulation_max_backlog_ticks: equ 32
object_linear_rate_128: equ 352
object_angular_rate_128: equ 4864
object_linear_step: equ object_linear_rate_128 >> 5
object_angular_step: equ object_angular_rate_128 >> 5
object_air_speed_limit: equ 255
obj_scale: equ 256
obj_initial_x: equ 0
obj_initial_y: equ -1144
obj_initial_z: equ 16384
object_ids: dw sid,0,0,0
camera_initial_position: dw obj_initial_x,obj_initial_y,obj_initial_z
object_state: ds p3d_object_size
camera_state: ds p3d_camera_size
object_packet: ds p3d_pingo_update_packet_size
simulation_accumulator: dl 0
simulation_steps_remaining: db 0
terrain_texture: db "terrain-palette.rgba2",0
    include "terrain-scene.inc"

; MOS texture staging must be the final application address. Placing generated
; code or mesh data after this label lets mos_load overwrite it.
filedata:
