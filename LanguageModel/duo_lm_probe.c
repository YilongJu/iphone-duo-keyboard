/*
 The language model test of Duo Keyboard. duo_lm_probe.h describes the test and its result lines.

 The calls and the settings follow azooKey, a Japanese keyboard that runs models of this size
 through llama.cpp inside its keyboard extension: weights mapped from the file, the processor
 as the only device, a context of 512 tokens, and the stored state of a context reused for
 each candidate.
 */
#if !defined(__APPLE__)
/* Linux hides clock_gettime and sysconf from a C11 build without this line. */
#define _POSIX_C_SOURCE 200809L
#endif

#include "duo_lm_probe.h"

#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#if defined(__APPLE__)
#include <llama/llama.h>
#include <mach/mach.h>
#include <os/proc.h>
#include <sys/sysctl.h>
#else
#include "llama.h"
#endif

/* Count of tokens in the context that every measurement reads. */
#define CONTEXT_TOKENS 20
#define CANDIDATES 8
/* A candidate longer than this is cut, so every candidate holds 1 to 3 tokens. */
#define CANDIDATE_MAX_TOKENS 3
/* Count of tokens the per-token measurement reads after the context. */
#define FOLLOWING_TOKENS 200
/* The most tokens the model keeps in its state, as in azooKey. */
#define CONTEXT_SIZE 512
/* The most tokens one call hands to the model. The context and the candidates need 20 and 16. */
#define BATCH_CAPACITY 64
#define BYTES_PER_MB 1048576.0

/* 20 common words and one comma, which the GPT-2 vocabulary holds as one token each. */
static const char context_text[] =
    "I missed the early train this morning, so I think I will have to go to the office by";

static const char *const candidate_texts[CANDIDATES] = {
    " bus", " car", " taxi", " bike", " the subway", " the next train", " public transport", " my own car",
};

static const int thread_counts[] = {1, 2, 4};

typedef struct {
    duo_lm_line_fn emit;
    void *context;
} report_t;

#if defined(__GNUC__)
static void line(const report_t *report, const char *format, ...) __attribute__((format(printf, 2, 3)));
#endif

static void line(const report_t *report, const char *format, ...) {
    char text[640];
    va_list arguments;
    va_start(arguments, format);
    vsnprintf(text, sizeof text, format, arguments);
    va_end(arguments);
    report->emit(text, report->context);
}

static double now_ms(void) {
    struct timespec moment;
    clock_gettime(CLOCK_MONOTONIC, &moment);
    return (double)moment.tv_sec * 1000.0 + (double)moment.tv_nsec / 1e6;
}

/* The last error text of llama.cpp. A failed step reports it. */
static char last_error[200];

/* llama.cpp writes every message to the error stream unless a function takes the messages.
   This function keeps the last error and drops the rest. */
static void keep_last_error(enum ggml_log_level level, const char *text, void *user_data) {
    (void)user_data;
    if (level != GGML_LOG_LEVEL_ERROR || text == NULL) return;
    snprintf(last_error, sizeof last_error, "%s", text);
    size_t length = strlen(last_error);
    while (length > 0 && (last_error[length - 1] == '\n' || last_error[length - 1] == ' ')) {
        last_error[--length] = 0;
    }
}

/* Writes one line with the memory of the process at the named moment. */
static void memory_line(const report_t *report, const char *moment) {
#if defined(__APPLE__)
    task_vm_info_data_t info;
    mach_msg_type_number_t count = TASK_VM_INFO_COUNT;
    kern_return_t result = task_info(mach_task_self(), TASK_VM_INFO, (task_info_t)&info, &count);
    if (result != KERN_SUCCESS) {
        line(report, "memory      %s: failed, task_info returned %d", moment, (int)result);
        return;
    }
    line(report, "memory      %s: footprint %.1f MB, highest %.1f MB, still allowed %.1f MB", moment,
         (double)info.phys_footprint / BYTES_PER_MB, (double)info.ledger_phys_footprint_peak / BYTES_PER_MB,
         (double)os_proc_available_memory() / BYTES_PER_MB);
#else
    line(report, "memory      %s: not measured, this system is not iOS", moment);
#endif
}

