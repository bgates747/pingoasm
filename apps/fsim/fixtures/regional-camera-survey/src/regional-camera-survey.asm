; Full-region, no-dynamics camera survey over loose Bay Area P3DM terrain.

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
p3dm_stage_buffer_id: equ 07400h

viewport_width: equ 320
viewport_height: equ 240
viewport_x: equ 0
viewport_y: equ 0

simulation_step_ticks: equ 4
simulation_max_steps_per_pass: equ 4
simulation_max_backlog_ticks: equ 32
survey_angular_rate_128: equ 4864
survey_angular_step: equ survey_angular_rate_128 >> 5
survey_pitch_limit: equ 8191
survey_translation_rate_min: equ 8
survey_translation_rate_initial: equ 32
survey_translation_rate_max: equ 256

; Exact accepted Campanile profile witness in the regional grid.  X/Z are
; local floating-origin coordinates; Y remains absolute NAVD88 elevation.
regional_start_tile_x: equ 85
regional_start_tile_y: equ 179
regional_frame_z_bias: equ 12288
camera_initial_x: equ -1857
camera_initial_y: equ 3496
camera_initial_z_canonical: equ 3638
camera_initial_z: equ camera_initial_z_canonical+regional_frame_z_bias

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

    include "../../berkeley-flight-triangular-dither/src/input.inc"
    include "../../berkeley-flight-triangular-dither/src/timer.inc"
    include "../../berkeley-flight-triangular-dither/src/vdu_pingo.inc"
    include "../../berkeley-flight-triangular-dither/src/agon/3d.inc"
    include "../../berkeley-flight-triangular-dither/src/agon/3d_sincos_table.inc"
    include "../../berkeley-flight-triangular-dither/src/camera-survey-input.inc"
    include "../../koak-flight-streamed/src/flight-backdrop.inc"
    include "../../berkeley-flight-fdm/src/render-async.inc"
    include "../../koak-flight-streamed/src/streaming-vdu.inc"
    include "../../p3dm-loader-probe/src/p3dm-loader.inc"
    include "regional-camera-streaming.inc"
    include "regional-camera-scene.inc"

main:
    ld hl,title
    call printString
    call load_scene_resources
    CTB2 tgtbmid,viewport_width,viewport_height
    CCS sid,viewport_width,viewport_height
    call pingo_bind_flat_pattern_library
    call regional_establish_scene_slots

; Match the accepted dithered Berkeley lighting control.
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
    call app_special_init
    call init_camera_survey
    call regional_streaming_initialize
    call regional_streaming_load_startup
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

; Disk I/O and mesh publication occur only between completed renders.  One
; absent component is serviced per pass; resident geometry remains active
; until its complete replacement has passed validation and CRC.
    call regional_streaming_service_one
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
    jp vdu_load_img

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
    call simulate_camera_step
    call regional_streaming_rebase_camera
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

app_special_init:
    call vdu_clg
    call vdu_flip
    call vdu_clg
    call cursor_off
    ret

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
    db "Bay Area camera survey: arrows look, WASD move, PgUp/PgDn rise/fall, -/= speed",13,10,0
startup_failure_text:
    db "Regional P3DM startup error ",0

camera_initial_position:
    dw camera_initial_x,camera_initial_y,camera_initial_z
camera_state: ds p3d_camera_size
survey_translation_delta: ds p3d_vec3_size
survey_translation_rate: dw 0
survey_speed_keys_down: db 0
survey_rotation_changed: db 0
simulation_accumulator: dl 0
simulation_steps_remaining: db 0
startup_error: db 0

terrain_texture: db "MATID.RG2",0
terrain_patterns_file: db "PATTERN.RG2",0
terrain_pattern_lookup_file: db "PATLUT.BIN",0

; MOS resource staging must remain beyond every live program datum.
filedata:
