"""Types the dev cases through the Linux harness of scripts/lm-rerank with the tuned rule, and
writes every correction that went to the language model, for compare.py.

The harness is rerank.py as it is: its Python copy of the keyboard's correction rules, its engine
shim and its scorer lm_score. This script only runs the control and the one tuned setting, and
records each correction on the way.

Outputs in --out:
    control.dev.jsonl    the engine's own choice, as rerank.py writes it
    reranked.dev.jsonl   the tuned rule with the model, as rerank.py writes it
    trace.dev.jsonl      one line per correction with more than one reading
    requests.tsv         every distinct request to the model, in the request format of lm_score.c
    result.json          the groups of both runs, the setting, and the report of lm_score

Usage, from the repository root, on Linux:
    LD_LIBRARY_PATH=$PWD/build/lm-rerank/llama/lib python3 scripts/lm-keyboard/harness_trace.py \
        --shim build/lm-rerank/libduo_shim.so --lm build/lm-rerank/lm_score \
        --model build/lm-rerank/models/distilgpt2.Q3_K_M.gguf --out build/lm-keyboard/harness
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
import rerank  # noqa: E402

# The setting tuned for distilgpt2 Q3_K_M (scripts/lm-rerank/README.md, Table 2), with the
# apostrophe step tuned on the apostrophe words (docs/apostrophe-words-design.md). The keyboard's
# RerankRule.distilgpt2WithApostrophes holds the same numbers.
TUNED = rerank.Setting(weight=1.0, margin_from_typed=24, margin_to_typed=0, margin_other=2, space_after=1,
                       margin_apostrophe=1.0, apostrophe_scope="next", apostrophe_score="slips")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--lm", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4, help="threads of lm_score, 4 as in the tuning run")
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()

    cases = rerank.load_cases(rerank.CASE_FILES)
    if any(case["split"] != "dev" for case in cases):
        raise SystemExit("a case outside the dev half")
    engine = rerank.Engine(arguments.shim, rerank.LEXICON)
    model = rerank.LanguageModel(arguments.lm, arguments.model, arguments.threads, no_context=False)
    arguments.out.mkdir(parents=True, exist_ok=True)

    control = rerank.run(cases, engine, rerank.engine_choice)
    rerank.write_predictions(arguments.out / "control.dev.jsonl", cases, control)

    trace: list[dict] = []
    requests: dict[str, None] = {}
    reranked = {}
    for case in cases:
        step = 0

        def chooser(readings, text_before):
            nonlocal step
            context = text_before.rstrip(" ")
            choice = rerank.choose(readings, context, TUNED, model)
            if len(readings) > 1:
                scores = model.scores(context, [r["text"] for r in readings])
                opens_field = not context
                lm_context = rerank.language_model_text(context, True)
                sorted_texts = sorted(r["text"] for r in readings)
                requests["\t".join([lm_context, *[rerank.language_model_text(t, opens_field) for t in sorted_texts]])] = None
                trace.append({
                    "id": case["id"], "step": step, "text_before": text_before, "context": lm_context,
                    "readings": [{
                        "text": r["text"],
                        "candidate": ("" if opens_field else " ") + rerank.language_model_text(r["text"], opens_field),
                        "engine_score": r["score"], "as_typed": r["as_typed"], "chosen": r["chosen"],
                        "log_probability": scores[r["text"]][0], "space_after": scores[r["text"]][1],
                    } for r in readings],
                    "result": "scores", "choice": choice,
                })
                step += 1
            return choice

        reranked[case["id"]] = rerank.type_case(case, engine, chooser)
    rerank.write_predictions(arguments.out / "reranked.dev.jsonl", cases, reranked)

    with (arguments.out / "trace.dev.jsonl").open("w", encoding="utf-8") as file:
        for line in trace:
            file.write(json.dumps(line) + "\n")
    (arguments.out / "requests.tsv").write_text("".join(request + "\n" for request in requests), encoding="utf-8")

    result = {
        "setting": TUNED.__dict__, "lm_ready": model.ready,
        "control": rerank.summarize(cases, control), "reranked": rerank.summarize(cases, reranked),
        "corrections_read_by_the_model": len(trace), "distinct_requests": len(requests),
        "lm_report": model.close(),
    }
    (arguments.out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    for name in ("control", "reranked"):
        print(name, result[name]["right"], "of", result[name]["cases"], json.dumps(
            {group: f"{entry['right']}/{entry['cases']}" for group, entry in result[name]["groups"].items()}))
    print(len(trace), "corrections read by the model,", len(requests), "distinct requests")


if __name__ == "__main__":
    main()
