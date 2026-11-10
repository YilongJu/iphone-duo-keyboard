// Runs libpinyin's full-Pinyin parser and sentence guess over typed letters.
//
// Usage: libpinyin_cli SYSTEM_DATA_DIRECTORY USER_DIRECTORY [correction] [incomplete] [fuzzy] < cases > outputs
//
// Standard input holds one case per line: the case id, a tab, and the typed letters a to z.
// Standard output gets one line per case: the case id, a tab, and the text.
// Standard error gets the option value and the adapter statistics.
//
// The three mode words switch on libpinyin option flags:
//   correction   PINYIN_CORRECT_ALL, the eight spelling corrections such as gn for ng
//   incomplete   PINYIN_INCOMPLETE, a syllable typed as its first letters only
//   fuzzy        PINYIN_AMB_ALL, the ten fuzzy sound pairs such as l and n
//
// The program builds the text for one case from first sentences:
//   1. It parses the letters that are left. The parser returns the count of leading letters
//      that form whole syllables.
//   2. It guesses the sentence for the parsed letters and reads sentence 0.
//   3. When libpinyin does not give a sentence, it parses again with one letter fewer.
//   4. A letter that does not start any syllable goes to the text unchanged.
//   5. It repeats from step 1 with the letters after the parsed ones.
//
// The program never calls pinyin_train or pinyin_save, so libpinyin does not learn from one case
// to the next. USER_DIRECTORY must be a new, empty directory, because pinyin_init deletes user
// files whose format does not match the system data.
#include <pinyin.h>

#include <cstdlib>
#include <iostream>
#include <string>

namespace {

struct Statistics {
    size_t cases = 0;
    size_t searches = 0;
    size_t shortened_searches = 0;
    size_t cases_with_one_search = 0;
    size_t unchanged_letters = 0;
    size_t cases_with_unchanged_letters = 0;
};

[[noreturn]] void fail(const std::string &message) {
    std::cerr << "libpinyin_cli: " << message << std::endl;
    std::exit(1);
}

// Puts the first sentence for a leading part of `letters` in `text`.
// Returns the count of letters that the sentence covers.
// Returns 0 when libpinyin does not give a sentence for any leading part.
size_t first_candidate(pinyin_instance_t *instance, const std::string &letters, std::string &text,
                       Statistics &statistics) {
    size_t length = letters.size();
    while (length > 0) {
        const std::string attempt = letters.substr(0, length);
        pinyin_reset(instance);
        const size_t parsed = pinyin_parse_more_full_pinyins(instance, attempt.c_str());
        statistics.searches++;
        if (parsed > length)
            fail("the parser reported more letters than it got for " + attempt);
        if (parsed == 0)
            return 0;

        char *sentence = NULL;
        if (pinyin_guess_sentence(instance) && pinyin_get_sentence(instance, 0, &sentence)) {
            if (sentence == NULL || sentence[0] == '\0')
                fail("sentence 0 is empty for " + attempt);
            text = sentence;
            g_free(sentence);
            return parsed;
        }
        g_free(sentence);
        statistics.shortened_searches++;
        length = parsed - 1;
    }
    return 0;
}

std::string convert(pinyin_instance_t *instance, const std::string &letters, Statistics &statistics) {
    std::string output;
    size_t position = 0;
    size_t parts = 0;
    size_t unchanged = 0;
    const size_t searches_before = statistics.searches;
    while (position < letters.size()) {
        std::string text;
        const size_t covered = first_candidate(instance, letters.substr(position), text, statistics);
        if (covered == 0) {
            output += letters[position];
            position += 1;
            unchanged++;
        } else {
            output += text;
            position += covered;
        }
        parts++;
    }
    statistics.cases++;
    if (parts == 1 && unchanged == 0 && statistics.searches - searches_before == 1)
        statistics.cases_with_one_search++;
    statistics.unchanged_letters += unchanged;
    if (unchanged > 0)
        statistics.cases_with_unchanged_letters++;
    return output;
}

}  // namespace

int main(int argc, char **argv) {
    if (argc < 3)
        fail("usage: libpinyin_cli SYSTEM_DATA_DIRECTORY USER_DIRECTORY [correction] [incomplete] [fuzzy]");

    // The table and ordering flags of libpinyin's own test program, tests/test_pinyin.cpp.
    pinyin_option_t options = 0;
    options |= static_cast<pinyin_option_t>(USE_DIVIDED_TABLE);
    options |= static_cast<pinyin_option_t>(USE_RESPLIT_TABLE);
    options |= static_cast<pinyin_option_t>(DYNAMIC_ADJUST);
    std::string modes;
    for (int index = 3; index < argc; index++) {
        const std::string mode = argv[index];
        if (mode == "correction")
            options |= static_cast<pinyin_option_t>(PINYIN_CORRECT_ALL);
        else if (mode == "incomplete")
            options |= static_cast<pinyin_option_t>(PINYIN_INCOMPLETE);
        else if (mode == "fuzzy")
            options |= static_cast<pinyin_option_t>(PINYIN_AMB_ALL);
        else
            fail("unknown mode " + mode);
        modes += " " + mode;
    }

    pinyin_context_t *context = pinyin_init(argv[1], argv[2]);
    if (context == NULL)
        fail(std::string("pinyin_init did not load the data in ") + argv[1]);
    if (!pinyin_set_options(context, options))
        fail("pinyin_set_options returned false");
    pinyin_instance_t *instance = pinyin_alloc_instance(context);
    if (instance == NULL)
        fail("pinyin_alloc_instance returned NULL");

    Statistics statistics;
    std::string line;
    while (std::getline(std::cin, line)) {
        const size_t tab = line.find('\t');
        if (tab == std::string::npos || tab == 0)
            fail("an input line does not hold an id, a tab and letters: " + line);
        const std::string id = line.substr(0, tab);
        const std::string letters = line.substr(tab + 1);
        if (letters.empty())
            fail("the case " + id + " does not hold letters");
        for (const char letter : letters) {
            if (letter < 'a' || letter > 'z')
                fail("the case " + id + " holds a character outside a to z");
        }
        std::cout << id << '\t' << convert(instance, letters, statistics) << '\n';
    }
    std::cout.flush();
    pinyin_free_instance(instance);
    pinyin_fini(context);

    std::cerr << "modes:" << (modes.empty() ? " none" : modes) << '\n'
              << "options: 0x" << std::hex << options << std::dec << '\n'
              << "cases: " << statistics.cases << '\n'
              << "cases where one search covered all letters: " << statistics.cases_with_one_search << '\n'
              << "searches: " << statistics.searches << '\n'
              << "searches repeated with fewer letters: " << statistics.shortened_searches << '\n'
              << "cases with a letter left unchanged: " << statistics.cases_with_unchanged_letters << '\n'
              << "letters left unchanged: " << statistics.unchanged_letters << '\n';
    return 0;
}
