"""Writes the tables of the domain round from the results of score_model.py, and applies its rules.

For every arm in build/lm-domain/results and every setting rule, the script gives the counts of
each evaluation set, beside the engine alone and the perfect chooser, with the share of the gap
closed. It then applies three rules of docs/lm-domain-design.md to the selection sets:
- the pick of one candidate (eight conditions against `ship`),
- the share rule of the third wave,
- the loss rule of the third wave.
The domain test half is shown and decides nothing. A held-out set is never read here.

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
PRICE_GROUPS = ("term_for_everyday_word",)
PRICE_CATEGORIES = ("neighbour_slip_onto_term", "requested_term_for_everyday_word")
REFERENCE_ARMS = ("ship", "mix-seed1", "mix-seed2", "mix-seed3", "engine")
SHARES = {"dom-s15-seed1": "0.15", "dom-s40-seed1": "0.4", "dom-s100-seed1": "1.0"}
LOSS_ARMS = {"ce-c4": ("ce-c4-seed1", "ce-c4-seed2"), "ec-c4": ("ec-c4-seed1", "ec-c4-seed2")}


def read_outputs(path: Path) -> dict[str, dict[str, str]]:
    outputs: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8") as file:
        for line in file:
            row = json.loads(line)
            outputs.setdefault(row["set"], {})[row["id"]] = row["output"]
    return outputs


def domain_pools(cases: list[dict], outputs: dict[str, str], requested: set[str]) -> dict:
    """Pooled counts of a domain case set: the clean cases (the typed text is the intended
    text), the slip cases outside the price categories, and the slips of words by the way the
    training treated the word: with slip cases, withheld, or a requested word."""
    pools = {name: [0, 0] for name in ("clean", "slips", "slips_trained_words", "slips_withheld_words", "slips_requested_words", "price")}
    for case in cases:
        right = int(harness.is_right(case, outputs[case["id"]]))
        if case["typed"] == case["intended"]:
            names = ["clean"]
        elif case["group"] in PRICE_GROUPS or case["category"] in PRICE_CATEGORIES:
            names = ["price"]
        else:
            names = ["slips"]
            term = case.get("term")
            if case["category"] in ("domain_slip_new", "domain_slip_raised", "capital_slip_lower", "capital_slip_deliberate",
                                    "capital_slip_sentence_start", "term_space_extra", "term_letter_to_space"):
                names.append("slips_withheld_words" if is_withheld(term) else "slips_trained_words")
            elif term in requested and case["category"].startswith("required_slip"):
                names.append("slips_requested_words")
        for name in names:
            pools[name][0] += right
            pools[name][1] += 1
    return pools


def metrics_of(sets: dict, summaries: dict, outputs: dict, requested: set[str]) -> dict:
    """The numbers of one arm at one setting that the tables and the rules use."""
    dev = summaries["dev"]
    github = summaries["github_select"]["categories"]
    metrics = {
        "dev_right": dev["right"], "dev_groups": {name: value[0] for name, value in dev["groups"].items()},
        "dev_non_word_slips": dev["non_word_slips"][0],
        "apostrophe_word": summaries["apostrophe_word"]["right"], "apostrophe_next_word": summaries["apostrophe_next_word"]["right"],
        "published_dev": summaries["published_dev"]["right"],
        "github_misspelling": github["github_misspelling"][0], "github_real_word": github["github_real_word"][0],
        "stream_select_changed": summaries["stream_select"]["changed_words"],
    }
    metrics["real_misspellings"] = metrics["published_dev"] + metrics["github_misspelling"]
    for half in ("dev", "test"):
        name = f"domain_{half}"
        metrics[f"{name}_right"] = summaries[name]["right"]
        metrics[f"{name}_groups"] = {group: value[0] for group, value in summaries[name]["groups"].items()}
        metrics[f"{name}_pools"] = domain_pools(sets[name]["cases"], outputs[name], requested)
        streams = summaries[f"domain_stream_{half}"]["streams"]
        metrics[f"{name}_stream"] = {kind: entry["changed_words"] for kind, entry in streams.items()}
        metrics[f"{name}_technical_written_changed"] = streams["technical"]["changed_words"] + streams["written"]["changed_words"]
    return metrics


def pick_conditions(entry: dict, ship: dict, engine: dict, parity_passes: bool | None) -> dict:
    """The eight conditions of the pick, each True or False."""
    dev, ship_dev = entry["dev_groups"], ship["dev_groups"]
    pools, ship_pools = entry["domain_dev_pools"], ship["domain_dev_pools"]
    gain = ship_dev["real_word_slip"] - engine["dev_groups"]["real_word_slip"]
    pinned = all(dev[name] >= count for name, count in PINNED.items() if name != "all") and entry["dev_right"] >= PINNED["all"]
    return {
        "1 select stream": entry["stream_select_changed"] <= ship["stream_select_changed"],
        "2 dev clean": dev["clean"] >= ship_dev["clean"] and dev["clean_symbols"] >= ship_dev["clean_symbols"],
        "3 real misspellings": entry["real_misspellings"] >= ship["real_misspellings"],
        "4 non-word slips": entry["dev_non_word_slips"] >= ship["dev_non_word_slips"] - 25,
        "5 real-word slips": dev["real_word_slip"] - engine["dev_groups"]["real_word_slip"] >= gain / 2,
        "6 pinned dev counts": pinned,
        "7 domain dev": pools["clean"][0] >= ship_pools["clean"][0]
        and pools["slips"][0] >= ship_pools["slips"][0] - 0.005 * ship_pools["slips"][1],
        "8 parity": parity_passes is not False,
    }


def parity_of(folder: Path, arm: str) -> dict | None:
    """The parity results of an arm of this round, or None for an arm without them."""
    found = {}
    for lists in ("everyday", "domain"):
        path = folder / arm / lists / "parity.json"
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--parity", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    sets = harness.load_sets(arguments.data, "evaluation")
    requested = {line.split("\t")[0] for line in (ROOT / "scripts" / "domain-pack" / "pack" / "required-terms.tsv")
                 .read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")} - {"word"}
    arms = sorted(path.parent.name for path in arguments.results.glob("*/result.json"))
    if "ship" not in arms:
        raise SystemExit("the results hold no arm `ship`")
    summary = {"arms": {}, "sets": {name: len(entry["cases"]) for name, entry in sets.items()}}
    engine = perfect = None
    for arm in arms:
        folder = arguments.results / arm
        result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
        if "evaluation" not in result:
            continue
        if engine is None:
            engine = metrics_of(sets, result["engine"]["evaluation"], read_outputs(folder / "outputs.engine.jsonl"), requested)
            perfect = metrics_of(sets, result["perfect"]["evaluation"], read_outputs(folder / "outputs.perfect.jsonl"), requested)
        entry = {"model_sha256": result["model_sha256"], "parity": parity_of(arguments.parity, arm), "rules": {}}
        for rule in RULES:
            evaluation = result["evaluation"][rule]
            tuning = result["tuning"]["rules"][rule]
            if evaluation is None:
                entry["rules"][rule] = None
                continue
            source = evaluation.get("same_setting_as", rule)
            evaluation = result["evaluation"][source]
            metrics = metrics_of(sets, evaluation["sets"], read_outputs(folder / f"outputs.{source}.jsonl"), requested)
            entry["rules"][rule] = {"setting": tuning["setting"], "same_setting_as": source if source != rule else None,
                                    "tune_right": tuning["tune_right"], "tune_changed_words": tuning["tune_changed_words"], **metrics}
        unprotected = result["unprotected"]["shipped"]
        entry["unprotected_at_the_shipped_setting"] = {
            name: (unprotected[name]["changed_words"] if "changed_words" in unprotected[name] else
                   {"right": unprotected[name]["right"], "groups": {g: v[0] for g, v in unprotected[name]["groups"].items()}})
            for name in unprotected}
        summary["arms"][arm] = entry
    summary["engine"], summary["perfect"] = engine, perfect
    ship = summary["arms"]["ship"]["rules"]["shipped"]

    # ---- The pick ----
    entries = []
    for arm, entry in summary["arms"].items():
        if arm in REFERENCE_ARMS:
            continue
        for rule in PICK_RULES:
            metrics = entry["rules"][rule]
            if metrics is None or metrics["same_setting_as"] in PICK_RULES[:PICK_RULES.index(rule)]:
                continue
            parity = entry["parity"]["passes"] if entry["parity"] is not None else None
            conditions = pick_conditions(metrics, ship, engine, parity)
            entries.append({"arm": arm, "rule": rule, "conditions": conditions, "qualifies": all(conditions.values()),
                            "technical_written_changed": metrics["domain_dev_technical_written_changed"],
                            "domain_dev_right": metrics["domain_dev_right"], "stream_select_changed": metrics["stream_select_changed"]})
    qualified = [entry for entry in entries if entry["qualifies"]]
    qualified.sort(key=lambda e: (e["technical_written_changed"], -e["domain_dev_right"], e["stream_select_changed"], e["arm"]))
    summary["pick"] = {"entries": entries, "candidate": qualified[0] if qualified else None}

    # ---- The rules of the third wave ----
    wave = {}
    shares = []
    for arm, share in SHARES.items():
        if arm in summary["arms"]:
            metrics = summary["arms"][arm]["rules"]["shipped"]
            conditions = pick_conditions(metrics, ship, engine, None)
            passes = all(conditions[name] for name in list(conditions)[:5])
            shares.append({"arm": arm, "share": share, "passes_conditions_1_to_5": passes,
                           "technical_written_changed": metrics["domain_dev_technical_written_changed"]})
    if len(shares) == len(SHARES):
        passing = [row for row in shares if row["passes_conditions_1_to_5"]] or shares
        wave["share"] = {"rows": shares, "picked": min(passing, key=lambda row: (row["technical_written_changed"], float(row["share"])))["share"]}
    if "ce-c1-seed1" in summary["arms"] and all(arm in summary["arms"] for members in LOSS_ARMS.values() for arm in members):
        def score(arm: str) -> tuple[float, float]:
            metrics = summary["arms"][arm]["rules"]["ceiling-0.3"]
            return metrics["dev_right"] + metrics["real_misspellings"], metrics["stream_select_changed"]
        base_score, base_changed = score("ce-c1-seed1")
        rows = []
        for loss, members in LOSS_ARMS.items():
            scores = [score(arm) for arm in members]
            mean_score = sum(value[0] for value in scores) / len(scores)
            mean_changed = sum(value[1] for value in scores) / len(scores)
            rows.append({"loss": loss, "score": mean_score, "changed": mean_changed,
                         "helps": mean_score > base_score and mean_changed <= base_changed})
        helping = [row for row in rows if row["helps"]]
        wave["loss"] = {"base": {"score": base_score, "changed": base_changed}, "rows": rows,
                        "picked": max(helping, key=lambda row: (row["score"], row["loss"] == "ce-c4"))["loss"] if helping else None}
    summary["third_wave"] = wave

    arguments.out.mkdir(parents=True, exist_ok=True)
    (arguments.out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    (arguments.out / "tables.md").write_text(tables(summary), encoding="utf-8", newline="\n")
    print(tables(summary))


def share(got: float, low: float, high: float) -> str:
    return "n/a" if high == low else f"{100 * (got - low) / (high - low):.0f}%"


def tables(summary: dict) -> str:
    engine, perfect = summary["engine"], summary["perfect"]
    lines = []

    def pool(metrics: dict, half: str, name: str) -> str:
        right, cases = metrics[f"domain_{half}_pools"][name]
        return f"{right}/{cases}"

    for rule in RULES:
        lines += [f"Table. Every arm at the setting of the rule `{rule}`. Changed words are counts of changed correct words, and lower is better.",
                  "",
                  "| Arm | setting w/from/to/other/space | dev /6,799 | dev clean | dev clean symbols | dev non-word slips | dev real-word slips "
                  "| apostrophe word, next word | published /751 | github misspelling /1,500 | github real word /1,000 | select stream changed /8,439 "
                  "| domain dev right | domain dev clean | domain dev slips | domain dev technical+written changed | domain dev everyday changed "
                  "| domain test right | domain test clean | domain test slips | domain test technical+written changed |",
                  "| --- |" + " --- |" * 20]

        def row(name: str, metrics: dict, setting: str) -> str:
            return ("| " + " | ".join([
                name, setting, str(metrics["dev_right"]), str(metrics["dev_groups"]["clean"]), str(metrics["dev_groups"]["clean_symbols"]),
                str(metrics["dev_non_word_slips"]), str(metrics["dev_groups"]["real_word_slip"]),
                f"{metrics['apostrophe_word']}, {metrics['apostrophe_next_word']}", str(metrics["published_dev"]),
                str(metrics["github_misspelling"]), str(metrics["github_real_word"]), str(metrics["stream_select_changed"]),
                str(metrics["domain_dev_right"]), pool(metrics, "dev", "clean"), pool(metrics, "dev", "slips"),
                str(metrics["domain_dev_technical_written_changed"]), str(metrics["domain_dev_stream"]["everyday"]),
                str(metrics["domain_test_right"]), pool(metrics, "test", "clean"), pool(metrics, "test", "slips"),
                str(metrics["domain_test_technical_written_changed"])]) + " |")

        lines.append(row("`engine`", engine, ""))
        lines.append(row("`perfect`", perfect, ""))
        for arm, entry in summary["arms"].items():
            metrics = entry["rules"][rule]
            if metrics is None:
                lines.append(f"| `{arm}` | no setting passes the rule |" + " |" * 19)
                continue
            s = metrics["setting"]
            setting = f"{s['weight']:g}/{s['margin_from_typed']:g}/{s['margin_to_typed']:g}/{s['margin_other']:g}/{s['space_after']}"
            lines.append(row(f"`{arm}`", metrics, setting))
        lines += ["", f"Table. Share of the gap between the engine alone and the perfect chooser that each arm closes, at the rule `{rule}`.",
                  "",
                  "| Arm | dev | published | github misspelling | github real word | select stream | domain dev | domain dev technical+written | domain test | domain test technical+written |",
                  "| --- |" + " --- |" * 9]
        for arm, entry in summary["arms"].items():
            metrics = entry["rules"][rule]
            if metrics is None:
                continue
            cells = [share(metrics[key], engine[key], perfect[key]) for key in ("dev_right", "published_dev", "github_misspelling", "github_real_word")]
            cells.append(share(-metrics["stream_select_changed"], -engine["stream_select_changed"], 0))
            for half in ("dev", "test"):
                cells.append(share(metrics[f"domain_{half}_right"], engine[f"domain_{half}_right"], perfect[f"domain_{half}_right"]))
                cells.append(share(-metrics[f"domain_{half}_technical_written_changed"], -engine[f"domain_{half}_technical_written_changed"], 0))
            lines.append(f"| `{arm}` | " + " | ".join(cells) + " |")
        lines.append("")

    lines += ["Table. Slips of pack words on the domain dev half at the shipped setting, by the way the training treated the word.", "",
              "| Arm | words with slip cases in training | withheld words | requested words | price cases |", "| --- | --- | --- | --- | --- |"]
    for name, metrics in [("`engine`", engine), ("`perfect`", perfect)] + [
            (f"`{arm}`", entry["rules"]["shipped"]) for arm, entry in summary["arms"].items()]:
        lines.append(f"| {name} | " + " | ".join(pool(metrics, "dev", key) for key in
                                                 ("slips_trained_words", "slips_withheld_words", "slips_requested_words", "price")) + " |")
    lines.append("")

    lines += ["Table. Conditions of the pick per entry.", "", "| Arm | rule | " + " | ".join(
        ["1 select stream", "2 dev clean", "3 real misspellings", "4 non-word slips", "5 real-word slips", "6 pinned dev counts",
         "7 domain dev", "8 parity"]) + " | qualifies | technical+written changed |", "| --- |" + " --- |" * 11]
    for entry in summary["pick"]["entries"]:
        lines.append(f"| `{entry['arm']}` | `{entry['rule']}` | " + " | ".join("yes" if value else "no" for value in entry["conditions"].values())
                     + f" | {'yes' if entry['qualifies'] else 'no'} | {entry['technical_written_changed']} |")
    candidate = summary["pick"]["candidate"]
    lines += ["", "Candidate: " + (f"`{candidate['arm']}` at `{candidate['rule']}`" if candidate else "none"), ""]
    lines += ["Third wave: " + json.dumps(summary["third_wave"]), ""]
    lines += ["Table. Parity of the arms of this round: largest difference between PyTorch and lm_score in nats, limit 0.05.", "",
              "| Arm | everyday lists, log probability | everyday lists, space | domain lists, log probability | domain lists, space | token mismatches | passes |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for arm, entry in summary["arms"].items():
        parity = entry["parity"]
        if parity is not None:
            lines.append(f"| `{arm}` | {parity['everyday']['largest_log_probability_difference']} | {parity['everyday']['largest_space_after_difference']} "
                         f"| {parity['domain']['largest_log_probability_difference']} | {parity['domain']['largest_space_after_difference']} "
                         f"| {parity['everyday']['token_mismatches'] + parity['domain']['token_mismatches']} | {'yes' if parity['passes'] else 'no'} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
