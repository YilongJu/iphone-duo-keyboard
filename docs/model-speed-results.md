# Results of the speed test of larger language models

`docs/model-speed-design.md` defines the terms, the delay target, the shortlist and the method.
Every number on this page comes from the desktop or from the macOS runner. Each table names its
machine.

## Parts with no result

- **The phone.** No phone run exists yet. The branch is ready for a TestFlight build. So no number
  below is the felt delay on the phone, and no number shows the memory limit of the keyboard.
- **Metal and Core ML on a real GPU.** The runner's GPU is a paravirtual device, so its GPU times
  rank nothing.
- **llama.cpp b12017 on the phone.** The workflow built its xcframework. No phone build links it yet.
- **Time between the last letter and the space.** No typing log of real use exists.
- **The 10-minute run for heat.**

## Summary

1. On the processor, no larger model meets the delay target on either machine. On the macOS
   runner (a virtual Apple M1) the best larger pair is SmolLM2-360M at Q4_0 with llama.cpp
   b12017: its candidate part takes 43.3 ms in the median and 61.7 ms at the 95th percentile.
   The target is 20 ms and 50 ms.
2. The candidate part of the 135M model meets the median target on the runner only with Q4_0 and
   llama.cpp b12017: 21.1 ms in the median and 29.3 ms at the 95th percentile. Today's way, the
   keyboard's file with b4846, takes 58.3 ms and 85.9 ms there.
3. The gain of b12017 comes from the repacking of the weights, and that repacking costs memory
   that the keyboard does not have. On the runner the footprint after the load rises from
   36.5 MB (b4846) to 147.6 MB (b12017, Q4_0, 135M). Without the repacking b12017 takes 61.3 MB
   and is no faster than b4846. The keyboard of build 44 had about 170 MB in all.
4. Every Core ML conversion is correct: with 16-bit weights its top candidate equals llama.cpp's
   at Q8_0 in 98.2% to 99.6% of the requests. Its 4-bit weights agree in 84.6% to 92.0%, about as
   often as llama.cpp's own 4-bit files (84.0% to 97.7%).
5. The open question is the GPU of the phone. Metal (llama.cpp b4846) and Core ML on the GPU both
   run on the phone with the `duo:speed` command. Only a phone run gives their delay and memory.

```mermaid
---
config:
  xyChart:
    showDataLabel: true
---
xychart-beta
    title "Candidate part, median ms, macOS runner (line: target 20 ms)"
    x-axis ["shipped b4846", "135M Q4_0 b12017", "135M Q4_0 b4846", "360M Q4_0 b12017", "Granite Q4_0 b12017", "Qwen2.5 Q4_0 b12017", "Qwen3 Q4_0 b12017"]
    y-axis "ms" 0 --> 90
    bar [58.3, 21.1, 31.5, 43.3, 52.7, 64.3, 81.8]
    line [20, 20, 20, 20, 20, 20, 20]
```

Figure 1. Median of the candidate part of each request on the macOS runner, at 2 threads, with the
reuse of the cache. The larger the model, the longer its candidate part. Only the 135M model at
Q4_0 with b12017 comes near the line, and that pair needs about 110 MB more memory (Table 4).

## Desktop: Intel i9-13900K in WSL, 2 threads

`scripts/model-speed/desktop/jobs/speed.sh` ran each pair alone on the machine, on the 486
requests, in order, with the reuse of the cache. The times are over the 485 requests after the
first. "shipped" is the keyboard's own file. The agreement is with llama.cpp b12017 at Q8_0 on the
same model, and for "shipped" with b4846 on the same file.

Table 1. Desktop, ms.

