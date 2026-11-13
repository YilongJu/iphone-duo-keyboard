# Codex review of the confirmation round of `dom-s100-seed1`

## Summary

Codex (`codex exec --skip-git-repo-check -c model_reasoning_effort=high -s read-only`) reviewed the amendment of 2026-11-12 before the plan commit and before any model scored the confirmation set.
It read `docs/lm-domain-design.md`, the scripts of `scripts/lm-domain/` and `git diff HEAD`. It made 9 points, and 2 of them blocked the read.
The amendment took 3 points in full and 3 in part. Two points asked for no change, and the amendment did not take 1 point.

1. Read Table 1 for the decision on each point.
2. Read "Second pass on the changes" for the 6 points of the second pass.
3. Read "Text of the review" and "Text of the second pass" for the points in Codex's own words.

This file is a decision record. It keeps the points that the current design no longer shows.

## Decisions on each point

Table 1. Each point of the review, the decision, and the change.

| # | Point | Decision | Change |
| --- | --- | --- | --- |
| 1 | Blocks the read. 31 confirmation cases share a GitHub commit with a selection case, and 24 with a round 2 held-out case. | Accepted | `build_fresh_holdout.py` leaves out every commit of a case of the select half, of round 2 and of the fresh held-out set. `check_fresh_holdout.py` checks the same in rule 11. The set was built again. |
| 2 | Blocks the read. The 10 symbol tokens from the domain text skip the document rule, and domain tokens can favour a domain-trained file under a condition without a band. | Accepted | The domain tokens are out. The set takes the 119 tokens that the word list still has, so its group clean symbols has 419 cases. |
| 3 | Note. The bootstrap arithmetic is correct. | No change asked | None. |
| 4 | Should fix. The bootstrap share is no exact test at the level 0.05. With no differing case it passes any margin. The four tests do not correct for the pick among 53 entries. | Accepted in part | A part now passes only when the bootstrap share and Tango's score test are both under 0.05. The design calls the bootstrap share approximate and calls the comparison a gate on development data. The design adds no correction for the 53 entries: the confirmation read is the test of the picked entry. |
| 5 | Should fix. Table 12 does not justify the margins: 12 pairs from 6 files, and seed spread is no measure of acceptable harm. The margins were chosen with the counts known. | Accepted in part | The design calls the margins engineering tolerances, states what a loss at the margin means in use, and says that the 12 pairs are not independent. The margins stay at 0.5 and 1 percent, the bands of the other conditions. |
| 6 | Note. No other pick condition is relaxed: condition 2 asks for 954 and 428 clean cases, and the removed floors were 953 and 428. | No change asked | None. |
| 7 | Should fix. The plan writer takes the candidate that the summary names, and the reader checks no commitment. The guard against a second read is a check of the output folder. | Accepted | `make_holdout_plan.py --expect-candidate` stops unless the pick is `dom-s100-seed1` at `ceiling-0.3`. `read_fresh_holdout.py` needs `--plan-sha256`, writes `read-started.json` into the folder of the set before any model types a case, and refuses another plan from then on. |
| 8 | Note. The checks against the fresh held-out set passed. Stream letters are compared, and no check covers every sentence of every used document. Training pairs of generated and real misspellings are flagged, and they stay in. | Not taken | The domain parts share no document with an earlier set, so a sentence of a used document cannot be in them. A pair that training holds stays flagged in `pair_in_training`, as in the fresh held-out set, so the two reads count the same thing. |
| 9 | Should fix. The 20 readings allow more cases per sentence, so intervals are a little narrow. The report lacks intervals for the clean groups, and the stream interval resamples sentences. | Accepted in part | The report adds an interval for each clean group and an interval of the streams over documents. The design states the effect of the later readings. The generator still reads the sentences up to 20 times for this set. |

The checker run of Codex did not complete on this machine, as the first paragraph of its text says. The checker ran in the project environment before and after the changes. It stopped at rule 11 on the first build of the set, and it passes on the final build.

## Second pass on the changes

Codex read the changes in a second, short pass and made 6 points. Three confirmed a change, and three asked for a further change.

Table 2. Each point of the second pass, the decision, and the change.

