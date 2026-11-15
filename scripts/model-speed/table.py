"""Prints the table of the speed runs of one folder, for docs/model-speed-results.md.

Usage: python3 table.py OUT_DIR REFERENCE_DIR
  OUT_DIR        holds the runs of speed_cli or check_coreml.py: NAME.summary, NAME.times and
                 NAME.answers, where NAME is MODEL.TYPE.RUNTIME
  REFERENCE_DIR  scripts/model-speed/reference: MODEL.Q8_0.answers, and
                 shipped.Q4_K_M.b4846.answers for the keyboard's own file
Prints one Markdown row per run, in milliseconds, over the requests after the first.
"""

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from summarize import agreement, read_answers, stats  # noqa: E402


def main():
    out = pathlib.Path(sys.argv[1])
    references = pathlib.Path(sys.argv[2])
    print("| run | request mean | request median | request p95 | candidates mean | candidates median | "
          "candidates p95 | window mean | first request | load | reuse share | agreement |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for summary_path in sorted(out.glob("*.summary")):
        name = summary_path.name[: -len(".summary")]
        match = re.match(r"^(.+?)\.(Q[0-9A-Z_]+|coreml-.+)", name)
        if match is None:
            raise SystemExit(f"the run {name} is not MODEL.TYPE.RUNTIME")
        model = match.group(1)
        reference = references / ("shipped.Q4_K_M.b4846.answers" if model == "shipped" else f"{model}.Q8_0.answers")
        summary = dict(line.partition(" ")[::2] for line in summary_path.read_text().splitlines())
        rows = [line.split() for line in out.joinpath(name + ".times").read_text().splitlines()][1:]
        request = stats([float(row[4]) for row in rows])
        candidates = stats([float(row[3]) for row in rows])
        window = stats([float(row[2]) for row in rows])
        share = int(summary["window_tokens_reused"]) / int(summary["window_tokens"])
        agree = agreement(read_answers(out / (name + ".answers")), read_answers(reference))
        print(f"| {name} | {request['mean']:.1f} | {request['median']:.1f} | {request['p95']:.1f} | "
              f"{candidates['mean']:.1f} | {candidates['median']:.1f} | {candidates['p95']:.1f} | {window['mean']:.1f} | "
              f"{float(summary['first_request_ms']):.1f} | {float(summary['load_ms']):.0f} | {100 * share:.1f}% | "
              f"{100 * agree:.1f}% |")


if __name__ == "__main__":
    main()
