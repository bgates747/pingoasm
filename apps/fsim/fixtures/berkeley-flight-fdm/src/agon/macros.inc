
; test the sign of UHL
; inputs: UHL obviously
; outputs: sign flag set if UHL is negative, zero flag set if UHL is zero
    MACRO SIGN_UHL
    add hl,de ; 1 cycle
    or a ; clear flags ; 1 cycle
    sbc hl,de ; 2 cycles
    ; 4 cycles total
    ENDMACRO

; test the sign of HL
; inputs: HL obviously
; outputs: sign flag set if HL is negative, zero flag set if HL is zero, ***hlu is zeroed***
    MACRO SIGN_HL
    add hl,de
    or a ; clear flags
    sbc.s hl,de ; 16-bit subtract so bit 7 of H is the sign. ***clears hlu***
    ENDMACRO

; test the 16-bit value of HL for zero
; inputs: HL
; outputs: zero flag set if HL is zero
; destroys: A
    MACRO ZERO_HL
    ld a,h
    or l
    ENDMACRO

; put the value in A into HLU
; affects: HLU
; destroys: nothing
; note: $ instead of @@ b/c anon labels deprecated in ez80asm
    MACRO A_TO_HLU
    xor a ; 1 cycle
    ld ($+8+1),hl ; 7 cycles
    ld ($+4+3),a ; 5 cycles
    ld hl,0x000000 ; 4 cycles
    ; 17 cycles total
    ENDMACRO

; alternative: https://discord.com/channels/1158535358624039014/1282290921815408681/1318315567102300220
; one cycle less but burns flags
    MACRO A_TO_HLU_ALT
    push hl ; 4 cycles
    ld hl,2 ; 4 cycles
    add hl,sp ; 1 cycle
    ld (hl),a ; 2 cycles
    pop hl ; 4 cycles
    ; 15 cycles total
    ENDMACRO

    MACRO HLU_MUL_256
    add hl,hl ; * 2
    add hl,hl ; * 4
    add hl,hl ; * 8
    add hl,hl ; * 16 
    add hl,hl ; * 32
    add hl,hl ; * 64
    add hl,hl ; * 128
    add hl,hl ; * 256
    ENDMACRO

; https://discord.com/channels/1158535358624039014/1282290921815408681/1317793870070812715
    MACRO SRL_UHL
    dec sp ; 1 cycle
    push hl ; 4 cycles
    inc sp ; 1 cycle
    pop hl ; 4 cycles
    inc hl ; 1 cycle
    dec.s hl ; 2 cycles <-- the .s sets hlu to zero (undocumented)
    ; 13 cycles total
    ENDMACRO

    MACRO printChar char
    LD A, char
    RST.LIL 10h
    ENDMACRO

; Simulated call to subroutine at HL
; inputs: HL pointing to the subroutine address plus whatever the called function expects
; outputs: whatever the subroutine does, including HL and BC
; destroys: only what the subroutine does, but always BC
    MACRO CALL_HL
    ld bc,$+6 ; Address of first instruction after the jump
    push bc ; which constitutes the return address
    jp (hl) ; Jump to the address in HL
    ENDMACRO

; Simulated call to subroutine at IX
; inputs: IX pointing to the subroutine address plus whatever the called function expects
; outputs: whatever the subroutine does, including IX and BC
; destroys: only what the subroutine does, but always BC
    MACRO CALL_IX
    ld bc,$+6 ; Address of first instruction after the jump
    push bc ; which constitutes the return address
    jp (ix) ; Jump to the address in IX
    ENDMACRO

; Simulated call to soubroutinte at IY
; inputs: IY pointing to the subroutine address plus whatever the called function expects
; outputs: whatever the subroutine does, including IY and BC
; destroys: only what the subroutine does, but always BC
    MACRO CALL_IY
    ld bc,$+6 ; Address of first instruction after the jump
    push bc ; which constitutes the return address
    jp (iy) ; Jump to the address in IY
    ENDMACRO

