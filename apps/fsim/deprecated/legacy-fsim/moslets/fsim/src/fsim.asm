; FSIM terrain-fixture launcher.
;
; This MOSlet remains resident at 0x0B0000 while each ordinary ADL fixture is
; loaded at, and called through, its public MOS entry at 0x040000.  Every
; fixture therefore uses the same final RET both under this launcher and when
; LOAD/RUN directly from MOS.

mos_getkey:  equ 00h
mos_load:    equ 01h
mos_cd:      equ 03h
mos_fopen:   equ 0Ah
mos_fclose:  equ 0Bh
mos_getkbmap: equ 1Eh
mos_fread:   equ 1Ah
ffs_getcwd:  equ 09Eh

fa_read: equ 01h

fixture_entry:        equ 040000h
fixture_header:       equ fixture_entry+040h
fixture_load_capacity: equ 070000h
config_root_max:      equ 176
path_buffer_bytes:    equ 256
fixture_count:        equ 13

    MACRO MOSCALL function
        ld a,function
        rst.lil 08h
    ENDMACRO

    .assume adl=1
    .org 0B0000h
    jp _start
_exec_name:
    db "fsim.bin",0
    .align 64
    db "MOS",0,1

_start:
    push af
    push bc
    push de
    push ix
    push iy
    ld a,MB
    push af
    xor a
    ld MB,a
    call main
    pop af
    ld MB,a
    pop iy
    pop ix
    pop de
    pop bc
    pop af
    ret

main:
    call save_current_directory
    jp nz,main_cwd_failed
    call read_config_root
    jp nz,main_config_failed

main_menu:
    call restore_current_directory
    jp nz,main_restore_failed
    call show_menu
launcher_menu_wait:
    MOSCALL mos_getkey
    cp 27
    jr z,main_exit
    cp '0'
    jr nz,@regular_fixture
    ld a,9
    jr @fixture_selected
@regular_fixture:
    cp 'R'
    jr z,@select_regular
    cp 'r'
    jr nz,@distance_fixture
@select_regular:
    ld a,12
    jr @fixture_selected
@distance_fixture:
    cp 'D'
    jr z,@select_distance
    cp 'd'
    jr nz,@natural_fixture
@select_distance:
    ld a,11
    jr @fixture_selected
@natural_fixture:
    cp 'N'
    jr z,@select_natural
    cp 'n'
    jr nz,@numbered_fixture
@select_natural:
    ld a,10
    jr @fixture_selected
@numbered_fixture:
    cp '1'
    jr c,launcher_menu_wait
    cp '9'+1
    jr nc,launcher_menu_wait
    sub '1'
@fixture_selected:
    ld (selected_index),a
    call wait_for_keys_released
    call run_selected_fixture
launcher_after_fixture:
    ld (last_error),a
    or a
    call z,release_fixture_scene
    call restore_current_directory
    jp nz,main_restore_failed
    call wait_for_keys_released
    ld a,(last_error)
    or a
    jr z,main_menu
    call show_launch_error
    jr main_menu

main_exit:
    call wait_for_keys_released
    call restore_current_directory
    jp nz,main_restore_failed
    call reset_text_screen
    ld hl,exit_text
    call print_string
launcher_return_to_mos:
    ld hl,0
    ret

main_cwd_failed:
    call reset_text_screen
    ld hl,cwd_error_text
    call print_string
    ld hl,1
    ret

main_config_failed:
    call reset_text_screen
    ld hl,config_error_text
    call print_string
    ld hl,2
    ret

main_restore_failed:
    call reset_text_screen
    ld hl,restore_error_text
    call print_string
    ld hl,3
    ret

; Save the caller's actual FatFS working directory once.  All later changes,
; including restoration, deliberately go through the high-level mos_cd path.
; The old profile MOS leaves its printable _cwd cache stale across API 3, so
; qualification proves the real FatFS directory with relative loads instead.
save_current_directory:
    ld hl,saved_current_directory
    ld bc,path_buffer_bytes
    MOSCALL ffs_getcwd
    or a
    ret

restore_current_directory:
    ld hl,saved_current_directory
    MOSCALL mos_cd
    or a
    ret

; Read one absolute Agon SD path from /mos/fsim.cfg.  The root is intentionally
; data rather than assembly so the same launcher binary can be installed with
; fixtures at another location.  The maximum leaves ample space for the
; longest built-in relative fixture directory in path_buffer.
read_config_root:
    xor a
    ld (config_root),a
    ld hl,config_filename
    ld c,fa_read
    MOSCALL mos_fopen
    or a
    jr z,@failed
    ld (config_handle),a
    ld c,a
    ld hl,config_root
    ld de,config_root_max
    MOSCALL mos_fread
    ld a,(config_handle)
    ld c,a
    MOSCALL mos_fclose

    ld hl,config_root
    add hl,de
    xor a
    ld (hl),a
    ld hl,config_root_max
    or a
    sbc hl,de
    jr z,@failed

    ld hl,config_root
    ld a,(hl)
    cp '/'
    jr nz,@failed
