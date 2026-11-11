"""Measures the "AI and software" vocabulary pack through the Linux harness of rerank.py.

Four configurations type every case, through the keyboard rules of rerank.py:
- engine, pack off: the engine's own choice with the base lexicon alone.
- engine, pack on: the same with the supplement Shared/supplement-ai-software.bin laid over the
  lexicon and the preferred capitals of Shared/supplement-ai-software.tsv.
- model, pack off and model, pack on: the same two with the keyboard's SmolLM2 fine-tune and its
  tuned rule (harness_trace.TUNED), as the keyboard ships.

Cases:
- cases/english-domain.HALF.jsonl: the new groups, one count per category and group. A case with
  `scoring` "case" is right only with the intended capitals.
- cases/english-domain-stream.HALF.jsonl: whole sentences typed word by word. The count is the
  changed words: the word edit distance between the field and the sentence. The stream
  "written" is typed with its capitals and punctuation, and a change of capitals counts.
- On the dev half only: the existing dev cases of english.dev.jsonl and english-symbols.dev.jsonl,
  and the apostrophe words typed alone and with the next word. No category may lose a case when
  the pack comes on.

The test half is read only with --half test, once, for the pack that the dev half chose.
Without --lm and --model the script runs the two engine configurations only.

Usage, from the repository root, on Linux:
    LD_LIBRARY_PATH=$PWD/build/lm-rerank/llama/lib python3 scripts/lm-rerank/domain_pack.py \
        --shim build/lm-rerank/libduo_shim.so --lm build/lm-rerank/lm_score \
        --model Shared/smollm2-lora-typed-seed1.Q4_K_M.gguf --half dev --out build/lm-rerank/domain-pack
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
sys.path.insert(0, str(ROOT / "scripts" / "lm-keyboard"))
import apostrophe_words  # noqa: E402
import harness_trace  # noqa: E402
import rerank  # noqa: E402
from score import normalize  # noqa: E402

CASES = ROOT / "scripts" / "typing-evaluation" / "cases"
EXISTING = [CASES / "english.dev.jsonl", CASES / "english-symbols.dev.jsonl"]


def word_distance(first: list[str], second: list[str]) -> int:
    previous = list(range(len(second) + 1))
    for i, a in enumerate(first, 1):
        current = [i]
        for j, b in enumerate(second, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def tally_stream(rows: list[dict], outputs: dict[str, str], pack_words: set[str]) -> dict:
    """Changed words per kind of stream. A changed sentence also lists its typed and shown text.
    `of_pack_words` counts the changed sentences whose typed words that the field lacks hold a
    word of the pack."""
    result = {}
    for row in rows:
        entry = result.setdefault(row["stream"], {"sentences": 0, "words": 0, "changed_words": 0, "changed_sentences": 0,
                                                  "changed_sentences_with_a_pack_word": 0, "changes": []})
        # The stream as written counts a change of capitals too.
        exact = row["stream"] == "written"
        typed = (row["typed"] if exact else row["typed"].lower()).split(" ")
        shown = (outputs[row["id"]] if exact else outputs[row["id"]].lower()).split(" ")
        distance = word_distance(typed, shown)
        entry["sentences"] += 1
        entry["words"] += len(typed)
        entry["changed_words"] += distance
        if distance:
            entry["changed_sentences"] += 1
            missing = [word for word in typed if word not in shown]
            entry["changed_sentences_with_a_pack_word"] += int(any(
                word.lower().strip(".,!?;:\"()[]") in pack_words for word in missing))
            entry["changes"].append({"id": row["id"], "typed_words_changed": missing,
                                     "shown_words_new": [word for word in shown if word not in typed]})
    for entry in result.values():
        entry["changed_words_per_1000"] = round(1000 * entry["changed_words"] / entry["words"], 2)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--lm", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--half", choices=["dev", "test"], required=True)
    parser.add_argument("--lexicon", type=Path, default=rerank.LEXICON)
    parser.add_argument("--supplement", type=Path, default=rerank.SUPPLEMENT)
    parser.add_argument("--table", type=Path, default=rerank.CAPITALS_TABLE)
    parser.add_argument("--merged-lexicon", type=Path,
                        help="the comparison lexicon of scripts/domain-pack/build_merged_lexicon.py: the engine alone "
                             "also types every case with it, without a supplement")
    parser.add_argument("--merged-shim", type=Path,
                        help="a second copy of the shim for --merged-lexicon: one shim holds one lexicon")
    parser.add_argument("--stream-limit", type=int,
                        help="type only this many sentences of each stream, for a short check of the script")
    parser.add_argument("--only-new", action="store_true",
                        help="leave out the existing dev cases and the apostrophe words, for a short check or a "
                             "comparison of pack settings")
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    if (arguments.lm is None) != (arguments.model is None):
        raise SystemExit("--lm and --model go together")
    if (arguments.merged_lexicon is None) != (arguments.merged_shim is None):
        raise SystemExit("--merged-lexicon and --merged-shim go together")
    if arguments.merged_shim is not None and arguments.merged_shim.resolve() == arguments.shim.resolve():
        raise SystemExit("--merged-shim must be another file than --shim")
    half = arguments.half

    domain = rerank.load_cases([CASES / f"english-domain.{half}.jsonl"])
    stream = rerank.load_cases([CASES / f"english-domain-stream.{half}.jsonl"])
    if any(case["split"] != half for case in domain + stream):
        raise SystemExit(f"a case outside the {half} half")
    if arguments.stream_limit is not None:
        stream = [row for kind in ("technical", "written", "everyday")
                  for row in [r for r in stream if r["stream"] == kind][:arguments.stream_limit]]
    existing, apostrophe = [], []
    with_existing = half == "dev" and not arguments.only_new
    if with_existing:
        existing = rerank.load_cases(EXISTING)
        apostrophe = rerank.load_cases([CASES / "english-apostrophe-words.dev.jsonl"])
        if any(case["split"] != "dev" for case in existing + apostrophe):
            raise SystemExit("an existing case outside the dev half")
    arguments.out.mkdir(parents=True, exist_ok=True)

    capitals = rerank.PreferredCapitals(arguments.table)
    pack_words = {line.split("\t")[0] for line in arguments.table.read_text(encoding="utf-8").splitlines()[1:]}
    engines = {"off": rerank.Engine(arguments.shim, arguments.lexicon, arguments.supplement, use_supplement=False),
               "on": rerank.Engine(arguments.shim, arguments.lexicon, arguments.supplement, use_supplement=True)}
    choosers = {"engine": rerank.engine_choice}
    model = None
    if arguments.model is not None:
        model = rerank.LanguageModel(arguments.lm, arguments.model, arguments.threads, no_context=False,
                                     prompt_format=harness_trace.PROMPT_FORMAT)
        choosers["model"] = rerank.setting_chooser(harness_trace.TUNED, model)

    result = {"half": half, "supplement": str(arguments.supplement), "table": str(arguments.table),
              "lexicon": str(arguments.lexicon), "stream_sentences": len(stream),
              "setting": harness_trace.TUNED.__dict__, "configurations": {}}
    outputs = {}
    started = time.monotonic()
    for chooser_name, chooser in choosers.items():
        for pack in ("off", "on"):
            name = f"{chooser_name}, pack {pack}"
            engine = engines[pack]
            table = capitals if pack == "on" else None

            def run(cases):
                return rerank.run(cases, engine, chooser, table, keep_capitals=True)

            entry = {}
            shown = {"domain": run(domain), "stream": run(stream)}
            entry["domain"] = rerank.tally_by_group(domain, shown["domain"])
            entry["stream"] = tally_stream(stream, shown["stream"], pack_words)
            if with_existing:
                shown["existing"] = run(existing)
                entry["existing"] = rerank.summarize(existing, shown["existing"])
                next_cases = [apostrophe_words.with_next_word(case) for case in apostrophe]
                shown["apostrophe_word"] = run(apostrophe)
                shown["apostrophe_next_word"] = run(next_cases)
                entry["apostrophe"] = {"word": apostrophe_words.tally(apostrophe, shown["apostrophe_word"]),
                                       "next_word": apostrophe_words.tally(next_cases, shown["apostrophe_next_word"])}
                if pack == "off":
                    # The typing of this script keeps the typed capitals in the field, and the
                    # harness of the pinned numbers does not. With the pack off, the two must give
                    # the same letters for every existing case.
                    legacy = rerank.run(existing, engine, chooser)
                    entry["existing_cases_that_differ_from_the_typing_without_capitals"] = [
                        case["id"] for case in existing
                        if normalize("english", legacy[case["id"]]) != normalize("english", shown["existing"][case["id"]])]
            outputs[name] = shown
            result["configurations"][name] = entry
            line = {"domain": {g: f"{v[0]}/{v[1]}" for g, v in entry["domain"]["groups"].items()},
                    "stream": {k: v["changed_words_per_1000"] for k, v in entry["stream"].items()}}
            if with_existing:
                line["existing"] = entry["existing"]["right"]
                line["apostrophe"] = [entry["apostrophe"]["word"]["right"], entry["apostrophe"]["next_word"]["right"]]
            print(name, json.dumps(line), f"{time.monotonic() - started:.0f} s", flush=True)
            with (arguments.out / f"outputs.{half}.{chooser_name}-pack-{pack}.jsonl").open("w", encoding="utf-8") as file:
                for kind, values in shown.items():
                    for case_id, output in values.items():
                        file.write(json.dumps({"set": kind, "id": case_id, "output": output}) + "\n")

    # The other way of bringing the pack to the engine: one lexicon with the pack merged in.
    if arguments.merged_lexicon is not None:
        merged_engine = rerank.Engine(arguments.merged_shim, arguments.merged_lexicon)
        supplement_outputs = outputs["engine, pack on"]
        sets = {"domain": domain, "stream": stream}
        if with_existing:
            sets["existing"] = existing
        comparison = {"lexicon": str(arguments.merged_lexicon), "sets": {}}
        for kind, cases in sets.items():
            shown = rerank.run(cases, merged_engine, rerank.engine_choice, capitals, keep_capitals=True)
            if kind == "stream":
                comparison["stream"] = {k: v["changed_words_per_1000"] for k, v in tally_stream(cases, shown, pack_words).items()}

            def same(case):
                a, b = supplement_outputs[kind][case["id"]], shown[case["id"]]
                return a.strip() == b.strip() if case.get("scoring") == "case" else normalize("english", a) == normalize("english", b)
            comparison["sets"][kind] = {
                "cases": len(cases), "same": sum(same(case) for case in cases),
                "right_supplement": sum(rerank.case_is_right(case, supplement_outputs[kind][case["id"]]) for case in cases),
                "right_merged": sum(rerank.case_is_right(case, shown[case["id"]]) for case in cases),
                "differences": [{"id": case["id"], "typed": case["typed"], "intended": case["intended"],
                                 "supplement": supplement_outputs[kind][case["id"]], "merged": shown[case["id"]]}
                                for case in cases if not same(case)][:100]}
        result["merged_lexicon"] = comparison
        print("merged lexicon", json.dumps({k: [v["cases"], v["same"], v["right_supplement"], v["right_merged"]]
                                            for k, v in comparison["sets"].items()}), flush=True)

    # The cases that the pack turns from right to wrong, and from wrong to right, per chooser.
    result["pack_effect"] = {}
    for chooser_name in choosers:
        off, on = outputs[f"{chooser_name}, pack off"], outputs[f"{chooser_name}, pack on"]
        effect = {}
        sets = [("domain", domain, rerank.case_is_right)]
        if with_existing:
            def letters_right(case, output):
                return normalize("english", output) == normalize("english", case["intended"])
            sets += [("existing", existing, letters_right), ("apostrophe_word", apostrophe, letters_right),
                     ("apostrophe_next_word", [apostrophe_words.with_next_word(c) for c in apostrophe], letters_right)]
        for kind, cases, right in sets:
            lost = [c for c in cases if right(c, off[kind][c["id"]]) and not right(c, on[kind][c["id"]])]
            gained = [c for c in cases if not right(c, off[kind][c["id"]]) and right(c, on[kind][c["id"]])]

            def rows(found):
                return [{"id": c["id"], "category": c["category"], "context": c["context"][-60:], "typed": c["typed"],
                         "intended": c["intended"], "pack_off": off[kind][c["id"]], "pack_on": on[kind][c["id"]]} for c in found]
            effect[kind] = {"lost": rows(lost), "gained_count": len(gained), "gained": rows(gained)[:200]}
        result["pack_effect"][chooser_name] = effect
        print(chooser_name, "pack effect", json.dumps({k: [len(v["lost"]), v["gained_count"]] for k, v in effect.items()}), flush=True)

    if model is not None:
        result["lm_requests"] = model.requests
        result["lm_report"] = model.close()
    (arguments.out / f"result.{half}.json").write_text(json.dumps(result, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
