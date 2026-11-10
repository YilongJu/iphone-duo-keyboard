// Adapter program between the typing evaluation and the sunpinyin input method engine.
//
// Usage: sunpinyin_cli MODE USER_DATA_DIR < cases.tsv > outputs.tsv
//   MODE           default, correction or fuzzy
//   USER_DATA_DIR  an empty folder for the engine's history file and user dictionary
//
// Each input line holds a case id, a tab, and the typed letters a to z.
// Each output line holds four fields separated by tabs: the case id, the way the output was
// read ("sentence" or "words"), the output, and the engine's own split of the letters.
//
// The program types the letters into a sunpinyin session as key presses and reads the first
// candidate. It never commits text, so the engine does not learn from one case to the next.
//
// Exit codes: 2 wrong arguments, 3 the engine did not create a session, 4 a malformed input
// line, 5 the engine holds a different number of letters than the case, 6 the session did not
// return to its empty state.

#include <sunpinyin.h>

#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

// The five spelling repairs that the settings window of ibus-sunpinyin offers
// (wrapper/ibus/setup/main.py, class CorrectionSetupDialog, sunpinyin v3.0.0-rc2).
// The library itself ships an empty list.
static const char* const kCorrectionPairs[][2] = {
    {"gn", "ng"}, {"uen", "un"}, {"img", "ing"}, {"iou", "iu"}, {"uei", "ui"},
};

// The 14 sound pairs that the settings window of ibus-sunpinyin offers
// (wrapper/ibus/setup/main.py, class FuzzySetupDialog, sunpinyin v3.0.0-rc2).
static const char* const kFuzzyPairs[][2] = {
    {"sh", "s"},   {"zh", "z"},   {"ch", "c"},     {"an", "ang"},   {"on", "ong"},
    {"en", "eng"}, {"in", "ing"}, {"eng", "ong"},  {"ian", "iang"}, {"uan", "uang"},
    {"n", "l"},    {"f", "h"},    {"l", "r"},      {"k", "g"},
};

template <size_t N>
static string_pairs to_pairs(const char* const (&table)[N][2])
{
    string_pairs pairs;
    for (size_t i = 0; i < N; ++i)
        pairs.push_back(std::make_pair(std::string(table[i][0]), std::string(table[i][1])));
    return pairs;
}

// sunpinyin stores text as 32-bit code points (TWCHAR). The evaluation reads UTF-8.
static std::string utf8(const TWCHAR* text)
{
    std::string bytes;
    if (text == NULL)
        return bytes;
    for (; *text != 0; ++text) {
        const unsigned c = *text;
        if (c < 0x80) {
            bytes += static_cast<char>(c);
        } else if (c < 0x800) {
            bytes += static_cast<char>(0xC0 | (c >> 6));
            bytes += static_cast<char>(0x80 | (c & 0x3F));
        } else if (c < 0x10000) {
            bytes += static_cast<char>(0xE0 | (c >> 12));
            bytes += static_cast<char>(0x80 | ((c >> 6) & 0x3F));
            bytes += static_cast<char>(0x80 | (c & 0x3F));
        } else {
            bytes += static_cast<char>(0xF0 | (c >> 18));
            bytes += static_cast<char>(0x80 | ((c >> 12) & 0x3F));
            bytes += static_cast<char>(0x80 | ((c >> 6) & 0x3F));
            bytes += static_cast<char>(0x80 | (c & 0x3F));
        }
    }
    return bytes;
}

// The view computes its sentence candidates only while a window handler is attached.
// This handler draws nothing and counts the commits, which must stay at zero.
class CQuietWinHandler : public CIMIWinHandler
{
public:
    CQuietWinHandler() : commits(0) {}
    virtual void commit(const TWCHAR*) { ++commits; }
    virtual void throwBackKey(unsigned, unsigned, unsigned) {}
    virtual void updatePreedit(const IPreeditString*) {}
    virtual void updateCandidates(const ICandidateList*) {}
    virtual void updateStatus(int, int) {}

    unsigned commits;
};

// Takes the engine's first word candidate at each position in turn. The evaluation asks for
// this when the first candidate covers only some letters. A letter where the engine does not
// offer a candidate stays as typed.
static std::string first_candidates_in_turn(CIMIContext* context, const std::string& typed)
{
    std::string output;
    unsigned at = 0;
    const unsigned last = context->getLastFrIdx();
    while (at < last) {
        CCandidates words;
        context->getCandidates(at, words);
        if (words.empty() || words[0].m_cwstr == NULL || words[0].m_end <= at) {
            output += typed[at];
            ++at;
            continue;
        }
        output += utf8(words[0].m_cwstr);
        at = words[0].m_end;
    }
    return output;
}

