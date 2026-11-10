/*
 The typing engine of Duo Keyboard.

 The engine reads the keys a person typed as a noisy signal. It looks at every way to read the
 keys as words from a lexicon, charges a cost for each slip that reading assumes (a neighbor key,
 a missing letter, a doubled letter, two swapped letters, a slip around the space bar), adds how
 probable the words are, alone and after the word before them, and returns the best reading.

 One code base serves both languages. English: the words are English words and a space separates
 them. Pinyin: the words are Chinese words spelled in Pinyin letters, and they follow each other
 with nothing between them.

 scripts/typing-engine/lexicon_format.py describes the lexicon file.
 */
#ifndef DUO_ENGINE_H
#define DUO_ENGINE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* The longest typed span the engine reads, in bytes. */
#define DUO_MAX_TYPED 120
/* Size of a result's text buffer, in bytes. A Chinese character takes 3 bytes. */
#define DUO_TEXT_SIZE 512

/* A lexicon file in memory. The engine reads the caller's bytes in place and does not copy them,
   so the bytes must stay valid while the lexicon is in use. */
typedef struct {
    const uint8_t *nodes;
    const uint8_t *words;
    const uint8_t *pair_index;
    const uint8_t *pairs;
    const uint8_t *strings;
    uint32_t node_count;
    uint32_t word_count;
    uint32_t pair_count;
    uint32_t strings_size;
    /* 0: a word's chance after another is a fixed blend of the pair statistic and the word's
       own probability. 1: a back-off model, where a listed pair gives the chance directly and
       an unlisted pair costs the first word's back-off weight plus the second word's own
       log probability. */
    uint32_t model;
} duo_lexicon;

/* Costs are in natural-log units, the same scale as the word probabilities: a cost of 4.6 makes
   a reading 100 times less likely. */
typedef struct {
    /* A letter typed on a key next to the intended key, and on a key farther away. */
    float adjacent_substitution;
    float far_substitution;
    /* A letter of the word that the person did not type. The second of a doubled letter and an
       apostrophe are skipped more often, so they cost less. */
    float omission;
    float omission_of_double;
    float omission_of_apostrophe;
    /* A typed letter that the word does not have. A letter typed twice costs less. */
    float insertion;
    float insertion_of_double;
    /* Two letters typed in the wrong order. */
    float transposition;
    /* Added to the cost of an extra letter before a word and of a missing first letter. People
       mistype the first letter of a word less often than the letters after it. */
    float first_letter_extra;
    /* The highest total slip cost inside one word: for words of 2 to 4 letters, and of 5 or more.
       A one-letter word must match exactly. */
    float short_word_budget;
    float long_word_budget;
    /* Slips around the space bar (English only). */
    float missing_space;      /* two words typed with nothing between them */
    float letter_for_space;   /* a letter from the row above the space bar typed in place of the space */
    float extra_space;        /* a space typed inside a word */
    float space_for_letter;   /* a space typed in place of a letter from the row above the space bar */
    float shifted_space;      /* a space typed one key early or one key late */
    /* Share of the word-pair statistic in a word's probability, from 0 to 1. A lexicon with a
       back-off model does not use this share. */
    float pair_weight;
    /* Log probability of text that is not in the lexicon: unknown_word + unknown_letter * letters. */
    float unknown_word;
    float unknown_letter;
    /* The best reading replaces the typed text only when it is more likely by this much:
       margin_known when every typed word is in the lexicon, margin_unknown otherwise. */
    float margin_known;
    float margin_unknown;
    /* How much the chance of ending the sentence after the last word counts, from 0 to 1.
       Only a lexicon with a sentence-end mark has that chance. */
    float sentence_end_weight;
    /* 1 when a space separates words (English), 0 when words follow each other directly (Pinyin). */
    int spaces_between_words;
    /* How many partial readings the search keeps at each position, from 1 to 16. */
    int beam;
} duo_params;

typedef struct {
    char text[DUO_TEXT_SIZE];
    /* Count of typed bytes that the text stands for. */
    int consumed;
    /* Log probability of the reading, slips included. */
    float score;
} duo_result;

/* Checks the bytes and fills `lexicon`. Returns 1 on success and 0 when the bytes are not a
   valid lexicon file. The check reads the whole file once. */
int duo_lexicon_open(duo_lexicon *lexicon, const void *data, size_t size);

/* Fills `lexicon` after a check of the header and the file size only. This is for a file that
   an earlier full check accepted, such as a file inside a signed app. It does not read the
   file's body, so a keyboard opens fast. Returns 1 on success and 0 on a wrong header or size. */
int duo_lexicon_open_checked_before(duo_lexicon *lexicon, const void *data, size_t size);

duo_params duo_english_params(void);
duo_params duo_pinyin_params(void);

/* Sets one parameter by its field name. Returns 1, or 0 for an unknown name. */
int duo_params_set(duo_params *params, const char *name, float value);

/* Reads typed English text and writes the text the person most likely meant.
   `typed` holds one or a few words in lower case: letters, apostrophes and single spaces.
   `previous_word` is the word before the typed text, in lower case, or an empty string.
   The result equals `typed` when no other reading is clearly more likely.
   Returns 1, or 0 when `typed` is empty, too long, or holds other characters. */
int duo_correct_english(
    const duo_lexicon *lexicon, const duo_params *params,
    const char *previous_word, const char *typed, duo_result *result);

/* Reads typed Pinyin letters and writes candidates into `results`.
   The first result is the most likely reading of all the letters. The results after it are
   words that stand for the first letters only, longest first, and `consumed` says how many
   letters each one covers. Returns the count of results written, or 0 for bad input. */
int duo_convert_pinyin(
    const duo_lexicon *lexicon, const duo_params *params,
    const char *typed, duo_result *results, int capacity);

#ifdef __cplusplus
}
#endif

#endif
