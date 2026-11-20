import UIKit
import XCTest

@testable import DuoKeyboard

/// The emoji of a word: in the top row of keys, at the start of the prediction strip, for the
/// English word right before the cursor, and on the candidate row right after the first Pinyin
/// candidate. A tap on an English emoji puts the emoji in place of the word, as the iOS
/// keyboard does. The tests read the bundled table
/// Shared/emoji-suggestions.tsv, which offers "👍" for "good" and for "好", "👋" for "你好" and
/// "💻" for "office", and nothing for "the", "我" and "xyz".
@MainActor
final class EmojiSuggestionTests: XCTestCase {
    private var keyboardView: KeyboardView!
    private var document: FakeDocument!
    private var spellChecker: FakeSpellChecker!
    private var controller: KeyboardTextController!

    private func makeController(before: String = "", chinese: Bool = false) {
        let height = KeyboardView.preferredHeight(forWidth: 466, compactHeight: false, device: .phone, landscape: false)
        keyboardView = KeyboardView(frame: CGRect(x: 0, y: 0, width: 466, height: height))
        keyboardView.layoutIfNeeded()
        document = FakeDocument(before: before)
        spellChecker = FakeSpellChecker()
        controller = KeyboardTextController(
            keyboardView: keyboardView, document: document, spellChecker: spellChecker,
            pinyinEngine: { PinyinEngine(dictionaryText: testDictionary) })
        if chinese {
            controller.keyboardView(keyboardView, edit: .toggleLanguage)
        }
    }

    private func type(_ text: String) {
        for character in text {
            controller.keyboardView(keyboardView, insert: String(character))
        }
    }

    private func tap(_ index: Int) {
        controller.keyboardView(keyboardView, didSelectCandidateAt: index)
    }

    /// The words of the candidate row from left to right, or nil while the row is hidden.
    private func row() -> [String]? {
        guard let bar = keyboardView.subviews.compactMap({ $0 as? CandidateBar }).first, !bar.isHidden else {
            return nil
        }
        var views: [UIView] = [bar]
        var buttons: [UIButton] = []
        while let view = views.popLast() {
            if let button = view as? UIButton { buttons.append(button) } else { views += view.subviews }
        }
        return buttons.sorted { $0.tag < $1.tag }.map { $0.configuration?.title ?? "" }
    }

    /// The emoji labels of the keyboard view outside the keys and the candidate row, from left to right.
    private func emojiLabels() -> [UILabel] {
        keyboardView.layoutIfNeeded()
        var views: [UIView] = keyboardView.subviews.filter {
            // The typing speed holds a number and its unit, and no emoji.
            !($0 is KeyView) && !($0 is CandidateBar) && !($0 is TypingSpeedView)
        }
        var labels: [UILabel] = []
        while let view = views.popLast() {
            if view.isHidden { continue }
            if let label = view as? UILabel, let text = label.text, !text.isEmpty { labels.append(label) }
            views += view.subviews
        }
        return labels.sorted { $0.convert($0.bounds, to: keyboardView).minX < $1.convert($1.bounds, to: keyboardView).minX }
    }

    /// The emoji that the top row of keys shows, from left to right.
    private func topRow() -> [String] {
        emojiLabels().compactMap(\.text)
    }

    /// A finger tap on the emoji at `index` in the top row of keys. The emoji is an entry of the
    /// prediction strip, and the finger comes down and lifts inside that entry.
    private func tapEmoji(_ index: Int, file: StaticString = #filePath, line: UInt = #line) {
        let labels = emojiLabels()
        guard labels.indices.contains(index), let entry = labels[index].superview as? PredictionStripEntry else {
            XCTFail("The top row shows \(labels.count) emoji", file: file, line: line)
            return
        }
        entry.sendActions(for: .touchDown)
        entry.sendActions(for: .touchUpInside)
    }

    private func pinyinWords(_ letters: String) -> [String] {
        PinyinEngine(dictionaryText: testDictionary).candidates(for: letters).map(\.word)
    }

    // MARK: English

