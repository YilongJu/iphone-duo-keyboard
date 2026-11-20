"""Brings the Pinyin lexicon's words up to date with the word lists of the Wanxiang project.

The Pinyin lexicon (Shared/lexicon-pinyin.bin) comes from the language model and the dictionary
of libime. That model puts four fifths of its words at or near one lowest probability, the
floor, so it cannot order them: a vogue word of 2021 counts as much as a word nobody writes.
The model also lacks many names and terms of the last years.

The Wanxiang word lists (https://github.com/amzxyz/rime-wanxiang, CC BY 4.0) hold a weight for
each word and phrase, which grows with how often people write it. This script turns the weights
into lines for scripts/typing-engine/build_pinyin_lexicon_from_libime.py --updates:

- A new value: a word of the libime model in the floor band gets the probability that fits its
  Wanxiang weight, when that probability is higher than the model's. The floor band reaches
  FLOOR_MARGIN above the floor. On the dev cases this choice and the other one of
  --floor-words, which also lowers a word with a lower fit, score alike, and this choice
  changes 21,482 words where the other changes 167,298.
- An addition: a word that only Wanxiang holds joins the lexicon with the probability that fits
  its weight.

The fit is a straight line between the base-10 log of the weight and the base-10 log of the
model's probability. The words that both hold are put in groups by weight, and the line goes
through the middle probability of each group whose middle lies well above the floor. Below
that, most words of a group sit at the floor, and the floor hides their real order.

Wanxiang lists phrases as well as words, such as "when the currency". A phrase that joined the
lexicon as one word would take the place of the reading that the model builds from its own
words. So the script types the Pinyin of every candidate into the engine and reads the text and
the log probability of the engine's first reading. A candidate joins the lexicon in two cases:

1. A new first reading. The engine gives another text, the candidate's own probability beats
   that reading by FIRST_MARGIN, and the reading is not a Wanxiang entry with a weight as high
   as the candidate's. The engine has no good reading of these letters, as for a new vogue word.
   A candidate of the everyday list must also hold no function character, such as a pronoun or
   a particle, and at most one numeral: such a candidate is a piece of a sentence.
2. A known word behind a more likely reading. The engine gives another text, and the candidate
   is a name of the Wanxiang lists of people and places, a title of the Chinese Wikipedia or a
   term of its list of web slang (the lists of https://github.com/felixonmars/fcitx5-pinyin-zhwiki,
   from text under CC BY-SA 4.0). The candidate's probability then stays just under that of
   the engine's reading, so the candidate shows as a later candidate for the same letters.

Steps, from the repository root, on Linux, with the libime files in build/libime-data and the
engine tool in build/engine/duo_cli (see .github/workflows/pinyin-lexicon.yml):
    python3 scripts/pinyin-dictionary/modern_words.py prepare
        Downloads the lists. Writes build/pinyin-modern/values.tsv and candidates.tsv.
    python3 scripts/typing-engine/build_pinyin_lexicon_from_libime.py build/libime-data 1250000 3000000 \
        --updates build/pinyin-modern/values.tsv --output build/pinyin-modern/lexicon-values.bin
    python3 scripts/pinyin-dictionary/modern_words.py select
        Types every candidate into the engine with that lexicon, which takes about half an hour
        on 30 processor threads. Writes build/pinyin-modern/readings.tsv and
        scripts/pinyin-dictionary/pinyin-updates.tsv.gz, the file that the lexicon build reads.
        With --reuse the step reads readings.tsv again and types no candidate.
    python3 scripts/typing-engine/build_pinyin_lexicon_from_libime.py build/libime-data 1250000 3000000 \
        --updates scripts/pinyin-dictionary/pinyin-updates.tsv.gz
"""
import argparse
import collections
import concurrent.futures
import gzip
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import unicodedata
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LIBIME = ROOT / "build" / "libime-data"
WORK = ROOT / "build" / "pinyin-modern"
SOURCES = WORK / "sources"
HASHES_FILE = HERE / "source-hashes.json"
UPDATES = HERE / "pinyin-updates.tsv.gz"

