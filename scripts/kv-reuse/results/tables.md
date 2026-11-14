Speed, the requests of every fourth document of A's replay, 2 threads.

| Approach | mean ms | median ms | 95th pct ms | window mean ms | window median ms | candidates mean ms | reuse share |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A no reuse | 123.5 | 106.7 | 224.6 | 79.4 | 60.4 | 43.0 | 0.0% |
| B prefix, 1 slot | 91.3 | 59.5 | 225.0 | 47.6 | 13.9 | 43.2 | 43.4% |
| C shift, 1 slot | 60.0 | 58.3 | 83.7 | 15.8 | 13.9 | 43.7 | 85.2% |
| D anchor, 1 slot | 59.3 | 57.5 | 83.6 | 15.3 | 12.9 | 43.6 | 83.8% |
| BE prefix, 2 slots | 93.1 | 60.9 | 229.7 | 48.2 | 14.3 | 44.0 | 43.5% |
| CE shift, 2 slots | 60.0 | 58.5 | 83.5 | 15.6 | 14.1 | 43.8 | 85.7% |
| DE anchor, 2 slots | 59.1 | 57.4 | 83.1 | 15.0 | 12.7 | 43.4 | 84.0% |
| B1 prefix, 1 slot, calls of one token | 90.4 | 59.2 | 221.3 | 47.0 | 13.7 | 43.0 | 43.5% |
| A-again no reuse, again | 124.5 | 107.2 | 226.4 | 80.2 | 61.3 | 43.3 | 0.0% |

Speed per part, mean ms per request and reuse share.

| Approach | dev | work area dev | everyday stream | technical stream | written stream |
| --- | --- | --- | --- | --- | --- |
| A | 55.9 (0%) | 65.7 (0%) | 124.4 (0%) | 171.7 (0%) | 175.2 (0%) |
| B | 51.3 (23%) | 60.1 (21%) | 59.6 (87%) | 133.0 (34%) | 139.2 (30%) |
| C | 51.8 (23%) | 61.5 (21%) | 58.8 (89%) | 64.0 (91%) | 61.4 (92%) |
| D | 52.0 (23%) | 61.4 (21%) | 59.5 (89%) | 61.9 (90%) | 60.7 (90%) |
| BE | 53.3 (24%) | 62.3 (22%) | 60.7 (87%) | 134.9 (34%) | 141.9 (30%) |
| CE | 53.8 (24%) | 62.7 (22%) | 59.8 (89%) | 62.3 (92%) | 59.8 (92%) |
| DE | 51.5 (24%) | 60.3 (22%) | 58.0 (89%) | 63.2 (90%) | 59.3 (90%) |
| B1 | 51.5 (23%) | 60.7 (21%) | 58.9 (87%) | 130.7 (34%) | 138.3 (30%) |
| A-again | 55.8 (0%) | 65.6 (0%) | 126.3 (0%) | 173.4 (0%) | 176.2 (0%) |

Requests of the speed pass per part: {"dev": 2026, "work area dev": 1639, "everyday stream": 2203, "technical stream": 3729, "written stream": 963}

Accuracy, each approach's own replay.

| Approach | requests | corrections | changed decisions | share | clean | letter_slips | space_slips | symbol_slips | clean_symbols | all 6,799 | work area |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A no reuse | 42390 | 41556 | 0 | 0.000% | 957 | 2052 | 1387 | 1164 | 429 | 6538 | 6619 |
| B prefix, 1 slot | 42390 | 41556 | 0 | 0.000% | 957 | 2052 | 1387 | 1164 | 429 | 6538 | 6619 |
| C shift, 1 slot | 42390 | 41556 | 4 | 0.010% | 957 | 2052 | 1387 | 1164 | 429 | 6538 | 6619 |
| D anchor, 1 slot | 42390 | 41556 | 4 | 0.010% | 957 | 2052 | 1387 | 1164 | 429 | 6538 | 6619 |
| BE prefix, 2 slots | 42390 | 41556 | 0 | 0.000% | 957 | 2052 | 1387 | 1164 | 429 | 6538 | 6619 |
| CE shift, 2 slots | 42390 | 41556 | 4 | 0.010% | 957 | 2052 | 1387 | 1164 | 429 | 6538 | 6619 |
| DE anchor, 2 slots | 42390 | 41556 | 4 | 0.010% | 957 | 2052 | 1387 | 1164 | 429 | 6538 | 6619 |
| B1 prefix, 1 slot, calls of one token | 42390 | 41556 | 0 | 0.000% | 957 | 2052 | 1387 | 1164 | 429 | 6538 | 6619 |

Numbers on A's requests, against A.

| Approach | requests that differ | widest | median of those | decisions that differ |
| --- | --- | --- | --- | --- |
| B | 0 of 10560 | 0 | 0 | 0 |
| C | 2215 of 10560 | 4.9394 | 0.80921 | 1 |
| D | 2218 of 10560 | 6.1896 | 0.769688 | 0 |
| BE | 0 of 10560 | 0 | 0 | 0 |
| CE | 2246 of 10560 | 5.19467 | 0.85107 | 1 |
| DE | 2214 of 10560 | 6.1896 | 0.768819 | 0 |
| B1 | 0 of 10560 | 0 | 0 | 0 |
| A-again | 0 of 10560 | 0 | 0 |  |

Window calls of B by the tokens the model read: median ms.

| tokens read | requests | median ms |
| --- | --- | --- |
| 2 | 948 | 7.04 |
| 3 | 338 | 8.93 |
| 4 | 321 | 9.59 |
| 5 | 3055 | 12.07 |
| 6 | 1076 | 12.90 |
| 7 | 704 | 14.82 |
| 8 | 464 | 15.71 |
| 9 | 323 | 17.62 |
| 10 | 232 | 18.67 |
| 11 | 148 | 20.55 |
| 12 | 142 | 21.71 |
| 13 | 87 | 23.57 |
| 14 | 66 | 24.68 |
| 15 | 44 | 26.84 |
| 16 | 36 | 27.99 |
| 17 | 34 | 29.96 |
| 18 | 25 | 31.25 |
| 21 | 26 | 36.01 |
| 23 | 22 | 39.29 |

Selection: {"qualifies": {"C": true, "D": true, "BE": true, "CE": true, "DE": true, "B": true}, "pick": "DE"}
