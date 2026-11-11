# Design of the weight-edit comparison for the English re-ranker

## Summary

This design tests one question. Can an edit of the stock weights, with few or no gradient
steps on this task, pick the intended reading as well as the existing fine-tunes do?

1. Build each edited model from the stock weights and the existing fine-tuned weights in
   `build/worktrees/lm-finetune/build/lm-finetune/models`. Train nothing new, except where an
   arm says so.
2. Score every edit on the stopping split, as `train.py` scores a checkpoint. The stopping split
   chooses each edit's own numbers, by the rule in "Selection rule fixed before dev".
3. Convert each chosen edit to Q3_K_M with the llama.cpp b4846 tools of the fine-tune. Check
   tokens and scores against `lm_score`.
4. Run `evaluate.py` of the fine-tune on each chosen edit. The tuning split picks the re-ranker
   setting, and dev scores the arm once at that setting.
5. Leave the test half alone. The report names any arm that should join the fine-tune's single
   test read.

6. Test whether an interpolation between the stock and the fine-tuned weights keeps the clean dev
   cases at the control's count, by the rule in "Interpolation between stock and fine-tuned
   weights for the clean dev cases".

This design does not settle phone time or memory on the device. It does not test the edits on
slips from a source other than our generator, apart from the published misspellings.

## Glossary

| Term | Meaning |
| --- | --- |
| stock weights, theta_0 | The Hugging Face weights of distilgpt2 or SmolLM2-135M, before any training on this task. |
| fine-tuned weights, theta_i | The merged weights of one existing fine-tune, for example `smollm2-lora-seed1`. |
| task vector, tau_i | theta_i less theta_0, weight by weight (Ilharco et al. 2023). |
| lam | The scale of a task vector in an edit. |
| stopping split | 7,556 lists from new sentences (`lists.stop.jsonl.gz`). It chose each fine-tune's checkpoint. Here it chooses lam and the other numbers of each edit. |
| tuning split | 6,748 cases (`cases.tune.jsonl`). It chooses the re-ranker setting of every arm in `evaluate.py`. |
| dev | The 6,799 generated dev cases, then the 751 published misspellings apart. |
| lists right | The stopping lists whose target has the highest engine score plus model score, at weight 1, with the space-after term, without margins. The engine alone gets 6,766 of 7,556. |
| setting | The weight, the three margins and the space-after switch of `rerank.py`. |
| gradient step on this task | One optimizer update from the loss on our lists. An arm built from a fine-tune inherits that fine-tune's steps. |

## Methods found in the search, and their fit to this task

The search covered four families. Table 1 names each method by how the field fits it.

Table 1. Weight-editing methods from the literature, and whether each fits a listwise choice
among typing corrections.

| Method (source) | How the field fits it | Fit to this task |
| --- | --- | --- |
| Task vector scaling (Ilharco et al. 2023) | theta_0 + lam * tau, lam chosen on held-out data, 0 to 1 in the paper; values above 1 extrapolate | Fits. One fine-tune per base gives tau. |
| WiSE-FT (Wortsman et al. 2022) | Linear interpolation (1 - a) theta_0 + a theta_1, a chosen on held-out data | Fits. It is the lam in [0, 1] part of the row above. |
| Task arithmetic sum (Ilharco et al. 2023) | theta_0 + lam * sum of several tau_i | Fits distilgpt2, which has several fine-tunes. |
| Uniform model soup (Wortsman et al. 2022) | Mean of several fine-tuned weights from one base | Fits distilgpt2. |
| TIES-merging (Yadav et al. 2023) | Flatten each tau_i over the whole model and keep its top 20 percent by magnitude. The sign of each weight's sum wins, and a zero sum takes the majority sign. Average the values that agree, scale by lam. This follows the authors' `merge_utils.py`. | Fits distilgpt2. With one tau it reduces to a magnitude trim, so SmolLM2 does not get a TIES arm. |
| DARE (Yu et al. 2024) | Drop each weight of tau_i with probability p, scale the rest by 1 / (1 - p), then merge | Fits both bases. |
| Task vector from a public sibling checkpoint | theta_0 + lam * (theta_instruct - theta_0), lam chosen on held-out data | Fits SmolLM2, which has `SmolLM2-135M-Instruct`. It takes no gradient step on this task. |
| Training-Free Task Vectors, TFTV (Perin et al. 2026, arXiv 2609.09054) | A steering vector s from forward passes. Each attention output projection W of a block range gets W + alpha * s_bar q^T, with q = sum_i sign(mu^T v_i) sigma_i v_i from the SVD of W and the mean input mu. The update has the Frobenius norm of W. alpha in 0.01 to 0.05. | Fits. It is a training-free weight edit, and its update depends on the input. |
| Contrastive activation addition, CAA (Rimsky et al. 2024; ActAdd, Turner et al. 2023) | Mean difference of residual activations between positive and negative examples, added at the answer positions with a coefficient | A weight edit can only add a constant at every position. So this design runs a substitute, named "mean-reading attention-bias steering" in every table. |
| ROME, MEMIT, AlphaEdit (Meng et al. 2022, 2023; Fang et al. 2025) | A rank-one or least-squares update of mid-layer MLP weights, keyed on the last token of a subject, toward a value vector found by gradient descent | Does not fit. See below. |

