; Exact AGNB 0.3/P3DM one-component loader and experimental publication API.
;
; Contract:
;   p3dm_load_component
;       opens the path in p3dm_filename_pointer, reads it completely, closes
;       it, validates the exact fixed container and caller-selected policy,
;       CRC32 and indices,
;       uploads only DATA to p3dm_stage_buffer_id, consolidates, and sends
;       Pingo subcommand 50 to the already-established p3dm_target_mesh_id.
;   pingo_set_object_active
;       sends Pingo subcommand 51 for an already-established object.
;
; The 16 KiB whole-file window admits all current Bay Area proof components,
; including KSFO M00 (14,120 bytes). It keeps parsing fail-closed and wholly
; pre-publication while the regional coordinator reuses the request block.

    MACRO P3DM_LD_U16_BC ADDRESS
    ld bc,0
    ld a,(ADDRESS)
    ld c,a
    ld a,(ADDRESS+1)
    ld b,a
    ENDMACRO

    MACRO P3DM_LD_U16_DE ADDRESS
    ld de,0
    ld a,(ADDRESS)
    ld e,a
    ld a,(ADDRESS+1)
    ld d,a
    ENDMACRO

    MACRO P3DM_LD_U16_HL ADDRESS
    ld hl,0
    ld a,(ADDRESS)
    ld l,a
    ld a,(ADDRESS+1)
    ld h,a
    ENDMACRO

    MACRO P3DM_ST_U16_HL ADDRESS
    ld a,l
    ld (ADDRESS),a
    ld a,h
    ld (ADDRESS+1),a
    ENDMACRO

; Direct FatFS dependencies retained from the proven AGNB API.
ffs_fopen: equ 080h
ffs_fclose: equ 081h
ffs_fread: equ 082h
fa_read: equ 01h
ffobjid_objsize: equ 11
fil_obj: equ 0
fil_dir_ptr: equ 33
p3dm_fil_size: equ fil_dir_ptr+3
    MACRO FFSCALL function
        push iy
        ld a,function
        rst.lil 08h
        pop iy
    ENDMACRO

; Fixed wire offsets. AGNB 0.3's exact chunk sizes place DATA at byte 100.
p3dm_riff_size_offset: equ 4
p3dm_vers_size_offset: equ 16
p3dm_list_size_offset: equ 28
p3dm_bhdr_size_offset: equ 40
p3dm_stage_id_offset: equ 44
p3dm_descriptor_size_offset: equ 52
p3dm_descriptor_offset: equ 56
p3dm_data_chunk_offset: equ 92
p3dm_data_size_offset: equ 96
p3dm_data_offset: equ 100

p3dm_desc_layout: equ p3dm_descriptor_offset+0
p3dm_desc_layer: equ p3dm_descriptor_offset+1
p3dm_desc_lod: equ p3dm_descriptor_offset+2
p3dm_desc_shading: equ p3dm_descriptor_offset+3
p3dm_desc_illumination: equ p3dm_descriptor_offset+4
p3dm_desc_material_set: equ p3dm_descriptor_offset+5
p3dm_desc_tile_x: equ p3dm_descriptor_offset+6
p3dm_desc_tile_y: equ p3dm_descriptor_offset+8
p3dm_desc_center_east: equ p3dm_descriptor_offset+10
p3dm_desc_center_north: equ p3dm_descriptor_offset+14
p3dm_desc_minimum_elevation: equ p3dm_descriptor_offset+18
p3dm_desc_maximum_elevation: equ p3dm_descriptor_offset+20
p3dm_desc_half_extent: equ p3dm_descriptor_offset+22
p3dm_desc_vertices: equ p3dm_descriptor_offset+24
p3dm_desc_position_indices: equ p3dm_descriptor_offset+26
p3dm_desc_uvs: equ p3dm_descriptor_offset+28
p3dm_desc_uv_indices: equ p3dm_descriptor_offset+30
p3dm_desc_crc32: equ p3dm_descriptor_offset+32

p3dm_max_file_bytes: equ 16384
p3dm_max_data_bytes: equ p3dm_max_file_bytes-p3dm_data_offset

