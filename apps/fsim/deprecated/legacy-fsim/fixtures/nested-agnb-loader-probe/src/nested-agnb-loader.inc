; Bounded selected-record reader for ordinary multi-record AGNB 0.3 files.
;
; Include this after p3dm-loader.inc. The caller initializes the same request
; block used by p3dm_load_component, then calls agnb_load_selected_component.
; Unmatched DATA chunks are skipped with absolute FatFS seeks. The selected
; LIST is reconstructed at p3dm_file_buffer+24 and then follows the proven
; p3dm_validate_container / upload / command-50 publication path.

ffs_flseek: equ 084h

agnb_prefix_bytes: equ 24
agnb_record_prefix_bytes: equ 76
agnb_list_fixed_payload_bytes: equ 68
agnb_max_records: equ 16
agnb_max_family_bytes: equ 0FFFFFFh

agnb_error_seek: equ 12
agnb_error_not_found: equ 13
agnb_error_duplicate: equ 14
agnb_error_record_limit: equ 15

; Top-level transaction. No VDP byte is emitted until the selected DATA has
; passed the original exact parser, policy, count, index, padding and CRC path.
agnb_load_selected_component:
    xor a
    ld (p3dm_last_error),a
    ld (p3dm_loader_state),a
    call agnb_read_selected_container
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

; Open and always close the family before validation/publication observes the
; reconstructed single-record image.
agnb_read_selected_container:
    ld de,(p3dm_filename_pointer) ; ADL24 OK: native 24-bit path pointer
    ld hl,p3dm_fil
    ld c,fa_read
    FFSCALL ffs_fopen
    or a
    jp nz,p3dm_bad_open
    ld a,p3dm_state_reading
    ld (p3dm_loader_state),a

    call agnb_scan_open_file
    ld (p3dm_pending_error),a
    ld hl,p3dm_fil
    FFSCALL ffs_fclose
    ld (p3dm_close_result),a
    ld a,(p3dm_pending_error)
    or a
    ret nz
    ld a,(p3dm_close_result)
    or a
    jp nz,p3dm_bad_close
    ld a,p3dm_state_closed
    ld (p3dm_loader_state),a
    xor a
    ret

; Input HL is a bounded absolute u24 offset. All accepted files have a zero
; fourth offset byte, so ffs_flseek receives C=0 and DEU:DE=HL.
agnb_seek_hl:
    ld (agnb_seek_position),hl ; ADL24 OK: destination is exactly dl/u24
    ld de,(agnb_seek_position) ; ADL24 OK: source is exactly dl/u24
    ld c,0
    ld hl,p3dm_fil
    FFSCALL ffs_flseek
    or a
    ret z
    ld a,agnb_error_seek
    jp p3dm_return_error

; Read and scan fixed metadata only. Every sibling contributes 76 bytes plus
; zero to three alignment bytes; only the chosen DATA enters the 16 KiB window.
agnb_scan_open_file:
; FatFS records a u32 file size. This bounded implementation admits 100 bytes
; through 0x00ffffff and retains the low 24 bits as a native ADL quantity.
    ld a,(p3dm_fil+fil_obj+ffobjid_objsize+3)
    or a
    jp nz,p3dm_bad_file_size
    ld a,(p3dm_fil+fil_obj+ffobjid_objsize+0)
    ld (agnb_file_size+0),a
    ld a,(p3dm_fil+fil_obj+ffobjid_objsize+1)
    ld (agnb_file_size+1),a
    ld a,(p3dm_fil+fil_obj+ffobjid_objsize+2)
    ld (agnb_file_size+2),a
    ld hl,(agnb_file_size) ; ADL24 OK: source is exactly dl/u24
    ld de,p3dm_data_offset
    or a
    sbc hl,de
    jp c,p3dm_bad_file_size

    ld hl,0
    call agnb_seek_hl
    ret nz
    ld bc,agnb_prefix_bytes
    ld de,p3dm_file_buffer
    call p3dm_read_exact
    ret nz
    call agnb_validate_outer_prefix
    ret nz

    xor a
    ld (agnb_record_count),a
    ld (agnb_selected_found),a
    ld hl,agnb_prefix_bytes
    ld (agnb_scan_offset),hl ; ADL24 OK: destination is exactly dl/u24

