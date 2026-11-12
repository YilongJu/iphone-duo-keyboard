#!/usr/bin/env bash
# Job: builds the stopping lists again with the final pack, to count the lists that the pack's
# last frequency changes alter (WSL). compare_lists.py reads the result.
set -euo pipefail
out=build/lm-domain/data/final-pack-check
mkdir -p "$out"
python3 scripts/lm-domain/build_lists3.py --shim "$HOME/lmdom/bin/libduo_shim.so" --workers 10 \
  --cases build/lm-domain/data/domain/cases.stop.jsonl --out "$out/domain-stop.jsonl.gz"
python3 scripts/lm-domain/build_lists3.py --shim "$HOME/lmdom/bin/libduo_shim.so" --workers 10 \
  --cases build/lm-domain/data/everyday/cases.stop.jsonl build/lm-domain/data/everyday/cases2.stop.jsonl --out "$out/everyday-stop.jsonl.gz"
