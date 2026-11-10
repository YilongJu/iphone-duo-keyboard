"""Merges the parts that the workflow jobs wrote into one output folder per engine name.

Usage, from the repository root:
    python3 scripts/typing-evaluation/engines/apple-stock-keyboard/collect_outputs.py \
        --parts build/typing-evaluation-parts --out build/typing-evaluation

Each job of the workflow writes one part folder with a `part.json` file.

A part of kind `keyboard` holds the cases one job typed on the stock keyboard:
`sample.jsonl` (every sampled case of the engine name and half), `cases.jsonl` (the share of this
job), `detail.jsonl` (what the UI test read from the text view) and the run logs, accessibility
trees and screenshots. The script writes, for each engine name, task and half:
    TASK.HALF.cases.jsonl    the sampled cases, the file to score against
    TASK.HALF.jsonl          one object per typed case with the case `id` and the `output`
    TASK.HALF.detail.jsonl   the raw reads, the output and the checks for each typed case
    diagnostics/PART/        the logs, trees and screenshots of each part

A part of kind `outputs` holds finished files under `outputs/ENGINE/`, and the script copies them.

Field text of a case: the text view after the last space tap, read a second time after the
settle time of the run. Marked text does not count for English, because the English keyboard
marks an inline prediction that the person has not accepted.
Output of an English case: the field text after the first N words, where N is the number of
words in the context.
Output of a Pinyin case: the field text without spaces at the ends.
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


def english_fields(case: dict, detail: dict) -> dict:
    context_words = case["context"].split()
    field_text = detail.get("settled_committed", detail["after_committed"])
    words = field_text.split()
    prefix = case["context"] + " " if case["context"] else ""
    tokens = case["typed"].split(" ")
    states = [without_marked(entry).lower().replace("’", "'") for entry in detail["history"]]
    return {
        "output": " ".join(words[len(context_words):]),
        # False when the keyboard changed a word of the context while the person typed.
        "context_kept": [normalize("english", word) for word in words[: len(context_words)]] == context_words,
        # True when the field once held the context and the first typed token, letter for letter,
        # and once ended with the last typed token. False means that a key tap did not arrive.
        "letters_arrived": prefix + tokens[0] in states and any(state.endswith(tokens[-1]) for state in states),
        "changed_after_first_read": field_text != detail["after_committed"],
    }


def pinyin_fields(case: dict, detail: dict) -> dict:
    field_text = detail.get("settled", detail["after"])
    return {
        "output": field_text.strip(),
        # True when the marked text once held every typed letter.
        "letters_arrived": any(OPEN in entry and letters(entry) == case["typed"] for entry in detail["history"]),
        "marked_text_left": detail.get("settled_marked", detail["after_marked"]),
        "changed_after_first_read": field_text != detail["after"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parts", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()

    groups: dict[tuple[str, str, str], list[Path]] = {}
    for part in sorted(path for path in arguments.parts.iterdir() if (path / "part.json").exists()):
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
        details: dict[str, dict] = {}
        for part in parts:
            if [case["id"] for case in read_lines(part / "sample.jsonl")] != [case["id"] for case in sample]:
                raise SystemExit(f"{part.name}: the sample differs from the sample of {parts[0].name}")
            if (part / "detail.jsonl").exists():
                for detail in read_lines(part / "detail.jsonl"):
                    if detail["id"] in details:
                        raise SystemExit(f"{part.name}: case {detail['id']} appears in two parts")
                    details[detail["id"]] = detail
            diagnostics = folder / "diagnostics" / part.name
            diagnostics.mkdir(parents=True, exist_ok=True)
            for path in part.iterdir():
                if path.is_file() and path.suffix != ".jsonl":
                    shutil.copy2(path, diagnostics / path.name)

        rows = []
        for case in sample:
            if case["id"] not in details:
                continue
            detail = details[case["id"]]
            fields = english_fields(case, detail) if task == "english" else pinyin_fields(case, detail)
            right = normalize(task, fields["output"]) == normalize(task, case["intended"])
            rows.append({**detail, **fields, "intended": case["intended"], "right": right})
        write_lines(folder / f"{task}.{half}.cases.jsonl", sample)
        write_lines(folder / f"{task}.{half}.jsonl", [{"id": row["id"], "output": row["output"]} for row in rows])
        write_lines(folder / f"{task}.{half}.detail.jsonl", rows)

        print(f"\n{engine} {task}.{half}: {len(sample)} sampled cases, {len(rows)} typed, from {len(parts)} parts")
        print(f"  cases where a key tap did not arrive: {sum(not row['letters_arrived'] for row in rows)}")
        print(f"  cases where the first read after the space did not show the expected change: {sum(not row['after_as_expected'] for row in rows)}")
        print(f"  cases where the field text changed between the first read and the settled read: {sum(row['changed_after_first_read'] for row in rows)}")
        if task == "english":
            print(f"  cases where the keyboard changed the context: {sum(not row['context_kept'] for row in rows)}")
            print(f"  cases with an inline prediction left as marked text: {sum(row.get('settled_marked', row['after_marked']) for row in rows)}")
        else:
            print(f"  cases with marked text left after the space taps: {sum(row['marked_text_left'] for row in rows)}")
            print(f"  cases that took more than one space tap: {sum(row['space_taps'] > 1 for row in rows)}")
        if rows:
            seconds = sorted(row["seconds"] for row in rows)
            print(f"  seconds per case: median {seconds[len(seconds) // 2]}, sum {sum(seconds):.0f}")
        shown: dict[str, int] = {}
        for row in rows:
            shown[row["category"]] = shown.get(row["category"], 0) + 1
            if shown[row["category"]] <= 4:
                mark = "right" if row["right"] else "WRONG"
                print(f"  {row['category']:24s} {row['typed']} -> {row['output']} (intended {row['intended']}) {mark}")


if __name__ == "__main__":
    main()
