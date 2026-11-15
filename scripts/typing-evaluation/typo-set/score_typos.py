"""Scores outputs on the typo set, per category, per group and per stratum.

A case is right when the output equals `intended`: for English after the normalization of
scripts/typing-evaluation/score.py (letter case and a curly apostrophe), for Pinyin exactly.
For English the script also counts the cases whose output differs from `typed`, so a keep case
that the keyboard changed shows as a change. A Pinyin slip case with a `twin` also counts
among the cases whose clean twin is right.

Strata: the layout of the slip, whether the case types more words after the slip word
(`follow`), the drift direction, the pair of an apostrophe case, whether a word one slip from
the typed word is at least as common as the intended word (`rival`), whether the keyboard reads
a drifted word with a digit or symbol key (`keyboard_reads_word`), whether the typed letters of
a Pinyin slip parse as standard syllables (`typed_parses_exactly`), and whether the
longest-first cut of a clean Pinyin clause gives other syllables (`longest_first_cut_differs`).

Usage:
    python3 scripts/typing-evaluation/typo-set/score_typos.py --task english --cases FILE [FILE ...] \
        --predictions FILE --name NAME --json OUT.json [--markdown OUT.md]
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from score import edit_distance, normalize  # noqa: E402

STRATA = ("layout", "follow", "direction", "pair", "rival", "keyboard_reads_word", "typed_parses_exactly",
          "longest_first_cut_differs")
# Strata that every case of a file has, present or not: the field's presence is the value.
PRESENCE_STRATA = {"rival"}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def score(task: str, cases: list[dict], outputs: dict[str, str]) -> dict:
    missing = [case["id"] for case in cases if case["id"] not in outputs]
    if missing:
        raise SystemExit(f"{len(missing)} cases have no output, as {missing[:3]}")
    rows = {}
    for case in cases:
        output = outputs[case["id"]]
        right = normalize(task, output) == normalize(task, case["intended"])
        changed = normalize(task, output) != normalize(task, case["typed"])
        row = {"case": case, "right": right, "changed": changed if task == "english" else None}
        if task == "pinyin":
            row["characters"] = max(0.0, 1 - edit_distance(output.strip(), case["intended"]) / len(case["intended"]))
        rows[case["id"]] = row
    for row in rows.values():
        twin = row["case"].get("twin")
        row["twin_right"] = rows[twin]["right"] if twin is not None else None

    def tally(members: list[dict]) -> dict:
        entry = {"cases": len(members), "right": sum(r["right"] for r in members)}
        if task == "english":
            entry["changed"] = sum(r["changed"] for r in members)
        if task == "pinyin" and members:
            entry["character_accuracy"] = round(sum(r["characters"] for r in members) / len(members), 4)
        paired = [r for r in members if r["twin_right"] is not None]
        if paired:
            able = [r for r in paired if r["twin_right"]]
            entry["twin_right_cases"] = len(able)
            entry["right_when_twin_right"] = sum(r["right"] for r in able)
        return entry

    by = {"category": {}, "group": {}}
    for row in rows.values():
        by["category"].setdefault(row["case"]["category"], []).append(row)
        by["group"].setdefault(row["case"]["group"], []).append(row)
    summary = {"cases": len(rows), "right": sum(r["right"] for r in rows.values()),
               "categories": {k: tally(v) for k, v in by["category"].items()},
               "groups": {k: tally(v) for k, v in sorted(by["group"].items())}, "strata": {}}
    for field in STRATA:
        values: dict[str, list] = {}
        for row in rows.values():
            if field in PRESENCE_STRATA:
                if row["case"]["expected"] != "correct" or not any(field in r["case"] for r in rows.values()):
                    continue
                value = "a rival word" if field in row["case"] else "no rival word"
            elif field in row["case"]:
                value = row["case"][field]
                if field == "follow":
                    value = "next words typed" if value else "slip word alone"
            else:
                continue
            values.setdefault(str(value), []).append(row)
        if values:
            summary["strata"][field] = {k: tally(v) for k, v in sorted(values.items())}
    return summary


def markdown(name: str, summary: dict) -> str:
    def line(label: str, entry: dict) -> str:
        cells = [label, f"{entry['right']}/{entry['cases']}"]
        if "changed" in entry:
            cells.append(f"{entry['changed']}")
        if "character_accuracy" in entry:
            cells.append(f"{entry['character_accuracy']:.3f}")
        if "twin_right_cases" in entry:
            cells.append(f"{entry['right_when_twin_right']}/{entry['twin_right_cases']}")
        return "| " + " | ".join(cells) + " |"

    pinyin = any("character_accuracy" in e for e in summary["categories"].values())
    if pinyin:
        header = "| Count | Right | Character accuracy | Right when the twin is right |"
        rule = "| --- | --- | --- | --- |"
    else:
        header = "| Count | Right | Output differs from typed |"
        rule = "| --- | --- | --- |"
    lines = [f"### {name}: {summary['right']} of {summary['cases']} cases right", "", header, rule]
    lines += [line(f"group {k}", v) for k, v in summary["groups"].items()]
    lines += [line(k, v) for k, v in summary["categories"].items()]
    for field, values in summary["strata"].items():
        lines += [line(f"{field}: {k}", v) for k, v in values.items()]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=["english", "pinyin"], required=True)
    parser.add_argument("--cases", type=Path, nargs="+", required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    arguments = parser.parse_args()
    cases = [case for path in arguments.cases for case in read_jsonl(path)]
    outputs = {}
    for row in read_jsonl(arguments.predictions):
        if row["id"] in outputs:
            raise SystemExit(f"{row['id']} has two outputs")
        outputs[row["id"]] = row["output"]
    extra = set(outputs) - {case["id"] for case in cases}
    if extra:
        raise SystemExit(f"{len(extra)} outputs belong to no case, as {sorted(extra)[:3]}")
    summary = score(arguments.task, cases, outputs)
    summary.update({"name": arguments.name, "cases_files": [p.name for p in arguments.cases]})
    arguments.json.parent.mkdir(parents=True, exist_ok=True)
    arguments.json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    text = markdown(arguments.name, summary)
    if arguments.markdown:
        arguments.markdown.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
