# Design of the vocabulary pack "AI and software" for the English typing engine

## Summary

The vocabulary pack "AI and software" keeps and corrects the words of the field. The pack does
not turn any existing dev case wrong. The numbers below are from the test half, read once. The
shipping keyboard keeps 946 of 950 correctly typed pack words with the pack on and 835 with it
off. The keyboard corrects 647 of 727 slips of those words, against 341.

```mermaid
xychart-beta
    title "Right test cases with the model, pack off and pack on"
    x-axis ["clean 835 off", "clean 946 on", "slips 341 off", "slips 647 on", "requested 64 off", "requested 163 on"]
    y-axis "right cases" 0 --> 950
    bar [835, 946, 341, 647, 64, 163]
```

Figure 1. The pack raises the kept clean words from 835 to 946 of 950, the corrected slips from
341 to 647 of 727, and the requested words from 64 to 163 of 164. Everyday running text does
not change: the keyboard changes 34 of 6,979 words with the pack off and on.

What to do:

1. Install a build of `engine/domain-pack` on the phone through TestFlight.
2. Type the lines of "Phone checks" at the end of this page.
3. Type `duo:work` and a space to turn the work area off, and type it again to turn it on.
4. Read "Decisions for the user" and say which of the 7 choices to change.

The page does not settle the time and memory on the phone with the pack. The keyboard does not
correct a slip after a hyphen, as in "fine-tunign".

## Glossary

| Term | Meaning |
| --- | --- |
| base lexicon | `Shared/lexicon-english.bin`, the word list that the keyboard ships today. |
| work area | A field of work that the person turns on in the keyboard. This page builds one: "AI and software". |
| pack | The words of one work area with their frequencies and preferred forms: `Shared/supplement-ai-software.bin` and `.tsv`. |
| supplement | A second, small lexicon file that the engine reads beside the base lexicon (`duo_lexicon_set_supplement`). |
| new word | A word of the pack that the base lexicon lacks, as "pytorch". |
| raised word | A word of the pack that the base lexicon holds at a frequency 10 times lower or less, as "gpu". |
| requested word | A word that the user asked for by name. The corpus does not decide it. |
| preferred form | The letter case that the domain text uses most for a word, as "PyTorch". |
| everyday word of the pack | A word of the pack that everyday text writes in another form, as "rag" for "RAG". |
| Zipf | Frequency on a log scale: 3 is once per million words, 6 is once per thousand. |
| domain share | The share of domain text in a person's text that the frequencies of the pack assume. |
| dev half, test half | The two halves of the test cases. Every choice of this page was made on the dev half. The test half was read once, at the end. |
| reading | One way the engine reads the typed letters as words, as "pytorch" and "porch" for "pytorhc". |
| clean case | A case typed without a slip. The keyboard must leave it as typed. |
| slip | One typing error of `keyboard_noise.py`: a neighbour key, a missing, doubled or extra letter, two swapped letters, or a slip at the space bar. |
| engine alone | The choice of `duo_correct_english`, as the keyboard types before its language model is ready. |
| model | The SmolLM2-135M fine-tune that re-ranks the engine's readings, with the rule of `KeyboardLanguageModel.rule`. |
| protection | The model may not change a typed new word. It chooses among the readings that keep the word. |

## Sources of the domain text

The pack comes from 71.6 million words of public text in 859,014 documents. Each source has a
licence that allows a word list and short quoted sentences in a public repository.

Table 1. Source groups of the domain text. The word counts are those of the build bucket.

| Source group | Sources | Licence | Words |
| --- | --- | --- | --- |
| `arxiv` | Abstracts of cs.CL, cs.LG, cs.AI and cs.SE, the newest 8,000 of each | CC0 1.0 (arXiv metadata) | 4,906,097 |
| `questions-ai` | Stack Exchange sites ai, genai and datascience, dump of 2024-04 | CC BY-SA 4.0, older posts 3.0 and 2.5 | 13,238,915 |
| `questions-software` | Stack Exchange sites softwareengineering and devops, dump of 2024-04 | CC BY-SA 4.0, older posts 3.0 and 2.5 | 49,840,919 |
| `docs-ai` | Documentation of 12 projects, as transformers, vLLM, llama.cpp and the Claude cookbooks | Apache 2.0, MIT or CC BY 4.0 | 1,380,521 |
| `docs-software` | Documentation of 6 projects, as Kubernetes, Docker and GitHub | Apache 2.0 or CC BY 4.0 | 2,200,098 |

`scripts/domain-pack/pack/ai-software.sources.json` names all 27 sources, with the commit and
the licence that GitHub reports for each repository. The collector stops when a reported
licence differs from the one in `sources.json`. `cases/english-domain-ATTRIBUTION.tsv` gives the
address, author, date and licence of each of the 8,359 sources that a case quotes.

A hash of each document's identifier sends it to one of three buckets. The build bucket holds 80
of 100 documents and feeds the pack. The dev and test buckets hold 10 of 100 each and feed the
test cases. A held-out sentence stays out when a build sentence has the same letters. Capitals,
spaces and punctuation do not count. This rule left out 19,622 sentences, and it also covers an
arXiv abstract listed under two categories.

The pack does not use Hacker News comments as a source. The set of terms does not give an open
licence for the text.

## Rules that pick the words of the pack

