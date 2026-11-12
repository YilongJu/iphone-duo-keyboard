# Codex review of the design of the domain round

## Summary

Codex (`codex exec --skip-git-repo-check -c model_reasoning_effort=high`, read-only) reviewed `docs/lm-domain-design.md` and the scripts of `scripts/lm-domain/` on 2026-11-12, before any training.
It made 13 points. The design took 11 in full and 2 in part.

1. Read Table 1 for the decision on each point.
2. Read "Text of the review" for the points in Codex's own words.

This file is a decision record. It keeps the points that the current design no longer shows.

## Decisions on each point

Table 1. Each point of the review, the decision, and the change.

| # | Point | Decision | Change |
| --- | --- | --- | --- |
| 1 | Everyday training sentences of rounds 1 and 2 are also sources of domain dev and test cases: 117 and 146 cases, 63 and 67 stream sentences. | Accepted | `audit_overlap.py` marks these cases and the slip pairs that a training case holds. The pick and the domain tables leave them out for every arm, and a second table shows them alone. |
| 2 | A fresh domain sentence from an unused document can have the letters of an evaluated sentence: 15 sentences. The everyday rule must inherit the filters of round 2. | Accepted | `build_fresh_holdout.py` leaves out every sentence with the letters of a sentence of a used document. It repeats the source and text filters of `build_cases2.py`. The design states both rules. |
| 3 | The perfect chooser took the longest matching reading, so its count was a greedy score and no ceiling. It matched before the capitals rules. | Accepted | `harness.perfect_typing` keeps a clean case as typed, which is exact. For a slip case it searches the matching readings for 40 typings at most, and also tries the text as typed where no reading matches. The design calls the count a lower bound of the ceiling for slip cases. I found the same fault in the lists of round 2 on my own: 200 of 54,759 clean running-text lists have a target that adds the next word. |
| 4 | The share of the gap for running text assumed that the perfect chooser changes 0 words. A written sentence with a changed capital counted as right. | Accepted | `score_model.gap_closed` uses the perfect chooser's own changed words. A stream sentence is right when no word of it changed. The perfect chooser changes 3 dev and 4 test words through the capitals rules. |
| 5 | Phrase cases held withheld words: 263 cases of 25 words. Clean twins hold typed texts of evaluation misspellings: 70 cases. The breakdown by kind of word was missing. | Accepted | A pair with a withheld word gets no phrase case. The design states that the typed-text rule binds slip cases. `summarize3.py` counts slips of trained, withheld and requested words apart. |
| 6 | The replacement test counted sentences while the pick counts words, and it took sentences of one document as independent. | Accepted | Condition 1 now asks for fewer changed words, with an exact sign test over documents. |
| 7 | `dom-s0` against `ce-c1` changes the capitals and the target rule beside the supplement. A domain arm also changes the share of clean lists and the everyday exposure. | Accepted in part | The design calls each comparison a comparison of two whole recipes, and the loss arms now train on the same rebuilt lists as `dom-s0`. The round does not add a control with matched clean share and exposure. That control costs one more arm per share. |
| 8 | Equal step numbers do not mean equal optimization: the learning rate of `mix-seed1` at step 11,000 was about 1.0e-4. The micro-batch changes the dropout masks. | Accepted | Table 6 gives the learning rate at step 11,000. The design limits every result to one budget of steps, drops the claim about the gradient, and flags an arm whose last stopping loss lies 2 percent above its lowest. |
| 9 | The pick left out the simplest option: the shipped file at a ceiling setting. | Accepted | Every scored file is an entry, the shipped file at its two ceiling settings included. |
| 10 | The rules of the third wave had no tie-break and no branch for a missing result. The loss rule compared two seeds with one. The picked share's seed 1 is no replication. | Accepted | Ties and missing arms are defined. `dom-s0-seed2` joins the queue, the loss rule compares paired seeds and asks for 10 cases, and the results give seeds 2 and 3 apart. `summarize3.py` applies both rules. |
| 11 | The floors of condition 6 come from another run. One-case gates turn on chance. Pooled domain gates hide subgroups. No gate covers the apostrophe words or `github_real_word`. | Accepted in part | Condition 7 adds the group `required`, condition 8 adds the apostrophe words, and a clean case is defined by its letters. The floors of condition 6 stay, because the request sets them, and the table shows the counts of `ship` in this harness beside them. `github_real_word` stays shown only, as in round 2. The one-case gates stay, as round 2 has them, and the limits name them. |
| 12 | "The 18 requested words do not stand in the domain text" was false. The exposure of 1.0 at share 1.0 was an estimate. | Accepted | The design states the mechanism: the builder takes its words from the corpus words. The results page gives the realized list counts and exposure. |
| 13 | Condition 8 named three kinds of file while soups are eligible. The audit did not fix its sample or the order of its labels. | Accepted | The parity condition covers every entry, and `summarize3.py` reads the measured differences. `label-rule.md` fixes the sample, the order of the labels and the label `unclear`. |

