"""Measures the keyboard's corrections of words with and without an apostrophe, through the Linux
harness of rerank.py, on cases/english-apostrophe-words.HALF.jsonl, and the effect of the same
runs on the dev cases of english.dev.jsonl and english-symbols.dev.jsonl.

Each case is typed in two ways:
- word: the context, then the typed word and one space, as rerank.py types every case. The
  keyboard sees only the text before the word.
- next word: the context, the typed word, one space, the next word of the sentence and one
  space. At the second space the keyboard reads the two words together, so it sees the word
  after the target word. A case is right when the field holds the intended word and the next word.

Runs, each one through the keyboard rules of rerank.py:
- engine: the engine's own choice, as the keyboard types before its model is ready.
- shipped: the readings without the apostrophe readings (engine setting apostrophe_readings=0)
  and the tuned distilgpt2 rule, as the keyboard of engine/lm-keyboard types.
- readings only: the apostrophe readings with the tuned rule and without the apostrophe step.
- apostrophe step M: the apostrophe readings, the tuned rule and the apostrophe step with
  margin_apostrophe M, for each M of the grid.

The dev half picks M: the most right cases of the new group over both ways of typing, among the
values of M that keep the right cases of every group of the existing dev cases at the shipped
count or more. The test half is read only with --half test, for the one value --margin.

Usage, from the repository root, on Linux:
    LD_LIBRARY_PATH=$PWD/build/lm-rerank/llama/lib python3 scripts/lm-rerank/apostrophe_words.py \
        --shim build/lm-rerank/libduo_shim.so --lm build/lm-rerank/lm_score \
        --model Shared/smollm2-lora-typed-seed1.Q4_K_M.gguf --base smollm2-typed --steps next-slips --half dev         --out build/lm-rerank/apostrophe-words
"""
import argparse
import ctypes
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
import rerank  # noqa: E402

CASES = ROOT / "scripts" / "typing-evaluation" / "cases"
EXISTING = [CASES / "english.dev.jsonl", CASES / "english-symbols.dev.jsonl"]
# 0 is left out: on a tie of model scores the step would then move away from the engine's choice.
GRID = [0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0]
# The settings of the step on the dev half: its scope, its score and its margin. The scope "all"
# runs with the model score only, as the comparison for the scope "next".
STEPS = ([("all", "model", margin) for margin in GRID]
         + [("next", score, margin) for score in ("model", "slips", "slips_only") for margin in GRID])
# The setting of each model and the input format it reads. distilgpt2 Q3_K_M: scripts/lm-rerank/README.md,
# Table 2. The SmolLM2-135M LoRA fine-tune: the arm smollm2-lora-seed1 of scripts/lm-finetune/test-plan.json
# on engine/lm-finetune, which the keyboard ships (KeyboardLanguageModel.rule).
BASES = {
    "distilgpt2": (dict(weight=1.0, margin_from_typed=24, margin_to_typed=0, margin_other=2, space_after=1), "stock"),
    "smollm2-typed": (dict(weight=1.0, margin_from_typed=0, margin_to_typed=4, margin_other=2, space_after=1), "typed"),
}
TUNED: dict = {}


class SetEngine(rerank.Engine):
    """The engine with one setting of apostrophe_readings. The shim holds one set of parameters
    for the process, so each call sets the value first."""

    def __init__(self, shim: Path, lexicon: Path, apostrophe_readings: int):
        super().__init__(shim, lexicon)
        self.library.shim_set.argtypes = [ctypes.c_char_p, ctypes.c_float]
        self.value = apostrophe_readings

    def readings(self, previous_word, typed):
        if self.library.shim_set(b"apostrophe_readings", float(self.value)) != 1:
            raise SystemExit("the engine does not know the setting apostrophe_readings")
        return super().readings(previous_word, typed)


def with_next_word(case: dict) -> dict:
    return {**case, "typed": case["typed"] + " " + case["next_word"], "intended": case["intended"] + " " + case["next_word"]}


def tally(cases: list[dict], predictions: dict[str, str]) -> dict:
    """Right cases per category, and per pair and category."""
    categories: dict[str, list[int]] = {}
    pairs: dict[str, dict[str, list[int]]] = {}
    for case in cases:
        right = int(predictions[case["id"]].strip().lower() == case["intended"].strip().lower())
        entry = categories.setdefault(case["category"], [0, 0])
        entry[0] += right
        entry[1] += 1
        cell = pairs.setdefault(case["pair"], {}).setdefault(case["category"], [0, 0])
        cell[0] += right
        cell[1] += 1
    return {"right": sum(v[0] for v in categories.values()), "cases": len(cases), "categories": categories, "pairs": pairs}


