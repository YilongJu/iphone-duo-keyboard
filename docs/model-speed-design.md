# Speed test of larger language models

This page sets the delay target, the models and the ways to run them, and the method of the
speed test. `docs/model-speed-results.md` holds the numbers. Fine-tuning is out of scope: every
model is a stock base model.

## Glossary

| Term | Meaning |
| --- | --- |
| request | One call of the re-ranker at a space press: a context and 1 to 8 candidates, in the prompt format of `Shared/LanguageModelPrompt`. |
| window | The start token and at most 96 tokens of the context, the text the model reads before the candidates. |
| window part | The time of the model calls that read the window tokens that the cache does not hold yet. |
| candidate part | The time of the model calls that read the candidates. |
| request time | Window part plus candidate part: all model work for one word. |
| felt delay | The time from the space press to the corrected text. It is the request time when the model reads everything at the space, and the candidate part when the window part runs before the space. |
| pair | One model and one way to run it. |
| top candidate | The candidate with the highest log probability plus space-after term. |
| agreement | The share of requests whose top candidate equals the top candidate of llama.cpp on the same model at Q8_0 on the desktop. It checks that a conversion is correct. |
| reuse | The cache reuse of `engine/kv-reuse`: the anchored window with two slots, approach DE of `docs/kv-reuse-design.md`. |
| Q4_K_M, Q4_0, Q8_0 | Weight types of llama.cpp: about 4.8, 4.5 and 8.5 bits per weight. The keyboard's file is Q4_K_M. |
| int4 | The 4-bit Core ML weights of `scripts/model-speed/coreml/convert.py`: symmetric, in blocks of 32. |

## Delay target

The felt delay on the phone must have a median of 20 ms or less and a 95th percentile of 50 ms
or less. The test also gives the request time, because the window part can run while the
person types the next word only if the request time fits between key presses.

Today the keyboard reads the whole request at the space press. On build 44 the space press
waited 101 ms in the median and 160 ms at the 95th percentile. So the target asks for about
five times less.

## Shortlist

| Model | Hugging Face revision | Layers, KV heads, head size | Vocabulary | Note |
| --- | --- | --- | --- | --- |
| SmolLM2-135M | `93efa2f` | 30, 3, 64 | 49,152 | The base of the keyboard's fine-tune. The baseline. |
| SmolLM2-360M | `f8027fd` | 32, 5, 64 | 49,152 | Same tokenizer as the keyboard. English only. |
| Qwen2.5-0.5B | `060db64` | 24, 2, 64 | 151,936 | Smallest cache per token. Also covers Chinese. |
| Qwen3-0.6B-Base | `da87bfb` | 28, 8, 128 | 151,936 | Newest Qwen at this size. |
| Granite-4.0-350M-Base | `a50b46c` | 28, 4, 64 | 100,352 | The attention-only Granite 4.0, not the hybrid "-h". |

All five use the Apache 2.0 license. `scripts/model-speed/models.json` pins each revision.

The test also runs the keyboard's own file, the SmolLM2-135M fine-tune at Q4_K_M, so every way
to run it has the number of today's model beside the others.

## Ways to run a model

| Way | Where it runs | Reuse | Note |
| --- | --- | --- | --- |
| llama.cpp b4846, processor | the app's framework, 2 threads | yes | Today's way. b4846 has no architecture "qwen3", so it cannot load Qwen3. The attention-only Granite 4.0 converts to the architecture "granite", which b4846 loads. |
| llama.cpp b4846, Metal | the app's framework, every layer on the GPU | yes | The framework holds the Metal code with its library source, so Metal compiles its kernels at the first load. |
| llama.cpp b4846, Metal without residency | as above, with `GGML_METAL_NO_RESIDENCY=1` | yes | Checks whether the residency set of llama.cpp raises the footprint. |
| Core ML, CPU and GPU | a stateful Core ML model of `scripts/model-speed/coreml` | yes | Every model of the shortlist. |
| Core ML, all units | as above, the Neural Engine allowed | yes | SmolLM2-135M only. The model's shapes change from call to call, so Core ML is not expected to use the Neural Engine. |
| llama.cpp b12017, processor | a build of our own | yes | Desktop and macOS runner only in this round (see "Limits"). |

### The Core ML model

`scripts/model-speed/coreml/scoring_model.py` holds one small decoder for the four
architectures. It loads the Hugging Face weights and keeps the keys and values in two buffers
that coremltools turns into the state of the Core ML model, so the cache stays on the device
between calls. The model does the sums of the scorer itself, so a call returns a few numbers per
token and never the 49,152 to 151,936 scores of the vocabulary:

- the scores of the vocabulary after the last token, for the first token of each candidate
- the score of the next token of the same candidate, for every other token
- the log of the sum of e to each score, and the same sum over the tokens that start with a space

A request makes two calls. The window call reads the window tokens that the cache does not hold.
The candidate call reads every candidate in one call: each candidate takes cells of its own
after the window, and the attention mask lets each candidate see the window and its own earlier
tokens only. The window rules copy `LanguageModel/duo_lm_scorer.c`, and each slot of the reuse
has a Core ML state of its own.

Core ML has no tokenizer for these models, so `speed_cli tokens` writes the tokens of each
request with llama.cpp's tokenizer, into `Shared/model-speed-tokens.MODEL.tsv`.

## Method

### Requests

`scripts/model-speed/freeze_requests.py` takes 486 requests from the speed pass of
`docs/kv-reuse-results.md`, as whole documents in their order, so the reuse sees the same
sequence of requests as in the keyboard:

| Part | Requests | Documents |
| --- | --- | --- |
| dev cases, every 20th | 103 | 84 |
| work area cases, every 16th | 101 | 89 |
| everyday stream, field 1 | 74 | 1 |
| technical stream, field 7 | 99 | 1 |
| written stream, field 11 | 109 | 1 |

`Shared/model-speed-requests.tsv` holds them, with the SHA-256 value
`40d3b7fb93e02c0c972f18e55baa95281d435f0351e41775351e19dc77ab7533`. Every pair reads the same file.

### Numbers of each pair

1. Load time, and the footprint (`phys_footprint`) right before and right after the load.
2. The memory that iOS still allows (`os_proc_available_memory`) after the load, and its least
   value during the requests.
3. The time of the first request, which pays for the first reads of the weights.
4. Request time, candidate part and window part of the 485 later requests: mean, median, 95th
   percentile and worst.
5. The reuse share: the window tokens that the cache already held.
6. The agreement with llama.cpp on the same model at Q8_0, from the desktop. For the keyboard's
   own file the reference is llama.cpp b4846 on the same file on the desktop.

### Machines

| Machine | What it shows | What it cannot show |
| --- | --- | --- |
| Desktop: Intel i9-13900K in WSL, 2 threads | Cost ratios between the models, the gain of a newer llama.cpp, token counts, the agreement reference | Phone times, Metal, Core ML |
| macOS runner, a virtual Apple M1 with 3 cores | The processor ranking on an ARM Mac, the Core ML conversion check, Core ML on the processor | GPU times (a paravirtual GPU), the Neural Engine (none), the memory limit of a keyboard |
| Phone: iPhone Duo (iPhone19,4) | Every number of the delay target, inside the keyboard extension | The models are not downloaded until the person taps the buttons |

### On the phone

1. The containing app has one button per test model. A tap downloads the files of the model
   from the release `model-speed-1` of this repository into the shared container of the app
   group `group.com.yilongju.duokeyboard`. `App/ModelSpeedDownloader.swift` checks the size and
   the SHA-256 value of each file before the file goes to its place.
2. The person types `duo:speed` and a space with Duo Keyboard. The keyboard frees its own model,
   runs every pair whose files are in place, and types the result lines. The lines also go to
   the system log (subsystem `com.yilongju.duokeyboard`, category `speed`).
3. The keyboard has no network code. It reads only the bundle and the shared container.

Why a download: the files of the shortlist hold about 2.4 GB. In the bundle they would make every
TestFlight build that large. The download keeps the build small, and a person downloads only the
models to measure.

The app group needs one step on developer.apple.com: the App IDs `com.yilongju.duokeyboard`
and `com.yilongju.duokeyboard.keyboard` must both have the App Group capability with
`group.com.yilongju.duokeyboard` selected. A practitioner reports that the App Store Connect API
could not select the group ([Prism #864](https://github.com/Hash-Studios/Prism/pull/864)).
The TestFlight workflow archives with signing off, and an unsigned archive holds no
entitlements, so `scripts/ci/sign_with_entitlements.sh` signs the app and the keyboard ad hoc
with their entitlements before the export.

## Limits

- llama.cpp b12017 does not run on the phone in this round. The app links one llama.cpp, and a
  second release in the same process would clash by its symbol names. The workflow
  "Model speed" builds the xcframework of b12017 with and without the dot-product and i8mm flags,
  as the step before a phone build with it.
- The test does not measure the time between the last letter and the space on the phone. That
  needs typing logs of real use.
- The test does not run the 10-minute run for heat.
- A base model without fine-tuning gives speed and memory only. Its accuracy cannot be compared
  with the fine-tuned 135M model.
