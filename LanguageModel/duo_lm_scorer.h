/*
 The language model that re-ranks the English corrections of Duo Keyboard.

 The scorer loads one model through llama.cpp, on the processor only, and keeps it loaded until
 the caller closes it. One request holds a context and 1 to 8 candidate texts. The model reads
 the start token and the context once. Each candidate then follows the context in a sequence of
 its own that shares the stored state of the context, so the context is read once per request.

 For each candidate the scorer gives two natural logarithms:
   log_probability  the probability of the candidate's tokens right after the context
   space_after      the probability that the token after the candidate starts with a space

 The scorer reads each text exactly as given. The caller builds the context and the candidates,
 with the space between them (LanguageModelPrompt in Shared/EnglishReranking.swift).

 scripts/lm-rerank/lm_score.c gives the same numbers on Linux, where the re-ranking rule was
 tuned. This scorer follows that program in each step that sets a number: the start token, the
 last 96 tokens of the context, the token that takes the place of -1, and the sums over the
 vocabulary. duo_lm_scorer.c names the two steps that differ and why they leave the numbers alone.
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
} duo_lm_scorer_info;

/* Loads the model at `model_path` with `threads` threads. Returns NULL when the model does not
   load, and then writes the reason into `error`. */
duo_lm_scorer *duo_lm_scorer_open(const char *model_path, int threads, char *error, size_t error_size);

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
