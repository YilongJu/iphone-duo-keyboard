# Design of the correction of words with and without an apostrophe

## Summary

The keyboard of `engine/lm-keyboard` never adds the apostrophe to a typed word that is also a
common word, such as "its", "were" or "ill": 0 of 318 dev cases, also with the next word typed.
The fix corrects the earlier word when the next word arrives. The language model compares the
two forms of the typed letters with the word after them. With the next word typed, the keyboard
gets 1,403 of 1,623 new dev cases right, where it got 608. It keeps the existing dev cases: no
existing case turns wrong, and the total rises from 6,126 to 6,131.

What to do:

1. Install a build of `engine/apostrophe-words` on the phone through TestFlight.
2. Type "were going to be late", "ill call you", "whats happening" and "we were here". The
   correction comes at the space after the second word. The dev cases predict "we're going"
   (38 of 40 such cases), "i'll call" (39 of 40) and "what's happening" (18 of 20), and "we were
   here" as typed (40 of 40 controls). The phone has not run these sentences.
3. Type a word and the next word, see the correction, and press backspace once. Both words
   come back as shown before the correction, and the keyboard keeps them from then on.

This page does not settle the phone's time per correction. The pair its/it's stays weak with
distilgpt2: 13 of 40 with the next word typed.

## Glossary

| Term | Meaning |
| --- | --- |
| pair | A form without the apostrophe and its contraction, written "its/it's". |
| ambiguous pair | A pair whose form without the apostrophe is a common word: its, were, well, ill, hell, shell, wed, id, lets, shed, whore. |
| control | A case where the person meant the form without the apostrophe and typed it right, or meant the contraction and typed it right. |
| reading | One way the engine reads the typed span (`duo_english_readings`). |
| two-word span | The previous word and the current word. The keyboard reads them together at the space after the current word (`correctLastWord`). This is the delayed correction. |
| twin | A reading of a two-word span whose first word spells the typed letters with other apostrophes and whose later words are as typed: "it's going" for the typed "its going". |
| apostrophe step | The rule that replaces the choice by its best twin when the twin's step score leads by the margin. The step score is the model's log probability, plus the space-after term, less the reading's slip cost. |
| shipped | The keyboard of `engine/lm-keyboard`: its lexicon, its readings and the tuned distilgpt2 rule. |
| word, next word | The two ways of typing a case: the target word and a space, or the target word, a space, the next word and a space. |

## Test cases of the apostrophe words

`scripts/typing-evaluation/build_english_apostrophe_cases.py` writes
`cases/english-apostrophe-words.{dev,test}.jsonl`: 1,623 dev and 1,617 test cases. The existing
case files do not change.

Table 1. Categories of the new cases in the dev half.

| Category | Example, typed to intended | Dev cases |
| --- | --- | --- |
| `apostrophe_dropped_ambiguous` | its to it's | 318 |
| `clean_ambiguous_word` (control) | its to its | 318 |
| `apostrophe_added` | it's to its, let's to lets | 72 |
| `clean_ambiguous_contraction` (control) | it's to it's | 72 |
| `apostrophe_dropped` | whats to what's | 843 |

Each ambiguous pair has as many controls as slips. A keyboard that always shows the
contraction gets 1,233 of 1,623 right, because 843 cases have no control. A keyboard that never
shows it gets 390. The choice of the setting therefore also requires each control category at
the shipped count or more.

Each case stores `next_word`, the word after the target word, with no punctuation between the
two. The sentences, the 4 to 12 word limit and the split by Tatoeba id come from
`build_english_cases.py`. The contractions of the list also count as known words, because
wordfreq splits "y'all" and "ma'am" into two tokens. "why's" and "ma'am" have no sentence with
a next word, so they have no case.

The existing builder made no case of an ambiguous pair because of its frequency rule. It keeps
a contraction only when the contraction is 1.0 Zipf more frequent than the form without the
apostrophe. "it's" (6.33) and "its" (6.14) differ by 0.19.

## Causes of the wrong corrections today

Table 2. Causes per kind of word, from the engine's readings of the dev cases.

