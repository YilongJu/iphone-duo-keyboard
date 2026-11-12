"""Builds the domain training and stopping cases of the domain round.

The sentences come from the build bucket of the domain text (collect_train_sentences.py), the
bucket that built the vocabulary pack. A sentence of a dev or test document never enters, and a
build sentence with the letters of a held-out sentence of the pack's corpus stays out as well.

Split. SHA-256 of "lm-domain-split:" and the document sends 1 document in 20 to the stopping
cases, and the others to the training cases.

Kinds of case, with the generators of scripts/typing-evaluation/build_english_domain_cases.py:
- clean_stream_technical   a whole sentence in lower case without punctuation, typed word by word
- clean_stream_written     a whole sentence with the capitals and punctuation of its source
- domain_train_slip_new, domain_train_slip_raised
                           a word of the pack typed with one slip of keyboard_noise.py, after the
                           words before it in the sentence. One case in eight opens the field.
- domain_train_clean_new, domain_train_clean_raised
                           the same text typed without the slip (the twin of each slip case)
- domain_train_term_space  a word of the pack typed with a slip at the space bar inside it
- domain_train_phrase_space, domain_train_phrase_clean
                           a frequent pair of the domain text with a slip at the space bar, and
                           the pair typed right

Three rules keep the evaluation sets apart from these cases:
1. A case never has the typed text and the intended text of a slip case of
   cases/english-domain.{dev,test}.jsonl.
2. A case never has the typed text of a published dev misspelling or of a GitHub typo of the
   select half (the rule of round 2).
3. One word of the pack in five is a withheld word: SHA-256 of "lm-domain-term:" and the word,
   modulo 5, is 0. A withheld word gets no slip case, no twin and no space case. It still
   stands in clean running text. The evaluation counts its slips apart, so they show what the
   model does for a word of the pack whose slips it never trained on.

Every case holds `u`, a fixed number from 0 to 1 from SHA-256 of its sentence. An arm with the
domain share S trains on the cases with u under S, so a larger share holds a smaller one.
Every case names its source and document, and ATTRIBUTION files follow from that field.

Usage, from the repository root (needs wordfreq):
    uv run --with wordfreq python scripts/lm-domain/build_domain_train_cases.py \
        --sentences build/lm-domain/corpus/sentences.build.jsonl --held-out build/lm-domain/data/pack-corpus \
        --everyday build/lm-domain/data/everyday --out build/lm-domain/data/domain
"""
import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "typing-evaluation"))
sys.path.insert(0, str(ROOT / "scripts" / "domain-pack"))
import build_english_domain_cases as dom  # noqa: E402
import keyboard_noise as noise  # noqa: E402
from build_pack import read_base_lexicon  # noqa: E402

SEED = "lm-domain-20261112"
QUOTAS = {"stream_technical": 5500, "stream_written": 2200, "term_slip": 13000, "term_space": 3200, "phrase": 4800}
STREAM_PER_SOURCE = 600
SLIPS_PER_TERM = 12
SPACES_PER_TERM = 4
CASES_PER_PHRASE = 6
FIELD_START_ONE_IN = 8
WITHHELD_ONE_IN = 5
STOP_ONE_IN = 20


def number(text: str) -> int:
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")


def is_withheld(term: str) -> bool:
    return number("lm-domain-term:" + term) % WITHHELD_ONE_IN == 0


