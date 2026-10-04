#!/usr/bin/env python3
"""
chat.py – Terminal agent with tool use.
Backends: Ollama (streaming, think mode) and Bonsai 27B (OpenAI-compatible).

Usage:
    python chat.py [--backend ollama|bonsai] [--model <name>]

Slash commands:
    /backend ollama|bonsai   Switch backend mid-conversation
    /model <name>            Switch model
    /think                   Toggle thinking mode (Ollama only)
    /reset                   Clear conversation history
    /status                  Show current config + server health
    /stop                    Stop Bonsai server (if this script started it)
    /exit  or  Ctrl-D        Exit
    /help                    Show this message
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Optional

# ─── ANSI colours ─────────────────────────────────────────────────────────────
RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
CYAN    = "\033[36m"
GREEN   = "\033[32m"
YELLOW  = "\033[33m"
RED     = "\033[31m"
MAGENTA = "\033[35m"

def cprint(color: str, text: str, end: str = "\n") -> None:
    print(f"{color}{text}{RESET}", end=end, flush=True)

# ─── Tool JSON schemas ────────────────────────────────────────────────────────

def _schema(name: str, description: str, props: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": props, "required": required},
        },
    }

TOOLS = [
    _schema(
        "list_dir",
        "List files and directories at a path. Path must stay inside the working directory.",
        {"path": {"type": "string", "description": "Relative path to list. Use '.' for CWD."}},
        ["path"],
    ),
    _schema(
        "read_file",
        "Read the contents of a file. Path must stay inside the working directory.",
        {"path": {"type": "string", "description": "Relative path to the file."}},
        ["path"],
    ),
    _schema(
        "write_file",
        "Write content to a file (asks confirmation). Path must stay inside the working directory.",
        {
            "path":    {"type": "string", "description": "Relative path to write."},
            "content": {"type": "string", "description": "Content to write."},
        },
        ["path", "content"],
    ),
    _schema(
        "run_shell",
        "Run a shell command (asks confirmation). Timeout: 30 s.",
        {"command": {"type": "string", "description": "Shell command to execute."}},
        ["command"],
    ),
    _schema(
        "delegate",
        "Delegate a sub-task to a named role (planner, coder, reviewer, …).",
        {
            "role": {"type": "string", "description": "Role name for the sub-agent."},
            "task": {"type": "string", "description": "Task description."},
        },
        ["role", "task"],
    ),
]

# ─── Safety + file sandbox ────────────────────────────────────────────────────
CWD = Path.cwd().resolve()

def _safe_path(rel: str) -> Path:
    p = (CWD / rel).resolve()
    if not str(p).startswith(str(CWD)):
        raise PermissionError(f"Path '{rel}' escapes the working directory.")
    return p

def _confirm(prompt: str) -> bool:
    try:
        return input(f"{YELLOW}{prompt} [y/N]{RESET} ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False

# ─── Tool implementations ──────────────────────────────────────────────────────

def tool_list_dir(path: str) -> str:
    try:
        p = _safe_path(path)
        if not p.exists():
            return f"Error: does not exist: {path}"
        if p.is_file():
            return f"'{path}' is a file, not a directory."
        entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
        lines = [
            f"{'📁' if e.is_dir() else '📄'} {e.name}"
            + (f"  ({e.stat().st_size:,} B)" if e.is_file() else "")
            for e in entries
        ]
        return "\n".join(lines) if lines else "(empty directory)"
    except PermissionError as exc:
        return f"Permission error: {exc}"
    except Exception as exc:
        return f"Error: {exc}"


def tool_read_file(path: str) -> str:
    try:
        p = _safe_path(path)
        if not p.exists():
            return f"Error: not found: {path}"
        if not p.is_file():
            return f"Error: '{path}' is not a file."
        text = p.read_text(errors="replace")
        if len(text) > 20_000:
            text = text[:20_000] + "\n\n[…truncated at 20 000 chars…]"
        return text
    except PermissionError as exc:
        return f"Permission error: {exc}"
    except Exception as exc:
        return f"Error: {exc}"


def tool_write_file(path: str, content: str) -> str:
    try:
        p = _safe_path(path)
        action = "overwrite" if p.exists() else "create"
        cprint(YELLOW, f"[write_file] About to {action} '{path}' ({len(content):,} chars)")
        if not _confirm("Proceed?"):
            return "Write cancelled by user."
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"Written {len(content):,} chars to '{path}'."
    except PermissionError as exc:
        return f"Permission error: {exc}"
    except Exception as exc:
        return f"Error: {exc}"


def tool_run_shell(command: str) -> str:
    cprint(YELLOW, f"[run_shell] $ {command}")
    if not _confirm("Run this command?"):
        return "Command cancelled by user."
    try:
        r = subprocess.run(
            command, shell=True, capture_output=True,
            text=True, timeout=30, cwd=str(CWD),
        )
        out = r.stdout[:8000] + ("\n[stdout truncated]" if len(r.stdout) > 8000 else "")
        err = r.stderr[:2000] + ("\n[stderr truncated]" if len(r.stderr) > 2000 else "")
        parts = []
        if out.strip(): parts.append(f"stdout:\n{out}")
        if err.strip(): parts.append(f"stderr:\n{err}")
        parts.append(f"exit code: {r.returncode}")
        return "\n".join(parts)
    except subprocess.TimeoutExpired:
        return "Error: timed out after 30 s."
    except Exception as exc:
        return f"Error: {exc}"


def tool_delegate(role: str, task: str) -> str:
    return (
        f"[delegate → {role}] Task:\n{task}\n\n"
        "Proceed step by step using the available tools."
    )


TOOL_FN = {
    "list_dir":  tool_list_dir,
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "run_shell": tool_run_shell,
    "delegate":  tool_delegate,
}


def dispatch_tool(name: str, arguments: str | dict) -> str:
    if name not in TOOL_FN:
        return f"Unknown tool: {name}"
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments)
        except json.JSONDecodeError as exc:
            return f"Tool error: invalid JSON for '{name}': {exc}"
    else:
        args = arguments
    try:
        return TOOL_FN[name](**args)
    except TypeError as exc:
        return f"Tool error ({name}): bad arguments – {exc}"
    except Exception as exc:
        return f"Tool error ({name}): {exc}"

# ─── Neutral history helpers ──────────────────────────────────────────────────

def make_msg(role: str, content: str = "", **kw) -> dict:
    m: dict[str, Any] = {"role": role, "content": content}
    m.update(kw)
    return m

# ─── Bonsai server management ──────────────────────────────────────────────────
BONSAI_PORT    = 8080
BONSAI_BASE    = f"http://127.0.0.1:{BONSAI_PORT}/v1"
BONSAI_LOG     = Path.home() / ".bonsai-server.log"
BONSAI_DIR     = Path.home() / "Bonsai-demo"
_bonsai_proc: Optional[subprocess.Popen] = None   # only set if we started it


def _http_get(url: str, timeout: int = 3) -> Optional[bytes]:
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read()
    except Exception:
        return None


def bonsai_is_up() -> bool:
    return _http_get(f"{BONSAI_BASE}/models") is not None


def bonsai_model_name() -> Optional[str]:
    raw = _http_get(f"{BONSAI_BASE}/models", timeout=5)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data["data"][0]["id"] if data.get("data") else None
    except Exception:
        return None


def _unload_ollama_models() -> None:
    """Ask Ollama to unload all running models to free VRAM."""
    raw = _http_get("http://127.0.0.1:11434/api/ps")
    if not raw:
        return
    try:
        data = json.loads(raw)
        import urllib.request
        for m in data.get("models", []):
            name = m.get("name", "")
            if not name:
                continue
            payload = json.dumps({"model": name, "keep_alive": 0}).encode()
            req = urllib.request.Request(
                "http://127.0.0.1:11434/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                urllib.request.urlopen(req, timeout=10)
            except Exception:
                pass
        cprint(DIM, "Ollama models unloaded from VRAM.")
    except Exception:
        pass


def start_bonsai(ctx_size: Optional[int] = None) -> bool:
    global _bonsai_proc
    if bonsai_is_up():
        cprint(GREEN, "Bonsai server already running.")
        return True

    launcher = BONSAI_DIR / "scripts" / "start_llama_server.sh"
    if not launcher.exists():
        cprint(RED, f"Bonsai launcher not found: {launcher}")
        cprint(RED, "Run setup.sh first (it clones Bonsai-demo and downloads the model).")
        return False

    _unload_ollama_models()

    env = os.environ.copy()
    env.update({
        "BONSAI_FAMILY":           "bonsai",
        "BONSAI_MODEL":            "27B",
        "BONSAI_OPENWEBUI":        "0",
        "BONSAI_CODE_INTERPRETER": "0",
    })
    if ctx_size:
        env["BONSAI_CTX"] = str(ctx_size)

    cprint(CYAN, f"Starting Bonsai server (log → {BONSAI_LOG}) …")
    log_fh = BONSAI_LOG.open("w")
    _bonsai_proc = subprocess.Popen(
        ["bash", str(launcher)],
        env=env, stdout=log_fh, stderr=subprocess.STDOUT,
        cwd=str(BONSAI_DIR),
    )

    for i in range(240):
        if _bonsai_proc.poll() is not None:
            cprint(RED, f"Bonsai server exited early (code {_bonsai_proc.returncode}). "
                        f"See {BONSAI_LOG}")
            return False
        if bonsai_is_up():
            cprint(GREEN, f"Bonsai server up after {i+1} s  [{BONSAI_BASE}]")
            return True
        time.sleep(1)
        if i % 30 == 29:
            cprint(YELLOW, f"  …waiting for Bonsai ({i+1}/240 s)")

    cprint(RED, f"Bonsai did not respond in 240 s. See {BONSAI_LOG}")
    return False


def stop_bonsai() -> None:
    global _bonsai_proc
    if _bonsai_proc is None:
        return
    cprint(YELLOW, "Stopping Bonsai server …")
    _bonsai_proc.terminate()
    try:
        _bonsai_proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        _bonsai_proc.kill()
    _bonsai_proc = None
    cprint(GREEN, "Bonsai server stopped.")

# ─── History conversion ───────────────────────────────────────────────────────

def _to_ollama_msgs(history: list[dict]) -> list[dict]:
    out = []
    for m in history:
        role, content = m["role"], m.get("content", "")
        if role == "tool":
            out.append({"role": "tool", "content": content, "name": m.get("name", "")})
        elif role == "assistant" and m.get("tool_calls"):
            out.append({"role": "assistant", "content": content or "", "tool_calls": m["tool_calls"]})
        else:
            out.append({"role": role, "content": content})
    return out


def _to_openai_msgs(history: list[dict]) -> list[dict]:
    out = []
    for m in history:
        role, content = m["role"], m.get("content", "")
        if role == "tool":
            out.append({"role": "tool", "tool_call_id": m.get("tool_call_id", "0"), "content": content})
        elif role == "assistant" and m.get("tool_calls"):
            out.append({"role": "assistant", "content": content or None, "tool_calls": m["tool_calls"]})
        else:
            out.append({"role": role, "content": content})
    return out

# ─── Backend: Ollama ──────────────────────────────────────────────────────────
SYSTEM_OLLAMA = (
    "You are a helpful terminal agent. Tools available: list_dir, read_file, "
    "write_file, run_shell, delegate. File access is limited to the current working directory. "
    "Use tools as needed to complete the user's request."
)

def chat_ollama(history: list[dict], model: str, think: bool) -> tuple[str, list[dict], float]:
    """Returns (reply, tool_calls, tok/s)."""
    try:
        import ollama as _ollama
    except ImportError:
        cprint(RED, "ollama package missing. Activate the venv: source .venv/bin/activate")
        return "", [], 0.0

    msgs = [{"role": "system", "content": SYSTEM_OLLAMA}] + _to_ollama_msgs(history)
    options: dict = {"num_ctx": 8192}
    if think:
        options["think"] = True

    try:
        response = _ollama.chat(model=model, messages=msgs, tools=TOOLS, stream=True, options=options)
    except Exception as exc:
        cprint(RED, f"Ollama error: {exc}")
        return "", [], 0.0

    full = ""
    thinking = ""
    tool_calls: list[dict] = []
    eval_count = 0
    eval_dur_ns = 0

    for chunk in response:
        msg   = chunk.get("message", {})
        delta = msg.get("content", "") or ""
        think_delta = msg.get("thinking", "") or ""

        if think_delta:
            if not thinking:
                print(f"\n{DIM}[thinking]", end="", flush=True)
            print(f"{DIM}{think_delta}{RESET}", end="", flush=True)
            thinking += think_delta

        if delta:
            if not full and not thinking:
                print()
            print(delta, end="", flush=True)
            full += delta

        if msg.get("tool_calls"):
            tool_calls.extend(msg["tool_calls"])

        if chunk.get("done"):
            eval_count  = chunk.get("eval_count", 0)
            eval_dur_ns = chunk.get("eval_duration", 0)

    print()
    tps = eval_count / (eval_dur_ns / 1e9) if eval_dur_ns > 0 else 0.0
    return full, tool_calls, tps

# ─── Backend: Bonsai (OpenAI-compatible) ─────────────────────────────────────
SYSTEM_BONSAI = (
    "You are a helpful terminal agent. Tools: list_dir, read_file, write_file, run_shell, delegate. "
    "File access is limited to the current working directory. "
    "Call at most one tool per step. Use exact file paths."
)

def chat_bonsai(history: list[dict], model: str) -> tuple[str, list[dict], float]:
    """Returns (reply, tool_calls, tok/s)."""
    try:
        import openai as _openai
    except ImportError:
        cprint(RED, "openai package missing. Activate the venv: source .venv/bin/activate")
        return "", [], 0.0

    client = _openai.OpenAI(base_url=BONSAI_BASE, api_key="none")
    msgs = [{"role": "system", "content": SYSTEM_BONSAI}] + _to_openai_msgs(history)

    try:
        stream = client.chat.completions.create(
            model=model, messages=msgs, tools=TOOLS,
            tool_choice="auto", stream=True,
            temperature=1.0, top_p=0.95, max_tokens=4096,
        )
    except Exception as exc:
        if "Connection" in str(exc) or "refused" in str(exc):
            cprint(RED, "Bonsai server is down. Use /backend ollama or restart.")
        else:
            cprint(RED, f"Bonsai API error: {exc}")
        return "", [], 0.0

    full = ""
    reasoning = ""
    tc_accum: dict[int, dict] = {}   # index → {id, name, arguments}
    completion_tokens = 0
    t0 = time.monotonic()

    for chunk in stream:
        choice = chunk.choices[0] if chunk.choices else None
        if not choice:
            continue
        delta = choice.delta

        # Reasoning / thinking tokens (shown dimmed)
        rc = getattr(delta, "reasoning_content", None) or ""
        if rc:
            if not reasoning:
                print(f"\n{DIM}[thinking]", end="", flush=True)
            print(f"{DIM}{rc}{RESET}", end="", flush=True)
            reasoning += rc

        # Regular content
        dc = delta.content or ""
        if dc:
            if not full:
                if reasoning:
                    print(f"\n{RESET}", end="", flush=True)
                else:
                    print()
            print(dc, end="", flush=True)
            full += dc
            completion_tokens += 1

        # Tool-call fragments (assembled by index)
        if delta.tool_calls:
            for tc in delta.tool_calls:
                idx = tc.index
                if idx not in tc_accum:
                    tc_accum[idx] = {"id": "", "name": "", "arguments": ""}
                if tc.id:
                    tc_accum[idx]["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        tc_accum[idx]["name"] += tc.function.name
                    if tc.function.arguments:
                        tc_accum[idx]["arguments"] += tc.function.arguments

        if hasattr(chunk, "usage") and chunk.usage:
            completion_tokens = getattr(chunk.usage, "completion_tokens", completion_tokens) or completion_tokens

    print()
    elapsed = time.monotonic() - t0
    tps = completion_tokens / elapsed if elapsed > 0 and completion_tokens > 0 else 0.0

    # Parse accumulated tool calls; bad JSON becomes a tool error at dispatch time
    tool_calls: list[dict] = []
    for idx in sorted(tc_accum):
        raw = tc_accum[idx]
        args_str = raw["arguments"]
        parse_err: Optional[str] = None
        try:
            json.loads(args_str)
        except json.JSONDecodeError:
            parse_err = args_str
            args_str = "{}"

        tool_calls.append({
            "id":   raw["id"] or f"call_{idx}",
            "type": "function",
            "function": {"name": raw["name"], "arguments": args_str},
            "_parse_error": parse_err,
        })

    return full, tool_calls, tps

# ─── Agent loop ───────────────────────────────────────────────────────────────
MAX_TOOL_ROUNDS = 8


class Agent:
    def __init__(self, backend: str = "ollama"):
        self.backend = backend
        self.model: Optional[str] = None
        self.think  = False
        self.history: list[dict] = []

    def _default_model(self) -> str:
        return "qwen3:4b" if self.backend == "ollama" else (bonsai_model_name() or "bonsai-27b")

    def _ensure_model(self) -> None:
        if self.model is None:
            self.model = self._default_model()

    def _ensure_bonsai(self) -> bool:
        if not bonsai_is_up():
            cprint(CYAN, "Bonsai server not running – auto-starting …")
            return start_bonsai()
        return True

    def switch_backend(self, new: str) -> None:
        if new not in ("ollama", "bonsai"):
            cprint(RED, "Backend must be 'ollama' or 'bonsai'."); return
        old = self.backend
        self.backend = new
        self.model   = None
        if old == "bonsai" and new == "ollama":
            stop_bonsai()
        cprint(GREEN, f"Backend → {new}  (model will auto-select on next message)")

    def chat(self, user_input: str) -> None:
        self._ensure_model()

        if self.backend == "bonsai" and not self._ensure_bonsai():
            cprint(RED, "Cannot connect to Bonsai. Run setup.sh first."); return

        self.history.append(make_msg("user", user_input))

        for tool_round in range(MAX_TOOL_ROUNDS + 1):
            # Print the backend header on the same line as model reply
            cprint(BOLD + CYAN, f"\n[{self.backend}:{self.model}]", end=" ")
            sys.stdout.flush()

            if self.backend == "ollama":
                reply, raw_tcs, tps = chat_ollama(self.history, self.model, self.think)
            else:
                reply, raw_tcs, tps = chat_bonsai(self.history, self.model)

            cprint(DIM, f"  [{tps:.1f} tok/s]")

            # Normalise tool_calls to OpenAI format for storage
            norm_tcs: list[dict] = []
            for tc in raw_tcs:
                if self.backend == "ollama":
                    fn = tc.get("function", {})
                    args = fn.get("arguments", {})
                    norm_tcs.append({
                        "id":   tc.get("id", f"call_{len(norm_tcs)}"),
                        "type": "function",
                        "function": {
                            "name": fn.get("name", ""),
                            "arguments": json.dumps(args) if isinstance(args, dict) else args,
                        },
                    })
                else:
                    norm_tcs.append(tc)   # already normalised in chat_bonsai

            asst: dict = {"role": "assistant", "content": reply}
            if norm_tcs:
                asst["tool_calls"] = norm_tcs
            self.history.append(asst)

            if not norm_tcs or tool_round >= MAX_TOOL_ROUNDS:
                if tool_round >= MAX_TOOL_ROUNDS and norm_tcs:
                    cprint(YELLOW, f"[reached max tool rounds ({MAX_TOOL_ROUNDS})]")
                break

            cprint(MAGENTA, f"\n[tool round {tool_round + 1}/{MAX_TOOL_ROUNDS}]")
            for tc in norm_tcs:
                fn        = tc.get("function", {})
                name      = fn.get("name", "")
                raw_args  = fn.get("arguments", "{}")
                tc_id     = tc.get("id", "0")
                parse_err = tc.get("_parse_error")

                cprint(MAGENTA,
                       f"  → {name}({raw_args[:120]}{'…' if len(raw_args) > 120 else ''})")

                if parse_err is not None:
                    result = f"Tool error: could not parse arguments JSON: {parse_err!r}"
                else:
                    result = dispatch_tool(name, raw_args)

                cprint(DIM, f"  ← {result[:300]}{'…' if len(result) > 300 else ''}")
                self.history.append(make_msg("tool", result, tool_call_id=tc_id, name=name))

    def status(self) -> None:
        self._ensure_model()
        print(f"  Backend : {BOLD}{self.backend}{RESET}")
        print(f"  Model   : {self.model}")
        print(f"  Think   : {self.think}  (Ollama only)")
        print(f"  History : {len(self.history)} messages")
        print(f"  CWD     : {CWD}")
        if self.backend == "bonsai":
            up = bonsai_is_up()
            mn = bonsai_model_name() if up else "—"
            print(f"  Bonsai  : {'✅ up' if up else '❌ down'}  model={mn}")
            if _bonsai_proc:
                print(f"  Bonsai PID (this session): {_bonsai_proc.pid}")
        else:
            ok = _http_get("http://127.0.0.1:11434") is not None
            print(f"  Ollama  : {'✅ up' if ok else '❌ down'}")

# ─── REPL ─────────────────────────────────────────────────────────────────────
HELP_TEXT = """
Commands:
  /backend ollama|bonsai   Switch backend (stops/starts servers as needed)
  /model <name>            Change active model
  /think                   Toggle thinking mode (Ollama only)
  /reset                   Clear conversation history
  /status                  Show current config + server health
  /stop                    Stop Bonsai server if started by this script
  /exit  or  Ctrl-D        Exit
  /help                    Show this help
