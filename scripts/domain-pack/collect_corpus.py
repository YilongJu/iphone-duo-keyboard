"""Collects the domain text of the "AI and software" vocabulary pack, and counts its words.

The script reads three kinds of public text, each under a licence that allows a word list and
short quoted sentences in a public repository:

- arXiv abstracts of cs.CL, cs.LG, cs.AI and cs.SE, the newest first, through the arXiv API.
  arXiv metadata, the abstract included, is CC0 1.0.
- Posts and comments of five Stack Exchange sites, from the data dump of 2024-04 on the Internet
  Archive. The content is CC BY-SA 4.0 (older posts CC BY-SA 3.0 and 2.5).
- The documentation prose of open-source projects on GitHub. sources.json names each
  repository, its folders and the licence that the GitHub API reports for it.

Every document goes to one of three buckets by a hash of its identifier:
    build   80 of 100   the counts that build the pack
    dev     10 of 100   sentences for the dev half of the test cases
    test    10 of 100   sentences for the test half of the test cases
So the test sentences come from documents that the pack never saw. A held-out sentence whose
letters equal those of a sentence in a build document is left out as well.

Outputs in --out:
    counts.tsv      one row per word form and source of the build bucket:
                    form, source, count inside a sentence, count as the first word of a sentence,
                    count of documents
    pairs.tsv       one row per pair of neighbouring lower-case words of the build bucket
    totals.json     words, documents and sentences per source, group and bucket, with the licences
    sentences.dev.jsonl, sentences.test.jsonl
                    held-out sentences with their source and document

Usage, on Linux with 7z installed, from the repository root:
    python3 scripts/domain-pack/collect_corpus.py --out build/domain-pack/corpus
"""
import argparse
import hashlib
import html
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ElementTree
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCES: dict = {}
USER_AGENT = "domain-vocabulary-build/1.0"

# A word form: letters, with single hyphens or apostrophes inside. A token with a digit or any
# other sign is not a word form, and it breaks a pair.
FORM = re.compile(r"[A-Za-z]+(?:['\-][A-Za-z]+)*")
EDGE = ".,!?;:\"()[]{}<>*_~`“”‘’…"
# Stands for code, a formula or a link that the cleaning took out. It is not a word form.
GAP = "\u00a7"
SENTENCE_END = re.compile(r"(?<=[.!?])[\"')\]]*\s+(?=[\"'(\[]*[A-Z])")
MINIMUM_ROW_COUNT = 3
HELD_OUT_PER_SOURCE = 30000


def bucket_of(document_id: str) -> str:
    value = int.from_bytes(hashlib.sha256(document_id.encode()).digest()[:4], "big") % 100
    return "build" if value < 80 else ("dev" if value < 90 else "test")


def fetch(url: str, attempts: int = 5) -> bytes:
    for attempt in range(attempts):
        try:
            headers = {"User-Agent": USER_AGENT}
            # A runner shares its address with others, and GitHub limits requests without a token per address.
            if url.startswith("https://api.github.com/") and os.environ.get("GITHUB_TOKEN"):
                headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except Exception as error:  # noqa: BLE001  the last attempt raises below
            print(f"  attempt {attempt + 1} of {url} gave {error!r}", flush=True)
            time.sleep(10 * (attempt + 1))
    raise SystemExit(f"{url} did not answer in {attempts} attempts")


# ---- Cleaning ----

def clean_html(body: str) -> str:
    body = re.sub(r"(?is)<pre.*?</pre>", f" {GAP}. ", body)
    body = re.sub(r"(?is)<code.*?</code>", f" {GAP} ", body)
    body = re.sub(r"(?is)<blockquote.*?</blockquote>", " ", body)
    body = re.sub(r"(?i)</p>|<br\s*/?>|</li>|</h\d>", "\n", body)
    body = re.sub(r"(?s)<[^>]+>", " ", body)
    return html.unescape(body)


def clean_comment(text: str) -> str:
    text = re.sub(r"`[^`]*`", f" {GAP} ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", f" {GAP} ", text)
    return re.sub(r"@\w+", f" {GAP} ", text)


def clean_latex(text: str) -> str:
    text = re.sub(r"\$[^$]*\$", f" {GAP} ", text)
    return re.sub(r"\\[A-Za-z]+(\{[^}]*\})?", f" {GAP} ", text)


