/*
 Checks duo_english_readings against duo_correct_english on many inputs. Build it with the
 memory checks of the compiler, as the evaluation workflow builds the engine.

 Usage: readings_check LEXICON < input.tsv
 Input lines, as for Engine/duo_cli.c: id <TAB> previous word <TAB> typed text

 For each input the check asks for 8 readings and for 2 readings, and stops with exit code 1
 when a list breaks a rule: a refused input that the other function reads, a count outside
 1 to the capacity, the chosen reading that differs from duo_correct_english, no single
 reading as typed and no single chosen reading, a score out of order, a text twice, or a slip
 cost below 0.
 */
#include "duo_engine.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int fail(const char *id, const char *rule) {
    printf("readings_check: %s breaks the rule: %s\n", id, rule);
    return 1;
}

static int check(const duo_lexicon *lexicon, const duo_params *params, const char *id, const char *previous,
                 const char *typed, int capacity, long *total) {
    duo_result result;
    duo_reading readings[8];
    int corrected = duo_correct_english(lexicon, params, previous, typed, &result);
    int count = duo_english_readings(lexicon, params, previous, typed, readings, capacity);
    if (!corrected) return count == 0 ? 0 : fail(id, "duo_english_readings reads an input that duo_correct_english refuses");
    if (count < 1 || count > capacity) return fail(id, "the count is outside 1 to the capacity");
    int chosen = 0, as_typed = 0;
    for (int index = 0; index < count; index++) {
        if (readings[index].chosen) {
            chosen++;
            if (strcmp(readings[index].text, result.text) != 0) return fail(id, "the chosen reading differs from duo_correct_english");
        }
        if (readings[index].as_typed) {
            as_typed++;
            if (strcmp(readings[index].text, typed) != 0) return fail(id, "the reading as typed differs from the input");
        }
        if (readings[index].slip_cost < 0.0f) return fail(id, "a slip cost is below 0");
        for (int other = 0; other < index; other++) {
            if (strcmp(readings[index].text, readings[other].text) == 0) return fail(id, "a text appears twice");
        }
        /* A list cut at the capacity can hold the two kept readings out of order at its end. */
        if (index > 0 && count < capacity && readings[index].score > readings[index - 1].score) {
            return fail(id, "the scores are out of order");
        }
    }
    if (chosen != 1 || as_typed != 1) return fail(id, "the list needs one chosen reading and one reading as typed");
    *total += count;
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: readings_check LEXICON < input.tsv\n");
        return 2;
    }
    FILE *file = fopen(argv[1], "rb");
    if (file == NULL) return 1;
    fseek(file, 0, SEEK_END);
    long length = ftell(file);
    fseek(file, 0, SEEK_SET);
    void *data = malloc((size_t)length);
    if (data == NULL || fread(data, 1, (size_t)length, file) != (size_t)length) return 1;
    fclose(file);
    duo_lexicon lexicon;
    if (!duo_lexicon_open(&lexicon, data, (size_t)length)) return 1;
    duo_params params = duo_english_params();

    char line[4096];
    long inputs = 0, readings = 0;
    while (fgets(line, sizeof line, stdin) != NULL) {
        line[strcspn(line, "\r\n")] = 0;
        char *first_tab = strchr(line, '\t');
        char *second_tab = first_tab != NULL ? strchr(first_tab + 1, '\t') : NULL;
        if (second_tab == NULL) {
            fprintf(stderr, "readings_check: expected 3 fields: %s\n", line);
            return 1;
        }
        *first_tab = 0;
        *second_tab = 0;
        inputs++;
        if (check(&lexicon, &params, line, first_tab + 1, second_tab + 1, 8, &readings)) return 1;
        long ignored = 0;
        if (check(&lexicon, &params, line, first_tab + 1, second_tab + 1, 2, &ignored)) return 1;
    }
    printf("readings_check: %ld inputs, %.2f readings per input at a capacity of 8, every rule held\n", inputs,
           inputs > 0 ? (double)readings / (double)inputs : 0.0);
    free(data);
    return 0;
}