p3dm_error_ok: equ 0
p3dm_error_open: equ 1
p3dm_error_read: equ 2
p3dm_error_close: equ 3
p3dm_error_file_size: equ 4
p3dm_error_structure: equ 5
p3dm_error_policy: equ 6
p3dm_error_counts: equ 7
p3dm_error_bounds: equ 8
p3dm_error_crc32: equ 9
p3dm_error_indices: equ 10
p3dm_error_eof: equ 11

p3dm_state_idle: equ 0
p3dm_state_reading: equ 1
p3dm_state_closed: equ 2
p3dm_state_validated: equ 3
p3dm_state_staged: equ 4
p3dm_state_published: equ 5

; Top-level fail-closed operation. Transform and command 51 activation stay
; with the caller so paired components can later activate as one world unit.
p3dm_load_component:
    xor a
    ld (p3dm_last_error),a
    ld (p3dm_loader_state),a
    call p3dm_read_container
    ret nz
    call p3dm_validate_container
    ret nz
    ld a,p3dm_state_validated
    ld (p3dm_loader_state),a
    call p3dm_upload_data
    ret nz
    ld a,p3dm_state_staged
    ld (p3dm_loader_state),a
    call pingo_replace_mesh_from_buffer
    ld a,p3dm_state_published
    ld (p3dm_loader_state),a
    xor a
    ld (p3dm_last_error),a
    ret

; Open/read/close exactly one path. Validation never observes an open FIL.
p3dm_read_container:
    ld de,(p3dm_filename_pointer) ; ADL24 OK: native 24-bit path pointer
    ld hl,p3dm_fil
    ld c,fa_read
    FFSCALL ffs_fopen
    or a
    jr nz,p3dm_bad_open
    ld a,p3dm_state_reading
    ld (p3dm_loader_state),a

    call p3dm_read_open_file
    ld (p3dm_pending_error),a
    ld hl,p3dm_fil
    FFSCALL ffs_fclose
    ld (p3dm_close_result),a
    ld a,(p3dm_pending_error)
    or a
    ret nz
    ld a,(p3dm_close_result)
    or a
    jr nz,p3dm_bad_close
    ld a,p3dm_state_closed
    ld (p3dm_loader_state),a
    xor a
    ret

p3dm_bad_open:
    ld a,p3dm_error_open
    jp p3dm_return_error
p3dm_bad_close:
    ld a,p3dm_error_close
    jp p3dm_return_error

; Validate the FatFS u32 size before reducing it to this probe's exact u16.
p3dm_read_open_file:
    ld a,(p3dm_fil+fil_obj+ffobjid_objsize+2)
    or a
    jr nz,p3dm_bad_file_size
    ld a,(p3dm_fil+fil_obj+ffobjid_objsize+3)
    or a
    jr nz,p3dm_bad_file_size
    ld a,(p3dm_fil+fil_obj+ffobjid_objsize)
    ld (p3dm_file_size),a
    ld a,(p3dm_fil+fil_obj+ffobjid_objsize+1)
    ld (p3dm_file_size+1),a
    P3DM_LD_U16_HL p3dm_file_size
    ld de,p3dm_data_offset
    or a
    sbc hl,de
    jr c,p3dm_bad_file_size
    P3DM_LD_U16_HL p3dm_file_size
    ld de,p3dm_max_file_bytes+1
    or a
    sbc hl,de
    jr nc,p3dm_bad_file_size

    P3DM_LD_U16_BC p3dm_file_size
    ld de,p3dm_file_buffer
    call p3dm_read_exact
    ret

p3dm_bad_file_size:
    ld a,p3dm_error_file_size
    jp p3dm_return_error

; Read exactly BC bytes, tolerating legal short reads and rejecting zero-byte
; progress. The three-byte fields are intentionally native ADL quantities.
p3dm_read_exact:
    ld (p3dm_read_remaining),bc ; ADL24 OK: native u24 FatFS byte count
    ld (p3dm_read_pointer),de   ; ADL24 OK: native 24-bit RAM pointer
