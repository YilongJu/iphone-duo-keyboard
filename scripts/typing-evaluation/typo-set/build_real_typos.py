"""Builds the cases of the typo set that come from real typing errors, into
build/typo-set/cases/, outside git:
    english-typos-aalto.{dev,test}.jsonl   from the Aalto mobile typing study
    pinyin-typos-cscd.{dev,test}.jsonl      from the CSCD-NS Chinese spelling data

Neither source states a licence that allows redistribution, so the repository holds this script
and fetch_real_data.sh, and the data stay out of git. docs/typo-set-design.md gives the rules.

Aalto mobile typing study (Palin, Feit, Kim, Kristensson and Oulasvirta, "How do people type on
mobile devices? Observations from a study with 37,000 volunteers", MobileHCI 2019,
https://userinterfaces.aalto.fi/typing37k/). Volunteers copied a shown sentence on their own
phone. The script keeps a test section when the volunteer said they use no autocorrection,
prediction or swipe, the section logged none of the three, the keyboard is a phone keyboard with
the QWERTY layout, and the typed text has as many words as the shown sentence. A word that
differs from the shown word, after every shown word before it was typed right, gives one case:
the shown words before it as `context`, the typed word as `typed`, and the shown word as
`intended`. The case keeps the error that the volunteer left in the text.

CSCD-NS (Hu, Meng and Zhou, "CSCD-NS: a Chinese Spelling Check Dataset for Native Speakers",
ACL 2024, https://github.com/nghuyong/cscd-ime). Each row holds a Weibo sentence with errors and
the corrected sentence. The script keeps a row with one wrong character whose toneless Pinyin
differs from the Pinyin of the right character by one slip: a fuzzy pair, a neighbor key, a
letter left out, an extra letter or two swapped letters. Then a person who typed the slipped
Pinyin and took the first candidate wrote that wrong character. The case types the Pinyin of the
clause with the slipped syllable, and the intended text is the corrected clause. The Pinyin of the
wrong character is an inference: the data hold the characters, never the keys.

Leakage: the language model reads English only, so no CSCD text can be training text. For the
Aalto sentences, `--lm-domain-data` and `--lm-finetune2-data` name the training files
(leakage.py), and the script writes the ids of the shown sentences that training text holds to
reports/real-leakage.json. Without the two options the script reads that file, as the workflows
do, because the training files are not in git.

Usage, from the repository root, after fetch_real_data.sh:
    python3 scripts/typing-evaluation/typo-set/build_real_typos.py [--lm-domain-data DIR --lm-finetune2-data DIR]
(needs wordfreq, pypinyin and zipfile-deflate64)
"""
import argparse
import hashlib
import json
import random
import re
import sys
from pathlib import Path

from pypinyin import Style, lazy_pinyin
from wordfreq import zipf_frequency

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import layout_keys  # noqa: E402
import sql_rows  # noqa: E402

ROOT = HERE.parents[2]
DOWNLOAD = ROOT / "build" / "typo-set" / "download"
EXTERNAL = ROOT / "build" / "typo-set" / "cases"
LEAKAGE_FILE = HERE / "reports" / "real-leakage.json"
SEED = "typo-set-real-20261114"

WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")
TYPED_WORD = re.compile(r"[a-z']+")
MARKS = ".,!?;:\"()"
# A shown word this rare can be a typo of the shown sentence itself, as "importannce".
INTENDED_MINIMUM_ZIPF = 3.0
REAL_WORD_ZIPF = 3.0
PER_PAIR = 3
# Few contractions make up the apostrophe category, so one pair may appear this often there.
APOSTROPHE_PER_PAIR = 15
PER_CATEGORY = 200
ENGLISH_GROUP = {
    "real_aalto_neighbor": "real_letter_slips", "real_aalto_omitted": "real_letter_slips",
    "real_aalto_added": "real_letter_slips", "real_aalto_doubled": "real_letter_slips",
    "real_aalto_swapped": "real_letter_slips", "real_aalto_drift": "real_drift",
    "real_aalto_apostrophe": "real_apostrophe", "real_aalto_apostrophe_ambiguous": "real_ambiguous",
    "real_aalto_real_word": "real_real_word",
    "real_aalto_two_or_more": "real_two_or_more",
}

