def flip_winding_order_in_obj(filepath):
    with open(filepath, 'r') as file:
        lines = file.readlines()
    
    new_lines = []
    
    for line in lines:
        if line.startswith('f '):
            # Split the face line into components
            parts = line.strip().split()
            
            # Keep the first part ('f') and reverse the rest (vertex indices)
            reversed_face = [parts[0]] + parts[1:][::-1]
            
            # Join them back into a single line
            new_line = ' '.join(reversed_face) + '\n'
            new_lines.append(new_line)
        else:
            # If it's not a face line, just keep it as is
            new_lines.append(line)
    
    # Write the modified lines back to a new file
    output_filepath = filepath.replace('.obj', '_flipped.obj')
    with open(output_filepath, 'w') as file:
        file.writelines(new_lines)
    
    print(f"Winding order flipped in OBJ file. New file saved as: {output_filepath}")

# Example usage
flip_winding_order_in_obj('src/blender/manhattan.obj')
