"""Check of the request whose answer depends on how the keyboard's scorer splits a context into calls.

The keyboard's scorer reads a long context in calls of 31 tokens at most. llama.cpp b4846
computes a call of one token with another routine than a call of two tokens or more, and on the
macOS runner the two routines differ in the last bits of their sums. The scorer therefore
splits a context into calls whose sizes differ by one token at most (call_size in
LanguageModel/duo_lm_scorer.c). The context below has 32 tokens, one more than a call. With a
last call of one token, the candidate " egg nns" gets -32.79410 on the macOS runner, and
lm_score gives -33.07924. This script writes that request and nearby requests, and then
compares the answers of several builds.

    probe.py requests OUT.tsv      writes the requests, one per line, and OUT.tsv.names with a
                                   name per request
    probe.py compare DIR           reads DIR/*.answers (one file per build) and DIR/tokens.txt,
                                   and prints a table of the differences. It stops with exit
                                   code 1 when the keyboard's scorer as it ships (scorer-c31)
                                   differs from lm_score (lm_score-u512) in any number.

The requests:
- original: the request of the run, 8 candidates.
- alone N: candidate N alone after the same context.
- reversed: the 8 candidates in the other order.
- drop K: the original with the first K words of the context taken off, K = 1 to 12.
"""
import sys
from pathlib import Path

CONTEXT = ("To bridge this gap, we propose SHiFT, which synergizes the reasoning power of LLMs with the "
           "structural representation capability of | ggnns |")
CANDIDATES = ["egg ms", "egg na", "egg nns", "ggnns", "gnn is", "gnn s", "gnns", "gunn's"]


def requests() -> list[tuple[str, str, list[str]]]:
    rows = [("original", CONTEXT, CANDIDATES)]
    rows += [(f"alone {index}", CONTEXT, [candidate]) for index, candidate in enumerate(CANDIDATES)]
    rows.append(("reversed", CONTEXT, CANDIDATES[::-1]))
    words = CONTEXT.split(" ")
    rows += [(f"drop {k}", " ".join(words[k:]), CANDIDATES) for k in range(1, 13)]
    return rows


def read_answers(path: Path) -> list[list[tuple[float, float]]]:
    return [[tuple(float(v) for v in field.split(" ")) for field in line.split("\t")]
            for line in path.read_text(encoding="utf-8").splitlines()]


def main():
    if sys.argv[1] == "requests":
        out = Path(sys.argv[2])
        rows = requests()
        out.write_text("".join("\t".join([context, *candidates]) + "\n" for _, context, candidates in rows),
                       encoding="utf-8", newline="\n")
        Path(str(out) + ".names").write_text("".join(name + "\n" for name, _, _ in rows), encoding="utf-8", newline="\n")
        return
    folder = Path(sys.argv[2])
    rows = requests()
    reference_name = "lm_score-u512"
    answers = {path.stem: read_answers(path) for path in sorted(folder.glob("*.answers"))}
    if reference_name not in answers:
        raise SystemExit(f"{folder} holds no {reference_name}.answers")
    reference = answers[reference_name]
    token_lines = (folder / "tokens.txt").read_text(encoding="utf-8").splitlines()
    print(f"Reference: {reference_name}. Each cell: the largest difference of a log probability from the reference,")
    print("and the candidate where it is. The token counts come from lm_score tokens.")
    print()
    builds = [name for name in answers if name != reference_name]
    print("| Request | context tokens with the start token | candidate tokens | " + " | ".join(builds) + " |")
    print("| --- | --- | --- |" + " --- |" * len(builds))
    for index, (name, _, candidates) in enumerate(rows):
        fields = token_lines[index].split("\t")
        context_count = len(fields[0].split(" "))
        lengths = [len(field.split(" ")) for field in fields[1:]]
        cells = []
        for build in builds:
            worst, where = 0.0, ""
            for place, (a, b) in enumerate(zip(reference[index], answers[build][index])):
                difference = max(abs(a[0] - b[0]), abs(a[1] - b[1]))
                if difference > worst:
                    worst, where = difference, candidates[place]
            cells.append(f"{worst:.5f}" + (f" ({where})" if worst > 0 else ""))
        print(f"| {name} | {context_count} | {','.join(map(str, lengths))} | " + " | ".join(cells) + " |")
    print()
    print("Answers of the original request, candidate \"egg nns\":")
    for build, values in answers.items():
        print(f"  {build}: {values[0][2]}")
    shipped = answers["scorer-c31"]
    if shipped != reference:
        print()
        print("The keyboard's scorer as it ships (calls of 31 tokens) differs from lm_score.")
        sys.exit(1)
    print()
    print("The keyboard's scorer as it ships (calls of 31 tokens) gives the numbers of lm_score.")


if __name__ == "__main__":
    main()
