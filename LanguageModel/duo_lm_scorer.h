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
 The reuse modes DUO_LM_REUSE_PREFIX and DUO_LM_REUSE_ANCHOR change only the calls in which the
 model reads the tokens, so a window gets the numbers of a full read of that window. The anchored
 window of a context of more than 96 tokens holds other tokens than lm_score.c reads, and so its
 numbers differ (docs/kv-reuse-results.md). The keyboard reads with DUO_LM_REUSE_ANCHOR and two
 slots.
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
    /* Requests whose context held more than DUO_LM_MAX_CONTEXT_TOKENS tokens. Only their window
       depends on the reuse mode: the anchored window of DUO_LM_REUSE_ANCHOR holds other tokens
       than the last 96 of lm_score.c. */
    long long_contexts;
    /* Time spent in the calls of the model that read windows, and that read candidates, in
       milliseconds of a monotonic clock. The check's reads do not count. */
    double window_milliseconds;
    double candidate_milliseconds;
    /* Time spent in the tokenizer: the context and the candidates of each request. */
    double tokenize_milliseconds;
} duo_lm_scorer_info;

/* Loads the model at `model_path` with `threads` threads and the reuse mode `reuse`, on the
   processor only. Returns NULL when the model does not load or `reuse` is not valid, and then
   writes the reason into `error`. The keyboard opens its model with this function. */
duo_lm_scorer *duo_lm_scorer_open(const char *model_path, int threads, duo_lm_reuse reuse, char *error,
                                  size_t error_size);

/* The device that runs the products of the model, for the speed test of docs/model-speed-design.md.
   DUO_LM_DEVICE_CPU    the processor only, the settings of duo_lm_scorer_open
   DUO_LM_DEVICE_GPU    llama.cpp's GPU device (Metal on Apple devices) runs every layer and the
                        attention. The processor runs only what the GPU device refuses. */
typedef enum {
    DUO_LM_DEVICE_CPU = 0,
    DUO_LM_DEVICE_GPU = 1,
} duo_lm_device;

/* duo_lm_scorer_open with a choice of device. With DUO_LM_DEVICE_CPU it is duo_lm_scorer_open. */
duo_lm_scorer *duo_lm_scorer_open_on(const char *model_path, int threads, duo_lm_reuse reuse, duo_lm_device device,
                                     char *error, size_t error_size);

/* Tokenizes `text` the way a request does, with the repair of -1 of duo_lm_scorer.c, and writes
   at most `capacity` tokens into `tokens`. Returns the count of tokens, or -1 with the reason in
   `error`, also when the text needs more than `capacity` tokens. The speed test writes the tokens
   of each request with it, for the runtimes that have no tokenizer of their own. */
int duo_lm_scorer_tokenize(duo_lm_scorer *scorer, const char *text, int *tokens, int capacity, char *error,
                           size_t error_size);

/* The start token of the model, which every window begins with. */
int duo_lm_scorer_start_token(const duo_lm_scorer *scorer);

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

/* The last line of llama.cpp's Metal code since the last open that says whether it keeps
   residency sets, such as "ggml_metal_init: has residency sets    = true", or an empty text when
   no such line came. The speed test reports it for each Metal pair. */
const char *duo_lm_scorer_residency_note(void);

/* llama.cpp's own line about the build: the processor features it was compiled for, such as
   DOTPROD and MATMUL_INT8, and whether it repacks Q4_0 weights (AARCH64_REPACK). */
const char *duo_lm_scorer_system_info(void);

/* Frees the model and its state. NULL is allowed. */
void duo_lm_scorer_close(duo_lm_scorer *scorer);

#ifdef __cplusplus
}
#endif

#endif
