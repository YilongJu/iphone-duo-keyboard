# The key "s" pressed in place of the key "a"

## Summary

The keyboard kept "thst" and "whst" in some sentences, although the typing engine reads them as
"that" and "what". The language model step moved the text back to the typed text. The keyboard's
rule now asks for a lead of 12 before typed text with an unknown word comes back. The lead was 4.

## Terms

| Term | Meaning |
| --- | --- |
| engine | The typing engine of `Engine/duo_engine.c`. The engine reads the typed text and chooses a correction. |
| rule | `KeyboardLanguageModel.rule`. The rule picks one reading from the engine's score and the language model's score. |
| text as typed | The reading that changes no typed character. |
| unknown word | A typed word that is in neither the lexicon nor its supplement (`duo_english_words_known`). |
| lead | How much higher the combined score of the text as typed must be before it replaces the engine's correction. |

## What went wrong

The person types "i think thst is fine". At the space after "thst", the engine reads "that". At
the space after "is", the keyboard reads the two words "thst is" again. The model reads the typed
letters in its prompt, and it gives the text as typed a high score. With a lead of 4, the text as
typed replaced "that is".

## The measurement

`compare_rules.py` types three sets of cases through the Linux copy of the keyboard rules
(`scripts/lm-rerank/rerank.py`), with the model file that the keyboard ships:

- The English dev cases of `scripts/typing-evaluation`, 6,799 cases.
- 1,134 slip words: the 150 most frequent words with an "a" in the dev cases, typed with "s" for
  each "a", each after 7 texts that are already in the field (`check_a_slips.py`).
- 22 whole typed sentences with "thst", "whst" or "sre" (`check_typed_sentences.py`).

Table 1. Right texts per lead for typed text with an unknown word, from `compare_rules.json`.
The lead for typed text of known words is 4 in every row with the model.

| Rule | Dev cases, of 6,799 | Clean dev cases, of 973 | Slip words, of 1,134 | Sentences, of 22 |
| --- | --- | --- | --- | --- |
| Engine alone | 6,075 | 957 | 1,048 | 22 |
| Lead 4 (the rule before) | 6,538 | 957 | 966 | 18 |
| Lead 8 | 6,543 | 955 | 1,011 | 21 |
| Lead 10 | 6,540 | 953 | 1,017 | 21 |
| Lead 12 (the rule now) | 6,540 | 953 | 1,021 | 22 |
| Lead 16 | 6,535 | 951 | 1,023 | 22 |
| Never back to the text as typed | 6,529 | 948 | 1,023 | 22 |

The higher the lead, the more slip words the keyboard fixes, and the fewer clean dev cases stay
as typed. The lead 12 is the lowest lead that gets all 22 sentences right. It fixes 55 more slip
words than the lead 4, and it changes 4 more clean dev cases.

## Limits

- The lead 12 was chosen on the dev cases and on the two slip sets of this folder. No other set
  has confirmed it.
- 113 of the 1,134 slip words are still wrong with the lead 12. The engine alone gets 86 wrong.
- The measurement ran on Linux. The phone runs the same rule in Swift (`RerankRule.choose`).

## How to run

On Linux, from the repository root, after `scripts/lm-rerank/build_on_linux.sh llama`:

```
python3 scripts/a-slip-check/compare_rules.py --shim "$PWD/build/lm-rerank/libduo_shim.so" \
    --lm build/lm-rerank/lm_score --model Shared/smollm2-lora-domain-s100-seed1.Q4_K_M.gguf \
    --out scripts/a-slip-check/compare_rules.json
```
