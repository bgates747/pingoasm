; =============================================================================
; Deterministic 30 Hz light-aircraft point-mass model.
;
; This is deliberately separate from the visually accepted terrain fixture.
; It reuses PingoASM's qualified signed-Q15 matrix and persistent object-pose
; implementation.  Position is signed 16.8 Pingo translation counts in exact
; three-byte fields; velocity and per-step force are signed Q8 counts/tick.
;
; One Pingo translation count is approximately 0.0625 m.  At 30 Hz, the
; initial -4608 Q8 Z velocity is approximately 33.75 m/s.  Gravity is -45 Q8
; velocity counts per step, approximately -9.89 m/s^2 after quantization.
; =============================================================================

flight_flag_on_ground: equ 01h
flight_flag_arithmetic: equ 02h

flight_gravity_step_q8: equ -45
flight_velocity_limit_q8: equ 8192
flight_takeoff_speed_q8: equ 3200
flight_initial_speed_q8: equ 4608
flight_rate_limit: equ 512
flight_rate_limit_high: equ 2
flight_rate_negative_limit_high: equ 0feh
flight_velocity_limit_high: equ 32
flight_velocity_negative_limit_high: equ 0e0h
flight_pitch_moment: equ 12
flight_roll_moment: equ 24
flight_yaw_moment: equ 8
flight_throttle_step: equ 4
flight_cruise_throttle: equ 160
flight_cruise_thrust_q8: equ 18
flight_max_thrust_q8: equ 28

    MACRO FLIGHT_STORE_HL16 target
        ld a,l
        ld (target),a
        ld a,h
        ld (target+1),a
    ENDMACRO

    MACRO FLIGHT_LOAD_HL16 source
        ld a,(source)
        ld l,a
        ld a,(source+1)
        ld h,a
    ENDMACRO

    MACRO FLIGHT_LOAD_DE16 source
        ld a,(source)
        ld e,a
        ld a,(source+1)
        ld d,a
    ENDMACRO

; Initialize the private object pose and the higher-precision flight state.
; Identity attitude faces local/world -Z, true east in the Berkeley frame.
flight_model_init:
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

; Clear only the flight-owned block.  The P3D object has its own initializer.
    ld hl,flight_state
    ld de,flight_state+1
    ld bc,flight_state_size-1
    xor a
    ld (hl),a
    ldir

; Signed 16.8 local positions: fraction byte followed by the rendered word.
    ld hl,obj_initial_x
    FLIGHT_STORE_HL16 flight_position_x_q8+1
    ld hl,obj_initial_y
    FLIGHT_STORE_HL16 flight_position_y_q8+1
    ld hl,obj_initial_z
    FLIGHT_STORE_HL16 flight_position_z_q8+1
    ld hl,obj_ground_y
    FLIGHT_STORE_HL16 flight_ground_y_q8+1

; Begin in exact level-flight trim over the Campanile.  Cruise throttle gives
; 18 Q8 thrust, exactly balancing 4608>>8 linear drag.  Lift is
; (4608>>7)+(4608>>9)=45, exactly balancing quantized gravity.
    ld hl,-flight_initial_speed_q8
    FLIGHT_STORE_HL16 flight_velocity_q8+p3d_vec3_z
    ld hl,flight_initial_speed_q8
    FLIGHT_STORE_HL16 flight_airspeed_q8
    ld a,flight_cruise_throttle
    ld (flight_throttle),a
    ret

; Advance exactly one fixed simulation quantum.  Rendering never changes this
; cadence; callers may coalesce several completed quanta into one frame.
flight_model_step:
    call flight_read_controls
    call flight_update_angular_rates

; P3D owns intrinsic local rotation, Euler export, matrix re-orthogonalizing,
; and angular lookup residuals.  Local linear velocity stays zero because the
; force model integrates a world-space inertia vector below.
    ld ix,object_state
    call p3d_object_step16
    jr c,flight_model_failed

    call flight_build_orientation_transpose
    ld hl,flight_velocity_q8
    ld de,flight_body_velocity_q8
    ld bc,p3d_vec3_size
    ldir
    ld ix,flight_body_velocity_q8
    ld iy,flight_orientation_transpose
    call p3d_mat3_mul_vec3_16
    jr c,flight_model_failed

    call flight_compute_aero_scalars
    call flight_build_world_force
    jr c,flight_model_failed
    call flight_resolve_acceleration

