"""Builds the "AI and software" vocabulary pack from the counts of collect_corpus.py.

Inputs:
- build/domain-pack/corpus/{counts.tsv,pairs.tsv,totals.json}: the artifact of the workflow
  "Domain pack corpus". Only the build bucket of the documents is in these counts.
- Shared/lexicon-english.bin: the base lexicon, for the words it holds and their frequencies.
- The wordfreq package: how frequent each word is in general English.
- Wikipedia's list of common misspellings, as build_english_lexicon.py reads it.
- The Tatoeba English sentences, as build_english_cases.py reads them: the letter case of a
  word in everyday text. Four pairs of ids in five are read. The fifth pair feeds the everyday
  cases of build_english_domain_cases.py, and this script does not read it.
- pack/required-terms.tsv: the words the user asked for by name. The corpus does not decide them.

Outputs:
- scripts/domain-pack/pack/ai-software.terms.tsv     the words from the corpus, with every number
- scripts/domain-pack/pack/ai-software.phrases.tsv   the frequent word pairs of the domain text
- scripts/domain-pack/pack/ai-software.report.json   counts of each rule, and the seed-word check
- Shared/supplement-ai-software.bin                  the supplement lexicon for the engine
- Shared/supplement-ai-software.tsv                  word, frequency, preferred capitals, and the mark of
                                                     a word new to the base lexicon, for the keyboard

Frequencies are on the Zipf scale: 3 means once per million words, 6 once per thousand.

1. Domain frequency. Each source (an arXiv category, a Stack Exchange site, a documentation
   repository) gives the word a rate, its count over the source's words. A source group (arXiv,
   two groups of Stack Exchange sites, two groups of documentation) gives the mean rate of its
   sources, and the domain frequency is the mean of the five group rates. So the largest
   group does not decide a frequency, and the documentation of one project does not either.
2. Pack frequency. A person who works in the area writes domain text some of the time. With the
   share DOMAIN_SHARE of domain text, a word's frequency in that person's text is
   DOMAIN_SHARE * domain frequency + (1 - DOMAIN_SHARE) * everyday frequency. This puts the
   domain words on the scale of the everyday words of the base lexicon.
3. A word enters the pack when its pack frequency is at least MINIMUM_ZIPF, it is in two sources
   or more and in MINIMUM_DOCUMENTS documents, and its pack frequency is at least RAISE_ZIPF above the frequency the keyboard
   has for it today: the base lexicon's value, or the everyday frequency of a word the base
   lexicon lacks.
4. A word that looks like a slip stays out: a listed misspelling, and a word one edit away from a
   word whose frequency in the person's text is SLIP_ZIPF_GAP higher.
5. Preferred capitals. The most frequent form of the word inside a sentence of the domain text,
   when that form holds PREFERRED_SHARE of the word's uses inside a sentence and is not all
   lower case. A word is "everyday" when everyday text (Tatoeba) writes it mostly in another form,
   as "it" for "IT" and "rag" for "RAG": the keyboard then never turns its plain capital form
   into the preferred form.

Usage, from the repository root:
    uv run --with wordfreq python scripts/domain-pack/build_pack.py
"""
import argparse
import bz2
import json
import math
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

from wordfreq import zipf_frequency

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "typing-engine"))
sys.path.insert(0, str(ROOT / "scripts" / "typing-evaluation"))
from build_english_lexicon import (  # noqa: E402
    MISSPELLINGS_FILE, MISSPELLINGS_URL, PAIRS_FILE, SYMSPELL, WORD, WORDS_FILE, fetch, one_edit_away)
from lexicon_format import MODEL_MIXED, write_lexicon  # noqa: E402

HERE = Path(__file__).resolve().parent
PACK = HERE / "pack"
CORPUS = ROOT / "build" / "domain-pack" / "corpus"
BASE_LEXICON = ROOT / "Shared" / "lexicon-english.bin"
TATOEBA = ROOT / "build" / "typing-evaluation" / "eng_sentences.tsv.bz2"
NAME = "ai-software"

# The share of domain text in the text of a person who works in the area. It picks the words.
DOMAIN_SHARE = 0.3
# The share of domain text that the frequencies of the pack assume. The share rule of
# docs/domain-pack-design.md picked 0.3 among 0.03, 0.1, 0.3 and 1.0 on the dev half. The words
# of the pack stay those of DOMAIN_SHARE, so --frequency-share can compare other values.
FREQUENCY_SHARE = 0.3
MINIMUM_ZIPF = 2.5
RAISE_ZIPF = 1.0
MINIMUM_SOURCES = 2
MINIMUM_DOCUMENTS = 20
SLIP_ZIPF_GAP = 2.0
PREFERRED_SHARE = 0.5
# A word of two letters is one key away from many common words, so it needs a higher frequency.
SHORT_WORD_MINIMUM_ZIPF = 4.0
# A requested word gets the frequency of a word that the person uses about once in 30,000 words.
REQUESTED_ZIPF = 4.5
PHRASE_RATIO = 10.0
EDGE = ".,!?;:\"()[]"

