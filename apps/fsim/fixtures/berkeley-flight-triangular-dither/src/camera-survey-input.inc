; =============================================================================
; Direct, upright camera controls for the Berkeley terrain survey fixture.
;
; There is deliberately no proxy object, velocity integrator, flight model, or
; collision query in this path.  Each 30 Hz quantum decodes held keys into one
; commanded displacement and an absolute pitch/yaw update.  Horizontal motion
; is rotated by yaw alone; pitch can therefore never turn forward motion into
; a climb or dive, and Page Up/Down remain exact world-Y translations.
; =============================================================================

; ADL warning: an unsuffixed multi-byte memory load/store is 24-bit.  Every
; scalar below is a wire-compatible 16-bit word and is transferred bytewise.
    MACRO SURVEY_LOAD_HL ADDRESS
        ld a,(ADDRESS)
        ld l,a
        ld a,(ADDRESS+1)
        ld h,a
    ENDMACRO

    MACRO SURVEY_STORE_HL ADDRESS
        ld a,l
        ld (ADDRESS),a
        ld a,h
        ld (ADDRESS+1),a
    ENDMACRO

    MACRO SURVEY_NEGATE_HL
        xor a
        sub l
        ld l,a
        ld a,0
        sbc a,h
        ld h,a
    ENDMACRO

; Establish exactly the same initial pose as fixture 3.  p3d_camera_init16
; copies camera_initial_position and supplies zero Euler rotation, zero roll,
; and an identity retained orientation.
init_camera_survey:
    ld hl,survey_translation_rate_initial
    SURVEY_STORE_HL survey_translation_rate
    xor a
    ld (survey_speed_keys_down),a
    ld ix,camera_state
    ld iy,camera_initial_position
    ld hl,sid
    call p3d_camera_init16
    jp sync_camera_state

; One deterministic input quantum.  Changing the speed setting alone does not
; dirty the camera or request a redundant render.
simulate_camera_step:
    call survey_update_translation_rate
    call survey_update_rotation
    jp survey_update_translation

; Minus and Equals choose the next slower/faster power-of-two rate only on a
; rising edge.  Holding a key cannot race through the ladder; opposed keys
; cancel.  MOS maps main Minus to byte 2 bit 7 and main Equals/Plus to byte 11
; bit 5 (BBC physical key 94).
survey_update_translation_rate:
    ld ix,keyboard_masks
    ld b,0
    bit 7,(ix+2)                       ; Minus
    jr z,@minus_ready
    set 0,b
@minus_ready:
    bit 5,(ix+11)                      ; Equals
    jr z,@current_ready
    set 1,b
@current_ready:
    ld a,(survey_speed_keys_down)
    ld c,a                             ; C = preceding held state
    ld a,b
    ld (survey_speed_keys_down),a
    cp 3
    ret z                              ; opposed keys cancel
    ld a,c
    cpl
    and b                              ; A = newly pressed keys
    cp 1
    jr z,survey_translation_rate_down
    cp 2
    jr z,survey_translation_rate_up
    ret

survey_translation_rate_down:
    SURVEY_LOAD_HL survey_translation_rate
    srl h
    rr l
    push hl
    ld de,survey_translation_rate_min
    or a
    sbc.s hl,de
    pop hl
    jr nc,@store
    ld hl,survey_translation_rate_min
@store:
    SURVEY_STORE_HL survey_translation_rate
    ret

survey_translation_rate_up:
    SURVEY_LOAD_HL survey_translation_rate
    add.s hl,hl
    push hl
    ld de,survey_translation_rate_max
    or a
    sbc.s hl,de
    pop hl
    jr c,@store
    jr z,@store
    ld hl,survey_translation_rate_max
@store:
    SURVEY_STORE_HL survey_translation_rate
    ret

; Arrow keys own absolute camera pitch/yaw. Camera Euler angles act inversely
; on the view: Up/Left subtract from the rendered pitch/yaw, while Down/Right
; add. Opposed keys cancel. Pitch is held
; one raw angle word short of either exact vertical, and roll is forcibly zero
; whenever an angular command is applied.
survey_update_rotation:
    xor a
    ld (survey_rotation_changed),a
    ld ix,keyboard_masks

    bit 1,(ix+7)                       ; Up
    jr z,@down_only
    bit 1,(ix+5)                       ; Down
    jr nz,@pitch_done
    call survey_pitch_up
    jr @pitch_changed