@next:
    ld hl,(p3dm_read_remaining) ; ADL24 OK: native u24 FatFS byte count
    ld de,0
    or a
    sbc hl,de
    jr z,@success
    push hl
    pop bc
    ld de,(p3dm_read_pointer)   ; ADL24 OK: native 24-bit RAM pointer
    ld hl,p3dm_fil
    FFSCALL ffs_fread
    or a
    jr nz,@read_error
    ld hl,0
    or a
    sbc hl,bc
    jr z,@eof
    ld hl,(p3dm_read_remaining) ; ADL24 OK: native u24 FatFS byte count
    or a
    sbc hl,bc
    jr c,@read_error
    ld (p3dm_read_remaining),hl ; ADL24 OK: native u24 FatFS byte count
    ld hl,(p3dm_read_pointer)   ; ADL24 OK: native 24-bit RAM pointer
    add hl,bc
    ld (p3dm_read_pointer),hl   ; ADL24 OK: native 24-bit RAM pointer
    jr @next
@read_error:
    ld a,p3dm_error_read
    jp p3dm_return_error
@eof:
    ld a,p3dm_error_eof
    jp p3dm_return_error
@success:
    xor a
    ret

; Compare four bytes at HL against the table at DE.
p3dm_compare_fourcc:
    push bc
    push de
    push hl
    ld b,4
@loop:
    ld a,(de)
    cp (hl)
    jr nz,@done
    inc de
    inc hl
    djnz @loop
@done:
    pop hl
    pop de
    pop bc
    ret

; Exact fixed-offset parser. Every u32 chunk size is checked in all four
; bytes; the upper word must be zero because the physical file is <=16384.
p3dm_validate_container:
    ld hl,p3dm_file_buffer+0
    ld de,p3dm_id_riff
    call p3dm_compare_fourcc
    jp nz,p3dm_bad_structure
    ld hl,p3dm_file_buffer+8
    ld de,p3dm_id_agnb
    call p3dm_compare_fourcc
    jp nz,p3dm_bad_structure

    ld a,(p3dm_file_buffer+p3dm_riff_size_offset+2)
    ld hl,p3dm_file_buffer+p3dm_riff_size_offset+3
    or (hl)
    jp nz,p3dm_bad_bounds
    P3DM_LD_U16_HL p3dm_file_size
    ld de,8
    or a
    sbc hl,de
    P3DM_LD_U16_DE p3dm_file_buffer+p3dm_riff_size_offset
    or a
    sbc hl,de
    jp nz,p3dm_bad_bounds

    ld hl,p3dm_file_buffer+12
    ld de,p3dm_id_vers
    call p3dm_compare_fourcc
    jp nz,p3dm_bad_structure
    P3DM_LD_U16_HL p3dm_file_buffer+p3dm_vers_size_offset
    ld de,2
    or a
    sbc hl,de
    jp nz,p3dm_bad_structure
    ld a,(p3dm_file_buffer+p3dm_vers_size_offset+2)
    ld hl,p3dm_file_buffer+p3dm_vers_size_offset+3
    or (hl)
    jp nz,p3dm_bad_structure
    ld a,(p3dm_file_buffer+20)
    or a
    jp nz,p3dm_bad_structure
    ld a,(p3dm_file_buffer+21)
    cp 3
    jp nz,p3dm_bad_structure
    ld a,(p3dm_file_buffer+22)
    ld hl,p3dm_file_buffer+23
    or (hl)
    jp nz,p3dm_bad_structure

    ld hl,p3dm_file_buffer+24
    ld de,p3dm_id_list
    call p3dm_compare_fourcc
    jp nz,p3dm_bad_structure
    ld a,(p3dm_file_buffer+p3dm_list_size_offset+2)
    ld hl,p3dm_file_buffer+p3dm_list_size_offset+3
    or (hl)
    jp nz,p3dm_bad_bounds
    P3DM_LD_U16_HL p3dm_file_size
    ld de,32
    or a
    sbc hl,de
    P3DM_LD_U16_DE p3dm_file_buffer+p3dm_list_size_offset
    or a
    sbc hl,de
    jp nz,p3dm_bad_bounds
    ld hl,p3dm_file_buffer+32
    ld de,p3dm_id_bufr
    call p3dm_compare_fourcc
    jp nz,p3dm_bad_structure

    ld hl,p3dm_file_buffer+36
    ld de,p3dm_id_bhdr
    call p3dm_compare_fourcc
    jp nz,p3dm_bad_structure
    P3DM_LD_U16_HL p3dm_file_buffer+p3dm_bhdr_size_offset
    ld de,2
    or a
    sbc hl,de
    jp nz,p3dm_bad_structure
    ld a,(p3dm_file_buffer+p3dm_bhdr_size_offset+2)
    ld hl,p3dm_file_buffer+p3dm_bhdr_size_offset+3
    or (hl)
    jp nz,p3dm_bad_structure
    P3DM_LD_U16_HL p3dm_file_buffer+p3dm_stage_id_offset
    ld de,p3dm_stage_buffer_id
    or a
    sbc hl,de
    jp nz,p3dm_bad_policy
    ld a,(p3dm_file_buffer+46)
    ld hl,p3dm_file_buffer+47
    or (hl)
    jp nz,p3dm_bad_structure

    ld hl,p3dm_file_buffer+48
    ld de,p3dm_id_p3dm
    call p3dm_compare_fourcc
    jp nz,p3dm_bad_structure
    P3DM_LD_U16_HL p3dm_file_buffer+p3dm_descriptor_size_offset
    ld de,36
    or a
    sbc hl,de
    jp nz,p3dm_bad_structure
    ld a,(p3dm_file_buffer+p3dm_descriptor_size_offset+2)
    ld hl,p3dm_file_buffer+p3dm_descriptor_size_offset+3
    or (hl)
    jp nz,p3dm_bad_structure