ROME, MEMIT and AlphaEdit do not get an arm. The field has not mapped their objective onto a
listwise choice among readings, and this design would have to invent that mapping.

1. Each edit writes one (subject, relation, object) fact as a new output for a key. The key is
   the hidden state at the subject's last token. Our target is a choice among up to 8 readings,
   scored by the probability of each reading's tokens. No reading is one object token.
2. The papers test an edit on its own fact and on paraphrases of it. They do not test transfer
   to new facts. Our dev cases hold typed and intended pairs that training does not hold.
3. Each value vector comes from gradient steps on the edit's own loss. So these methods are not
   training-free.
4. Gupta et al. 2024 (arXiv 2401.07453) report gradual and then sudden forgetting over a few
   thousand sequential ROME and MEMIT edits. AlphaEdit (Fang et al. 2025) targets that problem.
   Our training lists number about 100,000. The design does not test how many edits would serve.

Practitioners merge with mergekit (Goddard et al. 2024). A 2025 study of merging LLMs "in the
wild" (arXiv 2511.21437) found that plain task arithmetic gave the only reliable gain in its
setting. Tan et al. 2024 (arXiv 2407.12404) found that steering vectors generalize for some
concepts and not for others. Neither study predicts the outcome here.

## Arms and controls

Table 2. Every arm of SmolLM2-135M, named by how it is fit. "Steps" counts gradient steps on
this task, including those of the fine-tune the arm starts from.

| Label | Edit | Numbers searched on the stopping split | Steps |
| --- | --- | --- | --- |
| `s-stock` | theta_0 | none | 0 |
| `s-lora` | theta_1 = merged `smollm2-lora-seed1` | none | 4,500 |
| `s-tv` | theta_0 + lam * tau_1. lam = 1 is `s-lora`. | lam in 0.25, 0.5, 0.75, 1.25, 1.5, 1.75, 2, 2.5, 3 | 4,500, inherited |
| `s-dare` | DARE of tau_1 | p in 0.5, 0.9, 0.99, times lam in 1, 1.5, seed 1 | 4,500, inherited |
| `s-random` | theta_0 + lam * r, r Gaussian with the norm of tau_1 in each tensor | lam in 0.5, 1, 2, seed 1 | 0 |
| `s-instruct` | theta_0 + lam * (theta_instruct - theta_0) | lam in -1, -0.5, 0.5, 1 | 0 |
| `s-steer` | Mean-reading attention-bias steering at block L (a substitute for CAA) | L in 4, 8, 15, 22, alpha in -2, -1, 1, 2, 4, 8 | 0 |
| `s-tftv` | TFTV on the attention output projections of blocks a to b - 1 | blocks 8-16, 12-22, 16-24; alpha in 0.01 to 0.05, then 0.1 and 0.2 as an extension past the paper's grid | 0 |
| `s-steer-shuffled`, `s-tftv-shuffled` | The chosen steer and TFTV arms, with vectors from random labels | none | 0 |

Table 3. Every arm of distilgpt2. L1 and L2 are the LoRA fine-tunes of seeds 1 and 2. F1 is the
full fine-tune. L2 joins only if its training ends during this work.

