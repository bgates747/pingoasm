; =============================================================================
; Novel apps/anim assembly: sampled rigid-pose playback, controlled locomotion,
; and an eZ80-owned following camera.
;
; Provenance boundary: generic transport, object state, timing, input, and
; P3DR lifecycle are snapshots of apps/earth-party-tex. This file contains the
; new Lara-specific behavior only. Generated geometry and samples live in
; lara-meshes.inc and lara-poses.inc.
; =============================================================================

; ADL warning: LD.S changes the instruction's address/stack mode; it is not a
; harmless 16-bit operand-size suffix. Retained words are transferred one byte
; at a time, following the qualified Earth Party camera implementation.
    macro LARA_LOAD_HL16 address
        ld a,(address)
        ld l,a
        ld a,(address+1)
        ld h,a
    endmacro

    macro LARA_LOAD_DE16 address
        ld a,(address)
        ld e,a
        ld a,(address+1)
        ld d,a
    endmacro

    macro LARA_LOAD_BC16 address
        ld a,(address)
        ld c,a
        ld a,(address+1)
        ld b,a
    endmacro

    macro LARA_STORE_HL16 address
        ld a,l
        ld (address),a
        ld a,h
        ld (address+1),a
    endmacro

lara_turn_step:             equ 273 ; approximately 3 degrees at 30 Hz
lara_camera_height_step:    equ 32
lara_camera_height_limit:   equ 3200
lara_world_recenter_limit:  equ 24000
lara_camera_mode_look_at:   equ 0
lara_camera_mode_chase:     equ 1

; The camera is unrotated on the scene's +Z side. Pingo's directional vector
; points from a surface toward the light, so +Z places the source behind the
; camera. In the established +X-right/+Z-up plan view, positive X swings that
; vector 15 degrees clockwise. Command 43 normalizes these signed ratios.
lara_light_direction_x: equ 8481
lara_light_direction_y: equ 0
lara_light_direction_z: equ 31650

; Initialize all control-local objects, install source frame 1, initialize the
; retained controller/camera state, and submit it before the setup barrier.
; Generated ID tuples are sid, oid, mid, texture-bmid.
lara_animation_initialize:
    xor a
    ld (lara_current_frame),a
    ld (lara_control_latches),a
    ld (lara_pose_dirty),a
    ld (lara_view_dirty),a
    ld (lara_restart_pending),a
    ld (lara_camera_mode),a
    ld a,1
    ld (lara_playing),a
    ld hl,lara_pose_samples
    ld (lara_pose_pointer),hl

    ld hl,0
    LARA_STORE_HL16 lara_scene_heading
    LARA_STORE_HL16 lara_camera_height
    LARA_STORE_HL16 lara_world_position+p3d_vec3_x
    LARA_STORE_HL16 lara_world_position+p3d_vec3_y
    LARA_STORE_HL16 lara_world_position+p3d_vec3_z
    ld hl,lara_nominal_forward_step
    LARA_STORE_HL16 lara_motion_step

    ld ix,lara_object_states
    ld iy,lara_object_ids
    ld a,lara_track_count
@initialize_object:
    push af
    call p3d_object_init16
    ld hl,lara_object_scale
    ld (ix+p3d_object_scale+p3d_vec3_x),l
    ld (ix+p3d_object_scale+p3d_vec3_x+1),h
    ld (ix+p3d_object_scale+p3d_vec3_y),l
    ld (ix+p3d_object_scale+p3d_vec3_y+1),h
    ld (ix+p3d_object_scale+p3d_vec3_z),l
    ld (ix+p3d_object_scale+p3d_vec3_z+1),h
    lea ix,ix+p3d_object_size
    lea iy,iy+p3d_object_ids_size
    pop af
    dec a
    jr nz,@initialize_object

    call lara_apply_current_pose
    call lara_initialize_camera
    call lara_configure_lighting
    jp lara_sync_scene

lara_configure_lighting:
    ld bc,lara_light_direction_x
    ld de,lara_light_direction_y
    ld iy,lara_light_direction_z
    jp pingo_set_light_direction

