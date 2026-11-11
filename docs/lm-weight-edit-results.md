# Weight edits of the English re-ranker compared with its fine-tunes

## Summary

No training-free weight edit improves the re-ranker on dev. Every edit that gains on dev starts
from a fine-tune, and the gain over that fine-tune stays inside the noise of two seeds.

What to do:

1. Keep the fine-tuned models as the candidates for the test read. A weight edit does not
   replace the fine-tune.
2. If the test read takes one more SmolLM2 arm, take `s-dare`
   (`build/lm-weight-edit/models/s-dare-p0.5-lam1.0`, Q3_K_M file
   `~/lmedit/models/s-dare-p0.5-lam1.0.Q3_K_M.gguf` in WSL). Its gain over the LoRA fine-tune
   is 9 dev cases, p = 0.25, so it is a control for the fine-tune, not a new method to ship.
3. If the test read takes one more distilgpt2 arm, take `d-ties`
   (`~/lmedit/models/d-ties3-1.0.Q3_K_M.gguf`). PENDING_TIES_SENTENCE
4. Do not spend more work on steering vectors or TFTV for this task. Their gain on the stopping
   split disappears once the tuning split sets the re-ranker weight and margins.

This report does not settle the test-half result, phone time, or phone memory.

## Glossary

| Term | Meaning |
| --- | --- |
| reading | One way to read the typed span as words. The engine gives up to 8. |
| list | The readings at one correction, with the text before the span and the target. |
| stopping split | 7,556 lists from new sentences. It chose each fine-tune's checkpoint, and here it chooses each edit's own numbers. The engine alone gets 6,766 right. |
| tuning split | 6,748 cases. It picks the re-ranker setting of every arm. |
| dev | The 6,799 generated dev cases. The engine alone gets 6,069 right, and a chooser that knows the target gets 6,688. |
| setting | The weight, the three margins and the space-after switch of `rerank.py`. |
| task vector | The fine-tuned weights less the stock weights, weight by weight. |
| lam | The scale of a task vector in an edit. |
| typed format | The input in which the model reads the text before the span, then the typed span between bars, then the reading. Every edit here uses it. |

Table 1. The arm labels of this report. The prefix names the base model.

| Label | Edit | Why it exists |
| --- | --- | --- |
| `s-stock`, `d-stock` | Stock weights of SmolLM2-135M or distilgpt2 | The floor without an edit |
| `s-lora`, `d-lora`, `d-full` | The existing fine-tunes | The comparison the request names |
| `s-dare`, `d-dare` | DARE (Yu et al. 2024) of the fine-tunes' task vectors | A merge method that drops and rescales the task vector |
| `d-tv-lora`, `d-tv-full` | A fine-tune's task vector scaled by lam | Task arithmetic (Ilharco et al. 2023) and WiSE-FT interpolation (Wortsman et al. 2022) |
| `d-soup`, `d-ta`, `d-ties` | Merges of the three distilgpt2 fine-tunes: uniform soup, task arithmetic, TIES (Yadav et al. 2023) | Merges of several fine-tunes |
| `s-random`, `d-random` | A random direction with the task vector's norm in each tensor | Tests whether any change of that size moves the score |
| `s-instruct` | The task vector of SmolLM2-135M-Instruct | A training-free task vector from a public checkpoint |
| `s-steer`, `d-steer` | Mean-reading attention-bias steering, a substitute for contrastive activation addition | A training-free edit from forward passes |
| `s-tftv`, `d-tftv` | Training-Free Task Vectors (Perin et al. 2026) | The training-free weight edit the field reports for behaviour |

## Dev results of every chosen arm

Each arm's own numbers come from the stopping split, by the rule in
`docs/lm-weight-edit-design.md`. The tuning split then picks its setting, and dev scores it once.
The fine-tune rows come from the fine-tune worker's own `evaluate.py` runs, on the same path.

Table 2. Every arm at Q3_K_M, with the stock and fine-tuned models. "Inherited" steps belong to
the fine-tunes an edit starts from. The parity lists are 500 lists of the tuning split, scored at
weight 1 by `lm_score`.

TABLE