; Layout 1 is the only wire layout understood here. All render/identity policy
; after it is selected by the caller, so this same loader can publish terrain,
; airport pavement, or airport markings into distinct stable slots.
    ld a,(p3dm_file_buffer+p3dm_desc_layout)
    cp 1
    jp nz,p3dm_bad_policy
    ld a,(p3dm_expected_layer)
    ld b,a
    ld a,(p3dm_file_buffer+p3dm_desc_layer)
    cp b
    jp nz,p3dm_bad_policy
    ld a,(p3dm_expected_lod)
    ld b,a
    ld a,(p3dm_file_buffer+p3dm_desc_lod)
    cp b
    jp nz,p3dm_bad_policy
    ld a,(p3dm_expected_shading)
    ld b,a
    ld a,(p3dm_file_buffer+p3dm_desc_shading)
    cp b
    jp nz,p3dm_bad_policy
    ld a,(p3dm_expected_illumination)
    ld b,a
    ld a,(p3dm_file_buffer+p3dm_desc_illumination)
    cp b
    jp nz,p3dm_bad_policy
    ld a,(p3dm_expected_material_set)
    ld b,a
    ld a,(p3dm_file_buffer+p3dm_desc_material_set)
    cp b
    jp nz,p3dm_bad_policy
    P3DM_LD_U16_HL p3dm_file_buffer+p3dm_desc_tile_x
    P3DM_LD_U16_DE p3dm_expected_tile_x
    or a
    sbc hl,de
    jp nz,p3dm_bad_policy
    P3DM_LD_U16_HL p3dm_file_buffer+p3dm_desc_tile_y
    P3DM_LD_U16_DE p3dm_expected_tile_y
    or a
    sbc hl,de
    jp nz,p3dm_bad_policy

; Signed minimum elevation must not exceed signed maximum elevation.
    ld a,(p3dm_file_buffer+p3dm_desc_minimum_elevation+1)
    xor 080h
    ld b,a
    ld a,(p3dm_file_buffer+p3dm_desc_maximum_elevation+1)
    xor 080h
    ld c,a
    ld a,b
    cp c
    jr c,@elevation_ok
    jp nz,p3dm_bad_bounds
    ld a,(p3dm_file_buffer+p3dm_desc_minimum_elevation)
    ld b,a
    ld a,(p3dm_file_buffer+p3dm_desc_maximum_elevation)
    cp b
    jp c,p3dm_bad_bounds
@elevation_ok:
    ld a,(p3dm_file_buffer+p3dm_desc_half_extent)
    ld hl,p3dm_file_buffer+p3dm_desc_half_extent+1
    or (hl)
    jp z,p3dm_bad_policy
; Q8.8 object scale is model_half_extent_m / 8, so the exact supported domain
; is 1..2047 m. 2048 would require 65536 and wrap a u16 scale to zero.
    P3DM_LD_U16_HL p3dm_file_buffer+p3dm_desc_half_extent
    ld de,2048
    or a
    sbc hl,de
    jp nc,p3dm_bad_policy

