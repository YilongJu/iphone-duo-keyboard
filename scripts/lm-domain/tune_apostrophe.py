"""Tunes the lead of the apostrophe step for one scored file, per setting, and scores the file at it.

The keyboard's apostrophe step moves from the choice of the margins to a reading with other
apostrophes when that reading leads by `margin_apostrophe` in the stock prompt. The lead 4 was
picked for the shipped file (scripts/lm-rerank/apostrophe_words.py on engine/lm-keyboard). This
script picks the lead of any file by the same rule, with the work area on, for each setting
that score_model.py named (shipped, ceiling-0.3, ceiling-0.2):

- A lead of the grid 0.5 to 8 is allowed when every category of the generated dev half, and the
  two clean controls of the apostrophe words typed with the next word, keep at least the count
  of the same setting without the step.
- The allowed lead with the most right next-word cases wins. The first lead of the grid wins a tie.
- When no lead is allowed, the file keeps lead 4, and the result says so.

For a setting whose lead is not 4, the script types every selection set again at that lead.
It also measures the stock prompt alone: at each correction of a next-word case that has a
reading with other apostrophes, whether the step's score, in the stock prompt, is higher for
the intended form than for the other form.

The script writes OUT/apostrophe.json and OUT/outputs.select.RULE.own-lead.jsonl. Its answers
of lm_score come from and go to OUT/answers.jsonl.

Usage, from the repository root, on Linux:
    LD_LIBRARY_PATH=$HOME/lmft/llama/lib python3 scripts/lm-domain/tune_apostrophe.py --shim SHIM --lm LM_SCORE \
        --model MODEL.gguf --data build/lm-domain/data --out build/lm-domain/results/ARM
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-domain"))
import harness  # noqa: E402
import apostrophe_words  # noqa: E402
import rerank  # noqa: E402
import score_model  # noqa: E402
import select_setting  # noqa: E402

GRID = apostrophe_words.GRID
CONTROLS = apostrophe_words.CONTROLS
RULES = ("shipped", "ceiling-0.3", "ceiling-0.2")
SHIP_LEAD = harness.SHIPPED.margin_apostrophe


def setting_with(values: dict, lead: float | None) -> rerank.Setting:
    step = dict(harness.STEP, margin_apostrophe=lead)
    return rerank.Setting(**{name: values[name] for name in harness.GRID_FIELDS}, **step)


def stock_prompt_preference(typist: harness.Typist, cases: list[dict], values: dict, scorer) -> dict:
    """Among the corrections of the next-word cases that hold the intended form and another form
    of the same letters: how often the step's score in the stock prompt is higher for the
    intended form, and the mean lead of the intended form in nats."""
    setting = setting_with(values, None)
    step = setting_with(values, SHIP_LEAD)
    found = []
    for case in cases:
        target = ((case["context"] + " " if case["context"] else "") + case["intended"].strip() + " ").lower()

        def chooser(readings, text_before, typed=None):
            context = text_before.rstrip(" ")
            choice = rerank.choose(readings, context, setting, scorer, typed)
            as_typed = next(r for r in readings if r["as_typed"])
            forms = [as_typed] + [r for r in readings if not r["as_typed"] and rerank.is_twin(r["text"], as_typed["text"], step.apostrophe_scope)]
            intended = [r for r in forms if target.startswith(text_before.lower() + r["text"] + " ")]
            if len(forms) >= 2 and len(intended) == 1:
                scores = scorer.step_scores(context, [r["text"] for r in forms], step.apostrophe_prompt)

                def value(reading):
                    log_probability, space_after = scores[reading["text"]]
                    return log_probability + space_after - reading["slips"]
                best_other = max(value(r) for r in forms if r is not intended[0])
                found.append(value(intended[0]) - best_other)
            return choice

        typist.type(case, chooser)
    return {"corrections": len(found), "intended_form_scores_higher": sum(1 for lead in found if lead > 0),
            "intended_form_leads_by_4_or_more": sum(1 for lead in found if lead >= 4),
            "mean_lead_of_the_intended_form": round(sum(found) / len(found), 3) if found else None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--lm", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    if (arguments.out / "apostrophe.json").exists():
        raise SystemExit(f"{arguments.out} already holds apostrophe.json")
    started = time.monotonic()
    first = json.loads((arguments.out / "result.json").read_text(encoding="utf-8"))
    sets = harness.load_sets(arguments.data, "select")
    typist = harness.Typist(arguments.shim, readings_file=arguments.data / "engine-readings.pickle")
    scorer, stored, digest = harness.open_model(arguments.lm, arguments.model, arguments.threads, arguments.out / "answers.jsonl")
    if digest != first["model_sha256"]:
        raise SystemExit("the model file is not the file of result.json")
    tuning_sets = {name: sets[name] for name in ("dev", "apostrophe_word", "apostrophe_next_word")}
    result = {"model_sha256": digest, "grid": GRID, "rules": {}}
    done: list[tuple[dict, str]] = []
    for rule in RULES:
        values = first["tuning"]["rules"][rule]["setting"]
        if values is None:
            result["rules"][rule] = None
            continue
        earlier = next((name for other, name in done if select_setting.same_setting(other, values)), None)
        if earlier is not None:
            result["rules"][rule] = {"same_setting_as": earlier}
            continue
        done.append((values, rule))

        def counts(lead):
            _, summaries = score_model.run_sets(tuning_sets, typist, rerank.setting_chooser(setting_with(values, lead), scorer))
            return {"dev_right": summaries["dev"]["right"], "dev_categories": {name: value[0] for name, value in summaries["dev"]["categories"].items()},
                    "word": summaries["apostrophe_word"]["right"], "next_word": summaries["apostrophe_next_word"]["right"],
                    "controls_next_word": {name: summaries["apostrophe_next_word"]["categories"][name][0] for name in CONTROLS}}

        base = counts(None)
        rows = {}
        for lead in GRID:
            row = counts(lead)
            row["allowed"] = (all(row["dev_categories"][name] >= count for name, count in base["dev_categories"].items())
                              and all(row["controls_next_word"][name] >= base["controls_next_word"][name] for name in CONTROLS))
            rows[f"{lead:g}"] = row
        allowed = [lead for lead in GRID if rows[f"{lead:g}"]["allowed"]]
        chosen = max(allowed, key=lambda lead: rows[f"{lead:g}"]["next_word"]) if allowed else None
        lead = chosen if chosen is not None else SHIP_LEAD
        entry = {"setting": values, "without_the_step": {key: base[key] for key in ("dev_right", "word", "next_word", "controls_next_word")},
                 "leads": {name: {key: row[key] for key in ("dev_right", "word", "next_word", "controls_next_word", "allowed")}
                           for name, row in rows.items()},
                 "allowed_leads": allowed, "chosen_lead": chosen, "lead": lead,
                 "stock_prompt": stock_prompt_preference(typist, sets["apostrophe_next_word"]["cases"], values, scorer)}
        if lead != SHIP_LEAD:
            outputs, summaries = score_model.run_sets(sets, typist, rerank.setting_chooser(setting_with(values, lead), scorer))
            score_model.write_outputs(arguments.out / f"outputs.select.{rule}.own-lead.jsonl", outputs)
            entry["sets"] = summaries
        result["rules"][rule] = entry
        print(f"{time.monotonic() - started:6.0f} s  {rule}: lead {lead:g} (allowed {allowed}), next word "
              + json.dumps({name: row['next_word'] for name, row in entry['leads'].items()}) + " stock prompt " + json.dumps(entry["stock_prompt"]), flush=True)
    result["lm_answers_new"] = stored.asked
    scorer.close()
    typist.save_readings()
    (arguments.out / "apostrophe.json").write_text(json.dumps(result, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
