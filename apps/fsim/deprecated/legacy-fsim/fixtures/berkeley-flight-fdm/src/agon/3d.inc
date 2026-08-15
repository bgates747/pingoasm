; eZ80-local integer 3D arithmetic for Pingo-compatible values
;
; Scalar arithmetic, forward/inverse trigonometric lookup, vector and matrix
; transforms, persistent object-pose integration, stateful camera look-at,
; and dirty Pingo command synchronization are implemented below. Include
; 3d_sincos_table.inc after this file so its forward table references resolve.
;
; Pingo wire values are little-endian 16-bit quantities:
;
;   mesh coordinate: signed normalized, value = raw / 32767
;   rotation angle:  signed turns,      radians = raw * 2*pi / 32767
;   translation:     signed distance,   value = raw * 256 / 32767
;   scale:           unsigned 8.8,      value = raw / 256
;
; A local vec3 occupies six bytes. Its component interpretation is supplied
; by the operation; the layout itself does not encode a numeric domain.

p3d_vec3_x:       equ 0
p3d_vec3_y:       equ 2
p3d_vec3_z:       equ 4
p3d_vec3_size:    equ 6
p3d_norm_max:     equ 32767
p3d_norm_half_up: equ 16384

; A row-major signed-Q15 matrix occupies 18 bytes.
p3d_mat3_r0c0:    equ 0
p3d_mat3_r0c1:    equ 2
p3d_mat3_r0c2:    equ 4
p3d_mat3_r1c0:    equ 6
p3d_mat3_r1c1:    equ 8
p3d_mat3_r1c2:    equ 10
p3d_mat3_r2c0:    equ 12
p3d_mat3_r2c1:    equ 14
p3d_mat3_r2c2:    equ 16
p3d_mat3_size:    equ 18

; Packed eZ80-side state for one Pingo object. The eZ80 owns this complete
; state; Pingo receives absolute create/scale/rotation/translation commands.
; All word and aggregate fields start at even offsets.
p3d_object_dirty:                    equ 0
p3d_object_reserved:                 equ 1
p3d_object_sid:                      equ 2
p3d_object_oid:                      equ 4
p3d_object_mid:                      equ 6
p3d_object_bmid:                     equ 8
p3d_object_world_position:           equ 10
p3d_object_pingo_translation:        equ p3d_object_world_position
p3d_object_pingo_rotation:           equ 16
p3d_object_scale:                    equ 22
p3d_object_orientation:              equ 28
p3d_object_local_linear_velocity:    equ 46
p3d_object_local_angular_velocity:   equ 52
p3d_object_angular_residual:         equ 58
p3d_object_size:                     equ 64

; The four-word input tuple accepted by p3d_object_init16 has the same ID
; offsets relative to its own base, minus the two-byte state header.
p3d_object_ids_sid:                  equ 0
p3d_object_ids_oid:                  equ 2
p3d_object_ids_mid:                  equ 4
p3d_object_ids_bmid:                 equ 6
p3d_object_ids_size:                 equ 8

p3d_object_dirty_position:           equ 0x01
p3d_object_dirty_rotation:           equ 0x02
p3d_object_dirty_scale:              equ 0x04
p3d_object_dirty_create:             equ 0x08
p3d_object_dirty_pose:               equ 0x03
p3d_object_dirty_all:                equ 0x0f

; Packed eZ80-side state for one Pingo camera. Camera commands describe a
; world pose, just like object commands; Pingo inverts that pose internally
; when constructing the view matrix. The orientation is retained so later
; camera-local movement can use the same matrix/vector primitives as objects.
p3d_camera_dirty:                    equ 0
p3d_camera_look_flags:               equ 1
p3d_camera_sid:                      equ 2
p3d_camera_world_position:           equ 4
p3d_camera_pingo_translation:        equ p3d_camera_world_position
p3d_camera_pingo_rotation:           equ 10
p3d_camera_orientation:              equ 16
p3d_camera_pole_yaw:                 equ 34
p3d_camera_size:                     equ 36

p3d_camera_dirty_position:           equ 0x01
p3d_camera_dirty_rotation:           equ 0x02
p3d_camera_dirty_all:                equ 0x03

; Known look-at state bits. Unknown bits are caller-owned and preserved.
p3d_camera_look_valid:               equ 0x01
p3d_camera_look_in_pole:             equ 0x02
p3d_camera_look_inverted:            equ 0x04
p3d_camera_look_known:               equ 0x07

; Required A-register policy for each camera aim call.
p3d_camera_roll_upright:             equ 0
p3d_camera_roll_continuous:          equ 1
p3d_camera_roll_policy_count:        equ 2

; Current buffered-command Pingo selector and absolute object subcommands.
p3d_pingo_command:                   equ 0x49
p3d_pingo_create_object:             equ 5
p3d_pingo_set_object_xyz_scale:      equ 9
p3d_pingo_set_object_xyz_rotation:   equ 13
p3d_pingo_set_object_xyz_translation: equ 17
p3d_pingo_create_packet_size:        equ 13
p3d_pingo_update_packet_size:        equ 15

; ---------------------------------------------------------------------------
; Scalar arithmetic primitives
; ---------------------------------------------------------------------------

; Unsigned 16-bit by unsigned 16-bit multiplication.
;
; inputs:
;   hl = unsigned 16-bit multiplicand (H:L; UHL ignored)
;   de = unsigned 16-bit multiplier (D:E; UDE ignored)
; outputs:
;   hl:de = unsigned 32-bit product in bytes H:L:D:E
; destroys:
;   af, bc
; preserves:
;   bc', de', hl'
p3d_umul16x16_32:
    ld b,e
    ld c,l
    ld l,e
    ld e,c
    mlt bc                  ; bc = low * low
    ld a,b                  ; save product byte 1
    ld b,h                  ; prepare high * high
    mlt hl                  ; hl = high * low
    add a,l
    ld l,a
    adc a,h
    sub a,l
    ld h,a
    ld a,c                  ; save product byte 0
    ld c,d                  ; bc = high:high
    mlt de                  ; de = low * high
    add.s hl,de             ; accumulate middle bytes
    ld e,a
    ld d,l
    ld l,h
    ld h,0
    rl h                    ; carry from middle-byte accumulation
    mlt bc                  ; bc = high * high
    add.s hl,bc
    ret

; Signed 16-bit by signed 16-bit multiplication.
;
; inputs:
;   hl = signed 16-bit multiplicand (H:L; UHL ignored)
;   de = signed 16-bit multiplier (D:E; UDE ignored)
; outputs:
;   hl:de = signed 32-bit product in bytes H:L:D:E
;   carry clear on success
; destroys:
;   af, af', bc
; preserves:
;   bc', de', hl'
p3d_smul16x16_32:
; park the product sign in the shadow flags
    ld a,h
    xor d
    ex af,af'
; absolute value of hl
    bit 7,h
    jr z,@hl_positive
    xor a
    sub l
    ld l,a
    ld a,0                  ; ld preserves carry
    sbc a,h
    ld h,a
@hl_positive:
; absolute value of de
    bit 7,d
    jr z,@de_positive
    xor a
    sub e
    ld e,a
    ld a,0
    sbc a,d
    ld d,a
@de_positive:
    call p3d_umul16x16_32
; restore the sign flags
    ex af,af'
    ret p
; negate logical H:L:D:E
    xor a
    sub e
    ld e,a
    ld a,0
    sbc a,d
    ld d,a
    ld a,0
    sbc a,l
    ld l,a
    ld a,0
    sbc a,h
    ld h,a
    or a                    ; success: carry clear
    ret

; Add two signed 32-bit values held in opposite GP register banks.
;
; inputs:
;   active hl:de = right/addend in bytes H:L:D:E
;   shadow hl:de = left/accumulator in bytes H':L':D':E'
; outputs:
;   hl:de = left + right
;   the opposite GP register bank is active on return
;   carry clear on success
;   carry set on signed overflow
; destroys:
;   af and both hl:de banks
; preserves:
;   af' and both bc banks
p3d_sadd32:
; low byte
    ld a,e
    exx
    add a,e
    ld e,a
; middle-low byte
    exx
    ld a,d
    exx
    adc a,d
    ld d,a
; middle-high byte
    exx
    ld a,l
    exx
    adc a,l
    ld l,a
; high byte
    exx
    ld a,h
    exx
    adc a,h
    ld h,a
; the final byte operation owns the signed-overflow flag
    jp pe,@overflow
    or a                    ; success: carry clear
    ret
@overflow:
    scf
    ret

; Subtract two signed 32-bit values held in opposite GP register banks.
;
; inputs:
;   active hl:de = right/subtrahend in bytes H:L:D:E
;   shadow hl:de = left/minuend in bytes H':L':D':E'
; outputs:
;   hl:de = left - right
;   the opposite GP register bank is active on return
;   carry clear on success
;   carry set on signed overflow
; destroys:
;   af and both hl:de banks
; preserves:
;   af' and both bc banks
p3d_ssub32:
; low byte: left + ~right + 1
    ld a,e
    cpl
    scf
    exx
    adc a,e
    ld e,a
; middle-low byte
    exx
    ld a,d
    cpl
    exx
    adc a,d
    ld d,a
; middle-high byte
    exx
    ld a,l
    cpl
    exx
    adc a,l
    ld l,a
; high byte
    exx
    ld a,h
    cpl
    exx
    adc a,h
    ld h,a
; the final byte operation owns the signed-overflow flag
    jp pe,@overflow
    or a                    ; success: carry clear
    ret
@overflow:
    scf
    ret

; Reduce a signed 32-bit product by Pingo's signed-normalized divisor.
;
; This is the narrowing operation needed after multiplying a coordinate by a
; normalized sine, cosine, or matrix coefficient:
;
;   result = round(product / 32767)
;
; inputs:
;   hl:de = signed 32-bit product in bytes H:L:D:E
; outputs:
;   hl = signed 16-bit result in H:L
;   carry clear on success
;   carry set if the rounded result is outside -32768..32767
; destroys:
;   af, af', bc, de
; preserves:
;   bc', de', hl'
p3d_sdiv32767_32_to_16:
; park the input sign in the shadow accumulator
    ld a,h
    and 0x80
    ex af,af'
; form the unsigned magnitude in H:L:D:E
    bit 7,h
    jr z,@magnitude_ready
    xor a
    sub e
    ld e,a
    ld a,0
    sbc a,d
    ld d,a
    ld a,0
    sbc a,l
    ld l,a
    ld a,0
    sbc a,h
    ld h,a
@magnitude_ready:
; A magnitude above 0x3FFFBFFF rounds beyond 32768 and cannot
; produce a signed 16-bit result for either input sign.
    ld a,h
    cp 0x3F
    jr c,@range_ok
    jr nz,@range_overflow
    ld a,l
    cp 0xFF
    jr c,@range_ok
    ld a,d
    cp 0xC0
    jr nc,@range_overflow
@range_ok:
; q = magnitude >> 15
    ld a,d
    rla                     ; carry = original product bit 15
    adc.s hl,hl
    ld b,h
    ld c,l
; r = magnitude & 32767
    res 7,d
; magnitude = q*32767 + (q+r)
    add.s hl,de             ; range check guarantees no carry
; The accepted result range limits q+r to 49150, so subtract at most once.
; Incrementing makes the threshold 0x8000. On the subtraction path, clearing
; bit 15 then computes (q+r+1)-32768 = (q+r)-32767.
    inc.s hl
    bit 7,h
    jr z,@below_norm
    res 7,h
    inc.s bc
    jr @remainder
@below_norm:
    dec.s hl                ; restore q+r
@remainder:
; Divisor 32767 has no exact half-integer remainder.
    bit 6,h                 ; remainder >= 16384
    jr z,@rounded
    inc.s bc
@rounded:
; Restore the input sign.
    ex af,af'
    or a
    jr nz,@negative
; Positive 32768 is outside the signed 16-bit result range.
    ld h,b
    ld l,c
    bit 7,h
    jr z,@positive_ready
; A=0 distinguishes this exact positive one-count boundary from a product
; whose magnitude is genuinely outside the Q15-adjacent range.
    xor a
    jr @overflow
@positive_ready:
    or a                    ; success: carry clear
    ret
@negative:
; The range check guarantees a magnitude no greater than 32768.
    ld h,b
    ld l,c
    xor a
    sub l
    ld l,a
    ld a,0
    sbc a,h
    ld h,a
    or a                    ; success: carry clear
    ret
@range_overflow:
; Balance the earlier AF exchange before returning.
    ex af,af'
    ld a,1
@overflow:
    scf
    ret

; Narrow a signed normalized product for a Q15 orientation coefficient.
; Matrix composition may overshoot one by a single output count when two
; rounded table directions mathematically land on a cardinal. Clamp only
; that exact +/-32768 result to the representable Q15 endpoints; larger
; magnitudes remain failures. General scalar/vector callers retain the strict
; p3d_sdiv32767_32_to_16 contract above.
;
; inputs:
;   hl:de = signed 32-bit product in bytes H:L:D:E
; outputs:
;   hl = signed Q15 result in -32767..32767
;   carry clear on success, including the one-count clamp
;   carry set for a genuine larger overflow
; destroys:
;   af, af', bc, de
; preserves:
;   bc', de', hl'
p3d_sdiv32767_32_to_q15_16:
    call p3d_sdiv32767_32_to_16
    jr c,@positive_boundary
; Strict signed narrowing legitimately admits -32768. In a Q15 orientation
; matrix that exact endpoint is the negative one-count boundary.
    ld a,h
    cp 0x80
    jr z,@check_negative_boundary
    or a
    ret
@check_negative_boundary:
    ld a,l
    or a
    ret nz
    ld hl,-32767
    or a
    ret
@positive_boundary:
; A=0 is emitted only for the rounded +32768 boundary.
    or a
    jr nz,@genuine_overflow
    ld hl,32767
    or a
    ret
@genuine_overflow:
    scf
    ret

; Multiply a signed 16-bit value by a signed Pingo-normalized coefficient.
;
; This is the common composition of p3d_smul16x16_32 and
; p3d_sdiv32767_32_to_16.
;
; inputs:
;   hl = signed 16-bit value (low word)
;   de = signed normalized coefficient (low word)
; outputs:
;   hl = round(value * coefficient / 32767)
;   carry clear on success
;   carry set on overflow
; destroys:
;   af, af', bc, de
; preserves:
;   bc', de', hl'
p3d_smul_norm16:
    call p3d_smul16x16_32
    jp p3d_sdiv32767_32_to_16

; Convert a Pingo rotation angle to normalized sine and cosine values.
;
; inputs:
;   hl = signed Pingo rotation angle (low word)
; outputs:
;   bc = signed normalized sine (low word)
;   de = signed normalized cosine (low word)
;   carry clear on success
; destroys:
;   af, hl
; preserves:
;   af', ix, iy, and all shadow GP registers
p3d_sincos16:
    ld b,0                  ; input-negative flag
    bit 7,h
    jr z,@magnitude_ready
    inc b
    xor a
    sub l
    ld l,a
    ld a,0
    sbc a,h
    ld h,a
@magnitude_ready:
; index = round(abs(angle) / 128), modulo 256
    ld a,l
    add a,64
    ld l,a
    ld a,h
    adc a,0
    add a,a
    bit 7,l
    jr z,@rounded_index
    inc a
@rounded_index:
    bit 0,b
    jr z,@index_ready
    neg
@index_ready:
; Four bytes per interleaved sine/cosine entry.
    ld e,a
    ld d,4
    mlt de
    inc de
    dec.s de                ; zero-extend UDE
    ld hl,p3d_sincos_q15
    add hl,de               ; full 24-bit table address
    ld c,(hl)
    inc hl
    ld b,(hl)
    inc hl
    ld e,(hl)
    inc hl
    ld d,(hl)
    or a
    ret

