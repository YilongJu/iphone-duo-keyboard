"""Collects a sample of sentences from the build bucket of the "AI and software" domain text.

scripts/domain-pack/collect_corpus.py sends every document to one of three buckets by a hash of
its identifier: build (80 of 100), dev (10) and test (10). It writes the sentences of the dev and
test buckets only. The fine-tune needs sentences of the build bucket, so this script reads the
same sources with the same cleaning and the same bucket function, and keeps a seeded sample of
build sentences per source. A sentence of a dev or test document never enters the output.

Each row names its source and its document, so every training sentence keeps its attribution:
    {"source": "stackexchange:ai", "document": "Posts.xml:123", "text": "..."}
licences.json holds the licence of each source, and the commit of each repository.

Usage, on Linux with 7z installed, from the repository root:
    python3 scripts/lm-domain/collect_train_sentences.py --out build/lm-domain/corpus
"""
import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "domain-pack"))
import collect_corpus as corpus  # noqa: E402

PER_SOURCE = 12000


class BuildSample:
    """Takes the place of collect_corpus.Counts: it has the same `add`, and keeps build sentences."""

    def __init__(self):
        self.kept: dict[str, list] = {}
        self.seen: dict[str, int] = {}
        self.totals: dict[str, dict] = {}
        self.random = random.Random(20261112)

    def add(self, source: str, group: str, document_id: str, text: str) -> None:
        bucket = corpus.bucket_of(f"{source}:{document_id}")
        total = self.totals.setdefault(source, {"group": group, "build": 0, "dev": 0, "test": 0})
        total[bucket] += 1
        if bucket != "build":
            return
        for sentence in corpus.sentences_of(text):
            words = sum(1 for form in corpus.forms_of(sentence) if form is not None)
            # The filter of the held-out sentences of collect_corpus.py.
            if corpus.GAP in sentence or not 5 <= words <= 30 or len(sentence) > 300:
                continue
            kept = self.kept.setdefault(source, [])
            seen = self.seen.get(source, 0) + 1
            self.seen[source] = seen
            row = {"source": source, "group": group, "document": document_id, "text": sentence}
            if len(kept) < PER_SOURCE:
                kept.append(row)
            else:
                place = self.random.randrange(seen)
                if place < PER_SOURCE:
                    kept[place] = row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sources", type=Path, default=ROOT / "scripts" / "domain-pack" / "sources.json")
    arguments = parser.parse_args()
    corpus.SOURCES.update(json.loads(arguments.sources.read_text(encoding="utf-8")))
    arguments.out.mkdir(parents=True, exist_ok=True)
    work = arguments.out / "raw"
    work.mkdir(exist_ok=True)
    sample = BuildSample()
    licences = {"arxiv": corpus.SOURCES["arxiv"]["licence"], "stack_exchange": corpus.SOURCES["stack_exchange"]["licence"]}
    licences["repositories"] = corpus.read_repositories(sample, work)
    corpus.read_arxiv(sample, work)
    corpus.read_stack_exchange(sample, work)
    rows = 0
    with (arguments.out / "sentences.build.jsonl").open("w", encoding="utf-8", newline="\n") as file:
        for source in sorted(sample.kept):
            for row in sample.kept[source]:
                if corpus.bucket_of(f"{row['source']}:{row['document']}") != "build":
                    raise SystemExit(f"a sentence outside the build bucket: {row}")
                file.write(json.dumps(row, ensure_ascii=False) + "\n")
                rows += 1
    report = {"per_source_limit": PER_SOURCE, "sentences": rows, "licences": licences,
              "sources": {source: {**sample.totals[source], "build_sentences_seen": sample.seen.get(source, 0),
                                   "build_sentences_kept": len(sample.kept.get(source, []))}
                          for source in sorted(sample.totals)}}
    (arguments.out / "licences.json").write_text(json.dumps(report, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps({"sentences": rows, "sources": len(sample.kept)}))


if __name__ == "__main__":
    main()
