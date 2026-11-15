#!/usr/bin/env bash
# Job: turns each model of the shortlist into GGUF files with the converter of llama.cpp b12017:
# a file of 16-bit weights, then Q8_0 (the reference of the agreement), Q4_K_M (the type of the
# keyboard's file) and Q4_0.
# Usage, from the repository root in WSL, after jobs/setup.sh and jobs/venv.sh: convert.sh
# The 16-bit files stay on the Windows drive in build/model-speed/f16. The other files go to
# $HOME/modelspeed/gguf, where the speed runs read them.
set -euo pipefail
work="${MODEL_SPEED_WORK:-$HOME/modelspeed}"
python="$work/venv/bin/python"
llama="$work/llama-b12017"
mkdir -p build/model-speed/f16 "$work/gguf"
export LD_LIBRARY_PATH="$llama/lib"
for name in $(python3 -c "import json; print(' '.join(m['name'] for m in json.load(open('scripts/model-speed/models.json'))['models']))"); do
  f16="build/model-speed/f16/$name.f16.gguf"
  if [ ! -s "$f16" ]; then
    "$python" "$work/src-b12017/convert_hf_to_gguf.py" "build/model-speed/hf/$name" --outtype f16 --outfile "$f16.part"
    mv "$f16.part" "$f16"
  fi
  for type in Q8_0 Q4_K_M Q4_0; do
    out="$work/gguf/$name.$type.gguf"
    if [ ! -s "$out" ]; then
      "$llama/bin/llama-quantize" "$f16" "$out.part" "$type" 2
      mv "$out.part" "$out"
    fi
  done
  echo "converted $name"
done
ls -la "$work/gguf"