; Linearly interpolate one signed-Q15 table component over 1/128 of a
; coarse phase. Adjacent generated values differ by at most 804, so the
; signed product is comfortably inside 32 bits.
;
; inputs:
;   hl = signed base value
;   de = signed next value
;   a  = unsigned interpolation fraction 0..127
; outputs:
;   hl = round((base*(128-fraction)+next*fraction)/128)
;        with halves away from zero
;   carry clear
; destroys:
;   af, af', bc, de and all shadow GP registers
; preserves:
;   ix, iy
p3d_lerp_q15_frac7:
    ld b,0
    ld c,a
    push hl                 ; retain the base across multiplication
    ex de,hl
    or a
    sbc.s hl,de             ; signed next-base
    ld e,c
    ld d,b
    call p3d_smul16x16_32
; Add signed base*128 in the opposite GP bank. p3d_sadd32 deliberately
; returns with that opposite bank active.
    exx
    pop de
    ld hl,0
    bit 7,d
    jr z,@base_extended
    dec.s hl
@base_extended:
    ld b,7
@base_shift:
    sla e
    rl d
    rl l
    rl h
    djnz @base_shift
    exx
    call p3d_sadd32
; Divide the signed full weighted numerator by 128 with symmetric rounding.
    ld c,0
    bit 7,h
    jr z,@magnitude_ready
    inc c
    xor a
    sub e
    ld e,a
    ld a,0
    sbc a,d
    ld d,a
    ld a,0
    sbc a,l
    ld l,a
    ld a,0
    sbc a,h
    ld h,a
@magnitude_ready:
    ld a,e
    add a,64
    ld e,a
    ld a,d
    adc a,0
    ld d,a
    ld a,l
    adc a,0
    ld l,a
    ld a,h
    adc a,0
    ld h,a
    ld b,7
@shift:
    srl h
    rr l
    rr d
    rr e
    djnz @shift
    ld h,d
    ld l,e
    bit 0,c
    jr z,@signed_result_ready
    xor a
    sub l
    ld l,a
    ld a,0
    sbc a,h
    ld h,a
@signed_result_ready:
; Restore the caller's original GP bank while transferring the low-word
; result out of the bank in which p3d_sadd32 accumulated it.
    push hl
    exx
    pop hl
    or a
    ret

; Convert a Pingo rotation angle to interpolated normalized sine and cosine
; values. Unlike p3d_sincos16, this consumes every raw angle bit. Reflection
; into the positive half turn makes odd/even trig symmetry byte-exact.
;
; inputs:
;   hl = signed Pingo rotation angle (low word)
; outputs:
;   bc = signed normalized sine (low word)
;   de = signed normalized cosine (low word)
;   carry clear
; destroys:
;   af, af', hl and all shadow GP registers
; preserves:
;   ix, iy
p3d_sincos_fine16:
    push ix
    push iy
; One binary turn is 32768 raw units. Reflect the negative half into a
; positive magnitude so sin(-x)=-sin(x) and cos(-x)=cos(x) remain exact even
; when interpolation rounding lands on a tie.
    ld b,0
    res 7,h
    bit 6,h
    jr z,@magnitude_ready
    inc b
    ex de,hl
    ld hl,0x8000
    or a
    sbc.s hl,de
@magnitude_ready:
    ld a,l
    and 0x7f
    ld c,a                  ; interpolation fraction
; index = angle >> 7.
    ld a,h
    add a,a
    bit 7,l
    jr z,@index_ready
    inc a
@index_ready:
    ld e,a
    ld d,4
    mlt de
    inc de
    dec.s de                ; zero-extend UDE
    ld ix,p3d_sincos_q15
    add ix,de
; Retain the fraction and reflected sign in one logical stack word.
    ld l,c
    ld h,b
    push hl
    ld iy,0
    add iy,sp
; Interpolate sine.
    ld l,(ix+0)
    ld h,(ix+1)
    ld e,(ix+4)
    ld d,(ix+5)
    ld a,(iy+0)
    call p3d_lerp_q15_frac7
    ld a,(iy+1)
    or a
    jr z,@sine_ready
    xor a
    sub l
    ld l,a
    ld a,0
    sbc a,h
    ld h,a
@sine_ready:
    push hl
; Interpolate cosine.
    ld l,(ix+2)
    ld h,(ix+3)
    ld e,(ix+6)
    ld d,(ix+7)
    ld a,(iy+0)
    call p3d_lerp_q15_frac7
    ex de,hl                ; DE = cosine
    pop bc                  ; BC = sine
    pop hl                  ; discard fraction word
    pop iy
    pop ix
    or a
    ret

; Convert one signed Cartesian direction to the nearest 1/256-turn Pingo
; angle. The chosen phase maximizes x*cos(phase)+y*sin(phase) against the
; generated Q15 table. Exact ties choose the numerically smaller signed phase;
; atan2(0,0) is zero.
;
; inputs:
;   hl = signed Y component (low word)
;   de = signed X component (low word)
; outputs:
;   hl = signed Pingo angle, always a multiple of 128
;   carry clear
; destroys:
;   af, af', bc, de, and all shadow GP registers
; preserves:
;   ix, iy
p3d_atan2_16:
    push ix
    push iy
; Record original X/Y signs in bits 0/1.
    ld b,0
    bit 7,d
    jr z,@x_sign_ready
    set 0,b
@x_sign_ready:
    bit 7,h
    jr z,@y_sign_ready
    set 1,b
@y_sign_ready:
; Unsigned magnitudes; -32768 deliberately becomes 32768.
    bit 7,d
    jr z,@x_magnitude_ready
    xor a
    sub e
    ld e,a
    ld a,0
    sbc a,d
    ld d,a
@x_magnitude_ready:
    bit 7,h
    jr z,@y_magnitude_ready
    xor a
    sub l
    ld l,a
    ld a,0
    sbc a,h
    ld h,a
@y_magnitude_ready:
    ld a,h
    or l
    or d
    or e
    jr nz,@nonzero
    ld hl,0
    pop iy
    pop ix
    or a
    ret
@nonzero:
; IX=max magnitude, IY=min magnitude. Bit 2 records folding across 45
; degrees so the first-octant result can be unfolded later.
    push de
    pop ix
    push hl
    pop iy
    or a
    sbc.s hl,de
    jr c,@magnitudes_ordered
    jr z,@magnitudes_ordered
    push ix
    push iy
    pop ix
    pop iy
    set 2,b
@magnitudes_ordered:
; An exact boundary must choose the smaller final signed phase. Within the
; folded octant that means choosing the upper bin when (X sign XOR Y sign
; XOR fold) is true.
    ld c,0
    ld a,b
    and 3
    cp 1
    jr z,@different_signs
    cp 2
    jr nz,@sign_difference_ready
@different_signs:
    inc c
@sign_difference_ready:
    bit 2,b
    jr z,@fold_tie_ready
    ld a,c
    xor 1
    ld c,a
@fold_tie_ready:
    bit 0,c
    jr z,@tie_ready
    set 3,b
@tie_ready:
; Park the mapping code in AF'. Search bins 0..32 using exact dot-product
; boundaries. Thirty-three possible bins require at most six comparisons.
    ld a,b
    ex af,af'
    ld b,0                  ; inclusive lower bin
    ld c,32                 ; inclusive upper bin
@search:
    ld a,b
    cp c
    jr z,@search_complete
    push bc
    add a,c
    srl a                   ; midpoint/boundary index
    ld e,a
    ld d,4
    mlt de
    inc de
    dec.s de                ; zero-extend UDE
    ld hl,p3d_atan2_octant_boundaries_q15
    add hl,de
    ld e,(hl)
    inc hl
    ld d,(hl)               ; DE = dx
    push de
    inc hl
    ld e,(hl)
    inc hl
    ld d,(hl)               ; DE = dy
; left = min*dy
    push iy
    pop hl
    call p3d_umul16x16_32
    exx
; right = max*dx
    pop de
    push ix
    pop hl
    call p3d_umul16x16_32
; Return to the original bank with left-right. Both products are below 2^31,
; so signed subtraction also gives an exact unsigned ordering result.
    call p3d_ssub32
    pop bc
    bit 7,h
    jr nz,@choose_lower
    ld a,h
    or l
    or d
    or e
    jr nz,@choose_upper
; Exact boundary: apply the parked final-phase tie rule.
    ex af,af'
    ld e,a
; The quadrant-II boundary between phases +127 and -128 crosses the signed
; phase wrap. Its numerically smaller choice is -128 (folded bin zero), unlike
; all other quadrant-II boundaries.
    and 3
    cp 1
    jr nz,@ordinary_tie_shadow
    ld a,b
    add a,c
    srl a
    jr nz,@ordinary_tie_shadow
    ld a,e
    ex af,af'
    jr @choose_lower
@ordinary_tie_shadow:
    bit 3,e
    jr z,@tie_lower_shadow
    ld a,e
    ex af,af'
    jr @choose_upper
@tie_lower_shadow:
    ld a,e
    ex af,af'
    jr @choose_lower
@choose_upper:
    ld a,b
    add a,c
    srl a
    inc a
    ld b,a
    jr @search
@choose_lower:
    ld a,b
    add a,c
    srl a
    ld c,a
    jr @search

@search_complete:
; Unfold the octant, then map the positive magnitude through the original
; Cartesian quadrant to signed phase -128..127.
    ex af,af'
    ld c,a                  ; mapping code
    ld a,b                  ; folded phase
    bit 2,c
    jr z,@base_ready
    ld a,64
    sub b
@base_ready:
    ld d,a                  ; positive phase magnitude 0..64
    ld a,c
    and 3
    jr z,@phase_positive
    dec a
    jr z,@phase_quadrant_ii
    dec a
    jr z,@phase_quadrant_iv
; Quadrant III: phase = base-128.
    ld a,d
    sub 128
    jr @phase_ready
@phase_quadrant_ii:
    ld a,128
    sub d
    jr @phase_ready
@phase_quadrant_iv:
    xor a
    sub d
    jr @phase_ready
@phase_positive:
    ld a,d
@phase_ready:
    ld l,a
    ld h,0
    bit 7,l
    jr z,@phase_extended
    dec h
@phase_extended:
    add.s hl,hl
    add.s hl,hl
    add.s hl,hl
    add.s hl,hl
    add.s hl,hl
    add.s hl,hl
    add.s hl,hl
    pop iy
    pop ix
    or a
    ret

; Return round(min/max*32768) without ever constructing the 32-bit numerator.
; The restoring fractional division operates only on logical low words.
;
; inputs:
;   hl = unsigned minimum, 0..32768
;   de = unsigned maximum, 1..32768, and minimum <= maximum
; outputs:
;   hl = unsigned Q15 ratio, 0..32768
;   carry clear
; destroys:
;   af, bc, de
; preserves:
;   ix, iy and all shadow GP registers
p3d_ratio_q15_16:
    or a
    sbc.s hl,de
    jr nz,@not_equal
    ld hl,0x8000
    ret
@not_equal:
    add.s hl,de             ; restore the minimum/remainder
    ld bc,0                 ; quotient
    ld a,15
@bit_loop:
    add.s hl,hl
    sla c
    rl b
    and a                   ; clear carry without changing the loop count
    sbc.s hl,de
    jr nc,@set_bit
    add.s hl,de
    jr @bit_ready
@set_bit:
    inc.s bc                ; shifted quotient bit zero is known clear
@bit_ready:
    dec a
    jr nz,@bit_loop
; Round half up from the final remainder.
    add.s hl,hl
    and a
    sbc.s hl,de
    jr c,@rounded
    inc.s bc
@rounded:
    push bc
    pop hl
    or a
    ret

; Convert one signed Cartesian direction to a fine Pingo angle. A Q15
; min/max ratio selects and linearly interpolates 65 first-octant atan nodes.
; The worst first-octant table/interpolation error is about 0.012 degrees;
; atan2(0,0) is zero.
;
; inputs:
;   hl = signed Y component (low word)
;   de = signed X component (low word)
; outputs:
;   hl = canonical signed Pingo angle in -16384..16383
;   carry clear
; destroys:
;   af, af', bc, de and all shadow GP registers
; preserves:
;   ix, iy
p3d_atan2_fine16:
    push ix
    push iy
; Record original X/Y signs in bits 0/1.
    ld b,0
    bit 7,d
    jr z,@x_sign_ready
    set 0,b
@x_sign_ready:
    bit 7,h
    jr z,@y_sign_ready
    set 1,b
@y_sign_ready:
; Unsigned magnitudes; -32768 deliberately becomes 32768.
    bit 7,d
    jr z,@x_magnitude_ready
    xor a
    sub e
    ld e,a
    ld a,0
    sbc a,d
    ld d,a
@x_magnitude_ready:
    bit 7,h
    jr z,@y_magnitude_ready
    xor a
    sub l
    ld l,a
    ld a,0
    sbc a,h
    ld h,a
@y_magnitude_ready:
    ld a,h
    or l
    or d
    or e
    jr nz,@nonzero
    ld hl,0
    pop iy
    pop ix
    or a
    ret
@nonzero:
; IX=max magnitude, IY=min magnitude. Bit 2 records folding across 45
; degrees so the first-octant result can be unfolded later.
    push de
    pop ix
    push hl
    pop iy
    or a
    sbc.s hl,de
    jr c,@magnitudes_ordered
    jr z,@magnitudes_ordered
    push ix
    push iy
    pop ix
    pop iy
    set 2,b
@magnitudes_ordered:
    ld c,b
    ld b,0
    push bc                 ; retain sign/fold mapping
    push iy
    pop hl
    push ix
    pop de
    call p3d_ratio_q15_16
; An exact diagonal is the final table node and has no following entry.
    bit 7,h
    jr z,@interpolate
    ld hl,4096
    jr @octant_ready
@interpolate:
    push hl
    pop iy                  ; retain ratio/fraction
    ld a,h
    srl a                   ; node index = ratio >> 9
    ld e,a
    ld d,2
    mlt de
    inc de
    dec.s de
    ld ix,p3d_atan_octant_fine_q15
    add ix,de
    ld c,(ix+0)
    ld b,(ix+1)            ; BC = base node
    ld l,(ix+2)
    ld h,(ix+3)
    or a
    sbc.s hl,bc            ; HL = positive adjacent delta
    push bc
    push iy
    pop de
    ld a,d
    and 1
    ld d,a                 ; DE = low nine ratio bits
    call p3d_umul16x16_32
; round(delta*fraction/512): product < 0x10000, so adding 0x0100
; and taking the high byte shifted once is exact.
    inc d
    srl d
    ld e,d
    ld d,0
    pop hl
    add.s hl,de
@octant_ready:
    pop bc                  ; C = sign/fold mapping
    bit 2,c
    jr z,@base_ready
    ex de,hl
    ld hl,8192
    or a
    sbc.s hl,de
@base_ready:
; Map the positive 0..quarter-turn magnitude into the original quadrant.
    ld a,c
    and 3
    jr z,@phase_ready
    dec a
    jr z,@quadrant_ii
    dec a
    jr z,@quadrant_iv
; Quadrant III: base-half-turn.
    ld de,16384
    or a
    sbc.s hl,de
    jr @phase_ready
@quadrant_ii:
    ex de,hl
    ld hl,16384
    or a
    sbc.s hl,de
