#!/usr/bin/env python3
"""Terminal chat for Ollama with tool calling and multi-model delegation.

Setup:  pip install ollama
Run:    python chat.py
Commands: /model <name>  /think  /reset  /exit
"""
import pathlib
import subprocess
import sys

import ollama

MAIN_MODEL = "qwen3:4b"                # orchestrator, must support tools
HELPERS = {                            # models the main model can delegate to
    "coder": "qwen2.5-coder:3b",
    "general": "gemma3:4b",
}
NUM_CTX = 8192
MAX_STEPS = 8                          # max tool rounds per user message
MAX_OUT = 4000                         # max chars returned from a tool
WORKDIR = pathlib.Path.cwd().resolve()

DIM, RESET = "\033[2m", "\033[0m"


def safe_path(path: str) -> pathlib.Path:
    p = (WORKDIR / path).expanduser().resolve()
    if WORKDIR != p and WORKDIR not in p.parents:
        raise ValueError(f"path outside {WORKDIR}")
    return p


def confirm(action: str) -> bool:
    return input(f"{DIM}Allow {action}? [y/N] {RESET}").strip().lower() == "y"


# ---------- tools (docstrings are the schema the model sees) ----------

def list_dir(path: str = ".") -> str:
    """List files and folders in a directory.

    Args:
        path: Directory path relative to the working directory.
    """
    items = sorted(safe_path(path).iterdir())
    return "\n".join(f"{i.name}{'/' if i.is_dir() else ''}" for i in items)[:MAX_OUT]


def read_file(path: str) -> str:
    """Read a text file.

    Args:
        path: File path relative to the working directory.
    """
    return safe_path(path).read_text(errors="replace")[:MAX_OUT]


def write_file(path: str, content: str) -> str:
    """Write text to a file, replacing it. Asks the user for confirmation.

    Args:
        path: File path relative to the working directory.
        content: Full new file content.
    """
    p = safe_path(path)
    if not confirm(f"writing {len(content)} chars to {p}"):
        return "Denied by user."
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"Wrote {p}"


def run_shell(command: str) -> str:
    """Run a shell command and return stdout and stderr. Asks the user for confirmation.

    Args:
        command: The shell command to run.
    """
    if not confirm(f"command: {command}"):
        return "Denied by user."
    r = subprocess.run(command, shell=True, capture_output=True, text=True,
                       timeout=60, cwd=WORKDIR)
    return (f"exit={r.returncode}\n{r.stdout}{r.stderr}")[:MAX_OUT]


def delegate(role: str, task: str) -> str:
    """Send a self-contained task to a specialist model and return its answer.

    Args:
        role: "coder" for writing or reviewing code, "general" for other text tasks.
        task: Complete task description with all needed context.
    """
    model = HELPERS.get(role)
    if not model:
        return f"Unknown role. Use one of: {', '.join(HELPERS)}"
    print(f"{DIM}[delegate -> {model}]{RESET}")
    r = ollama.chat(model=model, messages=[{"role": "user", "content": task}],
                    options={"num_ctx": NUM_CTX})
    return r.message.content[:MAX_OUT]


TOOLS = {f.__name__: f for f in (list_dir, read_file, write_file, run_shell, delegate)}

SYSTEM = (
    f"You are a terminal assistant. Working directory: {WORKDIR}. "
    "Use tools when you need real data or actions; never invent file contents or command output. "
    "Use delegate(role='coder') for substantial code writing. Be concise."
)


# ---------- chat engine ----------

def stream_reply(model: str, msgs: list, think: bool):
    """Stream one model turn. Returns (text, tool_calls)."""
    text, calls, in_think = "", [], False
    stream = ollama.chat(model=model, messages=msgs, tools=list(TOOLS.values()),
                         think=think, stream=True, options={"num_ctx": NUM_CTX})
    for chunk in stream:
        m = chunk.message
        if m.thinking:
            in_think = True
            print(f"{DIM}{m.thinking}{RESET}", end="", flush=True)
        if m.content:
            if in_think:
                print()
                in_think = False
            text += m.content
            print(m.content, end="", flush=True)
        if m.tool_calls:
            calls.extend(m.tool_calls)
    print()
    return text, calls


def run_tool(call) -> str:
    name, args = call.function.name, call.function.arguments
    print(f"{DIM}[tool] {name}({args}){RESET}")
    fn = TOOLS.get(name)
    if not fn:
        return f"Unknown tool: {name}"
    try:
        return str(fn(**args))
    except Exception as e:  # return errors to the model so it can retry
        return f"Error: {type(e).__name__}: {e}"


def turn(model: str, msgs: list, think: bool) -> None:
    for _ in range(MAX_STEPS):
        text, calls = stream_reply(model, msgs, think)
        msgs.append({"role": "assistant", "content": text, "tool_calls": calls or None})
        if not calls:
            return
        for c in calls:
            msgs.append({"role": "tool", "tool_name": c.function.name, "content": run_tool(c)})
    print(f"{DIM}[stopped: {MAX_STEPS} tool rounds reached]{RESET}")


def supports_tools(model: str) -> bool:
    try:
        return "tools" in (ollama.show(model).capabilities or [])
    except Exception:
        return True  # unknown, try anyway


def main() -> None:
    model, think = MAIN_MODEL, False
    msgs = [{"role": "system", "content": SYSTEM}]
    if not supports_tools(model):
        print(f"Warning: {model} does not report 'tools' capability.")
    print(f"model={model} think={think} helpers={HELPERS}\n/model <name>  /think  /reset  /exit")

    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line == "/exit":
            return
        if line == "/reset":
            msgs = msgs[:1]
            print("history cleared")
            continue
        if line == "/think":
            think = not think
            print(f"think={think}")
            continue
        if line.startswith("/model "):
            model = line.split(maxsplit=1)[1]
            print(f"model={model}" + ("" if supports_tools(model) else "  (no tools support)"))
            continue

        msgs.append({"role": "user", "content": line})
        try:
            turn(model, msgs, think)
        except KeyboardInterrupt:
            print("\n[interrupted]")
        except ollama.ResponseError as e:
            print(f"\nOllama error: {e}")
            if think:
                print("Try /think to disable thinking.")
        except Exception as e:
            print(f"\nError: {type(e).__name__}: {e}")
            sys.stdout.flush()


if __name__ == "__main__":
    main()