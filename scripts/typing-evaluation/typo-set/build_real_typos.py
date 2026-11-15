"""Builds the cases of the typo set that come from real typing errors, into
build/typo-set/cases/, outside git:
    english-typos-aalto.{dev,test}.jsonl   from the Aalto mobile typing study
    pinyin-typos-cscd.{dev,test}.jsonl      from the CSCD-NS Chinese spelling data

Neither source states a licence that allows redistribution, so the repository holds this script
and fetch_real_data.sh, and the data stay out of git and out of every workflow artifact
(redact_real.py). docs/typo-set-design.md gives the rules.

Aalto mobile typing study (Palin, Feit, Kim, Kristensson and Oulasvirta, "How do people type on
mobile devices? Observations from a study with 37,000 volunteers", MobileHCI 2019,
https://userinterfaces.aalto.fi/typing37k/). Volunteers copied a shown sentence on their own
phone. The script keeps a test section when the volunteer said they use no autocorrection,
prediction or swipe, the section logged none of the three, the keyboard is a phone keyboard with
the QWERTY layout, and the typed text has as many words as the shown sentence. A word that
differs from the shown word, after every shown word before it was typed right, gives one case:
the shown words before it as `context`, the typed word as `typed`, and the shown word as
`intended`. The case keeps the error that the volunteer left in the text. An error that is no
typing slip stays out: a spelling variant ("behaviour" for "behavior"), a short form ("u"), and
a word that is more than three edits from the shown word.

CSCD-NS (Hu, Meng and Zhou, "CSCD-NS: a Chinese Spelling Check Dataset for Native Speakers",
ACL 2024, https://github.com/nghuyong/cscd-ime). Each row holds a Weibo sentence with errors and
the corrected sentence. The script keeps a row with one wrong character whose toneless Pinyin
differs from the Pinyin of the right character by one slip: a fuzzy pair, a neighbor key, a
letter left out, an extra letter or two swapped letters. Then a person who typed the slipped
Pinyin and took the first candidate wrote that wrong character. A wrong character that has the
right syllable among its readings stays out, because a wrong pick among the candidates of the
right keys explains it. The case types the Pinyin of the clause with the slipped syllable, and
the intended text is the corrected clause. The Pinyin of the wrong character is an inference:
the data hold the characters, never the keys.

Leakage: the language model reads English only, so no CSCD text can be training text. For the
Aalto sentences, `--lm-domain-data` and `--lm-finetune2-data` name the language-model files
(leakage.py), and the script writes to reports/real-leakage.json the ids of the shown sentences
that those files hold, and the sentence starts that equal a language-model case. Without the two
options the script reads that file, as the workflows do, because the files are not in git.

Usage, from the repository root, after fetch_real_data.sh:
    python3 scripts/typing-evaluation/typo-set/build_real_typos.py [--lm-domain-data DIR --lm-finetune2-data DIR]
(needs wordfreq, pypinyin, jieba and zipfile-deflate64, at the versions of the workflows)
"""
import argparse
import hashlib
import json
import random
import re
import sys
from pathlib import Path

from pypinyin import Style, lazy_pinyin, pinyin
from wordfreq import zipf_frequency

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import layout_keys  # noqa: E402
import pinyin_reading  # noqa: E402
import sql_rows  # noqa: E402

ROOT = HERE.parents[2]
DOWNLOAD = ROOT / "build" / "typo-set" / "download"
EXTERNAL = ROOT / "build" / "typo-set" / "cases"
GENERATED = ROOT / "scripts" / "typing-evaluation" / "cases"
LEAKAGE_FILE = HERE / "reports" / "real-leakage.json"
SEED = "typo-set-real-20261114"

WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")
TYPED_WORD = re.compile(r"[a-z']+")
MARKS = ".,!?;:\"()"
# A shown word this rare can be a typo of the shown sentence itself, as "importannce".
INTENDED_MINIMUM_ZIPF = 3.0
REAL_WORD_ZIPF = 3.0
# A typed word more edits than this from the shown word is a copy or memory error, as "kelly"
# for "need", or a cut-off word, as "sepa" for "separately".
MOST_EDITS = 3
# Short forms that people type on purpose, as "u" for "you".
SHORT_FORMS = {"u", "ur", "r", "n", "y", "k", "b", "c", "im", "ya", "thx", "pls", "plz", "cuz", "tho"}
# Spelling variants: British and American forms. A typed word that one of these rules turns into
# the shown word, or the shown word into the typed word, is a variant and no slip.
VARIANT_RULES = [(r"ise", "ize"), (r"ised", "ized"), (r"ising", "izing"), (r"isation", "ization"), (r"our", "or"),
                 (r"tre", "ter"), (r"yse", "yze"), (r"lled", "led"), (r"lling", "ling"), (r"ogue", "og"),
                 (r"ence", "ense"), (r"wards", "ward"), (r"ise", "ice"), (r"mme", "m")]
