"""Runs the sunpinyin engine over the Pinyin test cases and writes one output per case.

Usage, from the repository root, after building sunpinyin_cli.cpp:
    python3 scripts/typing-evaluation/engines/sunpinyin/run_sunpinyin.py --cli build/engines/sunpinyin/sunpinyin_cli --half dev
    python3 scripts/typing-evaluation/engines/sunpinyin/run_sunpinyin.py --cli build/engines/sunpinyin/sunpinyin_cli --probes

For each engine name the script writes, under build/typing-evaluation/NAME/:
    pinyin.HALF.jsonl          the case id and the engine's output, the file score.py reads
    pinyin.HALF.details.jsonl  the typed letters, the engine's split of them, and how the output was read
    pinyin.HALF.run.json       counts for the run and every case where the engine program stopped

The script does not score. Run scripts/typing-evaluation/score.py on the first file.

A case where the engine program stops (a crash, a wrong exit code or a time limit) does not get
an output line, so score.py counts the case as wrong and reports it as missing. The script starts the
program again for the cases after it.
"""
import argparse
import json
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CASES = ROOT / "scripts" / "typing-evaluation" / "cases"
OUTPUT = ROOT / "build" / "typing-evaluation"

# Engine name in the evaluation, and the mode argument of sunpinyin_cli.
MODES = {
    "sunpinyin-default": "default",
    "sunpinyin-correction": "correction",
    "sunpinyin-fuzzy": "fuzzy",
    "sunpinyin-ibus-defaults": "ibus",
}

# Exit codes of sunpinyin_cli that mean the set-up is wrong. A case cannot run after one of them.
SETUP_EXIT_CODES = {2: "wrong arguments", 3: "the engine did not create a session", 4: "a malformed input line"}

# Strings that show the output of each mode. The strings do not come from the test cases.
PROBES = [
    ("clean", "nihao"),
    ("clean", "zhongguoren"),
    ("clean", "womenmingtianqubeijing"),
    ("pair gn to ng", "dagn"),
    ("pair gn to ng", "zhognguo"),
    ("pair uen to un", "shuen"),
    ("pair img to ing", "dimg"),
    ("pair iou to iu", "jiou"),
    ("pair uei to ui", "guei"),
    ("neighbor key in place of a letter", "nihso"),
    ("letter left out", "niha"),
    ("letter typed twice", "nihaoo"),
    ("extra neighbor key", "nihjao"),
    ("two letters swapped", "nihoa"),
    ("sound pair n and l", "lixihuan"),
    ("sound pair z and zh", "zongguoren"),
    ("sound pair l and r, r typed for l", "raoshi"),
    ("sound pair l and r, l typed for r", "liben"),
    ("sound pair eng and ong", "dengxi"),
    ("syllable outside the dictionary", "yiden"),
]


def run_engine(cli: Path, mode: str, items: list[tuple[str, str]], seconds: int) -> tuple[dict[str, dict], list[dict]]:
    """Types every item into the engine. Returns the outputs by id, and the items where the program stopped."""
    results: dict[str, dict] = {}
    stops: list[dict] = []
    start = 0
    while start < len(items):
        batch = items[start:]
        payload = "".join(f"{identifier}\t{typed}\n" for identifier, typed in batch).encode("ascii")
        # A new, empty user data folder for each start: the engine begins without a history.
        with tempfile.TemporaryDirectory(prefix="sunpinyin-user-") as user_data:
            try:
                completed = subprocess.run([str(cli), mode, user_data], input=payload, capture_output=True, timeout=seconds)
                stdout, stderr, reason = completed.stdout, completed.stderr, f"exit code {completed.returncode}"
                code = completed.returncode
            except subprocess.TimeoutExpired as expired:
                stdout, stderr, reason = expired.stdout or b"", expired.stderr or b"", f"no exit after {seconds} seconds"
                code = None
        error_text = stderr.decode("utf-8", errors="replace").strip()
        if code in SETUP_EXIT_CODES:
            raise RuntimeError(f"sunpinyin_cli {mode}: {SETUP_EXIT_CODES[code]} ({reason}): {error_text}")

        # The program writes one whole line per case. A last piece without a line end is not a result.
        lines = stdout.split(b"\n")[:-1]
        if len(lines) > len(batch):
            raise RuntimeError(f"sunpinyin_cli {mode} wrote {len(lines)} lines for {len(batch)} cases")
        for position, raw in enumerate(lines):
            fields = raw.decode("utf-8").split("\t")
            if len(fields) != 4 or fields[0] != batch[position][0]:
                raise RuntimeError(f"sunpinyin_cli {mode}: unexpected output line {raw!r} for case {batch[position][0]}")
            results[fields[0]] = {"read_as": fields[1], "output": fields[2], "segments": fields[3]}

        if len(lines) == len(batch):
            if code != 0:
                stops.append({"id": None, "typed": None, "reason": f"{reason} after the last case", "stderr": error_text[-2000:]})
            break
        identifier, typed = batch[len(lines)]
        stops.append({"id": identifier, "typed": typed, "reason": reason, "stderr": error_text[-2000:]})
        print(f"  the engine program stopped at {identifier} ({typed}): {reason}: {error_text[-300:]}", flush=True)
        if len(stops) > max(20, len(items) // 10):
            raise RuntimeError(f"sunpinyin_cli {mode} stopped at {len(stops)} cases, the latest with {reason}: {error_text[-2000:]}")
        start += len(lines) + 1
    return results, stops


def check_clean_input(cli: Path, mode: str) -> None:
    """Stops the run when the engine does not turn nihao into the two characters of 'hello'."""
    results, stops = run_engine(cli, mode, [("sanity-nihao", "nihao")], seconds=60)
    output = results.get("sanity-nihao", {}).get("output")
    if stops or output != "你好":
        raise RuntimeError(f"sunpinyin_cli {mode} gave {output!r} for nihao, expected '你好'. Stops: {stops}")


def run_probes(cli: Path, names: list[str]) -> None:
    items = [(f"probe-{index:02d}", typed) for index, (_, typed) in enumerate(PROBES)]
    for name in names:
        results, stops = run_engine(cli, MODES[name], items, seconds=120)
        rows = ["slip\ttyped\tengine split\toutput\tread as"]
        for (identifier, typed), (slip, _) in zip(items, PROBES):
            result = results.get(identifier)
            rows.append("\t".join([slip, typed, result["segments"], result["output"], result["read_as"]] if result
                                  else [slip, typed, "", "", "the engine program stopped"]))
        folder = OUTPUT / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "probes.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")
        print(f"{name} on the probe strings")
        for row in rows:
            print("  " + row.replace("\t", " | "))
        for stop in stops:
            print(f"  STOP {stop}")