def run_group(cases, engine, chooser) -> dict:
    """Both ways of typing for the new group."""
    word = rerank.run(cases, engine, chooser)
    next_cases = [with_next_word(case) for case in cases]
    next_word = rerank.run(next_cases, engine, chooser)
    return {"word": tally(cases, word), "next_word": tally(next_cases, next_word),
            "outputs": {case["id"]: {"word": word[case["id"]], "next_word": next_word[case["id"]]} for case in cases}}


def existing_summary(cases, engine, chooser) -> dict:
    predictions = rerank.run(cases, engine, chooser)
    summary = rerank.summarize(cases, predictions)
    summary["outputs"] = predictions
    return summary


def readings_report(cases, engine) -> dict:
    """For each case and way of typing: the place of the intended text among the readings of the
    last correction, or None. The oracle of rerank.py types it."""
    report = {}
    for way, typed_cases in (("word", cases), ("next_word", [with_next_word(c) for c in cases])):
        found = {}
        for case in typed_cases:
            target = (case["context"] + " " if case["context"] else "") + case["intended"].strip().lower() + " "
            output = rerank.type_case(case, engine, rerank.oracle_chooser(target))
            found[case["id"]] = output.strip().lower() == case["intended"].strip().lower()
        report[way] = tally(typed_cases, {c["id"]: (c["intended"] if found[c["id"]] else "") for c in typed_cases})
    return report


CONTROLS = ["clean_ambiguous_word", "clean_ambiguous_contraction"]
EXISTING_CASES: list[dict] = []


def lost_cases(cases: list[dict], before: dict[str, str], after: dict[str, str]) -> list[str]:
    """The cases right in `before` and wrong in `after`."""
    def right(outputs, case):
        return outputs[case["id"]].strip().lower() == case["intended"].strip().lower()
    return [case["id"] for case in cases if right(before, case) and not right(after, case)]


