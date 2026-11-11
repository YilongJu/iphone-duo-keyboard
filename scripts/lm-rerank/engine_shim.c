/*
 A small shared library over Engine/duo_engine.c for rerank.py, which loads it with ctypes.
 The library holds one English lexicon and the English parameters, so the Python side does not
 mirror the C structs.

 Build: gcc -std=c11 -O2 -shared -fPIC -I Engine Engine/duo_engine.c scripts/lm-rerank/engine_shim.c -o libduo_shim.so
 */
#include "duo_engine.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void *lexicon_bytes;
static duo_lexicon lexicon;
static void *supplement_bytes;
static duo_lexicon supplement;
static duo_params params;

/* Reads a whole file. Returns its bytes and sets `size`, or NULL. */
static void *read_file(const char *path, size_t *size) {
    FILE *file = fopen(path, "rb");
    if (file == NULL) return NULL;
    fseek(file, 0, SEEK_END);
    long length = ftell(file);
    fseek(file, 0, SEEK_SET);
    void *bytes = length > 0 ? malloc((size_t)length) : NULL;
    int read = bytes != NULL && fread(bytes, 1, (size_t)length, file) == (size_t)length;
    fclose(file);
    if (!read) {
        free(bytes);
        return NULL;
    }
    *size = (size_t)length;
    return bytes;
}

/* Opens the lexicon file with the full check. Returns 1, or 0 when the file is not valid. */
int shim_open(const char *path) {
    size_t size;
    lexicon_bytes = read_file(path, &size);
    if (lexicon_bytes == NULL) return 0;
    params = duo_english_params();
    return duo_lexicon_open(&lexicon, lexicon_bytes, size);
}

/* Lays the lexicon file `path` over the open lexicon as its supplement, after shim_open, with
   the full check. An empty path takes the supplement off. Returns 1, or 0 when the file is not
   a valid supplement. */
int shim_set_supplement(const char *path) {
    if (path == NULL || path[0] == 0) return duo_lexicon_set_supplement(&lexicon, NULL);
    size_t size;
    void *bytes = read_file(path, &size);
    static duo_lexicon opened;
    if (bytes == NULL || !duo_lexicon_open(&opened, bytes, size)) {
        free(bytes);
        return 0;
    }
    duo_lexicon_set_supplement(&lexicon, NULL);
    free(supplement_bytes);
    supplement_bytes = bytes;
    supplement = opened;
    return duo_lexicon_set_supplement(&lexicon, &supplement);
}

/* Lays the supplement that shim_set_supplement loaded over the lexicon (1) or takes it off (0),
   without reading the file again. Returns 1, or 0 when no supplement is loaded. */
int shim_use_supplement(int on) {
    if (supplement_bytes == NULL) return 0;
    return duo_lexicon_set_supplement(&lexicon, on ? &supplement : NULL);
}

/* Sets one English parameter by its field name, after shim_open. Returns 1, or 0 for an unknown name. */
int shim_set(const char *name, float value) {
    return duo_params_set(&params, name, value);
}

/* duo_correct_english. Writes the text into `out`. Returns 1, or 0 for input outside the engine. */
int shim_correct(const char *previous_word, const char *typed, char *out, int out_size) {
    duo_result result;
    if (!duo_correct_english(&lexicon, &params, previous_word, typed, &result)) return 0;
    snprintf(out, (size_t)out_size, "%s", result.text);
    return 1;
}

/* duo_english_readings. Writes one line per reading into `out`:
   text <TAB> score <TAB> slip cost <TAB> as typed (0 or 1) <TAB> chosen (0 or 1).
   Returns the count of readings, 0 for input outside the engine, or -1 when `out` is too small. */
int shim_readings(const char *previous_word, const char *typed, int capacity, char *out, int out_size) {
    duo_reading *readings = (duo_reading *)malloc(sizeof(duo_reading) * (size_t)capacity);
    if (readings == NULL) abort();
    int count = duo_english_readings(&lexicon, &params, previous_word, typed, readings, capacity);
    int used = 0;
    out[0] = 0;
    for (int index = 0; index < count; index++) {
        int wrote = snprintf(out + used, (size_t)(out_size - used), "%s\t%.6f\t%.6f\t%d\t%d\n", readings[index].text,
                             (double)readings[index].score, (double)readings[index].slip_cost,
                             readings[index].as_typed, readings[index].chosen);
        if (wrote < 0 || wrote >= out_size - used) {
            free(readings);
            return -1;
        }
        used += wrote;
    }
    free(readings);
    return count;
}
