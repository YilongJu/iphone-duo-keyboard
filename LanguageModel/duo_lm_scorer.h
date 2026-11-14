/*
 The language model that re-ranks the English corrections of Duo Keyboard.

 The scorer loads one model through llama.cpp, on the processor only, and keeps it loaded until
 the caller closes it. One request holds a context and 1 to 8 candidate texts. The model reads
 the start token and the context once. Each candidate then follows the context in a sequence of
 its own that shares the stored state of the context, so the context is read once per request.
 With a reuse mode (duo_lm_reuse below) the scorer also keeps the stored state of the context
 between requests, and the model reads only the tokens after the start that a request shares
 with the request before.

 For each candidate the scorer gives two natural logarithms:
   log_probability  the probability of the candidate's tokens right after the context
   space_after      the probability that the token after the candidate starts with a space

 The scorer reads each text exactly as given. The caller builds the context and the candidates,
 with the space between them (LanguageModelPrompt in Shared/EnglishReranking.swift).

 scripts/lm-rerank/lm_score.c gives the same numbers on Linux, where the re-ranking rule was
 tuned. This scorer follows that program in each step that sets a number: the start token, the
 last 96 tokens of the context, the token that takes the place of -1, and the sums over the
 vocabulary. duo_lm_scorer.c names the two steps that differ and why they leave the numbers alone.
 The reuse mode DUO_LM_REUSE_PREFIX changes only the calls in which the model reads the tokens,
 so it keeps those numbers as well (docs/kv-reuse-results.md).
 */
#ifndef DUO_LM_SCORER_H
#define DUO_LM_SCORER_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* The most candidates in one request. */
#define DUO_LM_MAX_CANDIDATES 8
/* The context keeps its last tokens up to this count, after the start token. */
#define DUO_LM_MAX_CONTEXT_TOKENS 96
/* The most tokens of one candidate. */
#define DUO_LM_MAX_CANDIDATE_TOKENS 32
/* Size of an error text buffer that holds every error text of this scorer. */
#define DUO_LM_ERROR_SIZE 256
/* The most cache slots: one stored context per prompt format of the keyboard. */
#define DUO_LM_MAX_SLOTS 2
/* The window of the anchored mode keeps this many tokens of the context when it starts again. */
#define DUO_LM_ANCHOR_REFILL_TOKENS 64

/* How the scorer reuses the cache between requests. The cache is llama.cpp's stored keys and
   values of the tokens the model read (its KV cache). The window is the start token and the
   last tokens of the context that the model reads. docs/kv-reuse-design.md describes each mode.
   DUO_LM_REUSE_NONE     every request clears the cache and reads its whole window.
   DUO_LM_REUSE_PREFIX   the model reads only the tokens after the longest start that the
                         window shares with the cached window. The numbers equal a full read.
   DUO_LM_REUSE_SHIFT    the prefix mode, and when the window moved forward, the cache drops
                         its oldest tokens and moves the others to their new positions. This
                         changes the numbers.
   DUO_LM_REUSE_ANCHOR   the window starts at a fixed token of the context and starts again
                         at the last DUO_LM_ANCHOR_REFILL_TOKENS tokens only when the context
                         outgrows it. This changes what the model reads. */
typedef enum {
    DUO_LM_REUSE_NONE = 0,
    DUO_LM_REUSE_PREFIX = 1,
    DUO_LM_REUSE_SHIFT = 2,
    DUO_LM_REUSE_ANCHOR = 3,
} duo_lm_reuse_mode;

typedef struct {
    duo_lm_reuse_mode mode;
    /* Stored contexts, 1 or DUO_LM_MAX_SLOTS. A request reuses the slot that shares the most
       tokens with it. The mode DUO_LM_REUSE_NONE takes 1. */
    int slots;
} duo_lm_reuse;

typedef struct duo_lm_scorer duo_lm_scorer;

typedef struct {
    double log_probability;
    double space_after;
} duo_lm_score;

/* Counts since the scorer opened. */
typedef struct {
    int vocabulary;
    int start_token;
    /* Tokens of -1 that the scorer replaced by the token of one space, and of one line break. */
    long space_repairs;
    long line_break_repairs;
    long requests;
    /* Tokens the model read, the start tokens included. */
    long tokens_read;
    /* Tokens of the windows of the requests that the model scored, the start tokens included,
       and the part of them that the cache already held. */
    long window_tokens;
    long window_tokens_reused;
    /* Requests that the check of duo_lm_scorer_set_check read a second time, and the widest
       difference between a number of the cache and the number of the fresh read. */
    long checked_requests;
    double checked_widest;
    /* Time spent in the calls of the model that read windows, and that read candidates, in
       milliseconds of a monotonic clock. The check's reads do not count. */
    double window_milliseconds;
    double candidate_milliseconds;
} duo_lm_scorer_info;

/* Loads the model at `model_path` with `threads` threads and the reuse mode `reuse`. Returns
   NULL when the model does not load or `reuse` is not valid, and then writes the reason into
   `error`. */
duo_lm_scorer *duo_lm_scorer_open(const char *model_path, int threads, duo_lm_reuse reuse, char *error,
                                  size_t error_size);

/* Turns on the check of the cache, for tests and the replay of scripts/kv-reuse: after each
   request the scorer reads the same window and candidates again in a second llama.cpp state,
   from an empty cache, and compares the numbers. A difference wider than `tolerance` makes the
   request return -1 with both numbers in `error`. A tolerance of 0 asks for the same numbers.
   The check needs the memory of a second state, so the keyboard does not turn it on.
   Returns 1, or 0 with the reason in `error`. */
int duo_lm_scorer_set_check(duo_lm_scorer *scorer, double tolerance, char *error, size_t error_size);

/* Scores `count` candidates after `context` and writes one result per candidate into `scores`.
   Returns 1 on success.
   Returns 0 for a request outside the limits above, such as a candidate of more than 32 tokens.
   Returns -1 when the model or the tokenizer did not do its part.
   On 0 and -1 the reason goes into `error`, and `scores` holds no result. */
int duo_lm_scorer_score(duo_lm_scorer *scorer, const char *context, const char *const *candidates, int count,
                        duo_lm_score *scores, char *error, size_t error_size);

duo_lm_scorer_info duo_lm_scorer_get_info(const duo_lm_scorer *scorer);

/* Frees the model and its state. NULL is allowed. */
void duo_lm_scorer_close(duo_lm_scorer *scorer);

#ifdef __cplusplus
}
#endif

#endif