; One fixed 30 Hz quantum. Wolf-style turning is applied before translation.
; Animation advances independently of movement input. The source frame's
; outgoing pelvis delta supplies the speed when W/A/D are held.
lara_animation_step:
    call lara_handle_edge_controls
    jr c,@track_camera
    call lara_apply_turn_controls
    call lara_apply_camera_height_controls

; A reset pose must be published before catch-up can coalesce frame 2 over it.
    ld a,(lara_restart_pending)
    or a
    jr nz,@track_camera

; A paused pose may still be moved for inspection at the generated cycle mean.
    ld hl,lara_nominal_forward_step
    LARA_STORE_HL16 lara_motion_step
    ld a,(lara_playing)
    or a
    call nz,lara_advance_pose

    call lara_apply_locomotion_controls
    call lara_rebase_world_if_needed

@track_camera:
    jp lara_update_camera_tracking

; Compute the outgoing captured pelvis +Z delta, then install the next pose.
; Frame indexes are zero based. The 23 -> 1 wrap uses the generated virtual
; frame 24 delta, which was loop-conditioned to match frame 1 -> 2.
lara_advance_pose:
    ld iy,(lara_pose_pointer)
    ld e,(iy+p3d_vec3_z)
    ld d,(iy+p3d_vec3_z+1)
    ld a,(lara_current_frame)
    inc a
    cp lara_pose_frame_count
    jr c,@advance

    ld hl,lara_loop_forward_step
    LARA_STORE_HL16 lara_motion_step
    xor a
    ld hl,lara_pose_samples
    jr @install

@advance:
    push af
    push de
    push iy
    pop hl
    ld de,lara_pose_frame_size
    add hl,de
    push hl
    pop iy
    pop de
    ld l,(iy+p3d_vec3_z)
    ld h,(iy+p3d_vec3_z+1)
    or a
    sbc.s hl,de
    LARA_STORE_HL16 lara_motion_step
    push iy
    pop hl
    pop af

@install:
    ld (lara_current_frame),a
    ld (lara_pose_pointer),hl
    jp lara_apply_current_pose

; R resets the clip to a paused frame 1; P toggles pose advancement. Edge
; latches keep a held key from retriggering on every 30 Hz quantum. Carry means
; reset already installed frame 1 and this quantum must not advance to frame 2.
lara_handle_edge_controls:
    ld ix,keyboard_masks
    ld a,(lara_control_latches)
    ld b,a

; R, virtual key 52: byte 6 bit 3.
    bit 3,(ix+6)
    jr z,@restart_released
    bit 0,b
    jr nz,@pause_key
    set 0,b
    ld a,b
    ld (lara_control_latches),a
    call lara_restart
    scf
    ret
@restart_released:
    res 0,b

; P, virtual key 56: byte 6 bit 7.
@pause_key:
    bit 7,(ix+6)
    jr z,@pause_released
    bit 1,b
    jr nz,@controls_done
    set 1,b
    ld a,(lara_playing)
    xor 1
    ld (lara_playing),a
    jr @controls_done
@pause_released:
    res 1,b

@controls_done:
    ld a,b
    ld (lara_control_latches),a
    or a
    ret

; Left and Right use the Wolf keyboard matrix and cancel when opposed. Their
; signs are qualified from the rendered Lara/camera convention rather than an
; abstract plan view. Word wrap is intentional: Pingo angles are periodic.
lara_apply_turn_controls:
    ld ix,keyboard_masks
    bit 1,(ix+3)                       ; Left
    jr z,@right_only
    bit 1,(ix+15)                      ; Right
    ret nz
    LARA_LOAD_HL16 lara_scene_heading
    ld de,lara_turn_step
    add.s hl,de
    jr @store
@right_only:
    bit 1,(ix+15)
    ret z
    LARA_LOAD_HL16 lara_scene_heading
    ld de,-lara_turn_step
    add.s hl,de
@store:
    LARA_STORE_HL16 lara_scene_heading
    ld a,1
    ld (lara_view_dirty),a
    ret

