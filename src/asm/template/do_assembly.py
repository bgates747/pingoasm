import os
import subprocess
import shutil
from agonImages import img_to_rgba2
from PIL import Image as pil

def process_and_assemble(asm_template_dir, asm_template_filepath, build_dir, input_type, tgt_dir):
    # Delete tgt_dir if it exists and recreate it
    if os.path.exists(tgt_dir):
        shutil.rmtree(tgt_dir)

    # Copy all files from the build_dir to tgt_dir
    shutil.copytree(build_dir, tgt_dir)

    # Generate the input include filename and filepath based on the input_type parameter
    input_include_filename = f"input{input_type}.inc"
    input_include_filepath = f"{asm_template_dir}/{input_include_filename}"

    # Copy the the input include file to the tgt_dir
    shutil.copy(input_include_filepath, tgt_dir)

    # Read the template assembly file
    with open(asm_template_filepath, 'r') as file:
        lines = file.readlines()

    # Read the application includes block and copy each include file to the tgt_dir
    in_block = False
    start_idx = None
    end_idx = None

    # Identify the block to process
    for i, line in enumerate(lines):
        if line.strip().startswith('; application includes'):
            in_block = True
            start_idx = i + 1
        elif line.strip().startswith('; end application includes'):
            end_idx = i
            break

    if in_block and start_idx is not None and end_idx is not None:
        # Process each line in the block
        for j in range(start_idx, end_idx):
            filename = lines[j].strip().split('"')[1]  # Extract the file name inside quotes
            shutil.copy(f"{asm_template_dir}/{filename}", tgt_dir)

    # Uncomment the control include line in the template assembly file based on the input_type parameter
    for i, line in enumerate(lines):
        if line.strip().startswith(f'; include "input{input_type}.inc"'):
            lines[i] = f'    include "{input_include_filename}"'
            break

    # Find the model includes block and process each include file
    in_block = False
    start_idx = None
    end_idx = None

    # Identify the block to process
    for i, line in enumerate(lines):
        if line.strip().startswith('; model includes'):
            in_block = True
            start_idx = i + 1  # Skip the line starting with `; model includes`
        elif line.strip().startswith('; end model includes'):
            end_idx = i
            break

    if in_block and start_idx is not None and end_idx is not None:
        # Process each line in the block
        for j in range(start_idx, end_idx):
            # Work with a fresh copy of the lines each time
            working_lines = lines[:]

            # Uncomment the current line
            working_lines[j] = '    ' + working_lines[j].lstrip('; ')

            # Debug print the current line being processed
            print(f"Processing: {working_lines[j].strip()}")

            # Extract the base file name for the bin output file
            include_file = working_lines[j].strip().split('"')[1]  # Extract the file name inside quotes
            output_bin_filename = os.path.splitext(os.path.basename(include_file))[0] + ".bin"
            main_asm_filename = output_bin_filename.replace(".bin", ".asm")

            # Write the modified lines to the main assembly file
            main_assembly_filepath = f"{tgt_dir}/{main_asm_filename}"
            with open(main_assembly_filepath, 'w') as file:
                file.writelines(working_lines)

            # Assemble the program
            try:
                assemble_program(main_asm_filename, output_bin_filename, tgt_dir)
            except subprocess.CalledProcessError as e:
                print(f"Error during assembly of {include_file}: {e}")
                break  # Exit the loop if there's an error

            # Re-comment the current line in the original copy
            lines[j] = f";{lines[j].lstrip(';')}"

def assemble_program(main_asm_filename, output_bin_filename, tgt_dir):
    # Save the current working directory
    original_directory = os.getcwd()

    try:
        # Change to the directory containing the .asm file
        os.chdir(tgt_dir)

        # Execute the assembly command using subprocess
        subprocess.run(["ez80asm", main_asm_filename, output_bin_filename], check=True)

    finally:
        # Restore the original working directory
        os.chdir(original_directory)

def make_rgba(png_filepath):
    rgba2_filepath = png_filepath.replace('.png', '.rgba2')
    img = pil.open(png_filepath)
    img_size = img.size
    img_to_rgba2(img, rgba2_filepath)
    return img_size, rgba2_filepath

if __name__ == "__main__":
    img_src_dir = 'src/blender'    
    asm_template_dir = "src/asm/template"
    asm_template_filepath = f"{asm_template_dir}/app.asm"
    build_dir = "src/asm/build"
    inputcam_dir = "src/asm/movecam"
    inputobj_dir = "src/asm/moveobj"
    inputair_dir = "src/asm/moveair"

    # Process the file and assemble each include file
    process_and_assemble(asm_template_dir, asm_template_filepath, build_dir, 'cam', inputcam_dir)
    process_and_assemble(asm_template_dir, asm_template_filepath, build_dir, 'obj', inputobj_dir)
    process_and_assemble(asm_template_dir, asm_template_filepath, build_dir, 'air', inputair_dir)

    fsim_images = [
        'fsimpanel.png', 
        'fsimviewport.png'
    ]
    for img_filename in fsim_images:
        img_size, rgba2_filepath = make_rgba(f'{img_src_dir}/{img_filename}')
        rgba2_base_filename = os.path.basename(rgba2_filepath)
        shutil.copyfile(f'{rgba2_filepath}', f'{inputair_dir}/{rgba2_base_filename}')
        print(f'RGBA2 file has been written to {inputair_dir}/{rgba2_base_filename}')