CLAUSE = re.compile(r"[一-鿿]+")
PINYIN_SLIPS_PER_HALF = 300
PINYIN_WINDOW = 12
FUZZY = [("z", "zh"), ("c", "ch"), ("s", "sh")]
FUZZY_FINALS = [("an", "ang"), ("en", "eng"), ("in", "ing")]


def zipf(word: str) -> float:
    return zipf_frequency(word, "en")


def tokens_of(text: str) -> list[str]:
    return [raw.strip(MARKS) for raw in text.lower().replace("’", "'").split()]


def one_edit(typed: str, intended: str, layouts) -> str | None:
    """The kind of the one letter slip between two words, by the real layouts, or None."""
    if len(typed) == len(intended):
        diff = [i for i in range(len(typed)) if typed[i] != intended[i]]
        if len(diff) == 1:
            a, b = typed[diff[0]], intended[diff[0]]
            if b in layout_keys.LETTERS and any(a in layout.neighbors[b] for layout in layouts.values()):
                return "neighbor"
            return None
        if len(diff) == 2 and diff[1] == diff[0] + 1 and typed[diff[0]] == intended[diff[1]] and typed[diff[1]] == intended[diff[0]]:
            return "swapped"
        return None
    if len(typed) == len(intended) - 1:
        for i in range(len(intended)):
            if intended[:i] + intended[i + 1:] == typed:
                return "omitted"
        return None
    if len(typed) == len(intended) + 1:
        for i in range(len(typed)):
            if typed[:i] + typed[i + 1:] == intended:
                return "doubled" if (i > 0 and typed[i - 1] == typed[i]) or (i + 1 < len(typed) and typed[i + 1] == typed[i]) else "added"
        return None
    return None


def is_drift(typed: str, intended: str, layouts) -> bool:
    """Whether every letter from some place on is the drifted key of the intended letter, for one
    direction of one layout, with two drifted letters or more."""
    if len(typed) != len(intended) or len(typed) < 3:
        return False
    for layout in layouts.values():
        for direction in layout_keys.DIRECTIONS:
            for sideways in (layout_keys.SIDEWAYS if direction in ("up", "down") else (0.0,)):
                for start in range(0, len(intended) - 1):
                    if typed[:start] == intended[:start] and layout.drift_text(intended, direction, sideways, start) == typed:
                        return True
    return False


# Contractions whose form without the apostrophe is a common word of its own, as in
# build_english_typos.AMBIGUOUS_PAIRS.
AMBIGUOUS_CONTRACTIONS = {"we'll", "it's", "we're", "i'll", "won't", "he'll", "she'll", "let's"}
# Contractions with "'s" of a pronoun or a question word. Any other word with "'s" is a
# possessive, as "nation's", and its form without the apostrophe is often a word ("nations").
S_CONTRACTIONS = {"that's", "what's", "there's", "he's", "she's", "here's", "who's", "where's", "how's", "when's", "why's"}


def apostrophe_is_ambiguous(typed: str, intended: str) -> bool:
    if intended in AMBIGUOUS_CONTRACTIONS:
        return True
    return intended.endswith("'s") and intended not in S_CONTRACTIONS and zipf(typed) >= REAL_WORD_ZIPF


def english_category(typed: str, intended: str, layouts) -> str:
    if "'" in intended and typed == intended.replace("'", ""):
        return "real_aalto_apostrophe_ambiguous" if apostrophe_is_ambiguous(typed, intended) else "real_aalto_apostrophe"
    if is_drift(typed, intended, layouts):
        return "real_aalto_drift"
    if zipf(typed) >= REAL_WORD_ZIPF:
        return "real_aalto_real_word"
    kind = one_edit(typed, intended, layouts)
    return f"real_aalto_{kind}" if kind else "real_aalto_two_or_more"


