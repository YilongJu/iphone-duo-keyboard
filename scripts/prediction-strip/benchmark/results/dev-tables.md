## text sets

| Set | Sentences | Chunks | Plain words | Strip states | Key presses without the strip |
| --- | --- | --- | --- | --- | --- |
| technical | 1,000 | 16,166 | 15,567 | 76,078 | 97,855 |
| everyday | 1,000 | 7,040 | 7,040 | 28,606 | 35,758 |
| mobile | 954 | 9,286 | 9,126 | 37,156 | 47,255 |

## settings of M

| Model file | Form rule | First word none | First word engine | First word model |
| --- | --- | --- | --- | --- |
| shipped fine-tune | typed | 50.3 (50.0 to 50.6) | 50.4 (50.1 to 50.7) | 49.1 (48.8 to 49.4) |
| shipped fine-tune | model | 50.0 (49.7 to 50.3) | 50.1 (49.8 to 50.4) | 48.7 (48.4 to 49.1) |
| shipped fine-tune | typed_built | 50.1 (49.8 to 50.4) | 50.2 (49.9 to 50.5) | 48.9 (48.6 to 49.2) |
| shipped fine-tune | model_built | 50.0 (49.7 to 50.3) | 50.1 (49.8 to 50.4) | 48.8 (48.4 to 49.1) |
| SmolLM2-135M | typed | 52.2 (51.9 to 52.6) | 52.3 (52.0 to 52.7) | 51.1 (50.8 to 51.5) |
| SmolLM2-135M | model | 51.7 (51.4 to 52.0) | 51.8 (51.5 to 52.1) | 50.6 (50.2 to 50.9) |
| SmolLM2-135M | typed_built | 52.1 (51.8 to 52.4) | 52.2 (51.9 to 52.5) | 50.9 (50.6 to 51.3) |
| SmolLM2-135M | model_built | 51.7 (51.4 to 52.0) | 51.8 (51.5 to 52.1) | 50.6 (50.3 to 50.9) |
| SmolLM2-360M | typed | 52.6 (52.3 to 52.9) | 52.7 (52.4 to 53.0) | 52.2 (51.9 to 52.6) |
| SmolLM2-360M | model | 52.3 (51.9 to 52.6) | 52.4 (52.0 to 52.7) | 51.9 (51.5 to 52.2) |
| SmolLM2-360M | typed_built | 52.6 (52.2 to 52.9) | 52.7 (52.3 to 53.0) | 52.2 (51.8 to 52.5) |
| SmolLM2-360M | model_built | 52.3 (52.0 to 52.6) | 52.4 (52.1 to 52.7) | 51.9 (51.5 to 52.2) |
| Qwen2.5-0.5B | typed | 52.8 (52.5 to 53.1) | 52.9 (52.6 to 53.2) | 52.3 (52.0 to 52.7) |
| Qwen2.5-0.5B | model | 52.0 (51.7 to 52.4) | 52.1 (51.8 to 52.5) | 51.5 (51.2 to 51.9) |
| Qwen2.5-0.5B | typed_built | 52.5 (52.2 to 52.9) | 52.6 (52.3 to 53.0) | 52.1 (51.8 to 52.4) |
| Qwen2.5-0.5B | model_built | 52.0 (51.7 to 52.4) | 52.1 (51.8 to 52.5) | 51.5 (51.2 to 51.9) |

## mix weights

