#!/usr/bin/env bash
# Downloads the real typing-error data of the typo set into build/typo-set/download/, outside git,
# and stops when a file does not have its SHA-256 value. A file that is in place and matches is
# kept. Neither source states a licence that allows redistribution, so the files stay out of git.
#
#   Aalto mobile typing study, https://userinterfaces.aalto.fi/typing37k/ (no licence stated)
#   CSCD-NS, https://github.com/nghuyong/cscd-ime (code under MIT, data licence not stated),
#   from the Google Drive folder that the repository's README names. Needs gdown.
#
# Usage, from anywhere: bash scripts/typing-evaluation/typo-set/fetch_real_data.sh
set -euo pipefail
cd "$(dirname "$0")/../../.."
download="build/typo-set/download"

sha256_of() {
  if command -v sha256sum > /dev/null; then sha256sum "$1" | cut -d ' ' -f 1; else shasum -a 256 "$1" | cut -d ' ' -f 1; fi
}

check() {
  local path="$1" expected="$2" actual
  actual=$(sha256_of "$path")
  if [ "$actual" != "$expected" ]; then
    echo "error: $path has the SHA-256 value $actual, expected $expected" >&2
    rm -f "$path"
    exit 1
  fi
}

fetch_url() {
  local url="$1" path="$2" expected="$3"
  if [ -f "$path" ] && [ "$(sha256_of "$path")" = "$expected" ]; then echo "kept $path"; return 0; fi
  mkdir -p "$(dirname "$path")"
  curl --fail --location --silent --show-error --retry 3 --output "$path" "$url"
  check "$path" "$expected"
  echo "fetched $path"
}

fetch_drive() {
  local id="$1" path="$2" expected="$3"
  if [ -f "$path" ] && [ "$(sha256_of "$path")" = "$expected" ]; then echo "kept $path"; return 0; fi
  mkdir -p "$(dirname "$path")"
  python3 -m gdown --quiet "$id" -O "$path"
  check "$path" "$expected"
  echo "fetched $path"
}

fetch_url https://userinterfaces.aalto.fi/typing37k/data/processed_typing_data.zip \
  "$download/aalto37k/processed_typing_data.zip" 1187a500b83b915e1469878d25c32ddcee0e466a4f9b011b45a1d66653c142ae
fetch_url https://userinterfaces.aalto.fi/typing37k/resources/sentences_content.sql \
  "$download/aalto37k/sentences_content.sql" 8c111657a49b82f6e677deb49a917ee0a0399b9fd45091cfccb2c6d78a7ec30b
fetch_drive 1Fm0at3KLNjMFnrB3PO8K0OzxfK4uAj-T "$download/cscd/cscd-ns/train.tsv" \
  d5e3276a556dd890c5d26d82a15e9f7f61fee9d83cea899cb765cc45a2decdbf
fetch_drive 1HFCgGQcrvitTOo6D5RQHSXCDYs9mAX0X "$download/cscd/cscd-ns/dev.tsv" \
  68e6525cef92bbcc55b19e30803b210b39c41f042ac4a33dd76e2e05243e4cae
fetch_drive 1oDf1iZBod9rvk7T3MNU-ILqTE9X5UhGb "$download/cscd/cscd-ns/test.tsv" \
  81f6b719570472ab6a5ccb82f014ec58bf91cc244db9b70135fd5b824d7583da
