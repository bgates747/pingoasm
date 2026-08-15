; Syntax/width harness for fixtures/_common/aircraft-view.inc.
    .assume adl=1
    .org 040000h
    jp start

p3d_vec3_size: equ 6
p3d_mat3_size: equ 18
p3d_object_world_position: equ 10
p3d_object_pingo_rotation: equ 16
p3d_object_orientation: equ 28
p3d_object_size: equ 64
p3d_camera_dirty: equ 0
p3d_camera_look_flags: equ 1
p3d_camera_world_position: equ 4
p3d_camera_pingo_rotation: equ 10
p3d_camera_orientation: equ 16
p3d_camera_size: equ 36
p3d_camera_dirty_position: equ 1
p3d_camera_dirty_rotation: equ 2
p3d_camera_roll_upright: equ 0

start:
    call aircraft_view_init
    call aircraft_view_handle_toggle
    call aircraft_view_update_camera
    ret

    include "../fixtures/_common/aircraft-view.inc"

; Arithmetic is already qualified in agon/3d.inc; only call resolution matters
; in this small include-syntax harness.
p3d_mat3_mul_vec3_16:
    or a
    ret
p3d_vec3_translate16:
    or a
    ret
p3d_camera_aim_at_point16:
    or a
    ret

object_state:
    ds p3d_object_size
camera_state:
    ds p3d_camera_size
keyboard_masks:
    ds 16
