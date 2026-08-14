; Marina regular-hierarchy survey: regional client of the universal manager.

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

; Universal-manager policy.  This client supplies no flight dynamics,
; collision, aircraft, or non-terrain scenery assumptions.
; Slots 0..90 retain the qualified radius-five TRH/L0 hash.  The hierarchy
; plan owns 91..254 dynamically: no legal plan needs more than 159 coarse
; leaves, leaving five protected replacement slots at the proven 250-object
; maximum.
terrain_manager_slot_count: equ 255
terrain_manager_max_ring: equ 5
terrain_manager_initial_ring: equ 5
terrain_manager_mesh_id_base: equ 1
terrain_manager_object_id_base: equ 1

; Command 53 carries the complete unsigned word.  At the terrain convention of
; eight metres per Pingo unit this is about 524 km; resident rings and later
; LOD policy, rather than the projection plane, still bound submitted geometry.
manager_survey_projection_far_units: equ 65535

manager_survey_slot_count: equ terrain_manager_slot_count
manager_survey_default_radius: equ terrain_manager_initial_ring
manager_survey_mesh_base: equ terrain_manager_mesh_id_base
manager_survey_object_base: equ terrain_manager_object_id_base

; Preserve the visually reviewed Berkeley Marina pose, but express it in its
; actual containing cell so the first manager publication needs no corrective
; origin rebase.  The view is 500 m above the source datum, facing almost due
; south and pitched down twenty degrees.
manager_survey_start_q: equ 80
manager_survey_start_r: equ 125
camera_initial_x: equ 4275
camera_initial_y: equ 8000
camera_initial_z: equ 466
camera_initial_pitch: equ -1820
camera_initial_yaw: equ 8192

; The complete TRH/RGL corpora use the provider's true Bay Area q/r bounds. The
; historical Campanile and Marina extractions remain separate build artifacts,
; but no experimental disk fence limits this regional viewer.
hex_provider_fixture_bounds_enabled: equ 0
hex_provider_fixture_center_q: equ manager_survey_start_q
hex_provider_fixture_center_r: equ manager_survey_start_r
hex_provider_fixture_radius: equ 5
hex_provider_natural_namespace: equ 1

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
    include "../../../fixtures/_common/pingo-wide-translation.inc"
    include "../../../fixtures/_common/pingo-projection.inc"
    include "terrain-manager-scene.inc"
    include "terrain-manager-controls.inc"
    include "../../../build/p3dm/bay-area-regular-n1-hierarchy/REGCORP.INC"
    include "../../terrain-manager-regular-lod-survey/tgt/regular-lod-runtime.inc"
    include "terrain-manager-regular-lod-provider.inc"
    include "../../../runtime/ez80/terrain-manager.inc"

main:
    ld hl,title
    call printString
    call load_scene_resources
    CTB2 tgtbmid,viewport_width,viewport_height
    CCS sid,viewport_width,viewport_height
    ld hl,manager_survey_projection_far_units
    call pingo_set_projection_far_units
    call pingo_bind_flat_pattern_library
    call manager_survey_establish_scene_slots

; Preserve the visually qualified regional-survey illumination.
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
    call initialize_regional_camera_attitude
    call manager_survey_initialize_radius_controls
    call terrain_manager_initialize
    jp c,@startup_failed
    ld bc,manager_survey_start_q
    ld de,manager_survey_start_r
    call terrain_manager_submit_origin
    jp c,@startup_failed
    ld a,manager_survey_default_radius
    call terrain_manager_set_ring
    jp c,@startup_failed
    call terrain_provider_prepare_plan
    jp c,@startup_failed

; Ordinal zero is the centre cell, providing one bounded first-frame barrier.
; Every other member of the selected disk is serviced between renders.
    call terrain_manager_service_idle
    jp c,@startup_failed
    call sync_camera_state

    MOSCALL mos_sysvars
    ld (sysvars_pointer),ix             ; ADL24 OK: native MOS sysvars pointer
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
    call manager_survey_update_radius_keys
    call manager_survey_apply_radius_request
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