WANXIANG_COMMIT = "e52c2958464d23fe2675f7c6770d921926b5d245"
WANXIANG_URL = "https://raw.githubusercontent.com/amzxyz/rime-wanxiang/{commit}/dicts/{name}.dict.yaml"
ZHWIKI_URL = "https://github.com/felixonmars/fcitx5-pinyin-zhwiki/releases/download/0.3.1/{name}.dict.yaml"
# The Wanxiang lists the script reads: everyday and technical words, well-known people,
# performers and athletes, and places.
LISTS = ("jichu", "mingren", "yiren", "diming")
EVERYDAY_LIST = "jichu"
# The lists of the Chinese Wikipedia: every article title, and the terms of its list of web slang.
TITLE_LISTS = ("zhwiki-20261018", "web-slang-20261018")
# The lowest weight of a candidate, by list. The list of places gives its villages the weight
# 10, and those stay out.
LOWEST_WEIGHT = {"jichu": 1.0, "mingren": 1.0, "yiren": 1.0, "diming": 11.0}
WORD = re.compile(r"[一-鿿]{2,8}")
# A word is in the floor band when the model puts it this close to its lowest probability,
# in base-10 log.
FLOOR_MARGIN = 0.3
# The fit puts the words in groups of this width in base-10 log of the weight. A group counts
# when it holds this many words and its middle probability lies this far above the floor.
FIT_GROUP_WIDTH = 0.25
FIT_GROUP_WORDS = 30
FIT_ABOVE_FLOOR = 0.3
# A fitted value ends here, in base-10 log of the probability: the level of a frequent word.
# Many floor words with a very high weight are short phrases that the model reads as two words,
# such as "one piece of". Their text is the same either way, so a higher place gains nothing.
HIGHEST_VALUE = -5.0
# A candidate is a new first reading when its natural-log probability beats the engine's
# reading by this much.
FIRST_MARGIN = 2.0
# A known word behind a more likely reading stays this far under that reading, in natural log.
BEHIND_STEP = 0.1
# Characters that mark a piece of a sentence: pronouns, particles, and the most frequent
# adverbs, prepositions and conjunctions.
FUNCTION_CHARACTERS = set("的了着吗呢吧啊呀啦嘛哦哈呗们我你您他她它咱谁这那哪啥么很都也就才又还再已把被让跟和与或但而且虽若则因所是没不别请个些每各某几怎")
NUMERALS = set("一二三四五六七八九十百千万亿两零")
LN10 = math.log(10)


def fetch(name: str, url: str) -> Path:
    """One source list, from the cache or the network, checked against its SHA-256."""
    SOURCES.mkdir(parents=True, exist_ok=True)
    path = SOURCES / f"{name}.dict.yaml"
    if not path.exists():
        request = urllib.request.Request(url, headers={"User-Agent": "pinyin-lexicon-build"})
        with urllib.request.urlopen(request) as response:
            path.write_bytes(response.read())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    hashes = json.loads(HASHES_FILE.read_text(encoding="utf-8"))
    if hashes.get(path.name) != digest:
        raise SystemExit(f"{path.name}: SHA-256 {digest} differs from source-hashes.json ({hashes.get(path.name)}). "
                         f"Check the new file, then write its hash into source-hashes.json.")
    return path


def toneless(pinyin: str) -> str:
    """Pinyin with tone marks as the letters a person types: "lüè" gives "lve"."""
    text = unicodedata.normalize("NFD", pinyin).replace("ü", "v")
    return "".join(character for character in text if unicodedata.category(character) != "Mn")


def body_lines(path: Path):
    """The lines of a Rime dictionary file after its header."""
    in_body = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if not in_body:
            in_body = line == "..."
            continue
        if line and not line.startswith("#"):
            yield line


def read_wanxiang(name: str) -> tuple[dict[tuple[str, str], float], int]:
    """The entries of one list as (word, syllables with a space between them) to weight, and
    the count of lines without a weight that is a number."""
    entries: dict[tuple[str, str], float] = {}
    odd = 0
    for line in body_lines(fetch(name, WANXIANG_URL.format(commit=WANXIANG_COMMIT, name=name))):
        fields = line.split("\t")
        if len(fields) < 2:
            raise SystemExit(f"{name}: a line needs a word and its Pinyin: {line!r}")
        if len(fields) == 2 or not re.fullmatch(r"\d+(\.\d+)?", fields[2]):
            odd += 1
            continue
        key = (fields[0], toneless(fields[1]))
        entries[key] = max(entries.get(key, 0.0), float(fields[2]))
    return entries, odd


