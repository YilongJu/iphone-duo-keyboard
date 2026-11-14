/*
 The keyboard's scorer (LanguageModel/duo_lm_scorer.c) with a reuse mode of the cache, behind
 the request protocol of scripts/lm-rerank/lm_score.c, for the replay of scripts/kv-reuse.

 Usage: kv_replay MODEL.gguf THREADS MODE SLOTS DECIMALS [check TOLERANCE] [times FILE]
   MODE        none, prefix, shift or anchor (duo_lm_reuse_mode of duo_lm_scorer.h)
   SLOTS       1 or 2
   DECIMALS    5 for the answers of lm_score.c, or 17 for 17 significant digits
   check       turns on duo_lm_scorer_set_check with TOLERANCE, a number or "inf"
   times FILE  writes one line per request: the tokens of the window, the tokens the cache
               kept, the milliseconds of the window calls, of the candidate calls, and of the
               whole request

 The program first writes one line that starts with "ready", as lm_score.c does, so
 scripts/lm-rerank/rerank.py can start it as its scorer.

 Request line:  context <TAB> candidate 1 <TAB> candidate 2 ...
 Answer line:   log probability 1 <SPACE> space after 1 <TAB> ...
 A candidate follows the context after one space, or right after the start token when the
 context is empty, as in lm_score.c.
 */
#define _POSIX_C_SOURCE 200809L

#include "duo_lm_scorer.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define MAX_LINE 65536

static double now_milliseconds(void) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (double)now.tv_sec * 1000.0 + (double)now.tv_nsec / 1e6;
}

static int usage(void) {
    fprintf(stderr, "usage: kv_replay MODEL.gguf THREADS none|prefix|shift|anchor SLOTS 5|17 [check TOLERANCE] [times FILE]\n");
    return 2;
}

int main(int argc, char **argv) {
    if (argc < 6) return usage();
    duo_lm_reuse reuse;
    if (strcmp(argv[3], "none") == 0) {
        reuse.mode = DUO_LM_REUSE_NONE;
    } else if (strcmp(argv[3], "prefix") == 0) {
        reuse.mode = DUO_LM_REUSE_PREFIX;
    } else if (strcmp(argv[3], "shift") == 0) {
        reuse.mode = DUO_LM_REUSE_SHIFT;
    } else if (strcmp(argv[3], "anchor") == 0) {
        reuse.mode = DUO_LM_REUSE_ANCHOR;
    } else {
        return usage();
    }
    reuse.slots = atoi(argv[4]);
    int decimals = atoi(argv[5]);
    if (decimals != 5 && decimals != 17) return usage();
    int check = 0;
    double tolerance = 0;
    FILE *times = NULL;
    for (int index = 6; index < argc; index += 2) {
        if (index + 1 >= argc) return usage();
        if (strcmp(argv[index], "check") == 0) {
            char *end;
            tolerance = strtod(argv[index + 1], &end);
            if (*end != 0) return usage();
            check = 1;
        } else if (strcmp(argv[index], "times") == 0) {
            times = fopen(argv[index + 1], "w");
            if (times == NULL) {
                fprintf(stderr, "kv_replay: cannot write %s\n", argv[index + 1]);
                return 1;
            }
        } else {
            return usage();
        }
    }

    char error[DUO_LM_ERROR_SIZE];
    duo_lm_scorer *scorer = duo_lm_scorer_open(argv[1], atoi(argv[2]), reuse, error, sizeof error);
    if (scorer == NULL) {
        fprintf(stderr, "kv_replay: %s\n", error);
        return 1;
    }
    if (check && !duo_lm_scorer_set_check(scorer, tolerance, error, sizeof error)) {
        fprintf(stderr, "kv_replay: %s\n", error);
        return 1;
    }
    printf("ready kv_replay %s %d slots\n", argv[3], reuse.slots);
    fflush(stdout);

    static char line[MAX_LINE];
    static char texts[DUO_LM_MAX_CANDIDATES][4096];
    long requests = 0;
    while (fgets(line, sizeof line, stdin) != NULL) {
        size_t length = strcspn(line, "\r\n");
        if (length + 1 >= sizeof line) {
            fprintf(stderr, "kv_replay: a request line is too long\n");
            return 1;
        }
        line[length] = 0;
        char *fields[DUO_LM_MAX_CANDIDATES + 1];
        int field_count = 0;
        char *cursor = line;
        for (;;) {
            if (field_count == DUO_LM_MAX_CANDIDATES + 1) {
                fprintf(stderr, "kv_replay: a request holds more than %d candidates\n", DUO_LM_MAX_CANDIDATES);
                return 1;
            }
            fields[field_count++] = cursor;
            char *tab = strchr(cursor, '\t');
            if (tab == NULL) break;
            *tab = 0;
            cursor = tab + 1;
        }
        if (field_count < 2) {
            fprintf(stderr, "kv_replay: a request needs a context and one candidate or more\n");
            return 1;
        }
        const char *context = fields[0];
        int count = field_count - 1;
        const char *candidates[DUO_LM_MAX_CANDIDATES];
        for (int candidate = 0; candidate < count; candidate++) {
            snprintf(texts[candidate], sizeof texts[candidate], "%s%s", context[0] != 0 ? " " : "",
                     fields[candidate + 1]);
            candidates[candidate] = texts[candidate];
        }
        duo_lm_scorer_info before = duo_lm_scorer_get_info(scorer);
        double started = now_milliseconds();
        duo_lm_score scores[DUO_LM_MAX_CANDIDATES];
        int result = duo_lm_scorer_score(scorer, context, candidates, count, scores, error, sizeof error);
        double total = now_milliseconds() - started;
        if (result != 1) {
            fprintf(stderr, "kv_replay: request %ld gave %d: %s\n", requests + 1, result, error);
            return 1;
        }
        duo_lm_scorer_info after = duo_lm_scorer_get_info(scorer);
        if (times != NULL) {
            fprintf(times, "%ld %ld %.4f %.4f %.4f\n", after.window_tokens - before.window_tokens,
                    after.window_tokens_reused - before.window_tokens_reused,
                    after.window_milliseconds - before.window_milliseconds,
                    after.candidate_milliseconds - before.candidate_milliseconds, total);
        }
        for (int candidate = 0; candidate < count; candidate++) {
            if (decimals == 17) {
                printf("%s%.17g %.17g", candidate == 0 ? "" : "\t", scores[candidate].log_probability,
                       scores[candidate].space_after);
            } else {
                printf("%s%.5f %.5f", candidate == 0 ? "" : "\t", scores[candidate].log_probability,
                       scores[candidate].space_after);
            }
        }
        printf("\n");
        fflush(stdout);
        requests++;
    }
    duo_lm_scorer_info info = duo_lm_scorer_get_info(scorer);
    fprintf(stderr,
            "kv_replay: %s, %d slots, %ld requests, %ld tokens read, %ld of %ld window tokens reused, "
            "%ld requests checked, widest difference %.17g\n",
            argv[3], reuse.slots, info.requests, info.tokens_read, info.window_tokens_reused, info.window_tokens,
            info.checked_requests, info.checked_widest);
    if (times != NULL) fclose(times);
    duo_lm_scorer_close(scorer);
    return 0;
}
