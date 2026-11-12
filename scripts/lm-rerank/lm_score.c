/*
 Scores candidate texts with a language model through llama.cpp, for rerank.py.

 Usage: lm_score MODEL.gguf THREADS < requests > answers
        lm_score MODEL.gguf THREADS tokens < requests > token lines

 Request line:  context <TAB> candidate 1 <TAB> candidate 2 ...
 Answer line:   log probability 1 <SPACE> space after 1 <TAB> log probability 2 <SPACE> space after 2 ...
 Token line:    the token ids the model would read, as numbers with a space between them: first the
                start token and the context, then one field per candidate. With "tokens" the
                program loads the vocabulary only, and scripts/lm-finetune/check_parity.py compares
                these ids with the ids of the training code.

 The context is the text before the candidates. The model reads the start-of-text token, then
 the context. A candidate follows the context after one space, or right after the start-of-text
 token when the context is empty. "log probability" is the natural log of the probability of
 the candidate's tokens after the context. "space after" is the natural log of the probability
 that the next token starts with a space, which is what the person typed after the candidate.

 Each candidate is its own sequence that shares the stored state of the context, as in
 LanguageModel/duo_lm_probe.c. The weights stay mapped from the file, on the processor only.

 At the end the program writes two lines to the error stream: the tokens read and the time the
 model took, and the highest anonymous resident memory of the process (RssAnon on Linux).
 */
#define _POSIX_C_SOURCE 200809L

#include "llama.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define MAX_LINE 65536
#define MAX_CANDIDATES 64
#define MAX_CANDIDATE_TOKENS 32
/* The context keeps its last tokens up to this count. */
#define MAX_CONTEXT_TOKENS 96
#define CONTEXT_SIZE 4096
#define BATCH_SIZE 2048
/* Tokens of one step of llama.cpp. A build may set another value, as scripts/lm-keyboard/scorer-probe
   does to compare step sizes. */
#ifndef UBATCH_SIZE
#define UBATCH_SIZE 512
#endif

static double now_ms(void) {
    struct timespec moment;
    clock_gettime(CLOCK_MONOTONIC, &moment);
    return (double)moment.tv_sec * 1000.0 + (double)moment.tv_nsec / 1e6;
}

static void quiet_log(enum ggml_log_level level, const char *text, void *user_data) {
    (void)user_data;
    if (level == GGML_LOG_LEVEL_ERROR && text != NULL) fputs(text, stderr);
}

/* RssAnon of this process in kB, or -1 when /proc/self/status does not hold it. */
static long rss_anon_kb(void) {
    FILE *file = fopen("/proc/self/status", "r");
    if (file == NULL) return -1;
    char line[256];
    long value = -1;
    while (fgets(line, sizeof line, file) != NULL) {
        if (strncmp(line, "RssAnon:", 8) == 0) {
            value = strtol(line + 8, NULL, 10);
            break;
        }
    }
    fclose(file);
    return value;
}

