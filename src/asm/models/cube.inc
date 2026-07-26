model_indices_n: equ 36
model_vertices_n: equ 8
model_uvs_n: equ 24
model_normals_n: equ 6
model_texture_width: equ 34
model_texture_height: equ 34
model_texture_size: equ 1156

; -- VERTICES --
model_vertices:
	dw -32767, -32767, 32767
	dw -32767, 32767, 32767
	dw -32767, -32767, -32767
	dw -32767, 32767, -32767
	dw 32767, -32767, 32767
	dw 32767, 32767, 32767
	dw 32767, -32767, -32767
	dw 32767, 32767, -32767

; -- FACE VERTEX INDICES --
model_vertex_indices:
	dw 1, 2, 0
	dw 3, 6, 2
	dw 7, 4, 6
	dw 5, 0, 4
	dw 6, 0, 2
	dw 3, 5, 7
	dw 1, 3, 2
	dw 3, 7, 6
	dw 7, 5, 4
	dw 5, 1, 0
	dw 6, 4, 0
	dw 3, 1, 5

; -- TEXTURE UV COORDINATES --
model_uvs:
	dw 22108, 351
	dw 43227, 21789
	dw 43227, 22108
	dw 22108, 22108
	dw 43227, 43546
	dw 351, 43227
	dw 22108, 21789
	dw 43227, 351
	dw 351, 351
	dw 351, 22108
	dw 22108, 43546
	dw 351, 64984
	dw 64984, 21789
	dw 43227, 43227
	dw 64984, 22108
	dw 43227, 64984
	dw 64984, 43546
	dw 22108, 43227
	dw 64984, 43227
	dw 351, 21789
	dw 64984, 351
	dw 22108, 64984
	dw 351, 43546
	dw 64984, 64984

; -- TEXTURE VERTEX INDICES --
model_uv_indices:
	dw 3, 8, 0
	dw 10, 19, 6
	dw 23, 13, 18
	dw 16, 1, 12
	dw 20, 2, 7
	dw 11, 17, 21
	dw 3, 9, 8
	dw 10, 22, 19
	dw 23, 15, 13
	dw 16, 4, 1
	dw 20, 14, 2
	dw 11, 5, 17

; -- NORMALS --
model_normals:
	dw -32767, 0, 0
	dw 0, 0, -32767
	dw 32767, 0, 0
	dw 0, 0, 32767
	dw 0, -32767, 0
	dw 0, 32767, 0

; -- NORMAL INDICES --
model_normal_indices:
	dw 0, 0, 0
	dw 1, 1, 1
	dw 2, 2, 2
	dw 3, 3, 3
	dw 4, 4, 4
	dw 5, 5, 5
	dw 0, 0, 0
	dw 1, 1, 1
	dw 2, 2, 2
	dw 3, 3, 3
	dw 4, 4, 4
	dw 5, 5, 5

model_texture: db "blenderaxes.rgba2",0