; Canonicalize the exact negative-X axis from +half-turn to -half-turn.
    ld a,h
    cp 0x40
    jr nz,@phase_ready
    ld a,l
    or a
    jr nz,@phase_ready
    set 7,h
    jr @phase_ready
@quadrant_iv:
    xor a
    sub l
    ld l,a
    ld a,0
    sbc a,h
    ld h,a
@phase_ready:
    pop iy
    pop ix
    or a
    ret

; Convert one signed normalized sine coefficient to the nearest canonical
; pitch in -1/4..+1/4 turn. Exact ties choose the smaller magnitude.
;
; inputs:
;   hl = signed normalized sine coefficient
; outputs:
;   hl = signed Pingo angle, always a multiple of 128
;   carry clear
; destroys:
;   af, af', bc, de
; preserves:
;   ix, iy and all shadow GP registers
p3d_asin16:
    push ix
    ld b,0
    bit 7,h
    jr z,@magnitude_ready
    inc b
    xor a
    sub l
    ld l,a
    ld a,0
    sbc a,h
    ld h,a
@magnitude_ready:
    push hl
    pop ix
    ld a,b
    ex af,af'               ; park input sign
; The final threshold selects the cardinal pitch directly. This also clamps
; magnitude 32768 to the table's maximum 32767.
    ld de,32763
    or a
    sbc.s hl,de
    jr c,@search_needed
    ld b,64
    jr @search_complete
@search_needed:
    ld b,0
    ld c,63
@search:
    ld a,b
    cp c
    jr z,@search_complete
    add a,c
    srl a
    push bc
    ld e,a
    ld d,2
    mlt de
    inc de
    dec.s de
    ld hl,p3d_asin_thresholds_q15
    add hl,de
    ld e,(hl)
    inc hl
    ld d,(hl)
    push ix
    pop hl
    or a
    sbc.s hl,de
    pop bc
    jr c,@choose_lower
    ld a,b
    add a,c
    srl a
    inc a
    ld b,a
    jr @search
@choose_lower:
    ld a,b
    add a,c
    srl a
    ld c,a
    jr @search
@search_complete:
    ld a,b
    ex af,af'
    or a
    jr z,@positive_shadow
    ex af,af'
    neg
    jr @sign_ready
@positive_shadow:
    ex af,af'
@sign_ready:
    ld l,a
    ld h,0
    bit 7,l
    jr z,@phase_extended
    dec h
@phase_extended:
    add.s hl,hl
    add.s hl,hl
    add.s hl,hl
    add.s hl,hl
    add.s hl,hl
    add.s hl,hl
    add.s hl,hl
    pop ix
    or a
    ret

; Unsigned 24-bit integer square root used by the camera look-at solver.
;
; This is deliberately an internal-width exception to the library's normal
; logical-low-word convention: the radicand is a genuine UHL:H:L value.
; Camera position inputs and emitted angles remain 16-bit, and the solver
; bounds its squared horizontal intermediate below 2^23 before calling here.
;
; inputs:
;   uhl:h:l = unsigned 24-bit radicand
; outputs:
;   ude:d:e = floor(sqrt(input))
;   uhl:h:l = input - result^2
;   carry clear
; destroys:
;   af, bc, de, hl
; preserves:
;   ix, iy and all shadow registers
;
; Adapted and namespaced from the established AgonMaths sqrt24 routine,
; credited there to xeda112358.
p3d_lookat_isqrt24:
    ld bc,0
    ld de,0
    xor a
    ld b,l
    push bc
    ld b,a
    ld l,a
; Iteration 1
    add hl,hl
    rl c
    add hl,hl
    rl c
    sub c
    jr nc,$+6
    inc e
    inc e
    cpl
    ld c,a
; Iteration 2
    add hl,hl
    rl c
    add hl,hl
    rl c
    rl e
    ld a,e
    sub c
    jr nc,$+6
    inc e
    inc e
    cpl
    ld c,a
; Iteration 3
    add hl,hl
    rl c
    add hl,hl
    rl c
    rl e
    ld a,e
    sub c
    jr nc,$+6
    inc e
    inc e
    cpl
    ld c,a
; Iteration 4
    add hl,hl
    rl c
    add hl,hl
    rl c
    rl e
    ld a,e
    sub c
    jr nc,$+6
    inc e
    inc e
    cpl
    ld c,a
; Iteration 5
    add hl,hl
    rl c
    add hl,hl
    rl c
    rl e
    ld a,e
    sub c
    jr nc,$+6
    inc e
    inc e
    cpl
    ld c,a
; Iteration 6
    add hl,hl
    rl c
    add hl,hl
    rl c
    rl e
    ld a,e
    sub c
    jr nc,$+6
    inc e
    inc e
    cpl
    ld c,a
; Iteration 7
    add hl,hl
    rl c
    add hl,hl
    rl c
    rl b
    ex de,hl
    add hl,hl
    push hl
    sbc hl,bc
    jr nc,$+8
    ld a,h
    cpl
    ld b,a
    ld a,l
    cpl
    ld c,a
    pop hl
    jr nc,$+4
    inc hl
    inc hl
    ex de,hl
; Iteration 8
    add hl,hl
    ld l,c
    ld h,b
    adc hl,hl
    adc hl,hl
    ex de,hl
    add hl,hl
    sbc hl,de
    add hl,de
    ex de,hl
    jr nc,$+6
    sbc hl,de
    inc de
    inc de
; Iteration 9
    pop af
    rla
    adc hl,hl
    rla
    adc hl,hl
    ex de,hl
    add hl,hl
    sbc hl,de
    add hl,de
    ex de,hl
    jr nc,$+6
    sbc hl,de
    inc de
    inc de
; Iteration 10
    rla
    adc hl,hl
    rla
    adc hl,hl
    ex de,hl
    add hl,hl
    sbc hl,de
    add hl,de
    ex de,hl
    jr nc,$+6
    sbc hl,de
    inc de
    inc de
; Iteration 11
    rla
    adc hl,hl
    rla
    adc hl,hl
    ex de,hl
    add hl,hl
    sbc hl,de
    add hl,de
    ex de,hl
    jr nc,$+6
    sbc hl,de
    inc de
    inc de
; Iteration 12
    rla
    adc hl,hl
    rla
    adc hl,hl
    ex de,hl
    add hl,hl
    sbc hl,de
    add hl,de
    ex de,hl
    jr nc,$+6
    sbc hl,de
    inc de
    inc de
    rr d
    rr e
    ret

; ---------------------------------------------------------------------------
; Single-vector transforms
; ---------------------------------------------------------------------------

; Signed low-16 addition with signed-overflow carry.
;
; inputs:  hl = left, de = right
; outputs: hl = wrapped sum; carry set on signed overflow
; destroys: af
p3d_sadd16:
    ld a,l
    add a,e
    ld l,a
    ld a,h
    adc a,d
    ld h,a
    jp pe,@overflow
    or a
    ret
@overflow:
    scf
    ret

; Translate one signed 16-bit vec3 in place.
;
; This performs component-wise integer addition. Both operands must use the
; same Pingo domain, normally translation-distance units.
;
; inputs:
;   ix -> six-byte source/destination vec3
;   iy -> six-byte translation vec3
; outputs:
;   (ix) = (ix) + (iy)
;   carry clear on success
;   carry set if any signed component overflows
;   vector is unchanged on overflow
; destroys:
;   af, bc, de, hl
; preserves:
;   ix, iy, and all shadow registers
p3d_vec3_translate16:
    ld l,(ix+p3d_vec3_x)
    ld h,(ix+p3d_vec3_x+1)
    ld e,(iy+p3d_vec3_x)
    ld d,(iy+p3d_vec3_x+1)
    call p3d_sadd16
    ret c
    push hl
    ld l,(ix+p3d_vec3_y)
    ld h,(ix+p3d_vec3_y+1)
    ld e,(iy+p3d_vec3_y)
    ld d,(iy+p3d_vec3_y+1)
    call p3d_sadd16
    jr c,@y_failed
    push hl
    ld l,(ix+p3d_vec3_z)
    ld h,(ix+p3d_vec3_z+1)
    ld e,(iy+p3d_vec3_z)
    ld d,(iy+p3d_vec3_z+1)
    call p3d_sadd16
    jr c,@z_failed
    ld c,l
    ld b,h
    pop hl
    ld (ix+p3d_vec3_y),l
    ld (ix+p3d_vec3_y+1),h
    pop hl
    ld (ix+p3d_vec3_x),l
    ld (ix+p3d_vec3_x+1),h
    ld (ix+p3d_vec3_z),c
    ld (ix+p3d_vec3_z+1),b
    or a
    ret
@z_failed:
    pop hl
@y_failed:
    pop hl
    scf
    ret

; Load a*cos and b*sin into opposite GP banks.
; Requires BC=sin, DE=cos, IX=vector.
    MACRO P3D_ROT_LOAD_COS_SIN a_offset, b_offset
    ld a,c
    exx
    ld e,a
    exx
    ld a,b
    exx
    ld d,a
    ld l,(ix+b_offset)
    ld h,(ix+b_offset+1)
    exx
    ld l,(ix+a_offset)
    ld h,(ix+a_offset+1)
    ENDMACRO

; Load a*sin and b*cos into opposite GP banks.
; Requires BC=sin, DE=cos, IX=vector.
    MACRO P3D_ROT_LOAD_SIN_COS a_offset, b_offset
    ld a,e
    exx
    ld e,a
    exx
    ld a,d
    exx
    ld d,a
    ld l,(ix+b_offset)
    ld h,(ix+b_offset+1)
    exx
    ld e,c
    ld d,b
    ld l,(ix+a_offset)
    ld h,(ix+a_offset+1)
    ENDMACRO

; Multiply the two active/shadow operand pairs, add, and normalize.
p3d_rot_muladd_norm:
    call p3d_smul16x16_32
    exx
    call p3d_smul16x16_32
    call p3d_sadd32
    ret c
    jp p3d_sdiv32767_32_to_16

; Multiply the two active/shadow operand pairs, subtract, and normalize.
p3d_rot_mulsub_norm:
    call p3d_smul16x16_32
    exx
    call p3d_smul16x16_32
    call p3d_ssub32
    ret c
    jp p3d_sdiv32767_32_to_16

; Matrix-row equivalents clamp only the exact +/-32768 Q15 boundary.
p3d_mat_rot_muladd_norm:
    call p3d_smul16x16_32
    exx
    call p3d_smul16x16_32
    call p3d_sadd32
    ret c
    jp p3d_sdiv32767_32_to_q15_16

p3d_mat_rot_mulsub_norm:
    call p3d_smul16x16_32
    exx
    call p3d_smul16x16_32
    call p3d_ssub32
    ret c
    jp p3d_sdiv32767_32_to_q15_16

; Rotate one signed 16-bit vec3 around the X axis in place.
;
; inputs:
;   ix -> six-byte source/destination vec3
;   hl = signed Pingo rotation angle (low word)
; outputs:
;   rotated vec3 at (ix)
;   carry clear on success
;   carry set on arithmetic overflow
; destroys:
;   af, af', bc, de, hl, bc', de', hl'
; preserves:
;   ix, iy; vector is unchanged on failure
    MACRO P3D_VEC3_ROTATE_X_BODY mulsub_routine, muladd_routine
    push iy
    push hl
    call p3d_sincos16
    P3D_ROT_LOAD_COS_SIN p3d_vec3_y,p3d_vec3_z
    call mulsub_routine
    jr c,@first_failed
    push hl
    pop iy
    pop hl
    call p3d_sincos16
    P3D_ROT_LOAD_SIN_COS p3d_vec3_y,p3d_vec3_z
    call muladd_routine
    jr c,@second_failed
    ld e,l
    ld d,h
    push iy
    pop hl
    ld (ix+p3d_vec3_y),l
    ld (ix+p3d_vec3_y+1),h
    ld (ix+p3d_vec3_z),e
    ld (ix+p3d_vec3_z+1),d
    pop iy
    or a
    ret
@second_failed:
    pop iy
    scf
    ret
@first_failed:
    pop hl
    pop iy
    scf
    ret
    ENDMACRO

p3d_vec3_rotate_x16:
    P3D_VEC3_ROTATE_X_BODY p3d_rot_mulsub_norm,p3d_rot_muladd_norm

; Internal Q15 row rotation used only by orientation matrices.
p3d_mat3_row_rotate_x16:
    P3D_VEC3_ROTATE_X_BODY p3d_mat_rot_mulsub_norm,p3d_mat_rot_muladd_norm

; Rotate one signed 16-bit vec3 around the Y axis in place.
;
; inputs:
;   ix -> six-byte source/destination vec3
;   hl = signed Pingo rotation angle (low word)
; outputs:
;   rotated vec3 at (ix)
;   carry clear on success
;   carry set on arithmetic overflow
; destroys:
;   af, af', bc, de, hl, bc', de', hl'
; preserves:
;   ix, iy; vector is unchanged on failure
    MACRO P3D_VEC3_ROTATE_Y_BODY muladd_routine, mulsub_routine
    push iy
    push hl
    call p3d_sincos16
    P3D_ROT_LOAD_COS_SIN p3d_vec3_x,p3d_vec3_z
    call muladd_routine
    jr c,@first_failed
    push hl
    pop iy
    pop hl
    call p3d_sincos16
    P3D_ROT_LOAD_COS_SIN p3d_vec3_z,p3d_vec3_x
    call mulsub_routine
    jr c,@second_failed
    ld e,l
    ld d,h
    push iy
    pop hl
    ld (ix+p3d_vec3_x),l
    ld (ix+p3d_vec3_x+1),h
    ld (ix+p3d_vec3_z),e
    ld (ix+p3d_vec3_z+1),d
    pop iy
    or a
    ret
@second_failed:
    pop iy
    scf
    ret
@first_failed:
    pop hl
    pop iy
    scf
    ret
    ENDMACRO

p3d_vec3_rotate_y16:
    P3D_VEC3_ROTATE_Y_BODY p3d_rot_muladd_norm,p3d_rot_mulsub_norm

; Internal Q15 row rotation used only by orientation matrices.
p3d_mat3_row_rotate_y16:
    P3D_VEC3_ROTATE_Y_BODY p3d_mat_rot_muladd_norm,p3d_mat_rot_mulsub_norm

; Rotate one signed 16-bit vec3 around the Z axis in place.
;
; inputs:
;   ix -> six-byte source/destination vec3
;   hl = signed Pingo rotation angle (low word)
; outputs:
;   rotated vec3 at (ix)
;   carry clear on success
;   carry set on arithmetic overflow
; destroys:
;   af, af', bc, de, hl, bc', de', hl'
; preserves:
;   ix, iy; vector is unchanged on failure
    MACRO P3D_VEC3_ROTATE_Z_BODY mulsub_routine, muladd_routine
    push iy
    push hl
    call p3d_sincos16
    P3D_ROT_LOAD_COS_SIN p3d_vec3_x,p3d_vec3_y
    call mulsub_routine
    jr c,@first_failed
    push hl
    pop iy
    pop hl
    call p3d_sincos16
    P3D_ROT_LOAD_SIN_COS p3d_vec3_x,p3d_vec3_y
    call muladd_routine
    jr c,@second_failed
    ld e,l
    ld d,h
    push iy
    pop hl
    ld (ix+p3d_vec3_x),l
    ld (ix+p3d_vec3_x+1),h
    ld (ix+p3d_vec3_y),e
    ld (ix+p3d_vec3_y+1),d
    pop iy
    or a
    ret
@second_failed:
    pop iy
    scf
    ret
@first_failed:
    pop hl
    pop iy
    scf
    ret
    ENDMACRO

