"""Check of the writing rules on the results document of the benchmark of the predicted words.

The check reads the prose of a Markdown file: the lines outside code blocks, tables and
headings. It fails for:
  - an em-dash, as a character or as an HTML entity;
  - a sentence of more than 20 words;
  - a contrast of the kind "not X, but Y";
  - a word of the list LONG_WORDS, which has a plain word in its place;
  - a word of the list FIGURES, which holds figures of speech that stand in for a plain verb;
  - a word of the list JUDGING, which holds words that judge and do not measure.
The check does not see whether a caption gives the takeaway of its table, or whether one idea
keeps one name. A person reads the document for those rules.

Usage:
    python3 scripts/prediction-strip/benchmark/check_doc.py docs/prediction-strip-benchmark-results.md
"""
import re
import sys
from pathlib import Path

MOST_WORDS = 20
LONG_WORDS = ("approximately", "sufficient", "utilise", "utilize", "prior to", "methodology", "commence", "leverage")
FIGURES = ("drift", "slide", "bury", "cliff", "hill", "sharpen", "story", "landscape", "journey")
JUDGING = ("fail", "succeed", "win", "beat", "best", "worst", "worthless")
CONTRAST = re.compile(r"\bnot\b[^.;:]*,\s+but\b|\b(?:is|are) not\b[^.]*\.\s+(?:It|They) (?:is|are)\b", re.IGNORECASE)


def prose(text: str) -> list[tuple[int, str]]:
    """The paragraphs and list items of prose, each with the number of its first line."""
    blocks, lines, start, in_code = [], [], 0, False

    def close() -> None:
        if lines:
            blocks.append((start, " ".join(lines)))
            lines.clear()

    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith("```"):
            in_code = not in_code
            close()
            continue
        if in_code or line.startswith("|") or line.startswith("#") or not line.strip():
            close()
            continue
        if re.match(r"\s*(?:[-*]|\d+\.)\s+", line):
            close()
        if not lines:
            start = number
        lines.append(line.strip())
    close()
    return blocks


def failures_of(text: str) -> list[str]:
    failures = []
    if "—" in text or "&mdash;" in text or "&#8212;" in text:
        failures.append("the file holds an em-dash")
    for start, block in prose(text):
        plain = re.sub(r"`[^`]*`", "CODE", block)
        plain = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", plain)
        plain = re.sub(r"^(?:[-*]|\d+\.)\s+", "", plain)
        plain = plain.replace("**", "")
        if CONTRAST.search(plain):
            failures.append(f"line {start}: a contrast of the kind 'not X, but Y'")
        lowered = plain.lower()
        for word in LONG_WORDS + FIGURES + JUDGING:
            if re.search(rf"\b{re.escape(word)}", lowered):
                failures.append(f"line {start}: the word {word!r}")
        for sentence in re.split(r"(?<=[.!?:])\s+(?=[A-Z0-9\"(`])", plain):
            count = len(sentence.split())
            if count > MOST_WORDS:
                failures.append(f"line {start}: a sentence of {count} words: {sentence[:70]}...")
    return failures


def main() -> None:
    path = Path(sys.argv[1])
    failures = failures_of(path.read_text(encoding="utf-8"))
    for failure in failures:
        print(failure)
    print(f"{path}: {len(failures)} failures of the writing rules")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
