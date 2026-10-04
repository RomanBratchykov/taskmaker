#!/usr/bin/env python3


"""Terminal chat for Ollama — smart orchestrator with context management.

Features:
  • Real-time context tracking + automatic compression when near limit
  • Compressed snapshots saved to temp files for audit/recovery
  • Rich tool-set tuned for 4 B-parameter models (short, explicit schemas)
  • Web search via DuckDuckGo HTML scrape — no API key needed
  • Skill loader: reads ./skills/**/*.md and injects them into system prompt
  • OS-safety layer: blocks dangerous shell patterns, mandatory confirmation

Setup:  pip install ollama requests lxml
Run:    python chat.py [--model qwen3:4b] [--ctx 8192]

Commands (at the > prompt):
  /model <name>   switch active model
  /think          toggle chain-of-thought
  /reset          clear history (keeps system prompt)
  /compress       manually compress now
  /skills         list loaded skills
  /help           show commands
  /exit
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import textwrap
import time
import traceback
from datetime import datetime
from typing import Any

import ollama

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_MODEL = "qwen3:4b"
HELPERS: dict[str, str] = {
    "coder":   "qwen2.5-coder:3b",
    "fast":    "qwen3:1.7b",
    "general": "gemma3:4b",
}
DEFAULT_CTX  = 8192          # tokens Ollama reserves per session
CTX_WARN     = 0.80          # compress when used tokens > 80 % of limit
CTX_CRITICAL = 0.92          # hard-compress: drop oldest non-system turns
MAX_STEPS    = 10            # max tool rounds per user message
MAX_OUT      = 3000          # max chars returned by any single tool
WORKDIR      = pathlib.Path.cwd().resolve()
SKILLS_DIR   = WORKDIR / "skills"
COMPRESS_DIR = pathlib.Path(tempfile.gettempdir()) / "chat_compress"
COMPRESS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------
DIM   = "\033[2m"
BOLD  = "\033[1m"
CYAN  = "\033[36m"
YELLOW = "\033[33m"
RED   = "\033[31m"
RESET = "\033[0m"

def dim(s: str)    -> str: return f"{DIM}{s}{RESET}"
def bold(s: str)   -> str: return f"{BOLD}{s}{RESET}"
def cyan(s: str)   -> str: return f"{CYAN}{s}{RESET}"
def yellow(s: str) -> str: return f"{YELLOW}{s}{RESET}"
def red(s: str)    -> str: return f"{RED}{s}{RESET}"


# ---------------------------------------------------------------------------
# Skills loader
# ---------------------------------------------------------------------------
_LOADED_SKILLS: dict[str, str] = {}

def load_skills() -> str:
    """Scan SKILLS_DIR for *.md files, return concatenated skill text."""
    global _LOADED_SKILLS
    _LOADED_SKILLS = {}
    if not SKILLS_DIR.is_dir():
        return ""
    for md in sorted(SKILLS_DIR.rglob("*.md")):
        name = md.stem
        try:
            text = md.read_text(errors="replace")[:2000]
            _LOADED_SKILLS[name] = text
        except Exception:
            pass
    if not _LOADED_SKILLS:
        return ""
    parts = [f"## Skill: {n}\n{t}" for n, t in _LOADED_SKILLS.items()]
    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# OS-safety layer
# ---------------------------------------------------------------------------
# Patterns that are blocked outright (never sent to model either)
_BLOCKED_PATTERNS = [
    r"rm\s+-rf\s+/",           # wipe root
    r"dd\s+if=.*of=/dev/",     # write to raw device
    r"mkfs\.",                  # format filesystem
    r">\s*/dev/sd[a-z]",       # overwrite block device
    r"chmod\s+-R\s+777\s+/",   # chmod root recursively
    r"shutdown|reboot|halt|poweroff",
    r":()\{.*\};:",             # fork bomb
    r"curl.*\|.*sh",           # curl-pipe-sh
    r"wget.*\|.*sh",
    r"base64.*\|.*bash",
    r"/etc/passwd",
    r"/etc/shadow",
    r"sudo\s+rm",
]
_BLOCKED_RE = re.compile("|".join(_BLOCKED_PATTERNS), re.IGNORECASE)

_SUSPICIOUS_PATTERNS = [
    r"\brm\b.*-[rf]",
    r"\bmv\b.*\s+/",
    r"\bkill\b",
    r"\bpkill\b",
    r"\bchmod\b",
    r"\bchown\b",
    r"\bcrontab\b",
    r"\bnohup\b",
    r"\b&\s*$",   # background job
    r"\bsudo\b",
]
_SUSPICIOUS_RE = re.compile("|".join(_SUSPICIOUS_PATTERNS), re.IGNORECASE)


def check_command_safety(cmd: str) -> tuple[bool, str]:
    """Return (is_safe, reason). Blocked commands are never safe."""
    if _BLOCKED_RE.search(cmd):
        return False, "BLOCKED: command matches a permanently disallowed pattern"
    if _SUSPICIOUS_RE.search(cmd):
        return True, "SUSPICIOUS"  # still requires user confirmation
    return True, "OK"


def confirm(action: str, default_deny: bool = True) -> bool:
    prompt_hint = "[y/N]" if default_deny else "[Y/n]"
    try:
        ans = input(f"{yellow(f'Allow {action}?')} {dim(prompt_hint)} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return ans == "y" if default_deny else ans != "n"


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------
def safe_path(path: str) -> pathlib.Path:
    p = (WORKDIR / path).expanduser().resolve()
    if p != WORKDIR and WORKDIR not in p.parents:
        raise ValueError(f"path '{p}' is outside working directory '{WORKDIR}'")
    return p


# ---------------------------------------------------------------------------
# Context token estimation
# ---------------------------------------------------------------------------
def estimate_tokens(text: str) -> int:
    """Fast token estimator: ~1 token per 3.5 chars."""
    return max(1, len(text) // 4)


def msgs_token_count(msgs: list[dict]) -> int:
    total = 0
    for m in msgs:
        total += estimate_tokens(m.get("content") or "")
        for tc in (m.get("tool_calls") or []):
            total += estimate_tokens(json.dumps(tc))
    return total


# ---------------------------------------------------------------------------
# Context compression
# ---------------------------------------------------------------------------
def _snapshot_to_file(msgs: list[dict]) -> pathlib.Path:
    """Save current messages to a compressed JSON temp file."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    h  = hashlib.md5(str(time.time()).encode()).hexdigest()[:6]
    fp = COMPRESS_DIR / f"ctx_{ts}_{h}.json"
    fp.write_text(json.dumps(msgs, ensure_ascii=False, indent=2))
    return fp