def run_half(cli: Path, name: str, half: str, show_misses: int, seconds: int) -> None:
    cases = [json.loads(line) for line in (CASES / f"pinyin.{half}.jsonl").read_text(encoding="utf-8").splitlines() if line]
    began = time.monotonic()
    results, stops = run_engine(cli, MODES[name], [(case["id"], case["typed"]) for case in cases], seconds)
    elapsed = time.monotonic() - began

    folder = OUTPUT / name
    folder.mkdir(parents=True, exist_ok=True)
    answered = [case for case in cases if case["id"] in results]
    (folder / f"pinyin.{half}.jsonl").write_text(
        "".join(json.dumps({"id": case["id"], "output": results[case["id"]]["output"]}, ensure_ascii=False) + "\n" for case in answered),
        encoding="utf-8", newline="\n")
    (folder / f"pinyin.{half}.details.jsonl").write_text(
        "".join(json.dumps({"id": case["id"], "typed": case["typed"], **results[case["id"]]}, ensure_ascii=False) + "\n" for case in answered),
        encoding="utf-8", newline="\n")
    run = {
        "engine": name,
        "mode": MODES[name],
        "half": half,
        "cases": len(cases),
        "outputs": len(answered),
        "first_candidate_was_the_whole_sentence": sum(results[case["id"]]["read_as"] == "sentence" for case in answered),
        "first_word_candidates_taken_in_turn": sum(results[case["id"]]["read_as"] == "words" for case in answered),
        "outputs_with_a_letter_a_to_z": sum(any("a" <= character <= "z" for character in results[case["id"]]["output"]) for case in answered),
        "cases_where_the_engine_program_stopped": stops,
        "seconds": round(elapsed, 1),
    }
    (folder / f"pinyin.{half}.run.json").write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"{name} on pinyin.{half}: {run['outputs']} outputs for {run['cases']} cases in {run['seconds']} seconds, "
          f"{run['first_candidate_was_the_whole_sentence']} read as a whole sentence, "
          f"{run['first_word_candidates_taken_in_turn']} read as word candidates in turn, "
          f"{run['outputs_with_a_letter_a_to_z']} outputs with a letter a to z, {len(stops)} stops", flush=True)

    if show_misses:
        shown: dict[str, int] = {}
        for case in cases:
            result = results.get(case["id"])
            output = result["output"] if result else None
            if output != case["intended"] and shown.get(case["category"], 0) < show_misses:
                shown[case["category"]] = shown.get(case["category"], 0) + 1
                split = result["segments"] if result else ""
                print(f"    MISS {case['category']}: {case['typed']!r} split {split!r} -> {output!r}, wanted {case['intended']!r}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", type=Path, required=True, help="the program built from sunpinyin_cli.cpp")
    parser.add_argument("--half", choices=["dev", "test"])
    parser.add_argument("--probes", action="store_true", help="print each mode's output for a few fixed strings")
    parser.add_argument("--engine", action="append", choices=sorted(MODES), help="engine names to run, all of them when left out")
    parser.add_argument("--show-misses", type=int, default=0, help="print this many wrong cases per category, dev half only")
    parser.add_argument("--seconds", type=int, default=600, help="time limit for one start of the engine program")
    arguments = parser.parse_args()
    if arguments.probes == bool(arguments.half):
        parser.error("give either --half or --probes")
    if arguments.show_misses and arguments.half != "dev":
        parser.error("--show-misses reads the intended text, so it runs on the dev half only")

    names = arguments.engine or list(MODES)
    for name in names:
        check_clean_input(arguments.cli, MODES[name])
    if arguments.probes:
        run_probes(arguments.cli, names)
    else:
        for name in names:
            run_half(arguments.cli, name, arguments.half, arguments.show_misses, arguments.seconds)


if __name__ == "__main__":
    main()