# A short list of words that the method must find. It is a check of the method. It adds no word.
SEED = ["gpu", "gpus", "llm", "llms", "api", "sdk", "cli", "rag", "mcp", "lora", "cuda", "vllm", "pytorch", "numpy",
        "kubernetes", "kubectl", "docker", "github", "tokenizer", "embeddings", "quantization", "backprop",
        "hyperparameter", "inference", "agentic", "multimodal", "guardrails", "evals", "repo", "async", "refactor",
        "monorepo", "finetuning"]


def read_base_lexicon(path: Path) -> dict[str, float]:
    """The words of a lexicon file of version 2 with their Zipf frequency."""
    data = path.read_bytes()
    magic, version, node_count, word_count, strings_size, pair_count, _, _ = struct.unpack_from("<8I", data, 0)
    if magic != 0x4C4F5544 or version != 2:
        raise SystemExit(f"{path} is not a lexicon file of version 2")
    words_at = 32 + node_count * 12
    strings_at = len(data) - strings_size
    result = {}
    for index in range(word_count):
        offset, log_probability, _ = struct.unpack_from("<Iff", data, words_at + index * 12)
        end = data.index(b"\0", strings_at + offset)
        result[data[strings_at + offset:end].decode("utf-8")] = log_probability / math.log(10) + 9
    return result


def read_counts() -> tuple[dict, dict, dict, dict, list[str]]:
    totals = json.loads((CORPUS / "totals.json").read_text(encoding="utf-8"))
    source_words = {name: source["build"][2] for name, source in totals["sources"].items()}
    members = defaultdict(list)
    for name, source in totals["sources"].items():
        members[source["group"]].append(name)
    groups = sorted(members)
    inside = defaultdict(Counter)       # lower-case word -> form -> count inside a sentence, all sources
    first = defaultdict(Counter)        # the same for the first word of a sentence
    per_source = defaultdict(Counter)   # lower-case word -> source -> count
    documents = defaultdict(Counter)    # lower-case word -> source -> documents
    with (CORPUS / "counts.tsv").open(encoding="utf-8") as file:
        next(file)
        for line in file:
            form, source, count_inside, count_first, document_count = line.rstrip("\n").split("\t")
            word = form.lower()
            inside[word][form] += int(count_inside)
            first[word][form] += int(count_first)
            per_source[word][source] += int(count_inside) + int(count_first)
            documents[word][source] = int(document_count)

    def rate(counts: Counter) -> float:
        """The mean over the groups of the mean over each group's sources of the word's rate."""
        return sum(sum(counts[source] / source_words[source] for source in members[group]) / len(members[group])
                   for group in groups) / len(groups)

    rates = {word: rate(counts) for word, counts in per_source.items()}
    return rates, inside, first, {"sources": per_source, "documents": documents}, groups


def to_zipf(rate: float) -> float:
    return math.log10(rate * 1e9) if rate > 0 else 0.0


def from_zipf(zipf: float) -> float:
    return 10 ** (zipf - 9) if zipf > 0 else 0.0


