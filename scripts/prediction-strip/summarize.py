"""Writes the tables of the predicted-word measurement from the files of measure.py and
engine_order.py (scripts/prediction-strip/README.md gives the definitions).

Found share: of the words with more letters than the typed count, the share whose list holds
the right word among its first N words.
Saved key presses: a typist types letter by letter and taps the right word as soon as it is
among the first N words. A tap costs one press and gives the word and its space. The share is
1 less the presses with the strip over the presses without it (the letters and one space per
word). The strip of F is empty before the first typed letter. "F2 from 1 letter" gives F2 the
same empty strip there.
Rule: at 2 typed letters and the first 4 words, over all streams, the found share of a model
method less the found share of F, or of F2, in words of each 100.

Usage, from the repository root:
    python3 scripts/prediction-strip/summarize.py --ranks build/prediction-strip/ranks \
        --engine build/prediction-strip/engine-order.jsonl --out scripts/prediction-strip/results
"""
import argparse
import json
import statistics
from pathlib import Path

STREAMS = ("all", "technical", "written", "everyday")
METHODS = ("F", "F2", "A", "A2", "B", "B0")
MODEL_METHODS = ("A", "A2", "B", "B0")
TYPED_COUNTS = (0, 1, 2, 3)
FIRST = (3, 4, 6, 10, 20)
TAP_FIRST = (3, 6)
EXPECTED_WORDS = 26453
# The engine's list holds 20 words, so a place past it is unknown for F2.
ENGINE_WORDS = 20


