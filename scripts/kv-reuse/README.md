# Replay and speed pass of the reuse of the model's cache

These scripts measure the approaches of `docs/kv-reuse-design.md` on the local PC, and
`docs/kv-reuse-results.md` holds their numbers. The keyboard reuses the cache with the prefix mode
(approach B), one slot.

## Files

| File | Content |
| --- | --- |
| `kv_replay.c` | The keyboard's scorer `LanguageModel/duo_lm_scorer.c` with a reuse mode, behind the request protocol of `lm_score.c`, with the time of each request |
| `replay.py` | Types the replay documents through the keyboard's typing rules and `kv_replay`, without a table of earlier answers, and writes every request and correction |
| `analyze.py` | Turns the replays and the speed pass into the tables of the results page, and applies the selection rule |
| `cache_test.c` | Tests of the cache on Linux, the same cases as `Tests/LanguageModelCacheTests.swift` |
| `jobs/build.sh` | Builds the engine shim, `kv_replay` and `kv_replay-min1` (calls of one token) |
| `jobs/accuracy.sh` | One replay per approach, all at once, each at 2 threads, with the check of the cache |
| `jobs/speed.sh` | The requests of approach A's replay through each approach, one at a time, at 2 threads |

## Steps

Run these from the repository root. The jobs need WSL with the llama.cpp b4846 build of
`$HOME/lmft/llama` (`scripts/lm-rerank/build_on_linux.sh llama`), the shipped file in `Shared/`
(`scripts/ci/fetch_language_model.sh model`), and the folder of `cases.stream.select.jsonl` of
`scripts/lm-domain` (`build/lm-domain/data/everyday`). The outputs go to `$HOME/kvreuse`.

1. Start the accuracy job detached, so a restart of the session does not stop it:
   `powershell -File scripts/lm-domain/detach.ps1 -Name kv-accuracy -Where wsl -Script scripts/kv-reuse/jobs/accuracy.sh -Arguments "<everyday folder>"`
2. After it ends, start the speed job the same way, with `-Name kv-speed -Script scripts/kv-reuse/jobs/speed.sh`,
   and nothing else running on the machine.
3. Run `python3 scripts/kv-reuse/analyze.py --kv ~/kvreuse --out build/kv-reuse` in WSL.

Both jobs keep each finished approach, so a job that starts again goes on where it stopped. The
log is `build/lm-domain/logs/NAME.log`.

## The tests of the cache on Linux

```
gcc -std=c11 -O2 -Wall -Wextra -Werror -I $HOME/lmft/llama/include -I LanguageModel \
  LanguageModel/duo_lm_scorer.c scripts/kv-reuse/cache_test.c \
  -L $HOME/lmft/llama/lib -lllama -lggml -lggml-cpu -lggml-base -lm -o cache_test
LD_LIBRARY_PATH=$HOME/lmft/llama/lib ./cache_test Shared/smollm2-lora-domain-s100-seed1.Q4_K_M.gguf prefix 1
```

With the mode `none`, which reads every request from an empty cache as the scorer did before the
reuse, the two tests of the reuse fail. With `prefix` every test passes.