@scan:
    ld a,(hl)
    or a
    jr z,@trim_slash
    cp 13
    jr z,@terminate
    cp 10
    jr z,@terminate
    cp 32
    jr c,@failed
    inc hl
    jr @scan
@terminate:
    xor a
    ld (hl),a
@trim_slash:
    ld de,config_root
    or a
    sbc hl,de
    jr z,@failed
    add hl,de
    dec hl
    ld a,(hl)
    cp '/'
    jr nz,@success
    ld de,config_root
    push hl
    or a
    sbc hl,de
    pop hl
    jr z,@success
    xor a
    ld (hl),a
@success:
    xor a
    ret
@failed:
    ld a,1
    or a
    ret

show_menu:
    call reset_text_screen
    ld hl,menu_text
    call print_string
    ret

; Return A=0 after a fixture returns normally.  Nonzero launcher-local errors:
; 1 = chdir, 2 = load, 3 = invalid common executable entry/header.
run_selected_fixture:
    call locate_fixture_record
    call build_fixture_directory
    push hl
    ld hl,path_buffer
    MOSCALL mos_cd
    ld (last_mos_status),a
    pop hl
    or a
    jr nz,@chdir_failed

    xor a
    ld (fixture_entry),a
    ld (fixture_header),a
    ld de,fixture_entry
    ld bc,fixture_load_capacity
    MOSCALL mos_load
    ld (last_mos_status),a
    or a
    jr nz,@load_failed
    call validate_fixture_entry
    jr nz,@entry_failed

    ; Mirror the normal MOS ADL entry registers for fixtures that later choose
    ; to consume arguments.  The current thirteen fixtures ignore them.
    xor a
    ld de,fixture_entry
    ld hl,empty_arguments
    call fixture_entry
    xor a
    ret
@chdir_failed:
    ld a,1
    or a
    ret
@load_failed:
    ld a,2
    or a
    ret
@entry_failed:
    xor a
    ld (last_mos_status),a
    ld a,3
    or a
    ret

validate_fixture_entry:
    ld hl,fixture_entry
    ld de,entry_signature
    ld b,entry_signature_end-entry_signature
    call compare_bytes
    ret nz
    ld hl,fixture_header
    ld de,header_signature
    ld b,header_signature_end-header_signature
    call compare_bytes
    ret

compare_bytes:
@loop:
    ld a,(de)
    cp (hl)
    ret nz
    inc de
    inc hl
    djnz @loop
    xor a
    ret

; Return HL at the selected record's relative directory.  Each record is two
; adjacent zero-terminated strings: directory, then executable filename.
locate_fixture_record:
    ld hl,fixture_records
    ld a,(selected_index)
    ld b,a
    or a
    ret z
@skip_record:
    call skip_string
    call skip_string
    djnz @skip_record
    ret

skip_string:
    ld a,(hl)
    inc hl
    or a
    jr nz,skip_string
    ret

; Input HL points at the record's directory.  Output HL points at its binary.
build_fixture_directory:
    push hl
    ld hl,config_root
    ld de,path_buffer
    call copy_string_without_nul
    dec de
    ld a,(de)
    inc de
    cp '/'
    jr z,@copy_relative
    ld a,'/'
    ld (de),a
    inc de
@copy_relative:
    pop hl
@copy_loop:
    ld a,(hl)
    ld (de),a
    inc hl
    inc de
    or a
    jr nz,@copy_loop
    ret

copy_string_without_nul:
    ld a,(hl)
    or a
    ret z
    ld (de),a
    inc hl
    inc de
    jr copy_string_without_nul

; Number-key and Escape presses must be physically released before ownership
; crosses the launcher/fixture boundary.  This prevents held-key repeat from
; satisfying an appliance's start gate or acting as the launcher's second Esc.
wait_for_keys_released:
    MOSCALL mos_getkbmap
    ld b,16
    ld c,0
@scan:
    ld a,(ix)
    or c
    ld c,a
    inc ix
    djnz @scan
    ld a,c
    or a
    jr nz,wait_for_keys_released
    ret

; Fixtures currently own one of two scene IDs.  Release the selected fixture's
; known-live control after its normal return so cross-family menu sessions do
; not retain scene-private allocations.  Load/entry failures created no scene.
release_fixture_scene:
    ld a,(selected_index)
    cp 5
    jr z,@family
    ld hl,@default_command
    ld bc,@default_end-@default_command
    rst.lil 18h
    ret
@family:
    ld hl,@family_command
    ld bc,@family_end-@family_command
    rst.lil 18h
    ret
@default_command:
    db 23,0,0A0h
    dw 1731
    db 49h,39
@default_end:
@family_command:
    db 23,0,0A0h
    dw 1732
    db 49h,39
@family_end:

show_launch_error:
    call reset_text_screen
    ld hl,launch_error_text
    call print_string
    ld a,(last_error)
    cp 1
    jr z,@directory
    cp 2
    jr z,@load
    ld hl,entry_error_text
    jr @detail
@directory:
    ld hl,directory_error_text
    jr @detail
@load:
    ld hl,load_error_text
