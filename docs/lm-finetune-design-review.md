# Codex review of the distilgpt2 fine-tune design

## Summary

Codex (`gpt-6-astra`, `codex exec -c model_reasoning_effort=high`, read-only) reviewed the first
draft of `docs/lm-finetune-design.md` on 2026-11-10. It raised 9 points and 3 number corrections.
The design took every point in full or in part. It turned down one suggestion inside point 5:
an extra arm trained without the engine score in the loss.

This file is a decision record. It keeps the points that the current design no longer shows.

## Decisions on each point

Table 1. Each point of the review, the decision, and the reason.

| Point | Decision | Change in the design, or the reason to turn it down |
| --- | --- | --- |
| 1. The dev test checks a winner picked on the same dev cases | Accepted | The dev limit is p < 0.025 for two arms. The test read is the deciding comparison. The 6,799 generated cases are the main count. McNemar counts only cases where one arm is right and the other wrong. A bootstrap over the 574 repeated pairs is added. I counted the 574 myself: 6,225 distinct pairs in 6,799 cases. |
| 2. Each arm must type the cases with its own choices, and the oracle is greedy | Accepted | The design states that every arm replays every case through the keyboard rules. Lists without a target leave training only. The oracle is named the greedy oracle of `rerank.py`. |
| 3a. Add a fine-tune in the stock format | Accepted | New arm `lora-stock-format`. |
| 3b. Add a typed-format fine-tune without context | Accepted | New arm `chosen-no-context`. |
| 3c. Add a small trained chooser on engine features | Accepted | New arm `linear-features`, a linear listwise chooser on eight engine features. |
| 4a. Rule 4 drops 57 percent of the sentences | Accepted as a stated cost | The request names rule 4 for every context. The design keeps it and states the size and the phrases it removes. |
| 4b. The clean-word ban as written would ban common words | Accepted | The ban now covers whole words of the three list-based clean categories only. The draft text named every clean category, which would have banned 1,627 dev slip targets by Codex's count. |
| 4c. Train and tuning may share a sentence text | Accepted in part | A training sentence whose words equal a sentence of another split leaves training. The phrase rule does not run between the new splits. Those splits choose a checkpoint and a setting. Dev holds the measured cases, and all four rules protect it. |
| 4d. The published test misspellings rule reads `typed` | Accepted | The design states that this rule reads the `typed` field of the published test cases. |
| 5a. The loss text claimed learning only where the engine is wrong | Accepted | The text now gives the gradient, the softmax share less 1 at the target. |
| 5b. Add a loss without the engine score | Turned down | The question is whether a fine-tune helps the re-ranker as it runs. The re-ranker adds the engine score, so the loss holds it too. A loss without it is a method variant. `linear-features` and `stock-typed` cover the recalibration question. |
| 6a. The clean share is a share of cases | Accepted | The report gives the share of clean lists after the build, per category. |
| 6b. The name stand-ins differ from the hand-picked names | Accepted as a stated limit | The design says so, and the report reads that category with care. |
| 6c. Dev and test do not use up the rare-word pool | Accepted | The text now says the list leaves out the words that dev and test cases use. |
| 7a. One tuning split chooses both checkpoint and setting | Accepted | A separate stopping split chooses the checkpoint. The tuning split chooses the setting. |
| 7b. The two-fold check pools both clean groups | Accepted as a stated difference | `rerank.py` keeps its check unchanged, so the within-dev numbers stay comparable with `scripts/lm-rerank/README.md`. The design states the difference. |
| 7c. A clean count hides breaks offset by repairs | Accepted | The report gives clean breaks and clean repairs per arm and per clean category. |
| 8. The published misspellings cannot test the context | Accepted | The generated dev cases with an empty context are reported as the fair comparison. A test of the context on slips from another source is a stated limit. |
| 9a. The keyboard does not pass the context or readings yet | Accepted | The design states the plumbing that a keyboard build needs. |
| 9b. A bar in phone input | Accepted | The design states that a typed span cannot hold a bar, and that the text before the span can. |
| 9c. Compare `stock-converted` at a fixed setting | Accepted | It is compared at the published setting, per case and per reading, before any tuning. |
| Number: 120 settings for `no-model` | Accepted | Stated. |
| Number: 3,990 and 3,993 per symbol category | Accepted | Table 3 gives the real counts, 107,963 cases in all. |
| Number: the 38 minutes and the memory cap are not measured | Accepted | The results report the measured times and memory. |

## Codex's final message, word for word

