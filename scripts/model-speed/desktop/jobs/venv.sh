#!/usr/bin/env bash
# Job: the Python environment of the desktop part of the speed test, in $HOME/modelspeed/venv.
# It holds the requirements of the converter of llama.cpp b12017 (torch for the processor,
# transformers, gguf from the source of that release) and safetensors.
# Usage, from the repository root in WSL, after jobs/setup.sh cloned llama.cpp: venv.sh
set -euo pipefail
work="${MODEL_SPEED_WORK:-$HOME/modelspeed}"
src="$work/src-b12017"
# The cache of uv stays on the Windows drive, because the disk of WSL is nearly full.
export PATH="/snap/bin:$PATH"
export UV_CACHE_DIR="$PWD/build/model-speed/uv-cache"
uv venv --python 3.12 "$work/venv"
VIRTUAL_ENV="$work/venv" uv pip install -r "$src/requirements/requirements-convert_hf_to_gguf.txt" safetensors
VIRTUAL_ENV="$work/venv" uv pip install -e "$src/gguf-py"
"$work/venv/bin/python" -c "import torch, transformers, gguf, safetensors; print('torch', torch.__version__, 'transformers', transformers.__version__)"
