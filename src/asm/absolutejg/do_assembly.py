import os
import subprocess

def process_file(filepath):
    with open(filepath, 'r') as file:
        lines = file.readlines()

    in_block = False
    start_idx = None
    end_idx = None

    for i, line in enumerate(lines):
        if line.strip().startswith('; model includes'):
            in_block = True
            start_idx = i + 1  # Skip the line starting with `; model includes`
        elif line.strip().startswith('; end model includes'):
            end_idx = i
            break

    if in_block and start_idx is not None and end_idx is not None:
        # Uncomment the first include line if it's commented
        if lines[start_idx].strip().startswith(';'):
            lines[start_idx] = lines[start_idx].replace(';', '', 1)

        # Comment all other lines in the block
        for j in range(start_idx + 1, end_idx):
            if not lines[j].strip().startswith(';'):
                lines[j] = f";{lines[j]}"

    # Write back the changes to the file
    with open(filepath, 'w') as file:
        file.writelines(lines)

def assemble_program(asm_filepath, output_filename):
    # Save the current working directory
    original_directory = os.getcwd()

    try:
        # Get the directory and the filename
        directory = os.path.dirname(asm_filepath)
        filename = os.path.basename(asm_filepath)

        # Change to the directory containing the .asm file
        os.chdir(directory)

        # Execute the assembly command using subprocess
        subprocess.run(["ez80asm", filename, output_filename], check=True)

    finally:
        # Restore the original working directory
        os.chdir(original_directory)

if __name__ == "__main__":
    asm_file_path = "src/asm/absolutejg/app.asm"
    output_file = "includename.bin"

    process_file(asm_file_path)
    assemble_program(asm_file_path, output_file)
