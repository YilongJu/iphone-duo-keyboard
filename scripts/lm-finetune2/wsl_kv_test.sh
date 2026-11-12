#!/usr/bin/env bash
# Tests whether the 16-bit key and value cache of llama.cpp explains the score difference between
# PyTorch and lm_score on the f16 file. It builds two copies of lm_score.c that differ from the
# original in one setting each, scores the first 500 parity requests of an arm with the f16 file,
# and prints the difference from the PyTorch float32 scores for each copy.
#   kv16_plain:  the cache holds 16-bit floats as in lm_score.c, flash attention off
#   kv32_plain:  the cache holds 32-bit floats (type_k and type_v), flash attention off
# llama.cpp b4846 aborts with a 32-bit cache and flash attention on, so that pair is not tested.
# Usage, in WSL: bash scripts/lm-finetune2/wsl_kv_test.sh ARM [ARM ...]
set -euo pipefail
cd /mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-finetune2
export LD_LIBRARY_PATH="$HOME/lmft/llama/lib"
work="$HOME/lmft2/kv-test"
mkdir -p "$work"
sed 's|context_settings.no_perf = true;|context_settings.no_perf = true; context_settings.type_k = GGML_TYPE_F32; context_settings.type_v = GGML_TYPE_F32;|' \
  scripts/lm-rerank/lm_score.c > "$work/lm_score_kv32.c"
sed 's|context_settings.flash_attn = true;|context_settings.flash_attn = false;|' "$work/lm_score_kv32.c" > "$work/lm_score_kv32_plain.c"
sed 's|context_settings.flash_attn = true;|context_settings.flash_attn = false;|' scripts/lm-rerank/lm_score.c > "$work/lm_score_kv16_plain.c"
grep -c "GGML_TYPE_F32" "$work/lm_score_kv32_plain.c" > /dev/null
for name in kv16_plain kv32_plain; do
  gcc -std=c11 -O2 -Wall -Wextra -Werror -I "$HOME/lmft/llama/include" "$work/lm_score_$name.c" \
    -L "$HOME/lmft/llama/lib" -lllama -lggml -lggml-cpu -lggml-base -lm -o "$work/lm_score_$name"
done
for arm in "$@"; do
  parity="build/lm-finetune2/parity/$arm"
  for name in kv16_plain kv32_plain; do
    head -n 500 "$parity/requests.tsv" | nice -n 19 "$work/lm_score_$name" "$HOME/lmft2/models/$arm.f16.gguf" 2 > "$parity/scores-$name.txt" 2> /dev/null
  done
  python3 - "$parity" "$arm" <<'PY'
import json, sys
from pathlib import Path
parity, arm = Path(sys.argv[1]), sys.argv[2]
torch_scores = [pair[0] for line in (parity / "hf-scores.jsonl").read_text().splitlines() for pair in json.loads(line)]
def read(name):
    lines = (parity / name).read_text().splitlines()[1:]
    return [float(field.split(" ")[0]) for line in lines for field in line.split("\t")]
for label, name in (("lm_score as it is, 16-bit cache", "gaps-f16.txt"), ("16-bit cache, flash attention off", "scores-kv16_plain.txt"), ("32-bit cache, flash attention off", "scores-kv32_plain.txt")):
    scores = read(name)
    gaps = [abs(a - b) for a, b in zip(torch_scores, scores)]
    print(f"{arm}: {label}: largest {max(gaps):.4f}, mean {sum(gaps) / len(gaps):.5f}, over 0.05: {sum(g > 0.05 for g in gaps)} of {len(gaps)}")
PY
done
