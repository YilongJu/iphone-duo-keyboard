/*
 * Evaluation driver for the native suggest engine of the Android Open Source Project keyboard
 * (packages/inputmethods/LatinIME, native/jni/src, Apache License 2.0).
 *
 * The driver replaces two layers that sit above the native engine on a phone:
 *   1. The JNI glue (native/jni/com_android_inputmethod_*.cpp). The driver calls the same C++
 *      classes in the same order. The engine reads and writes Java arrays through a JNIEnv, so
 *      the driver gives it a JNIEnv whose array functions work on plain C++ vectors.
 *   2. The Java code that decides which word the keyboard commits when the person presses space
 *      (Suggest.getSuggestedWordsForNonBatchInput and InputLogic.commitCurrentAutoCorrection).
 *      The driver holds a line-by-line port of that decision.
 * Each ported block names the AOSP file and method it follows.
 *
 * Input, one case per line on standard input:   id TAB context TAB typed
 * Output, one line per case and engine name:    id TAB engine-name TAB committed-text
 *
 * Usage:
 *   latinime_driver --dictionary main_en.dict --layout layout.tsv \
 *       --engine NAME:MODE:THRESHOLD [--engine ...] [--explain] [--dump-layout]
 * MODE is "token" (each space-separated token of `typed` is one composing word, as on a phone)
 * or "span" (the whole of `typed` is one touch sequence, and a typed space is a touch on the
 * space bar). THRESHOLD is the auto-correction threshold on the normalized score.
 */
#include <algorithm>
#include <cmath>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <execinfo.h>
#include <fstream>
#include <iostream>
#include <iterator>
#include <limits>
#include <map>
#include <set>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>

#include "defines.h"
#include "dictionary/interface/dictionary_header_structure_policy.h"
#include "dictionary/property/ngram_context.h"
#include "dictionary/structure/dictionary_structure_with_buffer_policy_factory.h"
#include "jni.h"
#include "suggest/core/dictionary/dictionary.h"
#include "suggest/core/layout/proximity_info.h"
#include "suggest/core/result/suggestion_results.h"
#include "suggest/core/session/dic_traverse_session.h"
#include "suggest/core/suggest_options.h"
#include "utils/autocorrection_threshold_utils.h"

