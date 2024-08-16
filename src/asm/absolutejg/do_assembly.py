import os
import subprocess

def process_and_assemble(filepath):
    # Read the original file and save its contents in memory
    with open(filepath, 'r') as file:
        original_lines = file.readlines()

    # Make a working copy of the original lines
    lines = original_lines[:]

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
            output_file = os.path.splitext(os.path.basename(include_file))[0] + ".bin"

            # Write the modified lines back to the file
            with open(filepath, 'w') as file:
                file.writelines(working_lines)

            # Assemble the program
            try:
                assemble_program(filepath, output_file)
            except subprocess.CalledProcessError as e:
                print(f"Error during assembly of {include_file}: {e}")
                break  # Exit the loop if there's an error

            # Re-comment the current line in the original copy
            lines[j] = f";{lines[j].lstrip(';')}"

    # Restore the original file
    with open(filepath, 'w') as file:
        file.writelines(original_lines)

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

    # Process the file and assemble each include file
    process_and_assemble(asm_file_path)