; Page Up/Down alter only the retained camera height. Opposed keys cancel.
lara_apply_camera_height_controls:
    ld ix,keyboard_masks
    bit 7,(ix+7)                       ; Page Up
    jr z,@page_down_only
    bit 6,(ix+9)                       ; Page Down
    ret nz
    call lara_camera_height_up
    jr @changed
@page_down_only:
    bit 6,(ix+9)
    ret z
    call lara_camera_height_down
@changed:
    ld a,1
    ld (lara_view_dirty),a
    ret

lara_camera_height_up:
    LARA_LOAD_HL16 lara_camera_height
    ld de,lara_camera_height_step
    call p3d_sadd16
    jr c,@maximum
    bit 7,h
    jr nz,@store
    push hl
    ld de,lara_camera_height_limit
    or a
    sbc.s hl,de
    pop hl
    jr c,@store
    jr z,@store
@maximum:
    ld hl,lara_camera_height_limit
@store:
    LARA_STORE_HL16 lara_camera_height
    ret

lara_camera_height_down:
    LARA_LOAD_HL16 lara_camera_height
    ld de,-lara_camera_height_step
    call p3d_sadd16
    jr c,@minimum
    bit 7,h
    jr z,@store
    push hl
    ld de,-lara_camera_height_limit
    or a
    sbc.s hl,de
    pop hl
    jr nc,@store
@minimum:
    ld hl,-lara_camera_height_limit
@store:
    LARA_STORE_HL16 lara_camera_height
    ret

; W applies forward +Z; A/D apply left/right X using the same captured step.
; S is deliberately unbound because reverse playback would not be a run.
; Combining forward and strafe retains Wolf's independent-axis diagonal rate.
lara_apply_locomotion_controls:
    xor a
    ld (lara_movement_work+p3d_vec3_x),a
    ld (lara_movement_work+p3d_vec3_x+1),a
    ld (lara_movement_work+p3d_vec3_y),a
    ld (lara_movement_work+p3d_vec3_y+1),a
    ld (lara_movement_work+p3d_vec3_z),a
    ld (lara_movement_work+p3d_vec3_z+1),a

    ld ix,keyboard_masks
    bit 1,(ix+4)                       ; W
    jr z,@strafe
    LARA_LOAD_HL16 lara_motion_step
    LARA_STORE_HL16 lara_movement_work+p3d_vec3_z

@strafe:
    bit 1,(ix+8)                       ; A
    jr z,@right_only
    bit 2,(ix+6)                       ; D
    jr nz,@ready
    LARA_LOAD_HL16 lara_motion_step
    call lara_negate_hl
    LARA_STORE_HL16 lara_movement_work+p3d_vec3_x
    jr @ready
@right_only:
    bit 2,(ix+6)
    jr z,@ready
    LARA_LOAD_HL16 lara_motion_step
    LARA_STORE_HL16 lara_movement_work+p3d_vec3_x

@ready:
    ld a,(lara_movement_work+p3d_vec3_x)
    ld b,a
    ld a,(lara_movement_work+p3d_vec3_x+1)
    or b
    ld b,a
    ld a,(lara_movement_work+p3d_vec3_z)
    or b
    ld b,a
    ld a,(lara_movement_work+p3d_vec3_z+1)
    or b
    ret z

    ld ix,lara_movement_work
    LARA_LOAD_HL16 lara_scene_heading
    call p3d_vec3_rotate_y16
    ret c
    ld ix,lara_world_position
    ld iy,lara_movement_work
    call p3d_vec3_translate16
    ret c
    ld a,1
    ld (lara_view_dirty),a
    ret

lara_negate_hl:
    xor a
    sub l
    ld l,a
    ld a,0
    sbc a,h
    ld h,a
    ret

