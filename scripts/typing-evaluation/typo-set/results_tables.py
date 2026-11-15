"""Writes the tables of docs/typo-set-results.md from the artifacts of one run of "Language model
in the keyboard", so each number of the document comes from a file of that run.

The real-data outputs of the artifacts are SHA-256 values (redact_real.py). The script compares
them with the SHA-256 values of the normalized typed and intended texts of the local case
files, which build_real_typos.py writes from the same data, so it needs those files.

Usage, from the repository root:
    gh run download RUN_ID -D DIR
    python3 scripts/typing-evaluation/typo-set/results_tables.py --artifacts DIR --out TABLES.md
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
from score import normalize  # noqa: E402

GENERATED = ROOT / "scripts" / "typing-evaluation" / "cases"
REAL = ROOT / "build" / "typo-set" / "cases"
ENGLISH = [("english-typos", GENERATED), ("english-typos-capitals", GENERATED), ("english-typos-aalto", REAL)]
PINYIN = [("pinyin-typos", GENERATED), ("pinyin-typos-cscd", REAL)]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def hashed(path: Path, task: str) -> dict[str, str]:
    return {r["id"]: r.get("normalized_output_sha256") or sha(normalize(task, r["output"])) for r in read_jsonl(path)}


def summary(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def cell(entry: dict | None) -> str:
    return "" if entry is None else f"{entry['right']}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    a = arguments.artifacts
    lines = []
    for name, folder in ENGLISH:
        runs = {"Engine alone": summary(a / "typo-keyboard" / f"{name}.dev.engine-only.summary.json"),
                "Keyboard with the model": summary(a / "typo-keyboard" / f"{name}.dev.summary.json"),
                "x86 harness with the model": summary(a / "typo-harness" / f"{name}.dev.summary.json")}
        first = next(iter(runs.values()))
        lines += [f"## {name}", "", "| Count | Cases | " + " | ".join(runs) + " |", "| --- | --- |" + " --- |" * len(runs)]
        lines.append("| all cases | " + f"{first['cases']:,} | " + " | ".join(str(s["right"]) for s in runs.values()) + " |")
        for kind in ("groups", "categories"):
            for key, entry in first[kind].items():
                label = f"group `{key}`" if kind == "groups" else f"`{key}`"
                lines.append(f"| {label} | {entry['cases']:,} | " + " | ".join(cell(s[kind].get(key)) for s in runs.values()) + " |")
        for field, values in first["strata"].items():
            if field in ("pair", "direction"):
                continue
            for key, entry in values.items():
                lines.append(f"| {field}: {key} | {entry['cases']:,} | "
                             + " | ".join(cell(s["strata"][field].get(key)) for s in runs.values()) + " |")
        # The cases where the model and the engine alone differ in being right.
        cases = read_jsonl(folder / f"{name}.dev.jsonl")
        engine = hashed(a / "typo-keyboard" / f"{name}.dev.engine-only.jsonl", "english")
        model = hashed(a / "typo-keyboard" / f"{name}.dev.jsonl", "english")
        lines += ["", "| Next words typed | Model right, engine wrong | Engine right, model back to the typed text | Engine right, model other text |",
                  "| --- | --- | --- | --- |"]
        for follow in (False, True):
            subset = [c for c in cases if bool(c.get("follow")) == follow]
            gain = back = other = 0
            for c in subset:
                intended, typed = sha(normalize("english", c["intended"])), sha(normalize("english", c["typed"]))
                e_right, m_right = engine[c["id"]] == intended, model[c["id"]] == intended
                if m_right and not e_right:
                    gain += 1
                elif e_right and not m_right:
                    if model[c["id"]] == typed:
                        back += 1
                    else:
                        other += 1
            lines.append(f"| {'yes' if follow else 'no'} | {gain} | {back} | {other} |")
        lines.append("")
    for name, folder in PINYIN:
        runs = {"C engine": summary(a / "typo-harness" / f"{name}.dev.engine-only.summary.json"),
                "Keyboard": summary(a / "typo-keyboard" / f"{name}.dev.summary.json")}
        first = runs["Keyboard"]
        lines += [f"## {name}", "", "| Count | Cases | C engine | Keyboard | Keyboard, right of the cases with the twin right |",
                  "| --- | --- | --- | --- | --- |"]
        lines.append(f"| all cases | {first['cases']:,} | {runs['C engine']['right']} | {first['right']} | |")
        for kind in ("groups", "categories"):
            for key, entry in first[kind].items():
                label = f"group `{key}`" if kind == "groups" else f"`{key}`"
                twin = (f"{entry['right_when_twin_right']} of {entry['twin_right_cases']}"
                        if kind == "groups" and "twin_right_cases" in entry else "")
                lines.append(f"| {label} | {entry['cases']:,} | {cell(runs['C engine'][kind].get(key))} | {entry['right']} | {twin} |")
        for field, values in first["strata"].items():
            for key, entry in values.items():
                lines.append(f"| {field}: {key} | {entry['cases']:,} | {cell(runs['C engine']['strata'].get(field, {}).get(key))} | "
                             f"{entry['right']} | |")
        lines.append("")
    arguments.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
