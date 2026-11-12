#include "duo_engine.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

#define DUO_MAGIC 0x4C4F5544u
/* A file of version 2 holds words and word pairs. A file of version 3 adds a reading cost to
   each word, a back-off weight to each pair, and word triples. */
#define VERSION_PAIRS 2u
#define VERSION_TRIPLES 3u
#define MODEL_BACK_OFF 1u
#define NODE_BYTES 12
#define PAIR_BYTES 8
#define CONTEXT_BYTES 8
#define TRIPLE_BYTES 4
/* Version 3 stores the two numbers of a pair in 16 bits each, in steps of 1/2048. A triple is
   one 32-bit number: its third word in the low 20 bits and its log probability in the high 12
   bits, in steps of 1/256. Bit 31 of a pair's second word marks a pair that opens triples. */
#define PAIR_STEPS 2048.0f
#define TRIPLE_STEPS 256.0f
#define TRIPLE_WORD_BITS 20
#define TRIPLE_WORD_MASK 0x000FFFFFu
#define PAIR_OPENS_TRIPLES 0x80000000u

/* The most slips the search follows inside one word. */
#define BAND 2
#define ROW (2 * BAND + 1)
/* The longest spelling the search follows, in letters. */
#define MAX_DEPTH 64
#define MAX_BEAM 64
#define MAX_EDGES 4096
#define BIG 1.0e9f

/* Marks a state with no lexicon word: the start of the text, or text kept as typed. */
#define NO_WORD 0xFFFFFFFFu
/* Marks a state whose last two words are not a pair that a later word depends on. */
#define NO_PAIR 0xFFFFFFFFu
/* Set in the number of a word that only the supplement holds. The rest of the number is the
   word's place in the supplement's word table. */
#define SUPPLEMENT_BIT 0x40000000u

/* ---- Reading the lexicon bytes ---- */

static uint32_t read_u32(const uint8_t *bytes) {
    uint32_t value;
    memcpy(&value, bytes, 4);
    return value;
}

static uint16_t read_u16(const uint8_t *bytes) {
    uint16_t value;
    memcpy(&value, bytes, 2);
    return value;
}

static int16_t read_i16(const uint8_t *bytes) {
    int16_t value;
    memcpy(&value, bytes, 2);
    return value;
}

static float read_f32(const uint8_t *bytes) {
    float value;
    memcpy(&value, bytes, 4);
    return value;
}

typedef struct {
    uint32_t first_child;
    uint32_t first_word;
    uint32_t child_count;
    uint32_t word_count;
    uint8_t letter;
} node_t;

static node_t node_at(const duo_lexicon *lexicon, uint32_t index) {
    const uint8_t *bytes = lexicon->nodes + NODE_BYTES * (size_t)index;
    node_t node;
    node.first_child = read_u32(bytes);
    node.first_word = read_u32(bytes + 4);
    node.child_count = bytes[8];
    node.letter = bytes[9];
    node.word_count = read_u16(bytes + 10);
    return node;
}

static char node_letter(const duo_lexicon *lexicon, uint32_t index) {
    return (char)lexicon->nodes[NODE_BYTES * (size_t)index + 9];
}

static const uint8_t *word_record(const duo_lexicon *lexicon, uint32_t word) {
    return lexicon->words + (size_t)lexicon->word_bytes * word;
}

/* A word's own log probability. For a word with several readings it holds the reading cost. */
static float word_log_probability(const duo_lexicon *lexicon, uint32_t word) {
    return read_f32(word_record(lexicon, word) + 4);
}

static float word_back_off(const duo_lexicon *lexicon, uint32_t word) {
    return read_f32(word_record(lexicon, word) + 8);
}

/* The log of the share of this reading among the readings of the word's text. A file of
   version 2 does not hold it, and the cost is 0. */
static float word_reading_cost(const duo_lexicon *lexicon, uint32_t word) {
    return lexicon->version == VERSION_TRIPLES ? read_f32(word_record(lexicon, word) + 12) : 0.0f;
}

static const char *word_text(const duo_lexicon *lexicon, uint32_t word) {
    return (const char *)lexicon->strings + read_u32(word_record(lexicon, word));
}

/* The position of a word's first pair. The pairs of a word end where the next word's start. */
static uint32_t pair_start(const duo_lexicon *lexicon, uint32_t word) {
    return read_u32(lexicon->pair_index + 4 * (size_t)word);
}

static uint32_t pair_second(const duo_lexicon *lexicon, uint32_t pair) {
    uint32_t second = read_u32(lexicon->pairs + PAIR_BYTES * (size_t)pair);
    return lexicon->version == VERSION_TRIPLES ? second & ~PAIR_OPENS_TRIPLES : second;
}

static float pair_log_probability(const duo_lexicon *lexicon, uint32_t pair) {
    const uint8_t *bytes = lexicon->pairs + PAIR_BYTES * (size_t)pair + 4;
    return lexicon->version == VERSION_TRIPLES ? -(float)read_u16(bytes) / PAIR_STEPS : read_f32(bytes);
}

/* The back-off weight of a pair: the cost of a third word that has no listed triple with the
   pair. A file of version 2 does not hold triples, and the weight is 0. */
static float pair_back_off(const duo_lexicon *lexicon, uint32_t pair) {
    if (lexicon->version != VERSION_TRIPLES) return 0.0f;
    return (float)read_i16(lexicon->pairs + PAIR_BYTES * (size_t)pair + 6) / PAIR_STEPS;
}

/* Whether the chance of a later word depends on this pair: the pair opens triples, or it has a
   back-off weight. Two readings that end in the same word, and in pairs for which this is 0,
   go on the same way. */
static int pair_matters_later(const duo_lexicon *lexicon, uint32_t pair) {
    if (lexicon->version != VERSION_TRIPLES) return 0;
    const uint8_t *bytes = lexicon->pairs + PAIR_BYTES * (size_t)pair;
    return (read_u32(bytes) & PAIR_OPENS_TRIPLES) != 0 || read_i16(bytes + 6) != 0;
}

static uint32_t triple_word(const duo_lexicon *lexicon, uint32_t triple) {
    return read_u32(lexicon->triples + TRIPLE_BYTES * (size_t)triple) & TRIPLE_WORD_MASK;
}

static float triple_log_probability(const duo_lexicon *lexicon, uint32_t triple) {
    uint32_t steps = read_u32(lexicon->triples + TRIPLE_BYTES * (size_t)triple) >> TRIPLE_WORD_BITS;
    return -(float)steps / TRIPLE_STEPS;
}

/* Finds the triples that a pair opens: the positions `first` up to `end` in the triple table.
   A pair that opens no triple gives an empty run. */
static void triples_of_pair(const duo_lexicon *lexicon, uint32_t pair, uint32_t *first, uint32_t *end) {
    *first = 0;
    *end = 0;
    uint32_t low = 0, high = lexicon->context_count;
    while (low < high) {
        uint32_t middle = low + (high - low) / 2;
        const uint8_t *row = lexicon->contexts + CONTEXT_BYTES * (size_t)middle;
        uint32_t found = read_u32(row);
        if (found == pair) {
            *first = read_u32(row + 4);
            *end = read_u32(row + CONTEXT_BYTES + 4);
            return;
        }
        if (found < pair) low = middle + 1;
        else high = middle;
    }
}

int duo_lexicon_open_checked_before(duo_lexicon *lexicon, const void *data, size_t size) {
    const uint8_t *bytes = (const uint8_t *)data;
    if (lexicon == NULL || data == NULL || size < 32) return 0;
    if (read_u32(bytes) != DUO_MAGIC) return 0;
    uint32_t version = read_u32(bytes + 4);
    if (version != VERSION_PAIRS && version != VERSION_TRIPLES) return 0;
    /* Version 2 has a header of 8 numbers. Version 3 has 10: the count of pairs that open
       triples and the count of triples follow the model, and the last number is 0. */
    size_t header = version == VERSION_TRIPLES ? 40 : 32;
    if (size < header) return 0;
    uint32_t node_count = read_u32(bytes + 8);
    uint32_t word_count = read_u32(bytes + 12);
    uint32_t strings_size = read_u32(bytes + 16);
    uint32_t pair_count = read_u32(bytes + 20);
    uint32_t model = read_u32(bytes + 24);
    uint32_t context_count = version == VERSION_TRIPLES ? read_u32(bytes + 28) : 0;
    uint32_t triple_count = version == VERSION_TRIPLES ? read_u32(bytes + 32) : 0;
    uint32_t word_bytes = version == VERSION_TRIPLES ? 16 : 12;
    if (model > MODEL_BACK_OFF) return 0;
    uint64_t expected = (uint64_t)header + (uint64_t)node_count * NODE_BYTES + (uint64_t)word_count * word_bytes
        + ((uint64_t)word_count + 1) * 4 + (uint64_t)pair_count * PAIR_BYTES + (uint64_t)strings_size;
    if (version == VERSION_TRIPLES) {
        expected += ((uint64_t)context_count + 1) * CONTEXT_BYTES + (uint64_t)triple_count * TRIPLE_BYTES;
    }
    if (node_count == 0 || expected != (uint64_t)size) return 0;

    lexicon->node_count = node_count;
    lexicon->word_count = word_count;
    lexicon->pair_count = pair_count;
    lexicon->context_count = context_count;
    lexicon->triple_count = triple_count;
    lexicon->strings_size = strings_size;
    lexicon->model = model;
    lexicon->version = version;
    lexicon->word_bytes = word_bytes;
    lexicon->nodes = bytes + header;
    lexicon->words = lexicon->nodes + (size_t)node_count * NODE_BYTES;
    lexicon->pair_index = lexicon->words + (size_t)word_count * word_bytes;
    lexicon->pairs = lexicon->pair_index + ((size_t)word_count + 1) * 4;
    lexicon->contexts = lexicon->pairs + (size_t)pair_count * PAIR_BYTES;
    lexicon->triples = lexicon->contexts;
    if (version == VERSION_TRIPLES) lexicon->triples += ((size_t)context_count + 1) * CONTEXT_BYTES;
    lexicon->strings = lexicon->triples + (size_t)triple_count * TRIPLE_BYTES;
    lexicon->supplement = NULL;
    return 1;
}

