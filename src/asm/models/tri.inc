model_indices_n: equ 3
model_vertices_n: equ 3
model_uvs_n: equ 3
model_normals_n: equ 1
model_texture_width: equ 34
model_texture_height: equ 34
model_texture_size: equ 1156

; -- VERTICES --
model_vertices:
	dw -32767, -32767, 0
	dw -32767, 32767, 0
	dw 32767, 32767, 0

; -- FACE VERTEX INDICES --
model_vertex_indices:
	dw 2, 1, 0

; -- TEXTURE UV COORDINATES --
model_uvs:
	dw 43227, 21789
	dw 43227, 43546
	dw 64984, 43546

; -- TEXTURE VERTEX INDICES --
model_uv_indices:
	dw 2, 1, 0

; -- NORMALS --
model_normals:
	dw 0, 0, 32767

; -- NORMAL INDICES --
model_normal_indices:
	dw 0, 0, 0

model_texture: db "blenderaxes.rgba2",0
