# libime adapter for the Pinyin typing evaluation

## Summary

With the fcitx5 phone defaults, libime 1.1.17 converts 73.4 percent of [clean](#terms-of-the-libime-evaluation "A clean case holds correct Pinyin") [dev](#terms-of-the-libime-evaluation "The dev half is the half of the cases where settings may be chosen") cases and repairs 9.5 percent of [slips](#terms-of-the-libime-evaluation "A slip case holds one or two typing mistakes that the case generator put in").

1. Use the engine name `libime-fcitx5-mobile` as the libime row of the engine comparison. Its dev scores are in the file `libime-fcitx5-mobile/pinyin.dev.summary.json` of the artifact `typing-evaluation-libime`.
2. Plan a typo layer outside libime for doubled letters and extra letters. On the dev half, libime repairs 0 to 0.7 percent of those cases. The slip operators in `scripts/typing-evaluation/keyboard_noise.py` list the slips that such a layer must undo.
3. Start a new run with a push to the branch `eval/libime`. Find the run with `gh run list --branch eval/libime --limit 1`. Read its scores with `gh run download RUN_ID --name typing-evaluation-libime --dir DIR`, where `DIR` is an empty folder.

The scores do not give slip rates in real typing, latency on a phone, or memory on a phone.

## Pinyin conversion task with libime in the Model row

The evaluation defines the task, and libime fills the Model row. The other seven rows are the same for every engine.

Table 1. The Pinyin conversion task of the evaluation, in the eight rows that define a machine learning task.

| Row | Pinyin conversion with libime |
| --- | --- |
| Input | One string, `typed`: 4 to 80 letters a to z with no spaces. The string is the toneless Pinyin of a clause, and a slip case holds one or two slips. One example is `dadehao`. |
| Model | libime: a dictionary search with a trigram language model. The run does not train any part of libime. The 1.1.17 data holds 300,624 dictionary lines and 7,250,101 language model entries. |
| Output | One string of any length: the first sentence that libime gives for all the letters. The string is Chinese text. A part that libime does not convert stays in Latin letters. |
| Target | `intended`: a clause of 2 to 20 Simplified Chinese characters from Tatoeba. The case generator made its Pinyin with pypinyin. |
| Training signal | None. libime runs with its stock data, and each engine name has a fixed flag set. |
| Negatives | The clean cases: correct Pinyin, where slip handling must not lower accuracy. Each half has 900 clean cases beside 2,100 slip cases. |
| Split | The Tatoeba sentence, by the parity of its id. One parity forms the dev half and the other the test half. |
| Eval | Exact match between output and target, as a percent of cases. The scorer counts per category of 300 cases, then pools the 3 clean categories and the 7 slip categories. The scorer also gives character accuracy per category. Character accuracy is 1 minus the edit distance over the target length, floored at 0. The scorer averages that value over the cases. |

Each flag set is read against the same libime build with every flag off, scored in the same run.

## Terms of the libime evaluation

Each term below keeps one meaning in every section.

Table 2. Terms that this document uses with one fixed meaning.

| Term | Meaning |
| --- | --- |
| libime | The Pinyin engine library of [fcitx5](https://github.com/fcitx/fcitx5 "fcitx5 is an open-source input method framework"). The libime source is at https://github.com/fcitx/libime. |
| case | One test input: the typed Pinyin letters, and the Chinese text the person meant. |
| clean case | A case with correct Pinyin. |
| slip case | A case with one or two typing mistakes that the case generator put in. |
| dev half, test half | The two halves of the cases. Settings may be chosen on the dev half only. |
| fuzzy flag | A libime option of the type `PinyinFuzzyFlag`. Each flag lets more spellings match a syllable. |
| correction profile | A libime table that lists, for each key, the keys a finger may hit in its place. |
| decoder | The part of libime that searches for the most likely sentence for the typed letters. |
| language model | The table that the decoder uses to rank sentences. The table scores sequences of 1, 2 and 3 words. The field calls such a table a trigram model. |
| KenLM | The open-source library whose binary file format holds the libime language model. The KenLM source is at https://github.com/kpu/kenlm. |
| engine name | The label of one libime build with one set of fuzzy flags. The output files use this label. |
| address layout | The memory addresses that a process gets. Linux picks them at random for each process by default. |

## Eleven engine names for libime builds and flag sets

An engine name is one libime build with one set of fuzzy flags. Three names repeat the packaged flag sets on the source build, and one name is a control. These four names separate flag effects from code effects and data effects.

Table 3. The eleven engine names, in plain words.

| Engine name | libime build and settings | Reason the name exists |
| --- | --- | --- |
| `libime-none` | libime 1.1.5 from the Ubuntu packages, with every fuzzy flag off | The baseline of the packaged version |
| `libime-commontypo` | libime 1.1.5 with the flag CommonTypo | The first of the two typo flags |
| `libime-advancedtypo` | libime 1.1.5 with CommonTypo and AdvancedTypo | The second typo flag, which exists from libime 1.1.3 |
| `libime-src-none-packaged-data` | The libime 1.1.17 code with the packaged dictionary and language model, with every fuzzy flag off | The control that separates the newer code from the newer data |
| `libime-src-none` | libime 1.1.17 built from source with its own data, with every fuzzy flag off | The baseline of the source build |
| `libime-src-commontypo` | libime 1.1.17 with CommonTypo | The CommonTypo effect on the source build |
| `libime-src-advancedtypo` | libime 1.1.17 with CommonTypo and AdvancedTypo | The control for `libime-correction`: same code, same data, Correction off |
| `libime-correction` | libime 1.1.17 with CommonTypo, AdvancedTypo and Correction, and the built-in QWERTY correction profile | The Correction flag, which exists from libime 1.1.7 |
| `libime-fcitx5-desktop` | libime 1.1.17 with the decoder options that the fcitx5 Pinyin input method sets on a desktop | The decoder settings of a desktop user of fcitx5 |
| `libime-fcitx5-mobile` | The desktop options plus Correction with the QWERTY correction profile | The decoder settings of fcitx5 on Android and iOS |
| `libime-allflags` | The phone options plus PartialFinal and the 13 sound-pair flags | The most tolerant setting that libime offers |

Table 4 gives the spellings that each flag accepts, in plain words. The first three rows come from probe strings that the workflow types.

Table 4. Fuzzy flags in the engine names. A quoted text is the label of the option in fcitx5.

| Fuzzy flag | Spellings that the flag accepts |
| --- | --- |
| `CommonTypo` | Fixed letter swaps such as `gn` for `ng`: the probe `zhognguo` gives 中国 |
| `AdvancedTypo` | More swaps inside one syllable, such as `oa` for `ao`: the probe `nihoa` gives 你好 |
| `Correction` | One key replaced by its left or right neighbor: the probe `nihso` gives 你好 |
| `VE_UE` | "ue -> ve" |
| `Letter` | "Match Letter in lower case" |
| `Inner` | "Inner Segment (xian -> xi'an)" |
| `InnerShort` | "Inner Segment for Short Pinyin (qie -> qi'e)" |
| `PartialFinal` | "Match partial finals (e -> en, eng, ei)" |
| 13 sound-pair flags | Two sounds read as one, such as "l <-> n", "z <-> zh" and "an <-> ang" |

Table 5 gives the exact flags of each engine name. The more flags a name has, the more spellings libime accepts for one syllable.

Table 5. The flags that the adapter passes to `PinyinIME::setFuzzyFlags`, and the other settings of each engine name.

| Engine names | Fuzzy flags | Other settings |
| --- | --- | --- |
| `libime-none`, `libime-src-none-packaged-data`, `libime-src-none` | `None` | Library defaults |
| `libime-commontypo`, `libime-src-commontypo` | `CommonTypo` | Library defaults |
| `libime-advancedtypo`, `libime-src-advancedtypo` | `CommonTypo`, `AdvancedTypo` | Library defaults |
| `libime-correction` | `CommonTypo`, `AdvancedTypo`, `Correction` | Library defaults, QWERTY correction profile |
| `libime-fcitx5-desktop` | `VE_UE`, `CommonTypo`, `AdvancedTypo`, `Letter`, `Inner`, `InnerShort` | fcitx5 settings |
| `libime-fcitx5-mobile` | The desktop flags and `Correction` | fcitx5 settings, QWERTY correction profile |
| `libime-allflags` | The phone flags, `PartialFinal`, `V_U`, `AN_ANG`, `EN_ENG`, `IAN_IANG`, `IN_ING`, `U_OU`, `UAN_UANG`, `C_CH`, `F_H`, `L_N`, `L_R`, `S_SH`, `Z_ZH` | fcitx5 settings, QWERTY correction profile |

The library defaults are 1 sentence, beam size 20 and frame size 40, as the adapter printed them. Beam size and frame size limit the candidates that the decoder keeps.

The fcitx5 settings are five calls that fcitx5-chinese-addons adds to the library defaults:

- `setNBest(2)` keeps 2 sentences, the fcitx5 option "Number of Sentences".
- `setWordCandidateLimit(15)` is the fcitx5 option "Number of Phrase Candidates".
- `setPartialLongWordLimit(4)` is the fcitx5 option "Prompt long word length when input length over (0 for disable)".
- `setScoreFilter(1.0)` is a fixed call in `pinyin.cpp`, with the argument name `maxDistance` in libime.
- `setMaxSentenceLength(35)` makes libime refuse more letters once the sentence holds more than 35 syllables. The longest case has 20 characters.

The flag defaults come from `im/pinyin/pinyin.h` and `im/pinyin/pinyin.cpp` of fcitx5-chinese-addons, master branch, read on 2026-11-09. The two fcitx5 names copy the decoder options only. The fcitx5 app also loads its own dictionary `chaizi.dict`, and `extb.dict` on a desktop. The adapter loads neither file.

## Scores of the eleven engine names on the dev half and the test half

Every engine name repairs less than 19 percent of the slip cases. Each added typo flag raises that percent: CommonTypo, AdvancedTypo, Correction, then the sound-pair flags with PartialFinal.

Table 6. Percent of cases with an exact match, in workflow run 42762822650. Each half has 900 clean cases and 2,100 slip cases. `score.py` prints the same values as shares from 0 to 1.

| Engine name | Clean, dev | Slips, dev | Clean, test | Slips, test |
| --- | --- | --- | --- | --- |
| `libime-none` | 68.89 | 1.52 | 68.56 | 1.14 |
| `libime-commontypo` | 68.89 | 2.29 | 68.56 | 1.62 |
| `libime-advancedtypo` | 68.78 | 4.57 | 68.33 | 3.71 |
| `libime-src-none-packaged-data` | 68.89 | 1.52 | 68.56 | 1.14 |
| `libime-src-none` | 73.67 | 1.76 | 71.22 | 1.29 |
| `libime-src-commontypo` | 73.56 | 2.71 | 71.11 | 1.95 |
| `libime-src-advancedtypo` | 73.56 | 4.95 | 71.22 | 4.43 |
| `libime-correction` | 73.44 | 9.52 | 71.00 | 8.48 |
| `libime-fcitx5-desktop` | 73.44 | 4.95 | 71.33 | 4.43 |
| `libime-fcitx5-mobile` | 73.44 | 9.52 | 71.11 | 8.48 |
| `libime-allflags` | 65.67 | 18.05 | 65.11 | 16.14 |

```mermaid
---
config:
  themeVariables:
    xyChart:
      plotColorPalette: "#0969da"
---
xychart-beta horizontal
    title "Dev slip cases with an exact match, of 2,100"
    x-axis "Engine name and its percent" ["libime-none 1.5", "libime-commontypo 2.3", "libime-advancedtypo 4.6", "libime-src-none-packaged-data 1.5", "libime-src-none 1.8", "libime-src-commontypo 2.7", "libime-src-advancedtypo 5.0", "libime-correction 9.5", "libime-fcitx5-desktop 5.0", "libime-fcitx5-mobile 9.5", "libime-allflags 18.0"]
    y-axis "Slip cases repaired (percent)" 0 --> 100
    bar [1.52, 2.29, 4.57, 1.52, 1.76, 2.71, 4.95, 9.52, 4.95, 9.52, 18.05]
```

Figure 1. Slip cases repaired on the dev half, one bar per engine name, on one scale from 0 to 100 percent. A bar at 100 means every slip case repaired. The longest bar, `libime-allflags`, ends at 18.0 percent.

Five comparisons in Table 6 change one group of settings at a time. The runs do not separate the flags inside one group.

- Correction raises the repaired dev slip cases from 4.95 to 9.52 percent. Clean dev accuracy goes from 73.56 to 73.44 percent.
- The sound-pair flags and PartialFinal raise the repaired dev slip cases from 9.52 to 18.05 percent. The same flags lower clean dev accuracy from 73.44 to 65.67 percent.
- The fcitx5 settings and four more flags change the exact-match counts by at most 1 of 3,000 dev cases. The four flags are `VE_UE`, `Letter`, `Inner` and `InnerShort`. Table 8 shows their effect on character accuracy.
- The newer data raises clean dev accuracy from 68.89 to 73.67 percent. Clean test accuracy goes from 68.56 to 71.22 percent.
- The newer code leaves every exact-match score of Table 6 and Table 7 unchanged. `libime-src-none-packaged-data` and `libime-none` differ in 11 of 6,000 outputs, and both miss each of those cases.

The evaluation allows a setting to lower clean dev accuracy by 1 point against the engine with slip handling off. `libime-allflags` lowers clean dev accuracy from 73.67 to 65.67 percent, so the name serves as an upper reference only. Inside the 1-point limit, `libime-correction` and `libime-fcitx5-mobile` repair the most dev slip cases, 9.52 percent each. `libime-fcitx5-mobile` is the libime row, because fcitx5 uses these options on a phone. The test half did not take part in this choice.

Table 7. Percent of dev slip cases with an exact match, by slip category. Each category has 300 cases, and the last column pools the 2,100 cases.

| Engine name | `substitution_adjacent` | `deletion` | `double_letter` | `extra_adjacent` | `transposition` | `two_errors` | `fuzzy_sound` | All slips |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `libime-none` | 0.00 | 10.67 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.52 |
| `libime-commontypo` | 0.00 | 11.67 | 0.00 | 0.00 | 4.33 | 0.00 | 0.00 | 2.29 |
| `libime-advancedtypo` | 0.00 | 11.67 | 0.00 | 0.00 | 20.33 | 0.00 | 0.00 | 4.57 |
| `libime-src-none-packaged-data` | 0.00 | 10.67 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.52 |
| `libime-src-none` | 0.00 | 12.33 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.76 |
| `libime-src-commontypo` | 0.00 | 13.67 | 0.00 | 0.00 | 5.33 | 0.00 | 0.00 | 2.71 |
| `libime-src-advancedtypo` | 0.00 | 13.67 | 0.00 | 0.00 | 20.67 | 0.33 | 0.00 | 4.95 |
| `libime-correction` | 30.00 | 13.67 | 0.00 | 0.00 | 22.00 | 1.00 | 0.00 | 9.52 |
| `libime-fcitx5-desktop` | 0.00 | 13.67 | 0.00 | 0.00 | 20.67 | 0.33 | 0.00 | 4.95 |
| `libime-fcitx5-mobile` | 30.00 | 13.67 | 0.00 | 0.00 | 22.00 | 1.00 | 0.00 | 9.52 |
| `libime-allflags` | 24.67 | 20.00 | 0.33 | 0.67 | 19.33 | 2.00 | 59.33 | 18.05 |

Each flag repairs mainly one slip category, and two categories stay near zero under every flag set:

- Correction repairs 30.0 percent of the neighbor-key substitutions. The QWERTY correction profile lists the left and right neighbor of each key. The case generator also uses neighbors in the row above and the row below.
- Correction adds 96 repaired dev cases: 90 neighbor-key substitutions, 4 swapped-letter cases and 2 two-slip cases.
- AdvancedTypo repairs 20.3 to 20.7 percent of the swapped letters. CommonTypo alone repairs 4.3 to 5.3 percent.
- `libime-allflags` repairs 59.3 percent of the `fuzzy_sound` cases. Against `libime-fcitx5-mobile`, the same name repairs fewer substitutions (30.00 to 24.67 percent) and fewer swapped letters (22.00 to 19.33 percent).
- Every engine name repairs 0 to 0.7 percent of the doubled letters and the extra letters.
- The engine names repair 10.7 to 20.0 percent of the deleted letters. One cause is that libime reads a lone consonant as the start of a syllable.

Character accuracy counts the right characters inside a sentence that is not an exact match. The fcitx5 settings and four more flags raise character accuracy on 6 of the 7 slip categories.

Table 8. Character accuracy on the dev half, in percent, by category. Each value is the mean over 300 cases.

| Engine name | `clean_short` | `clean_medium` | `clean_long` | `substitution_adjacent` | `deletion` | `double_letter` | `extra_adjacent` | `transposition` | `two_errors` | `fuzzy_sound` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `libime-none` | 80.28 | 91.34 | 94.18 | 54.19 | 65.91 | 56.67 | 50.92 | 41.10 | 29.99 | 70.18 |
| `libime-commontypo` | 80.28 | 91.34 | 94.18 | 55.27 | 66.34 | 56.84 | 51.66 | 45.44 | 31.36 | 70.18 |
| `libime-advancedtypo` | 80.28 | 91.23 | 94.14 | 55.50 | 66.63 | 56.73 | 52.07 | 54.55 | 34.71 | 70.02 |
| `libime-src-none-packaged-data` | 80.28 | 91.34 | 94.18 | 54.19 | 65.70 | 56.67 | 50.92 | 41.17 | 29.93 | 70.18 |
| `libime-src-none` | 82.78 | 93.31 | 95.63 | 54.26 | 67.00 | 58.00 | 52.68 | 42.45 | 31.96 | 71.08 |
| `libime-src-commontypo` | 82.78 | 93.24 | 95.63 | 55.34 | 67.65 | 58.21 | 53.31 | 46.59 | 33.44 | 71.08 |
| `libime-src-advancedtypo` | 82.78 | 93.13 | 95.63 | 56.00 | 68.10 | 58.23 | 53.73 | 55.65 | 36.42 | 71.08 |
| `libime-correction` | 82.94 | 93.15 | 95.60 | 75.04 | 74.17 | 69.42 | 60.82 | 66.66 | 50.99 | 71.10 |
| `libime-fcitx5-desktop` | 82.78 | 93.13 | 95.60 | 59.96 | 72.81 | 67.21 | 57.55 | 63.49 | 44.67 | 70.77 |
| `libime-fcitx5-mobile` | 82.72 | 93.13 | 95.62 | 75.00 | 73.84 | 68.69 | 61.35 | 66.28 | 50.79 | 71.05 |
| `libime-allflags` | 76.11 | 89.56 | 93.16 | 71.84 | 72.62 | 64.91 | 58.70 | 64.48 | 48.94 | 89.88 |

Two rows of Table 8 differ in the fcitx5 settings and the four flags only:

- On swapped letters, character accuracy goes from 55.65 percent for `libime-src-advancedtypo` to 63.49 percent for `libime-fcitx5-desktop`.
- On deleted letters, character accuracy goes from 68.10 to 72.81 percent.

## Repeatable outputs through a fixed address layout

The scored runs start the adapter with a fixed address layout, so two processes give the same outputs. With the normal random layout, libime 1.1.17 with its 2026 data gives a different first sentence for a few cases.

Table 9. Dev outputs that differ between two adapter processes, of 3,000 cases, in workflow run 42762822650. Both layouts ran with the same environment.

| libime build and flags | Random address layout | Fixed address layout |
| --- | --- | --- |
| libime 1.1.5 packages, every flag off | 0 | 0 |
| libime 1.1.17 source build, every flag off | 4 | 0 |
| libime 1.1.17 source build, fcitx5 phone options | 18 | 0 |

The fixed layout also repeats across runner machines. Workflow runs 42759199191 and 42762822650 gave the same 66,000 outputs for the eleven engine names.

One case shows the effect of the random layout. For the letters `zheshigeguanzi`, `libime-src-none` gave 这是个管子 in run 42753887385 and 这是个罐子 in run 42757015202. Both runs used the random layout.

The file `src/libime/core/decoder.cpp` of libime gives a mechanism that fits these counts:

1. The function `buildLattice` keeps the word candidates in a hash table whose keys are memory addresses.
2. The function moves the candidates out in the order of that table.
3. The search compares scores, and the code does not give a second key for equal scores.

Candidates with equal scores can therefore change order when the addresses change. A phone app also gets a random layout, so the same effect is possible there. The runs measured Linux processes only.

With the packaged data, the outputs did not depend on the address layout. The three names on libime 1.1.5 gave the same outputs in runs 42753887385 and 42757015202, which used the random layout. The fixed layout gave these outputs again. `libime-src-none-packaged-data` gave the same outputs under the random layout of run 42757015202 and under the fixed layout.

The build file of libime 1.1.17 passes `-q 4` to the model builder, and the build file of 1.1.5 passes `-q 8`. The option sets the bits for each stored probability. A coarser model can make equal scores more common. The runs did not test this difference as the cause.

The adapter gets the fixed layout from `setarch -R`. `check_repeatability.py` makes the counts of Table 9.

## Versions and packages on the ubuntu-24.04 runner

The runner installed libime 1.1.5 from Ubuntu packages and built libime 1.1.17 from source in one job.

Table 10. Packages that `apt-get install` put on the runner for the engine names on libime 1.1.5.

| Package | Version |
| --- | --- |
| `libimepinyin-dev`, `libimepinyin0` | 1.1.5-1 |
| `libimecore-dev`, `libimecore0` | 1.1.5-1 |
| `libime-bin`, `libimetable0` | 1.1.5-1 |
| `libime-data` | 1.1.5-1 |
| `libime-data-language-model` | 1.1.5-1 |
| `libfcitx5utils-dev`, `libfcitx5utils2` | 5.1.7-1build3 |
| `libboost-dev` | 1.83.0.1ubuntu2 |
| `libboost1.83-dev` | 1.83.0-2.1ubuntu3.2 |
| `g++` | 13.3.0-6ubuntu2~24.04.1 |

CMake 3.31.6 and Ninja come from the runner image.

Table 11. Sources and packages of the libime 1.1.17 build.

| Part | Version |
| --- | --- |
| libime | Tag `1.1.17`, commit `171edcf137001e8eb8274f53ec010058cda70b09`, from https://github.com/fcitx/libime |
| KenLM inside libime | Submodule commit `4cb443e60b7bf2c0ddf3c745378f76cb59e254e5` |
| fcitx5 utility library | Tag `5.1.23`, commit `27cca6e0239938b2d53937061d0980c087856b22`, target `Fcitx5Utils` only |
| `gcc-14`, `g++-14` | 14.2.0-4ubuntu2~24.04.1 |
| `extra-cmake-modules` | 5.115.0-0ubuntu5 |
| `gettext` | 0.21-14ubuntu2 |
| `libboost-iostreams-dev` | 1.83.0.1ubuntu2 |
| `libzstd-dev`, `zstd` | 1.5.5+dfsg2-2build1.1 |

libime 1.1.17 needs the fcitx5 utility library 5.1.20 or later, and Ubuntu 24.04 packages 5.1.7. The job builds both libraries into the folder `build/libime-source/prefix`. The adapter for the source build runs with `LD_LIBRARY_PATH` set to that folder. The job checks the loaded libraries with `ldd`.

Table 12. Data files that the adapter loads. Both language models are trigram models.

| Property | libime 1.1.5 packages | libime 1.1.17 source build |
| --- | --- | --- |
| Dictionary file | `/usr/share/libime/sc.dict`, 3,170,345 bytes | `share/libime/sc.dict` in the prefix folder, 4,524,344 bytes |
| Dictionary source | The package `libime-data` | `dict-20260907.tar.zst`, where `dict_sc.txt` has 300,624 lines |
| Language model file | `/usr/lib/x86_64-linux-gnu/libime/zh_CN.lm`, 22,138,741 bytes | `lib/libime/zh_CN.lm` in the prefix folder, 34,736,327 bytes |
| Language model source | The package `libime-data-language-model` | `lm_sc.arpa-20260629.tar.zst` |
| n-gram order | 3 | 3 |
| Entries of 1, 2 and 3 words | 199,870, 2,522,964 and 1,000,002 | 270,714, 4,789,953 and 2,189,434 |

The n-gram order comes from the KenLM header of each file, read by `kenlm_header.py`. For the source build, the header of the text file `lm_sc.arpa` shows the same three counts. The libime build sets `KENLM_MAX_ORDER=3`, which limits the largest order to 3. The libime build downloads both archives from https://download.fcitx-im.org/data/ and checks each against a pinned SHA-256 value.

## Licenses of the libime code and data

The libime code and the libime data carry the license LGPL-2.1-or-later.

Table 13. License of each part, and the file that states it.

| Part | License | File that states the license |
| --- | --- | --- |
| libime code, versions 1.1.5 and 1.1.17 | LGPL-2.1-or-later | The SPDX line at the top of each source file, and `LICENSES/LGPL-2.1-or-later.txt` |
| Language model archive `lm_sc.arpa-*.tar.*` | LGPL-2.1-or-later | `REUSE.toml` at tag 1.1.17 |
| Dictionary archive `dict-*.tar.*` | LGPL-2.1-or-later | `REUSE.toml` at tag 1.1.17 |
| Ubuntu packages `libime-data` and `libime-data-language-model` | LGPL-2.1+ | The entry `Files: *` of `/usr/share/doc/libime-data/copyright` on the runner |
| KenLM inside libime | LGPL for most files, with other licenses for a few utility files | `LICENSE` in https://github.com/kpu/kenlm |
| fcitx5 utility library | LGPL-2.1-or-later | The SPDX line at the top of each source file |

## libime calls in the adapter

The adapter `libime_adapter.cpp` makes seven kinds of libime calls, in this order:

1. `PinyinIME ime(std::make_unique<PinyinDictionary>(), std::make_unique<UserLanguageModel>(LM_PATH))` builds the engine with the stock language model.
2. `ime.dict()->load(PinyinDictionary::SystemDict, DICT_PATH, PinyinDictFormat::Binary)` loads the stock dictionary.
3. `ime.setCorrectionProfile(std::make_shared<PinyinCorrectionProfile>(BuiltinPinyinCorrectionProfile::Qwerty))` loads the QWERTY correction profile, for the engine names with Correction.
4. `ime.setFuzzyFlags(flags)` sets the flags of Table 5. The fcitx5 names also get the four `PinyinIME` setters listed under Table 5.
5. `PinyinContext context(&ime)` makes a new context for each case. The fcitx5 names also call `context.setMaxSentenceLength(35)`.
6. `context.type(&letter, 1)` types the case one letter at a time, as a keyboard does. The adapter stops when libime does not accept a letter.
7. `context.select(0)` takes the first candidate while `context.selected()` is false. `context.selectedSentence()` then gives the output.

In every run the first candidate covered all the letters, so step 7 made one pick per case. The first candidate is the sentence that `PinyinContext::sentence()` returns.

Seven files of this folder and one workflow file make the evaluation run.

Table 14. Files of the adapter folder.

| File | Content |
| --- | --- |
| `libime_adapter.cpp` | The C++ program that types the cases into libime |
| `CMakeLists.txt` | The build file, which finds the installed libime through `find_package(LibIMEPinyin)` |
| `run_libime.py` | Feeds the cases to the adapter and writes `build/typing-evaluation/NAME/pinyin.HALF.jsonl` |
| `check_repeatability.py` | Counts the outputs that differ between two adapter processes |
| `kenlm_header.py` | Prints the n-gram order and the n-gram counts of a language model file |
| `summarize.py` | Prints the score tables from the summary files of `score.py` |
| `probes.tsv` | Fifteen strings that the workflow types before the scored runs, such as `nihao` |
| `.github/workflows/eval-libime.yml` at the repository root | The workflow that installs, builds, runs, scores and uploads |

## Limits of the adapter and of the scores

- The adapter reads the first sentence only. A person can also pick a lower candidate.
- The adapter loads the stock dictionary and the stock language model only. The adapter does not load a user dictionary, a typing history, `chaizi.dict`, `extb.dict` or `zh_CN.lm.predict`, and never calls `learn()`.
- Each case starts in a new context, so libime does not see the text before the clause.
- The packaged libime 1.1.5 does not have the Correction flag, so `libime-correction` exists for the source build only.
- The scores hold for the fixed address layout and for this order of the cases. Table 9 gives the size of the change under a random layout.
- With the packaged data, typing letter by letter and typing all letters in one call give the same outputs. With the 2026 data the two outputs differ in 5 to 27 of 3,000 cases per run. The scores use one letter at a time.
- In run 42762822650 the adapter took 0.6 to 1.3 milliseconds per letter with Correction off. With Correction on, the adapter took 2.2 to 3.1 milliseconds. Four adapter processes ran at the same time on one runner, so these times do not predict phone latency.
- The corpus behind the libime language model is not stated in the files read for this work. An overlap with the Tatoeba sentences of the cases is therefore possible.
- The scores come from a slip generator and do not give the rate of each slip in real typing.