| Model file | Form rule | Weight 0.0 | Weight 0.1 | Weight 0.2 | Weight 0.3 | Weight 0.5 |
| --- | --- | --- | --- | --- | --- | --- |
| shipped fine-tune | typed | 50.4 (50.1 to 50.7) | 51.7 (51.4 to 52.0) | 52.5 (52.2 to 52.8) | 52.8 (52.5 to 53.1) | 52.3 (52.0 to 52.5) |
| shipped fine-tune | model | 50.1 (49.8 to 50.4) | 51.4 (51.1 to 51.7) | 52.2 (51.9 to 52.5) | 52.6 (52.3 to 52.9) | 52.0 (51.7 to 52.3) |
| shipped fine-tune | typed_built | 50.2 (49.9 to 50.5) | 51.5 (51.2 to 51.9) | 52.4 (52.1 to 52.7) | 52.8 (52.5 to 53.1) | 52.2 (51.9 to 52.5) |
| shipped fine-tune | model_built | 50.1 (49.8 to 50.4) | 51.4 (51.1 to 51.7) | 52.2 (51.9 to 52.5) | 52.6 (52.3 to 52.9) | 52.0 (51.7 to 52.3) |
| SmolLM2-135M | typed | 52.3 (52.0 to 52.7) | 52.4 (52.1 to 52.7) | 52.2 (51.9 to 52.5) | 51.9 (51.6 to 52.2) | 50.7 (50.4 to 51.0) |
| SmolLM2-135M | model | 51.8 (51.5 to 52.1) | 51.9 (51.6 to 52.2) | 51.7 (51.4 to 52.0) | 51.4 (51.1 to 51.7) | 50.2 (49.9 to 50.5) |
| SmolLM2-135M | typed_built | 52.2 (51.9 to 52.5) | 52.3 (52.0 to 52.6) | 52.1 (51.8 to 52.4) | 51.8 (51.5 to 52.1) | 50.7 (50.4 to 51.0) |
| SmolLM2-135M | model_built | 51.8 (51.5 to 52.1) | 51.9 (51.6 to 52.2) | 51.7 (51.4 to 52.0) | 51.4 (51.1 to 51.7) | 50.2 (49.9 to 50.6) |
| SmolLM2-360M | typed | 52.7 (52.4 to 53.0) | 52.8 (52.5 to 53.1) | 52.7 (52.4 to 53.0) | 52.3 (52.0 to 52.6) | 51.1 (50.8 to 51.4) |
| SmolLM2-360M | model | 52.4 (52.0 to 52.7) | 52.5 (52.2 to 52.8) | 52.4 (52.0 to 52.7) | 52.0 (51.7 to 52.3) | 50.8 (50.4 to 51.1) |
| SmolLM2-360M | typed_built | 52.7 (52.3 to 53.0) | 52.8 (52.5 to 53.1) | 52.7 (52.3 to 53.0) | 52.3 (52.0 to 52.6) | 51.1 (50.8 to 51.4) |
| SmolLM2-360M | model_built | 52.4 (52.1 to 52.7) | 52.5 (52.2 to 52.8) | 52.4 (52.1 to 52.7) | 52.0 (51.7 to 52.3) | 50.8 (50.5 to 51.1) |
| Qwen2.5-0.5B | typed | 52.9 (52.6 to 53.2) | 53.1 (52.7 to 53.4) | 53.0 (52.7 to 53.3) | 52.7 (52.3 to 52.9) | 51.4 (51.1 to 51.7) |
| Qwen2.5-0.5B | model | 52.1 (51.8 to 52.5) | 52.3 (51.9 to 52.6) | 52.2 (51.9 to 52.5) | 51.9 (51.6 to 52.2) | 50.7 (50.3 to 51.0) |
| Qwen2.5-0.5B | typed_built | 52.6 (52.3 to 53.0) | 52.8 (52.5 to 53.1) | 52.8 (52.5 to 53.1) | 52.5 (52.2 to 52.8) | 51.3 (51.0 to 51.6) |
| Qwen2.5-0.5B | model_built | 52.1 (51.8 to 52.5) | 52.3 (51.9 to 52.6) | 52.2 (51.9 to 52.6) | 51.9 (51.6 to 52.2) | 50.7 (50.4 to 51.0) |

## word orders