def clean_markdown(text: str) -> str:
    text = re.sub(r"(?s)\A---\n.*?\n---\n", "", text)
    text = re.sub(r"(?s)```.*?```|~~~.*?~~~", f"\n{GAP}.\n", text)
    text = re.sub(r"(?s)<!--.*?-->", " ", text)
    text = re.sub(r"(?s)\{\{.*?\}\}|\{%.*?%\}", f" {GAP} ", text)
    # A documentation directive in double brackets, as "[[autodoc]] ClassName", is markup.
    text = re.sub(r"(?m)^.*\[\[[^\]]*\]\].*$", "", text)
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        # A heading, a table row, a directive and an indented code line do not hold running prose.
        if stripped.startswith(("#", "|", "..", ":::", "import ", "export ", "<", ">", "===", "---", "~~~", "***")):
            lines.append("")
            continue
        if line.startswith(("    ", "\t")):
            lines.append("")
            continue
        lines.append(re.sub(r"^\s*(?:[-*+]|\d+\.)\s+", "", line))
    text = "\n".join(lines)
    text = re.sub(r"``[^`]*``|`[^`]*`", f" {GAP} ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\[[^\]]*\]", r"\1", text)
    text = re.sub(r"https?://\S+", f" {GAP} ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"[*_]{1,3}([^*_\n]+)[*_]{1,3}", r"\1", text)
    return html.unescape(text)


def sentences_of(text: str) -> list[str]:
    """The sentences of a cleaned text. A line break between two paragraphs ends a sentence."""
    result = []
    for paragraph in re.split(r"\n\s*\n|\n(?=\s*$)", text):
        paragraph = " ".join(paragraph.split())
        if paragraph:
            result.extend(part for part in SENTENCE_END.split(paragraph) if part)
    return result


def forms_of(sentence: str) -> list[str | None]:
    """The word forms of a sentence in order, with None for a token that is not a word form."""
    result: list[str | None] = []
    for raw in sentence.replace("’", "'").split():
        token = raw.strip(EDGE)
        # Punctuation inside the sentence, as a comma, also breaks a pair of neighbours.
        ends_clause = raw.rstrip("\"')]}*_").endswith((",", ";", ":", ".", "!", "?"))
        result.append(token if FORM.fullmatch(token) else None)
        if ends_clause:
            result.append(None)
    return result


# ---- Counting ----

class Counts:
    def __init__(self):
        self.inside: dict[str, Counter] = {}
        self.first: dict[str, Counter] = {}
        self.documents: dict[str, Counter] = {}
        self.pairs: dict[str, Counter] = {}
        self.totals: dict[str, dict] = {}
        self.build_sentences: set[int] = set()
        self.held_out: dict[str, dict[str, list]] = {"dev": {}, "test": {}}
        self.held_out_seen: dict[tuple[str, str], int] = {}
        self.random = random.Random(20261111)

    @staticmethod
    def letters_hash(sentence: str) -> int:
        letters = re.sub(r"[^a-z]", "", sentence.lower())
        return int.from_bytes(hashlib.blake2b(letters.encode(), digest_size=8).digest(), "big")

    def add(self, source: str, group: str, document_id: str, text: str) -> None:
        bucket = bucket_of(f"{source}:{document_id}")
        total = self.totals.setdefault(source, {"group": group, "build": [0, 0, 0], "dev": [0, 0, 0], "test": [0, 0, 0]})
        sentences = sentences_of(text)
        total[bucket][0] += 1
        total[bucket][1] += len(sentences)
        seen_in_document = set()
        for sentence in sentences:
            forms = forms_of(sentence)
            words = sum(1 for form in forms if form is not None)
            total[bucket][2] += words
            if bucket != "build":
                if GAP not in sentence and 5 <= words <= 30 and len(sentence) <= 300:
                    self.keep_held_out(bucket, source, document_id, sentence)
                continue
            self.build_sentences.add(self.letters_hash(sentence))
            inside = self.inside.setdefault(source, Counter())
            first = self.first.setdefault(source, Counter())
            pairs = self.pairs.setdefault("all", Counter())
            previous = None
            for index, form in enumerate(forms):
                if form is not None:
                    (first if index == 0 else inside)[form] += 1
                    seen_in_document.add(form.lower())
                    if previous is not None:
                        pairs[previous.lower() + " " + form.lower()] += 1
                previous = form
        documents = self.documents.setdefault(source, Counter())
        for form in seen_in_document:
            documents[form] += 1

    def keep_held_out(self, bucket: str, source: str, document_id: str, sentence: str) -> None:
        """Keeps a seeded sample of the held-out sentences of each source, HELD_OUT_PER_SOURCE at most."""
        kept = self.held_out[bucket].setdefault(source, [])
        seen = self.held_out_seen.get((bucket, source), 0) + 1
        self.held_out_seen[(bucket, source)] = seen
        row = {"source": source, "document": document_id, "text": sentence}
        if len(kept) < HELD_OUT_PER_SOURCE:
            kept.append(row)
        else:
            place = self.random.randrange(seen)
            if place < HELD_OUT_PER_SOURCE:
                kept[place] = row

    def write(self, out: Path, licences: dict) -> None:
        with (out / "counts.tsv").open("w", encoding="utf-8", newline="\n") as file:
            file.write("form\tsource\tinside\tfirst\tdocuments\n")
            # A word stays out when all sources together hold it fewer than MINIMUM_ROW_COUNT times.
            lower_total = Counter()
            for source in self.inside:
                for counter in (self.inside[source], self.first[source]):
                    for form, count in counter.items():
                        lower_total[form.lower()] += count
            for source in sorted(self.inside):
                for form in sorted(set(self.inside[source]) | set(self.first[source])):
                    if lower_total[form.lower()] < MINIMUM_ROW_COUNT:
                        continue
                    file.write(f"{form}\t{source}\t{self.inside[source][form]}\t{self.first[source][form]}\t"
                               f"{self.documents[source][form.lower()]}\n")
        with (out / "pairs.tsv").open("w", encoding="utf-8", newline="\n") as file:
            file.write("pair\tcount\n")
            for pair, count in sorted(self.pairs.get("all", Counter()).items()):
                if count >= 10:
                    file.write(f"{pair}\t{count}\n")
        left_out = 0
        for bucket in ("dev", "test"):
            with (out / f"sentences.{bucket}.jsonl").open("w", encoding="utf-8", newline="\n") as file:
                for source in sorted(self.held_out[bucket]):
                    for row in self.held_out[bucket][source]:
                        if self.letters_hash(row["text"]) in self.build_sentences:
                            left_out += 1
                            continue
                        file.write(json.dumps(row, ensure_ascii=False) + "\n")
        totals = {"columns": ["documents", "sentences", "words"], "sources": self.totals, "licences": licences,
                  "held_out_sentences_left_out_for_a_build_twin": left_out}
        (out / "totals.json").write_text(json.dumps(totals, indent=1), encoding="utf-8", newline="\n")


# ---- Sources ----

def read_arxiv(counts: Counts, work: Path) -> None:
    settings = SOURCES["arxiv"]
    atom = "{http://www.w3.org/2005/Atom}"
    for category in settings["categories"]:
        got = 0
        for start in range(0, settings["abstracts_per_category"], settings["page"]):
            url = (f"https://export.arxiv.org/api/query?search_query=cat:{category}&start={start}"
                   f"&max_results={settings['page']}&sortBy=submittedDate&sortOrder=descending")
            entries = []
            # The API sometimes answers a page with no entry. The same request then works a little later.
            for attempt in range(6):
                entries = ElementTree.fromstring(fetch(url)).findall(atom + "entry")
                if entries:
                    break
                time.sleep(20)
            if not entries:
                raise SystemExit(f"arXiv gave no entry for {category} from {start}")
            for entry in entries:
                identifier = entry.find(atom + "id").text.rsplit("/", 1)[-1].split("v")[0]
                counts.add(f"arxiv:{category}", "arxiv", identifier, clean_latex(entry.find(atom + "summary").text))
            got += len(entries)
            time.sleep(3)
        print(f"arxiv {category}: {got} abstracts", flush=True)


def read_stack_exchange(counts: Counts, work: Path) -> None:
    settings = SOURCES["stack_exchange"]
    for site, group in settings["sites"].items():
        archive = work / f"{site}.7z"
        if not archive.exists():
            archive.write_bytes(fetch(settings["url"].format(site=site)))
        folder = work / site
        folder.mkdir(exist_ok=True)
        subprocess.run(["7z", "x", "-y", f"-o{folder}", str(archive), "Posts.xml", "Comments.xml"],
                       check=True, stdout=subprocess.DEVNULL)
        rows = 0
        for name, field, cleaner in (("Posts.xml", "Body", clean_html), ("Comments.xml", "Text", clean_comment)):
            for _, element in ElementTree.iterparse(folder / name, events=("end",)):
                if element.tag == "row" and element.get(field):
                    counts.add(f"stackexchange:{site}", group, f"{name}:{element.get('Id')}", cleaner(element.get(field)))
                    rows += 1
                element.clear()
        for name in ("Posts.xml", "Comments.xml"):
            (folder / name).unlink()
        archive.unlink()
        print(f"stackexchange {site}: {rows} posts and comments", flush=True)


def read_repositories(counts: Counts, work: Path) -> dict:
    licences = {}
    for repository, settings in SOURCES["repositories"].items():
        folder = work / repository.replace("/", "__")
        if not folder.exists():
            subprocess.run(["git", "clone", "--quiet", "--depth", "1", "--filter=blob:none", "--sparse",
                            f"https://github.com/{repository}", str(folder)], check=True)
            subprocess.run(["git", "-C", str(folder), "sparse-checkout", "set", "--no-cone",
                            *[f"*.{ext}" if path == "." else f"/{path}/**/*.{ext}"
                              for path in settings["folders"] for ext in ("md", "mdx", "rst", "ipynb")]],
                           check=True)
        commit = subprocess.run(["git", "-C", str(folder), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        api = json.loads(fetch(f"https://api.github.com/repos/{repository}"))
        reported = (api.get("license") or {}).get("spdx_id")
        if reported != settings["licence"]:
            raise SystemExit(f"{repository}: GitHub reports the licence {reported}, and sources.json says {settings['licence']}")
        licences[repository] = {"licence": reported, "commit": commit, "folders": settings["folders"]}
        files = 0
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or path.suffix not in (".md", ".mdx", ".rst", ".ipynb") or ".git" in path.parts:
                continue
            relative = path.relative_to(folder).as_posix()
            # Translations of the documentation are not English text.
            if not any(prefix == "." or relative.startswith(prefix + "/") for prefix in settings["folders"]):
                continue
            raw = path.read_text(encoding="utf-8", errors="replace")
            if path.suffix == ".ipynb":
                try:
                    cells = json.loads(raw).get("cells", [])
                except json.JSONDecodeError:
                    continue
                raw = "\n\n".join("".join(cell.get("source", [])) for cell in cells if cell.get("cell_type") == "markdown")
            counts.add(f"github:{repository}", settings["group"], relative, clean_markdown(raw))
            files += 1
        print(f"github {repository} at {commit[:8]}: {files} files", flush=True)
    return licences


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sources", type=Path, default=HERE / "sources.json")
    parser.add_argument("--only", choices=["arxiv", "stack_exchange", "repositories"], action="append",
                        help="read these kinds only, for a short check of the script")
    arguments = parser.parse_args()
    SOURCES.update(json.loads(arguments.sources.read_text(encoding="utf-8")))
    arguments.out.mkdir(parents=True, exist_ok=True)
    work = arguments.out / "raw"
    work.mkdir(exist_ok=True)
    kinds = arguments.only or ["arxiv", "stack_exchange", "repositories"]
    counts = Counts()
    licences = {"arxiv": SOURCES["arxiv"]["licence"], "stack_exchange": SOURCES["stack_exchange"]["licence"]}
    if "repositories" in kinds:
        licences["repositories"] = read_repositories(counts, work)
    if "arxiv" in kinds:
        read_arxiv(counts, work)
    if "stack_exchange" in kinds:
        read_stack_exchange(counts, work)
    counts.write(arguments.out, licences)
    for source, total in sorted(counts.totals.items()):
        print(f"{source:48s} {total['group']:18s} build {total['build']} dev {total['dev']} test {total['test']}")
    if not counts.totals:
        sys.exit("no text was read")


if __name__ == "__main__":
    main()