def select(result: dict, group: list[dict]) -> dict:
    """The setting of the step for the keyboard. Every category of the existing dev cases must keep
    at least the shipped count of right cases, and so must the controls of the new cases when the
    next word is typed. Among those settings the most right new cases with the next word typed
    count, because the keyboard shows that text in the end. The first setting of the grid wins a tie."""
    runs = result["runs"]
    base = runs["shipped"]
    allowed = []
    for name, entry in runs.items():
        if not name.startswith("step "):
            continue
        existing_ok = all(entry["existing"]["categories"][c]["right"] >= base["existing"]["categories"][c]["right"]
                          for c in base["existing"]["categories"])
        controls_ok = all(entry["group"]["next_word"]["categories"][c][0] >= base["group"]["next_word"]["categories"][c][0]
                          for c in CONTROLS)
        if existing_ok and controls_ok:
            allowed.append(name)
    chosen = max(allowed, key=lambda n: runs[n]["group"]["next_word"]["right"]) if allowed else None
    # The existing dev cases that each setting turns from right to wrong, against the shipped run.
    lost = {name: lost_cases(EXISTING_CASES, base["existing"]["outputs"], entry["existing"]["outputs"])
            for name, entry in runs.items() if "existing" in entry and name != "shipped"}
    # Two fixed keyboards for comparison: one that always shows the contraction, one that never does.
    always = sum(1 for case in group if "'" in case["intended"])
    return {"allowed": allowed, "chosen": chosen, "existing_lost_against_shipped": lost,
            "always_contraction": always, "never_contraction": len(group) - always}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--lm", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--half", choices=["dev", "test"], required=True)
    parser.add_argument("--base", choices=list(BASES), required=True, help="the model's setting and input format")
    parser.add_argument("--steps", choices=["all", "next-slips", "prompts"], required=True,
                        help="the dev grid: every scope and score; the keyboard's scope next and score slips; "
                             "or the scope next with the scores model and slips for every prompt of the step")
    parser.add_argument("--margin", type=float, help="the one margin_apostrophe of the test-half run")
    parser.add_argument("--scope", choices=["all", "next"], help="the one apostrophe_scope of the test-half run")
    parser.add_argument("--score", choices=["model", "slips", "slips_only"], help="the one apostrophe_score of the test-half run")
    parser.add_argument("--lexicon", type=Path, default=rerank.LEXICON)
    parser.add_argument("--shipped-lexicon", type=Path,
                        help="the lexicon of the keyboard as it ships, when it differs from --lexicon")
    parser.add_argument("--shipped-shim", type=Path,
                        help="a second copy of the shim for --shipped-lexicon: one shim holds one lexicon")
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    TUNED.update(BASES[arguments.base][0])
    prompt_format = BASES[arguments.base][1]
    if (arguments.lm is None) != (arguments.model is None):
        raise SystemExit("--lm and --model go together")
    one = (arguments.margin, arguments.scope, arguments.score)
    if arguments.half == "test" and (None in one or arguments.model is None):
        raise SystemExit("the test half runs once, for one --margin, --scope and --score, with the model")
    if arguments.half == "dev" and one != (None, None, None):
        raise SystemExit("the dev half runs the whole grid; --margin, --scope and --score are for the test half")

    group = rerank.load_cases([CASES / f"english-apostrophe-words.{arguments.half}.jsonl"])
    if any(case["split"] != arguments.half for case in group):
        raise SystemExit(f"a case outside the {arguments.half} half")
    existing = rerank.load_cases(EXISTING)
    EXISTING_CASES[:] = existing
    if any(case["split"] != "dev" for case in existing):
        raise SystemExit("an existing case outside the dev half")
    arguments.out.mkdir(parents=True, exist_ok=True)

    if (arguments.shipped_lexicon is None) != (arguments.shipped_shim is None):
        raise SystemExit("--shipped-lexicon and --shipped-shim go together")
    if arguments.shipped_shim is not None and arguments.shipped_shim.resolve() == arguments.shim.resolve():
        raise SystemExit("--shipped-shim must be another file than --shim")
    # The keyboard as it ships: its lexicon and the readings without the apostrophe readings.
    shipped_engine = (SetEngine(arguments.shipped_shim, arguments.shipped_lexicon, 0) if arguments.shipped_shim
                      else SetEngine(arguments.shim, arguments.lexicon, 0))
    old_engine = SetEngine(arguments.shim, arguments.lexicon, 0) if arguments.shipped_shim else shipped_engine
    new_engine = SetEngine(arguments.shim, arguments.lexicon, 1)
    result = {"half": arguments.half, "base": arguments.base, "setting": dict(TUNED), "prompt_format": prompt_format,
              "lexicon": str(arguments.lexicon),
              "shipped_lexicon": str(arguments.shipped_lexicon or arguments.lexicon), "cases": len(group), "runs": {}}

    def record(name, entry):
        result["runs"][name] = entry
        line = {way: entry["group"][way]["right"] for way in ("word", "next_word")}
        if "existing" in entry:
            line["existing"] = entry["existing"]["right"]
        print(name, json.dumps(line), flush=True)

    if arguments.shipped_shim is not None:
        record("engine, shipped lexicon", {"group": run_group(group, shipped_engine, rerank.engine_choice),
                                           "existing": existing_summary(existing, shipped_engine, rerank.engine_choice)})
    record("engine", {"group": run_group(group, old_engine, rerank.engine_choice),
                      "existing": existing_summary(existing, old_engine, rerank.engine_choice)})
    result["readings"] = {"without apostrophe readings": readings_report(group, old_engine),
                          "with apostrophe readings": readings_report(group, new_engine)}

    if arguments.model is not None:
        model = rerank.LanguageModel(arguments.lm, arguments.model, arguments.threads, no_context=False,
                                     prompt_format=prompt_format)
        result["lm_ready"] = model.ready
        started = time.monotonic()

        def chooser(setting):
            return rerank.setting_chooser(setting, model)

        shipped = rerank.Setting(**TUNED)
        if arguments.half == "dev":
            record("shipped", {"group": run_group(group, shipped_engine, chooser(shipped)),
                               "existing": existing_summary(existing, shipped_engine, chooser(shipped))})
            record("readings only", {"group": run_group(group, new_engine, chooser(shipped)),
                                     "existing": existing_summary(existing, new_engine, chooser(shipped))})
            if arguments.steps == "all":
                steps = [(*step, "same") for step in STEPS]
            elif arguments.steps == "next-slips":
                steps = [(*step, "same") for step in STEPS if step[:2] == ("next", "slips")]
            else:
                steps = [("next", score, margin, prompt) for prompt in rerank.APOSTROPHE_PROMPTS
                         for score in ("model", "slips") for margin in GRID]
        else:
            record("shipped", {"group": run_group(group, shipped_engine, chooser(shipped))})
            steps = [(arguments.scope, arguments.score, arguments.margin, "same")]
        for scope, step_score, margin, prompt in steps:
            setting = rerank.Setting(**TUNED, margin_apostrophe=margin, apostrophe_scope=scope, apostrophe_score=step_score,
                                     apostrophe_prompt=prompt)
            entry = {"group": run_group(group, new_engine, chooser(setting))}
            if arguments.half == "dev":
                entry["existing"] = existing_summary(existing, new_engine, chooser(setting))
            # The prompt "same" keeps the names of the earlier runs.
            record(f"step {scope} {step_score} {margin:g}" + ("" if prompt == "same" else f" {prompt}"), entry)
            print(f"  {time.monotonic() - started:.0f} s, {model.requests} model requests", flush=True)

        if arguments.half == "dev":
            result.update(select(result, group))
            print("chosen", result["chosen"], flush=True)
        result["lm_requests"] = model.requests
        result["lm_report"] = model.close()
    (arguments.out / f"result.{arguments.half}.json").write_text(json.dumps(result, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
