"""Sweep of the call size of the keyboard's scorer on the macOS runner: which split of a call
moves the numbers, and how often a split moves them over all requests of run 43142371994.

    sweep.py requests OUT.tsv     writes the requests of the sweep, and OUT.tsv.names
    sweep.py calls DIR            the table of the call-size sweep, from DIR/sweep-c*.answers
                                  (full precision) and DIR/sweep.tokens
    sweep.py all DIR              the table over all requests, from DIR/all-c31.answers,
                                  DIR/all-c256.answers (full precision) and DIR/all.tokens

The requests of the sweep: the original request, the prefixes " egg" and " egg nn" of the
candidate " egg nns" alone, and the original with the first K words of the context taken off,
K = 1 to 12. The reference is a build with calls of 256 tokens, which reads each context and the
candidates of a request in one call each, as lm_score does.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe import CANDIDATES, CONTEXT  # noqa: E402

REFERENCE = 256


def sweep_requests():
    rows = [("original", CONTEXT, CANDIDATES), ("egg", CONTEXT, ["egg"]), ("egg nn", CONTEXT, ["egg nn"]),
            ("egg nns", CONTEXT, ["egg nns"])]
    words = CONTEXT.split(" ")
    rows += [(f"drop {k}", " ".join(words[k:]), CANDIDATES) for k in range(1, 13)]
    return rows


def read(path):
    return [[tuple(float(v) for v in field.split(" ")) for field in line.split("\t")]
            for line in Path(path).read_text(encoding="utf-8").splitlines()]


def token_counts(path):
    """The count of tokens the model reads for the context, start token included, and for all
    candidates together, per request line of an lm_score tokens file."""
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        rows.append((len(fields[0].split(" ")), sum(len(field.split(" ")) for field in fields[1:])))
    return rows


def last_call(tokens: int, size: int) -> int:
    """The token count of the last call of a part of `tokens` tokens with calls of `size` tokens at
    most, as call_size of LanguageModel/duo_lm_scorer.c splits the part."""
    calls = -(-tokens // size)
    return tokens // calls


def largest(a, b):
    return max(max(abs(x[0] - y[0]), abs(x[1] - y[1])) for x, y in zip(a, b))


def main():
    command, target = sys.argv[1], Path(sys.argv[2])
    if command == "requests":
        rows = sweep_requests()
        target.write_text("".join("\t".join([c, *cs]) + "\n" for _, c, cs in rows), encoding="utf-8", newline="\n")
        Path(str(target) + ".names").write_text("".join(n + "\n" for n, _, _ in rows), encoding="utf-8", newline="\n")
        return
    if command == "calls":
        rows = sweep_requests()
        counts = token_counts(target / "sweep.tokens")
        reference = read(target / f"sweep-c{REFERENCE}.answers")
        sizes = sorted(int(p.stem.split("-c")[1]) for p in target.glob("sweep-c*.answers") if int(p.stem.split("-c")[1]) != REFERENCE)
        print(f"Largest difference of a number from the build with calls of {REFERENCE} tokens, full precision.")
        print("Each cell also gives the token count of the last call of the context, after a slash.")
        print()
        print("| Request | context tokens | candidate tokens | " + " | ".join(f"c{s}" for s in sizes) + " |")
        print("| --- | --- | --- |" + " --- |" * len(sizes))
        for index, (name, _, _) in enumerate(rows):
            context, candidates = counts[index]
            cells = []
            for size in sizes:
                answers = read(target / f"sweep-c{size}.answers")
                last = last_call(context, size)
                cells.append(f"{largest(reference[index], answers[index]):.2g}/{last}")
            print(f"| {name} | {context} | {candidates} | " + " | ".join(cells) + " |")
        return
    if command == "all":
        counts = token_counts(target / "all.tokens")
        a, b = read(target / "all-c256.answers"), read(target / "all-c31.answers")
        if not (len(a) == len(b) == len(counts)):
            raise SystemExit("the files hold other counts of requests")
        groups = {}
        for index, (context, candidates) in enumerate(counts):
            # A part of one token more than a multiple of 31 is the part that a split into full
            # calls ends with a call of one token.
            key = ("context in several calls" if context > 31 else "context in one call",
                   "one token more than full calls" if context > 31 and context % 31 == 1 else "other context",
                   "one token more than full calls" if candidates > 31 and candidates % 31 == 1 else "other candidates")
            entry = groups.setdefault(key, [0, 0, 0, 0.0])
            difference = largest(a[index], b[index])
            entry[0] += 1
            entry[1] += difference > 0
            entry[2] += difference >= 0.000005
            entry[3] = max(entry[3], difference)
        print("All requests of run 43142371994 on the macOS runner: calls of 31 tokens against calls of 256, full precision.")
        print()
        print("| Context | Context tokens | Candidate tokens | requests | any difference | difference of 0.000005 or more | largest |")
        print("| --- | --- | --- | --- | --- | --- | --- |")
        for key in sorted(groups):
            entry = groups[key]
            print(f"| {key[0]} | {key[1]} | {key[2]} | {entry[0]} | {entry[1]} | {entry[2]} | {entry[3]:.6f} |")
        return
    raise SystemExit(f"unknown command {command}")


if __name__ == "__main__":
    main()
