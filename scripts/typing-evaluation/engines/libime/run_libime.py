"""Runs the libime adapter over the Pinyin test cases and writes one output file per engine name.

Usage, from the repository root, after building libime_adapter:
    python3 scripts/typing-evaluation/engines/libime/run_libime.py \
        --adapter build/libime-apt/adapter/libime_adapter \
        --dict /usr/share/libime/sc.dict --lm /usr/lib/x86_64-linux-gnu/libime/zh_CN.lm \
        --engine libime-none=none --engine libime-commontypo=commontypo --halves dev test \
        --jobs 4 --address-layout fixed

Each --engine argument is ENGINE_NAME=ADAPTER_MODE. For each engine name and half the script writes
    build/typing-evaluation/ENGINE_NAME/pinyin.HALF.jsonl      the case id and the engine's output
    build/typing-evaluation/ENGINE_NAME/pinyin.HALF.run.json   the adapter's run statistics
The script starts one adapter process per engine name and half, and runs --jobs of them at a time.

--address-layout fixed starts the adapter through "setarch -R" with a fixed environment, so the
process gets the same memory addresses in every run. --address-layout random starts the adapter
the normal way. check_repeatability.py measures the outputs that differ between two processes
under each layout.
"""
import argparse
import hashlib
import json
import os
import platform
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CASES = ROOT / "scripts" / "typing-evaluation" / "cases"
OUTPUT = ROOT / "build" / "typing-evaluation"
STATS_PREFIX = "ADAPTER_STATS "


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_cases(half: str) -> list[dict]:
    return [json.loads(line) for line in (CASES / f"pinyin.{half}.jsonl").read_text(encoding="utf-8").splitlines() if line]


def run_adapter(adapter: Path, dictionary: Path, language_model: Path, mode: str, cases: list[dict],
                address_layout: str, label: str) -> tuple[dict[str, str], dict, list[str]]:
    """Types the cases into one adapter process.

    Returns the outputs by case id, the adapter's statistics, and the other lines the adapter wrote to stderr.
    """
    command = [str(adapter), "--dict", str(dictionary), "--lm", str(language_model), "--mode", mode]
    environment = None
    if address_layout == "fixed":
        # setarch -R switches address randomization off for this one process. The environment is
        # fixed too, because its size moves the stack.
        command = ["setarch", platform.machine(), "-R", *command]
        environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
        if "LD_LIBRARY_PATH" in os.environ:
            environment["LD_LIBRARY_PATH"] = os.environ["LD_LIBRARY_PATH"]
    elif address_layout != "random":
        raise ValueError(f"address layout must be fixed or random, got {address_layout!r}")
    lines = "".join(f"{case['id']}\t{case['typed']}\n" for case in cases)
    completed = subprocess.run(command, input=lines, capture_output=True, text=True, encoding="utf-8", env=environment)
    if completed.returncode != 0:
        raise RuntimeError(f"{label}: the adapter exited with {completed.returncode}\n{completed.stderr[-4000:]}")

    outputs = {}
    for line in completed.stdout.split("\n"):
        if not line:
            continue
        case_id, separator, output = line.partition("\t")
        if not separator:
            raise RuntimeError(f"{label}: output line without a tab: {line!r}")
        if case_id in outputs:
            raise RuntimeError(f"{label}: two outputs for case {case_id}")
        outputs[case_id] = output
    wanted = {case["id"] for case in cases}
    if set(outputs) != wanted:
        raise RuntimeError(f"{label}: {len(wanted - set(outputs))} cases without an output, "
                           f"{len(set(outputs) - wanted)} outputs without a case")

    stats_lines = [line for line in completed.stderr.splitlines() if line.startswith(STATS_PREFIX)]
    if len(stats_lines) != 1:
        raise RuntimeError(f"{label}: expected one statistics line, got {len(stats_lines)}\n{completed.stderr[-4000:]}")
    stats = json.loads(stats_lines[0][len(STATS_PREFIX):])
    other_stderr = [line for line in completed.stderr.splitlines() if not line.startswith(STATS_PREFIX)]
    return outputs, stats, other_stderr


