; create pingo control structure
    MACRO CCS SID, SCENE_WIDTH, SCENE_HEIGHT
    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    jp @end
@beg:
;   VDU 23,0, &A0, sid%; &49, 0, cstw%; csth%; Create Control Structure
    db 23,0,$A0
    dw SID 
    db $49,0
    dw SCENE_WIDTH
    dw SCENE_HEIGHT
@end:
    ENDMACRO

; DEFINE MESH VERTICES
    MACRO SV SID, MID, VERTICES, VERTICES_N
    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    jp @end
@beg:
;   VDU 23,0, &A0, sid%; &49, 1, mid%; VERTICES%; Define Mesh Vertices
    db 23,0,$A0
    dw SID
    db $49,1
    dw MID, VERTICES_N
@end:
    ld hl,VERTICES
    ld bc,VERTICES_N*6 ; 3 coordinates per vertex, 2 bytes per coordinate
    rst.lil $18
    ENDMACRO

; DEFINE MESH VERTEX INDICES
    MACRO SMVI SID, MID, VERTEX_INDICES, INDICES_N
    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    jp @end
@beg:
;   VDU 23,0, &A0, sid%; &49, 2, mid%; model_indices%; Set Mesh Vertex indices
    db 23,0,$A0
    dw SID
    db $49,2
    dw MID, INDICES_N
@end:
    ld hl,VERTEX_INDICES
    ld bc,INDICES_N*2 ; 2 bytes per index
    rst.lil $18
    ENDMACRO

; DEFINE OBJECT TEXTURE COORDINATES
    MACRO STC SID, OID, UVS, UVS_N
    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    jp @end
@beg:
;   VDU 23, 0, &A0, sid; &49, 3, oid; n; u0; v0; ... :  Define Object Texture Coordinates
    db 23,0,$A0
    dw SID
    db $49,3
    dw OID, UVS_N
@end:
    ld hl,UVS
    ld bc,UVS_N*4 ; 2 coordinates per uv, 2 bytes per coordinate
    rst.lil $18
    ENDMACRO

; SET OBJECT TEXTURE COORDINATE INDEXES
    MACRO STCI SID, OID, UV_INDICES, INDICES_N
    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    jp @end
@beg:
;   VDU 23, 0, &A0, sid; &49, 4, oid; n; i0; ... :  Set Object Texture Coordinate Indexes
    db 23,0,$A0
    dw SID
    db $49,4
    dw OID, INDICES_N
@end:
    ld hl,UV_INDICES
    ld bc,INDICES_N*2 ; 2 bytes per index
    rst.lil $18
    ENDMACRO

; DEFINE MESH NORMALS
    MACRO SN SID, MID, NORMALS, NORMALS_N
    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    jp @end
@beg:
;   VDU 23, 0, &A0, sid; &49, 129, mid; n; x0; y0; z0; ... :  Define Mesh Normals
    db 23,0,$A0
    dw SID
    db $49,129
    dw MID, NORMALS_N
@end:
    ld hl,NORMALS
    ld bc,NORMALS_N*6 ; 3 coordinates per normal, 2 bytes per coordinate
    rst.lil $18
    ENDMACRO

; SET MESH NORMAL INDEXES
    MACRO SMNI SID, MID, NORMAL_INDICES, INDICES_N
    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    jp @end
@beg:
;   VDU 23, 0, &A0, sid; &49, 130, mid; n; i0; ... :  Set Mesh Normal Indexes
    db 23,0,$A0
    dw SID
    db $49,130
    dw MID, INDICES_N
@end:
    ld hl,NORMAL_INDICES
    ld bc,INDICES_N*2 ; 2 bytes per index
    rst.lil $18
    ENDMACRO

; CREATE OBJECT
    MACRO CO SID, OID, MID, BMID
    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    jp @end
@beg:
;   VDU 23, 0, &A0, sid; &49, 5, oid; mid; bmid; :  Create Object
    db 23,0,$A0
    dw SID
    db $49,5
    dw OID
    dw MID
    dw BMID 
@end:
    ENDMACRO

; SET OBJECT XYZ SCALE FACTORS
    MACRO SO SID, OID, SCALEX, SCALEY, SCALEZ
    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    jp @end
