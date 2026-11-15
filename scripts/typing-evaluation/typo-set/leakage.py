"""The texts that trained, stopped or tuned the language models, for the leakage check.

The language model of the keyboard is the SmolLM2-135M LoRA fine-tune dom-s100-seed1 of
scripts/lm-domain. Its training lists come from the cases of rounds 1 and 2 (scripts/lm-finetune
and scripts/lm-finetune2 on their branches) and from the domain round (scripts/lm-domain). The
builders write those cases to build/, outside git. This module reads them and gives three sets:

- `sources`: the Tatoeba sentence ids of every case.
- `texts`: the words of every training sentence, and of every case's context plus intended text,
  in lower case and joined by single spaces.
- `pairs`: the typed and intended pairs of the slip cases and of the Wikipedia misspelling list.

A case of the typo set leaks when its Tatoeba id is in `sources`, or when the words of its
sentence are in `texts`. The pairs are for a report only,
because a common real slip such as "teh" for "the" is in the training lists and in every real
typing log.

The files and their roles (Table 3 of docs/lm-domain-design.md):
    everyday/cases.train.jsonl, cases2.train.jsonl, domain/cases.train.jsonl     the loss
    everyday/cases.stop.jsonl, cases2.stop.jsonl, domain/cases.stop.jsonl        the stopping lists
    everyday/cases.tune.jsonl, cases.stream.tune.jsonl                           the setting
    lm-finetune2 data/pairs.wikipedia.train.jsonl                               the misspelling pairs
"""
import hashlib
import json
import re
from pathlib import Path

LM_DOMAIN_FILES = [
    "everyday/cases.train.jsonl", "everyday/cases2.train.jsonl", "everyday/cases.stop.jsonl",
    "everyday/cases2.stop.jsonl", "everyday/cases.tune.jsonl", "everyday/cases.stream.tune.jsonl",
    "domain/cases.train.jsonl", "domain/cases.stop.jsonl",
]
PAIR_FILES = ["pairs.wikipedia.train.jsonl"]
WORD = re.compile(r"[a-z0-9']+")


def words_of(text: str) -> str:
    return " ".join(WORD.findall(text.lower().replace("’", "'")))


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TrainingTexts:
    def __init__(self, lm_domain_data: Path, lm_finetune2_data: Path):
        self.sources: set[str] = set()
        self.texts: set[str] = set()
        self.pairs: set[tuple[str, str]] = set()
        self.files: dict[str, dict] = {}
        for name in LM_DOMAIN_FILES:
            path = lm_domain_data / name
            if not path.exists():
                raise SystemExit(f"the training file {path} is missing")
            count = 0
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line:
                    continue
                case = json.loads(line)
                count += 1
                source = case.get("source", "")
                if source.startswith("tatoeba:"):
                    self.sources.add(source)
                if case.get("sentence"):
                    self.texts.add(words_of(case["sentence"]))
                whole = words_of((case.get("context") or "") + " " + case["intended"])
                if whole:
                    self.texts.add(whole)
                if case["typed"].lower() != case["intended"].lower():
                    self.pairs.add((case["typed"].lower(), case["intended"].lower()))
            self.files[f"lm-domain/{name}"] = {"sha256": sha256_of(path), "cases": count}
        for name in PAIR_FILES:
            path = lm_finetune2_data / name
            if not path.exists():
                raise SystemExit(f"the training file {path} is missing")
            count = 0
            for line in path.read_text(encoding="utf-8").splitlines():
                if line:
                    pair = json.loads(line)
                    self.pairs.add((pair["typed"].lower(), pair["intended"].lower()))
                    count += 1
            self.files[f"lm-finetune2/{name}"] = {"sha256": sha256_of(path), "pairs": count}

    def leaks(self, source: str | None, sentence: str) -> bool:
        """Whether a sentence of the typo set is training text: by its Tatoeba id, or by its
        words. A training case without a whole sentence counts with its context plus intended
        text, so a training sentence that ends at its intended text also matches."""
        if source is not None and source in self.sources:
            return True
        return words_of(sentence) in self.texts

    def report(self) -> dict:
        return {"files": self.files, "tatoeba_sources": len(self.sources), "texts": len(self.texts),
                "pairs": len(self.pairs)}
