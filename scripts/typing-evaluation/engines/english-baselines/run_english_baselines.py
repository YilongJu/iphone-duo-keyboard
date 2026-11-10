"""Runs one open-source English spelling engine over the English typing cases.

Usage, from the repository root, with a Python interpreter that holds the engine:
    python scripts/typing-evaluation/engines/english-baselines/run_english_baselines.py \
        --engine symspell-lookup --half dev test [--workers 4] [--show-misses 3]

The script writes build/typing-evaluation/ENGINE/english.HALF.jsonl with one JSON object per line:
the case id and the engine's output. scripts/typing-evaluation/score.py scores that file.

Every engine runs with its stock settings and its stock data. When an engine does not suggest a
replacement for a token, the adapter keeps the token as typed, because a keyboard would leave the
typed letters in the field. README.md in this folder describes each engine name.
"""
import argparse
import ctypes
import ctypes.util
import json
import multiprocessing
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CASES = ROOT / "scripts" / "typing-evaluation" / "cases"
OUTPUT = ROOT / "build" / "typing-evaluation"
HUNSPELL_DICTIONARY = Path("/usr/share/hunspell/en_US")


# SymSpell ---------------------------------------------------------------------------------------

def load_symspell(with_word_pairs: bool):
    from importlib.resources import files
    from symspellpy import SymSpell

    engine = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
    words = files("symspellpy") / "frequency_dictionary_en_82_765.txt"
    if not engine.load_dictionary(str(words), term_index=0, count_index=1):
        raise RuntimeError(f"symspellpy did not load its word list {words}")
    if with_word_pairs:
        pairs = files("symspellpy") / "frequency_bigramdictionary_en_243_342.txt"
        if not engine.load_bigram_dictionary(str(pairs), term_index=0, count_index=2):
            raise RuntimeError(f"symspellpy did not load its word-pair list {pairs}")
    return engine


def symspell_lookup(arguments):
    """One token at a time: the most frequent word among the words at the smallest edit distance."""
    from symspellpy import Verbosity

    engine = load_symspell(with_word_pairs=False)

    def correct_token(token: str) -> str:
        suggestions = engine.lookup(token, Verbosity.TOP, max_edit_distance=2)
        return suggestions[0].term if suggestions else token

    return correct_token


def symspell_compound(arguments):
    """The whole typed text in one call. lookup_compound can split a token and join two tokens."""
    engine = load_symspell(with_word_pairs=True)

    def correct(context: str, typed: str) -> str:
        suggestions = engine.lookup_compound(typed, max_edit_distance=2)
        if len(suggestions) != 1:
            raise RuntimeError(f"lookup_compound returned {len(suggestions)} suggestions for {typed!r}")
        return suggestions[0].term

    return correct


def symspell_segmentation(arguments):
    """The whole typed text in one call. word_segmentation places every space again and corrects letters."""
    engine = load_symspell(with_word_pairs=False)

    def correct(context: str, typed: str) -> str:
        return engine.word_segmentation(typed).corrected_string

    return correct


# pyspellchecker ---------------------------------------------------------------------------------

def pyspellchecker(arguments):
    """One token at a time: correction(), which returns None when it does not find a known word."""
    from spellchecker import SpellChecker

    engine = SpellChecker()

    def correct_token(token: str) -> str:
        correction = engine.correction(token)
        return token if correction is None else correction

    return correct_token


# Hunspell ---------------------------------------------------------------------------------------