| run | request mean | request median | request p95 | candidates median | candidates p95 | window mean | first request | agreement |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| shipped.Q4_K_M.b4846 | 60.4 | 58.5 | 83.9 | 43.5 | 63.9 | 16.2 | 56.2 | 100.0% |
| shipped.Q4_K_M.b12017 | 56.9 | 55.4 | 77.7 | 41.6 | 57.2 | 15.2 | 44.0 | 95.7% |
| smollm2-135m.Q4_K_M.b4846 | 58.9 | 57.8 | 81.7 | 42.7 | 61.7 | 15.9 | 73.8 | 91.8% |
| smollm2-135m.Q4_0.b4846 | 46.8 | 45.4 | 64.8 | 34.0 | 48.6 | 12.2 | 36.7 | 86.8% |
| smollm2-135m.Q4_0.b12017 | 39.9 | 38.6 | 53.2 | 28.3 | 39.8 | 10.4 | 34.7 | 89.1% |
| smollm2-135m.Q4_0.b12017-norepack | 54.3 | 53.3 | 74.1 | 40.3 | 54.6 | 14.2 | 40.7 | 89.1% |
| smollm2-360m.Q4_K_M.b4846 | 155.7 | 151.9 | 216.4 | 109.5 | 153.0 | 46.0 | 139.1 | 91.1% |
| smollm2-360m.Q4_0.b4846 | 110.8 | 106.3 | 157.0 | 77.7 | 109.5 | 32.3 | 89.4 | 91.1% |
| smollm2-360m.Q4_0.b12017 | 88.1 | 85.3 | 120.9 | 60.2 | 87.5 | 26.0 | 77.6 | 94.9% |
| granite-4.0-350m-base.Q4_K_M.b4846 | 132.8 | 130.5 | 187.6 | 101.7 | 144.2 | 31.5 | 145.5 | 83.7% |
| granite-4.0-350m-base.Q4_0.b4846 | 109.3 | 108.0 | 149.3 | 83.9 | 118.6 | 24.9 | 95.8 | 83.5% |
| granite-4.0-350m-base.Q4_0.b12017 | 88.1 | 87.8 | 115.7 | 67.1 | 89.9 | 21.7 | 72.0 | 85.8% |
| qwen2.5-0.5b.Q4_K_M.b4846 | 200.2 | 196.7 | 273.7 | 147.0 | 204.5 | 53.4 | 221.5 | 90.1% |
| qwen2.5-0.5b.Q4_0.b4846 | 137.8 | 134.0 | 184.7 | 101.7 | 142.6 | 35.1 | 121.2 | 89.1% |
| qwen2.5-0.5b.Q4_0.b12017 | 118.8 | 115.4 | 164.8 | 87.7 | 122.6 | 30.3 | 108.0 | 92.6% |
| qwen3-0.6b-base.Q4_K_M.b12017 | 156.4 | 154.7 | 203.2 | 113.5 | 155.5 | 41.5 | 168.8 | 96.3% |
| qwen3-0.6b-base.Q4_0.b12017 | 140.2 | 138.0 | 192.1 | 104.0 | 140.9 | 35.6 | 122.9 | 94.9% |

On the desktop the larger models take 1.5 to 3.4 times the time of the keyboard's file. The more
parameters a model has, the longer its request. Q4_0 is faster than Q4_K_M in every pair, by 13% to
31%. llama.cpp b4846 cannot load Qwen3: b4846 has no architecture "qwen3", and both Qwen3 runs
ended with "the model did not load". `scripts/model-speed/results/all-runs.md` holds every run,
the Q4_K_M runs of b12017 and the runs without repacking included.

The reuse share is 81.0% to 81.1% in every run. The window part takes about a quarter of the
request time in every pair.

## macOS runner: a virtual Apple M1 with 3 cores, 2 threads

The job `llama-mac` of the workflow "Model speed" (run 43657493075) ran the same requests with
the macOS part of the app's framework (b4846) and with b12017 built on the runner. The runner
shares its machine, so its times move from run to run. Its processor is an ARM processor with the
dot-product instructions, as the phone's, so it ranks the pairs closer to the phone than the
desktop does.

Table 2. macOS runner, ms.

| run | request median | request p95 | candidates median | candidates p95 | window mean | agreement |
| --- | --- | --- | --- | --- | --- | --- |
| shipped.Q4_K_M.b4846 | 77.4 | 120.7 | 58.3 | 85.9 | 21.9 | 99.6% |
| shipped.Q4_K_M.b12017 | 70.1 | 105.4 | 52.7 | 80.0 | 19.8 | 95.3% |
| smollm2-135m.Q4_0.b4846 | 40.8 | 62.9 | 31.5 | 46.5 | 10.5 | 86.6% |
| smollm2-135m.Q4_0.b12017 | 27.9 | 37.7 | 21.1 | 29.3 | 7.1 | 88.7% |
| smollm2-135m.Q4_0.b12017-norepack | 43.1 | 60.5 | 33.5 | 47.2 | 10.7 | 88.9% |
| smollm2-360m.Q4_0.b4846 | 95.5 | 149.6 | 72.9 | 106.7 | 27.4 | 90.5% |
| smollm2-360m.Q4_0.b12017 | 58.7 | 84.7 | 43.3 | 61.7 | 16.9 | 94.4% |
| granite-4.0-350m-base.Q4_0.b4846 | 121.3 | 173.8 | 99.9 | 142.1 | 23.6 | 84.0% |
| granite-4.0-350m-base.Q4_0.b12017 | 67.0 | 93.4 | 52.7 | 75.4 | 15.1 | 85.0% |
| qwen2.5-0.5b.Q4_0.b4846 | 127.6 | 185.8 | 100.3 | 139.4 | 31.6 | 89.1% |
| qwen2.5-0.5b.Q4_0.b12017 | 82.8 | 123.1 | 64.3 | 97.0 | 19.6 | 92.6% |
| qwen3-0.6b-base.Q4_0.b12017 | 104.8 | 150.0 | 81.8 | 118.8 | 24.7 | 94.0% |
| qwen3-0.6b-base.Q4_K_M.b12017 | 132.7 | 186.8 | 100.9 | 146.7 | 33.0 | 96.1% |