def split_of(document: str) -> str:
    return "stop" if number("lm-domain-split:" + document) % STOP_ONE_IN == 0 else "train"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sentences", type=Path, required=True)
    parser.add_argument("--held-out", type=Path, required=True, help="the folder of sentences.dev.jsonl and sentences.test.jsonl of the pack's corpus")
    parser.add_argument("--everyday", type=Path, required=True, help="the folder of published.dev.jsonl and cases.github.select.jsonl")
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()

    table, kinds, requested = dom.read_table()
    base_words = read_base_lexicon(ROOT / "Shared" / "lexicon-english.bin")
    known = set(base_words) | set(table)
    phrases = {line.split("\t")[0] for line in (dom.PACK / "ai-software.phrases.tsv").read_text(encoding="utf-8").splitlines()[1:]
               if "'" not in line.split("\t")[0]}
    withheld = {term for term in kinds if is_withheld(term)}

    held_letters = set()
    for half in ("dev", "test"):
        with (arguments.held_out / f"sentences.{half}.jsonl").open(encoding="utf-8") as file:
            for line in file:
                held_letters.add(dom.letters_of(json.loads(line)["text"]))
    evaluation_pairs, evaluation_typed = set(), set()
    for half in ("dev", "test"):
        for case in read_jsonl(dom.OUTPUT_DIR / f"english-domain.{half}.jsonl"):
            if case["typed"].lower() != case["intended"].lower():
                evaluation_pairs.add((case["typed"].lower(), case["intended"].lower()))
    for name in ("published.dev.jsonl", "cases.github.select.jsonl"):
        evaluation_typed |= {case["typed"].lower() for case in read_jsonl(arguments.everyday / name)}

    rows, seen = [], set()
    dropped = {"not_plain_text": 0, "same_letters_as_another_build_sentence": 0, "same_letters_as_a_held_out_sentence": 0}
    with arguments.sentences.open(encoding="utf-8") as file:
        for line in file:
            row = json.loads(line)
            text = row["text"]
            letters = dom.letters_of(text)
            if not text.isascii() or "|" in text or "\t" in text:
                dropped["not_plain_text"] += 1
            elif letters in held_letters:
                dropped["same_letters_as_a_held_out_sentence"] += 1
            elif letters in seen:
                dropped["same_letters_as_another_build_sentence"] += 1
            else:
                seen.add(letters)
                row["tokens"] = text.split()
                rows.append(row)
    rows.sort(key=lambda row: number(f"{SEED}-order:{row['source']}:{row['document']}:{row['text']}"))

    cases: list[dict] = []
    numbers: dict[str, int] = {}
    made = {kind: 0 for kind in QUOTAS}
    per_source: dict[tuple[str, str], int] = {}
    per_term: dict[tuple[str, str], int] = {}
    skipped = {"pair_of_a_domain_dev_or_test_case": 0, "typed_text_of_an_evaluation_misspelling": 0, "no_slip_left": 0}

    def add(row: dict, category: str, context: str, typed: str, intended: str, term: str | None = None, twin: str | None = None) -> str:
        document = f"{row['source']}:{row['document']}"
        split = split_of(document)
        count = numbers.get((split, category), 0)
        numbers[(split, category)] = count + 1
        case = {"id": f"domtrain-{split}-{category}-{count:05d}", "split": split, "category": category, "context": context,
                "typed": typed, "intended": intended, "source": document, "source_group": row["group"],
                "u": round(number(f"{SEED}-u:{document}:{row['text']}") / 2**64, 6)}
        if term is not None:
            case["term"] = term
        if twin is not None:
            case["twin"] = twin
        for field in (context, typed, intended):
            if "|" in field or "\t" in field or "\n" in field or not field.isascii():
                raise SystemExit(f"a case text holds a sign that the harness cannot type: {case}")
        cases.append(case)
        return case["id"]

    def allowed_pair(typed: str, intended: str) -> bool:
        if (typed.lower(), intended.lower()) in evaluation_pairs:
            skipped["pair_of_a_domain_dev_or_test_case"] += 1
            return False
        if typed.lower() in evaluation_typed:
            skipped["typed_text_of_an_evaluation_misspelling"] += 1
            return False
        return True

    def term_spots(tokens: list[str], minimum_length: int) -> list[int]:
        return [index for index, token in enumerate(tokens)
                if (word := dom.bare(token)) is not None and word.lower() in kinds and dom.LETTERS.fullmatch(word.lower())
                and len(word) >= minimum_length and word.lower() not in withheld]

    def make_stream_technical(row: dict, rng: random.Random) -> bool:
        words = []
        for token in row["tokens"]:
            word = token.strip(dom.EDGE)
            if not dom.FORM.fullmatch(word):
                return False
            words.append(word.lower())
        if not 6 <= len(words) <= 25 or per_source.get(("technical", row["source"]), 0) >= STREAM_PER_SOURCE:
            return False
        per_source[("technical", row["source"])] = per_source.get(("technical", row["source"]), 0) + 1
        text = " ".join(words)
        add(row, "clean_stream_technical", "", text, text)
        return True

    def make_stream_written(row: dict, rng: random.Random) -> bool:
        text = " ".join(row["tokens"])
        if not 6 <= len(row["tokens"]) <= 25 or any(c.isdigit() for c in text) \
                or per_source.get(("written", row["source"]), 0) >= STREAM_PER_SOURCE:
            return False
        per_source[("written", row["source"])] = per_source.get(("written", row["source"]), 0) + 1
        add(row, "clean_stream_written", "", text, text)
        return True

    def make_term_slip(row: dict, rng: random.Random) -> bool:
        tokens = row["tokens"]
        spots = term_spots(tokens, 4)
        if not spots:
            return False
        index = rng.choice(spots)
        term = dom.bare(tokens[index]).lower()
        if per_term.get(("slip", term), 0) >= SLIPS_PER_TERM:
            return False
        every = dom.all_slips(term)
        slips = sorted(typed for typed in every if typed not in known)
        if not slips:
            skipped["no_slip_left"] += 1
            return False
        operator = rng.choice(sorted(noise.LETTER_OPERATORS))
        named = sorted(typed for typed in slips if every[typed] == operator)
        typed = rng.choice(named or slips)
        if not allowed_pair(typed, term):
            return False
        per_term[("slip", term)] = per_term.get(("slip", term), 0) + 1
        # One case in eight opens the field, where the keyboard types the first capital by itself.
        context = "" if rng.randrange(FIELD_START_ONE_IN) == 0 else " ".join(tokens[:index])
        kind = kinds[term]
        clean = add(row, f"domain_train_clean_{kind}", context, term, term, term=term)
        add(row, f"domain_train_slip_{kind}", context, typed, term, term=term, twin=clean)
        return True

    def make_term_space(row: dict, rng: random.Random) -> bool:
        tokens = row["tokens"]
        spots = term_spots(tokens, 5)
        if not spots:
            return False
        index = rng.choice(spots)
        term = dom.bare(tokens[index]).lower()
        if per_term.get(("space", term), 0) >= SPACES_PER_TERM:
            return False
        operator = rng.choice([noise.extra_space, noise.letter_to_space])
        typed = operator(term, rng)
        if typed is None or all(part in known for part in typed.split(" ")) or not allowed_pair(typed, term):
            return False
        per_term[("space", term)] = per_term.get(("space", term), 0) + 1
        add(row, "domain_train_term_space", " ".join(tokens[:index]), typed, term, term=term)
        return True

    def make_phrase(row: dict, rng: random.Random) -> bool:
        tokens = row["tokens"]
        spots = []
        for index in range(len(tokens) - 1):
            left, right = tokens[index], dom.bare(tokens[index + 1])
            if right is not None and dom.LETTERS.fullmatch(left) and dom.LETTERS.fullmatch(right.lower()) and right.islower() \
                    and f"{left} {right}" in phrases:
                spots.append(index)
        if not spots:
            return False
        index = rng.choice(spots)
        phrase = f"{tokens[index]} {dom.bare(tokens[index + 1])}"
        if per_term.get(("phrase", phrase), 0) >= CASES_PER_PHRASE:
            return False
        context = " ".join(tokens[:index])
        choice = rng.randrange(3)
        if choice == 0:
            add(row, "domain_train_phrase_clean", context, phrase, phrase, term=phrase)
        else:
            operator = rng.choice([noise.drop_space, noise.space_to_letter, noise.transpose_space])
            typed = operator(phrase, rng)
            # Typed parts that are all known words read as two intended words, so the case has no slip to see.
            if typed is None or typed == phrase or all(part in known for part in typed.split(" ")) or not allowed_pair(typed, phrase):
                return False
            add(row, "domain_train_phrase_space", context, typed, phrase, term=phrase)
        per_term[("phrase", phrase)] = per_term.get(("phrase", phrase), 0) + 1
        return True

    makers = {"stream_technical": make_stream_technical, "stream_written": make_stream_written, "term_slip": make_term_slip,
              "term_space": make_term_space, "phrase": make_phrase}
    used_rows = 0
    for row in rows:
        if all(made[kind] >= QUOTAS[kind] for kind in QUOTAS):
            break
        rng = random.Random(f"{SEED}-case:{row['source']}:{row['document']}:{row['text']}")
        # The kind that is furthest from its quota takes the sentence, when the sentence fits it.
        for kind in sorted(QUOTAS, key=lambda kind: made[kind] / QUOTAS[kind]):
            if made[kind] < QUOTAS[kind] and makers[kind](row, rng):
                made[kind] += 1
                used_rows += 1
                break
    short = {kind: made[kind] for kind in QUOTAS if made[kind] < QUOTAS[kind]}

    arguments.out.mkdir(parents=True, exist_ok=True)
    report = {"seed": SEED, "quotas": QUOTAS, "made": made, "kinds_under_their_quota": short, "sentences_read": len(rows),
              "sentences_used": used_rows, "dropped_sentences": dropped, "skipped": skipped,
              "pack_words": len(kinds), "withheld_words": len(withheld),
              "evaluation_pairs": len(evaluation_pairs), "evaluation_typed": len(evaluation_typed), "splits": {}}
    for split in ("train", "stop"):
        chosen = [case for case in cases if case["split"] == split]
        categories, groups, sources = {}, {}, {}
        for case in chosen:
            categories[case["category"]] = categories.get(case["category"], 0) + 1
            groups[case["source_group"]] = groups.get(case["source_group"], 0) + 1
            source = ":".join(case["source"].split(":")[:2])
            sources[source] = sources.get(source, 0) + 1
        (arguments.out / f"cases.{split}.jsonl").write_text("".join(json.dumps(case) + "\n" for case in chosen),
                                                             encoding="utf-8", newline="\n")
        report["splits"][split] = {"cases": len(chosen), "categories": dict(sorted(categories.items())),
                                   "source_groups": dict(sorted(groups.items())), "sources": dict(sorted(sources.items())),
                                   "words_of_the_pack_with_a_slip_case": len({case["term"] for case in chosen
                                                                               if case["category"].startswith("domain_train_slip")})}
    (arguments.out / "cases-report.json").write_text(json.dumps(report, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
