# Check of the names and terms of the last years

`check_terms.py` types the Pinyin of each term of `terms.tsv` into the Pinyin engine and looks
for the term among the engine's candidates. [docs/pinyin-modern-words.md](../../../docs/pinyin-modern-words.md)
describes the change that this check measures.

| File | Content |
| --- | --- |
| `terms.tsv` | 500 names and terms that came into wide use from 2015 to 2025, in 12 groups. |
| `check_terms.py` | The check. It prints the counts per group and writes one line per term. |
| `results-before.tsv` | The result with the lexicon of build 71. |
| `results.tsv` | The result with the lexicon of this commit. |

| Lexicon | First reading | Among the first 5 | Offered at all |
| --- | --- | --- | --- |
| Build 71 | 330 | 374 | 376 |
| This commit | 410 | 465 | 471 |

The lexicon of this commit offers 95 more of the 500 terms.

The terms come from memory, among them the yearly lists of ten vogue words of the magazine
Yaowen Jiaozi. No term was checked against a source. The script derives the Pinyin of a term
from the libime dictionary, and `terms.tsv` gives the Pinyin of a term whose character has two
readings.

Run it on Linux, from the repository root, with the libime dictionary in `build/libime-data`
and the engine tool in `build/engine/duo_cli`:

```
python3 scripts/pinyin-dictionary/new-words-check/check_terms.py --out build/new-words-check/results.tsv
```