The method follows the field's term extraction. Compare a word's frequency in domain text with
its frequency in general text. Require the word in more than one source
([TermSuite's weirdness ratio](https://liner.com/review/terminology-extraction-with-term-variant-detection),
[keyness](https://dh-abstracts.library.virginia.edu/works/11926)). Keyboards layer such a list
over their main dictionary. AOSP LatinIME does the same with its
[user and contacts dictionaries](https://git.aicp-rom.com/packages_inputmethods_LatinIME.git/plain/java/src/com/android/inputmethod/latin/Dictionary.java).

1. A source gives a word a rate: its count over the source's words. A source group gives the
   mean rate of its sources. The domain frequency is the mean of the five group rates. The
   largest group does not set a frequency alone. One project's documentation does not set a
   frequency alone either.
2. A word enters when 0.3 times its domain frequency is Zipf 2.5 or more. That is about 3 uses
   in 10 million words. A word of two letters needs Zipf 4.0.
3. A word must be in 2 sources or more, 3 times each, and in 20 documents.
4. That frequency must be 10 times the frequency the keyboard has for the word today.
5. A listed misspelling stays out. A word also stays out when another word meets both
   conditions. The other word is one edit away, and the person writes that word 100 times as
   often. The base lexicon builder uses the same rule.

Table 2. Count of words after each rule, from `ai-software.report.json`.

| Rule | Words |
| --- | --- |
| Frequent enough in the domain text | 15,388 |
| Left out: the keyboard already has the word at about this frequency | 12,345 |
| Left out: in too few sources or documents | 1,138 |
| Left out: a listed misspelling | 2 |
| Left out: one edit away from a far more frequent word | 96 |
| Words from the corpus | 1,807 |
| Of them new words | 1,004 |
| Of them raised words | 803 |

The method finds all 33 words of a seed list that names the obvious terms. Examples include
"gpu", "llms", "kubectl", "agentic" and "finetuning". The seed list is a check and does not add
a word.

`pack/required-terms.tsv` holds the requested words apart from the corpus words: "ultrathink"
and "ultracode". The builder stops when the corpus or the base lexicon already gives one.

The pack does not hold a word with a digit, as "k8s" and "s3". The engine reads a digit key as
a slip for a letter, and its lexicon holds letters and apostrophes only.

## Frequencies on the scale of everyday words

A person who works in the area writes domain text some of the time. The pack frequency of a word
is its domain frequency times the domain share. With the share 0.3, a word that is Zipf 5.0 in
domain text gets Zipf 4.48. The domain share puts "llm" (5.37) beside "several" (5.39), and
"kubectl" (4.21) beside "awkward" (4.29). Section "Rule that picks the domain share" gives the
rule and the dev numbers behind 0.3.

The corpus does not give a count for a requested word. Each requested word gets one fixed
frequency, Zipf 4.5: about once in 30,000 words.

Table 3. Right dev cases of the requested words at 8 frequencies, from run 43122414341. Run
43098598158 gives the same counts. The engine alone gets all 164 cases right at each value.

| Zipf of the requested words | Named slips, model | Other slips, model | Controls, model | All 164 cases, model |
| --- | --- | --- | --- | --- |
| 2.0 | 11/18 | 61/80 | 18/18 | 138 |
| 2.5 | 12/18 | 66/80 | 18/18 | 144 |
| 3.0 | 15/18 | 69/80 | 18/18 | 150 |
| 3.5 | 18/18 | 71/80 | 18/18 | 155 |
| 4.0 | 18/18 | 72/80 | 18/18 | 156 |
| 4.5 | 18/18 | 74/80 | 18/18 | 158 |
| 5.0 | 18/18 | 75/80 | 18/18 | 159 |
| 5.5 | 18/18 | 78/80 | 17/18 | 161 |

The more frequent the requested words, the more of their slips the model corrects. The three
slips that the user named need Zipf 3.5 with the model, and 5.5 turns one control wrong. The
value 4.5 is one Zipf unit above 3.5. The 48 clean cases are right at every value.

## Path of the pack into the engine

The pack reaches the engine as a supplement: a second lexicon file of the same format. The
supplement does not hold word pairs. The engine reads the supplement beside the base lexicon.

```mermaid
flowchart LR
    typed["typed: pytorhc"] --> engine
    subgraph engine["duo_engine.c"]
        base["base lexicon<br/>7.7 MB, word pairs"]
        supplement["supplement<br/>138 KB, 1,809 words"]
    end
    engine --> readings["readings: pytorch, porch, ..."]
    readings --> protect["readings that keep<br/>a typed new word"]
    protect --> model["SmolLM2 re-ranker"]
    model --> capitals["preferred capitals<br/>529 words"]
    capitals --> field["field: pytorch or PyTorch"]
    setting["work area on or off<br/>duo:work"] -.-> supplement
    setting -.-> protect
    setting -.-> capitals
```

Figure 2. The supplement adds words to the engine's search. The protection and the table of
preferred capitals act on the result, and one switch turns all three off.

Table 4. Two ways to bring the pack to the engine. They differ in one dev stream sentence.

| | Merged lexicon | Supplement (taken) |
| --- | --- | --- |
| Files in the app | A second lexicon of 7,799,970 bytes for the setting "on" | One file of 138,343 bytes per work area |
| Switch at run time | Open the other file | Set or clear one pointer |
| A word the person teaches the keyboard later | Needs a rebuild of the 7.8 MB file | A second small file of the same format |
| A raised word | Takes the pack frequency and keeps its pairs | Takes the higher of its base value and its pack value, and keeps its pairs |
| Engine change | None | A second walk of the letter tree |
| Same output as the other way, engine alone | 5,988 of 5,988 new dev cases, 2,299 of 2,300 stream sentences, 6,799 of 6,799 existing dev cases | the same |

The supplement is chosen because it switches at run time and costs 56 times fewer bytes. The
supplement also has the shape that a store of personally learned words needs. The merged lexicon
stays in the repository as the comparison (`build_merged_lexicon.py`). The keyboard does not
ship the merged lexicon.

A new word does not have a word pair. After any word, a new word gets its own frequency, as a
base word without a listed pair does. The engine scores the word after a new word as it scores
a word after any known word.

The supplement does not join typed words that are all known words. A person who typed "hard
coded" meant two words, also when the pack holds "hardcoded". The base lexicon keeps its own
joins, as before.

The engine without a supplement gives the outputs of the engine before the change on every
existing dev task. `duo_english_readings` passes the memory checks of the compiler with the
supplement on 14,410 inputs. `scripts/domain-pack/check_supplement.py` holds 99 checks of the
supplement, the capitals rule and the protection. The engine before the change does not pass the
first supplement check.

The supplement file is mapped from the app bundle, as the base lexicon is. iOS reads its pages
from disk when the engine touches them. So its 138 KB do not count as loaded data. The table of
preferred capitals is 38 KB of text. The keyboard reads the table once into 529 entries and a
set of 1,006 words. In the simulator the keyboard's footprint before the model loads is 143.1 MB
with the work area. The footprint was 142.8 MB without it. The footprint on the phone was not
measured.

## Protection of a typed new word from the model

The model must keep a typed word that only the pack holds. The model chooses among the readings
that keep every such word. The text as typed and the engine's own choice always stay among them.

The model was fine-tuned on everyday sentences. Without the protection, the model changes
correctly typed pack words: "cnns" to "cnn's" and "ide" to "ride". Other changes include "sft"
to "soft" and "json" to "is on". The pack knows these words better than the model does. The
protection does not cover a raised word because that word is also an everyday word. Examples
include "node", "model" and "token".

The price is the group `term_for_everyday_word`. A slip of an everyday word that spells a new
word of the pack stays as typed. An example is "gpt" for "got". Section
"Results on the dev half" gives both sides of that trade.

## Rule of the preferred capitals

The user decided the rule. When the person means a properly capitalized word, the keyboard
writes that word, and lower case is fine otherwise. The keyboard writes a word of the pack in
one of three forms. The forms are lower case, the preferred form, or all capitals. The typed
capitals pick the form.

1. Without a typed capital, the word stays in lower case: "gpu" stays "gpu".
2. Typed in capitals only, the word stays: "PYTORCH" stays.
3. One capital that the keyboard typed by itself, at the start of a sentence: the preferred
   form. "Gpu" becomes "GPU", and "Vllm" becomes "vLLM".
4. One capital that the person typed: the preferred form. "Gpu" inside a sentence becomes "GPU",
   and "pyTorch" becomes "PyTorch".
5. Two or more capitals: the preferred form or all capitals, whichever differs from the typed
   capitals in fewer letters. A tie goes to the preferred form. "PYTORCh" becomes "PYTORCH", and
   "PYtorch" becomes "PyTorch".
6. An everyday word of the pack keeps a plain first capital. "Rag" stays "Rag" in rules 3 and 4.
7. A corrected slip follows the same rules with the case of its first typed letter. "Pytorhc"
   becomes "PyTorch", and "pytorhc" becomes "pytorch".
8. The rule does not count an apostrophe as a letter: "Gpu's" becomes "GPU's".
9. A first letter typed as a symbol key gets the keyboard's own capital at sentence start. Thus,
   "[ytorch" becomes "PyTorch" there and "pytorch" inside a sentence.
10. The rule does not change a word outside the pack or a pack word that prefers lower case.

Table 5. Three rules for the form of a word, on three typed texts inside a sentence.

| Typed | Distance over the letter case alone | Always the preferred form | Intent first (taken) |
| --- | --- | --- | --- |
| gpu | gpu | GPU | gpu |
| Gpu | gpu, one letter away | GPU | GPU |
| PYTORCH | PYTORCH | PyTorch | PYTORCH |

A distance alone undoes a capital that the person typed. Always the preferred form overrides a
person who types in lower case, which the user ruled out. So intent comes first, and the
distance only decides between the preferred form and all capitals.

Table 6. Letter case of the pack's words in the domain text, for the 521 words with a preferred
form excluding everyday words.

| Place | Words | Uses | Preferred form | Plain first capital, as "Gpu" | Lower case |
| --- | --- | --- | --- | --- | --- |
| Inside a sentence | 521 | 361,730 | 85.9% | counted with other forms | 11.6% |
| First word of a sentence, preferred form starts with a capital | 510 | 19,276 | 93.0% | 4.0% | 1.8% |
| First word of a sentence, preferred form starts in lower case | 11 | 256 | 80.9% | 2.7% | 1.2% |

At the start of a sentence, the domain text writes the preferred form 93.0% of the time. Thus,
rule 3 gives the preferred form. The rule also gives the preferred form for the 11 words such as
"vLLM" and "macOS": 80.9%. The table shows how writers of the field spell these words. The table
does not measure the intent of a person who types a capital.

A word is an everyday word of the pack when everyday sentences meet both conditions. The
sentences write the word in another form at least 5 times. That form occurs at least as often as
the preferred form. The pack marks 8 words: pod, azure, compose, rag, llama, terraform, copilot
and ides. The count comes from four of five pairs of Tatoeba ids. The fifth pair feeds the
everyday cases, so those are new text for this rule.

The keyboard does not read a word with a capital after its first letter for slips. Thus, a
corrected slip carries at most one capital, on its first letter. Rule 7 does not need alignment
of the typed letters with the corrected ones.

A case change is a correction like any other. One backspace right after the correction brings
the typed form back. The keyboard keeps that word as typed from then on.

## Work area setting

The work area is on in a new install. The text `duo:work` and a space turns the work area off or
on. The keyboard takes the text out of the field and names the new state on the space bar. The
keyboard extension stores the switch in its own settings. The app does not share a settings
store with the extension today. A switch in the app needs an app group first.

## Test cases of the pack

`scripts/typing-evaluation/build_english_domain_cases.py` writes
`cases/english-domain.{dev,test}.jsonl` and `cases/english-domain-stream.{dev,test}.jsonl`. The
build does not change the existing case files.

Table 7. Groups of the new cases.

| Group | The keyboard must | Example, typed to intended | Dev cases | Test cases |
| --- | --- | --- | --- | --- |
| `domain_clean` | keep a word of the pack in a technical sentence | pytorch to pytorch | 950 | 950 |
| `domain_slips` | correct one slip into the word of the pack | weighhts to weights | 723 | 727 |
| `domain_phrases` | repair the space bar in a frequent pair and inside a word of the pack, and keep the pair | linearlayer to linear layer | 1,197 | 1,192 |
| `required` | keep and correct the requested words, and keep "ultra", "ultrathin" and "ultrasound" | ultrathnik to ultrathink | 164 | 164 |
| `neighbour_controls` | keep a common word one edit away from a word of the pack, and correct its slips to it | tom to tom, tolm to tom | 1,100 | 1,100 |
| `term_for_everyday_word` | (the price of the pack) read a slip that spells a new word of the pack as the common word | aws to was | 158 | 154 |
| `capitals` | write the form that the typed capitals ask for, with the capitals scored | Rnn to RNN, Coat to Coat | 1,696 | 1,666 |
| stream, technical | change no word of 1,000 held-out technical sentences in lower case | 14,765 dev words | 1,000 | 1,000 |
| stream, written | change no word of 300 other technical sentences with their capitals and punctuation | 4,648 dev words | 300 | 300 |
| stream, everyday | change no word of 1,000 Tatoeba sentences in lower case | 7,040 dev words | 1,000 | 1,000 |

The context of a technical case is the sentence before the word, as its source wrote it. The
typed word is in lower case, unless the case is about capitals. The contexts of the requested
words are written by hand. Public text does not hold these words yet.

The group `term_for_everyday_word` does not serve as a control. A pack that knows "gpt" does not
also read "gpt" as a slip of "got" from the word alone. The group measures that price.

The technical stream measures every word of held-out text, in the pack or not. The cases of the
other groups take their words from the pack, so they measure the pack's own words.

## Rule that picks the domain share

The rule was fixed before any run with the model was read. The rule compares the shares 0.03,
0.1, 0.3 and 1.0 on one set of words. The comparison uses the configuration that ships: the
model with the pack on.

1. A share stays in when the pack does not turn any clean control case from right to wrong. The
   controls are `neighbour_clean`, `required_control`, `domain_clean_hyphenated`, `phrase_clean`
   and the five capital controls. The gate reads each case, so a gain elsewhere does not hide a
   loss.
2. The pack must change at most as many words of the everyday stream as the pack-off run.
3. Among those shares, choose the share with the most right new dev cases over every group. Each
   case counts the same, also the cases of `term_for_everyday_word`. These weights are those of
   the case files. The weighting does not measure how often each slip happens.
4. A tie goes to the smaller share.

The chosen share must also keep every existing dev category at the pack-off count or more. Each
category of the apostrophe words must also meet that condition.
`scripts/lm-rerank/domain_pack_shares.py` applies the rule.

Table 8. The four shares with the model and the pack on, on the dev half, from run 43122414341.

| Share | Right new dev cases | Lost clean controls | Everyday stream, changed words (pack off) | Technical stream, changed words per 1,000 | Existing dev cases | Passes the gates |
| --- | --- | --- | --- | --- | --- | --- |
| 0.03 | 5,198 | 0 | 25 (25) | 13.41 | 6,544 | yes |
| 0.1 | 5,269 | 0 | 25 (25) | 12.94 | 6,543 | yes |
| 0.3 (chosen) | 5,325 | 0 | 25 (25) | 12.80 | 6,543 | yes |
| 1.0 | 5,396 | 1 | 25 (25) | 13.07 | 6,544 | no |

The higher the share, the more new cases are right. The share 1.0 turns one clean control wrong:
"model" becomes "models". The rule picks 0.3. With the engine alone, the share 1.0 also turns
one existing clean case wrong, "ttyl" to "ttl". The four jobs ran on different runners, whose
model numbers differ in the last digits. Thus, the pack-off totals differ by one case.

## Results on the dev half

The pack keeps the words of the field and corrects their slips. The pack does not turn any
existing dev case wrong. All numbers are from the job of share 0.3 in run 43122414341, at commit
57d75b2.

Table 9. Right dev cases of the new groups in the four configurations.

| Configuration | domain_clean | domain_slips | domain_phrases | required | neighbour_controls | term_for_everyday_word | capitals | all |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| engine, pack off | 745/950 | 322/723 | 869/1197 | 37/164 | 997/1100 | 108/158 | 755/1696 | 3833/5988 |
| engine, pack on | 949/950 | 631/723 | 947/1197 | 164/164 | 990/1100 | 28/158 | 1604/1696 | 5313/5988 |
| model, pack off | 835/950 | 341/723 | 905/1197 | 64/164 | 1030/1100 | 134/158 | 777/1696 | 4086/5988 |
| model, pack on (ships) | 946/950 | 627/723 | 980/1197 | 158/164 | 1028/1100 | 28/158 | 1558/1696 | 5325/5988 |

Table 10. Right dev cases of each category.

| Category | engine, pack off | engine, pack on | model, pack off | model, pack on |
| --- | --- | --- | --- | --- |
| `domain_clean_new` | 200/400 | 399/400 | 297/400 | 399/400 |
| `domain_clean_raised` | 395/400 | 400/400 | 388/400 | 397/400 |
| `domain_clean_hyphenated` | 150/150 | 150/150 | 150/150 | 150/150 |
| `domain_slip_new` | 0/343 | 270/343 | 0/343 | 262/343 |
| `domain_slip_raised` | 322/380 | 361/380 | 341/380 | 365/380 |
| `phrase_clean` | 292/300 | 294/300 | 293/300 | 296/300 |
| `phrase_space_missing` | 104/150 | 115/150 | 106/150 | 118/150 |
| `phrase_space_to_letter` | 128/150 | 135/150 | 139/150 | 141/150 |
| `phrase_space_transposed` | 127/150 | 128/150 | 134/150 | 135/150 |
| `term_space_extra` | 108/150 | 137/150 | 114/150 | 145/150 |
| `term_letter_to_space` | 110/150 | 138/150 | 119/150 | 145/150 |
| `hyphen_second_part_slip` | 0/147 | 0/147 | 0/147 | 0/147 |
| `required_clean` | 5/12 | 12/12 | 12/12 | 12/12 |
| `required_clean_next_word` | 14/36 | 36/36 | 34/36 | 36/36 |
| `required_slip_named` | 0/18 | 18/18 | 0/18 | 18/18 |
| `required_slip` | 0/80 | 80/80 | 0/80 | 74/80 |
| `required_control` | 18/18 | 18/18 | 18/18 | 18/18 |
| `neighbour_clean` | 398/400 | 398/400 | 388/400 | 388/400 |
| `neighbour_slip` | 338/400 | 338/400 | 365/400 | 365/400 |
| `neighbour_slip_between` | 261/300 | 254/300 | 277/300 | 275/300 |
| `neighbour_slip_onto_term` | 108/158 | 28/158 | 134/158 | 28/158 |
| `capital_lower_stays` | 107/150 | 150/150 | 122/150 | 149/150 |
| `capital_deliberate` | 29/150 | 150/150 | 31/150 | 149/150 |
| `capital_sentence_start` | 22/150 | 150/150 | 24/150 | 149/150 |
| `capital_inner` | 0/100 | 100/100 | 0/100 | 100/100 |
| `capital_preferred_stays` | 97/100 | 100/100 | 100/100 | 100/100 |
| `capital_all_capitals_stay` | 100/100 | 100/100 | 100/100 | 100/100 |
| `capital_two_capitals_nearest` | 0/60 | 60/60 | 0/60 | 60/60 |
| `capital_slip_lower` | 29/150 | 118/150 | 29/150 | 111/150 |
| `capital_slip_deliberate` | 18/150 | 114/150 | 17/150 | 107/150 |
| `capital_slip_sentence_start` | 3/87 | 74/87 | 4/87 | 56/87 |
| `capital_plain_word_keeps_capital` | 90/100 | 100/100 | 98/100 | 100/100 |
| `capital_possessive` | 24/51 | 51/51 | 27/51 | 51/51 |
| `capital_symbol_first` | 8/120 | 109/120 | 11/120 | 110/120 |
| `capital_control_everyday_start` | 8/8 | 8/8 | 7/8 | 7/8 |
| `capital_control_everyday_deliberate` | 7/7 | 7/7 | 5/7 | 6/7 |
| `capital_control_everyday_lower` | 7/7 | 7/7 | 5/7 | 6/7 |
| `capital_control_ordinary_word` | 150/150 | 150/150 | 147/150 | 147/150 |
| `capital_control_collision_lower` | 56/56 | 56/56 | 50/56 | 50/56 |

Every clean control is at the pack-off count or more in both pairs of columns. Most wrong
capital cases with the pack on are slips that the keyboard left uncorrected.

Table 11. Changed words of clean running text on the dev half, per 1,000 typed words.

| Configuration | Technical, 14,765 words | Technical, changed sentences that hold a changed pack word | Written, 4,648 words | Everyday, 7,040 words |
| --- | --- | --- | --- | --- |
| engine, pack off | 23.43 (346 words) | 84 | 11.83 (55) | 10.80 (76) |
| engine, pack on | 13.75 (203) | 2 | 8.61 (40) | 10.80 (76) |
| model, pack off | 16.59 (245) | 47 | 11.19 (52) | 3.55 (25) |
| model, pack on (ships) | 12.80 (189) | 6 | 10.11 (47) | 3.55 (25) |

With the model, the pack lowers changed words of technical text from 16.59 to 12.80 per 1,000.
The pack does not change the everyday text: 25 words with the pack off and on. The keyboard
still changes technical text 3.6 times as often as everyday text.

Table 12. Right existing dev cases. The grouping does not include the last two categories.

| Configuration | clean | letter slips | space slips | symbol slips | clean symbols | apostrophe_missing | real_word_slip | all dev cases | apostrophe words, word | apostrophe words, next word |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| engine, pack off | 957/973 | 1943/2100 | 1299/1500 | 1131/1197 | 427/429 | 255/300 | 62/300 | 6074/6799 | 882/1623 | 628/1623 |
| engine, pack on | 960/973 | 1943/2100 | 1299/1500 | 1131/1197 | 427/429 | 255/300 | 62/300 | 6077/6799 | 882/1623 | 628/1623 |
| model, pack off | 953/973 | 2057/2100 | 1387/1500 | 1165/1197 | 428/429 | 296/300 | 256/300 | 6542/6799 | 1264/1623 | 1432/1623 |
| model, pack on (ships) | 953/973 | 2057/2100 | 1387/1500 | 1165/1197 | 429/429 | 296/300 | 256/300 | 6543/6799 | 1264/1623 | 1432/1623 |

With the engine alone or the model, the pack does not turn any existing dev case from right to
wrong. The pack does not turn any apostrophe case from right to wrong either. The pack turns 3
existing cases right with the engine alone ("postgres", "websocket", "finetune"). The pack turns
1 right with the model ("readme.md"). Each of the 24 existing categories and each of the 10
apostrophe categories keeps its count or gains.

Table 13. New dev cases that the pack turns from right to wrong, outside `term_for_everyday_word`.

| Configuration | Cases | Examples, typed to shown, with the intended text |
| --- | --- | --- |
| engine | 11 | "lofs" to "logs" (lots), "nosde" to "node" (nose), "pseudoc ode" to "pseudocode" (pseudo code) |
| model | 7 | "sparwe" to "sparse" (spare), "deckding" to "decoding" (deciding), "vectorbstore" to "vectorstore" (vector store) |

All 18 are slips. Some are slips of everyday words that sit closer to words of the pack. Others
are slips at the space bar whose letters spell joined words of the pack.

### Price and gain of the protection

Table 14. The model with the pack on, with and without the protection, on the dev half.

| | With the protection (ships) | Without |
| --- | --- | --- |
| `domain_clean_new` | 399/400 | 388/400 |
| `capitals` | 1558/1696 | 1543/1696 |
| `term_for_everyday_word` | 28/158 | 113/158 |
| All new dev cases | 5325/5988 | 5384/5988 |
| Technical stream, changed words | 189 | 191 |
| Existing dev cases | 6543/6799 | 6543/6799 |

The protection keeps 11 more of 400 clean new words and 15 more capital cases. The protection
leaves 85 more of the 158 slips that spell a new word of the pack. By the count of cases, the
protection gives fewer right cases. The protection ships because a correctly typed word of the
person's own field must stay. Without protection, the model turns "json" into "is on" and "cnns"
into "cnn's". The 158 cases were built to hit a word of the pack. Thus, their count does not say
how often such a slip happens.

### Supplement against the merged lexicon

With the engine alone, the supplement and the merged lexicon give the same output in these
cases. The counts are 5,988 of 5,988 new dev cases and 6,799 of 6,799 existing dev cases. The
output also matches in 2,299 of 2,300 stream sentences. The one difference is the rule against
joining typed known words. The merged lexicon turns "auto
scaling" into "autoscaling", and the
supplement keeps the two words. The numbers are from the engine job of run 43142372002.

### Keyboard code against the harness

The keyboard's own code types the same dev cases in the iOS simulator. Run 43142371994 has the
keyboard and the harness on one machine. The two give the same output in all 12,787 dev cases.
They make the same choice in all 13,404 corrections that went to the model. A case about
capitals is compared with its capitals. With the model the keyboard gets 5,326 of the 5,988 new
dev cases right. It gets 6,537 of the 6,799 existing ones. The harness on that machine gets the
same two counts.

One step of that job is red. The two scorers differ in 1 of 12,886 requests on the macOS
runner. The difference is 0.285 in one candidate. `scripts/lm-keyboard/README.md` describes the
request. The choice of that correction is the same on both sides.

## Results on the test half

The test half was read once, for the shipped design alone, in run 43142372002 at commit
6eef96e. Its numbers follow the dev numbers.

Table 15. Right test cases of the new groups in the four configurations.

| Configuration | domain_clean | domain_slips | domain_phrases | required | neighbour_controls | term_for_everyday_word | capitals | all |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| engine, pack off | 736/950 | 322/727 | 840/1192 | 33/164 | 1012/1100 | 104/154 | 739/1666 | 3786/5953 |
| engine, pack on | 949/950 | 652/727 | 925/1192 | 164/164 | 1007/1100 | 20/154 | 1580/1666 | 5297/5953 |
| model, pack off | 835/950 | 341/727 | 890/1192 | 64/164 | 1054/1100 | 130/154 | 775/1666 | 4089/5953 |
| model, pack on (ships) | 946/950 | 647/727 | 956/1192 | 163/164 | 1053/1100 | 20/154 | 1541/1666 | 5326/5953 |

Table 16. Changed words of clean running text on the test half, per 1,000 typed words.

| Configuration | Technical, 15,021 words | Written, 4,681 words | Everyday, 6,979 words |
| --- | --- | --- | --- |
| engine, pack off | 22.97 (345 words) | 13.89 (65) | 13.61 (95) |
| engine, pack on | 12.12 (182) | 8.97 (42) | 13.61 (95) |
| model, pack off | 15.11 (227) | 13.25 (62) | 4.87 (34) |
| model, pack on (ships) | 10.45 (157) | 10.68 (50) | 4.87 (34) |

With the model, the pack does not turn any test case of a clean control from right to wrong. The
pack turns 5 slips outside `term_for_everyday_word` wrong. These include "feedbforward" to
"feedforward" for "feed
forward" and three space slips of the same kind. The remaining slip is
"lls" to "ls" for "los". Among the clean controls, `neighbour_clean` stays at 390 of 400. The
count for `phrase_clean` goes from 292 to 294 of 300. The count for `required_control` stays at
18 of 18.

The requested words get 163 of 164 test cases right with the model. The counts are 12 of 12
clean and 36 of 36 with the next word. The named slips give 18 of 18, and the other slips give
79 of 80. The controls give 18 of 18.

## Effect of the model on the words of the field

The model helps on four measures and lowers three. Table 9 and Table 11 give the numbers.

- The model helps: phrases 947 to 980 and neighbour controls 990 to 1,028. The technical stream
  improves from 13.75 to 12.80 changed words per 1,000. The everyday stream improves from 10.80
  to 3.55.
- The model lowers slips of pack words from 631 to 627 and the requested words from 164 to 158.
  The capitals fall from 1,604 to 1,558. Of the 46 capital cases, 32 are slips corrected by the
  engine and left uncorrected by the model. Of these, 18 are at the start of a sentence. Another
  12 are controls that the model changes with the pack off too.
- Without the pack, the model keeps 835 of 950 clean pack words. The model changes 16.59 of
  1,000 words of technical text against 3.55 of everyday text. It knows the words of the field
  less well than everyday words.

## Use of the pack by the next fine-tune

Technical clean text in the training data looks necessary. The model was trained on everyday
sentences in lower case. With the pack off, the model changes technical text 4.7 times as often
as everyday text. The counts are 16.59 against 3.55 words per 1,000. The fine-tuning worker
found that clean running text in training cuts the changed correct words by more than half. That
text was everyday text.

A later training round can take these steps. The page does not build them.

1. Add clean running technical text, typed word by word with the work area on. Each list must
   hold the readings that the engine gives with the supplement.
2. Take that text from the build bucket alone. `collect_corpus.py` writes held-out sentences
   only today, so it needs one more output, a sample of build sentences. The dev and test
   documents of this page must stay out of training.
3. Add slips of pack words in technical sentences, built as `domain_slip_new` and
   `domain_slip_raised` are. Add slips at the start of a sentence, where the model lowers the
   engine most.
4. Keep the capitals and punctuation of the source in the text before the word. The contexts of
   the new cases have them. The everyday training text does not keep the capitals and
   punctuation.
5. Use `cases/english-domain.dev.jsonl` and the three streams as selection sets. Keep the
   existing rule: the clean running text must stay at least as good.
6. Measure the protection again with the new model. A model that keeps `domain_clean_new`
   without it can give back the 85 cases of `term_for_everyday_word`.

## Work area in the sentence proofreader

The proofreader (`Shared/SentenceProofreader.swift`) does not know the work area today. It can
"fix" a word of the pack that the keyboard just kept. Three changes would pass the area on:

1. Add one sentence to `SystemModelProofreader.instructions` when the area is on: "The person
   writes about AI and software."
2. Add one line to each request with the pack's words from the sentence. The line reads:
   "These words are
   correct: PyTorch, vLLM, ultrathink." The list is short, because it holds only the
   words of that sentence.
3. In `KeyboardTextLogic.acceptedProofreading`, drop an answer that changes or removes a word of
   the pack that the sentence held.

The page does not build these changes.

## Decisions for the user

Table 17. Choices that are the user's, with what ships now.

| # | Decision | Ships now | The other way |
| --- | --- | --- | --- |
| 1 | Protection of a typed new word from the model | On. 399 of 400 clean new words stay, and 28 of 158 slips that spell a new word are corrected. | Off: 388 of 400, and 113 of 158 (Table 14). |
| 2 | Domain share | 0.3, the pick of the rule (Table 8). | 1.0 corrects 37 more slips of pack words and turns "model" into "models" in one control. |
| 3 | A typed capital on a word of the pack that is also a name | The preferred form: "Lora" becomes "LoRA". One backspace keeps "Lora" from then on. | Mark more words as everyday words by hand. |
| 4 | Frequency of a requested word | Zipf 4.5 (Table 3). | 5.0 corrects 1 more of 80 slips. |
| 5 | Place of the work area switch | `duo:work` typed in any field. | A switch in the app, which needs an app group shared with the keyboard. |
| 6 | More requested words | "ultrathink" and "ultracode" only. | See the list below. |
| 7 | A slip after a hyphen, as "fine-tunign" | Not corrected, as before the pack. | Let the keyboard read the word after a hyphen, which also changes everyday text. |

The corpora miss some words of coding agents and of this project's own tools. With the pack on,
the keyboard changes correctly typed "worktree" and "worktrees" (to "work tree"). The keyboard
also changes "ultraplan", "ultrareview", "autocompact", "codegen", "typecheck", "precommit" and
"devcontainer". Further changes include "testflight", "nextjs", "swiftui", "xcode", "pnpm",
"vite" and "todo". The keyboard does not correct slips of the following words, which stay as
typed: "tmux", "ripgrep", "vercel", "supabase" and "litellm". The same applies to "langfuse",
"wandb", "runpod", "vibecoding" and "llamacpp". The pack does not include any of these words.

## Limits of this design

- The frequencies come from written text: papers, questions and documentation. A person's chat
  about the same work uses other words more often.
- The Stack Exchange dump ends in 2024-04. Newer words reach the pack through arXiv and the
  documentation only.
- A typed capital gives the preferred form for a word of the pack that is also a name. "Lora"
  becomes "LoRA". The pack knows 8 everyday words. The list does not include a name outside
  Tatoeba.
- The keyboard infers its own capital from the place in the text. It does not record whether the
  person or the automatic shift made the capital.
- The cases take their words from the pack and give the context ready in the field. The case set
  does not include a slip that spells a known word. The case set does not cover a slip of a pack
  word shorter than 4 letters.
- The posts of one Stack Exchange thread can sit in two buckets. One thread does not bring a
  word into the pack, because a word needs 20 documents in 2 sources.
- The keyboard does not read a word after a hyphen, so a slip there stays: 0 of 147 dev cases.
- The time per correction on the phone with the supplement was not measured.
- The keyboard's scorer and the harness scorer differ in one request of the new cases on the
  macOS runner. The cause was not found.

## Phone checks

Type each line in a field that capitalizes sentences, such as Notes. The engine alone gives
these results in the harness and in the unit tests of the simulator. Phone testing does not
cover these lines yet.

Table 18. Lines to type on the phone, each followed by a space.

| Type | Expect |
| --- | --- |
| the pytorch tokenizer and the evals | no change. With the work area off, the engine alone gives "porch" and "evils". |
| we trained the llm with pytorch on two gpus | no change |
| we trained it with pytorhc | "pytorch" |
| we trained it with Pytorhc | "PyTorch" |
| Gpu (as the first word, with the automatic capital) | "GPU" |
| we need one more Gpu | "GPU" |
| we need one more gpu | no change |
| I use PYTORCH | no change |
| please ultrathink about this and use ultracode | no change |
| please ultrathnik | "ultrathink" |
| use ultracoed | "ultracode" |
| an ultrathin ultrasound | no change |
| it is hard coded | no change, two words |
| It was Monday and Tom saw us | no change |
| we trained it with Pytorch, then one backspace | "PyTorch", then "Pytorch", and "Pytorch" stays from then on |
| duo:work | the text goes away, and the space bar shows "AI and software words off" |

## Files of the pack

| File | Content |
| --- | --- |
| `scripts/domain-pack/collect_corpus.py`, `sources.json` | The collector of the domain text, and its sources |
| `scripts/domain-pack/build_pack.py` | The rules of this page, from the counts to the pack |
| `scripts/domain-pack/pack/` | The corpus words with every number, the phrases, the sources, and the requested words |
| `scripts/domain-pack/check_supplement.py` | The checks of the supplement, the capitals rule and the protection |
| `scripts/domain-pack/build_merged_lexicon.py` | The comparison lexicon of Table 4 |
| `scripts/domain-pack/attribute_cases.py` | The attribution table of the case sources |
| `scripts/domain-pack/requested_frequency.py` | The comparison of frequencies for the requested words |
| `Engine/duo_engine.c`, `Engine/duo_engine.h` | The supplement |
| `Shared/PreferredCapitals.swift` | The rule of the preferred capitals, and the protection |
| `Shared/KeyboardTextController.swift` | The work area in the keyboard, and its switch |
| `scripts/lm-rerank/rerank.py` | The same supplement, rule and protection in the harness |
| `scripts/lm-rerank/domain_pack.py`, `domain_pack_table.py`, `domain_pack_shares.py` | The measurement, its tables, and the share rule |
| `scripts/typing-evaluation/build_english_domain_cases.py` | The new cases |
| `Tests/DomainPackTests.swift` | The unit tests of the rule, the engine and the keyboard |
| `docs/domain-pack-design-review.md` | The Codex review of this design |