def run_one(adapter: Path, dictionary: Path, language_model: Path, engine: str, mode: str, half: str, files: dict,
            address_layout: str) -> dict:
    cases = load_cases(half)
    outputs, stats, other_stderr = run_adapter(adapter, dictionary, language_model, mode, cases, address_layout,
                                               f"{engine} on {half}")
    wanted = [case["id"] for case in cases]

    folder = OUTPUT / engine
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"pinyin.{half}.jsonl").write_text(
        "".join(json.dumps({"id": case_id, "output": outputs[case_id]}, ensure_ascii=False) + "\n" for case_id in wanted),
        encoding="utf-8", newline="\n")
    run = {"engine": engine, "half": half, "adapter_mode": mode, "adapter": str(adapter),
           "address_layout": address_layout, **files, "statistics": stats,
           "empty_outputs": sum(1 for case_id in wanted if not outputs[case_id]),
           "outputs_with_a_latin_letter": sum(1 for case_id in wanted if any("a" <= ch <= "z" for ch in outputs[case_id])),
           "adapter_stderr_lines": other_stderr[:20]}
    (folder / f"pinyin.{half}.run.json").write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    return run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--dict", type=Path, required=True, dest="dictionary")
    parser.add_argument("--lm", type=Path, required=True, dest="language_model")
    parser.add_argument("--engine", action="append", required=True, help="ENGINE_NAME=ADAPTER_MODE, may repeat")
    parser.add_argument("--halves", nargs="+", choices=["dev", "test"], required=True)
    parser.add_argument("--jobs", type=int, required=True)
    parser.add_argument("--address-layout", choices=["fixed", "random"], required=True)
    arguments = parser.parse_args()

    for path in (arguments.adapter, arguments.dictionary, arguments.language_model):
        if not path.is_file():
            raise FileNotFoundError(path)
    files = {
        "dictionary": str(arguments.dictionary), "dictionary_bytes": arguments.dictionary.stat().st_size,
        "dictionary_sha256": sha256(arguments.dictionary),
        "language_model": str(arguments.language_model), "language_model_bytes": arguments.language_model.stat().st_size,
        "language_model_sha256": sha256(arguments.language_model),
    }
    engines = []
    for item in arguments.engine:
        name, separator, mode = item.partition("=")
        if not separator or not name or not mode:
            raise ValueError(f"--engine needs ENGINE_NAME=ADAPTER_MODE, got {item!r}")
        engines.append((name, mode))

    with ThreadPoolExecutor(max_workers=arguments.jobs) as pool:
        futures = [pool.submit(run_one, arguments.adapter, arguments.dictionary, arguments.language_model, name, mode, half,
                               files, arguments.address_layout)
                   for name, mode in engines for half in arguments.halves]
        runs = [future.result() for future in futures]
    for run in runs:
        stats = run["statistics"]
        per_letter = 1000 * stats["typing_seconds"] / stats["letters"]
        print(f"{run['engine']} on pinyin.{run['half']}: mode {run['adapter_mode']}, address layout {run['address_layout']}, "
              f"libime {stats['libime_version']}, "
              f"flags {'+'.join(stats['flags']) or 'None'} (value {stats['flags_value']}), "
              f"{stats['cases']} cases, {stats['letters']} letters, {stats['typing_seconds']:.1f} s typing, "
              f"{per_letter:.3f} ms per letter, slowest case {stats['slowest_case_milliseconds']:.1f} ms, "
              f"cases with more than one pick {stats['cases_with_more_than_one_pick']}, "
              f"sentence differs from picks {stats['sentence_differs_from_picks']}, "
              f"bulk typing differs {stats['bulk_typing_differs']}, empty outputs {run['empty_outputs']}, "
              f"outputs with a Latin letter {run['outputs_with_a_latin_letter']}")
        for line in run["adapter_stderr_lines"]:
            print(f"    adapter stderr: {line}")


if __name__ == "__main__":
    main()
