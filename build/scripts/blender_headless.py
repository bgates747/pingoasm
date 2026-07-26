import os
import shutil
import subprocess


def find_blender(blender_executable=None):
    """Return a usable Blender executable on Linux or macOS."""
    if blender_executable:
        executable = shutil.which(blender_executable)
        if executable:
            return executable
        if os.path.isfile(blender_executable) and os.access(
            blender_executable, os.X_OK
        ):
            return blender_executable
        raise FileNotFoundError(
            f"Blender executable is not usable: {blender_executable}"
        )

    macos_blender = "/Applications/Blender.app/Contents/MacOS/Blender"
    if os.path.isfile(macos_blender) and os.access(macos_blender, os.X_OK):
        return macos_blender

    for executable_name in ("blender", "Blender"):
        executable = shutil.which(executable_name)
        if executable:
            return executable

    raise FileNotFoundError(
        "Blender executable not found on PATH or in the standard macOS app."
    )

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
    blender_executable = find_blender(blender_executable)
    
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
    return subprocess.run(cmd, env=env_vars, check=True)

def check_blender_version(blender_executable=None):
    """
    Checks and prints the Blender version.
    
    :param blender_executable: Path to the Blender executable.
    """
    blender_executable = find_blender(blender_executable)
    
    # Command to check Blender version
    cmd = [blender_executable, "--version"]
    
    result = subprocess.run(
        cmd, capture_output=True, text=True, check=True
    )
    print(result.stdout)
    return result.stdout

if __name__ == "__main__":
    check_blender_version()
