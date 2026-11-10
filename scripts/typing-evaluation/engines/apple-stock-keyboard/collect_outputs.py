"""Merges the parts that the workflow jobs wrote into one output folder per engine name.

Usage, from the repository root:
    python3 scripts/typing-evaluation/engines/apple-stock-keyboard/collect_outputs.py \
        --parts build/typing-evaluation-parts --out build/typing-evaluation

Each simulator of a workflow job writes one part folder with a `part.json` file. The script
reads every part folder under `--parts`, at any depth.

A part of kind `keyboard` holds the cases one job typed on the stock keyboard:
`sample.jsonl` (every sampled case of the engine name and half), `cases.jsonl` (the share of this
job), `attempts.jsonl` (what the UI test read from the text view, one line per attempt) and the
run logs, accessibility trees and screenshots. The script writes, for each engine name, task and half:
    TASK.HALF.cases.jsonl    the sampled cases, the file to score against
    TASK.HALF.jsonl          one object per typed case with the case `id` and the `output`
    TASK.HALF.detail.jsonl   the counted attempt, the output and the checks for each typed case
    TASK.HALF.checks.json    the counts of the checks and the measured key interval
    diagnostics/PART/        the logs, trees and screenshots of each part

A part of kind `outputs` holds finished files under `outputs/ENGINE/`, and the script copies them.

Counted attempt of a case: the UI test types a case once. It types a case again only when the
attempt ended with an error or the last space did not arrive. The last complete attempt counts.
A case without a complete attempt counts with its last attempt that read the text view.
Control part: a part whose `part.json` holds `"control": true` was typed with every correction
of the text view off. The script counts the cases whose text view holds exactly the context, the
typed characters and the last space. That count checks that every key tap arrived.
Field text of a case: the text view after the last space tap. Marked text does not count for
English, because the English keyboard marks an inline prediction that the person has not accepted.
Output of an English case: the field text after the first N words, where N is the number of
words in the context.
Output of a Pinyin case: the field text without spaces at the ends.

The host app stamps each change of the text with its time. The script reports the time between
two key arrivals while a case is typed, which is the key interval the keyboard saw.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from score import normalize  # noqa: E402

# The host app wraps marked text in these two brackets in each entry of the text history.
OPEN, CLOSE = "⟦", "⟧"
# Two growths of the typed text closer than this come from one tap, as in the host app.
SAME_TAP_MS = 20
# A case keeps its rhythm when each key gap stays under this many key intervals, as in the UI test.
RHYTHM_LIMIT = 1.5


def read_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_lines(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8", newline="\n")


def letters(text: str) -> str:
    return "".join(character for character in text.lower() if "a" <= character <= "z")


def without_marked(entry: str) -> str:
    """The text of a history entry without its marked text."""
    if OPEN not in entry:
        return entry
    return entry[: entry.index(OPEN)] + entry[entry.index(CLOSE) + 1:]


def key_gaps(task: str, attempt: dict) -> list[int]:
    """Milliseconds between two key arrivals while the case was typed.

    A key arrival is a moment the typed text grew: for English the text without the marked text,
    and for Pinyin the letters of the text. A change of an inline prediction alone does not
    count. The first entry of the history is the loaded case, so the time before the first key
    is left out."""
    arrivals: list[int] = []
    length = None
    for entry, time in zip(attempt["history"], attempt["history_ms"]):
        new_length = len(without_marked(entry) if task == "english" else letters(entry))
        if length is not None and new_length > length and (not arrivals or time - arrivals[-1] >= SAME_TAP_MS):
            arrivals.append(time)
        length = new_length
    return [later - earlier for earlier, later in zip(arrivals, arrivals[1:])]


def english_fields(case: dict, attempt: dict) -> dict:
    context_words = case["context"].split()
    words = attempt["after_committed"].split()
    prefix = case["context"] + " " if case["context"] else ""
    tokens = case["typed"].split(" ")
    states = [without_marked(entry).lower().replace("’", "'") for entry in attempt["history"]]
    return {
        "output": " ".join(words[len(context_words):]),
        # False when the keyboard changed a word of the context while the person typed.
        "context_kept": [normalize("english", word) for word in words[: len(context_words)]] == context_words,
        # True when the field once held the context and the first typed token, letter for letter,
        # and once ended with the last typed token. False means that a key tap did not arrive.
        "letters_arrived": prefix + tokens[0] in states and any(state.endswith(tokens[-1]) for state in states),
    }


def pinyin_fields(case: dict, attempt: dict) -> dict:
    return {
        "output": attempt["after"].strip(),
        # True when the marked text once held every typed letter.
        "letters_arrived": any(OPEN in entry and letters(entry) == case["typed"] for entry in attempt["history"]),
    }


def counted_attempt(attempts: list[dict]) -> dict | None:
    """The last complete attempt, or the last attempt that read the text view."""
    read = [attempt for attempt in attempts if "after" in attempt]
    complete = [attempt for attempt in read if attempt["complete"]]
    if complete:
        return complete[-1]
    return read[-1] if read else None


def percentile(values: list[int], share: float) -> int:
    return sorted(values)[min(len(values) - 1, int(share * len(values)))]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parts", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()

    groups: dict[tuple[str, str, str], list[Path]] = {}
    for part in sorted(path.parent for path in arguments.parts.rglob("part.json")):
        meta = json.loads((part / "part.json").read_text(encoding="utf-8"))
        if meta["kind"] == "outputs":
            shutil.copytree(part / "outputs", arguments.out, dirs_exist_ok=True)
            print(f"{part.name}: copied {sorted(path.name for path in (part / 'outputs').iterdir())}")
        elif meta["kind"] == "keyboard":
            groups.setdefault((meta["engine"], meta["task"], meta["half"]), []).append(part)
        else:
            raise SystemExit(f"{part.name}: unknown kind {meta['kind']}")

    for (engine, task, half), parts in groups.items():
        folder = arguments.out / engine
        folder.mkdir(parents=True, exist_ok=True)
        sample = read_lines(parts[0] / "sample.jsonl")
        first_meta = json.loads((parts[0] / "part.json").read_text(encoding="utf-8"))
        key_interval_ms = round(1000 * first_meta["key_interval"])
        control = first_meta["control"]
        if control and task != "english":
            raise SystemExit(f"{parts[0].name}: the control run is defined for the english task only")
        attempts: dict[str, list[dict]] = {}
        for part in parts:
            if [case["id"] for case in read_lines(part / "sample.jsonl")] != [case["id"] for case in sample]:
                raise SystemExit(f"{part.name}: the sample differs from the sample of {parts[0].name}")
            if (part / "attempts.jsonl").exists():
                for attempt in read_lines(part / "attempts.jsonl"):
                    attempts.setdefault(attempt["id"], []).append(attempt)
            diagnostics = folder / "diagnostics" / part.name
            diagnostics.mkdir(parents=True, exist_ok=True)
            for path in part.iterdir():
                if path.is_file() and path.suffix != ".jsonl":
                    shutil.copy2(path, diagnostics / path.name)

        rows = []
        for case in sample:
            attempt = counted_attempt(attempts.get(case["id"], []))
            if attempt is None:
                continue
            fields = english_fields(case, attempt) if task == "english" else pinyin_fields(case, attempt)
            gaps = key_gaps(task, attempt)
            rows.append({
                **attempt, **fields, "intended": case["intended"],
                "right": normalize(task, fields["output"]) == normalize(task, case["intended"]),
                "key_gaps_ms": gaps,
                "rhythm_kept": all(gap <= RHYTHM_LIMIT * key_interval_ms for gap in gaps),
                **({"exact": attempt["after"] == (case["context"] + " " if case["context"] else "") + case["typed"] + " "} if control else {}),
                "attempts": len(attempts[case["id"]]),
            })
        write_lines(folder / f"{task}.{half}.cases.jsonl", sample)
        write_lines(folder / f"{task}.{half}.jsonl", [{"id": row["id"], "output": row["output"]} for row in rows])
        write_lines(folder / f"{task}.{half}.detail.jsonl", rows)

        # The checks say how far the typing of this run matched the typing the cases describe.
        checks = {
            "sampled cases": len(sample),
            "typed cases": len(rows),
            "parts": len(parts),
            "attempts": sum(len(case_attempts) for case_attempts in attempts.values()),
            "attempts that ended with an error": sum("error" in attempt for case_attempts in attempts.values() for attempt in case_attempts),
            "cases typed in more than one pass": sum(row["attempts"] > 1 for row in rows),
            f"cases whose counted attempt has a key gap above {RHYTHM_LIMIT} times the key interval": sum(not row["rhythm_kept"] for row in rows),
            "cases whose counted attempt is not complete": sum(not row["complete"] for row in rows),
            "cases where a key tap did not arrive": sum(not row["letters_arrived"] for row in rows),
            "right cases": sum(row["right"] for row in rows),
            "cases with every key gap inside the limit": sum(row["rhythm_kept"] for row in rows),
            "right cases among the cases with every key gap inside the limit": sum(row["right"] for row in rows if row["rhythm_kept"]),
        }
        if control:
            exact = sum(row["exact"] for row in rows)
            checks["control: cases whose text view holds exactly the typed characters"] = exact
            checks["control: share of the typed cases"] = round(exact / len(rows), 4) if rows else None
        if task == "english":
            checks["cases where the keyboard changed the context"] = sum(not row["context_kept"] for row in rows)
            checks["cases with an inline prediction left as marked text"] = sum(row["after_marked"] for row in rows)
        else:
            checks["cases that took more than one space tap"] = sum(row["space_taps"] > 1 for row in rows)
        gaps = [gap for row in rows for gap in row["key_gaps_ms"]]
        if gaps:
            checks["key interval asked for, ms"] = key_interval_ms
            checks["time between two key arrivals in the counted attempts, ms"] = {
                "median": percentile(gaps, 0.5), "10th percentile": percentile(gaps, 0.1),
                "90th percentile": percentile(gaps, 0.9), "99th percentile": percentile(gaps, 0.99), "gaps": len(gaps)}
        if rows:
            seconds = sorted(row["seconds"] for row in rows)
            checks["seconds per counted attempt"] = {"median": seconds[len(seconds) // 2], "sum": round(sum(seconds))}
        (folder / f"{task}.{half}.checks.json").write_text(
            json.dumps(checks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        print()
        print(f"{engine} {task}.{half}")
        for name, value in checks.items():
            print(f"  {name}: {value}")
        shown: dict[str, int] = {}
        for row in rows:
            shown[row["category"]] = shown.get(row["category"], 0) + 1
            if shown[row["category"]] <= 4:
                mark = "right" if row["right"] else "WRONG"
                print(f"  {row['category']:24s} {row['typed']} -> {row['output']} (intended {row['intended']}) {mark}")


if __name__ == "__main__":
    main()
