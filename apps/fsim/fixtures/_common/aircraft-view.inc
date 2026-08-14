; =============================================================================
; Cockpit/chase camera policy for the streamed light-flight fixture.
;
; Required caller symbols:
;   object_state    one retained p3d_object state for the aircraft
;   camera_state    one initialized p3d_camera state
;   keyboard_masks  the ordinary 16-byte OR-latched MOS keyboard map
;
; Required P3D routines/constants come from the qualified agon/3d.inc:
;   p3d_mat3_mul_vec3_16, p3d_vec3_translate16,
;   p3d_camera_aim_at_point16, p3d_camera_roll_upright, and structure offsets.
;
; The caller invokes aircraft_view_handle_toggle and aircraft_view_update_camera
; once per completed physics quantum.  It publishes dirty camera state, the
; aircraft pose, and any visibility change only while no render is in flight.
; =============================================================================

aircraft_view_mode_cockpit: equ 0
aircraft_view_mode_chase: equ 1

; Physical V is BBC/MOS virtual key 100: (100-1)/8 = byte 12, bit 3.
aircraft_view_key_byte: equ 12
aircraft_view_key_bit: equ 3

; Local -Z is forward.  Pingo translation words are 1/16-metre counts.
aircraft_view_cockpit_eye_local:
    dw 0,20,-48                       ; 0,+1.25,-3.00 metres
aircraft_view_chase_camera_local:
    dw 0,80,288                       ; 0,+5.00,+18.00 metres
aircraft_view_chase_target_local:
    dw 0,16,-48                       ; 0,+1.00,-3.00 metres

; Start in cockpit mode.  Visibility is deliberately dirty so the integration
; must deactivate the stable aircraft object before its first render.
aircraft_view_init:
    xor a
    ld (aircraft_view_mode),a
    ld (aircraft_view_key_latched),a
    ld (aircraft_view_aircraft_active),a
    inc a
    ld (aircraft_view_mode_changed),a
    ld (aircraft_view_visibility_dirty),a
    jp aircraft_view_update_camera

; Rising edge only: down toggles once, held does nothing, release only rearms.
; A changed mode also dirties aircraft visibility.  Entering chase invalidates
; old look-at branch memory so the qualified solver starts canonically.
aircraft_view_handle_toggle:
    xor a
    ld (aircraft_view_mode_changed),a
    ld ix,keyboard_masks
    bit 3,(ix+12)
    jr z,@released
    ld a,(aircraft_view_key_latched)
    or a
    ret nz
    ld a,1
    ld (aircraft_view_key_latched),a
    ld a,(aircraft_view_mode)
    xor 1
    ld (aircraft_view_mode),a
    ld (aircraft_view_aircraft_active),a
    ld a,1
    ld (aircraft_view_mode_changed),a
    ld (aircraft_view_visibility_dirty),a
    ld a,(aircraft_view_mode)
    or a
    ret z
    xor a
    ld (camera_state+p3d_camera_look_flags),a
    ret
@released:
    xor a
    ld (aircraft_view_key_latched),a
    ret

; Build the current camera pose from the aircraft's retained position and Q15
; local-to-world orientation.  Cockpit submits the aircraft rotation directly.
; Chase rotates both local points through the aircraft matrix, then invokes the
; proven transactional look-at solver with an upright horizon.
aircraft_view_update_camera:
    ld a,(aircraft_view_mode)
    or a
    jr z,@cockpit

    ld hl,aircraft_view_chase_camera_local
    call aircraft_view_build_world_point
    ret c
    ld hl,aircraft_view_point_work
    ld de,aircraft_view_camera_work
    ld bc,p3d_vec3_size
    ldir
    ld hl,aircraft_view_chase_target_local
    call aircraft_view_build_world_point
    ret c
    ld hl,aircraft_view_point_work
    ld de,aircraft_view_target_work
    ld bc,p3d_vec3_size
    ldir
    ld hl,aircraft_view_camera_work
    call aircraft_view_commit_camera_position
    ld ix,camera_state
    ld iy,aircraft_view_target_work
    ld a,p3d_camera_roll_upright
    jp p3d_camera_aim_at_point16

@cockpit:
    ld hl,aircraft_view_cockpit_eye_local
    call aircraft_view_build_world_point
    ret c
    ld hl,aircraft_view_point_work
    call aircraft_view_commit_camera_position

; Keep all camera pose fields semantically coherent.  The VDP consumes the
; Euler words; copying the orientation also preserves future camera-local use.
    ld hl,object_state+p3d_object_pingo_rotation
    ld de,camera_state+p3d_camera_pingo_rotation
    ld bc,p3d_vec3_size
    ldir
    ld hl,object_state+p3d_object_orientation
    ld de,camera_state+p3d_camera_orientation
    ld bc,p3d_mat3_size
    ldir
    ld a,(camera_state+p3d_camera_dirty)
    or p3d_camera_dirty_rotation
    ld (camera_state+p3d_camera_dirty),a
    or a
    ret

; HL points at a six-byte local offset.  Return its aircraft-relative world
; point in aircraft_view_point_work, transactionally on P3D arithmetic errors.
aircraft_view_build_world_point:
    ld de,aircraft_view_point_work
    ld bc,p3d_vec3_size
    ldir
    ld ix,aircraft_view_point_work
    ld iy,object_state+p3d_object_orientation
    call p3d_mat3_mul_vec3_16
    ret c
    ld iy,object_state+p3d_object_world_position
    jp p3d_vec3_translate16

aircraft_view_commit_camera_position:
    ld de,camera_state+p3d_camera_world_position
    ld bc,p3d_vec3_size
    ldir
    ld a,(camera_state+p3d_camera_dirty)
    or p3d_camera_dirty_position
    ld (camera_state+p3d_camera_dirty),a
    ret

; Render-idle visibility publication order on a cockpit -> chase transition:
; sync aircraft absolute pose, sync camera, send command 51 active=1, render.
; On chase -> cockpit, command 51 active=0 may precede the next render.
aircraft_view_mode:
    db aircraft_view_mode_cockpit
aircraft_view_key_latched:
    db 0
aircraft_view_mode_changed:
    db 0
aircraft_view_aircraft_active:
    db 0
aircraft_view_visibility_dirty:
    db 0
aircraft_view_point_work:
    ds p3d_vec3_size
aircraft_view_camera_work:
    ds p3d_vec3_size
aircraft_view_target_work:
    ds p3d_vec3_size