int duo_lexicon_open(duo_lexicon *lexicon, const void *data, size_t size) {
    if (!duo_lexicon_open_checked_before(lexicon, data, size)) return 0;
    uint32_t node_count = lexicon->node_count;
    uint32_t word_count = lexicon->word_count;
    uint32_t pair_count = lexicon->pair_count;
    uint32_t strings_size = lexicon->strings_size;

    /* Every number that the search later uses as a position is checked here, once, so the
       search itself cannot read outside the file. */
    for (uint32_t index = 0; index < node_count; index++) {
        node_t node = node_at(lexicon, index);
        if ((uint64_t)node.first_child + node.child_count > node_count) return 0;
        if (node.child_count > 0 && node.first_child <= index) return 0;
        if ((uint64_t)node.first_word + node.word_count > word_count) return 0;
    }
    if (strings_size > 0 && lexicon->strings[strings_size - 1] != 0) return 0;
    for (uint32_t word = 0; word < word_count; word++) {
        if (read_u32(word_record(lexicon, word)) >= strings_size) return 0;
    }
    uint32_t previous_start = 0;
    for (uint32_t word = 0; word <= word_count; word++) {
        uint32_t start = pair_start(lexicon, word);
        if (start < previous_start || start > pair_count) return 0;
        previous_start = start;
    }
    for (uint32_t pair = 0; pair < pair_count; pair++) {
        if (pair_second(lexicon, pair) >= word_count) return 0;
    }
    if (lexicon->version != VERSION_TRIPLES) return 1;

    /* The table of the pairs that open triples holds one row per pair, sorted by the pair's
       position, with the position of the pair's first triple. A closing row ends the last run. */
    uint32_t context_count = lexicon->context_count;
    uint32_t triple_count = lexicon->triple_count;
    uint32_t previous_pair = 0, previous_first = 0;
    for (uint32_t row = 0; row <= context_count; row++) {
        uint32_t pair = read_u32(lexicon->contexts + CONTEXT_BYTES * (size_t)row);
        uint32_t first = read_u32(lexicon->contexts + CONTEXT_BYTES * (size_t)row + 4);
        if (row == context_count) {
            if (pair != pair_count || first != triple_count) return 0;
        } else {
            if (pair >= pair_count || (row > 0 && pair <= previous_pair)) return 0;
            if ((read_u32(lexicon->pairs + PAIR_BYTES * (size_t)pair) & PAIR_OPENS_TRIPLES) == 0) return 0;
        }
        if (first < previous_first || first > triple_count) return 0;
        previous_pair = pair;
        previous_first = first;
    }
    for (uint32_t triple = 0; triple < triple_count; triple++) {
        if (triple_word(lexicon, triple) >= word_count) return 0;
    }
    return 1;
}

/* ---- The supplement ---- */

int duo_lexicon_set_supplement(duo_lexicon *lexicon, const duo_lexicon *supplement) {
    if (lexicon == NULL) return 0;
    if (supplement == NULL) {
        lexicon->supplement = NULL;
        return 1;
    }
    if (lexicon->model != 0 || supplement->model != 0 || supplement->version != VERSION_PAIRS) return 0;
    if (supplement->pair_count != 0 || supplement->supplement != NULL || supplement == lexicon) return 0;
    if (lexicon->word_count >= SUPPLEMENT_BIT || supplement->word_count >= SUPPLEMENT_BIT) return 0;
    for (uint32_t index = 0; index < supplement->node_count; index++) {
        if (read_u16(supplement->nodes + NODE_BYTES * (size_t)index + 10) > 1) return 0;
    }
    lexicon->supplement = supplement;
    return 1;
}

/* Whether a word number names a word that only the supplement holds. */
static int in_supplement(uint32_t word) {
    return word != NO_WORD && (word & SUPPLEMENT_BIT) != 0;
}

/* ---- Parameters ---- */

duo_params duo_english_params(void) {
    duo_params params;
    params.adjacent_substitution = 4.5f;
    params.far_substitution = 9.0f;
    params.omission = 5.0f;
    params.omission_of_double = 3.5f;
    params.omission_of_apostrophe = 0.5f;
    params.insertion = 5.5f;
    params.insertion_of_double = 3.5f;
    params.transposition = 4.5f;
    params.first_letter_extra = 0.0f;
    params.slipped_word = 0.0f;
    params.short_word_budget = 5.6f;
    params.long_word_budget = 11.0f;
    params.missing_space = 5.0f;
    params.letter_for_space = 5.0f;
    params.extra_space = 5.0f;
    params.space_for_letter = 5.0f;
    params.shifted_space = 4.0f;
    /* The seven costs of a symbol or digit key typed on purpose come from a sweep on the dev
       half of the cases in scripts/typing-evaluation/cases/english-symbols.dev.jsonl. Each
       value sits inside the range that repairs the most slips and still keeps the clean text. */
    params.bracket_before_word = 8.0f;
    params.dot_before_word = 8.0f;
    params.comma_before_word = 10.0f;
    params.semicolon_before_word = 10.0f;
    params.dash_before_word = 9.0f;
    params.digit_before_word = 12.0f;
    params.digit_after_word = 13.0f;
    params.pair_weight = 0.6f;
    params.unknown_word = -13.0f;
    params.unknown_letter = -1.2f;
    params.margin_known = 5.0f;
    params.margin_unknown = 0.0f;
    params.sentence_end_weight = 0.0f;
    params.reading_cost_weight = 1.0f;
    params.spaces_between_words = 1;
    params.beam = 8;
    params.apostrophe_readings = 1;
    return params;
}

duo_params duo_pinyin_params(void) {
    duo_params params = duo_english_params();
    /* On the dev half of the Pinyin cases, these two values change correctly typed Pinyin less
       often than the English values do, and they repair slightly more slips. */
    params.omission = 4.0f;
    params.slipped_word = 2.0f;
    params.omission_of_apostrophe = BIG;
    params.missing_space = 0.0f;
    params.letter_for_space = BIG;
    params.extra_space = BIG;
    params.space_for_letter = BIG;
    params.shifted_space = BIG;
    params.unknown_word = 0.0f;
    params.unknown_letter = -16.0f;
    params.margin_known = 0.0f;
    params.margin_unknown = 0.0f;
    params.sentence_end_weight = 1.0f;
    params.spaces_between_words = 0;
    /* Many Chinese words share one spelling, and each of them is its own reading. */
    params.beam = 32;
    params.apostrophe_readings = 0;
    return params;
}

int duo_params_set(duo_params *params, const char *name, float value) {
#define FIELD(field) if (strcmp(name, #field) == 0) { params->field = value; return 1; }
    FIELD(adjacent_substitution)
    FIELD(far_substitution)
    FIELD(omission)
    FIELD(omission_of_double)
    FIELD(omission_of_apostrophe)
    FIELD(insertion)
    FIELD(insertion_of_double)
    FIELD(transposition)
    FIELD(first_letter_extra)
    FIELD(slipped_word)
    FIELD(short_word_budget)
    FIELD(long_word_budget)
    FIELD(missing_space)
    FIELD(letter_for_space)
    FIELD(extra_space)
    FIELD(space_for_letter)
    FIELD(shifted_space)
    FIELD(bracket_before_word)
    FIELD(dot_before_word)
    FIELD(comma_before_word)
    FIELD(semicolon_before_word)
    FIELD(dash_before_word)
    FIELD(digit_before_word)
    FIELD(digit_after_word)
    FIELD(pair_weight)
    FIELD(unknown_word)
    FIELD(unknown_letter)
    FIELD(margin_known)
    FIELD(margin_unknown)
    FIELD(sentence_end_weight)
    FIELD(reading_cost_weight)
#undef FIELD
    if (strcmp(name, "beam") == 0) { params->beam = (int)value; return 1; }
    if (strcmp(name, "apostrophe_readings") == 0) { params->apostrophe_readings = value != 0.0f; return 1; }
    return 0;
}

/* ---- Keys ---- */

/* Key places on the phone letter layout, in key widths. The second row starts half a key to the
   right of the first, and the third row one and a half keys to the right. */
