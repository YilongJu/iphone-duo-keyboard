# Codex review of the round 2 design

## Summary

Codex (`gpt-6-astra`, `codex exec -c model_reasoning_effort=high`, read-only) reviewed
`docs/lm-finetune2-design.md` and the scripts of `scripts/lm-finetune2/` on 2026-11-10, before any
training. It found one wrong count, two gaps in the leakage check, four weak points of the two
rules and two missing controls. The design took all of them except one control.

This file is a decision record. It keeps the points that the current design no longer shows.

## Decisions on each point

Table 1. Each point of the review, the decision, and the change.

| Point | Decision | Change |
| --- | --- | --- |
| The Mitton part held 25 pairs that round 1 already had in a dev or test case of another list | Accepted. I recounted: 25 of 728 rows, 701 fresh pairs. | `build_real_typo_cases.py` leaves out every round 1 pair of every list, and a pair that an earlier source gave. `check_leakage2.py` fails on either. The part now holds 721 pairs. |
| The leakage check read training cases, and the model reads lists. A list can hold a pair that no case holds, such as "welcom" with the target "welcome". | Accepted | `check_leakage2.py` reads the training and stopping lists of round 1 and round 2. The design and `summarize2.py` count a pair as seen when a list holds it. |
| "Words in no round 1 case" was too strong for the list-based clean words | Accepted | The design says "the intended text of no round 1 case". The check counts the words that a list shows in its context or among its readings. |
| A candidate could pass the replacement rule with the same clean damage as `ship` | Accepted | Condition 1 now asks for fewer changed stream sentences at p < 0.05. |
| Pooled counts could hide a loss on one stream or on one source | Accepted | Conditions 2 and 5 bound the closed stream, the open stream, and each source of real misspellings. |
| The paired test counted repeated cases as independent. I recounted: 388 non-word slip rows repeat a context and an intended text. | Accepted | The McNemar test stays on the stream, where the sentences differ. The non-word bound adds an interval that resamples groups of one context and one intended text. |
| The weighted estimate chose the candidate and gated the replacement, on two shares that nobody measured | Accepted | No rule uses the estimate. The pick ranks by changed words. A new condition keeps half of the real-word gain of `ship`. |
| The pick did not say how a tie ends, or what happens when no arm qualifies | Accepted | The design names the tie order, and says that `ship` stays. |
| Beating `ship` does not show that new training helped | Accepted in part | The report repeats the six conditions against `smollm2-lora-seed1-calibrated`. The replacement decision still compares with `ship`, because the request sets that reference. |
| The clean-only arm was optional | Accepted | `smollm2-lora-clean-seed1` is a required arm, third in the run order. |
| A `mix` arm differs in stopping lists and step count, and no run matches the round 1 step budget | Rejected for its cost | A matched run costs about 90 minutes of GPU per arm. The design states the limit, and the report shows the best step of each run. |
| The hinge mean did not name its denominator | Accepted | The design says that both means run over every list of the step. |
| The seen and unseen breakdowns were promised and not written | Accepted | `summarize2.py` writes them from the prediction files (Table D of its output). |
| Freeze the data and model hashes before the read | Accepted | `holdout-plan.json` holds the SHA-256 of every data file and model file. |

Codex judged the choice to leave out the round 1 phrase rule as defensible for ordinary language,
with the seen and unseen counts as a diagnostic.

Codex did not run the project's Python or WSL. So it did not repeat the leakage self-test, and it
checked the hinge term by reading only. Both ran here: the self-test finds every planted fault, and
a smoke run of `train2.py` covers the hinge path.

## Codex's final message, word for word

