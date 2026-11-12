"""Applies the two rules of docs/lm-finetune2-design.md and writes the tables of round 2.

pick     reads the selection scores of evaluate2.py for every candidate arm, applies the five
         conditions of "Pick of one candidate", and names the candidate.
holdout  reads the one held-out read of read_holdout.py, writes the tables per arm, and applies the
         six conditions of "Replacement rule on the held-out set" to the candidate against `ship`
         and against the calibrated file of `ship`.

Both modes count from the prediction files, not from stored summaries. The four set shapes:
    generated   generated cases (the dev half, or the fresh held-out cases)
    stream      clean running text
    github      GitHub typos (github_misspelling and github_real_word)
    lists       misspelling lists without a context (published dev, or the Mitton remainder)

Usage, from the repository root:
    python scripts/lm-finetune2/summarize2.py pick --round1 ROUND1 --data build/lm-finetune2/data \
        --results RESULTS --ship smollm2-lora-seed1-calibrated:ship --arm NAME:tuned ... --out pick.json
    python scripts/lm-finetune2/summarize2.py holdout --round1 ROUND1 --data build/lm-finetune2/data \
        --read READ_FOLDER --plan scripts/lm-finetune2/holdout-plan.json --out OUT_FOLDER
"""
import argparse
import gzip
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-finetune2"))
import metrics2  # noqa: E402

CASES = ROOT / "scripts" / "typing-evaluation" / "cases"
GROUP_ORDER = ["clean", "clean_symbols", "letter_slips", "space_slips", "symbol_slips", "apostrophe_missing", "real_word_slip"]
NON_WORD_TOLERANCE = 25
NON_WORD_INTERVAL_FLOOR = -50
SOURCE_TOLERANCE_SHARE = 0.01
REAL_WORD_GAIN_SHARE = 0.5
BOOTSTRAP_SAMPLES = 2000
SLIP_SHARES = (0.02, 0.05, 0.10)
REAL_WORD_SHARES = (0.05, 0.12, 0.30)


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def predictions(path: Path) -> dict[str, str]:
    return {row["id"]: row["output"] for row in read_jsonl(path)}


def binomial_tail(successes: int, trials: int) -> float:
    """P(X <= successes) for X ~ Binomial(trials, 0.5)."""
    if trials == 0:
        return 1.0
    return sum(math.comb(trials, k) for k in range(successes + 1)) / 2 ** trials


class Arm:
    """The right cases and the changed words of one arm on the four set shapes."""

    def __init__(self, name: str, sets: dict[str, list[dict]], outputs: dict[str, dict[str, str]]):
        self.name = name
        self.right, self.changed = {}, {}
        for shape, cases in sets.items():
            for case in cases:
                output = outputs[shape][case["id"]]
                self.right[case["id"]] = metrics2.normal(output) == metrics2.normal(case["intended"])
                if shape == "stream":
                    self.changed[case["id"]] = metrics2.changed_words(output, case["intended"])

    def count(self, cases: list[dict]) -> int:
        return sum(self.right[case["id"]] for case in cases)

    def changed_words(self, cases: list[dict]) -> int:
        return sum(self.changed[case["id"]] for case in cases)


