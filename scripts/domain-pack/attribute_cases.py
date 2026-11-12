"""Writes the attribution of every source sentence in the cases of the vocabulary pack:
scripts/typing-evaluation/cases/english-domain-ATTRIBUTION.tsv.

The case files name each source in the field `source`. This script reads only that field, and
adds what a licence asks for: the address of the source, its author where the source names one,
its date and its licence.

- arXiv: the address of the abstract. arXiv metadata, the abstract included, is CC0 1.0.
- Stack Exchange: the address of the post or comment, the author's display name and profile, the
  date, and the licence version of that date (https://stackoverflow.com/help/licensing). The
  script reads Posts.xml, Comments.xml and Users.xml of the same data dump as collect_corpus.py.
- GitHub: the address of the file at the commit that collect_corpus.py read, and the licence of
  the repository from pack/ai-software.sources.json.
- Tatoeba: the address of the sentence, which names its author. CC BY 2.0 FR.

With --reuse TABLE the script takes the row of a Stack Exchange source from an earlier table,
and reads the data dump only for the sources that the earlier table does not hold. The workflow
runs without it, so the workflow checks every row against the dump.

Usage, on Linux with 7z installed, from the repository root:
    python3 scripts/domain-pack/attribute_cases.py --work build/domain-pack/attribution [--reuse TABLE]
"""
import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from collect_corpus import fetch  # noqa: E402

CASES = ROOT / "scripts" / "typing-evaluation" / "cases"
OUTPUT = CASES / "english-domain-ATTRIBUTION.tsv"


def stack_exchange_licence(date: str) -> str:
    if date < "2011-04-08":
        return "CC BY-SA 2.5"
    return "CC BY-SA 3.0" if date < "2018-05-02" else "CC BY-SA 4.0"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--reuse", type=Path, help="an earlier table whose Stack Exchange rows stay as they are")
    arguments = parser.parse_args()
    earlier = {}
    if arguments.reuse is not None:
        for line in arguments.reuse.read_text(encoding="utf-8").splitlines()[1:]:
            fields = line.split("	")
            if len(fields) != 6:
                raise SystemExit(f"{arguments.reuse}: the line {line!r} does not have 6 columns")
            earlier[fields[0]] = tuple(fields)
    arguments.work.mkdir(parents=True, exist_ok=True)
    settings = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))
    recorded = json.loads((HERE / "pack" / "ai-software.sources.json").read_text(encoding="utf-8"))["licences"]["repositories"]

    sources = set()
    for path in sorted(CASES.glob("english-domain*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            sources.add(json.loads(line)["source"])

    rows = []
    wanted: dict[str, dict[str, set[str]]] = {}
    for source in sorted(sources):
        kind = source.split(":", 1)[0]
        if kind == "arxiv":
            identifier = source.split(":")[2]
            rows.append((source, f"https://arxiv.org/abs/{identifier}", "", "", "", "CC0 1.0 (arXiv metadata)"))
        elif kind == "github":
            _, repository, path = source.split(":", 2)
            entry = recorded[repository]
            rows.append((source, f"https://github.com/{repository}/blob/{entry['commit']}/{path}", "", "", "", entry["licence"]))
        elif kind == "tatoeba":
            rows.append((source, f"https://tatoeba.org/sentences/show/{source.split(':')[1]}", "", "", "", "CC BY 2.0 FR"))
        elif kind == "stackexchange" and source in earlier:
            rows.append(earlier[source])
        elif kind == "stackexchange":
            _, site, file, row_id = source.split(":")
            wanted.setdefault(site, {}).setdefault(file, set()).add(row_id)
        else:
            rows.append((source, "", "", "", "", "written for the case file"))

    for site, files in sorted(wanted.items()):
        archive = arguments.work / f"{site}.7z"
        if not archive.exists():
            archive.write_bytes(fetch(settings["stack_exchange"]["url"].format(site=site)))
        folder = arguments.work / site
        folder.mkdir(exist_ok=True)
        subprocess.run(["7z", "x", "-y", f"-o{folder}", str(archive), "Posts.xml", "Comments.xml", "Users.xml"],
                       check=True, stdout=subprocess.DEVNULL)
        found = {}
        for file, ids in files.items():
            for _, element in ElementTree.iterparse(folder / file, events=("end",)):
                if element.tag == "row" and element.get("Id") in ids:
                    user = element.get("OwnerUserId") if file == "Posts.xml" else element.get("UserId")
                    name = element.get("OwnerDisplayName") if file == "Posts.xml" else element.get("UserDisplayName")
                    found[(file, element.get("Id"))] = {"user": user, "name": name, "date": element.get("CreationDate")[:10]}
                element.clear()
            missing = ids - {row_id for found_file, row_id in found if found_file == file}
            if missing:
                raise SystemExit(f"{site} {file} does not hold the rows {sorted(missing)[:5]}")
        users = {entry["user"] for entry in found.values() if entry["user"]}
        names = {}
        for _, element in ElementTree.iterparse(folder / "Users.xml", events=("end",)):
            if element.tag == "row" and element.get("Id") in users:
                names[element.get("Id")] = element.get("DisplayName")
            element.clear()
        base = f"https://{site}.stackexchange.com"
        for (file, row_id), entry in sorted(found.items()):
            address = f"{base}/q/{row_id}" if file == "Posts.xml" else f"{base}/posts/comments/{row_id}"
            # A post of a deleted account has no user number. The dump then holds the display name, or nothing.
            author = names.get(entry["user"]) or entry["name"] or "a deleted account"
            author = " ".join(author.split())
            profile = f"{base}/users/{entry['user']}" if entry["user"] else ""
            rows.append((f"stackexchange:{site}:{file}:{row_id}", address, author, profile, entry["date"],
                         stack_exchange_licence(entry["date"])))
        for name in ("Posts.xml", "Comments.xml", "Users.xml"):
            (folder / name).unlink()
        archive.unlink()
        print(f"{site}: {len(found)} rows", flush=True)

    if {row[0] for row in rows} != sources:
        raise SystemExit("a source of the cases has no attribution row")
    rows.sort()
    OUTPUT.write_text("source\taddress\tauthor\tauthor_profile\tdate\tlicence\n"
                      + "".join("\t".join(row) + "\n" for row in rows), encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT.relative_to(ROOT)}: {len(rows)} sources")


if __name__ == "__main__":
    main()