; The dormant chase mode can rebase Lara and its translated camera together
; without a visible jump. A fixed look-at observer cannot preserve an
; arbitrarily distant target in signed Pingo space, so it relies on the
; transactional movement add to stop at the representable boundary.
lara_rebase_world_if_needed:
    ld a,(lara_camera_mode)
    cp lara_camera_mode_chase
    ret nz
    LARA_LOAD_HL16 lara_world_position+p3d_vec3_x
    call lara_compare_recenter_magnitude
    jr nc,@rebase
    LARA_LOAD_HL16 lara_world_position+p3d_vec3_z
    call lara_compare_recenter_magnitude
    ret c
@rebase:
    ld hl,0
    LARA_STORE_HL16 lara_world_position+p3d_vec3_x
    LARA_STORE_HL16 lara_world_position+p3d_vec3_z
    ld a,1
    ld (lara_view_dirty),a
    ret

; Return carry when abs(HL) is below the recenter threshold.
lara_compare_recenter_magnitude:
    bit 7,h
    call nz,lara_negate_hl
    ld de,lara_world_recenter_limit
    or a
    sbc.s hl,de
    ret

lara_restart:
    xor a
    ld (lara_current_frame),a
; Discard pre-restart backlog so source frame 1 is published before any later
; sample can coalesce over it. Position, heading, and camera height survive.
    ld hl,0
    ld (simulation_accumulator),hl
    ld a,1
    ld (lara_restart_pending),a
    ld hl,lara_pose_samples
    ld (lara_pose_pointer),hl
    ld hl,lara_nominal_forward_step
    LARA_STORE_HL16 lara_motion_step
    xor a
    ld (lara_playing),a
    jp lara_apply_current_pose

; Restart frame 1 remains advancement-gated until the foreground has copied
; that pose to Pingo and submitted the render that owns the resulting scene.
lara_render_submitted:
    xor a
    ld (lara_restart_pending),a
    ret

; Copy one frame-major group of 15 contiguous translation/Euler records into
; the matching p3d states. Subtract only the current sampled pelvis Z from all
; object Z translations. This removes progressive source travel but preserves
; captured pelvis X sway, Y bob, and every relative body-part displacement.
lara_apply_current_pose:
    ld ix,lara_object_states
    ld iy,(lara_pose_pointer)
    ld l,(iy+p3d_vec3_z)
    ld h,(iy+p3d_vec3_z+1)
    LARA_STORE_HL16 lara_pose_root_z
    ld a,lara_track_count
@copy_track:
    push af
    push iy
    pop hl
    lea de,ix+p3d_object_pingo_translation
    ld bc,lara_pose_record_size
    ldir
    push hl
    pop iy

    ld l,(ix+p3d_object_pingo_translation+p3d_vec3_z)
    ld h,(ix+p3d_object_pingo_translation+p3d_vec3_z+1)
    LARA_LOAD_DE16 lara_pose_root_z
    or a
    sbc.s hl,de
    ld (ix+p3d_object_pingo_translation+p3d_vec3_z),l
    ld (ix+p3d_object_pingo_translation+p3d_vec3_z+1),h

    ld a,(ix+p3d_object_dirty)
    or p3d_object_dirty_pose
    ld (ix+p3d_object_dirty),a
    lea ix,ix+p3d_object_size
    pop af
    dec a
    jr nz,@copy_track
    ld a,1
    ld (lara_pose_dirty),a
    ret

; Default Earth Party-style policy: retain one fixed world observer and aim it
; at the moving target. This makes W/A/D locomotion visible in the empty test
; scene. Page controls alter only its world Y coordinate.
lara_build_camera_position:
    ld a,(lara_camera_mode)
    cp lara_camera_mode_chase
    jp z,lara_build_chase_camera_position
    jp lara_build_look_at_camera_position

lara_build_look_at_camera_position:
    ld hl,lara_camera_offset_x
    LARA_STORE_HL16 lara_camera_position_work+p3d_vec3_x

    LARA_LOAD_HL16 lara_camera_height
    ld de,lara_camera_offset_y
    call p3d_sadd16
    ret c
    LARA_STORE_HL16 lara_camera_position_work+p3d_vec3_y

    ld hl,lara_camera_offset_z
    LARA_STORE_HL16 lara_camera_position_work+p3d_vec3_z
    or a
    ret

