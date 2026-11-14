/*
 Tests of the reuse of the cache in LanguageModel/duo_lm_scorer.c on Linux, the same cases as
 Tests/LanguageModelCacheTests.swift. The contexts are the texts that LanguageModelPrompt.make
 and makeStock build for the keyboard.

 Usage: cache_test MODEL.gguf none|prefix|shift|anchor SLOTS
 Prints one line per test and exits with 1 when a test fails. With the mode none, which reads
 every request from an empty cache as the scorer did before the reuse, the test of the reuse
 fails. Every request runs with the check of the cache at the tolerance 0.
 */
#define _POSIX_C_SOURCE 200809L

#include "duo_lm_scorer.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static duo_lm_scorer *scorer;
static int failures;

static void score(const char *context, const char *const *candidates, int count, int expected) {
    duo_lm_score scores[DUO_LM_MAX_CANDIDATES];
    char error[DUO_LM_ERROR_SIZE];
    int result = duo_lm_scorer_score(scorer, context, candidates, count, scores, error, sizeof error);
    if (result != expected) {
        printf("  request \"%s\" gave %d, expected %d: %s\n", context, result, expected, result == 1 ? "" : error);
        failures++;
    }
}

#define SCORE(context, ...)                                                                      \
    do {                                                                                         \
        const char *list[] = {__VA_ARGS__};                                                      \
        score(context, list, (int)(sizeof list / sizeof list[0]), 1);                            \
    } while (0)

static void report(const char *name, int before) {
    printf("%s %s\n", failures == before ? "pass" : "FAIL", name);
}

int main(int argc, char **argv) {
    if (argc != 4) {
        fprintf(stderr, "usage: cache_test MODEL.gguf none|prefix|shift|anchor SLOTS\n");
        return 2;
    }
    duo_lm_reuse reuse = {DUO_LM_REUSE_NONE, atoi(argv[3])};
    if (strcmp(argv[2], "prefix") == 0) reuse.mode = DUO_LM_REUSE_PREFIX;
    else if (strcmp(argv[2], "shift") == 0) reuse.mode = DUO_LM_REUSE_SHIFT;
    else if (strcmp(argv[2], "anchor") == 0) reuse.mode = DUO_LM_REUSE_ANCHOR;
    else if (strcmp(argv[2], "none") != 0) return 2;
    char error[DUO_LM_ERROR_SIZE];
    scorer = duo_lm_scorer_open(argv[1], 2, reuse, error, sizeof error);
    if (scorer == NULL || !duo_lm_scorer_set_check(scorer, 0, error, sizeof error)) {
        fprintf(stderr, "cache_test: %s\n", error);
        return 1;
    }

    /* The next space press reads only the tokens after the shared start. */
    int before = failures;
    SCORE("I missed the early train this morning, so I think I will have to go to the office | by bys |", " by bus",
          " by bys", " by buys");
    duo_lm_scorer_info first = duo_lm_scorer_get_info(scorer);
    SCORE("I missed the early train this morning, so I think I will have to go to the office by bus | and then |",
          " and then", " and than");
    duo_lm_scorer_info second = duo_lm_scorer_get_info(scorer);
    long reused = second.window_tokens_reused - first.window_tokens_reused;
    long window = second.window_tokens - first.window_tokens;
    if (!(reused > 15 && reused <= window - 2)) {
        printf("  %ld of %ld window tokens came from the cache, expected more than 15 and at most %ld\n", reused, window,
               window - 2);
        failures++;
    }
    report("the next space press reads only the tokens after the shared start", before);

    /* The events of the keyboard, each checked against a fresh read. */
    before = failures;
    SCORE("We met at the station and walked to the old bridge | aftre |", " after", " aftre", " afire");
    SCORE("We met at the station and walked to the old bridge after | lunch we |", " lunch we", " lunch wee");
    SCORE("We met at the station and walked to the old bridge afire | lunch we |", " lunch we", " lunch wee");
    SCORE("We met at the station and walked to the old bridge after lunch", " we're", " were");
    SCORE("We met at the station and walked to the old bridge after lunch | were going |", " we're going",
          " were going");
    SCORE("We met at the station and | walkde |", " walked", " walkde");
    SCORE("We met at | teh |", " the", " teh", " tech");
    SCORE("We met at the station. The train was late again, as it is most days in the winter, and the people on "
          "the platform stood close together to keep warm while they waited | for th |",
          " for the", " for th", " for tho");
    SCORE("Dear Anna, thank you for your | lettr |", " letter", " lettr");
    SCORE("Dear Anna,\nthank you for your | lettr |", " letter", " lettr");
    SCORE("| helo |", " Hello", " Helo", " Help");
    SCORE("Hello | tehre |", " there", " tehre");
    report("the events of the keyboard give the numbers of a fresh read", before);

    /* A window that moves: more than 96 tokens before the span. */
    before = failures;
    char text[4096] = "";
    for (int sentence = 0; sentence < 12; sentence++) {
        char part[128];
        snprintf(part, sizeof part, "On day %d we walked along the river and talked about the weather. ", sentence);
        strcat(text, part);
    }
    const char *words[] = {"then", "we", "took", "the", "bus", "home"};
    for (int index = 0; index < 6; index++) {
        char context[4200], typo[64], right[64];
        snprintf(context, sizeof context, "%s| %sx |", text, words[index]);
        snprintf(right, sizeof right, " %s", words[index]);
        snprintf(typo, sizeof typo, " %sx", words[index]);
        SCORE(context, right, typo);
        strcat(text, words[index]);
        strcat(text, " ");
    }
    report("a window that moves gives the numbers of a fresh read", before);

    /* A refused request leaves the cache ready. */
    before = failures;
    SCORE("The meeting starts at nine and ends at | tne |", " ten", " tne");
    char long_candidate[200] = " ";
    for (int index = 0; index < 60; index++) strcat(long_candidate, "zq");
    const char *refused[] = {long_candidate};
    score("The meeting starts at nine and ends at | tne |", refused, 1, 0);
    duo_lm_scorer_info third = duo_lm_scorer_get_info(scorer);
    SCORE("The meeting starts at nine and ends at ten | in teh |", " in the", " in teh");
    duo_lm_scorer_info fourth = duo_lm_scorer_get_info(scorer);
    if (!(fourth.window_tokens_reused - third.window_tokens_reused > 5)) {
        printf("  %ld window tokens came from the cache after the refused request, expected more than 5\n",
               fourth.window_tokens_reused - third.window_tokens_reused);
        failures++;
    }
    report("a refused request leaves the cache ready", before);

    duo_lm_scorer_info info = duo_lm_scorer_get_info(scorer);
    printf("%s, %d slots: %ld requests, %ld checked, widest difference %.17g, %ld of %ld window tokens reused\n",
           argv[2], reuse.slots, info.requests, info.checked_requests, info.checked_widest, info.window_tokens_reused,
           info.window_tokens);
    duo_lm_scorer_close(scorer);
    return failures == 0 ? 0 : 1;
}