; put the value in HLU into A
; destroys: af
    MACRO HLU_TO_A
    dec sp ; 1 cycle
    push hl ; 4 cycles
    inc sp ; 1 cycle
    pop af ; 4 cycles
    ; 10 cycles total
    ENDMACRO

    MACRO PUSH_ALL
    ex af,af'
    exx
    push af
    push hl
    push bc
    push de

    ex af,af'
    exx
    push af
    push hl
    push bc
    push de
    push ix
    push iy
    ENDMACRO

    MACRO POP_ALL
    pop iy
    pop ix
    pop de
    pop bc
    pop hl
    pop af
    ex af,af'
    exx

    pop de
    pop bc
    pop hl
    pop af
    ex af,af'
    exx
    ENDMACRO

    ; load hl with the 16-bit value at addr
    MACRO LD_HL_mn addr
    ld hl,(addr)
    dec hl
    inc.s hl ; zeros hlu
    ENDMACRO

    ; load bc with the 16-bit value at addr
    MACRO LD_BC_mn addr
    ld bc,(addr)
    dec bc
    inc.s bc ; zeros bcu
    ENDMACRO

    ; load de with the 16-bit value at addr
    MACRO LD_DE_mn addr
    ld de,(addr)
    dec de
    inc.s de ; zeros deu
    ENDMACRO

    ; load ix with the 16-bit value at addr
    MACRO LD_IX_mn addr
    ld ix,(addr)
    dec ix
    inc.s ix ; zeros ixu
    ENDMACRO

    ; load iy with the 16-bit value at addr
    MACRO LD_IY_mn addr
    ld iy,(addr)
    dec iy
    inc.s iy ; zeros iyu
    ENDMACRO

    MACRO PRINT_UNPACK_F16 msg
        ld a,'S'
        rst.lil 0x10
        signF16UI
        call printHexA
        ld a,'E'
        rst.lil 0x10
        expF16UI
        call printHexA
        push hl
        call printInline
        asciz "Sig"
        pop hl
        push hl
        fracF16UI
        call printHexHL
        call printInline
        asciz msg,"\r\n"
        pop hl
    ENDMACRO

    MACRO PRINT_HL_HEX_BIN msg
        push bc
        push de
        push af
        push hl
        call printHLHexBin
        pop hl
        push hl
        call printInline
        asciz msg,"\r\n"
        pop hl
        pop af
        pop de
        pop bc
    ENDMACRO

    MACRO PRINT_A_HEX msg
        push bc
        push de
        push hl
        push af
        ld a,'0'
        rst.lil 0x10
        ld a,'x'
        rst.lil 0x10
        pop af
        push af
        call printHexA
        call printInline
        asciz "  ",msg,"\r\n"
        pop af
        pop hl
        pop de
        pop bc
    ENDMACRO

    MACRO PRINT_HL_HEX msg
        push bc
        push de
        push af
        push hl
        ld a,'0'
        rst.lil 0x10
        ld a,'x'
        rst.lil 0x10
        call printHexHL
        call printInline
        asciz msg,"\r\n"
        pop hl
        pop af
        pop de
        pop bc
    ENDMACRO

    MACRO PRINT_HL_F16 msg
        push bc
        push de
        push af
        push hl
        push ix
        push iy
        call f16_print
        call printString
        ld a,' '
        rst.lil 0x10
        call printInline
        asciz msg,"\r\n"
        pop iy
        pop ix
        pop hl
        pop af
        pop de
        pop bc
    ENDMACRO

    MACRO PRINT_UHL_HEX msg
        push bc
        push de
        push af
        push hl
        ld a,'0'
        rst.lil 0x10
        ld a,'x'
        rst.lil 0x10
        call printHexUHL
        call printInline
        asciz msg,"\r\n"
        pop hl
        pop af
        pop de
        pop bc
    ENDMACRO

    MACRO PRINT_AUHL_HEX msg
        push bc
        push af
        push hl
        push de
        push af
        ld a,'0'
        rst.lil 0x10
        ld a,'x'
        rst.lil 0x10
        pop af
        call printHexAUHL
        call printInline
        asciz msg,"\r\n"
        pop de
        pop hl
        pop af
        pop bc
    ENDMACRO

    MACRO PRINT_BC_HEX msg
        push bc
        push de
        push af
        push hl
        push bc
        pop hl
        ld a,'0'
        rst.lil 0x10
        ld a,'x'
        rst.lil 0x10
        call printHexHL
        call printInline
        asciz msg,"\r\n"
        pop hl
        pop af
        pop de
        pop bc
    ENDMACRO

    MACRO PRINT_DE_HEX msg
        push bc
        push de
        push af
        push hl
        ex de,hl
        ld a,'0'
        rst.lil 0x10
        ld a,'x'
        rst.lil 0x10
        call printHexHL
        call printInline
        asciz msg,"\r\n"
        pop hl
        pop af
        pop de
        pop bc
    ENDMACRO

    MACRO PRINT_HLDE_HEX msg
        push bc
        push de
        push af
        push hl
        ld a,'0'
        rst.lil 0x10
        ld a,'x'
        rst.lil 0x10
        call printHexHLDE
        call printInline
        asciz msg,"\r\n"
        pop hl
        pop af
        pop de
        pop bc
    ENDMACRO

    MACRO PRINT_DEHL_HEX msg
        push bc
        push de
        push af
        push hl
        ld a,'0'
        rst.lil 0x10
        ld a,'x'
        rst.lil 0x10
        call printHexDEHL
        call printInline
        asciz msg,"\r\n"
        pop hl
        pop af
        pop de
        pop bc
    ENDMACRO

    MACRO PRINT_AHL_HEX msg
        push bc
        push de
        push af
        push hl
        push af
        ld a,'0'
        rst.lil 0x10
        ld a,'x'
        rst.lil 0x10
        pop af
        call printHexAHL
        call printInline
        asciz msg,"\r\n"
        pop hl
        pop af
        pop de
        pop bc
    ENDMACRO

    MACRO PRINT_ADE_HEX msg
        push bc
        push de
        push af
        push hl
        push af
        ld a,'0'
        rst.lil 0x10
        ld a,'x'
        rst.lil 0x10
        pop af
        call printHexADE
        call printInline
        asciz msg,"\r\n"
        pop hl
        pop af
        pop de
        pop bc
    ENDMACRO

    MACRO DUMP_REGISTERS_HEX msg
        push de
        push af
        push hl
        call printInline
        asciz "\r\n",msg,"\r\n"
        pop hl
        pop af
        pop de
        call dumpRegistersHex
        ; call dumpFlags
    ENDMACRO