; The manager alone owns reposition, one bounded publication/deactivation,
; activation order, retry state, and stable residency between renders.
    call terrain_manager_service_idle
    call sync_camera_state
    call submit_current_render
    jr @loop

@exit:
    call terrain_manager_shutdown_idle
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
    call terrain_manager_shutdown_idle
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

manager_survey_apply_radius_request:
    ld a,(manager_survey_radius_pending)
    or a
    ret z
    xor a
    ld (manager_survey_radius_pending),a
    ld a,(manager_survey_radius_request)
    call terrain_manager_set_ring
    ret c
    call terrain_provider_prepare_plan
    ret c
; Ring-only refinement changes have the same ancestor/descendant retirement
; requirement as an origin change.  Reuse the manager's render-idle rebase
; phase so every stale parent is inactive before a replacement is published.
    ld a,1
    ld (terrain_manager_origin_dirty),a
    xor a
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

; The shared camera-control include deliberately defaults to a zero Euler
; pose.  This fixture then installs its reviewed regional attitude and rebuilds
; the retained no-roll orientation before the first terrain publication.
initialize_regional_camera_attitude:
    ld hl,camera_initial_pitch
    SURVEY_STORE_HL camera_state+p3d_camera_pingo_rotation+p3d_vec3_x
    ld hl,camera_initial_yaw
    SURVEY_STORE_HL camera_state+p3d_camera_pingo_rotation+p3d_vec3_y
    xor a
    ld (camera_state+p3d_camera_pingo_rotation+p3d_vec3_z),a
    ld (camera_state+p3d_camera_pingo_rotation+p3d_vec3_z+1),a
    ld ix,camera_state+p3d_camera_orientation
    ld iy,camera_state+p3d_camera_pingo_rotation
    call p3d_camera_mat3_from_euler_fine16
    ld ix,camera_state
    ld a,(ix+p3d_camera_dirty)
    or p3d_camera_dirty_rotation
    ld (ix+p3d_camera_dirty),a
    jp sync_camera_state

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
    ld (simulation_accumulator),hl      ; ADL24 OK: exact dl accumulator
    ret

accumulate_simulation_time:
    call timestamp_tick
    ld de,(simulation_accumulator)      ; ADL24 OK: exact dl accumulator
    add hl,de
    ld de,simulation_max_backlog_ticks+1
    or a
    sbc hl,de
    jr c,@below
    ld hl,simulation_max_backlog_ticks
    ld (simulation_accumulator),hl      ; ADL24 OK: exact dl accumulator
    ret
@below:
    add hl,de
    ld (simulation_accumulator),hl      ; ADL24 OK: exact dl accumulator
    ret

run_simulation_batch:
    ld a,simulation_max_steps_per_pass
    ld (simulation_steps_remaining),a
@next:
    call take_simulation_step
    ret c
    call simulate_camera_step
    ld ix,camera_state
    call terrain_manager_update_position
    call nz,terrain_provider_prepare_plan
    call reset_keys
    call set_keys
    call latch_exit_request
    call manager_survey_update_radius_keys
    call manager_survey_apply_radius_request
    ld a,(exit_requested)
    or a
    ret nz
    ld hl,simulation_steps_remaining
    dec (hl)
    jr nz,@next
    ret

take_simulation_step:
    ld hl,(simulation_accumulator)      ; ADL24 OK: exact dl accumulator
    ld de,simulation_step_ticks
    or a
    sbc hl,de
    ret c
    ld (simulation_accumulator),hl      ; ADL24 OK: exact dl accumulator
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
    db "Marina hierarchy: TRH N5 near, regular L1/L2/L4/L8 far; arrows look, WASD move, PgUp/PgDn rise/fall",13,10,0
startup_failure_text:
    db "Regular hierarchy terrain manager startup error ",0

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