def read_aalto() -> tuple[dict, list, dict]:
    folder = DOWNLOAD / "aalto37k"
    sentences = {row[0]: row[1] for row in sql_rows.table_rows(
        (folder / "sentences_content.sql").read_text(encoding="utf-8").splitlines(keepends=True), "SENTENCES")}
    sections, participants = [], {}
    # The archive uses Deflate64, which zipfile reads only with the package zipfile-deflate64.
    import zipfile_deflate64 as zipfile
    archive = zipfile.ZipFile(folder / "processed_typing_data.zip")
    for raw in archive.open("processed_mobiletyping_data.sql"):
        if raw.startswith(b"INSERT INTO `open_test_sections`"):
            line = raw.decode("utf-8", errors="replace")
            sections.extend(sql_rows.parse_values(line, line.index("VALUES") + len("VALUES")))
        elif raw.startswith(b"INSERT INTO `open_participants`"):
            line = raw.decode("utf-8", errors="replace")
            for row in sql_rows.parse_values(line, line.index("VALUES") + len("VALUES")):
                participants[row[0]] = row
    return sentences, sections, participants


def aalto_leaking(sentences: dict, arguments) -> list[int]:
    if arguments.lm_domain_data is None:
        if not LEAKAGE_FILE.exists():
            raise SystemExit(f"{LEAKAGE_FILE} is missing: run once with --lm-domain-data and --lm-finetune2-data")
        return json.loads(LEAKAGE_FILE.read_text(encoding="utf-8"))["aalto_sentence_ids"]
    import leakage
    training = leakage.TrainingTexts(arguments.lm_domain_data, arguments.lm_finetune2_data)
    ids = sorted(sid for sid, text in sentences.items() if training.leaks(None, text))
    LEAKAGE_FILE.parent.mkdir(exist_ok=True)
    LEAKAGE_FILE.write_text(json.dumps({"training": training.report(), "aalto_sentences": len(sentences),
                                        "aalto_sentence_ids": ids}, indent=2) + "\n", encoding="utf-8", newline="\n")
    return ids


