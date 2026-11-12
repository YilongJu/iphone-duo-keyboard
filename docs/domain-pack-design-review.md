# Codex review of the design of the vocabulary pack "AI and software"

## Summary

Codex reviewed the design with `codex exec -c model_reasoning_effort=high`. It read the design,
the pack, the engine code, the capitals rule and the dev cases. The review came before any run
with the model was read. Codex did not open a test-half file. It gave 11 findings. Seven were taken, three were taken in part, and one was not
taken. Table 1 gives the reason for each.

A second review read the 16 later requested words and the results of the final runs. It gave 6
findings, and all 6 were taken. Table 2 lists them.

1. Read Table 1 and Table 2 for each finding and its outcome.
2. Read `docs/domain-pack-design.md` for the design after the two reviews.

This page does not hold a review of the results with the model.

## Findings and their outcome

Table 1. The 11 findings of the review, most serious first, as Codex ordered them.

| # | Finding | Outcome | Change or reason |
| --- | --- | --- | --- |
| 1 | The notice of the cases names licences, and it lacks the author, the date and the address of each Stack Exchange post. A repository's licence field does not prove the licence of each file. | Taken in part | `attribute_cases.py` writes the address, author, date and licence version of each source into `cases/english-domain-ATTRIBUTION.tsv`. The table gives the file address at the commit. A licence check per file was not done. |
| 2 | The share rule left `term_for_everyday_word` and the phrases out of its ranking, and a category total can hide a lost clean case, as "hyper parameters" to "hyperparameters". | Taken | The gates read each case of the clean controls, with `phrase_clean` among them. The ranking counts every new dev case. The rule picks no share when none passes. |
| 3 | The capitals rule can change a name or an identifier that the person typed on purpose, as "Lora" to "LoRA". The share of the preferred form in edited text does not measure intent. The rule infers the keyboard's own capital from the position. | Not taken, listed as a limit | The user decided that a typed capital asks for the preferred form. One backspace brings the typed form back, and the keyboard keeps it. The design lists both points as limits and as a decision for the user. |
| 4 | The keyboard gave a repaired first letter its capital after the preferred form, and the harness did not do it at all: "[ytorch" at the start of a sentence gave "Pytorch". | Taken | Both give the capital of a repaired first letter first, and the rule reads it as the keyboard's own capital. New category `capital_symbol_first`. |
| 5 | 29 of the 529 preferred forms hold an apostrophe, and the rule left such a word unchanged: "Gpu's" stayed. | Taken | The rule skips the apostrophe. New category `capital_possessive`. |
| 6 | The pack builder read all Tatoeba sentences for the everyday letter case, also those of the controls. A cross-listed arXiv paper and the posts of one Stack Exchange thread can sit in two buckets. | Taken in part | The builder reads four of five pairs of Tatoeba ids, and the everyday cases come from the fifth. A test sentence with the letters of a dev sentence stays out. The buckets were not split again: a held-out sentence with the letters of a build sentence was already left out, which covers a cross-listed abstract, and one thread cannot bring a word into the pack, because a word needs 20 documents in 2 sources. |
| 7 | The cases take their words from the pack, leave out slips that give a known word, and give the context ready in the field. The stream is in lower case. | Taken in part | The technical stream measures every word of held-out text, in the pack or not. A new stream of 300 sentences is typed as written, with capitals and punctuation. The slip rules of the two sides stay as they are, and the design names the difference. |
| 8 | The gain of the clean words does not show that a supplement is needed in place of a merged lexicon, and the frequency of the requested words is not set by data. | Taken | The engine job types every case with the merged lexicon too. The design says that the engine alone does not set the frequency of a requested word. |
| 9 | "400 dev words" are 400 cases, and "every Zipf value" are 8 values. | Taken | The wording. |
| 10 | `duo_convert_pinyin` reads every edge as a node of the main lexicon. | Taken | The Pinyin entry point refuses a lexicon with a supplement. Only a lexicon of the mixed model takes one, so the shipped Pinyin lexicon cannot have one. |
| 11 | The undo of a case change looks right in the code and was not run on a phone. The design named two sections that it did not have. | Taken | Unit tests of both undo paths, and the two sections. The phone checks are for the user. |

Codex recounted the numbers of the design from the files and found them right. The recount
covered 71,566,550 build words, 859,014 documents, 27 sources, 1,807 corpus words and 138,343
bytes. It also covered every fraction of the engine tables. Codex did not find a read outside a
buffer in the English path.

## Review of the 16 later requested words

Codex read commits 8661a70 and 835dc5f and the section "Requested words" of the design. The
review covered the pack table, the case builder, the capitals rule in Python and in Swift, and
the frequency results of the dev half. Codex then recounted the numbers of the design from the
result files of run 43187473874.

Table 2. The 6 findings of the second review.

| # | Finding | Outcome | Change |
| --- | --- | --- | --- |
| 1 | Four capital cases had the same context and typed text in both halves. An example is an empty field and "Nextjs". | Taken | The test half types these cases after "It is ready." The dev half does not change (commit 835dc5f). |
| 2 | The rule for a word's own frequency left one case open. The grid lacks a frequency at which every clean case of "todo" is right. | Taken | The rule names that case. The word takes the highest frequency that keeps its existing dev cases right. |
| 3 | The design said that the slips of "pnpm" become "pnpm". The engine changes the slip "nppm" to "npm". | Taken | The design names the one slip that the unit test holds, "pnmp". |
| 4 | The design said that the model lowers three measures. The dev results show five. | Taken | The section on the effect of the model names all five. The clean pack words and the written stream are the two added ones. |
| 5 | The limits said that the case set leaves out each slip that spells a known word. The group `term_for_everyday_word` holds such slips. | Taken | The limit names that group as the exception. |
| 6 | The design named the processor as the cause of a one-case difference between jobs. The design did not show the comparison. | Taken | The design gives the counts of the pack-off runs. Those runs type the same cases with the same model on each processor. |

Codex read the Swift rule and the Python rule of the preferred capitals and found them the
same, also for a form with a sign. Codex found that the choice of a frequency reads dev cases
only. Codex compared the cells of Tables 4 to 6 and 10 to 20 of the design with the result
files. Finding 4 was the one number in the prose that did not match.