@beg:
;   VDU 23, 0, &A0, sid%; &49, 9, oid%; scale; scale; scale; Set Object XYZ Scale Factors
    db 23,0,$A0
    dw SID
    db $49,9
    dw OID
    dw SCALEX
    dw SCALEY
    dw SCALEZ
@end:
    ENDMACRO

; CREATE RENDER TARGET BITMAP
    MACRO CTB BMID, SCENE_WIDTH, SCENE_HEIGHT
    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    jp @end
@beg:
;   VDU 23, 27, &20, bmid2% Select output bitmap
    db 23,27,$20
    dw BMID
;   VDU 23, 27, 2, cstw%; csth%; &0000; &00C0; Create solid color bitmap
    db 23,27,2
    dw SCENE_WIDTH
    dw SCENE_HEIGHT
    dw $0000
    dw $00C0
@end:
    ENDMACRO

; RENDER TO TARGET BITMAP
    MACRO RENDBMP SID, BMID
    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    jp @end
@beg:
;  1040 VDU 23, 0, &A0, sid%; &49, 38, bmid%; Render To Bitmap
    db 23, 0, $A0
    dw SID
    db $49, 38
    dw BMID
@end:
    ENDMACRO

; DISPLAY RENDER TARGET BITMAP
    MACRO DISPBMP BMID, X, Y
    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    jp @end
@beg:
;   VDU 23, 27, &20, bmid% Select output bitmap
    db 23,27,$20
    dw BMID
;   VDU 23, 27, 3, 0; 0; Display output bitmap
    db 23,27,3 
    dw X,Y
@end:
    ENDMACRO

; set pingo camera distance
; inputs: bc distx, de disty, iy distz
scdabs:
    ld (@x),bc
    ld (@y),de
    ld (@z),iy
    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    ret
@beg:
;   360 VDU 23,0, &A0, sid%; &49, 25, distx; disty; distz; Set Camera XYZ Translation Distances
    db 23,0,$A0
    dw sid
    db $49,25
@x: dw 0x0000
@y: dw 0x0000
@z: dw 0x0000
@end: db 0x00 ; padding

; set pingo camera rotation angkes
; inputs: bc anglex, de angley, iy anglez
scrabs:
    ld (@rx),bc
    ld (@ry),de
    ld (@rz),iy
    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    ret
@beg:
; VDU 23, 0, &A0, sid; &49, 21, anglex; angley; anglez; : Set Camera XYZ Rotation Angles
        db 23,0,$A0
        dw sid
        db $49,18
@rx:    dw 0x0000
@ry:    dw 0x0000
@rz:    dw 0x0000
@end:   db 0x00 ; padding

; set pingo object distance
; inputs: hl oid, bc distx, de disty, iy distz
sodabs:
    ld (@oid),hl
    ld (@x),bc
    ld (@y),de
    ld (@z),iy
    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    ret
@beg:
; VDU 23, 0, &A0, sid; &49, 17, oid; distx; disty; distz; : Set Object XYZ Translation Distances
        db 23, 0, $A0
        dw sid
        db $49, 17
@oid:   dw 0
@x:     dw 0
@y:     dw 0
@z:     dw 0
@end:   db 0 ; padding

; set pingo object rotation angkes
; inputs: hl oid, bc anglex, de angley, iy anglez
sorabs:
    ld (@oid),hl
    ld (@rx),bc
    ld (@ry),de
    ld (@rz),iy
    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    ret
@beg:
;  1120 VDU 23, 0, &A0, sid%; &49, 13, oid%; rx; ry; rz; Set Object XYZ Rotation Angles
        db 23, 0, $A0
        dw sid
        db $49, 13
@oid:   dw 0
@rx:    dw 0
@ry:    dw 0
@rz:    dw 0
@end:   db 0 ; padding

; set pingo camera distance relative
; inputs: bc distx, de disty, iy distz
scdrel:
    ld (@x),bc
    ld (@y),de
    ld (@z),iy
    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    ret
@beg:
;   360 VDU 23,0, &A0, sid%; &49, 153, distx; disty; distz; Set Camera XYZ Translation Distances Relative
    db 23,0,$A0
    dw sid
    db $49,153
@x: dw 0x0000
@y: dw 0x0000
@z: dw 0x0000
@end: db 0x00 ; padding