; Velocity update is transactional in the proven vector primitive.  Explicit
; saturation below is an ordinary flight envelope, not arithmetic recovery.
    ld ix,flight_velocity_q8
    ld iy,flight_acceleration_q8
    call p3d_vec3_translate16
    jr c,flight_model_failed
    call flight_limit_velocity
    call flight_apply_runway_support
    call flight_integrate_position
    call flight_publish_position
    or a
    ret

flight_model_failed:
    ld a,(flight_flags)
    or flight_flag_arithmetic
    ld (flight_flags),a
    scf
    ret

; Convert the latched MOS keyboard map into signed -1/0/+1 control demands.
; W/S move a persistent byte throttle; there is no reverse thrust.
flight_read_controls:
    xor a
    ld (flight_pitch_control),a
    ld (flight_roll_control),a
    ld (flight_yaw_control),a
    ld ix,keyboard_masks

    bit 1,(ix+4)
    jr z,@throttle_down
    ld a,(flight_throttle)
    cp 256-flight_throttle_step
    jr c,@increase_throttle
    ld a,255
    jr @store_increased_throttle
@increase_throttle:
    add a,flight_throttle_step
@store_increased_throttle:
    ld (flight_throttle),a
@throttle_down:
    bit 1,(ix+10)
    jr z,@pitch
    ld a,(flight_throttle)
    cp flight_throttle_step
    jr nc,@decrease_throttle
    xor a
    jr @store_decreased_throttle
@decrease_throttle:
    sub flight_throttle_step
@store_decreased_throttle:
    ld (flight_throttle),a

@pitch:
; Up pushes the nose down (-X); Down pulls the nose up (+X).
    bit 1,(ix+7)
    jr z,@pitch_up
    ld a,-1
    ld (flight_pitch_control),a
@pitch_up:
    bit 1,(ix+5)
    jr z,@roll
    ld a,(flight_pitch_control)
    inc a
    ld (flight_pitch_control),a

@roll:
    bit 1,(ix+3)
    jr z,@roll_right
    ld a,1
    ld (flight_roll_control),a
@roll_right:
    bit 1,(ix+15)
    jr z,@yaw
    ld a,(flight_roll_control)
    dec a
    ld (flight_roll_control),a

@yaw:
    bit 1,(ix+8)
    jr z,@yaw_right
    ld a,1
    ld (flight_yaw_control),a
@yaw_right:
    bit 2,(ix+6)
    ret z
    ld a,(flight_yaw_control)
    dec a
    ld (flight_yaw_control),a
    ret

; Apply control moments and approximately 1/16-per-step rotational damping.
; At sustained full input, pitch/roll/yaw settle near 192/384/128 Pingo angle
; words per step (about 63/127/42 degrees per second at 30 Hz).
flight_update_angular_rates:
    ld ix,object_state

    ld l,(ix+p3d_object_local_angular_velocity+p3d_vec3_x)
    ld h,(ix+p3d_object_local_angular_velocity+p3d_vec3_x+1)
    push hl
    ld a,(flight_pitch_control)
    ld de,flight_pitch_moment
    call flight_apply_axis_moment
    push hl
    pop bc
    pop de
    or a
    sbc.s hl,de
    FLIGHT_STORE_HL16 flight_angular_acceleration+p3d_vec3_x
    ld h,b
    ld l,c
    ld (ix+p3d_object_local_angular_velocity+p3d_vec3_x),l
    ld (ix+p3d_object_local_angular_velocity+p3d_vec3_x+1),h

    ld l,(ix+p3d_object_local_angular_velocity+p3d_vec3_z)
    ld h,(ix+p3d_object_local_angular_velocity+p3d_vec3_z+1)
    push hl
    ld a,(flight_roll_control)
    ld de,flight_roll_moment
    call flight_apply_axis_moment
    push hl
    pop bc
    pop de
    or a
    sbc.s hl,de
    FLIGHT_STORE_HL16 flight_angular_acceleration+p3d_vec3_z
    ld h,b
    ld l,c
    ld (ix+p3d_object_local_angular_velocity+p3d_vec3_z),l
    ld (ix+p3d_object_local_angular_velocity+p3d_vec3_z+1),h

    ld l,(ix+p3d_object_local_angular_velocity+p3d_vec3_y)
    ld h,(ix+p3d_object_local_angular_velocity+p3d_vec3_y+1)
    push hl
    ld a,(flight_yaw_control)
    ld de,flight_yaw_moment
    call flight_apply_axis_moment

