"""Writes the tables of the domain round from the results of score_model.py, and applies its rules.

For every arm in build/lm-domain/results and every setting rule, the script gives the counts of
each evaluation set, beside the engine alone and the perfect chooser, with the share of the gap
closed. It then applies three rules of docs/lm-domain-design.md to the selection sets:
- the pick of one candidate (nine conditions against `ship`),
- the share rule of the third wave,
- the loss rule of the third wave.
The domain counts leave out the cases that audit_overlap.py marks, because a training case
holds their text. A second table shows the marked cases alone. The test half of the domain
cases is shown when an arm has its result-test.json, and it decides nothing. A held-out set is
never read here.

Outputs in --out: tables.md, and summary.json with every number of the tables.

Usage, from the repository root:
    python3 scripts/lm-domain/summarize3.py --results build/lm-domain/results --data build/lm-domain/data \
        --parity build/lm-domain/parity --out build/lm-domain/summary
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-domain"))
import harness  # noqa: E402
from domain_terms import is_withheld  # noqa: E402

RULES = ("shipped", "ceiling-0.3", "ceiling-0.2", "control-rule")
PICK_RULES = ("shipped", "ceiling-0.3", "ceiling-0.2")
# The pinned dev numbers of engine/lm-keyboard (scripts/lm-keyboard/compare.py, PUBLISHED).
PINNED = {"clean": 953, "letter_slips": 2057, "space_slips": 1387, "symbol_slips": 1165, "clean_symbols": 428, "all": 6542}
PRICE_CATEGORIES = ("neighbour_slip_onto_term", "requested_term_for_everyday_word")
TERM_SLIP_CATEGORIES = ("domain_slip_new", "domain_slip_raised", "capital_slip_lower", "capital_slip_deliberate",
                        "capital_slip_sentence_start", "term_space_extra", "term_letter_to_space")
# The order of the arms in every table: the order of Table 5 of the design.
ORDER = ["ship", "full-mix-seed1", "mix-hinge-seed1", "mix-seed1", "mix-seed2", "mix-seed3", "soup-mix", "soup-r1", "ce-c1-seed1", "dom-s0-seed1", "dom-s0-seed2",
         "ce-c4-seed1", "ce-c4-seed2", "ec-c4-seed1", "ec-c4-seed2", "dom-s15-seed1", "dom-s40-seed1", "dom-s100-seed1"]
SHARES = {"dom-s15-seed1": "0.15", "dom-s40-seed1": "0.4", "dom-s100-seed1": "1.0"}
LOSS_MINIMUM_GAIN = 10


def read_outputs(path: Path) -> dict[str, dict[str, str]]:
    outputs: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8") as file:
        for line in file:
            row = json.loads(line)
            outputs.setdefault(row["set"], {})[row["id"]] = row["output"]
    return outputs


def domain_counts(cases: list[dict], outputs: dict[str, str], requested: set[str], marked: set[str]) -> dict:
    """Counts of one domain case set as [right, cases]. `all`, the groups and the pools leave the
    marked cases out, and `marked` holds the marked cases alone. The pools: `clean` for a case
    whose typed letters are its intended letters, `slips` for a slip case outside the price
    categories, `price` for those, `required` for the group of the requested words, and the
    slips of pack words by the way the training treated the word."""
    counts = {name: [0, 0] for name in ("all", "marked", "clean", "slips", "price", "required", "slips_trained_words",
                                         "slips_withheld_words", "slips_requested_words")}
    groups: dict[str, list[int]] = {}
    for case in cases:
        right = int(harness.is_right(case, outputs[case["id"]]))
        if case["id"] in marked:
            names = ["marked"]
        else:
            names = ["all"]
            group = groups.setdefault(case["group"], [0, 0])
            group[0] += right
            group[1] += 1
            if case["group"] == "required":
                names.append("required")
            if case["typed"].lower() == case["intended"].lower():
                names.append("clean")
            elif case["category"] in PRICE_CATEGORIES:
                names.append("price")
            else:
                names.append("slips")
                term = case.get("term")
                if term in requested:
                    names.append("slips_requested_words")
                elif case["category"] in TERM_SLIP_CATEGORIES:
                    names.append("slips_withheld_words" if is_withheld(term) else "slips_trained_words")
        for name in names:
            counts[name][0] += right
            counts[name][1] += 1
    counts["groups"] = groups
    return counts


def stream_counts(cases: list[dict], outputs: dict[str, str], marked: set[str]) -> dict:
    """Changed words per stream of a domain stream set, without the marked sentences, and the
    changed words of the marked sentences alone."""
    counts: dict[str, list[int]] = {}
    for case in cases:
        name = "marked" if case["id"] in marked else case["stream"]
        entry = counts.setdefault(name, [0, 0])
        entry[0] += harness.changed_words(case, outputs[case["id"]])
        entry[1] += len(case["intended"].split())
    counts.setdefault("marked", [0, 0])
    counts["technical_written"] = [counts["technical"][0] + counts["written"][0], counts["technical"][1] + counts["written"][1]]
    return counts


def select_metrics(sets: dict, summaries: dict, outputs: dict, requested: set[str], marked: dict) -> dict:
    """The numbers of one arm at one setting on the selection sets."""
    dev = summaries["dev"]
    github = summaries["github_select"]["categories"]
    metrics = {
        "dev_right": dev["right"], "dev_groups": {name: value[0] for name, value in dev["groups"].items()},
        "dev_non_word_slips": dev["non_word_slips"][0],
        "apostrophe_word": summaries["apostrophe_word"]["right"], "apostrophe_next_word": summaries["apostrophe_next_word"]["right"],
        "published_dev": summaries["published_dev"]["right"],
        "github_misspelling": github["github_misspelling"][0], "github_real_word": github["github_real_word"][0],
        "stream_select_changed": summaries["stream_select"]["changed_words"],
        "domain_dev": domain_counts(sets["domain_dev"]["cases"], outputs["domain_dev"], requested, set(marked["domain_dev"])),
        "domain_stream_dev": stream_counts(sets["domain_stream_dev"]["cases"], outputs["domain_stream_dev"], set(marked["domain_stream_dev"])),
    }
    metrics["real_misspellings"] = metrics["published_dev"] + metrics["github_misspelling"]
    return metrics


def test_metrics(sets: dict, outputs: dict, requested: set[str], marked: dict) -> dict:
    return {"domain_test": domain_counts(sets["domain_test"]["cases"], outputs["domain_test"], requested, set(marked["domain_test"])),
            "domain_stream_test": stream_counts(sets["domain_stream_test"]["cases"], outputs["domain_stream_test"],
                                                set(marked["domain_stream_test"]))}


def pick_conditions(entry: dict, ship: dict, engine: dict, parity_passes: bool | None) -> dict:
    """The nine conditions of the pick, each True or False. `parity_passes` is None for a file
    without a parity result, and the condition then does not hold."""
    dev, ship_dev = entry["dev_groups"], ship["dev_groups"]
    domain, ship_domain = entry["domain_dev"], ship["domain_dev"]
    gain = ship_dev["real_word_slip"] - engine["dev_groups"]["real_word_slip"]
    pinned = all(dev[name] >= count for name, count in PINNED.items() if name != "all") and entry["dev_right"] >= PINNED["all"]
    return {
        "1 select stream": entry["stream_select_changed"] <= ship["stream_select_changed"],
        "2 dev clean": dev["clean"] >= ship_dev["clean"] and dev["clean_symbols"] >= ship_dev["clean_symbols"],
        "3 real misspellings": entry["real_misspellings"] >= ship["real_misspellings"],
        "4 non-word slips": entry["dev_non_word_slips"] >= ship["dev_non_word_slips"] - 25,
        "5 real-word slips": dev["real_word_slip"] - engine["dev_groups"]["real_word_slip"] >= gain / 2,
        "6 pinned dev counts": pinned,
        "7 domain dev": domain["clean"][0] >= ship_domain["clean"][0]
        and domain["slips"][0] >= ship_domain["slips"][0] - 0.005 * ship_domain["slips"][1]
        and domain["required"][0] >= ship_domain["required"][0] - 0.01 * ship_domain["required"][1],
        "8 apostrophe words": entry["apostrophe_word"] >= ship["apostrophe_word"] - 8
        and entry["apostrophe_next_word"] >= ship["apostrophe_next_word"] - 8,
        "9 parity": parity_passes is True,
    }


def parity_of(folder: Path, arm: str, name: str = "parity.json") -> dict | None:
    """The parity results of an arm, or None for an arm without both of them."""
    found = {}
    for lists in ("everyday", "domain"):
        path = folder / arm / lists / name
        if not path.exists():
            return None
        report = json.loads(path.read_text(encoding="utf-8"))
        found[lists] = {"token_mismatches": report["token_mismatches"],
                        "largest_log_probability_difference": round(report["largest_log_probability_difference"], 4),
                        "largest_space_after_difference": round(report["largest_space_after_difference"], 4)}
    found["passes"] = all(entry["token_mismatches"] == 0 and max(entry["largest_log_probability_difference"],
                                                                 entry["largest_space_after_difference"]) <= 0.05
                          for entry in (found["everyday"], found["domain"]))
    return found


def third_wave(arms: dict, ship: dict, engine: dict) -> dict:
    """The share rule and the loss rule of the design. A rule that still waits for an arm says so."""
    wave: dict = {}
    missing = [arm for arm in SHARES if arm not in arms]
    if missing:
        wave["share"] = {"waits_for": missing}
    else:
        rows = []
        for arm, share in SHARES.items():
            metrics = arms[arm]["rules"]["shipped"]
            conditions = pick_conditions(metrics, ship, engine, None)
            rows.append({"arm": arm, "share": share, "passes_conditions_1_to_5": all(list(conditions.values())[:5]),
                         "technical_written_changed": metrics["domain_stream_dev"]["technical_written"][0]})
        passing = [row for row in rows if row["passes_conditions_1_to_5"]] or rows
        wave["share"] = {"rows": rows, "picked": min(passing, key=lambda row: (row["technical_written_changed"], float(row["share"])))["share"]}

    def score(arm: str) -> tuple[int, int] | None:
        metrics = arms.get(arm, {}).get("rules", {}).get("ceiling-0.3")
        return None if metrics is None else (metrics["dev_right"] + metrics["real_misspellings"], metrics["stream_select_changed"])

    bases = {seed: score(f"dom-s0-seed{seed}") for seed in (1, 2)}
    if any(arm not in arms for arm in ("dom-s0-seed1", "dom-s0-seed2", "ce-c4-seed1", "ce-c4-seed2", "ec-c4-seed1", "ec-c4-seed2")):
        wave["loss"] = {"waits_for": [arm for arm in ("dom-s0-seed1", "dom-s0-seed2", "ce-c4-seed1", "ce-c4-seed2", "ec-c4-seed1",
                                                      "ec-c4-seed2") if arm not in arms]}
    else:
        rows = []
        for loss in ("ce-c4", "ec-c4"):
            pairs = [(score(f"{loss}-seed{seed}"), bases[seed]) for seed in (1, 2)]
            helps = all(mine is not None and base is not None and mine[0] >= base[0] + LOSS_MINIMUM_GAIN and mine[1] <= base[1]
                        for mine, base in pairs)
            scores = [mine[0] for mine, _ in pairs if mine is not None]
            rows.append({"loss": loss, "pairs_of_loss_and_base": pairs, "helps": helps,
                         "mean_score": sum(scores) / len(scores) if scores else None})
        helping = [row for row in rows if row["helps"]]
        wave["loss"] = {"rows": rows,
                        "picked": max(helping, key=lambda row: (row["mean_score"], row["loss"] == "ce-c4"))["loss"] if helping else None}
    return wave


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--parity", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--parity-name", default="parity.json",
                        help="parity.json for the f16 file of check_parity.py, or parity-f32.json of parity_report.py")
    arguments = parser.parse_args()
    select_sets = harness.load_sets(arguments.data, "select")
    test_sets = harness.load_sets(arguments.data, "test")
    marked = json.loads((arguments.data / "overlap.json").read_text(encoding="utf-8"))["marked"]
    requested = {line.split("\t")[0] for line in (ROOT / "scripts" / "domain-pack" / "pack" / "required-terms.tsv")
                 .read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")} - {"word"}
    found = sorted(path.parent.name for path in arguments.results.glob("*/result.json"))
    names = [arm for arm in ORDER if arm in found] + [arm for arm in found if arm not in ORDER]
    if "ship" not in names:
        raise SystemExit("the results hold no arm `ship`")
    summary: dict = {"parity_file": arguments.parity_name, "arms": {}, "marked_cases": {name: len(ids) for name, ids in marked.items()}}
    engine = perfect = None
    engine_test = perfect_test = None
    for arm in names:
        folder = arguments.results / arm
        result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
        if "evaluation" not in result:
            continue
        if engine is None:
            engine = select_metrics(select_sets, result["engine"]["evaluation"], read_outputs(folder / "outputs.select.engine.jsonl"), requested, marked)
            perfect = select_metrics(select_sets, result["perfect"]["evaluation"], read_outputs(folder / "outputs.select.perfect.jsonl"), requested, marked)
        entry = {"model_sha256": result["model_sha256"], "parity": parity_of(arguments.parity, arm, arguments.parity_name), "rules": {}, "test": None}
        for rule in RULES:
            evaluation = result["evaluation"][rule]
            tuning = result["tuning"]["rules"][rule]
            if evaluation is None:
                entry["rules"][rule] = None
                continue
            source = evaluation.get("same_setting_as", rule)
            metrics = select_metrics(select_sets, result["evaluation"][source]["sets"], read_outputs(folder / f"outputs.select.{source}.jsonl"),
                                     requested, marked)
            entry["rules"][rule] = {"setting": tuning["setting"], "same_setting_as": source if source != rule else None,
                                    "tune_right": tuning["tune_right"], "tune_changed_words": tuning["tune_changed_words"], **metrics}
        free = read_outputs(folder / "outputs.select.shipped-unprotected.jsonl")
        entry["unprotected_at_the_shipped_setting"] = {
            "domain_dev": domain_counts(select_sets["domain_dev"]["cases"], free["domain_dev"], requested, set(marked["domain_dev"])),
            "domain_stream_dev": stream_counts(select_sets["domain_stream_dev"]["cases"], free["domain_stream_dev"], set(marked["domain_stream_dev"]))}
        if (folder / "result-test.json").exists():
            test_result = json.loads((folder / "result-test.json").read_text(encoding="utf-8"))
            if engine_test is None:
                engine_test = test_metrics(test_sets, read_outputs(folder / "outputs.test.engine.jsonl"), requested, marked)
                perfect_test = test_metrics(test_sets, read_outputs(folder / "outputs.test.perfect.jsonl"), requested, marked)
            entry["test"] = {}
            for rule in RULES:
                evaluation = test_result["evaluation"][rule]
                if evaluation is None:
                    entry["test"][rule] = None
                    continue
                source = evaluation.get("same_setting_as", rule)
                entry["test"][rule] = test_metrics(test_sets, read_outputs(folder / f"outputs.test.{source}.jsonl"), requested, marked)
        summary["arms"][arm] = entry
    summary.update({"engine": engine, "perfect": perfect, "engine_test": engine_test, "perfect_test": perfect_test})
    ship = summary["arms"]["ship"]["rules"]["shipped"]

    # ---- The pick: every file at every pick rule, except the reference itself ----
    entries = []
    for arm, entry in summary["arms"].items():
        for rule in PICK_RULES:
            metrics = entry["rules"][rule]
            if metrics is None or metrics["same_setting_as"] in PICK_RULES[:PICK_RULES.index(rule)] or (arm == "ship" and rule == "shipped"):
                continue
            parity = entry["parity"]["passes"] if entry["parity"] is not None else None
            conditions = pick_conditions(metrics, ship, engine, parity)
            entries.append({"arm": arm, "rule": rule, "conditions": conditions, "qualifies": all(conditions.values()),
                            "technical_written_changed": metrics["domain_stream_dev"]["technical_written"][0],
                            "domain_dev_right": metrics["domain_dev"]["all"][0], "stream_select_changed": metrics["stream_select_changed"]})
    order = {arm: place for place, arm in enumerate(names)}
    qualified = sorted((entry for entry in entries if entry["qualifies"]),
                       key=lambda e: (e["technical_written_changed"], -e["domain_dev_right"], e["stream_select_changed"], order[e["arm"]]))
    summary["pick"] = {"entries": entries, "candidate": qualified[0] if qualified else None}
    summary["third_wave"] = third_wave(summary["arms"], ship, engine)

    arguments.out.mkdir(parents=True, exist_ok=True)
    (arguments.out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    text = tables(summary)
    (arguments.out / "tables.md").write_text(text, encoding="utf-8", newline="\n")
    print(text)


def share(got: float, low: float, high: float) -> str:
    return "n/a" if high == low else f"{100 * (got - low) / (high - low):.0f}%"


def cell(pair: list[int]) -> str:
    return f"{pair[0]}/{pair[1]}"


def tables(summary: dict) -> str:
    engine, perfect = summary["engine"], summary["perfect"]
    lines = [f"Cases that a training or tuning case shares text with, left out of the domain counts: {json.dumps(summary['marked_cases'])}", ""]

    def row(name: str, metrics: dict, setting: str) -> str:
        domain, stream = metrics["domain_dev"], metrics["domain_stream_dev"]
        return ("| " + " | ".join([
            name, setting, str(metrics["dev_right"]), str(metrics["dev_groups"]["clean"]), str(metrics["dev_groups"]["clean_symbols"]),
            str(metrics["dev_non_word_slips"]), str(metrics["dev_groups"]["real_word_slip"]),
            f"{metrics['apostrophe_word']}, {metrics['apostrophe_next_word']}", str(metrics["published_dev"]),
            str(metrics["github_misspelling"]), str(metrics["github_real_word"]), str(metrics["stream_select_changed"]),
            cell(domain["all"]), cell(domain["clean"]), cell(domain["slips"]), cell(domain["required"]),
            str(stream["technical"][0]), str(stream["written"][0]), str(stream["everyday"][0])]) + " |")

    for rule in RULES:
        lines += [f"Table. Every arm on the selection sets at the setting of the rule `{rule}`. A changed count is changed correct words, and lower is better.",
                  "",
                  "| Arm | setting weight/from/to/other/space | dev /6,799 | dev clean /973 | dev clean symbols /429 | dev non-word slips /5,097 "
                  "| dev real-word slips /300 | apostrophe word, next word /1,623 | published /751 | github misspelling /1,500 "
                  "| github real word /1,000 | select stream changed /8,439 | domain dev right | domain dev clean | domain dev slips "
                  "| domain dev requested words | technical changed | written changed | everyday changed |",
                  "| --- |" + " --- |" * 18]
        lines.append(row("`engine`", engine, ""))
        lines.append(row("`perfect`", perfect, ""))
        for arm, entry in summary["arms"].items():
            metrics = entry["rules"][rule]
            if metrics is None:
                lines.append(f"| `{arm}` | no setting passes the rule |" + " |" * 17)
                continue
            s = metrics["setting"]
            setting = f"{s['weight']:g}/{s['margin_from_typed']:g}/{s['margin_to_typed']:g}/{s['margin_other']:g}/{s['space_after']}"
            lines.append(row(f"`{arm}`", metrics, setting))
        lines += ["", f"Table. Share of the gap between the engine alone and the perfect chooser that each arm closes, at the rule `{rule}`.",
                  "",
                  "| Arm | dev | published | github misspelling | github real word | select stream | domain dev | technical and written streams |",
                  "| --- |" + " --- |" * 7]
        for arm, entry in summary["arms"].items():
            metrics = entry["rules"][rule]
            if metrics is None:
                continue
            cells = [share(metrics[key], engine[key], perfect[key]) for key in ("dev_right", "published_dev", "github_misspelling", "github_real_word")]
            cells.append(share(-metrics["stream_select_changed"], -engine["stream_select_changed"], -perfect["stream_select_changed"]))
            cells.append(share(metrics["domain_dev"]["all"][0], engine["domain_dev"]["all"][0], perfect["domain_dev"]["all"][0]))
            cells.append(share(-metrics["domain_stream_dev"]["technical_written"][0], -engine["domain_stream_dev"]["technical_written"][0],
                               -perfect["domain_stream_dev"]["technical_written"][0]))
            lines.append(f"| `{arm}` | " + " | ".join(cells) + " |")
        lines.append("")

    lines += ["Table. Domain dev half at the shipped setting: slips of pack words by the way the training of this round treated the word, "
              "the price cases, the cases that share text with training, and the right cases without the protection of a typed new word.", "",
              "| Arm | words with slip cases in training | withheld words | requested words | price cases | marked cases | right without the protection "
              "| technical and written changed without the protection |", "| --- |" + " --- |" * 7]
    for name, metrics, free in [("`engine`", engine, None), ("`perfect`", perfect, None)] + [
            (f"`{arm}`", entry["rules"]["shipped"], entry["unprotected_at_the_shipped_setting"]) for arm, entry in summary["arms"].items()]:
        domain = metrics["domain_dev"]
        lines.append(f"| {name} | " + " | ".join(cell(domain[key]) for key in ("slips_trained_words", "slips_withheld_words",
                                                                              "slips_requested_words", "price", "marked"))
                     + f" | {cell(free['domain_dev']['all']) if free else ''} | {free['domain_stream_dev']['technical_written'][0] if free else ''} |")
    lines.append("")

    if summary["engine_test"] is not None:
        lines += ["Table. Test half of the domain cases, per setting rule. It decides nothing.", "",
                  "| Arm | rule | right | clean | slips | requested words | technical changed | written changed | everyday changed |",
                  "| --- |" + " --- |" * 8]

        def test_row(name: str, rule: str, metrics: dict) -> str:
            domain, stream = metrics["domain_test"], metrics["domain_stream_test"]
            return (f"| {name} | {rule} | " + " | ".join([cell(domain["all"]), cell(domain["clean"]), cell(domain["slips"]), cell(domain["required"]),
                                                          str(stream["technical"][0]), str(stream["written"][0]), str(stream["everyday"][0])]) + " |")
        lines.append(test_row("`engine`", "", summary["engine_test"]))
        lines.append(test_row("`perfect`", "", summary["perfect_test"]))
        for arm, entry in summary["arms"].items():
            for rule in PICK_RULES:
                if entry["test"] and entry["test"].get(rule):
                    lines.append(test_row(f"`{arm}`", f"`{rule}`", entry["test"][rule]))
        lines.append("")

    lines += ["Table. Conditions of the pick per entry. Condition 9 holds only for a file with a parity result under the limit.", "",
              "| Arm | rule | " + " | ".join(["1 select stream", "2 dev clean", "3 real misspellings", "4 non-word slips", "5 real-word slips",
                                           "6 pinned dev counts", "7 domain dev", "8 apostrophe words", "9 parity"])
              + " | qualifies | technical and written changed |", "| --- |" + " --- |" * 12]
    for entry in summary["pick"]["entries"]:
        lines.append(f"| `{entry['arm']}` | `{entry['rule']}` | " + " | ".join("yes" if value else "no" for value in entry["conditions"].values())
                     + f" | {'yes' if entry['qualifies'] else 'no'} | {entry['technical_written_changed']} |")
    candidate = summary["pick"]["candidate"]
    lines += ["", "Candidate: " + (f"`{candidate['arm']}` at `{candidate['rule']}`" if candidate else "none"), ""]
    lines += ["Third wave: " + json.dumps(summary["third_wave"]), ""]
    lines += [f"Table. Parity from {summary['parity_file']}: largest difference between PyTorch and lm_score in nats, limit 0.05.", "",
              "| Arm | everyday lists, log probability | everyday lists, space | domain lists, log probability | domain lists, space | token mismatches | passes |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for arm, entry in summary["arms"].items():
        parity = entry["parity"]
        if parity is None:
            lines.append(f"| `{arm}` | not measured | | | | | no |")
        else:
            lines.append(f"| `{arm}` | {parity['everyday']['largest_log_probability_difference']} | {parity['everyday']['largest_space_after_difference']} "
                         f"| {parity['domain']['largest_log_probability_difference']} | {parity['domain']['largest_space_after_difference']} "
                         f"| {parity['everyday']['token_mismatches'] + parity['domain']['token_mismatches']} | {'yes' if parity['passes'] else 'no'} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