namespace {

// The case in work, for the message of the fatal-signal handler.
char gCurrentCase[512] = "(before the first case)";

[[noreturn]] void fail(const std::string &message) {
    std::fprintf(stderr, "latinime_driver: %s (case: %s)\n", message.c_str(), gCurrentCase);
    std::exit(1);
}

void onFatalSignal(int signalNumber) {
    static const char prefix[] = "latinime_driver: fatal signal while processing case: ";
    void *frames[64];
    const int frameCount = backtrace(frames, 64);
    ssize_t ignored = write(STDERR_FILENO, prefix, sizeof(prefix) - 1);
    ignored = write(STDERR_FILENO, gCurrentCase, std::strlen(gCurrentCase));
    ignored = write(STDERR_FILENO, "\n", 1);
    (void) ignored;
    backtrace_symbols_fd(frames, frameCount, STDERR_FILENO);
    _exit(128 + signalNumber);
}

// ---------------------------------------------------------------------------------------------
// A JNIEnv for the host. The engine core calls seven JNI functions on the paths this driver
// uses: GetArrayLength, GetIntArrayRegion and GetFloatArrayRegion (ProximityInfo constructor),
// SetIntArrayRegion and SetFloatArrayRegion (SuggestionResults::outputSuggestions), and FindClass
// and ExceptionClear (LogUtils::logToJava, called by the Dictionary constructor). Every other
// entry of the function table stays null, so an unexpected JNI call stops the run.
// ---------------------------------------------------------------------------------------------

struct HostArray {
    bool isFloat = false;
    std::vector<jint> ints;
    std::vector<jfloat> floats;
};

HostArray makeIntArray(const size_t size, const jint value) {
    HostArray array;
    array.ints.assign(size, value);
    return array;
}

HostArray makeFloatArray(const size_t size, const jfloat value) {
    HostArray array;
    array.isFloat = true;
    array.floats.assign(size, value);
    return array;
}

jintArray asJintArray(HostArray *const array) {
    return reinterpret_cast<jintArray>(array);
}

jfloatArray asJfloatArray(HostArray *const array) {
    return reinterpret_cast<jfloatArray>(array);
}

HostArray *hostArrayOf(jarray array) {
    if (!array) {
        fail("the engine passed a null array to a JNI array function");
    }
    return reinterpret_cast<HostArray *>(array);
}

void checkRegion(const char *const function, const size_t size, const jsize start,
        const jsize length) {
    if (start < 0 || length < 0
            || static_cast<size_t>(start) + static_cast<size_t>(length) > size) {
        fail(std::string(function) + ": region " + std::to_string(start) + "+"
                + std::to_string(length) + " is outside an array of " + std::to_string(size));
    }
}

jsize JNICALL hostGetArrayLength(JNIEnv *, jarray array) {
    const HostArray *const host = hostArrayOf(array);
    return static_cast<jsize>(host->isFloat ? host->floats.size() : host->ints.size());
}

void JNICALL hostGetIntArrayRegion(JNIEnv *, jintArray array, jsize start, jsize length,
        jint *buffer) {
    const HostArray *const host = hostArrayOf(array);
    if (host->isFloat) fail("GetIntArrayRegion on a float array");
    checkRegion("GetIntArrayRegion", host->ints.size(), start, length);
    std::copy_n(host->ints.begin() + start, length, buffer);
}

void JNICALL hostGetFloatArrayRegion(JNIEnv *, jfloatArray array, jsize start, jsize length,
        jfloat *buffer) {
    const HostArray *const host = hostArrayOf(array);
    if (!host->isFloat) fail("GetFloatArrayRegion on an int array");
    checkRegion("GetFloatArrayRegion", host->floats.size(), start, length);
    std::copy_n(host->floats.begin() + start, length, buffer);
}

void JNICALL hostSetIntArrayRegion(JNIEnv *, jintArray array, jsize start, jsize length,
        const jint *buffer) {
    HostArray *const host = hostArrayOf(array);
    if (host->isFloat) fail("SetIntArrayRegion on a float array");
    checkRegion("SetIntArrayRegion", host->ints.size(), start, length);
    std::copy_n(buffer, length, host->ints.begin() + start);
}

void JNICALL hostSetFloatArrayRegion(JNIEnv *, jfloatArray array, jsize start, jsize length,
        const jfloat *buffer) {
    HostArray *const host = hostArrayOf(array);
    if (!host->isFloat) fail("SetFloatArrayRegion on an int array");
    checkRegion("SetFloatArrayRegion", host->floats.size(), start, length);
    std::copy_n(buffer, length, host->floats.begin() + start);
}

// LogUtils::logToJava looks for android.util.Log. Its own comment says a missing class is the
// expected result off the device, and it then returns without logging.
jclass JNICALL hostFindClass(JNIEnv *, const char *) {
    return nullptr;
}

void JNICALL hostExceptionClear(JNIEnv *) {}

// Static storage, so every function pointer starts as null.
JNINativeInterface_ gJniFunctions;
JNIEnv gJniEnv;

JNIEnv *hostJniEnv() {
    gJniFunctions.GetArrayLength = hostGetArrayLength;
    gJniFunctions.GetIntArrayRegion = hostGetIntArrayRegion;
    gJniFunctions.GetFloatArrayRegion = hostGetFloatArrayRegion;
    gJniFunctions.SetIntArrayRegion = hostSetIntArrayRegion;
    gJniFunctions.SetFloatArrayRegion = hostSetFloatArrayRegion;
    gJniFunctions.FindClass = hostFindClass;
    gJniFunctions.ExceptionClear = hostExceptionClear;
    gJniEnv.functions = &gJniFunctions;
    return &gJniEnv;
}

// ---------------------------------------------------------------------------------------------
// Text helpers
// ---------------------------------------------------------------------------------------------

typedef std::vector<int> CodePoints;

CodePoints decodeUtf8(const std::string &text) {
    CodePoints codePoints;
    size_t i = 0;
    while (i < text.size()) {
        const unsigned char lead = static_cast<unsigned char>(text[i]);
        int extra = 0;
        int codePoint = 0;
        if (lead < 0x80) {
            codePoint = lead;
        } else if ((lead & 0xE0) == 0xC0) {
            extra = 1;
            codePoint = lead & 0x1F;
        } else if ((lead & 0xF0) == 0xE0) {
            extra = 2;
            codePoint = lead & 0x0F;
        } else if ((lead & 0xF8) == 0xF0) {
            extra = 3;
            codePoint = lead & 0x07;
        } else {
            fail("invalid UTF-8 in the input");
        }
        if (extra > 0 && i + extra >= text.size()) {
            fail("truncated UTF-8 in the input");
        }
        for (int k = 1; k <= extra; ++k) {
            const unsigned char next = static_cast<unsigned char>(text[i + k]);
            if ((next & 0xC0) != 0x80) fail("invalid UTF-8 in the input");
            codePoint = (codePoint << 6) | (next & 0x3F);
        }
        codePoints.push_back(codePoint);
        i += extra + 1;
    }
    return codePoints;
}

std::string encodeUtf8(const CodePoints &codePoints) {
    std::string text;
    for (const int codePoint : codePoints) {
        if (codePoint < 0) {
            fail("negative code point in the engine output");
        } else if (codePoint < 0x80) {
            text.push_back(static_cast<char>(codePoint));
        } else if (codePoint < 0x800) {
            text.push_back(static_cast<char>(0xC0 | (codePoint >> 6)));
            text.push_back(static_cast<char>(0x80 | (codePoint & 0x3F)));
        } else if (codePoint < 0x10000) {
            text.push_back(static_cast<char>(0xE0 | (codePoint >> 12)));
            text.push_back(static_cast<char>(0x80 | ((codePoint >> 6) & 0x3F)));
            text.push_back(static_cast<char>(0x80 | (codePoint & 0x3F)));
        } else {
            text.push_back(static_cast<char>(0xF0 | (codePoint >> 18)));
            text.push_back(static_cast<char>(0x80 | ((codePoint >> 12) & 0x3F)));
            text.push_back(static_cast<char>(0x80 | ((codePoint >> 6) & 0x3F)));
            text.push_back(static_cast<char>(0x80 | (codePoint & 0x3F)));
        }
    }
    return text;
}

std::vector<std::string> splitKeepingEmpty(const std::string &text, const char separator) {
    std::vector<std::string> parts;
    std::string current;
    for (const char character : text) {
        if (character == separator) {
            parts.push_back(current);
            current.clear();
        } else {
            current.push_back(character);
        }
    }
    parts.push_back(current);
    return parts;
}

bool contains(const CodePoints &codePoints, const int codePoint) {
    return std::find(codePoints.begin(), codePoints.end(), codePoint) != codePoints.end();
}

// java/res/values/donottranslate-config-spacing-and-punctuations.xml
bool isWordConnector(const int codePoint) {
    return codePoint == '\'' || codePoint == '-';
}

bool isSentenceTerminator(const int codePoint) {
    return codePoint == '.' || codePoint == '?' || codePoint == '!';
}

bool isWordSeparator(const int codePoint) {
    static const int separators[] = {0x09, 0x20, 0x0A, 0xA0, '(', ')', '[', ']', '{', '}', '*',
            '&', '<', '>', '+', '=', '|', '.', ',', ';', ':', '!', '?', '/', '_', '"'};
    return std::find(std::begin(separators), std::end(separators), codePoint)
            != std::end(separators);
}

// The class \s of java.util.regex.
bool isJavaRegexWhitespace(const int codePoint) {
    return codePoint == ' ' || codePoint == '\t' || codePoint == '\n' || codePoint == 0x0B
            || codePoint == '\f' || codePoint == '\r';
}

// Pattern.compile("\\s+").split(text) in Java 8 and later: a leading empty string stays, the
// trailing empty strings go, and a text without a match comes back as one element.
std::vector<CodePoints> javaSplitOnWhitespace(const CodePoints &text) {
    std::vector<CodePoints> parts;
    CodePoints current;
    bool matched = false;
    size_t i = 0;
    while (i < text.size()) {
        if (isJavaRegexWhitespace(text[i])) {
            matched = true;
            while (i < text.size() && isJavaRegexWhitespace(text[i])) ++i;
            parts.push_back(current);
            current.clear();
        } else {
            current.push_back(text[i]);
            ++i;
        }
    }
    parts.push_back(current);
    if (!matched) {
        return parts;
    }
    while (!parts.empty() && parts.back().empty()) parts.pop_back();
    return parts;
}

// A Java cast from float to int saturates. The same cast is undefined in C++ when the value is
// out of range, and the whitelist score (2147483646) rounds up to 2^31 as a float.
int javaFloatToInt(const float value) {
    if (std::isnan(value)) return 0;
    if (value >= 2147483648.0f) return std::numeric_limits<int>::max();
    if (value <= -2147483648.0f) return std::numeric_limits<int>::min();
    return static_cast<int>(value);
}

// ---------------------------------------------------------------------------------------------
// Keyboard layout and the proximity grid
// ---------------------------------------------------------------------------------------------

struct Key {
    int code;
    int x;
    int y;
    int width;
    int height;
};

struct Layout {
    int keyboardWidth = 0;
    int keyboardHeight = 0;
    int mostCommonKeyWidth = 0;
    int mostCommonKeyHeight = 0;
    std::vector<Key> keys; // In the order of KeyboardParams.ROW_COLUMN_COMPARATOR.
};

// java/res/values/config-common.xml: config_keyboard_grid_width and config_keyboard_grid_height.
const int kGridWidth = 32;
const int kGridHeight = 16;
// ProximityInfo.java: SEARCH_DISTANCE, in key widths.
const float kSearchDistance = 1.2f;

int parseInt(const std::string &text) {
    char *end = nullptr;
    const long value = std::strtol(text.c_str(), &end, 10);
    if (text.empty() || *end != '\0') {
        fail("not an integer: '" + text + "'");
    }
    return static_cast<int>(value);
}

Layout readLayout(const std::string &path) {
    std::ifstream input(path);
    if (!input) {
        fail("cannot open the layout file " + path);
    }
    Layout layout;
    std::string line;
    while (std::getline(input, line)) {
        if (line.empty()) continue;
        const std::vector<std::string> fields = splitKeepingEmpty(line, '\t');
        if (fields[0] == "keyboard_width" && fields.size() == 2) {
            layout.keyboardWidth = parseInt(fields[1]);
        } else if (fields[0] == "keyboard_height" && fields.size() == 2) {
            layout.keyboardHeight = parseInt(fields[1]);
        } else if (fields[0] == "most_common_key_width" && fields.size() == 2) {
            layout.mostCommonKeyWidth = parseInt(fields[1]);
        } else if (fields[0] == "most_common_key_height" && fields.size() == 2) {
            layout.mostCommonKeyHeight = parseInt(fields[1]);
        } else if (fields[0] == "key" && fields.size() == 6) {
            Key key;
            key.code = parseInt(fields[1]);
            key.x = parseInt(fields[2]);
            key.y = parseInt(fields[3]);
            key.width = parseInt(fields[4]);
            key.height = parseInt(fields[5]);
            layout.keys.push_back(key);
        } else {
            fail("unknown line in the layout file: " + line);
        }
    }
    if (layout.keyboardWidth <= 0 || layout.keyboardHeight <= 0 || layout.mostCommonKeyWidth <= 0
            || layout.mostCommonKeyHeight <= 0 || layout.keys.empty()) {
        fail("the layout file lacks a size or a key");
    }
    if (static_cast<int>(layout.keys.size()) > MAX_KEY_COUNT_IN_A_KEYBOARD) {
        fail("the layout holds more keys than MAX_KEY_COUNT_IN_A_KEYBOARD");
    }
    for (const Key &key : layout.keys) {
        // ProximityInfo.needsProximityInfo keeps a key when its code is CODE_SPACE or above.
        if (key.code < KEYCODE_SPACE) {
            fail("the layout holds a key below the space code");
        }
    }
    // KeyboardParams.ROW_COLUMN_COMPARATOR: top to bottom, then left to right.
    std::stable_sort(layout.keys.begin(), layout.keys.end(), [](const Key &left, const Key &right) {
        if (left.y != right.y) return left.y < right.y;
        return left.x < right.x;
    });
    return layout;
}

// Key.squaredDistanceToEdge
int squaredDistanceToEdge(const Key &key, const int x, const int y) {
    const int left = key.x;
    const int right = left + key.width;
    const int top = key.y;
    const int bottom = top + key.height;
    const int edgeX = x < left ? left : (x > right ? right : x);
    const int edgeY = y < top ? top : (y > bottom ? bottom : y);
    const int dx = x - edgeX;
    const int dy = y - edgeY;
    return dx * dx + dy * dy;
}

// ProximityInfo.computeNearestNeighbors and the first half of createNativeProximityInfo in
// java/src/com/android/inputmethod/keyboard/ProximityInfo.java: for each cell of a 32 by 16 grid,
// the codes of the keys whose edge is closer than 1.2 key widths to the cell center.
std::vector<int> computeProximityChars(const Layout &layout) {
    const int gridSize = kGridWidth * kGridHeight;
    const int cellWidth = (layout.keyboardWidth + kGridWidth - 1) / kGridWidth;
    const int cellHeight = (layout.keyboardHeight + kGridHeight - 1) / kGridHeight;
    const int threshold = static_cast<int>(layout.mostCommonKeyWidth * kSearchDistance);
    const int thresholdSquared = threshold * threshold;
    const int lastPixelXCoordinate = kGridWidth * cellWidth - 1;
    const int lastPixelYCoordinate = kGridHeight * cellHeight - 1;
    const int halfCellWidth = cellWidth / 2;
    const int halfCellHeight = cellHeight / 2;
    std::vector<std::vector<int>> gridNeighbors(gridSize);
    for (const Key &key : layout.keys) {
        const int topPixelWithinThreshold = key.y - threshold;
        const int yDeltaToGrid = topPixelWithinThreshold % cellHeight;
        const int yMiddleOfTopCell = topPixelWithinThreshold - yDeltaToGrid + halfCellHeight;
        const int yStart = std::max(halfCellHeight,
                yMiddleOfTopCell + (yDeltaToGrid <= halfCellHeight ? 0 : cellHeight));
        const int yEnd = std::min(lastPixelYCoordinate, key.y + key.height + threshold);

        const int leftPixelWithinThreshold = key.x - threshold;
        const int xDeltaToGrid = leftPixelWithinThreshold % cellWidth;
        const int xMiddleOfLeftCell = leftPixelWithinThreshold - xDeltaToGrid + halfCellWidth;
        const int xStart = std::max(halfCellWidth,
                xMiddleOfLeftCell + (xDeltaToGrid <= halfCellWidth ? 0 : cellWidth));
        const int xEnd = std::min(lastPixelXCoordinate, key.x + key.width + threshold);

        int baseIndexOfCurrentRow = (yStart / cellHeight) * kGridWidth + (xStart / cellWidth);
        for (int centerY = yStart; centerY <= yEnd; centerY += cellHeight) {
            int index = baseIndexOfCurrentRow;
            for (int centerX = xStart; centerX <= xEnd; centerX += cellWidth) {
                if (squaredDistanceToEdge(key, centerX, centerY) < thresholdSquared) {
                    if (index < 0 || index >= gridSize) {
                        fail("a key reaches a cell outside the proximity grid");
                    }
                    gridNeighbors[index].push_back(key.code);
                }
                ++index;
            }
            baseIndexOfCurrentRow += kGridWidth;
        }
    }
    std::vector<int> proximityChars(gridSize * MAX_PROXIMITY_CHARS_SIZE, NOT_A_CODE_POINT);
    for (int cell = 0; cell < gridSize; ++cell) {
        if (static_cast<int>(gridNeighbors[cell].size()) > MAX_PROXIMITY_CHARS_SIZE) {
            fail("a grid cell has more neighbor keys than MAX_PROXIMITY_CHARS_SIZE");
        }
        for (size_t j = 0; j < gridNeighbors[cell].size(); ++j) {
            proximityChars[cell * MAX_PROXIMITY_CHARS_SIZE + j] = gridNeighbors[cell][j];
        }
    }
    return proximityChars;
}

// ---------------------------------------------------------------------------------------------
// The engine: dictionary, proximity info, and one lookup
// ---------------------------------------------------------------------------------------------

// The three previous-word slots of NgramContext.java. An empty slot holds no code points and is
// not a sentence start.
struct PreviousWords {
    CodePoints codePoints[MAX_PREV_WORD_COUNT_FOR_N_GRAM];
    bool isBeginningOfSentence[MAX_PREV_WORD_COUNT_FOR_N_GRAM];