; A restrained bank-to-yaw coupling approximates a coordinated turn once the
; wing is above its low-speed regime.  Read world-Y from the aircraft's local
; right vector (orientation r1c0), a Q15 sine-like bank proxy.  Do not use the
; exported Euler Z word here: the matrix-to-Euler representation may select
; an equivalent +/-180-degree branch after a yawed pitch, which is physically
; the same attitude but a catastrophically false bank feedback signal.
    ld a,(flight_airspeed_q8+1)
    cp flight_takeoff_speed_q8 >> 8
    jr c,@store_yaw
    push hl
    ld l,(ix+p3d_object_orientation+p3d_mat3_r1c0)
    ld h,(ix+p3d_object_orientation+p3d_mat3_r1c0+1)
    ld a,12
@bank_shift:
    sra h
    rr l
    dec a
    jr nz,@bank_shift
    ld d,h
    ld e,l
    pop hl
    add.s hl,de
    call flight_clamp_rate16
@store_yaw:
    push hl
    pop bc
    pop de
    or a
    sbc.s hl,de
    FLIGHT_STORE_HL16 flight_angular_acceleration+p3d_vec3_y
    ld h,b
    ld l,c
    ld (ix+p3d_object_local_angular_velocity+p3d_vec3_y),l
    ld (ix+p3d_object_local_angular_velocity+p3d_vec3_y+1),h
    ret

; Input: HL=current signed rate, A=signed demand, DE=positive moment.
; Output: damped/moment-adjusted/clamped HL.
flight_apply_axis_moment:
    push af
    push de
    call flight_damp_rate16
    pop de
    pop af
    or a
    jr z,flight_clamp_rate16
    jp m,@negative
    add.s hl,de
    jr flight_clamp_rate16
@negative:
    or a
    sbc.s hl,de
    jr flight_clamp_rate16

; Damping has a minimum one-count decay so released controls converge to rest.
flight_damp_rate16:
    ld a,h
    or l
    ret z
    ld b,h
    ld c,l
    bit 7,h
    jr nz,@negative
    ld a,4
@positive_shift:
    srl h
    rr l
    dec a
    jr nz,@positive_shift
    ld a,h
    or l
    jr nz,@positive_ready
    inc hl
@positive_ready:
    ld d,h
    ld e,l
    ld h,b
    ld l,c
    or a
    sbc.s hl,de
    ret
@negative:
    xor a
    sub l
    ld l,a
    ld a,0
    sbc a,h
    ld h,a
    ld a,4
@negative_shift:
    srl h
    rr l
    dec a
    jr nz,@negative_shift
    ld a,h
    or l
    jr nz,@negative_ready
    inc hl
@negative_ready:
    ld d,h
    ld e,l
    ld h,b
    ld l,c
    add.s hl,de
    ret

flight_clamp_rate16:
    bit 7,h
    jr nz,@negative
    ld a,h
    cp flight_rate_limit_high
    ret c
    jr nz,@positive_limit
    ld a,l
    or a
    ret z
@positive_limit:
    ld hl,flight_rate_limit
    ret
@negative:
    ld a,h
    cp flight_rate_negative_limit_high
    ret nc
    ld hl,-flight_rate_limit
    ret

