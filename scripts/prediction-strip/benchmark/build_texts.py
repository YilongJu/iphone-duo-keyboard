"""Builds the text sets of the benchmark of the predicted words
(docs/prediction-strip-benchmark-design.md, "Text sets"), with their dev and test halves.

Each set keeps the capitals and the marks of its source. A sentence is left out when it holds a
character outside ASCII, an empty chunk (two spaces in a row, or a space at an end), or fewer
than 3 chunks or more than 40.

  technical  the 1,000 sentences with the lowest SHA-256 of source, document and text, in the
             dev and in the test bucket of the domain corpus (scripts/domain-pack/collect_corpus.py)
  everyday   the Tatoeba sentences of the everyday cases of english-domain-stream, as written
  mobile     every sentence of mobile_orig.txt of the Enron Mobile archive. A sentence whose
             SHA-256 is an even number goes to the dev half, and the others to the test half.

The script reads the test files only to build the texts. It scores nothing.

Usage, in WSL, from the repository root:
    python3 scripts/prediction-strip/benchmark/build_texts.py --corpus CORPUS_FOLDER \
        --tatoeba eng_sentences.tsv.bz2 --enron enronmobile.zip
"""
import argparse
import bz2
import hashlib
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rules import BENCH, ROOT, parse_chunk  # noqa: E402

CASES = ROOT / "scripts" / "typing-evaluation" / "cases"
TECHNICAL_SENTENCES = 1000
ENRON_FILE = "enronmobile/mobile_orig.txt"


def reason_to_drop(text: str) -> str | None:
    if not text.isascii():
        return "a character outside ASCII"
    if any(character in text for character in "\t\n\r"):
        return "a tab or a line break"
    chunks = text.split(" ")
    if any(not chunk for chunk in chunks):
        return "an empty chunk"
    if len(chunks) < 3:
        return "fewer than 3 chunks"
    if len(chunks) > 40:
        return "more than 40 chunks"
    return None


def keep(rows: list[dict], dropped: dict[str, int]) -> list[dict]:
    kept = []
    for row in rows:
        reason = reason_to_drop(row["text"])
        if reason is None:
            kept.append(row)
        else:
            dropped[reason] = dropped.get(reason, 0) + 1
    return kept


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def technical(corpus: Path, half: str, dropped: dict[str, int]) -> list[dict]:
    rows = {}
    with (corpus / f"sentences.{half}.jsonl").open(encoding="utf-8") as file:
        for line in file:
            row = json.loads(line)
            key = sha(f"{row['source']}|{row['document']}|{row['text']}")
            rows[key] = {"id": f"technical-{half}-{key[:12]}", "text": row["text"],
                         "source": f"{row['source']}:{row['document']}"}
    kept = keep([rows[key] for key in sorted(rows)], dropped)
    dropped["past the first 1,000"] = max(len(kept) - TECHNICAL_SENTENCES, 0)
    return kept[:TECHNICAL_SENTENCES]


def everyday(tatoeba: Path, half: str, dropped: dict[str, int]) -> list[dict]:
    ids = []
    for line in (CASES / f"english-domain-stream.{half}.jsonl").read_text(encoding="utf-8").splitlines():
        case = json.loads(line)
        if case["stream"] == "everyday":
            source, _, number = case["source"].partition(":")
            if source != "tatoeba":
                raise SystemExit(f"{case['id']} is no Tatoeba sentence")
            ids.append(number)
    wanted = set(ids)
    texts = {}
    with bz2.open(tatoeba, "rt", encoding="utf-8") as file:
        for line in file:
            number, _, text = line.rstrip("\n").split("\t", 2)
            if number in wanted:
                texts[number] = text
    missing = [number for number in ids if number not in texts]
    if missing:
        raise SystemExit(f"the Tatoeba file lacks {len(missing)} sentences, as {missing[:3]}")
    rows = [{"id": f"everyday-{half}-{number}", "text": texts[number], "source": f"tatoeba:{number}"} for number in ids]
    return keep(rows, dropped)


def mobile(archive: Path, half: str, dropped: dict[str, int]) -> list[dict]:
    with zipfile.ZipFile(archive) as file:
        lines = file.read(ENRON_FILE).decode("utf-8").splitlines()
    rows, seen = [], set()
    for line in lines:
        number, _, text = line.partition("\t")
        if not text:
            raise SystemExit(f"{ENRON_FILE}: line {number!r} is empty")
        if (int(sha(text), 16) % 2 == 0) != (half == "dev"):
            continue
        if text in seen:
            # The file holds 14 short sentences twice, as "Thanks." and "Please call.".
            dropped["a sentence a second time"] = dropped.get("a sentence a second time", 0) + 1
            continue
        seen.add(text)
        rows.append({"id": f"mobile-{half}-{number}", "text": text, "source": f"enronmobile:{number}"})
    return keep(rows, dropped)


def counts(rows: list[dict]) -> dict:
    chunks = [chunk for row in rows for chunk in row["text"].split(" ")]
    return {"sentences": len(rows), "chunks": len(chunks),
            "plain_words": sum(1 for chunk in chunks if parse_chunk(chunk) is not None),
            "characters": sum(len(row["text"]) for row in rows)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", required=True, type=Path, help="folder with sentences.dev.jsonl and sentences.test.jsonl")
    parser.add_argument("--tatoeba", required=True, type=Path)
    parser.add_argument("--enron", required=True, type=Path)
    args = parser.parse_args()
    out = BENCH / "texts"
    out.mkdir(parents=True, exist_ok=True)
    report = {"enron_archive_sha256": hashlib.sha256(args.enron.read_bytes()).hexdigest(), "enron_file": ENRON_FILE, "sets": {}}
    for name, build, source in [("technical", technical, args.corpus), ("everyday", everyday, args.tatoeba),
                                ("mobile", mobile, args.enron)]:
        for half in ("dev", "test"):
            dropped: dict[str, int] = {}
            rows = build(source, half, dropped)
            text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
            (out / f"{name}.{half}.jsonl").write_text(text, encoding="utf-8", newline="\n")
            report["sets"][f"{name}.{half}"] = {**counts(rows), "dropped": dropped, "sha256": sha(text)}
            print(name, half, json.dumps(report["sets"][f"{name}.{half}"]))
    (out / "counts.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