def build_aalto(arguments, layouts) -> dict:
    sentences, sections, participants = read_aalto()
    leaking = set(aalto_leaking(sentences, arguments))
    report = {"sentences": len(sentences), "leaking_sentences": len(leaking), "sections": len(sections)}
    found = {"dev": {}, "test": {}}
    kept = 0
    for row in sections:
        section_id, sentence_id, participant_id, user_input = row[0], row[1], row[2], row[3]
        n_swipe, n_prediction, n_auto = row[20], row[21], row[22]
        participant = participants.get(participant_id)
        if user_input is None or sentence_id not in sentences or participant is None:
            continue
        if n_swipe or n_prediction or n_auto:
            continue
        if participant[13] != "mobile" or participant[9] != "qwerty" or participant[15] != '["no"]':
            continue
        if sentence_id in leaking:
            continue
        shown, typed = tokens_of(sentences[sentence_id]), tokens_of(user_input)
        if len(shown) != len(typed):
            continue
        kept += 1
        half = "dev" if sentence_id % 2 == 0 else "test"
        for index, (intended, got) in enumerate(zip(shown, typed)):
            if intended == got:
                continue
            if shown[:index] != typed[:index]:
                break
            if not WORD.fullmatch(intended) or not TYPED_WORD.fullmatch(got or "-") or zipf(intended) < INTENDED_MINIMUM_ZIPF:
                break
            category = english_category(got, intended, layouts)
            follow = []
            for later in range(index + 1, min(index + 3, len(shown))):
                if shown[later] != typed[later] or not WORD.fullmatch(shown[later]):
                    break
                follow.append(shown[later])
            found[half].setdefault(category, []).append({
                "context": " ".join(shown[:index]), "typed": got, "intended": intended, "follow": follow,
                "source": f"aalto37k:section:{section_id}:word:{index}", "sentence_id": sentence_id})
            break
    report["sections_kept"] = kept
    report["halves"] = {}
    # Two volunteers can make the same error on the same shown words, and two sentences can begin
    # alike. The test half never repeats a dev case, so the dev half comes first.
    dev_cases: set[tuple[str, str, str]] = set()
    for half in ("dev", "test"):
        by_category = found[half]
        rng = random.Random(f"{SEED}-{half}-aalto")
        cases = []
        counts = {}
        skipped = 0
        for category in sorted(by_category):
            pool = sorted(by_category[category], key=lambda c: c["source"])
            rng.shuffle(pool)
            per_pair: dict[tuple[str, str], int] = {}
            number = 0
            for item in pool:
                key = (item["typed"], item["intended"])
                limit = APOSTROPHE_PER_PAIR if category.startswith("real_aalto_apostrophe") else PER_PAIR
                if per_pair.get(key, 0) >= limit:
                    continue
                per_pair[key] = per_pair.get(key, 0) + 1
                # Half the cases also type the next words, as the volunteer typed them right.
                follow = item["follow"][:rng.choice((1, 2))] if item["follow"] and rng.random() < 0.5 else []
                triple = (item["context"], " ".join([item["typed"]] + follow), " ".join([item["intended"]] + follow))
                if half == "test" and triple in dev_cases:
                    skipped += 1
                    continue
                cases.append({"id": f"enaalto-{half}-{category}-{number:04d}", "split": half, "category": category,
                              "group": ENGLISH_GROUP[category], "expected": "correct", "context": item["context"],
                              "typed": " ".join([item["typed"]] + follow), "intended": " ".join([item["intended"]] + follow),
                              "source": item["source"], "layout": "phone", "follow": len(follow)})
                number += 1
                if number == PER_CATEGORY:
                    break
            counts[category] = {"found": len(pool), "cases": number}
        write(EXTERNAL / f"english-typos-aalto.{half}.jsonl", cases)
        if half == "dev":
            dev_cases = {(c["context"], c["typed"], c["intended"]) for c in cases}
        report["halves"][half] = counts | {"skipped_as_dev_cases": skipped}
    return report


# ---- CSCD-NS ----

def pinyin_slip_kind(wrong: str, right: str, layouts) -> str | None:
    for short, long in FUZZY:
        for a, b in ((short, long), (long, short)):
            if right.startswith(a) and not (len(a) == 1 and right.startswith(a + "h")) and wrong == b + right[len(a):]:
                return "fuzzy"
    if (right[:1], wrong[:1]) in (("n", "l"), ("l", "n")) and right[1:] == wrong[1:]:
        return "fuzzy"
    for short, long in FUZZY_FINALS:
        for a, b in ((short, long), (long, short)):
            if right.endswith(a) and not right.endswith(a + "g") and wrong == right[:-len(a)] + b:
                return "fuzzy"
    kind = one_edit(wrong, right, layouts)
    return {"neighbor": "neighbor", "omitted": "omitted", "added": "added", "doubled": "added",
            "swapped": "swapped"}.get(kind) if kind else None


