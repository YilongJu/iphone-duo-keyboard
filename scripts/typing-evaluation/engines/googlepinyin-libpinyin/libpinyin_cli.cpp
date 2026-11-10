// Runs libpinyin's full-Pinyin parser and sentence guess over typed letters.
//
// Usage: libpinyin_cli SYSTEM_DATA_DIRECTORY USER_DIRECTORY [correction] [incomplete] [fuzzy] < cases > outputs
//
// first_candidates.h describes the input lines, the output lines and the steps for one case.
//
// The three mode words switch on libpinyin option flags:
//   correction   PINYIN_CORRECT_ALL, the eight spelling corrections such as gn for ng
//   incomplete   PINYIN_INCOMPLETE, a syllable typed as its first letters only
//   fuzzy        PINYIN_AMB_ALL, the ten fuzzy sound pairs such as l and n
//
// One search calls pinyin_parse_more_full_pinyins, which returns the count of leading letters
// that form whole syllables. It then calls pinyin_guess_sentence and reads sentence 0 with
// pinyin_get_sentence.
//
// The program never calls pinyin_train or pinyin_save, so libpinyin does not learn from one case
// to the next. USER_DIRECTORY must be a new, empty directory, because pinyin_init deletes user
// files whose format does not match the system data.
#include <pinyin.h>

#include <string>

#include "first_candidates.h"

using first_candidates::fail;

namespace {

pinyin_instance_t *g_instance = NULL;

first_candidates::FirstCandidate search_libpinyin(const std::string &letters, bool) {
    first_candidates::FirstCandidate result;
    pinyin_reset(g_instance);
    result.covered = pinyin_parse_more_full_pinyins(g_instance, letters.c_str());
    if (result.covered == 0)
        return result;
    char *sentence = NULL;
    if (pinyin_guess_sentence(g_instance) && pinyin_get_sentence(g_instance, 0, &sentence)) {
        if (sentence == NULL)
            fail("pinyin_get_sentence returned true without a sentence for " + letters);
        result.found = true;
        result.text = sentence;
    }
    g_free(sentence);
    return result;
}

}  // namespace

int main(int argc, char **argv) {
    first_candidates::program_name() = "libpinyin_cli";
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
    // pinyin_init reports the missing user.conf of the new user directory without a line end.
    std::cerr << std::endl;
    if (!pinyin_set_options(context, options))
        fail("pinyin_set_options returned false");
    g_instance = pinyin_alloc_instance(context);
    if (g_instance == NULL)
        fail("pinyin_alloc_instance returned NULL");

    std::cerr << "modes:" << (modes.empty() ? " none" : modes) << '\n'
              << "options: 0x" << std::hex << options << std::dec << '\n';
    // One search of libpinyin reads every letter.
    first_candidates::run_cases(search_libpinyin, 0);
    pinyin_free_instance(g_instance);
    pinyin_fini(context);
    return 0;
}
