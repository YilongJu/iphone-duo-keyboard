/*
 The scorer of duo_lm_scorer.h.

 Two steps differ from scripts/lm-rerank/lm_score.c. Neither should change a number, because
 every value of a token comes from that token's own row of each product. The workflow
 .github/workflows/lm-keyboard.yml compares this scorer with lm_score.c on the same requests:

 1. Each call of the model reads at most 31 tokens, so the context and the candidates may take
    more than one call. This keeps the memory small: llama.cpp keeps the scores of every token
    of one call, 49,152 numbers or 197 KB per token for SmolLM2-135M, and it sets aside room for
    the largest call at the start. The framework of the app also holds the BLAS backend of
    Apple's Accelerate library. In llama.cpp b4846 the processor device comes first in the list
    of backends, so the processor already runs every product. BLAS also refuses a product of
    fewer than 32 tokens (min_batch in ggml-blas.cpp), so a change of that order cannot move
    a product of this scorer to BLAS.
 2. The token -1 gets its repair from the text itself. The tokenizer of llama.cpp b4846 writes
    the token of "[UNK]" for a word piece that is a lone space or a lone line break
    (llm_tokenizer_bpe_session in src/llama-vocab.cpp), and a GPT-2 vocabulary has no "[UNK]",
    so the tokenizer gives -1. The text of the harness never holds a line break, so lm_score.c
    puts the space token in place of every -1. The text of a keyboard can hold a line break.
    Here the scorer walks the text along the tokens: each token must give back its own part of
    the text, and a -1 becomes the token of the one character at its place, a space or a line
    break. For a text without a line break this gives the tokens of lm_score.c.
 */
#if !defined(__APPLE__)
/* Linux hides some POSIX functions from a C11 build without this line. */
#define _POSIX_C_SOURCE 200809L
#endif

#include "duo_lm_scorer.h"

#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if defined(__APPLE__)
#include <llama/llama.h>
#else
#include "llama.h"
#endif

/* Room for the start token, the context and 8 candidates of 32 tokens is 353 tokens. llama.cpp
   rounds the size of its state up to a multiple of 256 for flash attention. */
#define CONTEXT_SIZE 512
/* The most tokens of one call of the model. See point 1 at the top of this file. A build may set
   another value, as scripts/lm-keyboard/scorer-probe does to compare call sizes. */
#ifndef CALL_TOKENS
#define CALL_TOKENS 31
#endif
/* Size of the piece buffer of the vocabulary scan, as in lm_score.c. A token whose text is
   longer does not count as a token that starts with a space, in both programs. */
#define SCAN_PIECE_SIZE 64

struct duo_lm_scorer {
    struct llama_model *model;
    struct llama_context *context;
    const struct llama_vocab *vocab;
    struct llama_batch batch;
    int vocabulary;
    llama_token start;
    llama_token space_token;
    llama_token line_break_token;
    /* 1 for each token whose text starts with a space. */
    unsigned char *space_first;
    duo_lm_scorer_info info;
};

/* The last error line of llama.cpp. A load that fails reports it. */
static char last_llama_error[200];

static void keep_last_error(enum ggml_log_level level, const char *text, void *user_data) {
    (void)user_data;
    if (level != GGML_LOG_LEVEL_ERROR || text == NULL) return;
    snprintf(last_llama_error, sizeof last_llama_error, "%s", text);
    size_t length = strlen(last_llama_error);
    while (length > 0 && (last_llama_error[length - 1] == '\n' || last_llama_error[length - 1] == ' ')) {
        last_llama_error[--length] = 0;
    }
}

#if defined(__GNUC__)
static void set_error(char *error, size_t size, const char *format, ...) __attribute__((format(printf, 3, 4)));
#endif

static void set_error(char *error, size_t size, const char *format, ...) {
    if (error == NULL || size == 0) return;
    va_list arguments;
    va_start(arguments, format);
    vsnprintf(error, size, format, arguments);
    va_end(arguments);
}