; Copy exact-u16 counts into normalized loader state.
    ld a,(p3dm_file_buffer+p3dm_desc_vertices)
    ld (p3dm_vertex_count),a
    ld a,(p3dm_file_buffer+p3dm_desc_vertices+1)
    ld (p3dm_vertex_count+1),a
    ld a,(p3dm_file_buffer+p3dm_desc_position_indices)
    ld (p3dm_position_index_count),a
    ld a,(p3dm_file_buffer+p3dm_desc_position_indices+1)
    ld (p3dm_position_index_count+1),a
    ld a,(p3dm_file_buffer+p3dm_desc_uvs)
    ld (p3dm_uv_count),a
    ld a,(p3dm_file_buffer+p3dm_desc_uvs+1)
    ld (p3dm_uv_count+1),a
    ld a,(p3dm_file_buffer+p3dm_desc_uv_indices)
    ld (p3dm_uv_index_count),a
    ld a,(p3dm_file_buffer+p3dm_desc_uv_indices+1)
    ld (p3dm_uv_index_count+1),a

    P3DM_LD_U16_HL p3dm_vertex_count
    ld de,3
    or a
    sbc hl,de
    jp c,p3dm_bad_counts
    P3DM_LD_U16_HL p3dm_position_index_count
    ld de,3
    or a
    sbc hl,de
    jp c,p3dm_bad_counts
    P3DM_LD_U16_HL p3dm_uv_count
    ld de,1
    or a
    sbc hl,de
    jp c,p3dm_bad_counts
    P3DM_LD_U16_HL p3dm_uv_index_count
    P3DM_LD_U16_DE p3dm_position_index_count
    or a
    sbc hl,de
    jp nz,p3dm_bad_counts
    P3DM_LD_U16_HL p3dm_position_index_count
@mod_three:
    ld de,3
    or a
    sbc hl,de
    jr c,@mod_done
    jr @mod_three
@mod_done:
    add hl,de
    ld a,h
    or l
    jp nz,p3dm_bad_counts

; Compute 6V+2I+4U+2T in native 24-bit registers, constrain it to the
; fixed probe window, and compare the exact DATA u32.
    ld hl,0
    P3DM_LD_U16_DE p3dm_vertex_count
    add hl,de
    add hl,de
    add hl,de
    add hl,de
    add hl,de
    add hl,de
    P3DM_LD_U16_DE p3dm_position_index_count
    add hl,de
    add hl,de
    P3DM_LD_U16_DE p3dm_uv_count
    add hl,de
    add hl,de
    add hl,de
    add hl,de
    P3DM_LD_U16_DE p3dm_uv_index_count
    add hl,de
    add hl,de
    push hl
    ld de,p3dm_max_data_bytes+1
    or a
    sbc hl,de
    pop hl
    jp nc,p3dm_bad_counts
    P3DM_ST_U16_HL p3dm_data_size

    ld hl,p3dm_file_buffer+p3dm_data_chunk_offset
    ld de,p3dm_id_data
    call p3dm_compare_fourcc
    jp nz,p3dm_bad_structure
    ld a,(p3dm_file_buffer+p3dm_data_size_offset+2)
    ld hl,p3dm_file_buffer+p3dm_data_size_offset+3
    or (hl)
    jp nz,p3dm_bad_bounds
    P3DM_LD_U16_HL p3dm_file_buffer+p3dm_data_size_offset
    P3DM_LD_U16_DE p3dm_data_size
    or a
    sbc hl,de
    jp nz,p3dm_bad_counts

; File end must be exactly DATA plus zero-valued 4-byte alignment padding.
    P3DM_LD_U16_HL p3dm_data_size
    ld de,3
    add hl,de
    res 0,l
    res 1,l
    ld de,p3dm_data_offset
    add hl,de
    P3DM_LD_U16_DE p3dm_file_size
    or a
    sbc hl,de
    jp nz,p3dm_bad_bounds
    call p3dm_validate_padding
    ret nz
    call p3dm_validate_position_indices
    ret nz
    call p3dm_validate_uv_indices
    ret nz
    call p3dm_validate_crc32
    ret nz
    call p3dm_retain_descriptor
    xor a
    ret