int main(int argc, char** argv)
{
    if (argc != 3) {
        fprintf(stderr, "usage: sunpinyin_cli default|correction|fuzzy USER_DATA_DIR < cases.tsv\n");
        return 2;
    }
    const std::string mode = argv[1];
    const std::string user_data_dir = argv[2];

    CQuanpinSchemePolicy& scheme = AQuanpinSchemePolicy::instance();
    if (mode == "correction") {
        scheme.setAutoCorrectionPairs(to_pairs(kCorrectionPairs));
        scheme.setAutoCorrecting(true);
    } else if (mode == "fuzzy") {
        scheme.setFuzzyPinyinPairs(to_pairs(kFuzzyPairs));
        scheme.setFuzzyForwarding(true);
    } else if (mode != "default") {
        fprintf(stderr, "unknown mode '%s': use default, correction or fuzzy\n", mode.c_str());
        return 2;
    }

    // The language model and the dictionary come from the folder compiled into the library.
    ASimplifiedChinesePolicy::instance().setUserDataDir(user_data_dir);

    CSunpinyinSessionFactory& factory = CSunpinyinSessionFactory::getFactory();
    factory.setLanguage(CSunpinyinSessionFactory::SIMPLIFIED_CHINESE);
    factory.setPinyinScheme(CSunpinyinSessionFactory::QUANPIN);
    factory.setInputStyle(CSunpinyinSessionFactory::CLASSIC_STYLE);
    CIMIView* view = factory.createSession();
    if (view == NULL) {
        fprintf(stderr, "sunpinyin did not create a session: check the data files lm_sc.t3g and "
                        "pydict_sc.bin, and the user data folder '%s'\n", user_data_dir.c_str());
        return 3;
    }
    CQuietWinHandler handler;
    view->attachWinHandler(&handler);
    CIMIContext* context = view->getIC();

    std::string line;
    while (std::getline(std::cin, line)) {
        const size_t tab = line.find('\t');
        if (tab == std::string::npos || tab == 0 || tab + 1 == line.size()) {
            fprintf(stderr, "malformed input line: '%s'\n", line.c_str());
            return 4;
        }
        const std::string id = line.substr(0, tab);
        const std::string typed = line.substr(tab + 1);
        for (size_t i = 0; i < typed.size(); ++i) {
            if (typed[i] < 'a' || typed[i] > 'z') {
                fprintf(stderr, "case %s holds a character outside a to z: '%s'\n", id.c_str(), typed.c_str());
                return 4;
            }
        }

        for (size_t i = 0; i < typed.size(); ++i) {
            const unsigned key = static_cast<unsigned char>(typed[i]);
            view->onKeyEvent(CKeyEvent(key, key, 0));
        }
        if (context->getLastFrIdx() != typed.size()) {
            fprintf(stderr, "case %s: the engine holds %u letters, the case has %u\n", id.c_str(),
                    context->getLastFrIdx(), static_cast<unsigned>(typed.size()));
            return 5;
        }

        CCandidateList list;
        view->getCandidateList(list, 0, static_cast<int>(view->getCandiWindowSize()));
        std::string output;
        const char* read_as;
        if (list.size() > 0 && list.candiType(0) == ICandidateList::BEST_TAIL) {
            // The first candidate is the engine's best sentence for all the letters.
            output = utf8(list.candiString(0));
            read_as = "sentence";
        } else {
            output = first_candidates_in_turn(context, typed);
            read_as = "words";
        }

        CPreEditString preedit;
        view->getPreeditString(preedit);
        const std::string segments = utf8(preedit.string());

        // Escape empties the session without a commit.
        view->onKeyEvent(CKeyEvent(IM_VK_ESCAPE, 0, 0));
        if (!context->isEmpty() || handler.commits != 0) {
            fprintf(stderr, "case %s: the session did not return to its empty state (commits %u)\n",
                    id.c_str(), handler.commits);
            return 6;
        }

        std::cout << id << '\t' << read_as << '\t' << output << '\t' << segments << '\n' << std::flush;
    }

    factory.destroySession(view);
    return 0;
}
