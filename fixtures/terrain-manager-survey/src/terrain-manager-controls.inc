; =============================================================================
; Fixture-only live terrain-radius controls.
;
; The manager receives policy through manager_survey_radius_request; it does
; not know about keyboards.  Top-row digits use MOS's BBC-compatible physical
; key map.  Selection is rising-edge only, and simultaneous presses choose the
; lowest radius deterministically.
; =============================================================================

manager_survey_initialize_radius_controls:
    xor a
    ld (manager_survey_radius_keys_down),a
    ld (manager_survey_radius_pending),a
    ld a,manager_survey_default_radius
    ld (manager_survey_radius_request),a
    ret

manager_survey_update_radius_keys:
    ld ix,keyboard_masks
    ld b,0
    bit 7,(ix+4)                       ; top-row 0: physical key 40
    jr z,@one
    set 0,b
@one:
    bit 0,(ix+6)                       ; top-row 1: physical key 49
    jr z,@two
    set 1,b
@two:
    bit 1,(ix+6)                       ; top-row 2: physical key 50
    jr z,@three
    set 2,b
@three:
    bit 1,(ix+2)                       ; top-row 3: physical key 18
    jr z,@four
    set 3,b
@four:
    bit 2,(ix+2)                       ; top-row 4: physical key 19
    jr z,@five
    set 4,b
@five:
    bit 3,(ix+2)                       ; top-row 5: physical key 20
    jr z,@edges
    set 5,b

@edges:
    ld a,(manager_survey_radius_keys_down)
    ld c,a
    ld a,b
    ld (manager_survey_radius_keys_down),a
    ld a,c
    cpl
    and b                              ; A = newly pressed radius keys
    ret z
    bit 0,a
    jr nz,@radius_zero
    bit 1,a
    jr nz,@radius_one
    bit 2,a
    jr nz,@radius_two
    bit 3,a
    jr nz,@radius_three
    bit 4,a
    jr nz,@radius_four
    ld a,5
    jr @publish
@radius_zero:
    xor a
    jr @publish
@radius_one:
    ld a,1
    jr @publish
@radius_two:
    ld a,2
    jr @publish
@radius_three:
    ld a,3
    jr @publish
@radius_four:
    ld a,4
@publish:
    ld (manager_survey_radius_request),a
    ld a,1
    ld (manager_survey_radius_pending),a
    ret

manager_survey_radius_keys_down: db 0
manager_survey_radius_request: db manager_survey_default_radius
manager_survey_radius_pending: db 0
