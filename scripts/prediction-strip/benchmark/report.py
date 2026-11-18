"""The result tables of a half of the benchmark of the predicted words as Markdown, from the
files of simulate.py and time_reads.py: scripts/prediction-strip/benchmark/results/HALF-tables.md.

The tables give saved key presses in percent with their 95% interval, the paired differences
that the decision rule of docs/prediction-strip-benchmark-design.md reads, and the steps of
that rule. build_doc.py puts the tables into the results document.

Cost classes of the decision rule: the engine's order costs the least. A word order with one
model read per word costs more with a larger model file. Two model files of one size in MB, to
one decimal, cost the same. The word order M+R costs more than M and M+E with the same file.
The rule reads the classes from the cheapest to the costliest, and a larger file counts before
more model reads.

Usage, in WSL, from the repository root:
    uv run --with numpy python scripts/prediction-strip/benchmark/report.py --half dev
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import core  # noqa: E402
from simulate import FIRST_WORD_RULES, RESULTS, SAMPLES_FOLDER, STRIP_WORDS, TYPED_LETTERS  # noqa: E402
from places import FORM_RULES, WEIGHTS  # noqa: E402

MODEL_TITLES = {"shipped": "shipped fine-tune", "base135": "SmolLM2-135M", "smol360": "SmolLM2-360M", "qwen05": "Qwen2.5-0.5B"}
NEEDED_POINTS = 1.0   # rule 2 of the decision rule


def title(name: str) -> str:
    """A word order as the tables name it: the order, the model file, the form rule, the first word."""
    if name == "E":
        return "E"
    parts = name.split("|")
    model, rule, first_word, weight = parts[:4]
    order = "M" if float(weight) == 0 else f"M+E {weight}"
    if len(parts) == 5:
        order = "M+R"
    return f"{order}, {MODEL_TITLES.get(model, model)}, {rule}, {first_word}"


class Numbers:
    """The numbers of one half."""

    def __init__(self, half: str):
        self.data = json.loads((RESULTS / f"{half}.json").read_text(encoding="utf-8"))
        self.cost = json.loads((RESULTS / "cost.json").read_text(encoding="utf-8"))["models"]
        stored = np.load(SAMPLES_FOLDER / f"{half}.npz")
        self.names = [str(name) for name in stored["names"]]
        self.samples = stored["samples"].astype(np.float64)   # set, order, strip words, typist, sample
        self.values = stored["values"]
        self.number = {name: index for index, name in enumerate(self.names)}
        self.models = sorted({name.split("|")[0] for name in self.names if name != "E"}, key=list(MODEL_TITLES).index)

    def entry(self, name: str, words: int = 3, typist: int = 1, where: str = "mean") -> list[float]:
        return self.data["orders"][name]["saved"][f"{words}/{typist}"][where]

    def saved(self, name: str, words: int = 3, typist: int = 1, where: str = "mean") -> str:
        entry = self.entry(name, words, typist, where)
        return f"{100 * entry[0]:.1f} ({100 * entry[1]:.1f} to {100 * entry[2]:.1f})"

    def number_of(self, name: str) -> float:
        """The deciding number: saved key presses for a strip of 3 words, mean of the sets."""
        return self.entry(name)[0]

    def gap(self, first: str, second: str, words: int = 3, typist: int = 1, text_set: str | None = None) -> tuple[float, float, float]:
        """Saved key presses of `first` minus those of `second` in points, with the paired interval."""
        w, t = STRIP_WORDS.index(words), (1, 2).index(typist)
        one, two = self.number[first], self.number[second]
        if text_set is None:
            pairs = self.samples[:, one, w, t].mean(axis=0) - self.samples[:, two, w, t].mean(axis=0)
            point = self.values[:, one, w, t].mean() - self.values[:, two, w, t].mean()
        else:
            s = core.SETS.index(text_set)
            pairs = self.samples[s, one, w, t] - self.samples[s, two, w, t]
            point = self.values[s, one, w, t] - self.values[s, two, w, t]
        return 100 * float(point), 100 * float(np.percentile(pairs, 2.5)), 100 * float(np.percentile(pairs, 97.5))

    def difference(self, first: str, second: str, **where) -> str:
        point, low, high = self.gap(first, second, **where)
        return f"{point:+.2f} ({low:+.2f} to {high:+.2f})"

    def highest(self, names: list[str]) -> str:
        return max(names, key=self.number_of)

    def megabytes(self, model: str) -> float:
        return round(self.cost[model]["bytes"] / 1e6, 1)

    def decision(self) -> tuple[str, list[dict]]:
        """The choice of the decision rule and its steps."""
        classes: dict[tuple[float, int], list[str]] = {}
        for name in self.names:
            if name != "E":
                classes.setdefault((self.megabytes(name.split("|")[0]), 2 if name.endswith("|R") else 1), []).append(name)
        choice, steps = "E", []
        for key in sorted(classes):
            candidate = self.highest(classes[key])
            point, low, _ = self.gap(candidate, choice)
            takes = point >= NEEDED_POINTS and low > 0
            steps.append({"megabytes": key[0], "reads": key[1], "candidate": candidate, "against": choice, "takes": takes})
            if takes:
                choice = candidate
        return choice, steps


def tables(numbers: Numbers) -> dict[str, list[str]]:
    """The tables by their names."""
    n = numbers
    result: dict[str, list[str]] = {}

    out = ["| Set | Sentences | Chunks | Plain words | Strip states | Key presses without the strip |", "| --- | --- | --- | --- | --- | --- |"]
    for text_set in core.SETS:
        row = n.data["counts"][text_set]
        out.append(f"| {text_set} | {row['sentences']:,} | {row['chunks']:,} | {row['plain_words']:,} | {row['strip_states']:,} | {row['key_presses']:,} |")
    result["text sets"] = out

    out = ["| Model file | Form rule | First word none | First word engine | First word model |", "| --- | --- | --- | --- | --- |"]
    for model in n.models:
        for rule in FORM_RULES:
            cells = [n.saved(f"{model}|{rule}|{first_word}|0.0") for first_word in FIRST_WORD_RULES]
            out.append(f"| {MODEL_TITLES[model]} | {rule} | " + " | ".join(cells) + " |")
    result["settings of M"] = out

    out = ["| Model file | Form rule | " + " | ".join(f"Weight {weight}" for weight in WEIGHTS) + " |",
           "| --- | --- | " + " | ".join("---" for _ in WEIGHTS) + " |"]
    for model in n.models:
        for rule in FORM_RULES:
            cells = [n.saved(f"{model}|{rule}|engine|{weight}") for weight in WEIGHTS]
            out.append(f"| {MODEL_TITLES[model]} | {rule} | " + " | ".join(cells) + " |")
    result["mix weights"] = out

    rows = ["E"]
    for model in n.models:
        every = [name for name in n.names if name.startswith(model + "|") and not name.endswith("|R")]
        plain = n.highest([name for name in every if name.endswith("|0.0")])
        mixed = n.highest(every)
        rows.append(plain)
        if mixed != plain:
            rows.append(mixed)
        rows.extend(name for name in n.names if name.startswith(model + "|") and name.endswith("|R"))
    rows.sort(key=n.number_of, reverse=True)

    out = ["| Word order | Strip of 3, mean | technical | everyday | mobile | Strip of 6, mean | Strip of 10, mean |",
           "| --- | --- | --- | --- | --- | --- | --- |"]
    for name in rows:
        out.append(f"| {title(name)} | {n.saved(name)} | " + " | ".join(n.saved(name, where=text_set) for text_set in core.SETS)
                   + f" | {n.saved(name, 6)} | {n.saved(name, 10)} |")
    result["word orders"] = out

    out = ["| Word order | Mean of the sets | technical | everyday | mobile |", "| --- | --- | --- | --- | --- |"]
    for name in rows:
        if name != "E":
            out.append(f"| {title(name)} | {n.difference(name, 'E')} | "
                       + " | ".join(n.difference(name, "E", text_set=text_set) for text_set in core.SETS) + " |")
    result["differences to E"] = out

    choice, steps = n.decision()
    out = ["| Step | File size, MB | Model reads | Word order of the cost class with the most saved key presses | Saved key presses | Difference to the choice so far | Takes the place |",
           "| --- | --- | --- | --- | --- | --- | --- |"]
    for index, step in enumerate(steps, start=1):
        reads = "1 per word" if step["reads"] == 1 else "1 per word and 1 per strip state"
        out.append(f"| {index} | {step['megabytes']} | {reads} | {title(step['candidate'])} | {100 * n.number_of(step['candidate']):.2f} | "
                   f"{n.difference(step['candidate'], step['against'])} against {title(step['against'])} | {'yes' if step['takes'] else 'no'} |")
    result["decision rule"] = out

    if choice != "E":
        model, rule, first_word, weight = choice.split("|")[:4]
        tail = "|R" if choice.endswith("|R") else ""
        others = [("form rule", f"{model}|{other}|{first_word}|{weight}{tail}") for other in FORM_RULES]
        others += [("first word", f"{model}|{rule}|{other}|{weight}{tail}") for other in FIRST_WORD_RULES]
        others += [("mix weight", f"{model}|{rule}|{first_word}|{other}{tail}") for other in WEIGHTS]
        for other in n.models:
            if other != model and n.megabytes(other) == n.megabytes(model):
                others.append(("model file", n.highest([name for name in n.names if name.startswith(other + "|") and not name.endswith("|R")])))
        out = ["| Changed setting | Word order | Saved key presses | Difference to the choice |", "| --- | --- | --- | --- |"]
        for label, name in others:
            if name != choice and name in n.number:
                out.append(f"| {label} | {title(name)} | {100 * n.number_of(name):.2f} | {n.difference(name, choice)} |")
        result["settings around the choice"] = out

    out = ["| Word order | Strip of 3 | Strip of 6 | Strip of 10 |", "| --- | --- | --- | --- |"]
    for name in rows:
        out.append(f"| {title(name)} | {n.saved(name, 3, 2)} | {n.saved(name, 6, 2)} | {n.saved(name, 10, 2)} |")
    result["second typist"] = out

    shown = ["E"] + ([choice] if choice != "E" else [])
    for model in n.models:
        plain = n.highest([name for name in n.names if name.startswith(model + "|") and name.endswith("|0.0")])
        if plain not in shown:
            shown.append(plain)
    shown += [name for name in rows if name.endswith("|R") and name not in shown]
    out = ["| Word order | Set | " + " | ".join(f"{count} typed letters" for count in TYPED_LETTERS) + " |",
           "| --- | --- | " + " | ".join("---" for _ in TYPED_LETTERS) + " |"]
    for name in shown:
        for text_set in core.SETS:
            pairs = n.data["orders"][name]["found"]["3"][text_set]
            out.append(f"| {title(name)} | {text_set} | " + " | ".join(f"{100 * found / total:.1f}" for found, total in pairs) + " |")
    result["found share"] = out

    out = ["| Model file | Size, MB | PC time of one read, ms: median, 95th percentile | PC time of one request of M+R, ms: median, 95th percentile |",
           "| --- | --- | --- | --- |"]
    for model in n.models:
        entry = n.cost[model]
        request = f"{entry['request_ms_median']:.1f}, {entry['request_ms_p95']:.1f}" if "request_ms_median" in entry else "not run"
        out.append(f"| {MODEL_TITLES[model]} | {entry['bytes'] / 1e6:.1f} | {entry['read_ms_median']:.1f}, {entry['read_ms_p95']:.1f} | {request} |")
    result["cost"] = out
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--half", required=True)
    args = parser.parse_args()
    numbers = Numbers(args.half)
    parts = []
    for name, lines in tables(numbers).items():
        parts.append(f"## {name}\n\n" + "\n".join(lines) + "\n")
    choice, _ = numbers.decision()
    parts.append(f"Choice by the decision rule: {title(choice)} (`{choice}`).\n")
    text = "\n".join(parts)
    (RESULTS / f"{args.half}-tables.md").write_text(text, encoding="utf-8", newline="\n")
    print(text)


if __name__ == "__main__":
    main()