## Amendments to the design after the first scores

Table 2. Each amendment, its date, and the scores that existed when it was written. No amendment uses held-out data.

| Date | Amendment | Scores seen before it | Reason |
| --- | --- | --- | --- |
| 2026-11-12 | The lead of the apostrophe step is tuned per file and setting, by the rule that `engine/lm-keyboard` used for the shipped file. The pick reads an entry at its own lead. The tables show the lead of `ship` beside it. | Selection scores of the first ten arms at lead 4, the lead of `ship` | Lead 4 was picked for the shipped file alone, and the harness gave it to every file. A drop of the apostrophe words can be an effect of that setting. |
| 2026-11-12 | The results give, for each entry that misses a pinned dev floor, the dev cases that only `ship` has right and the cases that only the entry has right. The floors stay as written. | The same scores | A reader sees the size of a miss of 1 to 3 cases beside the gains. |
| 2026-11-12 | One more arm can join the third wave: the picked share with apostrophe lists in the stock prompt. It trains only when the picked share, at its own lead, stays more than 8 next-word cases under `ship`. | The same scores | The step reads the stock prompt, and the fine-tune trains on the typed prompt only. |
| 2026-11-12 | The parity condition is read three ways and the pick is reported for each: the f16 file as written, an F32 file, and an F32 file with a 32-bit cache. The limit stays 0.05. No file ships on the second or third reading before the user chooses. | Parity results of 18 files | The parity study shows that the differences come from 16-bit arithmetic of llama.cpp. |

## Checks of the review that I repeated

- The 200 clean lists of round 2 with a target that adds a word: counted in `lists2.train.jsonl.gz`, 200 of 54,759.
- The perfect chooser on clean running text after the change: 0 changed words on the select stream, 3 on the dev streams of the pack.
- The withheld words in phrase cases after the change: the builder made 3,625 training phrase cases against 3,884 before.

## Text of the review