| Word order | Strip of 3, mean | technical | everyday | mobile | Strip of 6, mean | Strip of 10, mean |
| --- | --- | --- | --- | --- | --- | --- |
| M+E 0.1, Qwen2.5-0.5B, typed, engine | 53.1 (52.7 to 53.4) | 55.3 (54.7 to 55.8) | 53.0 (52.5 to 53.4) | 51.0 (50.3 to 51.5) | 57.8 (57.5 to 58.0) | 60.7 (60.4 to 61.0) |
| M, Qwen2.5-0.5B, typed, engine | 52.9 (52.6 to 53.2) | 55.2 (54.7 to 55.8) | 52.8 (52.3 to 53.3) | 50.7 (50.0 to 51.3) | 57.5 (57.3 to 57.8) | 60.4 (60.2 to 60.7) |
| M+E 0.3, shipped fine-tune, typed, engine | 52.8 (52.5 to 53.1) | 52.8 (52.2 to 53.3) | 55.1 (54.6 to 55.6) | 50.7 (50.0 to 51.2) | 57.7 (57.4 to 58.0) | 60.7 (60.4 to 60.9) |
| M+E 0.1, SmolLM2-360M, typed, engine | 52.8 (52.5 to 53.1) | 55.3 (54.8 to 55.9) | 52.1 (51.6 to 52.7) | 51.0 (50.4 to 51.6) | 57.5 (57.2 to 57.8) | 60.5 (60.2 to 60.8) |
| M, SmolLM2-360M, typed, engine | 52.7 (52.4 to 53.0) | 55.4 (54.8 to 55.9) | 52.1 (51.5 to 52.6) | 50.7 (50.1 to 51.3) | 57.4 (57.0 to 57.7) | 60.3 (60.0 to 60.6) |
| M+E 0.1, SmolLM2-135M, typed, engine | 52.4 (52.1 to 52.7) | 52.8 (52.2 to 53.3) | 53.8 (53.3 to 54.3) | 50.6 (50.0 to 51.3) | 57.2 (56.9 to 57.5) | 60.2 (59.9 to 60.6) |
| M, SmolLM2-135M, typed, engine | 52.3 (52.0 to 52.7) | 52.7 (52.1 to 53.2) | 53.9 (53.4 to 54.4) | 50.4 (49.8 to 51.0) | 57.1 (56.8 to 57.4) | 60.1 (59.8 to 60.4) |
| M+R, shipped fine-tune, typed, engine | 50.7 (50.4 to 51.0) | 50.7 (50.2 to 51.3) | 53.7 (53.1 to 54.2) | 47.6 (47.0 to 48.2) | 55.7 (55.4 to 56.0) | 58.7 (58.4 to 59.0) |
| M, shipped fine-tune, typed, engine | 50.4 (50.1 to 50.7) | 50.4 (49.8 to 51.0) | 53.4 (52.8 to 53.9) | 47.5 (46.8 to 48.1) | 55.4 (55.1 to 55.7) | 58.7 (58.4 to 59.0) |
| E | 42.4 (42.1 to 42.7) | 42.3 (41.8 to 42.7) | 41.6 (41.1 to 42.1) | 43.3 (42.7 to 43.8) | 48.3 (48.0 to 48.6) | 52.1 (51.8 to 52.4) |

## differences to E

| Word order | Mean of the sets | technical | everyday | mobile |
| --- | --- | --- | --- | --- |
| M+E 0.1, Qwen2.5-0.5B, typed, engine | +10.67 (+10.45 to +10.89) | +12.99 (+12.65 to +13.36) | +11.35 (+10.93 to +11.80) | +7.68 (+7.32 to +8.00) |
| M, Qwen2.5-0.5B, typed, engine | +10.53 (+10.30 to +10.75) | +12.97 (+12.61 to +13.35) | +11.23 (+10.79 to +11.73) | +7.39 (+7.02 to +7.74) |
| M+E 0.3, shipped fine-tune, typed, engine | +10.45 (+10.23 to +10.67) | +10.51 (+10.15 to +10.90) | +13.45 (+12.99 to +13.88) | +7.38 (+7.02 to +7.76) |
| M+E 0.1, SmolLM2-360M, typed, engine | +10.45 (+10.21 to +10.67) | +13.07 (+12.72 to +13.43) | +10.52 (+10.09 to +10.95) | +7.75 (+7.39 to +8.09) |
| M, SmolLM2-360M, typed, engine | +10.33 (+10.09 to +10.58) | +13.09 (+12.74 to +13.48) | +10.48 (+10.02 to +10.92) | +7.43 (+7.06 to +7.79) |
| M+E 0.1, SmolLM2-135M, typed, engine | +10.04 (+9.82 to +10.25) | +10.52 (+10.17 to +10.89) | +12.22 (+11.80 to +12.62) | +7.37 (+7.06 to +7.71) |
| M, SmolLM2-135M, typed, engine | +9.94 (+9.71 to +10.17) | +10.40 (+10.03 to +10.79) | +12.29 (+11.84 to +12.70) | +7.15 (+6.82 to +7.49) |
| M+R, shipped fine-tune, typed, engine | +8.29 (+8.00 to +8.56) | +8.47 (+8.04 to +8.93) | +12.05 (+11.52 to +12.56) | +4.36 (+3.92 to +4.81) |
| M, shipped fine-tune, typed, engine | +8.02 (+7.75 to +8.29) | +8.13 (+7.69 to +8.58) | +11.75 (+11.22 to +12.27) | +4.18 (+3.76 to +4.64) |

