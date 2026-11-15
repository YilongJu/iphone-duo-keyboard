"""Types the typo set through the Linux copy of the keyboard's rules, and scores it.

English: each case goes through the keyboard's correction rules of scripts/lm-rerank/rerank.py
(`type_case`), with the engine of the shim and the work area "AI and software" on, as the
keyboard ships. The engine's own choice gives the run "engine only". With --lm and --model the
same cases also go through the tuned rule with the language model, as
scripts/lm-keyboard/harness_trace.py does, and every correction that went to the model is
written to a trace for compare_typos.py.

Pinyin: each case goes through Engine/duo_cli.c in the Pinyin mode, as
scripts/typing-evaluation/run_duo_engine.py does: the engine's first reading of all the letters.

Case files: cases/english-typos.HALF.jsonl and cases/pinyin-typos.HALF.jsonl, and the cases from
real data in build/typo-set/cases/ that build_real_typos.py writes (english-typos-aalto and
pinyin-typos-cscd). A missing real-data file stops the script, unless --generated-only is given.

Outputs in --out, for each case file NAME:
    NAME.HALF.engine-only.jsonl, and with the model NAME.HALF.jsonl and NAME.HALF.trace.jsonl
    NAME.HALF[.engine-only].summary.json and summary.md, from score_typos.py
    requests.tsv, result.json (with the model)

Usage, from the repository root, on Linux:
    python3 scripts/typing-evaluation/typo-set/run_typos.py --shim build/lm-rerank/libduo_shim.so \
        --cli build/engine/duo_cli --half dev --out build/typo-set/engine
    LD_LIBRARY_PATH=$PWD/build/lm-rerank/llama/lib python3 scripts/typing-evaluation/typo-set/run_typos.py \
        --shim build/lm-rerank/libduo_shim.so --cli build/engine/duo_cli --lm build/lm-rerank/lm_score \
        --model Shared/smollm2-lora-domain-s100-seed1.Q4_K_M.gguf --half dev --out build/typo-set/harness
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
sys.path.insert(0, str(ROOT / "scripts" / "lm-keyboard"))
import rerank  # noqa: E402
import score_typos  # noqa: E402
from harness_trace import PROMPT_FORMAT, TUNED  # noqa: E402

CASES = ROOT / "scripts" / "typing-evaluation" / "cases"
REAL = ROOT / "build" / "typo-set" / "cases"
ENGLISH = [("english-typos", CASES), ("english-typos-aalto", REAL)]
PINYIN = [("pinyin-typos", CASES), ("pinyin-typos-cscd", REAL)]


def case_files(half: str, generated_only: bool) -> tuple[list, list]:
    found = {"english": [], "pinyin": []}
    for task, names in (("english", ENGLISH), ("pinyin", PINYIN)):
        for name, folder in names:
            path = folder / f"{name}.{half}.jsonl"
            if folder == REAL and generated_only:
                continue
            if not path.exists():
                raise SystemExit(f"{path} is missing: run fetch_real_data.sh and build_real_typos.py, or give --generated-only")
            found[task].append((name, path))
    return found["english"], found["pinyin"]


def write(path: Path, cases: list[dict], outputs: dict[str, str]) -> None:
    path.write_text("".join(json.dumps({"id": c["id"], "output": outputs[c["id"]]}, ensure_ascii=False) + "\n" for c in cases),
                    encoding="utf-8", newline="\n")


def summarize(task: str, name: str, cases: list[dict], outputs: dict[str, str], stem: Path, label: str) -> dict:
    summary = score_typos.score(task, cases, outputs)
    summary.update({"name": label, "cases_files": [name]})
    Path(str(stem) + ".summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    text = score_typos.markdown(label, summary)
    Path(str(stem) + ".summary.md").write_text(text, encoding="utf-8")
    print(text, flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--lm", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--half", choices=["dev", "test"], required=True)
    parser.add_argument("--generated-only", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    if (arguments.lm is None) != (arguments.model is None):
        raise SystemExit("--lm and --model go together")
    english, pinyin = case_files(arguments.half, arguments.generated_only)
    arguments.out.mkdir(parents=True, exist_ok=True)
    half = arguments.half

    engine = rerank.Engine(arguments.shim, rerank.LEXICON, rerank.SUPPLEMENT, use_supplement=True)
    capitals = rerank.PreferredCapitals(rerank.CAPITALS_TABLE)
    model = None
    if arguments.model is not None:
        model = rerank.LanguageModel(arguments.lm, arguments.model, arguments.threads, no_context=False,
                                     prompt_format=PROMPT_FORMAT)
    result = {"half": half, "files": {}}
    requests: dict[str, None] = {}
    for name, path in english:
        cases = score_typos.read_jsonl(path)
        if any(case["split"] != half for case in cases):
            raise SystemExit(f"{path} holds a case of another half")
        control = rerank.run(cases, engine, rerank.engine_choice, capitals, keep_capitals=True)
        write(arguments.out / f"{name}.{half}.engine-only.jsonl", cases, control)
        entry = {"engine only": summarize("english", name, cases, control, arguments.out / f"{name}.{half}.engine-only",
                                          f"{name} {half}, engine only")}
        if model is not None:
            trace, reranked = [], {}
            for case in cases:
                step = 0

                def chooser(readings, text_before, typed):
                    nonlocal step
                    context = text_before.rstrip(" ")
                    choice = rerank.choose(readings, context, TUNED, model, typed)
                    if len(readings) > 1:
                        scores = model.reading_scores(context, readings, typed)
                        typed_text = next(r["text"] for r in readings if r["as_typed"])
                        has_twin = any(not r["as_typed"] and rerank.is_twin(r["text"], typed_text, TUNED.apostrophe_scope)
                                       for r in readings)
                        step_lm = model.step_scores(context, [r["text"] for r in readings], TUNED.apostrophe_prompt) if has_twin else {}
                        opens_field = not context
                        lm_context = rerank.language_model_prompt(context, typed, PROMPT_FORMAT)
                        requests["\t".join([lm_context, *[rerank.language_model_text(t, opens_field)
                                                          for t in sorted(r["text"] for r in readings)]])] = None
                        trace.append({
                            "id": case["id"], "step": step, "text_before": text_before, "context": lm_context,
                            "readings": [{
                                "text": r["text"],
                                "candidate": ("" if not lm_context else " ") + rerank.language_model_text(r["text"], opens_field),
                                "engine_score": r["score"], "slip_cost": r["slips"], "as_typed": r["as_typed"],
                                "chosen": r["chosen"], "log_probability": scores[r["text"]][0], "space_after": scores[r["text"]][1],
                                "step_log_probability": step_lm[r["text"]][0] if step_lm else None,
                                "step_space_after": step_lm[r["text"]][1] if step_lm else None,
                            } for r in readings],
                            "result": "scores", "choice": choice,
                        })
                        step += 1
                    return choice

                reranked[case["id"]] = rerank.type_case(case, engine, chooser, capitals, keep_capitals=True)
            write(arguments.out / f"{name}.{half}.jsonl", cases, reranked)
            with (arguments.out / f"{name}.{half}.trace.jsonl").open("w", encoding="utf-8") as file:
                for line in trace:
                    file.write(json.dumps(line) + "\n")
            entry["with the model"] = summarize("english", name, cases, reranked, arguments.out / f"{name}.{half}",
                                                f"{name} {half}, with the model")
            entry["corrections_read_by_the_model"] = len(trace)
        result["files"][name] = entry

    for name, path in pinyin:
        cases = score_typos.read_jsonl(path)
        completed = subprocess.run([str(arguments.cli), "pinyin", str(ROOT / "Shared" / "lexicon-pinyin.bin")],
                                   input="".join(f"{c['id']}\t{c['typed']}\n" for c in cases), capture_output=True,
                                   text=True, encoding="utf-8", check=True)
        outputs = dict(line.split("\t", 1) for line in completed.stdout.splitlines())
        write(arguments.out / f"{name}.{half}.engine-only.jsonl", cases, outputs)
        result["files"][name] = {"engine only": summarize("pinyin", name, cases, outputs,
                                                          arguments.out / f"{name}.{half}.engine-only", f"{name} {half}, engine only")}
    if model is not None:
        (arguments.out / "requests.tsv").write_text("".join(r + "\n" for r in requests), encoding="utf-8")
        result["setting"] = TUNED.__dict__
        result["lm_ready"] = model.ready
        result["distinct_requests"] = len(requests)
        result["lm_report"] = model.close()
    (arguments.out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