static int key_place(char letter, float *x, float *y) {
    static const char *rows[3] = { "qwertyuiop", "asdfghjkl", "zxcvbnm" };
    static const float offsets[3] = { 0.0f, 0.5f, 1.5f };
    for (int row = 0; row < 3; row++) {
        const char *found = strchr(rows[row], letter);
        if (found != NULL && letter != 0) {
            *x = offsets[row] + (float)(found - rows[row]);
            *y = (float)row;
            return 1;
        }
    }
    return 0;
}

/* Keys side by side are 1.0 apart, and keys one row apart are about 1.12 apart. */
static int keys_are_neighbors(char first, char second) {
    float x1, y1, x2, y2;
    if (!key_place(first, &x1, &y1) || !key_place(second, &x2, &y2)) return 0;
    float dx = x1 - x2, dy = y1 - y2;
    return dx * dx + dy * dy <= 1.15f * 1.15f;
}

/* The letters right above the space bar. */
static int is_above_space(char letter) {
    return letter != 0 && strchr("cvbnm", letter) != NULL;
}

static int is_letter(char character) {
    return character >= 'a' && character <= 'z';
}

static int is_digit(char character) {
    return character >= '0' && character <= '9';
}

/* The letters beside a symbol or digit key, or NULL for any other byte. The table holds the
   keys of the wide layout and of the compact layout in Shared/keyboard-layout.json together.
   scripts/typing-evaluation/symbol_keys.py derives it from the key positions, and its check
   fails when this copy differs. */
static const char *symbol_neighbors(char symbol) {
    switch (symbol) {
    case '1': return "q";
    case '2': return "qw";
    case '3': return "ew";
    case '4': return "er";
    case '5': return "rt";
    case '6': return "ty";
    case '7': return "uy";
    case '8': return "iu";
    case '9': return "io";
    case '0': return "op";
    case '-': return "p";
    case '[': return "p";
    case ';': return "lp";
    case ',': return "klmn";
    case '.': return "lm";
    default: return NULL;
    }
}

/* Whether a symbol or digit key can stand for a letter: the letter's key is beside it. */
static int symbol_is_beside(char symbol, char letter) {
    const char *letters = symbol_neighbors(symbol);
    return letters != NULL && letter != 0 && strchr(letters, letter) != NULL;
}

static float substitution_cost(const duo_params *params, char typed, char intended) {
    if (typed == intended) return 0.0f;
    if (typed == ' ') return is_above_space(intended) ? params->space_for_letter : BIG;
    if (typed == '\'' || intended == '\'') return BIG;
    /* A symbol or digit key stands only for a letter beside it, never for a letter farther away. */
    if (!is_letter(typed) && symbol_neighbors(typed) != NULL) {
        return symbol_is_beside(typed, intended) ? params->adjacent_substitution : BIG;
    }
    return keys_are_neighbors(typed, intended) ? params->adjacent_substitution : params->far_substitution;
}

/* ---- Matching one word against the typed text, with slips ---- */

typedef struct {
    int end;          /* typed position right after the word */
    uint32_t node;    /* the lexicon node whose words the typed text stands for */
    float cost;       /* total cost of the slips this match assumes */
    int supplement;   /* 1 when the node is a node of the supplement */
    uint32_t twin;    /* for a node of the supplement: the main lexicon's node of the same spelling, or NO_WORD */
} edge_t;

typedef struct {
    const duo_lexicon *lexicon;  /* the lexicon whose letter tree the walk follows */
    const duo_lexicon *main;     /* for a walk of the supplement: the main lexicon, and NULL otherwise */
    const duo_params *params;
    const char *typed;  /* the typed text from the word's first position on */
    const char *original;  /* the same span of the text as the person typed it, before a space was moved */
    int length;         /* count of typed bytes from that position to the end */
    int start;          /* the word's first position in the whole typed text */
    int has_symbol;     /* whether that typed text holds a symbol or digit key */
    /* rows[d][b]: the lowest slip cost that lines up the first d letters of the spelling with
       the first k typed bytes, where k = d - BAND + b. Only readings within BAND slips of the
       diagonal are kept, which is why a row holds ROW numbers and not one per typed byte. */
    float rows[MAX_DEPTH + 2][ROW];
    char letters[MAX_DEPTH + 2];
    edge_t *edges;
    int edge_count;
} walk_t;

/* A reading that takes a symbol key for a letter and the same letter beside it for an extra
   key gives the text without the symbol: "[please" and "p[lease" would read as "please", and
   "a[pple" as "apple". The engine never drops a symbol key, so the two checks below leave
   those readings out. */

/* Whether the typed letter at `index` starts a run of that letter that ends right before a
   symbol key that can stand for the letter, as each "p" does in "pp[lease". Such a letter is
   never an extra key. The check does not know which letter the symbol key will stand for, so
   it also leaves out the rare reading with the symbol key as another letter. */
static int runs_into_symbol(const walk_t *walk, int index) {
    char typed = walk->typed[index];
    int next = index + 1;
    while (next < walk->length && walk->typed[next] == typed) next++;
    return next < walk->length && symbol_is_beside(walk->typed[next], typed);
}

/* Whether the typed letter at `index` follows a symbol key, alone or after a run of the same
   letter, while the spelling reads the symbol key and the whole run as that letter. `letter`
   is the last letter of the spelling that is lined up with the bytes before `index`, and
   `depth` is the count of letters before it. */
static int follows_symbol_as_same_letter(const walk_t *walk, int index, int depth, char letter) {
    char typed = walk->typed[index];
    if (typed != letter) return 0;
    int run = 0;
    while (index - run - 1 >= 0 && walk->typed[index - run - 1] == typed) run++;
    int symbol = index - run - 1;
    if (symbol < 0 || !symbol_is_beside(walk->typed[symbol], typed) || depth < run) return 0;
    for (int back = 1; back <= run; back++) {
        if (walk->letters[depth - back] != typed) return 0;
    }
    return 1;
}

static float insertion_cost(const walk_t *walk, int index) {
    char typed = walk->typed[index];
    if (typed == ' ') return walk->params->extra_space;
    if (walk->has_symbol) {
        if (!is_letter(typed)) {
            /* A symbol or digit key is never an extra key: a person may have typed it on purpose. */
            if (symbol_neighbors(typed) != NULL) return BIG;
        } else if (runs_into_symbol(walk, index)) {
            return BIG;
        }
    }
    if (index > 0 && walk->typed[index - 1] == typed) return walk->params->insertion_of_double;
    return walk->params->insertion;
}

static float omission_cost(const walk_t *walk, char letter, int depth) {
    if (letter == '\'') return walk->params->omission_of_apostrophe;
    if (depth > 0 && walk->letters[depth - 1] == letter) return walk->params->omission_of_double;
    return walk->params->omission + (depth == 0 ? walk->params->first_letter_extra : 0.0f);
}

static uint32_t find_exact_node(const duo_lexicon *lexicon, const char *letters, int length);
static int is_known_word(const duo_lexicon *lexicon, const char *letters, int length);

/* Whether the first `consumed` bytes, as the person typed them, hold a space and every word
   between the spaces is a known word. A person who typed two known words meant two words, so a word of the supplement
   does not join them: "hard coded" stays, also when the supplement holds "hardcoded". The main
   lexicon keeps its own joins, as before the supplement. */
static int typed_known_words(const walk_t *walk, int consumed) {
    int spaces = 0;
    int start = 0;
    for (int index = 0; index <= consumed; index++) {
        if (index < consumed && walk->original[index] != ' ') continue;
        if (index < consumed) spaces++;
        if (index == start || !is_known_word(walk->main, walk->original + start, index - start)) return 0;
        start = index + 1;
    }
    return spaces > 0;
}

static void walk_node(walk_t *walk, uint32_t node_index, int depth) {
    node_t node = node_at(walk->lexicon, node_index);
    const duo_params *params = walk->params;

    if (depth > 0 && node.word_count > 0) {
        /* A one-letter word must match exactly. Longer words may hold slips up to a budget. */
        float budget = depth <= 1 ? 0.0f : (depth <= 4 ? params->short_word_budget : params->long_word_budget);
        for (int b = 0; b < ROW; b++) {
            int consumed = depth - BAND + b;
            float cost = walk->rows[depth][b];
            if (consumed < 1 || consumed > walk->length || cost > budget) continue;
            if (walk->main != NULL && cost > 0.0f && typed_known_words(walk, consumed)) continue;
            if (walk->edge_count < MAX_EDGES) {
                edge_t *edge = &walk->edges[walk->edge_count++];
                edge->end = walk->start + consumed;
                edge->node = node_index;
                edge->cost = cost;
                edge->supplement = walk->main != NULL;
                edge->twin = walk->main != NULL ? find_exact_node(walk->main, walk->letters, depth) : NO_WORD;
            }
        }
    }
    if (depth >= MAX_DEPTH) return;

    for (uint32_t child_index = node.first_child; child_index < node.first_child + node.child_count; child_index++) {
        char letter = node_letter(walk->lexicon, child_index);
        float *row = walk->rows[depth + 1];
        const float *above = walk->rows[depth];
        float lowest = BIG;
        for (int b = 0; b < ROW; b++) {
            int consumed = depth + 1 - BAND + b;
            float best = BIG;
            if (consumed >= 0 && consumed <= walk->length) {
                if (consumed >= 1) {
                    /* The typed byte stands for this letter: a match, or a wrong key. */
                    float cost = above[b] + substitution_cost(params, walk->typed[consumed - 1], letter);
                    if (cost < best) best = cost;
                    /* The typed byte is extra. */
                    if (b >= 1 && !(walk->has_symbol && follows_symbol_as_same_letter(walk, consumed - 1, depth, letter))) {
                        cost = row[b - 1] + insertion_cost(walk, consumed - 1);
                        if (cost < best) best = cost;
                    }
                }
                if (b + 1 < ROW) {
                    /* The person did not type this letter. */
                    float cost = above[b + 1] + omission_cost(walk, letter, depth);
                    if (cost < best) best = cost;
                }
                if (depth >= 1 && consumed >= 2 && letter != walk->letters[depth - 1]
                    && walk->typed[consumed - 2] == letter && walk->typed[consumed - 1] == walk->letters[depth - 1]) {
                    /* This letter and the one before it were typed in the wrong order. */
                    float cost = walk->rows[depth - 1][b] + params->transposition;
                    if (cost < best) best = cost;
                }
            }
            row[b] = best;
            if (best < lowest) lowest = best;
        }
        if (lowest <= params->long_word_budget) {
            walk->letters[depth] = letter;
            walk_node(walk, child_index, depth + 1);
        }
    }
}