| Label | Edit | Numbers searched on the stopping split | Steps |
| --- | --- | --- | --- |
| `d-stock` | theta_0 | none | 0 |
| `d-tv-lora` | theta_0 + lam * tau_L1 | lam as in `s-tv`, plus 1 | 7,000, inherited |
| `d-tv-full` | theta_0 + lam * tau_F1 | lam as in `s-tv`, plus 1 | 2,000, inherited |
| `d-soup` | mean of L1, F1 (and L2) | none | inherited |
| `d-ta` | theta_0 + lam * (tau_L1 + tau_F1 (+ tau_L2)) | lam in 0.3, 0.5, 0.7, 1 | inherited |
| `d-ties` | TIES of the same task vectors, top 20 percent per tensor | lam in 0.5, 1, 1.5, 2 | inherited |
| `d-dare` | DARE p = 0.9 of each, then their sum | lam in 0.5, 1 | inherited |
| `d-random` | Gaussian with the norm of tau_L1 per tensor | lam in 0.5, 1, 2 | 0 |
| `d-steer` | Mean-reading attention-bias steering at block L, added to the GPT-2 attention output bias | L in 2, 3, 4, alpha in -2, -1, 1, 2, 4, 8 | 0 |
| `d-tftv` | TFTV on the attention output projections | blocks 1-3, 2-4, 3-5; alpha as in `s-tftv` | 0 |
| `d-steer-shuffled`, `d-tftv-shuffled` | As for SmolLM2 | none | 0 |

The steering vector is the mean, over 2,000 training lists, of one difference. It is the mean
residual stream at the target reading's tokens, less the same mean over the other readings. The
stock model computes it in forward passes, without a gradient. The steer arm takes the vector
that enters block L, and adds it as block L's attention output bias, at every position. TFTV takes
the vector that leaves each edited block, as the paper does. Its mean input mu is the mean input
of the attention output projection over every reading's tokens.
SmolLM2 has no attention biases, so its export sets `attention_bias` and writes zero q, k and v
biases. llama.cpp b4846 reads these tensors as optional (`src/llama-model.cpp` lines 1537 to
1540).

The controls answer four questions.

- `s-stock` and `d-stock` give the edit-free floor.
- The fine-tunes give the ceiling an edit has to reach: their stopping and dev numbers.
- `s-random` and `d-random` test whether any change of that size moves the score.
- `s-tv` at lam below 1 tests whether a smaller step from the stock model ranks as well, as
  WiSE-FT reports for robustness.
- The shuffled-label arms test whether a steering or TFTV gain needs the target label.
- Scaling a merged LoRA delta by lam equals running the LoRA adapter with alpha times lam. So
  `s-tv` and `d-tv-lora` do not find a new direction. They test the adapter's scale. The
  re-ranker weight differs: it scales the finished model score, and the tuning grid already
  searches it.
- A uniform soup of n fine-tunes equals `ta` at lam = 1 / n.

## Selection rule fixed before dev

1. Within each labeled family, the arm with the most lists right on the stopping split wins. A
   tie goes to the lower stopping loss.
2. Each winner goes to Q3_K_M and `evaluate.py`. So do `s-stock`, `s-lora`, the `s-random` arm at
   lam 1, and their distilgpt2 counterparts that lack a dev score.
3. The tuning split picks each arm's setting, with the clean rule of `rerank.py`.
4. Dev scores each arm once, at that setting. Dev picks nothing in this design. The ranking
   among arms on dev is reported, not acted on.
5. The stopping split also chose the fine-tunes' checkpoints, by the lowest loss. An inherited
   edit gets a second search on the same split, by lists right. So a gain over the fine-tune on
   the stopping split can come from the extra search alone. Dev, at the setting from the tuning
   split, is the fair comparison.

## Interpolation between stock and fine-tuned weights for the clean dev cases

This part tests a keyboard hypothesis that follows Wortsman et al. 2022. They report that a
model between the stock and the fine-tuned weights keeps the fine-tune's accuracy on its own
task, and gains accuracy under distribution shift. They do not promise the stock model's
choice on each input. Each fine-tune here keeps fewer clean dev cases than the control at its
tuning-split setting. The hypothesis: an interpolated model keeps the clean dev cases at the
control's count, and keeps most of the dev gain.