## decision rule

| Step | File size, MB | Model reads | Word order of the cost class with the most saved key presses | Saved key presses | Difference to the choice so far | Takes the place |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 105.5 | 1 per word | M+E 0.3, shipped fine-tune, typed, engine | 52.83 | +10.45 (+10.23 to +10.67) against E | yes |
| 2 | 105.5 | 1 per word and 1 per strip state | M+R, shipped fine-tune, typed, engine | 50.68 | -2.16 (-2.29 to -2.04) against M+E 0.3, shipped fine-tune, typed, engine | no |
| 3 | 270.6 | 1 per word | M+E 0.1, SmolLM2-360M, typed, engine | 52.83 | -0.00 (-0.18 to +0.15) against M+E 0.3, shipped fine-tune, typed, engine | no |
| 4 | 397.8 | 1 per word | M+E 0.1, Qwen2.5-0.5B, typed, engine | 53.06 | +0.22 (+0.08 to +0.38) against M+E 0.3, shipped fine-tune, typed, engine | no |

## settings around the choice

| Changed setting | Word order | Saved key presses | Difference to the choice |
| --- | --- | --- | --- |
| form rule | M+E 0.3, shipped fine-tune, model, engine | 52.57 | -0.26 (-0.31 to -0.22) |
| form rule | M+E 0.3, shipped fine-tune, typed_built, engine | 52.77 | -0.06 (-0.08 to -0.05) |
| form rule | M+E 0.3, shipped fine-tune, model_built, engine | 52.58 | -0.25 (-0.30 to -0.21) |
| first word | M+E 0.3, shipped fine-tune, typed, none | 52.73 | -0.10 (-0.12 to -0.08) |
| first word | M+E 0.3, shipped fine-tune, typed, model | 51.53 | -1.30 (-1.37 to -1.22) |
| mix weight | M, shipped fine-tune, typed, engine | 50.41 | -2.43 (-2.54 to -2.31) |
| mix weight | M+E 0.1, shipped fine-tune, typed, engine | 51.68 | -1.15 (-1.24 to -1.06) |
| mix weight | M+E 0.2, shipped fine-tune, typed, engine | 52.45 | -0.38 (-0.44 to -0.32) |
| mix weight | M+E 0.5, shipped fine-tune, typed, engine | 52.25 | -0.58 (-0.67 to -0.49) |
| model file | M+E 0.1, SmolLM2-135M, typed, engine | 52.42 | -0.41 (-0.54 to -0.28) |

## second typist

| Word order | Strip of 3 | Strip of 6 | Strip of 10 |
| --- | --- | --- | --- |
| M+E 0.1, Qwen2.5-0.5B, typed, engine | 50.5 (50.1 to 50.8) | 55.7 (55.4 to 56.0) | 58.6 (58.3 to 59.0) |
| M, Qwen2.5-0.5B, typed, engine | 50.3 (50.0 to 50.7) | 55.4 (55.1 to 55.8) | 58.3 (58.0 to 58.7) |
| M+E 0.3, shipped fine-tune, typed, engine | 50.2 (49.8 to 50.5) | 55.5 (55.2 to 55.9) | 58.5 (58.1 to 58.8) |
| M+E 0.1, SmolLM2-360M, typed, engine | 50.2 (49.9 to 50.6) | 55.4 (55.0 to 55.7) | 58.4 (58.1 to 58.7) |
| M, SmolLM2-360M, typed, engine | 50.1 (49.7 to 50.5) | 55.2 (54.9 to 55.6) | 58.2 (57.9 to 58.5) |
| M+E 0.1, SmolLM2-135M, typed, engine | 49.8 (49.5 to 50.2) | 55.2 (54.8 to 55.5) | 58.2 (57.9 to 58.5) |
| M, SmolLM2-135M, typed, engine | 49.7 (49.4 to 50.1) | 55.1 (54.7 to 55.4) | 58.1 (57.7 to 58.4) |
| M+R, shipped fine-tune, typed, engine | 47.8 (47.5 to 48.2) | 53.2 (52.9 to 53.6) | 56.1 (55.8 to 56.5) |
| M, shipped fine-tune, typed, engine | 47.4 (47.1 to 47.8) | 52.9 (52.6 to 53.3) | 56.1 (55.8 to 56.5) |
| E | 38.8 (38.5 to 39.1) | 45.5 (45.2 to 45.8) | 49.7 (49.4 to 50.0) |

