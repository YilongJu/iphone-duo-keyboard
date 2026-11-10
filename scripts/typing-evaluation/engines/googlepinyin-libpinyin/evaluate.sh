#!/usr/bin/env bash
# Steps of the googlepinyin and libpinyin evaluation, for Ubuntu 24.04 with the engine packages installed.
#
# Usage, from the repository root:
#   bash scripts/typing-evaluation/engines/googlepinyin-libpinyin/evaluate.sh versions
#   bash scripts/typing-evaluation/engines/googlepinyin-libpinyin/evaluate.sh build
#   bash scripts/typing-evaluation/engines/googlepinyin-libpinyin/evaluate.sh run dev test
#   bash scripts/typing-evaluation/engines/googlepinyin-libpinyin/evaluate.sh score dev test
#
# The packages: g++ pkg-config libglib2.0-dev libgooglepinyin0 libgooglepinyin0-dev
#               libpinyin15 libpinyin15-dev libpinyin-common-dev libpinyin-data
set -euo pipefail

GROUP=googlepinyin-libpinyin
HERE="scripts/typing-evaluation/engines/$GROUP"
PROGRAMS="build/engine-adapters/$GROUP"
OUTPUT="build/typing-evaluation"
PACKAGES=(libgooglepinyin0 libgooglepinyin0-dev libpinyin15 libpinyin15-dev libpinyin-common-dev libpinyin-data libglib2.0-dev)

# One engine name for each mode. set_command holds the settings behind each name.
NAMES=(
  googlepinyin
  googlepinyin-no-abbreviation
  libpinyin-default
  libpinyin-correction
  libpinyin-correction-incomplete
  libpinyin-correction-incomplete-fuzzy
)

if [ ! -f "$HERE/evaluate.sh" ]; then
  echo "evaluate.sh: run this script from the repository root" >&2
  exit 1
fi

# Fills COMMAND with the program and the arguments for one engine name.
# The second argument is a new, empty directory for the engine's user data.
set_command() {
  local name="$1" user="$2"
  case "$name" in
    googlepinyin)
      COMMAND=("$PROGRAMS/googlepinyin_cli" "$GOOGLE_DICTIONARY" "$user/user_dictionary.dat") ;;
    googlepinyin-no-abbreviation)
      COMMAND=("$PROGRAMS/googlepinyin_cli" "$GOOGLE_DICTIONARY" "$user/user_dictionary.dat" no-abbreviation) ;;
    libpinyin-default)
      COMMAND=("$PROGRAMS/libpinyin_cli" "$LIBPINYIN_DATA" "$user") ;;
    libpinyin-correction)
      COMMAND=("$PROGRAMS/libpinyin_cli" "$LIBPINYIN_DATA" "$user" correction) ;;
    libpinyin-correction-incomplete)
      COMMAND=("$PROGRAMS/libpinyin_cli" "$LIBPINYIN_DATA" "$user" correction incomplete) ;;
    libpinyin-correction-incomplete-fuzzy)
      COMMAND=("$PROGRAMS/libpinyin_cli" "$LIBPINYIN_DATA" "$user" correction incomplete fuzzy) ;;
    *)
      echo "evaluate.sh: unknown engine name $name" >&2
      exit 1 ;;
  esac
}

# Finds the packaged dictionary of each engine.
locate_data() {
  GOOGLE_DICTIONARY="$(dpkg -L libgooglepinyin0 | grep '/dict_pinyin\.dat$')"
  LIBPINYIN_DATA="$(pkg-config --variable=pkgdatadir libpinyin)/data"
  if [ ! -f "$GOOGLE_DICTIONARY" ]; then
    echo "evaluate.sh: the Google Pinyin dictionary is missing: $GOOGLE_DICTIONARY" >&2
    exit 1
  fi
  if [ ! -f "$LIBPINYIN_DATA/table.conf" ]; then
    echo "evaluate.sh: the libpinyin data is missing: $LIBPINYIN_DATA/table.conf" >&2
    exit 1
  fi
}

# Prints the lines of a header that match a pattern, each with the line after it.
show() {
  echo "-- $2"
  grep -n -A 1 -E "$1" "$2" || echo "the pattern $1 does not match a line in $2"
}