"""


def repl(agent: Agent) -> None:
    cprint(BOLD + GREEN, "Terminal Agent  •  type /help for commands")
    cprint(DIM, f"Backend: {agent.backend}  •  CWD: {CWD}")

    while True:
        try:
            line = input(f"\n{BOLD}{GREEN}you>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            stop_bonsai()
            cprint(YELLOW, "Goodbye.")
            break

        if not line:
            continue

        if line.startswith("/"):
            parts = line.split(maxsplit=1)
            cmd   = parts[0].lower()
            arg   = parts[1].strip() if len(parts) > 1 else ""

            if cmd == "/exit":
                stop_bonsai()
                cprint(YELLOW, "Goodbye."); break
            elif cmd == "/help":
                print(HELP_TEXT)
            elif cmd == "/reset":
                agent.history.clear()
                cprint(GREEN, "History cleared.")
            elif cmd == "/status":
                agent.status()
            elif cmd == "/think":
                if agent.backend == "ollama":
                    agent.think = not agent.think
                    cprint(GREEN, f"Thinking mode {'ON' if agent.think else 'OFF'}.")
                else:
                    cprint(YELLOW, "/think only applies to the Ollama backend.")
            elif cmd == "/stop":
                stop_bonsai()
            elif cmd == "/backend":
                if not arg: cprint(RED, "Usage: /backend ollama|bonsai")
                else:        agent.switch_backend(arg)
            elif cmd == "/model":
                if not arg: cprint(RED, "Usage: /model <name>")
                else:
                    agent.model = arg
                    cprint(GREEN, f"Model → {arg}")
            else:
                cprint(RED, f"Unknown command '{cmd}'. Type /help.")
        else:
            try:
                agent.chat(line)
            except KeyboardInterrupt:
                print()
                cprint(YELLOW, "[interrupted]")
            except Exception as exc:
                cprint(RED, f"Error: {exc}")
                cprint(DIM, traceback.format_exc())


def main() -> None:
    parser = argparse.ArgumentParser(description="Terminal agent – Ollama + Bonsai")
    parser.add_argument("--backend", choices=["ollama", "bonsai"], default="ollama")
    parser.add_argument("--model",   default=None, help="Override model name")
    args = parser.parse_args()

    agent = Agent(backend=args.backend)
    if args.model:
        agent.model = args.model

    if args.backend == "bonsai":
        if not agent._ensure_bonsai():
            cprint(RED, "Failed to start Bonsai. Run setup.sh first."); sys.exit(1)
        if agent.model is None:
            agent.model = bonsai_model_name() or "bonsai-27b"

    repl(agent)


if __name__ == "__main__":
    main()