import UIKit
import XCTest

@testable import DuoKeyboard

/// The field shows the typed Pinyin letters as marked text. A picked candidate takes their
/// place, and the return key leaves them as plain text.
@MainActor
final class PinyinLettersInTheFieldTests: XCTestCase {
    private var keyboardView: KeyboardView!
    private var document: FakeDocument!
    private var controller: KeyboardTextController!

    private func makeController(before: String = "", after: String = "") {
        keyboardView = KeyboardView()
        document = FakeDocument(before: before, after: after)
        controller = KeyboardTextController(
            keyboardView: keyboardView, document: document, spellChecker: FakeSpellChecker(),
            pinyinEngine: { PinyinEngine(dictionaryText: testDictionary) })
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
    }

    private func type(_ text: String) {
        for character in text {
            controller.keyboardView(keyboardView, insert: String(character))
        }
    }

    func testTheFieldShowsEachTypedLetterAsMarkedText() {
        makeController()
        type("n")
        XCTAssertEqual(document.text, "n")
        XCTAssertEqual(document.markedText, "n")
        type("ih")
        XCTAssertEqual(document.text, "nih")
        XCTAssertEqual(document.markedText, "nih")
        // An apostrophe between two syllables shows as the person typed it.
        makeController()
        type("xi'an")
        XCTAssertEqual(document.markedText, "xi'an")
    }

    func testTheLettersShowAtTheCursorInsideAText() {
        makeController(before: "ab", after: "cd")
        type("ni")
        XCTAssertEqual(document.text, "abnicd")
        XCTAssertEqual(document.markedText, "ni")
        type(" ")
        XCTAssertEqual(document.text, "ab\u{4F60}cd")
        XCTAssertEqual(document.markedText, "")
    }

    func testADeleteTakesTheLastLetterOutOfTheField() {
        makeController(before: "a")
        type("ni")
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "an")
        XCTAssertEqual(document.markedText, "n")
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "a")
        XCTAssertEqual(document.markedText, "")
        XCTAssertEqual(controller.pinyinBuffer, "")
        // The next delete takes a character of the text.
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "")
    }

    func testAPickedCandidateTakesThePlaceOfTheLetters() {
        makeController()
        type("nihao ")
        XCTAssertEqual(document.text, "\u{4F60}\u{597D}")
        XCTAssertEqual(document.markedText, "")
        // One call per letter marks the text, and the word goes in with one insert.
        XCTAssertEqual(document.markedTextCalls, ["n", "ni", "nih", "niha", "nihao"])
    }

    func testAShorterCandidateLeavesTheOtherLettersMarked() {
        makeController()
        type("wonihao")
        let candidates = PinyinEngine(dictionaryText: testDictionary).candidates(for: "wonihao")
        let shorter = candidates.firstIndex { $0.word == "\u{6211}" }!
        controller.keyboardView(keyboardView, didSelectCandidateAt: shorter)
        XCTAssertEqual(document.text, "\u{6211}nihao")
        XCTAssertEqual(document.markedText, "nihao")
        type(" ")
        XCTAssertEqual(document.text, "\u{6211}\u{4F60}\u{597D}")
        XCTAssertEqual(document.markedText, "")
    }

    func testReturnLeavesTheLettersAsPlainText() {
        makeController(before: "a ")
        type("nihao\n")
        XCTAssertEqual(document.text, "a nihao")
        XCTAssertEqual(document.markedText, "")
        XCTAssertEqual(controller.pinyinBuffer, "")
        // The next letters start a new word after the plain letters.
        type("wo ")
        XCTAssertEqual(document.text, "a nihao\u{6211}")
    }

    func testAMarkTypesTheWordAndThenTheMark() {
        makeController()
        type("nihao,")
        XCTAssertEqual(document.text, "\u{4F60}\u{597D}\u{FF0C}")
        XCTAssertEqual(document.markedText, "")
    }

    func testATapAtAnotherPlaceEndsTheWord() {
        makeController(before: "ab")
        type("ni")
        // The field reports the change that the keyboard made.
        controller.documentDidChange()
        XCTAssertEqual(controller.pinyinBuffer, "ni")
        // The person taps at the start of the field. The field keeps the letters as plain text.
        document.tap(atUTF16Offset: 0)
        controller.documentDidChange()
        XCTAssertEqual(controller.pinyinBuffer, "")
        XCTAssertEqual(document.text, "abni")
        // The next word goes in at the new place, and the old letters stay where they are.
        type("wo ")
        XCTAssertEqual(document.text, "\u{6211}abni")
    }

    func testAFieldThatDoesNotReportItsMarkedTextKeepsTheLetters() {
        makeController(before: "ab")
        document.hidesMarkedText = true
        type("ni")
        controller.documentDidChange()
        type("h")
        controller.documentDidChange()
        XCTAssertEqual(controller.pinyinBuffer, "nih")
        type("ao ")
        XCTAssertEqual(document.text, "ab\u{4F60}\u{597D}")
    }

    func testTheCursorKeyEndsTheWordFirst() {
        makeController(before: "ab")
        type("ni")
        controller.keyboardView(keyboardView, moveCursorBy: -1)
        XCTAssertEqual(controller.pinyinBuffer, "")
        XCTAssertEqual(document.markedText, "")
        XCTAssertEqual(document.text, "abni")
        XCTAssertEqual(document.textBeforeCursor, "abn")
    }

    func testEnglishTypingMarksNoText() {
        makeController()
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        type("hello ")
        XCTAssertEqual(document.markedTextCalls, [])
        XCTAssertEqual(document.text, "hello ")
    }
}