def hunspell(arguments):
    """One token at a time, through the C interface of libhunspell: spell, then the first suggestion."""
    affix_file = HUNSPELL_DICTIONARY.with_suffix(".aff")
    word_file = HUNSPELL_DICTIONARY.with_suffix(".dic")
    for path in (affix_file, word_file):
        if not path.is_file():
            raise FileNotFoundError(f"the Hunspell dictionary file {path} is missing")
    library_name = ctypes.util.find_library("hunspell-1.7")
    if library_name is None:
        raise RuntimeError("the shared library libhunspell-1.7 is not installed")
    library = ctypes.CDLL(library_name)
    text_list = ctypes.POINTER(ctypes.c_char_p)
    library.Hunspell_create.restype = ctypes.c_void_p
    library.Hunspell_create.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    library.Hunspell_get_dic_encoding.restype = ctypes.c_char_p
    library.Hunspell_get_dic_encoding.argtypes = [ctypes.c_void_p]
    library.Hunspell_spell.restype = ctypes.c_int
    library.Hunspell_spell.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    library.Hunspell_suggest.restype = ctypes.c_int
    library.Hunspell_suggest.argtypes = [ctypes.c_void_p, ctypes.POINTER(text_list), ctypes.c_char_p]
    library.Hunspell_free_list.restype = None
    library.Hunspell_free_list.argtypes = [ctypes.c_void_p, ctypes.POINTER(text_list), ctypes.c_int]

    # The handle serves every token of the run. The process ends after the run, so the adapter does not call Hunspell_destroy.
    handle = library.Hunspell_create(str(affix_file).encode(), str(word_file).encode())
    if not handle:
        raise RuntimeError("Hunspell_create returned a null handle")
    encoding = library.Hunspell_get_dic_encoding(handle).decode("ascii")
    if not library.Hunspell_spell(handle, "the".encode(encoding)):
        raise RuntimeError("Hunspell marks 'the' as misspelled, so the dictionary did not load")

    def correct_token(token: str) -> str:
        word = token.encode(encoding)
        if library.Hunspell_spell(handle, word):
            return token
        suggestions = text_list()
        count = library.Hunspell_suggest(handle, ctypes.byref(suggestions), word)
        try:
            return suggestions[0].decode(encoding) if count > 0 else token
        finally:
            library.Hunspell_free_list(handle, ctypes.byref(suggestions), count)

    return correct_token


# JamSpell ---------------------------------------------------------------------------------------

def load_jamspell(arguments):
    import jamspell

    if arguments.jamspell_model is None:
        raise SystemExit("a JamSpell engine needs --jamspell-model with the path of en.bin")
    if not arguments.jamspell_model.is_file():
        raise FileNotFoundError(f"the JamSpell model {arguments.jamspell_model} is missing")
    engine = jamspell.TSpellCorrector()
    if not engine.LoadLangModel(str(arguments.jamspell_model)):
        raise RuntimeError(f"JamSpell did not load the model {arguments.jamspell_model}")
    return engine


def jamspell_fix(engine, text: str, typed: str) -> str:
    """Corrects `text`, which ends with `typed`, and returns the part that replaces `typed`.

    FixFragment replaces letters inside words and copies every character between words, so the
    output has as many space-separated pieces as the input. The last pieces replace `typed`.
    """
    fixed = engine.FixFragment(text)
    pieces = fixed.split(" ")
    if len(pieces) != len(text.split(" ")):
        raise RuntimeError(f"JamSpell changed the number of spaces: {text!r} became {fixed!r}")
    return " ".join(pieces[-len(typed.split(" ")):])


def jamspell_with_context(arguments):
    """One call on the context followed by the typed text, so the model sees the words before."""
    engine = load_jamspell(arguments)

    def correct(context: str, typed: str) -> str:
        return jamspell_fix(engine, f"{context} {typed}" if context else typed, typed)

    return correct


def jamspell_without_context(arguments):
    """One call on the typed text alone."""
    engine = load_jamspell(arguments)

    def correct(context: str, typed: str) -> str:
        return jamspell_fix(engine, typed, typed)

    return correct


# The adapter ------------------------------------------------------------------------------------

