#!/usr/bin/env python3
"""
download_input.py
Resolve inputs (local files, URLs) and place them in a workspace.

Usage:
    python download_input.py <input1> [<input2> ...] --workspace <workspace_path>

Each input can be a local file path or a URL.
The function will copy/download each input to the workspace/input/ directory.
It returns the list of resolved local file paths in the workspace.
"""

import os
import sys
import shutil
import hashlib
import requests
from urllib.parse import urlparse
from pathlib import Path

def is_url(string):
    try:
        result = urlparse(string)
        return all([result.scheme, result.netloc])
    except:
        return False

def download_url(url, dest_dir):
    """Download a URL to a temporary file in dest_dir, return the local path."""
    # Generate a filename from the URL path or use a hash
    parsed = urlparse(url)
    filename = os.path.basename(parsed.path)
    if not filename:
        # If no filename in URL, use a hash of the URL
        filename = hashlib.sha256(url.encode()).hexdigest()[:16]
    dest_path = os.path.join(dest_dir, filename)

    # If file already exists, we might want to avoid re-downloading?
    # For simplicity, we'll download every time.
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(dest_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return dest_path
    except Exception as e:
        print(f"Error downloading {url}: {e}", file=sys.stderr)
        return None

def copy_local_file(src_path, dest_dir):
    """Copy a local file to dest_dir, return the local path in dest_dir."""
    if not os.path.isfile(src_path):
        print(f"Error: Local file not found: {src_path}", file=sys.stderr)
        return None
    filename = os.path.basename(src_path)
    dest_path = os.path.join(dest_dir, filename)
    try:
        shutil.copy2(src_path, dest_path)
        return dest_path
    except Exception as e:
        print(f"Error copying {src_path}: {e}", file=sys.stderr)
        return None

def resolve_inputs(input_list, workspace_dir):
    """
    Resolve a list of inputs (local files or URLs) and place them in workspace_dir/input/.
    Returns a list of resolved local file paths.
    """
    input_dir = os.path.join(workspace_dir, 'input')
    os.makedirs(input_dir, exist_ok=True)

    resolved_paths = []
    for inp in input_list:
        if is_url(inp):
            local_path = download_url(inp, input_dir)
        else:
            local_path = copy_local_file(inp, input_dir)
        if local_path:
            resolved_paths.append(local_path)
        else:
            print(f"Warning: Failed to resolve input: {inp}", file=sys.stderr)
    return resolved_paths

def create_workspace(base_dir=None):
    """
    Create a workspace directory with a unique name under base_dir (or current directory).
    Returns the path to the workspace.
    """
    if base_dir is None:
        base_dir = os.getcwd()
    workspace_base = os.path.join(base_dir, 'workspace')
    os.makedirs(workspace_base, exist_ok=True)

    # Create a unique workspace name using timestamp and a random string
    import time
    timestamp = int(time.time())
    # Use a random string to avoid collisions
    random_str = hashlib.sha256(os.urandom(16)).hexdigest()[:8]
    workspace_name = f"task_{timestamp}_{random_str}"
    workspace_path = os.path.join(workspace_base, workspace_name)
    os.makedirs(workspace_path, exist_ok=True)

    # Create the standard directory structure
    for dir_name in ['input', 'extracted', 'source', 'context', 'calculations', 'code', 'generated', 'validation', 'output']:
        os.makedirs(os.path.join(workspace_path, dir_name), exist_ok=True)

    return workspace_path

if __name__ == '__main__':
    # Simple command-line interface for testing
    import argparse
    parser = argparse.ArgumentParser(description='Resolve inputs and create workspace.')
    parser.add_argument('inputs', nargs='+', help='Input files or URLs')
    parser.add_argument('--workspace', help='Path to workspace directory (if not provided, a new one is created)')
    args = parser.parse_args()

    if args.workspace:
        workspace_path = args.workspace
        # Ensure the workspace directory exists and has the subdirectories
        for dir_name in ['input', 'extracted', 'source', 'context', 'calculations', 'code', 'generated', 'validation', 'output']:
            os.makedirs(os.path.join(workspace_path, dir_name), exist_ok=True)
    else:
        workspace_path = create_workspace()

    resolved = resolve_inputs(args.inputs, workspace_path)
    print(f"Workspace created at: {workspace_path}")
    print("Resolved input files:")
    for f in resolved:
        print(f"  {f}")