p3d_vec3_rotate_z16:
    P3D_VEC3_ROTATE_Z_BODY p3d_rot_mulsub_norm,p3d_rot_muladd_norm

; Internal Q15 row rotation used only by orientation matrices.
p3d_mat3_row_rotate_z16:
    P3D_VEC3_ROTATE_Z_BODY p3d_mat_rot_mulsub_norm,p3d_mat_rot_muladd_norm

; Apply Pingo-order Euler rotations to one signed 16-bit vec3 in place.
;
; Rotation order is X, then Y, then Z, matching Pingo transform construction.
;
; inputs:
;   ix -> six-byte source/destination vec3
;   iy -> six-byte angle vec3 (X, Y, Z)
; outputs:
;   rotated vec3 at (ix)
;   carry clear on success
;   carry set on arithmetic overflow
; destroys:
;   af, af', bc, de, hl, bc', de', hl'
; note:
;   The vector is restored to its original value if any axis fails.
p3d_vec3_rotate_xyz16:
; Snapshot the vector and all angles before any in-place write.
    ld l,(ix+p3d_vec3_x)
    ld h,(ix+p3d_vec3_x+1)
    push hl
    ld l,(ix+p3d_vec3_y)
    ld h,(ix+p3d_vec3_y+1)
    push hl
    ld l,(ix+p3d_vec3_z)
    ld h,(ix+p3d_vec3_z+1)
    push hl
    ld l,(iy+p3d_vec3_z)
    ld h,(iy+p3d_vec3_z+1)
    push hl
    ld l,(iy+p3d_vec3_y)
    ld h,(iy+p3d_vec3_y+1)
    push hl
    ld l,(iy+p3d_vec3_x)
    ld h,(iy+p3d_vec3_x+1)
    push hl
    pop hl
    call p3d_vec3_rotate_x16
    jr c,@x_failed
    pop hl
    call p3d_vec3_rotate_y16
    jr c,@y_failed
    pop hl
    call p3d_vec3_rotate_z16
    jr c,@z_failed
; Discard the saved original Z, Y, X.
    pop hl
    pop hl
    pop hl
    or a
    ret
@x_failed:
    pop hl                  ; unused Y angle
@y_failed:
    pop hl                  ; unused Z angle
@z_failed:
; Restore original Z, Y, X.
    pop hl
    ld (ix+p3d_vec3_z),l
    ld (ix+p3d_vec3_z+1),h
    pop hl
    ld (ix+p3d_vec3_y),l
    ld (ix+p3d_vec3_y+1),h
    pop hl
    ld (ix+p3d_vec3_x),l
    ld (ix+p3d_vec3_x+1),h
    scf
    ret

; ---------------------------------------------------------------------------
; Matrix-vector primitives
; ---------------------------------------------------------------------------

; Multiply a signed normalized 3x3 matrix by one signed 16-bit vec3.
;
; Matrix storage is row-major, matching Pingo. Each element is a signed
; normalized 16-bit coefficient, so the matrix occupies 18 bytes.
;
; inputs:
;   ix -> six-byte source/destination vec3
;   iy -> 18-byte row-major matrix
; outputs:
;   transformed vec3 at (ix)
;   carry clear on success
;   carry set on arithmetic overflow
; destroys:
;   af, af', bc, de, hl, bc', de', hl'
; preserves:
;   ix, iy; vector is unchanged on failure
p3d_mat3_mul_vec3_16:
    push iy
    call p3d_mat3_row_mul_vec3_16
    jr c,@row0_failed
    push hl
    lea iy,iy+6
    call p3d_mat3_row_mul_vec3_16
    jr c,@row1_failed
    push hl
    lea iy,iy+6
    call p3d_mat3_row_mul_vec3_16
    jr c,@row2_failed
    ld e,l
    ld d,h
    pop hl
    ld (ix+p3d_vec3_y),l
    ld (ix+p3d_vec3_y+1),h
    pop hl
    ld (ix+p3d_vec3_x),l
    ld (ix+p3d_vec3_x+1),h
    ld (ix+p3d_vec3_z),e
    ld (ix+p3d_vec3_z+1),d
    pop iy
    or a
    ret
@row2_failed:
    pop hl
@row1_failed:
    pop hl
@row0_failed:
    pop iy
    scf
    ret

; Multiply the row at IY by the vector at IX, accumulate all three products
; at signed 32-bit width, then normalize once.
p3d_mat3_row_mul_vec3_16:
; product 0 operands in the active bank
    ld l,(ix+p3d_vec3_x)
    ld h,(ix+p3d_vec3_x+1)
    ld e,(iy+0)
    ld d,(iy+1)
; product 1 operands in the shadow bank
    exx
    ld l,(ix+p3d_vec3_y)
    ld h,(ix+p3d_vec3_y+1)
    ld e,(iy+2)
    ld d,(iy+3)
    exx
    call p3d_smul16x16_32
    exx
    call p3d_smul16x16_32
    call p3d_sadd32
    ret c
; park the two-product sum and form product 2 in the opposite bank
    exx
    ld l,(ix+p3d_vec3_z)
    ld h,(ix+p3d_vec3_z+1)
    ld e,(iy+4)
    ld d,(iy+5)
    call p3d_smul16x16_32
    call p3d_sadd32
    ret c
    jp p3d_sdiv32767_32_to_16

; ---------------------------------------------------------------------------
; Matrix composition and orientation conversion
; ---------------------------------------------------------------------------

; Multiply two signed-Q15 row-major matrices in place.
;
; inputs:
;   ix -> left/source/destination matrix A
;   iy -> right/source matrix B
; outputs:
;   (ix) = A*B
;   carry clear on success
;   carry set on signed accumulator or narrowed-result overflow
; destroys:
;   af, af', bc, de, hl, bc', de', hl'
; preserves:
;   ix, iy; A is unchanged on failure
; note:
;   Exact IX=IY aliasing is supported. No output is committed until all nine
;   dot products have succeeded.
p3d_mat3_mul_mat3_16:
    push ix
    push iy
    call p3d_mat3_dot_row_col16
    jp c,@result0_failed
    push hl
    lea iy,iy+2
    call p3d_mat3_dot_row_col16
    jp c,@result1_failed
    push hl
    lea iy,iy+2
    call p3d_mat3_dot_row_col16
    jp c,@result2_failed
    push hl
    lea iy,iy-4
    lea ix,ix+6
    call p3d_mat3_dot_row_col16
    jp c,@result3_failed
    push hl
    lea iy,iy+2
    call p3d_mat3_dot_row_col16
    jp c,@result4_failed
    push hl
    lea iy,iy+2
    call p3d_mat3_dot_row_col16
    jp c,@result5_failed
    push hl
    lea iy,iy-4
    lea ix,ix+6
    call p3d_mat3_dot_row_col16
    jp c,@result6_failed
    push hl
    lea iy,iy+2
    call p3d_mat3_dot_row_col16
    jp c,@result7_failed
    push hl
    lea iy,iy+2
    call p3d_mat3_dot_row_col16
    jp c,@result8_failed
    push hl
; Restore the working pointers to their bases, then commit in reverse order.
    lea ix,ix-12
    lea iy,iy-4
    pop hl
    ld (ix+p3d_mat3_r2c2),l
    ld (ix+p3d_mat3_r2c2+1),h
    pop hl
    ld (ix+p3d_mat3_r2c1),l
    ld (ix+p3d_mat3_r2c1+1),h
    pop hl
    ld (ix+p3d_mat3_r2c0),l
    ld (ix+p3d_mat3_r2c0+1),h
    pop hl
    ld (ix+p3d_mat3_r1c2),l
    ld (ix+p3d_mat3_r1c2+1),h
    pop hl
    ld (ix+p3d_mat3_r1c1),l
    ld (ix+p3d_mat3_r1c1+1),h
    pop hl
    ld (ix+p3d_mat3_r1c0),l
    ld (ix+p3d_mat3_r1c0+1),h
    pop hl
    ld (ix+p3d_mat3_r0c2),l
    ld (ix+p3d_mat3_r0c2+1),h
    pop hl
    ld (ix+p3d_mat3_r0c1),l
    ld (ix+p3d_mat3_r0c1+1),h
    pop hl
    ld (ix+p3d_mat3_r0c0),l
    ld (ix+p3d_mat3_r0c0+1),h
    pop iy
    pop ix
    or a
    ret
@result8_failed:
    pop hl
@result7_failed:
    pop hl
@result6_failed:
    pop hl
@result5_failed:
    pop hl
@result4_failed:
    pop hl
@result3_failed:
    pop hl
@result2_failed:
    pop hl
@result1_failed:
    pop hl
@result0_failed:
    pop iy
    pop ix
    scf
    ret

; Dot the row beginning at IX with the column beginning at IY. B's column
; elements are six bytes apart.
p3d_mat3_dot_row_col16:
    ld l,(ix+0)
    ld h,(ix+1)
    ld e,(iy+0)
    ld d,(iy+1)
    exx
    ld l,(ix+2)
    ld h,(ix+3)
    ld e,(iy+6)
    ld d,(iy+7)
    exx
    call p3d_smul16x16_32
    exx
    call p3d_smul16x16_32
    call p3d_sadd32
    ret c
    exx
    ld l,(ix+4)
    ld h,(ix+5)
    ld e,(iy+12)
    ld d,(iy+13)
    call p3d_smul16x16_32
    call p3d_sadd32
    ret c
    jp p3d_sdiv32767_32_to_16

; Right-multiply a local-to-world matrix by one axis rotation. A row vector
; right-multiplied by Raxis(angle) is the existing column-vector axis rotation
; applied to that row with -angle.
    MACRO P3D_MAT3_LOCAL_AXIS_BODY vector_routine
    push iy
    push ix
; IY retains the negated angle across all three row calls.
    xor a
    sub l
    ld l,a
    ld a,0
    sbc a,h
    ld h,a
    push hl
    pop iy
; Snapshot all nine logical words for transactional failure.
    ld l,(ix+0)
    ld h,(ix+1)
    push hl
    ld l,(ix+2)
    ld h,(ix+3)
    push hl
    ld l,(ix+4)
    ld h,(ix+5)
    push hl
    ld l,(ix+6)
    ld h,(ix+7)
    push hl
    ld l,(ix+8)
    ld h,(ix+9)
    push hl
    ld l,(ix+10)
    ld h,(ix+11)
    push hl
    ld l,(ix+12)
    ld h,(ix+13)
    push hl
    ld l,(ix+14)
    ld h,(ix+15)
    push hl
    ld l,(ix+16)
    ld h,(ix+17)
    push hl
    push iy
    pop hl
    call vector_routine
    jr c,@row0_failed
    lea ix,ix+6
    push iy
    pop hl
    call vector_routine
    jr c,@row1_failed
    lea ix,ix+6
    push iy
    pop hl
    call vector_routine
    jr c,@row2_failed
    lea ix,ix-12
; Discard the saved matrix.
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop ix
    pop iy
    or a
    ret
@row2_failed:
    lea ix,ix-12
    jr @restore
@row1_failed:
    lea ix,ix-6
    jr @restore
@row0_failed:
@restore:
; Restore elements 8..0 from the reverse-order stack snapshot.
    pop hl
    ld (ix+16),l
    ld (ix+17),h
    pop hl
    ld (ix+14),l
    ld (ix+15),h
    pop hl
    ld (ix+12),l
    ld (ix+13),h
    pop hl
    ld (ix+10),l
    ld (ix+11),h
    pop hl
    ld (ix+8),l
    ld (ix+9),h
    pop hl
    ld (ix+6),l
    ld (ix+7),h
    pop hl
    ld (ix+4),l
    ld (ix+5),h
    pop hl
    ld (ix+2),l
    ld (ix+3),h
    pop hl
    ld (ix+0),l
    ld (ix+1),h
    pop ix
    pop iy
    scf
    ret
    ENDMACRO

; inputs: IX=matrix, HL=Pingo angle. IX/IY and matrix are preserved on failure.
p3d_mat3_rotate_local_x16:
    P3D_MAT3_LOCAL_AXIS_BODY p3d_mat3_row_rotate_x16
p3d_mat3_rotate_local_y16:
    P3D_MAT3_LOCAL_AXIS_BODY p3d_mat3_row_rotate_y16
p3d_mat3_rotate_local_z16:
    P3D_MAT3_LOCAL_AXIS_BODY p3d_mat3_row_rotate_z16

; Apply one intrinsic local Euler delta to a local-to-world orientation.
; Fixed-point operations are deliberately ordered as:
;
;   ((R * Rz(dz)) * Ry(dy)) * Rx(dx)
;
; This is continuously equivalent to R*(Rz*Ry*Rx), while making the exact
; integer rounding order explicit and avoiding construction of a temporary
; matrix.
;
; inputs:
;   ix -> matrix
;   iy -> Pingo-angle vec3
; outputs:
;   updated matrix, carry as for the axis routines
; destroys:
;   af, af', bc, de, hl, bc', de', hl'
; preserves:
;   ix, iy; matrix is unchanged if any axis fails
p3d_mat3_rotate_local_xyz16:
; Whole-operation snapshot, because each individual axis is only locally
; transactional.
    ld l,(ix+0)
    ld h,(ix+1)
    push hl
    ld l,(ix+2)
    ld h,(ix+3)
    push hl
    ld l,(ix+4)
    ld h,(ix+5)
    push hl
    ld l,(ix+6)
    ld h,(ix+7)
    push hl
    ld l,(ix+8)
    ld h,(ix+9)
    push hl
    ld l,(ix+10)
    ld h,(ix+11)
    push hl
    ld l,(ix+12)
    ld h,(ix+13)
    push hl
    ld l,(ix+14)
    ld h,(ix+15)
    push hl
    ld l,(ix+16)
    ld h,(ix+17)
    push hl
    ld l,(iy+p3d_vec3_z)
    ld h,(iy+p3d_vec3_z+1)
    call p3d_mat3_rotate_local_z16
    jr c,@failed
    ld l,(iy+p3d_vec3_y)
    ld h,(iy+p3d_vec3_y+1)
    call p3d_mat3_rotate_local_y16
    jr c,@failed
    ld l,(iy+p3d_vec3_x)
    ld h,(iy+p3d_vec3_x+1)
    call p3d_mat3_rotate_local_x16
    jr c,@failed
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    or a
    ret
@failed:
    pop hl
    ld (ix+16),l
    ld (ix+17),h
    pop hl
    ld (ix+14),l
    ld (ix+15),h
    pop hl
    ld (ix+12),l
    ld (ix+13),h
    pop hl
    ld (ix+10),l
    ld (ix+11),h
    pop hl
    ld (ix+8),l
    ld (ix+9),h
    pop hl
    ld (ix+6),l
    ld (ix+7),h
    pop hl
    ld (ix+4),l
    ld (ix+5),h
    pop hl
    ld (ix+2),l
    ld (ix+3),h
    pop hl
    ld (ix+0),l
    ld (ix+1),h
    scf
    ret

