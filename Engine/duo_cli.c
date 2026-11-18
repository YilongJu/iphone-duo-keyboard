/*
 Runs the typing engine over many inputs, for the evaluation in scripts/typing-evaluation.

 Usage:
     duo_cli english LEXICON [supplement=FILE] [name=value ...] < input.tsv > output.tsv
     duo_cli pinyin  LEXICON [name=value ...] < input.tsv > output.tsv
     duo_cli predict LEXICON [supplement=FILE] [words=COUNT] [name=value ...] < input.tsv > output.tsv
     duo_cli predict-model LEXICON table=FILE next=FILE [supplement=FILE] [words=COUNT] [weight=W]
             [name=value ...] < input.tsv > output.tsv

 English input lines:  id <TAB> previous word (may be empty) <TAB> typed text
 Pinyin input lines:   id <TAB> typed letters
 Output lines:         id <TAB> the engine's text

 Predict input lines:  id <TAB> previous word (may be empty) <TAB> typed letters (may be empty)
 Predict output lines: id <TAB> the predicted words of duo_predict_english, most probable first,
                       with one space between them. words=COUNT sets how many, from 1 to 64,
                       and 20 without it.

 Predict-model input lines:  id <TAB> previous word <TAB> typed letters <TAB> 1 when only forms
                       with a capital are allowed, else 0 <TAB> the number of a next-token block
 Predict-model output lines: id <TAB> the words of duo_predict_english_with_model, each as
                       word/form, with one space between them. table=FILE is the word table of
                       scripts/typing-engine/build_word_table.py. next=FILE holds next-token
                       blocks one after the other, each one 32-bit float per token, as the mode
                       "next" of lm_score writes them. The first block has the number 0.
                       weight=W is the engine_weight, 0 without it.

 A name=value argument sets one field of duo_params, such as missing_space=4.5.
 The argument supplement=FILE lays the lexicon file FILE over the English lexicon as its
 supplement (duo_lexicon_set_supplement).

 After the last input the program writes one line to the error stream: the count of inputs and
 the processor time per input, without the time to load and check the lexicon.
 */
#include "duo_engine.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

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
    int with_model = argc >= 2 && strcmp(argv[1], "predict-model") == 0;
    int predict = with_model || (argc >= 2 && strcmp(argv[1], "predict") == 0);
    if (argc < 3 || (!predict && strcmp(argv[1], "english") != 0 && strcmp(argv[1], "pinyin") != 0)) {
        fprintf(stderr, "usage: duo_cli english|pinyin|predict|predict-model LEXICON [name=value ...]\n");
        return 2;
    }
    int english = predict || strcmp(argv[1], "english") == 0;
    int word_count = 20;
    duo_word_table table;
    void *table_data = NULL;
    int has_table = 0;
    FILE *next_file = NULL;
    float engine_weight = 0.0f;
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
        if (strcmp(argv[index], "supplement") == 0) {
            static duo_lexicon supplement;
            size_t supplement_size;
            void *supplement_data = read_file(equals + 1, &supplement_size);
            if (!english || supplement_data == NULL || !duo_lexicon_open(&supplement, supplement_data, supplement_size)
                || !duo_lexicon_set_supplement(&lexicon, &supplement)) {
                fprintf(stderr, "duo_cli: %s is not a valid supplement of %s\n", equals + 1, argv[2]);
                return 1;
            }
            continue;
        }
        if (with_model && strcmp(argv[index], "table") == 0) {
            size_t table_size;
            table_data = read_file(equals + 1, &table_size);
            if (table_data == NULL || !duo_word_table_open(&table, table_data, table_size)) {
                fprintf(stderr, "duo_cli: %s is not a valid word table\n", equals + 1);
                return 1;
            }
            has_table = 1;
            continue;
        }
        if (with_model && strcmp(argv[index], "next") == 0) {
            next_file = fopen(equals + 1, "rb");
            if (next_file == NULL) {
                fprintf(stderr, "duo_cli: cannot read %s\n", equals + 1);
                return 1;
            }
            continue;
        }
        if (with_model && strcmp(argv[index], "weight") == 0) {
            engine_weight = (float)atof(equals + 1);
            continue;
        }
        if (predict && strcmp(argv[index], "words") == 0) {
            word_count = atoi(equals + 1);
            if (word_count < 1 || word_count > 64) {
                fprintf(stderr, "duo_cli: words takes a count from 1 to 64, got %s\n", equals + 1);
                return 2;
            }
            continue;
        }
        if (!duo_params_set(&params, argv[index], (float)atof(equals + 1))) {
            fprintf(stderr, "duo_cli: unknown parameter %s\n", argv[index]);
            return 2;
        }
    }

    float *next = NULL;
    if (with_model) {
        if (!has_table || next_file == NULL) {
            fprintf(stderr, "duo_cli: predict-model needs table=FILE and next=FILE\n");
            return 2;
        }
        if (table.words_hash != duo_word_table_hash(&lexicon)) {
            fprintf(stderr, "duo_cli: the word table does not belong to this lexicon and supplement\n");
            return 1;
        }
        next = (float *)malloc(sizeof(float) * (size_t)table.vocabulary);
        if (next == NULL) return 1;
    }

    char line[4096];
    duo_result results[1];
    long inputs = 0;
    clock_t started = clock();
    while (fgets(line, sizeof line, stdin) != NULL) {
        inputs++;
        line[strcspn(line, "\r\n")] = 0;
        char *fields[5];
        int count = split_tabs(line, fields, with_model ? 5 : 3);
        if (with_model) {
            if (count != 5) {
                fprintf(stderr, "duo_cli: expected 5 fields: %s\n", line);
                return 1;
            }
            long block = atol(fields[4]);
            size_t block_bytes = sizeof(float) * (size_t)table.vocabulary;
            if (block < 0 || fseek(next_file, (long)((size_t)block * block_bytes), SEEK_SET) != 0
                || fread(next, sizeof(float), (size_t)table.vocabulary, next_file) != (size_t)table.vocabulary) {
                fprintf(stderr, "duo_cli: the next-token file has no block %ld\n", block);
                return 1;
            }
            duo_predicted_word words[64];
            int found = duo_predict_english_with_model(
                &lexicon, &params, &table, next, (int)table.vocabulary, engine_weight, fields[1], fields[2],
                atoi(fields[3]), words, word_count);
            printf("%s\t", fields[0]);
            for (int word = 0; word < found; word++) {
                printf(word == 0 ? "%s/%d" : " %s/%d", words[word].text, words[word].form);
            }
            printf("\n");
        } else if (predict) {
            if (count != 3) {
                fprintf(stderr, "duo_cli: expected 3 fields: %s\n", line);
                return 1;
            }
            duo_predicted_word words[64];
            int found = duo_predict_english(&lexicon, &params, fields[1], fields[2], words, word_count);
            printf("%s\t", fields[0]);
            for (int word = 0; word < found; word++) {
                printf(word == 0 ? "%s" : " %s", words[word].text);
            }
            printf("\n");
        } else if (english) {
            if (count != 3) {
                fprintf(stderr, "duo_cli: expected 3 fields: %s\n", line);
                return 1;
            }
            /* Text the engine does not accept, such as text with a capital, stays as typed. */
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
    double milliseconds = 1000.0 * (double)(clock() - started) / CLOCKS_PER_SEC;
    fprintf(stderr, "duo_cli: %ld inputs, %.3f ms of processor time per input\n", inputs, inputs > 0 ? milliseconds / (double)inputs : 0.0);
    if (next_file != NULL) fclose(next_file);
    free(next);
    free(table_data);
    free(data);
    return 0;
}