/* Fills `edges` with every lexicon node that the typed text from `start` on can stand for.
   `original` is the text as the person typed it: `typed` itself, or the text before the search
   moved one of its spaces. */
static int find_edges(
    const duo_lexicon *lexicon, const duo_params *params,
    const char *typed, const char *original, int length, int start, edge_t *edges) {
    walk_t walk;
    walk.lexicon = lexicon;
    walk.main = NULL;
    walk.params = params;
    walk.typed = typed + start;
    walk.original = original + start;
    walk.length = length - start;
    walk.start = start;
    walk.edges = edges;
    walk.edge_count = 0;
    walk.has_symbol = 0;
    for (int index = 0; index < walk.length && !walk.has_symbol; index++) {
        walk.has_symbol = !is_letter(walk.typed[index]) && symbol_neighbors(walk.typed[index]) != NULL;
    }
    for (int b = 0; b < ROW; b++) {
        int consumed = b - BAND;
        if (consumed < 0 || consumed > walk.length) walk.rows[0][b] = BIG;
        else if (consumed == 0) walk.rows[0][b] = 0.0f;
        else walk.rows[0][b] = walk.rows[0][b - 1] + insertion_cost(&walk, consumed - 1) + params->first_letter_extra;
    }
    walk_node(&walk, 0, 0);
    if (lexicon->supplement != NULL) {
        /* The same walk over the supplement's letter tree. The first row does not change. */
        walk.lexicon = lexicon->supplement;
        walk.main = lexicon;
        walk_node(&walk, 0, 0);
    }
    return walk.edge_count;
}

/* The node that spells exactly these letters, or NO_WORD. */
static uint32_t find_exact_node(const duo_lexicon *lexicon, const char *letters, int length) {
    uint32_t index = 0;
    for (int position = 0; position < length; position++) {
        node_t node = node_at(lexicon, index);
        uint32_t next = NO_WORD;
        for (uint32_t child = node.first_child; child < node.first_child + node.child_count; child++) {
            if (node_letter(lexicon, child) == letters[position]) {
                next = child;
                break;
            }
        }
        if (next == NO_WORD) return NO_WORD;
        index = next;
    }
    return node_at(lexicon, index).word_count > 0 ? index : NO_WORD;
}

/* ---- Word probabilities ---- */

/* A walk over the words of one node, each with its log probability after a reading's last
   words. The words of a node share one spelling, such as the Chinese words that sound alike.

   The words of a node sit side by side in the word table, most probable first. The pairs of a
   word are sorted by their second word, and the triples of a pair by their third word, so the
   listed pairs and triples that end in the node are one run of each list. The walk goes
   through the node's words and both runs in step.

   A word without a listed pair or triple gets a back-off estimate: a sum of weights that is
   the same for the whole node, plus the word's own log probability. These estimates fall from
   word to word. A caller that has no use for one of them has no use for the later ones, and
   turns them off with `skip_estimates`. The words with a listed pair or triple still come. */
typedef struct {
    const duo_lexicon *lexicon;
    uint32_t word;         /* the next word of the node */
    uint32_t end;          /* one past the node's last word */
    uint32_t pair;         /* the next listed pair of the word before, and one past the last */
    uint32_t pair_end;
    uint32_t triple;       /* the next listed triple of the pair before, and one past the last */
    uint32_t triple_end;
    float pair_back_off;   /* added to a listed pair's value: the back-off weight of the pair before */
    float estimate_base;   /* added to a word's own log probability for a back-off estimate */
    float pair_weight;     /* the blend of model 0 */
    float own_share;
    float reading_cost_weight;
    int own_only;          /* every word gets its own log probability and nothing else */
    int mixed;             /* model 0 */
    int skip_estimates;
} followers_t;

/* Starts a walk over the words of `node_index` after a reading that ends in the word `previous`.
   `context` is the pair of the reading's last two words, or NO_PAIR. */
static void start_followers(
    followers_t *followers, const duo_lexicon *lexicon, const duo_params *params,
    uint32_t previous, uint32_t context, uint32_t node_index) {
    node_t node = node_at(lexicon, node_index);
    followers->lexicon = lexicon;
    followers->word = node.first_word;
    followers->end = node.first_word + node.word_count;
    followers->pair = 0;
    followers->pair_end = 0;
    followers->triple = 0;
    followers->triple_end = 0;
    followers->pair_back_off = 0.0f;
    followers->estimate_base = 0.0f;
    followers->pair_weight = params->pair_weight;
    followers->own_share = 1.0f - params->pair_weight;
    followers->reading_cost_weight = params->reading_cost_weight;
    followers->mixed = lexicon->model != MODEL_BACK_OFF;
    followers->skip_estimates = 0;
    followers->own_only = previous == NO_WORD
        || (followers->mixed && (lexicon->pair_count == 0 || params->pair_weight <= 0.0f));
    if (followers->own_only) return;
    if (in_supplement(previous)) {
        /* A word that only the supplement holds has no listed pair, so every word after it
           gets the estimate. A lexicon with a supplement uses the mixed model. */
        followers->estimate_base = logf(followers->own_share);
        return;
    }

    if (followers->mixed) {
        followers->estimate_base = logf(followers->own_share);
    } else {
        if (context != NO_PAIR) {
            followers->pair_back_off = pair_back_off(lexicon, context);
            uint32_t low, high;
            triples_of_pair(lexicon, context, &low, &high);
            followers->triple_end = high;
            while (low < high) {
                uint32_t middle = low + (high - low) / 2;
                if (triple_word(lexicon, middle) < node.first_word) low = middle + 1;
                else high = middle;
            }
            followers->triple = low;
        }
        followers->estimate_base = followers->pair_back_off + word_back_off(lexicon, previous);
    }
    uint32_t low = pair_start(lexicon, previous);
    uint32_t high = pair_start(lexicon, previous + 1);
    followers->pair_end = high;
    while (low < high) {
        uint32_t middle = low + (high - low) / 2;
        if (pair_second(lexicon, middle) < node.first_word) low = middle + 1;
        else high = middle;
    }
    followers->pair = low;
}

/* Gives the next word of the node, its log probability, and the listed pair of the word before
   with this word, or NO_PAIR. `estimated` says that the value is a back-off estimate. Returns 0
   when the node has no word left. */
static int next_follower(followers_t *followers, uint32_t *word, float *log_probability, uint32_t *pair, int *estimated) {
    const duo_lexicon *lexicon = followers->lexicon;
    uint32_t pair_word = followers->pair < followers->pair_end ? pair_second(lexicon, followers->pair) : NO_WORD;
    uint32_t third_word = followers->triple < followers->triple_end ? triple_word(lexicon, followers->triple) : NO_WORD;
    if (followers->skip_estimates) {
        /* Go straight to the next word with a listed pair or triple. */
        uint32_t listed = pair_word < third_word ? pair_word : third_word;
        if (listed > followers->word) followers->word = listed;
    }
    if (followers->word >= followers->end) return 0;

    uint32_t current = followers->word++;
    float own = word_log_probability(lexicon, current);
    *word = current;
    *pair = NO_PAIR;
    *estimated = 1;
    if (followers->own_only) {
        *log_probability = own;
        return 1;
    }
    float value = own + followers->estimate_base;
    if (pair_word == current) {
        *pair = followers->pair;
        *estimated = 0;
        float listed = pair_log_probability(lexicon, followers->pair);
        followers->pair++;
        if (followers->mixed) {
            float blend = logf(followers->pair_weight * expf(listed) + followers->own_share * expf(own));
            if (blend > value) value = blend;
        } else {
            value = followers->pair_back_off + listed
                + followers->reading_cost_weight * word_reading_cost(lexicon, current);
        }
    }
    if (third_word == current) {
        *estimated = 0;
        value = triple_log_probability(lexicon, followers->triple)
            + followers->reading_cost_weight * word_reading_cost(lexicon, current);
        followers->triple++;
    }
    *log_probability = value;
    return 1;
}

