"""Builds docs/prediction-strip-benchmark-results.md from the template results_template.md of
this folder and the numbers of the dev halves, and checks the writing rules on the result.

Marks of the template, each in two pairs of braces:
  table NAME                 the table NAME of report.py
  saved ORDER [WORDS] [SET]  saved key presses of a word order in percent, for a strip of WORDS
                             words (3 without it) and one text set (the mean of the sets without it)
  range ORDER [WORDS] [SET]  the same number with its 95% interval
  gap FIRST SECOND [SET]     saved key presses of FIRST minus those of SECOND in points, with
                             the paired 95% interval
  gap2 FIRST SECOND WORDS TYPIST  the same difference for a strip of WORDS words and the
                             typist who taps for TYPIST key presses or more, as the mean of the sets
  choice                     the word order that the decision rule gives
  needed                     the deciding number of the choice plus the 1.0 point of rule 2
ORDER is "E", "choice", or a name of simulate.py such as shipped|typed|engine|0.3.

The build stops when a number of the list CHECKED in the template's first comment differs from
the numbers, so a sentence that was written for other numbers cannot stay.

Usage, in WSL, from the repository root:
    uv run --with numpy python scripts/prediction-strip/benchmark/build_doc.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import check_doc  # noqa: E402
import core  # noqa: E402
import report  # noqa: E402

TEMPLATE = Path(__file__).with_name("results_template.md")
DOCUMENT = core.ROOT / "docs" / "prediction-strip-benchmark-results.md"


def main() -> None:
    numbers = report.Numbers("dev")
    tables = report.tables(numbers)
    choice, _ = numbers.decision()

    def order(name: str) -> str:
        return choice if name == "choice" else name

    def where(rest: list[str]) -> tuple[int, str]:
        words, text_set = 3, "mean"
        for field in rest:
            if field.isdigit():
                words = int(field)
            else:
                text_set = field
        return words, text_set

    def fill(match: re.Match) -> str:
        kind, *rest = match.group(1).split()
        if kind == "table":
            return "\n".join(tables[" ".join(rest)])
        if kind == "choice":
            return report.title(choice)
        if kind == "needed":
            return f"{100 * numbers.number_of(choice) + report.NEEDED_POINTS:.1f}"
        if kind in ("saved", "range"):
            words, text_set = where(rest[1:])
            if kind == "range":
                return numbers.saved(order(rest[0]), words, 1, text_set)
            return f"{100 * numbers.entry(order(rest[0]), words, 1, text_set)[0]:.1f}"
        if kind == "gap":
            text_set = rest[2] if len(rest) > 2 else None
            return numbers.difference(order(rest[0]), order(rest[1]), text_set=text_set)
        if kind == "gap2":
            return numbers.difference(order(rest[0]), order(rest[1]), words=int(rest[2]), typist=int(rest[3]))
        raise SystemExit(f"unknown mark of the template: {match.group(0)}")

    template = TEMPLATE.read_text(encoding="utf-8")
    header = re.match(r"<!--(.*?)-->\n", template, re.DOTALL)
    if header is None:
        raise SystemExit(f"{TEMPLATE} must start with a comment that holds the list CHECKED")
    for line in header.group(1).splitlines():
        if "=" in line:
            mark, _, expected = line.partition("=")
            got = re.sub(r"\{\{(.*?)\}\}", fill, mark.strip())
            if got != expected.strip():
                raise SystemExit(f"the template was written for {mark.strip()} = {expected.strip()}, and the numbers give {got}")
    text = re.sub(r"\{\{(.*?)\}\}", fill, template[header.end():])
    failures = check_doc.failures_of(text)
    for failure in failures:
        print(failure)
    if failures:
        raise SystemExit(f"{len(failures)} failures of the writing rules, so {DOCUMENT} stays as it was")
    DOCUMENT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {DOCUMENT}")


if __name__ == "__main__":
    main()
