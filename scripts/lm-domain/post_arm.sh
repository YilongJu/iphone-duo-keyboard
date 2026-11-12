#!/usr/bin/env bash
# Converts one trained arm of the domain round the way the phone runs it (llama.cpp b4846, f16,
# then Q4_K_M), and checks its tokens and its scores against lm_score, on everyday lists and on
# domain lists. The quantized file goes to ~/lmdom/models in WSL, where run_eval_queue.py finds it.
# A score difference over the limit of check_parity.py is written to parity.json and to the log,
# and the script still ends with exit code 0, so the arm is scored. The report names the result.
# Usage, from Git Bash at the root of the worktree: bash scripts/lm-domain/post_arm.sh NAME
set -euo pipefail
name="$1"
root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$root"
python="$root/build/lm-domain/venv/Scripts/python.exe"
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2
out="build/lm-domain/models/$name"
wsl_root="/mnt/d/Github/iphone-duo-keyboard/build/worktrees/lm-domain"
if [ ! -f "$out/model-f16.gguf" ]; then
  "$python" build/lm-domain/llama-convert/convert_hf_to_gguf.py "$out/hf" --outtype f16 --outfile "$out/model-f16.part.gguf" > "$out/convert.log" 2>&1
  mv "$out/model-f16.part.gguf" "$out/model-f16.gguf"
fi
wsl.exe -d Ubuntu -- bash -lc "set -e; mkdir -p ~/lmdom/models; if [ ! -f ~/lmdom/models/$name.Q4_K_M.gguf ]; then nice -n 15 ~/lmft/quantize-build/bin/llama-quantize $wsl_root/$out/model-f16.gguf ~/lmdom/models/$name.part.gguf Q4_K_M 2 > $wsl_root/$out/quantize.log 2>&1; mv ~/lmdom/models/$name.part.gguf ~/lmdom/models/$name.Q4_K_M.gguf; fi; sha256sum ~/lmdom/models/$name.Q4_K_M.gguf | tee $wsl_root/$out/Q4_K_M.sha256; ls -l ~/lmdom/models/$name.Q4_K_M.gguf"
for lists in everyday domain; do
  parity="build/lm-domain/parity/$name/$lists"
  if [ -f "$parity/parity.json" ]; then continue; fi
  "$python" scripts/lm-finetune/check_parity.py prepare --data "build/lm-domain/data/parity-lists/$lists" \
    --prompt-format typed --model-dir "$out/hf" --out "$parity" > "$out/parity-prepare-$lists.log" 2>&1
  wsl.exe -d Ubuntu -- bash -lc "set -e; export LD_LIBRARY_PATH=~/lmft/llama/lib; cd $wsl_root; nice -n 15 ~/lmdom/bin/lm_score ~/lmdom/models/$name.Q4_K_M.gguf 2 tokens < $parity/requests.tsv > $parity/llama-tokens.txt 2> $parity/lm-tokens-stderr.txt; head -n 500 $parity/requests.tsv | nice -n 15 ~/lmdom/bin/lm_score $out/model-f16.gguf 2 > $parity/llama-scores.txt 2> $parity/lm-scores-stderr.txt"
  "$python" scripts/lm-finetune/check_parity.py compare --out "$parity" 2>&1 | tail -3 || echo "$name: the parity check on the $lists lists did not pass"
done
echo "$name: converted and checked"