| Words | Cause | Evidence |
| --- | --- | --- |
| its, were, well, ill and the other ambiguous pairs | The engine keeps a known word unless another reading leads by `margin_known` 5. The model then needs a lead of 24 (`margin_from_typed`). | "it's" is among the 8 readings of a typed "its" in 318 of 318 cases. The shipped keyboard picks it in 0. |
| the same, with the next word | The search keeps one reading per last word. "its going" and "it's going" end in the same word, so the search keeps only the better one, and "it's going" never reaches the model. | The intended text is among the readings of the two-word span in 24 of 318 cases. |
| whats, thats, theres after or before a word | The engine's word pairs come from the SymSpell list, and none of its 242,342 rows holds an apostrophe. A contraction gets its own probability less 0.92 (log 0.4) and never a listed pair. Its rivals get their listed pairs. "whats" after "understand" becomes "what". | 0 SymSpell rows with an apostrophe. |
| hows, howd, whod, itd, theyd | The contraction is rare, and a frequent word one slip away wins: "hows" becomes "how". | "how" scores -11.86 and "how's" -12.13. |
| youre | A builder rule kept "youre" as a word. | "youre" was in the lexicon at Zipf 3.86. |
| whatd, thered | The builder took "what'd" and "there'd" for slips of "what's" and "there's". | Neither was in the lexicon. |
| yall, maam | The lexicon holds "ya'll" and neither "y'all" nor "ma'am". wordfreq splits both, so the builder's sources give no frequency for them. | Not fixed. |

The shipped model makes the plain contractions worse than the engine alone: 407 of 843 against
487 for the word alone. Its rule moves to any correction at a lead of 2 and to the text as
typed at no lead.

## Options weighed

Table 3. Options and the reason for each decision.

| Option | Decision | Reason |
| --- | --- | --- |
| A rule list, as the "ill" to "I'll" whitelist of AOSP LatinIME | not taken | A fixed rule cannot tell "its tail" from "it's going". |
| The engine alone with the next word | not taken | The engine's pairs never favor a contraction (Table 2). |
| A lower `margin_from_typed` for all corrections | not taken | The margin protects clean text in every category. |
| Apostrophe readings in the readings list | taken | Without them the two-word span holds the intended text in 24 of 318 cases. With them, in 318. |
| Apostrophe step at every correction | not taken | It changes a word from the text before it alone, and it turns 1 to 3 existing clean cases wrong at margins under 6. |
| Apostrophe step on the first word of a two-word span | taken | The model reads the word after the changed word, as in Apple's sentence-level correction of iOS 17. A word alone stays as typed. |
| Step score of the model alone, or less the slip cost | measured | Less the slip cost is better for the plain contractions: 700 against 398 of 843 at margin 1. |
| Lexicon fixes for "youre", "what'd", "there'd" | taken | Two builder rules were wrong. The fix raises the engine from 6,069 to 6,074. |
| A separate delayed correction | not needed | The keyboard already reads the previous word with the current word at each space. The undo and the kept words work as for any correction. |

The field reads such confusion sets with a language model over the words on both sides
(Golding and Roth 1999, Bergsma and others 2009). No open keyboard found in the search (AOSP
LatinIME, FUTO, HeliBoard, Presage) documents a rule for "its" against "it's".

## The fix in the keyboard

1. `duo_english_readings` adds, for each typed word, the reading with one apostrophe put in
   where the lexicon holds that word ("its" to "it's"). It also adds the reading with a typed
   apostrophe taken out ("it's" to "its"). Each gets the engine score of its words read
   exactly, less the slip cost: `omission_of_apostrophe` 0.5 or `insertion` 5.5.
   `duo_correct_english` does not read them, so the engine's choice stays.
2. `RerankRule.choose` runs the margins as before.
3. In a span of two or more typed words, the apostrophe step compares the choice with its best
   twin. A twin changes the apostrophes of the first word only. The step score leaves the
   engine's word statistics out, because they never give a contraction a listed pair.
4. The correction of a two-word span is the existing one. It replaces both words and leaves the
   cursor after the space and the text after the cursor as it was. Backspace brings back the
   two words as the field showed them before the correction, and the keyboard keeps both.
