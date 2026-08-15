; Experimental Marina regular-hierarchy sibling with an AgonDev C policy seam.

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
; Correct the legacy reflected disk corpus to right-handed Z=+east while it is
; in the validated host staging window, before publication to Pingo.
p3dm_mirror_z_on_load: equ 1

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
; Keep the preceding plan visible until every desired replacement is active.
; The regular provider has a proven one-cell placement fringe for this handoff.
terrain_manager_defer_stale_rebase: equ 1
; The accepted regular fixture uses full-owner coverage-group staging.
; scripts/build_regular_lod_group_scratch.py --group-staging 0 preserves the
; byte-exact inactive-first policy as an isolated rollback build.
terrain_manager_group_staging: equ 1
; The accepted appliance keeps the qualified assembly selector byte-for-byte.
; A separately named sibling fixture overrides both constants and includes the
; fixed-address AgonDev policy client without changing P3DRGL.BIN.
terrain_manager_regular_policy_client: equ 1
terrain_manager_regular_policy_mode: equ 2
    include "../../../build/experiments/agondev-regular-policy/regular-policy-import.inc"
    include "terrain-manager-regular-lod-policy-mode-c-guarded.inc"

; Command 53 carries the complete unsigned word.  At the terrain convention of
; eight metres per Pingo unit this is about 524 km; resident rings and later
; LOD policy, rather than the projection plane, still bound submitted geometry.
manager_survey_projection_far_units: equ 65535

manager_survey_slot_count: equ terrain_manager_slot_count
manager_survey_default_radius: equ terrain_manager_initial_ring
manager_survey_mesh_base: equ terrain_manager_mesh_id_base
manager_survey_object_base: equ terrain_manager_object_id_base

; Preserve the reviewed Berkeley Marina position, but express it in its
; actual containing cell so the first manager publication needs no corrective
; origin rebase.  The view is 500 m above the source datum, level, and facing
; almost due north.  Roll is explicitly zeroed by the attitude initializer.
manager_survey_start_q: equ 80
manager_survey_start_r: equ 125
camera_initial_x: equ 4275
camera_initial_y: equ 8000
camera_initial_z: equ -466
camera_initial_pitch: equ 0
camera_initial_yaw: equ -8192

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
    include "terrain-manager-solid-sky.inc"
    include "../../berkeley-flight-fdm/src/render-async.inc"
    include "../../koak-flight-streamed/src/streaming-vdu.inc"
    include "../../p3dm-loader-probe/src/p3dm-loader.inc"
    include "../../../fixtures/_common/pingo-wide-translation.inc"
    include "../../../fixtures/_common/pingo-projection.inc"
    include "terrain-manager-scene.inc"
    include "terrain-manager-controls.inc"
    include "../../../build/p3dm/bay-area-regular-n1-hierarchy/REGCORP.INC"
    include "../../terrain-manager-regular-lod-survey/tgt/regular-lod-runtime.inc"
.if terrain_manager_group_staging
    include "../../terrain-manager-regular-lod-survey/tgt/regular-lod-transitions.inc"
.endif
    include "terrain-manager-regular-lod-provider.inc"
.if terrain_manager_regular_policy_client
    include "terrain-manager-regular-lod-policy-client.inc"
.endif
    include "../../../runtime/ez80/terrain-manager.inc"

main:
    ld hl,title
    call printString
.if terrain_manager_regular_policy_client
    call regular_policy_initialize
.endif
    call load_scene_resources
    CTB2 tgtbmid,viewport_width,viewport_height
    CCS sid,viewport_width,viewport_height
    ld hl,manager_survey_projection_far_units
    call pingo_set_projection_far_units
    call pingo_bind_flat_pattern_library
; Disable the scene illumination multiplier.  Flat-pattern faces therefore
; select the unity band, whose three accepted terrain patterns are solid Agon
; palette pixels rather than dithers.
    call manager_survey_disable_scene_illumination
    call manager_survey_establish_scene_slots

; Retain the light settings as inert scene state so illumination can be
; re-enabled later without rebuilding terrain or changing its material ABI.
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
.if terrain_manager_group_staging
; Radius changes in the unified-slot profile are deliberately cold restarts.
; Apply them only after the completed frame has released the render target;
; the early input/simulation calls merely leave the latest request queued.
    call manager_survey_apply_radius_request
    jr c,@exit