@detail:
    call print_string
    ld hl,status_text
    call print_string
    ld a,(last_mos_status)
    call print_hex_byte
    ld a,')'
    rst.lil 10h
    call print_newline
    ld hl,continue_text
    call print_string
    MOSCALL mos_getkey
    call wait_for_keys_released
    ret

reset_text_screen:
    ld a,22
    rst.lil 10h
    xor a
    rst.lil 10h
    ld a,23
    rst.lil 10h
    ld a,1
    rst.lil 10h
    ld a,1
    rst.lil 10h
    ld a,12
    rst.lil 10h
    ret

print_string:
    ld a,(hl)
    or a
    ret z
    rst.lil 10h
    inc hl
    jr print_string

print_newline:
    ld a,13
    rst.lil 10h
    ld a,10
    rst.lil 10h
    ret

print_hex_byte:
    push af
    rrca
    rrca
    rrca
    rrca
    call print_hex_nibble
    pop af
print_hex_nibble:
    and 0Fh
    add a,'0'
    cp '9'+1
    jr c,@emit
    add a,'A'-'9'-1
@emit:
    rst.lil 10h
    ret

config_filename:
    db "/mos/fsim.cfg",0
empty_arguments:
    db 0

entry_signature:
    db 0C3h,045h,000h,004h
entry_signature_end:
header_signature:
    db "MOS",0,1
header_signature_end:

menu_text:
    db "Pingo Terrain Flight Simulator",13,10
    db "================================",13,10,13,10
    db "1  Rectangular Berkeley - original embedded-grid free flight",13,10
    db "2  Triangular Berkeley  - self-lit continuous triangular terrain",13,10
    db "3  Dithered Berkeley    - scene-lit flat-pattern terrain",13,10
    db "4  Berkeley Light Flight - cockpit and deterministic dynamics",13,10
    db "5  KOAK Streamed        - runway 28L and loose terrain records",13,10
    db "6  KOAK Family LOD      - nested-family mixed-LOD handoff",13,10
    db "7  P3DM Loader Probe    - publish one loose terrain record",13,10
    db "8  Nested AGNB Probe    - select from a ten-record family",13,10
    db "9  Campanile Probe      - streamed solid-flat Sather Tower",13,10
    db "0  Hex Manager Survey  - regular N=5 terrain, live rings 0-5",13,10
    db "N  Natural Survey      - full-region post-partition terrain, rings 0-5",13,10
    db "D  Distance LOD        - natural ring 5 plus regular terrain to ring 30",13,10
    db "R  Regular LOD         - position-driven N5 near and regular terrain to ring 30",13,10,13,10
    db "Press 1-9, 0, N, D, or R to launch; Esc returns to MOS.",13,10,0

exit_text:
    db "FSIM returned to MOS.",13,10,0
cwd_error_text:
    db "FSIM: unable to read the current directory.",13,10,0
config_error_text:
    db "FSIM: /mos/fsim.cfg must contain one absolute fixture root.",13,10,0
restore_error_text:
    db "FSIM: unable to restore the original working directory.",13,10,0
launch_error_text:
    db "FSIM could not launch that fixture: ",0
directory_error_text:
    db "directory change failed",0
load_error_text:
    db "executable load failed",0
entry_error_text:
    db "common entry/header validation failed",0
status_text:
    db " (MOS status 0x",0
continue_text:
    db "Press any key to return to the fixture menu.",13,10,0

fixture_records:
    db "fixtures/berkeley-flight/tgt",0
    db "berkeley-flight.bin",0
    db "fixtures/berkeley-flight-triangular/tgt",0
    db "berkeley-flight-triangular.bin",0
    db "fixtures/berkeley-flight-triangular-dither/tgt",0
    db "berkeley-flight-triangular-dither.bin",0
    db "fixtures/berkeley-flight-fdm/tgt",0
    db "berkeley-flight-fdm.bin",0
    db "build/p3dm/bay-area-koak-proof",0
    db "P3DFSIM.BIN",0
    db "build/p3dm/bay-area-koak-family-proof",0
    db "P3DLOD.BIN",0
    db "fixtures/p3dm-loader-probe/tgt",0
    db "p3dm-loader-probe.bin",0
    db "fixtures/nested-agnb-loader-probe/tgt",0
    db "nested-agnb-loader-probe.bin",0
    db "fixtures/campanile-p3dm-probe/tgt",0
    db "CAMPTEST.BIN",0
    db "build/p3dm/bay-area-hex-full-l0",0
    db "P3DHXMG.BIN",0
    db "build/p3dm/bay-area-natural-full-l0",0
    db "P3DNAT.BIN",0
    db "build/p3dm/bay-area-distance-lod-control",0
    db "P3DDST.BIN",0
    db "build/p3dm/bay-area-regular-n1-hierarchy",0
    db "P3DRGL.BIN",0

selected_index:
    db 0
last_error:
    db 0
last_mos_status:
    db 0
config_handle:
    db 0
config_root:
    blkb config_root_max+1,0
saved_current_directory:
    blkb path_buffer_bytes,0
path_buffer:
    blkb path_buffer_bytes,0
