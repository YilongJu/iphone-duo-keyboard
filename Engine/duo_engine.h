/*
 The typing engine of Duo Keyboard.

 The engine reads the keys a person typed as a noisy signal. It looks at every way to read the
 keys as words from a lexicon, charges a cost for each slip that reading assumes (a neighbor key,
 a missing letter, a doubled letter, two swapped letters, a slip around the space bar), adds how
 probable the words are, alone and after the one or two words before them, and returns the best
 reading.

 In English a neighbor key can also be a symbol or digit key: "[lease" reads as "please" and
 "2hat" as "what". Such a key stands only for a letter beside it. The engine never drops it,
 so punctuation that a person typed on purpose stays in the text.

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
typedef struct duo_lexicon {
    const uint8_t *nodes;
    const uint8_t *words;
    const uint8_t *pair_index;
    const uint8_t *pairs;
    const uint8_t *contexts;
    const uint8_t *triples;
    const uint8_t *strings;
    uint32_t node_count;
    uint32_t word_count;
    uint32_t pair_count;
    /* Count of the pairs that open one or more triples, and count of the triples. Both are 0 in
       a file of version 2. */
    uint32_t context_count;
    uint32_t triple_count;
    uint32_t strings_size;
    /* 0: a word's chance after another is a fixed blend of the pair statistic and the word's
       own probability. 1: a back-off model. A listed triple gives the chance of its third word
       after the two words before it. Without a listed triple the chance is the back-off weight
       of those two words as a pair plus the chance after the one word before, and that chance
       is a listed pair's value, or the back-off weight of the word before plus the word's own
       log probability. */
    uint32_t model;
    /* The version of the file format, 2 or 3, and the size of one word record in that version. */
    uint32_t version;
    uint32_t word_bytes;
    /* A supplement: a second, small lexicon whose words the engine reads beside the words of
       this one, or NULL. duo_lexicon_set_supplement sets it. */
    const struct duo_lexicon *supplement;
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
    /* Added once to the cost of every word that the search reads with one or more slips. Most
       typed words do not hold a slip, and this cost states that share. */
    float slipped_word;
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
    /* A symbol or digit key that a person typed on purpose (English only). A key right before a
       word, as in "[note", ".net" and "-ish", and a digit right after a word, as in "mp3". Each
       cost states how seldom people type that key there on purpose. The text as typed is read
       as the word with this cost when the lexicon holds the word, and the reading that takes
       the key for a slip must be more likely than that. */
    float bracket_before_word;
    float dot_before_word;
    float comma_before_word;
    float semicolon_before_word;
    float dash_before_word;
    float digit_before_word;
    float digit_after_word;
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
    /* How much a word's reading cost counts when a listed pair or triple gives the word's
       chance, from 0 to 1. A Chinese word with several Pinyin readings has a cost for each
       reading, the log of that reading's share. A word's own probability always holds the cost. */
    float reading_cost_weight;
    /* 1 when a space separates words (English), 0 when words follow each other directly (Pinyin). */
    int spaces_between_words;
    /* How many partial readings the search keeps at each position, from 1 to 64. */
    int beam;
    /* 1 adds to duo_english_readings the readings that differ from the typed text in one
       apostrophe of one word, such as "it's going" for "its going". 0 leaves them out. The
       choice of duo_correct_english is the same either way. */
    int apostrophe_readings;
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

/* Lays a supplement over an English lexicon: a small lexicon file of words that the main file
   lacks or holds at too low a probability, such as the words of a work area or the words a
   person taught the keyboard. The engine then reads a word of the supplement as a known word:
   it stays as typed, and a slip can be corrected into it. A word that only the supplement holds
   has no word pairs, so it gets its own probability after any word, as a word of the main file
   without a listed pair does. A word that both files hold gets the higher of its two values.
   A word of the supplement never joins typed words that are all known words: "hard coded" stays
   two words, also when the supplement holds "hardcoded". NULL takes the supplement off again.

   Both files must use model 0 (the mixed model of English), and the supplement must be a file
   of version 2 without word pairs, with one word per spelling and no supplement of its own.
   The supplement's bytes must stay valid while the lexicon uses it. Returns 1, or 0 when a file
   does not meet these rules, and the lexicon then keeps the supplement it had. */
int duo_lexicon_set_supplement(duo_lexicon *lexicon, const duo_lexicon *supplement);

duo_params duo_english_params(void);
duo_params duo_pinyin_params(void);

/* Sets one parameter by its field name. Returns 1, or 0 for an unknown name. */
int duo_params_set(duo_params *params, const char *name, float value);

/* Reads typed English text and writes the text the person most likely meant.
   `typed` holds one or a few words in lower case: letters, apostrophes and single spaces.
   A word of two or more letters may also hold one symbol or digit key that sits beside a
   letter key: a digit or "[" at any place, or one of "-" ";" "," "." in front of the word.
   `previous_word` is the word before the typed text, in lower case, or an empty string.
   The result equals `typed` when no other reading is clearly more likely.
   Returns 1, or 0 when `typed` is empty, too long, or holds other characters. */
int duo_correct_english(
    const duo_lexicon *lexicon, const duo_params *params,
    const char *previous_word, const char *typed, duo_result *result);

/* One reading of typed English text, for a caller that ranks the readings itself. */
typedef struct {
    char text[DUO_TEXT_SIZE];
    /* Log probability of the reading, slips included, on the scale that duo_correct_english
       compares. The text as typed has the score of its words read exactly as typed. */
    float score;
    /* The part of the score that the assumed slips cost, as a positive number: the channel
       cost. The rest, score + slip_cost, is the lexicon's log probability of the words, with
       the price of text kept as typed and of a symbol key typed on purpose. */
    float slip_cost;
    /* 1 for the text exactly as typed. */
    int as_typed;
    /* 1 for the reading that duo_correct_english returns for the same input. */
    int chosen;
} duo_reading;

/* Writes the readings of typed English text that the search keeps, best score first, into
   `readings`: the text as typed, and for each search (the text as typed and each shifted space)
   the best reading for each last word, up to the beam. The same text appears once, at its
   best score. A list cut at `capacity` still holds the text as typed and the chosen reading.
   The input rules and the choice are those of duo_correct_english, which this function does
   not change. Returns the count written, or 0 for bad input or a capacity under 2. */
int duo_english_readings(
    const duo_lexicon *lexicon, const duo_params *params,
    const char *previous_word, const char *typed, duo_reading *readings, int capacity);

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