On the ARM runner b12017 at Q4_0 takes 31% to 46% less time than b4846 at Q4_0. Without its
repacking b12017 takes about as long as b4846. The GPU runs of the keyboard's file took 211 to
216 ms in the median on the paravirtual GPU, about three times the processor, and they say
nothing about the phone's GPU.

Table 3. Footprint of the process on the macOS runner, MB, right after the load and the highest
during the requests.

| model and type | b4846 | b12017 | b12017 without repacking |
| --- | --- | --- | --- |
| shipped, Q4_K_M | 36.5, 55.8 | 122.3, 142.1 | not run |
| SmolLM2-135M, Q4_0 | 36.5, 54.7 | 147.6, 169.5 | 61.3, 83.1 |
| SmolLM2-360M, Q4_0 | 45.3, 69.3 | 287.1, 312.1 | 70.3, 95.3 |
| Granite-4.0-350M, Q4_0 | 55.8, 85.9 | 294.2, 327.2 | 80.3, 113.5 |
| Qwen2.5-0.5B, Q4_0 | 61.1, 96.4 | 418.4, 455.0 | 88.4, 125.0 |
| Qwen3-0.6B, Q4_0 | does not load | 497.3, 547.7 | 138.6, 189.2 |

The repacking copies the weights into memory of the process, so the footprint grows with the
model. b4846 reads the weights from the mapped file, so its footprint stays near the cache and the
buffers of the scores. The more parameters, the larger the gap. On the phone the keyboard had
about 114 MB to spare after its load on build 44, so every repacked b12017 pair would pass the
limit unless the phone counts this memory in another way.

### Core ML on the macOS runner

The `coreml` jobs of run 43657493075 converted each model with coremltools 9.0 and ran it with
`coremltools` from Python, through the window rules of the keyboard. The runner has no Neural
Engine and a paravirtual GPU. The times hold the cost of the Python calls, so they rank the models
and do not show the speed of Core ML.

Table 4. Core ML on the macOS runner: agreement with llama.cpp at Q8_0, candidate part median in
ms, and the size of the compiled 4-bit model.

| model | 16-bit, processor | 4-bit, processor | 4-bit, "CPU and GPU" | 4-bit candidates median | 4-bit compiled size |
| --- | --- | --- | --- | --- | --- |
| SmolLM2-135M | 98.4% | 91.6% | 91.6% | 59.9 | 73 MB |
| SmolLM2-360M | 98.2% | 89.7% | 89.7% | 126.0 | 195 MB |
| Granite-4.0-350M | 99.0% | 84.6% | 84.6% | 122.3 | 190 MB |
| Qwen2.5-0.5B | 98.2% | 89.9% | 89.9% | 127.7 | 266 MB |
| Qwen3-0.6B | 99.6% | 92.0% | 92.0% | 351.2 | 321 MB |

Python crashed inside Core ML in the check of the 4-bit Qwen2.5 model in run 43661294275 (twice,
"Bus error: 10" and "Segmentation fault: 11") and in run 43665575923 ("Segmentation fault: 11"
in the "CPU and GPU" check), and passed in run 43657493075. The other four models passed every
check. The phone run puts this pair last, because a crash in the keyboard ends the run.

The 16-bit models agree with llama.cpp in 98.2% or more, so each conversion is correct. The
4-bit models lose about as much agreement as the 4-bit files of llama.cpp. The processor and the
"CPU and GPU" runs give the same numbers, so Core ML ran the "CPU and GPU" model on the processor
of the runner.