static void add_token(struct llama_batch *batch, llama_token token, llama_pos position, llama_seq_id sequence,
                      int wants_scores) {
    int32_t index = batch->n_tokens;
    batch->token[index] = token;
    batch->pos[index] = position;
    batch->n_seq_id[index] = 1;
    batch->seq_id[index][0] = sequence;
    batch->logits[index] = (int8_t)wants_scores;
    batch->n_tokens = index + 1;
}

/* Natural log of the sum of e to the power of each score, with the arithmetic of lm_score.c. */
static double log_of_sum(const float *scores, int vocabulary) {
    float highest = scores[0];
    for (int index = 1; index < vocabulary; index++) {
        if (scores[index] > highest) highest = scores[index];
    }
    double sum = 0;
    for (int index = 0; index < vocabulary; index++) sum += exp((double)(scores[index] - highest));
    return (double)highest + log(sum);
}

/* Natural log of the probability mass on the tokens that `marked` flags, as in lm_score.c. */
static double log_of_marked(const float *scores, int vocabulary, const unsigned char *marked, double all) {
    double sum = 0;
    for (int index = 0; index < vocabulary; index++) {
        if (marked[index]) sum += exp((double)scores[index] - all);
    }
    return log(sum);
}

/* Writes the text of `token` into `piece`, which holds `capacity` bytes, and returns its length.
   A text longer than `capacity` goes into a buffer from malloc, and `*allocated` points to it. */
static int token_piece(const struct llama_vocab *vocab, llama_token token, char *piece, int capacity,
                       char **allocated, const char **text) {
    *allocated = NULL;
    int32_t length = llama_token_to_piece(vocab, token, piece, capacity, 0, false);
    if (length >= 0) {
        *text = piece;
        return length;
    }
    int32_t needed = -length;
    *allocated = (char *)malloc((size_t)needed);
    if (*allocated == NULL) return -1;
    length = llama_token_to_piece(vocab, token, *allocated, needed, 0, false);
    *text = *allocated;
    return length;
}

/* Tokenizes `text` and repairs -1 (point 2 at the top of this file). Writes a buffer from malloc
   into `*tokens_out` and returns the count of tokens, or -1 with the reason in `error`. */
static int tokenize(duo_lm_scorer *scorer, const char *text, llama_token **tokens_out, char *error,
                    size_t error_size) {
    *tokens_out = NULL;
    size_t length = strlen(text);
    /* A GPT-2 vocabulary gives at most one token per byte. A tokenizer that needs more says so,
       and the second call gets the room it asked for. */
    int capacity = (int)length + 8;
    llama_token *tokens = (llama_token *)malloc(sizeof(llama_token) * (size_t)capacity);
    if (tokens == NULL) {
        set_error(error, error_size, "out of memory for the tokens");
        return -1;
    }
    int count = llama_tokenize(scorer->vocab, text, (int32_t)length, tokens, capacity, false, false);
    if (count < 0) {
        capacity = -count;
        llama_token *larger = (llama_token *)realloc(tokens, sizeof(llama_token) * (size_t)capacity);
        if (larger == NULL) {
            free(tokens);
            set_error(error, error_size, "out of memory for the tokens");
            return -1;
        }
        tokens = larger;
        count = llama_tokenize(scorer->vocab, text, (int32_t)length, tokens, capacity, false, false);
    }
    if (count < 0) {
        free(tokens);
        set_error(error, error_size, "the tokenizer asked for room twice");
        return -1;
    }

    size_t place = 0;
    for (int index = 0; index < count; index++) {
        if (tokens[index] == LLAMA_TOKEN_NULL) {
            char character = place < length ? text[place] : 0;
            llama_token repair = character == ' ' ? scorer->space_token
                : character == '\n' ? scorer->line_break_token : LLAMA_TOKEN_NULL;
            if (repair == LLAMA_TOKEN_NULL) {
                set_error(error, error_size, "token -1 at place %d of %d stands for byte %d, not a space or a line break",
                          index, count, (int)(unsigned char)character);
                free(tokens);
                return -1;
            }
            tokens[index] = repair;
            if (character == ' ') {
                scorer->info.space_repairs++;
            } else {
                scorer->info.line_break_repairs++;
            }
            place += 1;
            continue;
        }
        if (tokens[index] < 0 || tokens[index] >= scorer->vocabulary) {
            set_error(error, error_size, "token %d at place %d is outside the vocabulary", tokens[index], index);
            free(tokens);
            return -1;
        }
        char buffer[SCAN_PIECE_SIZE];
        char *allocated;
        const char *piece;
        int piece_length = token_piece(scorer->vocab, tokens[index], buffer, (int)sizeof buffer, &allocated, &piece);
        int matches = piece_length >= 0 && (size_t)piece_length <= length - place
            && memcmp(text + place, piece, (size_t)piece_length) == 0;
        free(allocated);
        if (!matches) {
            set_error(error, error_size, "token %d at place %d does not give back the text at byte %zu",
                      tokens[index], index, place);
            free(tokens);
            return -1;
        }
        place += (size_t)piece_length;
    }
    if (place != length) {
        set_error(error, error_size, "the tokens give back %zu of the %zu bytes of the text", place, length);
        free(tokens);
        return -1;
    }
    *tokens_out = tokens;
    return count;
}

duo_lm_scorer *duo_lm_scorer_open(const char *model_path, int threads, char *error, size_t error_size) {
    if (threads < 1) {
        set_error(error, error_size, "the thread count must be 1 or more");
        return NULL;
    }
    duo_lm_scorer *scorer = (duo_lm_scorer *)calloc(1, sizeof(duo_lm_scorer));
    if (scorer == NULL) {
        set_error(error, error_size, "out of memory");
        return NULL;
    }
    last_llama_error[0] = 0;
    llama_log_set(keep_last_error, NULL);
    llama_backend_init();

    /* The processor is the only device, as in LanguageModel/duo_lm_probe.c. */
    ggml_backend_dev_t devices[2] = {ggml_backend_dev_by_type(GGML_BACKEND_DEVICE_TYPE_CPU), NULL};
    if (devices[0] == NULL) {
        set_error(error, error_size, "llama.cpp does not offer the processor as a device");
        free(scorer);
        return NULL;
    }
    struct llama_model_params model_settings = llama_model_default_params();
    model_settings.devices = devices;
    model_settings.n_gpu_layers = 0;
    model_settings.split_mode = LLAMA_SPLIT_MODE_NONE;
    /* The weights stay in the file. Pages that iOS reads from a file and that nobody changed do
       not count against the memory limit of the keyboard. */
    model_settings.use_mmap = true;
    model_settings.use_mlock = false;
    scorer->model = llama_model_load_from_file(model_path, model_settings);
    if (scorer->model == NULL) {
        set_error(error, error_size, "the model did not load: %s",
                  last_llama_error[0] != 0 ? last_llama_error : "llama.cpp gave no reason");
        free(scorer);
        return NULL;
    }
    scorer->vocab = llama_model_get_vocab(scorer->model);
    scorer->vocabulary = llama_vocab_n_tokens(scorer->vocab);
    scorer->info.vocabulary = scorer->vocabulary;

    scorer->start = llama_vocab_bos(scorer->vocab);
    if (scorer->start == LLAMA_TOKEN_NULL) scorer->start = llama_vocab_eos(scorer->vocab);
    if (scorer->start == LLAMA_TOKEN_NULL) {
        set_error(error, error_size, "the vocabulary has neither a start token nor an end token");
        duo_lm_scorer_close(scorer);
        return NULL;
    }
    scorer->info.start_token = scorer->start;

    /* The tokens whose text starts with a space, and the tokens of one space and of one line
       break, found the way lm_score.c finds them. */
    scorer->space_first = (unsigned char *)calloc((size_t)scorer->vocabulary, 1);
    if (scorer->space_first == NULL) {
        set_error(error, error_size, "out of memory");
        duo_lm_scorer_close(scorer);
        return NULL;
    }
    scorer->space_token = LLAMA_TOKEN_NULL;
    scorer->line_break_token = LLAMA_TOKEN_NULL;
    int space_tokens = 0;
    for (llama_token token = 0; token < scorer->vocabulary; token++) {
        char piece[SCAN_PIECE_SIZE];
        int32_t length = llama_token_to_piece(scorer->vocab, token, piece, (int32_t)sizeof piece, 0, false);
        if (length > 0 && piece[0] == ' ') {
            scorer->space_first[token] = 1;
            space_tokens++;
            if (length == 1 && scorer->space_token == LLAMA_TOKEN_NULL) scorer->space_token = token;
        }
        if (length == 1 && piece[0] == '\n' && scorer->line_break_token == LLAMA_TOKEN_NULL) {
            scorer->line_break_token = token;
        }
    }
    if (space_tokens == 0) {
        set_error(error, error_size, "no token of the vocabulary starts with a space");
        duo_lm_scorer_close(scorer);
        return NULL;
    }

    struct llama_context_params context_settings = llama_context_default_params();
    context_settings.n_ctx = CONTEXT_SIZE;
    context_settings.n_batch = CALL_TOKENS;
    context_settings.n_ubatch = CALL_TOKENS;
    context_settings.n_seq_max = DUO_LM_MAX_CANDIDATES + 1;
    context_settings.n_threads = threads;
    context_settings.n_threads_batch = threads;
    context_settings.offload_kqv = false;
    context_settings.flash_attn = true;
    context_settings.no_perf = true;
    scorer->context = llama_init_from_model(scorer->model, context_settings);
    if (scorer->context == NULL) {
        set_error(error, error_size, "the model state did not set up: %s",
                  last_llama_error[0] != 0 ? last_llama_error : "llama.cpp gave no reason");
        duo_lm_scorer_close(scorer);
        return NULL;
    }
    if ((long)llama_n_ubatch(scorer->context) > (long)CALL_TOKENS) {
        set_error(error, error_size, "llama.cpp set %ld tokens per step, more than %d",
                  (long)llama_n_ubatch(scorer->context), CALL_TOKENS);
        duo_lm_scorer_close(scorer);
        return NULL;
    }
    scorer->batch = llama_batch_init(CALL_TOKENS, 0, 1);
    return scorer;
}

/* Reads the queued tokens of the batch. Returns 0 when the model did not run. */
static int run_batch(duo_lm_scorer *scorer, char *error, size_t error_size) {
    int result = llama_decode(scorer->context, scorer->batch);
    if (result != 0) {
        set_error(error, error_size, "llama_decode returned %d for %d tokens%s%s", result, scorer->batch.n_tokens,
                  last_llama_error[0] != 0 ? ": " : "", last_llama_error);
        return 0;
    }
    scorer->info.tokens_read += scorer->batch.n_tokens;
    return 1;
}

int duo_lm_scorer_score(duo_lm_scorer *scorer, const char *context, const char *const *candidates, int count,
                        duo_lm_score *scores, char *error, size_t error_size) {
    if (scorer == NULL || context == NULL || candidates == NULL || scores == NULL) {
        set_error(error, error_size, "a pointer of the request is NULL");
        return -1;
    }
    if (count < 1 || count > DUO_LM_MAX_CANDIDATES) {
        set_error(error, error_size, "a request holds %d candidates, and the limit is 1 to %d", count,
                  DUO_LM_MAX_CANDIDATES);
        return 0;
    }
    scorer->info.requests++;

    /* The start token, then the last tokens of the context. */
    llama_token context_tokens[DUO_LM_MAX_CONTEXT_TOKENS + 1];
    int context_count = 1;
    context_tokens[0] = scorer->start;
    if (context[0] != 0) {
        llama_token *tokens;
        int found = tokenize(scorer, context, &tokens, error, error_size);
        if (found < 0) return -1;
        int first = found > DUO_LM_MAX_CONTEXT_TOKENS ? found - DUO_LM_MAX_CONTEXT_TOKENS : 0;
        for (int index = first; index < found; index++) context_tokens[context_count++] = tokens[index];
        free(tokens);
    }

    llama_token candidate_tokens[DUO_LM_MAX_CANDIDATES][DUO_LM_MAX_CANDIDATE_TOKENS];
    int lengths[DUO_LM_MAX_CANDIDATES];
    for (int candidate = 0; candidate < count; candidate++) {
        if (candidates[candidate] == NULL) {
            set_error(error, error_size, "candidate %d is NULL", candidate);
            return -1;
        }
        llama_token *tokens;
        int found = tokenize(scorer, candidates[candidate], &tokens, error, error_size);
        if (found < 0) return -1;
        if (found < 1 || found > DUO_LM_MAX_CANDIDATE_TOKENS) {
            free(tokens);
            set_error(error, error_size, "candidate %d gives %d tokens, and the limit is 1 to %d", candidate, found,
                      DUO_LM_MAX_CANDIDATE_TOKENS);
            return 0;
        }
        memcpy(candidate_tokens[candidate], tokens, sizeof(llama_token) * (size_t)found);
        lengths[candidate] = found;
        free(tokens);
    }

    /* The context, in calls of at most CALL_TOKENS tokens. Only its last token needs scores. */
    llama_kv_cache_clear(scorer->context);
    last_llama_error[0] = 0;
    for (int first = 0; first < context_count; first += CALL_TOKENS) {
        int end = first + CALL_TOKENS < context_count ? first + CALL_TOKENS : context_count;
        scorer->batch.n_tokens = 0;
        for (int index = first; index < end; index++) {
            add_token(&scorer->batch, context_tokens[index], index, 0, index == context_count - 1);
        }
        if (!run_batch(scorer, error, error_size)) return -1;
    }
    const float *after_context = llama_get_logits_ith(scorer->context, scorer->batch.n_tokens - 1);
    if (after_context == NULL) {
        set_error(error, error_size, "the model gave no scores after the context");
        return -1;
    }
    double context_all = log_of_sum(after_context, scorer->vocabulary);
    for (int candidate = 0; candidate < count; candidate++) {
        scores[candidate].log_probability = (double)after_context[candidate_tokens[candidate][0]] - context_all;
        scores[candidate].space_after = 0;
        llama_kv_cache_seq_cp(scorer->context, 0, candidate + 1, -1, -1);
    }

    /* The candidates, each in its own sequence after the context. Their tokens go in order, in
       calls of at most CALL_TOKENS tokens, and the scores of each call are read before the
       next call writes over them. Every token of a candidate needs scores: each token but the
       last gives the probability of the next token, and the last token gives the probability
       of a space after the candidate. */
    int candidate = 0, place = 0;
    while (candidate < count) {
        int owners[CALL_TOKENS], places[CALL_TOKENS];
        scorer->batch.n_tokens = 0;
        while (candidate < count && scorer->batch.n_tokens < CALL_TOKENS) {
            owners[scorer->batch.n_tokens] = candidate;
            places[scorer->batch.n_tokens] = place;
            add_token(&scorer->batch, candidate_tokens[candidate][place], context_count + place, candidate + 1, 1);
            place++;
            if (place == lengths[candidate]) {
                candidate++;
                place = 0;
            }
        }
        if (!run_batch(scorer, error, error_size)) return -1;
        for (int row = 0; row < scorer->batch.n_tokens; row++) {
            const float *row_scores = llama_get_logits_ith(scorer->context, row);
            if (row_scores == NULL) {
                set_error(error, error_size, "the model gave no scores for a candidate token");
                return -1;
            }
            int owner = owners[row], at = places[row];
            double all = log_of_sum(row_scores, scorer->vocabulary);
            if (at + 1 < lengths[owner]) {
                scores[owner].log_probability += (double)row_scores[candidate_tokens[owner][at + 1]] - all;
            } else {
                scores[owner].space_after = log_of_marked(row_scores, scorer->vocabulary, scorer->space_first, all);
            }
        }
    }
    return 1;
}

duo_lm_scorer_info duo_lm_scorer_get_info(const duo_lm_scorer *scorer) {
    duo_lm_scorer_info empty;
    memset(&empty, 0, sizeof empty);
    return scorer != NULL ? scorer->info : empty;
}

void duo_lm_scorer_close(duo_lm_scorer *scorer) {
    if (scorer == NULL) return;
    if (scorer->batch.token != NULL) llama_batch_free(scorer->batch);
    if (scorer->context != NULL) llama_free(scorer->context);
    if (scorer->model != NULL) llama_model_free(scorer->model);
    free(scorer->space_first);
    free(scorer);
}
