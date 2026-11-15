"""The texts that trained, stopped, tuned or selected the language models, and the texts of the
held-out sets that decided on them, for the leakage check.

The language model of the keyboard is the SmolLM2-135M LoRA fine-tune dom-s100-seed1 of
scripts/lm-domain. Its training lists come from the cases of rounds 1 and 2 (scripts/lm-finetune
and scripts/lm-finetune2 on their branches) and from the domain round (scripts/lm-domain). The
builders write those cases to build/, outside git. This module reads them.

Two groups of files:
- Model files: every text that trained, stopped, tuned or selected the model. A typo-set case
  must hold no such text.
- Decision files: the held-out sets that decided whether a model replaced the shipped file. They
  trained nothing, but a typo-set case that repeats one of them repeats a decision case. The
  typo set leaves them out too, and counts them apart.

The files and their roles (Tables 3 and 4 of docs/lm-domain-design.md):
    everyday/cases.train.jsonl, cases2.train.jsonl, domain/cases.train.jsonl     the loss
    everyday/cases.stop.jsonl, cases2.stop.jsonl, domain/cases.stop.jsonl        the stopping lists
    everyday/cases.tune.jsonl, cases.stream.tune.jsonl                           the setting
    everyday/cases.stream.select.jsonl, cases.github.select.jsonl, published.dev.jsonl
                                                                                 the pick of the model
    lm-finetune2 data/pairs.wikipedia.train.jsonl                               the misspelling pairs
    confirm-holdout/*.confirm.jsonl, fresh-holdout/*.fresh.jsonl                 decision files
    lm-finetune2 data/cases.*.holdout.jsonl                                      decision files

The other selection sets of the domain round are case files of scripts/typing-evaluation/cases,
which the builders leave out by their own rule.

A sentence leaks in three ways:
1. A model case names its Tatoeba id.
2. Its words equal the words of a model sentence, or of a model case's context plus intended
   text.
3. It has as many words as a model sentence and differs from it in one word only, as "she is
   proud of her son" against "mary is proud of her son". A name swap is such a change.
"""
import hashlib
import json
import re
from pathlib import Path

LM_DOMAIN_FILES = [
    "everyday/cases.train.jsonl", "everyday/cases2.train.jsonl", "everyday/cases.stop.jsonl",
    "everyday/cases2.stop.jsonl", "everyday/cases.tune.jsonl", "everyday/cases.stream.tune.jsonl",
    "everyday/cases.stream.select.jsonl", "everyday/cases.github.select.jsonl", "everyday/published.dev.jsonl",
    "domain/cases.train.jsonl", "domain/cases.stop.jsonl",
]
LM_DOMAIN_DECISION_PATTERNS = ["confirm-holdout/cases.*.confirm.jsonl", "fresh-holdout/cases.*.fresh.jsonl"]
LM_FINETUNE2_DECISION_PATTERNS = ["cases.*.holdout.jsonl"]
PAIR_FILES = ["pairs.wikipedia.train.jsonl"]
WORD = re.compile(r"[a-z0-9']+")
# The fewest words of a sentence that the one-word rule reads. "is tom" against "is mary" is no
# leak of text.
NEAR_MINIMUM_WORDS = 4


def words_of(text: str) -> str:
    return " ".join(WORD.findall(text.lower().replace("’", "'")))


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def masked_keys(words: str) -> list[str]:
    """The sentence with each word in turn replaced by a mark, for the one-word rule."""
    parts = words.split(" ")
    if len(parts) < NEAR_MINIMUM_WORDS:
        return []
    return [" ".join(parts[:i] + ["\x00"] + parts[i + 1:]) for i in range(len(parts))]


class TextSet:
    """The sources, the texts and the one-word keys of one group of files."""

    def __init__(self):
        self.sources: set[str] = set()
        self.texts: set[str] = set()
        self.sentences: set[str] = set()
        self.near: set[str] = set()

    def add_case(self, case: dict) -> None:
        source = case.get("source", "")
        if source.startswith("tatoeba:"):
            self.sources.add(source)
        if case.get("sentence"):
            self.sentences.add(words_of(case["sentence"]))
        whole = words_of((case.get("context") or "") + " " + case["intended"])
        if whole:
            self.texts.add(whole)

    def finish(self) -> None:
        self.texts |= self.sentences
        for text in self.texts:
            self.near.update(masked_keys(text))

    def reason(self, source: str | None, sentence: str) -> str | None:
        """Why a sentence is in this set: "source", "text" or "one word", or None."""
        if source is not None and source in self.sources:
            return "source"
        words = words_of(sentence)
        if words in self.texts:
            return "text"
        if any(key in self.near for key in masked_keys(words)):
            return "one word"
        return None


def read_cases(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"the language-model file {path} is missing")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class TrainingTexts:
    def __init__(self, lm_domain_data: Path, lm_finetune2_data: Path):
        self.model = TextSet()
        self.decision = TextSet()
        self.pairs: set[tuple[str, str]] = set()
        self.files: dict[str, dict] = {}
        for name in LM_DOMAIN_FILES:
            path = lm_domain_data / name
            cases = read_cases(path)
            for case in cases:
                self.model.add_case(case)
                if case["typed"].lower() != case["intended"].lower():
                    self.pairs.add((case["typed"].lower(), case["intended"].lower()))
            self.files[f"lm-domain/{name}"] = {"sha256": sha256_of(path), "cases": len(cases), "role": "model"}
        decision_paths = []
        for folder, label, patterns in ((lm_domain_data, "lm-domain", LM_DOMAIN_DECISION_PATTERNS),
                                        (lm_finetune2_data, "lm-finetune2", LM_FINETUNE2_DECISION_PATTERNS)):
            for pattern in patterns:
                found = sorted(folder.glob(pattern))
                if not found:
                    raise SystemExit(f"no decision file matches {folder / pattern}")
                decision_paths += [(label, folder, path) for path in found]
        for label, folder, path in decision_paths:
            cases = read_cases(path)
            for case in cases:
                self.decision.add_case(case)
            self.files[f"{label}/{path.relative_to(folder).as_posix()}"] = {
                "sha256": sha256_of(path), "cases": len(cases), "role": "decision"}
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
            self.files[f"lm-finetune2/{name}"] = {"sha256": sha256_of(path), "pairs": count, "role": "model pairs"}
        self.model.finish()
        self.decision.finish()

    def leak_reason(self, source: str | None, sentence: str) -> str | None:
        """Why a sentence of the typo set leaves the pool: "model source", "model text", "model one
        word", "decision source", "decision text", "decision one word", or None."""
        for label, texts in (("model", self.model), ("decision", self.decision)):
            reason = texts.reason(source, sentence)
            if reason is not None:
                return f"{label} {reason}"
        return None

    def leaks(self, source: str | None, sentence: str) -> bool:
        return self.leak_reason(source, sentence) is not None

    def prefix_is_model_text(self, context: str, intended: str) -> bool:
        """Whether a case's context plus intended text equals a model sentence or a model case's
        context plus intended text."""
        return words_of(context + " " + intended) in self.model.texts

    def report(self) -> dict:
        return {"files": self.files, "model_tatoeba_sources": len(self.model.sources), "model_texts": len(self.model.texts),
                "decision_tatoeba_sources": len(self.decision.sources), "decision_texts": len(self.decision.texts),
                "pairs": len(self.pairs)}