; Transpose the retained local-to-world matrix so the same qualified row
; transform converts world velocity into body coordinates.
flight_build_orientation_transpose:
    ld a,(object_state+p3d_object_orientation+0)
    ld (flight_orientation_transpose+0),a
    ld a,(object_state+p3d_object_orientation+1)
    ld (flight_orientation_transpose+1),a
    ld a,(object_state+p3d_object_orientation+6)
    ld (flight_orientation_transpose+2),a
    ld a,(object_state+p3d_object_orientation+7)
    ld (flight_orientation_transpose+3),a
    ld a,(object_state+p3d_object_orientation+12)
    ld (flight_orientation_transpose+4),a
    ld a,(object_state+p3d_object_orientation+13)
    ld (flight_orientation_transpose+5),a

    ld a,(object_state+p3d_object_orientation+2)
    ld (flight_orientation_transpose+6),a
    ld a,(object_state+p3d_object_orientation+3)
    ld (flight_orientation_transpose+7),a
    ld a,(object_state+p3d_object_orientation+8)
    ld (flight_orientation_transpose+8),a
    ld a,(object_state+p3d_object_orientation+9)
    ld (flight_orientation_transpose+9),a
    ld a,(object_state+p3d_object_orientation+14)
    ld (flight_orientation_transpose+10),a
    ld a,(object_state+p3d_object_orientation+15)
    ld (flight_orientation_transpose+11),a

    ld a,(object_state+p3d_object_orientation+4)
    ld (flight_orientation_transpose+12),a
    ld a,(object_state+p3d_object_orientation+5)
    ld (flight_orientation_transpose+13),a
    ld a,(object_state+p3d_object_orientation+10)
    ld (flight_orientation_transpose+14),a
    ld a,(object_state+p3d_object_orientation+11)
    ld (flight_orientation_transpose+15),a
    ld a,(object_state+p3d_object_orientation+16)
    ld (flight_orientation_transpose+16),a
    ld a,(object_state+p3d_object_orientation+17)
    ld (flight_orientation_transpose+17),a
    ret

; Forward airspeed is -body Z.  Lift grows linearly at this first fidelity:
; speed*(1/128+1/512).  It therefore falls smoothly below gravity at low
; speed.  Large body-Y/forward ratios halve or quarter lift as a cheap
; high-angle-of-attack/stall proxy.
flight_compute_aero_scalars:
    FLIGHT_LOAD_HL16 flight_body_velocity_q8+p3d_vec3_z
    bit 7,h
    jr z,@no_forward_speed
    xor a
    sub l
    ld l,a
    ld a,0
    sbc a,h
    ld h,a
    ld de,flight_velocity_limit_q8
    or a
    sbc.s hl,de
    jr c,@speed_unclamped
    ld hl,flight_velocity_limit_q8
    jr @store_speed
@speed_unclamped:
    add.s hl,de
    jr @store_speed
@no_forward_speed:
    ld hl,0
@store_speed:
    FLIGHT_STORE_HL16 flight_airspeed_q8

    ld b,h
    ld c,l
    ld a,7
@lift_shift_7:
    srl h
    rr l
    dec a
    jr nz,@lift_shift_7
    ld d,h
    ld e,l
    ld h,b
    ld l,c
    ld a,9
@lift_shift_9:
    srl h
    rr l
    dec a
    jr nz,@lift_shift_9
    add.s hl,de
    FLIGHT_STORE_HL16 flight_lift_q8

; Compute absolute body-Y and compare it with forward speed and half-speed.
    FLIGHT_LOAD_HL16 flight_body_velocity_q8+p3d_vec3_y
    bit 7,h
    jr z,@body_y_magnitude
    xor a
    sub l
    ld l,a
    ld a,0
    sbc a,h
    ld h,a
@body_y_magnitude:
    FLIGHT_LOAD_DE16 flight_airspeed_q8
    push hl
    or a
    sbc.s hl,de
    pop hl
    jr c,@compare_half_speed
    call flight_quarter_lift
    jr @thrust
@compare_half_speed:
    srl d
    rr e
    or a
    sbc.s hl,de
    jr c,@thrust
    call flight_half_lift

@thrust:
; The piecewise-monotonic map (throttle>>3)-(throttle>>6) retains the exact
; 160 -> 18 cruise trim while reserving 255 -> 28 for runway acceleration.
    ld a,(flight_throttle)
    ld b,a
    srl a
    srl a
    srl a
    ld c,a
    ld a,b
    srl a
    srl a
    srl a
    srl a
    srl a
    srl a
    ld b,a
    ld a,c
    sub b
    ld (flight_thrust_q8),a
    xor a
    ld (flight_thrust_q8+1),a
    ret

flight_half_lift:
    FLIGHT_LOAD_HL16 flight_lift_q8
    srl h
    rr l
    FLIGHT_STORE_HL16 flight_lift_q8
    ret

flight_quarter_lift:
    call flight_half_lift
    jr flight_half_lift