; Build a canonical local-to-world matrix from Pingo XYZ Euler angles.
;
; inputs:
;   ix -> destination matrix
;   iy -> Pingo-angle vec3
; outputs:
;   matrix = Rz(z)*Ry(y)*Rx(x)
; destroys:
;   af, af', bc, de, hl, bc', de', hl'
; preserves:
;   ix, iy; matrix is unchanged on failure
p3d_mat3_from_euler16:
    ld l,(ix+0)
    ld h,(ix+1)
    push hl
    ld l,(ix+2)
    ld h,(ix+3)
    push hl
    ld l,(ix+4)
    ld h,(ix+5)
    push hl
    ld l,(ix+6)
    ld h,(ix+7)
    push hl
    ld l,(ix+8)
    ld h,(ix+9)
    push hl
    ld l,(ix+10)
    ld h,(ix+11)
    push hl
    ld l,(ix+12)
    ld h,(ix+13)
    push hl
    ld l,(ix+14)
    ld h,(ix+15)
    push hl
    ld l,(ix+16)
    ld h,(ix+17)
    push hl
    ld hl,32767
    ld (ix+0),l
    ld (ix+1),h
    ld (ix+8),l
    ld (ix+9),h
    ld (ix+16),l
    ld (ix+17),h
    ld hl,0
    ld (ix+2),l
    ld (ix+3),h
    ld (ix+4),l
    ld (ix+5),h
    ld (ix+6),l
    ld (ix+7),h
    ld (ix+10),l
    ld (ix+11),h
    ld (ix+12),l
    ld (ix+13),h
    ld (ix+14),l
    ld (ix+15),h
    call p3d_mat3_rotate_local_xyz16
    jr c,@failed
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    or a
    ret
@failed:
    pop hl
    ld (ix+16),l
    ld (ix+17),h
    pop hl
    ld (ix+14),l
    ld (ix+15),h
    pop hl
    ld (ix+12),l
    ld (ix+13),h
    pop hl
    ld (ix+10),l
    ld (ix+11),h
    pop hl
    ld (ix+8),l
    ld (ix+9),h
    pop hl
    ld (ix+6),l
    ld (ix+7),h
    pop hl
    ld (ix+4),l
    ld (ix+5),h
    pop hl
    ld (ix+2),l
    ld (ix+3),h
    pop hl
    ld (ix+0),l
    ld (ix+1),h
    scf
    ret

; Build the fine camera local-to-world orientation for roll zero. This is the
; closed form Ry(y)*Rx(x), avoiding the coarse general Euler rotators while
; keeping the retained matrix byte-consistent with the emitted fine angles.
;
; inputs:
;   ix -> destination matrix
;   iy -> Pingo-angle vec3; z is ignored and must semantically be zero
; outputs:
;   matrix = Ry(y)*Rx(x)
;   carry clear on success
; destroys:
;   af, af', bc, de, hl, bc', de', hl'
; preserves:
;   ix, iy
;
; This helper is used inside the camera's whole-state transaction. A
; theoretical multiply failure may leave a partial destination for that
; outer transaction to restore.
p3d_camera_mat3_from_euler_fine16:
    push iy
    ld l,(iy+p3d_vec3_x)
    ld h,(iy+p3d_vec3_x+1)
    call p3d_sincos_fine16
    push bc                 ; +9 sx
    push de                 ; +6 cx
    ld l,(iy+p3d_vec3_y)
    ld h,(iy+p3d_vec3_y+1)
    call p3d_sincos_fine16
    push bc                 ; +3 sy
    push de                 ; +0 cy
    ld iy,0
    add iy,sp

; Direct coefficients and signs.
    ld l,(iy+0)
    ld h,(iy+1)
    ld (ix+p3d_mat3_r0c0),l
    ld (ix+p3d_mat3_r0c0+1),h
    ld l,(iy+6)
    ld h,(iy+7)
    ld (ix+p3d_mat3_r1c1),l
    ld (ix+p3d_mat3_r1c1+1),h
    ld hl,0
    ld (ix+p3d_mat3_r1c0),l
    ld (ix+p3d_mat3_r1c0+1),h
    ld l,(iy+9)
    ld h,(iy+10)
    xor a
    sub l
    ld l,a
    ld a,0
    sbc a,h
    ld h,a
    ld (ix+p3d_mat3_r1c2),l
    ld (ix+p3d_mat3_r1c2+1),h
    ld l,(iy+3)
    ld h,(iy+4)
    xor a
    sub l
    ld l,a
    ld a,0
    sbc a,h
    ld h,a
    ld (ix+p3d_mat3_r2c0),l
    ld (ix+p3d_mat3_r2c0+1),h

; r01 = sy*sx.
    ld l,(iy+3)
    ld h,(iy+4)
    ld e,(iy+9)
    ld d,(iy+10)
    call p3d_smul_norm16
    jr c,@failed
    ld (ix+p3d_mat3_r0c1),l
    ld (ix+p3d_mat3_r0c1+1),h
; r02 = sy*cx.
    ld l,(iy+3)
    ld h,(iy+4)
    ld e,(iy+6)
    ld d,(iy+7)
    call p3d_smul_norm16
    jr c,@failed
    ld (ix+p3d_mat3_r0c2),l
    ld (ix+p3d_mat3_r0c2+1),h
; r21 = cy*sx.
    ld l,(iy+0)
    ld h,(iy+1)
    ld e,(iy+9)
    ld d,(iy+10)
    call p3d_smul_norm16
    jr c,@failed
    ld (ix+p3d_mat3_r2c1),l
    ld (ix+p3d_mat3_r2c1+1),h
; r22 = cy*cx.
    ld l,(iy+0)
    ld h,(iy+1)
    ld e,(iy+6)
    ld d,(iy+7)
    call p3d_smul_norm16
    jr c,@failed
    ld (ix+p3d_mat3_r2c2),l
    ld (ix+p3d_mat3_r2c2+1),h
    pop hl
    pop hl
    pop hl
    pop hl
    pop iy
    or a
    ret
@failed:
    pop hl
    pop hl
    pop hl
    pop hl
    pop iy
    scf
    ret

; Export a row-major local-to-world matrix as canonical Pingo XYZ Euler words.
; The convention is R=Rz*Ry*Rx, with pitch in -quarter..+quarter turn.
;
; inputs:
;   ix -> matrix
;   iy -> output angle vec3
; outputs:
;   canonical angle vec3
;   carry clear
; destroys:
;   af, af', bc, de, hl, bc', de', hl'
; preserves:
;   ix, iy
p3d_mat3_to_euler16:
; y = asin(-r20), saturating the otherwise unrepresentable -(-32768).
    ld l,(ix+p3d_mat3_r2c0)
    ld h,(ix+p3d_mat3_r2c0+1)
    ld a,h
    cp 0x80
    jr nz,@negate_pitch
    ld a,l
    or a
    jr nz,@negate_pitch
    ld hl,32767
    jr @pitch_ready
@negate_pitch:
    xor a
    sub l
    ld l,a
    ld a,0
    sbc a,h
    ld h,a
@pitch_ready:
    call p3d_asin16
    push hl                  ; canonical Y
; Gimbal lock is exactly the cardinal pitch bins +/-8192.
    ld a,h
    cp 0x20
    jr nz,@check_negative_gimbal
    ld a,l
    or a
    jr z,@gimbal
@check_negative_gimbal:
    ld a,h
    cp 0xe0
    jr nz,@nonsingular
    ld a,l
    or a
    jr z,@gimbal

@nonsingular:
; x = atan2(r21,r22)
    ld l,(ix+p3d_mat3_r2c1)
    ld h,(ix+p3d_mat3_r2c1+1)
    ld e,(ix+p3d_mat3_r2c2)
    ld d,(ix+p3d_mat3_r2c2+1)
    call p3d_atan2_16
    push hl
; z = atan2(r10,r00)
    ld l,(ix+p3d_mat3_r1c0)
    ld h,(ix+p3d_mat3_r1c0+1)
    ld e,(ix+p3d_mat3_r0c0)
    ld d,(ix+p3d_mat3_r0c0+1)
    call p3d_atan2_16
    ld (iy+p3d_vec3_z),l
    ld (iy+p3d_vec3_z+1),h
    pop hl
    ld (iy+p3d_vec3_x),l
    ld (iy+p3d_vec3_x+1),h
    pop hl
    ld (iy+p3d_vec3_y),l
    ld (iy+p3d_vec3_y+1),h
    or a
    ret

@gimbal:
; Canonical lock: z=0, x=atan2(-r12,r11). This preserves x-z at +90
; degrees and x+z at -90 degrees.
    ld l,(ix+p3d_mat3_r1c2)
    ld h,(ix+p3d_mat3_r1c2+1)
    ld a,h
    cp 0x80
    jr nz,@negate_lock_y
    ld a,l
    or a
    jr nz,@negate_lock_y
    ld hl,32767
    jr @lock_y_ready
@negate_lock_y:
    xor a
    sub l
    ld l,a
    ld a,0
    sbc a,h
    ld h,a
@lock_y_ready:
    ld e,(ix+p3d_mat3_r1c1)
    ld d,(ix+p3d_mat3_r1c1+1)
    call p3d_atan2_16
    ld (iy+p3d_vec3_x),l
    ld (iy+p3d_vec3_x+1),h
    pop hl
    ld (iy+p3d_vec3_y),l
    ld (iy+p3d_vec3_y+1),h
    ld hl,0
    ld (iy+p3d_vec3_z),l
    ld (iy+p3d_vec3_z+1),h
    or a
    ret

; ---------------------------------------------------------------------------
; Persistent eZ80-side Pingo object state
; ---------------------------------------------------------------------------

; Initialize all 64 bytes of one object state.
;
; inputs:
;   ix -> destination p3d object state
;   iy -> four-word tuple: sid, oid, mid, bmid
; outputs:
;   identity pose, unit scale, zero velocities/residuals, copied IDs
;   all four known dirty bits set for initial Pingo synchronization
;   carry clear
; destroys:
;   af, bc, de, hl
; preserves:
;   ix, iy and all shadow registers
; note:
;   The ID tuple may alias the destination; it is captured before the state is
;   overwritten.
p3d_object_init16:
    push ix
    push iy
    ld l,(iy+p3d_object_ids_sid)
    ld h,(iy+p3d_object_ids_sid+1)
    push hl
    ld l,(iy+p3d_object_ids_oid)
    ld h,(iy+p3d_object_ids_oid+1)
    push hl
    ld l,(iy+p3d_object_ids_mid)
    ld h,(iy+p3d_object_ids_mid+1)
    push hl
    ld l,(iy+p3d_object_ids_bmid)
    ld h,(iy+p3d_object_ids_bmid+1)
    push hl
; Seed byte zero, then replicate it over the remaining 63 bytes.
    xor a
    ld (ix+0),a
    push ix
    pop hl
    push ix
    pop de
    inc de
    ld bc,p3d_object_size-1
    ldir
; Restore the captured creation IDs.
    pop hl
    ld (ix+p3d_object_bmid),l
    ld (ix+p3d_object_bmid+1),h
    pop hl
    ld (ix+p3d_object_mid),l
    ld (ix+p3d_object_mid+1),h
    pop hl
    ld (ix+p3d_object_oid),l
    ld (ix+p3d_object_oid+1),h
    pop hl
    ld (ix+p3d_object_sid),l
    ld (ix+p3d_object_sid+1),h
    ld a,p3d_object_dirty_all
    ld (ix+p3d_object_dirty),a
; Pingo unit scale is unsigned 8.8 value 256.
    ld hl,256
    ld (ix+p3d_object_scale+p3d_vec3_x),l
    ld (ix+p3d_object_scale+p3d_vec3_x+1),h
    ld (ix+p3d_object_scale+p3d_vec3_y),l
    ld (ix+p3d_object_scale+p3d_vec3_y+1),h
    ld (ix+p3d_object_scale+p3d_vec3_z),l
    ld (ix+p3d_object_scale+p3d_vec3_z+1),h
; Signed-Q15 identity orientation.
    ld hl,32767
    ld (ix+p3d_object_orientation+p3d_mat3_r0c0),l
    ld (ix+p3d_object_orientation+p3d_mat3_r0c0+1),h
    ld (ix+p3d_object_orientation+p3d_mat3_r1c1),l
    ld (ix+p3d_object_orientation+p3d_mat3_r1c1+1),h
    ld (ix+p3d_object_orientation+p3d_mat3_r2c2),l
    ld (ix+p3d_object_orientation+p3d_mat3_r2c2+1),h
    pop iy
    pop ix
    or a
    ret

; Return Z when an angle maps to the identity lookup-table phase.
; inputs: HL=Pingo angle. Destroys AF,BC,DE,HL; preserves indexes/shadows.
p3d_angle_is_identity16:
    call p3d_sincos16
    ld a,b
    or c
    jr nz,@not_identity
    ld a,d
    cp 0x7f
    jr nz,@not_identity
    ld a,e
    cp 0xff
    jr nz,@not_identity
    xor a
    ret
@not_identity:
    ld a,1
    or a
    ret

; Finish a successful object-orientation update. IX is the state pointer.
; This exports canonical absolute Euler words and then rebuilds the internal
; matrix from those exact words, keeping eZ80 movement and Pingo rendering
; aligned while removing fixed-point orthogonality drift.
p3d_object_finish_rotation16:
    lea iy,ix+p3d_object_pingo_rotation
    lea ix,ix+p3d_object_orientation
    call p3d_mat3_to_euler16
    call p3d_mat3_from_euler16
    lea ix,ix-p3d_object_orientation
    ret c
    or a
    ret

; The object-rotation wrappers have 13 ADL words on the stack in this order:
; dirty, Euler X/Y/Z, matrix 0..8. With matrix 8 on top, the old Euler Z/Y/X
; low bytes are at SP+27/+30/+33. Mark rotation dirty only when the absolute
; Pingo Euler command actually changed.
    MACRO P3D_OBJECT_MARK_ROTATION_IF_CHANGED
    ld iy,0
    add iy,sp
    ld a,(ix+p3d_object_pingo_rotation+0)
    cp (iy+33)
    jr nz,@changed
    ld a,(ix+p3d_object_pingo_rotation+1)
    cp (iy+34)
    jr nz,@changed
    ld a,(ix+p3d_object_pingo_rotation+2)
    cp (iy+30)
    jr nz,@changed
    ld a,(ix+p3d_object_pingo_rotation+3)
    cp (iy+31)
    jr nz,@changed
    ld a,(ix+p3d_object_pingo_rotation+4)
    cp (iy+27)
    jr nz,@changed
    ld a,(ix+p3d_object_pingo_rotation+5)
    cp (iy+28)
    jr z,@complete
@changed:
    ld a,(ix+p3d_object_dirty)
    or p3d_object_dirty_rotation
    ld (ix+p3d_object_dirty),a
@complete:
    ENDMACRO

; Snapshot/finish body for a one-axis object-local rotation.
    MACRO P3D_OBJECT_ROTATE_LOCAL_AXIS_BODY matrix_routine
    push hl
    call p3d_angle_is_identity16
    pop hl
    ret z
; Preserve caller IY and retain the input angle there while HL is used for the
; transactional state snapshot.
    push iy
    push hl
    pop iy
    ld l,(ix+p3d_object_dirty)
    ld h,0
    push hl
    ld l,(ix+p3d_object_pingo_rotation+0)
    ld h,(ix+p3d_object_pingo_rotation+1)
    push hl
    ld l,(ix+p3d_object_pingo_rotation+2)
    ld h,(ix+p3d_object_pingo_rotation+3)
    push hl
    ld l,(ix+p3d_object_pingo_rotation+4)
    ld h,(ix+p3d_object_pingo_rotation+5)
    push hl
    ld l,(ix+p3d_object_orientation+0)
    ld h,(ix+p3d_object_orientation+1)
    push hl
    ld l,(ix+p3d_object_orientation+2)
    ld h,(ix+p3d_object_orientation+3)
    push hl
    ld l,(ix+p3d_object_orientation+4)
    ld h,(ix+p3d_object_orientation+5)
    push hl
    ld l,(ix+p3d_object_orientation+6)
    ld h,(ix+p3d_object_orientation+7)
    push hl
    ld l,(ix+p3d_object_orientation+8)
    ld h,(ix+p3d_object_orientation+9)
    push hl
    ld l,(ix+p3d_object_orientation+10)
    ld h,(ix+p3d_object_orientation+11)
    push hl
    ld l,(ix+p3d_object_orientation+12)
    ld h,(ix+p3d_object_orientation+13)
    push hl
    ld l,(ix+p3d_object_orientation+14)
    ld h,(ix+p3d_object_orientation+15)
    push hl
    ld l,(ix+p3d_object_orientation+16)
    ld h,(ix+p3d_object_orientation+17)
    push hl
    push iy
    pop hl
    lea ix,ix+p3d_object_orientation
    call matrix_routine
    lea ix,ix-p3d_object_orientation
    jr c,@discard_failed
    call p3d_object_finish_rotation16
    jr c,@restore_failed
    P3D_OBJECT_MARK_ROTATION_IF_CHANGED