def summarise_with_model(model: str, text: str, num_ctx: int) -> str:
    """Ask the model for a concise summary (used during compression)."""
    prompt = (
        "Summarise the following conversation excerpt into a compact paragraph "
        "preserving all important facts, decisions, file names, and code snippets. "
        "Be extremely concise.\n\n" + text[:6000]
    )
    try:
        r = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"num_ctx": num_ctx},
        )
        return r.message.content.strip()
    except Exception as e:
        # fallback: truncate
        return text[:1500] + f"\n[...compressed, summarisation failed: {e}]"


def compress_context(
    msgs: list[dict],
    model: str,
    num_ctx: int,
    keep_last_n: int = 4,
) -> list[dict]:
    """
    Compress context:
    1. Save snapshot to temp file.
    2. Summarise the middle portion (between system msg and last N turns).
    3. Return new shorter message list.
    """
    snapshot_path = _snapshot_to_file(msgs)
    print(dim(f"[context] snapshot → {snapshot_path}"))

    system_msgs = [m for m in msgs if m.get("role") == "system"]
    non_system  = [m for m in msgs if m.get("role") != "system"]

    if len(non_system) <= keep_last_n:
        # nothing meaningful to compress
        return msgs

    to_compress = non_system[:-keep_last_n]
    keep        = non_system[-keep_last_n:]

    # Build a readable block for summarisation
    excerpt_lines = []
    for m in to_compress:
        role    = m.get("role", "?")
        content = m.get("content") or ""
        excerpt_lines.append(f"[{role}]: {content[:800]}")
    excerpt = "\n".join(excerpt_lines)

    print(dim(f"[context] compressing {len(to_compress)} turns → summary …"))
    summary = summarise_with_model(model, excerpt, num_ctx)

    summary_msg = {
        "role": "system",
        "content": (
            f"[COMPRESSED HISTORY — full log in {snapshot_path}]\n{summary}"
        ),
    }

    new_msgs = system_msgs + [summary_msg] + keep
    saved = msgs_token_count(msgs) - msgs_token_count(new_msgs)
    print(dim(f"[context] freed ~{saved} tokens"))
    return new_msgs