# "token": the function corrects one space-separated token, and the adapter joins the results.
# "text": the function gets the context and the whole typed text, and returns the new typed text.
ENGINES = {
    "symspell-lookup": ("token", symspell_lookup),
    "symspell-compound": ("text", symspell_compound),
    "symspell-segmentation": ("text", symspell_segmentation),
    "pyspellchecker": ("token", pyspellchecker),
    "hunspell": ("token", hunspell),
    "jamspell": ("text", jamspell_with_context),
    "jamspell-no-context": ("text", jamspell_without_context),
}

_worker_correct_token = None


def _start_worker(engine: str, arguments) -> None:
    global _worker_correct_token
    _worker_correct_token = ENGINES[engine][1](arguments)


def _correct_in_worker(token: str) -> str:
    return _worker_correct_token(token)


def correct_tokens(engine: str, arguments, tokens: list[str]) -> dict[str, str]:
    """Corrects each distinct token once. A token engine gives one output per token, so order does not matter."""
    if arguments.workers == 1:
        correct_token = ENGINES[engine][1](arguments)
        return {token: correct_token(token) for token in tokens}
    with multiprocessing.Pool(arguments.workers, initializer=_start_worker, initargs=(engine, arguments)) as pool:
        return dict(zip(tokens, pool.map(_correct_in_worker, tokens, chunksize=8)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=sorted(ENGINES), required=True)
    parser.add_argument("--half", choices=["dev", "test"], nargs="+", required=True)
    parser.add_argument("--workers", type=int, default=1, help="processes for an engine that corrects one token at a time")
    parser.add_argument("--jamspell-model", type=Path, help="the path of the JamSpell model file en.bin")
    parser.add_argument("--show-misses", type=int, default=0, help="print this many wrong dev cases per category")
    arguments = parser.parse_args()

    kind, build = ENGINES[arguments.engine]
    cases = {
        half: [json.loads(line) for line in (CASES / f"english.{half}.jsonl").read_text(encoding="utf-8").splitlines() if line]
        for half in arguments.half
    }
    started = time.monotonic()
    outputs: dict[str, str] = {}
    if kind == "token":
        tokens = sorted({token for half in arguments.half for case in cases[half] for token in case["typed"].split(" ")})
        if "" in tokens:
            raise ValueError("a typed text holds an empty token")
        corrected = correct_tokens(arguments.engine, arguments, tokens)
        for half in arguments.half:
            for case in cases[half]:
                outputs[case["id"]] = " ".join(corrected[token] for token in case["typed"].split(" "))
    else:
        if arguments.workers != 1:
            raise SystemExit("--workers applies only to an engine that corrects one token at a time")
        correct = build(arguments)
        for half in arguments.half:
            for case in cases[half]:
                outputs[case["id"]] = correct(case["context"], case["typed"])
    seconds = time.monotonic() - started

    for half in arguments.half:
        folder = OUTPUT / arguments.engine
        folder.mkdir(parents=True, exist_ok=True)
        lines = []
        for case in cases[half]:
            output = outputs[case["id"]]
            if not isinstance(output, str):
                raise TypeError(f"{arguments.engine} returned {output!r} for case {case['id']}")
            lines.append(json.dumps({"id": case["id"], "output": output}, ensure_ascii=False) + "\n")
        (folder / f"english.{half}.jsonl").write_text("".join(lines), encoding="utf-8", newline="\n")
        print(f"{arguments.engine}: wrote {len(lines)} outputs to {folder / f'english.{half}.jsonl'}")
    total = sum(len(cases[half]) for half in arguments.half)
    print(f"{arguments.engine}: {total} cases in {seconds:.1f} seconds, engine loading included")

    if arguments.show_misses and "dev" in cases:
        shown: dict[str, int] = {}
        for case in cases["dev"]:
            output = outputs[case["id"]]
            if output.lower() != case["intended"].lower() and shown.get(case["category"], 0) < arguments.show_misses:
                shown[case["category"]] = shown.get(case["category"], 0) + 1
                print(f"    MISS {case['category']}: [{case['context']}] {case['typed']!r} -> {output!r}, wanted {case['intended']!r}")


if __name__ == "__main__":
    main()
