#!/usr/bin/env bash
# Prints the versions of the English baseline engines and the checksums of their data files.
#
# Usage, from the repository root, on the Ubuntu runner after the engines are installed:
#   PYTHON=build/venv/bin/python bash scripts/typing-evaluation/engines/english-baselines/print_versions.sh [JAMSPELL_MODEL]
#
# Give the path of the JamSpell model file en.bin when JamSpell is installed.
set -euo pipefail

python="${PYTHON:?set PYTHON to the interpreter that holds the engines}"

echo "== System"
lsb_release -ds
uname -m
"$python" --version
uv --version

echo "== Python packages"
uv pip freeze --python "$python"

echo "== Hunspell packages and dictionary files"
dpkg-query -W -f='${Package} ${Version}\n' hunspell hunspell-en-us 'libhunspell*'
sha256sum /usr/share/hunspell/en_US.aff /usr/share/hunspell/en_US.dic
wc -l /usr/share/hunspell/en_US.dic
echo "-- settings in en_US.aff that steer suggestions"
grep -E '^(SET|KEY|TRY|REP [0-9]+$|MAP [0-9]+$|NOSPLITSUGS|MAXNGRAMSUGS|WORDCHARS)' /usr/share/hunspell/en_US.aff \
  || echo "en_US.aff does not hold any of these settings"
echo "-- start of /usr/share/doc/hunspell-en-us/copyright"
if [ -f /usr/share/doc/hunspell-en-us/copyright ]; then
  head -n 60 /usr/share/doc/hunspell-en-us/copyright
else
  echo "the runner image does not hold this file"
fi

echo "== License fields and data files of the Python packages"
"$python" - <<'EOF'
import hashlib
from importlib.metadata import metadata
from importlib.resources import files
from pathlib import Path

for package, module in (("symspellpy", "symspellpy"), ("pyspellchecker", "spellchecker")):
    info = metadata(package)
    licenses = [value for key, value in info.items() if key in ("License", "License-Expression") and len(value) < 80]
    licenses += [value for key, value in info.items() if key == "Classifier" and value.startswith("License")]
    print(f"{package} {info['Version']}  license fields: {licenses}")
    folder = Path(str(files(module)))
    for path in sorted(folder.rglob("*")):
        if path.is_file() and path.suffix not in (".py", ".pyc", ".typed"):
            data = path.read_bytes()
            print(f"  {path.relative_to(folder).as_posix()}  {len(data)} bytes  sha256 {hashlib.sha256(data).hexdigest()}")
EOF

if [ "$#" -ge 1 ]; then
  model="$1"
  echo "== JamSpell build tools, package and model"
  swig -version | grep -i version
  g++ --version | sed -n 1p
  uv pip show --python "$python" jamspell
  ls -l "$(dirname "$model")"
  sha256sum "$model"
fi
