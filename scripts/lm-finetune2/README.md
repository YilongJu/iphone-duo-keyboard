# Round 2 of the re-ranker fine-tune

## Summary

Round 2 is running. This page holds the status of the held-out set until the results are in.

1. Read `docs/lm-finetune2-design.md` for the sets, the arms and the two rules.
2. Read `docs/lm-finetune2-design-review.md` for the Codex review of that design.
3. Score an outside model on the held-out set with the command in "Scoring command for the held-out set".

This page does not hold a result yet.

## Status of the held-out set

The held-out set is final since 2026-11-11. Its four files, the leakage check and the scoring
command do not change from here on. `check_leakage2.py` passes on these files.

Table 1. The four files of the held-out set, in `build/lm-finetune2/data` of this worktree.

| File | Cases | SHA-256 |
| --- | --- | --- |
| `cases.generated.holdout.jsonl` | 6,745 generated cases in 24 categories | `f139f6ac86ff0a6d287616fcc90d8d469a926ce02ace993e80ec5cb8a41c9a20` |
| `cases.stream.holdout.jsonl` | 4,000 clean sentences, 26,060 words | `f2f793fb76ff97c450bbc6dd3968199e170ed10262cdef9cb89f9092a6382426` |
| `cases.github.holdout.jsonl` | 1,500 `github_misspelling` and 1,000 `github_real_word` | `155e480fd160c1f1ec734459ce512e23cc9bc0dc07a152beef87de514fd09cf1` |
| `cases.mitton-remainder.holdout.jsonl` | 600 Birkbeck and 121 Holbrook pairs | `ab7a32e824e916033e0ecde199ce132e20cde2040520619fb672ee85db0cc935` |

A held-out read gives one number per arm, once. Fix the model file and its setting before the read,
and do not choose anything from its result. The selection files `cases.stream.select.jsonl` and
`cases.github.select.jsonl` have the same shapes, and they are open for tuning and for dry runs.

## Scoring command for the held-out set

The command runs on Linux or WSL, from the root of this worktree. It needs the engine shim,
`lm_score` and llama.cpp b4846 of `scripts/lm-rerank/build_on_linux.sh`.

    LD_LIBRARY_PATH=$HOME/lmft/llama/lib nice -n 19 python3 scripts/lm-finetune2/read_holdout.py \
        --plan PLAN.json --shim $HOME/lmft/bin/libduo_shim.so --lm $HOME/lmft/bin/lm_score \
        --models MODEL_FOLDER --data build/lm-finetune2/data --threads 2 --workers 2 --out OUT_FOLDER

- `PLAN.json` names each arm: `{"arms": [{"name": "my-arm", "model": "my-model.gguf", "prompt_format": "typed", "setting": {"weight": 1.0, "margin_from_typed": 0, "margin_to_typed": 4, "margin_other": 2, "space_after": 1}}]}`.
- An arm with `"model": null` and `"setting": null` is the engine alone.
- `--dry-run-on-select` reads the selection files in place of the held-out files, to check a plan.
- The script refuses a folder that already holds a result.
- `OUT_FOLDER/result.json` holds the counts per set. `metrics2.py` defines each count.

Table 2. The counts of one arm in `result.json`.

| Set | Count |
| --- | --- |
| `generated` | right cases per category, per group, and for the non-word slips |
| `stream` | changed words and changed sentences of the clean running text, closed and open apart |
| `github` | right cases per category |
| `mitton` | right cases per source |
