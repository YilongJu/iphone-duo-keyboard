Selection sets, right cases and changed words per arm.

| Arm | closed stream, changed of 6,449 words (per 10,000) | open stream, changed of 1,990 words (per 10,000) | clean /973 | clean symbols /429 | letter slips /2,100 | space slips /1,500 | symbol slips /1,197 | apostrophe missing /300 | real word slip /300 | github misspelling /1,500 | lists /751 | github real word /1,000 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `control` | 66 (102.3) | 30 (150.8) | 957 | 427 | 1943 | 1299 | 1131 | 250 | 62 | 1269 | 381 | 31 |
| `ship` | 41 (63.6) | 27 (135.7) | 954 | 427 | 2057 | 1388 | 1165 | 295 | 257 | 1279 | 403 | 388 |
| `smollm2-lora-seed1-calibrated:tuned` | 41 (63.6) | 27 (135.7) | 954 | 427 | 2057 | 1388 | 1165 | 295 | 257 | 1279 | 403 | 388 |
| `smollm2-lora-seed2:tuned` | 28 (43.4) | 22 (110.6) | 951 | 428 | 2052 | 1380 | 1169 | 299 | 264 | 1252 | 378 | 421 |
| `smollm2-lora-seed3:tuned` | 30 (46.5) | 26 (130.7) | 954 | 428 | 2056 | 1388 | 1163 | 298 | 259 | 1279 | 397 | 395 |
| `smollm2-lora-mix-seed1:tuned` | 6 (9.3) | 13 (65.3) | 950 | 428 | 2062 | 1388 | 1164 | 298 | 258 | 1277 | 400 | 413 |
| `smollm2-lora-mix-seed2:tuned` | 3 (4.7) | 8 (40.2) | 946 | 429 | 2053 | 1384 | 1167 | 297 | 259 | 1264 | 397 | 498 |
| `smollm2-lora-mix-seed3:tuned` | 8 (12.4) | 7 (35.2) | 952 | 427 | 2059 | 1387 | 1166 | 295 | 260 | 1291 | 379 | 411 |
| `smollm2-lora-mix-hinge-seed1:tuned` | 3 (4.7) | 2 (10.1) | 957 | 428 | 2055 | 1383 | 1165 | 297 | 250 | 1280 | 381 | 389 |
| `smollm2-full-mix-seed1:tuned` | 7 (10.9) | 7 (35.2) | 952 | 427 | 2053 | 1392 | 1166 | 299 | 256 | 1296 | 394 | 454 |
| `smollm2-lora-clean-seed1:tuned` | 9 (14.0) | 14 (70.4) | 959 | 426 | 2058 | 1390 | 1166 | 298 | 252 | 1278 | 384 | 364 |

Conditions of the pick per arm.

| Arm | 1 fewer changed words on the stream | 2 clean and clean symbols each at least ship | 3 real misspellings at least ship | 4 non-word slips at least ship less 25 | 5 real-word slips keep half of the gain of ship | qualifies |
| --- | --- | --- | --- | --- | --- | --- |
| `smollm2-lora-seed1-calibrated:tuned` | no | yes | yes | yes | yes | no |
| `smollm2-lora-seed2:tuned` | yes | no | no | yes | yes | no |
| `smollm2-lora-seed3:tuned` | yes | yes | no | yes | yes | no |
| `smollm2-lora-mix-seed1:tuned` | yes | no | no | yes | yes | no |
| `smollm2-lora-mix-seed2:tuned` | yes | no | no | yes | yes | no |
| `smollm2-lora-mix-seed3:tuned` | yes | no | no | yes | yes | no |
| `smollm2-lora-mix-hinge-seed1:tuned` | yes | yes | no | yes | yes | no |
| `smollm2-full-mix-seed1:tuned` | yes | no | yes | yes | yes | no |
| `smollm2-lora-clean-seed1:tuned` | yes | no | no | yes | yes | no |

Candidate: None

Dry run of the six replacement conditions on the selection sets. It checks the code, and it decides nothing.

| Arm | 1 | 2 | 3 | 4 | 5 | 6 | changed sentences only ship / only arm | p | non-word difference (interval) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `smollm2-lora-seed1-calibrated:tuned` | no | yes | yes | yes | yes | yes | 0 / 0 | 1 | +0 (+0 to +0) |
| `smollm2-lora-seed2:tuned` | yes | yes | no | yes | no | yes | 24 / 5 | 0.000273 | -5 (-19 to +11) |
| `smollm2-lora-seed3:tuned` | yes | yes | yes | yes | no | yes | 19 / 7 | 0.0145 | +0 (-14 to +15) |
| `smollm2-lora-mix-seed1:tuned` | yes | yes | no | yes | no | yes | 44 / 0 | 5.68e-14 | +7 (-9 to +24) |
| `smollm2-lora-mix-seed2:tuned` | yes | yes | no | yes | no | yes | 49 / 0 | 1.78e-15 | -4 (-19 to +12) |
| `smollm2-lora-mix-seed3:tuned` | yes | yes | no | yes | no | yes | 47 / 1 | 1.74e-13 | +2 (-12 to +17) |
| `smollm2-lora-mix-hinge-seed1:tuned` | yes | yes | yes | yes | no | yes | 52 / 0 | 2.22e-16 | -5 (-21 to +12) |
| `smollm2-full-mix-seed1:tuned` | yes | yes | no | yes | no | yes | 48 / 1 | 8.88e-14 | +5 (-9 to +21) |
| `smollm2-lora-clean-seed1:tuned` | yes | yes | no | yes | no | yes | 42 / 1 | 5e-12 | +7 (-10 to +25) |