The PyTorch model behind each conversion (`scripts/model-speed/coreml/check_torch.py`, 32-bit,
on the desktop) agrees with llama.cpp at Q8_0 in 97.9% to 99.6% of the requests, with a median
difference of 0.024 to 0.048 in the two numbers.

## Tokens per request

Table 5. Tokens of the speed requests and of the Chinese texts of `pinyin.dev.jsonl`, from the
tokenizer of llama.cpp on the desktop.

| model | context tokens per request | tokens per candidate | English characters per token | Chinese characters per token |
| --- | --- | --- | --- | --- |
| SmolLM2-135M and 360M | 45.2 | 2.17 | 4.36 | 0.53 |
| Granite-4.0-350M | 43.0 | 2.11 | 4.58 | 0.76 |
| Qwen2.5-0.5B and Qwen3-0.6B | 43.0 | 2.11 | 4.57 | 1.56 |

The English requests take about the same tokens under every tokenizer. Chinese text takes about
three times fewer tokens under the Qwen tokenizer than under SmolLM2's.

## The simulator

The unit test `testTheSpeedTestRunsEveryPairAndPrintsEveryLine` ran the `duo:speed` test in the
simulator of run 43688643199 (commit 8ce3ac1), with the Core ML model of SmolLM2-135M in place.
The simulator shares the processor of the runner and has no memory limit, so its times say
nothing about the phone.

Table 6. The pairs that ran in the simulator.

| pair | candidates median | request median | reuse | agreement |
| --- | --- | --- | --- | --- |
| shipped, llama.cpp b4846, processor | 82.4 ms | 110.9 ms | 14,918 of 18,403 | 484 of 486 |
| SmolLM2-135M Core ML 4-bit, CPU and GPU | 138.9 ms | 224.3 ms | 14,918 of 18,403 | 446 of 486 |
| SmolLM2-135M Core ML 4-bit, all units | 119.9 ms | 192.3 ms | 14,918 of 18,403 | 446 of 486 |

The Swift code of the Core ML route keeps the same context tokens from the cache as the C scorer,
14,918 of 18,403, and agrees with llama.cpp at Q8_0 in 91.8% of the requests, close to the 91.6%
of the Python check. The two Metal pairs of the keyboard's file did not load in the simulator:
"llama_model_load_from_file_impl: failed to load model". Only the phone shows whether Metal loads
there.

## The keyboard's normal autocorrection

`scripts/model-speed/compare_keyboard_runs.py` compared the artifact "keyboard" of run
43688643199 (commit 8ce3ac1) with that of run 43625399707 on `engine/kv-reuse`, case by case. All
14 case files hold the same cases with the same outputs: 54,744 cases, 0 differ. This covers the
outputs with the model and with the engine alone, the traces with every model number, and the
Pinyin cases. The re-ranker changed the same choices in both runs: 839 of 6,234, 60 of 1,826 and
526 of 6,566. Every unit test of run 43688643199 passed.

## What the phone run must show

For each pair, from the lines of `duo:speed`:

1. The felt delay: the candidate part's median of 20 ms or less and 95th percentile of 50 ms or
   less. This decides whether the context part may run before the space press.
2. The request time, for the case that the whole request runs at the space.
3. The footprint after the load and the least memory still allowed. A pair that leaves less than
   about 20 MB is not usable in the keyboard.
4. The agreement: about 85% or more for a 4-bit pair, and 100% for the keyboard's file on the
   processor. A much lower number means a broken conversion or a broken runtime.
5. For Metal, whether the pair loads in the keyboard at all, its first request (the Metal library
   compiles at the first load), and the footprint with and without the residency set.

## Steps on the phone

1. Before the first TestFlight build of this branch, on developer.apple.com, open Identifiers,
   create the App Group `group.com.yilongju.duokeyboard`, and select it under App Groups for both
   App IDs, `com.yilongju.duokeyboard` and `com.yilongju.duokeyboard.keyboard`.
2. Start the TestFlight workflow on `engine/model-speed` and install the build.
3. Open the Duo Keyboard app. Under "Speed test models", tap each download button. Each line of
   the status says when a file is in place. Keep the app open until the last line says "every
   file is in place".
4. Open Notes, choose Duo Keyboard, type `duo:speed` and a space. Keep the keyboard on screen
   until the line that starts with "done" appears. Every pair runs 486 requests, so the whole run
   takes several minutes.
5. Copy the lines from the note and send them back.