5. The lexicon builder keeps the most frequent contraction per form without the apostrophe. It
   also keeps a rare contraction whose frequent neighbors are all other endings of the same word.

## Results on the dev half

Table 4. Right new dev cases with the next word typed, from run 42965906697. The engine runs use
the new lexicon unless named.

| Run | dropped, ambiguous | control, word | added | control, contraction | dropped, plain | all |
| --- | --- | --- | --- | --- | --- | --- |
| engine, shipped lexicon | 0/318 | 306/318 | 11/72 | 71/72 | 233/843 | 621/1623 |
| shipped | 0/318 | 306/318 | 11/72 | 71/72 | 220/843 | 608/1623 |
| readings only | 1/318 | 306/318 | 11/72 | 71/72 | 282/843 | 671/1623 |
| step on the first word, less slip cost, margin 1 (chosen) | 272/318 | 306/318 | 54/72 | 71/72 | 700/843 | 1403/1623 |
| step on the first word, model only, margin 1.5 | 232/318 | 306/318 | 70/72 | 71/72 | 379/843 | 1058/1623 |
| step at every correction, model only, margin 6 | 61/318 | 306/318 | 55/72 | 71/72 | 284/843 | 777/1623 |

With the word alone, the chosen setting equals the shipped rule plus the lexicon fix: 802 of
1,623 against 792. The setting with margin 0.5 gets 1,426, and it is out because it turns one
`clean_ambiguous_word` case wrong.

Table 5. Right existing dev cases, from the same run.

| Run | clean | letter slips | space slips | symbol slips | clean symbols | all dev cases |
| --- | --- | --- | --- | --- | --- | --- |
| engine, shipped lexicon | 957/973 | 1943/2100 | 1299/1500 | 1131/1197 | 427/429 | 6069/6799 |
| engine | 957/973 | 1943/2100 | 1299/1500 | 1131/1197 | 427/429 | 6074/6799 |
| shipped | 958/973 | 1975/2100 | 1316/1500 | 1139/1197 | 427/429 | 6126/6799 |
| chosen | 958/973 | 1975/2100 | 1316/1500 | 1139/1197 | 427/429 | 6131/6799 |

The 5 more cases are "youre" to "you're" in `apostrophe_missing`. Every step on the first word
of a span turns no existing case wrong against the shipped run.

Table 6. Right cases of the chosen setting per ambiguous pair, with the next word typed.

| Pair | dropped | control |
| --- | --- | --- |
| its/it's | 13/40 | 40/40 |
| were/we're | 38/40 | 40/40 |
| well/we'll | 32/40 | 40/40 |
| ill/i'll | 39/40 | 38/40 |
| hell/he'll | 40/40 | 40/40 |
| shell/she'll | 17/19 | 19/19 |
| wed/we'd | 4/5 | 5/5 |
| id/i'd | 24/24 | 17/24 |
| lets/let's | 31/32 | 31/32 |
| shed/she'd | 30/32 | 31/32 |
| whore/who're | 4/6 | 5/6 |

"its" stays as typed mostly at the start of a sentence, as in "its not" and "its a". distilgpt2
gives "Its" and "It's" close scores there. The controls equal the shipped counts in every pair.

Plain pairs below 10 of 20 with the next word: "whens" 0/20, "whyd" 0/7, "wherere" 0/5,
"whatd" 0/3, "yall" 0/14, "thatll" 8/20, "shouldve" 8/20.

## Files of the fix

| File | Change |
| --- | --- |
| `Engine/duo_engine.c`, `Engine/duo_engine.h` | The apostrophe readings and the setting `apostrophe_readings` |
| `Shared/EnglishReranking.swift` | The apostrophe step and the rule `distilgpt2WithApostrophes` |
| `scripts/lm-rerank/rerank.py` | The same step in the harness |
| `scripts/typing-engine/build_english_lexicon.py`, `Shared/lexicon-english.bin` | The two builder rules |
| `scripts/typing-evaluation/build_english_apostrophe_cases.py` | The new cases |
| `scripts/lm-rerank/apostrophe_words.py`, `apostrophe_words_table.py` | The measurement and its tables |
| `Tests/ApostropheWordsTests.swift` | The unit tests of the rule and of the keyboard |
