#!/usr/bin/env python3
"""
run_code.py
Execute a Python script and capture the output.

Usage:
    python run_code.py <script_path> [--workspace <workspace_dir>] [--output <output_file>] [--error <error_file>]

Arguments:
    script_path: Path to the Python script to execute.
    workspace_dir: Directory to run the script in (default: current directory).
    output_file: File to capture stdout (default: stdout printed to console).
    error_file: File to capture stderr (default: stderr printed to console).

The script runs the Python script and returns the exit code.
It captures stdout and stderr to files or prints them.
"""
import sys
import os
import subprocess
import argparse

def run_python_script(script_path, workspace_dir=None, output_file=None, error_file=None):
    """Run a Python script and capture output."""
    if not os.path.isfile(script_path):
        print(f"Error: Script not found: {script_path}", file=sys.stderr)
        return 1

    if workspace_dir is None:
        workspace_dir = os.getcwd()

    # Ensure the script path is absolute or relative to workspace
    if not os.path.isabs(script_path):
        script_path = os.path.join(workspace_dir, script_path)

    # Prepare the command
    cmd = [sys.executable, script_path]

    # Prepare output and error file handles
    out_handle = open(output_file, 'w') if output_file else subprocess.PIPE
    err_handle = open(error_file, 'w') if error_file else subprocess.PIPE

    try:
        # Run the script
        result = subprocess.run(
            cmd,
            cwd=workspace_dir,
            stdout=out_handle,
            stderr=err_handle,
            text=True
        )
    except Exception as e:
        print(f"Error running script: {e}", file=sys.stderr)
        return 1
    finally:
        if output_file:
            out_handle.close()
        if error_file:
            err_handle.close()

    # If we captured output in pipes, print them
    if not output_file and result.stdout:
        print("STDOUT:")
        print(result.stdout)
    if not error_file and result.stderr:
        print("STDERR:")
        print(result.stderr, file=sys.stderr)

    return result.returncode

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run a Python script and capture output.')
    parser.add_argument('script_path', help='Path to the Python script to execute')
    parser.add_argument('--workspace', help='Directory to run the script in')
    parser.add_argument('--output', help='File to capture stdout')
    parser.add_argument('--error', help='File to capture stderr')
    args = parser.parse_args()

    exit_code = run_python_script(
        args.script_path,
        workspace_dir=args.workspace,
        output_file=args.output,
        error_file=args.error
    )
    sys.exit(exit_code)