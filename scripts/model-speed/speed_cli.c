/*
 The speed test of docs/model-speed-design.md on a desktop or a Mac, with the keyboard's scorer
 (LanguageModel/duo_lm_scorer.c) and the reuse mode of the keyboard: the anchored window with two
 slots.

 Usage:
   speed_cli MODEL.gguf THREADS cpu|gpu REQUESTS.tsv OUT
       Loads the model, reads every request of REQUESTS.tsv in order, and writes:
         OUT.summary   one line "key value" per fact: load time, memory, first request
         OUT.times     one line per request: window tokens, reused tokens, ms of the window
                       calls, ms of the candidate calls, ms of the whole request
         OUT.answers   one line per request: log probability and space after of each candidate,
                       17 significant digits, as kv_replay of scripts/kv-reuse writes them
   speed_cli MODEL.gguf THREADS tokens REQUESTS.tsv OUT
       Writes OUT.tokens: per request one line "start TAB context tokens TAB candidate 1 tokens
       TAB ...", each a list of numbers with spaces. A runtime without a tokenizer of its own reads
       these tokens (scripts/model-speed/coreml).

 A request line is "context TAB candidate 1 TAB candidate 2 ...", the protocol of kv_replay. A
 candidate follows the context after one space, or right after the start token when the context
 is empty.
 */
#if !defined(__APPLE__)
#define _POSIX_C_SOURCE 200809L
#endif

#include "duo_lm_scorer.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#if defined(__APPLE__)
#include <mach/mach.h>
#endif

#define MAX_LINE 65536
#define MAX_TOKENS 4096

static double now_milliseconds(void) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (double)now.tv_sec * 1000.0 + (double)now.tv_nsec / 1e6;
}

/* The memory of this process in MB: the footprint on a Mac, the resident set on Linux. */
static double memory_mb(void) {
#if defined(__APPLE__)
    task_vm_info_data_t info;
    mach_msg_type_number_t count = TASK_VM_INFO_COUNT;
    if (task_info(mach_task_self(), TASK_VM_INFO, (task_info_t)&info, &count) != KERN_SUCCESS) {
        fprintf(stderr, "speed_cli: task_info failed\n");
        exit(1);
    }
    return (double)info.phys_footprint / 1048576.0;
#else
    FILE *status = fopen("/proc/self/status", "r");
    if (status == NULL) {
        fprintf(stderr, "speed_cli: cannot read /proc/self/status\n");
        exit(1);
    }
    char line[256];
    double kilobytes = -1;
    while (fgets(line, sizeof line, status) != NULL) {
        if (strncmp(line, "VmRSS:", 6) == 0) kilobytes = strtod(line + 6, NULL);
    }
    fclose(status);
    if (kilobytes < 0) {
        fprintf(stderr, "speed_cli: /proc/self/status has no VmRSS line\n");
        exit(1);
    }
    return kilobytes / 1024.0;
#endif
}

static const char *memory_name(void) {
#if defined(__APPLE__)
    return "footprint";
#else
    return "resident";
#endif
}

static int usage(void) {
    fprintf(stderr, "usage: speed_cli MODEL.gguf THREADS cpu|gpu|tokens REQUESTS.tsv OUT\n");
    return 2;
}

static FILE *open_out(const char *out, const char *suffix) {
    char path[4096];
    snprintf(path, sizeof path, "%s.%s", out, suffix);
    FILE *file = fopen(path, "w");
    if (file == NULL) {
        fprintf(stderr, "speed_cli: cannot write %s\n", path);
        exit(1);
    }
    return file;
}

/* Splits a request line in place. Returns the count of candidates, or -1 for a bad line. */
static int split_request(char *line, const char **context, char texts[DUO_LM_MAX_CANDIDATES][4096],
                         const char *candidates[DUO_LM_MAX_CANDIDATES]) {
    char *fields[DUO_LM_MAX_CANDIDATES + 1];
    int field_count = 0;
    char *cursor = line;
    for (;;) {
        if (field_count == DUO_LM_MAX_CANDIDATES + 1) return -1;
        fields[field_count++] = cursor;
        char *tab = strchr(cursor, '\t');
        if (tab == NULL) break;
        *tab = 0;
        cursor = tab + 1;
    }
    if (field_count < 2) return -1;
    *context = fields[0];
    int count = field_count - 1;
    for (int candidate = 0; candidate < count; candidate++) {
        snprintf(texts[candidate], 4096, "%s%s", fields[0][0] != 0 ? " " : "", fields[candidate + 1]);
        candidates[candidate] = texts[candidate];
    }
    return count;
}

static void write_tokens(FILE *file, const int *tokens, int count) {
    for (int index = 0; index < count; index++) fprintf(file, "%s%d", index == 0 ? "" : " ", tokens[index]);
}

