"""Reads the accuracy replays and the speed pass of scripts/kv-reuse/jobs and writes the tables of
docs/kv-reuse-results.md, and the pick of the selection rule of docs/kv-reuse-design.md.

Usage: python3 scripts/kv-reuse/analyze.py --kv ~/kvreuse --out OUT
Writes OUT/tables.md and OUT/summary.json.
"""
import argparse
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
sys.path.insert(0, str(ROOT / "scripts" / "lm-keyboard"))
import harness_trace  # noqa: E402
import rerank  # noqa: E402

SETTING = harness_trace.TUNED
# The approaches in the order of the tables: name, description.
APPROACHES = [("A", "no reuse"), ("B", "prefix, 1 slot"), ("C", "shift, 1 slot"), ("D", "anchor, 1 slot"),
              ("BE", "prefix, 2 slots"), ("CE", "shift, 2 slots"), ("DE", "anchor, 2 slots"),
              ("B1", "prefix, 1 slot, calls of one token")]
# The approaches that the selection rule compares, first round and second round.
FIRST_ROUND = ["C", "D", "BE", "CE", "DE"]
GROUPS = ["clean", "letter_slips", "space_slips", "symbol_slips", "clean_symbols"]
PARTS = ["dev", "work area dev", "everyday stream", "technical stream", "written stream"]


def percentile(values: list[float], fraction: float) -> float:
    """The nearest rank, as RerankStatistics.percentileMilliseconds in the keyboard."""
    ordered = sorted(values)
    rank = math.ceil(fraction * len(ordered))
    return ordered[min(max(rank, 1), len(ordered)) - 1]


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def parse_answer(line: str) -> list[tuple[float, float]]:
    return [tuple(float(value) for value in field.split(" ")) for field in line.split("\t")]


def speed_table(kv: Path, meta: list[list[str]], parts: dict[str, str]) -> dict:
    """Per approach: the times and the tokens of the speed pass, over all requests and per part."""
    result = {}
    for name, _ in APPROACHES + [("A-again", "")]:
        path = kv / "speed" / f"{name}.times"
        if not path.exists():
            continue
        rows = [line.split(" ") for line in read_lines(path)]
        if len(rows) != len(meta):
            raise SystemExit(f"{path} has {len(rows)} lines for {len(meta)} requests")
        groups = {"all": list(range(len(rows)))}
        for part in PARTS:
            groups[part] = [i for i, m in enumerate(meta) if parts[m[0]] == part]
        entry = {}
        for group, indices in groups.items():
            if not indices:
                continue
            window = [float(rows[i][2]) for i in indices]
            candidates = [float(rows[i][3]) for i in indices]
            total = [float(rows[i][4]) for i in indices]
            tokens = sum(int(rows[i][0]) for i in indices)
            kept = sum(int(rows[i][1]) for i in indices)
            entry[group] = {
                "requests": len(indices), "window_tokens": tokens, "kept_tokens": kept, "reuse_share": kept / tokens,
                "window_ms": {"mean": statistics.fmean(window), "median": percentile(window, 0.5), "p95": percentile(window, 0.95)},
                "candidate_ms": {"mean": statistics.fmean(candidates), "median": percentile(candidates, 0.5)},
                "total_ms": {"mean": statistics.fmean(total), "median": percentile(total, 0.5), "p95": percentile(total, 0.95)},
            }
        result[name] = entry
    return result


def numbers_table(kv: Path) -> dict:
    """Per approach: the requests of the speed pass whose numbers differ from A's, and how far."""
    reference = [parse_answer(line) for line in read_lines(kv / "speed" / "A.answers")]
    result = {}
    for name, _ in APPROACHES[1:] + [("A-again", "")]:
        path = kv / "speed" / f"{name}.answers"
        if not path.exists():
            continue
        answers = [parse_answer(line) for line in read_lines(path)]
        differing, widest, differences = 0, 0.0, []
        for mine, theirs in zip(answers, reference):
            gaps = [abs(a - b) for pair_a, pair_b in zip(mine, theirs) for a, b in zip(pair_a, pair_b)]
            gap = max(gaps)
            if gap > 0:
                differing += 1
                differences.append(gap)
            widest = max(widest, gap)
        result[name] = {"requests": len(answers), "differing": differing, "widest": widest,
                        "median_of_differing": percentile(differences, 0.5) if differences else 0.0}
    return result