/* Picks the most probable word of a node after the word `previous`, and its log probability. */
static void best_word(
    const duo_lexicon *lexicon, const duo_params *params, uint32_t previous, uint32_t node_index,
    uint32_t *word, float *log_probability) {
    followers_t followers;
    uint32_t candidate, pair;
    float value;
    int estimated;
    int found = 0;
    *word = node_at(lexicon, node_index).first_word;
    *log_probability = -BIG;
    start_followers(&followers, lexicon, params, previous, NO_PAIR, node_index);
    while (next_follower(&followers, &candidate, &value, &pair, &estimated)) {
        if (!found || value > *log_probability) {
            *log_probability = value;
            *word = candidate;
            found = 1;
        }
        /* The first back-off estimate of a node is its highest. */
        if (estimated) followers.skip_estimates = 1;
    }
}

/* The log probability of one given word after a reading that ends in the word `previous`.
   `context` is the pair of the reading's last two words, or NO_PAIR. */
static float word_after(
    const duo_lexicon *lexicon, const duo_params *params, uint32_t previous, uint32_t context, uint32_t word) {
    float own = word_log_probability(lexicon, word);
    int back_off_model = lexicon->model == MODEL_BACK_OFF;
    if (previous == NO_WORD || (!back_off_model && lexicon->pair_count == 0)) return own;
    if (in_supplement(previous)) return params->pair_weight > 0.0f ? own + logf(1.0f - params->pair_weight) : own;
    float reading_cost = params->reading_cost_weight * word_reading_cost(lexicon, word);
    float weight = 0.0f;
    if (back_off_model && context != NO_PAIR) {
        uint32_t low, high;
        triples_of_pair(lexicon, context, &low, &high);
        while (low < high) {
            uint32_t middle = low + (high - low) / 2;
            uint32_t third = triple_word(lexicon, middle);
            if (third == word) return triple_log_probability(lexicon, middle) + reading_cost;
            if (third < word) low = middle + 1;
            else high = middle;
        }
        weight = pair_back_off(lexicon, context);
    }
    uint32_t low = pair_start(lexicon, previous);
    uint32_t high = pair_start(lexicon, previous + 1);
    while (low < high) {
        uint32_t middle = low + (high - low) / 2;
        uint32_t second = pair_second(lexicon, middle);
        if (second == word) {
            float pair_value = pair_log_probability(lexicon, middle);
            if (back_off_model) return weight + pair_value + reading_cost;
            return logf(params->pair_weight * expf(pair_value) + (1.0f - params->pair_weight) * expf(own));
        }
        if (second < word) low = middle + 1;
        else high = middle;
    }
    if (back_off_model) return weight + word_back_off(lexicon, previous) + own;
    return params->pair_weight > 0.0f ? own + logf(1.0f - params->pair_weight) : own;
}

/* The log probability of the supplement's word `word` after the word `previous`: the value of a
   word without a listed pair in the mixed model, as next_follower gives it. */
static float supplement_word_value(
    const duo_lexicon *lexicon, const duo_params *params, uint32_t previous, uint32_t word) {
    float own = word_log_probability(lexicon->supplement, word);
    if (previous == NO_WORD || lexicon->pair_count == 0 || params->pair_weight <= 0.0f) return own;
    return own + logf(1.0f - params->pair_weight);
}

/* The most probable word that exactly these letters spell, in the lexicon or its supplement,
   after the word `previous`, and its log probability. A spelling that both hold gives the
   main lexicon's word at the higher of the two values, so the word keeps its pairs. Returns 0
   when neither holds the letters. */
static int exact_word(
    const duo_lexicon *lexicon, const duo_params *params, uint32_t previous, const char *letters, int length,
    uint32_t *word, float *log_probability) {
    int found = 0;
    uint32_t node = find_exact_node(lexicon, letters, length);
    if (node != NO_WORD) {
        best_word(lexicon, params, previous, node, word, log_probability);
        found = 1;
    }
    if (lexicon->supplement != NULL) {
        uint32_t extra = find_exact_node(lexicon->supplement, letters, length);
        if (extra != NO_WORD) {
            uint32_t extra_word = node_at(lexicon->supplement, extra).first_word;
            float value = supplement_word_value(lexicon, params, previous, extra_word);
            if (!found) *word = extra_word | SUPPLEMENT_BIT;
            if (!found || value > *log_probability) *log_probability = value;
            found = 1;
        }
    }
    return found;
}

/* Whether the lexicon or its supplement holds a word with exactly these letters. */
static int is_known_word(const duo_lexicon *lexicon, const char *letters, int length) {
    if (find_exact_node(lexicon, letters, length) != NO_WORD) return 1;
    return lexicon->supplement != NULL && find_exact_node(lexicon->supplement, letters, length) != NO_WORD;
}

/* The two sentence marks of a back-off lexicon sit under spellings that nobody can type. */
static uint32_t find_mark(const duo_lexicon *lexicon, char mark) {
    node_t root = node_at(lexicon, 0);
    for (uint32_t child = root.first_child; child < root.first_child + root.child_count; child++) {
        if (node_letter(lexicon, child) == mark) {
            node_t node = node_at(lexicon, child);
            return node.word_count > 0 ? node.first_word : NO_WORD;
        }
    }
    return NO_WORD;
}

#define SENTENCE_START_MARK 1
#define SENTENCE_END_MARK 2

/* ---- The search over whole readings ---- */

typedef struct {
    float score;
    uint32_t word;        /* the last word of this reading, or NO_WORD */
    uint32_t pair;        /* the pair of the last two words when a later word depends on it, or NO_PAIR */
    int from_position;    /* where the reading stood before its last word, or -1 at the start */
    int from_state;
    int kept_start;       /* for text kept as typed: its span in the typed text */
    int kept_end;
    float slips;          /* the part of the score that the assumed slips cost, as a positive number */
} state_t;

typedef struct {
    state_t states[MAX_BEAM];
    int count;
    int weakest;          /* in a full cell: the first of the readings with the lowest score */
} cell_t;

static void find_weakest(cell_t *cell) {
    int weakest = 0;
    for (int index = 1; index < cell->count; index++) {
        if (cell->states[index].score < cell->states[weakest].score) weakest = index;
    }
    cell->weakest = weakest;
}

/* Adds a reading to a cell. Two readings that end in the same word, and in the same pair when
   a later word depends on the pair, go on the same way, so the cell keeps the better one. A
   full cell drops its weakest reading. Returns 0 when the cell is full and the reading is not
   better than the weakest reading in it, and 1 otherwise. */
static int add_state(cell_t *cell, int beam, state_t state) {
    int full = cell->count >= beam;
    if (full && state.score <= cell->states[cell->weakest].score) return 0;
    for (int index = 0; index < cell->count; index++) {
        state_t *existing = &cell->states[index];
        if (existing->word == state.word && existing->pair == state.pair
            && existing->kept_start == state.kept_start && existing->kept_end == state.kept_end) {
            if (state.score > existing->score) {
                *existing = state;
                if (full) find_weakest(cell);
            }
            return 1;
        }
    }
    if (full) cell->states[cell->weakest] = state;
    else cell->states[cell->count++] = state;
    if (cell->count >= beam) find_weakest(cell);
    return 1;
}

/* Writes the reading that ends in `state` into `text`. Returns 0 when the text does not fit. */
static int write_reading(
    const duo_lexicon *lexicon, const duo_params *params, const char *typed, int length,
    const cell_t *cells, int position, int state_index, char *text) {
    /* Follow the reading back to its start, then write its words front to back. */
    int positions[DUO_MAX_TYPED + 2];
    int states[DUO_MAX_TYPED + 2];
    int count = 0;
    while (position >= 0) {
        const state_t *state = &cells[position].states[state_index];
        if (state->from_position < 0) break;
        positions[count] = position;
        states[count] = state_index;
        count++;
        position = state->from_position;
        state_index = state->from_state;
    }
    size_t used = 0;
    /* Set after a symbol kept right before a word: the word follows it without a space. */
    int joined = 0;
    text[0] = 0;
    for (int index = count - 1; index >= 0; index--) {
        const state_t *state = &cells[positions[index]].states[states[index]];
        const char *piece;
        size_t piece_length;
        if (state->kept_start >= 0) {
            piece = typed + state->kept_start;
            piece_length = (size_t)(state->kept_end - state->kept_start);
        } else {
            piece = in_supplement(state->word)
                ? word_text(lexicon->supplement, state->word & ~SUPPLEMENT_BIT) : word_text(lexicon, state->word);
            piece_length = strlen(piece);
        }
        int needs_space = params->spaces_between_words && used > 0 && !joined;
        if (used + piece_length + (needs_space ? 1 : 0) + 1 > DUO_TEXT_SIZE) return 0;
        if (needs_space) text[used++] = ' ';
        memcpy(text + used, piece, piece_length);
        used += piece_length;
        text[used] = 0;
        joined = state->kept_start >= 0 && state->kept_end < length && typed[state->kept_end] != ' ';
    }
    return 1;
}

