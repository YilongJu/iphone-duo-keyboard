"""Writes scripts/lm-finetune2/README.md from readme-template.md and the tables of the held-out read.

The template holds the text. Each mark {{A}}, {{B}}, {{C}}, {{D}}, {{E}}, {{G}}, {{H}} takes the
table of that letter from holdout-summary.md (summarize2.py holdout), without its caption. {{PICK}}
takes the two tables of reports/pick.md.

Usage, in WSL, from the repository root:
    python3 scripts/lm-finetune2/write_readme.py --summary ~/lmft2/holdout/summary/holdout-summary.md
"""
import argparse
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


def tables(text: str) -> list[str]:
    """Every markdown table of a text, in order."""
    found, current = [], []
    for line in text.splitlines():
        if line.startswith("|"):
            current.append(line)
        elif current:
            found.append("\n".join(current))
            current = []
    if current:
        found.append("\n".join(current))
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    arguments = parser.parse_args()
    summary = arguments.summary.read_text(encoding="utf-8")
    parts = re.split(r"(?m)^Table ([A-H])\. ", summary)
    by_letter = {parts[i]: tables(parts[i + 1])[0] for i in range(1, len(parts), 2)}
    pick = tables((HERE / "reports" / "pick.md").read_text(encoding="utf-8"))
    text = (HERE / "readme-template.md").read_text(encoding="utf-8")
    for letter, table in by_letter.items():
        text = text.replace("{{" + letter + "}}", table)
    text = text.replace("{{PICK1}}", pick[0]).replace("{{PICK2}}", pick[1])
    left = re.findall(r"\{\{[A-Z0-9]+\}\}", text)
    if left:
        raise SystemExit(f"marks without a table: {left}")
    if "—" in text:
        raise SystemExit("the text holds an em-dash")
    (HERE / "README.md").write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote README.md, {len(text.splitlines())} lines")


if __name__ == "__main__":
    main()
