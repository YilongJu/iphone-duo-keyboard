#include "duo_engine.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

#define DUO_MAGIC 0x4C4F5544u
#define DUO_VERSION 2u
#define WORD_BYTES 12
#define MODEL_BACK_OFF 1u

/* The most slips the search follows inside one word. */
#define BAND 2
#define ROW (2 * BAND + 1)
/* The longest spelling the search follows, in letters. */
#define MAX_DEPTH 64
#define MAX_BEAM 16
#define MAX_EDGES 4096
#define BIG 1.0e9f

/* Marks a state with no lexicon word: the start of the text, or text kept as typed. */
#define NO_WORD 0xFFFFFFFFu

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
    const uint8_t *bytes = lexicon->nodes + 12 * (size_t)index;
    node_t node;
    node.first_child = read_u32(bytes);
    node.first_word = read_u32(bytes + 4);
    node.child_count = bytes[8];
    node.letter = bytes[9];
    node.word_count = read_u16(bytes + 10);
    return node;
}

static float word_log_probability(const duo_lexicon *lexicon, uint32_t word) {
    return read_f32(lexicon->words + WORD_BYTES * (size_t)word + 4);
}

static float word_back_off(const duo_lexicon *lexicon, uint32_t word) {
    return read_f32(lexicon->words + WORD_BYTES * (size_t)word + 8);
}

static const char *word_text(const duo_lexicon *lexicon, uint32_t word) {
    return (const char *)lexicon->strings + read_u32(lexicon->words + WORD_BYTES * (size_t)word);
}

int duo_lexicon_open_checked_before(duo_lexicon *lexicon, const void *data, size_t size) {
    const uint8_t *bytes = (const uint8_t *)data;
    if (lexicon == NULL || data == NULL || size < 32) return 0;
    if (read_u32(bytes) != DUO_MAGIC || read_u32(bytes + 4) != DUO_VERSION) return 0;
    uint32_t node_count = read_u32(bytes + 8);
    uint32_t word_count = read_u32(bytes + 12);
    uint32_t strings_size = read_u32(bytes + 16);
    uint32_t pair_count = read_u32(bytes + 20);
    uint32_t model = read_u32(bytes + 24);
    if (model > MODEL_BACK_OFF) return 0;
    size_t expected = 32 + (size_t)node_count * 12 + (size_t)word_count * WORD_BYTES
        + ((size_t)word_count + 1) * 4 + (size_t)pair_count * 8 + (size_t)strings_size;
    if (node_count == 0 || expected != size) return 0;

    lexicon->node_count = node_count;
    lexicon->word_count = word_count;
    lexicon->pair_count = pair_count;
    lexicon->strings_size = strings_size;
    lexicon->model = model;
    lexicon->nodes = bytes + 32;
    lexicon->words = lexicon->nodes + (size_t)node_count * 12;
    lexicon->pair_index = lexicon->words + (size_t)word_count * WORD_BYTES;
    lexicon->pairs = lexicon->pair_index + ((size_t)word_count + 1) * 4;
    lexicon->strings = lexicon->pairs + (size_t)pair_count * 8;
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
        if (read_u32(lexicon->words + WORD_BYTES * (size_t)word) >= strings_size) return 0;
    }
    uint32_t previous_start = 0;
    for (uint32_t word = 0; word <= word_count; word++) {
        uint32_t start = read_u32(lexicon->pair_index + 4 * (size_t)word);
        if (start < previous_start || start > pair_count) return 0;
        previous_start = start;
    }
    for (uint32_t pair = 0; pair < pair_count; pair++) {
        if (read_u32(lexicon->pairs + 8 * (size_t)pair) >= word_count) return 0;
    }
    return 1;
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
    params.short_word_budget = 5.6f;
    params.long_word_budget = 11.0f;
    params.missing_space = 5.0f;
    params.letter_for_space = 5.0f;
    params.extra_space = 5.0f;
    params.space_for_letter = 5.0f;
    params.shifted_space = 4.0f;
    params.pair_weight = 0.6f;
    params.unknown_word = -13.0f;
    params.unknown_letter = -1.2f;
    params.margin_known = 5.0f;
    params.margin_unknown = 0.0f;
    params.sentence_end_weight = 0.0f;
    params.spaces_between_words = 1;
    params.beam = 8;
    return params;
}