def maybe_compress(msgs: list[dict], model: str, num_ctx: int) -> list[dict]:
    """Check token budget and compress if needed."""
    used  = msgs_token_count(msgs)
    ratio = used / num_ctx
    if ratio >= CTX_CRITICAL:
        print(yellow(f"[context] CRITICAL {ratio:.0%} used — compressing now"))
        return compress_context(msgs, model, num_ctx, keep_last_n=2)
    if ratio >= CTX_WARN:
        print(dim(f"[context] {ratio:.0%} used — soft-compressing"))
        return compress_context(msgs, model, num_ctx, keep_last_n=6)
    return msgs


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def list_dir(path: str = ".") -> str:
    """List files and folders in a directory.

    Args:
        path: Directory path relative to working directory. Default is '.'.
    """
    items = sorted(safe_path(path).iterdir())
    lines = [f"{i.name}{'/' if i.is_dir() else ''}" for i in items]
    return "\n".join(lines)[:MAX_OUT]


def read_file(path: str, start_line: int = 1, end_line: int = 0) -> str:
    """Read text file content, optionally a line range.

    Args:
        path: File path relative to working directory.
        start_line: First line to return (1-based, default 1).
        end_line: Last line to return inclusive (0 = all remaining).
    """
    text = safe_path(path).read_text(errors="replace")
    if start_line > 1 or end_line:
        lines = text.splitlines()
        sl = max(0, start_line - 1)
        el = end_line if end_line else len(lines)
        text = "\n".join(lines[sl:el])
    return text[:MAX_OUT]


def write_file(path: str, content: str) -> str:
    """Write text to a file (replaces file). Requires user confirmation.

    Args:
        path: File path relative to working directory.
        content: Full new file content.
    """
    p = safe_path(path)
    if not confirm(f"write {len(content)} chars → {p}"):
        return "Denied by user."
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"OK: wrote {p} ({len(content)} chars)"


def append_file(path: str, content: str) -> str:
    """Append text to a file. Requires user confirmation.

    Args:
        path: File path relative to working directory.
        content: Text to append.
    """
    p = safe_path(path)
    if not confirm(f"append {len(content)} chars → {p}"):
        return "Denied by user."
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(content)
    return f"OK: appended {len(content)} chars to {p}"


def run_shell(command: str) -> str:
    """Run a safe shell command and return output. Requires confirmation.

    Args:
        command: Shell command. Must not modify the OS or installed software.
    """
    ok, reason = check_command_safety(command)
    if not ok:
        return f"Error: {reason}"
    warning = f" ⚠ {reason}" if reason != "OK" else ""
    if not confirm(f"shell{warning}: {command}"):
        return "Denied by user."
    try:
        r = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=60, cwd=WORKDIR,
        )
        out = f"exit={r.returncode}\n{r.stdout}{r.stderr}"
        return out[:MAX_OUT]
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 60 s"
    except MemoryError:
        return "Error: command produced too much output (MemoryError)"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


def search_web(query: str, max_results: int = 5) -> str:
    """Search the internet via DuckDuckGo and return concise results.

    Args:
        query: Search terms.
        max_results: How many results to return (1–10, default 5).
    """
    import urllib.parse
    import urllib.request
    from lxml import html as lxml_html

    max_results = max(1, min(10, max_results))
    q = urllib.parse.quote_plus(query)
    url = f"https://html.duckduckgo.com/html/?q={q}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        req  = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=10)
        body = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"Search error: {e}"

    try:
        tree    = lxml_html.fromstring(body)
        results = tree.cssselect(".result__body") or tree.cssselect(".result")
        lines   = []
        for res in results[:max_results]:
            title_el  = res.cssselect(".result__title a") or res.cssselect("a")
            snippet_el = res.cssselect(".result__snippet") or res.cssselect(".snippet")
            title   = title_el[0].text_content().strip()  if title_el   else "(no title)"
            snippet = snippet_el[0].text_content().strip() if snippet_el else ""
            href    = title_el[0].get("href", "") if title_el else ""
            # DDG wraps links — extract real URL
            if "uddg=" in href:
                href = urllib.parse.unquote(href.split("uddg=")[-1].split("&")[0])
            lines.append(f"• {title}\n  {href}\n  {snippet[:300]}")
        return ("\n\n".join(lines) or "No results found.")[:MAX_OUT]
    except Exception as e:
        return f"Parse error: {e}\nRaw (first 500):\n{body[:500]}"