def tatoeba_feeds_the_cases(sentence_id: int) -> bool:
    """Whether a Tatoeba sentence may feed the cases of the pack: one pair of ids in five. The
    other sentences give the pack its everyday letter case. So the everyday cases of
    build_english_domain_cases.py come from sentences that this script never reads."""
    return (sentence_id // 2) % 5 == 0


def tatoeba_forms(words: set[str]) -> dict[str, Counter]:
    """The forms of the given lower-case words inside the sentences of everyday text."""
    if not TATOEBA.exists():
        raise SystemExit(f"{TATOEBA} is missing: run scripts/typing-evaluation/build_english_cases.py, which downloads it")
    forms = defaultdict(Counter)
    with bz2.open(TATOEBA, "rt", encoding="utf-8") as lines:
        for line in lines:
            sentence_id, _, text = line.rstrip("\n").split("\t", 2)
            if tatoeba_feeds_the_cases(int(sentence_id)):
                continue
            tokens = text.split()
            for token in tokens[1:]:
                token = token.strip(EDGE)
                if token.lower() in words:
                    forms[token.lower()][token] += 1
    return forms


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain-share", type=float, default=DOMAIN_SHARE)
    parser.add_argument("--frequency-share", type=float, default=FREQUENCY_SHARE,
                        help="write the frequencies for this share of domain text and keep the words of --domain-share, "
                             "to compare shares on one set of words")
    parser.add_argument("--out-shared", type=Path, default=ROOT / "Shared")
    parser.add_argument("--out-pack", type=Path, default=PACK)
    arguments = parser.parse_args()
    share = arguments.domain_share

    base = read_base_lexicon(BASE_LEXICON)
    rates, inside, first, spread, groups = read_counts()
    misspellings = {line.strip().split("->")[0] for line in fetch(MISSPELLINGS_URL, MISSPELLINGS_FILE)
                    if "->" in line and not line.startswith("<")}

    def everyday(word: str) -> float:
        """The frequency the keyboard has for the word today, as a rate."""
        return from_zipf(base[word]) if word in base else from_zipf(zipf_frequency(word, "en"))

    def mixed(word: str) -> float:
        return share * rates.get(word, 0.0) + (1 - share) * everyday(word)

    report = Counter()
    candidates = {}
    for word, rate in rates.items():
        if not WORD.fullmatch(word) or len(word) < 2:
            continue
        pack_zipf = to_zipf(share * rate)
        minimum = SHORT_WORD_MINIMUM_ZIPF if len(word) == 2 else MINIMUM_ZIPF
        if pack_zipf < minimum:
            continue
        report["frequent enough in the domain text"] += 1
        in_sources = sum(1 for count in spread["sources"][word].values() if count >= 3)
        if in_sources < MINIMUM_SOURCES or sum(spread["documents"][word].values()) < MINIMUM_DOCUMENTS:
            report["out: in too few sources or documents"] += 1
            continue
        if pack_zipf - to_zipf(everyday(word)) < RAISE_ZIPF:
            report["out: the keyboard already has the word at about this frequency"] += 1
            continue
        if word in misspellings:
            report["out: a listed misspelling"] += 1
            continue
        candidates[word] = pack_zipf

    # A candidate one edit away from a word that the person writes SLIP_ZIPF_GAP more often is
    # taken for a slip of that word, as build_english_lexicon.py does for the base lexicon.
    words = {}
    for word, pack_zipf in candidates.items():
        own = to_zipf(mixed(word))
        neighbour = max(((to_zipf(mixed(other)), other) for other in one_edit_away(word) if other in base or other in rates),
                        default=(0.0, ""))
        if neighbour[0] - own >= SLIP_ZIPF_GAP:
            report["out: one edit away from a far more frequent word"] += 1
            continue
        words[word] = pack_zipf
    report["words from the corpus"] = len(words)
    report["of them new to the base lexicon"] = sum(1 for word in words if word not in base)
    report["of them raised in the base lexicon"] = sum(1 for word in words if word in base)

    requested = []
    for line in (PACK / "required-terms.tsv").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            term = line.split("\t")[0].strip()
            if not WORD.fullmatch(term):
                raise SystemExit(f"required-terms.tsv: {term!r} is not a word of lower-case letters")
            requested.append(term)

    everyday_forms = tatoeba_forms(set(words) | set(requested))
    rows = []
    for word in sorted(words, key=lambda w: (-words[w], w)):
        forms = inside[word]
        total = sum(forms.values())
        top, top_count = forms.most_common(1)[0] if forms else (word, 0)
        preferred = top if total and top != word and top_count / total >= PREFERRED_SHARE else ""
        other_everyday = sum(count for form, count in everyday_forms[word].items() if form != preferred)
        is_everyday = int(bool(preferred) and other_everyday >= max(5, everyday_forms[word][preferred]))
        rows.append({
            "word": word, "zipf": round(words[word], 2), "preferred": preferred,
            "preferred_share": round(top_count / total, 3) if preferred else "", "everyday": is_everyday,
            "kind": "raised" if word in base else "new", "domain_zipf": round(to_zipf(rates[word]), 2),
            "base_zipf": round(base[word], 2) if word in base else "", "general_zipf": zipf_frequency(word, "en"),
            "sources": sum(1 for count in spread["sources"][word].values() if count >= 3),
            "documents": sum(spread["documents"][word].values()),
        })
    for term in requested:
        if term in words:
            raise SystemExit(f"required-terms.tsv: the corpus already gives {term!r}; take it off the list")
    report["words with preferred capitals"] = sum(1 for row in rows if row["preferred"])
    report["of them everyday words"] = sum(row["everyday"] for row in rows)
    report["words requested by the user"] = len(requested)

    arguments.out_pack.mkdir(parents=True, exist_ok=True)
    columns = list(rows[0])
    (arguments.out_pack / f"{NAME}.terms.tsv").write_text(
        "\t".join(columns) + "\n" + "".join("\t".join(str(row[c]) for c in columns) + "\n" for row in rows),
        encoding="utf-8", newline="\n")

    # The supplement holds the corpus words and the requested words. A requested word is lower
    # case, so it has no preferred capitals.
    shift = math.log10(arguments.frequency_share / share)
    # The last value marks a word that the base lexicon lacks. The keyboard's language model
    # may not change such a word when the person typed it.
    entries = [(row["word"], round(row["zipf"] + shift, 2), row["preferred"], row["everyday"], int(row["kind"] == "new"))
               for row in rows]
    for term in requested:
        if term in base:
            raise SystemExit(f"required-terms.tsv: the base lexicon already holds {term!r}")
        entries.append((term, REQUESTED_ZIPF, "", 0, 1))
    stats = write_lexicon(arguments.out_shared / f"supplement-{NAME}.bin",
                          [(word, word, (zipf - 9) * math.log(10), 0.0) for word, zipf, _, _, _ in sorted(entries)], {}, MODEL_MIXED)
    table = "".join(f"{word}\t{zipf:.2f}\t{preferred}\t{flag}\t{new}\n" for word, zipf, preferred, flag, new in sorted(entries))
    (arguments.out_shared / f"supplement-{NAME}.tsv").write_text(
        "word\tzipf\tpreferred\teveryday\tnew\n" + table, encoding="utf-8", newline="\n")
    report["supplement"] = stats
    report["supplement table bytes"] = (arguments.out_shared / f"supplement-{NAME}.tsv").stat().st_size

    # Frequent pairs of the domain text: both words known, the two words together far more often
    # than chance, and the pair PHRASE_RATIO times as frequent as in the book text of the SymSpell
    # pair list, or not in that list at all. The last rule leaves out "for example" and "thank you".
    book_total = sum(int(line.split()[1]) for line in fetch(SYMSPELL + WORDS_FILE, WORDS_FILE))
    book_pairs = {}
    for line in fetch(SYMSPELL + PAIRS_FILE, PAIRS_FILE):
        left, right, count = line.split()
        book_pairs[f"{left} {right}"] = int(count) / book_total
    known = set(base) | set(words) | set(requested)
    pair_counts = Counter()
    with (CORPUS / "pairs.tsv").open(encoding="utf-8") as file:
        next(file)
        for line in file:
            pair, count = line.rstrip("\n").split("\t")
            pair_counts[pair] += int(count)
    totals = json.loads((CORPUS / "totals.json").read_text(encoding="utf-8"))
    corpus_words = sum(source["build"][2] for source in totals["sources"].values())
    word_counts = {word: sum(counts.values()) for word, counts in spread["sources"].items()}
    phrases = []
    for pair, count in pair_counts.items():
        left, right = pair.split(" ")
        if count < 200 or left not in known or right not in known or len(left) < 3 or len(right) < 3:
            continue
        if left not in words and right not in words and min(zipf_frequency(left, "en"), zipf_frequency(right, "en")) >= 5.5:
            continue
        pmi = math.log2(count * corpus_words / (word_counts[left] * word_counts[right]))
        ratio = (count / corpus_words) / book_pairs[pair] if pair in book_pairs else None
        if pmi >= 5.0 and (ratio is None or ratio >= PHRASE_RATIO):
            phrases.append((count, pair, round(pmi, 2), "" if ratio is None else round(ratio, 1)))
    phrases.sort(key=lambda row: (-row[0], row[1]))
    (arguments.out_pack / f"{NAME}.phrases.tsv").write_text(
        "phrase\tcount\tpmi\ttimes_the_book_rate\n"
        + "".join(f"{pair}\t{count}\t{pmi}\t{ratio}\n" for count, pair, pmi, ratio in phrases),
        encoding="utf-8", newline="\n")
    report["phrases"] = len(phrases)

    seed = {}
    for word in SEED:
        row = next((row for row in rows if row["word"] == word), None)
        if row is not None:
            seed[word] = f"in the pack, {row['kind']}, Zipf {row['zipf']}, preferred {row['preferred'] or 'lower case'}"
        elif word in base:
            seed[word] = (f"not in the pack: the base lexicon has it at Zipf {base[word]:.2f}, "
                          f"and its pack frequency is {to_zipf(share * rates.get(word, 0.0)):.2f}")
        else:
            seed[word] = f"not in the pack and not in the base lexicon: pack frequency {to_zipf(share * rates.get(word, 0.0)):.2f}"
    result = {"domain_share": share, "frequency_share": arguments.frequency_share, "source_groups": groups,
              "rules": dict(report), "seed_check": seed}
    (arguments.out_pack / f"{NAME}.report.json").write_text(json.dumps(result, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