/* Count of threads for the measurements that do not name one: the fast cores of an Apple
   processor, as in azooKey. A thread on a slow core holds back the threads on the fast cores. */
static int default_thread_count(const report_t *report) {
    long cores = sysconf(_SC_NPROCESSORS_ONLN);
    if (cores < 1) cores = 1;
#if defined(__APPLE__)
    int32_t fast_cores = 0;
    size_t size = sizeof fast_cores;
    if (sysctlbyname("hw.perflevel0.physicalcpu", &fast_cores, &size, NULL, 0) == 0
        && fast_cores > 0 && fast_cores <= cores) {
        line(report, "threads     %d (the fast cores, of %ld cores)", (int)fast_cores, cores);
        return (int)fast_cores;
    }
#endif
    int threads = cores < 4 ? (int)cores : 4;
    line(report, "threads     %d (count of fast cores not readable, %ld cores, 4 at most)", threads, cores);
    return threads;
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

/* Natural logarithm of the sum of e to the power of each score. A score less this value is
   the natural logarithm of that token's probability. */
static double log_of_sum(const float *scores, int vocabulary) {
    float highest = scores[0];
    for (int index = 1; index < vocabulary; index++) {
        if (scores[index] > highest) highest = scores[index];
    }
    double sum = 0;
    for (int index = 0; index < vocabulary; index++) {
        sum += exp((double)(scores[index] - highest));
    }
    return (double)highest + log(sum);
}

static llama_token most_likely(const float *scores, int vocabulary) {
    llama_token best = 0;
    for (int index = 1; index < vocabulary; index++) {
        if (scores[index] > scores[best]) best = index;
    }
    return best;
}

/* Empties the stored state, reads the context as sequence 0, and returns the scores of every
   token for the place after the context. Returns NULL when the model did not run. */
static const float *read_context(struct llama_context *model_context, struct llama_batch *batch,
                                 const llama_token *tokens) {
    llama_kv_cache_clear(model_context);
    batch->n_tokens = 0;
    for (int index = 0; index < CONTEXT_TOKENS; index++) {
        add_token(batch, tokens[index], index, 0, index == CONTEXT_TOKENS - 1);
    }
    if (llama_decode(model_context, *batch) != 0) return NULL;
    return llama_get_logits_ith(model_context, CONTEXT_TOKENS - 1);
}

typedef struct {
    llama_token tokens[CANDIDATES][CANDIDATE_MAX_TOKENS];
    int lengths[CANDIDATES];
    int token_total;
} candidates_t;

/* Adds the probability of each candidate's later tokens to `scores`, one candidate per call
   of the model. Sequence 0 holds the context, and each candidate goes in after the context
   and comes out again. Returns 0 when the model did not run. */
static int score_one_by_one(struct llama_context *model_context, struct llama_batch *batch, int vocabulary,
                            const candidates_t *candidates, double *scores) {
    for (int candidate = 0; candidate < CANDIDATES; candidate++) {
        int length = candidates->lengths[candidate];
        if (length == 1) continue;
        (void)llama_kv_cache_seq_rm(model_context, 0, CONTEXT_TOKENS, -1);
        batch->n_tokens = 0;
        for (int index = 0; index < length - 1; index++) {
            add_token(batch, candidates->tokens[candidate][index], CONTEXT_TOKENS + index, 0, 1);
        }
        if (llama_decode(model_context, *batch) != 0) return 0;
        for (int index = 1; index < length; index++) {
            const float *token_scores = llama_get_logits_ith(model_context, index - 1);
            if (token_scores == NULL) return 0;
            scores[candidate] += (double)token_scores[candidates->tokens[candidate][index]]
                - log_of_sum(token_scores, vocabulary);
        }
    }
    (void)llama_kv_cache_seq_rm(model_context, 0, CONTEXT_TOKENS, -1);
    return 1;
}

/* The same scores from one call of the model. Each candidate gets its own sequence that
   shares the stored state of the context. Returns 0 when the model did not run. */
static int score_in_one_batch(struct llama_context *model_context, struct llama_batch *batch, int vocabulary,
                              const candidates_t *candidates, double *scores) {
    int rows[CANDIDATES][CANDIDATE_MAX_TOKENS];
    batch->n_tokens = 0;
    for (int candidate = 0; candidate < CANDIDATES; candidate++) {
        int length = candidates->lengths[candidate];
        if (length == 1) continue;
        llama_kv_cache_seq_cp(model_context, 0, candidate + 1, -1, -1);
        for (int index = 0; index < length - 1; index++) {
            rows[candidate][index] = batch->n_tokens;
            add_token(batch, candidates->tokens[candidate][index], CONTEXT_TOKENS + index, candidate + 1, 1);
        }
    }
    int ran = batch->n_tokens == 0 || llama_decode(model_context, *batch) == 0;
    for (int candidate = 0; ran && candidate < CANDIDATES; candidate++) {
        for (int index = 1; index < candidates->lengths[candidate]; index++) {
            const float *token_scores = llama_get_logits_ith(model_context, rows[candidate][index - 1]);
            if (token_scores == NULL) {
                ran = 0;
                break;
            }
            scores[candidate] += (double)token_scores[candidates->tokens[candidate][index]]
                - log_of_sum(token_scores, vocabulary);
        }
    }
    for (int candidate = 0; candidate < CANDIDATES; candidate++) {
        if (candidates->lengths[candidate] > 1) (void)llama_kv_cache_seq_rm(model_context, candidate + 1, -1, -1);
    }
    return ran;
}

/* Copies the text of one token, with a question mark for each control character. */
static void token_text(const struct llama_vocab *vocab, llama_token token, char *text, size_t size) {
    char piece[48];
    int32_t length = llama_token_to_piece(vocab, token, piece, (int32_t)sizeof piece, 0, false);
    if (length < 0) length = 0;
    size_t count = 0;
    for (int32_t index = 0; index < length && count + 1 < size; index++) {
        unsigned char byte = (unsigned char)piece[index];
        text[count++] = byte < 0x20 || byte == 0x7F ? '?' : (char)byte;
    }
    text[count] = 0;
}

/* Reads the context once and scores the candidates both ways, with the thread count that the
   model context holds now. Returns 0 when the model did not run. */
static int measure_candidates(const report_t *report, struct llama_context *model_context,
                              struct llama_batch *batch, int vocabulary, const llama_token *context_tokens,
                              const candidates_t *candidates, const char *label) {
    double start = now_ms();
    const float *context_scores = read_context(model_context, batch, context_tokens);
    if (context_scores == NULL) {
        line(report, "candidates  %s: failed to read the context: %s", label, last_error);
        return 0;
    }
    double context_log_sum = log_of_sum(context_scores, vocabulary);
    double first[CANDIDATES], alone[CANDIDATES], together[CANDIDATES];
    for (int candidate = 0; candidate < CANDIDATES; candidate++) {
        first[candidate] = (double)context_scores[candidates->tokens[candidate][0]] - context_log_sum;
        alone[candidate] = first[candidate];
        together[candidate] = first[candidate];
    }
    double context_done = now_ms();
    if (!score_one_by_one(model_context, batch, vocabulary, candidates, alone)) {
        line(report, "candidates  %s: failed to score one by one: %s", label, last_error);
        return 0;
    }
    double alone_done = now_ms();
    if (!score_in_one_batch(model_context, batch, vocabulary, candidates, together)) {
        line(report, "candidates  %s: failed to score in one batch: %s", label, last_error);
        return 0;
    }
    double together_done = now_ms();

    int best = 0;
    double widest_gap = 0;
    for (int candidate = 0; candidate < CANDIDATES; candidate++) {
        if (alone[candidate] > alone[best]) best = candidate;
        double gap = fabs(alone[candidate] - together[candidate]);
        if (gap > widest_gap) widest_gap = gap;
    }
    line(report, "candidates  %s: context %.1f ms, then %d candidates of %d tokens: %.1f ms one by one, "
         "%.1f ms in one batch",
         label, context_done - start, CANDIDATES, candidates->token_total, alone_done - context_done,
         together_done - alone_done);
    line(report, "candidates  %s: most probable \"%s\" (log probability %.2f), the two ways differ by %.4f at most",
         label, candidate_texts[best] + 1, alone[best], widest_gap);
    return 1;
}

/* Reads the context and then 200 more tokens, one per call, each the most likely next token.
   Returns 0 when the model did not run. */
static int measure_per_token(const report_t *report, struct llama_context *model_context,
                             struct llama_batch *batch, int vocabulary, const llama_token *context_tokens,
                             const char *label) {
    const float *scores = read_context(model_context, batch, context_tokens);
    if (scores == NULL) {
        line(report, "per token   %s: failed to read the context: %s", label, last_error);
        return 0;
    }
    llama_token next = most_likely(scores, vocabulary);
    double total = 0, worst = 0;
    for (int index = 0; index < FOLLOWING_TOKENS; index++) {
        double start = now_ms();
        batch->n_tokens = 0;
        add_token(batch, next, CONTEXT_TOKENS + index, 0, 1);
        if (llama_decode(model_context, *batch) != 0 || (scores = llama_get_logits_ith(model_context, 0)) == NULL) {
            line(report, "per token   %s: failed at token %d: %s", label, index + 1, last_error);
            return 0;
        }
        next = most_likely(scores, vocabulary);
        double elapsed = now_ms() - start;
        total += elapsed;
        if (elapsed > worst) worst = elapsed;
    }
    line(report, "per token   %s: mean %.2f ms, worst %.2f ms over %d tokens", label, total / FOLLOWING_TOKENS,
         worst, FOLLOWING_TOKENS);
    return 1;
}

int duo_lm_measure(const char *model_path, duo_lm_line_fn emit, void *context) {
    report_t report_value = {emit, context};
    const report_t *report = &report_value;
    struct llama_model *model = NULL;
    struct llama_context *model_context = NULL;
    struct llama_batch batch;
    memset(&batch, 0, sizeof batch);
    int has_batch = 0;
    int passed = 0;

    struct stat file_info;
    if (stat(model_path, &file_info) != 0) {
        line(report, "model       failed: the file %s is not readable", model_path);
        line(report, "done        a step failed, see the line that says failed");
        return 0;
    }
    const char *slash = strrchr(model_path, '/');
    const char *file_name = slash != NULL ? slash + 1 : model_path;

    last_error[0] = 0;
    llama_log_set(keep_last_error, NULL);
    llama_backend_init();
    memory_line(report, "before load");

    /* The processor is the only device. A graphics processor is reported to stop a keyboard
       extension, and llama.cpp sets one up at the first use unless the device list leaves it out. */
    ggml_backend_dev_t devices[2] = {ggml_backend_dev_by_type(GGML_BACKEND_DEVICE_TYPE_CPU), NULL};
    if (devices[0] == NULL) {
        line(report, "load        failed: llama.cpp does not offer the processor as a device");
        goto finish;
    }
    struct llama_model_params model_settings = llama_model_default_params();
    model_settings.devices = devices;
    model_settings.n_gpu_layers = 0;
    model_settings.split_mode = LLAMA_SPLIT_MODE_NONE;
    /* The weights stay in the file. Pages that iOS reads from a file and that nobody changed
       do not count against the memory limit of the process. */
    model_settings.use_mmap = true;
    model_settings.use_mlock = false;

    double load_start = now_ms();
    model = llama_model_load_from_file(model_path, model_settings);
    double load_ms = now_ms() - load_start;
    if (model == NULL) {
        line(report, "load        failed: %s", last_error);
        goto finish;
    }
    const struct llama_vocab *vocab = llama_model_get_vocab(model);
    int vocabulary = llama_vocab_n_tokens(vocab);
    line(report, "model       %s, %.1f MB, %.1f million weights, %d tokens in the vocabulary", file_name,
         (double)file_info.st_size / BYTES_PER_MB, (double)llama_model_n_params(model) / 1e6, vocabulary);
    line(report, "load        %.0f ms", load_ms);
    memory_line(report, "after load");

    int threads = default_thread_count(report);
    struct llama_context_params context_settings = llama_context_default_params();
    context_settings.n_ctx = CONTEXT_SIZE;
    context_settings.n_batch = CONTEXT_SIZE;
    context_settings.n_ubatch = BATCH_CAPACITY;
    /* Each candidate of the one-batch measurement is its own sequence, beside the context. */
    context_settings.n_seq_max = CANDIDATES + 1;
    context_settings.n_threads = threads;
    context_settings.n_threads_batch = threads;
    context_settings.offload_kqv = false;
    context_settings.flash_attn = true;
    context_settings.no_perf = true;
    model_context = llama_init_from_model(model, context_settings);
    if (model_context == NULL) {
        line(report, "context     failed to set up the state of the model: %s", last_error);
        goto finish;
    }
    batch = llama_batch_init(BATCH_CAPACITY, 0, 1);
    has_batch = 1;
    memory_line(report, "after the model state is set up");

    llama_token text_tokens[64];
    int text_token_count = llama_tokenize(vocab, context_text, (int32_t)strlen(context_text), text_tokens, 64,
                                          false, false);
    if (text_token_count < CONTEXT_TOKENS) {
        line(report, "context     failed: the text gave %d tokens and the test needs %d", text_token_count,
             CONTEXT_TOKENS);
        goto finish;
    }
    candidates_t candidates;
    candidates.token_total = 0;
    for (int candidate = 0; candidate < CANDIDATES; candidate++) {
        llama_token tokens[16];
        const char *text = candidate_texts[candidate];
        int count = llama_tokenize(vocab, text, (int32_t)strlen(text), tokens, 16, false, false);
        if (count < 1) {
            line(report, "candidates  failed: \"%s\" gave %d tokens", text + 1, count);
            goto finish;
        }
        if (count > CANDIDATE_MAX_TOKENS) count = CANDIDATE_MAX_TOKENS;
        memcpy(candidates.tokens[candidate], tokens, (size_t)count * sizeof tokens[0]);
        candidates.lengths[candidate] = count;
        candidates.token_total += count;
    }

    double cold_start = now_ms();
    const float *scores = read_context(model_context, &batch, text_tokens);
    double cold_log_sum = scores != NULL ? log_of_sum(scores, vocabulary) : 0;
    double cold_ms = now_ms() - cold_start;
    if (scores == NULL) {
        line(report, "context     failed at the first run: %s", last_error);
        goto finish;
    }
    llama_token likely = most_likely(scores, vocabulary);
    double likely_probability = exp((double)scores[likely] - cold_log_sum);
    double warm_start = now_ms();
    scores = read_context(model_context, &batch, text_tokens);
    if (scores != NULL) (void)log_of_sum(scores, vocabulary);
    double warm_ms = now_ms() - warm_start;
    if (scores == NULL) {
        line(report, "context     failed at the second run: %s", last_error);
        goto finish;
    }
    char likely_text[64];
    token_text(vocab, likely, likely_text, sizeof likely_text);
    line(report, "context     %d tokens of %d in the text: cold %.1f ms, warm %.1f ms, most likely next token \"%s\" "
         "(probability %.2f)",
         CONTEXT_TOKENS, text_token_count, cold_ms, warm_ms, likely_text, likely_probability);
    memory_line(report, "after the first scoring");

    passed = 1;
    for (size_t index = 0; index < sizeof thread_counts / sizeof thread_counts[0]; index++) {
        char label[32];
        snprintf(label, sizeof label, "%d thread%s", thread_counts[index], thread_counts[index] == 1 ? "" : "s");
        llama_set_n_threads(model_context, thread_counts[index], thread_counts[index]);
        if (!measure_per_token(report, model_context, &batch, vocabulary, text_tokens, label)
            || !measure_candidates(report, model_context, &batch, vocabulary, text_tokens, &candidates, label)) {
            passed = 0;
            break;
        }
    }
    memory_line(report, "at the end, model still loaded");

finish:
    if (has_batch) llama_batch_free(batch);
    if (model_context != NULL) llama_free(model_context);
    if (model != NULL) llama_model_free(model);
    memory_line(report, "after the model is freed");
    line(report, passed ? "done        every step ran" : "done        a step failed, see the line that says failed");
    return passed;
}