    PreviousWords() {
        for (bool &flag : isBeginningOfSentence) flag = false;
    }
};

// SuggestedWords.SuggestedWordInfo, with the fields the commit decision reads.
struct Suggestion {
    CodePoints word;
    int score = 0;
    int kindAndFlags = 0;

    int kind() const {
        return kindAndFlags & 0xFF; // KIND_MASK_KIND
    }
    bool isAppropriateForAutoCorrection() const {
        // KIND_FLAG_APPROPRIATE_FOR_AUTO_CORRECTION
        return (static_cast<unsigned int>(kindAndFlags) & 0x10000000u) != 0;
    }
};

// SuggestionResults.SuggestedWordInfoComparator: higher score first, then fewer code points,
// then the word in string order.
struct SuggestionOrder {
    bool operator()(const Suggestion &left, const Suggestion &right) const {
        if (left.score != right.score) return left.score > right.score;
        if (left.word.size() != right.word.size()) return left.word.size() < right.word.size();
        return left.word < right.word;
    }
};

const int kKindWhitelist = 3; // SuggestedWordInfo.KIND_WHITELIST
const int kKindShortcut = 7; // SuggestedWordInfo.KIND_SHORTCUT
// SuggestedWords.MAX_SUGGESTIONS, the capacity of the Java result set.
const size_t kMaxSuggestions = 18;
// DictionaryFacilitatorImpl.DictionaryGroup.WEIGHT_FOR_MOST_PROBABLE_LANGUAGE
const float kWeightForLocale = 1.0f;

class Engine {
 public:
    Engine(const std::string &dictionaryPath, const Layout &layout)
            : mEnv(hostJniEnv()), mLayout(layout) {
        struct stat fileStatus;
        if (stat(dictionaryPath.c_str(), &fileStatus) != 0) {
            fail("cannot read the dictionary file " + dictionaryPath);
        }
        mDictionarySize = static_cast<long>(fileStatus.st_size);

        // latinime_BinaryDictionary_open in com_android_inputmethod_latin_BinaryDictionary.cpp
        latinime::DictionaryStructureWithBufferPolicy::StructurePolicyPtr structurePolicy(
                latinime::DictionaryStructureWithBufferPolicyFactory::newPolicyForExistingDictFile(
                        dictionaryPath.c_str(), 0 /* dictOffset */,
                        static_cast<int>(mDictionarySize), false /* isUpdatable */));
        if (!structurePolicy) {
            fail("the engine did not accept the dictionary file " + dictionaryPath);
        }
        mDictionary = new latinime::Dictionary(mEnv, std::move(structurePolicy));

        // ProximityInfo.createNativeProximityInfo in Java, then
        // latinime_Keyboard_setProximityInfo in com_android_inputmethod_keyboard_ProximityInfo.cpp.
        // The three sweet-spot arrays are null: every keyboard theme of the AOSP keyboard sets
        // touchPositionCorrectionData to @null (java/res/values/themes-*.xml).
        const size_t keyCount = mLayout.keys.size();
        HostArray proximityChars = makeIntArray(0, 0);
        proximityChars.ints = computeProximityChars(mLayout);
        mProximityChars = proximityChars.ints;
        HostArray keyXCoordinates = makeIntArray(keyCount, 0);
        HostArray keyYCoordinates = makeIntArray(keyCount, 0);
        HostArray keyWidths = makeIntArray(keyCount, 0);
        HostArray keyHeights = makeIntArray(keyCount, 0);
        HostArray keyCharCodes = makeIntArray(keyCount, 0);
        for (size_t i = 0; i < keyCount; ++i) {
            keyXCoordinates.ints[i] = mLayout.keys[i].x;
            keyYCoordinates.ints[i] = mLayout.keys[i].y;
            keyWidths.ints[i] = mLayout.keys[i].width;
            keyHeights.ints[i] = mLayout.keys[i].height;
            keyCharCodes.ints[i] = mLayout.keys[i].code;
        }
        mProximityInfo = new latinime::ProximityInfo(mEnv, mLayout.keyboardWidth,
                mLayout.keyboardHeight, kGridWidth, kGridHeight, mLayout.mostCommonKeyWidth,
                mLayout.mostCommonKeyHeight, asJintArray(&proximityChars),
                static_cast<int>(keyCount), asJintArray(&keyXCoordinates),
                asJintArray(&keyYCoordinates), asJintArray(&keyWidths), asJintArray(&keyHeights),
                asJintArray(&keyCharCodes), nullptr /* sweetSpotCenterXs */,
                nullptr /* sweetSpotCenterYs */, nullptr /* sweetSpotRadii */);
    }