; set pingo camera rotation angkes relative
; inputs: bc anglex, de angley, iy anglez
scrrel:
    ld (@rx),bc
    ld (@ry),de
    ld (@rz),iy
    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    ret
@beg:
; VDU 23, 0, &A0, sid; &49, 149, anglex; angley; anglez; : Set Camera XYZ Rotation Angles Relative
        db 23,0,$A0
        dw sid
        db $49,149
@rx:    dw 0x0000
@ry:    dw 0x0000
@rz:    dw 0x0000
@end:   db 0x00 ; padding

; VDU 23, 0, &A0, sid; &49, 42, oid; : Rotate Camera Locally to track a specified object
; inputs: hl oid
cto:
    ld (@oid),hl
    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    ret
@beg:
    db 23, 0, $A0
    dw sid
    db $49, 42
@oid:   dw 0
@end:   db 0 ; padding

; set pingo object distance
; inputs: hl oid, bc distx, de disty, iy distz
sodrel:
    ld (@oid),hl
    ld (@x),bc
    ld (@y),de
    ld (@z),iy
    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    ret
@beg:
; VDU 23, 0, &A0, sid; &49, 145, oid; distx; disty; distz; : Set Object XYZ Translation Distances Relative
        db 23, 0, $A0
        dw sid
        db $49, 145
@oid:   dw 0
@x:     dw 0
@y:     dw 0
@z:     dw 0
@end:   db 0 ; padding

; set pingo object rotation angkes
; inputs: hl oid, bc anglex, de angley, iy anglez
sorrel:
    ld (@oid),hl
    ld (@rx),bc
    ld (@ry),de
    ld (@rz),iy
    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    ret
@beg:
;  1120 VDU 23, 0, &A0, sid%; &49, 141, oid%; rx; ry; rz; Set Object XYZ Rotation Angles Relative
        db 23, 0, $A0
        dw sid
        db $49, 141
@oid:   dw 0
@rx:    dw 0
@ry:    dw 0
@rz:    dw 0
@end:   db 0 ; padding

cycle_dithering:
    ld a,(dithering_type)
    inc a
    cp 3
    jr nz,@set
    xor a
@set:
    ld (dithering_type),a
; fall through to vdu_set_dither

; set dithering type
; inputs: a = dithering type/optons
; dithering types bits 0-1: 00 none (default), 01 bayer ordered matrix, 10 floyd-steinberg
vdu_set_dither:
; VDU 23, 0, &A0, sid; &49, 41, type
    ld (@dt),a
    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    ret
@beg:
        db 23,0,$A0
        dw sid
        db $49,41
@dt:    db 0x00
@end:

move_object_abs:
    call printNewLine

    ld hl,(objx)
    ld de,(objdx)
    add hl,de
    ld (@x),hl
    ld (objx),hl
    call printDec

    ld hl,(objy)
    ld de,(objdy)
    add hl,de
    ld (@y),hl
    ld (objy),hl
    call printDec

    ld hl,(objz)
    ld de,(objdz)
    add hl,de
    ld (@z),hl
    ld (objz),hl
    call printDec

    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    ret
@beg:
; VDU 23, 0, &A0, sid; &49, 17, oid; distx; disty; distz; : Set Object XYZ Translation Distances
        db 23, 0, $A0
        dw sid
        db $49, 17
        dw oid
@x:     dw 0
@y:     dw 0
@z:     dw 0
@end:   db 0 ; padding

rotate_object_abs:
;  1080 objrx=objrx+objdrx: IF objrx>=pi2 THEN objrx=objrx-pi2
    ld hl,(objrx)
    ld de,(objdrx)
    add hl,de
    ld (@rx),hl
    ld (objrx),hl
    call printDec
;  1090 objry=objry+objdry: IF objry>=pi2 THEN objry=objry-pi2
    ld hl,(objry)
    ld de,(objdry)
    add hl,de
    ld (@ry),hl
    ld (objry),hl
    call printDec
;  1100 objrz=objrz+objdrz: IF objrz>=pi2 THEN objrz=objrz-pi2
    ld hl,(objrz)
    ld de,(objdrz)
    add hl,de
    ld (@rz),hl
    ld (objrz),hl
    call printDec

    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    ret