def read_titles() -> set[str]:
    """The titles and web slang terms of the Chinese Wikipedia that are words of Chinese characters."""
    titles = set()
    for name in TITLE_LISTS:
        for line in body_lines(fetch(name, ZHWIKI_URL.format(name=name))):
            title = line.split("\t")[0]
            if WORD.fullmatch(title):
                titles.add(title)
    return titles


def read_model_words() -> dict[str, float]:
    """The base-10 log probability of every single word of the libime language model."""
    words = {}
    in_words = False
    with (LIBIME / "lm_sc.arpa").open(encoding="utf-8") as lines:
        for line in lines:
            line = line.rstrip("\n")
            if line.startswith("\\"):
                if in_words:
                    break
                in_words = line == "\\1-grams:"
                continue
            if in_words and line:
                fields = line.split("\t")
                words[fields[1]] = float(fields[0])
    if "<unk>" not in words:
        raise SystemExit("the language model has no <unk> entry, which gives its floor")
    return words


def read_dictionary() -> tuple[set[str], set[str]]:
    """The words of the libime dictionary, and every syllable of its readings."""
    words = set()
    syllables = set()
    for line in (LIBIME / "dict_sc.txt").read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) not in (2, 3):
            raise SystemExit(f"unexpected dictionary line: {line!r}")
        words.add(fields[0])
        syllables.update(fields[1].split("'"))
    return words, syllables


def fit_line(points: list[tuple[float, float, int]]) -> tuple[float, float]:
    """Weighted least squares: the slope and the intercept of y over x. A point is x, y and its weight."""
    total = sum(weight for _, _, weight in points)
    mean_x = sum(x * weight for x, _, weight in points) / total
    mean_y = sum(y * weight for _, y, weight in points) / total
    slope = (sum(weight * (x - mean_x) * (y - mean_y) for x, y, weight in points)
             / sum(weight * (x - mean_x) ** 2 for x, _, weight in points))
    return slope, mean_y - slope * mean_x


def read_weights() -> tuple[dict[str, dict[tuple[str, str], float]], dict[str, float]]:
    """The Wanxiang lists, and the highest weight of each word over all lists and readings."""
    lists = {}
    for name in LISTS:
        lists[name], odd = read_wanxiang(name)
        print(f"{name}: {len(lists[name])} entries, {odd} lines left out because they have no weight that is a number")
    weight: dict[str, float] = collections.defaultdict(float)
    for entries in lists.values():
        for (word, _), value in entries.items():
            weight[word] = max(weight[word], value)
    return lists, dict(weight)