versions() {
  locate_data
  mkdir -p "$OUTPUT"
  {
    echo "== System"
    echo "runner image: ${ImageOS:-not set} ${ImageVersion:-not set}"
    grep -E '^(PRETTY_NAME|VERSION_ID)=' /etc/os-release
    uname -m
    g++ --version | head -n 1
    echo "pkg-config $(pkg-config --version)"
    python3 --version
    echo "== Packages"
    dpkg-query -W -f='${Package} ${Version} ${Architecture}\n' "${PACKAGES[@]}"
    echo "== pkg-config"
    echo "googlepinyin $(pkg-config --modversion googlepinyin): $(pkg-config --cflags --libs googlepinyin)"
    echo "libpinyin $(pkg-config --modversion libpinyin): $(pkg-config --cflags --libs libpinyin)"
    echo "== Google Pinyin dictionary"
    ls -l "$GOOGLE_DICTIONARY"
    sha256sum "$GOOGLE_DICTIONARY"
    echo "== libpinyin data"
    ls -l "$LIBPINYIN_DATA"
    find "$LIBPINYIN_DATA" -maxdepth 1 -type f -print0 | sort -z | xargs -0 sha256sum
    echo "== libpinyin table.conf"
    cat "$LIBPINYIN_DATA/table.conf"
  } | tee "$OUTPUT/$GROUP.versions.txt"

  # The lines below are a record for the reader of the log. A missing file or pattern prints a note.
  echo "== Package licenses"
  local package
  for package in libgooglepinyin0 libpinyin15 libpinyin-data; do
    echo "-- /usr/share/doc/$package/copyright"
    cat "/usr/share/doc/$package/copyright" || echo "the copyright file of $package is missing"
  done
  echo "== Declarations that the adapter programs call"
  local google_include libpinyin_include
  google_include="$(pkg-config --variable=includedir googlepinyin)"
  libpinyin_include="$(pkg-config --variable=libpinyinincludedir libpinyin)"
  ls "$google_include" "$libpinyin_include"
  show 'im_(open_decoder|close_decoder|reset_search|search|get_sps_str|get_candidate|enable_shm_as_szm|enable_ym_as_szm)\(' "$google_include/pinyinime.h"
  show 'typedef .* char16;' "$google_include/utf16char.h"
  show 'kMaxSearchSteps|kMaxLemmaSize =' "$google_include/dictdef.h"
  show 'pinyin_(init|fini|set_options|alloc_instance|free_instance|reset|parse_more_full_pinyins|guess_sentence|get_sentence)\(' "$libpinyin_include/pinyin.h"
  show 'PINYIN_INCOMPLETE|USE_DIVIDED_TABLE|USE_RESPLIT_TABLE|DYNAMIC_ADJUST|PINYIN_AMB_|PINYIN_CORRECT_' "$libpinyin_include/pinyin_custom2.h"
}

build() {
  mkdir -p "$PROGRAMS"
  local warnings=(-std=c++17 -O2 -Wall -Wextra -Wpedantic -Werror)
  # The engine headers go in as system headers, so the warning flags apply to the adapter code only.
  local text google_flags libpinyin_flags google_libraries libpinyin_libraries
  text="$(pkg-config --cflags googlepinyin | sed -E 's/(^| )-I/\1-isystem /g')"
  read -r -a google_flags <<< "$text"
  text="$(pkg-config --cflags libpinyin | sed -E 's/(^| )-I/\1-isystem /g')"
  read -r -a libpinyin_flags <<< "$text"
  text="$(pkg-config --libs googlepinyin)"
  read -r -a google_libraries <<< "$text"
  text="$(pkg-config --libs libpinyin)"
  read -r -a libpinyin_libraries <<< "$text"
  set -x
  g++ "${warnings[@]}" "${google_flags[@]}" "$HERE/googlepinyin_cli.cpp" "${google_libraries[@]}" -o "$PROGRAMS/googlepinyin_cli"
  g++ "${warnings[@]}" "${libpinyin_flags[@]}" "$HERE/libpinyin_cli.cpp" "${libpinyin_libraries[@]}" -o "$PROGRAMS/libpinyin_cli"
  { set +x; } 2>/dev/null
  ldd "$PROGRAMS/googlepinyin_cli" "$PROGRAMS/libpinyin_cli"
}

# Every engine name must turn the clean input nihao into the Chinese text for "hello".
smoke_test() {
  local name user log output expected
  expected="$(printf 'smoke\t\xe4\xbd\xa0\xe5\xa5\xbd')"
  log="$(mktemp)"
  for name in "${NAMES[@]}"; do
    user="$(mktemp -d)"
    set_command "$name" "$user"
    output="$(printf 'smoke\tnihao\n' | "${COMMAND[@]}" 2> "$log")" || {
      cat "$log" >&2
      echo "evaluate.sh: the smoke test of $name ended with an error" >&2
      exit 1
    }
    echo "smoke test of $name: nihao -> ${output#*$'\t'}"
    if [ "$output" != "$expected" ]; then
      echo "evaluate.sh: $name did not turn nihao into ${expected#*$'\t'}" >&2
      exit 1
    fi
  done
}

run() {
  locate_data
  smoke_test
  local half name user
  for half in "$@"; do
    for name in "${NAMES[@]}"; do
      user="$(mktemp -d)"
      set_command "$name" "$user"
      python3 "$HERE/run_adapter.py" --engine "$name" --half "$half" -- "${COMMAND[@]}"
    done
  done
}

score() {
  local half name
  mkdir -p "$OUTPUT"
  for half in "$@"; do
    for name in "${NAMES[@]}"; do
      python3 scripts/typing-evaluation/score.py --task pinyin --engine "$name" \
        --cases "scripts/typing-evaluation/cases/pinyin.$half.jsonl" \
        --predictions "$OUTPUT/$name/pinyin.$half.jsonl" \
        --json "$OUTPUT/$name/pinyin.$half.summary.json"
    done
  done | tee "$OUTPUT/$GROUP.scores.txt"
  # Google Pinyin reads 39 letters in one search, so the clean cases over 39 letters get a count of their own.
  for half in "$@"; do
    python3 "$HERE/score_by_length.py" --half "$half" --letters 39 "${NAMES[@]}"
  done | tee "$OUTPUT/$GROUP.clean-by-length.txt"
}

step="${1:-}"
if [ "$#" -gt 0 ]; then
  shift
fi
case "$step" in
  versions) versions ;;
  build) build ;;
  run|score)
    if [ "$#" -eq 0 ]; then
      echo "evaluate.sh: name the halves to use, dev or test" >&2
      exit 1
    fi
    "$step" "$@" ;;
  *)
    echo "evaluate.sh: the first argument must be versions, build, run or score" >&2
    exit 1 ;;
esac
