import numpy as np
from agonImages import img_to_rgba8, convert_to_agon_palette
import PIL.Image as pil
from blender_headless import do_blender
import os

def write_bbc_basic_data(vertices, faces, texture_coords, texture_vertex_indices, template_filepath, tgt_filepath, uv_texture_rgba8, img_size):
    # Read the template file
    with open(template_filepath, 'r') as file:
        lines = file.readlines()

    # Write the template file to the target file
    with open(tgt_filepath, 'w') as file:
        for i, line in enumerate(lines):
            if line.strip().startswith("20 model_vertices%="):
                lines[i] = f"   20 model_vertices%={len(vertices)}\n"
            elif line.strip().startswith("30 model_indices%="):
                lines[i] = f"   30 model_indices%={len(faces) * 3}\n"
            elif line.strip().startswith("40 model_uvs%="):
                lines[i] = f"   40 model_uvs%={len(texture_coords)}\n"
            elif line.strip().startswith("50 texture_width%="):
                lines[i] = f"   50 texture_width%={img_size[0]} : texture_height%={img_size[1]}\n"
        file.writelines(lines)

        # Write the model vertices
        line_number = 2000
        file.write(f"\n{line_number} REM -- VERTICES --\n")
        line_number += 2
        for vertex in vertices:
            file.write(f"{line_number} DATA {', '.join(map(str, vertex))}\n")
            line_number += 2

        # Write the face vertex indices
        file.write(f"{line_number} REM -- FACE VERTEX INDICES --\n")
        line_number += 2
        for face in faces:
            file.write(f"{line_number} DATA {', '.join(map(str, face))}\n")
            line_number += 2

        # Write the texture UV coordinates
        file.write(f"{line_number} REM -- TEXTURE UV COORDINATES --\n")
        line_number += 2
        for coord in texture_coords:
            file.write(f"{line_number} DATA {', '.join(map(str, coord))}\n")
            line_number += 2

        # Write the texture vertex indices
        file.write(f"{line_number} REM -- TEXTURE VERTEX INDICES --\n")
        line_number += 2
        for indices in texture_vertex_indices:
            file.write(f"{line_number} DATA {', '.join(map(str, indices))}\n")
            line_number += 2

        # Write the texture data
        file.write(f"{line_number} REM -- TEXTURE BITMAP --\n")
        line_number += 2
        with open(uv_texture_rgba8, 'rb') as img_file:
            img_data = img_file.read()
            filesize = len(img_data)
            linesize = 16
            for i, byte in enumerate(img_data):
                if i % linesize == 0:
                    file.write(f"{line_number} DATA ")
                    line_number += 2
                if (i + 1) % linesize == 0 or i == filesize - 1:
                    file.write(f"{byte}\n")
                else:
                    file.write(f"{byte},")

def make_texture_rgba(uv_texture_png):
    uv_texture_rgba8 = uv_texture_png.replace('.png', '.rgba8')
    img = pil.open(uv_texture_png)
    img_size = img.size
    if not os.path.exists(uv_texture_rgba8):
        img_to_rgba8(img, uv_texture_rgba8)
    return img_size, uv_texture_rgba8

import importlib

if __name__ == '__main__':
    src_dir = 'ez80/src/blender'
    tgt_dir = 'ez80/src/bas'
    blender_executable = "/Applications/Blender.app/Contents/MacOS/Blender"
    blender_local_prefs_path = None

    # base_filename, mesh_name, blender_filename, uv_texture_png
    do_these_things = [
        ['cubeaxes-y+z', 'Cube', 'cubeaxes.blend', 'blenderaxes.png'],
        ['cubeaxes+z+y', 'Cube', 'cubeaxes.blend', 'blenderaxes.png'],
        # ['cube', 'Cube', 'cube.blend', 'colors64HSV.png'],
        # ['cube2', 'Cube', 'cube2.blend', 'colors64HSV.png'],
        # ['earth', 'Sphere', 'earth.blend', 'earth160x80.png'],
        # ['HeavyTank', 'HeavyTank', 'stellar7a.blend', 'colorcube.png'],
        # ['wolf', 'Cube', 'wolf.blend', 'thumb_16.png']
    ]

    for thing in do_these_things:
        base_filename, mesh_name, blender_filename, uv_texture_png = thing
        template_filepath = f'{tgt_dir}/template.bas'
        tgt_filepath = f'{tgt_dir}/{base_filename}.bas'
        img_size, uv_texture_rgba8 = make_texture_rgba(f'{src_dir}/{uv_texture_png}')
        blender_file_path = f'{src_dir}/{blender_filename}'
        blender_script_path = "ez80/build/scripts/blend_export.py"
        output_file = "ez80/build/scripts/vertices_from_blender.py"
            
        do_blender(blender_file_path, blender_script_path, blender_executable, None, output_file, mesh_name)

        # Import the vertices, faces, texture_coords, and texture_vertex_indices from vertices_from_blender.py
        import vertices_from_blender
        importlib.reload(vertices_from_blender)
        vertices = vertices_from_blender.vertices
        faces = vertices_from_blender.faces
        texture_coords = vertices_from_blender.texture_coords
        texture_vertex_indices = vertices_from_blender.texture_vertex_indices

        write_bbc_basic_data(vertices, faces, texture_coords, texture_vertex_indices, template_filepath, tgt_filepath, uv_texture_rgba8, img_size)

        print(f"Modified BASIC code has been written to {tgt_filepath}")
