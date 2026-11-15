#!/usr/bin/env bash
# Job: downloads the models of the shortlist and builds llama.cpp b12017 on Linux.
# Usage, from the repository root in WSL: setup.sh
# The files of Hugging Face go to build/model-speed/hf on the Windows drive, because the disk of
# WSL is nearly full. llama.cpp goes to $HOME/modelspeed.
set -euo pipefail
work="${MODEL_SPEED_WORK:-$HOME/modelspeed}"
mkdir -p "$work" build/model-speed
bash scripts/model-speed/desktop/fetch_models.sh build/model-speed
bash scripts/model-speed/desktop/build_llama.sh b12017 "$work"
