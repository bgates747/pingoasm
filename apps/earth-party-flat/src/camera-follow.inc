; =============================================================================

; ADL warning: LD.S changes the instruction's address/stack mode; it is not a
; harmless 16-bit operand-size suffix. Keep camera scalars in ordinary ADL
; memory and transfer their two bytes explicitly.
    macro CAMERA_LOAD_HL address
        ld a,(address)
        ld l,a
        ld a,(address+1)
        ld h,a
    endmacro

    macro CAMERA_LOAD_DE address
        ld a,(address)
        ld e,a
        ld a,(address+1)
        ld d,a
    endmacro

    macro CAMERA_STORE_HL address
        ld a,l
        ld (address),a
        ld a,h
        ld (address+1),a
    endmacro

    macro CAMERA_STORE_BC address
        ld a,c
        ld (address),a
        ld a,b
        ld (address+1),a
    endmacro

    macro CAMERA_STORE_DE address
        ld a,e
        ld (address),a
        ld a,d
        ld (address+1),a
    endmacro
; Earth-relative camera positioning for the eZ80-owned moveair world state.
;
; The camera retains a horizontal radius, world Y, and sweep around Earth's
; world-space center. Camera orientation is solved independently from the
; retained Jet pose: Earth is only the position reference and is never the
; aim target. Pingo receives only dirty absolute camera commands immediately
; before the next render, never while the preceding render is in flight.
; =============================================================================

; Initialize the persistent camera, establish its first aim, and submit both
; absolute pose components before the setup barrier.
init_camera_tracking:
    ld hl,camera_initial_horizontal_radius
    CAMERA_STORE_HL camera_horizontal_radius
    ld hl,camera_initial_world_y
    CAMERA_STORE_HL camera_world_y
    ld hl,camera_initial_sweep
    CAMERA_STORE_HL camera_sweep
    xor a
    ld (camera_step_changed),a
    ld ix,camera_state
    ld iy,camera_initial_position
    ld hl,sid
    call p3d_camera_init16
    call aim_camera_at_object
    jp sync_camera_state

; Apply one fixed-step camera-control quantum. Page Up/Page Down change world
; Y. Home/End scale the Earth-relative radial vector inward/outward. Insert
; and Delete change sweep around world +Y while preserving horizontal radius
; and world Y, and therefore preserving elevation above the world X-Z plane.
simulate_camera_step:
    xor a
    ld (camera_step_changed),a
    ld ix,keyboard_masks

; Opposed keys cancel rather than applying two rounded operations.
    bit 7,(ix+7)                       ; Page Up
    jr z,@page_down_only
    bit 6,(ix+9)                       ; Page Down
    jr nz,@vertical_done
    call camera_world_y_up
    jr @vertical_changed
@page_down_only:
    bit 6,(ix+9)
    jr z,@vertical_done
    call camera_world_y_down
@vertical_changed:
    ld a,1
    ld (camera_step_changed),a
@vertical_done:

    bit 6,(ix+7)                       ; Home
    jr z,@end_only
    bit 1,(ix+13)                      ; Copy/End
    jr nz,@radial_done
    call camera_radial_in
    jr @radial_changed
@end_only:
    bit 1,(ix+13)
    jr z,@radial_done
    call camera_radial_out
@radial_changed:
    ld a,1
    ld (camera_step_changed),a
@radial_done:

    bit 5,(ix+7)                       ; Insert: increase sweep
    jr z,@delete_only
    bit 1,(ix+11)                      ; Delete: decrease sweep
    jr nz,@sweep_done
    call camera_sweep_increase
    jr @sweep_changed
@delete_only:
    bit 1,(ix+11)
    jr z,@sweep_done
    call camera_sweep_decrease
@sweep_changed:
    ld a,1
    ld (camera_step_changed),a
@sweep_done:

    ld a,(camera_step_changed)
    or a
    ret z
    jp rebuild_camera_position

camera_world_y_up:
    CAMERA_LOAD_HL camera_world_y
    ld de,camera_world_y_step
    call p3d_sadd16
    jr c,@maximum
    bit 7,h
    jr nz,@store
    push hl
    ld de,camera_world_y_limit
    or a
    sbc.s hl,de
    pop hl
    jr c,@store
    jr z,@store
@maximum:
    ld hl,camera_world_y_limit
@store:
    CAMERA_STORE_HL camera_world_y
    ret

camera_world_y_down:
    CAMERA_LOAD_HL camera_world_y
    ld de,-camera_world_y_step
    call p3d_sadd16
    jr c,@minimum
    bit 7,h
    jr z,@store
    push hl
    ld de,-camera_world_y_limit
    or a
    sbc.s hl,de
    pop hl
    jr nc,@store
@minimum:
    ld hl,-camera_world_y_limit
@store:
    CAMERA_STORE_HL camera_world_y
    ret

; Return signed truncation toward zero of HL/256 in DE. Any nonzero input
; returns at least one count so radial controls cannot stall near an axis.
; HL is preserved.
camera_signed_fraction_256:
    push hl
    ld de,0
    ld a,h
    or l
    jr z,@done
    bit 7,h
    jr nz,@negative
    ld e,h
    ld a,e
    or a
    jr nz,@done
    inc e
    jr @done
@negative:
    xor a
    sub l
    ld l,a
    ld a,0
    sbc a,h
    ld h,a
    ld e,h
    ld a,e
    or a
    jr nz,@negate
    inc e
@negate:
    xor a
    sub e
    ld e,a
    ld a,0
    sbc a,d
    ld d,a
@done:
    pop hl
    ret

camera_radial_in:
; Horizontal radius is unsigned and bounded away from zero.
    CAMERA_LOAD_HL camera_horizontal_radius
    ld e,h
    ld d,0
    ld a,e
    or a
    jr nz,@radius_delta_ready
    inc e