; Transform local (0,lift,-thrust) through the retained Q15 orientation, then
; add world-axis linear drag and gravity.
flight_build_world_force:
    xor a
    ld (flight_local_force_q8+p3d_vec3_x),a
    ld (flight_local_force_q8+p3d_vec3_x+1),a
    ld a,(flight_lift_q8)
    ld (flight_local_force_q8+p3d_vec3_y),a
    ld a,(flight_lift_q8+1)
    ld (flight_local_force_q8+p3d_vec3_y+1),a
    FLIGHT_LOAD_HL16 flight_thrust_q8
    xor a
    sub l
    ld l,a
    ld a,0
    sbc a,h
    ld h,a
    FLIGHT_STORE_HL16 flight_local_force_q8+p3d_vec3_z

    ld hl,flight_local_force_q8
    ld de,flight_force_q8
    ld bc,p3d_vec3_size
    ldir
    ld ix,flight_force_q8
    ld iy,object_state+p3d_object_orientation
    call p3d_mat3_mul_vec3_16
    ret c

; X drag.
    FLIGHT_LOAD_HL16 flight_force_q8+p3d_vec3_x
    FLIGHT_LOAD_DE16 flight_velocity_q8+p3d_vec3_x
    call flight_drag_from_velocity_de
    call p3d_sadd16
    FLIGHT_STORE_HL16 flight_force_q8+p3d_vec3_x

; Y drag plus gravity.
    FLIGHT_LOAD_HL16 flight_force_q8+p3d_vec3_y
    FLIGHT_LOAD_DE16 flight_velocity_q8+p3d_vec3_y
    call flight_drag_from_velocity_de
    call p3d_sadd16
    ld de,flight_gravity_step_q8
    call p3d_sadd16
    FLIGHT_STORE_HL16 flight_force_q8+p3d_vec3_y

; Z drag.
    FLIGHT_LOAD_HL16 flight_force_q8+p3d_vec3_z
    FLIGHT_LOAD_DE16 flight_velocity_q8+p3d_vec3_z
    call flight_drag_from_velocity_de
    call p3d_sadd16
    FLIGHT_STORE_HL16 flight_force_q8+p3d_vec3_z
    or a
    ret

; Input DE=signed Q8 velocity.  Output DE=opposing integer drag; the velocity
; high byte is its signed whole-count portion, so this is exactly -(v>>8).
flight_drag_from_velocity_de:
    ld a,d
    ld e,a
    add a,a
    sbc a,a
    ld d,a
    xor a
    sub e
    ld e,a
    ld a,0
    sbc a,d
    ld d,a
    ret

; Unit mass is explicit in this first fixture, so normalized force and
; acceleration have identical integer values.  Keeping both vectors makes the
; force -> acceleration -> velocity contract visible and leaves one isolated
; place for a later aircraft-mass reciprocal.
flight_resolve_acceleration:
    ld hl,flight_force_q8
    ld de,flight_acceleration_q8
    ld bc,p3d_vec3_size
    ldir
    ret

flight_limit_velocity:
    ld ix,flight_velocity_q8
    ld l,(ix+p3d_vec3_x)
    ld h,(ix+p3d_vec3_x+1)
    call flight_clamp_velocity16
    ld (ix+p3d_vec3_x),l
    ld (ix+p3d_vec3_x+1),h
    ld l,(ix+p3d_vec3_y)
    ld h,(ix+p3d_vec3_y+1)
    call flight_clamp_velocity16
    ld (ix+p3d_vec3_y),l
    ld (ix+p3d_vec3_y+1),h
    ld l,(ix+p3d_vec3_z)
    ld h,(ix+p3d_vec3_z+1)
    call flight_clamp_velocity16
    ld (ix+p3d_vec3_z),l
    ld (ix+p3d_vec3_z+1),h
    ret

flight_clamp_velocity16:
    bit 7,h
    jr nz,@negative
    ld a,h
    cp flight_velocity_limit_high
    ret c
    jr nz,@positive_limit
    ld a,l
    or a
    ret z
@positive_limit:
    ld hl,flight_velocity_limit_q8
    ret
@negative:
    ld a,h
    cp flight_velocity_negative_limit_high
    ret nc
    ld hl,-flight_velocity_limit_q8
    ret