duo_params duo_pinyin_params(void) {
    duo_params params = duo_english_params();
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
    FIELD(short_word_budget)
    FIELD(long_word_budget)
    FIELD(missing_space)
    FIELD(letter_for_space)
    FIELD(extra_space)
    FIELD(space_for_letter)
    FIELD(shifted_space)
    FIELD(pair_weight)
    FIELD(unknown_word)
    FIELD(unknown_letter)
    FIELD(margin_known)
    FIELD(margin_unknown)
    FIELD(sentence_end_weight)
#undef FIELD
    if (strcmp(name, "beam") == 0) { params->beam = (int)value; return 1; }
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

static float substitution_cost(const duo_params *params, char typed, char intended) {
    if (typed == intended) return 0.0f;
    if (typed == ' ') return is_above_space(intended) ? params->space_for_letter : BIG;
    if (typed == '\'' || intended == '\'') return BIG;
    return keys_are_neighbors(typed, intended) ? params->adjacent_substitution : params->far_substitution;
}

/* ---- Matching one word against the typed text, with slips ---- */

typedef struct {
    int end;          /* typed position right after the word */
    uint32_t node;    /* the lexicon node whose words the typed text stands for */
    float cost;       /* total cost of the slips this match assumes */
} edge_t;

typedef struct {
    const duo_lexicon *lexicon;
    const duo_params *params;
    const char *typed;  /* the typed text from the word's first position on */
    int length;         /* count of typed bytes from that position to the end */
    int start;          /* the word's first position in the whole typed text */
    /* rows[d][b]: the lowest slip cost that lines up the first d letters of the spelling with
       the first k typed bytes, where k = d - BAND + b. Only readings within BAND slips of the
       diagonal are kept, which is why a row holds ROW numbers and not one per typed byte. */
    float rows[MAX_DEPTH + 2][ROW];
    char letters[MAX_DEPTH + 2];
    edge_t *edges;
    int edge_count;
} walk_t;

static float insertion_cost(const walk_t *walk, int index) {
    char typed = walk->typed[index];
    if (typed == ' ') return walk->params->extra_space;
    if (index > 0 && walk->typed[index - 1] == typed) return walk->params->insertion_of_double;
    return walk->params->insertion;
}

static float omission_cost(const walk_t *walk, char letter, int depth) {
    if (letter == '\'') return walk->params->omission_of_apostrophe;
    if (depth > 0 && walk->letters[depth - 1] == letter) return walk->params->omission_of_double;
    return walk->params->omission + (depth == 0 ? walk->params->first_letter_extra : 0.0f);
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
            if (walk->edge_count < MAX_EDGES) {
                edge_t *edge = &walk->edges[walk->edge_count++];
                edge->end = walk->start + consumed;
                edge->node = node_index;
                edge->cost = cost;
            }
        }
    }
    if (depth >= MAX_DEPTH) return;

    for (uint32_t child_index = node.first_child; child_index < node.first_child + node.child_count; child_index++) {
        char letter = (char)walk->lexicon->nodes[12 * (size_t)child_index + 9];
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
                    if (b >= 1) {
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

/* Fills `edges` with every lexicon node that the typed text from `start` on can stand for. */
static int find_edges(
    const duo_lexicon *lexicon, const duo_params *params,
    const char *typed, int length, int start, edge_t *edges) {
    walk_t walk;
    walk.lexicon = lexicon;
    walk.params = params;
    walk.typed = typed + start;
    walk.length = length - start;
    walk.start = start;
    walk.edges = edges;
    walk.edge_count = 0;
    for (int b = 0; b < ROW; b++) {
        int consumed = b - BAND;
        if (consumed < 0 || consumed > walk.length) walk.rows[0][b] = BIG;
        else if (consumed == 0) walk.rows[0][b] = 0.0f;
        else walk.rows[0][b] = walk.rows[0][b - 1] + insertion_cost(&walk, consumed - 1) + params->first_letter_extra;
    }
    walk_node(&walk, 0, 0);
    return walk.edge_count;
}

/* The node that spells exactly these letters, or NO_WORD. */
static uint32_t find_exact_node(const duo_lexicon *lexicon, const char *letters, int length) {
    uint32_t index = 0;
    for (int position = 0; position < length; position++) {
        node_t node = node_at(lexicon, index);
        uint32_t next = NO_WORD;
        for (uint32_t child = node.first_child; child < node.first_child + node.child_count; child++) {
            if ((char)lexicon->nodes[12 * (size_t)child + 9] == letters[position]) {
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

/* Picks the most probable word of a node after the word `previous`, and its log probability.
   With a known previous word the probability comes from the word-pair statistic and the word's
   own frequency, combined by the lexicon's model. The words of a node sit side by side in the
   word table, so the pairs of `previous` that fall inside the node are one run of its sorted
   pair list. */
static void best_word(
    const duo_lexicon *lexicon, const duo_params *params, uint32_t previous, uint32_t node_index,
    uint32_t *word, float *log_probability) {
    node_t node = node_at(lexicon, node_index);
    float top = word_log_probability(lexicon, node.first_word);
    *word = node.first_word;
    if (previous == NO_WORD || lexicon->pair_count == 0) {
        *log_probability = top;
        return;
    }
    int back_off_model = lexicon->model == MODEL_BACK_OFF;
    if (!back_off_model && params->pair_weight <= 0.0f) {
        *log_probability = top;
        return;
    }
    float own_share = 1.0f - params->pair_weight;
    /* Back-off model: a listed pair gives the chance of its second word, so the back-off
       estimate holds only for the words of the node that have no listed pair. `listed` keeps
       the listed words, to find the best word outside them. */
    uint32_t listed[32];
    int listed_count = 0;
    float best = back_off_model ? -BIG : top + logf(own_share);
    uint32_t low = read_u32(lexicon->pair_index + 4 * (size_t)previous);
    uint32_t end = read_u32(lexicon->pair_index + 4 * ((size_t)previous + 1));
    uint32_t high = end;
    while (low < high) {
        uint32_t middle = low + (high - low) / 2;
        if (read_u32(lexicon->pairs + 8 * (size_t)middle) < node.first_word) low = middle + 1;
        else high = middle;
    }
    for (uint32_t pair = low; pair < end; pair++) {
        uint32_t second = read_u32(lexicon->pairs + 8 * (size_t)pair);
        if (second >= node.first_word + node.word_count) break;
        float pair_value = read_f32(lexicon->pairs + 8 * (size_t)pair + 4);
        float value = back_off_model
            ? pair_value
            : logf(params->pair_weight * expf(pair_value) + own_share * expf(word_log_probability(lexicon, second)));
        if (back_off_model && listed_count < 32) listed[listed_count++] = second;
        if (value > best) {
            best = value;
            *word = second;
        }
    }
    if (back_off_model) {
        /* The words of a node are sorted by their own probability, so the first word without a
           listed pair has the best back-off estimate. */
        float weight = word_back_off(lexicon, previous);
        for (uint32_t candidate = node.first_word; candidate < node.first_word + node.word_count; candidate++) {
            int is_listed = 0;
            for (int index = 0; index < listed_count; index++) {
                if (listed[index] == candidate) {
                    is_listed = 1;
                    break;
                }
            }
            if (is_listed) continue;
            float value = weight + word_log_probability(lexicon, candidate);
            if (value > best) {
                best = value;
                *word = candidate;
            }
            break;
        }
    }
    *log_probability = best;
}

/* The log probability of one given word after the word `previous`. */
static float word_after(const duo_lexicon *lexicon, const duo_params *params, uint32_t previous, uint32_t word) {
    float own = word_log_probability(lexicon, word);
    if (previous == NO_WORD || lexicon->pair_count == 0) return own;
    uint32_t low = read_u32(lexicon->pair_index + 4 * (size_t)previous);
    uint32_t high = read_u32(lexicon->pair_index + 4 * ((size_t)previous + 1));
    while (low < high) {
        uint32_t middle = low + (high - low) / 2;
        uint32_t second = read_u32(lexicon->pairs + 8 * (size_t)middle);
        if (second == word) {
            float pair_value = read_f32(lexicon->pairs + 8 * (size_t)middle + 4);
            if (lexicon->model == MODEL_BACK_OFF) return pair_value;
            return logf(params->pair_weight * expf(pair_value) + (1.0f - params->pair_weight) * expf(own));
        }
        if (second < word) low = middle + 1;
        else high = middle;
    }
    if (lexicon->model == MODEL_BACK_OFF) return word_back_off(lexicon, previous) + own;
    return params->pair_weight > 0.0f ? own + logf(1.0f - params->pair_weight) : own;
}

/* The two sentence marks of a back-off lexicon sit under spellings that nobody can type. */
static uint32_t find_mark(const duo_lexicon *lexicon, char mark) {
    node_t root = node_at(lexicon, 0);
    for (uint32_t child = root.first_child; child < root.first_child + root.child_count; child++) {
        if ((char)lexicon->nodes[12 * (size_t)child + 9] == mark) {
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
    int from_position;    /* where the reading stood before its last word, or -1 at the start */
    int from_state;
    int kept_start;       /* for text kept as typed: its span in the typed text */
    int kept_end;
} state_t;

typedef struct {
    state_t states[MAX_BEAM];
    int count;
} cell_t;

/* Adds a reading to a cell. Two readings that end in the same word go on the same way, so the
   cell keeps the better one. A full cell drops its weakest reading. */
static void add_state(cell_t *cell, int beam, state_t state) {
    for (int index = 0; index < cell->count; index++) {
        state_t *existing = &cell->states[index];
        if (existing->word == state.word && existing->kept_start == state.kept_start && existing->kept_end == state.kept_end) {
            if (state.score > existing->score) *existing = state;
            return;
        }
    }
    if (cell->count < beam) {
        cell->states[cell->count++] = state;
        return;
    }
    int weakest = 0;
    for (int index = 1; index < cell->count; index++) {
        if (cell->states[index].score < cell->states[weakest].score) weakest = index;
    }
    if (state.score > cell->states[weakest].score) cell->states[weakest] = state;
}

/* Writes the reading that ends in `state` into `text`. Returns 0 when the text does not fit. */
static int write_reading(
    const duo_lexicon *lexicon, const duo_params *params, const char *typed,
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
    text[0] = 0;
    for (int index = count - 1; index >= 0; index--) {
        const state_t *state = &cells[positions[index]].states[states[index]];
        const char *piece;
        size_t piece_length;
        if (state->word != NO_WORD) {
            piece = word_text(lexicon, state->word);
            piece_length = strlen(piece);
        } else {
            piece = typed + state->kept_start;
            piece_length = (size_t)(state->kept_end - state->kept_start);
        }
        int needs_space = params->spaces_between_words && used > 0;
        if (used + piece_length + (needs_space ? 1 : 0) + 1 > DUO_TEXT_SIZE) return 0;
        if (needs_space) text[used++] = ' ';
        memcpy(text + used, piece, piece_length);
        used += piece_length;
        text[used] = 0;
    }
    return 1;
}

/* Finds the best reading of typed[0..length). Returns 1 and fills `result`, or 0 on failure.
   When the lexicon cannot read the text to its end, the unreadable parts are kept as typed. */
static int decode(
    const duo_lexicon *lexicon, const duo_params *params, const char *typed, int length,
    uint32_t previous_word, duo_result *result) {
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
    state_t first = { 0.0f, previous_word, -1, -1, -1, -1 };
    cells[0].states[0] = first;
    cells[0].count = 1;

    for (int start = 0; start < length; start++) {
        cell_t *cell = &cells[start];
        if (cell->count == 0) continue;

        /* Text the lexicon does not know stays as typed, at a price. English keeps a whole
           unknown word. Pinyin keeps one letter, so the letters around it can still be read. */
        int kept_end = start + 1;
        int keep = 1;
        if (params->spaces_between_words) {
            keep = start == 0 || typed[start - 1] == ' ';
            while (kept_end < length && typed[kept_end] != ' ') kept_end++;
            if (keep && find_exact_node(lexicon, typed + start, kept_end - start) != NO_WORD) keep = 0;
        }
        if (keep && typed[start] != ' ') {
            int next = kept_end < length && typed[kept_end] == ' ' ? kept_end + 1 : kept_end;
            for (int index = 0; index < cell->count; index++) {
                state_t state;
                state.score = cell->states[index].score + params->unknown_word
                    + params->unknown_letter * (float)(kept_end - start);
                state.word = NO_WORD;
                state.from_position = start;
                state.from_state = index;
                state.kept_start = start;
                state.kept_end = kept_end;
                add_state(&cells[next > length ? length : next], beam, state);
            }
        }

        int edge_count = find_edges(lexicon, params, typed, length, start, edges);
        for (int edge_index = 0; edge_index < edge_count; edge_index++) {
            const edge_t *edge = &edges[edge_index];
            for (int index = 0; index < cell->count; index++) {
                uint32_t word;
                float log_probability;
                best_word(lexicon, params, cell->states[index].word, edge->node, &word, &log_probability);
                state_t state;
                state.score = cell->states[index].score + log_probability - edge->cost;
                state.word = word;
                state.from_position = start;
                state.from_state = index;
                state.kept_start = -1;
                state.kept_end = -1;
                if (edge->end >= length) {
                    add_state(&cells[length], beam, state);
                } else if (!params->spaces_between_words) {
                    add_state(&cells[edge->end], beam, state);
                } else if (typed[edge->end] == ' ') {
                    add_state(&cells[edge->end + 1 > length ? length : edge->end + 1], beam, state);
                } else {
                    /* No space was typed after this word. Either the space is missing, or the
                       next byte is a letter from the row above the space bar typed in its place. */
                    state_t missing = state;
                    missing.score -= params->missing_space;
                    add_state(&cells[edge->end], beam, missing);
                    if (is_above_space(typed[edge->end]) && edge->end + 1 < length) {
                        state_t replaced = state;
                        replaced.score -= params->letter_for_space;
                        add_state(&cells[edge->end + 1], beam, replaced);
                    }
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
            float score = last->states[index].score;
            if (end_mark != NO_WORD && last->states[index].word != NO_WORD) {
                score += params->sentence_end_weight * word_after(lexicon, params, last->states[index].word, end_mark);
            }
            if (score > best_score) {
                best_score = score;
                best = index;
            }
        }
        result->score = best_score;
        result->consumed = length;
        ok = write_reading(lexicon, params, typed, cells, length, best, result->text);
    }
    free(cells);
    free(edges);
    return ok;
}

/* ---- Input checks ---- */

static int is_letter(char character) {
    return character >= 'a' && character <= 'z';
}

/* English input: letters, apostrophes and single spaces, with a letter or apostrophe at both ends. */
static int english_input_length(const char *typed) {
    size_t length = strlen(typed);
    if (length == 0 || length > DUO_MAX_TYPED) return 0;
    for (size_t index = 0; index < length; index++) {
        char character = typed[index];
        if (character == ' ') {
            if (index == 0 || index + 1 == length || typed[index - 1] == ' ') return 0;
        } else if (!is_letter(character) && character != '\'') {
            return 0;
        }
    }
    return (int)length;
}

static uint32_t find_word(const duo_lexicon *lexicon, const char *letters, int length) {
    uint32_t node = find_exact_node(lexicon, letters, length);
    return node == NO_WORD ? NO_WORD : node_at(lexicon, node).first_word;
}

/* ---- English ---- */

/* Log probability of the typed text read exactly as typed, and whether every typed word is known. */
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
        uint32_t node = find_exact_node(lexicon, typed + start, end - start);
        if (node != NO_WORD) {
            uint32_t word;
            float log_probability;
            best_word(lexicon, params, previous, node, &word, &log_probability);
            score += log_probability;
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

int duo_correct_english(
    const duo_lexicon *lexicon, const duo_params *params,
    const char *previous_word, const char *typed, duo_result *result) {
    int length = english_input_length(typed);
    if (lexicon == NULL || params == NULL || result == NULL || length == 0) return 0;
    uint32_t previous = NO_WORD;
    if (previous_word != NULL && previous_word[0] != 0 && strlen(previous_word) <= MAX_DEPTH) {
        previous = find_word(lexicon, previous_word, (int)strlen(previous_word));
    }

    int all_known;
    float typed_score = score_as_typed(lexicon, params, typed, length, previous, &all_known);
    float margin = all_known ? params->margin_known : params->margin_unknown;

    duo_result best;
    memcpy(best.text, typed, (size_t)length + 1);
    best.consumed = length;
    best.score = typed_score;
    float best_gain = 0.0f;

    duo_result reading;
    if (decode(lexicon, params, typed, length, previous, &reading)) {
        float gain = reading.score - typed_score;
        if (strcmp(reading.text, typed) != 0 && gain >= margin && gain > best_gain) {
            best = reading;
            best_gain = gain;
        }
    }

    /* A space typed one key early or one key late: move each space one place to either side,
       read the result, and charge the cost of the shifted space. */
    char shifted[DUO_MAX_TYPED + 1];
    for (int index = 1; index + 1 < length; index++) {
        if (typed[index] != ' ') continue;
        for (int direction = -1; direction <= 1; direction += 2) {
            int other = index + direction;
            if (typed[other] == ' ' || other == 0 || other + 1 == length) continue;
            memcpy(shifted, typed, (size_t)length + 1);
            shifted[index] = typed[other];
            shifted[other] = ' ';
            if (english_input_length(shifted) == 0) continue;
            if (!decode(lexicon, params, shifted, length, previous, &reading)) continue;
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
    size_t length = strlen(typed);
    if (length == 0 || length > DUO_MAX_TYPED) return 0;
    for (size_t index = 0; index < length; index++) {
        if (!is_letter(typed[index])) return 0;
    }

    int count = 0;
    if (decode(lexicon, params, typed, (int)length, NO_WORD, &results[0])) count = 1;

    /* The words that stand for the first letters only: exact spellings longest first, then
       the words that assume a slip. */
    edge_t *edges = (edge_t *)malloc(sizeof(edge_t) * MAX_EDGES);
    if (edges == NULL) return count;
    int edge_count = find_edges(lexicon, params, typed, (int)length, 0, edges);
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
