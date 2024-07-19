import subprocess
import os
import shutil

def do_blender(blender_file_path, blender_script_path, blender_executable=None, blender_local_prefs_path=None, *args):
    """
    Runs Blender with the given script and optionally uses a local user preferences file.
    Dynamically accepts additional arguments to pass to the Blender script.
    
    :param blender_file_path: Path to the Blender file to run the script against.
    :param blender_script_path: Path to the Blender script to run.
    :param blender_executable: Path to the Blender executable.
    :param blender_local_prefs_path: Optional path to a directory containing the userpref.blend file.
    :param args: Arbitrary list of additional arguments to pass to the Blender script.
    """
    # Set default Blender executable path if not provided
    if not blender_executable:
        default_blender_path = "/Applications/Blender.app/Contents/MacOS/Blender"
        if os.path.exists(default_blender_path):
            blender_executable = default_blender_path
        else:
            blender_executable = shutil.which("Blender")
            if not blender_executable:
                raise FileNotFoundError("Blender executable not found. Please provide the correct path.")
    
    # Environment variables for Blender
    env_vars = os.environ.copy()
    
    # If a local user preferences path is provided, set it in the environment
    if blender_local_prefs_path and os.path.exists(blender_local_prefs_path):
        env_vars["BLENDER_USER_CONFIG"] = blender_local_prefs_path
    
    # Command to run Blender in headless mode with the specified script, including additional arguments
    cmd = [
        blender_executable, 
        "-b", 
        blender_file_path,  # Add Blender file path here
        "-P", blender_script_path, 
        "--"
    ] + [str(arg) for arg in args]  # Convert all arguments to strings and append
    
    print(' '.join(cmd))
    subprocess.run(cmd, env=env_vars)

def check_blender_version(blender_executable=None):
    """
    Checks and prints the Blender version.
    
    :param blender_executable: Path to the Blender executable.
    """
    # Set default Blender executable path if not provided
    if not blender_executable:
        default_blender_path = "/Applications/Blender.app/Contents/MacOS/Blender"
        if os.path.exists(default_blender_path):
            blender_executable = default_blender_path
        else:
            blender_executable = shutil.which("Blender")
            if not blender_executable:
                raise FileNotFoundError("Blender executable not found. Please provide the correct path.")
    
    # Command to check Blender version
    cmd = [blender_executable, "--version"]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)

if __name__ == "__main__":
    blender_executable = None
    blender_local_prefs_path = None

    blender_file_path = "ez80/src/blender/cube.blend"
    blender_script_path = "ez80/build/scripts/blend_export.py"
    output_file = 'ez80/build/scripts/vertices_from_blender.py'
    do_blender(blender_file_path, blender_script_path, blender_executable, None, output_file)