; This is only the support constraint required to begin on one known runway.
; It is intentionally not terrain collision: C1 will own regional height and
; probable-contact tests.  Above takeoff speed, positive vertical inertia
; releases the aircraft; otherwise the runway cancels downward velocity.
flight_apply_runway_support:
    ld a,(flight_flags)
    and flight_flag_on_ground
    ret z
    FLIGHT_LOAD_HL16 flight_velocity_q8+p3d_vec3_y
    bit 7,h
    jr nz,@support
    ld a,h
    or l
    jr z,@support
    FLIGHT_LOAD_HL16 flight_airspeed_q8
    ld de,flight_takeoff_speed_q8
    or a
    sbc.s hl,de
    jr c,@support
    ld a,(flight_flags)
    and 0ffh-flight_flag_on_ground
    ld (flight_flags),a
    ret
@support:
    xor a
    ld (flight_velocity_q8+p3d_vec3_y),a
    ld (flight_velocity_q8+p3d_vec3_y+1),a
    ret

; Add each signed 16-bit Q8 velocity to its exact three-byte 16.8 position.
; Unsuffixed 24-bit memory transfers are correct here because each target is
; explicitly `dl`; no access below touches a `dw` field with a wide register.
flight_integrate_position:
    ld de,0
    ld a,(flight_velocity_q8+p3d_vec3_x+1)
    bit 7,a
    jr z,@x_extended
    ld de,0ff0000h
@x_extended:
    FLIGHT_LOAD_DE16 flight_velocity_q8+p3d_vec3_x
    ld hl,(flight_position_x_q8)
    add hl,de
    ld (flight_position_x_q8),hl

    ld a,(flight_flags)
    and flight_flag_on_ground
    jr nz,@ground_y
    ld de,0
    ld a,(flight_velocity_q8+p3d_vec3_y+1)
    bit 7,a
    jr z,@y_extended
    ld de,0ff0000h
@y_extended:
    FLIGHT_LOAD_DE16 flight_velocity_q8+p3d_vec3_y
    ld hl,(flight_position_y_q8)
    add hl,de
    ld (flight_position_y_q8),hl
    jr @z
@ground_y:
    ld hl,(flight_ground_y_q8)
    ld (flight_position_y_q8),hl

@z:
    ld de,0
    ld a,(flight_velocity_q8+p3d_vec3_z+1)
    bit 7,a
    jr z,@z_extended
    ld de,0ff0000h
@z_extended:
    FLIGHT_LOAD_DE16 flight_velocity_q8+p3d_vec3_z
    ld hl,(flight_position_z_q8)
    add hl,de
    ld (flight_position_z_q8),hl
    ret

; Publish the integer words (bytes 1..2) to the existing object/camera pose.
flight_publish_position:
    ld ix,object_state
    ld a,(flight_position_x_q8+1)
    ld (ix+p3d_object_world_position+p3d_vec3_x),a
    ld a,(flight_position_x_q8+2)
    ld (ix+p3d_object_world_position+p3d_vec3_x+1),a
    ld a,(flight_position_y_q8+1)
    ld (ix+p3d_object_world_position+p3d_vec3_y),a
    ld a,(flight_position_y_q8+2)
    ld (ix+p3d_object_world_position+p3d_vec3_y+1),a
    ld a,(flight_position_z_q8+1)
    ld (ix+p3d_object_world_position+p3d_vec3_z),a
    ld a,(flight_position_z_q8+2)
    ld (ix+p3d_object_world_position+p3d_vec3_z+1),a
    ld a,(ix+p3d_object_dirty)
    or p3d_object_dirty_position
    ld (ix+p3d_object_dirty),a
    ret

; Flight-owned data.  Positions and ground height are deliberately exact
; three-byte fields; the remaining vectors are exact little-endian words.
flight_state:
flight_position_x_q8: dl 0
flight_position_y_q8: dl 0
flight_position_z_q8: dl 0
flight_ground_y_q8: dl 0
flight_velocity_q8: ds p3d_vec3_size
flight_force_q8: ds p3d_vec3_size
flight_acceleration_q8: ds p3d_vec3_size
flight_angular_acceleration: ds p3d_vec3_size
flight_body_velocity_q8: ds p3d_vec3_size
flight_local_force_q8: ds p3d_vec3_size
flight_orientation_transpose: ds p3d_mat3_size
flight_airspeed_q8: dw 0
flight_lift_q8: dw 0
flight_thrust_q8: dw 0
flight_throttle: db 0
flight_pitch_control: db 0
flight_roll_control: db 0
flight_yaw_control: db 0
flight_flags: db 0
flight_state_end:
flight_state_size: equ flight_state_end-flight_state