; Retained for a future navigation fixture: translate the camera with the
; controlled root while keeping its offset fixed in world axes (not actor
; yaw). Selecting lara_camera_mode_chase makes locomotion view-invariant in an
; otherwise empty scene, which is why it is not the default here.
lara_build_chase_camera_position:
    LARA_LOAD_HL16 lara_world_position+p3d_vec3_x
    ld de,lara_camera_offset_x
    call p3d_sadd16
    ret c
    LARA_STORE_HL16 lara_camera_position_work+p3d_vec3_x

    LARA_LOAD_HL16 lara_camera_height
    ld de,lara_camera_offset_y
    call p3d_sadd16
    ret c
    LARA_STORE_HL16 lara_camera_position_work+p3d_vec3_y

    LARA_LOAD_HL16 lara_world_position+p3d_vec3_z
    ld de,lara_camera_offset_z
    call p3d_sadd16
    ret c
    LARA_STORE_HL16 lara_camera_position_work+p3d_vec3_z
    or a
    ret

; The first generated track is contractually pelvis_bundle/pelvis. Rotate its
; root-cancelled local anchor by scene yaw, then add controlled world position.
lara_build_camera_target:
    ld ix,lara_object_states
    ld a,(ix+p3d_object_world_position+p3d_vec3_x)
    ld (lara_camera_target_work+p3d_vec3_x),a
    ld a,(ix+p3d_object_world_position+p3d_vec3_x+1)
    ld (lara_camera_target_work+p3d_vec3_x+1),a
    ld a,(ix+p3d_object_world_position+p3d_vec3_y)
    ld (lara_camera_target_work+p3d_vec3_y),a
    ld a,(ix+p3d_object_world_position+p3d_vec3_y+1)
    ld (lara_camera_target_work+p3d_vec3_y+1),a
    ld a,(ix+p3d_object_world_position+p3d_vec3_z)
    ld (lara_camera_target_work+p3d_vec3_z),a
    ld a,(ix+p3d_object_world_position+p3d_vec3_z+1)
    ld (lara_camera_target_work+p3d_vec3_z+1),a

    ld ix,lara_camera_target_work
    LARA_LOAD_HL16 lara_scene_heading
    call p3d_vec3_rotate_y16
    ret c
    ld ix,lara_camera_target_work
    ld iy,lara_world_position
    jp p3d_vec3_translate16

lara_initialize_camera:
    call lara_build_camera_position
    ret c
    ld ix,lara_camera_state
    ld iy,lara_camera_position_work
    ld hl,sid
    call p3d_camera_init16
    call lara_build_camera_target
    ret c
    ld ix,lara_camera_state
    ld iy,lara_camera_target_work
    ld a,p3d_camera_roll_upright
    call p3d_camera_aim_at_point16
    ld a,1
    ld (lara_view_dirty),a
    or a
    ret

; Commit camera position only when it changed, re-aim at the latest pelvis,
; and summarize dirty camera state for the render-idle foreground publisher.
lara_update_camera_tracking:
    call lara_build_camera_position
    ret c
    ld ix,lara_camera_state
    ld iy,lara_camera_position_work
    ld a,(iy+p3d_vec3_x)
    cp (ix+p3d_camera_world_position+p3d_vec3_x)
    jr nz,@commit_position
    ld a,(iy+p3d_vec3_x+1)
    cp (ix+p3d_camera_world_position+p3d_vec3_x+1)
    jr nz,@commit_position
    ld a,(iy+p3d_vec3_y)
    cp (ix+p3d_camera_world_position+p3d_vec3_y)
    jr nz,@commit_position
    ld a,(iy+p3d_vec3_y+1)
    cp (ix+p3d_camera_world_position+p3d_vec3_y+1)
    jr nz,@commit_position
    ld a,(iy+p3d_vec3_z)
    cp (ix+p3d_camera_world_position+p3d_vec3_z)
    jr nz,@commit_position
    ld a,(iy+p3d_vec3_z+1)
    cp (ix+p3d_camera_world_position+p3d_vec3_z+1)
    jr z,@aim

