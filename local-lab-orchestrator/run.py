#!/usr/bin/env python3
"""
run.py
Main orchestrator for the local-lab-orchestrator skill.
This script runs the complete workflow for processing an assignment.

Usage:
    python run.py <input1> [<input2> ...] [--use-openrouter] [--workspace <workspace_dir>]

The script will:
1. Resolve inputs and create a workspace.
2. Extract PDF and DOCX files to Markdown.
3. Use AI to analyze the assignment and extract requirements.
4. Use AI to identify the variant.
5. Use AI to create a plan and extract formulas.
6. Execute calculation scripts.
7. Execute code generation scripts.
8. Generate graphs.
9. Generate the final report.
10. Validate the output.

Note: This script assumes that the AI steps are performed by an external agent (like Claude Code)
      that follows the SKILL.md and prompts. In this script, we simulate the AI steps with
      placeholder functions that would be replaced by actual AI calls in a real agent setup.

For demonstration, we will implement the AI steps as simple placeholder functions that
just copy the input to the output. In a real scenario, the agent would use the prompts
and local models to generate the content.

However, to make this script runnable without an agent, we will implement the AI steps
using very basic rule-based extraction (for demonstration only). This is not the intended
use; the intended use is with an agent that uses the SKILL.md and prompts.

We will structure the script so that each phase is a function that can be replaced by
an agent's actions.

"""

import os
import sys
import shutil
import subprocess
import json
from pathlib import Path

# Add the scripts directory to the path so we can import our modules
sys.path.append(os.path.join(os.path.dirname(__file__), 'scripts'))

def main():
    print("=== Local Lab Orchestrator ===")
    print("This script demonstrates the workflow. For actual AI-powered processing,")
    print("use the SKILL.md with an agent like Claude Code.")
    print()

    # Parse command line arguments (simplified)
    args = sys.argv[1:]
    inputs = []
    use_openrouter = False
    workspace_dir = None
    i = 0
    while i < len(args):
        if args[i] == '--use-openrouter':
            use_openrouter = True
            i += 1
        elif args[i] == '--workspace':
            if i+1 < len(args):
                workspace_dir = args[i+1]
                i += 2
            else:
                print("Error: --workspace requires a directory argument")
                sys.exit(1)
        else:
            inputs.append(args[i])
            i += 1

    if not inputs:
        print("Error: No input files provided.")
        print("Usage: python run.py <input1> [<input2> ...] [--use-openrouter] [--workspace <workspace_dir>]")
        sys.exit(1)

    # Step 1: Resolve inputs and create workspace
    print("[1/10] Resolving inputs and creating workspace...")
    workspace = resolve_inputs(inputs, workspace_dir)
    print(f"Workspace created at: {workspace}")

    # Step 2: Extract files
    print("[2/10] Extracting files to Markdown...")
    extract_files(workspace)

    # Step 3: Analyze assignment (AI step)
    print("[3/10] Analyzing assignment (AI step)...")
    analyze_assignment(workspace)

    # Step 4: Identify variant (AI step)
    print("[4/10] Identifying variant (AI step)...")
    identify_variant(workspace)

    # Step 5: Plan solution (AI step)
    print("[5/10] Planning solution (AI step)...")
    plan_solution(workspace)

    # Step 6: Perform calculations
    print("[6/10] Performing calculations...")
    perform_calculations(workspace)

    # Step 7: Generate code
    print("[7/10] Generating code...")
    generate_code(workspace)

    # Step 8: Generate graphs
    print("[8/10] Generating graphs...")
    generate_graphs(workspace)

    # Step 9: Generate report
    print("[9/10] Generating report...")
    generate_report(workspace)

    # Step 10: Validate output
    print("[10/10] Validating output...")
    validate_output(workspace)

    print("\n=== Workflow complete ===")
    print(f"Check the workspace at: {workspace}")
    print("Output files are in the 'output' directory.")

def resolve_inputs(inputs, workspace_dir=None):
    """Resolve inputs (local files/URLs) and create a workspace."""
    # We'll use the download_input.py script
    script_path = os.path.join(os.path.dirname(__file__), 'scripts', 'download_input.py')
    cmd = [sys.executable, script_path] + inputs
    if workspace_dir:
        cmd.extend(['--workspace', workspace_dir])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error resolving inputs: {result.stderr}")
        sys.exit(1)
    # The script prints the workspace path; we'll extract it from the output
    # For simplicity, we'll assume the workspace is created in the current directory under 'workspace'
    # and has a timestamp-based name. We'll instead modify the download_input.py to return the workspace path.
    # However, to keep this demo simple, we'll create a workspace in a fixed way.
    # Let's change approach: we'll call a function from download_input.py directly.
    # But to avoid importing, we'll run the script and parse the output.
    # The download_input.py prints: "Workspace created at: <path>"
    for line in result.stdout.split('\n'):
        if line.startswith("Workspace created at:"):
            workspace = line.split(":")[1].strip()
            return workspace
    # If we didn't find it, create a default workspace
    import time
    timestamp = int(time.time())
    workspace = os.path.join(os.getcwd(), 'workspace', f"task_{timestamp}")
    os.makedirs(workspace, exist_ok=True)
    for sub in ['input', 'extracted', 'source', 'calculations', 'code', 'generated', 'validation', 'output']:
        os.makedirs(os.path.join(workspace, sub), exist_ok=True)
    return workspace