def fetch_page(url: str) -> str:
    """Fetch a web page and return its main text content (no JS).

    Args:
        url: Full URL starting with http:// or https://.
    """
    import urllib.request
    from lxml import html as lxml_html

    if not url.startswith(("http://", "https://")):
        return "Error: URL must start with http:// or https://"
    try:
        req  = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; chatpy/1.0)"},
        )
        resp = urllib.request.urlopen(req, timeout=15)
        body = resp.read(200_000).decode("utf-8", errors="replace")
    except MemoryError:
        return "Error: page too large (MemoryError)"
    except Exception as e:
        return f"Fetch error: {e}"

    try:
        tree = lxml_html.fromstring(body)
        # Remove script / style noise
        for bad in tree.cssselect("script, style, nav, footer, header"):
            bad.drop_tree()
        text = tree.text_content()
        # Collapse whitespace
        text = re.sub(r"\n{3,}", "\n\n", text.strip())
        return text[:MAX_OUT]
    except Exception:
        # Fallback: strip HTML tags with regex
        text = re.sub(r"<[^>]+>", "", body)
        return text[:MAX_OUT]


def delegate(role: str, task: str) -> str:
    """Send a task to a specialist model and return its response.

    Args:
        role: One of 'coder' (code tasks), 'fast' (quick lookups), 'general' (text/analysis).
        task: Complete self-contained task description with all needed context.
    """
    model = HELPERS.get(role)
    if not model:
        return f"Unknown role '{role}'. Available: {', '.join(HELPERS)}"
    print(dim(f"[delegate → {model}]"))
    try:
        r = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": task}],
            options={"num_ctx": _CTX},
        )
        return (r.message.content or "")[:MAX_OUT]
    except ollama.ResponseError as e:
        return f"Delegate error ({model}): {e}"


def read_skill(name: str) -> str:
    """Return the raw content of a loaded skill by name.

    Args:
        name: Skill name as shown by /skills command.
    """
    text = _LOADED_SKILLS.get(name)
    if text is None:
        avail = ", ".join(_LOADED_SKILLS) or "(none)"
        return f"Skill '{name}' not found. Available: {avail}"
    return text[:MAX_OUT]


TOOLS = {
    f.__name__: f
    for f in (list_dir, read_file, write_file, append_file,
               run_shell, search_web, fetch_page, delegate, read_skill)
}


# ---------------------------------------------------------------------------
# System prompt factory
# ---------------------------------------------------------------------------
def build_system(skills_text: str) -> str:
    base = textwrap.dedent(f"""\
        You are a local terminal assistant running on Ollama.
        Working directory: {WORKDIR}
        Current time: {datetime.now().strftime('%Y-%m-%d %H:%M')}

        Rules:
        - Use tools when you need real data — never invent file contents or command output.
        - Prefer short, specific tool calls; do not chain more than 3 per reply.
        - For substantial code, use delegate(role='coder').
        - For quick factual answers, use delegate(role='fast').
        - For internet queries, use search_web() then fetch_page() if you need page content.
        - Be concise; the user reads in a terminal.
        - NEVER suggest commands that alter system software, users, or device files.
    """)
    if skills_text:
        base += f"\n\n# Loaded Skills\n{skills_text}"
    return base


# ---------------------------------------------------------------------------
# Chat engine
# ---------------------------------------------------------------------------
_CTX: int = DEFAULT_CTX


def stream_reply(model: str, msgs: list, think: bool) -> tuple[str, list]:
    """Stream one model turn. Returns (text, tool_calls)."""
    text, calls, in_think = "", [], False
    try:
        stream = ollama.chat(
            model=model,
            messages=msgs,
            tools=list(TOOLS.values()),
            think=think,
            stream=True,
            options={"num_ctx": _CTX},
        )
        for chunk in stream:
            m = chunk.message
            if m.thinking:
                if not in_think:
                    print(dim("‹think›"), end=" ", flush=True)
                    in_think = True
                print(dim(m.thinking), end="", flush=True)
            if m.content:
                if in_think:
                    print(f"\n{dim('‹/think›')}")
                    in_think = False
                text += m.content
                print(m.content, end="", flush=True)
            if m.tool_calls:
                calls.extend(m.tool_calls)
    except MemoryError:
        print(red("\n[MemoryError during stream — context may be too large]"))
    except ollama.ResponseError as e:
        print(red(f"\n[Ollama error: {e}]"))
        raise
    finally:
        if in_think:
            print()
    print()
    return text, calls


