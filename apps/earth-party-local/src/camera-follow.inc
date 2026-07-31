; =============================================================================
; Fixed-position camera tracking for the eZ80-owned moveair world state.
;
; Camera orientation is solved on simulation ticks from retained object and
; camera poses. Pingo receives only dirty absolute camera commands immediately
; before the next render, never while the preceding render is in flight.
; =============================================================================

; Initialize the persistent camera, establish its first aim, and submit both
; absolute pose components before the setup barrier.
init_camera_tracking:
    ld ix,camera_state
    ld iy,camera_initial_position
    ld hl,sid
    call p3d_camera_init16
    call aim_camera_at_object
    jp sync_camera_state

; Re-aim only after a quantum that changed the target's world position.
; A translation dirty bit may span several catch-up quanta; recomputing in
; that case simply keeps the camera coalesced onto the newest retained pose.
update_camera_tracking:
    ld ix,object_state
    bit 0,(ix+p3d_object_dirty)
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