| # | Point | Decision | Change |
| --- | --- | --- | --- |
| 1 | Note. The confirmation set shares no commit and no case with the 2,500 selection cases, the 2,500 picks of round 2 and the 1,958 GitHub cases of the fresh held-out set. | No change asked | None. |
| 2 | Note. The path for domain tokens is gone. Codex could not run the word list. | Checked here | A run in the project environment finds all 119 tokens in the word list. |
| 3 | Note. The score test is Tango's test with the right tail, and with no differing case it does not pass by itself. | No change asked | None. |
| 4 | Should fix. The same plan can be read into another output folder, a stopped attempt leaves no record, and the marker is not created in one step. The hash does not prove a commit. | Accepted in part | The reader creates `read-started.json` in one step with the plan value and the output folder, and it refuses another plan and another folder. Every start adds a line to `read-attempts.jsonl`. The reader does not ask Git: the agent that starts the read checks the commit. |
| 5 | Should fix. "Within 4 percent" is false for the domain slips: 1,838 against 1,955. "Refuses a second read" says too much. | Accepted | The design has Table 14 with the cases behind each condition, and it states what the guards are. |
| 6 | Should fix. The marker was written before the plan and the files were checked. | Accepted | The reader checks the plan and every file first, and then creates the marker. |

## Text of the review