; Discard 13 saved logical words.
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop iy
    or a
    ret
@discard_failed:
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop iy
    scf
    ret
@restore_failed:
; Matrix 8..0, Euler Z/Y/X, then the prior dirty byte.
    pop hl
    ld (ix+p3d_object_orientation+16),l
    ld (ix+p3d_object_orientation+17),h
    pop hl
    ld (ix+p3d_object_orientation+14),l
    ld (ix+p3d_object_orientation+15),h
    pop hl
    ld (ix+p3d_object_orientation+12),l
    ld (ix+p3d_object_orientation+13),h
    pop hl
    ld (ix+p3d_object_orientation+10),l
    ld (ix+p3d_object_orientation+11),h
    pop hl
    ld (ix+p3d_object_orientation+8),l
    ld (ix+p3d_object_orientation+9),h
    pop hl
    ld (ix+p3d_object_orientation+6),l
    ld (ix+p3d_object_orientation+7),h
    pop hl
    ld (ix+p3d_object_orientation+4),l
    ld (ix+p3d_object_orientation+5),h
    pop hl
    ld (ix+p3d_object_orientation+2),l
    ld (ix+p3d_object_orientation+3),h
    pop hl
    ld (ix+p3d_object_orientation+0),l
    ld (ix+p3d_object_orientation+1),h
    pop hl
    ld (ix+p3d_object_pingo_rotation+4),l
    ld (ix+p3d_object_pingo_rotation+5),h
    pop hl
    ld (ix+p3d_object_pingo_rotation+2),l
    ld (ix+p3d_object_pingo_rotation+3),h
    pop hl
    ld (ix+p3d_object_pingo_rotation+0),l
    ld (ix+p3d_object_pingo_rotation+1),h
    pop hl
    ld (ix+p3d_object_dirty),l
    pop iy
    scf
    ret
    ENDMACRO

; Rotate one object around its own current X/Y/Z axis.
; inputs: IX=object state, HL=Pingo angle. IX/IY are preserved.
p3d_object_rotate_local_x16:
    P3D_OBJECT_ROTATE_LOCAL_AXIS_BODY p3d_mat3_rotate_local_x16
p3d_object_rotate_local_y16:
    P3D_OBJECT_ROTATE_LOCAL_AXIS_BODY p3d_mat3_rotate_local_y16
p3d_object_rotate_local_z16:
    P3D_OBJECT_ROTATE_LOCAL_AXIS_BODY p3d_mat3_rotate_local_z16

; Rotate one object intrinsically by a local XYZ delta. Identity table phases
; leave both state and dirty flags untouched.
;
; inputs:
;   ix -> object state
;   iy -> local Pingo-angle vec3
; outputs:
;   canonicalized orientation/Euler cache and rotation dirty bit
;   carry set leaves the complete orientation/Euler/dirty subset unchanged
; destroys:
;   af, af', bc, de, hl, bc', de', hl'
; preserves:
;   ix, iy
p3d_object_rotate_local_xyz16:
; Fast identity test. Preserve IY; p3d_angle_is_identity16 already preserves
; both index registers.
    ld l,(iy+p3d_vec3_x)
    ld h,(iy+p3d_vec3_x+1)
    call p3d_angle_is_identity16
    jr nz,@apply
    ld l,(iy+p3d_vec3_y)
    ld h,(iy+p3d_vec3_y+1)
    call p3d_angle_is_identity16
    jr nz,@apply
    ld l,(iy+p3d_vec3_z)
    ld h,(iy+p3d_vec3_z+1)
    call p3d_angle_is_identity16
    ret z
@apply:
    push iy
    ld l,(ix+p3d_object_dirty)
    ld h,0
    push hl
    ld l,(ix+p3d_object_pingo_rotation+0)
    ld h,(ix+p3d_object_pingo_rotation+1)
    push hl
    ld l,(ix+p3d_object_pingo_rotation+2)
    ld h,(ix+p3d_object_pingo_rotation+3)
    push hl
    ld l,(ix+p3d_object_pingo_rotation+4)
    ld h,(ix+p3d_object_pingo_rotation+5)
    push hl
    ld l,(ix+p3d_object_orientation+0)
    ld h,(ix+p3d_object_orientation+1)
    push hl
    ld l,(ix+p3d_object_orientation+2)
    ld h,(ix+p3d_object_orientation+3)
    push hl
    ld l,(ix+p3d_object_orientation+4)
    ld h,(ix+p3d_object_orientation+5)
    push hl
    ld l,(ix+p3d_object_orientation+6)
    ld h,(ix+p3d_object_orientation+7)
    push hl
    ld l,(ix+p3d_object_orientation+8)
    ld h,(ix+p3d_object_orientation+9)
    push hl
    ld l,(ix+p3d_object_orientation+10)
    ld h,(ix+p3d_object_orientation+11)
    push hl
    ld l,(ix+p3d_object_orientation+12)
    ld h,(ix+p3d_object_orientation+13)
    push hl
    ld l,(ix+p3d_object_orientation+14)
    ld h,(ix+p3d_object_orientation+15)
    push hl
    ld l,(ix+p3d_object_orientation+16)
    ld h,(ix+p3d_object_orientation+17)
    push hl
    lea ix,ix+p3d_object_orientation
    call p3d_mat3_rotate_local_xyz16
    lea ix,ix-p3d_object_orientation
    jr c,@discard_failed
    call p3d_object_finish_rotation16
    jr c,@restore_failed
    P3D_OBJECT_MARK_ROTATION_IF_CHANGED
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop iy
    or a
    ret
@discard_failed:
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop hl
    pop iy
    scf
    ret
@restore_failed:
    pop hl
    ld (ix+p3d_object_orientation+16),l
    ld (ix+p3d_object_orientation+17),h
    pop hl
    ld (ix+p3d_object_orientation+14),l
    ld (ix+p3d_object_orientation+15),h
    pop hl
    ld (ix+p3d_object_orientation+12),l
    ld (ix+p3d_object_orientation+13),h
    pop hl
    ld (ix+p3d_object_orientation+10),l
    ld (ix+p3d_object_orientation+11),h
    pop hl
    ld (ix+p3d_object_orientation+8),l
    ld (ix+p3d_object_orientation+9),h
    pop hl
    ld (ix+p3d_object_orientation+6),l
    ld (ix+p3d_object_orientation+7),h
    pop hl
    ld (ix+p3d_object_orientation+4),l
    ld (ix+p3d_object_orientation+5),h
    pop hl
    ld (ix+p3d_object_orientation+2),l
    ld (ix+p3d_object_orientation+3),h
    pop hl
    ld (ix+p3d_object_orientation+0),l
    ld (ix+p3d_object_orientation+1),h
    pop hl
    ld (ix+p3d_object_pingo_rotation+4),l
    ld (ix+p3d_object_pingo_rotation+5),h
    pop hl
    ld (ix+p3d_object_pingo_rotation+2),l
    ld (ix+p3d_object_pingo_rotation+3),h
    pop hl
    ld (ix+p3d_object_pingo_rotation+0),l
    ld (ix+p3d_object_pingo_rotation+1),h
    pop hl
    ld (ix+p3d_object_dirty),l
    pop iy
    scf
    ret

; Transform a local displacement through the object's current orientation and
; add the resulting world displacement to its absolute position.
;
; inputs:
;   ix -> object state
;   iy -> local displacement vec3 in Pingo translation words
; outputs:
;   updated world position and position dirty bit when the rounded world delta
;   is nonzero
;   carry set leaves the object state unchanged
; destroys:
;   af, af', bc, de, hl, bc', de', hl'
; preserves:
;   ix, iy and the caller's displacement
p3d_object_translate_local16:
; Preserve caller pointers, then expose IX=delta and IY=orientation to the
; existing three-product row helper.
    push ix
    push iy
    push ix
    push iy
    pop ix
    pop iy
    lea iy,iy+p3d_object_orientation
    call p3d_mat3_row_mul_vec3_16
    jp c,@row0_failed
    push hl
    lea iy,iy+6
    call p3d_mat3_row_mul_vec3_16
    jp c,@row1_failed
    push hl
    lea iy,iy+6
    call p3d_mat3_row_mul_vec3_16
    jp c,@row2_failed
    push hl
; Park world X/Y/Z in BC'/DE'/HL', then restore the caller pointers.
    exx
    pop hl                  ; Z
    pop de                  ; Y
    pop bc                  ; X
    exx
    pop iy
    pop ix
; Candidate X.
    ld l,(ix+p3d_object_world_position+p3d_vec3_x)
    ld h,(ix+p3d_object_world_position+p3d_vec3_x+1)
    exx
    ld a,c
    exx
    ld e,a
    exx
    ld a,b
    exx
    ld d,a
    call p3d_sadd16
    ret c
    push hl
; Candidate Y.
    ld l,(ix+p3d_object_world_position+p3d_vec3_y)
    ld h,(ix+p3d_object_world_position+p3d_vec3_y+1)
    exx
    ld a,e
    exx
    ld e,a
    exx
    ld a,d
    exx
    ld d,a
    call p3d_sadd16
    jr c,@position_y_failed
    push hl
; Candidate Z.
    ld l,(ix+p3d_object_world_position+p3d_vec3_z)
    ld h,(ix+p3d_object_world_position+p3d_vec3_z+1)
    exx
    ld a,l
    exx
    ld e,a
    exx
    ld a,h
    exx
    ld d,a
    call p3d_sadd16
    jr c,@position_z_failed
    ld c,l
    ld b,h
    pop hl
    ld (ix+p3d_object_world_position+p3d_vec3_y),l
    ld (ix+p3d_object_world_position+p3d_vec3_y+1),h
    pop hl
    ld (ix+p3d_object_world_position+p3d_vec3_x),l
    ld (ix+p3d_object_world_position+p3d_vec3_x+1),h
    ld (ix+p3d_object_world_position+p3d_vec3_z),c
    ld (ix+p3d_object_world_position+p3d_vec3_z+1),b
; Dirty only when the rounded displacement actually changed the renderable
; position.
    exx
    ld a,b
    or c
    or d
    or e
    or h
    or l
    exx
    jr z,@position_complete
    ld a,(ix+p3d_object_dirty)
    or p3d_object_dirty_position
    ld (ix+p3d_object_dirty),a
@position_complete:
    or a
    ret
@position_z_failed:
    pop hl
@position_y_failed:
    pop hl
    scf
    ret
@row2_failed:
    pop hl
@row1_failed:
    pop hl
@row0_failed:
    pop iy
    pop ix
    scf
    ret

; Add one tick of persistent object-local angular and linear velocity.
;
; Angular residuals retain sub-bin rates. Per component:
;
;   total    = velocity + residual                   (16-bit angular wrap)
;   residual = ((total + 64) mod 128) - 64          (-64..63)
;   delta    = total - residual                     (multiple of 128)
;
; The tie rule is intentionally toward the positive phase, making residual
; -64 stable when velocity becomes zero. The tick applies rotation first,
; snaps the absolute Euler/matrix state, then translates through that resulting
; orientation. Any failure restores all 64 state bytes.
;
; inputs:
;   ix -> object state
; outputs:
;   integrated object state; carry set leaves all 64 bytes unchanged
; destroys:
;   af, af', bc, de, hl, bc', de', hl'
; preserves:
;   ix, iy
    MACRO P3D_OBJECT_ACCUMULATE_ANGLE velocity_offset, residual_offset, delta_offset
    ld l,(ix+velocity_offset)
    ld h,(ix+velocity_offset+1)
    ld e,(ix+residual_offset)
    ld d,(ix+residual_offset+1)
    add.s hl,de
    ld a,l
    add a,64
    and 0x7f
    sub 64
    ld e,a
    add a,a
    sbc a,a
    ld d,a
    ld (ix+residual_offset),e
    ld (ix+residual_offset+1),d
    or a
    sbc.s hl,de
    ld (iy+delta_offset),l
    ld (iy+delta_offset+1),h
    ENDMACRO

p3d_object_step16:
    push iy
    push ix
; Reserve a packed 64-byte snapshot followed by a six-byte local angular
; delta. SP arithmetic is full ADL; all public arithmetic remains low-16.
    ld hl,-70
    add hl,sp
    ld sp,hl
    ld iy,0
    add iy,sp
; Snapshot the entire state.
    push ix
    pop hl
    push iy
    pop de
    ld bc,p3d_object_size
    ldir
; Build the quantized angular delta while committing new internal residuals.
    P3D_OBJECT_ACCUMULATE_ANGLE p3d_object_local_angular_velocity+p3d_vec3_x,p3d_object_angular_residual+p3d_vec3_x,64+p3d_vec3_x
    P3D_OBJECT_ACCUMULATE_ANGLE p3d_object_local_angular_velocity+p3d_vec3_y,p3d_object_angular_residual+p3d_vec3_y,64+p3d_vec3_y
    P3D_OBJECT_ACCUMULATE_ANGLE p3d_object_local_angular_velocity+p3d_vec3_z,p3d_object_angular_residual+p3d_vec3_z,64+p3d_vec3_z
; Skip the expensive orientation path for the common zero-delta tick.
    ld a,(iy+64)
    or (iy+65)
    or (iy+66)
    or (iy+67)
    or (iy+68)
    or (iy+69)
    jr z,@rotation_complete
    lea iy,iy+64
    call p3d_object_rotate_local_xyz16
    jr c,@restore
@rotation_complete:
; Skip a static linear velocity as well.
    ld a,(ix+p3d_object_local_linear_velocity+0)
    or (ix+p3d_object_local_linear_velocity+1)
    or (ix+p3d_object_local_linear_velocity+2)
    or (ix+p3d_object_local_linear_velocity+3)
    or (ix+p3d_object_local_linear_velocity+4)
    or (ix+p3d_object_local_linear_velocity+5)
    jr z,@success
    lea iy,ix+p3d_object_local_linear_velocity
    call p3d_object_translate_local16
    jr c,@restore
@success:
    ld hl,70
    add hl,sp
    ld sp,hl
    pop ix
    pop iy
    or a
    ret
@restore:
; Reconstruct the local snapshot pointer because IY may currently address the
; delta or velocity field.
    ld iy,0
    add iy,sp
    push iy
    pop hl
    push ix
    pop de
    ld bc,p3d_object_size
    ldir
    ld hl,70
    add hl,sp
    ld sp,hl
    pop ix
    pop iy
    scf
    ret

; ---------------------------------------------------------------------------
; Persistent eZ80-side Pingo camera state and look-at solving
; ---------------------------------------------------------------------------