; Publish descriptor placement witnesses to coordinator-readable state only
; after all structural, bounds, index, and CRC checks have succeeded. Signed
; i32 and i16 values remain little-endian two's-complement byte sequences.
p3dm_retain_descriptor:
    ld a,(p3dm_file_buffer+p3dm_desc_tile_x)
    ld (p3dm_tile_x),a
    ld a,(p3dm_file_buffer+p3dm_desc_tile_x+1)
    ld (p3dm_tile_x+1),a
    ld a,(p3dm_file_buffer+p3dm_desc_tile_y)
    ld (p3dm_tile_y),a
    ld a,(p3dm_file_buffer+p3dm_desc_tile_y+1)
    ld (p3dm_tile_y+1),a
    ld a,(p3dm_file_buffer+p3dm_desc_center_east+0)
    ld (p3dm_center_east_m+0),a
    ld a,(p3dm_file_buffer+p3dm_desc_center_east+1)
    ld (p3dm_center_east_m+1),a
    ld a,(p3dm_file_buffer+p3dm_desc_center_east+2)
    ld (p3dm_center_east_m+2),a
    ld a,(p3dm_file_buffer+p3dm_desc_center_east+3)
    ld (p3dm_center_east_m+3),a
    ld a,(p3dm_file_buffer+p3dm_desc_center_north+0)
    ld (p3dm_center_north_m+0),a
    ld a,(p3dm_file_buffer+p3dm_desc_center_north+1)
    ld (p3dm_center_north_m+1),a
    ld a,(p3dm_file_buffer+p3dm_desc_center_north+2)
    ld (p3dm_center_north_m+2),a
    ld a,(p3dm_file_buffer+p3dm_desc_center_north+3)
    ld (p3dm_center_north_m+3),a
    ld a,(p3dm_file_buffer+p3dm_desc_minimum_elevation+0)
    ld (p3dm_minimum_elevation_dm+0),a
    ld a,(p3dm_file_buffer+p3dm_desc_minimum_elevation+1)
    ld (p3dm_minimum_elevation_dm+1),a
    ld a,(p3dm_file_buffer+p3dm_desc_maximum_elevation+0)
    ld (p3dm_maximum_elevation_dm+0),a
    ld a,(p3dm_file_buffer+p3dm_desc_maximum_elevation+1)
    ld (p3dm_maximum_elevation_dm+1),a
    ld a,(p3dm_file_buffer+p3dm_desc_half_extent+0)
    ld (p3dm_model_half_extent_m+0),a
    ld a,(p3dm_file_buffer+p3dm_desc_half_extent+1)
    ld (p3dm_model_half_extent_m+1),a
    ret

p3dm_validate_padding:
    P3DM_LD_U16_HL p3dm_data_size
    ld de,p3dm_file_buffer+p3dm_data_offset
    add hl,de
    push hl
    pop ix
    P3DM_LD_U16_HL p3dm_data_size
    ld de,3
    add hl,de
    res 0,l
    res 1,l
    P3DM_LD_U16_DE p3dm_data_size
    or a
    sbc hl,de
    ld b,l
    ld a,b
    or a
    jr z,@ok
@loop:
    ld a,(ix)
    or a
    jp nz,p3dm_bad_structure
    inc ix
    djnz @loop
@ok:
    xor a
    ret

p3dm_validate_position_indices:
; IX = DATA + 6V, BC = V bound, DE = I entries remaining.
    ld hl,0
    P3DM_LD_U16_DE p3dm_vertex_count
    add hl,de
    add hl,de
    add hl,de
    add hl,de
    add hl,de
    add hl,de
    ld de,p3dm_file_buffer+p3dm_data_offset
    add hl,de
    push hl
    pop ix
    P3DM_LD_U16_BC p3dm_vertex_count
    P3DM_LD_U16_DE p3dm_position_index_count
@loop:
    ld a,d
    or e
    jr z,@ok
    ld hl,0
    ld l,(ix+0)
    ld h,(ix+1)
    or a
    sbc hl,bc
    jp nc,p3dm_bad_indices
    lea ix,ix+2
    dec de
    jr @loop
@ok:
    xor a
    ret

p3dm_validate_uv_indices:
; IX = DATA + data_size - 2T. Flat P3DM requires one repeated selector
; index per triangle, so equality plus the first index's bound check suffices.
    P3DM_LD_U16_HL p3dm_data_size
    P3DM_LD_U16_DE p3dm_uv_index_count
    or a
    sbc hl,de
    or a
    sbc hl,de
    ld de,p3dm_file_buffer+p3dm_data_offset
    add hl,de
    push hl
    pop ix
    P3DM_LD_U16_BC p3dm_uv_count
    P3DM_LD_U16_DE p3dm_uv_index_count