/* The cost of a symbol or digit key that a person typed on purpose right before a word.
   Returns 0 for a byte that is not such a key. */
static int cost_before_word(const duo_params *params, char symbol, float *cost) {
    if (is_digit(symbol)) {
        *cost = params->digit_before_word;
        return 1;
    }
    switch (symbol) {
    case '[': *cost = params->bracket_before_word; return 1;
    case '.': *cost = params->dot_before_word; return 1;
    case ',': *cost = params->comma_before_word; return 1;
    case ';': *cost = params->semicolon_before_word; return 1;
    case '-': *cost = params->dash_before_word; return 1;
    default: return 0;
    }
}

/* Reads a typed word with a symbol or digit key as text typed on purpose: a key right before
   a known word, as in "[note", or a digit right after a known word, as in "mp3". Returns 1,
   the place of the known word's first letter in `letters`, and the cost of the key, or 0 for
   any other text. The known word is one letter shorter than the typed word. */
static int word_beside_symbol(
    const duo_lexicon *lexicon, const duo_params *params, const char *letters, int length, int *first, float *cost) {
    if (length < 2) return 0;
    if (cost_before_word(params, letters[0], cost)) {
        *first = 1;
        return is_known_word(lexicon, letters + 1, length - 1);
    }
    if (is_digit(letters[length - 1])) {
        *cost = params->digit_after_word;
        *first = 0;
        return is_known_word(lexicon, letters, length - 1);
    }
    return 0;
}

/* The log probability of a typed word that holds a known word with a symbol or digit key
   beside it, after the word `previous`. The typed word has two readings. Typed on purpose, it
   is the known word at the cost of the key. It can also be unknown text. A reading that takes
   the key for a slip must beat the first one by margin_known, as for any known word, and the
   second one by margin_unknown. Typed text whose words are all known gets margin_known as a
   whole, so the unknown text counts that much lower here. In typed text with an unknown word
   beside this one, the whole text gets margin_unknown, as it does without a symbol key.
   `known` is the known word inside the typed word, of `length` - 1 letters, and `symbol_cost`
   the cost of the key, both from word_beside_symbol. */
static float score_beside_symbol(
    const duo_lexicon *lexicon, const duo_params *params, uint32_t previous, const char *known,
    float symbol_cost, int length, uint32_t *word) {
    float log_probability;
    /* word_beside_symbol found the word, so exact_word finds it too. */
    if (!exact_word(lexicon, params, previous, known, length - 1, word, &log_probability)) abort();
    float on_purpose = log_probability - symbol_cost;
    float unknown = params->unknown_word + params->unknown_letter * (float)length
        - (params->margin_known - params->margin_unknown);
    return on_purpose > unknown ? on_purpose : unknown;
}

/* The readings of the whole typed text that a search collects for duo_english_readings. */
typedef struct {
    duo_reading *items;
    int count;
    int capacity;
    /* The text as typed. That reading has its own score, so a search does not collect it. */
    const char *typed;
    /* Slip cost that the caller adds to every reading of this search, as for a shifted space. */
    float extra_slip;
} reading_pool_t;

/* Adds one reading to the pool. The same text from two ways keeps the higher score. A full pool
   drops its lowest reading. */
static void pool_add(reading_pool_t *pool, const char *text, float score, float slips) {
    if (strcmp(text, pool->typed) == 0) return;
    int lowest = -1;
    for (int index = 0; index < pool->count; index++) {
        duo_reading *existing = &pool->items[index];
        if (strcmp(existing->text, text) == 0) {
            if (score > existing->score) {
                existing->score = score;
                existing->slip_cost = slips;
            }
            return;
        }
        if (lowest < 0 || existing->score < pool->items[lowest].score) lowest = index;
    }
    duo_reading *slot;
    if (pool->count < pool->capacity) {
        slot = &pool->items[pool->count++];
    } else {
        if (score <= pool->items[lowest].score) return;
        slot = &pool->items[lowest];
    }
    memcpy(slot->text, text, strlen(text) + 1);
    slot->score = score;
    slot->slip_cost = slips;
    slot->as_typed = 0;
    slot->chosen = 0;
}

/* A cell that a reading reaches with its next word, and the cost of reaching it. */
typedef struct {
    cell_t *cell;
    float cost;
} target_t;

/* Adds the reading that goes on from `from` with one word over `edge` to each target cell.
   `index` is the place of `from` in the cell at `start`. Returns 1 when a cell took it. */
static int reach_targets(
    const duo_params *params, const state_t *from, int start, int index, const edge_t *edge,
    uint32_t word, uint32_t pair, float log_probability, const target_t *targets, int target_count, int beam) {
    state_t state;
    state.score = from->score + log_probability - edge->cost - (edge->cost > 0.0f ? params->slipped_word : 0.0f);
    state.word = word;
    state.pair = pair;
    state.from_position = start;
    state.from_state = index;
    state.kept_start = -1;
    state.kept_end = -1;
    state.slips = from->slips + edge->cost + (edge->cost > 0.0f ? params->slipped_word : 0.0f);
    int added = 0;
    for (int target = 0; target < target_count; target++) {
        state_t reached = state;
        if (targets[target].cost != 0.0f) {
            reached.score -= targets[target].cost;
            reached.slips += targets[target].cost;
        }
        added |= add_state(targets[target].cell, beam, reached);
    }
    return added;
}

/* Finds the best reading of typed[0..length). `original` is the text as the person typed it,
   which differs from `typed` in a search that moved a space. Returns 1 and fills `result`, or 0 on failure.
   When the lexicon cannot read the text to its end, the unreadable parts are kept as typed.
   A `pool` that is not NULL also receives every reading that the search keeps at the end of
   the text, one per last word. The pool does not change the result. */
