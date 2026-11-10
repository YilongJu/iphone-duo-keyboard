"""Prints checks on the librime outputs in build/typing-evaluation/, after run_librime.py.

Usage, from the repository root:
    python3 scripts/typing-evaluation/engines/librime/summarize_runs.py --halves dev test

The script prints three things for each engine name and half:
1. The reason the adapter stopped, as counts, and the count of outputs that hold letters a to z.
2. The count of cases where a patched engine and the default engine of one schema differ, per
   category, with the count of cases that changed from wrong to right and from right to wrong.
3. An error when librime committed a case, because a commit feeds the user dictionary of librime.
4. An error when the reverse order of the cases changed an output, because one case then changes
   a later case.
"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CASES = ROOT / "scripts" / "typing-evaluation" / "cases"
OUTPUT = ROOT / "build" / "typing-evaluation"
PAIRS = [("rime-default", "rime-correction"), ("rime-default", "rime-fuzzy"),
         ("rime-pinyin-simp-default", "rime-pinyin-simp-correction")]


def read_details(engine: str, half: str) -> dict[str, dict]:
    lines = (OUTPUT / engine / f"pinyin.{half}.details.tsv").read_text(encoding="utf-8").removesuffix("\n").split("\n")
    columns = lines[0].split("\t")
    return {row["id"]: row for row in (dict(zip(columns, line.split("\t"))) for line in lines[1:])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--halves", nargs="+", choices=["dev", "test"], required=True)
    arguments = parser.parse_args()

    engines = sorted(path.parent.name for path in OUTPUT.glob("*/run-info.json"))
    if not engines:
        raise SystemExit(f"{OUTPUT} does not hold a run-info.json file")
    committed = 0
    changed_by_order = 0
    for engine in engines:
        info = json.loads((OUTPUT / engine / "run-info.json").read_text(encoding="utf-8"))
        print(f"{engine}: librime {info['librime_version']}, schema {info['schema']}, "
              f"custom files {sorted(info['custom_files'])}, "
              f"files built in the user folder {info['files_built_in_user_folder']}")
        for half in arguments.halves:
            rows = read_details(engine, half)
            with_letters = sum(bool(re.search("[a-z]", row["output"])) for row in rows.values())
            entry = info["halves"][half]
            committed += entry["stops"].get("committed", 0)
            changed_by_order += entry["outputs_changed_by_reverse_order"]
            print(f"  pinyin.{half}: {entry['cases']} cases in {entry['seconds']} s, stops {entry['stops']}, "
                  f"cases with a space press {entry['cases_with_a_selection']}, outputs that hold letters {with_letters}, "
                  f"outputs changed by the reverse order {entry['outputs_changed_by_reverse_order']}")

    for default, patched in PAIRS:
        if default not in engines or patched not in engines:
            continue
        for half in arguments.halves:
            cases = [json.loads(line) for line in (CASES / f"pinyin.{half}.jsonl").read_text(encoding="utf-8").splitlines() if line]
            before, after = read_details(default, half), read_details(patched, half)
            print(f"{patched} against {default} on pinyin.{half}: category, cases, outputs that differ, "
                  f"wrong to right, right to wrong")
            totals: dict[str, list[int]] = {}
            for case in cases:
                first, second = before[case["id"]]["output"], after[case["id"]]["output"]
                counts = totals.setdefault(case["category"], [0, 0, 0, 0])
                counts[0] += 1
                counts[1] += first != second
                counts[2] += first != case["intended"] and second == case["intended"]
                counts[3] += first == case["intended"] and second != case["intended"]
            for category, counts in totals.items():
                print(f"  {category:24s} {counts[0]:5d} {counts[1]:5d} {counts[2]:5d} {counts[3]:5d}")
            print(f"  {'ALL':24s} " + " ".join(f"{sum(counts[i] for counts in totals.values()):5d}" for i in range(4)))

    if committed:
        raise SystemExit(f"librime committed {committed} cases, so its user dictionary changed during the run")
    if changed_by_order:
        raise SystemExit(f"the reverse order of the cases changed {changed_by_order} outputs, so one case changes a later case")
    print("librime did not commit a case, and the reverse order of the cases did not change an output.")


if __name__ == "__main__":
    main()
