"""Builds Shared/pinyin-dictionary.txt from the Android Open Source Project's Pinyin dictionary.

Source: rawdict_utf16_65105_freq.txt in platform/packages/inputmethods/PinyinIME, Apache License 2.0.
Each source line holds a word, a frequency, a flag and the word's Pinyin syllables. Flag 1 marks a
character outside the common GB2312 set, and this build leaves those out.

The output holds one word per line as "syllables<TAB>word<TAB>frequency", with the most frequent
word first. The keyboard reads the file top to bottom, so the candidates for a spelling keep that
order, and it uses the frequencies to pick the most likely sentence for a run of syllables.

Usage, from the repository root:
    python scripts/pinyin-dictionary/build_dictionary.py
"""
import base64
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_URL = (
    "https://android.googlesource.com/platform/packages/inputmethods/PinyinIME/"
    "+/refs/heads/main/jni/data/rawdict_utf16_65105_freq.txt?format=TEXT"
)
CACHE = ROOT / "build" / "pinyin-source" / "rawdict_utf16.txt"
OUTPUT = ROOT / "Shared" / "pinyin-dictionary.txt"

if not CACHE.exists():
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(SOURCE_URL) as response:
        CACHE.write_bytes(base64.b64decode(response.read()))

entries = []
for line in CACHE.read_bytes().decode("utf-16").splitlines():
    parts = line.split(" ")
    if len(parts) < 4:
        raise SystemExit(f"unexpected source line: {line!r}")
    word, frequency, flag, syllables = parts[0], float(parts[1]), parts[2], parts[3:]
    if flag != "0":
        continue
    if len(syllables) != len(word):
        raise SystemExit(f"syllable count does not match the word length: {line!r}")
    entries.append((frequency, " ".join(syllables), word))

entries.sort(key=lambda entry: -entry[0])
text = "".join(f"{key}\t{word}\t{frequency:.5g}\n" for frequency, key, word in entries)
OUTPUT.write_text(text, encoding="utf-8", newline="\n")
syllable_set = {key for _, key, _ in entries if " " not in key}
print(f"wrote {OUTPUT.relative_to(ROOT)}: {len(entries)} words, {len(syllable_set)} syllables, {len(text.encode('utf-8'))} bytes")