The stock models in the typed format also sit below the control on clean dev cases, at 948 and 954
of 973 against 957. So a pass cannot mean a return to the stock model's behaviour. A pass needs
the model and its tuned setting together to keep the clean cases.

WiSE-FT builds (1 - a) theta_0 + a theta_1. Task vector scaling below 1 builds
theta_0 + a tau_1. With one fine-tune per arm, the two formulas give the same weights. So this
design runs one arm per coefficient a, and every table names it "WiSE-FT interpolation, equal to
task vector scaling at lam = a".

Table 4. The interpolation arms. The grid was fixed before any interpolated arm met dev. The dev
results of the fine-tunes were known, and they are the reason for this part.

| Label | Edit | Coefficient grid | Steps |
| --- | --- | --- | --- |
| `s-wise-a` | (1 - a) theta_0 + a theta_1, theta_1 = merged `smollm2-lora-seed1` | a in 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9 | 4,500, inherited |
| `d-wise-a` | (1 - a) theta_0 + a theta_L1, theta_L1 = merged `distilgpt2-lora-seed1` | the same nine values | 7,000, inherited |
| `d2-wise-a` | The same edit from theta_L2 = merged `distilgpt2-lora-seed2` | the same nine values | 6,000, inherited |

The reference rows are a = 0 (`s-stock`, `d-stock` in the typed format) and a = 1 (`s-lora`,
`d-lora`, `d-lora` seed 2). Every arm is a Q3_K_M file in the typed format. `d2-wise` repeats
`d-wise` on the second seed of the same fine-tune. It shows how far a pass depends on the seed.

Each coefficient follows these steps.

1. Export the weights, convert to Q3_K_M, and check tokens and scores, as every other arm.
2. `evaluate.py` picks the setting on the tuning split, with the clean rule of `rerank.py`, and
   scores dev and the published misspellings of the dev half at that setting. It runs with
   `--skip-dev-grid`, so dev does not tune a setting.
3. `eval_extra.py` types the 6,740 stopping cases (`cases.stop.jsonl`) through the keyboard rules
   at that setting. It also scores the control on them.
4. `eval_extra.py` scores dev and the published misspellings at the common setting of the base
   (see "Controls for the re-ranker setting").

The tuning split is a weak judge of the coefficients on clean cases. Every tuned setting has to
keep the control's clean counts there, so the tuning rule has already used those cases. The
stopping cases are the nearest set outside dev. Each fine-tune read the stopping lists only for
its checkpoint, by the listwise loss. That reuse makes a count on the stopping cases optimistic.
So the stopping cases choose a coefficient, and they are not evidence for it.

Selection rule for the coefficient, fixed before any interpolated arm met dev:

1. A coefficient is eligible when its clean group and its clean-symbol group on the stopping
   cases both hold at least as many right cases as the control there.
2. The chosen coefficient of a base is the eligible grid value with the most right stopping
   cases. A tie goes to the smaller coefficient.
3. If the grid does not hold an eligible value, the base does not get a chosen coefficient.
4. Dev does not take part in the choice. The report gives every grid value on dev.

Dev criteria for the chosen coefficient, fixed before any interpolated arm met dev:

- Clean rule: at least 957 of 973 clean dev cases right and at least 427 of 429 clean-symbol dev
  cases right. These are the control's counts, and this is the pick rule of the fine-tune design.
- Gain kept: (dev right at a, less dev right at a = 0) divided by (dev right at a = 1, less dev
  right at a = 0). "Most of the gain" means a share above 0.5. With the endpoints at 6,084 and
  6,537, SmolLM2 needs 6,311 right dev cases. With 6,087 and 6,491, distilgpt2 seed 1 needs 6,290.
- Published misspellings: right cases of 751, against the control (381) and against a = 1, with
  the exact McNemar test for both.

The chosen coefficient passes when it meets the clean rule and keeps more than half the gain. A
pass is a pass of the observed counts. The clean groups differ by 1 to 12 cases between arms, and
two seeds of one LoRA fine-tune differ by 5 clean dev cases. So the report adds four numbers.

- Per clean group, the clean cases the control gets right and the arm gets wrong, and the reverse,
  with the exact McNemar test on those cases. Equal counts can hide a broken case beside a
  repaired one.
