import re
import os

def parse_array(data, dtype="float"):
    # Extracting continuous digits and handling commas and whitespace
    items = []
    if dtype == "float":
        items = [tuple(map(float, item.split(','))) for item in re.findall(r'{(.*?)}', data, re.S)]
    elif dtype == "int":
        items = [tuple(map(int, item.split(','))) for item in re.findall(r'{(.*?)}', data, re.S)]
    return items

def extract_indices(data):
    # Handling possible multiline and whitespace variations
    data_clean = re.sub(r'\s+', '', data)  # Remove all whitespace
    numbers = re.findall(r'\d+', data_clean)  # Extract numbers
    return [int(num) for num in numbers]

def convert_c_to_obj(c_file_path, obj_file_path):
    file_name = os.path.basename(c_file_path).split('.')[0]
    proper_name = file_name.capitalize()

    with open(c_file_path, 'r') as file:
        data = file.read()

    vertices = parse_array(re.search(r'Vec3f _vert\[\d+\] = {(.*?)};', data, re.S).group(1))
    tex_coords = parse_array(re.search(r'Vec2f _coord\[\d+\] = {(.*?)};', data, re.S).group(1))
    pos_indices_data = re.search(r'uint16_t pos_indices\[\d+\] = {(.*?)};', data, re.S).group(1)
    tex_indices_data = re.search(r'uint16_t tex_indices\[\d+\] = {(.*?)};', data, re.S).group(1)
    
    pos_indices = extract_indices(pos_indices_data)
    tex_indices = extract_indices(tex_indices_data)

    with open(obj_file_path, 'w') as obj_file:
        obj_file.write(f'mtllib {file_name}.mtl\n')
        obj_file.write(f'o {proper_name}\n')

        for vertex in vertices:
            obj_file.write(f'v {vertex[0]} {vertex[1]} {vertex[2]}\n')
        
        for coord in tex_coords:
            obj_file.write(f'vt {coord[0]} {coord[1]}\n')

        obj_file.write('s 0\n')
        obj_file.write(f'usemtl {proper_name}\n')

        # Writing faces assuming each face is a triangle
        for i in range(0, len(pos_indices), 3):
            pi = pos_indices[i:i+3]
            ti = tex_indices[i:i+3]
            obj_file.write(f'f {pi[0]+1}/{ti[0]+1} {pi[1]+1}/{ti[1]+1} {pi[2]+1}/{ti[2]+1}\n')

# Example usage
convert_c_to_obj('/home/smith/Agon/mystuff/pingo/assets/viking.c', '/home/smith/Agon/mystuff/pingo/assets/viking.obj')
