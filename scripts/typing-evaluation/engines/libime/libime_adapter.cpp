// Typing-evaluation adapter for libime, the Pinyin engine of fcitx5.
//
// The program reads one case per line from standard input, as "id<TAB>typed letters".
// For each case it makes a new libime::PinyinContext and types the letters one at a time,
// the way a keyboard does. It then takes the first candidate until every letter is used and
// writes "id<TAB>Chinese text" to standard output. One line of run statistics, with the
// prefix ADAPTER_STATS, goes to standard error.
//
// Usage:
//   libime_adapter --dict SC_DICT --lm LANGUAGE_MODEL --mode MODE < cases.tsv > outputs.tsv
//   libime_adapter --list-modes
//
// The program does not load a user dictionary or a typing history, and it never calls
// PinyinContext::learn(), so one case does not change the result of the next case.

#include <chrono>
#include <cstddef>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include <libime/core/userlanguagemodel.h>
#include <libime/pinyin/pinyincontext.h>
#include <libime/pinyin/pinyindictionary.h>
#include <libime/pinyin/pinyinencoder.h>
#include <libime/pinyin/pinyinime.h>

#if ADAPTER_HAS_1_1_17_API
#include <libime/pinyin/pinyincorrectionprofile.h>
#endif

namespace {

struct NamedFlag {
    const char *name;
    libime::PinyinFuzzyFlag flag;
};

#define ADAPTER_FLAG(NAME) NamedFlag{#NAME, libime::PinyinFuzzyFlag::NAME}

struct Mode {
    std::string name;
    std::vector<NamedFlag> flags;
    // Load libime's built-in QWERTY correction profile. The Correction flag needs it.
    bool qwertyCorrection;
    // Apply the settings that fcitx5-chinese-addons applies on top of the libime defaults:
    // 2 sentences, score filter 1, long-word limit 4, 15 word candidates, 35 syllables at most.
    bool fcitx5Settings;
};

std::vector<Mode> allModes() {
    std::vector<Mode> modes;
    modes.push_back({"none", {}, false, false});
    modes.push_back({"commontypo", {ADAPTER_FLAG(CommonTypo)}, false, false});
    modes.push_back({"advancedtypo", {ADAPTER_FLAG(CommonTypo), ADAPTER_FLAG(AdvancedTypo)}, false, false});
#if ADAPTER_HAS_1_1_17_API
    modes.push_back(
        {"correction", {ADAPTER_FLAG(CommonTypo), ADAPTER_FLAG(AdvancedTypo), ADAPTER_FLAG(Correction)}, true, false});
    // The default options of fcitx5-chinese-addons (im/pinyin/pinyin.h and pinyin.cpp, master
    // branch read on 2026-11-09): its "Common Typo" option sets CommonTypo and AdvancedTypo.
    modes.push_back({"fcitx5-desktop",
                     {ADAPTER_FLAG(VE_UE), ADAPTER_FLAG(CommonTypo), ADAPTER_FLAG(AdvancedTypo), ADAPTER_FLAG(Letter),
                      ADAPTER_FLAG(Inner), ADAPTER_FLAG(InnerShort)},
                     false, true});
    // On Android and iOS the same file sets the correction layout to Qwerty.
    modes.push_back({"fcitx5-mobile",
                     {ADAPTER_FLAG(VE_UE), ADAPTER_FLAG(CommonTypo), ADAPTER_FLAG(AdvancedTypo), ADAPTER_FLAG(Letter),
                      ADAPTER_FLAG(Inner), ADAPTER_FLAG(InnerShort), ADAPTER_FLAG(Correction)},
                     true, true});
    // The mobile defaults plus every optional fuzzy option of full Pinyin switched on.
    modes.push_back({"allflags",
                     {ADAPTER_FLAG(VE_UE),    ADAPTER_FLAG(CommonTypo), ADAPTER_FLAG(AdvancedTypo),
                      ADAPTER_FLAG(Letter),   ADAPTER_FLAG(Inner),      ADAPTER_FLAG(InnerShort),
                      ADAPTER_FLAG(Correction), ADAPTER_FLAG(PartialFinal), ADAPTER_FLAG(V_U),
                      ADAPTER_FLAG(AN_ANG),   ADAPTER_FLAG(EN_ENG),     ADAPTER_FLAG(IAN_IANG),
                      ADAPTER_FLAG(IN_ING),   ADAPTER_FLAG(U_OU),       ADAPTER_FLAG(UAN_UANG),
                      ADAPTER_FLAG(C_CH),     ADAPTER_FLAG(F_H),        ADAPTER_FLAG(L_N),
                      ADAPTER_FLAG(L_R),      ADAPTER_FLAG(S_SH),       ADAPTER_FLAG(Z_ZH)},
                     true, true});
#endif
    return modes;
}

struct Statistics {
    std::size_t cases = 0;
    std::size_t letters = 0;
    // Letters the context did not accept, because PinyinContext::type returned false.
    std::size_t refusedLetters = 0;
    // Cases where the first candidate did not cover every letter, so a second pick was needed.
    std::size_t casesWithMoreThanOnePick = 0;
    // Cases where PinyinContext::sentence() differs from the text built by the picks.
    std::size_t sentenceDiffersFromPicks = 0;
    // Cases where typing all letters in one call gives a different text than one letter at a time.
    std::size_t bulkTypingDiffers = 0;
    double seconds = 0;
    double slowestCaseMilliseconds = 0;
};

struct Conversion {
    std::string output;
    std::string sentence;
    std::size_t refusedLetters = 0;
    std::size_t picks = 0;
};

Conversion convert(libime::PinyinIME &ime, const Mode &mode, const std::string &typed, bool oneLetterAtATime) {
    Conversion result;
    libime::PinyinContext context(&ime);
    if (mode.fcitx5Settings) {
        context.setMaxSentenceLength(35);
    }
    if (oneLetterAtATime) {
        for (const char &letter : typed) {
            if (!context.type(&letter, 1)) {
                result.refusedLetters += 1;
            }
        }
    } else if (!context.type(typed.data(), typed.size())) {
        result.refusedLetters += typed.size();
    }
    if (context.empty()) {
        return result;
    }
    result.sentence = context.sentence();
    // The harness rule: take the first candidate until every letter is used.
    while (!context.selected()) {
        if (context.candidates().empty()) {
            throw std::runtime_error("libime gave an empty candidate list for: " + typed);
        }
        context.select(0);
        result.picks += 1;
        if (result.picks > typed.size()) {
            throw std::runtime_error("the picks did not use every letter of: " + typed);
        }
    }
    result.output = context.selectedSentence();
    return result;
}

std::string quoted(const std::string &text) { return "\"" + text + "\""; }

int listModes() {
    for (const Mode &mode : allModes()) {
        std::cout << mode.name << "\t";
        for (std::size_t i = 0; i < mode.flags.size(); i++) {
            std::cout << (i ? "," : "") << mode.flags[i].name;
        }
        if (mode.flags.empty()) {
            std::cout << "None";
        }
        std::cout << "\tqwerty_correction=" << mode.qwertyCorrection << "\tfcitx5_settings=" << mode.fcitx5Settings
                  << "\n";
    }
    return 0;
}

} // namespace

