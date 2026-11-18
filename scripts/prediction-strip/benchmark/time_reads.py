"""The cost numbers of the benchmark of the predicted words: the size of each model file, and
the time of one model read on the PC (docs/prediction-strip-benchmark-design.md, "Cost").

One scorer process with 2 threads reads the next-token block of 200 texts of the mobile dev
half, one after the other, while no other job runs. For a model given with --requests, the
script also times the request of the word order M+R: the full log probability of 8 words after
the same texts.

The script writes scripts/prediction-strip/benchmark/results/cost.json.

Usage, in WSL, from the repository root:
    uv run --with numpy python scripts/prediction-strip/benchmark/time_reads.py --lm LM_SCORE \
        --model shipped=MODEL.gguf --model base135=MODEL.gguf --requests shipped
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import blocks as block_store  # noqa: E402
import core  # noqa: E402
from simulate import RESULTS  # noqa: E402
from tables import Tables  # noqa: E402

TEXTS = 200
THREADS = 2
WORDS = 8


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lm", required=True)
    parser.add_argument("--model", action="append", required=True, help="NAME=FILE, one per model file")
    parser.add_argument("--requests", action="append", default=[], help="the name of a model file that also times the request of M+R")
    args = parser.parse_args()
    states = core.states_of("mobile", "dev")
    contexts, _ = states.contexts()
    filled = [context for context in contexts if context]
    step = len(filled) // TEXTS
    sample = filled[::step][:TEXTS]
    if len(sample) != TEXTS:
        raise SystemExit(f"the mobile dev half gives {len(sample)} texts, and the script needs {TEXTS}")
    result = {"texts": TEXTS, "threads": THREADS, "models": {}}
    for pair in args.model:
        name, _, path = pair.partition("=")
        scorer = block_store.Scorer(args.lm, path, THREADS, core.BENCH / f"time_reads.{name}.lm_score.log")
        scorer.next_tokens(sample[0])   # the first read also loads the weights
        scorer.seconds.clear()
        blocks = [scorer.next_tokens(context) for context in sample]
        reads = np.array(scorer.seconds) * 1000
        entry = {"file": path, "bytes": Path(path).stat().st_size, "vocabulary": scorer.vocabulary,
                 "read_ms_median": float(np.median(reads)), "read_ms_p95": float(np.percentile(reads, 95))}
        if name in args.requests:
            tables = Tables(core.BENCH / "tables" / name)
            first = np.asarray(tables.first["spaced"])[:, 0]
            share = np.asarray(tables.share["spaced"])[:, 0]
            times = []
            for context, block in zip(sample, blocks):
                values = np.append(block, -np.inf)[first] + share
                words = [tables.forms[int(number)][0] for number in np.argsort(-values)[:WORDS]]
                began = time.monotonic()
                scorer.exact(context, words)
                times.append((time.monotonic() - began) * 1000)
            entry["request_ms_median"] = float(np.median(times))
            entry["request_ms_p95"] = float(np.percentile(times, 95))
        scorer.close()
        result["models"][name] = entry
        print(name, json.dumps(entry), flush=True)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "cost.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
