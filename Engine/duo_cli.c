/*
 Runs the typing engine over many inputs, for the evaluation in scripts/typing-evaluation.

 Usage:
     duo_cli english LEXICON [name=value ...] < input.tsv > output.tsv
     duo_cli pinyin  LEXICON [name=value ...] < input.tsv > output.tsv

 English input lines:  id <TAB> previous word (may be empty) <TAB> typed text
 Pinyin input lines:   id <TAB> typed letters
 Output lines:         id <TAB> the engine's text

 A name=value argument sets one field of duo_params, such as missing_space=4.5.
 */
#include "duo_engine.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void *read_file(const char *path, size_t *size) {
    FILE *file = fopen(path, "rb");
    if (file == NULL) return NULL;
    fseek(file, 0, SEEK_END);
    long length = ftell(file);
    fseek(file, 0, SEEK_SET);
    void *data = length > 0 ? malloc((size_t)length) : NULL;
    if (data != NULL && fread(data, 1, (size_t)length, file) != (size_t)length) {
        free(data);
        data = NULL;
    }
    fclose(file);
    *size = data != NULL ? (size_t)length : 0;
    return data;
}

/* Cuts the line at its tabs. Returns the count of fields found, up to `capacity`. */
static int split_tabs(char *line, char **fields, int capacity) {
    int count = 0;
    char *cursor = line;
    while (count < capacity) {
        fields[count++] = cursor;
        char *tab = strchr(cursor, '\t');
        if (tab == NULL) break;
        *tab = 0;
        cursor = tab + 1;
    }
    return count;
}

int main(int argc, char **argv) {
    if (argc < 3 || (strcmp(argv[1], "english") != 0 && strcmp(argv[1], "pinyin") != 0)) {
        fprintf(stderr, "usage: duo_cli english|pinyin LEXICON [name=value ...]\n");
        return 2;
    }
    int english = strcmp(argv[1], "english") == 0;
    size_t size;
    void *data = read_file(argv[2], &size);
    duo_lexicon lexicon;
    if (data == NULL || !duo_lexicon_open(&lexicon, data, size)) {
        fprintf(stderr, "duo_cli: %s is not a valid lexicon file\n", argv[2]);
        return 1;
    }
    duo_params params = english ? duo_english_params() : duo_pinyin_params();
    for (int index = 3; index < argc; index++) {
        char *equals = strchr(argv[index], '=');
        if (equals == NULL) {
            fprintf(stderr, "duo_cli: expected name=value, got %s\n", argv[index]);
            return 2;
        }
        *equals = 0;
        if (!duo_params_set(&params, argv[index], (float)atof(equals + 1))) {
            fprintf(stderr, "duo_cli: unknown parameter %s\n", argv[index]);
            return 2;
        }
    }

    char line[4096];
    duo_result results[1];
    while (fgets(line, sizeof line, stdin) != NULL) {
        line[strcspn(line, "\r\n")] = 0;
        char *fields[3];
        int count = split_tabs(line, fields, 3);
        if (english) {
            if (count != 3) {
                fprintf(stderr, "duo_cli: expected 3 fields: %s\n", line);
                return 1;
            }
            /* Text the engine does not accept, such as text with a digit, stays as typed. */
            if (duo_correct_english(&lexicon, &params, fields[1], fields[2], &results[0])) {
                printf("%s\t%s\n", fields[0], results[0].text);
            } else {
                printf("%s\t%s\n", fields[0], fields[2]);
            }
        } else {
            if (count != 2) {
                fprintf(stderr, "duo_cli: expected 2 fields: %s\n", line);
                return 1;
            }
            if (duo_convert_pinyin(&lexicon, &params, fields[1], results, 1) >= 1) {
                printf("%s\t%s\n", fields[0], results[0].text);
            } else {
                printf("%s\t%s\n", fields[0], fields[1]);
            }
        }
    }
    free(data);
    return 0;
}