@record:
    ld hl,(agnb_scan_offset) ; ADL24 OK: source is exactly dl/u24
    ld de,(agnb_file_size)   ; ADL24 OK: source is exactly dl/u24
    or a
    sbc hl,de
    jp z,@scan_complete
    jp nc,p3dm_bad_bounds

; Require the complete fixed record prefix before issuing its read.
    ld hl,(agnb_file_size)   ; ADL24 OK: source is exactly dl/u24
    ld de,(agnb_scan_offset) ; ADL24 OK: source is exactly dl/u24
    or a
    sbc hl,de
    ld de,agnb_record_prefix_bytes
    or a
    sbc hl,de
    jp c,p3dm_bad_bounds
    ld a,(agnb_record_count)
    cp agnb_max_records
    jp nc,agnb_bad_record_limit

    ld hl,(agnb_scan_offset) ; ADL24 OK: source is exactly dl/u24
    call agnb_seek_hl
    ret nz
    ld bc,agnb_record_prefix_bytes
    ld de,p3dm_file_buffer+agnb_prefix_bytes
    call p3dm_read_exact
    ret nz
    call agnb_validate_record_prefix
    ret nz

; Detect an exact caller-selected identity. A second match is ambiguous and
; rejected even though its DATA would otherwise remain unread.
    call agnb_descriptor_matches_request
    jr nz,@padding
    ld a,(agnb_selected_found)
    or a
    jp nz,agnb_bad_duplicate
    inc a
    ld (agnb_selected_found),a
    ld a,(agnb_record_count)
    ld (agnb_selected_index),a
    ld hl,(agnb_scan_offset) ; ADL24 OK: source is exactly dl/u24
    ld (agnb_selected_offset),hl ; ADL24 OK: destination is exactly dl/u24
    P3DM_LD_U16_HL agnb_current_data_size
    P3DM_ST_U16_HL agnb_selected_data_size

@padding:
; LIST payloads are multiples of four; any DATA alignment bytes are their last
; bytes. Read and reject nonzero padding without reading sibling DATA.
    P3DM_LD_U16_HL agnb_current_data_size
    push hl
    ld de,3
    add hl,de
    res 0,l
    res 1,l
    pop de
    or a
    sbc hl,de
    ld a,l
    ld (agnb_padding_count),a
    or a
    jr z,@next_record
    ld hl,(agnb_scan_offset) ; ADL24 OK: source is exactly dl/u24
    ld de,agnb_record_prefix_bytes
    add hl,de
    jp c,p3dm_bad_bounds
    P3DM_LD_U16_DE agnb_current_data_size
    add hl,de
    jp c,p3dm_bad_bounds
    call agnb_seek_hl
    ret nz
    ld bc,0
    ld a,(agnb_padding_count)
    ld c,a
    ld de,agnb_padding_scratch
    call p3dm_read_exact
    ret nz
    ld a,(agnb_padding_count)
    ld b,a
    ld hl,agnb_padding_scratch
@padding_byte:
    ld a,(hl)
    or a
    jp nz,p3dm_bad_structure
    inc hl
    djnz @padding_byte

@next_record:
    ld hl,(agnb_next_offset) ; ADL24 OK: source is exactly dl/u24
    ld (agnb_scan_offset),hl ; ADL24 OK: destination is exactly dl/u24
    ld a,(agnb_record_count)
    inc a
    ld (agnb_record_count),a
    jp @record

@scan_complete:
    ld a,(agnb_record_count)
    or a
    jp z,p3dm_bad_structure
    ld a,(agnb_selected_found)
    or a
    jp z,agnb_bad_not_found

