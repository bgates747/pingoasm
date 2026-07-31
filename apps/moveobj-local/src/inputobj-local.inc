; =============================================================================
; Fixed-step object-local controls for the eZ80-owned Pingo pose.
;
; The keyboard map and signs match the historical moveobj application. This
; file writes per-quantum velocity deltas into the packed p3d object state;
; render synchronization is intentionally owned by the asynchronous main loop.
; =============================================================================

; Initialize the packed object state after mesh and UV data have been sent.
; p3d_object_init16 marks create, scale, rotation, and translation dirty.
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

; Decode one latched input quantum and integrate it. Velocity fields contain
; the already-scaled four-MOS-tick deltas, not the 128-tick rate constants.
simulate_object_step:
    ld iy,object_state
    xor a
    ld (iy+p3d_object_local_linear_velocity+0),a
    ld (iy+p3d_object_local_linear_velocity+1),a
    ld (iy+p3d_object_local_linear_velocity+2),a
    ld (iy+p3d_object_local_linear_velocity+3),a
    ld (iy+p3d_object_local_linear_velocity+4),a
    ld (iy+p3d_object_local_linear_velocity+5),a
    ld (iy+p3d_object_local_angular_velocity+0),a
    ld (iy+p3d_object_local_angular_velocity+1),a
    ld (iy+p3d_object_local_angular_velocity+2),a
    ld (iy+p3d_object_local_angular_velocity+3),a
    ld (iy+p3d_object_local_angular_velocity+4),a
    ld (iy+p3d_object_local_angular_velocity+5),a

    ld ix,keyboard_masks

; Space formerly changed dithering through an obsolete one-byte command 41.
; Current Pingo uses command 41 for the render-completion registration packet,
; so no executable Space binding exists here.
;   bit 2,(ix+12)
;   call nz,cycle_dithering

; W/S: forward (-Z) / backward (+Z).
    bit 1,(ix+4)
    jr z,@W
    ld hl,-object_linear_step
    ld (iy+p3d_object_local_linear_velocity+p3d_vec3_z),l
    ld (iy+p3d_object_local_linear_velocity+p3d_vec3_z+1),h
@W:
    bit 1,(ix+10)
    jr z,@S
    ld l,(iy+p3d_object_local_linear_velocity+p3d_vec3_z)
    ld h,(iy+p3d_object_local_linear_velocity+p3d_vec3_z+1)
    ld de,object_linear_step
    add.s hl,de
    ld (iy+p3d_object_local_linear_velocity+p3d_vec3_z),l
    ld (iy+p3d_object_local_linear_velocity+p3d_vec3_z+1),h
@S:

; A/D: left (-X) / right (+X).
    bit 1,(ix+8)
    jr z,@A
    ld hl,-object_linear_step
    ld (iy+p3d_object_local_linear_velocity+p3d_vec3_x),l
    ld (iy+p3d_object_local_linear_velocity+p3d_vec3_x+1),h
@A:
    bit 2,(ix+6)
    jr z,@D
    ld l,(iy+p3d_object_local_linear_velocity+p3d_vec3_x)
    ld h,(iy+p3d_object_local_linear_velocity+p3d_vec3_x+1)
    ld de,object_linear_step
    add.s hl,de
    ld (iy+p3d_object_local_linear_velocity+p3d_vec3_x),l
    ld (iy+p3d_object_local_linear_velocity+p3d_vec3_x+1),h
@D:

; Page Up/Page Down: up (+Y) / down (-Y).
    bit 7,(ix+7)
    jr z,@PgUp
    ld hl,object_linear_step
    ld (iy+p3d_object_local_linear_velocity+p3d_vec3_y),l
    ld (iy+p3d_object_local_linear_velocity+p3d_vec3_y+1),h
@PgUp:
    bit 6,(ix+9)
    jr z,@PgDn
    ld l,(iy+p3d_object_local_linear_velocity+p3d_vec3_y)
    ld h,(iy+p3d_object_local_linear_velocity+p3d_vec3_y+1)
    ld de,-object_linear_step
    add.s hl,de
    ld (iy+p3d_object_local_linear_velocity+p3d_vec3_y),l
    ld (iy+p3d_object_local_linear_velocity+p3d_vec3_y+1),h
@PgDn:

; Q/E: roll left (+Z) / roll right (-Z).
    bit 0,(ix+2)
    jr z,@Q
    ld hl,object_angular_step
    ld (iy+p3d_object_local_angular_velocity+p3d_vec3_z),l
    ld (iy+p3d_object_local_angular_velocity+p3d_vec3_z+1),h
@Q:
    bit 2,(ix+4)
    jr z,@E
    ld l,(iy+p3d_object_local_angular_velocity+p3d_vec3_z)
    ld h,(iy+p3d_object_local_angular_velocity+p3d_vec3_z+1)
    ld de,-object_angular_step
    add.s hl,de
    ld (iy+p3d_object_local_angular_velocity+p3d_vec3_z),l
    ld (iy+p3d_object_local_angular_velocity+p3d_vec3_z+1),h
@E:

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

; Left/Right: yaw left (+Y) / yaw right (-Y).
    bit 1,(ix+3)
    jr z,@Left
    ld hl,object_angular_step
    ld (iy+p3d_object_local_angular_velocity+p3d_vec3_y),l
    ld (iy+p3d_object_local_angular_velocity+p3d_vec3_y+1),h
@Left:
    bit 1,(ix+15)
    jr z,@Right
    ld l,(iy+p3d_object_local_angular_velocity+p3d_vec3_y)
    ld h,(iy+p3d_object_local_angular_velocity+p3d_vec3_y+1)
    ld de,-object_angular_step
    add.s hl,de
    ld (iy+p3d_object_local_angular_velocity+p3d_vec3_y),l
    ld (iy+p3d_object_local_angular_velocity+p3d_vec3_y+1),h
@Right:

; Avoid the expensive transform when opposing inputs cancel or no control is
; active. Angular residuals do not advance when velocity is zero.
    ld a,(iy+p3d_object_local_linear_velocity+0)
    or (iy+p3d_object_local_linear_velocity+1)
    or (iy+p3d_object_local_linear_velocity+2)
    or (iy+p3d_object_local_linear_velocity+3)
    or (iy+p3d_object_local_linear_velocity+4)
    or (iy+p3d_object_local_linear_velocity+5)
    or (iy+p3d_object_local_angular_velocity+0)
    or (iy+p3d_object_local_angular_velocity+1)
    or (iy+p3d_object_local_angular_velocity+2)
    or (iy+p3d_object_local_angular_velocity+3)
    or (iy+p3d_object_local_angular_velocity+4)
    or (iy+p3d_object_local_angular_velocity+5)
    ret z

    ld ix,object_state
    jp p3d_object_step16
