# Reuse of the language model's cache across space presses

## Goal

Each space press of an English correction asks the language model to score the engine's readings.
Today the scorer reads the whole context again at every request. Most presses share a long start of
text with the press before. This page defines four ways to keep the model's cache between requests,
the replay that measures them, and the rule that picks one for the keyboard. The rule was written
and committed before the accuracy numbers of approaches C, D and E were read.

The keyboard's time is about 110 ms per space press on the phone, and the user calls it fine. So
a faster approach ships only if it keeps the accuracy.

## Glossary

| Term | Meaning |
| --- | --- |
| cache | llama.cpp's stored keys and values of the tokens the model read (its KV cache). Each token's keys and values depend on that token, its position and the tokens before it. |
| context | The text the model reads before the candidates: `LanguageModelPrompt.make` or `makeStock` in `Shared/EnglishReranking.swift`. |
| window | The start token and the last tokens of the context, at most 96 (`DUO_LM_MAX_CONTEXT_TOKENS`), at positions 0 to 96. The model reads the window. |
| request | One call of `duo_lm_scorer_score`: one context and 1 to 8 candidates. |
| correction | One space press whose typed span has more than one engine reading. A correction makes one request in the typed format, and a second request in the stock format when the apostrophe step finds a twin. |
| decision | The reading that a correction shows. |
| full read | A request that clears the cache and reads its whole window. |
| kept tokens | The tokens of a window that the cache already holds at the right positions, so the model does not read them again. |
| reuse share | Kept tokens divided by window tokens, summed over the requests. |
| call | One `llama_decode` call: at most 31 tokens (`CALL_TOKENS`). |
| slot | One stored window in the cache, in its own llama.cpp sequence. |
| fresh read | A full read of the same window and candidates in a second llama.cpp state, for the check. |
| replay | The typing of the replay documents through the keyboard's rules and the scorer, defined below. |

## How the scorer reads a request today (approach A)

`LanguageModel/duo_lm_scorer.c` tokenizes the context and keeps the start token and the last 96
tokens. It clears the cache. It reads the window in calls of at most 31 tokens, with call sizes that
differ by one token at most (`call_size`). It copies sequence 0 to sequences 1 to 8 and reads the
candidates, one sequence each.

The typed format puts the typed span at the end of the context, as in `How much | sutar |`. At the
next press the text before the span has grown by the corrected word. So the shared start of two
requests ends where the earlier span began. The tokens after it differ.

A correction with a twin makes a second request in the stock format, which is the text before the
span alone. That text is a start of the typed context of the same press, while the context holds
96 tokens or fewer.

## The approaches

### B. Exact prefix reuse

The cache keeps the window of the last request. A new request finds the longest start that its
window shares with the stored window, token by token. The scorer removes the candidate sequences
and the stored tokens after that start (`llama_kv_cache_seq_rm`). The model then reads only the
window tokens after the shared start.

The start token at position 0 is the same in every window. When the 96-token window has moved, the
token at position 1 differs, so B keeps only the start token. That is a full read.

Each kept token has the same token, position and tokens before it as in a full read. Only the call
boundaries change. llama.cpp b4846 computes a row of a product the same way for any call of 2 or
more tokens on the x86 and macOS processors of the agreement check (`scripts/lm-keyboard/README.md`,
Table 3 and the sweep of 31-token and 256-token calls). So B should give the numbers of A.

### C. B plus a shifted window

When the window has moved forward by d tokens, the scorer removes the stored tokens at positions 1
to d and moves the later tokens back by d positions (`llama_kv_cache_seq_rm` and
`llama_kv_cache_seq_add`, as the context shift of llama.cpp does). llama.cpp then turns the stored
keys to their new positions. The kept keys were computed with the dropped tokens in view, so the
numbers differ from A. When the window does not move, C equals B.

### D. Anchored window

While the context holds 96 tokens or fewer, the window is the whole context, as in A. When the
context holds more, the window starts at an anchor, a fixed token of the context:

1. The anchor of the stored slot stays while the new context still holds the stored context's tokens
   up to the anchor and one token after it, and the window from the anchor holds 96 tokens or fewer.
2. Otherwise the anchor moves to the last 64 tokens of the context (`DUO_LM_ANCHOR_REFILL_TOKENS`).

The anchor rule was chosen before any measurement. Sixty-four tokens keep two thirds of the window
that the model was tuned with. The other 32 tokens give room for about 20 more space presses before
the anchor moves again, at about 1.5 tokens per word. D changes what the model reads, because the
window holds 64 to 96 tokens of context where A holds 96.

### E. Two slots

The scorer keeps two stored windows. A request takes the slot that keeps the most tokens. When no
slot keeps more than the start token, the slot that waited longer takes it, an empty slot first.
E combines with B, C or D.

