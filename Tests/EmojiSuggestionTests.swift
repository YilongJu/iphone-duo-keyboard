import UIKit
import XCTest

@testable import DuoKeyboard

/// The emoji of a word on the candidate row: after the English word right before the cursor,
/// and right after the first Pinyin candidate. The tests read the bundled table
/// Shared/emoji-suggestions.tsv, which offers "👍" for "good" and for "好", "👋" for "你好" and
/// "💻" for "office", and nothing for "the", "我" and "xyz".
@MainActor
final class EmojiSuggestionTests: XCTestCase {
    private var keyboardView: KeyboardView!
    private var document: FakeDocument!
    private var spellChecker: FakeSpellChecker!
    private var controller: KeyboardTextController!

    private func makeController(before: String = "", chinese: Bool = false) {
        keyboardView = KeyboardView()
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

    private func pinyinWords(_ letters: String) -> [String] {
        PinyinEngine(dictionaryText: testDictionary).candidates(for: letters).map(\.word)
    }

    // MARK: English

    func testTheWordBeingTypedShowsItsEmoji() {
        makeController()
        type("good")
        XCTAssertEqual(row()?.first, "\u{1F44D}")
        XCTAssertLessThanOrEqual(row()?.count ?? 0, 2)
    }

    func testTheWordBeforeOneSpaceShowsItsEmoji() {
        makeController(before: "That is ")
        type("good ")
        XCTAssertEqual(row()?.first, "\u{1F44D}")
    }

    func testACapitalDoesNotHideTheEmoji() {
        makeController()
        type("Good ")
        XCTAssertEqual(row()?.first, "\u{1F44D}")
    }

    func testATapAfterTheSpacePutsTheEmojiAfterTheSpace() {
        makeController()
        type("good ")
        tap(0)
        XCTAssertEqual(document.text, "good \u{1F44D}")
        XCTAssertNil(row())
    }

    func testATapWhileTypingPutsOneSpaceBetweenTheWordAndTheEmoji() {
        makeController()
        type("good")
        tap(0)
        XCTAssertEqual(document.text, "good \u{1F44D}")
    }

    func testTheSecondEmojiOfAWordGoesInOnItsTap() {
        makeController()
        type("good ")
        let shown = row() ?? []
        XCTAssertEqual(shown.count, 2)
        tap(1)
        XCTAssertEqual(document.text, "good " + shown[1])
    }

    func testOtherTextShowsNoEmoji() {
        // A word outside the table, two spaces, a mark, a word inside another word, and a word
        // right after a sign.
        for text in ["xyz ", "good  ", "good.", "good,", "goodness ", "@good ", "the "] {
            makeController()
            type(text)
            XCTAssertNil(row(), text)
        }
    }

    func testAFieldWithoutAutocorrectionShowsNoEmoji() {
        makeController()
        document.allowsAutocorrection = false
        type("good ")
        XCTAssertNil(row())
        type("good")
        XCTAssertNil(row())
    }

    func testAutocorrectionStaysAsBefore() {
        makeController()
        type("good teh ")
        XCTAssertEqual(document.text, "good the ")
        XCTAssertNil(row())
        type("recieve ")
        XCTAssertEqual(document.text, "good the receive ")
    }

    func testAnEmojiTapLeavesTheWordAsTyped() {
        makeController()
        spellChecker.corrections["good"] = "food"
        type("good")
        tap(0)
        XCTAssertEqual(document.text, "good \u{1F44D}")
        // A delete after the emoji is a plain delete, and no correction comes back.
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "good ")
        XCTAssertEqual(row()?.first, "\u{1F44D}")
    }

    func testAMarkAfterTheEmojiKeepsItsSpace() {
        // An emoji is not a word, so a mark after the emoji and one space keeps that space.
        makeController()
        type("good ")
        tap(0)
        type(" ,")
        XCTAssertEqual(document.text, "good \u{1F44D} ,")
        makeController()
        type("good ")
        tap(0)
        type(".")
        XCTAssertEqual(document.text, "good \u{1F44D}.")
    }

    func testSpaceRemovalAndItsUndoStillWorkAfterAWordWithEmoji() {
        makeController()
        type("good ,")
        XCTAssertEqual(document.text, "good,")
        XCTAssertNil(row())
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "good ")
        XCTAssertEqual(row()?.first, "\u{1F44D}")
        type(",")
        XCTAssertEqual(document.text, "good ,")
    }

    func testSpaceRestoreStillWorksAfterAWordWithEmoji() {
        makeController()
        type("good .e")
        XCTAssertEqual(document.text, "good .e")
    }

    func testAProofreadFixComesBeforeTheEmoji() async {
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
        XCTAssertEqual(document.text, "I came form the office \u{1F4BB}")
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
        XCTAssertNotNil(row())
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        XCTAssertNil(row())
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        XCTAssertEqual(row()?.first, "\u{1F44D}")
    }

    func testACursorMoveShowsTheEmojiOfTheWordBeforeTheCursor() {
        makeController()
        type("good xyz")
        XCTAssertNil(row())
        controller.keyboardView(keyboardView, moveCursorBy: -4)
        XCTAssertEqual(row()?.first, "\u{1F44D}")
    }

    // MARK: Chinese

    func testTheFirstCandidateInTheTableGetsItsEmojiRightAfterIt() {
        makeController(chinese: true)
        type("hao")
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
        XCTAssertEqual(document.text, "\u{597D}\u{4F60}")
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
        XCTAssertEqual(document.text, second)
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
