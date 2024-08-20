model_indices_n: equ 36
model_vertices_n: equ 8
model_uvs_n: equ 20
model_normals_n: equ 6
model_texture_width: equ 277
model_texture_height: equ 240
model_texture_size: equ 66480

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
	dw 0, 0
	dw 0, 65335
	dw 65335, 0
	dw 65335, 65335
	dw 0, 0
	dw 0, 65335
	dw 65335, 65335
	dw 65335, 0
	dw 0, 0
	dw 0, 65335
	dw 65335, 65335
	dw 65335, 65335
	dw 65335, 0
	dw 0, 65335
	dw 0, 0
	dw 0, 65335
	dw 65335, 0
	dw 0, 0
	dw 65335, 65335
	dw 65335, 0

; -- TEXTURE VERTEX INDICES --
model_uv_indices:
	dw 2, 5, 0
	dw 7, 15, 4
	dw 19, 9, 14
	dw 12, 1, 8
	dw 16, 1, 4
	dw 7, 13, 17
	dw 2, 6, 5
	dw 7, 18, 15
	dw 19, 11, 9
	dw 12, 3, 1
	dw 16, 10, 1
	dw 7, 3, 13

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

model_texture: db "trirainbow.rgba2",0
