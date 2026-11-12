"""Checks the supplement of the typing engine (duo_lexicon_set_supplement in Engine/duo_engine.c)
through Engine/duo_cli.c, and the rule of the preferred capitals in scripts/lm-rerank/rerank.py.

The script builds a small supplement of its own, so the checks do not depend on the words of
the pack that ships. Each check names the behaviour it needs. The script stops with exit code 1
at the first check that does not hold. The engine before the supplement fails the first check,
because its duo_cli does not know the argument supplement=FILE.

Usage, from the repository root, after building Engine/duo_cli.c into build/engine/duo_cli:
    python3 scripts/domain-pack/check_supplement.py [--cli build/engine/duo_cli]
"""
import argparse
import math
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "typing-engine"))
sys.path.insert(0, str(ROOT / "scripts" / "lm-rerank"))
from lexicon_format import MODEL_MIXED, write_lexicon  # noqa: E402

LEXICON = ROOT / "Shared" / "lexicon-english.bin"
# word, Zipf frequency. "gpu" and "repo" are in the base lexicon, and the others are not.
WORDS = [("pytorch", 4.3), ("ultrathink", 4.5), ("ultracode", 4.5), ("llm", 5.4), ("llms", 5.2), ("evals", 3.7),
         ("gpu", 4.9), ("repo", 4.5), ("hyperparameters", 4.5), ("hardcoded", 3.8), ("backpropagation", 3.8)]
checks = 0


def check(condition: bool, text: str) -> None:
    global checks
    checks += 1
    if not condition:
        print(f"check_supplement: this does not hold: {text}")
        sys.exit(1)


def read(cli: Path, rows: list[tuple[str, str]], *arguments: str) -> list[str]:
    """The engine's text for each (previous word, typed text)."""
    lines = "".join(f"{index}\t{previous}\t{typed}\n" for index, (previous, typed) in enumerate(rows))
    done = subprocess.run([str(cli), "english", str(LEXICON), *arguments], input=lines, capture_output=True, text=True, encoding="utf-8")
    if done.returncode != 0:
        print(f"check_supplement: duo_cli {' '.join(arguments)} stopped with code {done.returncode}: {done.stderr.strip()}")
        sys.exit(1)
    return [line.split("\t", 1)[1] for line in done.stdout.splitlines()]


def check_engine(cli: Path) -> None:
    with tempfile.TemporaryDirectory() as folder:
        supplement = Path(folder) / "supplement.bin"
        write_lexicon(supplement, [(word, word, (zipf - 9) * math.log(10), 0.0) for word, zipf in sorted(WORDS)], {}, MODEL_MIXED)
        on = f"supplement={supplement}"

        def with_supplement(previous: str, typed: str) -> str:
            return read(cli, [(previous, typed)], on)[0]

        def without(previous: str, typed: str) -> str:
            return read(cli, [(previous, typed)])[0]

        # A word of the supplement stays as typed. The base lexicon alone changes these.
        for word, base_reading in (("pytorch", "porch"), ("ultrathink", "ultra think"), ("ultracode", "ultra code"),
                                   ("llm", "ll"), ("evals", "evils")):
            check(without("the", word) == base_reading, f"without the supplement, 'the {word}' reads as '{base_reading}'")
            check(with_supplement("the", word) == word, f"with the supplement, '{word}' after 'the' stays")
            check(with_supplement("", word) == word, f"with the supplement, '{word}' at the start stays")
        # A slip is corrected into a word of the supplement.
        for typed, word in (("pytorhc", "pytorch"), ("pytotch", "pytorch"), ("ultrathnik", "ultrathink"),
                            ("ultrathinl", "ultrathink"), ("ultracoed", "ultracode"), ("gpuu", "gpu"), ("llmms", "llms")):
            check(with_supplement("the", typed) == word, f"with the supplement, '{typed}' reads as '{word}'")
        check(without("the", "pytorhc") != "pytorch", "without the supplement, 'pytorhc' does not read as 'pytorch'")
        # Everyday words near a word of the supplement stay, and their slips go to them.
        for word in ("ultra", "ultrathin", "ultrasound", "porch", "all", "evils", "rope", "repo", "gpu"):
            check(with_supplement("the", word) == word, f"with the supplement, '{word}' stays")
        for typed, word in (("teh", "the"), ("becuase", "because"), ("porhc", "porch")):
            check(with_supplement("", typed) == word, f"with the supplement, '{typed}' still reads as '{word}'")
        # A word that only the supplement holds is a known word before the next word.
        check(with_supplement("pytorch", "modle") == "model", "after 'pytorch', 'modle' reads as 'model'")
        check(with_supplement("", "pytorch modle") == "pytorch model", "'pytorch modle' reads as 'pytorch model'")
        check(with_supplement("", "ultrathink about") == "ultrathink about", "'ultrathink about' stays")
        # The space bar inside and beside a word of the supplement.
        check(with_supplement("", "ultra think") == "ultra think", "'ultra think' typed as two words stays two words")
        check(with_supplement("the", "pyt orch") == "pytorch", "'pyt orch' reads as 'pytorch'")
        check(with_supplement("", "thepytorch") == "the pytorch", "'thepytorch' reads as 'the pytorch'")
        # Two typed known words stay two words, also when the supplement holds them as one word.
        for previous, words in (("more", "hyper parameters"), ("the", "hard coded"), ("the", "back propagation")):
            check(with_supplement(previous, words) == words, f"with the supplement, '{words}' typed as two words stays two words")
        check(with_supplement("the", "hyperparameters") == "hyperparameters", "'hyperparameters' typed as one word stays one word")
        check(with_supplement("the", "hyper parameers") == "hyperparameters" or with_supplement("the", "hyper parameers") == "hyper parameters",
              "'hyper parameers' reads as a form of the word")
        # A symbol key beside a word of the supplement, typed on purpose, stays.
        check(with_supplement("", "[pytorch") == "[pytorch", "'[pytorch' stays")
        # A word that both hold keeps the pairs of the base lexicon: the outputs agree with the
        # base lexicon on text without a word of the supplement.
        rows = [("", "i went to teh store"), ("how", "aer you"), ("", "it was a good ide"), ("see", "you tomorow")]
        check(read(cli, rows) == read(cli, rows, on), "text without a word of the supplement reads the same with it")

        # A file with word pairs is not a supplement.
        refused = subprocess.run([str(cli), "english", str(LEXICON), f"supplement={LEXICON}"], input="", capture_output=True, text=True)
        check(refused.returncode == 1 and "not a valid supplement" in refused.stderr,
              "duo_cli refuses a supplement that holds word pairs")