; Re-read the chosen fixed prefix after the complete family scan, then verify
; its identity and length again before reading only its padded DATA.
    ld hl,(agnb_selected_offset) ; ADL24 OK: source is exactly dl/u24
    ld (agnb_scan_offset),hl ; ADL24 OK: validator needs selected LIST origin
    call agnb_seek_hl
    ret nz
    ld bc,agnb_record_prefix_bytes
    ld de,p3dm_file_buffer+agnb_prefix_bytes
    call p3dm_read_exact
    ret nz
    call agnb_validate_record_prefix
    ret nz
    call agnb_descriptor_matches_request
    jp nz,p3dm_bad_policy
    P3DM_LD_U16_HL agnb_current_data_size
    P3DM_LD_U16_DE agnb_selected_data_size
    or a
    sbc hl,de
    jp nz,p3dm_bad_bounds

    ld hl,(agnb_selected_offset) ; ADL24 OK: source is exactly dl/u24
    ld de,agnb_record_prefix_bytes
    add hl,de
    jp c,p3dm_bad_bounds
    call agnb_seek_hl
    ret nz
    P3DM_LD_U16_HL agnb_current_data_size
    ld de,3
    add hl,de
    res 0,l
    res 1,l
    push hl
    pop bc
    ld de,p3dm_file_buffer+p3dm_data_offset
    call p3dm_read_exact
    ret nz

; Turn the selected LIST into the exact one-record image understood by the
; existing parser. Writes are bytewise so no u16 field can consume a neighbor.
    P3DM_LD_U16_HL agnb_current_data_size
    ld de,3
    add hl,de
    res 0,l
    res 1,l
    ld de,p3dm_data_offset
    add hl,de
    ld de,p3dm_max_file_bytes+1
    push hl
    or a
    sbc hl,de
    pop hl
    jp nc,p3dm_bad_bounds
    P3DM_ST_U16_HL p3dm_file_size

    push hl
    ld de,8
    or a
    sbc hl,de
    ld a,l
    ld (p3dm_file_buffer+p3dm_riff_size_offset+0),a
    ld a,h
    ld (p3dm_file_buffer+p3dm_riff_size_offset+1),a
    xor a
    ld (p3dm_file_buffer+p3dm_riff_size_offset+2),a
    ld (p3dm_file_buffer+p3dm_riff_size_offset+3),a
    pop hl
    ld de,32
    or a
    sbc hl,de
    ld a,l
    ld (p3dm_file_buffer+p3dm_list_size_offset+0),a
    ld a,h
    ld (p3dm_file_buffer+p3dm_list_size_offset+1),a
    xor a
    ld (p3dm_file_buffer+p3dm_list_size_offset+2),a
    ld (p3dm_file_buffer+p3dm_list_size_offset+3),a
    ret

; Validate the exact RIFF/AGNB/VERS prefix and full-file equality. The fourth
; file-size byte was already required to be zero before this comparison.
agnb_validate_outer_prefix:
    ld hl,p3dm_file_buffer+0
    ld de,p3dm_id_riff
    call p3dm_compare_fourcc
    jp nz,p3dm_bad_structure
    ld hl,p3dm_file_buffer+8
    ld de,p3dm_id_agnb
    call p3dm_compare_fourcc
    jp nz,p3dm_bad_structure
    ld a,(p3dm_file_buffer+p3dm_riff_size_offset+3)
    or a
    jp nz,p3dm_bad_bounds
    ld hl,(agnb_file_size) ; ADL24 OK: source is exactly dl/u24
    ld de,8
    or a
    sbc hl,de
    ld de,(p3dm_file_buffer+p3dm_riff_size_offset) ; ADL24 OK: low 24 bits of u32
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
    xor a
    ret

; Validate one 76-byte LIST/BUFR/BHDR/P3DM/DATA prefix, its bounded DATA size,
; exact LIST length and next offset. Selected mesh semantics remain delegated
; to p3dm_validate_container after DATA is present.
agnb_validate_record_prefix:
    ld hl,p3dm_file_buffer+24
    ld de,p3dm_id_list
    call p3dm_compare_fourcc
    jp nz,p3dm_bad_structure
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
    ld a,(p3dm_file_buffer+p3dm_desc_layout)
    cp 1
    jp nz,p3dm_bad_policy
    ld hl,p3dm_file_buffer+p3dm_data_chunk_offset
    ld de,p3dm_id_data
    call p3dm_compare_fourcc
    jp nz,p3dm_bad_structure

    ld a,(p3dm_file_buffer+p3dm_data_size_offset+2)
    ld hl,p3dm_file_buffer+p3dm_data_size_offset+3
    or (hl)
    jp nz,p3dm_bad_bounds
    P3DM_LD_U16_HL p3dm_file_buffer+p3dm_data_size_offset
    ld de,p3dm_max_data_bytes+1
    push hl
    or a
    sbc hl,de
    pop hl
    jp nc,p3dm_bad_bounds
    P3DM_ST_U16_HL agnb_current_data_size