    // The header fields that Dictionary::logDictionaryInfo reads.
    std::string describeDictionary() const {
        const latinime::DictionaryHeaderStructurePolicy *const headerPolicy =
                mDictionary->getDictionaryStructurePolicy()->getHeaderStructurePolicy();
        std::string description = "format=" + std::to_string(headerPolicy->getFormatVersionNumber())
                + " bytes=" + std::to_string(mDictionarySize);
        for (const char *const key : {"dictionary", "locale", "version", "date"}) {
            int value[64];
            std::fill_n(value, 64, 0);
            headerPolicy->readHeaderValueOrQuestionMark(key, value, 64);
            CodePoints codePoints;
            for (int i = 0; i < 64 && value[i] != 0; ++i) codePoints.push_back(value[i]);
            description += std::string(" ") + key + "=" + encodeUtf8(codePoints);
        }
        description += std::string(" boost_exact_matches=")
                + (headerPolicy->shouldBoostExactMatches() ? "true" : "false");
        description += " multi_word_cost_multiplier="
                + std::to_string(headerPolicy->getMultiWordCostMultiplier());
        return description;
    }

    // Keyboard.getCoordinates: the center of the key that produces the code point, or
    // NOT_A_COORDINATE twice when the layout does not hold such a key.
    void coordinatesOf(const int codePoint, int *const x, int *const y) const {
        for (const Key &key : mLayout.keys) {
            if (key.code == codePoint) {
                *x = key.x + key.width / 2;
                *y = key.y + key.height / 2;
                return;
            }
        }
        *x = NOT_A_COORDINATE;
        *y = NOT_A_COORDINATE;
    }