; Initialize one camera state.
;
; inputs:
;   ix -> destination p3d camera state
;   iy -> initial world-position vec3
;   hl = Pingo scene/control ID
; outputs:
;   copied ID/position, zero Euler pose, identity orientation, valid upright
;   look frame, and both camera dirty bits set
;   carry clear
; destroys:
;   af, bc, de, hl
; preserves:
;   ix, iy and all shadow registers
; note:
;   The position may alias the destination; every input is captured first.
p3d_camera_init16:
    push ix
    push iy
    push hl
    ld l,(iy+p3d_vec3_x)
    ld h,(iy+p3d_vec3_x+1)
    push hl
    ld l,(iy+p3d_vec3_y)
    ld h,(iy+p3d_vec3_y+1)
    push hl
    ld l,(iy+p3d_vec3_z)
    ld h,(iy+p3d_vec3_z+1)
    push hl
; Seed byte zero, then replicate it over the remaining camera state.
    xor a
    ld (ix+0),a
    push ix
    pop hl
    push ix
    pop de
    inc de
    ld bc,p3d_camera_size-1
    ldir
; Restore position Z/Y/X and scene ID.
    pop hl
    ld (ix+p3d_camera_world_position+p3d_vec3_z),l
    ld (ix+p3d_camera_world_position+p3d_vec3_z+1),h
    pop hl
    ld (ix+p3d_camera_world_position+p3d_vec3_y),l
    ld (ix+p3d_camera_world_position+p3d_vec3_y+1),h
    pop hl
    ld (ix+p3d_camera_world_position+p3d_vec3_x),l
    ld (ix+p3d_camera_world_position+p3d_vec3_x+1),h
    pop hl
    ld (ix+p3d_camera_sid),l
    ld (ix+p3d_camera_sid+1),h
    ld a,p3d_camera_dirty_all
    ld (ix+p3d_camera_dirty),a
    ld a,p3d_camera_look_valid
    ld (ix+p3d_camera_look_flags),a
; Signed-Q15 identity orientation.
    ld hl,32767
    ld (ix+p3d_camera_orientation+p3d_mat3_r0c0),l
    ld (ix+p3d_camera_orientation+p3d_mat3_r0c0+1),h
    ld (ix+p3d_camera_orientation+p3d_mat3_r1c1),l
    ld (ix+p3d_camera_orientation+p3d_mat3_r1c1+1),h
    ld (ix+p3d_camera_orientation+p3d_mat3_r2c2),l
    ld (ix+p3d_camera_orientation+p3d_mat3_r2c2+1),h
    pop iy
    pop ix
    or a
    ret

; Return the exact sign and unsigned magnitude of target-camera without ever
; forming the potentially 17-bit signed difference. XOR 0x8000 maps signed
; words into monotonically ordered unsigned words.
;
; inputs:  HL=target component, DE=camera component
; outputs: HL=unsigned magnitude 0..65535, A=1 when negative else 0
; destroys: AF, DE; preserves BC and all shadow registers
p3d_lookat_difference_magnitude16:
    ld a,h
    xor 0x80
    ld h,a
    ld a,d
    xor 0x80
    ld d,a
    or a
    sbc.s hl,de
    jr nc,@positive
    xor a
    sub l
    ld l,a
    ld a,0
    sbc a,h
    ld h,a
    ld a,1
    ret
@positive:
    xor a
    ret

; Negate one logical signed/unsigned low word.
; input/output: HL; destroys AF; preserves every other register.
p3d_lookat_negate16:
    xor a
    sub l
    ld l,a
    ld a,0
    sbc a,h
    ld h,a
    ret

; Add one half turn and return the canonical signed half-turn representative.
; Input is one canonical p3d_atan2_fine16 result in -16384..16383.
; input/output: HL; destroys AF,DE; preserves indexes/shadows.
p3d_lookat_add_half_turn16:
    ld de,16384
    add.s hl,de
    bit 6,h
    ret z
    set 7,h
    ret

; Select the exact upside-down Euler representation of the same look
; direction. Work offsets are private to p3d_camera_aim_at_point16.
;
; inputs:
;   ix -> camera state
;   iy -> look-at work frame
;   work +0 = canonical pitch, work +12 = canonical yaw
; outputs:
;   those words replaced by the equivalent inverted pitch/yaw
; destroys:
;   af, de, hl
p3d_lookat_select_inverted16:
    ld l,(iy+0)
    ld h,(iy+1)
    ld a,h
    or l
    jr nz,@nonzero_pitch
; At the ambiguous half turn, retain the sign approached by the previous
; camera pitch. Both words aim identically, but this avoids a raw-word jump.
    bit 7,(ix+p3d_camera_pingo_rotation+p3d_vec3_x+1)
    jr nz,@negative_half
    ld hl,16384
    jr @pitch_ready
@negative_half:
    ld hl,-16384
    jr @pitch_ready
@nonzero_pitch:
    bit 7,h
    jr nz,@negative_pitch
    ex de,hl
    ld hl,16384
    or a
    sbc.s hl,de
    jr @pitch_ready
@negative_pitch:
    ex de,hl
    ld hl,-16384
    or a
    sbc.s hl,de
@pitch_ready:
    ld (iy+0),l
    ld (iy+1),h
    ld l,(iy+12)
    ld h,(iy+13)
    call p3d_lookat_add_half_turn16
    ld (iy+12),l
    ld (iy+13),h
    ret

; Return the unsigned shortest distance between two library angles. Angles
; are periodic modulo 32768 raw units in the generated 256-phase model.
;
; inputs:  HL=left angle, DE=right angle
; outputs: HL=distance 0..16384
; destroys: AF,DE; preserves indexes/shadows
p3d_lookat_abs_angle_delta16:
    or a
    sbc.s hl,de
    res 7,h                 ; reduce modulo one 32768-word turn
    bit 6,h
    ret z
    ex de,hl
    ld hl,0x8000
    or a
    sbc.s hl,de
    ret

; Compare the upright and inverted exact-phase representations against the
; previously emitted Euler pair. The unsigned sum of two 0..16384 component
; distances is at most 32768. An exact tie retains the prior branch.
;
; inputs:
;   ix -> camera state
;   iy -> look-at work frame with canonical pitch at +0, yaw at +12,
;         candidate flags at +9
; outputs:
;   canonical pitch/yaw restored in the work frame
;   candidate inverted flag selected/cleared for the caller to materialize
; destroys:
;   af, bc, de, hl
p3d_lookat_select_closest16:
; Preserve the canonical pair in magnitude slots no longer needed by the
; solver at this point.
    ld a,(iy+0)
    ld (iy+18),a
    ld a,(iy+1)
    ld (iy+19),a
    ld a,(iy+12)
    ld (iy+15),a
    ld a,(iy+13)
    ld (iy+16),a
; Upright distance = |pitch-prev_x| + |yaw-prev_y|.
    ld l,(iy+0)
    ld h,(iy+1)
    ld e,(ix+p3d_camera_pingo_rotation+p3d_vec3_x)
    ld d,(ix+p3d_camera_pingo_rotation+p3d_vec3_x+1)
    call p3d_lookat_abs_angle_delta16
    push hl
    ld l,(iy+12)
    ld h,(iy+13)
    ld e,(ix+p3d_camera_pingo_rotation+p3d_vec3_y)
    ld d,(ix+p3d_camera_pingo_rotation+p3d_vec3_y+1)
    call p3d_lookat_abs_angle_delta16
    pop de
    add.s hl,de
    ld (iy+6),l
    ld (iy+7),h
; Materialize the inverted candidate and calculate its distance.
    call p3d_lookat_select_inverted16
    ld l,(iy+0)
    ld h,(iy+1)
    ld e,(ix+p3d_camera_pingo_rotation+p3d_vec3_x)
    ld d,(ix+p3d_camera_pingo_rotation+p3d_vec3_x+1)
    call p3d_lookat_abs_angle_delta16
    push hl
    ld l,(iy+12)
    ld h,(iy+13)
    ld e,(ix+p3d_camera_pingo_rotation+p3d_vec3_y)
    ld d,(ix+p3d_camera_pingo_rotation+p3d_vec3_y+1)
    call p3d_lookat_abs_angle_delta16
    pop de
    add.s hl,de
; Compare the unsigned low word; both sums are at most 0x8000.
    ld e,(iy+6)
    ld d,(iy+7)
    or a
    sbc.s hl,de
    jr c,@choose_inverted
    jr nz,@choose_upright
; Equal path lengths retain the previous branch.
    bit 2,(ix+p3d_camera_look_flags)
    jr nz,@choose_inverted
@choose_upright:
    ld a,(iy+9)
    res 2,a
    ld (iy+9),a
    jr @restore_canonical
@choose_inverted:
    ld a,(iy+9)
    set 2,a
    ld (iy+9),a
@restore_canonical:
    ld a,(iy+18)
    ld (iy+0),a
    ld a,(iy+19)
    ld (iy+1),a
    ld a,(iy+15)
    ld (iy+12),a
    ld a,(iy+16)
    ld (iy+13),a
    ret

; Aim a Pingo camera at one world-space point.
;
; inputs:
;   ix -> p3d camera state
;   iy -> target world-position vec3
;   a  = required roll policy:
;          p3d_camera_roll_upright
;          p3d_camera_roll_continuous
; outputs:
;   absolute Pingo Euler words and matching local-to-world matrix updated
;   rotation dirty set iff the emitted Euler bytes changed
;   carry clear on success
;   carry set for an invalid policy or coincident camera/target, with the
;   complete camera state unchanged
; destroys:
;   af, af', bc, de, hl, bc', de', hl'
; preserves:
;   ix, iy and the target vec3
;
; The solver first retains roughly eleven direction bits by scaling all three
; exact sign/magnitude differences into a common 1024..2047 maximum. Thus
; x^2+z^2 is below 2^23. The pole cone is scale-independent: enter when
; horizontal <= |dy|/32 and leave only when horizontal > |dy|/16.
;
; Upright mode emits pitch=atan2(dy,horizontal), yaw=atan2(-dx,-dz), roll=0.
; Continuous mode retains the equivalent inverted Euler branch after a pole
; crossing, allowing pitch to pass through +/-90 degrees without a 180-degree
; frame twist. Inside the hysteresis band the last reliable canonical yaw is
; retained and pitch is the exact vertical cardinal.
p3d_camera_look_at_point16:
p3d_camera_aim_at_point16:
    cp p3d_camera_roll_policy_count
    jr c,@policy_valid
    scf
    ret
@policy_valid:
    ld c,a                  ; p3d difference helper preserves BC
    push iy
    ld b,0                  ; component sign bits X/Y/Z
; Exact X magnitude/sign.
    ld l,(iy+p3d_vec3_x)
    ld h,(iy+p3d_vec3_x+1)
    ld e,(ix+p3d_camera_world_position+p3d_vec3_x)
    ld d,(ix+p3d_camera_world_position+p3d_vec3_x+1)
    call p3d_lookat_difference_magnitude16
    or a
    jr z,@x_sign_ready
    set 0,b
@x_sign_ready:
    inc hl
    dec.s hl
    push hl
; Exact Y magnitude/sign.
    ld l,(iy+p3d_vec3_y)
    ld h,(iy+p3d_vec3_y+1)
    ld e,(ix+p3d_camera_world_position+p3d_vec3_y)
    ld d,(ix+p3d_camera_world_position+p3d_vec3_y+1)
    call p3d_lookat_difference_magnitude16
    or a
    jr z,@y_sign_ready
    set 1,b
@y_sign_ready:
    inc hl
    dec.s hl
    push hl
; Exact Z magnitude/sign.
    ld l,(iy+p3d_vec3_z)
    ld h,(iy+p3d_vec3_z+1)
    ld e,(ix+p3d_camera_world_position+p3d_vec3_z)
    ld d,(ix+p3d_camera_world_position+p3d_vec3_z+1)
    call p3d_lookat_difference_magnitude16
    or a
    jr z,@z_sign_ready
    set 2,b
@z_sign_ready:
    inc hl
    dec.s hl
    push hl
; Complete the seven-word private work frame. Final offsets from SP are:
; +0 pitch/control, +3 policy, +6 horizontal/pole yaw, +9 signs/flags,
; +12 Z magnitude/yaw, +15 Y magnitude, +18 X magnitude.
    ld h,0
    ld l,b
    push hl
    ld hl,0
    push hl
    ld h,0
    ld l,c
    push hl
    ld hl,0
    push hl
    ld iy,0
    add iy,sp

; Find the maximum unsigned magnitude.
    ld c,(iy+18)
    ld b,(iy+19)
    ld l,(iy+15)
    ld h,(iy+16)
    or a
    sbc.s hl,bc
    jr c,@max_y_done
    jr z,@max_y_done
    ld c,(iy+15)
    ld b,(iy+16)
@max_y_done:
    ld l,(iy+12)
    ld h,(iy+13)
    or a
    sbc.s hl,bc
    jr c,@max_ready
    jr z,@max_ready
    ld c,(iy+12)
    ld b,(iy+13)
@max_ready:
    ld a,b
    or c
    jr nz,@yaw_normalize
; Coincident input: discard seven work words and restore the caller's IY.
    ld hl,21
    add hl,sp
    ld sp,hl
    pop iy
    scf
    ret

; Preserve yaw precision independently of a dominant vertical component.
; Exact X/Z differences need at most one common right shift to enter the
; signed atan2 input range.
@yaw_normalize:
    push bc                 ; fine atan destroys the retained XYZ maximum
    ld l,(iy+18)
    ld h,(iy+19)
    ld e,(iy+12)
    ld d,(iy+13)
@yaw_shift_test:
    bit 7,h
    jr nz,@yaw_shift
    bit 7,d
    jr z,@yaw_sign
@yaw_shift:
    srl h
    rr l
    srl d
    rr e
    jr @yaw_shift_test
@yaw_sign:
; yaw = atan2(-dx,-dz).
    bit 0,(iy+9)
    call z,p3d_lookat_negate16
    ex de,hl
    bit 2,(iy+9)
    call z,p3d_lookat_negate16
    ex de,hl
    call p3d_atan2_fine16
    pop bc
    push hl                 ; park exact-pair yaw below the fixed work frame

; Common right shifts guarantee x^2+z^2 < 2^23.
@normalize_down:
    ld a,b
    cp 8
    jr c,@normalize_up
    srl b
    rr c
    srl (iy+19)
    rr (iy+18)
    srl (iy+16)
    rr (iy+15)
    srl (iy+13)
    rr (iy+12)
    jr @normalize_down
; Common left shifts retain useful precision for close targets.
@normalize_up:
    ld a,b
    cp 4
    jr nc,@normalized
    sla c
    rl b
    sla (iy+18)
    rl (iy+19)
    sla (iy+15)
    rl (iy+16)
    sla (iy+12)
    rl (iy+13)
    jr @normalize_up

@normalized:
; Calculate x^2+z^2 at full 32-bit width in opposite GP banks.
    ld l,(iy+18)
    ld h,(iy+19)
    ld e,l
    ld d,h
    call p3d_umul16x16_32
    exx
    ld l,(iy+12)
    ld h,(iy+13)
    ld e,l
    ld d,h
    call p3d_umul16x16_32
    call p3d_sadd32
; The bounded sum is the real 24-bit byte sequence L:D:E. Stage it in the
; work frame because the square-root core consumes an actual ADL HL value.
    ld (iy+6),e
    ld (iy+7),d
    ld (iy+8),l
    ld hl,(iy+6)
    call p3d_lookat_isqrt24
; Round the horizontal magnitude to nearest: remainder > floor(root) means
; the next integer root is closer.
    or a
    sbc hl,de
    jr c,@root_ready
    jr z,@root_ready
    inc.s de
@root_ready:
    ld (iy+6),e
    ld (iy+7),d

