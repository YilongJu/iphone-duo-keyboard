"""Writes the attribution of every source document of the domain training and stopping cases:
scripts/lm-domain/reports/domain-train-ATTRIBUTION.tsv.

The cases name each source document in the field `source`. This script reads only that field and
adds what a licence asks for, as scripts/domain-pack/attribute_cases.py does for the test cases:
- arXiv: the address of the abstract. arXiv metadata, the abstract included, is CC0 1.0.
- Stack Exchange: the address of the post or comment, the author's display name and profile, the
  date, and the licence version of that date. The script reads Posts.xml, Comments.xml and
  Users.xml of the data dump that collect_corpus.py reads.
- GitHub: the address of the file at the commit that collect_train_sentences.py read, and the
  licence that GitHub reported for the repository at that time (licences.json of that script).

Usage, on Linux with 7z installed, from the repository root:
    python3 scripts/lm-domain/attribute_training.py --cases build/lm-domain/data/domain \
        --licences build/lm-domain/corpus/licences.json --work build/lm-domain/attribution
"""
import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "domain-pack"))
from attribute_cases import stack_exchange_licence  # noqa: E402
from collect_corpus import fetch  # noqa: E402

OUTPUT = ROOT / "scripts" / "lm-domain" / "reports" / "domain-train-ATTRIBUTION.tsv"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--licences", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    arguments = parser.parse_args()
    arguments.work.mkdir(parents=True, exist_ok=True)
    settings = json.loads((ROOT / "scripts" / "domain-pack" / "sources.json").read_text(encoding="utf-8"))
    recorded = json.loads(arguments.licences.read_text(encoding="utf-8"))["licences"]["repositories"]

    sources: dict[str, int] = {}
    for split in ("train", "stop"):
        for line in (arguments.cases / f"cases.{split}.jsonl").read_text(encoding="utf-8").splitlines():
            source = json.loads(line)["source"]
            sources[source] = sources.get(source, 0) + 1

    rows = []
    wanted: dict[str, dict[str, set[str]]] = {}
    for source in sorted(sources):
        kind = source.split(":", 1)[0]
        if kind == "arxiv":
            rows.append((source, f"https://arxiv.org/abs/{source.split(':')[2]}", "", "", "", "CC0 1.0 (arXiv metadata)"))
        elif kind == "github":
            _, repository, path = source.split(":", 2)
            entry = recorded[repository]
            rows.append((source, f"https://github.com/{repository}/blob/{entry['commit']}/{path}", "", "", "", entry["licence"]))
        elif kind == "stackexchange":
            _, site, file, row_id = source.split(":")
            wanted.setdefault(site, {}).setdefault(file, set()).add(row_id)
        else:
            raise SystemExit(f"a case names a source of an unknown kind: {source}")

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
            author = " ".join((names.get(entry["user"]) or entry["name"] or "a deleted account").split())
            profile = f"{base}/users/{entry['user']}" if entry["user"] else ""
            rows.append((f"stackexchange:{site}:{file}:{row_id}", address, author, profile, entry["date"],
                         stack_exchange_licence(entry["date"])))
        for name in ("Posts.xml", "Comments.xml", "Users.xml"):
            (folder / name).unlink()
        archive.unlink()
        print(f"{site}: {len(found)} rows", flush=True)

    if {row[0] for row in rows} != set(sources):
        raise SystemExit("a source of the cases has no attribution row")
    rows.sort()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("source\taddress\tauthor\tauthor_profile\tdate\tlicence\tcases\n"
                      + "".join("\t".join(row) + f"\t{sources[row[0]]}\n" for row in rows), encoding="utf-8", newline="\n")
    licences: dict[str, int] = {}
    for row in rows:
        licences[row[5]] = licences.get(row[5], 0) + 1
    print(f"wrote {OUTPUT.relative_to(ROOT)}: {len(rows)} source documents, by licence {json.dumps(licences)}")


if __name__ == "__main__":
    main()