    func testTheWordBeingTypedShowsItsEmojiInTheTopRow() {
        makeController()
        type("good")
        XCTAssertEqual(topRow().first, "\u{1F44D}")
        XCTAssertLessThanOrEqual(topRow().count, 2)
        // The English emoji take no row of their own.
        XCTAssertNil(row())
    }

    func testAWordRightAfterAnEmojiShowsItsEmoji() {
        // An emoji is no word, so the word after it counts without a space between the two.
        makeController(before: "\u{1F389}")
        type("good")
        XCTAssertEqual(topRow().first, "\u{1F44D}")
        type(" ")
        XCTAssertEqual(topRow().first, "\u{1F44D}")
    }

    func testAWordRightAfterAnEmojiGetsItsCorrection() {
        makeController(before: "ok \u{1F389}")
        type("teh ")
        XCTAssertEqual(document.text, "ok \u{1F389}the ")
        // The emoji is no word before the typed word.
        XCTAssertEqual(spellChecker.requests, ["|teh"])
    }

    func testTheRulesOfAWordTakeAnEmojiAsItsStart() {
        for emoji in ["\u{1F44D}", "\u{2764}\u{FE0F}", "1\u{FE0F}\u{20E3}", "\u{1F1E8}\u{1F1F3}", "\u{1F468}\u{200D}\u{1F469}\u{200D}\u{1F467}"] {
            XCTAssertTrue(KeyboardTextLogic.isEmoji(Character(emoji)), emoji)
            XCTAssertEqual(KeyboardTextLogic.correctableWord(before: emoji + "teh"), "teh", emoji)
            XCTAssertEqual(KeyboardTextLogic.typedLetters(before: emoji + "goo", after: ""), "goo", emoji)
            XCTAssertEqual(KeyboardTextLogic.wordForEmoji(before: emoji + "good "), "good", emoji)
            XCTAssertEqual(KeyboardTextLogic.wordWithInnerCapital(before: emoji + "pyTorch"), "pyTorch", emoji)
        }
        let context = KeyboardTextLogic.predictionContext(before: "\u{1F44D}goo", after: "")
        XCTAssertEqual(context?.previousWord, "")
        XCTAssertEqual(context?.typed, "goo")
        // A digit, a sign and a letter are no emoji, and a word right after them is still no word of its own.
        for character in ["1", "#", "*", "a", "\u{4E2D}", "\u{A9}", "@"] {
            XCTAssertFalse(KeyboardTextLogic.isEmoji(Character(character)), character)
        }
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "name@teh"))
        XCTAssertNil(KeyboardTextLogic.typedLetters(before: "\u{4E2D}goo", after: ""))
    }

    func testTheWordBeforeOneSpaceShowsItsEmoji() {
        makeController(before: "That is ")
        type("good ")
        XCTAssertEqual(topRow().first, "\u{1F44D}")
        XCTAssertNil(row())
    }

    func testACapitalDoesNotHideTheEmoji() {
        makeController()
        type("Good ")
        XCTAssertEqual(topRow().first, "\u{1F44D}")
    }

    func testATapReplacesTheWordAndKeepsTheSpaceAfterIt() {
        makeController(before: "I feel ")
        type("good ")
        tapEmoji(0)
        XCTAssertEqual(document.text, "I feel \u{1F44D} ")
        XCTAssertEqual(topRow(), [])
    }

    func testATapWhileTypingReplacesTheWord() {
        makeController()
        type("good")
        tapEmoji(0)
        XCTAssertEqual(document.text, "\u{1F44D}")
    }

    func testTheSecondEmojiOfAWordGoesInOnItsTap() throws {
        makeController()
        type("good ")
        XCTAssertEqual(topRow().count, 2)
        let second = try XCTUnwrap(topRow().dropFirst().first)
        tapEmoji(1)
        XCTAssertEqual(document.text, second + " ")
    }

    func testOneDeleteAfterTheReplacementBringsTheWordBack() {
        // As after a correction, the delete takes the space after the emoji too.
        makeController()
        type("Good ")
        tapEmoji(0)
        XCTAssertEqual(document.text, "\u{1F44D} ")
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "Good")
        // The word does not join the words the person brought back after a correction.
        XCTAssertEqual(spellChecker.learned, [])
        // A second delete is a plain delete.
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "Goo")
    }

    func testADeleteBringsTheWordBackAfterATapWhileTyping() {
        makeController()
        type("good")
        tapEmoji(0)
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "good")
    }

    func testAKeyAfterTheReplacementEndsTheWayBack() {
        makeController()
        type("good ")
        tapEmoji(0)
        type("x")
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "\u{1F44D} ")
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "\u{1F44D}")
    }

    func testOtherTextShowsNoEmoji() {
        // A word outside the table, two spaces, a mark, a word inside another word, and a word
        // right after a sign.
        for text in ["xyz ", "good  ", "good.", "good,", "goodness ", "@good ", "the "] {
            makeController()
            type(text)
            XCTAssertEqual(topRow(), [], text)
            XCTAssertNil(row(), text)
        }
    }

    func testAFieldWithoutAutocorrectionShowsNoEmoji() {
        makeController()
        document.allowsAutocorrection = false
        type("good ")
        XCTAssertEqual(topRow(), [])
        type("good")
        XCTAssertEqual(topRow(), [])
    }

    func testAutocorrectionStaysAsBefore() {
        makeController()
        type("good teh ")
        XCTAssertEqual(document.text, "good the ")
        XCTAssertEqual(topRow(), [])
        type("recieve ")
        XCTAssertEqual(document.text, "good the receive ")
    }

    func testATapWhileTypingRunsNoCorrection() {
        makeController()
        spellChecker.corrections["good"] = "food"
        type("good")
        tapEmoji(0)
        XCTAssertEqual(document.text, "\u{1F44D}")
        XCTAssertEqual(spellChecker.requests, [])
    }

    func testAMarkAfterTheEmojiKeepsItsSpace() {
        // An emoji is not a word, so a mark after the emoji and one space keeps that space.
        makeController()
        type("good ")
        tapEmoji(0)
        type(",")
        XCTAssertEqual(document.text, "\u{1F44D} ,")
        makeController()
        type("good")
        tapEmoji(0)
        type(".")
        XCTAssertEqual(document.text, "\u{1F44D}.")
    }

    func testSpaceRemovalAndItsUndoStillWorkAfterAWordWithEmoji() {
        makeController()
        type("good ,")
        XCTAssertEqual(document.text, "good,")
        XCTAssertEqual(topRow(), [])
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "good ")
        XCTAssertEqual(topRow().first, "\u{1F44D}")
        type(",")
        XCTAssertEqual(document.text, "good ,")
    }

    func testSpaceRestoreStillWorksAfterAWordWithEmoji() {
        makeController()
        type("good .e")
        XCTAssertEqual(document.text, "good .e")
    }

    func testAProofreadFixComesBeforeTheEmoji() async {
        // The fix has a row of its own, which covers the prediction strip, so that row also
        // offers the emoji after the fix.
        makeController()
        let proofreader = FakeProofreader()
        proofreader.answers = ["I came form the office": "I came from the office"]
        controller.proofreader = proofreader
        controller.proofreadPauseSeconds = 0.05
        type("I came form the office ")
        await controller.pauseTask?.value
        await controller.proofreadTask?.value
        XCTAssertEqual(row()?.first, "I came from the office")
        XCTAssertEqual(row()?.dropFirst().first, "\u{1F4BB}")
        tap(1)
        XCTAssertEqual(document.text, "I came form the \u{1F4BB} ")
    }

    func testTheProofreadFixStillGoesInOnATapOfTheFirstWord() async {
        makeController()
        let proofreader = FakeProofreader()
        proofreader.answers = ["I came form the office": "I came from the office"]
        controller.proofreader = proofreader
        controller.proofreadPauseSeconds = 0.05
        type("I came form the office ")
        await controller.pauseTask?.value
        await controller.proofreadTask?.value
        tap(0)
        XCTAssertEqual(document.text, "I came from the office ")
    }

    func testChineseModeShowsNoEnglishEmoji() {
        makeController()
        type("good ")
        XCTAssertEqual(topRow().first, "\u{1F44D}")
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        XCTAssertEqual(topRow(), [])
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        XCTAssertEqual(topRow().first, "\u{1F44D}")
    }

    func testACursorMoveShowsTheEmojiOfTheWordBeforeTheCursor() {
        makeController()
        type("good xyz")
        XCTAssertEqual(topRow(), [])
        controller.keyboardView(keyboardView, moveCursorBy: -4)
        XCTAssertEqual(topRow().first, "\u{1F44D}")
    }

    // MARK: Chinese

    func testTheFirstCandidateInTheTableGetsItsEmojiRightAfterIt() {
        makeController(chinese: true)
        type("hao")
        // Chinese emoji stay on the candidate row, and the top row of keys shows none.
        XCTAssertEqual(topRow(), [])
        let shown = row() ?? []
        XCTAssertEqual(shown.first, "\u{597D}")
        XCTAssertEqual(shown.dropFirst().first, "\u{1F44D}")
        // The Pinyin candidates keep their order.
        XCTAssertEqual(shown.filter { $0 != "\u{1F44D}" }, pinyinWords("hao"))
    }

    func testATapOnTheEmojiTypesItInPlaceOfTheWord() {
        makeController(chinese: true)
        type("hao")
        tap(1)
        XCTAssertEqual(document.text, "\u{1F44D}")
        XCTAssertEqual(controller.pinyinBuffer, "")
        XCTAssertNil(row())
    }

    func testAnEmojiTakesTheLettersOfItsWord() {
        makeController(chinese: true)
        type("nihao")
        XCTAssertEqual(row()?.first, "\u{4F60}\u{597D}")
        XCTAssertEqual(row()?.dropFirst().first, "\u{1F44B}")
        tap(1)
        XCTAssertEqual(document.text, "\u{1F44B}")
        XCTAssertEqual(controller.pinyinBuffer, "")
    }

    func testSpaceAndDigitsStillPickTheCandidates() {
        makeController(chinese: true)
        type("hao ")
        XCTAssertEqual(document.text, "\u{597D}")
        // Candidates of "nihao": the phrase, then the two characters for "ni". A digit counts
        // the Pinyin candidates only.
        type("nihao2")
        XCTAssertEqual(document.text, "\u{597D}\u{4F60}hao")
        XCTAssertEqual(document.markedText, "hao")
        XCTAssertEqual(controller.pinyinBuffer, "hao")
        XCTAssertEqual(row()?.prefix(2).map { $0 }, ["\u{597D}", "\u{1F44D}"])
    }

    func testAFirstCandidateOutsideTheTableGetsNoEmoji() {
        makeController(chinese: true)
        type("wo")
        XCTAssertEqual(row(), pinyinWords("wo"))
    }

    func testTheTapOnAPinyinCandidateAfterTheEmojiTypesThatCandidate() throws {
        makeController(chinese: true)
        type("nihao")
        let second = pinyinWords("nihao")[1]
        tap(try XCTUnwrap(row()?.firstIndex(of: second)))
        // The candidate covers "ni", and the other letters stay in the field as marked text.
        XCTAssertEqual(document.text, second + "hao")
        XCTAssertEqual(document.markedText, "hao")
    }

    func testAChineseFieldWithoutAutocorrectionShowsNoEmoji() {
        makeController(chinese: true)
        document.allowsAutocorrection = false
        type("hao")
        XCTAssertEqual(row(), pinyinWords("hao"))
    }

    func testAnEmojiAfterAnOpeningQuoteKeepsTheSpace() {
        // An emoji is not a letter, so it does not take the place of the space after a quote.
        makeController(before: "\u{201C} ", chinese: true)
        type("hao")
        tap(1)
        XCTAssertEqual(document.text, "\u{201C} \u{1F44D}")
    }
}