static void die(const char *message) {
    fprintf(stderr, "lm_score: %s\n", message);
    exit(1);
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

static double log_of_sum(const float *scores, int vocabulary) {
    float highest = scores[0];
    for (int index = 1; index < vocabulary; index++) {
        if (scores[index] > highest) highest = scores[index];
    }
    double sum = 0;
    for (int index = 0; index < vocabulary; index++) sum += exp((double)(scores[index] - highest));
    return (double)highest + log(sum);
}

/* Natural log of the probability mass on the tokens that `marked` flags. */
static double log_of_marked(const float *scores, int vocabulary, const unsigned char *marked, double all) {
    double sum = 0;
    for (int index = 0; index < vocabulary; index++) {
        if (marked[index]) sum += exp((double)scores[index] - all);
    }
    return log(sum);
}

/* The token whose text is one space. llama.cpp b4846 (src/llama-vocab.cpp, the BPE session)
   writes the token of "[UNK]" for a word piece that is a lone space, and a GPT-2 style
   vocabulary has no "[UNK]", so the tokenizer gives -1. The text of this script holds no line
   break, so -1 can only stand for a lone space, and the space token takes its place, as in the
   Hugging Face tokenizer: " ich" is the space token and then "ich". */
static llama_token space_token = LLAMA_TOKEN_NULL;
static long space_repairs = 0;

static int tokenize(const struct llama_vocab *vocab, const char *text, llama_token *tokens, int capacity) {
    int count = llama_tokenize(vocab, text, (int32_t)strlen(text), tokens, capacity, false, false);
    if (count < 0) die("a text gives more tokens than the buffer holds");
    int vocabulary = llama_vocab_n_tokens(vocab);
    for (int index = 0; index < count; index++) {
        if (tokens[index] == LLAMA_TOKEN_NULL && space_token != LLAMA_TOKEN_NULL) {
            tokens[index] = space_token;
            space_repairs++;
            /* The first repairs go to the error stream with their tokens, for a check against
               the Hugging Face tokenizer of the model. */
            if (space_repairs <= 30) {
                fprintf(stderr, "lm_score: repaired \"%s\":", text);
                for (int shown = 0; shown < count; shown++) {
                    fprintf(stderr, " %d", tokens[shown] == LLAMA_TOKEN_NULL ? space_token : tokens[shown]);
                }
                fprintf(stderr, "\n");
            }
        }
        if (tokens[index] < 0 || tokens[index] >= vocabulary) {
            fprintf(stderr, "lm_score: the text \"%s\" gives token %d at place %d of %d\n", text, tokens[index], index, count);
            die("a token is outside the vocabulary");
        }
    }
    return count;
}

int main(int argc, char **argv) {
    int tokens_only = argc == 4 && strcmp(argv[3], "tokens") == 0;
    if (argc != 3 && !tokens_only) {
        fprintf(stderr, "usage: lm_score MODEL.gguf THREADS [tokens]\n");
        return 2;
    }
    int threads = atoi(argv[2]);
    if (threads < 1) die("THREADS must be 1 or more");
    llama_log_set(quiet_log, NULL);
    llama_backend_init();

    ggml_backend_dev_t devices[2] = {ggml_backend_dev_by_type(GGML_BACKEND_DEVICE_TYPE_CPU), NULL};
    if (devices[0] == NULL) die("llama.cpp does not offer the processor as a device");
    struct llama_model_params model_settings = llama_model_default_params();
    model_settings.devices = devices;
    model_settings.n_gpu_layers = 0;
    model_settings.split_mode = LLAMA_SPLIT_MODE_NONE;
    model_settings.use_mmap = true;
    model_settings.use_mlock = false;
    model_settings.vocab_only = tokens_only;
    struct llama_model *model = llama_model_load_from_file(argv[1], model_settings);
    if (model == NULL) die("the model did not load");
    const struct llama_vocab *vocab = llama_model_get_vocab(model);
    int vocabulary = llama_vocab_n_tokens(vocab);

    llama_token start = llama_vocab_bos(vocab);
    if (start == LLAMA_TOKEN_NULL) start = llama_vocab_eos(vocab);
    if (start == LLAMA_TOKEN_NULL) die("the vocabulary has neither a start token nor an end token");

    /* The tokens whose text starts with a space. */
    unsigned char *space_first = (unsigned char *)calloc((size_t)vocabulary, 1);
    if (space_first == NULL) die("out of memory");
    int space_tokens = 0;
    for (llama_token token = 0; token < vocabulary; token++) {
        char piece[64];
        int32_t length = llama_token_to_piece(vocab, token, piece, (int32_t)sizeof piece, 0, false);
        if (length > 0 && piece[0] == ' ') {
            space_first[token] = 1;
            space_tokens++;
            if (length == 1 && space_token == LLAMA_TOKEN_NULL) space_token = token;
        }
    }
    if (space_tokens == 0) die("no token starts with a space");

    struct llama_context *model_context = NULL;
    struct llama_batch batch = {0};
    if (!tokens_only) {
        struct llama_context_params context_settings = llama_context_default_params();
        context_settings.n_ctx = CONTEXT_SIZE;
        context_settings.n_batch = BATCH_SIZE;
        context_settings.n_ubatch = UBATCH_SIZE;
        context_settings.n_seq_max = MAX_CANDIDATES + 1;
        context_settings.n_threads = threads;
        context_settings.n_threads_batch = threads;
        context_settings.offload_kqv = false;
        context_settings.flash_attn = true;
        context_settings.no_perf = true;
        model_context = llama_init_from_model(model, context_settings);
        if (model_context == NULL) die("the model state did not set up");
        batch = llama_batch_init(BATCH_SIZE, 0, 1);
    }

    fprintf(stdout, "ready vocabulary=%d start=%d space_tokens=%d space_token=%d\n", vocabulary, start, space_tokens,
            space_token);
    fflush(stdout);

    static char line[MAX_LINE];
    static llama_token tokens[MAX_LINE / 2];
    llama_token context_tokens[MAX_CONTEXT_TOKENS + 1];
    llama_token candidate_tokens[MAX_CANDIDATES][MAX_CANDIDATE_TOKENS];
    int candidate_lengths[MAX_CANDIDATES];
    int rows[MAX_CANDIDATES][MAX_CANDIDATE_TOKENS];
    long tokens_read = 0, highest_anon = rss_anon_kb();
    double model_ms = 0;

    while (fgets(line, sizeof line, stdin) != NULL) {
        size_t line_length = strcspn(line, "\r\n");
        if (line_length + 1 >= sizeof line) die("a request line is too long");
        line[line_length] = 0;
        char *fields[MAX_CANDIDATES + 1];
        int field_count = 0;
        char *cursor = line;
        for (;;) {
            if (field_count == MAX_CANDIDATES + 1) die("a request holds more candidates than the limit");
            fields[field_count++] = cursor;
            char *tab = strchr(cursor, '\t');
            if (tab == NULL) break;
            *tab = 0;
            cursor = tab + 1;
        }
        if (field_count < 2) die("a request needs a context and one candidate or more");
        const char *context = fields[0];
        int candidates = field_count - 1;

        /* The start token, then the last tokens of the context. */
        int context_count = 1;
        context_tokens[0] = start;
        if (context[0] != 0) {
            int count = tokenize(vocab, context, tokens, (int)(sizeof tokens / sizeof tokens[0]));
            int first = count > MAX_CONTEXT_TOKENS ? count - MAX_CONTEXT_TOKENS : 0;
            for (int index = first; index < count; index++) context_tokens[context_count++] = tokens[index];
        }
        for (int candidate = 0; candidate < candidates; candidate++) {
            char text[2048];
            snprintf(text, sizeof text, "%s%s", context[0] != 0 ? " " : "", fields[candidate + 1]);
            int count = tokenize(vocab, text, tokens, (int)(sizeof tokens / sizeof tokens[0]));
            if (count < 1) die("a candidate gives no token");
            if (count > MAX_CANDIDATE_TOKENS) die("a candidate gives more tokens than the limit");
            memcpy(candidate_tokens[candidate], tokens, sizeof(llama_token) * (size_t)count);
            candidate_lengths[candidate] = count;
        }

        if (tokens_only) {
            for (int index = 0; index < context_count; index++) printf("%s%d", index == 0 ? "" : " ", context_tokens[index]);
            for (int candidate = 0; candidate < candidates; candidate++) {
                printf("\t");
                for (int index = 0; index < candidate_lengths[candidate]; index++) {
                    printf("%s%d", index == 0 ? "" : " ", candidate_tokens[candidate][index]);
                }
            }
            printf("\n");
            fflush(stdout);
            continue;
        }

        double started = now_ms();
        llama_kv_cache_clear(model_context);
        batch.n_tokens = 0;
        for (int index = 0; index < context_count; index++) {
            add_token(&batch, context_tokens[index], index, 0, index == context_count - 1);
        }
        if (llama_decode(model_context, batch) != 0) die("the model did not read a context");
        const float *after_context = llama_get_logits_ith(model_context, context_count - 1);
        if (after_context == NULL) die("the model gave no scores after a context");
        double context_all = log_of_sum(after_context, vocabulary);
        double first_token[MAX_CANDIDATES];
        for (int candidate = 0; candidate < candidates; candidate++) {
            first_token[candidate] = (double)after_context[candidate_tokens[candidate][0]] - context_all;
        }
        tokens_read += context_count;

        /* Every candidate in one call, each in its own sequence after the context. */
        batch.n_tokens = 0;
        for (int candidate = 0; candidate < candidates; candidate++) {
            if (batch.n_tokens + candidate_lengths[candidate] > BATCH_SIZE) die("the candidates overflow one batch");
            llama_kv_cache_seq_cp(model_context, 0, candidate + 1, -1, -1);
            for (int index = 0; index < candidate_lengths[candidate]; index++) {
                rows[candidate][index] = batch.n_tokens;
                add_token(&batch, candidate_tokens[candidate][index], context_count + index, candidate + 1, 1);
            }
        }
        for (int index = 0; index < batch.n_tokens; index++) {
            if (batch.token[index] < 0 || batch.token[index] >= vocabulary) {
                fprintf(stderr, "lm_score: batch place %d of %d holds token %d\n", index, batch.n_tokens, batch.token[index]);
                die("a candidate batch holds a token outside the vocabulary");
            }
        }
        if (llama_decode(model_context, batch) != 0) die("the model did not read the candidates");
        tokens_read += batch.n_tokens;

        for (int candidate = 0; candidate < candidates; candidate++) {
            double total = first_token[candidate];
            int length = candidate_lengths[candidate];
            for (int index = 1; index < length; index++) {
                const float *scores = llama_get_logits_ith(model_context, rows[candidate][index - 1]);
                if (scores == NULL) die("the model gave no scores for a candidate");
                total += (double)scores[candidate_tokens[candidate][index]] - log_of_sum(scores, vocabulary);
            }
            const float *last = llama_get_logits_ith(model_context, rows[candidate][length - 1]);
            if (last == NULL) die("the model gave no scores after a candidate");
            double space_after = log_of_marked(last, vocabulary, space_first, log_of_sum(last, vocabulary));
            printf("%s%.5f %.5f", candidate == 0 ? "" : "\t", total, space_after);
        }
        printf("\n");
        fflush(stdout);
        model_ms += now_ms() - started;
        long anon = rss_anon_kb();
        if (anon > highest_anon) highest_anon = anon;
    }

    fprintf(stderr, "lm_score: %ld tokens read, %.1f ms in the model and the scores\n", tokens_read, model_ms);
    fprintf(stderr, "lm_score: highest RssAnon %ld kB\n", highest_anon);
    fprintf(stderr, "lm_score: %ld lone-space tokens put in place of -1\n", space_repairs);
    if (!tokens_only) {
        llama_batch_free(batch);
        llama_free(model_context);
    }
    llama_model_free(model);
    free(space_first);
    return 0;
}