def run_tool(call: Any) -> str:
    name = call.function.name
    args = call.function.arguments or {}
    print(dim(f"  ↳ {name}({', '.join(f'{k}={v!r}' for k,v in args.items())})"))
    fn = TOOLS.get(name)
    if not fn:
        return f"Unknown tool: {name}"
    try:
        result = str(fn(**args))
        # Guard against absurdly large tool results
        if len(result) > MAX_OUT:
            result = result[:MAX_OUT] + "\n[...truncated]"
        return result
    except MemoryError:
        return "Error: MemoryError — tool produced too much data"
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


def turn(model: str, msgs: list[dict], think: bool, num_ctx: int) -> list[dict]:
    """Run one full user-turn (with tool loops). Returns updated msgs."""
    for step in range(MAX_STEPS):
        # Compress before each step if needed
        msgs = maybe_compress(msgs, model, num_ctx)

        text, calls = stream_reply(model, msgs, think)
        msgs.append({
            "role": "assistant",
            "content": text,
            "tool_calls": calls or None,
        })
        if not calls:
            return msgs

        for c in calls:
            result = run_tool(c)
            msgs.append({
                "role": "tool",
                "tool_name": c.function.name,
                "content": result,
            })

    print(dim(f"[stopped: {MAX_STEPS} tool rounds reached]"))
    return msgs


def supports_tools(model: str) -> bool:
    try:
        caps = ollama.show(model).capabilities or []
        return "tools" in caps
    except Exception:
        return True   # optimistic default


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def print_help():
    print(cyan(textwrap.dedent("""\
        Commands:
          /model <name>    switch active model
          /think           toggle chain-of-thought (thinking tokens)
          /reset           clear history (keep system prompt)
          /compress        compress context now and save snapshot
          /skills          list loaded skills
          /ctx             show current context token usage
          /help            this message
          /exit            quit
    """)))


def main() -> None:
    global _CTX

    parser = argparse.ArgumentParser(description="Ollama chat orchestrator")
    parser.add_argument("--model",  default=DEFAULT_MODEL)
    parser.add_argument("--ctx",    type=int, default=DEFAULT_CTX)
    parser.add_argument("--think",  action="store_true")
    args = parser.parse_args()

    _CTX  = args.ctx
    model = args.model
    think = args.think

    # Load skills
    skills_text = load_skills()
    if skills_text:
        print(dim(f"[skills] loaded: {', '.join(_LOADED_SKILLS)}"))

    system = build_system(skills_text)
    msgs: list[dict] = [{"role": "system", "content": system}]

    if not supports_tools(model):
        print(yellow(f"[warn] {model} does not report 'tools' capability — continuing anyway"))

    print(bold(cyan("Ollama chat")) + f"  model={model}  ctx={_CTX}  think={think}")
    print(dim("Type /help for commands\n"))

    while True:
        # ---- read user input ----
        try:
            line = input(f"{cyan('>')} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if not line:
            continue

        # ---- commands ----
        if line == "/exit":
            return

        if line == "/help":
            print_help()
            continue

        if line == "/think":
            think = not think
            print(f"think={think}")
            continue

        if line == "/reset":
            msgs = [{"role": "system", "content": system}]
            print("history cleared")
            continue

        if line == "/compress":
            msgs = compress_context(msgs, model, _CTX)
            continue

        if line == "/skills":
            if _LOADED_SKILLS:
                for n in _LOADED_SKILLS:
                    print(f"  {n}")
            else:
                print(dim("no skills loaded (place .md files in ./skills/)"))
            continue

        if line == "/ctx":
            used  = msgs_token_count(msgs)
            ratio = used / _CTX
            bar   = "█" * int(ratio * 20) + "░" * (20 - int(ratio * 20))
            print(f"  [{bar}] {used}/{_CTX} tokens ({ratio:.0%})")
            continue

        if line.startswith("/model "):
            new_model = line.split(maxsplit=1)[1].strip()
            if new_model:
                model = new_model
                has_tools = supports_tools(model)
                print(f"model={model}" + ("" if has_tools else dim("  (no tool support)")))
            continue

        # ---- normal message ----
        msgs.append({"role": "user", "content": line})
        try:
            msgs = turn(model, msgs, think, _CTX)
        except KeyboardInterrupt:
            print(dim("\n[interrupted]"))
        except ollama.ResponseError as e:
            print(red(f"\nOllama error: {e}"))
            if think:
                print(dim("Hint: try /think to disable thinking mode"))
        except MemoryError:
            print(red("\n[MemoryError] Forcing compression …"))
            msgs = compress_context(msgs, model, _CTX, keep_last_n=2)
        except Exception:
            print(red(f"\n[unexpected error]"))
            traceback.print_exc()
            sys.stdout.flush()


if __name__ == "__main__":
    main()