    // The codes in the grid cell under a point, as ProximityInfo.getNearestKeys returns them.
    std::vector<int> gridNeighborsAt(const int x, const int y) const {
        const int cellWidth = (mLayout.keyboardWidth + kGridWidth - 1) / kGridWidth;
        const int cellHeight = (mLayout.keyboardHeight + kGridHeight - 1) / kGridHeight;
        const int cell = (y / cellHeight) * kGridWidth + (x / cellWidth);
        std::vector<int> codes;
        for (int j = 0; j < MAX_PROXIMITY_CHARS_SIZE; ++j) {
            const int code = mProximityChars[cell * MAX_PROXIMITY_CHARS_SIZE + j];
            if (code == NOT_A_CODE_POINT) break;
            codes.push_back(code);
        }
        return codes;
    }

    const Layout &layout() const {
        return mLayout;
    }

    // One lookup for one composing word. `typedCodePoints` is the typed word in lower case
    // and with its trailing single quotes removed, as
    // ComposedData.copyCodePointsExceptTrailingSingleQuotesAndReturnCodePointCount passes it.
    // The result is in the order of the Java result set. The lookup is cached by its arguments.
    const std::vector<Suggestion> &getSuggestions(const PreviousWords &previousWords,
            const CodePoints &typedCodePoints) {
        std::string cacheKey;
        for (size_t i = 0; i < MAX_PREV_WORD_COUNT_FOR_N_GRAM; ++i) {
            cacheKey += previousWords.isBeginningOfSentence[i] ? "<S>" : "";
            cacheKey += encodeUtf8(previousWords.codePoints[i]);
            cacheKey.push_back('\x1f');
        }
        cacheKey += encodeUtf8(typedCodePoints);
        const std::map<std::string, std::vector<Suggestion>>::const_iterator cached =
                mCache.find(cacheKey);
        if (cached != mCache.end()) {
            return cached->second;
        }
        return mCache[cacheKey] = lookUp(previousWords, typedCodePoints);
    }

    long lookUpCount() const {
        return mLookUpCount;
    }

 private:
    // BinaryDictionary.getSuggestions in Java, then latinime_BinaryDictionary_getSuggestions in
    // com_android_inputmethod_latin_BinaryDictionary.cpp, then the Java result set.
    std::vector<Suggestion> lookUp(const PreviousWords &previousWords,
            const CodePoints &typedCodePoints) {
        ++mLookUpCount;
        const int inputSize = static_cast<int>(typedCodePoints.size());
        if (inputSize > MAX_WORD_LENGTH) {
            // The Java method returns null for a word of more than 48 code points.
            return std::vector<Suggestion>();
        }
        int inputCodePoints[MAX_WORD_LENGTH];
        std::fill_n(inputCodePoints, MAX_WORD_LENGTH, NOT_A_CODE_POINT);
        // One entry more than the input, so that data() is valid for an empty input.
        std::vector<int> xCoordinates(inputSize + 1, 0);
        std::vector<int> yCoordinates(inputSize + 1, 0);
        std::vector<int> times(inputSize + 1, 0);
        std::vector<int> pointerIds(inputSize + 1, 0);
        for (int i = 0; i < inputSize; ++i) {
            inputCodePoints[i] = typedCodePoints[i];
            coordinatesOf(typedCodePoints[i], &xCoordinates[i], &yCoordinates[i]);
        }

        // NativeSuggestOptions: IS_GESTURE, USE_FULL_EDIT_DISTANCE, BLOCK_OFFENSIVE_WORDS,
        // SPACE_AWARE_GESTURE_ENABLED, WEIGHT_FOR_LOCALE_IN_THOUSANDS. Blocking offensive words
        // is the stock setting (config_block_potentially_offensive is true).
        int options[5] = {0, 0, 1, 0, static_cast<int>(kWeightForLocale * 1000)};
        const latinime::SuggestOptions suggestOptions(options, 5);

        // JniDataUtils::constructNgramContext
        int prevWordCodePoints[MAX_PREV_WORD_COUNT_FOR_N_GRAM][MAX_WORD_LENGTH];
        int prevWordCodePointCount[MAX_PREV_WORD_COUNT_FOR_N_GRAM];
        bool isBeginningOfSentence[MAX_PREV_WORD_COUNT_FOR_N_GRAM];
        for (size_t i = 0; i < MAX_PREV_WORD_COUNT_FOR_N_GRAM; ++i) {
            prevWordCodePointCount[i] = 0;
            isBeginningOfSentence[i] = false;
            const CodePoints &word = previousWords.codePoints[i];
            if (static_cast<int>(word.size()) > MAX_WORD_LENGTH) {
                continue;
            }
            std::copy(word.begin(), word.end(), prevWordCodePoints[i]);
            prevWordCodePointCount[i] = static_cast<int>(word.size());
            isBeginningOfSentence[i] = previousWords.isBeginningOfSentence[i];
        }
        const latinime::NgramContext ngramContext(prevWordCodePoints, prevWordCodePointCount,
                isBeginningOfSentence, MAX_PREV_WORD_COUNT_FOR_N_GRAM);

        // A new session for each lookup, so that a lookup does not continue the search of the
        // lookup before it. The Java class DicTraverseSession creates and initializes a session
        // through latinime_setDicTraverseSession and latinime_initDicTraverseSession.
        latinime::DicTraverseSession *const session = static_cast<latinime::DicTraverseSession *>(
                latinime::DicTraverseSession::getSessionInstance(mEnv, nullptr /* localeStr */,
                        static_cast<jlong>(mDictionarySize)));
        {
            const latinime::NgramContext emptyNgramContext;
            session->init(mDictionary, &emptyNgramContext, nullptr /* suggestOptions */);
        }

        latinime::SuggestionResults suggestionResults(MAX_RESULTS);
        if (inputSize > 0) {
            mDictionary->getSuggestions(mProximityInfo, session, xCoordinates.data(),
                    yCoordinates.data(), times.data(), pointerIds.data(), inputCodePoints,
                    inputSize, &ngramContext, &suggestOptions,
                    NOT_A_WEIGHT_OF_LANG_MODEL_VS_SPATIAL_MODEL, &suggestionResults);
        } else {
            mDictionary->getPredictions(&ngramContext, &suggestionResults);
        }

        HostArray outSuggestionCount = makeIntArray(1, 0);
        HostArray outCodePoints = makeIntArray(MAX_WORD_LENGTH * MAX_RESULTS, 0);
        HostArray outScores = makeIntArray(MAX_RESULTS, 0);
        HostArray outSpaceIndices = makeIntArray(MAX_RESULTS, 0);
        HostArray outTypes = makeIntArray(MAX_RESULTS, 0);
        HostArray outAutoCommitFirstWordConfidence = makeIntArray(1, 0);
        HostArray inOutWeightOfLangModelVsSpatialModel =
                makeFloatArray(1, NOT_A_WEIGHT_OF_LANG_MODEL_VS_SPATIAL_MODEL);
        suggestionResults.outputSuggestions(mEnv, asJintArray(&outSuggestionCount),
                asJintArray(&outCodePoints), asJintArray(&outScores),
                asJintArray(&outSpaceIndices), asJintArray(&outTypes),
                asJintArray(&outAutoCommitFirstWordConfidence),
                asJfloatArray(&inOutWeightOfLangModelVsSpatialModel));
        latinime::DicTraverseSession::releaseSessionInstance(session);

        // The loop at the end of BinaryDictionary.getSuggestions, and the bounded TreeSet of
        // com.android.inputmethod.latin.utils.SuggestionResults.
        std::set<Suggestion, SuggestionOrder> resultSet;
        const int count = outSuggestionCount.ints[0];
        for (int j = 0; j < count; ++j) {
            const int start = j * MAX_WORD_LENGTH;
            int length = 0;
            while (length < MAX_WORD_LENGTH && outCodePoints.ints[start + length] != 0) {
                ++length;
            }
            if (length == 0) {
                continue;
            }
            Suggestion suggestion;
            suggestion.word.assign(outCodePoints.ints.begin() + start,
                    outCodePoints.ints.begin() + start + length);
            suggestion.score = javaFloatToInt(
                    static_cast<float>(outScores.ints[j]) * kWeightForLocale);
            suggestion.kindAndFlags = outTypes.ints[j];
            // SuggestionResults.add: below the capacity the set takes the entry. At the capacity
            // it takes an entry that does not rank after the last one, then drops the last one.
            if (resultSet.size() < kMaxSuggestions) {
                resultSet.insert(suggestion);
            } else if (!SuggestionOrder()(*resultSet.rbegin(), suggestion)) {
                resultSet.insert(suggestion);
                resultSet.erase(std::prev(resultSet.end()));
            }
        }
        return std::vector<Suggestion>(resultSet.begin(), resultSet.end());
    }