class Sets:
    def __init__(self, sets: dict[str, list[dict]]):
        self.sets = sets
        generated = sets["generated"]
        self.groups = {name: [c for c in generated if c["category"] in members] for name, members in metrics2.GENERATED_GROUPS.items()}
        self.non_word = [c for name in metrics2.NON_WORD_SLIP_GROUPS for c in self.groups[name]]
        self.closed = [c for c in sets["stream"] if c["category"] == "clean_stream_closed"]
        self.open = [c for c in sets["stream"] if c["category"] == "clean_stream_open"]
        self.github_misspelling = [c for c in sets["github"] if c["category"] == "github_misspelling"]
        self.github_real_word = [c for c in sets["github"] if c["category"] == "github_real_word"]
        self.lists = sets["lists"]
        self.words = {"closed": sum(len(c["intended"].split()) for c in self.closed), "open": sum(len(c["intended"].split()) for c in self.open)}

    def row(self, arm: Arm) -> dict:
        row = {"changed_words_closed": arm.changed_words(self.closed), "changed_words_open": arm.changed_words(self.open),
               "changed_sentences": sum(1 for c in self.sets["stream"] if not arm.right[c["id"]]),
               "non_word_slips": arm.count(self.non_word), "generated": arm.count(self.sets["generated"]),
               "github_misspelling": arm.count(self.github_misspelling), "github_real_word": arm.count(self.github_real_word),
               "github_misspelling_with_context": arm.count([c for c in self.github_misspelling if c["context"]]),
               "github_misspelling_without_context": arm.count([c for c in self.github_misspelling if not c["context"]]),
               "lists": arm.count(self.lists)}
        row["changed_words"] = row["changed_words_closed"] + row["changed_words_open"]
        row["real_misspellings"] = row["github_misspelling"] + row["lists"]
        for name in GROUP_ORDER:
            row[name] = arm.count(self.groups[name])
        for source in sorted({c["category"] for c in self.lists}):
            row[source] = arm.count([c for c in self.lists if c["category"] == source])
        return row

    def sizes(self) -> dict:
        sizes = {"closed_words": self.words["closed"], "open_words": self.words["open"], "stream_sentences": len(self.sets["stream"]),
                 "non_word_slips": len(self.non_word), "generated": len(self.sets["generated"]),
                 "github_misspelling": len(self.github_misspelling), "github_real_word": len(self.github_real_word),
                 "github_misspelling_with_context": sum(1 for c in self.github_misspelling if c["context"]),
                 "lists": len(self.lists)}
        sizes.update({name: len(self.groups[name]) for name in GROUP_ORDER})
        for source in sorted({c["category"] for c in self.lists}):
            sizes[source] = sum(1 for c in self.lists if c["category"] == source)
        return sizes

    def estimate(self, row: dict, slip_share: float, real_word_share: float) -> float:
        """Wrong words per 1,000 typed, the weighted estimate of the design. No rule uses it."""
        changed = row["changed_words"] / (self.words["closed"] + self.words["open"])
        non_word = 1 - row["non_word_slips"] / len(self.non_word)
        real_word = 1 - row["real_word_slip"] / len(self.groups["real_word_slip"])
        return 1000 * ((1 - slip_share) * changed + slip_share * ((1 - real_word_share) * non_word + real_word_share * real_word))

    def non_word_interval(self, arm: Arm, reference: Arm) -> tuple[float, float]:
        """The 95 percent interval of the difference in right non-word slips. It resamples the
        groups of cases with one context and one intended text."""
        groups: dict[tuple, int] = {}
        for case in self.non_word:
            key = (case["context"], metrics2.normal(case["intended"]))
            groups[key] = groups.get(key, 0) + int(arm.right[case["id"]]) - int(reference.right[case["id"]])
        values = list(groups.values())
        rng = random.Random("lm-finetune2-non-word-interval")
        sums = sorted(sum(rng.choices(values, k=len(values))) for _ in range(BOOTSTRAP_SAMPLES))
        return sums[int(0.025 * BOOTSTRAP_SAMPLES)], sums[int(0.975 * BOOTSTRAP_SAMPLES) - 1]


def pick_conditions(sets: Sets, arm: dict, ship: dict, control: dict) -> dict:
    return {
        "1 fewer changed words on the stream": arm["changed_words"] < ship["changed_words"],
        "2 clean and clean symbols each at least ship": arm["clean"] >= ship["clean"] and arm["clean_symbols"] >= ship["clean_symbols"],
        "3 real misspellings at least ship": arm["real_misspellings"] >= ship["real_misspellings"],
        "4 non-word slips at least ship less 25": arm["non_word_slips"] >= ship["non_word_slips"] - NON_WORD_TOLERANCE,
        "5 real-word slips keep half of the gain of ship": arm["real_word_slip"] - control["real_word_slip"]
        >= REAL_WORD_GAIN_SHARE * (ship["real_word_slip"] - control["real_word_slip"]),
    }