def call_cost(kv: Path, name: str) -> list[dict]:
    """The time of the window calls of one approach by the count of window tokens the model read,
    from the speed pass. Requests that read 31 tokens or fewer make one window call."""
    rows = [line.split(" ") for line in read_lines(kv / "speed" / f"{name}.times")]
    by_count: dict[int, list[float]] = {}
    for row in rows:
        by_count.setdefault(int(row[0]) - int(row[1]), []).append(float(row[2]))
    return [{"tokens_read": count, "requests": len(values), "median_ms": percentile(values, 0.5)}
            for count, values in sorted(by_count.items()) if count <= 31 and len(values) >= 20]


class Mismatch(Exception):
    pass


def open_loop_decisions(kv: Path, a_requests: list[str]) -> dict:
    """Per approach: A's corrections chosen again with the approach's numbers of the speed pass."""
    corrections = [json.loads(line) for line in read_lines(kv / "accuracy" / "A" / "corrections.jsonl")]
    result = {}
    for name, _ in APPROACHES[1:]:
        path = kv / "speed" / f"{name}.answers"
        if not path.exists():
            continue
        answers = read_lines(path)
        changed = 0
        for correction in corrections:
            readings = correction["readings"]
            opens_field = not correction["context"]

            class Model:
                def reading_scores(self, context, readings_, typed):
                    values = parse_answer(answers[correction["typed_request"]])
                    return dict(zip([r["text"] for r in readings_], values))

                def step_scores(self, context, texts, prompt):
                    index = correction["stock_request"]
                    if index is None:
                        raise Mismatch()
                    sent = a_requests[index].split("\t")[1:]
                    if sent != [rerank.language_model_text(t, opens_field) for t in texts]:
                        raise Mismatch()
                    return dict(zip(texts, parse_answer(answers[index])))

            try:
                choice = rerank.choose(readings, correction["context"], SETTING, Model(), correction["typed"])
            except Mismatch:
                choice = None
            changed += int(choice != correction["choice"])
        result[name] = {"corrections": len(corrections), "changed": changed}
    return result


def closed_loop(kv: Path) -> dict:
    """Per approach: the counts of its own replay, and its decisions against A's."""
    def load(name):
        folder = kv / "accuracy" / name
        if not (folder / "result.json").exists():
            return None
        corrections = {(c["document"], c["index"]): c["choice"]
                       for c in map(json.loads, read_lines(folder / "corrections.jsonl"))}
        return json.loads((folder / "result.json").read_text(encoding="utf-8")), corrections

    reference = load("A")
    if reference is None:
        raise SystemExit("the replay of A has not finished")
    a_result, a_corrections = reference
    result = {}
    for name, _ in APPROACHES:
        loaded = load(name)
        if loaded is None:
            continue
        mine, corrections = loaded
        keys = set(a_corrections) | set(corrections)
        changed = sum(1 for key in keys if a_corrections.get(key) != corrections.get(key))
        dev = mine["dev"]
        result[name] = {
            "requests": mine["requests"], "corrections": len(corrections), "changed": changed,
            "changed_share": changed / len(a_corrections),
            "dev": [dev["groups"][g]["right"] for g in GROUPS] + [dev["right"]],
            "work_area": mine["work_area"]["right"], "kv_replay": mine["kv_replay"],
        }
    return result