> Full-checker verification remains incomplete. Its launcher stopped with `No Python at '"C:\Users\juyil\AppData\Roaming\uv\python\cpython-3.12.7-windows-x86_64-none\python.exe'`; the alternative stopped at checker line 51 with `ModuleNotFoundError: No module named 'wordfreq'`. I read every requested file and the diff, ran arithmetic and metadata checks, modified nothing, and scored no model.
>
> 1. Blocks the read. The promised source isolation fails on actual GitHub metadata. My read-only Python audit found 31 confirmation cases sharing commits with selection cases and 24 sharing commits with round-2 held-out cases. Those counts need not be disjoint. build_fresh_holdout.py:352 excludes commits only from the earlier fresh set; check_fresh_holdout.py:244 repeats that limitation. Splitting by the corrected word does not split commits. Exclude commits from every earlier partition and rebuild before scoring.
>
> 2. Blocks the read. The ten domain symbol tokens bypass document isolation. build_fresh_holdout.py:142 scans all test-bucket documents without excluding previously used documents. My metadata audit found two recorded token-provenance documents already represented in earlier fresh or pack evaluation cases. build_cases.py:267 records only the Tatoeba context source, so the checker cannot see that provenance. Training-word exclusion prevents direct token memorization from the listed training sentences, but domain-style tokens can still favor a domain-trained candidate. Ten cases can move the zero-tolerance clean-symbol condition. Preserve token provenance and apply the document exclusions before freezing this choice.
>
> 3. Note. The bootstrap arithmetic is correct for valid counts. paired_dev.py:43 factors the multinomial into the number of discordant draws and a conditional binomial; line 63 correctly implements B − C ≥ margin. The zero-discordance and probability-zero/one branches work. My exhaustive small-table enumeration agreed within 2.2×10⁻¹⁵. Dropping outer probabilities below exp(−60) loses at most 5.96×10⁻²³ here. The 10⁻¹² threshold tolerance affects only artificial margins extremely close to integers. The implemented 33.995 threshold is equivalent to 34 because losses are integers.
>
> 4. Should fix. “Exact bootstrap probability” does not mean an exact level-0.05 non-inferiority test. The percentile bootstrap is defensible as an approximate development gate, not a calibrated confirmatory claim after selection. With zero discordances it declares any positive margin acceptable regardless of sample size. For b=47, c=41, n=6799 and margin 34, I calculated bootstrap tail 0.00176666 and the restricted-likelihood [Tango score test](https://www.site.uottawa.ca/~nat/Courses/csi5388/Tango.paired.pdf), z=−2.83628, one-sided p=0.00228211. Both pass; that conclusion does not flip. Boundary cases can flip. Requiring all four tests avoids a four-test correction for one fixed candidate, but does not correct selection among 53 entries or margins chosen afterward.
>
> 5. Should fix. Table 12 does not justify acceptable harm. Twelve pairwise comparisons reuse six models and two settings; they are not twelve independent replications. Seed variability measures recipe instability, not the loss users should tolerate. Aggregate seed totals also cannot establish each slip-group margin. The “margin below 22 bars a seed” argument treats seed variation as something the rule must forgive. Disclosure is necessary and appropriately candid, but cannot establish the claimed independence of margin choice. Label these as retrospective engineering tolerances and justify them operationally before confirmation.
>
> 6. Note. I found no additional pick-condition relaxation. The removed clean floors were 953 and 428, while condition 2 still requires ship’s 954 and 428: stronger and equal, respectively. Evidence is summarize3.py:136 and reports/select-tables.md:9. The remaining pick predicates are unchanged in git diff HEAD. The clean-floor omission therefore does not weaken protection in this harness.
>
> 7. Should fix. The confirmation prose fixes the candidate hash, setting 1.5/1/4/2 with space-after, apostrophe lead 0.5, report-only arms and no alternative candidate after failure. read_fresh_holdout.py:148 retains all seven decision predicates; its set handling at line 180 correctly selects confirmation files, and neither Wikipedia nor the bootstrap report changes the decision. However, make_holdout_plan.py:62 accepts whatever candidate the summary names. The reader checks neither commitment nor agreement with the named candidate. Its “once” guard at line 176 is only an output-folder result check; another folder or an altered plan after interruption remains possible. Freeze and verify the exact plan and execution revision before starting.
>
> 8. Note. Other metadata checks passed: all seven hashes matched; confirmation shared no Tatoeba IDs, list words, real-typo pairs, GitHub commits, domain slip pairs or equal-letter domain streams with the earlier fresh set. Domain documents did not overlap earlier fresh/pack documents, and domain slip pairs did not overlap training. Those checks do not establish universal isolation. Checker lines 203 and 253 compare stream letters, not every sentence from every previously used document. Generated and real-typo training pairs can remain flagged rather than excluded.
>
> 9. Should fix. Wikipedia is safely report-only. The twenty-pass workaround retains quotas and rejects repeated sentence-position selections within each call, but permits more cases per source; independence-based intervals can consequently be optimistic. No candidate-specific direction follows from that workaround alone. Also, read_fresh_holdout.py:133 omits intervals for both clean groups despite the promise of an interval beside every difference, and resamples technical sentences rather than documents for the reported interval. Document those limitations or repair the reporting before the read.

## Text of the second pass

> Word-list membership remains unverified: `uv run --with wordfreq python` stopped before execution with “error: failed to create directory `C:\Users\juyil\AppData\Local\uv\cache`: Cannot create a file when that file already exists. (os error 183)”. The full checker was not run. Independent metadata and arithmetic checks ran with standard-library Python. No files changed; no model was scored.
>
> 1. Note. Fixed. My metadata audit found zero shared commits and zero overlapping confirmation cases against selection’s 2,500 cases, round 2’s 2,500 picks, and fresh holdout’s 1,958 GitHub cases. The round-2 file matches the checker’s pinned hash. `scripts/lm-domain/check_fresh_holdout.py:246–252` checks all three commit sources under rule 11 when `--earlier` is supplied.
>
> 2. Note. Partially verified. The built file contains 119 clean_symbol_token cases with 119 distinct tokens. `scripts/lm-domain/build_fresh_holdout.py:241–257` now obtains tokens exclusively through the word-list path, reducing the quota when necessary; the domain-text supplementation path is gone. However, the failed wordfreq run prevents independently confirming that every built token belongs to that list. The report alone cannot establish provenance.
>
> 3. Note. Correct for the positive margins used here. `scripts/lm-domain/paired_dev.py:75–79` implements [Tango’s score test](https://www.site.uottawa.ca/~nat/Courses/csi5388/Tango.paired.pdf), with loss defined as only-first-right minus only-second-right. Negative z supports non-inferiority, so the lower normal tail is correct. With zero discordances, z = −√(nδ/(1−δ)); the test does not automatically pass. Executed examples give p = 0.239199 for n=100, δ=0.005, and p = 0.002282114 for (47,41,6799,34).
>
> 4. Should fix. `make_holdout_plan.py:68` enforces the supplied expected candidate, and the job supplies the intended entry. However, `read_fresh_holdout.py:188–202` permits the same plan with another `--out`, overwriting the marker’s original output path. Interrupted attempts leave no durable attempt history. Different plans are rejected sequentially, but marker creation is not atomic, so concurrent starts can both pass. The supplied hash also does not verify a Git commitment or execution revision.
>
> 5. Should fix. Table 13’s counts and word totals match my audit; all seven file hashes match the report. However, `docs/lm-domain-design.md:428` says every condition-read part stays within 4 percent. Condition 7’s domain-slip group falls from 1,955 to 1,838, a 5.98 percent reduction, using `summarize3.py:72–77`. Line 454’s promise to refuse a second read also overstates the guard.
>
> 6. Should fix. The new marker is written before dataset hashes and plan structure are validated (`read_fresh_holdout.py:202–211`). An invalid plan can therefore reserve the set without scoring anything and prevent a corrected plan from running. Validate first, then atomically record the accepted plan and preserve attempt history.
