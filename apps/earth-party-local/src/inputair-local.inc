; =============================================================================
; Fixed-step moveair controls for the eZ80-owned Pingo pose.
;
; Forward throttle persists in the object's local -Z velocity. Angular input
; is transient: pitch, roll, and yaw are rebuilt from the latched keyboard map
; for each four-MOS-tick simulation quantum. Rendering remains independent.
; =============================================================================

; Initialize the packed object state after mesh and UV data have been sent.
; p3d_object_init16 zeroes velocities and marks all initial Pingo state dirty.
init_object_state:
    ld ix,object_state
    ld iy,object_ids
    call p3d_object_init16

    ld hl,obj_initial_x
    ld (ix+p3d_object_world_position+p3d_vec3_x),l
    ld (ix+p3d_object_world_position+p3d_vec3_x+1),h
    ld hl,obj_initial_y
    ld (ix+p3d_object_world_position+p3d_vec3_y),l
    ld (ix+p3d_object_world_position+p3d_vec3_y+1),h
    ld hl,obj_initial_z
    ld (ix+p3d_object_world_position+p3d_vec3_z),l
    ld (ix+p3d_object_world_position+p3d_vec3_z+1),h

    ld hl,obj_scale
    ld (ix+p3d_object_scale+p3d_vec3_x),l
    ld (ix+p3d_object_scale+p3d_vec3_x+1),h
    ld (ix+p3d_object_scale+p3d_vec3_y),l
    ld (ix+p3d_object_scale+p3d_vec3_y+1),h
    ld (ix+p3d_object_scale+p3d_vec3_z),l
    ld (ix+p3d_object_scale+p3d_vec3_z+1),h

    ld iy,object_packet
    jp p3d_object_sync16

; Apply one fixed simulation quantum. Local-linear Z is intentionally not
; cleared: it is the persistent throttle velocity. X/Y and all angular fields
; are transient control outputs.
simulate_object_step:
    ld iy,object_state
    xor a
    ld (iy+p3d_object_local_linear_velocity+p3d_vec3_x+0),a
    ld (iy+p3d_object_local_linear_velocity+p3d_vec3_x+1),a
    ld (iy+p3d_object_local_linear_velocity+p3d_vec3_y+0),a
    ld (iy+p3d_object_local_linear_velocity+p3d_vec3_y+1),a
    ld (iy+p3d_object_local_angular_velocity+0),a
    ld (iy+p3d_object_local_angular_velocity+1),a
    ld (iy+p3d_object_local_angular_velocity+2),a
    ld (iy+p3d_object_local_angular_velocity+3),a
    ld (iy+p3d_object_local_angular_velocity+4),a
    ld (iy+p3d_object_local_angular_velocity+5),a

    ld ix,keyboard_masks

; Space formerly changed dithering through an obsolete one-byte command 41.
; Current Pingo uses command 41 for render-completion registration.
;   bit 2,(ix+12)
;   call nz,cycle_dithering

; W increases forward throttle. Forward is local -Z, so this decrements the
; persistent signed velocity until the historical magnitude limit of 255.
    bit 1,(ix+4)
    jr z,@W
    ld l,(iy+p3d_object_local_linear_velocity+p3d_vec3_z)
    ld h,(iy+p3d_object_local_linear_velocity+p3d_vec3_z+1)
    ld de,-object_air_speed_limit
    or a
    sbc.s hl,de
    jr z,@W
    ld l,(iy+p3d_object_local_linear_velocity+p3d_vec3_z)
    ld h,(iy+p3d_object_local_linear_velocity+p3d_vec3_z+1)
    dec.s hl
    ld (iy+p3d_object_local_linear_velocity+p3d_vec3_z),l
    ld (iy+p3d_object_local_linear_velocity+p3d_vec3_z+1),h
@W:

; S decreases throttle toward zero; legacy moveair has no reverse thrust.
    bit 1,(ix+10)
    jr z,@S
    ld l,(iy+p3d_object_local_linear_velocity+p3d_vec3_z)
    ld h,(iy+p3d_object_local_linear_velocity+p3d_vec3_z+1)
    ld a,h
    or l
    jr z,@S
    inc.s hl
    ld (iy+p3d_object_local_linear_velocity+p3d_vec3_z),l
    ld (iy+p3d_object_local_linear_velocity+p3d_vec3_z+1),h
@S:

; Up/Down: pitch down (-X) / pitch up (+X).
    bit 1,(ix+7)
    jr z,@Up
    ld hl,-object_angular_step
    ld (iy+p3d_object_local_angular_velocity+p3d_vec3_x),l
    ld (iy+p3d_object_local_angular_velocity+p3d_vec3_x+1),h
@Up:
    bit 1,(ix+5)
    jr z,@Down
    ld l,(iy+p3d_object_local_angular_velocity+p3d_vec3_x)
    ld h,(iy+p3d_object_local_angular_velocity+p3d_vec3_x+1)
    ld de,object_angular_step
    add.s hl,de
    ld (iy+p3d_object_local_angular_velocity+p3d_vec3_x),l
    ld (iy+p3d_object_local_angular_velocity+p3d_vec3_x+1),h
@Down:

; Left/Right: roll left (+Z) / roll right (-Z), twice pitch/yaw rate.
    bit 1,(ix+3)
    jr z,@Left
    ld hl,object_angular_step*2
    ld (iy+p3d_object_local_angular_velocity+p3d_vec3_z),l
    ld (iy+p3d_object_local_angular_velocity+p3d_vec3_z+1),h
@Left:
    bit 1,(ix+15)
    jr z,@Right
    ld l,(iy+p3d_object_local_angular_velocity+p3d_vec3_z)
    ld h,(iy+p3d_object_local_angular_velocity+p3d_vec3_z+1)
    ld de,-object_angular_step*2
    add.s hl,de
    ld (iy+p3d_object_local_angular_velocity+p3d_vec3_z),l
    ld (iy+p3d_object_local_angular_velocity+p3d_vec3_z+1),h
@Right:

; A/D: yaw left (+Y) / yaw right (-Y).
    bit 1,(ix+8)
    jr z,@A
    ld hl,object_angular_step
    ld (iy+p3d_object_local_angular_velocity+p3d_vec3_y),l
    ld (iy+p3d_object_local_angular_velocity+p3d_vec3_y+1),h
@A:
    bit 2,(ix+6)
    jr z,@D
    ld l,(iy+p3d_object_local_angular_velocity+p3d_vec3_y)
    ld h,(iy+p3d_object_local_angular_velocity+p3d_vec3_y+1)
    ld de,-object_angular_step
    add.s hl,de
    ld (iy+p3d_object_local_angular_velocity+p3d_vec3_y),l
    ld (iy+p3d_object_local_angular_velocity+p3d_vec3_y+1),h
@D:

; Persistent nonzero thrust must integrate every simulation quantum even when
; no key is currently down. Rotation is applied before translation by p3d.
    ld a,(iy+p3d_object_local_linear_velocity+p3d_vec3_z)
    or (iy+p3d_object_local_linear_velocity+p3d_vec3_z+1)
    or (iy+p3d_object_local_angular_velocity+0)
    or (iy+p3d_object_local_angular_velocity+1)
    or (iy+p3d_object_local_angular_velocity+2)
    or (iy+p3d_object_local_angular_velocity+3)
    or (iy+p3d_object_local_angular_velocity+4)
    or (iy+p3d_object_local_angular_velocity+5)
    ret z

    ld ix,object_state
    jp p3d_object_step16
