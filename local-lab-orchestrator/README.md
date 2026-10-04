# Local Lab Orchestrator

A skill for orchestrating the completion of university assignments using local AI models and deterministic scripts.

## Purpose

This skill helps students process university assignments (PDF, DOCX, images, or links) by:
- Extracting text and structure from input files
- Using AI to understand the assignment and extract requirements
- Planning the solution
- Performing calculations and generating code
- Creating graphs and reports
- Validating the output

The system is designed to minimize token usage and make efficient use of limited VRAM (e.g., RTX 3050 with 6 GB) by:
- Using scripts for deterministic work (extraction, calculations, code execution)
- Reserving AI context for reasoning, decision-making, and writing
- Using a filesystem-based context strategy to avoid repeatedly processing raw documents
- Selecting appropriate local models based on availability and VRAM constraints

## Installation

1. Clone or copy this directory to your desired location.
2. Ensure you have Python 3.8+ installed.
3. Install the required Python packages:

   ```bash
   pip install --break-system-packages python-docx PyMuPDF requests
   ```

   (Alternatively, create a virtual environment and install there.)

4. Install a local model runtime such as [Ollama](https://ollama.com/) and pull a suitable model (e.g., a 7B or 8B quantized model).

5. (Optional) Set environment variables for model configuration:
   - `OLLAMA_HOST`: URL of the Ollama API (default: http://localhost:11434)
   - `LOCAL_LAB_VRAM_GB`: Available GPU VRAM in GB (default: 6.0)

## Usage

### As an Agent Skill

The intended usage is through an agent (like Claude Code) that reads the `SKILL.md` and follows the workflow.

1. Ensure the agent has access to the `local-lab-orchestrator` directory.
2. The agent will use the prompts in the `prompts/` directory and the scripts in the `scripts/` directory to process an assignment.

### Direct Execution (Demonstration)

For testing or simple automation, you can use the provided `run.py` script:

```bash
python run.py <input_file1> [<input_file2> ...] [--workspace <workspace_dir>]
```

Example:
```bash
python run.py ./assignment.pdf ./template.docx
```

This will create a workspace and run through the workflow steps, using placeholder AI functions. For actual AI-powered processing, use the SKILL.md with an agent.

## Workflow

The skill follows these steps:

1. **Resolve inputs**: Copy/download input files to a workspace `input/` directory.
2. **Extract files**: Convert PDF and DOCX to Markdown (with image extraction for PDF).
3. **Analyze assignment**: Use AI to extract requirements and create `context/requirements.md`.
4. **Identify variant**: Use AI to find the student's variant and create `context/variant.md`.
5. **Plan solution**: Use AI to create a step-by-step plan and extract formulas.
6. **Perform calculations**: Write and execute Python scripts for numerical work.
7. **Generate code**: Write and execute Python scripts for required programming.
8. **Generate graphs**: Write and execute Python scripts to create required graphs.
9. **Generate report**: Create the final report (DOCX, MD, etc.) using a template if provided.
10. **Validate output**: Check that all requirements are met and files are correct.

Each step produces human-readable intermediate files in the workspace, allowing the agent to inspect progress without excessive context usage.

## Workspace Structure

Each task gets its own workspace with the following directories:

- `input/`: Original input files (copied/downloaded)
- `extracted/`: Extracted Markdown and images
- `context/`: AI-generated context files (requirements, variant, plan, formulas)
- `calculations/`: Calculation scripts and results
- `code/`: Code scripts
- `generated/`: Generated graphs and tables
- `validation/`: Validation results
- `output/`: Final output files

## Model Selection

The skill includes a model inspection script (`scripts/inspect_models.py`) that queries the local Ollama runtime to determine available models, their sizes, context lengths, and estimated VRAM usage.

The agent should use this information to select a model appropriate for the task, preferring quantized 4B-8B models for reasoning and coding tasks.

If no suitable local model is available, the agent may optionally fall back to OpenRouter (configured via environment variables).

## Customization

You can customize the skill by:

- Modifying the prompt templates in the `prompts/` directory.
- Adding new scripts for specific assignment types.
- Adjusting the workspace structure in the scripts.
- Changing the AI call parameters (temperature, max tokens, etc.) in the agent's implementation.

## Limitations

- PDF OCR is not implemented by default; scanned PDFs will have empty text layers.
- DOCX image extraction preserves images but does not restore their original positions in the Markdown.
- Template-based DOCX generation is not fully implemented; the demonstrator uses a simple template replacement approach.
- The model inspection script currently only supports Ollama.

## Contributing

Feel free to submit issues or pull requests to improve the skill.

## License

This project is licensed under the MIT License.