@commit_position:
    ld a,(iy+p3d_vec3_x)
    ld (ix+p3d_camera_world_position+p3d_vec3_x),a
    ld a,(iy+p3d_vec3_x+1)
    ld (ix+p3d_camera_world_position+p3d_vec3_x+1),a
    ld a,(iy+p3d_vec3_y)
    ld (ix+p3d_camera_world_position+p3d_vec3_y),a
    ld a,(iy+p3d_vec3_y+1)
    ld (ix+p3d_camera_world_position+p3d_vec3_y+1),a
    ld a,(iy+p3d_vec3_z)
    ld (ix+p3d_camera_world_position+p3d_vec3_z),a
    ld a,(iy+p3d_vec3_z+1)
    ld (ix+p3d_camera_world_position+p3d_vec3_z+1),a
    ld a,(ix+p3d_camera_dirty)
    or p3d_camera_dirty_position
    ld (ix+p3d_camera_dirty),a

@aim:
    call lara_build_camera_target
    jr c,@summarize
    ld ix,lara_camera_state
    ld iy,lara_camera_target_work
    ld a,p3d_camera_roll_upright
    call p3d_camera_aim_at_point16

@summarize:
    ld ix,lara_camera_state
    ld a,(ix+p3d_camera_dirty)
    and p3d_camera_dirty_all
    ret z
    ld a,1
    ld (lara_view_dirty),a
    ret

; A byte summary avoids walking every state when the renderer is busy.
lara_scene_dirty:
    ld a,(lara_pose_dirty)
    ld b,a
    ld a,(lara_view_dirty)
    or b
    ret

; Called only with no render in flight. Object sync retains the qualified
; create -> scale -> rotation -> translation ordering and packet scratch.
; Scene and camera transport is intentionally kept behind the same gate.
lara_sync_scene:
    call lara_sync_objects
    call lara_sync_view
    xor a
    ld (lara_pose_dirty),a
    ld (lara_view_dirty),a
    ret

lara_sync_objects:
    ld ix,lara_object_states
    ld a,lara_track_count
@sync_track:
    push af
    ld iy,lara_object_packet
    call p3d_object_sync16
    lea ix,ix+p3d_object_size
    pop af
    dec a
    jr nz,@sync_track
    ret

; One scene-level Y rotation composes controlled heading over every sampled
; rigid part. Translation is the retained planar controller position. The
; camera state already contains its final world-space pose.
lara_sync_view:
    LARA_LOAD_HL16 lara_scene_heading
    call lara_set_scene_rotation_y

    LARA_LOAD_BC16 lara_world_position+p3d_vec3_x
    ld de,0
    LARA_LOAD_HL16 lara_world_position+p3d_vec3_z
    push hl
    pop iy
    call lara_set_scene_translation
    jp lara_sync_camera_state

; Current Pingo scene command 33 sets absolute XYZ rotation. Only Y varies.
; input: HL=y angle
lara_set_scene_rotation_y:
    ld a,l
    ld (@y),a
    ld a,h
    ld (@y+1),a
    ld hl,@command
    ld bc,@end-@command
    rst.lil 18h
    ret
@command:
    db 23,0,0A0h
    dw sid
    db 49h,33
@x:
    dw 0
@y:
    dw 0
@z:
    dw 0
@end:
    db 0

; Current Pingo scene command 37 is a SID-scoped absolute XYZ translation.
; Inputs: BC=x, DE=y, IY=z. Store explicit low words in ADL mode.
lara_set_scene_translation:
    ld a,c
    ld (@x),a
    ld a,b
    ld (@x+1),a
    ld a,e
    ld (@y),a
    ld a,d
    ld (@y+1),a
    push iy
    pop hl
    ld a,l
    ld (@z),a
    ld a,h
    ld (@z+1),a
    ld hl,@command
    ld bc,@end-@command
    rst.lil 18h
    ret
@command:
    db 23,0,0A0h
    dw sid
    db 49h,37
@x:
    dw 0
@y:
    dw 0