@loop:
    ld a,d
    or e
    jr z,@ok
    ld hl,0
    ld a,(ix+0)
    ld (p3dm_selector_index),a
    ld l,a
    ld a,(ix+1)
    ld (p3dm_selector_index+1),a
    ld h,a
    or a
    sbc hl,bc
    jp nc,p3dm_bad_indices
    ld a,(p3dm_selector_index)
    cp (ix+2)
    jp nz,p3dm_bad_indices
    ld a,(p3dm_selector_index+1)
    cp (ix+3)
    jp nz,p3dm_bad_indices
    ld a,(p3dm_selector_index)
    cp (ix+4)
    jp nz,p3dm_bad_indices
    ld a,(p3dm_selector_index+1)
    cp (ix+5)
    jp nz,p3dm_bad_indices
    lea ix,ix+6
    dec de
    dec de
    dec de
    jr @loop
@ok:
    xor a
    ret

; Reflected CRC-32/ISO-HDLC: init/xorout FFFFFFFF, polynomial EDB88320.
p3dm_validate_crc32:
    ld a,0FFh
    ld (p3dm_crc_value+0),a
    ld (p3dm_crc_value+1),a
    ld (p3dm_crc_value+2),a
    ld (p3dm_crc_value+3),a
    ld ix,p3dm_file_buffer+p3dm_data_offset
    P3DM_LD_U16_BC p3dm_data_size
@byte:
    ld a,b
    or c
    jr z,@finish
    push bc
    ld a,(ix)
    inc ix
    ld hl,p3dm_crc_value
    xor (hl)
    ld (hl),a
    ld b,8
@bit:
    ld hl,p3dm_crc_value+3
    srl (hl)
    dec hl
    rr (hl)
    dec hl
    rr (hl)
    dec hl
    rr (hl)
    jr nc,@no_polynomial
    ld a,(p3dm_crc_value+0)
    xor 020h
    ld (p3dm_crc_value+0),a
    ld a,(p3dm_crc_value+1)
    xor 083h
    ld (p3dm_crc_value+1),a
    ld a,(p3dm_crc_value+2)
    xor 0B8h
    ld (p3dm_crc_value+2),a
    ld a,(p3dm_crc_value+3)
    xor 0EDh
    ld (p3dm_crc_value+3),a
@no_polynomial:
    djnz @bit
    pop bc
    dec bc
    jr @byte
@finish:
    ld b,4
    ld hl,p3dm_crc_value
@complement:
    ld a,(hl)
    cpl
    ld (hl),a
    inc hl
    djnz @complement
    ld hl,p3dm_crc_value
    ld de,p3dm_file_buffer+p3dm_desc_crc32
    ld b,4
@compare:
    ld a,(de)
    cp (hl)
    jp nz,p3dm_bad_crc32
    inc de
    inc hl
    djnz @compare
    xor a
    ret

; Upload one exact consolidated DATA block. Container headers and metadata
; never enter the VDP staging buffer.
p3dm_upload_data:
    ld hl,@clear
    ld bc,@clear_end-@clear
    rst.lil 18h
    jp @clear_end
@clear:
    db 23,0,0A0h
    dw p3dm_stage_buffer_id
    db 2
@clear_end:
    P3DM_LD_U16_HL p3dm_data_size
    ld a,l
    ld (@length),a
    ld a,h
    ld (@length+1),a
    ld hl,@upload
    ld bc,@upload_end-@upload
    rst.lil 18h
    jp @upload_end
@upload:
    db 23,0,0A0h
    dw p3dm_stage_buffer_id
    db 0
@length:
    dw 0
@upload_end:
    ld hl,p3dm_file_buffer+p3dm_data_offset
    P3DM_LD_U16_BC p3dm_data_size
    rst.lil 18h
    ld hl,p3dm_stage_buffer_id
    call vdu_consolidate_buffer
    xor a
    ret