; Canonical pitch = atan2(dy,horizontal).
    ld l,(iy+15)
    ld h,(iy+16)
    bit 1,(iy+9)
    call nz,p3d_lookat_negate16
    ld e,(iy+6)
    ld d,(iy+7)
    call p3d_atan2_fine16
    ld (iy+0),l
    ld (iy+1),h

; Recover the separately normalized canonical yaw.
    pop hl
    ld (iy+12),l
    ld (iy+13),h

; Select the pole threshold according to the prior hysteresis state.
    ld a,(ix+p3d_camera_look_flags)
    bit 0,a
    jr z,@test_pole_entry
    bit 1,a
    jr nz,@test_pole_exit
@test_pole_entry:
; Enter cone: horizontal <= |dy|/32.
    ld e,(iy+15)
    ld d,(iy+16)
    srl d
    rr e
    srl d
    rr e
    srl d
    rr e
    srl d
    rr e
    srl d
    rr e
    ld l,(iy+6)
    ld h,(iy+7)
    or a
    sbc.s hl,de
    jr c,@enter_pole
    jr z,@enter_pole
    jp @outside_pole

@test_pole_exit:
; Retain cone: horizontal <= |dy|/16.
    ld e,(iy+15)
    ld d,(iy+16)
    srl d
    rr e
    srl d
    rr e
    srl d
    rr e
    srl d
    rr e
    ld l,(iy+6)
    ld h,(iy+7)
    or a
    sbc.s hl,de
    jr c,@remain_in_pole
    jr z,@remain_in_pole
    jp @leave_pole

@enter_pole:
; The exact vertical cardinal removes in-cone pitch jitter.
    ld hl,8192
    bit 1,(iy+9)
    jr z,@entry_pitch_ready
    ld hl,-8192
@entry_pitch_ready:
    ld (iy+0),l
    ld (iy+1),h
; Store the previous reliable *canonical* yaw. An inverted state carries an
; Euler yaw a half turn away from that canonical horizontal frame.
    ld a,(ix+p3d_camera_look_flags)
    bit 0,a
    jr z,@entry_use_computed_yaw
    ld l,(ix+p3d_camera_pingo_rotation+p3d_vec3_y)
    ld h,(ix+p3d_camera_pingo_rotation+p3d_vec3_y+1)
    bit 2,a
    call nz,p3d_lookat_add_half_turn16
    jr @entry_yaw_ready
@entry_use_computed_yaw:
    ld l,(iy+12)
    ld h,(iy+13)
@entry_yaw_ready:
    ld (iy+6),l
    ld (iy+7),h
    ld a,1
    ld (iy+10),a           ; commit the new pole yaw
    ld a,(ix+p3d_camera_look_flags)
    bit 0,a
    jr nz,@entry_frame_valid
    res 2,a
@entry_frame_valid:
    set 0,a
    set 1,a
    ld l,(iy+3)
    ld h,0
    ld de,p3d_camera_roll_upright
    or a
    sbc.s hl,de
    jr nz,@entry_policy_ready
    res 2,a
@entry_policy_ready:
    ld (iy+9),a            ; original signs are no longer needed
    ld l,(iy+6)
    ld h,(iy+7)
    bit 2,a
    call nz,p3d_lookat_add_half_turn16
    ld (iy+12),l
    ld (iy+13),h
    jp @selection_ready

@remain_in_pole:
    ld hl,8192
    bit 1,(iy+9)
    jr z,@held_pitch_ready
    ld hl,-8192
@held_pitch_ready:
    ld (iy+0),l
    ld (iy+1),h
    xor a
    ld (iy+10),a
    ld l,(ix+p3d_camera_pole_yaw)
    ld h,(ix+p3d_camera_pole_yaw+1)
    ld a,(ix+p3d_camera_look_flags)
    bit 0,a
    jr nz,@held_frame_valid
    res 2,a
@held_frame_valid:
    set 0,a
    set 1,a
    ld e,(iy+3)
    ld d,0
    push hl
    ld hl,p3d_camera_roll_upright
    or a
    sbc.s hl,de
    pop hl
    jr nz,@held_policy_ready
    res 2,a
@held_policy_ready:
    ld (iy+9),a
    bit 2,a
    call nz,p3d_lookat_add_half_turn16
    ld (iy+12),l
    ld (iy+13),h
    jp @selection_ready

@leave_pole:
    xor a
    ld (iy+10),a
    ld a,(ix+p3d_camera_look_flags)
    set 0,a
    res 1,a
    ld (iy+9),a
    ld a,(iy+3)
    or a
    jr nz,@continuous_exit
    ld a,(iy+9)
    res 2,a
    jr @exit_flags_ready
@continuous_exit:
; A negative cosine means the canonical azimuth crossed to the opposite side
; of the retained pole frame, so continuous mode changes Euler branch.
    ld a,(iy+9)
    push af
    ld l,(iy+12)
    ld h,(iy+13)
    ld e,(ix+p3d_camera_pole_yaw)
    ld d,(ix+p3d_camera_pole_yaw+1)
    or a
    sbc.s hl,de
    call p3d_sincos_fine16
    pop af
    bit 7,d
    jr z,@exit_flags_ready
    xor p3d_camera_look_inverted
@exit_flags_ready:
    ld (iy+9),a
    bit 2,a
    call nz,p3d_lookat_select_inverted16
    jp @selection_ready

@outside_pole:
    xor a
    ld (iy+10),a
    ld a,(ix+p3d_camera_look_flags)
    set 0,a
    res 1,a
    ld (iy+9),a
    ld a,(iy+3)
    or a
    jr nz,@outside_continuous
    ld a,(iy+9)
    res 2,a
    ld (iy+9),a
    jr @outside_policy_ready
@outside_continuous:
; Choose the representation with the smaller total wrapped pitch/yaw change.
; This handles a pole cone skipped by an arbitrarily coarse simulation step.
    bit 0,(ix+p3d_camera_look_flags)
    jr z,@outside_policy_ready
    call p3d_lookat_select_closest16
@outside_policy_ready:
    ld a,(iy+9)
; A state without a prior valid frame starts on the canonical branch.
    bit 0,(ix+p3d_camera_look_flags)
    jr nz,@outside_flags_ready
    res 2,a
@outside_flags_ready:
    ld (iy+9),a
    bit 2,a
    call nz,p3d_lookat_select_inverted16

@selection_ready:
; Determine byte-exact Pingo rotation dirtiness before changing the state.
    ld a,(iy+0)
    cp (ix+p3d_camera_pingo_rotation+p3d_vec3_x)
    jr nz,@rotation_changed
    ld a,(iy+1)
    cp (ix+p3d_camera_pingo_rotation+p3d_vec3_x+1)
    jr nz,@rotation_changed
    ld a,(iy+12)
    cp (ix+p3d_camera_pingo_rotation+p3d_vec3_y)
    jr nz,@rotation_changed
    ld a,(iy+13)
    cp (ix+p3d_camera_pingo_rotation+p3d_vec3_y+1)
    jr nz,@rotation_changed
    ld a,(ix+p3d_camera_pingo_rotation+p3d_vec3_z)
    or (ix+p3d_camera_pingo_rotation+p3d_vec3_z+1)
    jr nz,@rotation_changed
    xor a
    jr @changed_ready
@rotation_changed:
    ld a,1
@changed_ready:
    ld (iy+11),a

; Snapshot all 36 bytes so Euler, matrix, flags, pole memory, and dirty bits
; remain transactional if matrix construction ever reports a failure.
    ld hl,-p3d_camera_size
    add hl,sp
    ld sp,hl
    ld hl,0
    add hl,sp
    push hl
    pop de
    push ix
    pop hl
    ld bc,p3d_camera_size
    ldir

; Commit the selected semantic state, then build its matching matrix.
    ld a,(iy+9)
    ld (ix+p3d_camera_look_flags),a
    ld a,(iy+10)
    or a
    jr z,@pole_yaw_committed
    ld a,(iy+6)
    ld (ix+p3d_camera_pole_yaw),a
    ld a,(iy+7)
    ld (ix+p3d_camera_pole_yaw+1),a
@pole_yaw_committed:
    ld a,(iy+0)
    ld (ix+p3d_camera_pingo_rotation+p3d_vec3_x),a
    ld a,(iy+1)
    ld (ix+p3d_camera_pingo_rotation+p3d_vec3_x+1),a
    ld a,(iy+12)
    ld (ix+p3d_camera_pingo_rotation+p3d_vec3_y),a
    ld a,(iy+13)
    ld (ix+p3d_camera_pingo_rotation+p3d_vec3_y+1),a
    xor a
    ld (ix+p3d_camera_pingo_rotation+p3d_vec3_z),a
    ld (ix+p3d_camera_pingo_rotation+p3d_vec3_z+1),a
    push iy
    lea iy,ix+p3d_camera_pingo_rotation
    lea ix,ix+p3d_camera_orientation
    call p3d_camera_mat3_from_euler_fine16
    lea ix,ix-p3d_camera_orientation
    pop iy
    jr c,@restore_camera
    ld a,(iy+11)
    or a
    jr z,@camera_success
    ld a,(ix+p3d_camera_dirty)
    or p3d_camera_dirty_rotation
    ld (ix+p3d_camera_dirty),a
@camera_success:
; Discard snapshot plus seven work words, then restore the caller's IY.
    ld hl,p3d_camera_size+21
    add hl,sp
    ld sp,hl
    pop iy
    or a
    ret

@restore_camera:
    ld hl,0
    add hl,sp
    push ix
    pop de
    ld bc,p3d_camera_size
    ldir
    ld hl,p3d_camera_size+21
    add hl,sp
    ld sp,hl
    pop iy
    scf
    ret

; Aim a camera at the retained world position of one p3d object.
;
; inputs:
;   ix -> p3d camera state
;   iy -> p3d object state
;   a  = required roll policy, as for p3d_camera_aim_at_point16
; outputs/destroys:
;   as for p3d_camera_aim_at_point16
; preserves:
;   ix, iy and the complete object state
p3d_camera_look_at_object16:
p3d_camera_aim_at_object16:
    push iy
    lea iy,iy+p3d_object_world_position
    call p3d_camera_aim_at_point16
    pop iy
    ret

; ---------------------------------------------------------------------------
; Pingo command construction and dirty-state synchronization
; ---------------------------------------------------------------------------

; Write the common prefix for a 15-byte absolute object update.
; input: A=subcommand, IX=state, IY=packet. Preserves IX/IY.
p3d_object_build_update_prefix16:
    ld (iy+6),a
    ld a,23
    ld (iy+0),a
    xor a
    ld (iy+1),a
    ld a,0xa0
    ld (iy+2),a
    ld a,(ix+p3d_object_sid)
    ld (iy+3),a
    ld a,(ix+p3d_object_sid+1)
    ld (iy+4),a
    ld a,p3d_pingo_command
    ld (iy+5),a
    ld a,(ix+p3d_object_oid)
    ld (iy+7),a
    ld a,(ix+p3d_object_oid+1)
    ld (iy+8),a
    ret

; Build the Pingo create-object packet from the IDs retained in the state.
;
; inputs:
;   ix -> object state
;   iy -> at least 13 writable bytes
; outputs:
;   packet at IY
;   HL=IY, BC=13, A=create dirty bit, carry clear
; destroys:
;   af, bc, hl
; preserves:
;   ix, iy, de and all shadow registers
p3d_object_build_create16:
    ld a,p3d_pingo_create_object
    call p3d_object_build_update_prefix16
    ld a,(ix+p3d_object_mid)
    ld (iy+9),a
    ld a,(ix+p3d_object_mid+1)
    ld (iy+10),a
    ld a,(ix+p3d_object_bmid)
    ld (iy+11),a
    ld a,(ix+p3d_object_bmid+1)
    ld (iy+12),a
    push iy
    pop hl
    ld bc,p3d_pingo_create_packet_size
    ld a,p3d_object_dirty_create
    or a
    ret

; Build the next pending Pingo command without clearing its dirty bit.
; Priority is create, scale, rotation, then translation, so a newly initialized
; object is established before its absolute state is applied.
;
; inputs:
;   ix -> object state
;   iy -> at least 15 writable bytes
; outputs:
;   A=dirty bit represented by the packet, BC=packet length, HL=IY
;   Z set, A=0, BC=0 when no known dirty bit remains
;   carry clear
; destroys:
;   af, bc, hl
; preserves:
;   ix, iy, de and all shadow registers
p3d_object_build_next_dirty16:
    ld a,(ix+p3d_object_dirty)
    bit 3,a
    jp nz,p3d_object_build_create16
    bit 2,a
    jr nz,@scale
    bit 1,a
    jr nz,@rotation
    bit 0,a
    jr nz,@translation
    push iy
    pop hl
    ld bc,0
    xor a
    ret
@scale:
    ld a,p3d_pingo_set_object_xyz_scale
    call p3d_object_build_update_prefix16
    ld a,(ix+p3d_object_scale+0)
    ld (iy+9),a
    ld a,(ix+p3d_object_scale+1)
    ld (iy+10),a
    ld a,(ix+p3d_object_scale+2)
    ld (iy+11),a
    ld a,(ix+p3d_object_scale+3)
    ld (iy+12),a
    ld a,(ix+p3d_object_scale+4)
    ld (iy+13),a
    ld a,(ix+p3d_object_scale+5)
    ld (iy+14),a
    ld a,p3d_object_dirty_scale
    jr @update_ready
@rotation:
    ld a,p3d_pingo_set_object_xyz_rotation
    call p3d_object_build_update_prefix16
    ld a,(ix+p3d_object_pingo_rotation+0)
    ld (iy+9),a
    ld a,(ix+p3d_object_pingo_rotation+1)
    ld (iy+10),a
    ld a,(ix+p3d_object_pingo_rotation+2)
    ld (iy+11),a
    ld a,(ix+p3d_object_pingo_rotation+3)
    ld (iy+12),a
    ld a,(ix+p3d_object_pingo_rotation+4)
    ld (iy+13),a
    ld a,(ix+p3d_object_pingo_rotation+5)
    ld (iy+14),a
    ld a,p3d_object_dirty_rotation
    jr @update_ready
@translation:
    ld a,p3d_pingo_set_object_xyz_translation
    call p3d_object_build_update_prefix16
    ld a,(ix+p3d_object_world_position+0)
    ld (iy+9),a
    ld a,(ix+p3d_object_world_position+1)
    ld (iy+10),a
    ld a,(ix+p3d_object_world_position+2)
    ld (iy+11),a
    ld a,(ix+p3d_object_world_position+3)
    ld (iy+12),a
    ld a,(ix+p3d_object_world_position+4)
    ld (iy+13),a
    ld a,(ix+p3d_object_world_position+5)
    ld (iy+14),a
    ld a,p3d_object_dirty_position
@update_ready:
    push iy
    pop hl
    ld bc,p3d_pingo_update_packet_size
    or a
    ret

; Send every known dirty object command through the ordinary VDU byte-stream
; entry point. Each bit is cleared after its RST.LIL $18 call returns. The VDU
; stream has no delivery-status result, so transport failure cannot be reported
; by this routine.
;
; inputs:
;   ix -> object state
;   iy -> reusable 15-byte packet scratch
; outputs:
;   known dirty bits cleared, carry clear
; destroys:
;   af, bc, de, hl and any registers destroyed by RST.LIL $18
; preserves:
;   ix, iy
p3d_object_sync16:
@next:
    call p3d_object_build_next_dirty16
    or a
    ret z
    push ix
    push iy
    push af
    rst.lil 18h
    pop af
    pop iy
    pop ix
    cpl
    and (ix+p3d_object_dirty)
    ld (ix+p3d_object_dirty),a
    jr @next