@down_only:
    bit 1,(ix+5)
    jr z,@pitch_done
    call survey_pitch_down
@pitch_changed:
    ld a,1
    ld (survey_rotation_changed),a
@pitch_done:

    bit 1,(ix+3)                       ; Left
    jr z,@right_only
    bit 1,(ix+15)                      ; Right
    jr nz,@yaw_done
    call survey_yaw_left
    jr @yaw_changed
@right_only:
    bit 1,(ix+15)
    jr z,@yaw_done
    call survey_yaw_right
@yaw_changed:
    ld a,1
    ld (survey_rotation_changed),a
@yaw_done:

    ld a,(survey_rotation_changed)
    or a
    ret z

; The no-roll invariant is executable rather than merely conventional.
    xor a
    ld (camera_state+p3d_camera_pingo_rotation+p3d_vec3_z),a
    ld (camera_state+p3d_camera_pingo_rotation+p3d_vec3_z+1),a

; Keep the retained camera orientation coherent with the emitted Euler words.
; This closed form is Ry(yaw)*Rx(pitch), explicitly with roll zero.
    ld ix,camera_state+p3d_camera_orientation
    ld iy,camera_state+p3d_camera_pingo_rotation
    call p3d_camera_mat3_from_euler_fine16
    ld ix,camera_state
    ld a,(ix+p3d_camera_dirty)
    or p3d_camera_dirty_rotation
    ld (ix+p3d_camera_dirty),a
    ret

survey_pitch_up:
    SURVEY_LOAD_HL camera_state+p3d_camera_pingo_rotation+p3d_vec3_x
    ld de,-survey_angular_step
    add.s hl,de
; The bound comparison must be signed.  A plain unsigned compare would treat
; every positive pitch as "below" 0xe001 and snap directly to -8191 when the
; pilot reversed away from the positive limit.
    bit 7,h
    jr z,@store
    push hl
    ld de,-survey_pitch_limit
    or a
    sbc.s hl,de
    pop hl
    jr nc,@store
    ld hl,-survey_pitch_limit
@store:
    SURVEY_STORE_HL camera_state+p3d_camera_pingo_rotation+p3d_vec3_x
    ret

survey_pitch_down:
    SURVEY_LOAD_HL camera_state+p3d_camera_pingo_rotation+p3d_vec3_x
    ld de,survey_angular_step
    add.s hl,de
; Likewise, a negative candidate is already below the positive upper bound.
; Guarding its sign prevents a reversal from -8191 snapping to +8191.
    bit 7,h
    jr nz,@store
    push hl
    ld de,survey_pitch_limit
    or a
    sbc.s hl,de
    pop hl
    jr c,@store
    jr z,@store
    ld hl,survey_pitch_limit
@store:
    SURVEY_STORE_HL camera_state+p3d_camera_pingo_rotation+p3d_vec3_x
    ret

survey_yaw_left:
    SURVEY_LOAD_HL camera_state+p3d_camera_pingo_rotation+p3d_vec3_y
    ld de,survey_angular_step
    add.s hl,de                         ; intentional 16-bit turn wrap
    SURVEY_STORE_HL camera_state+p3d_camera_pingo_rotation+p3d_vec3_y
    ret

survey_yaw_right:
    SURVEY_LOAD_HL camera_state+p3d_camera_pingo_rotation+p3d_vec3_y
    ld de,-survey_angular_step
    add.s hl,de                         ; intentional 16-bit turn wrap
    SURVEY_STORE_HL camera_state+p3d_camera_pingo_rotation+p3d_vec3_y
    ret

