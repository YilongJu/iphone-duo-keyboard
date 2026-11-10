// Runs the Google Pinyin decoder (libgooglepinyin) over typed letters.
//
// Usage: googlepinyin_cli SYSTEM_DICTIONARY USER_DICTIONARY [no-abbreviation] < cases > outputs
//
// first_candidates.h describes the input lines, the output lines and the steps for one case.
//
// One search calls im_reset_search and im_search, then reads two things. im_get_sps_str gives
// the count of letters that the decoder kept. The decoder reads 39 letters at most, and it stops
// at a letter that cannot extend a syllable. im_get_candidate gives candidate 0, the
// whole-sentence candidate for the kept letters.
//
// A case with more than 39 letters fills the decoder's window, and the window can end inside a
// syllable. The program then reads the syllable starts with im_get_spl_start_pos and searches
// again with the letters before the possible cut. search_googlepinyin holds that rule.
//
// The program never calls im_choose, so the decoder does not learn from one case to the next.
#include <pinyinime.h>

#include <cstdint>
#include <string>

#include "first_candidates.h"

using namespace ime_pinyin;
using first_candidates::fail;

namespace {

// Room for one candidate. The decoder reads 39 letters, so a candidate has 39 characters at most.
const size_t kCandidateCapacity = 128;

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

first_candidates::FirstCandidate search_once(const std::string &letters) {
    first_candidates::FirstCandidate result;
    im_reset_search();
    im_search(letters.c_str(), letters.size());
    if (im_get_sps_str(&result.covered) == NULL)
        fail("im_get_sps_str returned NULL");
    char16 candidate[kCandidateCapacity];
    if (result.covered > 0 && im_get_candidate(0, candidate, kCandidateCapacity) != NULL) {
        result.found = true;
        result.text = utf16_to_utf8(candidate);
    }
    return result;
}

first_candidates::FirstCandidate search_googlepinyin(const std::string &letters, bool window_is_cut) {
    const first_candidates::FirstCandidate result = search_once(letters);
    if (!window_is_cut || !result.found || result.covered != letters.size())
        return result;
    // The window can end inside a syllable. A cut syllable has kMaxPinyinSize - 1 letters at most
    // inside the window, so a syllable start before those letters is a safe place to stop.
    // Search again with the letters up to the last safe syllable start. The next search then
    // reads the cut syllable whole.
    const uint16 *starts = NULL;
    const size_t syllables = im_get_spl_start_pos(starts);
    const size_t last_safe_start = letters.size() - (kMaxPinyinSize - 1);
    size_t stop = 0;
    for (size_t index = 1; index < syllables; index++) {
        if (static_cast<size_t>(starts[index]) <= last_safe_start)
            stop = starts[index];
    }
    if (stop == 0)
        return result;
    return search_once(letters.substr(0, stop));
}

}  // namespace

int main(int argc, char **argv) {
    first_candidates::program_name() = "googlepinyin_cli";
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

    std::cerr << "mode: " << (abbreviation ? "stock" : "no-abbreviation") << '\n';
    // One search of the decoder reads kMaxSearchSteps - 1 letters.
    first_candidates::run_cases(search_googlepinyin, kMaxSearchSteps - 1);
    im_close_decoder();
    return 0;
}
