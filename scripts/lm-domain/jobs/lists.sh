#!/usr/bin/env bash
# Job: the training and stopping lists of the domain round, with the work area on (WSL).
# A list file that exists is left as it is, so the job is safe to start again.
set -euo pipefail
shim="$HOME/lmdom/bin/libduo_shim.so"
data=build/lm-domain/data
mkdir -p "$data/everyday-pack-on"
build() {  # build OUT CASES...
  out="$1"; shift
  if [ -f "$out" ]; then echo "$out is already there"; return; fi
  stem="${out%.jsonl.gz}"
  nice -n 10 python3 scripts/lm-domain/build_lists3.py --shim "$shim" --workers 8 --cases "$@" --out "$stem.part.jsonl.gz"
  mv "$stem.part-report.json" "$stem-report.json"
  mv "$stem.part.jsonl.gz" "$out"
}
# The stopping lists come first: every arm of the queue reads them.
build "$data/domain/lists.stop.jsonl.gz" "$data/domain/cases.stop.jsonl"
build "$data/domain/lists.train.jsonl.gz" "$data/domain/cases.train.jsonl"
build "$data/everyday-pack-on/lists.stop.jsonl.gz" "$data/everyday/cases.stop.jsonl" "$data/everyday/cases2.stop.jsonl"
build "$data/everyday-pack-on/lists.train.jsonl.gz" "$data/everyday/cases.train.jsonl" "$data/everyday/cases2.train.jsonl"
sha256sum "$data"/domain/*.gz "$data"/everyday-pack-on/*.gz | tee "$data/lists-sha256.txt"
