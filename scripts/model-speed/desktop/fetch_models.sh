#!/usr/bin/env bash
# Downloads the files of the models of scripts/model-speed/models.json at their fixed revisions.
# Usage, from the repository root: fetch_models.sh OUT_DIR [NAME]
# Each model goes to OUT_DIR/hf/<name>/. With NAME only that model. A file that is already in
# place is kept. The macOS workflow .github/workflows/model-speed.yml uses it too.
set -euo pipefail
out="$1"
only="${2:-}"
models="scripts/model-speed/models.json"
list=$(python3 - "$models" "$only" <<'PY'
import json, sys
chosen = [model for model in json.load(open(sys.argv[1]))["models"] if sys.argv[2] in ("", model["name"])]
if not chosen:
    raise SystemExit(f"no model named {sys.argv[2]}")
for model in chosen:
    for file in model["files"]:
        print("\t".join([model["name"], model["repo"], model["revision"], file]))
PY
)
# A Python on Windows ends its lines with a carriage return.
list=$(printf '%s\n' "$list" | tr -d '\r')
while IFS=$'\t' read -r name repo revision file; do
  dir="$out/hf/$name"
  mkdir -p "$dir"
  if [ -s "$dir/$file" ]; then
    continue
  fi
  curl --fail --location --silent --show-error --retry 3 --output "$dir/$file.part" \
    "https://huggingface.co/$repo/resolve/$revision/$file"
  mv "$dir/$file.part" "$dir/$file"
  echo "fetched $name/$file ($(wc -c < "$dir/$file" | tr -d ' ') bytes)"
done <<< "$list"
echo "models fetched"
