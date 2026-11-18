"""Check of the Python copies of the keyboard's rules (rules.py) against the cases of the Swift
unit tests: Tests/PredictionStripTests.swift, Tests/EmojiSuggestionTests.swift and the examples
in the comments of Shared/KeyboardTextLogic.swift.

Usage, from the repository root:
    python3 scripts/prediction-strip/benchmark/check_rules.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import rules  # noqa: E402

failures = []
count = 0


def expect(name: str, got, wanted) -> None:
    global count
    count += 1
    if got != wanted:
        failures.append(f"{name}: got {got!r}, wanted {wanted!r}")


# PredictionStripTests: the text that the strip predicts a word for.
context = rules.prediction_context
expect("after a word and one space", context("See you ", ""), ("you", ""))
expect("one typed letter", context("See you t", ""), ("you", "t"))
expect("two typed letters", context("See you to", ""), ("you", "to"))
expect("typed letters after a capital word", context("Thank y", ""), ("thank", "y"))
expect("typed letters at the start", context("to", ""), ("", "to"))
for before in ["", "See you. ", "See you, ", "See you  ", "See you\n"]:
    expect(f"no word before the cursor in {before!r}", context(before, ""), None)
expect("cursor inside a word", context("to", "day"), None)
for before in ["@to", "2to", "iPh", "a.to", "to-"]:
    expect(f"no plain word in {before!r}", context(before, ""), None)
for before in ["(to", "\"to", "say “to"]:
    expect(f"opening character in {before!r}", context(before, ""), ("", "to"))
expect("capital typed letters", context("To", ""), ("", "To"))
expect("all capitals", context("TO", ""), ("", "TO"))
expect("apostrophe in typed letters", context("I don'", ""), ("i", "don'"))

# PredictionStripTests: the form of a predicted word.
expect("capital form", rules.predicted_word("tomorrow", "To"), "Tomorrow")
expect("all capitals form", rules.predicted_word("tomorrow", "TO"), "TOMORROW")
expect("lower-case form", rules.predicted_word("tomorrow", "to"), "tomorrow")
expect("no typed letter", rules.predicted_word("tomorrow", ""), "tomorrow")
expect("in after i", rules.predicted_word("in", "i"), "in")
expect("the word i'm", rules.predicted_word("i'm", "i"), "I'm")
expect("the word i", rules.predicted_word("i", ""), "I")
capitals = object.__new__(rules.PreferredCapitals)
capitals.entries = {"pytorch": ("PyTorch", False), "nextjs": ("Next.js", False), "rag": ("RAG", True)}
capitals.new_words = set()
for word, typed, wanted in [("pytorch", "py", "pytorch"), ("pytorch", "Py", "PyTorch"), ("python", "Py", "Python"),
                            ("nextjs", "Nextj", "Next.js"), ("rag", "R", "Rag"), ("pytorch", "PY", "PyTorch")]:
    shown = capitals.form(rules.predicted_word(word, typed), typed, False)
    expect(f"work area form of {word} for {typed}", shown, wanted)

# EmojiSuggestionTests: the word whose emoji the strip shows.
emoji = rules.word_for_emoji
expect("word being typed", emoji("good"), "good")
expect("word before one space", emoji("That is good "), "good")
expect("capital word", emoji("Good "), "good")
for text in ["good  ", "good.", "good,", "@good "]:
    expect(f"no word for emoji in {text!r}", emoji(text), None)
table = rules.EmojiTable()
expect("emoji of good", table.count_before("good "), 2)
expect("emoji of good while typing", table.count_before("I feel good"), 2)
expect("emoji of office", table.count_before("I came form the office "), 1)
for text in ["xyz ", "goodness ", "the ", "good xyz", ""]:
    expect(f"no emoji for {text!r}", table.count_before(text), 0)

# Shared/KeyboardTextLogic.swift: space removal and space restore.
removal = rules.space_removal
expect("comma after a word", removal(",", "word ", ""), "markOnly")
expect("comma before a word", removal(",", "hello ", "world"), "markThenSpace")
expect("two spaces", removal(",", "word  ", ""), None)
expect("percent sign", removal("%", "word ", ""), None)
expect("closing bracket", removal(")", "a (word ", ""), "markOnly")
expect("closing double quote", removal("\"", "say \"hi ", ""), "markOnly")
expect("opening double quote", removal("\"", "say ", ""), None)
expect("closing single quote", removal("'", "say 'hi ", ""), "markOnly")
expect("apostrophe after a word", removal("'", "the users ", ""), None)
expect("letter restores the space", rules.restores_space(".", "e"), True)
expect("emoticon", rules.restores_space(":", ")"), True)
expect("not equal sign", rules.restores_space("!", "="), True)
expect("path", rules.restores_space(".", "/"), True)
expect("bracket after a period", rules.restores_space(".", ")"), False)

# The chunks of the benchmark.
parse = rules.parse_chunk
expect("plain word", parse("word"), ("", "word", ""))
expect("word and period", parse("word."), ("", "word", "."))
expect("word in brackets", parse("(word)"), ("(", "word", ")"))
expect("quoted word", parse("\"Hello,\""), ("\"", "Hello", ",\""))
expect("apostrophe inside", parse("don't"), ("", "don't", ""))
expect("apostrophe at the end", parse("users'"), ("", "users", "'"))
for chunk in ["fine-tuning", "e.g.", "2019", "$word", "v2", "--", "'tis", "a/b"]:
    expect(f"no plain word in {chunk!r}", parse(chunk), None)
expect("tap before a period", rules.tap_fits("See you tomorrow", "."), True)
expect("tap with no mark", rules.tap_fits("See you tomorrow", ""), True)
expect("tap before an emoticon", rules.tap_fits("See you tomorrow", ":)"), False)
expect("tap before a closing bracket", rules.tap_fits("a (word", ")."), True)
expect("tap before a closing quote", rules.tap_fits("say \"hi", "\""), True)
expect("tap before a quote that opens", rules.tap_fits("hello", "\""), False)
expect("tap before an apostrophe", rules.tap_fits("the users", "'"), False)
expect("tap before a dash", rules.tap_fits("word", "-"), False)

for failure in failures:
    print("FAILED", failure)
print(f"{count} cases, {len(failures)} failed")
raise SystemExit(1 if failures else 0)