    JNIEnv *const mEnv;
    const Layout mLayout;
    long mDictionarySize = 0;
    // The dictionary and the proximity info live for the whole run.
    latinime::Dictionary *mDictionary = nullptr;
    latinime::ProximityInfo *mProximityInfo = nullptr;
    std::vector<int> mProximityChars;
    std::map<std::string, std::vector<Suggestion>> mCache;
    long mLookUpCount = 0;
};

// ---------------------------------------------------------------------------------------------
// The Java side: previous words, and the word the keyboard commits on a space press
// ---------------------------------------------------------------------------------------------

// RichInputConnection.NUM_CHARS_TO_GET_BEFORE_CURSOR
const size_t kCharsBeforeCursor = 40;

// RichInputConnection.getNgramContextFromNthPreviousWord with n = 2 (a word is in composition),
// which calls NgramContextUtils.getNgramContextFromNthPreviousWord. `textBeforeComposing` is the
// text field up to the composing word, and `composing` is the composing word.
PreviousWords previousWordsFor(const CodePoints &textBeforeComposing, const CodePoints &composing) {
    CodePoints text = textBeforeComposing;
    text.insert(text.end(), composing.begin(), composing.end());
    if (text.size() > kCharsBeforeCursor) {
        text.erase(text.begin(), text.end() - kCharsBeforeCursor);
    }
    if (contains(text, '\n') || contains(text, '\r')) {
        fail("a line break in the context is not supported");
    }
    const std::vector<CodePoints> words = javaSplitOnWhitespace(text);
    const int wordCount = static_cast<int>(words.size());
    const int n = 2;
    PreviousWords previousWords;
    for (int i = 0; i < MAX_PREV_WORD_COUNT_FOR_N_GRAM; ++i) {
        const int focusedWordIndex = wordCount - n - i;
        if (focusedWordIndex + 1 >= 0 && focusedWordIndex + 1 < wordCount) {
            const CodePoints &wordFollowingTheNthPrevWord = words[focusedWordIndex + 1];
            if (!wordFollowingTheNthPrevWord.empty()
                    && isWordConnector(wordFollowingTheNthPrevWord[0])) {
                break;
            }
        }
        if (focusedWordIndex < 0) {
            previousWords.isBeginningOfSentence[i] = true;
            break;
        }
        const CodePoints &focusedWord = words[focusedWordIndex];
        if (focusedWord.empty()) {
            previousWords.isBeginningOfSentence[i] = true;
            break;
        }
        const int lastChar = focusedWord.back();
        if (isSentenceTerminator(lastChar)) {
            previousWords.isBeginningOfSentence[i] = true;
            break;
        }
        if (isWordSeparator(lastChar) || isWordConnector(lastChar)) {
            break;
        }
        previousWords.codePoints[i] = focusedWord;
    }
    return previousWords;
}

// SuggestedWordInfo.removeSuggestedWordInfoFromList
int removeWordFromList(const CodePoints &word, std::vector<Suggestion> *const candidates,
        const int startIndexExclusive) {
    int firstOccurrenceOfWord = -1;
    for (int i = startIndexExclusive + 1; i < static_cast<int>(candidates->size()); ++i) {
        if ((*candidates)[i].word == word) {
            if (firstOccurrenceOfWord == -1) {
                firstOccurrenceOfWord = i;
            }
            candidates->erase(candidates->begin() + i);
            --i;
        }
    }
    return firstOccurrenceOfWord;
}

// SuggestedWordInfo.removeDups
int removeDups(const CodePoints &typedWord, std::vector<Suggestion> *const candidates) {
    if (candidates->empty()) {
        return -1;
    }
    int firstOccurrenceOfWord = -1;
    if (!typedWord.empty()) {
        firstOccurrenceOfWord = removeWordFromList(typedWord, candidates, -1);
    }
    for (int i = 0; i < static_cast<int>(candidates->size()); ++i) {
        const CodePoints word = (*candidates)[i].word;
        removeWordFromList(word, candidates, i);
    }
    return firstOccurrenceOfWord;
}

float normalizedScoreOf(const Suggestion &suggestion, const CodePoints &consideredWord) {
    return latinime::AutocorrectionThresholdUtils::calcNormalizedScore(consideredWord.data(),
            static_cast<int>(consideredWord.size()), suggestion.word.data(),
            static_cast<int>(suggestion.word.size()), suggestion.score);
}

// AutoCorrectionUtils.suggestionExceedsThreshold
bool suggestionExceedsThreshold(const Suggestion &suggestion, const CodePoints &consideredWord,
        const float threshold) {
    if (suggestion.kind() == kKindWhitelist) {
        return true;
    }
    if (!suggestion.isAppropriateForAutoCorrection()) {
        return false;
    }
    return normalizedScoreOf(suggestion, consideredWord) >= threshold;
}

struct CommitResult {
    CodePoints committed;
    bool hasAutoCorrection = false;
    bool foundInDictionary = false;
    std::vector<Suggestion> results; // The Java result set, for --explain.
    PreviousWords previousWords;
    CodePoints consideredWord;
};

// Suggest.getSuggestedWordsForNonBatchInput for a word typed in lower case with the shift state
// off, followed by InputLogic.commitCurrentAutoCorrection. `typedWord` is the composing word.
CommitResult commitComposingWord(Engine *const engine, const CodePoints &textBeforeComposing,
        const CodePoints &composingForContext, const CodePoints &typedWord,
        const float autoCorrectionThreshold) {
    CommitResult result;
    // StringUtils.getTrailingSingleQuotesCount
    int trailingSingleQuotesCount = 0;
    while (trailingSingleQuotesCount < static_cast<int>(typedWord.size())
            && typedWord[typedWord.size() - 1 - trailingSingleQuotesCount] == KEYCODE_SINGLE_QUOTE) {
        ++trailingSingleQuotesCount;
    }
    const CodePoints consideredWord(typedWord.begin(),
            typedWord.end() - trailingSingleQuotesCount);
    result.consideredWord = consideredWord;
    result.previousWords = previousWordsFor(textBeforeComposing, composingForContext);

    // DictionaryFacilitatorImpl.getSuggestionResults, with the main dictionary as the one source.
    const std::vector<Suggestion> &suggestionResults =
            engine->getSuggestions(result.previousWords, consideredWord);
    result.results = suggestionResults;

    // Suggest.getTransformedSuggestedWordInfoList. The typed word is in lower case, so the two
    // capitalization transforms do not apply, and the transform only appends single quotes.
    std::vector<Suggestion> suggestionsContainer(suggestionResults);
    if (trailingSingleQuotesCount != 0) {
        for (Suggestion &suggestion : suggestionsContainer) {
            const int quotesToAppend = trailingSingleQuotesCount
                    - (contains(suggestion.word, KEYCODE_SINGLE_QUOTE) ? 1 : 0);
            for (int i = quotesToAppend - 1; i >= 0; --i) {
                suggestion.word.push_back(KEYCODE_SINGLE_QUOTE);
            }
        }
    }

    bool foundInDictionary = false;
    for (const Suggestion &suggestion : suggestionsContainer) {
        if (suggestion.word == typedWord) {
            foundInDictionary = true;
            break;
        }
    }
    result.foundInDictionary = foundInDictionary;

    removeDups(typedWord, &suggestionsContainer);

    const bool hasWhitelistedWord = !suggestionsContainer.empty()
            && suggestionsContainer[0].kind() == kKindWhitelist;
    // DecoderSpecificConstants.SHOULD_AUTO_CORRECT_USING_NON_WHITE_LISTED_SUGGESTION is false.
    const bool allowsToBeAutoCorrected = hasWhitelistedWord
            || (consideredWord.size() > 1 && !foundInDictionary);

    bool hasAutoCorrection = false;
    // The other conditions of the Java expression are constant here: correction is enabled, a
    // word is in composition, the word has neither digits nor capitals, it is not resumed, and
    // the main dictionary is present.
    if (!allowsToBeAutoCorrected || suggestionResults.empty()
            || suggestionResults[0].kind() == kKindShortcut) {
        hasAutoCorrection = false;
    } else {
        // DictionaryFacilitatorImpl sets firstSuggestionExceedsConfidenceThreshold to false.
        // Suggest.isAllowedByAutoCorrectionWithSpaceFilter limits German only.
        hasAutoCorrection = suggestionExceedsThreshold(suggestionResults[0], consideredWord,
                autoCorrectionThreshold);
    }
    result.hasAutoCorrection = hasAutoCorrection;

    // InputLogic.setSuggestedWords takes index 1 of the final list (INDEX_OF_AUTO_CORRECTION),
    // which is the first entry of the container, because the typed word goes in at index 0.
    if (hasAutoCorrection) {
        if (suggestionsContainer.empty()) {
            fail("auto-correction without a candidate to commit");
        }
        result.committed = suggestionsContainer[0].word;
    } else {
        result.committed = typedWord;
    }
    return result;
}

// ---------------------------------------------------------------------------------------------
// Engine names, cases, and output
// ---------------------------------------------------------------------------------------------

struct EngineConfig {
    std::string name;
    bool spanMode = false;
    float threshold = 0.0f;
};

EngineConfig parseEngineConfig(const std::string &text) {
    const std::vector<std::string> fields = splitKeepingEmpty(text, ':');
    if (fields.size() != 3 || fields[0].empty()) {
        fail("an engine must read NAME:MODE:THRESHOLD, got '" + text + "'");
    }
    EngineConfig config;
    config.name = fields[0];
    if (fields[1] == "token") {
        config.spanMode = false;
    } else if (fields[1] == "span") {
        config.spanMode = true;
    } else {
        fail("unknown mode '" + fields[1] + "'");
    }
    char *end = nullptr;
    config.threshold = std::strtof(fields[2].c_str(), &end);
    if (fields[2].empty() || *end != '\0' || std::isnan(config.threshold)) {
        fail("not a threshold: '" + fields[2] + "'");
    }
    return config;
}

std::string describePreviousWords(const PreviousWords &previousWords) {
    std::string text;
    for (size_t i = 0; i < MAX_PREV_WORD_COUNT_FOR_N_GRAM; ++i) {
        if (i > 0) text += " | ";
        if (previousWords.isBeginningOfSentence[i]) {
            text += "<S>";
        } else if (previousWords.codePoints[i].empty()) {
            text += "(empty)";
        } else {
            text += encodeUtf8(previousWords.codePoints[i]);
        }
    }
    return text;
}

void explainCommit(const std::string &composing, const CommitResult &result) {
    std::printf("    composing [%s]  previous words, nearest first: %s\n", composing.c_str(),
            describePreviousWords(result.previousWords).c_str());
    int rank = 0;
    for (const Suggestion &suggestion : result.results) {
        if (++rank > 8) break;
        std::printf("      %d. [%s] score %d kind %d%s normalized %.4f\n", rank,
                encodeUtf8(suggestion.word).c_str(), suggestion.score, suggestion.kind(),
                suggestion.isAppropriateForAutoCorrection() ? "" : " (not for auto-correction)",
                static_cast<double>(normalizedScoreOf(suggestion, result.consideredWord)));
    }
    std::printf("      %zu suggestions, typed word among them: %s, auto-correction: %s,"
            " committed [%s]\n", result.results.size(), result.foundInDictionary ? "yes" : "no",
            result.hasAutoCorrection ? "yes" : "no", encodeUtf8(result.committed).c_str());
}

// The text the engine leaves in the field for one case and one engine configuration.
std::string runCase(Engine *const engine, const EngineConfig &config, const std::string &context,
        const std::string &typed, const bool explain) {
    // The text field before the typed text: the context and one space.
    CodePoints textBefore = decodeUtf8(context);
    if (!textBefore.empty()) {
        textBefore.push_back(' ');
    }
    if (config.spanMode) {
        // The whole span is one composing word. For the previous-word lookup the span counts
        // as one word, so its spaces are replaced by a letter there.
        const CodePoints span = decodeUtf8(typed);
        CodePoints spanForContext = span;
        std::replace(spanForContext.begin(), spanForContext.end(), static_cast<int>(' '),
                static_cast<int>('a'));
        const CommitResult result =
                commitComposingWord(engine, textBefore, spanForContext, span, config.threshold);
        if (explain) explainCommit(typed, result);
        return encodeUtf8(result.committed);
    }
    // Each space-separated token is one composing word. A space press commits the word and
    // puts one space after it, so a later token sees the committed text as its context.
    std::string output;
    const std::vector<std::string> tokens = splitKeepingEmpty(typed, ' ');
    for (size_t i = 0; i < tokens.size(); ++i) {
        if (i > 0) {
            output.push_back(' ');
        }
        if (tokens[i].empty()) {
            continue;
        }
        const CodePoints token = decodeUtf8(tokens[i]);
        const CommitResult result =
                commitComposingWord(engine, textBefore, token, token, config.threshold);
        if (explain) explainCommit(tokens[i], result);
        output += encodeUtf8(result.committed);
        textBefore.insert(textBefore.end(), result.committed.begin(), result.committed.end());
        textBefore.push_back(' ');
    }
    return output;
}

void dumpLayout(const Engine &engine) {
    const Layout &layout = engine.layout();
    std::printf("layout: keyboard %d x %d, most common key %d x %d, grid %d x %d, %zu keys\n",
            layout.keyboardWidth, layout.keyboardHeight, layout.mostCommonKeyWidth,
            layout.mostCommonKeyHeight, kGridWidth, kGridHeight, layout.keys.size());
    for (const Key &key : layout.keys) {
        int x = 0;
        int y = 0;
        engine.coordinatesOf(key.code, &x, &y);
        std::string neighbors;
        for (const int code : engine.gridNeighborsAt(x, y)) {
            neighbors += code == ' ' ? std::string("<space>") : encodeUtf8(CodePoints(1, code));
            neighbors.push_back(' ');
        }
        std::printf("  key [%s] box x %d y %d w %d h %d, touch at (%d, %d), grid cell keys: %s\n",
                key.code == ' ' ? "<space>" : encodeUtf8(CodePoints(1, key.code)).c_str(), key.x,
                key.y, key.width, key.height, x, y, neighbors.c_str());
    }
}

int run(int argc, char **argv) {
    std::string dictionaryPath;
    std::string layoutPath;
    std::vector<EngineConfig> configs;
    bool explain = false;
    bool dump = false;
    for (int i = 1; i < argc; ++i) {
        const std::string argument = argv[i];
        const bool hasValue = i + 1 < argc;
        if (argument == "--dictionary" && hasValue) {
            dictionaryPath = argv[++i];
        } else if (argument == "--layout" && hasValue) {
            layoutPath = argv[++i];
        } else if (argument == "--engine" && hasValue) {
            configs.push_back(parseEngineConfig(argv[++i]));
        } else if (argument == "--explain") {
            explain = true;
        } else if (argument == "--dump-layout") {
            dump = true;
        } else {
            fail("unknown or incomplete argument '" + argument + "'");
        }
    }
    if (dictionaryPath.empty() || layoutPath.empty()) {
        fail("--dictionary and --layout are required");
    }

    Engine engine(dictionaryPath, readLayout(layoutPath));
    std::fprintf(stderr, "latinime_driver: dictionary %s\n", engine.describeDictionary().c_str());
    if (dump) {
        dumpLayout(engine);
    }
    if (configs.empty()) {
        if (!dump) fail("at least one --engine is required");
        return 0;
    }

    long caseCount = 0;
    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.empty()) continue;
        const std::vector<std::string> fields = splitKeepingEmpty(line, '\t');
        if (fields.size() != 3) {
            fail("a case line must hold id, context and typed, separated by tabs: " + line);
        }
        const std::string &id = fields[0];
        const std::string &context = fields[1];
        const std::string &typed = fields[2];
        std::snprintf(gCurrentCase, sizeof(gCurrentCase), "%s", id.c_str());
        // The task defines `typed` as letters a to z, apostrophe and space.
        if (typed.empty()) {
            fail("empty typed text");
        }
        for (const char character : typed) {
            if (!((character >= 'a' && character <= 'z') || character == '\'' || character == ' ')) {
                fail("typed text holds a character outside a to z, apostrophe and space");
            }
        }
        ++caseCount;
        if (explain) {
            std::printf("case %s  context [%s]  typed [%s]\n", id.c_str(), context.c_str(),
                    typed.c_str());
        }
        for (const EngineConfig &config : configs) {
            if (explain) {
                std::printf("  %s (%s, threshold %g)\n", config.name.c_str(),
                        config.spanMode ? "span" : "token", static_cast<double>(config.threshold));
            }
            const std::string output = runCase(&engine, config, context, typed, explain);
            if (explain) {
                std::printf("  %s output: [%s]\n", config.name.c_str(), output.c_str());
            } else {
                std::printf("%s\t%s\t%s\n", id.c_str(), config.name.c_str(), output.c_str());
            }
        }
    }
    std::fprintf(stderr, "latinime_driver: %ld cases, %zu engine names, %ld engine lookups\n",
            caseCount, configs.size(), engine.lookUpCount());
    return 0;
}

} // namespace

int main(int argc, char **argv) {
    for (const int signalNumber : {SIGSEGV, SIGBUS, SIGFPE, SIGILL, SIGABRT}) {
        std::signal(signalNumber, onFatalSignal);
    }
    return run(argc, argv);
}
