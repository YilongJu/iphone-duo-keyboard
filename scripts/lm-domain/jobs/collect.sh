#!/usr/bin/env bash
# Job: the sample of build-bucket sentences of the domain text (collect_train_sentences.py), in WSL.
# The job starts again from nothing: a clone that a stop left half done is not safe to reuse.
set -euo pipefail
out=build/lm-domain/corpus
if [ -f "$out/sentences.build.jsonl" ] && [ -f "$out/licences.json" ]; then
  echo "the sample is already in $out"
  exit 0
fi
rm -rf "$out"
nice -n 10 python3 scripts/lm-domain/collect_train_sentences.py --out "$out"
rm -rf "$out/raw"
sha256sum "$out/sentences.build.jsonl" "$out/licences.json" | tee "$out/sha256.txt"