@z:
    dw 0
@end:
    db 0

; Send each dirty absolute camera component through the qualified Earth Party
; helpers. This routine is reached only from lara_sync_scene while idle.
lara_sync_camera_state:
    ld ix,lara_camera_state
    bit 0,(ix+p3d_camera_dirty)
    jr z,@rotation

    ld c,(ix+p3d_camera_world_position+p3d_vec3_x)
    ld b,(ix+p3d_camera_world_position+p3d_vec3_x+1)
    inc bc
    dec.s bc
    ld e,(ix+p3d_camera_world_position+p3d_vec3_y)
    ld d,(ix+p3d_camera_world_position+p3d_vec3_y+1)
    inc de
    dec.s de
    ld l,(ix+p3d_camera_world_position+p3d_vec3_z)
    ld h,(ix+p3d_camera_world_position+p3d_vec3_z+1)
    inc hl
    dec.s hl
    push hl
    pop iy
    push ix
    call scdabs
    pop ix
    ld a,(ix+p3d_camera_dirty)
    res 0,a
    ld (ix+p3d_camera_dirty),a

@rotation:
    bit 1,(ix+p3d_camera_dirty)
    ret z

    ld c,(ix+p3d_camera_pingo_rotation+p3d_vec3_x)
    ld b,(ix+p3d_camera_pingo_rotation+p3d_vec3_x+1)
    inc bc
    dec.s bc
    ld e,(ix+p3d_camera_pingo_rotation+p3d_vec3_y)
    ld d,(ix+p3d_camera_pingo_rotation+p3d_vec3_y+1)
    inc de
    dec.s de
    ld l,(ix+p3d_camera_pingo_rotation+p3d_vec3_z)
    ld h,(ix+p3d_camera_pingo_rotation+p3d_vec3_z+1)
    inc hl
    dec.s hl
    push hl
    pop iy
    push ix
    call scrabs
    pop ix
    ld a,(ix+p3d_camera_dirty)
    res 1,a
    ld (ix+p3d_camera_dirty),a
    or a
    ret

; The MOS start prompt completes on key-down. Wait for a completely released
; keyboard so movement, P, R, or Page keys cannot leak into the first quantum.
lara_wait_for_keys_released:
    MOSCALL mos_getkbmap
    ld b,16
    ld c,0
@scan:
    ld a,(ix)
    or c
    ld c,a
    inc ix
    djnz @scan
    ld a,c
    or a
    jr nz,lara_wait_for_keys_released
    ret

; Release global VDP resources in dependency order after the final render has
; completed. Command 39 destroys the Pingo control and its private scene,
; frame, depth, object, and mesh allocations. Generic buffer command 2 then
; releases the shared texture and render target. The caller fences this packet
; before removing the callback or returning to MOS.
lara_release_resources:
    ld hl,@commands
    ld bc,@end-@commands
    rst.lil 18h
    ret
@commands:
    db 23,0,0A0h
    dw sid
    db 49h,39
    db 23,0,0A0h
    dw tgtbmid
    db 2
    db 23,0,0A0h
    dw lara_texture_bmid
    db 2
@end:

lara_pose_pointer:
    dl 0

lara_current_frame:
    db 0

lara_playing:
    db 0

lara_control_latches:
    db 0

lara_pose_dirty:
    db 0

lara_view_dirty:
    db 0

lara_restart_pending:
    db 0

lara_camera_mode:
    db lara_camera_mode_look_at

lara_motion_step:
    dw lara_nominal_forward_step

lara_pose_root_z:
    dw 0

lara_scene_heading:
    dw 0

lara_camera_height:
    dw 0

lara_world_position:
    ds p3d_vec3_size

lara_movement_work:
    ds p3d_vec3_size

lara_camera_position_work:
    ds p3d_vec3_size

lara_camera_target_work:
    ds p3d_vec3_size

lara_camera_state:
    ds p3d_camera_size

lara_object_packet:
    ds p3d_pingo_update_packet_size

lara_object_states:
    ds p3d_object_size*lara_track_count
