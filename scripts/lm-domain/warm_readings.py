"""Fills the file of engine readings that score_model.py reads, with several processes.

One call of the engine for one typed span takes about 0.1 s with the supplement on, and the
sets of the harness hold about 150,000 spans. This script types every tuning and evaluation set
with the engine alone and with the perfect chooser, in --workers processes, and writes every
reading to DATA/engine-readings.pickle. score_model.py then reads the file and asks the engine
only for the few spans that a model's own choices add.

Usage, from the repository root, on Linux:
    python3 scripts/lm-domain/warm_readings.py --shim ~/lmdom/bin/libduo_shim.so --data build/lm-domain/data --workers 8
"""
import argparse
import multiprocessing
import os
import pickle
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lm-domain"))
import harness  # noqa: E402
import rerank  # noqa: E402

typist = None


def start_worker(shim: str) -> None:
    global typist
    typist = harness.Typist(Path(shim))


def readings_of_chunk(cases: list[dict]) -> dict:
    for case in cases:
        typist.type(case, rerank.engine_choice)
        typist.type(case, harness.perfect_chooser(case))
    return dict(typist.engine.cache)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--extra-cases", type=Path, nargs="*", default=[], help="more case files to type, as a held-out set")
    arguments = parser.parse_args()
    started = time.monotonic()
    cases = []
    for which in ("tune", "evaluation"):
        for entry in harness.load_sets(arguments.data, which).values():
            cases += entry["cases"]
    cases += rerank.load_cases(arguments.extra_cases)
    # Long cases first, so the chunks end at about the same time.
    cases.sort(key=lambda case: -len(case["typed"]))
    chunks = [cases[index::arguments.workers * 16] for index in range(arguments.workers * 16)]
    reference = harness.Typist(arguments.shim, readings_file=arguments.data / "engine-readings.pickle")
    merged = dict(reference.engine.cache)
    print(f"{len(cases)} cases, {len(merged)} spans already in the file", flush=True)
    with multiprocessing.Pool(arguments.workers, initializer=start_worker, initargs=(str(arguments.shim),)) as pool:
        for number, cache in enumerate(pool.imap_unordered(readings_of_chunk, chunks)):
            merged.update(cache)
            if number % 16 == 0:
                print(f"chunk {number + 1} of {len(chunks)}, {len(merged)} spans, {time.monotonic() - started:.0f} s", flush=True)
    path = arguments.data / "engine-readings.pickle"
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as file:
        pickle.dump((reference.readings_key, merged), file, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(temporary, path)
    print(f"wrote {path}: {len(merged)} spans in {time.monotonic() - started:.0f} s", flush=True)


if __name__ == "__main__":
    main()
