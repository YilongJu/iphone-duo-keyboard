#!/usr/bin/env bash
# Converts one exported arm the way the phone runs it, then checks token and score parity.
# It mirrors convert_arm.ps1 of the fine-tune: convert_hf_to_gguf.py of llama.cpp b4846 at f16 on
# Windows, llama-quantize in WSL, then check_parity.py prepare, lm_score, compare.
# Usage, from Git Bash: convert_edit.sh NAME [QUANT]
#   NAME is a folder under build/lm-weight-edit/models with an hf/ folder from sweep.py --export.
set -euo pipefail
name="$1"; quant="${2:-Q3_K_M}"
edit_root="/d/Github/iphone-duo-keyboard/build/worktrees/lm-edit"
finetune_root="/d/Github/iphone-duo-keyboard/build/worktrees/lm-finetune"
python="$finetune_root/build/lm-finetune/venv/Scripts/python.exe"
model="$edit_root/build/lm-weight-edit/models/$name"
wsl_model="/mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-edit/build/lm-weight-edit/models/$name"
export PYTHONDONTWRITEBYTECODE=1

"$python" "$finetune_root/build/lm-finetune/llama-convert/convert_hf_to_gguf.py" "$model/hf" --outtype f16 \
  --outfile "$model/model-f16.gguf" > "$model/convert.log" 2>&1
MSYS_NO_PATHCONV=1 wsl -d Ubuntu -- bash -lc "mkdir -p ~/lmedit/models && nice -n 19 ~/lmft/quantize-build/bin/llama-quantize $wsl_model/model-f16.gguf ~/lmedit/models/$name.$quant.gguf $quant 2 > $wsl_model/quantize.log 2>&1 && cp $wsl_model/model-f16.gguf ~/lmedit/models/$name.f16.gguf && sha256sum ~/lmedit/models/$name.$quant.gguf && stat -c '%s bytes' ~/lmedit/models/$name.$quant.gguf"

parity="$model/parity"
"$python" "$finetune_root/scripts/lm-finetune/check_parity.py" prepare --data "$finetune_root/build/lm-finetune/data" \
  --prompt-format typed --model-dir "$model/hf" --out "$parity" > "$model/parity-prepare.log" 2>&1
wsl_parity="$wsl_model/parity"
MSYS_NO_PATHCONV=1 wsl -d Ubuntu -- bash -lc "export LD_LIBRARY_PATH=~/lmft/llama/lib; nice -n 19 ~/lmft/bin/lm_score ~/lmedit/models/$name.$quant.gguf 2 tokens < $wsl_parity/requests.tsv > $wsl_parity/llama-tokens.txt 2> $wsl_parity/lm-tokens-stderr.txt && head -n 500 $wsl_parity/requests.tsv | nice -n 19 ~/lmft/bin/lm_score ~/lmedit/models/$name.f16.gguf 2 > $wsl_parity/llama-scores.txt 2> $wsl_parity/lm-scores-stderr.txt && head -n 500 $wsl_parity/requests.tsv | nice -n 19 ~/lmft/bin/lm_score ~/lmedit/models/$name.$quant.gguf 2 > $wsl_parity/llama-scores-quant.txt 2> $wsl_parity/lm-scores-quant-stderr.txt"
"$python" "$finetune_root/scripts/lm-finetune/check_parity.py" compare --out "$parity" 2>&1 | tail -3