def extract_files(workspace):
    """Extract PDF and DOCX files to Markdown."""
    input_dir = os.path.join(workspace, 'input')
    extracted_dir = os.path.join(workspace, 'extracted')
    os.makedirs(extracted_dir, exist_ok=True)

    for filename in os.listdir(input_dir):
        input_path = os.path.join(input_dir, filename)
        if filename.lower().endswith('.pdf'):
            output_md = os.path.join(extracted_dir, filename.replace('.pdf', '.md'))
            images_dir = os.path.join(extracted_dir, 'images')
            script_path = os.path.join(os.path.dirname(__file__), 'scripts', 'pdf_to_md.py')
            subprocess.run([sys.executable, script_path, input_path, output_md, '--images_dir', images_dir], check=True)
        elif filename.lower().endswith('.docx'):
            output_md = os.path.join(extracted_dir, filename.replace('.docx', '.md'))
            images_dir = os.path.join(extracted_dir, 'images')
            script_path = os.path.join(os.path.dirname(__file__), 'scripts', 'docx_to_md.py')
            subprocess.run([sys.executable, script_path, input_path, output_md, '--images_dir', images_dir], check=True)
        # For images, we might want to OCR them, but we skip for now
        else:
            # Copy other files as-is
            shutil.copy(input_path, extracted_dir)

def analyze_assignment(workspace):
    """AI step: Analyze the assignment and extract requirements."""
    # In a real agent, this would involve reading the prompt and using a local model.
    # For demonstration, we'll create a placeholder requirements.md.
    source_dir = os.path.join(workspace, 'source')
    os.makedirs(source_dir, exist_ok=True)
    requirements_path = os.path.join(source_dir, 'requirements.md')
    with open(requirements_path, 'w') as f:
        f.write("# Assignment Requirements\n\n")
        f.write("## Goal\n")
        f.write("Demonstrate the workflow.\n\n")
        f.write("## Required theory\n")
        f.write("None.\n\n")
        f.write("## Required calculations\n")
        f.write("None.\n\n")
        f.write("## Required programming\n")
        f.write("Write a simple script.\n\n")
        f.write("## Required graphs\n")
        f.write("None.\n\n")
        f.write("## Required tables\n")
        f.write("None.\n\n")
        f.write("## Required report sections\n")
        f.write("Title, Task, Solution, Conclusion.\n\n")
        f.write("## Variant\n")
        f.write("None.\n\n")
        f.write("## Input data\n")
        f.write("None.\n\n")
        f.write("## Expected output\n")
        f.write("A simple report.\n\n")
        f.write("## Constraints\n")
        f.write("None.\n\n")
        f.write("## Submission files\n")
        f.write("report.docx, solution.py\n")

def identify_variant(workspace):
    """AI step: Identify the variant."""
    source_dir = os.path.join(workspace, 'source')
    variant_path = os.path.join(source_dir, 'variant.md')
    with open(variant_path, 'w') as f:
        f.write("# Variant\n\n")
        f.write("No variant identified.\n")

def plan_solution(workspace):
    """AI step: Create a plan and extract formulas."""
    source_dir = os.path.join(workspace, 'source')
    plan_path = os.path.join(source_dir, 'plan.md')
    formulas_path = os.path.join(source_dir, 'formulas.md')
    with open(plan_path, 'w') as f:
        f.write("# Solution Plan\n\n")
        f.write("1. Write a simple Python script.\n")
        f.write("2. Execute the script.\n")
        f.write("3. Generate a report.\n")
    with open(formulas_path, 'w') as f:
        f.write("# Formulas and Constants\n\n")
        f.write("No formulas required.\n")