> The design can measure a benchmark gain, but several controls do not support the stronger explanation that fine-tuning learned to choose readings better. Ranked by potential effect on that conclusion:
>
> 1. **The dev significance rule tests a selected winner.** The design picks the better of two fine-tunes on dev, then requires McNemar p < 0.05 on that same dev (design:210–217). Correct for the two comparisons, or make the frozen chosen-arm versus stock comparison on test the confirmatory decision. Specify whether the primary denominator is 6,799 generated cases or 7,550 including published misspellings. McNemar must count **correctness disagreements**, excluding cases where both outputs differ but both are wrong; its exact calculation is binomial. My read-only count also found 574 repeated `(context, intended)` entries beyond their first occurrence in dev; inspect clustered uncertainty rather than assuming every row supplies independent evidence.
>
> 2. **"Same 8 readings" needs a correction-state qualification.** The harness corrects at each terminator; an earlier choice can change the later typed span, context and readings (rerank.py:275–303). Specify how training trajectories are collected, and replay every evaluation case through each arm's own choices. A fixed set of lists collected under one chooser does not reproduce every arm's keyboard behavior. Drop missing-target lists from **training only**; retain every evaluation case. The greedy prefix oracle chooses the engine fallback when no prefix reading exists, so a global sequential ceiling is not established by that code (rerank.py:172–180).
>
> 3. **The controls leave format adaptation and generator priors unresolved.** `stock-typed` measures the format's effect on an *untrained* model; it does not separate reading-selection learning from learning the artificial `context | typed | reading` task. Add a fine-tuned stock-format arm, and a typed-format fine-tune without context. A small trained chooser using engine score, edit features, candidate length and "as typed" would test whether simple calibration explains the gain. `no-model` only tunes three global margins. Generator shortcuts are substantial: common intended words versus rare misspellings, special frequency thresholds, and fixed keyboard-neighbor patterns (English generator:90–123, symbol generator:70–78, noise:101–120). A gain from learning those rules is a benchmark improvement, but weaker evidence of contextual disambiguation.
>
> 4. **The leakage policy creates a large distribution change and contains a contradiction.** Using your measurements, the unrestricted phrase rule hits approximately **56.8%** of eligible sentences; short common phrases account for much of that removal. The clean-target ban also removes ordinary vocabulary from training targets: my count found **1,627 of 5,397 dev slip cases** have an intended string appearing among dev/test clean targets. Define whether the ban concerns whole strings or constituent words. Hashing sentence IDs does not prevent duplicate sentence texts or phrases across train and tuning; deduplicate those splits too (design:135–164). Finally, excluding published test misspellings requires reading their **`typed`** field, contradicting the stated `source/context/intended`-only access. These exclusions cannot establish that *every* held-out phrase was absent, especially for empty-context cases.
>
> 5. **The listwise loss is reasonable; its justification is false.** With p = softmax(e+m), the derivative with respect to each model score is p_i − 1[i=y]. Gradient depends on the **combined** scores, not whether the engine alone was right. A large engine advantage can be overturned by the model. Consequently, "learns only where the engine is wrong" is unsupported (design:80–92). Keeping the engine score as a fixed prior is defensible, but the objective also differs from deployment's tuned weight, optional space term and margins (rerank.py:190–212). An engine-score-free loss ablation would reveal whether the benefit mainly comes from compensating for engine calibration.
>
> 6. **One-third clean describes requested cases, not necessarily training signal.** Cases can produce several correction lists, no eligible list, or singleton lists that the design discards. Report retained lists and loss contribution by category before claiming a clean share. Many clean symbol cases never exercise correction: the README identifies 66 of 129 dev tokens as automatically preserved (evaluation README:163–166). The replacement names list also changes from hand-picked names/terms to low-frequency wordfreq tokens, potentially teaching a different preservation rule. "Dev and test use up" the rare-word pool is wrong: the generator samples only 300 rare words per half from a much larger pool (generator:204–210, 233–236).
>
> 7. **Shared tuning is usable, but does not give equal selection effort or a clean safety guarantee.** The fine-tunes select checkpoints and re-ranker settings on tuning; stock selects only settings. That is extra adaptation, though an untouched evaluation can still measure the resulting procedure fairly. Prefer separate checkpoint-selection and setting-selection partitions. The existing two-fold check validates setting selection, not the entire training/arm-selection procedure. Worse, its clean constraint **pools** both clean groups, unlike full tuning's separate constraints (rerank.py:343–361). Aggregate clean counts can also hide newly broken cases offset by repairs. Report both transitions and each clean category.
>
> 8. **Published misspellings cannot diagnose contextual gains.** "A gain on generated cases with none here belongs to the generator" is too strong (design:226). Those cases have no context and retain common targets, uncommon wrong forms and at most two edits (external generator:77–90). They test transfer to that filtered spelling task. Compare context-free generated cases separately, and use independently sourced contextual cases to test contextual transfer.
>
> 9. **The format is buildable, but the current keyboard does not supply that interface yet.** `correctLastWord` has `before`, `typedSpan` and `shownSpan`; context should come from `before.dropLast(shownSpan.count)`, preserving original typed text across corrections (Swift:614–638). The current checker accepts only the previous word and typed span, so context/readings plumbing must change. Match candidate capitalization to the real context, not the nonempty artificial prompt; match separate tokenization and leading spaces (rerank.py:126–139, lm_score.c:223–238). No bars in evaluation data does not guarantee no bars in phone input. `stock-converted` should compare per-reading scores and predictions at a **fixed setting**, including typed format; retuning could conceal conversion differences.
>
> The principal numbers check out: **6,799/6,798 generated cases; 24 categories; 108,000 requested training cases; 1,402/6,799 = 20.62% clean dev; 6,126 published stock successes; approximately 1.18 million LoRA parameters** for the stated projections and model dimensions. Corrections and qualifications:
>
> - **2,160 settings applies to model arms; no-model has 120** (rerank.py:401–405).
> - Existing per-symbol integer division would produce **3,990 or 3,993**, not 4,000, unless remainder allocation changes (symbol generator:171–177).
> - **38 minutes** for 120,000 distinct spans is correct arithmetic; actual span count, replacement-word supply and the **3.5 GB training ceiling** remain unmeasured.
>
> No training, conversion, memory or phone-parity checks were run. All requested files were read; read-only `python -B -` checks verified counts, grid sizes and overlaps. All requested review topics are covered above, and no files were edited.