@beg:
;  1120 VDU 23, 0, &A0, sid%; &49, 13, oid%; rx; ry; rz; Set Object XYZ Rotation Angles
        db 23, 0, $A0
        dw sid
        db $49, 13
        dw oid
@rx:    dw 0
@ry:    dw 0
@rz:    dw 0
@end:   db 0 ; padding

rotate_camera_abs:
    call printNewLine

;  1080 camrx=camrx+camdrx: IF camrx>=pi2 THEN camrx=camrx-pi2
    ld hl,(camrx)
    ld de,(camdrx)
    add hl,de
    ld (@rx),hl
    ld (camrx),hl
    call printDec
;  1090 camry=camry+camdry: IF camry>=pi2 THEN camry=camry-pi2
    ld hl,(camry)
    ld de,(camdry)
    add hl,de
    ld (@ry),hl
    ld (camry),hl
    call printDec
;  1100 camrz=camrz+camdrz: IF camrz>=pi2 THEN camrz=camrz-pi2
    ld hl,(camrz)
    ld de,(camdrz)
    add hl,de
    ld (@rz),hl
    ld (camrz),hl
    call printDec

    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    ret
@beg:
; VDU 23, 0, &A0, sid; &49, 21, anglex; angley; anglez; : Set Camera XYZ Rotation Angles
        db 23, 0, $A0
        dw sid
        db $49, 21
@rx:    dw 0
@ry:    dw 0
@rz:    dw 0
@end:   db 0 ; padding

move_camera_abs:
    call printNewLine

    ld hl,(camx)
    ld de,(camdx)
    add hl,de
    ld (@x),hl
    ld (camx),hl
    call printDec

    ld hl,(camy)
    ld de,(camdy)
    add hl,de
    ld (@y),hl
    ld (camy),hl
    call printDec

    ld hl,(camz)
    ld de,(camdz)
    add hl,de
    ld (@z),hl
    ld (camz),hl
    call printDec

    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    ret
@beg:
;   VDU 23, 0, &A0, sid; &48, 25; distx; disty; distz :  Set Camera XYZ Translation Distances
        db 23, 0, $A0
        dw sid
        db $49, 25
@x:     dw 0
@y:     dw 0
@z:     dw 0
@end:   db 0 ; padding


move_object_loc:
    call printNewLine

    ld hl,(objx)
    ld de,(objdx)
    add hl,de
    ld (@x),de
    ld (objx),hl
    call printDec

    ld hl,(objy)
    ld de,(objdy)
    add hl,de
    ld (@y),de
    ld (objy),hl
    call printDec

    ld hl,(objz)
    ld de,(objdz)
    add hl,de
    ld (@z),de
    ld (objz),hl
    call printDec

    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    ret
@beg:
; VDU 23, 0, &A0, sid; &49, 145, oid; distx; disty; distz :  Set Object XYZ Translation Distances
        db 23, 0, $A0
        dw sid
        db $49, 145
        dw oid
@x:     dw 0
@y:     dw 0
@z:     dw 0
@end:   db 0 ; padding

rotate_object_loc:
;  1080 objrx=objrx+objdrx: IF objrx>=pi2 THEN objrx=objrx-pi2
    ld hl,(objrx)
    ld de,(objdrx)
    add hl,de
    ld (@rx),de
    ld (objrx),hl
    call printDec
;  1090 objry=objry+objdry: IF objry>=pi2 THEN objry=objry-pi2
    ld hl,(objry)
    ld de,(objdry)
    add hl,de
    ld (@ry),de
    ld (objry),hl
    call printDec
;  1100 objrz=objrz+objdrz: IF objrz>=pi2 THEN objrz=objrz-pi2
    ld hl,(objrz)
    ld de,(objdrz)
    add hl,de
    ld (@rz),de
    ld (objrz),hl
    call printDec

    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    ret
@beg:
; VDU 23, 0, &A0, sid; &49, 141, oid; anglex; angley; anglez; :  Set Object XYZ Rotation Angles Local
        db 23, 0, $A0
        dw sid
        db $49, 141
        dw oid
@rx:    dw 0
@ry:    dw 0
@rz:    dw 0
@end:   db 0 ; padding