def perform_calculations(workspace):
    """Perform calculations by running a generated script."""
    calculations_dir = os.path.join(workspace, 'calculations')
    os.makedirs(calculations_dir, exist_ok=True)
    # In a real scenario, the AI would write a calculations script.
    # For demonstration, we'll create a simple script that does nothing.
    calc_script = os.path.join(calculations_dir, 'calculations.py')
    with open(calc_script, 'w') as f:
        f.write("# Calculation script\n")
        f.write("print('No calculations to perform.')\n")
    # Run the script
    result = subprocess.run([sys.executable, calc_script], cwd=calculations_dir, capture_output=True, text=True)
    # Save output
    results_json = os.path.join(calculations_dir, 'results.json')
    results_md = os.path.join(calculations_dir, 'results.md')
    with open(results_json, 'w') as f:
        json.dump({"output": result.stdout}, f)
    with open(results_md, 'w') as f:
        f.write("# Calculation Results\n\n")
        f.write(result.stdout)

def generate_code(workspace):
    """Generate code by writing and executing a script."""
    code_dir = os.path.join(workspace, 'code')
    os.makedirs(code_dir, exist_ok=True)
    solution_script = os.path.join(code_dir, 'solution.py')
    with open(solution_script, 'w') as f:
        f.write("# Solution script\n")
        f.write("print('Hello from the solution!')\n")
    # Run the script to verify
    result = subprocess.run([sys.executable, solution_script], cwd=code_dir, capture_output=True, text=True)
    # Save output if needed
    output_dir = os.path.join(workspace, 'output')
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, 'solution_output.txt'), 'w') as f:
        f.write(result.stdout)

def generate_graphs(workspace):
    """Generate graphs by running a generated script."""
    generated_dir = os.path.join(workspace, 'generated')
    graphs_dir = os.path.join(generated_dir, 'graphs')
    os.makedirs(graphs_dir, exist_ok=True)
    # For demonstration, we'll create a simple placeholder image using matplotlib if available.
    # We'll skip if matplotlib is not installed.
    try:
        import matplotlib.pyplot as plt
        import numpy as np
        # Create a simple plot
        x = np.linspace(0, 10, 100)
        y = np.sin(x)
        plt.plot(x, y)
        plt.title('Sine Wave')
        plt.xlabel('x')
        plt.ylabel('sin(x)')
        plot_path = os.path.join(graphs_dir, 'sine_wave.png')
        plt.savefig(plot_path)
        plt.close()
    except ImportError:
        # If matplotlib is not available, create a placeholder text file
        with open(os.path.join(graphs_dir, 'graph_placeholder.txt'), 'w') as f:
            f.write("Graph placeholder: matplotlib not installed.\n")

def generate_report(workspace):
    """Generate the final report."""
    output_dir = os.path.join(workspace, 'output')
    os.makedirs(output_dir, exist_ok=True)
    # For demonstration, we'll create a simple DOCX if python-docx is available.
    try:
        from docx import Document
        doc = Document()
        doc.add_heading('Lab Report', 0)
        doc.add_paragraph('This is a demonstration report generated by the local-lab-orchestrator.')
        doc.add_paragraph('Task: Demonstrate the workflow.')
        doc.add_paragraph('Conclusion: The workflow completed successfully.')
        report_path = os.path.join(output_dir, 'final_report.docx')
        doc.save(report_path)
    except ImportError:
        # Fallback to Markdown
        report_path = os.path.join(output_dir, 'final_report.md')
        with open(report_path, 'w') as f:
            f.write('# Lab Report\n\n')
            f.write('This is a demonstration report generated by the local-lab-orchestrator.\n\n')
            f.write('## Task\n')
            f.write('Demonstrate the workflow.\n\n')
            f.write('## Conclusion\n')
            f.write('The workflow completed successfully.\n')

def validate_output(workspace):
    """Validate the output by checking that required files exist."""
    validation_dir = os.path.join(workspace, 'validation')
    os.makedirs(validation_dir, exist_ok=True)
    validation_path = os.path.join(validation_dir, 'validation.md')
    output_dir = os.path.join(workspace, 'output')
    required_files = ['final_report.docx', 'solution.py']  # Based on our demo
    missing = []
    for f in required_files:
        if not os.path.exists(os.path.join(output_dir, f)):
            missing.append(f)
    with open(validation_path, 'w') as f:
        f.write('# Validation\n\n')
        f.write('## Requirements\n')
        if missing:
            f.write('The following required files are missing:\n')
            for m in missing:
                f.write(f'- [ ] {m}\n')
        else:
            f.write('- [x] All required files are present.\n')
        f.write('\n## Problems\n')
        if missing:
            f.write('Missing required files.\n')
        else:
            f.write('None.\n')
        f.write('\n## Warnings\n')
        f.write('This is a demonstration validation. In a real run, more checks would be performed.\n')

if __name__ == '__main__':
    main()