@radius_delta_ready:
    or a
    sbc.s hl,de
    push hl
    ld de,camera_horizontal_radius_min
    or a
    sbc.s hl,de
    pop hl
    jr nc,@radius_store
    ld hl,camera_horizontal_radius_min
@radius_store:
    CAMERA_STORE_HL camera_horizontal_radius

; Apply the same 1/256-style signed scaling to world Y, moving it toward zero.
    CAMERA_LOAD_HL camera_world_y
    call camera_signed_fraction_256
    xor a
    sub e
    ld e,a
    ld a,0
    sbc a,d
    ld d,a
    call p3d_sadd16
    CAMERA_STORE_HL camera_world_y
    ret

camera_radial_out:
    CAMERA_LOAD_HL camera_horizontal_radius
    ld e,h
    ld d,0
    ld a,e
    or a
    jr nz,@radius_delta_ready
    inc e
@radius_delta_ready:
    add.s hl,de
    push hl
    ld de,camera_horizontal_radius_max
    or a
    sbc.s hl,de
    pop hl
    jr c,@radius_store
    jr z,@radius_store
    ld hl,camera_horizontal_radius_max
@radius_store:
    CAMERA_STORE_HL camera_horizontal_radius

; Scale world Y away from zero, clamping inside the safe signed scene range.
    CAMERA_LOAD_HL camera_world_y
    call camera_signed_fraction_256
    call p3d_sadd16
    jr c,@clamp_y
    bit 7,h
    jr nz,@test_minimum
    push hl
    ld de,camera_world_y_limit
    or a
    sbc.s hl,de
    pop hl
    jr c,@store_y
    jr z,@store_y
    ld hl,camera_world_y_limit
    jr @store_y
@test_minimum:
    push hl
    ld de,-camera_world_y_limit
    or a
    sbc.s hl,de
    pop hl
    jr nc,@store_y
    ld hl,-camera_world_y_limit
    jr @store_y
@clamp_y:
    bit 7,h
    jr z,@positive_limit
    ld hl,-camera_world_y_limit
    jr @store_y
@positive_limit:
    ld hl,camera_world_y_limit
@store_y:
    CAMERA_STORE_HL camera_world_y
    ret

camera_sweep_increase:
    CAMERA_LOAD_HL camera_sweep
    ld de,camera_sweep_step
    add.s hl,de                         ; signed turn domain wraps naturally
    jr camera_sweep_store

camera_sweep_decrease:
    CAMERA_LOAD_HL camera_sweep
    ld de,-camera_sweep_step
    add.s hl,de
camera_sweep_store:
    CAMERA_STORE_HL camera_sweep
    ret

; Regenerate Cartesian position from canonical cylindrical state. Repeated
; sweep operations therefore cannot accumulate a spiralling radius error.
rebuild_camera_position:
    CAMERA_LOAD_HL camera_sweep
    call p3d_sincos16
    CAMERA_STORE_BC camera_sweep_sine
    CAMERA_STORE_DE camera_sweep_cosine

    CAMERA_LOAD_HL camera_horizontal_radius
    CAMERA_LOAD_DE camera_sweep_sine
    call p3d_smul_norm16
    ret c
    CAMERA_STORE_HL camera_position_work+p3d_vec3_x

    CAMERA_LOAD_HL camera_world_y
    CAMERA_STORE_HL camera_position_work+p3d_vec3_y

    CAMERA_LOAD_HL camera_horizontal_radius
    CAMERA_LOAD_DE camera_sweep_cosine
    call p3d_smul_norm16
    ret c
    ld de,earth_z
    call p3d_sadd16
    ret c
    CAMERA_STORE_HL camera_position_work+p3d_vec3_z

; Avoid dirtying an already clamped pose repeatedly.
    ld ix,camera_state
    ld iy,camera_position_work
    ld a,(iy+p3d_vec3_x)
    cp (ix+p3d_camera_world_position+p3d_vec3_x)
    jr nz,@commit
    ld a,(iy+p3d_vec3_x+1)
    cp (ix+p3d_camera_world_position+p3d_vec3_x+1)
    jr nz,@commit
    ld a,(iy+p3d_vec3_y)
    cp (ix+p3d_camera_world_position+p3d_vec3_y)
    jr nz,@commit
    ld a,(iy+p3d_vec3_y+1)
    cp (ix+p3d_camera_world_position+p3d_vec3_y+1)
    jr nz,@commit
    ld a,(iy+p3d_vec3_z)
    cp (ix+p3d_camera_world_position+p3d_vec3_z)
    jr nz,@commit
    ld a,(iy+p3d_vec3_z+1)
    cp (ix+p3d_camera_world_position+p3d_vec3_z+1)
    ret z
@commit:
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
    or a
    ret

; Re-aim after a quantum that changed either the Jet's retained position or
; the camera's Earth-relative position. The target is always the Jet.
update_camera_tracking:
    ld ix,object_state
    bit 0,(ix+p3d_object_dirty)
    jr nz,aim_camera_at_object
    ld a,(camera_step_changed)
    or a
    ret z

aim_camera_at_object:
    ld ix,camera_state
    ld iy,object_state
    ld a,camera_tracking_roll_policy
    call p3d_camera_aim_at_object16
    ret nc

; If the Jet exactly coincides with the camera, retain the last valid frame.
; The following non-coincident simulation tick will resume ordinary tracking.
    or a
    ret

; Send each dirty absolute camera component through the same current-Pingo VDU
; helpers used by the historical applications. This routine is called only
; while no render is in flight. IX is saved around each VDU transfer because
; the transport does not publish a general register-preservation contract.
sync_camera_state:
    ld ix,camera_state
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
