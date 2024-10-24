from agonImages import img_to_rgba2
from PIL import Image as pil
import os
import shutil

def write_data(base_filename, vertices, faces, texture_coords, texture_vertex_indices, normals, normal_indices, tgt_filepath, uv_texture_rgba2, img_size):
    # Write header data to the target file
    with open(tgt_filepath, 'w') as file:
        file.write(f'model_indices_n: equ {len(faces) * 3}\n')
        file.write(f'model_vertices_n: equ {len(vertices)}\n')
        file.write(f'model_uvs_n: equ {len(texture_coords)}\n')
        file.write(f'model_normals_n: equ {len(normals)}\n')

        with open(uv_texture_rgba2, 'rb') as img_file:
            img_data = img_file.read()
            img_width, img_height = img_size
            filesize = len(img_data)
            file.write(f'model_texture_width: equ {img_width}\n')
            file.write(f'model_texture_height: equ {img_height}\n')
            file.write(f'model_texture_size: equ {filesize}\n')

        # Normalize vertices to [-1,1] if max(abs(coord)) > 1
        max_coord = max(max(abs(coord) for coord in vertex) for vertex in vertices)
        if max_coord > 1:
            vertices = [[coord / max_coord for coord in vertex] for vertex in vertices]
            scale_factor = 1 / max_coord
        else:
            scale_factor = 1

        # Write the model vertices
        file.write(f'\n; -- VERTICES --\n')
        file.write(f'model_vertices:\n')
        for item in vertices:
            item = [round(coord * 32767) for coord in item]
            file.write(f'\tdw {", ".join(map(str, item))}\n')

        # Write the face vertex indices
        file.write(f'\n; -- FACE VERTEX INDICES --\n')
        file.write(f'model_vertex_indices:\n')
        for item in faces:
            file.write(f'\tdw {", ".join(map(str, item))}\n')

        # Write the texture UV coordinates with rounding
        file.write(f'\n; -- TEXTURE UV COORDINATES --\n')
        file.write(f'model_uvs:\n')
        for item in texture_coords:
            item = [round(coord * 65335) for coord in item]
            file.write(f'\tdw {", ".join(map(str, item))}\n')

        # Write the texture vertex indices
        file.write(f'\n; -- TEXTURE VERTEX INDICES --\n')
        file.write(f'model_uv_indices:\n')
        for item in texture_vertex_indices:
            file.write(f'\tdw {", ".join(map(str, item))}\n')

        # Write the normals
        file.write(f'\n; -- NORMALS --\n')
        file.write(f'model_normals:\n')
        for item in normals:
            item = [round(coord * 32767) for coord in item]
            file.write(f'\tdw {", ".join(map(str, item))}\n')

        # Write the normal indices
        file.write(f'\n; -- NORMAL INDICES --\n')
        file.write(f'model_normal_indices:\n')
        for item in normal_indices:
            file.write(f'\tdw {", ".join(map(str, item))}\n')

        file.write(f'\nmodel_texture: db "{os.path.basename(uv_texture_rgba2)}",0\n')

def make_texture_rgba(uv_texture_png):
    uv_texture_rgba2 = uv_texture_png.replace('.png', '.rgba2')
    img = pil.open(uv_texture_png)
    img_size = img.size
    img_to_rgba2(img, uv_texture_rgba2)
    return img_size, uv_texture_rgba2

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
    normals = []
    normal_indices = []

    with open(filepath, 'r') as file:
        for line in file:
            parts = line.strip().split()
            if not parts:
                continue
            if parts[0] == 'v':
                vertices.append([sanitize_coord(float(parts[1])), sanitize_coord(float(parts[2])), sanitize_coord(float(parts[3]))])
            elif parts[0] == 'vt':
                texture_coords.append([sanitize_uv(float(parts[1])), sanitize_uv(float(parts[2]))])
            elif parts[0] == 'vn':
                normals.append([sanitize_coord(float(parts[1])), sanitize_coord(float(parts[2])), sanitize_coord(float(parts[3]))])
            elif parts[0] == 'f':
                face = []
                tex_indices = []
                nor_indices = []
                for part in parts[1:]:
                    v, vt, vn = (part.split('/') + [None, None, None])[:3]
                    face.append(int(v) - 1)
                    if vt:
                        tex_indices.append(int(vt) - 1)
                    if vn:
                        nor_indices.append(int(vn) - 1)
                faces.append(face)
                if tex_indices:
                    texture_vertex_indices.append(tex_indices)
                if nor_indices:
                    normal_indices.append(nor_indices)

    return vertices, faces, texture_coords, texture_vertex_indices, normals, normal_indices

if __name__ == '__main__':
    src_dir = 'src/blender'
    build_dir = 'src/asm/build'
    blender_executable = '/Applications/Blender.app/Contents/MacOS/Blender'
    blender_local_prefs_path = None

    # base_filename, uv_texture_png
    do_these_things = [
        # ['viking_mod', 'viking.png'],
        ['heavytank', 'blenderaxes.png'],
        # ['navball', 'navball640x320.png'],
        ['LaraCroft', 'Lara.png'],
        ['wolf_map', 'wolf_tex.png'],
        ['crash', 'crashtex.png'],
        # ['ship', 'ship_1c.png'],
        # ['checkerboard', 'checkerboard.png'],
        # ['trirainbow', 'trirainbow.png'],
        # ['cow', 'checkerboard.png'],
        # ['middle_harbor_drone', 'middle_harbor.png'],
        # ['equirectangular', 'equirectangular.png'],
        # ['runway_numbers', 'pixel_white.png'],
        # ['t38', 't38.png'],
        ['jet', 'jet.png'],
        ['airliner', 'airliner.png'],
        ['koak', 'koak256dith.png'],
        ['manhattan', 'manhattan720x360dith.png'],
        ['cube', 'blenderaxes.png'],
        ['tri', 'blenderaxes.png'],
        ['earthuv', 'earthuv.png'],
        ['earthuvinv', 'earthuv.png'],
        ['cyl', 'earthuv.png'],
        ['koak28lr', 'blenderaxes.png'],
    ]

    # delete the build directory and recreate it
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)
    os.makedirs(build_dir)

    for thing in do_these_things:
        base_filename, uv_texture_png = thing
        tgt_filepath = f'{build_dir}/{base_filename}.inc'
        obj_filepath = f'{src_dir}/{base_filename}.obj'

        img_size, uv_texture_rgba2 = make_texture_rgba(f'{src_dir}/{uv_texture_png}')
        # copy rgba2 file from source to target directory
        rgba2_base_filename = os.path.basename(uv_texture_rgba2)
        shutil.copyfile(f'{uv_texture_rgba2}', f'{build_dir}/{rgba2_base_filename}')
        # copy png file from source to target directory
        shutil.copyfile(f'{src_dir}/{uv_texture_png}', f'{build_dir}/{uv_texture_png}')
        
        # Parse the .obj file
        vertices, faces, texture_coords, texture_vertex_indices, normals, normal_indices = parse_obj_file(obj_filepath)

        write_data(base_filename, vertices, faces, texture_coords, texture_vertex_indices, normals, normal_indices, tgt_filepath, uv_texture_rgba2, img_size)

        print(f'Modified code has been written to {tgt_filepath}')