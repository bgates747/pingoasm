model_indices_n: equ 6
model_vertices_n: equ 4
model_uvs_n: equ 4
model_normals_n: equ 1
model_texture_width: equ 256
model_texture_height: equ 256
model_texture_size: equ 65536

; -- VERTICES --
model_vertices:
	dw 32767, 32767, 0
	dw 32767, -32767, 0
	dw -32767, 32767, 0
	dw -32767, -32767, 0

; -- FACE VERTEX INDICES --
model_vertex_indices:
	dw 0, 3, 1
	dw 0, 2, 3

; -- TEXTURE UV COORDINATES --
model_uvs:
	dw 65335, 0
	dw 0, 0
	dw 65335, 65335
	dw 0, 65335

; -- TEXTURE VERTEX INDICES --
model_uv_indices:
	dw 0, 3, 1
	dw 0, 2, 3

; -- NORMALS --
model_normals:
	dw 0, 0, 32767

; -- NORMAL INDICES --
model_normal_indices:
	dw 0, 0, 0
	dw 0, 0, 0

model_texture: db "checkerboard.rgba2",0