def fit_weights(model: dict[str, float], lexicon_words: set[str], weight: dict[str, float]) -> tuple[float, float, list]:
    """The line between the base-10 log of a Wanxiang weight and the base-10 log of the model's
    probability: its slope, its intercept, and the groups it goes through."""
    floor = model["<unk>"]
    groups: dict[int, list[float]] = collections.defaultdict(list)
    for word in lexicon_words:
        if len(word) >= 2 and weight.get(word, 0.0) >= 1.0:
            groups[math.floor(math.log10(weight[word]) / FIT_GROUP_WIDTH)].append(model[word])
    points = []
    for number, values in sorted(groups.items()):
        middle = sorted(values)[len(values) // 2]
        if len(values) >= FIT_GROUP_WORDS and middle >= floor + FIT_ABOVE_FLOOR:
            points.append(((number + 0.5) * FIT_GROUP_WIDTH, middle, len(values)))
    if len(points) < 3:
        raise SystemExit(f"the fit needs three groups of words above the floor, and it has {len(points)}")
    slope, intercept = fit_line(points)
    return slope, intercept, points


def prepare(floor_words: str):
    model = read_model_words()
    dictionary_words, syllables = read_dictionary()
    floor = model["<unk>"]
    lexicon_words = {word for word in model if word in dictionary_words}
    lists, weight = read_weights()
    slope, intercept, points = fit_weights(model, lexicon_words, weight)
    in_band = [word for word in lexicon_words if model[word] <= floor + FLOOR_MARGIN]
    print(f"floor of the model: {floor:.4f}; {len(in_band)} of {len(lexicon_words)} lexicon words are in the floor band")
    print("groups of the fit (log10 weight, middle log10 probability, words): "
          + " ".join(f"({x:.3f}, {y:.2f}, {count})" for x, y, count in points))
    print(f"fit: log10 probability = {slope:.4f} * log10 weight + {intercept:.4f}")

    def fitted(value: float) -> float:
        return min(slope * math.log10(value) + intercept, HIGHEST_VALUE)

    WORK.mkdir(parents=True, exist_ok=True)
    values = []
    raised = lowered = 0
    for word in sorted(in_band):
        if weight.get(word, 0.0) < 1.0:
            continue
        value = fitted(weight[word])
        if floor_words == "raise" and value <= model[word]:
            continue
        # The file holds seven digits after the point, and a new value is a clear step.
        if abs(value - model[word]) > 1e-6:
            values.append((word, value))
            raised += value > model[word]
            lowered += value < model[word]
    (WORK / "values.tsv").write_text("".join(f"{word}\t\t{value:.7f}\n" for word, value in values), encoding="utf-8")
    print(f"new values ({floor_words}): {len(values)} words of the floor band, {raised} higher and {lowered} lower than in the model")
    top = sorted(values, key=lambda item: -item[1])[:30]
    print("highest new values: " + " ".join(f"{word}({value:.2f})" for word, value in top))

    candidates = []
    skipped = collections.Counter()
    seen = set()
    for name in LISTS:
        for (word, spelled), value in lists[name].items():
            if word in lexicon_words or (word, spelled) in seen:
                continue
            parts = spelled.split(" ")
            if value < LOWEST_WEIGHT[name]:
                skipped["weight under the list's limit"] += 1
            elif not WORD.fullmatch(word):
                skipped["not 2 to 8 Chinese characters"] += 1
            elif len(parts) != len(word) or any(part not in syllables for part in parts):
                skipped["Pinyin that the libime dictionary does not use"] += 1
            else:
                seen.add((word, spelled))
                candidates.append((word, "'".join(parts), fitted(value), value, name))
    (WORK / "candidates.tsv").write_text(
        "".join(f"{word}\t{spelled}\t{value:.7f}\t{raw:g}\t{name}\n" for word, spelled, value, raw, name in candidates),
        encoding="utf-8")
    print(f"candidates: {len(candidates)}; left out: {dict(skipped)}")
    print("by list: " + str(dict(collections.Counter(name for *_, name in candidates))))


def type_into_engine(job: tuple[str, str, list[tuple[int, str]]]) -> dict[int, tuple[str, float]]:
    cli, lexicon, items = job
    lines = "".join(f"{index}\t{letters}\n" for index, letters in items)
    completed = subprocess.run([cli, "pinyin", lexicon, "score=1"], input=lines, capture_output=True, text=True,
                               encoding="utf-8", check=True)
    answers = {}
    for line in completed.stdout.splitlines():
        fields = line.split("\t")
        # Letters that the engine cannot read come back as they are, without a score.
        answers[int(fields[0])] = (fields[1], float(fields[2]) if len(fields) == 3 else -math.inf)
    return answers


def read_candidates() -> list[tuple[str, str, float, float, str]]:
    candidates = []
    for line in (WORK / "candidates.tsv").read_text(encoding="utf-8").splitlines():
        word, spelled, value, raw, name = line.split("\t")
        candidates.append((word, spelled, float(value), float(raw), name))
    return candidates


def engine_readings(candidates, cli: Path, lexicon: Path, jobs: int, reuse: bool) -> list[tuple[str, float]]:
    """The engine's first reading of each candidate's Pinyin: its text and its natural-log probability."""
    path = WORK / "readings.tsv"
    if reuse:
        readings = []
        for line in path.read_text(encoding="utf-8").splitlines():
            text, score = line.split("\t")
            readings.append((text, float(score)))
        if len(readings) != len(candidates):
            raise SystemExit(f"{path.name} holds {len(readings)} readings for {len(candidates)} candidates. Run without --reuse.")
        return readings
    items = [(index, spelled.replace("'", "")) for index, (_, spelled, *_rest) in enumerate(candidates)]
    size = max(1, math.ceil(len(items) / (jobs * 8)))
    chunks = [(str(cli), str(lexicon), items[start:start + size]) for start in range(0, len(items), size)]
    answers: dict[int, tuple[str, float]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        for part in pool.map(type_into_engine, chunks):
            answers.update(part)
    if len(answers) != len(items):
        raise SystemExit(f"the engine answered {len(answers)} of {len(items)} candidates")
    readings = [answers[index] for index in range(len(items))]
    path.write_text("".join(f"{text}\t{score:.4f}\n" for text, score in readings), encoding="utf-8")
    return readings


def is_piece_of_a_sentence(word: str) -> bool:
    return bool(set(word) & FUNCTION_CHARACTERS) or sum(character in NUMERALS for character in word) >= 2


def select(cli: Path, lexicon: Path, jobs: int, reuse: bool):
    candidates = read_candidates()
    readings = engine_readings(candidates, cli, lexicon, jobs, reuse)
    _, weight = read_weights()
    titles = read_titles()
    print(f"titles and web slang terms of the Chinese Wikipedia: {len(titles)}")

    additions = []
    counts = collections.Counter()
    for (word, spelled, value, raw, name), (text, score) in zip(candidates, readings):
        if text == word:
            counts["the engine types it already"] += 1
            continue
        listed_higher = weight.get(text, 0.0) >= raw
        first = value * LN10 > score + FIRST_MARGIN and not listed_higher
        if name == EVERYDAY_LIST and first and not is_piece_of_a_sentence(word):
            counts["added as a new first reading"] += 1
            additions.append((word, spelled, value, raw, name, "first"))
        elif name != EVERYDAY_LIST and first:
            counts["added as a new first reading"] += 1
            additions.append((word, spelled, value, raw, name, "first"))
        elif name != EVERYDAY_LIST or word in titles:
            counts["added behind a more likely reading"] += 1
            additions.append((word, spelled, min(value, (score - BEHIND_STEP) / LN10), raw, name, "behind"))
        else:
            counts["left out"] += 1
    print(f"candidates: {len(candidates)}; " + "; ".join(f"{reason}: {count}" for reason, count in counts.items()))
    print("additions by list: " + str(dict(collections.Counter(row[4] for row in additions))))
    print("additions by count of characters: " + str(dict(sorted(collections.Counter(len(row[0]) for row in additions).items()))))

    values = (WORK / "values.tsv").read_text(encoding="utf-8")
    text = values + "".join(f"{word}\t{spelled}\t{value:.7f}\n" for word, spelled, value, *_ in additions)
    # A fixed time stamp and no file name in the header, so the same lines give the same file.
    with open(UPDATES, "wb") as raw_file:
        with gzip.GzipFile(filename="", fileobj=raw_file, mode="wb", mtime=0) as packed:
            packed.write(text.encode("utf-8"))
    (WORK / "additions.tsv").write_text(
        "".join(f"{word}\t{spelled}\t{value:.7f}\t{raw:g}\t{name}\t{kind}\n" for word, spelled, value, raw, name, kind in additions),
        encoding="utf-8")
    print(f"wrote {UPDATES.relative_to(ROOT)}: {values.count(chr(10))} new values and {len(additions)} additions, "
          f"{UPDATES.stat().st_size} bytes")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["prepare", "select"])
    parser.add_argument("--floor-words", choices=["raise", "fit"], default="raise",
                        help="prepare: give every weighted word of the floor band its fitted value (fit), "
                             "or only the words whose fitted value is higher (raise)")
    parser.add_argument("--cli", type=Path, default=ROOT / "build" / "engine" / "duo_cli")
    parser.add_argument("--lexicon", type=Path, default=WORK / "lexicon-values.bin")
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument("--reuse", action="store_true", help="select: read build/pinyin-modern/readings.tsv again")
    arguments = parser.parse_args()
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    if arguments.step == "prepare":
        prepare(arguments.floor_words)
    else:
        select(arguments.cli, arguments.lexicon, arguments.jobs, arguments.reuse)


if __name__ == "__main__":
    main()