The more an edit starts from a fine-tune, the more dev cases it gets right. Every edit with zero
gradient steps on this task lands within 20 dev cases of its stock model.

## Scale of a task vector on the stopping split

Table 3. Lists right of 7,556 on the stopping split, at weight 1, as the task vector scale lam
changes. lam = 0 is the stock model, and lam = 1 is the fine-tune.

PENDING_CURVE

The stopping split peaks at lam = 1 for SmolLM2 and at lam = 1.25 for distilgpt2. The gain past
lam = 1 is 4 lists or fewer. So the fine-tune's own checkpoint is already at the best scale, and
extrapolation past it does not add a gain. Scaling a merged LoRA task vector by lam equals running
the adapter with alpha times lam. So this curve measures the adapter's strength.

## Training-free edits and their stopping-split gain

The training-free edits gain on the stopping split and lose that gain on dev.

Table 4. Training-free edits on the stopping split at weight 1, and on dev at the tuned setting.

PENDING_FREE

The stopping split scores the model at weight 1 without margins. In the typed format the stock
model scores below the engine alone at that setting: 6,492 and 5,839 against 6,766. A steering or
TFTV edit moves the model score toward the target reading on average, and that recovers part of
the gap. The tuning grid recovers the same gap by a lower weight and wider margins. Every
training-free arm takes weight 0.5 or 0.75 on the tuning split, as the stock models do. So both
fixes change the same calibration, and they do not add up.

The shuffled-label controls show that the stopping-split gain needs the target label for steering
and for SmolLM2's TFTV. distilgpt2's TFTV keeps 478 of its 802 lists with random labels. So most
of that gain comes from the size of the rank-one update, not from the label.

## Merges of the distilgpt2 fine-tunes

PENDING_MERGE

## Methods the search found that do not fit this task

ROME, MEMIT and AlphaEdit edit a (subject, relation, object) fact as a new output for the key at
the subject's last token. Each value vector comes from gradient steps on that one edit. The papers
test an edit on its fact and its paraphrases. Our target is a choice among readings of several
tokens each, and dev holds typed and intended pairs that training does not hold. The field has
not mapped this objective onto a ranking task, so this work does not run them. The design gives
the full reasons and sources.

Contrastive activation addition adds its vector only at the answer positions. A weight edit adds a
constant at every position. So the steering arms here are a substitute, and every table names them
"mean-reading attention-bias steering".

## Checks of the conversion and the quantization loss

- Tokens: every converted arm matches `lm_score` on all 2,000 parity lists.
- Scores: PyTorch and `lm_score` at f16 agree within 0.05 nats on 500 lists for every SmolLM2 arm.
  Three distilgpt2 arms exceed the limit on one reading of 3,982: `d-tv-lora` at 0.057, `d-ta` at
  0.051 and `d-tftv` at 0.057. Their mean gaps are 0.007 to 0.008 nats, as the fine-tunes' are.
  Their dev results stand, with that one failed check named.
- Quantization: on the 500 parity lists, Q3_K_M loses 4 lists or fewer against f16 for every arm
  that starts from a fine-tune. The stock SmolLM2 loses 9, and the instruct edit loses 9.
- The SmolLM2 steering edit adds q, k, v and o biases. llama.cpp b4846 loads them, and its scores
  match PyTorch within 0.038 nats.

## Fit on the phone

Every SmolLM2 arm at Q3_K_M takes 93.5 MB, or 93.7 MB with the steering biases. The SmolLM2
Q4_K_M file of the fine-tune takes 105.5 MB. The phone has about 110 MB of headroom. Every
distilgpt2 arm takes 75.4 MB. A weight edit does not change the phone time, because it keeps the
architecture.

## Limits of this comparison

- One SmolLM2 fine-tune exists, so SmolLM2 does not get a merge of two task vectors.
- The stopping split chose both the fine-tunes' checkpoints and the edits' numbers. Dev is the
  fair comparison, and dev differences under about 30 cases are within the spread of two seeds.
- The distilgpt2 steering and TFTV grids were extended past the design's grid, on the stopping
  split, because the best value sat at the edge. Dev did not take part in that choice.
- The test half was not read.