static int decode(
    const duo_lexicon *lexicon, const duo_params *params, const char *typed, const char *original, int length,
    uint32_t previous_word, duo_result *result, reading_pool_t *pool) {
    int beam = params->beam < 1 ? 1 : (params->beam > MAX_BEAM ? MAX_BEAM : params->beam);
    cell_t *cells = (cell_t *)calloc((size_t)length + 1, sizeof(cell_t));
    edge_t *edges = (edge_t *)malloc(sizeof(edge_t) * MAX_EDGES);
    if (cells == NULL || edges == NULL) {
        free(cells);
        free(edges);
        return 0;
    }
    /* Without a word before the typed text, the text opens a sentence. */
    if (previous_word == NO_WORD) previous_word = find_mark(lexicon, SENTENCE_START_MARK);
    uint32_t end_mark = params->sentence_end_weight > 0.0f ? find_mark(lexicon, SENTENCE_END_MARK) : NO_WORD;
    state_t first = { 0.0f, previous_word, NO_PAIR, -1, -1, -1, -1, 0.0f };
    cells[0].states[0] = first;
    cells[0].count = 1;

    for (int start = 0; start < length; start++) {
        cell_t *cell = &cells[start];
        if (cell->count == 0) continue;

        /* Text the lexicon does not know stays as typed, at a price. English keeps a whole
           unknown word. Pinyin keeps one letter, so the letters around it can still be read. */
        int kept_end = start + 1;
        int keep = 1;
        int word_start = 0;
        if (params->spaces_between_words) {
            word_start = start == 0 || typed[start - 1] == ' ';
            keep = word_start;
            while (kept_end < length && typed[kept_end] != ' ') kept_end++;
            if (keep && is_known_word(lexicon, typed + start, kept_end - start)) keep = 0;
        }
        if (keep && typed[start] != ' ') {
            int next = kept_end < length && typed[kept_end] == ' ' ? kept_end + 1 : kept_end;
            /* A known word with a symbol or digit key beside it, as in ".net" and "mp3", is
               text typed on purpose: the word at the cost of the key. Any other text is unknown. */
            int beside = 0, known_first = 0;
            float symbol_cost = 0.0f;
            if (params->spaces_between_words) {
                beside = word_beside_symbol(lexicon, params, typed + start, kept_end - start, &known_first, &symbol_cost);
            }
            for (int index = 0; index < cell->count; index++) {
                state_t state;
                if (beside) {
                    state.score = cell->states[index].score + score_beside_symbol(
                        lexicon, params, cell->states[index].word, typed + start + known_first, symbol_cost,
                        kept_end - start, &state.word);
                } else {
                    state.score = cell->states[index].score + params->unknown_word
                        + params->unknown_letter * (float)(kept_end - start);
                    state.word = NO_WORD;
                }
                state.pair = NO_PAIR;
                state.from_position = start;
                state.from_state = index;
                state.kept_start = start;
                state.kept_end = kept_end;
                state.slips = cell->states[index].slips;
                add_state(&cells[next > length ? length : next], beam, state);
            }
        }

        /* An opening bracket typed on purpose right before a word: the bracket stays at its
           cost, and the search reads the word after it, with or without slips, so "[teh"
           becomes "[the". The other symbol keys do not get this reading, because the short
           tokens that follow them, as in "1st" and ".js", are seldom slips. */
        if (word_start && typed[start] == '[' && start + 1 < length && typed[start + 1] != ' ') {
            for (int index = 0; index < cell->count; index++) {
                state_t state = cell->states[index];
                state.score -= params->bracket_before_word;
                state.from_position = start;
                state.from_state = index;
                state.kept_start = start;
                state.kept_end = start + 1;
                add_state(&cells[start + 1], beam, state);
            }
        }

        int edge_count = find_edges(lexicon, params, typed, original, length, start, edges);
        for (int edge_index = 0; edge_index < edge_count; edge_index++) {
            const edge_t *edge = &edges[edge_index];
            target_t targets[2];
            int target_count = 1;
            targets[0].cost = 0.0f;
            if (edge->end >= length) {
                targets[0].cell = &cells[length];
            } else if (!params->spaces_between_words) {
                targets[0].cell = &cells[edge->end];
            } else if (typed[edge->end] == ' ') {
                targets[0].cell = &cells[edge->end + 1 > length ? length : edge->end + 1];
            } else {
                /* No space was typed after this word. Either the space is missing, or the
                   next byte is a letter from the row above the space bar typed in its place. */
                targets[0].cell = &cells[edge->end];
                targets[0].cost = params->missing_space;
                if (is_above_space(typed[edge->end]) && edge->end + 1 < length) {
                    targets[1].cell = &cells[edge->end + 1];
                    targets[1].cost = params->letter_for_space;
                    target_count = 2;
                }
            }
            for (int index = 0; index < cell->count; index++) {
                const state_t *from = &cell->states[index];
                if (edge->supplement) {
                    /* A node of the supplement holds one word. A spelling that the main lexicon
                       also holds goes on as the main lexicon's word, so the cell keeps the
                       better of the two values and the word keeps its pairs. */
                    uint32_t extra_word = node_at(lexicon->supplement, edge->node).first_word;
                    uint32_t word = edge->twin != NO_WORD
                        ? node_at(lexicon, edge->twin).first_word : (extra_word | SUPPLEMENT_BIT);
                    reach_targets(params, from, start, index, edge, word, NO_PAIR,
                                  supplement_word_value(lexicon, params, from->word, extra_word), targets, target_count, beam);
                    continue;
                }
                /* Every word of the node goes on as its own reading, because the word that is
                   most probable here is not always the word of the best whole reading. */
                followers_t followers;
                uint32_t word, pair;
                float log_probability;
                int estimated;
                start_followers(&followers, lexicon, params, from->word, from->pair, edge->node);
                while (next_follower(&followers, &word, &log_probability, &pair, &estimated)) {
                    int added = reach_targets(
                        params, from, start, index, edge, word,
                        pair != NO_PAIR && pair_matters_later(lexicon, pair) ? pair : NO_PAIR,
                        log_probability, targets, target_count, beam);
                    /* A back-off estimate that no cell takes ends the node's estimates: the
                       later ones are lower, and a full cell only gets harder to enter. */
                    if (estimated && !added) followers.skip_estimates = 1;
                }
            }
        }
    }

    int ok = 0;
    const cell_t *last = &cells[length];
    if (last->count > 0) {
        int best = 0;
        float best_score = -BIG;
        for (int index = 0; index < last->count; index++) {
            const state_t *state = &last->states[index];
            float score = state->score;
            if (end_mark != NO_WORD && state->word != NO_WORD) {
                score += params->sentence_end_weight * word_after(lexicon, params, state->word, state->pair, end_mark);
            }
            if (score > best_score) {
                best_score = score;
                best = index;
            }
        }
        result->score = best_score;
        result->consumed = length;
        ok = write_reading(lexicon, params, typed, length, cells, length, best, result->text);
        if (ok && pool != NULL) {
            char text[DUO_TEXT_SIZE];
            for (int index = 0; index < last->count; index++) {
                const state_t *state = &last->states[index];
                float score = state->score;
                if (end_mark != NO_WORD && state->word != NO_WORD) {
                    score += params->sentence_end_weight * word_after(lexicon, params, state->word, state->pair, end_mark);
                }
                if (write_reading(lexicon, params, typed, length, cells, length, index, text)) {
                    pool_add(pool, text, score - pool->extra_slip, state->slips + pool->extra_slip);
                }
            }
        }
    }
    free(cells);
    free(edges);
    return ok;
}

/* ---- Input checks ---- */

/* English input: letters, apostrophes and single spaces, with a letter, an apostrophe or a
   symbol key at both ends. A word may hold one symbol or digit key that sits beside a letter
   key, when the word has two or more letters: a digit or "[" at any place, or another such key
   in front of the word. Any other text is outside the engine's input, so it stays as typed. */
static int english_input_length(const char *typed) {
    size_t length = strlen(typed);
    if (length == 0 || length > DUO_MAX_TYPED) return 0;
    int letters = 0, symbols = 0;
    for (size_t index = 0; index < length; index++) {
        char character = typed[index];
        if (character == ' ') {
            if (index == 0 || index + 1 == length || typed[index - 1] == ' ') return 0;
            if (symbols > 0 && letters < 2) return 0;
            letters = 0;
            symbols = 0;
        } else if (is_letter(character)) {
            letters++;
        } else if (character != '\'') {
            int in_front = index == 0 || typed[index - 1] == ' ';
            int allowed = is_digit(character) || character == '[' || (in_front && symbol_neighbors(character) != NULL);
            if (!allowed || ++symbols > 1) return 0;
        }
    }
    if (symbols > 0 && letters < 2) return 0;
    return (int)length;
}

static uint32_t find_word(const duo_lexicon *lexicon, const char *letters, int length) {
    uint32_t node = find_exact_node(lexicon, letters, length);
    if (node != NO_WORD) return node_at(lexicon, node).first_word;
    if (lexicon->supplement == NULL) return NO_WORD;
    node = find_exact_node(lexicon->supplement, letters, length);
    return node == NO_WORD ? NO_WORD : (node_at(lexicon->supplement, node).first_word | SUPPLEMENT_BIT);
}

/* ---- English ---- */

/* Log probability of the typed text read exactly as typed, and whether every typed word is
   known. A known word with a symbol or digit key beside it counts as known. */
static float score_as_typed(
    const duo_lexicon *lexicon, const duo_params *params, const char *typed, int length,
    uint32_t previous_word, int *all_known) {
    float score = 0.0f;
    uint32_t previous = previous_word;
    *all_known = 1;
    int start = 0;
    while (start < length) {
        int end = start;
        while (end < length && typed[end] != ' ') end++;
        uint32_t word;
        float log_probability;
        float symbol_cost = 0.0f;
        int known_first = 0;
        if (exact_word(lexicon, params, previous, typed + start, end - start, &word, &log_probability)) {
            score += log_probability;
            previous = word;
        } else if (word_beside_symbol(lexicon, params, typed + start, end - start, &known_first, &symbol_cost)) {
            score += score_beside_symbol(
                lexicon, params, previous, typed + start + known_first, symbol_cost, end - start, &word);
            previous = word;
        } else {
            score += params->unknown_word + params->unknown_letter * (float)(end - start);
            previous = NO_WORD;
            *all_known = 0;
        }
        start = end + 1;
    }
    return score;
}

/* The work of duo_correct_english. A `pool` that is not NULL also receives the readings of
   every search, for duo_english_readings. The pool does not change the result. */
static int correct_english(
    const duo_lexicon *lexicon, const duo_params *params,
    const char *previous_word, const char *typed, duo_result *result, float *typed_score_out,
    reading_pool_t *pool) {
    int length = english_input_length(typed);
    if (lexicon == NULL || params == NULL || result == NULL || length == 0) return 0;
    uint32_t previous = NO_WORD;
    if (previous_word != NULL && previous_word[0] != 0 && strlen(previous_word) <= MAX_DEPTH) {
        previous = find_word(lexicon, previous_word, (int)strlen(previous_word));
    }

    int all_known;
    float typed_score = score_as_typed(lexicon, params, typed, length, previous, &all_known);
    float margin = all_known ? params->margin_known : params->margin_unknown;
    if (typed_score_out != NULL) *typed_score_out = typed_score;

    duo_result best;
    memcpy(best.text, typed, (size_t)length + 1);
    best.consumed = length;
    best.score = typed_score;
    float best_gain = 0.0f;

    duo_result reading;
    if (pool != NULL) pool->extra_slip = 0.0f;
    if (decode(lexicon, params, typed, typed, length, previous, &reading, pool)) {
        float gain = reading.score - typed_score;
        if (strcmp(reading.text, typed) != 0 && gain >= margin && gain > best_gain) {
            best = reading;
            best_gain = gain;
        }
    }

    /* A space typed one key early or one key late: move each space one place to either side,
       read the result, and charge the cost of the shifted space. */
    char shifted[DUO_MAX_TYPED + 1];
    if (pool != NULL) pool->extra_slip = params->shifted_space;
    for (int index = 1; index + 1 < length; index++) {
        if (typed[index] != ' ') continue;
        for (int direction = -1; direction <= 1; direction += 2) {
            int other = index + direction;
            if (typed[other] == ' ' || other == 0 || other + 1 == length) continue;
            memcpy(shifted, typed, (size_t)length + 1);
            shifted[index] = typed[other];
            shifted[other] = ' ';
            if (english_input_length(shifted) == 0) continue;
            if (!decode(lexicon, params, shifted, typed, length, previous, &reading, pool)) continue;
            float gain = reading.score - params->shifted_space - typed_score;
            if (strcmp(reading.text, typed) != 0 && gain >= margin && gain > best_gain) {
                best = reading;
                best.score = reading.score - params->shifted_space;
                best_gain = gain;
            }
        }
    }
    *result = best;
    result->consumed = length;
    return 1;
}