; Build one local XZ displacement from WASD, rotate it around world Y using
; only the absolute camera yaw, then append Page Up/Down as an unrotated world
; Y displacement.  p3d_vec3_translate16 commits all three components together
; or leaves the camera unchanged at a signed-coordinate boundary.
survey_update_translation:
    xor a
    ld (survey_translation_delta+p3d_vec3_x+0),a
    ld (survey_translation_delta+p3d_vec3_x+1),a
    ld (survey_translation_delta+p3d_vec3_y+0),a
    ld (survey_translation_delta+p3d_vec3_y+1),a
    ld (survey_translation_delta+p3d_vec3_z+0),a
    ld (survey_translation_delta+p3d_vec3_z+1),a

    ld ix,keyboard_masks

; W/S: forward local -Z / backward local +Z.
    bit 1,(ix+4)                        ; W
    jr z,@backward_only
    bit 1,(ix+10)                       ; S
    jr nz,@forward_done
    SURVEY_LOAD_HL survey_translation_rate
    SURVEY_NEGATE_HL
    SURVEY_STORE_HL survey_translation_delta+p3d_vec3_z
    jr @forward_done
@backward_only:
    bit 1,(ix+10)
    jr z,@forward_done
    SURVEY_LOAD_HL survey_translation_rate
    SURVEY_STORE_HL survey_translation_delta+p3d_vec3_z
@forward_done:

; A/D: left local -X / right local +X.
    bit 1,(ix+8)                        ; A
    jr z,@right_translation_only
    bit 2,(ix+6)                        ; D
    jr nz,@horizontal_ready
    SURVEY_LOAD_HL survey_translation_rate
    SURVEY_NEGATE_HL
    SURVEY_STORE_HL survey_translation_delta+p3d_vec3_x
    jr @horizontal_ready
@right_translation_only:
    bit 2,(ix+6)
    jr z,@horizontal_ready
    SURVEY_LOAD_HL survey_translation_rate
    SURVEY_STORE_HL survey_translation_delta+p3d_vec3_x
@horizontal_ready:

; Skip the trigonometric path for a vertical-only command.
    ld ix,survey_translation_delta
    ld a,(ix+p3d_vec3_x+0)
    or (ix+p3d_vec3_x+1)
    or (ix+p3d_vec3_z+0)
    or (ix+p3d_vec3_z+1)
    jr z,@vertical
    SURVEY_LOAD_HL camera_state+p3d_camera_pingo_rotation+p3d_vec3_y
    ld ix,survey_translation_delta
    call p3d_vec3_rotate_y16
    jr nc,@vertical
; This cannot overflow at the bounded rate, but fail closed if the shared
; arithmetic contract ever changes.
    xor a
    ld (survey_translation_delta+p3d_vec3_x+0),a
    ld (survey_translation_delta+p3d_vec3_x+1),a
    ld (survey_translation_delta+p3d_vec3_z+0),a
    ld (survey_translation_delta+p3d_vec3_z+1),a

@vertical:
    ld ix,keyboard_masks
    bit 7,(ix+7)                        ; Page Up
    jr z,@page_down_only
    bit 6,(ix+9)                        ; Page Down
    jr nz,@translation_ready
    SURVEY_LOAD_HL survey_translation_rate
    SURVEY_STORE_HL survey_translation_delta+p3d_vec3_y
    jr @translation_ready
@page_down_only:
    bit 6,(ix+9)
    jr z,@translation_ready
    SURVEY_LOAD_HL survey_translation_rate
    SURVEY_NEGATE_HL
    SURVEY_STORE_HL survey_translation_delta+p3d_vec3_y

@translation_ready:
    ld ix,survey_translation_delta
    ld a,(ix+p3d_vec3_x+0)
    or (ix+p3d_vec3_x+1)
    or (ix+p3d_vec3_y+0)
    or (ix+p3d_vec3_y+1)
    or (ix+p3d_vec3_z+0)
    or (ix+p3d_vec3_z+1)
    ret z

    ld ix,camera_state+p3d_camera_world_position
    ld iy,survey_translation_delta
    call p3d_vec3_translate16
    ret c
    ld ix,camera_state
    ld a,(ix+p3d_camera_dirty)
    or p3d_camera_dirty_position
    ld (ix+p3d_camera_dirty),a
    ret