- The grouped bootstrap interval of dev right at a, less the mean of dev right at a = 0 and a = 1.
  A lower bound above 0 supports "more than half the gain".
- The count of grid values that pass on dev. That count reads dev nine times per base. It
  describes the curve, and it does not confirm a choice.
- The same criteria on the shared held-out cases of the second fine-tuning round, with the
  control's counts on those cases as the thresholds. That read confirms or rejects the pass.

The report gives, per coefficient: the clean group, the clean-symbol group, each of the 24
generated categories, the published misspellings per source, and the total.

## Controls for the re-ranker setting

The re-ranker adds weight times the model score to the engine score, then applies its margins.
An interpolated model can differ from the fine-tune mostly in the scale of its scores, and the
tuning grid already searches that scale. The interpolation also gets a second search, on the
stopping cases, that the fine-tune did not get. Two controls separate these explanations.

- Common setting: every coefficient of a base is also scored on dev at one shared setting, the
  tuned setting of its a = 1 fine-tune. For SmolLM2 that is weight 1.5 and margins 2, 4, 2. For
  distilgpt2 seed 1 it is weight 1.5 and margins 1, 4, 2. For seed 2 it is weight 1.0 and margins
  1, 0, 0. All three have the space-after term on. This row shows the change from the weights
  alone.
- Calibration-only candidates: the fine-tune at a = 1 with nine candidate settings, one per
  re-ranker weight of the grid (0.1 to 3.0). Each candidate is the best tuning-split setting of
  that weight under the clean rule. The selection rule above then picks among the nine on the
  stopping cases, with a tie going to the lower weight. So the fine-tune gets the same extra
  search as the interpolation. Interpolation adds something only if its chosen coefficient does
  better on the dev criteria than this chosen candidate.

## Controls added after the first dev table

- Random-edit control with several seeds: `s-random` and `d-random` at lam 1 with seeds 1 to 5.
  Each seed draws a new Gaussian direction with the norm of the task vector in each tensor. Each
  seed gets its own conversion, tuning-split setting and dev score. The report gives the five dev
  counts per base, and their range. These seeds measure the spread of a random direction. They do
  not measure the spread between fine-tuning seeds.
- Bootstrap over repeated contexts: dev holds 574 cases that repeat a context and an intended
  text of another case. `paired.py` adds a 95 percent interval of the difference in right cases.
  It resamples the 6,225 groups of one context and one intended text, 10,000 times, as
  `summarize.py` of the fine-tune does.

## Shared held-out cases of the second fine-tuning round

The second fine-tuning round (branch `engine/lm-finetune2`) builds new held-out cases. When they
exist, its scripts score these arms on them: the control, the chosen coefficient of each base, the
chosen calibration-only candidate, both fine-tunes, both stock models, and the dev rows of the
first table. Every coefficient and setting is fixed before that read. This design does not build
held-out cases of its own, and it does not read the test half.

## Quantization and the phone path

- `convert_hf_to_gguf.py` of llama.cpp b4846, f16, then `llama-quantize` Q3_K_M, as
  `convert_arm.ps1` of the fine-tune does.
- SmolLM2 rows use Q3_K_M, as the request names. The fine-tune scored SmolLM2 at Q4_K_M, so this
  work re-scores `smollm2-stock` and `smollm2-lora-seed1` at Q3_K_M for a like-for-like row.
- `check_parity.py` checks tokens on 2,000 tuning lists, and the f16 scores against PyTorch on
  500 lists within 0.05 nats.
- The quantization loss is measured on the same 500 parity lists of the tuning split: lists right
  from `lm_score` at f16 against Q3_K_M, at weight 1 without margins. A stopping-split number in
  PyTorch against a dev number at Q3_K_M mixes splits and settings, so this design does not call
  that difference a quantization loss.

## Limits of this design

- Every inherited arm needs the fine-tune first. Only `s-random`, `s-instruct`, `s-steer` and
  `d-steer` take no gradient step on this task.
- One SmolLM2 fine-tune exists. So SmolLM2 does not get a merge of two task vectors.
- The stopping split chooses lam. It also chose the checkpoint, so a gain over the fine-tune on
  that split is partly a second pick on it. Dev is the fair comparison.