int duo_correct_english(
    const duo_lexicon *lexicon, const duo_params *params,
    const char *previous_word, const char *typed, duo_result *result) {
    return correct_english(lexicon, params, previous_word, typed, result, NULL, NULL);
}

/* The most readings that one call collects before it sorts them: the beam of each search, for
   the text as typed and for each shifted space. */
#define READING_POOL (MAX_BEAM * 8)

static int compare_readings_by_score(const void *first, const void *second) {
    float a = ((const duo_reading *)first)->score;
    float b = ((const duo_reading *)second)->score;
    return (a < b) - (a > b);
}

/* The typed text with one word changed: `word_start` to `word_end` replaced by `word`. Returns 0
   when the text does not fit. */
static int replace_word(const char *typed, int word_start, int word_end, const char *word, char *text) {
    size_t head = (size_t)word_start, middle = strlen(word), tail = strlen(typed + word_end);
    if (head + middle + tail + 1 > DUO_TEXT_SIZE) return 0;
    memcpy(text, typed, head);
    memcpy(text + head, word, middle);
    memcpy(text + head + middle, typed + word_end, tail + 1);
    return 1;
}

/* Adds the readings that differ from the typed text in one apostrophe of one word: an
   apostrophe the person left out ("its going" read as "it's going"), and an apostrophe typed in
   a word that the lexicon also holds without it ("it's tail" read as "its tail"). Each reading
   gets the score of its words read exactly, less the cost of that one slip.

   The search keeps one reading per last word, so in "its going" the reading "it's going" loses
   to the text as typed inside the search and never reaches the list. These readings let a
   caller that ranks the readings with the words around them, such as the language model of the
   keyboard, see both forms. duo_correct_english does not read them, so its choice stays. */
static void add_apostrophe_readings(
    const duo_lexicon *lexicon, const duo_params *params, const char *typed, const char *previous_word,
    reading_pool_t *pool) {
    int length = (int)strlen(typed);
    uint32_t previous = NO_WORD;
    if (previous_word != NULL && previous_word[0] != 0 && strlen(previous_word) <= MAX_DEPTH) {
        previous = find_word(lexicon, previous_word, (int)strlen(previous_word));
    }
    char word[MAX_DEPTH + 2];
    char text[DUO_TEXT_SIZE];
    int start = 0;
    while (start < length) {
        int end = start;
        int apostrophes = 0, letters_only = 1;
        while (end < length && typed[end] != ' ') {
            if (typed[end] == '\'') apostrophes++;
            else if (!is_letter(typed[end])) letters_only = 0;
            end++;
        }
        int word_length = end - start;
        if (letters_only && word_length >= 2 && word_length < MAX_DEPTH) {
            if (apostrophes == 0) {
                /* An apostrophe between two letters of the word. */
                for (int place = 1; place < word_length; place++) {
                    memcpy(word, typed + start, (size_t)place);
                    word[place] = '\'';
                    memcpy(word + place + 1, typed + start + place, (size_t)(word_length - place));
                    word[word_length + 1] = 0;
                    if (!is_known_word(lexicon, word, word_length + 1)) continue;
                    if (!replace_word(typed, start, end, word, text)) continue;
                    int all_known;
                    float score = score_as_typed(lexicon, params, text, (int)strlen(text), previous, &all_known);
                    pool_add(pool, text, score - params->omission_of_apostrophe, params->omission_of_apostrophe);
                }
            } else if (apostrophes == 1) {
                int bare_length = 0;
                for (int index = start; index < end; index++) {
                    if (typed[index] != '\'') word[bare_length++] = typed[index];
                }
                word[bare_length] = 0;
                if (bare_length >= 1 && is_known_word(lexicon, word, bare_length)
                    && replace_word(typed, start, end, word, text)) {
                    int all_known;
                    float score = score_as_typed(lexicon, params, text, (int)strlen(text), previous, &all_known);
                    pool_add(pool, text, score - params->insertion, params->insertion);
                }
            }
        }
        start = end + 1;
    }
}

int duo_english_readings(
    const duo_lexicon *lexicon, const duo_params *params,
    const char *previous_word, const char *typed, duo_reading *readings, int capacity) {
    if (readings == NULL || capacity < 2) return 0;
    duo_reading *items = (duo_reading *)malloc(sizeof(duo_reading) * READING_POOL);
    if (items == NULL) return 0;
    reading_pool_t pool = { items, 0, READING_POOL, typed, 0.0f };
    duo_result chosen;
    float typed_score;
    if (!correct_english(lexicon, params, previous_word, typed, &chosen, &typed_score, &pool)) {
        free(items);
        return 0;
    }
    /* The text as typed, at the score that the choice compares against. */
    if (pool.count == pool.capacity) pool.count--;
    duo_reading *as_typed = &items[pool.count++];
    memcpy(as_typed->text, typed, strlen(typed) + 1);
    as_typed->score = typed_score;
    as_typed->slip_cost = 0.0f;
    as_typed->as_typed = 1;
    as_typed->chosen = 0;

    if (params->apostrophe_readings) add_apostrophe_readings(lexicon, params, typed, previous_word, &pool);

    int chosen_index = -1;
    for (int index = 0; index < pool.count; index++) {
        if (strcmp(items[index].text, chosen.text) == 0) chosen_index = index;
    }
    /* The choice is always one of the readings of its searches. Any other outcome is a fault
       of this function, so it stops the process. */
    if (chosen_index < 0) abort();
    items[chosen_index].chosen = 1;

    qsort(items, (size_t)pool.count, sizeof(duo_reading), compare_readings_by_score);
    int count = pool.count < capacity ? pool.count : capacity;
    memcpy(readings, items, sizeof(duo_reading) * (size_t)count);
    /* The text as typed and the choice stay in the list when the list is cut. */
    for (int index = count; index < pool.count; index++) {
        if (!items[index].as_typed && !items[index].chosen) continue;
        int slot = count - 1;
        while (readings[slot].as_typed || readings[slot].chosen) slot--;
        readings[slot] = items[index];
    }
    free(items);
    return count;
}

/* ---- Pinyin ---- */

/* Order of the word candidates. The words that the typed letters spell exactly come first,
   longest first. The words that assume a typing slip come after all of them, lowest slip cost
   first, so a repaired reading never stands ahead of a word the person did type. */
static int compare_edges_exact_then_longest(const void *first, const void *second) {
    const edge_t *a = (const edge_t *)first;
    const edge_t *b = (const edge_t *)second;
    int a_exact = a->cost == 0.0f;
    int b_exact = b->cost == 0.0f;
    if (a_exact != b_exact) return b_exact - a_exact;
    if (a_exact) return b->end - a->end;
    if (a->cost < b->cost) return -1;
    if (a->cost > b->cost) return 1;
    return b->end - a->end;
}

int duo_convert_pinyin(
    const duo_lexicon *lexicon, const duo_params *params,
    const char *typed, duo_result *results, int capacity) {
    if (lexicon == NULL || params == NULL || typed == NULL || results == NULL || capacity < 1) return 0;
    /* The candidates below read every edge as a node of the main lexicon. Only an English
       lexicon takes a supplement, so a lexicon with one is not valid here. */
    if (lexicon->supplement != NULL) return 0;
    size_t length = strlen(typed);
    if (length == 0 || length > DUO_MAX_TYPED) return 0;
    for (size_t index = 0; index < length; index++) {
        if (!is_letter(typed[index])) return 0;
    }

    int count = 0;
    if (decode(lexicon, params, typed, typed, (int)length, NO_WORD, &results[0], NULL)) count = 1;
    if (count == capacity) return count;

    /* The words that stand for the first letters only: exact spellings longest first, then
       the words that assume a slip. */
    edge_t *edges = (edge_t *)malloc(sizeof(edge_t) * MAX_EDGES);
    if (edges == NULL) return count;
    int edge_count = find_edges(lexicon, params, typed, typed, (int)length, 0, edges);
    qsort(edges, (size_t)edge_count, sizeof(edge_t), compare_edges_exact_then_longest);
    for (int edge_index = 0; edge_index < edge_count && count < capacity; edge_index++) {
        node_t node = node_at(lexicon, edges[edge_index].node);
        for (uint32_t word = node.first_word; word < node.first_word + node.word_count && count < capacity; word++) {
            const char *text = word_text(lexicon, word);
            if (strlen(text) + 1 > DUO_TEXT_SIZE) continue;
            int seen = 0;
            for (int index = 0; index < count; index++) {
                if (strcmp(results[index].text, text) == 0) {
                    seen = 1;
                    break;
                }
            }
            if (seen) continue;
            strcpy(results[count].text, text);
            results[count].consumed = edges[edge_index].end;
            results[count].score = word_log_probability(lexicon, word) - edges[edge_index].cost;
            count++;
        }
    }
    free(edges);
    return count;
}