; LIST size must be exactly 68+align4(DATA), so seeks can never be redirected
; into DATA or beyond the RIFF boundary by contradictory nested lengths.
    ld de,3
    add hl,de
    res 0,l
    res 1,l
    ld de,agnb_list_fixed_payload_bytes
    add hl,de
    P3DM_LD_U16_DE p3dm_file_buffer+p3dm_list_size_offset
    or a
    sbc hl,de
    jp nz,p3dm_bad_bounds
    ld a,(p3dm_file_buffer+p3dm_list_size_offset+2)
    ld hl,p3dm_file_buffer+p3dm_list_size_offset+3
    or (hl)
    jp nz,p3dm_bad_bounds

    ld hl,(agnb_scan_offset) ; ADL24 OK: source is exactly dl/u24
    ld de,8
    add hl,de
    jp c,p3dm_bad_bounds
    P3DM_LD_U16_DE p3dm_file_buffer+p3dm_list_size_offset
    add hl,de
    jp c,p3dm_bad_bounds
    ld (agnb_next_offset),hl ; ADL24 OK: destination is exactly dl/u24
    ld de,(agnb_file_size)   ; ADL24 OK: source is exactly dl/u24
    or a
    sbc hl,de
    jp nc,@at_or_beyond_end
    xor a
    ret
@at_or_beyond_end:
    ret z
    jp p3dm_bad_bounds

; Z means all exact request identity fields match. This routine intentionally
; excludes centre/count/CRC; the fixed P3DM validator owns those semantics.
agnb_descriptor_matches_request:
    ld a,(p3dm_expected_layer)
    ld b,a
    ld a,(p3dm_file_buffer+p3dm_desc_layer)
    cp b
    ret nz
    ld a,(p3dm_expected_lod)
    ld b,a
    ld a,(p3dm_file_buffer+p3dm_desc_lod)
    cp b
    ret nz
    ld a,(p3dm_expected_shading)
    ld b,a
    ld a,(p3dm_file_buffer+p3dm_desc_shading)
    cp b
    ret nz
    ld a,(p3dm_expected_illumination)
    ld b,a
    ld a,(p3dm_file_buffer+p3dm_desc_illumination)
    cp b
    ret nz
    ld a,(p3dm_expected_material_set)
    ld b,a
    ld a,(p3dm_file_buffer+p3dm_desc_material_set)
    cp b
    ret nz
    ld a,(p3dm_expected_tile_x+0)
    ld b,a
    ld a,(p3dm_file_buffer+p3dm_desc_tile_x+0)
    cp b
    ret nz
    ld a,(p3dm_expected_tile_x+1)
    ld b,a
    ld a,(p3dm_file_buffer+p3dm_desc_tile_x+1)
    cp b
    ret nz
    ld a,(p3dm_expected_tile_y+0)
    ld b,a
    ld a,(p3dm_file_buffer+p3dm_desc_tile_y+0)
    cp b
    ret nz
    ld a,(p3dm_expected_tile_y+1)
    ld b,a
    ld a,(p3dm_file_buffer+p3dm_desc_tile_y+1)
    cp b
    ret

agnb_bad_seek:
    ld a,agnb_error_seek
    jp p3dm_return_error
agnb_bad_not_found:
    ld a,agnb_error_not_found
    jp p3dm_return_error
agnb_bad_duplicate:
    ld a,agnb_error_duplicate
    jp p3dm_return_error
agnb_bad_record_limit:
    ld a,agnb_error_record_limit
    jp p3dm_return_error

; Native u24 fields are intentionally declared dl. Exact-u16 fields are dw
; and are accessed only through the bytewise P3DM macros.
agnb_file_size: dl 0
agnb_scan_offset: dl 0
agnb_next_offset: dl 0
agnb_selected_offset: dl 0
agnb_seek_position: dl 0
agnb_current_data_size: dw 0
agnb_selected_data_size: dw 0
agnb_record_count: db 0
agnb_selected_found: db 0
agnb_selected_index: db 0
agnb_padding_count: db 0
agnb_padding_scratch: ds 3