Only one window is in the cache at a time, in sequence 0. The other waits in memory as a copy of
its keys and values (`llama_state_seq_get_data`). When a request takes the other slot, the scorer
saves the window in the cache, clears the cache and puts the other window back
(`llama_state_seq_set_data`). The cells of the window then come first and in the order of their
positions, as after a full read. llama.cpp b4846 adds up the attention values over the cells in
the order of the cells, in half precision. Two windows side by side in the cache put a candidate's
cells before some cells of its window, and that gave numbers up to 0.094 away from a full read in
`scripts/kv-reuse/cache_test.c`. A saved window of 97 tokens takes about 2.2 MB of memory, and the
cache keeps its size of 512 cells (`CONTEXT_SIZE`).

### Calls of one token

llama.cpp b4846 computes a call of one token with other code than a call of two or more tokens, and
the two give other last bits. With reuse, the new part of a window is often a few tokens. So a
request with reuse reads at least the last two tokens of its window (`MIN_UNREAD_TOKENS`). Its last
window call then has two tokens or more, as in a full read. A window of the start token alone, the
stock prompt of an empty field, is a call of one token in a full read too, so the slot keeps
nothing of it. The replay also measures a build with
`MIN_UNREAD_TOKENS` 1, to show the effect of calls of one token.

A second way is to read the new window tokens and the candidates in one call. That needs calls of
more than 31 tokens or a token in nine sequences at once. The replay measures the time of the window
calls and the candidate calls apart. The results page states which way the keyboard uses.

## Events of the keyboard

The cache never gives a score for text that differs from the current context, because the scorer
compares tokens. Each request tokenizes its context and compares the window, token by token, with
the stored window. A stored token counts only when it and every token before it are equal. So no
event of the keyboard needs a hook:

| Event | What the scorer sees |
| --- | --- |
| correction of the previous word, delete, cursor move, paste | another context; the shared start ends at the first changed token |
| field change | another context; usually only the start token is shared |
| keyboard reload, memory warning | a new scorer with an empty cache |
| Chinese mode | no request; the next English request compares tokens as usual |
| a call of the model that fails | the scorer clears the cache and marks every slot empty, and the request returns the error |

`duo_lm_scorer_set_check` turns on a check for tests and the replay. After each request the scorer
reads the same window and candidates from an empty cache in a second llama.cpp state and compares
the numbers.

## The replay

The replay types documents in order through `scripts/kv-reuse/replay.py`. The typing rules are the
Python copy of the keyboard in `scripts/lm-rerank/rerank.py`, which builds the same requests as the
Swift code in 14,626 of 14,626 corrections (`scripts/lm-keyboard/README.md`, Table 2). Each
correction asks the scorer as the keyboard does: the typed request, then the stock request when the
apostrophe step finds a twin. The replay keeps no table of earlier answers.

The documents, in this order:

1. The dev cases of `english.dev.jsonl`, `english-symbols.dev.jsonl` and `english-domain.dev.jsonl`,
   each typed in its own field after its context, in file order.
2. The everyday stream of `scripts/lm-domain`: the 1,300 sentences of `cases.stream.select.jsonl`.
3. The technical and the written streams of `english-domain-stream.dev.jsonl`: 1,000 and 300
   sentences.

A stream is running text: 10 sentences in order per field. Each sentence gets a capital first
letter and a period after it, unless it ends with a period, a question mark or an exclamation mark.
No held-out set is read.

The replay runs at 2 threads on the local PC (Intel i9-13900K, WSL), with the Linux build of
`duo_lm_scorer.c` against llama.cpp b4846 and the shipped file
`smollm2-lora-domain-s100-seed1.Q4_K_M.gguf`.

### Measures

1. Accuracy, one replay per approach. Each correction's decision depends on the earlier decisions,
   as in the keyboard. A decision changes when the decision at the same document and correction
   number differs from A, or when only one of the two replays has that correction. The six dev
   counts are the right cases of the groups clean, letter slips, space slips, symbol slips and
   clean symbols, and of all 6,799 cases of the first two case files. The work area count is the
   right cases of the 7,137 cases of `english-domain.dev.jsonl`.
2. Speed. The requests of A's replay go in order through each approach, one approach at a time,
   with nothing else running. Per request the program records the window tokens, the kept tokens,
   the time of the window calls, the time of the candidate calls and the whole time. The results
   give the mean, the median and the 95th percentile.
3. Numbers. The same pass gives each approach's numbers on A's requests, compared with A's numbers.

## Selection rule

Pick the fastest approach, by the mean time per request of the speed pass, whose decisions on the
replay differ from A in at most 0.1% of A's corrections, and whose six dev counts and work area
count are each no lower than A's. Approaches C, D and E (with B, C or D) compete first. If none of
them qualifies, pick B if it qualifies. If nothing qualifies, keep A and report.

## Agreement with lm_score

The workflow "Language model in the keyboard" compares `scorer_cli` with `lm_score` on every distinct
request of the harness, byte for byte, on the x86 and the macOS runners. That check stays as it is,
for full reads. A second step runs `scorer_cli` with the chosen reuse mode on the same requests in
order, so consecutive requests share their starts, and compares it with `lm_score` too.