> **I would not start training yet.** Full frequency-filter regeneration, the leakage self-test, and tensor-level hinge checks remain unverified because the project Python interpreter is unavailable and WSL denied access. I completed the read-only review, recomputed case/list totals and overlaps, and ran 961 word-distance checks plus four tuning-rule boundary checks. No files changed; no model ran on holdout data.
>
> 1. **Counts: the raw totals agree, but “728 unsampled Mitton pairs” is wrong.**
>    The 728 rows include **8 pairs already in published dev and 17 already in published test**, leaving **703 unsampled rows, 701 distinct pairs**. For example, holdout `shoold → should` repeats published Holbrook dev. The builder correctly reproduces each source’s round 1 sample, but subtracts that sample only from the **same source**, missing cross-source reuse.
>
>    Recomputed headline counts match: 118,169/7,556 round 1 train/stop lists; 6,748 tuning cases; 6,799/751 selection cases; 6,745 generated holdout cases; stream totals 8,487/8,439/26,060 words; and 5,097/5,044 selection/holdout non-word slips. The reported 1,284 phrase overlaps and 2,295 case-pair overlaps also reproduce.
>
> 2. **The leakage audit checks cases, not everything training actually sees.**
>    Round 1 training **lists** contain pairs matching **242 GitHub holdout cases and 46 Mitton cases**, versus the reported case-level counts **211 and 41**. Selection GitHub increases from **247 to 283**. A concrete path: training case `welcom e → welcome` produces an intermediate list `welcom → welcome`, matching GitHub holdout. The checker never reads those lists.
>
>    The “words in no round 1 case” claim is also too strong: **36 held-out list words occur in round 1 training-list prompts; 150 occur among readings**. The exclusion checks only intended words. Exposure as a competing reading is not necessarily label leakage, but those words are not unseen.
>
>    I found no arithmetic bug in changed_words, the tuning predicate, or the hinge formula on inspection. The hinge averages over **all lists**, with zero contribution from ineligible lists; clarify that denominator.
>
> 3. **The replacement rule does not establish “fewer correct-word changes while keeping repairs.”**
>    The candidate can pass with **unchanged clean damage**, significant repair gains, and up to 25 lost non-word repairs. Pooling also permits a GitHub gain to hide a Mitton loss, or closed-stream improvement to hide open-stream harm. Sample-count inequalities provide no uncertainty bound on those regressions.
>
>    The significance calculation treats repeated cases as independent: the 5,044 non-word holdout rows contain **167 duplicate inputs/targets beyond their first occurrence**, and **388 repeated context/target combinations**. Use inference that resamples related cases together. Bonferroni across three outcomes is reasonable for **one genuinely untouched, preselected candidate**; it does not repair contaminated selection/holdout splits or correlated observations.
>
>    The **s/r estimate is not used safely**. Despite “for reading only,” it chooses the candidate and gates replacement. Its `r` comes after frequency exclusions, deduplication, and a three-case-per-pair cap—not a measured phone-slip distribution. The formula also substitutes case failure rates, including multiword slips, for wrong-word rates. A hypothetical candidate with one fewer changed word, 25 fewer non-word repairs, and ten more real-word repairs improves this score at `s=.05` but worsens it at `.10`.
>
> 4. **Several simpler explanations remain.**
>    Calibration and fixed-setting controls are useful, but replacement requires beating `ship`, **not calibrated `ship`**. A winning new model therefore need not demonstrate benefit from new training. Moreover, `mix` changes training data, stopping data, and the number of optimization steps under the four-epoch schedule. Changed checkpoint selection or training duration could explain gains. Make the clean-only comparison mandatory and separate these effects.
>
> **Omitting round 1 phrase rule 4 is defensible** for estimating performance on ordinary language, where common phrases recur. Retain sentence separation and explicitly distinguish familiar from unfamiliar inputs. However, the promised seen/unseen and context/no-context performance breakdowns are not implemented in the current summary path, which aggregates by category. Those breakdowns are diagnostics, not substitutes for an independent holdout.
>
> Changes required before training, most important first:
>
> 1. Rebuild Mitton holdout using exclusions across **all** sources and selection sets; audit actual round 1 and new training/stopping lists, including intermediate prompts and targets.
> 2. Freeze a rule requiring meaningful clean-word improvement and explicit repair-preservation bounds, with separate open/closed and real-typo-source safeguards.
> 3. Use paired inference that accounts for repeated cases; specify test direction, candidate tie-breaking, and no-qualifying-arm behavior.
> 4. Remove the s/r estimate from selection and replacement, or require a prespecified robustness criterion across the stated scenarios.
> 5. Require comparison with calibrated `ship`; make clean-only and matched stopping/training-budget controls explicit.
> 6. Build the missing new-list report and performance breakdowns, implement and dry-run the complete decision calculation, and freeze data/model hashes before the holdout read.

The quote leaves out the file links that Codex put after each point.