int main(int argc, char **argv) {
    std::string dictionaryPath;
    std::string languageModelPath;
    std::string modeName;
    for (int i = 1; i < argc; i++) {
        const std::string argument = argv[i];
        if (argument == "--list-modes") {
            return listModes();
        }
        if (i + 1 >= argc) {
            std::cerr << "Missing value after " << argument << "\n";
            return 2;
        }
        const std::string value = argv[++i];
        if (argument == "--dict") {
            dictionaryPath = value;
        } else if (argument == "--lm") {
            languageModelPath = value;
        } else if (argument == "--mode") {
            modeName = value;
        } else {
            std::cerr << "Unknown argument " << argument << "\n";
            return 2;
        }
    }
    if (dictionaryPath.empty() || languageModelPath.empty() || modeName.empty()) {
        std::cerr << "Usage: libime_adapter --dict SC_DICT --lm LANGUAGE_MODEL --mode MODE\n";
        return 2;
    }

    const std::vector<Mode> modes = allModes();
    const Mode *mode = nullptr;
    for (const Mode &candidate : modes) {
        if (candidate.name == modeName) {
            mode = &candidate;
        }
    }
    if (mode == nullptr) {
        std::cerr << "Mode " << modeName << " does not exist in this build against libime " << ADAPTER_LIBIME_VERSION
                  << ". Run --list-modes.\n";
        return 2;
    }

    libime::PinyinIME ime(std::make_unique<libime::PinyinDictionary>(),
                          std::make_unique<libime::UserLanguageModel>(languageModelPath.c_str()));
    ime.dict()->load(libime::PinyinDictionary::SystemDict, dictionaryPath.c_str(), libime::PinyinDictFormat::Binary);

    libime::PinyinFuzzyFlags flags{libime::PinyinFuzzyFlag::None};
    for (const NamedFlag &flag : mode->flags) {
        flags |= flag.flag;
    }
#if ADAPTER_HAS_1_1_17_API
    if (mode->qwertyCorrection) {
        ime.setCorrectionProfile(
            std::make_shared<libime::PinyinCorrectionProfile>(libime::BuiltinPinyinCorrectionProfile::Qwerty));
    }
#endif
    ime.setFuzzyFlags(flags);
    if (mode->fcitx5Settings) {
        ime.setNBest(2);
        ime.setScoreFilter(1.0F);
        ime.setPartialLongWordLimit(4);
#if ADAPTER_HAS_1_1_17_API
        ime.setWordCandidateLimit(15);
#endif
    }

    Statistics statistics;
    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.empty()) {
            continue;
        }
        const std::size_t tab = line.find('\t');
        if (tab == std::string::npos || tab == 0 || tab + 1 >= line.size()) {
            throw std::runtime_error("expected id<TAB>typed, got: " + line);
        }
        const std::string id = line.substr(0, tab);
        const std::string typed = line.substr(tab + 1);
        for (const char letter : typed) {
            if (letter < 'a' || letter > 'z') {
                throw std::runtime_error("typed text holds a character outside a to z: " + line);
            }
        }

        const auto start = std::chrono::steady_clock::now();
        const Conversion byLetter = convert(ime, *mode, typed, true);
        const double milliseconds =
            std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
        const Conversion inOneCall = convert(ime, *mode, typed, false);

        statistics.cases += 1;
        statistics.letters += typed.size();
        statistics.refusedLetters += byLetter.refusedLetters;
        statistics.casesWithMoreThanOnePick += byLetter.picks > 1;
        statistics.sentenceDiffersFromPicks += byLetter.sentence != byLetter.output;
        statistics.bulkTypingDiffers += inOneCall.output != byLetter.output;
        statistics.seconds += milliseconds / 1000.0;
        if (milliseconds > statistics.slowestCaseMilliseconds) {
            statistics.slowestCaseMilliseconds = milliseconds;
        }
        std::cout << id << "\t" << byLetter.output << "\n";
    }
    std::cout.flush();
    if (!std::cout) {
        throw std::runtime_error("writing the outputs did not finish");
    }

    std::ostringstream report;
    report << "ADAPTER_STATS {" << quoted("mode") << ": " << quoted(mode->name) << ", " << quoted("libime_version")
           << ": " << quoted(ADAPTER_LIBIME_VERSION) << ", " << quoted("flags") << ": [";
    for (std::size_t i = 0; i < mode->flags.size(); i++) {
        report << (i ? ", " : "") << quoted(mode->flags[i].name);
    }
    report << "], " << quoted("flags_value") << ": " << static_cast<long long>(ime.fuzzyFlags().toInteger()) << ", "
           << quoted("qwerty_correction") << ": " << (mode->qwertyCorrection ? "true" : "false") << ", "
           << quoted("fcitx5_settings") << ": " << (mode->fcitx5Settings ? "true" : "false") << ", "
           << quoted("nbest") << ": " << ime.nbest() << ", " << quoted("beam_size") << ": " << ime.beamSize() << ", "
           << quoted("frame_size") << ": " << ime.frameSize() << ", " << quoted("cases") << ": " << statistics.cases
           << ", " << quoted("letters") << ": " << statistics.letters << ", " << quoted("refused_letters") << ": "
           << statistics.refusedLetters << ", " << quoted("cases_with_more_than_one_pick") << ": "
           << statistics.casesWithMoreThanOnePick << ", " << quoted("sentence_differs_from_picks") << ": "
           << statistics.sentenceDiffersFromPicks << ", " << quoted("bulk_typing_differs") << ": "
           << statistics.bulkTypingDiffers << ", " << quoted("typing_seconds") << ": " << statistics.seconds << ", "
           << quoted("slowest_case_milliseconds") << ": " << statistics.slowestCaseMilliseconds << "}";
    std::cerr << report.str() << "\n";
    return 0;
}