def replacement_conditions(sets: Sets, arm: Arm, reference: Arm, control: Arm) -> dict:
    a, s, c = sets.row(arm), sets.row(reference), sets.row(control)
    only_reference = sum(1 for case in sets.sets["stream"] if arm.right[case["id"]] and not reference.right[case["id"]])
    only_arm = sum(1 for case in sets.sets["stream"] if not arm.right[case["id"]] and reference.right[case["id"]])
    p_value = binomial_tail(only_arm, only_arm + only_reference)
    low, high = sets.non_word_interval(arm, reference)
    github_floor = s["github_misspelling"] - SOURCE_TOLERANCE_SHARE * len(sets.github_misspelling)
    lists_floor = s["lists"] - SOURCE_TOLERANCE_SHARE * len(sets.lists)
    conditions = {
        "1 fewer changed stream sentences at p < 0.05": a["changed_sentences"] < s["changed_sentences"] and p_value < 0.05,
        "2 changed words of the closed and the open stream each at most the reference": a["changed_words_closed"] <= s["changed_words_closed"]
        and a["changed_words_open"] <= s["changed_words_open"],
        "3 clean and clean symbols each at least the reference": a["clean"] >= s["clean"] and a["clean_symbols"] >= s["clean_symbols"],
        "4 non-word slips at least the reference less 25, interval floor -50": a["non_word_slips"] >= s["non_word_slips"] - NON_WORD_TOLERANCE
        and low >= NON_WORD_INTERVAL_FLOOR,
        "5 real misspellings pooled at least the reference, each source within 1 percent": a["real_misspellings"] >= s["real_misspellings"]
        and a["github_misspelling"] >= github_floor and a["lists"] >= lists_floor,
        "6 real-word slips keep half of the gain of the reference": a["real_word_slip"] - c["real_word_slip"]
        >= REAL_WORD_GAIN_SHARE * (s["real_word_slip"] - c["real_word_slip"]),
    }
    numbers = {"sentences_changed_only_by_the_reference": only_reference, "sentences_changed_only_by_the_arm": only_arm,
               "mcnemar_one_sided_p": p_value, "non_word_difference": a["non_word_slips"] - s["non_word_slips"],
               "non_word_interval": [low, high], "arm": a, "reference": s, "control": c}
    return {"conditions": conditions, "passes": all(conditions.values()), "numbers": numbers}


def paired_counts(sets: Sets, arm: Arm, reference: Arm) -> dict:
    """Cases that only one of two arms gets right, per group of cases, with the two-sided exact
    McNemar p value. The repeats of one context and one intended text are counted as cases, so
    the p value of the generated groups reads a little too small."""
    groups = {"clean and clean symbols": sets.groups["clean"] + sets.groups["clean_symbols"], "non-word slips": sets.non_word,
              "real-word slips": sets.groups["real_word_slip"], "real misspellings": sets.github_misspelling + sets.lists,
              "github misspelling": sets.github_misspelling, "lists": sets.lists, "github real word": sets.github_real_word}
    result = {}
    for label, cases in groups.items():
        only_arm = sum(1 for case in cases if arm.right[case["id"]] and not reference.right[case["id"]])
        only_reference = sum(1 for case in cases if reference.right[case["id"]] and not arm.right[case["id"]])
        p_value = min(1.0, 2 * binomial_tail(min(only_arm, only_reference), only_arm + only_reference))
        result[label] = {"cases": len(cases), "only_arm": only_arm, "only_reference": only_reference, "two_sided_p": p_value}
    return result