# A shown sentence with a word cut in two, as "that s all", is a broken sentence of the study.
FRAGMENTS = set("bcdefghjklmnopqrstuvwxyz") | {"ll", "re", "ve"}
PER_PAIR = 3
# Few contractions make up the apostrophe category, so one pair may appear this often there.
APOSTROPHE_PER_PAIR = 15
PER_CATEGORY = 200
# A case whose context and intended word equal a language-model case leaves the set when its
# context has this many words or more, as in build_english_typos.py.
MODEL_START_MINIMUM_CONTEXT_WORDS = 2
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
FUZZY_LETTERS = [("n", "l"), ("f", "h"), ("r", "l")]
FUZZY_FINALS = [("an", "ang"), ("en", "eng"), ("in", "ing")]


def zipf(word: str) -> float:
    return zipf_frequency(word, "en")


def tokens_of(text: str) -> list[str]:
    return [raw.strip(MARKS) for raw in text.lower().replace("’", "'").split()]


def words_of(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", text.lower().replace("’", "'")))


def owner_of(key: str) -> str:
    return "dev" if hashlib.sha256(key.encode()).digest()[0] % 2 == 0 else "test"


def edits(a: str, b: str) -> int:
    """The Damerau-Levenshtein distance with swaps of two letters side by side."""
    rows = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        rows[i][0] = i
    for j in range(len(b) + 1):
        rows[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            rows[i][j] = min(rows[i - 1][j] + 1, rows[i][j - 1] + 1, rows[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                rows[i][j] = min(rows[i][j], rows[i - 2][j - 2] + 1)
    return rows[-1][-1]


def is_variant(typed: str, intended: str) -> bool:
    for a, b in VARIANT_RULES:
        for x, y in ((a, b), (b, a)):
            for place in [m.start() for m in re.finditer(re.escape(x), typed)]:
                if typed[:place] + y + typed[place + len(x):] == intended:
                    return True
    return False


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


def english_category(typed: str, intended: str, layouts) -> str | None:
    """The category of a real error, or None when the error is no typing slip."""
    if "'" in intended and typed == intended.replace("'", ""):
        return "real_aalto_apostrophe_ambiguous" if apostrophe_is_ambiguous(typed, intended) else "real_aalto_apostrophe"
    if not any(c.isalpha() for c in typed) or typed in SHORT_FORMS or is_variant(typed, intended):
        return None
    if is_drift(typed, intended, layouts):
        return "real_aalto_drift"
    kind = one_edit(typed, intended, layouts)
    if zipf(typed) >= REAL_WORD_ZIPF:
        # A real word one slip from the shown word. A real word further away is a copy or
        # memory error, as "did" for "do" or "program" for "system".
        return "real_aalto_real_word" if kind else None
    if kind:
        return f"real_aalto_{kind}"
    if edits(typed, intended) <= MOST_EDITS and 2 * len(typed) >= len(intended):
        return "real_aalto_two_or_more"
    return None


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


def aalto_leaking(sentences: dict, arguments) -> tuple[set[int], set[tuple[int, int]]]:
    """The ids of the shown sentences that a language-model file holds, and the (sentence id,
    word place) pairs whose sentence start through that word equals a language-model case."""
    if arguments.lm_domain_data is None:
        if not LEAKAGE_FILE.exists():
            raise SystemExit(f"{LEAKAGE_FILE} is missing: run once with --lm-domain-data and --lm-finetune2-data")
        saved = json.loads(LEAKAGE_FILE.read_text(encoding="utf-8"))
        return set(saved["aalto_sentence_ids"]), {tuple(pair) for pair in saved["aalto_model_starts"]}
    import leakage
    training = leakage.TrainingTexts(arguments.lm_domain_data, arguments.lm_finetune2_data)
    reasons = {sid: training.leak_reason(None, text) for sid, text in sentences.items()}
    ids = sorted(sid for sid, reason in reasons.items() if reason is not None)
    starts = []
    for sid, text in sorted(sentences.items()):
        shown = tokens_of(text)
        for index in range(MODEL_START_MINIMUM_CONTEXT_WORDS, len(shown)):
            if training.prefix_is_model_text(" ".join(shown[:index]), shown[index]):
                starts.append([sid, index])
    LEAKAGE_FILE.parent.mkdir(exist_ok=True)
    LEAKAGE_FILE.write_text(json.dumps({
        "training": training.report(), "aalto_sentences": len(sentences),
        "aalto_sentence_ids": ids, "aalto_sentence_reasons": {str(sid): reasons[sid] for sid in ids},
        "aalto_model_starts": starts}, indent=2) + "\n", encoding="utf-8", newline="\n")
    return set(ids), {tuple(pair) for pair in starts}


def generated_triples() -> dict[str, set[tuple[str, str, str]]]:
    """The (context, typed, intended) triples of the generated English cases, by half."""
    out = {}
    for half in ("dev", "test"):
        triples = set()
        for name in ("english-typos", "english-typos-capitals"):
            for line in (GENERATED / f"{name}.{half}.jsonl").read_text(encoding="utf-8").splitlines():
                if line:
                    case = json.loads(line)
                    triples.add((case["context"].lower(), case["typed"].lower(), case["intended"].lower()))
        out[half] = triples
    return out


def build_aalto(arguments, layouts) -> dict:
    sentences, sections, participants = read_aalto()
    leaking, model_starts = aalto_leaking(sentences, arguments)
    report = {"sentences": len(sentences), "leaking_sentences": len(leaking), "model_starts": len(model_starts),
              "sections": len(sections)}
    found = {"dev": {}, "test": {}}
    kept = 0
    dropped: dict[str, int] = {}

    def drop(reason: str) -> None:
        dropped[reason] = dropped.get(reason, 0) + 1

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
        if any(word in FRAGMENTS for word in shown):
            drop("shown sentence with a cut word")
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
            if (sentence_id, index) in model_starts:
                drop("start is language-model text")
                break
            category = english_category(got, intended, layouts)
            if category is None:
                drop("no typing slip")
                break
            follow = []
            for later in range(index + 1, min(index + 3, len(shown))):
                if shown[later] != typed[later] or not WORD.fullmatch(shown[later]):
                    break
                follow.append(shown[later])
            found[half].setdefault(category, []).append({
                "context": " ".join(shown[:index]), "typed": got, "intended": intended, "follow": follow,
                "source": f"aalto37k:section:{section_id}:word:{index}", "sentence_id": sentence_id})
            break
    # Two volunteers can make the same error on the same shown words, and two shown sentences can
    # begin alike. A sentence start (the context and the shown word) that both halves found goes
    # to the half that its SHA-256 value names.
    starts = {half: {words_of(item["context"] + " " + item["intended"]) for items in found[half].values() for item in items}
              for half in found}
    shared = starts["dev"] & starts["test"]
    for half in found:
        for category in found[half]:
            before = len(found[half][category])
            found[half][category] = [item for item in found[half][category]
                                     if words_of(item["context"] + " " + item["intended"]) not in shared
                                     or owner_of(words_of(item["context"] + " " + item["intended"])) == half]
            if before != len(found[half][category]):
                dropped["start kept by the other half"] = dropped.get("start kept by the other half", 0) + before - len(found[half][category])
    report["sections_kept"] = kept
    report["dropped"] = dropped
    report["halves"] = {}
    generated = generated_triples()
    for half in ("dev", "test"):
        other = "test" if half == "dev" else "dev"
        by_category = found[half]
        rng = random.Random(f"{SEED}-{half}-aalto")
        cases = []
        counts = {}
        seen: set[tuple[str, str, str]] = set()
        skipped = {"same case in this half": 0, "case of the other half of the generated cases": 0}
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
                # Half the cases also type the next words, as the volunteer typed them right.
                follow = item["follow"][:rng.choice((1, 2))] if item["follow"] and rng.random() < 0.5 else []
                triple = (item["context"], " ".join([item["typed"]] + follow), " ".join([item["intended"]] + follow))
                if triple in seen:
                    skipped["same case in this half"] += 1
                    continue
                if triple in generated[other]:
                    skipped["case of the other half of the generated cases"] += 1
                    continue
                if category == "real_aalto_apostrophe_ambiguous" and not item["context"] and not follow:
                    # Both forms are words, and no words around the case decide between them.
                    continue
                seen.add(triple)
                per_pair[key] = per_pair.get(key, 0) + 1
                cases.append({"id": f"enaalto-{half}-{category}-{number:04d}", "split": half, "category": category,
                              "group": ENGLISH_GROUP[category], "expected": "correct", "context": item["context"],
                              "typed": triple[1], "intended": triple[2],
                              "source": item["source"], "layout": "phone", "follow": len(follow)})
                number += 1
                if number == PER_CATEGORY:
                    break
            counts[category] = {"found": len(pool), "cases": number}
        write(EXTERNAL / f"english-typos-aalto.{half}.jsonl", cases)
        report["halves"][half] = counts | {"skipped": skipped}
    return report


# ---- CSCD-NS ----

def toneless_readings(character: str) -> set[str]:
    return {r for r in pinyin(character, style=Style.NORMAL, heteronym=True)[0]}


def pinyin_slip_kind(wrong: str, right: str, layouts) -> str | None:
    for short, long in FUZZY:
        for a, b in ((short, long), (long, short)):
            if right.startswith(a) and not (len(a) == 1 and right.startswith(a + "h")) and wrong == b + right[len(a):]:
                return "fuzzy"
    for a, b in FUZZY_LETTERS:
        if {right[:1], wrong[:1]} == {a, b} and right[1:] == wrong[1:]:
            return "fuzzy"
    if right[:1] in "ln" and right[1:] in ("u", "v") and wrong[:1] == right[:1] and wrong[1:] in ("u", "v") and wrong != right:
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
    reader = pinyin_reading.Reader()
    rows = []
    for name in ("train", "dev", "test"):
        for line in (folder / f"{name}.tsv").read_text(encoding="utf-8").splitlines():
            label, wrong_text, right_text = line.split("\t")
            if label == "1" and len(wrong_text) == len(right_text):
                rows.append((name, wrong_text, right_text))
    report = {"rows_with_errors_of_equal_length": len(rows), "halves": {}}
    found = {"dev": [], "test": []}
    dropped = {"uncertain reading": 0, "wrong character has the right syllable": 0}
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
        syllables = reader.syllables(clause)
        if syllables is None:
            dropped["uncertain reading"] += 1
            continue
        if not all(s.isascii() and s.isalpha() for s in syllables):
            continue
        index = place - start
        wrong_character = wrong_text[place]
        if syllables[index] in toneless_readings(wrong_character):
            dropped["wrong character has the right syllable"] += 1
            continue
        wrong_syllable = lazy_pinyin(wrong_character, style=Style.NORMAL)[0]
        if not wrong_syllable.isalpha():
            continue
        kind = pinyin_slip_kind(wrong_syllable, syllables[index], layouts)
        if kind is None:
            continue
        typed = "".join(syllables[:index] + [wrong_syllable] + syllables[index + 1:])
        half = "dev" if hashlib.sha256(right_text.encode()).digest()[0] % 2 == 0 else "test"
        found[half].append({"kind": kind, "clause": clause, "syllables": syllables, "typed": typed,
                            "context": right_text[:start], "source": f"cscd-ns:{name}:{hashlib.sha256(right_text.encode()).hexdigest()[:16]}",
                            "wrong": wrong_character, "wrong_syllable": wrong_syllable})
    report["dropped"] = dropped
    # One clause can stand in two sentences of the data. A clause that both halves found goes to
    # the half that its SHA-256 value names.
    clauses = {half: {item["clause"] for item in items} for half, items in found.items()}
    shared = clauses["dev"] & clauses["test"]
    for half in ("dev", "test"):
        items = found[half]
        rng = random.Random(f"{SEED}-{half}-cscd")
        items.sort(key=lambda c: (c["source"], c["clause"]))
        rng.shuffle(items)
        before = len(items)
        items = [item for item in items if item["clause"] not in shared or owner_of(item["clause"]) == half]
        skipped = before - len(items)
        cases, clean_of, numbers, seen = [], {}, {}, set()
        repeated = 0
        for item in items:
            if sum(numbers.values()) == PINYIN_SLIPS_PER_HALF:
                break
            triple = (item["context"], item["typed"], item["clause"])
            if triple in seen:
                repeated += 1
                continue
            seen.add(triple)
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
        report["halves"][half] = {"found": len(items), "slip_cases": sum(numbers.values()), "clean_cases": len(clean_of),
                                  "categories": numbers, "skipped_clause_kept_by_the_other_half": skipped,
                                  "skipped_same_case": repeated}
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
