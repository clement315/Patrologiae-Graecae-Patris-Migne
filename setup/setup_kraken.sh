#!/usr/bin/env bash
# =====================================================================
#  PG OCR - Kraken environment inside WSL2 Ubuntu
#
#  Run inside Ubuntu (WSL):
#     bash setup/setup_kraken.sh
#
#  - installs uv + Python 3.11 + kraken (with CUDA PyTorch, ~3 GB download)
#  - environment lives in ~/kraken-env (inside the Ubuntu disk on E:)
#  - project data stays on Windows: /mnt/e/PG_OCR
#  - safe to re-run
# =====================================================================
set -euo pipefail

PG_ROOT="/mnt/e/PG_OCR"
ENV_DIR="$HOME/kraken-env"

step() { printf '\n\033[1;36m=== %s ===\033[0m\n' "$1"; }

step "1/5  Check that WSL can see the GPU and the project folder"
if command -v nvidia-smi >/dev/null 2>&1 || [ -x /usr/lib/wsl/lib/nvidia-smi ]; then
    nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader \
        || /usr/lib/wsl/lib/nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader \
        || true
else
    echo "WARNING: nvidia-smi not found in WSL. Update the NVIDIA driver on Windows."
    echo "         (Do NOT install a Linux NVIDIA driver inside WSL.)"
fi
if [ -d "$PG_ROOT" ]; then
    echo "Project folder found: $PG_ROOT"
else
    echo "WARNING: $PG_ROOT not found - was setup_pg_ocr.ps1 run with the default E:\\PG_OCR?"
fi

step "2/5  Install basic system packages"
echo ">>> If you see '[sudo] password for $USER:', type your Ubuntu password (it stays invisible) and press Enter."
sudo apt-get update -y
sudo apt-get install -y curl ca-certificates build-essential

step "3/5  Install uv (Python package manager)"
if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
uv --version

step "4/5  Create Python 3.11 env and install kraken  [~3 GB download]"
if [ ! -x "$ENV_DIR/bin/python" ]; then
    uv venv "$ENV_DIR" --python 3.11 --python-preference only-managed
fi
uv pip install --python "$ENV_DIR/bin/python" kraken lxml shapely tqdm

step "5/5  Check kraken, ketos and GPU"
"$ENV_DIR/bin/python" - <<'EOF'
import sys
import torch
import kraken
from importlib.metadata import version
print("Python      :", sys.version.split()[0])
print("kraken      :", version("kraken"))
print("PyTorch     :", torch.__version__, "| CUDA build", torch.version.cuda)
ok = torch.cuda.is_available()
print("CUDA usable :", ok)
if ok:
    p = torch.cuda.get_device_properties(0)
    print("GPU         : %s, %.1f GB" % (p.name, p.total_memory / 1024 ** 3))
    x = torch.randn(2048, 2048, device="cuda")
    (x @ x).sum().item()
    print("GPU test    : matrix multiply OK")
else:
    print("WARNING: CUDA not usable inside WSL -> training would run on CPU")
EOF
"$ENV_DIR/bin/ketos" --help >/dev/null && echo "ketos       : OK"
"$ENV_DIR/bin/kraken" --help >/dev/null && echo "kraken CLI  : OK"

# Convenience: one command to enter the environment later
START="$HOME/pg.sh"
cat > "$START" <<EOF
export PATH="\$HOME/.local/bin:\$PATH"
source "$ENV_DIR/bin/activate"
cd "$PG_ROOT" 2>/dev/null || true
echo "Kraken environment ready (\$(kraken --version 2>/dev/null | head -n1))"
EOF
grep -q "alias pg=" "$HOME/.bashrc" 2>/dev/null || echo "alias pg='source \$HOME/pg.sh'" >> "$HOME/.bashrc"

printf '\n\033[1;32mALL CHECKS DONE.\033[0m  Next time in Ubuntu just type:  pg\n'
