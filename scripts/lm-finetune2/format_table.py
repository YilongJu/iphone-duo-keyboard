"""Prints the selection scores of the file formats of wsl_formats.sh, each at its own tuned setting.

Usage, on Linux: python3 scripts/lm-finetune2/format_table.py --results ~/lmft2/results --formats ~/lmft2/formats
"""
import argparse
import json
import re
from pathlib import Path

FORMATS = ["f16", "Q8_0", "Q5_K_M", "Q4_K_M", "Q4_K_M-imatrix"]
# The plain Q4_K_M files were scored under their arm names.
PLAIN = {"ship": "smollm2-lora-seed1-calibrated", "mix": "smollm2-lora-mix-seed1"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--formats", type=Path, required=True)
    arguments = parser.parse_args()
    seconds = {}
    for line in (arguments.formats / "timing.txt").read_text(encoding="utf-8").splitlines():
        match = re.match(r"(fmt-\S+)\.gguf run \d: lm_score: \d+ tokens read, ([0-9.]+) ms", line)
        seconds.setdefault(match.group(1), []).append(float(match.group(2)) / 1000)
    rows = []
    for arm in ("ship", "mix"):
        base = sum(seconds[f"fmt-{arm}-Q4_K_M"]) / 2
        for name in FORMATS:
            folder = PLAIN[arm] if name == "Q4_K_M" else f"fmt-{arm}-{name}"
            result = json.loads((arguments.results / folder / "result.json").read_text(encoding="utf-8"))
            sets = result["select"]["tuned"]["sets"]
            setting = result["tuning"]["setting"]
            file = arguments.formats / f"fmt-{arm}-{name}.gguf"
            github = sets["github"]["categories"]
            rows.append([arm, name, f"{file.stat().st_size:,}",
                         f"{setting['weight']}; {setting['margin_from_typed']}, {setting['margin_to_typed']}, {setting['margin_other']}; {setting['space_after']}",
                         result["tuning"]["tune"]["right"], result["tuning"]["tune"]["changed_words"],
                         sets["dev"]["right"], sets["dev"]["non_word_slips"]["right"], sets["dev"]["groups"]["real_word_slip"]["right"],
                         sets["stream"]["stream"]["changed_words"], sets["published_dev"]["right"],
                         github["github_misspelling"]["right"], github["github_real_word"]["right"],
                         f"{sum(seconds[f'fmt-{arm}-{name}']) / 2 / base:.2f}"])
    header = ["file", "format", "bytes", "setting", "tune right /6,748", "tune changed words /8,487", "dev right /6,799",
              "dev non-word slips /5,097", "dev real-word slips /300", "select changed words /8,439", "published dev /751",
              "github misspelling /1,500", "github real word /1,000", "time against Q4_K_M"]
    print("| " + " | ".join(header) + " |")
    print("| " + " | ".join("---" for _ in header) + " |")
    for row in rows:
        print("| " + " | ".join(str(cell) for cell in row) + " |")


if __name__ == "__main__":
    main()