def seen_flags(round1: Path, data: Path, generated: list[dict]) -> tuple[set, set]:
    """The phrases (context and intended text) of the generated cases that a training sentence
    holds, and the typed and target pairs of every training and stopping list."""
    round1_data = round1 / "build" / "lm-finetune" / "data"
    sentences = {c["sentence"] for c in read_jsonl(round1_data / "cases.train.jsonl")} | {c["sentence"] for c in read_jsonl(data / "cases2.train.jsonl")}
    wanted = {tuple((c["context"] + " " + metrics2.normal(c["intended"])).split(" ")) for c in generated if c["context"]}
    sizes = sorted({len(p) for p in wanted})
    phrases = set()
    for text in sentences:
        words = tuple(text.split(" "))
        for n in sizes:
            for i in range(len(words) - n + 1):
                if words[i:i + n] in wanted:
                    phrases.add(words[i:i + n])
    pairs = set()
    for path in (round1_data / "lists.train.jsonl.gz", round1_data / "lists.stop.jsonl.gz", data / "lists2.train.jsonl.gz", data / "lists2.stop.jsonl.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as file:
            for line in file:
                item = json.loads(line)
                pairs.add((item["typed"], item["readings"][item["target"]][0]))
    return phrases, pairs


def table(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def per_10000(changed: int, words: int) -> str:
    return f"{changed} ({10000 * changed / words:.1f})"


def main_table(sets: Sets, rows: dict[str, dict]) -> str:
    sizes = sets.sizes()
    header = ["Arm", f"closed stream, changed of {sizes['closed_words']:,} words (per 10,000)",
              f"open stream, changed of {sizes['open_words']:,} words (per 10,000)",
              *[f"{name.replace('_', ' ')} /{sizes[name]:,}" for name in GROUP_ORDER],
              f"github misspelling /{sizes['github_misspelling']:,}", f"lists /{sizes['lists']:,}",
              f"github real word /{sizes['github_real_word']:,}"]
    body = [[f"`{name}`", per_10000(row["changed_words_closed"], sizes["closed_words"]), per_10000(row["changed_words_open"], sizes["open_words"]),
             *[row[group] for group in GROUP_ORDER], row["github_misspelling"], row["lists"], row["github_real_word"]]
            for name, row in rows.items()]
    return table(header, body)


def pick(arguments) -> None:
    round1 = arguments.round1
    sets = Sets({"generated": read_jsonl(CASES / "english.dev.jsonl") + read_jsonl(CASES / "english-symbols.dev.jsonl"),
                 "stream": read_jsonl(arguments.data / "cases.stream.select.jsonl"),
                 "github": read_jsonl(arguments.data / "cases.github.select.jsonl"),
                 "lists": read_jsonl(round1 / "build" / "typing-evaluation" / "external" / "english.dev.jsonl")})
    files = {"generated": "dev", "stream": "stream", "github": "github", "lists": "published_dev"}

    def load(spec: str) -> Arm:
        name, label = spec.split(":")
        folder = arguments.results / name
        return Arm(spec, sets.sets, {shape: predictions(folder / f"{label}.{file}.jsonl") for shape, file in files.items()})

    ship = load(arguments.ship)
    control = Arm("control", sets.sets, {shape: predictions(arguments.results / arguments.ship.split(":")[0] / f"control.{file}.jsonl")
                                         for shape, file in files.items()})
    rows = {"control": sets.row(control), "ship": sets.row(ship)}
    result = {"sizes": sets.sizes(), "ship": arguments.ship, "arms": {}}
    qualified = []
    dry_run = {}
    for spec in arguments.arm:
        arm = load(spec)
        # A dry run of the replacement conditions on the selection sets. It checks the code, and it decides nothing.
        dry_run[spec] = replacement_conditions(sets, arm, ship, control)
        row = sets.row(arm)
        rows[spec] = row
        conditions = pick_conditions(sets, row, rows["ship"], rows["control"])
        result["arms"][spec] = {"row": row, "conditions": conditions, "qualifies": all(conditions.values())}
        if all(conditions.values()):
            qualified.append(spec)
    # Fewest changed words, then most real misspellings, then most non-word slips, then the order given.
    order = sorted(qualified, key=lambda spec: (rows[spec]["changed_words"], -rows[spec]["real_misspellings"], -rows[spec]["non_word_slips"],
                                                 arguments.arm.index(spec)))
    result.update({"rows": rows, "qualified": qualified, "candidate": order[0] if order else None,
                   "dry_run_of_the_replacement_conditions_on_the_selection_sets": dry_run})
    for name, row in rows.items():
        row["estimate"] = {f"s={s} r={r}": round(sets.estimate(row, s, r), 2) for s in SLIP_SHARES for r in REAL_WORD_SHARES}
    arguments.out.mkdir(parents=True, exist_ok=True)
    (arguments.out / "pick.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    text = "Selection sets, right cases and changed words per arm.\n\n" + main_table(sets, rows) + "\n"
    names = list(next(iter(result["arms"].values()))["conditions"]) if result["arms"] else []
    text += "Conditions of the pick per arm.\n\n" + table(
        ["Arm", *names, "qualifies"],
        [[f"`{spec}`", *["yes" if entry["conditions"][n] else "no" for n in names], "yes" if entry["qualifies"] else "no"]
         for spec, entry in result["arms"].items()])
    text += f"\nCandidate: {result['candidate']}\n\n"
    text += "Dry run of the six replacement conditions on the selection sets. It checks the code, and it decides nothing.\n\n" + table(
        ["Arm", "1", "2", "3", "4", "5", "6", "changed sentences only ship / only arm", "p", "non-word difference (interval)"],
        [[f"`{spec}`", *["yes" if v else "no" for v in d["conditions"].values()],
          f"{d['numbers']['sentences_changed_only_by_the_reference']} / {d['numbers']['sentences_changed_only_by_the_arm']}",
          f"{d['numbers']['mcnemar_one_sided_p']:.3g}",
          f"{d['numbers']['non_word_difference']:+d} ({d['numbers']['non_word_interval'][0]:+d} to {d['numbers']['non_word_interval'][1]:+d})"]
         for spec, d in dry_run.items()])
    (arguments.out / "pick.md").write_text(text, encoding="utf-8")
    print(text)


def holdout(arguments) -> None:
    plan = json.loads(arguments.plan.read_text(encoding="utf-8"))
    read = json.loads((arguments.read / "result.json").read_text(encoding="utf-8"))
    if read["plan"] != plan:
        raise SystemExit("the read used another plan")
    sets = Sets({"generated": read_jsonl(arguments.data / "cases.generated.holdout.jsonl"),
                 "stream": read_jsonl(arguments.data / "cases.stream.holdout.jsonl"),
                 "github": read_jsonl(arguments.data / "cases.github.holdout.jsonl"),
                 "lists": read_jsonl(arguments.data / "cases.mitton-remainder.holdout.jsonl")})
    files = {"generated": "generated", "stream": "stream", "github": "github", "lists": "mitton"}
    arms = {arm["name"]: Arm(arm["name"], sets.sets, {shape: predictions(arguments.read / f"{arm['name']}.{file}.jsonl")
                                                     for shape, file in files.items()}) for arm in plan["arms"]}
    rows = {name: sets.row(arm) for name, arm in arms.items()}
    sizes = sets.sizes()
    result = {"sizes": sizes, "rows": rows, "candidate": plan["candidate"]}
    text = "Table A. Held-out set: changed words of clean running text, and right cases per group.\n\n" + main_table(sets, rows) + "\n"

    sources = sorted({c["category"] for c in sets.lists})
    text += "Table B. Real misspellings per source, and non-word slips and all generated cases.\n\n" + table(
        ["Arm", f"github misspelling with a context /{sizes['github_misspelling_with_context']:,}",
         f"github misspelling without a context /{sizes['github_misspelling'] - sizes['github_misspelling_with_context']:,}",
         *[f"{source.replace('real_misspelling_', '')} /{sizes[source]}" for source in sources],
         f"non-word slips /{sizes['non_word_slips']:,}", f"generated, all /{sizes['generated']:,}", "changed stream sentences"],
        [[f"`{name}`", row["github_misspelling_with_context"], row["github_misspelling_without_context"], *[row[s] for s in sources],
          row["non_word_slips"], row["generated"], row["changed_sentences"]] for name, row in rows.items()]) + "\n"

    for name, row in rows.items():
        row["estimate"] = {f"s={s} r={r}": round(sets.estimate(row, s, r), 2) for s in SLIP_SHARES for r in REAL_WORD_SHARES}
    cells = [(s, 0.12) for s in SLIP_SHARES] + [(0.05, 0.05), (0.05, 0.30)]
    text += "Table C. Weighted estimate, wrong words per 1,000 typed. No rule uses it.\n\n" + table(
        ["Arm", *[f"s = {s}, r = {r}" for s, r in cells]],
        [[f"`{name}`", *[f"{row['estimate'][f's={s} r={r}']:.2f}" for s, r in cells]] for name, row in rows.items()]) + "\n"

    phrases, pairs = seen_flags(arguments.round1, arguments.data, sets.sets["generated"])
    with_context = [c for c in sets.sets["generated"] if c["context"] and c["typed"] != c["intended"]]
    seen_phrase = [c for c in with_context if tuple((c["context"] + " " + metrics2.normal(c["intended"])).split(" ")) in phrases]
    new_phrase = [c for c in with_context if tuple((c["context"] + " " + metrics2.normal(c["intended"])).split(" ")) not in phrases]
    slips = [c for c in sets.sets["generated"] if c["typed"] != c["intended"]]
    seen_pair = [c for c in slips if (c["typed"], metrics2.normal(c["intended"])) in pairs]
    new_pair = [c for c in slips if (c["typed"], metrics2.normal(c["intended"])) not in pairs]
    real = sets.github_misspelling + sets.lists
    real_seen = [c for c in real if (c["typed"], c["intended"]) in pairs]
    real_new = [c for c in real if (c["typed"], c["intended"]) not in pairs]
    cuts = {"slip, phrase in training": seen_phrase, "slip, phrase not in training": new_phrase,
            "slip, pair in a training list": seen_pair, "slip, pair in no training list": new_pair,
            "real misspelling, pair in a training list": real_seen, "real misspelling, pair in no training list": real_new}
    result["seen"] = {label: {"cases": len(cases), **{name: arm.count(cases) for name, arm in arms.items()}} for label, cases in cuts.items()}
    text += "Table D. Right held-out cases by whether training holds the phrase or the pair.\n\n" + table(
        ["Arm", *[f"{label} /{len(cases):,}" for label, cases in cuts.items()]],
        [[f"`{name}`", *[arm.count(cases) for cases in cuts.values()]] for name, arm in arms.items()]) + "\n"

    model_rows = []
    for arm in plan["arms"]:
        entry = read["arms"][arm["name"]]["stream"].get("model")
        if entry is None:
            continue
        model_rows.append([f"`{arm['name']}`", arm["model"], f"{arm.get('bytes', 0):,}", entry["arms_sharing_the_scorer"], entry["requests"],
                           f"{entry['tokens_read'] / entry['requests']:.1f}", f"{entry['model_ms'] / entry['requests']:.1f}",
                           f"{entry['rss_anon_kb'] / 1024:.0f}"])
    text += ("Table E. Model file and cost on the held-out stream, in WSL with 2 threads. Arms of one file share one scorer, "
             "so their requests are counted together.\n\n") + table(
        ["Arm", "file", "bytes", "arms on the scorer", "requests", "tokens per request", "model ms per request", "highest RssAnon MiB"], model_rows) + "\n"

    control = arms["control"]
    decisions = {}
    if plan["candidate"] is not None:
        for reference in ("ship", plan["calibrated_ship"]):
            if reference == plan["candidate"]:
                continue
            decisions[reference] = replacement_conditions(sets, arms[plan["candidate"]], arms[reference], control)
        for reference, decision in decisions.items():
            text += f"Table F. The six conditions for `{plan['candidate']}` against `{reference}`.\n\n" + table(
                ["Condition", "holds"], [[name, "yes" if value else "no"] for name, value in decision["conditions"].items()])
            numbers = decision["numbers"]
            text += (f"\nSentences changed only by the reference: {numbers['sentences_changed_only_by_the_reference']}. "
                     f"Sentences changed only by the candidate: {numbers['sentences_changed_only_by_the_arm']}. "
                     f"One-sided exact McNemar p = {numbers['mcnemar_one_sided_p']:.3g}. "
                     f"Non-word slips: {numbers['non_word_difference']:+d}, interval {numbers['non_word_interval'][0]:+d} to {numbers['non_word_interval'][1]:+d}. "
                     f"Passes all six: {'yes' if decision['passes'] else 'no'}.\n\n")
    result["decisions"] = decisions
    # Every other arm against ship, for reading: the same six conditions.
    result["every_arm_against_ship"] = {name: replacement_conditions(sets, arm, arms["ship"], control)
                                        for name, arm in arms.items() if name not in ("ship", "control")}
    text += "Table G. The six conditions for every arm against `ship`, for reading. Only the candidate faces the rule.\n\n" + table(
        ["Arm", "1", "2", "3", "4", "5", "6", "changed sentences only ship / only arm", "p", "non-word difference (interval)"],
        [[f"`{name}`", *["yes" if v else "no" for v in d["conditions"].values()],
          f"{d['numbers']['sentences_changed_only_by_the_reference']} / {d['numbers']['sentences_changed_only_by_the_arm']}",
          f"{d['numbers']['mcnemar_one_sided_p']:.3g}",
          f"{d['numbers']['non_word_difference']:+d} ({d['numbers']['non_word_interval'][0]:+d} to {d['numbers']['non_word_interval'][1]:+d})"]
         for name, d in result["every_arm_against_ship"].items()]) + "\n"
    result["paired_against_ship"] = {name: paired_counts(sets, arm, arms["ship"]) for name, arm in arms.items() if name != "ship"}
    labels = list(next(iter(result["paired_against_ship"].values())))
    text += ("Table H. Cases that only the arm gets right, and cases that only `ship` gets right, per group. The p value is the "
             "two-sided exact McNemar test.\n\n") + table(
        ["Arm", *[f"{label}: only arm / only ship (p)" for label in labels]],
        [[f"`{name}`", *[f"{entry[label]['only_arm']} / {entry[label]['only_reference']} ({entry[label]['two_sided_p']:.3g})" for label in labels]]
         for name, entry in result["paired_against_ship"].items()]) + "\n"
    arguments.out.mkdir(parents=True, exist_ok=True)
    (arguments.out / "holdout-summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (arguments.out / "holdout-summary.md").write_text(text, encoding="utf-8")
    print(text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["pick", "holdout"])
    parser.add_argument("--round1", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--results", type=Path, help="pick: the folder of the evaluate2.py results")
    parser.add_argument("--ship", help="pick: FOLDER:LABEL of the predictions of ship")
    parser.add_argument("--arm", action="append", default=[], help="pick: FOLDER:LABEL of a candidate arm, in the order of Table 2")
    parser.add_argument("--read", type=Path, help="holdout: the folder of read_holdout.py")
    parser.add_argument("--plan", type=Path, help="holdout: holdout-plan.json")
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.mode == "pick":
        pick(arguments)
    else:
        holdout(arguments)


if __name__ == "__main__":
    main()