int main(int argc, char **argv) {
    if (argc != 6) return usage();
    const char *model = argv[1];
    int threads = atoi(argv[2]);
    const char *mode = argv[3];
    const char *out = argv[5];
    int tokens_mode = strcmp(mode, "tokens") == 0;
    duo_lm_device device;
    if (strcmp(mode, "cpu") == 0 || tokens_mode) {
        device = DUO_LM_DEVICE_CPU;
    } else if (strcmp(mode, "gpu") == 0) {
        device = DUO_LM_DEVICE_GPU;
    } else {
        return usage();
    }
    FILE *requests = fopen(argv[4], "r");
    if (requests == NULL) {
        fprintf(stderr, "speed_cli: cannot read %s\n", argv[4]);
        return 1;
    }

    duo_lm_reuse reuse = {DUO_LM_REUSE_ANCHOR, 2};
    char error[DUO_LM_ERROR_SIZE];
    double before_load = memory_mb();
    double started = now_milliseconds();
    duo_lm_scorer *scorer = duo_lm_scorer_open_on(model, threads, reuse, device, error, sizeof error);
    double load = now_milliseconds() - started;
    if (scorer == NULL) {
        fprintf(stderr, "speed_cli: %s\n", error);
        return 1;
    }
    double after_load = memory_mb();

    static char line[MAX_LINE];
    static char texts[DUO_LM_MAX_CANDIDATES][4096];
    const char *candidates[DUO_LM_MAX_CANDIDATES];
    const char *context;
    long requests_done = 0;

    if (tokens_mode) {
        FILE *tokens_file = open_out(out, "tokens");
        static int tokens[MAX_TOKENS];
        while (fgets(line, sizeof line, requests) != NULL) {
            line[strcspn(line, "\r\n")] = 0;
            int count = split_request(line, &context, texts, candidates);
            if (count < 0) {
                fprintf(stderr, "speed_cli: request %ld is not a context and 1 to %d candidates\n", requests_done + 1,
                        DUO_LM_MAX_CANDIDATES);
                return 1;
            }
            fprintf(tokens_file, "%d\t", duo_lm_scorer_start_token(scorer));
            int found = duo_lm_scorer_tokenize(scorer, context, tokens, MAX_TOKENS, error, sizeof error);
            if (found < 0) {
                fprintf(stderr, "speed_cli: request %ld, context: %s\n", requests_done + 1, error);
                return 1;
            }
            write_tokens(tokens_file, tokens, found);
            for (int candidate = 0; candidate < count; candidate++) {
                found = duo_lm_scorer_tokenize(scorer, candidates[candidate], tokens, MAX_TOKENS, error, sizeof error);
                if (found < 1) {
                    fprintf(stderr, "speed_cli: request %ld, candidate %d: %s\n", requests_done + 1, candidate,
                            found < 0 ? error : "no token");
                    return 1;
                }
                fputc('\t', tokens_file);
                write_tokens(tokens_file, tokens, found);
            }
            fputc('\n', tokens_file);
            requests_done++;
        }
        fclose(tokens_file);
        duo_lm_scorer_close(scorer);
        printf("wrote the tokens of %ld requests\n", requests_done);
        return 0;
    }

    FILE *times = open_out(out, "times");
    FILE *answers = open_out(out, "answers");
    double first_request = 0, highest = after_load;
    while (fgets(line, sizeof line, requests) != NULL) {
        line[strcspn(line, "\r\n")] = 0;
        int count = split_request(line, &context, texts, candidates);
        if (count < 0) {
            fprintf(stderr, "speed_cli: request %ld is not a context and 1 to %d candidates\n", requests_done + 1,
                    DUO_LM_MAX_CANDIDATES);
            return 1;
        }
        duo_lm_scorer_info before = duo_lm_scorer_get_info(scorer);
        double request_started = now_milliseconds();
        duo_lm_score scores[DUO_LM_MAX_CANDIDATES];
        int result = duo_lm_scorer_score(scorer, context, candidates, count, scores, error, sizeof error);
        double total = now_milliseconds() - request_started;
        if (result != 1) {
            fprintf(stderr, "speed_cli: request %ld gave %d: %s\n", requests_done + 1, result, error);
            return 1;
        }
        if (requests_done == 0) first_request = total;
        duo_lm_scorer_info after = duo_lm_scorer_get_info(scorer);
        fprintf(times, "%ld %ld %.4f %.4f %.4f\n", after.window_tokens - before.window_tokens,
                after.window_tokens_reused - before.window_tokens_reused,
                after.window_milliseconds - before.window_milliseconds,
                after.candidate_milliseconds - before.candidate_milliseconds, total);
        for (int candidate = 0; candidate < count; candidate++) {
            fprintf(answers, "%s%.17g %.17g", candidate == 0 ? "" : "\t", scores[candidate].log_probability,
                    scores[candidate].space_after);
        }
        fputc('\n', answers);
        double memory = memory_mb();
        if (memory > highest) highest = memory;
        requests_done++;
    }
    fclose(times);
    fclose(answers);
    duo_lm_scorer_info info = duo_lm_scorer_get_info(scorer);
    FILE *summary = open_out(out, "summary");
    fprintf(summary, "model %s\n", model);
    fprintf(summary, "device %s\n", mode);
    fprintf(summary, "threads %d\n", threads);
    fprintf(summary, "load_ms %.3f\n", load);
    fprintf(summary, "memory_kind %s\n", memory_name());
    fprintf(summary, "memory_before_load_mb %.1f\n", before_load);
    fprintf(summary, "memory_after_load_mb %.1f\n", after_load);
    fprintf(summary, "memory_highest_mb %.1f\n", highest);
    fprintf(summary, "first_request_ms %.3f\n", first_request);
    fprintf(summary, "requests %ld\n", requests_done);
    fprintf(summary, "vocabulary %d\n", info.vocabulary);
    fprintf(summary, "tokens_read %ld\n", info.tokens_read);
    fprintf(summary, "window_tokens %ld\n", info.window_tokens);
    fprintf(summary, "window_tokens_reused %ld\n", info.window_tokens_reused);
    fclose(summary);
    duo_lm_scorer_close(scorer);
    printf("speed_cli: %ld requests, load %.1f ms, first request %.1f ms\n", requests_done, load, first_request);
    return 0;
}
