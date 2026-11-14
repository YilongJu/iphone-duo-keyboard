/*
 The keyboard's scorer (LanguageModel/duo_lm_scorer.c) behind the request protocol of
 scripts/lm-rerank/lm_score.c, so both programs can read the same requests on Linux and their
 answers can be compared byte for byte.

 Usage: scorer_cli MODEL.gguf THREADS [full] [prefix] [check] < requests > answers

 Request line:  context <TAB> candidate 1 <TAB> candidate 2 ...
 Answer line:   log probability 1 <SPACE> space after 1 <TAB> ...

 As in lm_score.c, a candidate follows the context after one space, or right after the start
 token when the context is empty, and each number has 5 decimals. With the word "full" each
 number has 17 significant digits instead. Without the word "prefix" the scorer reads every
 request from an empty cache. With it the scorer reuses the cache of the request before
 (DUO_LM_REUSE_PREFIX of duo_lm_scorer.h, one slot). With the word "check" the scorer also reads
 every request again from an empty cache and stops on any difference in the numbers.
 */
#define _POSIX_C_SOURCE 200809L

#include "duo_lm_scorer.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_LINE 65536

int main(int argc, char **argv) {
    int full = 0, check = 0;
    duo_lm_reuse reuse = {DUO_LM_REUSE_NONE, 1};
    int valid = argc >= 3;
    for (int index = 3; index < argc && valid; index++) {
        if (strcmp(argv[index], "full") == 0) {
            full = 1;
        } else if (strcmp(argv[index], "prefix") == 0) {
            reuse.mode = DUO_LM_REUSE_PREFIX;
        } else if (strcmp(argv[index], "check") == 0) {
            check = 1;
        } else {
            valid = 0;
        }
    }
    if (!valid) {
        fprintf(stderr, "usage: scorer_cli MODEL.gguf THREADS [full] [prefix] [check]\n");
        return 2;
    }
    char error[DUO_LM_ERROR_SIZE];
    duo_lm_scorer *scorer = duo_lm_scorer_open(argv[1], atoi(argv[2]), reuse, error, sizeof error);
    if (scorer == NULL) {
        fprintf(stderr, "scorer_cli: %s\n", error);
        return 1;
    }
    if (check && !duo_lm_scorer_set_check(scorer, 0, error, sizeof error)) {
        fprintf(stderr, "scorer_cli: %s\n", error);
        return 1;
    }
    static char line[MAX_LINE];
    static char texts[DUO_LM_MAX_CANDIDATES][4096];
    long requests = 0;
    while (fgets(line, sizeof line, stdin) != NULL) {
        size_t length = strcspn(line, "\r\n");
        if (length + 1 >= sizeof line) {
            fprintf(stderr, "scorer_cli: a request line is too long\n");
            return 1;
        }
        line[length] = 0;
        char *fields[DUO_LM_MAX_CANDIDATES + 1];
        int field_count = 0;
        char *cursor = line;
        for (;;) {
            if (field_count == DUO_LM_MAX_CANDIDATES + 1) {
                fprintf(stderr, "scorer_cli: a request holds more than %d candidates\n", DUO_LM_MAX_CANDIDATES);
                return 1;
            }
            fields[field_count++] = cursor;
            char *tab = strchr(cursor, '\t');
            if (tab == NULL) break;
            *tab = 0;
            cursor = tab + 1;
        }
        if (field_count < 2) {
            fprintf(stderr, "scorer_cli: a request needs a context and one candidate or more\n");
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
        duo_lm_score scores[DUO_LM_MAX_CANDIDATES];
        int result = duo_lm_scorer_score(scorer, context, candidates, count, scores, error, sizeof error);
        if (result != 1) {
            fprintf(stderr, "scorer_cli: request %ld gave %d: %s\n", requests + 1, result, error);
            return 1;
        }
        for (int candidate = 0; candidate < count; candidate++) {
            if (full) {
                printf("%s%.17g %.17g", candidate == 0 ? "" : "\t", scores[candidate].log_probability,
                       scores[candidate].space_after);
            } else {
                printf("%s%.5f %.5f", candidate == 0 ? "" : "\t", scores[candidate].log_probability,
                       scores[candidate].space_after);
            }
        }
        printf("\n");
        requests++;
    }
    duo_lm_scorer_info info = duo_lm_scorer_get_info(scorer);
    fprintf(stderr, "scorer_cli: start token %d, %ld requests, %ld tokens read, %ld space and %ld line break tokens put in place of -1\n",
            info.start_token, info.requests, info.tokens_read, info.space_repairs, info.line_break_repairs);
    if (reuse.mode != DUO_LM_REUSE_NONE || check) {
        fprintf(stderr, "scorer_cli: %ld of %ld window tokens reused, %ld requests checked, widest difference %.17g\n",
                info.window_tokens_reused, info.window_tokens, info.checked_requests, info.checked_widest);
    }
    duo_lm_scorer_close(scorer);
    return 0;
}
