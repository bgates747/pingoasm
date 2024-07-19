model_vertices_n: equ 8
model_indices_n: equ 36
model_uvs_n: equ 24
model_texture_width: equ 34
model_texture_height: equ 34
model_texture_size: equ model_texture_width*model_texture_height*4

; -- VERTICES --
model_vertices:
	dw -32767, 32767, 32767
	dw -32767, -32767, 32767
	dw -32767, 32767, -32767
	dw -32767, -32767, -32767
	dw 32767, 32767, 32767
	dw 32767, -32767, 32767
	dw 32767, 32767, -32767
	dw 32767, -32767, -32767

; -- FACE VERTEX INDICES --
model_vertex_indices:
	dw 2, 1, 0
	dw 6, 3, 2
	dw 4, 7, 6
	dw 0, 5, 4
	dw 0, 6, 2
	dw 5, 3, 7
	dw 2, 3, 1
	dw 6, 7, 3
	dw 4, 5, 7
	dw 0, 1, 5
	dw 0, 4, 6
	dw 5, 1, 3

; -- TEXTURE UV COORDINATES --
model_uvs:
	dw 351, 64984
	dw 22108, 43227
	dw 22108, 64984
	dw 351, 43546
	dw 22108, 21789
	dw 22108, 43546
	dw 43227, 22108
	dw 64984, 351
	dw 64984, 22108
	dw 43227, 43546
	dw 64984, 21789
	dw 64984, 43546
	dw 43227, 43227
	dw 64984, 64984
	dw 43227, 64984
	dw 22108, 22108
	dw 351, 351
	dw 22108, 351
	dw 351, 43227
	dw 351, 21789
	dw 43227, 351
	dw 43227, 21789
	dw 64984, 43227
	dw 351, 22108

; -- TEXTURE VERTEX INDICES --
model_uv_indices:
	dw 0, 1, 2
	dw 3, 4, 5
	dw 6, 7, 8
	dw 9, 10, 11
	dw 12, 13, 14
	dw 15, 16, 17
	dw 0, 18, 1
	dw 3, 19, 4
	dw 6, 20, 7
	dw 9, 21, 10
	dw 12, 22, 13
	dw 15, 23, 16

model_texture: db "blenderaxes.rgba8",0