def check_capitals() -> None:
    import rerank
    with tempfile.TemporaryDirectory() as folder:
        table = Path(folder) / "table.tsv"
        table.write_text("word\tzipf\tpreferred\teveryday\tnew\n"
                         "gpu\t4.9\tGPU\t0\t0\ngpu's\t3.5\tGPU's\t0\t0\npytorch\t4.3\tPyTorch\t0\t1\nvllm\t4.6\tvLLM\t0\t1\n"
                         "rag\t4.6\tRAG\t1\t0\ntokenizer\t4.1\t\t0\t1\nnextjs\t4.5\tNext.js\t0\t1\nxcode\t4.5\tXcode\t0\t1\n",
                         encoding="utf-8")
        capitals = rerank.PreferredCapitals(table)
    cases = [
        # word after restoring_capitals, typed, the keyboard's own capital, expected
        ("gpu", "gpu", False, "gpu"), ("pytorch", "pytorch", False, "pytorch"),          # lower case stays
        ("Gpu", "Gpu", False, "GPU"), ("Pytorch", "Pytorch", False, "PyTorch"),          # a typed capital
        ("Gpu", "Gpu", True, "GPU"), ("Pytorch", "Pytorch", True, "PyTorch"),            # the start of a sentence
        ("Vllm", "Vllm", True, "vLLM"), ("Vllm", "Vllm", False, "vLLM"),
        ("Pytorch", "Pytorhc", False, "PyTorch"), ("pytorch", "pytorhc", False, "pytorch"),  # a corrected slip
        ("Pytorch", "Pytorc", True, "PyTorch"), ("pytorch", "pytorcch", False, "pytorch"),
        ("pyTorch", "pyTorch", False, "PyTorch"), ("gPu", "gPu", False, "GPU"),          # a capital inside
        ("PYTORCH", "PYTORCH", False, "PYTORCH"), ("PyTorch", "PyTorch", False, "PyTorch"), ("VLLM", "VLLM", False, "VLLM"),
        ("PYTORCh", "PYTORCh", False, "PYTORCH"), ("PYtorch", "PYtorch", False, "PyTorch"),  # the nearer form
        ("VLlm", "VLlm", False, "VLLM"), ("vLLm", "vLLm", False, "vLLM"),
        ("Rag", "Rag", True, "Rag"), ("Rag", "Rag", False, "Rag"), ("rag", "rag", False, "rag"),  # an everyday word
        ("RAG", "RAG", False, "RAG"), ("rAg", "rAg", False, "RAG"), ("RAg", "RAg", False, "RAG"),
        ("Tokenizer", "Tokenizer", False, "Tokenizer"), ("tokenizer", "tokenizer", False, "tokenizer"),  # no preferred form
        ("Monday", "Monday", False, "Monday"), ("It", "It", True, "It"), ("us", "us", False, "us"),      # outside the table
        ("Gpu's", "Gpu's", False, "GPU's"), ("gpu's", "gpu's", False, "gpu's"), ("Gpu's", "Gpus", True, "GPU's"),  # a possessive
        ("GPU'S", "GPU'S", False, "GPU'S"),
        # A preferred form with a sign between its letters, and one that equals the plain capital.
        ("nextjs", "nextjs", False, "nextjs"), ("Nextjs", "Nextjs", False, "Next.js"), ("Nextjs", "Nextjs", True, "Next.js"),
        ("NEXTJS", "NEXTJS", False, "NEXTJS"), ("NextJS", "NextJS", False, "Next.js"), ("Nextjs", "Nextjd", False, "Next.js"),
        ("nextjs", "nextjd", False, "nextjs"), ("Xcode", "Xcode", True, "Xcode"), ("XCode", "XCode", False, "Xcode"),
        ("xcode", "xcode", False, "xcode"), ("XCODE", "XCODE", False, "XCODE"),
        # A symbol key in place of the first letter: the keyboard typed the capital by itself, or typed none.
        ("Pytorch", "[ytorch", False, "PyTorch"), ("pytorch", "[ytorch", False, "pytorch"),
    ]
    for word, typed, automatic, expected in cases:
        got = capitals.form(word, typed, automatic)
        check(got == expected, f"the form of {typed!r} ({'the keyboard' if automatic else 'the person'} typed the first "
                               f"capital) is {expected!r}, and the rule gives {got!r}")
    check(capitals.latch("pytorch is", "Pytorhc is", "") == "PyTorch is", "a slip at the start of the field gets the preferred form")
    check(capitals.latch("the gpu", "the gpu", "I use ") == "the gpu", "lower case inside a sentence stays")
    check(capitals.latch("pytorch", "Py torch", "I use ") == "PyTorch", "a joined word takes the capital of the first typed word")
    check(rerank.restoring_capitals("pytorch is", "Pytorhc is") == "Pytorch is", "restoring_capitals keeps the typed capital")

    def reading(text, as_typed=False, chosen=False):
        return {"text": text, "as_typed": as_typed, "chosen": chosen}

    def kept(readings, typed):
        return [r["text"] for r in capitals.keeping_new_words(readings, typed)]

    check(kept([reading("pytorch", True, True), reading("porch"), reading("torch")], "pytorch") == ["pytorch"],
          "the model may not change a typed word that is new in the pack")
    check(kept([reading("the pytorch", True), reading("the porch", chosen=True), reading("they pytorch"), reading("the torch")],
               "the pytorch") == ["the pytorch", "the porch", "they pytorch"],
          "the engine's choice and a reading that keeps the new word stay")
    check(kept([reading("pytorhc", True), reading("pytorch", chosen=True), reading("porch")], "pytorhc")
          == ["pytorhc", "pytorch", "porch"], "a slip is not a word of the pack, so every reading stays")
    check(kept([reading("gpu", True, True), reading("gnu")], "gpu") == ["gpu", "gnu"],
          "a word that the base lexicon also holds is not protected")
    check(rerank.capitalizing_repaired_first_letters("pytorch", "[ytorch", "") == "Pytorch"
          and rerank.capitalizing_repaired_first_letters("pytorch", "[ytorch", "we use ") == "pytorch",
          "a first letter typed as a symbol key gets its capital at the start of the field only")
    check(capitals.latch(rerank.capitalizing_repaired_first_letters("pytorch", "[ytorch", ""), "[ytorch", "") == "PyTorch",
          "a symbol key in place of the first letter at the start of the field gives the preferred form")
    check(rerank.should_auto_capitalize("") and rerank.should_auto_capitalize("Done. ") and not rerank.should_auto_capitalize("I use "),
          "the keyboard types a capital by itself at the start of the field and after a period")
    check(rerank.word_with_inner_capital("I use pyTorch") == "pyTorch" and rerank.word_with_inner_capital("I use Pytorch") is None
          and rerank.word_with_inner_capital("see x.pyTorch") is None, "a word with a capital after its first letter is found")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", type=Path, default=ROOT / "build" / "engine" / "duo_cli")
    parser.add_argument("--only", choices=["engine", "capitals"])
    arguments = parser.parse_args()
    if arguments.only != "capitals":
        check_engine(arguments.cli)
    if arguments.only != "engine":
        check_capitals()
    print(f"check_supplement: {checks} checks held")


if __name__ == "__main__":
    main()