rotate_camera_loc:
    call printNewLine

    ld hl,(camrx)
    ld de,(camdrx)
    add hl,de
    ld (@rx),de
    ld (camrx),hl
    call printDec

    ld hl,(camry)
    ld de,(camdry)
    add hl,de
    ld (@ry),de
    ld (camry),hl
    call printDec

    ld hl,(camrz)
    ld de,(camdrz)
    add hl,de
    ld (@rz),de
    ld (camrz),hl
    call printDec

    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    ret
@beg:
; VDU 23, 0, &A0, sid; &49, 149; anglex; angley; anglez; :  Set Camera XYZ Rotation Angles (Local)
        db 23, 0, $A0
        dw sid
        db $49, 149
@rx:    dw 0
@ry:    dw 0
@rz:    dw 0
@end:   db 0 ; padding

move_camera_loc:
    call printNewLine

    ld hl,(camx)
    ld de,(camdx)
    add hl,de
    ld (@x),de
    ld (camx),hl
    call printDec

    ld hl,(camy)
    ld de,(camdy)
    add hl,de
    ld (@y),de
    ld (camy),hl
    call printDec

    ld hl,(camz)
    ld de,(camdz)
    add hl,de
    ld (@z),de
    ld (camz),hl
    call printDec

    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    ret
@beg:
;   VDU 23, 0, &A0, sid; &49, 153, distx; disty; distz :  Set Camera XYZ Translation Distances (Local)
        db 23, 0, $A0
        dw sid
        db $49, 153
@x:     dw 0
@y:     dw 0
@z:     dw 0
@end:   db 0 ; padding

; https://github.com/envenomator/Agon/blob/master/ez80asm%20examples%20(annotated)/functions.s
; Print a zero-terminated string
; HL: Pointer to string
printString:
	PUSH	BC
	LD		BC,0
	LD 	 	A,0
	RST.LIL 18h
	POP		BC
	RET
; print a VDU sequence
; HL: Pointer to VDU sequence - <1 byte length> <data>
sendVDUsequence:
	PUSH	BC
	LD		BC, 0
	LD		C, (HL)
	RST.LIL	18h
	POP		BC
	RET
; Print Newline sequence to VDP
printNewLine:
	LD	A, '\r'
	RST.LIL 10h
	LD	A, '\n'
	RST.LIL 10h
	RET
; Print a 24-bit HEX number
; HLU: Number to print
printHex24:
	PUSH	HL
	LD		HL, 2
	ADD		HL, SP
	LD		A, (HL)
	POP		HL
	CALL	printHex8
; Print a 16-bit HEX number
; HL: Number to print
printHex16:
	LD		A,H
	CALL	printHex8
	LD		A,L
; Print an 8-bit HEX number
; A: Number to print
printHex8:
	LD		C,A
	RRA 
	RRA 
	RRA 
	RRA 
	CALL	@F
	LD		A,C
@@:
	AND		0Fh
	ADD		A,90h
	DAA
	ADC		A,40h
	DAA
	RST.LIL	10h
	RET

; Print a 0x HEX prefix
DisplayHexPrefix:
	LD	A, '0'
	RST.LIL 10h
	LD	A, 'x'
	RST.LIL 10h
	RET

; Prints the right justified decimal value in HL without leading zeroes
; HL : Value to print
printDec:
	LD	 DE, _printDecBuffer
	CALL Num2String
; BEGIN MY CODE
; replace leading zeroes with spaces
    LD	 HL, _printDecBuffer
    ld   B, 7 ; if HL was 0, we want to keep the final zero 
@loop:
    LD	 A, (HL)
    CP	 '0'
    JP	 NZ, @done
    LD   A, ' '
    LD	 (HL), A
    INC	 HL
    CALL vdu_cursor_forward
    DJNZ @loop
@done:
; END MY CODE
	; LD	 HL, _printDecBuffer
	CALL printString
	RET
_printDecBuffer: blkb 9,0 ; nine bytes full of zeroes

; This routine converts the value from HL into it's ASCII representation, 
; starting to memory location pointing by DE, in decimal form and with leading zeroes 
; so it will allways be 8 characters length
; HL : Value to convert to string
; DE : pointer to buffer, at least 8 byte + 0
Num2String:
	LD	 BC,-10000000
	CALL OneDigit
	LD	 BC,-1000000
	CALL OneDigit
	LD	 BC,-100000
	CALL OneDigit
	LD   BC,-10000
	CALL OneDigit
	LD   BC,-1000
	CALL OneDigit
	LD   BC,-100
	CALL OneDigit
	LD   C,-10
	CALL OneDigit
	LD   C,B
