/*
 The keyboard's scorer (LanguageModel/duo_lm_scorer.c) behind the request protocol of
 scripts/lm-rerank/lm_score.c, so both programs can read the same requests on Linux and their
 answers can be compared byte for byte.

 Usage: scorer_cli MODEL.gguf THREADS [full] [prefix|shift|anchor] [slots2] [check] [next] [long FILE] < requests > answers

 Request line:  context <TAB> candidate 1 <TAB> candidate 2 ...
 Answer line:   log probability 1 <SPACE> space after 1 <TAB> ...

 As in lm_score.c, a candidate follows the context after one space, or right after the start
 token when the context is empty, and each number has 5 decimals. With the word "full" each
 number has 17 significant digits instead. Without a reuse mode the scorer reads every request
 from an empty cache. The words "prefix", "shift" and "anchor" give the reuse modes of
 duo_lm_scorer.h, with one slot, or two slots with the word "slots2". With the word "check" the
 scorer also reads every request again from an empty cache and stops on any difference in the
 numbers. With "long FILE" the program writes the line number of each request whose context holds
 more than 96 tokens into FILE, one per line, counted from 1.

 With the word "next", a request line that holds a context and no candidate gets no answer line.
 The program writes the next-token block of duo_lm_scorer_next in its place, as the mode "next"
 of lm_score.c does: one 32-bit float per token of the vocabulary, in the byte order of the
 machine and with no line break.
 */
#define _POSIX_C_SOURCE 200809L

#include "duo_lm_scorer.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_LINE 65536

int main(int argc, char **argv) {
    int full = 0, check = 0, next = 0;
    FILE *long_lines = NULL;
    duo_lm_reuse reuse = {DUO_LM_REUSE_NONE, 1};
    int valid = argc >= 3;
    for (int index = 3; index < argc && valid; index++) {
        if (strcmp(argv[index], "long") == 0 && index + 1 < argc && long_lines == NULL) {
            long_lines = fopen(argv[++index], "w");
            if (long_lines == NULL) {
                fprintf(stderr, "scorer_cli: cannot write %s\n", argv[index]);
                return 1;
            }
        } else if (strcmp(argv[index], "full") == 0) {
            full = 1;
        } else if (strcmp(argv[index], "prefix") == 0) {
            reuse.mode = DUO_LM_REUSE_PREFIX;
        } else if (strcmp(argv[index], "shift") == 0) {
            reuse.mode = DUO_LM_REUSE_SHIFT;
        } else if (strcmp(argv[index], "anchor") == 0) {
            reuse.mode = DUO_LM_REUSE_ANCHOR;
        } else if (strcmp(argv[index], "slots2") == 0) {
            reuse.slots = 2;
        } else if (strcmp(argv[index], "check") == 0) {
            check = 1;
        } else if (strcmp(argv[index], "next") == 0) {
            next = 1;
        } else {
            valid = 0;
        }
    }
    if (!valid) {
        fprintf(stderr, "usage: scorer_cli MODEL.gguf THREADS [full] [prefix|shift|anchor] [slots2] [check] [next] [long FILE]\n");
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
    /* The numbers of one next-token block. */
    int vocabulary = duo_lm_scorer_get_info(scorer).vocabulary;
    float *next_scores = NULL;
    if (next) {
        next_scores = (float *)malloc(sizeof(float) * (size_t)vocabulary);
        if (next_scores == NULL) {
            fprintf(stderr, "scorer_cli: out of memory\n");
            return 1;
        }
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
        if (field_count < 2 && !next) {
            fprintf(stderr, "scorer_cli: a request needs a context and one candidate or more\n");
            return 1;
        }
        const char *context = fields[0];
        int count = field_count - 1;
        if (count == 0) {
            long long_before = duo_lm_scorer_get_info(scorer).long_contexts;
            int result = duo_lm_scorer_next(scorer, context, next_scores, vocabulary, error, sizeof error);
            if (long_lines != NULL && duo_lm_scorer_get_info(scorer).long_contexts != long_before) {
                fprintf(long_lines, "%ld\n", requests + 1);
            }
            if (result != 1) {
                fprintf(stderr, "scorer_cli: request %ld gave %d: %s\n", requests + 1, result, error);
                return 1;
            }
            if (fwrite(next_scores, sizeof(float), (size_t)vocabulary, stdout) != (size_t)vocabulary) {
                fprintf(stderr, "scorer_cli: a next-token block did not go out\n");
                return 1;
            }
            fflush(stdout);
            requests++;
            continue;
        }
        const char *candidates[DUO_LM_MAX_CANDIDATES];
        for (int candidate = 0; candidate < count; candidate++) {
            snprintf(texts[candidate], sizeof texts[candidate], "%s%s", context[0] != 0 ? " " : "",
                     fields[candidate + 1]);
            candidates[candidate] = texts[candidate];
        }
        duo_lm_score scores[DUO_LM_MAX_CANDIDATES];
        long long_before = duo_lm_scorer_get_info(scorer).long_contexts;
        int result = duo_lm_scorer_score(scorer, context, candidates, count, scores, error, sizeof error);
        if (long_lines != NULL && duo_lm_scorer_get_info(scorer).long_contexts != long_before) {
            fprintf(long_lines, "%ld\n", requests + 1);
        }
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
        fprintf(stderr, "scorer_cli: %ld requests with a context of more than %d tokens\n", info.long_contexts,
                DUO_LM_MAX_CONTEXT_TOKENS);
    }
    if (long_lines != NULL) fclose(long_lines);
    free(next_scores);
    duo_lm_scorer_close(scorer);
    return 0;
}
