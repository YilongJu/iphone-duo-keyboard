"""Writes scripts/pinyin-dictionary/wikidata-people.tsv: the names of well-known people in
Chinese characters, for scripts/pinyin-dictionary/modern_words.py.

The Wanxiang lists of people hold about 36,000 names. Many performers and athletes are not
among them. This script asks Wikidata (https://www.wikidata.org, data under CC0 1.0) for every
person who has an article in the Chinese Wikipedia and one of the occupations of OCCUPATIONS,
and takes the title of that article as the person's name.

A title is kept when it is 2 to 4 Chinese characters after two steps: the text in brackets at
its end is cut off, as in "Name (singer)", and Traditional characters become Simplified
characters (OpenCC, conversion t2s). A name written with a dot between its parts, as most
names from other languages are, stays out.

Wikidata changes every day, so the result file is part of the repository, and the lexicon build
reads the file. The file names the day of the query.

Usage, from the repository root:
    uv run --with opencc-python-reimplemented python scripts/pinyin-dictionary/fetch_wikidata_people.py
"""
import datetime
import hashlib
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from opencc import OpenCC

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "wikidata-people.tsv"
CACHE = HERE.parents[1] / "build" / "pinyin-modern" / "wikidata"
ENDPOINT = "https://query.wikidata.org/sparql"
TRIES = 4
NAME = re.compile(r"[一-鿿]{2,4}")
BRACKETS = re.compile(r"\s*[(（][^()（）]*[)）]$")

# The occupations, each with its Wikidata item. "tree" also takes every occupation below the
# item, as "table tennis player" below "athlete". One query for a whole tree can run into the
# time limit of the query service, so the script first asks for the occupations of the tree
# and then asks for their people in groups of TREE_GROUP occupations. The tree below "artist"
# holds painters and writers as well, so the kinds of performers are listed one by one.
TREE_GROUP = 40
OCCUPATIONS = [
    ("athlete", "Q2066131", "tree"),
    ("singer", "Q177220", "item"),
    ("actor", "Q33999", "item"),
    ("film actor", "Q10800557", "item"),
    ("television actor", "Q10798782", "item"),
    ("voice actor", "Q2405480", "item"),
    ("musician", "Q639669", "item"),
    ("singer-songwriter", "Q488205", "item"),
    ("songwriter", "Q753110", "item"),
    ("composer", "Q36834", "item"),
    ("recording artist", "Q55960555", "item"),
    ("television presenter", "Q947873", "item"),
    ("model", "Q4610556", "item"),
    ("comedian", "Q245068", "item"),
    ("dancer", "Q5716684", "item"),
    ("film director", "Q2526255", "item"),
    ("screenwriter", "Q28389", "item"),
    ("film producer", "Q3282637", "item"),
    ("YouTuber", "Q17125263", "item"),
    ("Internet celebrity", "Q2045208", "item"),
    ("influencer", "Q2906862", "item"),
    ("podcaster", "Q15077007", "item"),
    ("professional gamer", "Q4379701", "item"),
    ("Go player", "Q12039558", "item"),
    ("snooker player", "Q17165321", "item"),
]


def ask(query: str, column: str) -> list[str]:
    """The lines of one column that the query service answers, without the header line. The
    answer of a query is kept in build/pinyin-modern/wikidata/, so a second run of the script
    on the same day asks only for what the first run did not get."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / (hashlib.sha256(query.encode("utf-8")).hexdigest()[:24] + ".tsv")
    if cached.exists():
        return cached.read_text(encoding="utf-8").splitlines()[1:]
    request = urllib.request.Request(
        ENDPOINT + "?" + urllib.parse.urlencode({"query": query}),
        headers={"Accept": "text/tab-separated-values", "User-Agent": "pinyin-lexicon-build/1.0"})
    # The service ends a query after 60 seconds and then puts the error into the text. How long
    # a query takes changes with the load of the service, so a query gets TRIES tries.
    for attempt in range(1, TRIES + 1):
        with urllib.request.urlopen(request, timeout=120) as response:
            text = response.read().decode("utf-8")
        lines = text.splitlines()
        finished = bool(lines) and lines[0] == column and "TimeoutException" not in text and "java.util.concurrent" not in text
        # The query service asks clients to leave time between queries.
        time.sleep(2 if finished else 30)
        if finished:
            cached.write_text(text, encoding="utf-8")
            return lines[1:]
        print(f"try {attempt} of {TRIES} did not finish: {query[:90]}", flush=True)
    raise SystemExit(f"the query did not finish in {TRIES} tries: {query[:120]!r} gave {text[-300:]!r}")


def titles_of(item: str, kind: str) -> list[str]:
    """The titles of the Chinese Wikipedia articles of the people with this occupation."""
    items = [item]
    if kind == "tree":
        items = []
        for line in ask(f"SELECT ?occupation WHERE {{ ?occupation wdt:P279* wd:{item} }}", "?occupation"):
            match = re.fullmatch(r"<http://www\.wikidata\.org/entity/(Q\d+)>", line)
            if match is None:
                raise SystemExit(f"unexpected occupation below {item}: {line!r}")
            items.append(match.group(1))
        items = sorted(set(items), key=lambda name: int(name[1:]))
    titles = []
    for start in range(0, len(items), TREE_GROUP):
        values = " ".join(f"wd:{name}" for name in items[start:start + TREE_GROUP])
        query = (f"SELECT ?name WHERE {{ VALUES ?occupation {{ {values} }} ?person wdt:P106 ?occupation . "
                 f"?article schema:about ?person ; schema:isPartOf <https://zh.wikipedia.org/> ; schema:name ?name }}")
        for line in ask(query, "?name"):
            match = re.fullmatch(r'"(.*)"@zh', line)
            if match is None:
                raise SystemExit(f"unexpected line for {item}: {line!r}")
            titles.append(match.group(1))
    return titles


def main():
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    simplified = OpenCC("t2s")
    names: dict[str, str] = {}
    report = []
    for label, item, kind in OCCUPATIONS:
        titles = titles_of(item, kind)
        kept = 0
        for title in titles:
            name = simplified.convert(BRACKETS.sub("", title))
            if NAME.fullmatch(name):
                kept += 1
                names.setdefault(name, label)
        report.append(f"{label} ({item}): {len(titles)} articles, {kept} names of 2 to 4 Chinese characters")
        print(report[-1], flush=True)
    day = datetime.date.today().isoformat()
    header = [
        "# Names of well-known people in Chinese characters: the titles of the Chinese Wikipedia articles",
        f"# of the people that Wikidata lists with one of the occupations below, asked on {day}.",
        "# scripts/pinyin-dictionary/fetch_wikidata_people.py writes this file. Wikidata's data is under CC0 1.0.",
        "# Columns: the name, and the first occupation of the list that holds the person.",
    ] + [f"# {line}" for line in report]
    body = [f"{name}\t{label}" for name, label in sorted(names.items())]
    OUTPUT.write_text("\n".join(header + body) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT.name}: {len(names)} names")


if __name__ == "__main__":
    main()