def build_cscd(layouts) -> dict:
    folder = DOWNLOAD / "cscd" / "cscd-ns"
    rows = []
    for name in ("train", "dev", "test"):
        for line in (folder / f"{name}.tsv").read_text(encoding="utf-8").splitlines():
            label, wrong_text, right_text = line.split("\t")
            if label == "1" and len(wrong_text) == len(right_text):
                rows.append((name, wrong_text, right_text))
    report = {"rows_with_errors_of_equal_length": len(rows), "halves": {}}
    found = {"dev": [], "test": []}
    for name, wrong_text, right_text in rows:
        diff = [i for i in range(len(right_text)) if wrong_text[i] != right_text[i]]
        if len(diff) != 1:
            continue
        place = diff[0]
        match = next((m for m in CLAUSE.finditer(right_text) if m.start() <= place < m.end()), None)
        if match is None:
            continue
        start = max(match.start(), min(place - PINYIN_WINDOW // 2, match.end() - PINYIN_WINDOW))
        end = min(match.end(), start + PINYIN_WINDOW)
        clause = right_text[start:end]
        if len(clause) < 2:
            continue
        syllables = lazy_pinyin(clause, style=Style.NORMAL)
        if len(syllables) != len(clause) or not all(s.isascii() and s.isalpha() for s in syllables):
            continue
        wrong_syllable = lazy_pinyin(wrong_text[place], style=Style.NORMAL)[0]
        index = place - start
        if wrong_syllable == syllables[index] or not wrong_syllable.isalpha():
            continue
        kind = pinyin_slip_kind(wrong_syllable, syllables[index], layouts)
        if kind is None:
            continue
        typed = "".join(syllables[:index] + [wrong_syllable] + syllables[index + 1:])
        half = "dev" if hashlib.sha256(right_text.encode()).digest()[0] % 2 == 0 else "test"
        found[half].append({"kind": kind, "clause": clause, "syllables": syllables, "typed": typed,
                            "context": right_text[:start], "source": f"cscd-ns:{name}:{hashlib.sha256(right_text.encode()).hexdigest()[:16]}",
                            "wrong": wrong_text[place], "wrong_syllable": wrong_syllable})
    # One clause can stand in two sentences of the data, so a test case never holds a clause of
    # the dev half. The dev half comes first.
    dev_clauses: set[str] = set()
    for half in ("dev", "test"):
        items = found[half]
        rng = random.Random(f"{SEED}-{half}-cscd")
        items.sort(key=lambda c: (c["source"], c["clause"]))
        rng.shuffle(items)
        before = len(items)
        items = [item for item in items if item["clause"] not in dev_clauses]
        skipped = before - len(items)
        cases, clean_of, numbers = [], {}, {}
        for item in items[:PINYIN_SLIPS_PER_HALF]:
            if item["clause"] not in clean_of:
                clean_id = f"zhcscd-{half}-pinyin_cscd_clean-{len(clean_of):04d}"
                clean_of[item["clause"]] = clean_id
                cases.append({"id": clean_id, "split": half, "category": "pinyin_cscd_clean", "group": "real_clean",
                              "expected": "keep", "context": item["context"], "typed": "".join(item["syllables"]),
                              "intended": item["clause"], "intended_pinyin": " ".join(item["syllables"]),
                              "source": item["source"]})
            category = f"pinyin_cscd_{item['kind']}"
            numbers[category] = numbers.get(category, 0) + 1
            cases.append({"id": f"zhcscd-{half}-{category}-{numbers[category] - 1:04d}", "split": half,
                          "category": category, "group": "real_slips", "expected": "correct", "context": item["context"],
                          "typed": item["typed"], "intended": item["clause"], "intended_pinyin": " ".join(item["syllables"]),
                          "source": item["source"], "twin": clean_of[item["clause"]], "wrong_character": item["wrong"],
                          "wrong_syllable": item["wrong_syllable"]})
        write(EXTERNAL / f"pinyin-typos-cscd.{half}.jsonl", cases)
        if half == "dev":
            dev_clauses = {case["intended"] for case in cases}
        report["halves"][half] = {"found": len(items), "slip_cases": sum(numbers.values()), "categories": numbers,
                                  "skipped_as_dev_clauses": skipped}
    return report


def write(path: Path, cases: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases), encoding="utf-8", newline="\n")
    print(f"wrote {path.relative_to(ROOT)}: {len(cases)} cases")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lm-domain-data", type=Path)
    parser.add_argument("--lm-finetune2-data", type=Path)
    arguments = parser.parse_args()
    if (arguments.lm_domain_data is None) != (arguments.lm_finetune2_data is None):
        raise SystemExit("--lm-domain-data and --lm-finetune2-data go together")
    layouts = layout_keys.both()
    report = {"aalto": build_aalto(arguments, layouts), "cscd": build_cscd(layouts)}
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    (EXTERNAL / "typo-set-real-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
