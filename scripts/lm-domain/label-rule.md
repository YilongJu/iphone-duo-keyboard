# Label rule for the remaining errors of the shipped file

## Summary

Each sampled error of the shipped file gets one of four labels, by the rule on this page.

1. Run `scripts/lm-domain/dump_errors.py` to write the errors of `ship` with their readings.
2. Take the sample of "Sample of the errors".
3. Give each error the first label of Table 2 whose rule holds.
4. Write the label and one short reason into the label file.

This page does not settle the share of each label in the owner's own typing.

## Sample of the errors

An error is a case that the shipped file gets wrong at the shipped setting, with the work area on.
The sample holds 200 errors of the set `dev` and 200 errors of the category `github_misspelling` of the set `github_select`.
Sort the errors of a set by the SHA-256 value of the case id, and take the first 200. A set with fewer errors gives all of them.

## Fields of one error

Table 1. Fields that the dump shows for an error.

| Field | Content |
| --- | --- |
| `context` | The text before the typed span |
| `typed` | The typed span |
| `intended` | The text that the case counts as right |
| `shown` | The text that the keyboard wrote |
| `corrections` | Each correction on the way: the readings of the engine with their engine score and the model's two scores, and the choice |
| `intended_in_list` | Whether the perfect chooser reaches the intended text from the engine's lists |

## Four labels in the order of their test

Table 2. Labels of the hand pass. The first label whose rule holds is the label of the error.

| Label | Rule | Example |
| --- | --- | --- |
| `label_noise` | The shown text is also correct English in this context, and the context does not decide between it and the intended text. Or the intended text is itself wrong, as a misspelling or a wrong word. | typed "there", shown "there", intended "their", after an empty context |
| `engine_recall` | `intended_in_list` is false. | typed "recieveing", and no reading is "receiving" |
| `model_error` | The lists hold the intended text, the shown text is wrong in this context, and the context or the typed span decides it. | "I want to", typed "goe", shown "goes", intended "go" |
| `unclear` | The labeller cannot decide between two of the labels above. | a context of two words that fits both texts in part |

The label `label_noise` comes first. An error whose intended text is wrong is label noise, also when no reading gives that text.

## Tests for the label of label noise

Apply the tests in this order. Stop at the first test that decides.

1. Read the context and the intended text as one sentence start. Do the same with the shown text.
2. When the intended text is a misspelling or the wrong word for the context, the label is `label_noise`.
3. When the shown text is not an English word or phrase, the label is not `label_noise`.
4. When the context is empty or one word, and both texts are real words, the label is `label_noise`.
5. When both texts fit the grammar and the sense of the context, the label is `label_noise`.
6. When only the intended text fits, the label is not `label_noise`. Go on to `engine_recall`.

A case of clean text follows the same tests. The intended text is then the typed text.
A real typo from GitHub has a context cut at the typo. Judge it on that context alone.

## Format of the label file

One JSON line per error: the case `id`, the `label`, and a `reason` of at most 15 words.
The labeller does not see the scores of any other model while labelling.
