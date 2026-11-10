// Runs the Google Pinyin decoder (libgooglepinyin) over typed letters.
//
// Usage: googlepinyin_cli SYSTEM_DICTIONARY USER_DICTIONARY [no-abbreviation] < cases > outputs
//
// Standard input holds one case per line: the case id, a tab, and the typed letters a to z.
// Standard output gets one line per case: the case id, a tab, and the text.
// Standard error gets the adapter statistics.
//
// The program builds the text for one case from first candidates:
//   1. It searches with the letters that are left and reads how many letters the decoder kept.
//      The decoder keeps 39 letters at most, and it stops at a letter that cannot extend a syllable.
//   2. It reads candidate 0, the whole-sentence candidate for the kept letters.
//   3. When the decoder does not give candidate 0, it searches again with one letter fewer.
//   4. A letter that does not start any candidate goes to the text unchanged.
//   5. It repeats from step 1 with the letters after the covered ones.
//
// The program never calls im_choose, so the decoder does not learn from one case to the next.
#include <pinyinime.h>

#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>

using namespace ime_pinyin;

namespace {

// Room for one candidate. The decoder keeps 39 letters, so a candidate has 39 characters at most.
const size_t kCandidateCapacity = 128;

struct Statistics {
    size_t cases = 0;
    size_t searches = 0;
    size_t shortened_searches = 0;
    size_t cases_with_one_search = 0;
    size_t unchanged_letters = 0;
    size_t cases_with_unchanged_letters = 0;
};

[[noreturn]] void fail(const std::string &message) {
    std::cerr << "googlepinyin_cli: " << message << std::endl;
    std::exit(1);
}

void append_utf8(std::string &text, uint32_t code_point) {
    if (code_point < 0x80) {
        text += static_cast<char>(code_point);
    } else if (code_point < 0x800) {
        text += static_cast<char>(0xC0 | (code_point >> 6));
        text += static_cast<char>(0x80 | (code_point & 0x3F));
    } else if (code_point < 0x10000) {
        text += static_cast<char>(0xE0 | (code_point >> 12));
        text += static_cast<char>(0x80 | ((code_point >> 6) & 0x3F));
        text += static_cast<char>(0x80 | (code_point & 0x3F));
    } else {
        text += static_cast<char>(0xF0 | (code_point >> 18));
        text += static_cast<char>(0x80 | ((code_point >> 12) & 0x3F));
        text += static_cast<char>(0x80 | ((code_point >> 6) & 0x3F));
        text += static_cast<char>(0x80 | (code_point & 0x3F));
    }
}

// The decoder returns UTF-16 code units that end with a zero unit.
std::string utf16_to_utf8(const char16 *units) {
    std::string text;
    for (size_t index = 0; units[index] != 0; index++) {
        uint32_t code_point = units[index];
        if (code_point >= 0xD800 && code_point <= 0xDBFF) {
            const uint32_t low = units[index + 1];
            if (low < 0xDC00 || low > 0xDFFF)
                fail("the decoder returned a high surrogate without a low surrogate");
            code_point = 0x10000 + ((code_point - 0xD800) << 10) + (low - 0xDC00);
            index++;
        } else if (code_point >= 0xDC00 && code_point <= 0xDFFF) {
            fail("the decoder returned a low surrogate without a high surrogate");
        }
        append_utf8(text, code_point);
    }
    return text;
}

// Puts the first candidate for a leading part of `letters` in `text`.
// Returns the count of letters that the candidate covers.
// Returns 0 when the decoder does not give a candidate for any leading part.
size_t first_candidate(const std::string &letters, std::string &text, Statistics &statistics) {
    size_t length = letters.size();
    while (length > 0) {
        const std::string attempt = letters.substr(0, length);
        im_reset_search();
        im_search(attempt.c_str(), attempt.size());
        statistics.searches++;

        size_t kept = 0;
        if (im_get_sps_str(&kept) == NULL)
            fail("im_get_sps_str returned NULL");
        if (kept > length)
            fail("the decoder kept more letters than it got for " + attempt);
        if (kept == 0)
            return 0;

        char16 candidate[kCandidateCapacity];
        if (im_get_candidate(0, candidate, kCandidateCapacity) != NULL) {
            text = utf16_to_utf8(candidate);
            if (text.empty())
                fail("candidate 0 is empty for " + attempt);
            return kept;
        }
        statistics.shortened_searches++;
        length = kept - 1;
    }
    return 0;
}

std::string convert(const std::string &letters, Statistics &statistics) {
    std::string output;
    size_t position = 0;
    size_t parts = 0;
    size_t unchanged = 0;
    const size_t searches_before = statistics.searches;
    while (position < letters.size()) {
        std::string text;
        const size_t covered = first_candidate(letters.substr(position), text, statistics);
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
    if (argc != 3 && argc != 4)
        fail("usage: googlepinyin_cli SYSTEM_DICTIONARY USER_DICTIONARY [no-abbreviation]");
    bool abbreviation = true;
    if (argc == 4) {
        if (std::string(argv[3]) != "no-abbreviation")
            fail(std::string("unknown mode ") + argv[3]);
        abbreviation = false;
    }

    if (!im_open_decoder(argv[1], argv[2]))
        fail(std::string("im_open_decoder did not open ") + argv[1]);
    if (!abbreviation) {
        // The decoder then rejects one letter as a short form of a syllable.
        im_enable_shm_as_szm(false);
        im_enable_ym_as_szm(false);
    }

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
        std::cout << id << '\t' << convert(letters, statistics) << '\n';
    }
    std::cout.flush();
    im_close_decoder();

    std::cerr << "mode: " << (abbreviation ? "stock" : "no-abbreviation") << '\n'
              << "cases: " << statistics.cases << '\n'
              << "cases where one search covered all letters: " << statistics.cases_with_one_search << '\n'
              << "searches: " << statistics.searches << '\n'
              << "searches repeated with fewer letters: " << statistics.shortened_searches << '\n'
              << "cases with a letter left unchanged: " << statistics.cases_with_unchanged_letters << '\n'
              << "letters left unchanged: " << statistics.unchanged_letters << '\n';
    return 0;
}
