# Codex check of the fine-tune results

## Summary

Codex (`gpt-6-astra`, `codex exec -c model_reasoning_effort=high`, read-only) checked
`scripts/lm-finetune/README.md` against the raw outputs on 2026-11-10, before delivery. It found
one wrong number, five overstated claims, one simpler explanation and two misleading actions. The
README took all of them.

This file is a decision record. It keeps the points that the current README no longer shows.

## Decisions on each point

Table 1. Each point of the check, the decision, and the change.

| Point | Decision | Change in the README |
| --- | --- | --- |
| The GPU memory in use before each run read "15.5 to 17.5 GB" | Accepted | Table 13 gives 15,826 to 17,522 MiB of the whole GPU. |
| "The gain belongs to the generator" asserts a cause | Accepted in part | By the design's rule, the text says, the pattern points to the generator. It adds that the published lists differ in words and kinds of error. The rule stays, because the request sets it. |
| The seen-pair gain does not prove memory | Accepted | The text calls it a fit, and names frequency and category as other differences. |
| "Only SmolLM2 stands above the control in both" leaves out `linear-features` | Accepted | "Of the fine-tunes, only SmolLM2". |
| The test half does not repeat the whole dev order | Accepted | The text says the fine-tunes keep their dev order. I checked the order of all six fine-tune rows myself. |
| The parity claims cover more than the checks | Accepted | The token row names each model in its own format, and the shipped model in both. |
| Rounding to f16 is a guess | Accepted | "one possible cause". |
| Tables 2 and 9 leave out two categories, which hold most of the gain | Accepted | Both tables have the columns `apostrophe missing` and `real-word slips`. I recounted from the result files: 243 of the 337 test gain, 72 percent. The Summary names the real-word share. |
| "Keep the stock re-ranker in the keyboard" misstates the keyboard | Accepted | The keyboard does not use a re-ranker yet. The action now concerns the first keyboard build. |
| The SmolLM2 recommendation hides the clean cost and the setting trade-off | Accepted | The action gives both settings and calls the choice exploratory. |

## Codex's final message, word for word

> The headline **337-case gain is correct**. The main problems are omitted categories and conclusions stronger than the evidence.
>
> 1. **Numbers**
>
>    - **README lines 334–335:** “15.5 to 17.5 GB” does not match the training logs: `gpu_used_before_mib` ranges from **15,826 to 17,522 MiB**, or **15.46–17.11 GiB**. Those logs measure total GPU usage before training, not memory attributed individually to other apps.
>    - I found **no other numerical mismatch** in the reported tables, differences, ranges, percentages, steps, epochs, or rounded training minutes. In particular, **294–445**, **295–375**, **11.3/5.4 points**, and the clean-list percentages match.
>
> 2. **Unsupported or overstated claims**
>
>    - **Lines 11 and 137–139:** “the gain belongs to the generator” asserts a cause. The results establish gains on generated cases and losses on these published lists. They do not establish that gains cannot transfer to real phone slips. Matching empty context does not match vocabulary, error types, or difficulty; published misspellings were also explicitly excluded from training.
>    - **Lines 200–201:** Larger gains on seen pairs do **not prove memorization**. Seen and unseen pairs can differ in frequency, category, and difficulty. The 11.3/5.4-point comparison supports an association.
>    - **Lines 45–46:** “Only SmolLM2 … stands above the control in both” is false across the plotted arms: `linear-features` also exceeds control on generated test cases (**6,225 versus 6,106**) and published misspellings (**394 versus 390**). “Only fine-tune” would be supported.
>    - **Line 269:** Test does not repeat the complete dev ordering: `smollm2-stock` beats `stock-dev` on dev (**6,145 versus 6,126**), but loses on test (**6,164 versus 6,170**).
>    - **Lines 382–391:** The blanket assertion that converted files reproduce trained-weight scores overstates sampled, approximate parity checks. `full-seed2` fails the specified tolerance. Also, “every model, in both formats” exceeds the available parity records: most fine-tunes were checked only in their own format; SmolLM2 records show typed format.
>    - **Lines 542–543:** Weight rounding is a hypothesis, not an established “likely cause”; the supplied evidence does not distinguish it from other causes.
>
> 3. **A simpler explanation missing from the headline**
>
>    - **Lines 94–112 and 253–267:** Both group tables omit **`apostrophe_missing` and `real_word_slip`**, each containing 300 cases. The totals include them.
>    - Against `stock-tuned`, test `lora-seed1` gains **58 apostrophe cases** (298−240) and **185 real-word-slip cases** (244−59). Together, **243 of 337 gains—72.1%—come from those two categories**. The remaining 6,198 cases contribute only **94** net gains.
>    - **Lines 114 and 154–157:** Learning the generator’s correction patterns can explain much of the improvement without a large contextual benefit: removing context retains **294/393 ≈ 75%** of the dev gain; removing the typed-span format retains **336/393 ≈ 85%**. These comparisons deserve explicit interpretation.
>
> 4. **Summary statements that could lead to wrong action**
>
>    - **Line 9:** “Keep the shipped … re-ranker in the keyboard” misstates deployment status. The earlier re-ranker report says keyboard integration has not happened; this README itself says plumbing remains at lines 375–376. Keeping model assets and retaining an integrated re-ranker are different actions.
>    - **Lines 12–14:** The recommended SmolLM2 setting **fails the pre-set clean-dev requirement**. Its “2 fewer” clean test cases is a net count: it breaks **10** previously correct ordinary clean cases and repairs **8**, plus breaks and repairs **2** clean-symbol cases each. The alternative dev-tuned setting preserves both clean test totals but scores **383 published cases, below control’s 390**. No tested setting demonstrates both advertised advantages together.
>    - **Lines 5 and 12–14:** No arm qualified under the original selection rule. The expanded test plan was fixed beforehand, but choosing the next candidate from those test results remains exploratory; the Summary should not imply that the originally designed selection succeeded.
>
> All four requested review areas were checked. Python comparisons verified table values and arithmetic; I read the design and compared the test plan with the copy embedded in `result-test.json`. No files were edited, and training or phone tests were not rerun.
