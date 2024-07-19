from agonImages import img_to_rgba8
from PIL import Image as pil

def write_data(base_filename, vertices, faces, texture_coords, texture_vertex_indices, tgt_filepath, uv_texture_rgba8, img_size):
    # Write header data to the target file
    with open(tgt_filepath, 'w') as file:
        file.write(f'{base_filename}_vertices_n: equ {len(vertices)}\n')
        file.write(f'{base_filename}_indices_n: equ {len(faces) * 3}\n')
        file.write(f'{base_filename}_uvs_n: equ {len(texture_coords)}\n')

        with open(uv_texture_rgba8, 'rb') as img_file:
            img_data = img_file.read()
            img_width, img_height = img_size
            filesize = len(img_data)
            file.write(f'{base_filename}_texture_width: equ {img_width}\n')
            file.write(f'{base_filename}_texture_height: equ {img_height}\n')
            file.write(f'{base_filename}_texture_size: equ {filesize}\n')

        # Normalize vertices to [-1,1] if max(abs(coord)) > 1
        max_coord = max(max(abs(coord) for coord in vertex) for vertex in vertices)
        if max_coord > 1:
            vertices = [[coord / max_coord for coord in vertex] for vertex in vertices]
            scale_factor = 1 / max_coord
        else:
            scale_factor = 1

        # Write the model vertices
        file.write(f'\n; -- VERTICES --\n')
        file.write(f'{base_filename}_vertices:\n')
        for item in vertices:
            item = [round(coord * 32767) for coord in item]
            file.write(f'\tdw {", ".join(map(str, item))}\n')

        # Write the face vertex indices
        file.write(f'\n; -- FACE VERTEX INDICES --\n')
        file.write(f'{base_filename}_vertex_indices:\n')
        for item in faces:
            file.write(f'\tdw {", ".join(map(str, item))}\n')

        # Write the texture UV coordinates with rounding
        file.write(f'\n; -- TEXTURE UV COORDINATES --\n')
        file.write(f'{base_filename}_uvs:\n')
        for item in texture_coords:
            item = [round(coord * 65335) for coord in item]
            file.write(f'\tdw {", ".join(map(str, item))}\n')

        # Write the texture vertex indices
        file.write(f'\n; -- TEXTURE VERTEX INDICES --\n')
        file.write(f'{base_filename}_uv_indices:\n')
        for item in texture_vertex_indices:
            file.write(f'\tdw {", ".join(map(str, item))}\n')

        file.write(f'\n{base_filename}_texture: db "{uv_texture_rgba8}",0\n')
                    
def make_texture_rgba(uv_texture_png):
    uv_texture_rgba8 = uv_texture_png.replace('.png', '.rgba8')
    img = pil.open(uv_texture_png)
    img_size = img.size
    img_to_rgba8(img, uv_texture_rgba8)
    return img_size, uv_texture_rgba8

def sanitize_uv(coord):
    coord = round(coord, 6)
    if abs(coord) < 1e-6:
        coord = 0.0
    elif coord < 0:
        coord = 0.0
    return coord

def sanitize_coord(coord):
    coord = round(coord, 6)
    if abs(coord) < 1e-6:
        coord = 0.0
    return coord

def parse_obj_file(filepath):
    vertices = []
    faces = []
    texture_coords = []
    texture_vertex_indices = []

    with open(filepath, 'r') as file:
        for line in file:
            parts = line.strip().split()
            if not parts:
                continue
            if parts[0] == 'v':
                vertices.append([sanitize_coord(float(parts[1])), sanitize_coord(float(parts[2])), sanitize_coord(float(parts[3]))])
            elif parts[0] == 'vt':
                texture_coords.append([sanitize_uv(float(parts[1])), sanitize_uv(float(parts[2]))])
            elif parts[0] == 'f':
                face = []
                tex_indices = []
                for part in parts[1:]:
                    v, vt, _ = (part.split('/') + [None, None])[:3]
                    face.append(int(v) - 1)
                    if vt:
                        tex_indices.append(int(vt) - 1)
                faces.append(face)
                if tex_indices:
                    texture_vertex_indices.append(tex_indices)

    return vertices, faces, texture_coords, texture_vertex_indices


if __name__ == '__main__':
    src_dir = 'ez80/src/blender'
    tgt_dir = 'ez80/src/asm'
    blender_executable = '/Applications/Blender.app/Contents/MacOS/Blender'
    blender_local_prefs_path = None

    # base_filename, uv_texture_png
    do_these_things = [
        # ['cube', '2x2.png'],
        # ['sliced', '2x2.png'],
        # ['earthico', 'earthico160x76.png'],
        # ['earthico1', 'earthico160x76.png'],
        # ['earthico2', 'earthico160x76.png'],
        # ['heavytank', 'ferdinand.png'],
        # ['larasm', 'Lara.png'],
        ['Lara','Lara.png'],
        # ['glock', 'glock.png'],
    ]

    for thing in do_these_things:
        base_filename, uv_texture_png = thing
        tgt_filepath = f'{tgt_dir}/{base_filename}.asm'
        obj_filepath = f'{src_dir}/{base_filename}.obj'

        img_size, uv_texture_rgba8 = make_texture_rgba(f'{src_dir}/{uv_texture_png}')
        
        # Export the .obj file manually from Blender GUI

        # Parse the .obj file
        vertices, faces, texture_coords, texture_vertex_indices = parse_obj_file(obj_filepath)

        write_data(base_filename, vertices, faces, texture_coords, texture_vertex_indices, tgt_filepath, uv_texture_rgba8, img_size)

        print(f'Modified  code has been written to {tgt_filepath}')