OneDigit:
	LD   A,'0'-1
DivideMe:
	INC  A
	ADD  HL,BC
	JR   C,DivideMe
	SBC  HL,BC
	LD   (DE),A
	INC  DE
	RET

; wait until user presses a key
; inputs: none
; outputs: none
; destroys: af,hl,ix
waitKeypress:
    ; ld hl,str_press_shift
    ; call printString
    MOSCALL mos_sysvars
    xor a ; zero out any prior keypresses
    ld (ix+sysvar_keyascii),a
@loop:
    ld a,(ix+sysvar_keyascii)
    and a
    ret nz
    jr @loop

cursor_on:
	ld hl,@cmd
	ld bc,@end-@cmd
	rst.lil $18
	ret
@cmd:
	db 23,1,1
@end:

cursor_off:	
	ld hl,@cmd
	ld bc,@end-@cmd
	rst.lil $18
	ret
@cmd:
	db 23,1,0
@end:

; VDU 9: Move cursor forward one character
vdu_cursor_forward:
    ld a,9
	rst.lil $10  
	ret


; VDU 12: Clear text area (CLS)
vdu_cls:
    ld a,12
	rst.lil $10  
	ret

vdu_flip:       
	ld hl,@cmd         
	ld bc,@end-@cmd    
	rst.lil $18         
	ret
@cmd: db 23,0,0xC3
@end:

vdu_vblank:		PUSH 	IX			; Wait for VBLANK interrupt
			MOSCALL	mos_sysvars		; Fetch pointer to system variables
			LD	A, (IX + sysvar_time + 0)
@wait:			CP 	A, (IX + sysvar_time + 0)
			JR	Z, @wait
			POP	IX
			RET

; load an image file to a buffer and make it a bitmap
; inputs: a = image type ; bc,de image width,height ; hl = bufferId ; ix = file size ; iy = pointer to filename
vdu_load_img:
; back up image type and dimension parameters
    push af
	push bc
	push de
    push hl
; set parameters for vdu call
    ld (@bufferId),hl
    ld a,14
    ld (@bufferId+2),a
; load the image
	call vdu_load_buffer_from_file
; now make it a bitmap
; Command 14: Consolidate blocks in a buffer
; VDU 23, 0, &A0, bufferId; 14
    ld hl,@beg
    ld bc,@end-@beg
    rst.lil $18
    jp @end
@beg:
    db 23,0,0xA0
@bufferId: dw 0x0000
        db 14
@end:
    pop hl ; restore bufferId
    call vdu_buff_select
	pop de ; image height
	pop bc ; image width
	pop af ; image type
	jp vdu_bmp_create ; will return to caller from there

vdu_set_screen_mode:
	ld (@arg),a        
	ld hl,@cmd         
	ld bc,@end-@cmd    
	rst.lil $18         
	ret
@cmd: db 22 ; set screen mode
@arg: db 0  ; screen mode parameter
@end:

; VDU 23, 0, &C0, n: Turn logical screen scaling on and off *
; inputs: a is scaling mode, 1=on, 0=off
; note: default setting on boot is scaling ON
vdu_set_scaling:
	ld (@arg),a        
	ld hl,@cmd         
	ld bc,@end-@cmd    
	rst.lil $18         
	ret
@cmd: db 23,0,0xC0
@arg: db 0  ; scaling on/off
@end: 

; VDU 23, 27, &20, bufferId; : Select bitmap (using a buffer ID)
; inputs: hl=bufferId
vdu_buff_select:
	ld (@bufferId),hl
	ld hl,@cmd
	ld bc,@end-@cmd
	rst.lil $18
	ret
@cmd: db 23,27,0x20
@bufferId: dw 0x0000
@end: db 0x00 ; padding