def load(ranks: Path, engine: Path) -> list[dict]:
    rows: dict[tuple[str, int], dict] = {}
    for path in sorted(ranks.glob("shard-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            key = (row["id"], row["word"])
            if key in rows:
                raise SystemExit(f"{key} is in the files twice")
            rows[key] = row
    for line in engine.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        key = (row["id"], row["word"])
        if key not in rows:
            raise SystemExit(f"{key} is in {engine} and not in {ranks}")
        if len(row["places"]) != len(rows[key]["target"]):
            raise SystemExit(f"{key}: the two files count other typed letters")
        rows[key]["places"]["F2"] = row["places"]
    result = list(rows.values())
    if len(result) != EXPECTED_WORDS or any("F2" not in row["places"] for row in result):
        raise SystemExit(f"the files hold {len(result)} words, and the dev stream has {EXPECTED_WORDS}")
    return result


def found(row: dict, method: str, typed: int, first: int) -> bool:
    place = row["places"][method][typed]
    return place is not None and place < first


def presses(row: dict, method: str, first: int, from_typed: int) -> int:
    """Key presses for the word and its space, with a tap as soon as the list shows the word."""
    length = len(row["target"])
    for typed in range(from_typed, length):
        if found(row, method, typed, first):
            return typed + 1
    return length + 1


def summarize(rows: list[dict]) -> dict:
    shares: dict = {}
    saved: dict = {}
    for stream in STREAMS:
        part = [row for row in rows if stream == "all" or row["stream"] == stream]
        shares[stream] = {"words": len(part), "known_words": sum(row["known"] for row in part), "typed": {}}
        for typed in TYPED_COUNTS:
            counted = [row for row in part if len(row["target"]) > typed]
            shares[stream]["typed"][typed] = {
                "words": len(counted),
                "found": {method: {first: sum(found(row, method, typed, first) for row in counted) / len(counted)
                                   for first in FIRST} for method in METHODS}}
        without = sum(len(row["target"]) + 1 for row in part)
        saved[stream] = {"presses_without_the_strip": without, "saved": {}}
        for name, method, from_typed in [("F", "F", 1), ("F2", "F2", 0), ("F2 from 1 letter", "F2", 1),
                                         *[(method, method, 0) for method in MODEL_METHODS]]:
            saved[stream]["saved"][name] = {
                first: 1 - sum(presses(row, method, first, from_typed) for row in part) / without for first in TAP_FIRST}
    at_rule = shares["all"]["typed"][2]["found"]
    rule = {method: {"against F": round(100 * (at_rule[method][4] - at_rule["F"][4]), 2),
                     "against F2": round(100 * (at_rule[method][4] - at_rule["F2"][4]), 2)} for method in MODEL_METHODS}
    # The first word of a sentence opens the field, so the model reads only its start token there.
    by_place = {}
    for name, keep in [("first word of the field", lambda row: row["word"] == 0), ("later words", lambda row: row["word"] > 0)]:
        counted = [row for row in rows if keep(row) and len(row["target"]) > 2]
        by_place[name] = {"words": len(counted), "found": {
            method: sum(found(row, method, 2, 4) for row in counted) / len(counted) for method in METHODS}}
    return {"found_share": shares, "saved_key_presses": saved, "rule": rule, "typed_2_first_4_by_place": by_place}


def percent(value: float) -> str:
    return f"{100 * value:.1f}"


def markdown(summary: dict, timing: dict) -> str:
    lines = ["# Predicted words on the dev stream: result tables", "",
             "`scripts/prediction-strip/summarize.py` writes this file. `README.md` in the folder above gives the definitions.", ""]
    for stream in STREAMS:
        entry = summary["found_share"][stream]
        lines += [f"## Found share, stream {stream}", "",
                  f"Table: share in percent of the words whose list holds the right word among its first N words. "
                  f"The stream holds {entry['words']} words, and the candidates hold {entry['known_words']} of them.", "",
                  "| Typed letters | Words | Method | " + " | ".join(f"first {first}" for first in FIRST) + " |",
                  "| --- | --- | --- | " + " | ".join("---" for _ in FIRST) + " |"]
        for typed in TYPED_COUNTS:
            cell = entry["typed"][typed]
            for method in METHODS:
                lines.append(f"| {typed} | {cell['words']} | {method} | "
                             + " | ".join(percent(cell["found"][method][first]) for first in FIRST) + " |")
        lines.append("")
    lines += ["## Saved key presses", "",
              "Table: share in percent of the key presses that the taps save, per stream, for a strip of 3 and of 6 words.", "",
              "| Method | " + " | ".join(f"{stream}, first {first}" for stream in STREAMS for first in TAP_FIRST) + " |",
              "| --- | " + " | ".join("---" for _ in STREAMS for _ in TAP_FIRST) + " |"]
    for name in summary["saved_key_presses"]["all"]["saved"]:
        lines.append(f"| {name} | " + " | ".join(
            percent(summary["saved_key_presses"][stream]["saved"][name][first]) for stream in STREAMS for first in TAP_FIRST) + " |")
    lines += ["", "## Rule of the plan", "",
              "Table: found share of the method less the found share of F and of F2, at 2 typed letters and the first 4 words, "
              "over all streams, in words of each 100.", "",
              "| Method | against F | against F2 |", "| --- | --- | --- |"]
    for method, values in summary["rule"].items():
        lines.append(f"| {method} | {values['against F']:+.2f} | {values['against F2']:+.2f} |")
    lines += ["", "## First word of the field and later words", "",
              "Table: found share in percent at 2 typed letters and the first 4 words. The first word of a sentence opens "
              "the field, and the model then reads only its start token.", "",
              "| Words | Count | " + " | ".join(METHODS) + " |", "| --- | --- | " + " | ".join("---" for _ in METHODS) + " |"]
    for name, entry in summary["typed_2_first_4_by_place"].items():
        lines.append(f"| {name} | {entry['words']} | " + " | ".join(percent(entry["found"][method]) for method in METHODS) + " |")
    lines += ["", "## Time of the model on the PC", "",
              f"One read of the text before a word took {timing['next_ms_median']:.1f} ms (median of {timing['next_requests']} "
              f"reads, {timing['threads']} threads, {timing['processes']} scorer processes at the same time). The request of "
              f"method B took {timing['exact_ms_median']:.1f} ms more (median).", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ranks", required=True, type=Path)
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    rows = load(args.ranks, args.engine)
    summary = summarize(rows)
    timings = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(args.ranks.glob("shard-*.timing.json"))]
    timing = {"processes": len(timings), "threads": timings[0]["threads"],
              "next_requests": sum(t["next_requests"] for t in timings),
              "next_ms_median": statistics.median(t["next_ms_median"] for t in timings),
              "exact_ms_median": statistics.median(t["exact_ms_median"] for t in timings)}
    bars = sorted(row["bar"] for row in rows)
    summary["timing"] = timing
    summary["bar_token_log_probability_median"] = bars[len(bars) // 2]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "dev.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8", newline="\n")
    (args.out / "dev.md").write_text(markdown(summary, timing), encoding="utf-8", newline="\n")
    print(markdown(summary, timing))


if __name__ == "__main__":
    main()
