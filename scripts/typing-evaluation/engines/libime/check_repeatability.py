"""Counts the outputs that differ between two adapter processes that get the same cases.

Usage, from the repository root, after building libime_adapter:
    python3 scripts/typing-evaluation/engines/libime/check_repeatability.py \
        --adapter build/libime-source/adapter/libime_adapter --dict SC_DICT --lm LANGUAGE_MODEL \
        --mode none --mode fcitx5-mobile --half dev --jobs 4

For each adapter mode the script starts two processes with the normal, random address layout and two
processes with the fixed address layout of "setarch -R". It prints the number of cases where the
two processes of a pair give a different output, and the number of cases where the two address
layouts give a different output. The script does not write a score file.
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from run_libime import load_cases, run_adapter


def differing(first: dict[str, str], second: dict[str, str]) -> list[str]:
    return [case_id for case_id in first if first[case_id] != second[case_id]]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--dict", type=Path, required=True, dest="dictionary")
    parser.add_argument("--lm", type=Path, required=True, dest="language_model")
    parser.add_argument("--mode", action="append", required=True, help="adapter mode, may repeat")
    parser.add_argument("--half", choices=["dev"], required=True, help="the dev half only")
    parser.add_argument("--jobs", type=int, required=True)
    parser.add_argument("--json", type=Path, help="write the counts to this file")
    arguments = parser.parse_args()

    cases = load_cases(arguments.half)
    intended = {case["id"]: case["intended"] for case in cases}
    jobs = [(mode, layout, copy) for mode in arguments.mode for layout in ("random", "fixed") for copy in (1, 2)]
    with ThreadPoolExecutor(max_workers=arguments.jobs) as pool:
        futures = {
            job: pool.submit(run_adapter, arguments.adapter, arguments.dictionary, arguments.language_model, job[0], cases,
                             job[1], f"mode {job[0]}, address layout {job[1]}, process {job[2]}")
            for job in jobs}
        outputs = {job: future.result()[0] for job, future in futures.items()}

    report = []
    for mode in arguments.mode:
        entry = {"mode": mode, "half": arguments.half, "cases": len(cases)}
        for layout in ("random", "fixed"):
            first, second = outputs[(mode, layout, 1)], outputs[(mode, layout, 2)]
            changed = differing(first, second)
            right = [sum(result[case_id] == intended[case_id] for case_id in intended) for result in (first, second)]
            entry[f"{layout}_layout_outputs_that_differ_between_two_processes"] = len(changed)
            entry[f"{layout}_layout_exact_matches_of_the_two_processes"] = right
            print(f"mode {mode}, address layout {layout}: {len(changed)} of {len(cases)} outputs differ between two processes; "
                  f"exact matches {right[0]} and {right[1]}")
        across = differing(outputs[(mode, "random", 1)], outputs[(mode, "fixed", 1)])
        entry["outputs_that_differ_between_the_two_layouts"] = len(across)
        print(f"mode {mode}: {len(across)} of {len(cases)} outputs differ between the random layout and the fixed layout")
        report.append(entry)
    if arguments.json:
        arguments.json.parent.mkdir(parents=True, exist_ok=True)
        arguments.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