; VDU 23, 27, &21, w; h; format: Create bitmap from selected buffer
; inputs: a=format; bc=width; de=height
; prerequisites: buffer selected by vdu_bmp_select or vdu_buff_select
; formats: https://agonconsole8.github.io/agon-docs/VDP---Bitmaps-API.html
; 0 	RGBA8888 (4-bytes per pixel)
; 1 	RGBA2222 (1-bytes per pixel)
; 2 	Mono/Mask (1-bit per pixel)
; 3 	Reserved for internal use by VDP (“native” format)
vdu_bmp_create:
    ld (@width),bc
    ld (@height),de
    ld (@fmt),a
	ld hl,@cmd
	ld bc,@end-@cmd
	rst.lil $18
	ret
@cmd:       db 23,27,0x21
@width:     dw 0x0000
@height:    dw 0x0000
@fmt:       db 0x00
@end:

; &E8-&EF 	232-239 	Bitmap plot §
plot_bmp: equ 0xE8
; 5 	Plot absolute in current foreground colour
dr_abs_fg: equ 5

; https://agonconsole8.github.io/agon-docs/VDP---PLOT-Commands.html
; &E8-&EF 	232-239 	Bitmap plot §
; VDU 25, mode, x; y;: PLOT command
; inputs: bc=x0, de=y0
; prerequisites: vdu_buff_select
vdu_plot_bmp:
    ld (@x0),bc
    ld (@y0),de
	ld hl,@cmd
	ld bc,@end-@cmd
	rst.lil $18
	ret
@cmd:   db 25
@mode:  db plot_bmp+dr_abs_fg ; 0xED
@x0: 	dw 0x0000
@y0: 	dw 0x0000
@end:   db 0x00 ; padding

; inputs: hl = bufferId, ix = file size ; iy = pointer to filename
vdu_load_buffer_from_file:
; load buffer ids
    ld (@id0),hl
    ld (@id1),hl
; clean up bytes that got stomped on by the ID loads
    ld a,2
    ld (@id0+2),a
    xor a
    ld (@id1+2),a
; load filesize from ix
    ld (@filesize),ix
    ld bc,(@filesize) ; for the mos_load call
; load the file from disk into ram
    push iy
	pop hl ; pointer to filename
	ld de,filedata
	ld a,mos_load
	RST.LIL 08h
; clear target buffer
    ld hl,@clear0
    ld bc,@clear1-@clear0
    rst.lil $18
    jp @clear1
@clear0: db 23,0,0xA0
@id0:	dw 0x0000 ; bufferId
		db 2 ; clear buffer
@clear1:
; load default chunk size of 256 bytes
    xor a
    ld (@chunksize),a
    ld a,1
    ld (@chunksize+1),a
; point hl at the start of the file data
    ld hl,filedata
    ld (@chunkpointer),hl
@loop:
    ld hl,(@filesize) ; get the remaining bytes
    ld de,256
    xor a ; clear carry
    sbc hl,de
    ld (@filesize),hl ; store remaining bytes
    jp z,@loadchunk ; jp means will return to caller from there
    jp m,@lastchunk ; ditto
    call @loadchunk ; load the next chunk and return here to loop again
    jp @loop ; loop back to load the next chunk
@lastchunk:
    ld de,256
    add hl,de
    ld a,l
    ld (@chunksize),a ; store the remaining bytes
    ld a,h
    ld (@chunksize+1),a
    ; fall through to loadchunk
@loadchunk:
    ld hl,@chunk0
    ld bc,@chunk1-@chunk0
    rst.lil $18
    jp @chunk1
@chunk0:
; Upload data :: VDU 23, 0 &A0, bufferId; 0, length; <buffer-data>
		db 23,0,0xA0
@id1:	dw 0x0000 ; bufferId
		db 0 ; load buffer
@chunksize:	dw 0x0000 ; length of data in bytes
@chunk1:
    ld hl,(@chunkpointer) ; get the file data pointer
    ld bc,0 ; make sure bcu is zero
    ld a,(@chunksize)
    ld c,a
    ld a,(@chunksize+1)
    ld b,a
    rst.lil $18
    ld hl,(@chunkpointer) ; get the file data pointer
    ld bc,256
    add hl,bc ; advance the file data pointer
    ld (@chunkpointer),hl ; store pointer to file data
    ld a,'.' ; print a progress breadcrumb
    rst.lil 10h
    ret
@filesize: dl 0 ; file size in bytes
@chunkpointer: dl 0 ; pointer to current chunk