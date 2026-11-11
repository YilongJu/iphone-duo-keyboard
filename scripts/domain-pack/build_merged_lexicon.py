"""Builds the comparison lexicon of docs/domain-pack-design.md: the base English lexicon with the
words of the pack merged into it at build time.

The keyboard does not ship this file. It exists to measure the other way of bringing the pack to
the engine: one lexicon file per setting of the work area, in place of a supplement laid over the
base lexicon. scripts/lm-rerank/domain_pack.py types the same cases with either file.

A word that the base lexicon lacks comes in with its pack frequency and no word pair. A word
that the base lexicon holds keeps its pairs and takes the pack frequency when that is higher.

Usage, from the repository root:
    python3 scripts/domain-pack/build_merged_lexicon.py --out build/domain-pack/lexicon-english-merged.bin
"""
import argparse
import math
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "typing-engine"))
from lexicon_format import MODEL_MIXED, write_lexicon  # noqa: E402


def read_lexicon(path: Path) -> tuple[dict[str, float], dict[tuple[str, str], float]]:
    """The words of a version 2 lexicon with their log probability, and its pairs."""
    data = path.read_bytes()
    magic, version, node_count, word_count, strings_size, pair_count, model, _ = struct.unpack_from("<8I", data, 0)
    if magic != 0x4C4F5544 or version != 2 or model != MODEL_MIXED:
        raise SystemExit(f"{path} is not a version 2 lexicon of the mixed model")
    words_at = 32 + node_count * 12
    index_at = words_at + word_count * 12
    pairs_at = index_at + (word_count + 1) * 4
    strings_at = pairs_at + pair_count * 8
    if strings_at + strings_size != len(data):
        raise SystemExit(f"{path} has another size than its header says")
    texts, values = [], {}
    for index in range(word_count):
        offset, log_probability, _ = struct.unpack_from("<Iff", data, words_at + index * 12)
        end = data.index(b"\0", strings_at + offset)
        text = data[strings_at + offset:end].decode("utf-8")
        texts.append(text)
        values[text] = log_probability
    starts = struct.unpack_from(f"<{word_count + 1}I", data, index_at)
    pairs = {}
    for first in range(word_count):
        for position in range(starts[first], starts[first + 1]):
            second, log_probability = struct.unpack_from("<If", data, pairs_at + position * 8)
            pairs[(texts[first], texts[second])] = log_probability
    return values, pairs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lexicon", type=Path, default=ROOT / "Shared" / "lexicon-english.bin")
    parser.add_argument("--table", type=Path, default=ROOT / "Shared" / "supplement-ai-software.tsv")
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()

    words, pairs = read_lexicon(arguments.lexicon)
    added = raised = 0
    for line in arguments.table.read_text(encoding="utf-8").splitlines()[1:]:
        word, zipf = line.split("\t")[:2]
        value = (float(zipf) - 9) * math.log(10)
        if word not in words:
            added += 1
            words[word] = value
        elif value > words[word]:
            raised += 1
            words[word] = value
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    stats = write_lexicon(arguments.out, [(word, word, value, 0.0) for word, value in sorted(words.items())], pairs, MODEL_MIXED)
    print(f"wrote {arguments.out}: {stats}, {added} words added, {raised} words raised, "
          f"{arguments.out.stat().st_size - arguments.lexicon.stat().st_size} bytes more than the base lexicon")


if __name__ == "__main__":
    main()