## found share

| Word order | Set | 0 typed letters | 1 typed letters | 2 typed letters | 3 typed letters |
| --- | --- | --- | --- | --- | --- |
| E | technical | 17.4 | 45.2 | 55.3 | 69.5 |
| E | everyday | 15.2 | 48.8 | 60.8 | 79.8 |
| E | mobile | 17.3 | 53.1 | 65.2 | 79.6 |
| M+E 0.3, shipped fine-tune, typed, engine | technical | 30.5 | 63.1 | 74.8 | 84.2 |
| M+E 0.3, shipped fine-tune, typed, engine | everyday | 34.9 | 71.6 | 82.6 | 93.0 |
| M+E 0.3, shipped fine-tune, typed, engine | mobile | 29.7 | 64.6 | 77.1 | 86.4 |
| M, shipped fine-tune, typed, engine | technical | 25.4 | 57.8 | 71.5 | 82.4 |
| M, shipped fine-tune, typed, engine | everyday | 30.4 | 68.4 | 81.4 | 92.5 |
| M, shipped fine-tune, typed, engine | mobile | 24.1 | 58.4 | 73.0 | 84.2 |
| M, SmolLM2-135M, typed, engine | technical | 32.0 | 63.1 | 73.6 | 83.3 |
| M, SmolLM2-135M, typed, engine | everyday | 34.6 | 68.5 | 80.4 | 91.4 |
| M, SmolLM2-135M, typed, engine | mobile | 30.2 | 64.5 | 75.7 | 85.5 |
| M, SmolLM2-360M, typed, engine | technical | 35.7 | 68.0 | 79.0 | 87.1 |
| M, SmolLM2-360M, typed, engine | everyday | 33.4 | 65.4 | 76.8 | 88.6 |
| M, SmolLM2-360M, typed, engine | mobile | 31.1 | 65.2 | 75.6 | 85.6 |
| M, Qwen2.5-0.5B, typed, engine | technical | 35.3 | 68.0 | 78.9 | 87.1 |
| M, Qwen2.5-0.5B, typed, engine | everyday | 33.7 | 66.7 | 77.9 | 90.7 |
| M, Qwen2.5-0.5B, typed, engine | mobile | 30.8 | 64.3 | 75.8 | 86.5 |
| M+R, shipped fine-tune, typed, engine | technical | 26.0 | 58.4 | 71.9 | 82.6 |
| M+R, shipped fine-tune, typed, engine | everyday | 30.8 | 68.9 | 81.9 | 93.0 |
| M+R, shipped fine-tune, typed, engine | mobile | 24.6 | 58.3 | 73.0 | 84.6 |

## cost

| Model file | Size, MB | PC time of one read, ms: median, 95th percentile | PC time of one request of M+R, ms: median, 95th percentile |
| --- | --- | --- | --- |
| shipped fine-tune | 105.5 | 26.5, 58.3 | 52.9, 81.8 |
| SmolLM2-135M | 105.5 | 25.6, 52.8 | not run |
| SmolLM2-360M | 270.6 | 58.8, 133.6 | not run |
| Qwen2.5-0.5B | 397.8 | 63.2, 142.3 | not run |

Choice by the decision rule: M+E 0.3, shipped fine-tune, typed, engine (`shipped|typed|engine|0.3`).