; Pingo subcommand 50. The target slot must already exist and remain bound.
pingo_replace_mesh_from_buffer:
    ld a,(p3dm_target_mesh_id)
    ld (@mesh_id),a
    ld a,(p3dm_target_mesh_id+1)
    ld (@mesh_id+1),a
    P3DM_LD_U16_BC p3dm_vertex_count
    ld hl,@vertices
    ST_U16_BC_ADV
    P3DM_LD_U16_BC p3dm_position_index_count
    ST_U16_BC_ADV
    P3DM_LD_U16_BC p3dm_uv_count
    ST_U16_BC_ADV
    P3DM_LD_U16_BC p3dm_uv_index_count
    ST_U16_BC_ADV
    ld hl,@command
    ld bc,@command_end-@command
    rst.lil 18h
    ret
@command:
    db 23,0,0A0h
    dw sid
    db 049h,50
    dw p3dm_stage_buffer_id
@mesh_id:
    dw 0
@vertices:
    dw 0
@position_indices:
    dw 0
@uvs:
    dw 0
@uv_indices:
    dw 0
@command_end:

; Pingo subcommand 51. Inputs: HL=object ID, A=0 inactive or A=1 active.
pingo_set_object_active:
    push af
    ld a,l
    ld (@object_id),a
    ld a,h
    ld (@object_id+1),a
    pop af
    ld (@active),a
    ld hl,@command
    ld bc,@command_end-@command
    rst.lil 18h
    ret
@command:
    db 23,0,0A0h
    dw sid
    db 049h,51
@object_id:
    dw 0
@active:
    db 0
@command_end:

p3dm_bad_structure:
    ld a,p3dm_error_structure
    jr p3dm_return_error
p3dm_bad_policy:
    ld a,p3dm_error_policy
    jr p3dm_return_error
p3dm_bad_counts:
    ld a,p3dm_error_counts
    jr p3dm_return_error
p3dm_bad_bounds:
    ld a,p3dm_error_bounds
    jr p3dm_return_error
p3dm_bad_crc32:
    ld a,p3dm_error_crc32
    jr p3dm_return_error
p3dm_bad_indices:
    ld a,p3dm_error_indices
p3dm_return_error:
    ld (p3dm_last_error),a
    or a
    ret

p3dm_id_riff: db "RIFF"
p3dm_id_agnb: db "AGNB"
p3dm_id_vers: db "VERS"
p3dm_id_list: db "LIST"
p3dm_id_bufr: db "BUFR"
p3dm_id_bhdr: db "BHDR"
p3dm_id_p3dm: db "P3DM"
p3dm_id_data: db "DATA"

; Caller-owned request block. The writable pathname buffer accepts a sequence
; of 8.3 path components plus NUL; callers may alternatively point the native
; 24-bit pointer at another writable, lifetime-stable ASCIIZ pathname.
p3dm_filename_capacity: equ 64
p3dm_filename_buffer:
    db "TRN/L0/00/0C.AGN",0
p3dm_filename_default_end:
p3dm_filename_default_bytes: equ p3dm_filename_default_end-p3dm_filename_buffer
    ds p3dm_filename_capacity-p3dm_filename_default_bytes
p3dm_filename_pointer: dl p3dm_filename_buffer
p3dm_target_mesh_id: dw 0
p3dm_expected_layer: db 0
p3dm_expected_lod: db 0
p3dm_expected_shading: db 0
p3dm_expected_illumination: db 0
p3dm_expected_material_set: db 0
p3dm_expected_tile_x: dw 0
p3dm_expected_tile_y: dw 0

; Result block. It is authoritative only when p3dm_loader_state reaches
; p3dm_state_validated or later for the current synchronous request.
p3dm_last_error: db p3dm_error_ok
p3dm_loader_state: db p3dm_state_idle
p3dm_tile_x: dw 0
p3dm_tile_y: dw 0
p3dm_center_east_m: ds 4
p3dm_center_north_m: ds 4
p3dm_minimum_elevation_dm: dw 0
p3dm_maximum_elevation_dm: dw 0
p3dm_model_half_extent_m: dw 0
p3dm_pending_error: db 0
p3dm_close_result: db 0
p3dm_file_size: dw 0
p3dm_data_size: dw 0
p3dm_vertex_count: dw 0
p3dm_position_index_count: dw 0
p3dm_uv_count: dw 0
p3dm_uv_index_count: dw 0
p3dm_selector_index: dw 0
p3dm_crc_value: ds 4
p3dm_read_remaining: dl 0
p3dm_read_pointer: dl 0
p3dm_fil: ds p3dm_fil_size
p3dm_file_buffer: ds p3dm_max_file_bytes
