#!/usr/bin/env python3
"""
inspect_models.py
Inspect local AI models (via Ollama) and produce a machine-readable report.

Usage:
    python inspect_models.py [--output <output_json>]

Arguments:
    --output: Path to the output JSON file (default: models.json in current directory)

The script queries the Ollama API to list models and gathers details for each.
It estimates VRAM usage and recommends tasks based on model size and quantization.
"""
import sys
import os
import json
import requests
from typing import Dict, List, Optional

OLLAMA_API_BASE = os.getenv("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_VRAM_GB = float(os.getenv("LOCAL_LAB_VRAM_GB", "6.0"))  # GPU VRAM in GB

def check_ollama_available() -> bool:
    """Check if Ollama server is running."""
    try:
        resp = requests.get(f"{OLLAMA_API_BASE}/api/tags", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False

def list_models() -> List[Dict]:
    """Get list of models from Ollama."""
    try:
        resp = requests.get(f"{OLLAMA_API_BASE}/api/tags")
        resp.raise_for_status()
        return resp.json().get("models", [])
    except Exception as e:
        print(f"Error fetching model list: {e}", file=sys.stderr)
        return []

def get_model_details(name: str) -> Optional[Dict]:
    """Get detailed information for a specific model."""
    try:
        resp = requests.post(f"{OLLAMA_API_BASE}/api/show", json={"name": name})
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Error fetching details for model {name}: {e}", file=sys.stderr)
        return None

def estimate_vram_gb(model_size_bytes: int) -> float:
    """
    Estimate VRAM required to load the model.
    Rough estimate: model size in bytes converted to GB, plus 20% overhead.
    """
    size_gb = model_size_bytes / (1024 ** 3)
    return size_gb * 1.2  # 20% overhead

def determine_recommended_tasks(model_details: Dict, size_gb: float) -> List[str]:
    """
    Determine recommended tasks based on model characteristics.
    This is a simplified heuristic.
    """
    tasks = []
    model_name = model_details.get("name", "").lower()
    # Check for quantization in name
    quantized = any(q in model_name for q in ["q4", "q5", "q8", "quantized"])
    # Check parameter count if available in details
    param_count = model_details.get("parameter_count", "")
    if param_count:
        # Extract numbers if possible
        import re
        nums = re.findall(r'\d+', param_count)
        if nums:
            # Assume the first number is the parameter count in billions
            try:
                params = float(nums[0])
                if params < 3:
                    tasks.extend(["classification", "simple extraction", "summarization"])
                elif params < 10:
                    tasks.extend(["reasoning", "coding", "mathematics", "report writing"])
                else:
                    tasks.extend(["advanced reasoning", "complex coding"])
            except ValueError:
                pass
    else:
        # Fallback to size
        if size_gb < 2:
            tasks.extend(["classification", "simple extraction", "summarization"])
        elif size_gb < 5:
            tasks.extend(["reasoning", "coding"])
        else:
            tasks.extend(["advanced reasoning", "complex coding", "report writing"])
    # Remove duplicates
    return list(dict.fromkeys(tasks))

def inspect_models() -> Dict:
    """Inspect all available models and return a report."""
    if not check_ollama_available():
        return {
            "error": "Ollama server is not available at {}".format(OLLAMA_API_BASE),
            "runtime": "ollama",
            "models": []
        }

    models_list = list_models()
    report = {
        "runtime": "ollama",
        "vram_available_gb": VRAM_GB,
        "models": []
    }

    for model_info in models_list:
        name = model_info.get("name")
        size = model_info.get("size", 0)  # size in bytes
        details = get_model_details(name)
        if details is None:
            # Use basic info from list
            size_gb = size / (1024 ** 3)
            vram_estimate = estimate_vram_gb(size)
            model_details = {
                "name": name,
                "size": size,
                "size_gb": round(size_gb, 2),
                "estimated_vram_gb": round(vram_estimate, 2),
                "usable": vram_estimate <= VRAM_GB,
                "recommended_tasks": determine_recommended_tasks({}, size_gb),
                "context_length": "unknown",
                "quantization": "unknown"
            }
        else:
            # Extract more details
            size_gb = size / (1024 ** 3)
            vram_estimate = estimate_vram_gb(size)
            # Context length from details
            context = details.get("context_length", "unknown")
            # Quantization: check in model name or details
            quant = "unknown"
            model_name_lower = name.lower()
            if any(q in model_name_lower for q in ["q4", "q5", "q8"]):
                quant = "q4" if "q4" in model_name_lower else ("q5" if "q5" in model_name_lower else "q8")
            elif "quantized" in model_name_lower:
                quant = "quantized"
            # Parameter count
            param_count = details.get("parameter_count", "unknown")
            model_details = {
                "name": name,
                "size": size,
                "size_gb": round(size_gb, 2),
                "estimated_vram_gb": round(vram_estimate, 2),
                "usable": vram_estimate <= VRAM_GB,
                "recommended_tasks": determine_recommended_tasks(details, size_gb),
                "context_length": context,
                "quantization": quant,
                "parameter_count": param_count
            }
        report["models"].append(model_details)

    return report

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Inspect local AI models (Ollama).')
    parser.add_argument('--output', default='models.json', help='Output JSON file path')
    args = parser.parse_args()

    report = inspect_models()
    with open(args.output, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Model inspection report saved to {args.output}")