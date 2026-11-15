"""Freezes the fixed request set of the speed test from the speed pass of scripts/kv-reuse.

The speed pass of docs/kv-reuse-results.md wrote 10,560 requests in order, one line each, and
one line of metadata per request. This script keeps whole documents, in their order, so the cache
reuse of a stream field sees the same sequence of requests as in the replay:

  dev cases        every 20th document of the English and symbol dev cases
  work area cases  every 16th document of the work area dev cases
  everyday         the first field of the everyday stream
  technical        the second field of the technical stream
  written          the third field of the written stream

Usage: python3 freeze_requests.py SPEED_DIR
  SPEED_DIR holds requests.tsv and requests.meta of scripts/kv-reuse/jobs/speed.sh.
Run it from the repository root. It writes Shared/model-speed-requests.tsv (the requests in the
protocol of kv_replay, which the bundle carries) and scripts/model-speed/model-speed-requests.meta.tsv
(part, document and prompt format of each request).
"""

import collections
import hashlib
import pathlib
import sys

PARTS = ("dev cases", "work area cases", "everyday", "technical", "written")


def part_of(document: str) -> str:
    if document.startswith("en-dev-") or document.startswith("ensym-dev-"):
        return "dev cases"
    if document.startswith("endom-dev-"):
        return "work area cases"
    for stream in ("everyday", "technical", "written"):
        if document.startswith(stream + "-field-"):
            return stream
    raise SystemExit(f"unknown part of document {document}")


def main() -> None:
    speed = pathlib.Path(sys.argv[1])
    requests = speed.joinpath("requests.tsv").read_text(encoding="utf-8").split("\n")
    meta = speed.joinpath("requests.meta").read_text(encoding="utf-8").split("\n")
    if requests[-1] == "":
        requests.pop()
    if meta[-1] == "":
        meta.pop()
    if len(requests) != len(meta):
        raise SystemExit(f"{len(requests)} requests and {len(meta)} metadata lines")

    # The documents of each part, in their order of the speed pass.
    documents: dict[str, list[str]] = collections.defaultdict(list)
    lines_of: dict[str, list[int]] = collections.defaultdict(list)
    for index, line in enumerate(meta):
        document, _, prompt = line.split("\t")
        part = part_of(document)
        if not lines_of[document]:
            documents[part].append(document)
        lines_of[document].append(index)

    chosen: dict[str, list[str]] = {
        "dev cases": documents["dev cases"][::20],
        "work area cases": documents["work area cases"][::16],
        "everyday": documents["everyday"][0:1],
        "technical": documents["technical"][1:2],
        "written": documents["written"][2:3],
    }
    picked = sorted(index for part in PARTS for document in chosen[part] for index in lines_of[document])
    tsv = "".join(requests[index] + "\n" for index in picked)
    rows = []
    for index in picked:
        document, position, prompt = meta[index].split("\t")
        rows.append(f"{part_of(document)}\t{document}\t{position}\t{prompt}\n")
    pathlib.Path("Shared/model-speed-requests.tsv").write_text(tsv, encoding="utf-8", newline="\n")
    pathlib.Path("scripts/model-speed/model-speed-requests.meta.tsv").write_text(
        "".join(rows), encoding="utf-8", newline="\n")
    counts = collections.Counter(row.split("\t")[0] for row in rows)
    for part in PARTS:
        print(f"{part}: {counts[part]} requests in {len(chosen[part])} documents")
    print(f"total {len(picked)} requests, sha256 {hashlib.sha256(tsv.encode('utf-8')).hexdigest()}")


if __name__ == "__main__":
    main()
