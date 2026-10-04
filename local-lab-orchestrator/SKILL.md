# Local Lab Orchestrator

## Purpose
This skill orchestrates the completion of university assignments by using local AI models and deterministic scripts to minimize token usage and maximize efficiency on hardware with limited VRAM (e.g., RTX 3050 with 6 GB VRAM).

## When to use
Use this skill when you have a university assignment provided as PDF, DOCX, image, or a link to such files. The skill will help you understand the assignment, perform required calculations, generate code, and produce the final report.

## Workflow
1. **Resolve inputs**: Copy/download input files to a workspace.
2. **Extract files**: Convert PDF and DOCX to Markdown for AI analysis.
3. **Analyze assignment**: Use AI to extract requirements and identify variant.
4. **Plan solution**: Use AI to create a step-by-step plan and extract formulas.
5. **Perform calculations**: Write and execute Python scripts for numerical work.
6. **Generate code**: Write and execute Python scripts for any required programming.
7. **Generate graphs**: Write and execute Python scripts to create required graphs.
8. **Generate report**: Create the final report (DOCX, MD, etc.) using a template if provided.
9. **Validate output**: Check that all requirements are met and files are correct.

## Available scripts
- `scripts/download_input.py`: Resolve inputs (local files/URLs) and create workspace.
- `scripts/pdf_to_md.py`: Convert PDF to Markdown with image extraction.
- `scripts/docx_to_md.py`: Convert DOCX to Markdown with structure preservation.
- `scripts/docx_template.py`: Analyze a DOCX template and extract its structure.
- `scripts/inspect_models.py`: Inspect local AI models (Ollama) and produce a report.
- `scripts/run_code.py`: Execute a Python script and capture output.
- `scripts/prompts/analyze.md`: Prompt for analyzing assignment.
- `scripts/prompts/plan.md`: Prompt for planning solution.
- `scripts/prompts/solve.md`: Prompt for performing calculations.
- `scripts/prompts/code.md`: Prompt for generating code.
- `scripts/prompts/report.md`: Prompt for generating report.
- `scripts/prompts/validate.md`: Prompt for validating output.

## Environment setup

Before running any scripts, ensure the environment has the required dependencies installed.

**Requirements** (`requires-python = ">=3.10"`):

```toml
[project]
name = "local-lab-orchestrator"
requires-python = ">=3.10"
dependencies = [
    "PyMuPDF>=1.24.0",       # fitz — PDF parsing and image extraction (pdf_to_md.py)
    "python-docx>=1.1.0",    # docx — DOCX read/write (docx_template.py, docx_to_md.py)
    "requests>=2.31.0",      # HTTP client for Ollama API and file downloads (inspect_models.py, download_input.py)
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "ruff>=0.4.0",
]
```

**Install steps** (run from the `local-lab-orchestrator/` directory):

```bash
# Standard pip install (editable, includes all runtime deps)
pip install -e .

# Or install deps directly without the package
pip install "PyMuPDF>=1.24.0" "python-docx>=1.1.0" "requests>=2.31.0"

# Optional: dev tools
pip install -e ".[dev]"
```

> **Note**: If using `hatch`, run `hatch env create` — the default env already includes all runtime dependencies.

## Input/output conventions
- Each task uses a workspace directory with the following structure:
  - `input/`: Original input files.
  - `extracted/`: Extracted Markdown and images.
  - `source/`: Intermediate AI-generated files (requirements, variant, plan, formulas).
  - `calculations/`: Calculation scripts and results.
  - `code/`: Code scripts.
  - `generated/`: Generated graphs and tables.
  - `validation/`: Validation results.
  - `output/`: Final output files.
- The orchestrator (agent) should pass the workspace path to each script.
- AI prompts are stored in the `prompts/` directory and should be read and formatted with context from the workspace.

## Model selection
- Use `inspect_models.py` to discover available local models.
- Prefer quantized 4B-8B models for reasoning and coding tasks.
- Fall back to OpenRouter only if no suitable local model is available (set via environment variable).

## Rules
- **Python/tools do deterministic work. AI does reasoning.**
- Do not ask the AI to perform extraction, calculations, or file manipulations that scripts can do.
- Use AI only for understanding, reasoning, decision-making, coding, interpretation, and writing.
- Keep prompts concise and pass only relevant context files to the AI.
- Save all intermediate results to the workspace to avoid excessive context usage.
- Execute generated code whenever possible to verify correctness.

## Failure handling
- Scripts should exit with non-zero code on failure and print error messages to stderr.
- The agent should check script outputs and decide whether to retry, fallback, or abort.
- If a script fails, the agent should consult the error message and consider alternative approaches (e.g., enable OCR for scanned PDFs).

## Final checklist
- [ ] Inputs resolved and workspace created.
- [ ] Files extracted to Markdown.
- [ ] Requirements extracted and variant identified.
- [ ] Plan created and formulas extracted.
- [ ] Calculations performed and results saved.
- [ ] Code written, executed, and outputs saved.
- [ ] Graphs generated and saved.
- [ ] Report generated in required format.
- [ ] Validation passed with no critical issues.