> I read every requested file fully, including cases-report.json. No files were edited and no training ran. The findings below include read-only Python checks. Full engine/GGUF evaluation and PyTorch loss execution remain unverified; the fresh-holdout and labeling procedures were reviewed as specified in the design.
>
> 1. Existing everyday training data already overlaps the domain evaluation sets.
>
> Where: docs/lm-domain-design.md:54, 128–133, 141–143; make_train_queue.py:42, 51–53; build_english_domain_cases.py:771–776.
>
> The domain evaluation builder uses a Tatoeba partition that does not exclude the earlier fine-tuning sources. Joining source IDs to cases that actually contributed training lists found overlap with 117 domain-dev cases and 63 domain-dev stream sentences, plus 146 domain-test cases and 67 domain-test stream sentences.
>
> For example, endomstream-dev-everyday-0030 uses the same sentence as training case en-train-space_transposed-1727: “mary expects tom to eat dinner with her”.
>
> The inherited training lists also contain 81 list occurrences matching domain-dev slip pairs and 67 matching domain-test slip pairs. The new domain builder’s pair exclusion does not cover those inherited lists.
>
> Why it matters: the domain selection counts are partly in-sample. Rebuilding the everyday cases with the pack on preserves this overlap.
>
> Smallest fix: exclude contaminated evaluation sources and pairs from selection for every arm, retaining them only as diagnostics. Apply an independent overlap audit to all final training lists, not just new domain cases.
>
> 2. The planned fresh-domain rule permits text that has already been evaluated.
>
> Where: docs/lm-domain-design.md:260–270.
>
> “Unused document” does not imply unused text. Applying the proposed document exclusion to the available test corpus leaves 96,091 sentences; 15 have the same normalized letters as previously evaluated stream sentences. Another 496 match sentences in the dev corpus.
>
> The everyday rule also needs to explicitly inherit round 2’s exclusion of round 1 sources. Merely choosing hash buckets 0–2 and excluding previously sampled held-out cases does not provide that exclusion. Round 2 implements the additional source/text filtering in build_cases2.py:178–200.
>
> Why it matters: the final replacement decision can reuse evaluated text despite satisfying the written freshness rules.
>
> Smallest fix: require normalized-text exclusion against all earlier training, tuning, selection and evaluated text, alongside source exclusion. Apply pair exclusion across every training-list file and every fresh misspelling source. Freeze these rules, dataset hashes and sample sizes before reading candidate results.
>
> 3. perfect_chooser is a greedy heuristic, not an established end-to-end ceiling.
>
> Where: harness.py:150–163; build_lists3.py:41–59; docs/lm-domain-design.md:31, 303, 309.
>
> The chooser takes the longest matching prefix of the complete intended text, without accounting for characters still to be typed. A synthetic read-only check with readings “in” and “in the” while typing “in the” produced “in the the”; the engine’s shorter choice produced the correct sentence. That demonstrates the algorithmic problem, although I did not establish its frequency with actual engine lists.
>
> Matching also happens before capitalization and preferred-form rendering. For example, raw reading “nextjs” does not match intended “Next.js”, although PreferredCapitals renders it correctly. Protection can additionally remove a target before the chooser sees the list.
>
> Why it matters: failure of this chooser does not prove engine recall failure. The same heuristic supplies training targets, and its count is used as the denominator of reported improvement.
>
> Smallest fix: call the current result a greedy-oracle score rather than a ceiling. For a true ceiling, evaluate reachable typing states through the remaining input and the rendering rules. Diagnose raw-list absence, protection exclusion and rendering failure separately.
>
> 4. The stream gap calculation demonstrably uses the wrong denominator.
>
> Where: score_model.py:66–70; harness.py:173–185, 192–230; docs/lm-domain-design.md:210.
>
> gap_closed ignores the supplied perfect stream result and assumes zero changed words. A direct check with engine=40, model=20 and perfect=10 returned 0.5; the measured-gap formula gives 20/30, approximately 0.6667.
>
> Zero is not guaranteed by the typing rules. Using actual stream sentences with an as-typed-only engine and the real capitalization code still changed three dev written sentences and four test written sentences. One example is “i.e.” becoming “I.e.”.
>
> summarize also counts a written sentence with changed capitalization as “right”, because is_right normally ignores case, while changed_words counts that capitalization change.
>
> Why it matters: the reported ceiling, right-sentence count and share of gap closed can disagree or overstate remaining achievable improvement.
>
> Smallest fix: calculate stream share as (engine_changed − model_changed)/(engine_changed − perfect_changed), handling zero or invalid denominators explicitly. Define written-stream sentence correctness using changed_words == 0.
>
> 5. The withheld-word and typed-text guarantees are broader than their implementation.
>
> Where: build_domain_train_cases.py:155–167, 215–216, 236–260; docs/lm-domain-design.md:132–133, 301.
>
> The withheld-word filter applies to single-word term generation, but not phrase generation. The built training cases contain 263 phrase cases involving 25 withheld words: 158 phrase-space slips and 105 clean phrases. Examples include “trainabl eparameters” → “trainable parameters”.
>
> The typed-text exclusion is also bypassed by clean twins. Seventy training cases have exactly an evaluation misspelling’s typed text, including “parameters” and “urls”. These can be legitimate clean examples, but they contradict the blanket sentence at line 132.
>
> Finally, harness.summarize’s domain branch, lines 212–218, does not produce the promised withheld/trained/requested-word breakdown.
>
> Why it matters: the proposed “never trained on its slips” interpretation is false for some withheld words, and the promised diagnostic is absent.
>
> Smallest fix: exclude withheld words from phrase-slip targets too, audit final lists, and add the promised strata. Either apply the typed-text exclusion to every case or explicitly document the clean-example exception.
>
> 6. The fresh replacement test changes the objective and assumes independent sentences.
>
> Where: docs/lm-domain-design.md:226, 277–285.
>
> Selection minimizes changed words; replacement tests changed sentences. A candidate can improve the sentence count while concentrating more changed words into fewer sentences. No replacement condition bounds changed technical/written words.
>
> The sentence-level exact McNemar test also ignores document clustering. The existing technical/written dev streams contain 1,300 sentences from 1,063 documents, with up to eight sentences per document; the test streams reach ten per document. The proposed fresh sampling does not remove this dependence.
>
> Why it matters: the final test can approve a different improvement from the one selected, and its nominal p-value need not have the stated error rate under correlated sentence outcomes. Conditions 2–7 bound observed counts, not population losses.
>
> Smallest fix: retain a technical/written changed-word guard, and either sample one sentence per document or use a prespecified document-level paired test. Report uncertainty for the loss bounds rather than treating passing sample counts as proof of non-inferiority.
>
> 7. The domain comparisons cannot isolate domain knowledge from other recipe changes.
>
> Where: docs/lm-domain-design.md:143, 183, 295–296; build_lists3.py:35–59; scripts/lm-finetune/build_lists.py:30–55.
>
> dom-s0 versus ce-c1 changes more than supplement vocabulary. The new builder preserves capitals, applies preferred forms, and changes target-boundary matching from a following space to any terminator. The older builder uses the older typing behavior. Retained-list counts and contexts can therefore change independently of added pack readings.
>
> Adding domain data then changes domain content, the clean/slip mixture, context style and everyday exposure simultaneously. The design acknowledges exposure dilution, but the comparison still cannot distinguish domain learning from additional clean-example pressure or reduced everyday training.
>
> Smallest fix: describe these as whole-recipe comparisons. To make the stronger causal claims, rebuild pack-off and pack-on lists with the same builder and add a control matching clean fraction and everyday exposure.
>
> 8. ce-c1-seed1 is a useful bridge, but does not validate last-step selection for other arms.
>
> Where: docs/lm-domain-design.md:167–183, 294; train2.py:195–200, 263–292; train3.py:231–236, 294–318.
>
> The historical mix-seed1 artifact confirms 13,500 steps taken, step 11,000 retained, and an 800-token micro-batch. But the old learning rate at step 11,000 was approximately 0.000102; the new schedule reaches zero there. Equal checkpoint numbers do not mean equal optimization.
>
> Discarding best-checkpoint selection removes protection against arm-specific overfitting or different convergence speeds. One unweighted-CE seed cannot establish that 11,000 last-step weights are appropriate for weighted CE, expected cost and larger mixtures.
>
> Line 182’s “micro-batch changes … no gradient” is also too strong: LoRA dropout is 0.05, so different batch shapes can change dropout masks and per-seed gradients.
>
> Smallest fix: narrow the conclusion to performance under one fixed-budget schedule. Preserve intermediate weights for a separately prespecified checkpoint comparison, and describe micro-batch equivalence as an objective/expectation statement rather than exact gradient identity.
>
> 9. The candidate pool excludes the simplest deployment alternative: retuning the shipped model.
>
> Where: docs/lm-domain-design.md:214, 300; score_model.py:127–181.
>
> The harness can tune the shipped model, but the pick admits only new arms and soups, against ship at its old setting.
>
> Why it matters: a winning new model at ceiling-0.3 or ceiling-0.2 may deliver an improvement attainable by changing the shipped model’s setting alone. Scoring that alternative without allowing it to win does not resolve the deployment comparison.
>
> Smallest fix: admit the shipped model at both ceiling settings as candidates under the same gates and fresh replacement rule.
>
> 10. The third-wave rules have undefined branches and favor selected winners.
>
> Where: docs/lm-domain-design.md:235–236; make_train_queue.py:59–71; select_setting.py:39–42, 54–57.
>
> The share rule has no tie-breaker. The loss rule does not say what happens when ceiling-0.3 has no allowed setting, a seed fails, or a result is missing. The queue generator accepts a manually supplied share/loss without validating the rule.
>
> The loss comparison averages two seeds against ce-c1 seed 1 alone. The chosen domain share then receives additional seeds, while its unusually favorable seed-1 result remains part of the reported spread and candidate pool.
>
> Why it matters: one-case differences or seed luck can determine later compute allocation. The selected seed-1 result is not an independent replication.
>
> Smallest fix: specify all tie, missing-result and failure branches; implement the rules directly; compare paired seeds; and report seeds 2–3 as replication separately from the seed used to select the share. Prespecify a minimum improvement rather than merely “above”.
>
> 11. Several gates are weaker, less reproducible or less diagnostic than their wording suggests.
>
> Where: docs/lm-domain-design.md:217–229, 279–283.
>
> The absolute floors in pick condition 6 come from another run. domain-pack-design.md:500–505 records a same-machine keyboard/harness result of 6,537 existing dev cases, versus the pinned 6,542 elsewhere. A floor can therefore reflect scorer/runtime differences as well as model quality.
>
> The zero-loss gates and “above” comparisons can turn on one case. Pooled domain gates allow gains in common categories to hide losses in requested words or sentence-start slips. Defining clean cases by typed == intended also classifies deliberate capitalization normalization as a slip; some such cases bypass the language model entirely.
>
> The 1,000 github_real_word cases and apostrophe-word sets are scored but have no dedicated preservation gate.
>
> Smallest fix: anchor floors to a frozen, contemporaneous shipped run; define category membership explicitly; and add subgroup guards for the behavior the experiment specifically promises to preserve. Treat unchanged policy-controlled cases separately from model-controlled cases.
>
> 12. Two factual claims are unsupported or contradicted by available data.
>
> Where: docs/lm-domain-design.md:133, 183.
>
> “The 18 requested words do not stand in the domain text” is false. The collected build sentences include, for example, 22 occurrences by sentence of “worktree”, 37 of “todo” and seven of “xcode”. Training-case text includes “worktrees”, “todo”, “vite” and “nextjs”. Their exclusion from single-word slip generation follows from membership in kinds, not absence from the text.
>
> The stated 1.0 everyday-list exposures at share 1.0 cannot yet be verified from cases-report.json. The report counts cases; streams expand into multiple lists and other cases can produce none. The domain and pack-on list artifacts were absent when checked.
>
> Smallest fix: state the actual requested-word exclusion mechanism. Label the 1.0 exposure figure as an estimate until final list counts exist, then report list counts, clean fractions and realized exposure for each share.
>
> 13. The parity and hand-audit rules need explicit applicability and classification rules.
>
> Where: docs/lm-domain-design.md:224, 309–318; post_arm.sh:21–27; run_train_queue.py:97–100, 150–157.
>
> Pick condition 8 names ce/ec/dom files although soups are eligible. The conversion script checks Q4 tokenization but compares numerical scores against F16, and deliberately allows parity failure without a failing post-processing exit status. Queue completion therefore does not establish that condition 8 passed.
>
> The hand audit does not specify how the 200 errors are sampled or how overlapping labels are resolved. A wrong intended label and an absent target can satisfy both “label noise” and “engine recall”. The greedy-oracle problem also invalidates an automatic two-way recall/model split.
>
> Smallest fix: require explicit parity evidence for every eligible artifact, identify the precision being checked, and inspect the parity measurements rather than process success. Fix the audit sample seed, sampling scheme, label precedence and an unresolved/ambiguous category before annotation.
>
> Review-tool limitations: the PyTorch probe stopped with “No Python at '"C:/Users/USER\AppData\Roaming\uv\python\cpython-3.12.7-windows-x86_64-none\python.exe'”; the available Python had no torch module. The loss conclusion is therefore algebraic/source inspection, not executed autograd verification. The rg search failed with “The term 'rg' is not recognized as the name of a cmdlet, function, script file, or operable program”; PowerShell searches replaced it. An optional lookup of docs/lm-finetune2-design.md failed because that file does not exist; the historical training artifact supplied the schedule figures instead.
>
> Checked and found correct:
>
> - list_losses implements both printed formulas, including the unweighted 0.1 cross-entropy term in expected cost. Both loss families use matching data files, 11,000 steps and seeds 1 and 2.
> - select_setting implements independent ceilings of 25 and 16 words, maximizes generated accuracy, and breaks ties by changed words then grid order. An infeasible ceiling returns no setting.
> - The grid has 2,160 settings; non-word slips total 5,097.
> - Table 4 and the 35,952 training-case total match cases-report.json. The inherited training lists total 175,831.
> - The new domain cases have zero direct slip-pair matches against domain dev/test. Collection restricts sources to the build bucket; reusing that bucket for pack construction and training is not itself evaluation leakage.
> - A literal “change nothing” policy cannot pass: the read-only check scored 1,402/6,799 dev cases and zero non-word repairs.
> - Averaging merged weights in average_weights.py correctly averages model deltas when the inputs share the base.
> - No file edits or training were performed.
