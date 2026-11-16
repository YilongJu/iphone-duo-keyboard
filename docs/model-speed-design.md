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
| flexible form | The Core ML model whose shapes change from call to call. Core ML runs it on the processor or the GPU. |
| fixed form | The Core ML model that lists its shapes in advance ([enumerated shapes](https://apple.github.io/coremltools/docs-guides/source/flexible-inputs.html "coremltools: a model that lists the input shapes it accepts. From iOS 18 on, several inputs may list shapes, matched by their place in the list.")), so the Neural Engine can run it. |
| compute plan | Core ML's plan of the device (processor, GPU or Neural Engine) for each operation of a model, from [`MLComputePlan`](https://developer.apple.com/documentation/coreml/mlcomputeplan "Apple: the compute device usage and the estimated cost of each operation of a model, for a given configuration."). |
| processor time | The time that all threads of the process spent on the processor during a request, from `getrusage`. Divided by the request time, it gives about the count of busy threads. |
| thermal state | The heat level that iOS reports to an app, from `ProcessInfo.thermalState`: nominal, fair, serious or critical. A hot phone slows down. |
| control pair | The keyboard's file on the processor, run again as the last pair. Its times against the first pair show how much the phone slowed down during the run. |

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
| Core ML, CPU and GPU | the flexible form of a stateful Core ML model of `scripts/model-speed/coreml` | yes | Every model of the shortlist. |
| Core ML, CPU and Neural Engine | the fixed form of the same model | yes | Every model of the shortlist. The compute plan line says which operations Core ML puts on the Neural Engine. |
| llama.cpp b12017, processor | a build of our own | yes | Desktop and macOS runner only in this round (see "Limits"). |

### The Core ML model

`scripts/model-speed/coreml/scoring_model.py` holds one small decoder for the four
architectures. It loads the Hugging Face weights and keeps the keys and values in two buffers
that coremltools turns into the state of the Core ML model, so the cache stays on the device
between calls. The model does the sums of the scorer itself, so a call returns a few numbers per
scored token and never the 49,152 to 151,936 scores of the vocabulary:

- the scores of the first token of each candidate after the last window token
- the score of the next token of the same candidate, for every other token
- the log of the sum of e to each score, and the same sum over the tokens that start with a space

A request has two parts. The window part reads the window tokens that the cache does not hold
and scores the last of them only, as the C scorer asks llama.cpp for the scores of the last
window token only. The candidate part reads every candidate: each candidate takes cells of its
own after the window, and the attention mask lets each candidate see the window and its own
earlier tokens only. Every candidate token is scored, as in the C scorer. The window rules copy
`LanguageModel/duo_lm_scorer.c`, and each slot of the reuse has a Core ML state of its own.

`scripts/model-speed/coreml/convert.py` makes two forms of each model:

| Form | Shapes | Cache cells per call | Runs on |
| --- | --- | --- | --- |
| flexible | any count of tokens from 1 to 288 | the cells up to the last token of the call | the processor and the GPU |
| fixed | window part: 8, 16, 32 or 64 tokens; candidate part: 12, 24, 40 or 56 tokens, every token scored | all 512 cells, with an input that names the cell of each token | the Neural Engine, where Core ML puts it there |

The fixed form pads each call to the smallest shape of its part that holds its tokens, and
splits a part that is longer than its largest shape into several calls. A padding token writes
no cell. Core ML matches the listed shapes of the inputs by their place in the list, and it
refuses a model in which one input lists the same shape twice. So no two shapes share a count
of tokens or a count of scored tokens. A window shape scores its last token 1, 2, 3 or 4 times,
one count per shape, only to keep the counts apart. The fixed form makes the
scores of the vocabulary in parts of 16,384 tokens, because the Neural Engine takes no axis
longer than 16,384 ([an optimization guide](https://gist.github.com/antmikinka/715499ae63630575065b22e5cb6ad8dd "A practitioner's guide to the Neural Engine: it loads only tensors with no dimension above 16,384.")).
The parts hold a second copy of the embedding, so the fixed form is larger than the flexible
form: 93 MB against 77 MB for SmolLM2-135M at int4, and 356 MB against 279 MB for Qwen2.5-0.5B. On the requests of the speed test a window
part reads 5 tokens in the median and 68 at most, and a candidate part 17 in the median and 41
at most.

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

1. Load time, twice: the first load, and a second load after a close. The second load shows the
   cost of a load when Core ML has its compiled form of the model on disk already and the
   weights are in memory. The requests run on the model of the second load.
2. The share of the weight file in memory before the first load, from `mincore`. The keyboard's
   own file is in memory when the keyboard used it just before. A downloaded file is in memory
   only when the app read it a short time before.
3. The footprint (`phys_footprint`) right before the first load and right after the second, and
   the memory that iOS still allows (`os_proc_available_memory`).
4. The highest footprint during the loads and during the requests. A thread of its own reads the
   footprint every 2 ms, so a peak inside a request counts. The line also gives the highest
   footprint of the process so far (`ledger_phys_footprint_peak`) and whether this pair set it.
5. The time of the first request, which pays for the first reads of the weights.
6. Request time, candidate part and window part of the 485 later requests: mean, median, 95th
   percentile and worst. The request time starts at the tokens, so llama.cpp's tokenizer is left
   out of it. The Core ML pairs read tokens made in advance. The tokenizer line gives llama.cpp's
   tokenizer time, which a Core ML keyboard would pay too.
7. The reuse share: the window tokens that the cache already held.
8. The agreement with llama.cpp on the same model at Q8_0, from the desktop. For the keyboard's
   own file the reference is llama.cpp b4846 on the same file on the desktop.
9. The processor time of the process per request and its ratio to the request time. llama.cpp
   runs at 2 threads, and Core ML picks its own count of threads with no setting to change it.
   The ratio shows the count that each pair used.
10. Where the model ran. For Metal: llama.cpp's own line about residency sets, which exist only
    in a framework built with the iOS 18 SDK or later. For Core ML: the compute units, the form,
    the calls and the padded tokens, and the compute plan: per device, the operations that
    prefer it and their share of Core ML's estimated cost.
11. The thermal state at the start of the pair and the worst during it.

### Fair conditions for every pair

- Every pair reads the same 486 requests in the same order, with the same reuse of the cache.
- The keyboard holds its own model freed from the start of the run to its end. A load that was
  under way ends before the first pair starts, and no new load starts when the keyboard appears
  again or the language changes.
- Before each pair the test pauses for 20 seconds and then waits until the thermal state is
  nominal, for at most 180 seconds more. The heat line gives the pause.
- The control pair runs last. The larger models, Metal and Core ML run after minutes of load, so
  the control pair shows whether the phone slowed down over the run.
- The run keeps a record in the keyboard's Application Support folder: the start and the end of
  each pair, and the result lines of each pair. Each later `duo:speed` types the kept lines of
  the pairs that ended and runs only the rest, also after a run that reached "done". A pair that
  is not downloaded gets no end, so a later run tries the pair again.
- When the keyboard stops during a pair (iOS stopped the keyboard, or the person closed it), the
  next `duo:speed` runs that pair again. A pair that stopped 2 runs is skipped, and its line
  says so. That line is a result: the pair stops the keyboard.
- While a run is under way, the keyboard keeps one progress line at the end of the result lines
  and types it again every 2 seconds: a bar of the pairs, the pair, the step (the pause, the
  load, or the count of requests done) and the time since the start. The keyboard deletes the
  old line only when the text before the cursor ends with it, so after the person types or moves
  the cursor, the line stays as it is until the run ends.
- `duo:speedreset` and a space deletes the record, so the next `duo:speed` starts at the first
  pair. A change of the pairs or the requests also starts a new record.
- The first line of the run gives llama.cpp's build line, with the processor features of the
  framework (DOTPROD, MATMUL_INT8) and whether it repacks Q4_0 weights. A repacked Q4_0 pair
  copies its weights into the footprint, so its memory line shows the cost.

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
   the system log (subsystem `com.yilongju.duokeyboard`, category `speed`). A run that stopped
   goes on at the next `duo:speed`, and the record stays until `duo:speedreset`.
3. The keyboard has no network code. It reads only the bundle and the shared container.

Why a download: the files of the test models hold about 4.2 GB. In the bundle they would make every
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
  second release in the same process would clash by its symbol names. So the phone run does not
  show whether a larger model meets the target with the faster llama.cpp, and it has no Qwen3
  pair on llama.cpp. The workflow "Model speed" builds the xcframework of b12017 with and without
  the dot-product and i8mm flags, as the step before a phone build with it.
- Core ML has no setting for its count of processor threads. The processor line gives the count
  that each pair used.
- The page cache of iOS cannot be emptied from an app, so a pair cannot start with its weights
  out of memory on purpose. The load line gives the share that was in memory.
- The test does not measure the time between the last letter and the space on the phone. That
  needs typing logs of real use.
- The test does not run the 10-minute run for heat. It records the thermal state of each pair
  and runs the control pair last.
- A base model without fine-tuning gives speed and memory only. Its accuracy cannot be compared
  with the fine-tuned 135M model.
