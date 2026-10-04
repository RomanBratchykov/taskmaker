#!/usr/bin/env bash
# setup.sh – idempotent installer for the terminal agent environment
# Run from anywhere; all paths are absolute.  Safe to re-run.
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()  { err "$*"; exit 1; }

# The venv lives next to this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

# ── 1. Prerequisites ──────────────────────────────────────────────────────────
echo "=== Checking prerequisites ==="

for cmd in git curl python3; do
  command -v "$cmd" &>/dev/null \
    && ok "$cmd → $(command -v "$cmd")" \
    || die "$cmd is required but not installed. Install with: sudo apt install $cmd"
done

python3 -c "import venv" &>/dev/null \
  && ok "python3 venv module available" \
  || die "python3-venv missing. Install with: sudo apt install python3-venv  (or python3.XX-venv)"

# ── 2. GPU check ──────────────────────────────────────────────────────────────
echo ""
echo "=== GPU check ==="
if command -v nvidia-smi &>/dev/null; then
  nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader 2>/dev/null \
    && ok "nvidia-smi OK" \
    || warn "nvidia-smi present but query failed (WSL2 passthrough partial?)"
else
  warn "nvidia-smi not found – Bonsai will run on CPU"
fi

# ── 3. Clock sanity check ─────────────────────────────────────────────────────
echo ""
echo "=== Clock sanity ==="
SYS_EPOCH=$(date +%s)
if [ "$SYS_EPOCH" -lt 1704067200 ]; then   # 2024-01-01
  warn "System clock looks wrong ($(date -u))."
  warn "TLS may fail. Fix with: sudo hwclock -s"
else
  ok "Clock OK: $(date -u)"
fi

# ── 4. Ollama ─────────────────────────────────────────────────────────────────
echo ""
echo "=== Ollama ==="
if command -v ollama &>/dev/null; then
  ok "Ollama already installed: $(ollama --version 2>/dev/null || echo 'version unknown')"
else
  echo "Installing Ollama (curl|sh from ollama.com)..."
  curl -fsSL https://ollama.com/install.sh | sh
  ok "Ollama installed"
fi

# Ensure server is running
if curl -sf http://127.0.0.1:11434 &>/dev/null; then
  ok "Ollama server running at http://127.0.0.1:11434"
else
  echo "Starting Ollama server in background..."
  nohup ollama serve &>/tmp/ollama-serve.log &
  for i in $(seq 1 30); do
    curl -sf http://127.0.0.1:11434 &>/dev/null && { ok "Ollama server up"; break; }
    sleep 1
    [ "$i" -eq 30 ] && die "Ollama server did not start within 30 s. See /tmp/ollama-serve.log"
  done
fi

# Pull required models (idempotent)
for MODEL in qwen3:4b qwen2.5-coder:3b; do
  if ollama list 2>/dev/null | awk '{print $1}' | grep -qxF "$MODEL"; then
    ok "Model $MODEL already pulled"
  else
    echo "Pulling $MODEL …"
    ollama pull "$MODEL"
    ok "Pulled $MODEL"
  fi
done

# ── 5. Python venv (local to this folder) ────────────────────────────────────
echo ""
echo "=== Python venv $VENV_DIR ==="
if [ -d "$VENV_DIR" ] && [ -f "$VENV_DIR/bin/python" ]; then
  ok "venv already exists"
else
  # Debian/Ubuntu Python 3.13 ships without ensurepip; handle gracefully
  if python3 -m venv "$VENV_DIR" 2>/dev/null; then
    ok "venv created (with pip)"
  else
    python3 -m venv --without-pip "$VENV_DIR"
    ok "venv skeleton created; bootstrapping pip via get-pip.py..."
    GET_PIP="/tmp/get-pip-taskmaker.py"
    curl -fsSL https://bootstrap.pypa.io/get-pip.py -o "$GET_PIP"
    "$VENV_DIR/bin/python" "$GET_PIP" --quiet
    rm -f "$GET_PIP"
    ok "pip bootstrapped"
  fi
fi

# Also bootstrap if pip is missing from a pre-existing --without-pip venv
if ! "$VENV_DIR/bin/pip" --version &>/dev/null 2>&1; then
  warn "pip missing in existing venv; bootstrapping..."
  GET_PIP="/tmp/get-pip-taskmaker.py"
  curl -fsSL https://bootstrap.pypa.io/get-pip.py -o "$GET_PIP"
  "$VENV_DIR/bin/python" "$GET_PIP" --quiet
  rm -f "$GET_PIP"
  ok "pip bootstrapped"
fi

"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet --upgrade ollama openai
ok "Packages installed: ollama openai"

# ── 6. Bonsai-demo ────────────────────────────────────────────────────────────
echo ""
echo "=== Bonsai-demo ==="
BONSAI_DIR="$HOME/Bonsai-demo"

if [ -d "$BONSAI_DIR/.git" ]; then
  ok "Already cloned at $BONSAI_DIR"
  git -C "$BONSAI_DIR" pull --ff-only 2>/dev/null \
    || warn "git pull failed (offline?); continuing with existing clone"
else
  echo "Cloning Bonsai-demo …"
  git clone https://github.com/PrismML-Eng/Bonsai-demo.git "$BONSAI_DIR"
  ok "Cloned to $BONSAI_DIR"
fi

# Skip model download if any bonsai .gguf already present
BONSAI_GGUF_FOUND=0
if [ -d "$BONSAI_DIR/models" ]; then
  if find "$BONSAI_DIR/models" -name "*.gguf" -size +100M 2>/dev/null | grep -qi "bonsai"; then
    BONSAI_GGUF_FOUND=1
    FOUND=$(find "$BONSAI_DIR/models" -name "*.gguf" -size +100M 2>/dev/null | grep -i "bonsai" | head -1)
    ok "Bonsai GGUF already present: $FOUND"
  fi
fi

cd "$BONSAI_DIR"
if [ "$BONSAI_GGUF_FOUND" -eq 0 ]; then
  echo "Running Bonsai setup.sh (BONSAI_FAMILY=bonsai BONSAI_MODEL=27B) …"
  echo "Downloads 1-bit Bonsai 27B weights (~3–4 GB). Please wait …"
fi

# Always run setup.sh so binaries are current; download is skipped if already present
BONSAI_FAMILY=bonsai \
BONSAI_MODEL=27B \
BONSAI_OPENWEBUI=0 \
BONSAI_CODE_INTERPRETER=0 \
BONSAI_SKIP_MLX=1 \
bash setup.sh

ok "Bonsai-demo setup complete"
cd - >/dev/null

# ── 7. Summary ────────────────────────────────────────────────────────────────
echo ""
echo "================================================================"
echo " Setup complete"
echo "================================================================"
echo ""
echo "  Workspace   : $SCRIPT_DIR"
echo "  Python venv : $VENV_DIR"
echo "  Ollama      : http://127.0.0.1:11434"
echo "  Bonsai      : http://127.0.0.1:8080  (auto-started by chat.py)"
echo ""
echo "  Run the agent:"
echo "    $VENV_DIR/bin/python $SCRIPT_DIR/chat.py --backend ollama"
echo "    $VENV_DIR/bin/python $SCRIPT_DIR/chat.py --backend bonsai"
echo ""
ollama list