.endif

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
.if terrain_manager_group_staging
; The canonical handoff recipes cover adjacent radius-five moves.  Radius
; changes cannot reconcile arbitrary unified owner slots through the old split
; allocator, so apply every changed request as a render-idle cold fill at the
; current regional origin.  Requests arriving during a group transaction or
; in-flight frame remain queued and coalesce to the latest selected radius.
    call terrain_provider_transition_busy
    or a
    ret nz
    ld a,(render_in_flight)
    or a
    ret nz
    ld a,(manager_survey_radius_request)
    ld b,a
    ld a,(terrain_manager_current_ring)
    cp b
    jr nz,manager_survey_cold_restart_radius
    xor a
    ld (manager_survey_radius_pending),a
    ret
.else
    xor a
    ld (manager_survey_radius_pending),a
    ld a,(manager_survey_radius_request)
    call terrain_manager_set_ring
    ret c
    call terrain_provider_prepare_plan
    ret c
; Ring-only refinement changes have the same ancestor/descendant retirement
; requirement as an origin change. Reuse the manager's render-idle rebase
; phase to reposition the preceding plan; its stale parents remain active until
; every desired replacement has published and activated.
    ld a,1
    ld (terrain_manager_origin_dirty),a
    xor a
    ret
.endif

.if terrain_manager_group_staging
manager_survey_cold_restart_radius:
    ld a,(manager_survey_radius_request)
    cp terrain_manager_max_ring+1
    jr c,@ring_valid
    ld a,terrain_manager_error_ring
    jr @failed
@ring_valid:
    ld (manager_survey_restart_ring),a
    ld a,(terrain_manager_origin_q+0)
    ld (manager_survey_restart_origin_q+0),a
    ld a,(terrain_manager_origin_q+1)
    ld (manager_survey_restart_origin_q+1),a
    ld a,(terrain_manager_origin_r+0)
    ld (manager_survey_restart_origin_r+0),a
    ld a,(terrain_manager_origin_r+1)
    ld (manager_survey_restart_origin_r+1),a

; Shutdown first makes every published object invisible.  Resetting the
; provider then discards its unified owner map before manager initialization
; asks for a cold ring count.  Camera position and attitude live outside both
; state blocks and intentionally survive unchanged.
    call terrain_manager_shutdown_idle
    jr c,@failed
    call terrain_provider_reset_for_cold_restart
    jr c,@failed
    call terrain_manager_initialize
    jr c,@failed
    ld bc,0
    ld a,(manager_survey_restart_origin_q+0)
    ld c,a
    ld a,(manager_survey_restart_origin_q+1)
    ld b,a
    ld de,0
    ld a,(manager_survey_restart_origin_r+0)
    ld e,a
    ld a,(manager_survey_restart_origin_r+1)
    ld d,a
    call terrain_manager_submit_origin
    jr c,@failed
    ld a,(manager_survey_restart_ring)
    call terrain_manager_set_ring
    jr c,@failed
    call terrain_provider_prepare_plan
    jr c,@failed
    xor a
    ld (manager_survey_radius_pending),a
    ret
@failed:
    ld (startup_error),a
    ld a,1
    ld (exit_requested),a
    scf
    ret
.endif

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

; This scene-local wrapper deliberately avoids changing the shared historical
; Pingo transport include and therefore preserves every older fixture binary.
manager_survey_disable_scene_illumination:
    ld hl,@command
    ld bc,@end-@command
    rst.lil 18h
    ret
@command:
    db 23,0,0A0h
    dw sid
    db 49h,46,0
@end:

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
.if terrain_manager_group_staging
    call nz,terrain_provider_begin_transition
.else
    call nz,terrain_provider_prepare_plan
.endif
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
    db "Marina hierarchy C-policy C_GUARDED: TRH N5 near, regular L1/L2/L4/L8 far; arrows look, WASD move, PgUp/PgDn rise/fall",13,10,0
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
.if terrain_manager_group_staging
manager_survey_restart_ring: db manager_survey_default_radius
manager_survey_restart_origin_q: dw 0
manager_survey_restart_origin_r: dw 0
.endif

terrain_texture: db "MATID.RG2",0
terrain_patterns_file: db "PATTERN.RG2",0
terrain_pattern_lookup_file: db "PATLUT.BIN",0

; MOS resource staging must remain beyond every live program datum.
filedata:
