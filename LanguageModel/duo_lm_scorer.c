/*
 The scorer of duo_lm_scorer.h.

 Two steps differ from scripts/lm-rerank/lm_score.c. Neither should change a number, because
 every value of a token comes from that token's own row of each product. The workflow
 .github/workflows/lm-keyboard.yml compares this scorer with lm_score.c on the same requests:

 1. Each call of the model reads at most 31 tokens, so the context and the candidates may take
    more than one call. This keeps the memory small: llama.cpp keeps the scores of every token
    of one call, 49,152 numbers or 197 KB per token for SmolLM2-135M, and it sets aside room for
    the largest call at the start. The calls of one part, the context or the candidates, get
    sizes that differ by one token at most (call_size below). So a call holds one token only
    when the whole part is one token, as in lm_score.c. A call of one token takes other code
    for the Q8_0 weights of the model: llamafile_sgemm of llama.cpp b4846 refuses a product of
    fewer than 2 tokens, and ggml_vec_dot_q8_0_q8_0 then sums in another order. On a processor
    with the dot-product instructions, as the macOS and simulator parts of the app's framework
    have, the two orders give other numbers. A context of 32 tokens read as 31 and 1 moved one
    score by 0.285 against lm_score.c (scripts/lm-keyboard/scorer-probe). The framework of the app also holds the BLAS backend of
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

 With the reuse mode DUO_LM_REUSE_PREFIX the scorer keeps the cache of the last window. A new
 request keeps the cached tokens of the longest start that its window shares with that window,
 and the model reads the rest. Each kept token has the same token, position and tokens before it
 as in a full read, so only the call boundaries change, and point 1 keeps the numbers. The model
 reads at least the last two tokens of a window (MIN_UNREAD_TOKENS), so no call of a window holds
 one token where a full read holds more. docs/kv-reuse-design.md describes the modes.
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
#include <time.h>

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
/* The fewest tokens of the window that a request with reuse reads, so the last call of its
   window holds as many tokens and takes the same code as a full read (point 1 above). A build
   may set 1, as scripts/kv-reuse does to measure calls of one token. */
#ifndef MIN_UNREAD_TOKENS
#define MIN_UNREAD_TOKENS 2
#endif
/* Size of the piece buffer of the vocabulary scan, as in lm_score.c. A token whose text is
   longer does not count as a token that starts with a space, in both programs. */
#define SCAN_PIECE_SIZE 64

/* One stored context in the cache. */
struct slot {
    /* The sequence of llama.cpp that holds the context. The candidates take the sequences 1 to
       DUO_LM_MAX_CANDIDATES, so the slots take 0 and the sequences after the candidates. */
    llama_seq_id sequence;
    /* The window in the cache, at the positions 0 to count - 1: the start token, then the
       tokens of the context from `window_start` on. A count of 0 is an empty slot. */
    llama_token tokens[DUO_LM_MAX_CONTEXT_TOKENS + 1];
    int count;
    int window_start;
    /* Every token of the context of the last request of this slot. */
    llama_token *context;
    int context_count;
    int context_capacity;
    /* The request count at the last use, to pick the slot that waited longest. */
    long last_use;
};

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
    duo_lm_reuse reuse;
    struct slot slots[DUO_LM_MAX_SLOTS];
    /* The second state of the check, or NULL without the check. */
    struct llama_context *check_context;
    double check_tolerance;
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

/* The settings of every llama.cpp state of the scorer: the scorer's own and the check's. */
static struct llama_context_params state_settings(const duo_lm_scorer *scorer, int threads) {
    struct llama_context_params context_settings = llama_context_default_params();
    context_settings.n_ctx = CONTEXT_SIZE;
    context_settings.n_batch = CALL_TOKENS;
    context_settings.n_ubatch = CALL_TOKENS;
    context_settings.n_seq_max = (uint32_t)(DUO_LM_MAX_CANDIDATES + scorer->reuse.slots);
    context_settings.n_threads = threads;
    context_settings.n_threads_batch = threads;
    context_settings.offload_kqv = false;
    context_settings.flash_attn = true;
    context_settings.no_perf = true;
    return context_settings;
}

duo_lm_scorer *duo_lm_scorer_open(const char *model_path, int threads, duo_lm_reuse reuse, char *error,
                                  size_t error_size) {
    if (threads < 1) {
        set_error(error, error_size, "the thread count must be 1 or more");
        return NULL;
    }
    if (reuse.mode != DUO_LM_REUSE_NONE && reuse.mode != DUO_LM_REUSE_PREFIX && reuse.mode != DUO_LM_REUSE_SHIFT
        && reuse.mode != DUO_LM_REUSE_ANCHOR) {
        set_error(error, error_size, "the reuse mode %d is not known", (int)reuse.mode);
        return NULL;
    }
    if (reuse.slots < 1 || reuse.slots > DUO_LM_MAX_SLOTS || (reuse.mode == DUO_LM_REUSE_NONE && reuse.slots != 1)) {
        set_error(error, error_size, "%d slots with the reuse mode %d: the mode without reuse takes 1, the others 1 to %d",
                  reuse.slots, (int)reuse.mode, DUO_LM_MAX_SLOTS);
        return NULL;
    }
    duo_lm_scorer *scorer = (duo_lm_scorer *)calloc(1, sizeof(duo_lm_scorer));
    if (scorer == NULL) {
        set_error(error, error_size, "out of memory");
        return NULL;
    }
    scorer->reuse = reuse;
    for (int index = 0; index < reuse.slots; index++) {
        scorer->slots[index].sequence = index == 0 ? 0 : DUO_LM_MAX_CANDIDATES + index;
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

    scorer->context = llama_init_from_model(scorer->model, state_settings(scorer, threads));
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
    if (reuse.mode == DUO_LM_REUSE_SHIFT && !llama_kv_cache_can_shift(scorer->context)) {
        set_error(error, error_size, "llama.cpp cannot move the positions of this model's cache");
        duo_lm_scorer_close(scorer);
        return NULL;
    }
    scorer->batch = llama_batch_init(CALL_TOKENS, 0, 1);
    return scorer;
}

int duo_lm_scorer_set_check(duo_lm_scorer *scorer, double tolerance, char *error, size_t error_size) {
    if (scorer == NULL || !(tolerance >= 0)) {
        set_error(error, error_size, "the check needs a scorer and a tolerance of 0 or more");
        return 0;
    }
    if (scorer->check_context == NULL) {
        int threads = (int)llama_n_threads(scorer->context);
        last_llama_error[0] = 0;
        scorer->check_context = llama_init_from_model(scorer->model, state_settings(scorer, threads));
        if (scorer->check_context == NULL) {
            set_error(error, error_size, "the state of the check did not set up: %s",
                      last_llama_error[0] != 0 ? last_llama_error : "llama.cpp gave no reason");
            return 0;
        }
    }
    scorer->check_tolerance = tolerance;
    return 1;
}

/* The size of call `call` of a part of `tokens` tokens: the calls of a part get sizes that
   differ by one token at most, and none is larger than CALL_TOKENS. See point 1 at the top. */
static int call_size(int tokens, int call) {
    int calls = (tokens + CALL_TOKENS - 1) / CALL_TOKENS;
    return tokens / calls + (call < tokens % calls ? 1 : 0);
}

static double now_milliseconds(void) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (double)now.tv_sec * 1000.0 + (double)now.tv_nsec / 1e6;
}

/* Reads the queued tokens of the batch in `state`. Returns 0 when the model did not run. The
   reads of the check do not count in `tokens_read`. */
static int run_batch(duo_lm_scorer *scorer, struct llama_context *state, char *error, size_t error_size) {
    int result = llama_decode(state, scorer->batch);
    if (result != 0) {
        set_error(error, error_size, "llama_decode returned %d for %d tokens%s%s", result, scorer->batch.n_tokens,
                  last_llama_error[0] != 0 ? ": " : "", last_llama_error);
        return 0;
    }
    if (state == scorer->context) scorer->info.tokens_read += scorer->batch.n_tokens;
    return 1;
}

/* The tokens of the candidates of one request. */
struct candidate_tokens {
    llama_token tokens[DUO_LM_MAX_CANDIDATES][DUO_LM_MAX_CANDIDATE_TOKENS];
    int lengths[DUO_LM_MAX_CANDIDATES];
    int count;
};

/* Reads the window from token `kept` on into the sequence `sequence` of `state`, whose cache
   holds the tokens before `kept` at their positions, and then reads the candidates and writes
   their scores. The candidate sequences must be empty. */
static int read_window_and_candidates(duo_lm_scorer *scorer, struct llama_context *state, llama_seq_id sequence,
                                      const llama_token *window, int window_count, int kept,
                                      const struct candidate_tokens *candidates, duo_lm_score *scores, char *error,
                                      size_t error_size) {
    /* The window after the kept tokens, in calls of at most CALL_TOKENS tokens. Only its last
       token needs scores. */
    int unread = window_count - kept;
    int counts = state == scorer->context;
    double started = now_milliseconds();
    last_llama_error[0] = 0;
    for (int first = 0, call = 0; first < unread; first += call_size(unread, call), call++) {
        int end = first + call_size(unread, call);
        scorer->batch.n_tokens = 0;
        for (int index = kept + first; index < kept + end; index++) {
            add_token(&scorer->batch, window[index], index, sequence, index == window_count - 1);
        }
        if (!run_batch(scorer, state, error, error_size)) return -1;
    }
    const float *after_context = llama_get_logits_ith(state, scorer->batch.n_tokens - 1);
    if (after_context == NULL) {
        set_error(error, error_size, "the model gave no scores after the context");
        return -1;
    }
    double read_window = now_milliseconds();
    if (counts) scorer->info.window_milliseconds += read_window - started;
    int count = candidates->count;
    double context_all = log_of_sum(after_context, scorer->vocabulary);
    for (int candidate = 0; candidate < count; candidate++) {
        scores[candidate].log_probability = (double)after_context[candidates->tokens[candidate][0]] - context_all;
        scores[candidate].space_after = 0;
        llama_kv_cache_seq_cp(state, sequence, candidate + 1, -1, -1);
    }

    /* The candidates, each in its own sequence after the context. Their tokens go in order, in
       calls of the sizes of call_size, and the scores of each call are read before the
       next call writes over them. Every token of a candidate needs scores: each token but the
       last gives the probability of the next token, and the last token gives the probability
       of a space after the candidate. */
    int candidate_tokens_total = 0;
    for (int index = 0; index < count; index++) candidate_tokens_total += candidates->lengths[index];
    int candidate = 0, place = 0;
    for (int call = 0; candidate < count; call++) {
        int owners[CALL_TOKENS], places[CALL_TOKENS];
        int size = call_size(candidate_tokens_total, call);
        scorer->batch.n_tokens = 0;
        while (candidate < count && scorer->batch.n_tokens < size) {
            owners[scorer->batch.n_tokens] = candidate;
            places[scorer->batch.n_tokens] = place;
            add_token(&scorer->batch, candidates->tokens[candidate][place], window_count + place, candidate + 1, 1);
            place++;
            if (place == candidates->lengths[candidate]) {
                candidate++;
                place = 0;
            }
        }
        if (!run_batch(scorer, state, error, error_size)) return -1;
        for (int row = 0; row < scorer->batch.n_tokens; row++) {
            const float *row_scores = llama_get_logits_ith(state, row);
            if (row_scores == NULL) {
                set_error(error, error_size, "the model gave no scores for a candidate token");
                return -1;
            }
            int owner = owners[row], at = places[row];
            double all = log_of_sum(row_scores, scorer->vocabulary);
            if (at + 1 < candidates->lengths[owner]) {
                scores[owner].log_probability += (double)row_scores[candidates->tokens[owner][at + 1]] - all;
            } else {
                scores[owner].space_after = log_of_marked(row_scores, scorer->vocabulary, scorer->space_first, all);
            }
        }
    }
    if (counts) scorer->info.candidate_milliseconds += now_milliseconds() - read_window;
    return 1;
}

static int shared_start(const llama_token *first, int first_count, const llama_token *second, int second_count) {
    int length = 0;
    while (length < first_count && length < second_count && first[length] == second[length]) length++;
    return length;
}

/* What one slot offers a request: the window of the request with this slot, the tokens of the
   cache that the request keeps, and the positions that the kept tokens after the start token
   move back by (the shift mode only). */
struct plan {
    int window_start;
    int kept;
    int shift;
};

static struct plan plan_for_slot(const duo_lm_scorer *scorer, const struct slot *slot, const llama_token *context_tokens,
                                 int context_count) {
    struct plan plan;
    plan.shift = 0;
    plan.window_start = context_count > DUO_LM_MAX_CONTEXT_TOKENS ? context_count - DUO_LM_MAX_CONTEXT_TOKENS : 0;
    if (scorer->reuse.mode == DUO_LM_REUSE_ANCHOR && context_count > DUO_LM_MAX_CONTEXT_TOKENS) {
        /* The window keeps the start of the slot while the context still holds the tokens up to
           that start and one more, and the window fits. Otherwise it starts again at the last
           DUO_LM_ANCHOR_REFILL_TOKENS tokens. */
        int anchor = slot->window_start;
        int same = shared_start(slot->context, slot->context_count, context_tokens, context_count);
        int keeps = slot->count > 0 && same > anchor && context_count - anchor <= DUO_LM_MAX_CONTEXT_TOKENS;
        plan.window_start = keeps ? anchor : context_count - DUO_LM_ANCHOR_REFILL_TOKENS;
    }
    plan.kept = 0;
    if (slot->count == 0) return plan;
    /* The window of the request: the start token, then the context from window_start on. The
       cache holds the start token at position 0 and the slot's window after it. */
    const llama_token *window = context_tokens + plan.window_start;
    int window_count = context_count - plan.window_start;
    int moved = plan.window_start - slot->window_start;
    if (scorer->reuse.mode == DUO_LM_REUSE_SHIFT && moved > 0 && moved < slot->count - 1) {
        int same = shared_start(slot->tokens + 1 + moved, slot->count - 1 - moved, window, window_count);
        if (same > 0) {
            plan.shift = moved;
            plan.kept = 1 + same;
            return plan;
        }
    }
    /* The start token is always the same, and its keys and values do not depend on any other
       token, so the slot keeps at least that one. */
    plan.kept = 1 + shared_start(slot->tokens + 1, slot->count - 1, window, window_count);
    return plan;
}

/* Marks every slot empty and clears the cache, after a read that did not finish. */
static void forget_cache(duo_lm_scorer *scorer) {
    for (int index = 0; index < scorer->reuse.slots; index++) scorer->slots[index].count = 0;
    llama_kv_cache_clear(scorer->context);
}

static int remember_context(struct slot *slot, const llama_token *context_tokens, int context_count, char *error,
                            size_t error_size) {
    if (context_count > slot->context_capacity) {
        llama_token *larger = (llama_token *)realloc(slot->context, sizeof(llama_token) * (size_t)context_count);
        if (larger == NULL) {
            set_error(error, error_size, "out of memory for the tokens of a slot");
            return 0;
        }
        slot->context = larger;
        slot->context_capacity = context_count;
    }
    if (context_count > 0) memcpy(slot->context, context_tokens, sizeof(llama_token) * (size_t)context_count);
    slot->context_count = context_count;
    return 1;
}

/* Reads the same window and candidates in the state of the check, from an empty cache, and
   compares the numbers with `scores`. */
static int check_scores(duo_lm_scorer *scorer, const llama_token *window, int window_count,
                        const struct candidate_tokens *candidates, const duo_lm_score *scores, char *error,
                        size_t error_size) {
    duo_lm_score fresh[DUO_LM_MAX_CANDIDATES];
    llama_kv_cache_clear(scorer->check_context);
    if (read_window_and_candidates(scorer, scorer->check_context, 0, window, window_count, 0, candidates, fresh, error,
                                   error_size) != 1) {
        return -1;
    }
    scorer->info.checked_requests++;
    for (int candidate = 0; candidate < candidates->count; candidate++) {
        double pair[2][2] = {{scores[candidate].log_probability, fresh[candidate].log_probability},
                             {scores[candidate].space_after, fresh[candidate].space_after}};
        for (int number = 0; number < 2; number++) {
            double difference = fabs(pair[number][0] - pair[number][1]);
            if (difference > scorer->info.checked_widest) scorer->info.checked_widest = difference;
            if (difference > scorer->check_tolerance) {
                set_error(error, error_size, "the cache gave %.17g for the %s of candidate %d, a fresh read %.17g",
                          pair[number][0], number == 0 ? "log probability" : "space after", candidate, pair[number][1]);
                return -1;
            }
        }
    }
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

    /* Every token of the context. The window is the start token and the last tokens of it. */
    llama_token *context_tokens = NULL;
    int context_count = 0;
    if (context[0] != 0) {
        context_count = tokenize(scorer, context, &context_tokens, error, error_size);
        if (context_count < 0) return -1;
    }

    struct candidate_tokens candidate_tokens;
    candidate_tokens.count = count;
    for (int candidate = 0; candidate < count; candidate++) {
        if (candidates[candidate] == NULL) {
            free(context_tokens);
            set_error(error, error_size, "candidate %d is NULL", candidate);
            return -1;
        }
        llama_token *tokens;
        int found = tokenize(scorer, candidates[candidate], &tokens, error, error_size);
        if (found < 0) {
            free(context_tokens);
            return -1;
        }
        if (found < 1 || found > DUO_LM_MAX_CANDIDATE_TOKENS) {
            free(tokens);
            free(context_tokens);
            set_error(error, error_size, "candidate %d gives %d tokens, and the limit is 1 to %d", candidate, found,
                      DUO_LM_MAX_CANDIDATE_TOKENS);
            return 0;
        }
        memcpy(candidate_tokens.tokens[candidate], tokens, sizeof(llama_token) * (size_t)found);
        candidate_tokens.lengths[candidate] = found;
        free(tokens);
    }

    /* The slot that keeps the most tokens of the cache. When no slot keeps more than the start
       token, the slot that waited longest takes the request. */
    int chosen = 0;
    struct plan plan = plan_for_slot(scorer, &scorer->slots[0], context_tokens, context_count);
    for (int index = 1; index < scorer->reuse.slots; index++) {
        struct plan other = plan_for_slot(scorer, &scorer->slots[index], context_tokens, context_count);
        if (other.kept > plan.kept
            || (other.kept == plan.kept && plan.kept <= 1 && scorer->slots[index].last_use < scorer->slots[chosen].last_use)) {
            chosen = index;
            plan = other;
        }
    }
    struct slot *slot = &scorer->slots[chosen];
    llama_token window[DUO_LM_MAX_CONTEXT_TOKENS + 1];
    window[0] = scorer->start;
    int window_count = 1 + context_count - plan.window_start;
    memcpy(window + 1, context_tokens + plan.window_start, sizeof(llama_token) * (size_t)(window_count - 1));

    /* The model reads at least the last two tokens of the window, so its last call of the
       context holds two tokens or more, as a full read does. A full read of a window of one
       token, the start token alone, is one call of one token, as in lm_score.c. See point 1 at
       the top of this file. */
    int kept = plan.kept;
    if (kept > window_count - MIN_UNREAD_TOKENS) kept = window_count - MIN_UNREAD_TOKENS;
    if (kept < 0) kept = 0;
    if (scorer->reuse.mode == DUO_LM_REUSE_NONE) kept = 0;

    /* The cache keeps the first `kept` tokens of the slot and nothing of the candidates. */
    if (scorer->reuse.mode == DUO_LM_REUSE_NONE) {
        llama_kv_cache_clear(scorer->context);
    } else {
        int removed = 1;
        for (int candidate = 1; candidate <= DUO_LM_MAX_CANDIDATES; candidate++) {
            removed = removed && llama_kv_cache_seq_rm(scorer->context, candidate, -1, -1);
        }
        if (kept > 1 && plan.shift > 0) {
            removed = removed && llama_kv_cache_seq_rm(scorer->context, slot->sequence, 1, 1 + plan.shift);
            llama_kv_cache_seq_add(scorer->context, slot->sequence, 1 + plan.shift, -1, -plan.shift);
        }
        removed = removed && llama_kv_cache_seq_rm(scorer->context, slot->sequence, kept, -1);
        if (!removed) {
            free(context_tokens);
            forget_cache(scorer);
            set_error(error, error_size, "llama.cpp did not remove tokens from the cache");
            return -1;
        }
    }
    slot->count = 0;
    int result = read_window_and_candidates(scorer, scorer->context, slot->sequence, window, window_count, kept,
                                            &candidate_tokens, scores, error, error_size);
    if (result != 1) {
        free(context_tokens);
        forget_cache(scorer);
        return result;
    }
    scorer->info.window_tokens += window_count;
    scorer->info.window_tokens_reused += kept;
    memcpy(slot->tokens, window, sizeof(llama_token) * (size_t)window_count);
    slot->count = window_count;
    slot->window_start = plan.window_start;
    slot->last_use = scorer->info.requests;
    int remembered = remember_context(slot, context_tokens, context_count, error, error_size);
    free(context_tokens);
    if (!remembered) {
        forget_cache(scorer);
        return -1;
    }
    if (scorer->check_context != NULL) {
        return check_scores(scorer, window, window_count, &candidate_tokens, scores, error, error_size);
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
    if (scorer->check_context != NULL) llama_free(scorer->check_context);
    if (scorer->context != NULL) llama_free(scorer->context);
    for (int index = 0; index < DUO_LM_MAX_SLOTS; index++) free(scorer->slots[index].context);
    if (scorer->model != NULL) llama_model_free(scorer->model);
    free(scorer->space_first);
    free(scorer);
}