def select(closed: dict, speed: dict) -> dict:
    """The selection rule of docs/kv-reuse-design.md."""
    a = closed["A"]

    def qualifies(name):
        entry = closed.get(name)
        if entry is None or name not in speed:
            return False
        return (entry["changed"] <= 0.001 * a["corrections"]
                and all(mine >= theirs for mine, theirs in zip(entry["dev"], a["dev"]))
                and entry["work_area"] >= a["work_area"])

    reasons = {name: qualifies(name) for name in FIRST_ROUND + ["B"]}
    first = [name for name in FIRST_ROUND if reasons[name]]
    if first:
        pick = min(first, key=lambda name: speed[name]["all"]["total_ms"]["mean"])
    elif reasons["B"]:
        pick = "B"
    else:
        pick = "A"
    return {"qualifies": reasons, "pick": pick}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kv", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    kv = arguments.kv
    arguments.out.mkdir(parents=True, exist_ok=True)
    meta = [line.split("\t") for line in read_lines(kv / "accuracy" / "A" / "requests.meta")]
    a_requests = read_lines(kv / "accuracy" / "A" / "requests.tsv")
    parts = {row["id"]: row["part"] for row in map(json.loads, read_lines(kv / "accuracy" / "A" / "outputs.jsonl"))}
    summary = {"speed": speed_table(kv, meta, parts), "numbers": numbers_table(kv),
               "open_loop": open_loop_decisions(kv, a_requests), "closed_loop": closed_loop(kv)}
    summary["requests_per_part"] = {part: sum(1 for m in meta if parts[m[0]] == part) for part in PARTS}
    summary["selection"] = select(summary["closed_loop"], summary["speed"])
    summary["call_cost_B"] = call_cost(kv, "B") if (kv / "speed" / "B.times").exists() else []
    (arguments.out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    names = dict(APPROACHES)
    lines = ["Speed, all requests of A's replay, 2 threads.", "",
             "| Approach | mean ms | median ms | 95th pct ms | window mean ms | window median ms | candidates mean ms | reuse share |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for name, entry in summary["speed"].items():
        e = entry["all"]
        lines.append(f"| {name} {names.get(name, 'no reuse, again')} | {e['total_ms']['mean']:.1f} | {e['total_ms']['median']:.1f} | "
                     f"{e['total_ms']['p95']:.1f} | {e['window_ms']['mean']:.1f} | {e['window_ms']['median']:.1f} | "
                     f"{e['candidate_ms']['mean']:.1f} | {100 * e['reuse_share']:.1f}% |")
    lines += ["", "Speed per part, mean ms per request and reuse share.", "",
              "| Approach | " + " | ".join(PARTS) + " |", "| --- |" + " --- |" * len(PARTS)]
    for name, entry in summary["speed"].items():
        lines.append(f"| {name} | " + " | ".join(
            f"{entry[p]['total_ms']['mean']:.1f} ({100 * entry[p]['reuse_share']:.0f}%)" if p in entry else "none"
            for p in PARTS) + " |")
    lines += ["", "Requests per part: " + json.dumps(summary["requests_per_part"]), "",
              "Accuracy, each approach's own replay.", "",
              "| Approach | requests | corrections | changed decisions | share | " + " | ".join(GROUPS) + " | all 6,799 | work area |",
              "| --- |" + " --- |" * (len(GROUPS) + 6)]
    for name, e in summary["closed_loop"].items():
        lines.append(f"| {name} {names[name]} | {e['requests']} | {e['corrections']} | {e['changed']} | "
                     f"{100 * e['changed_share']:.3f}% | " + " | ".join(str(v) for v in e["dev"]) + f" | {e['work_area']} |")
    lines += ["", "Numbers on A's requests, against A.", "",
              "| Approach | requests that differ | widest | median of those | decisions that differ |", "| --- | --- | --- | --- | --- |"]
    for name, e in summary["numbers"].items():
        decisions = summary["open_loop"].get(name, {}).get("changed", "")
        lines.append(f"| {name} | {e['differing']} of {e['requests']} | {e['widest']:.6g} | {e['median_of_differing']:.6g} | {decisions} |")
    lines += ["", "Window calls of B by the tokens the model read: median ms.", "",
              "| tokens read | requests | median ms |", "| --- | --- | --- |"]
    lines += [f"| {e['tokens_read']} | {e['requests']} | {e['median_ms']:.2f} |" for e in summary["call_cost_B"]]
    lines += ["", "Selection: " + json.dumps(summary["selection"])]
    (arguments.out / "tables.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
