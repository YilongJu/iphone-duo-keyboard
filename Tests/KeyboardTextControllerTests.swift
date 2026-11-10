import UIKit
import XCTest

@testable import DuoKeyboard

/// A text field in memory. The cursor is a UTF-16 offset, as in UIKit.
@MainActor
final class FakeDocument: KeyboardDocument {
    var text: String
    var cursor: Int
    var selectedText: String?
    var autocapitalizationType: UITextAutocapitalizationType = .none
    var canUseClipboard = true
    var documentIdentifier = UUID()
    var allowsAutocorrection = true

    init(before: String, after: String = "") {
        text = before + after
        cursor = before.utf16.count
    }

    var textBeforeCursor: String { (text as NSString).substring(to: cursor) }
    var textAfterCursor: String { (text as NSString).substring(from: cursor) }

    func insertText(_ inserted: String) {
        text = textBeforeCursor + inserted + textAfterCursor
        cursor += inserted.utf16.count
    }

    func deleteBackward() {
        let before = textBeforeCursor
        guard let last = before.last else { return }
        text = String(before.dropLast()) + textAfterCursor
        cursor -= String(last).utf16.count
    }

    func moveCursor(byUTF16Offset offset: Int) {
        cursor = min(max(cursor + offset, 0), text.utf16.count)
    }
}

/// A spell checker with a fixed list of corrections.
@MainActor
final class FakeSpellChecker: SpellChecking {
    var corrections: [String: String] = ["teh": "the", "Teh": "The", "recieve": "receive"]
    var learned: [String] = []

    func correction(for word: String) -> String? {
        corrections[word]
    }

    func learn(_ word: String) {
        learned.append(word)
    }
}

@MainActor
final class KeyboardTextControllerTests: XCTestCase {
    private var keyboardView: KeyboardView!
    private var document: FakeDocument!
    private var spellChecker: FakeSpellChecker!
    private var controller: KeyboardTextController!

    private func type(_ text: String) {
        for character in text {
            controller.keyboardView(keyboardView, insert: String(character))
        }
    }

    func testASpaceCorrectsTheWordBeforeIt() {
        makeController(before: "")
        type("teh ")
        XCTAssertEqual(document.text, "the ")
    }

    func testACorrectionKeepsTheCapital() {
        makeController(before: "")
        type("Teh.")
        XCTAssertEqual(document.text, "The.")
    }

    func testBackspaceRightAfterACorrectionBringsTheTypedWordBack() {
        makeController(before: "")
        type("teh ")
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "teh")
        XCTAssertEqual(spellChecker.learned, ["teh"])
        type(" ")
        XCTAssertEqual(document.text, "teh ")
    }

    func testALoneLowerCaseIBecomesACapital() {
        makeController(before: "then ")
        type("i ")
        XCTAssertEqual(document.text, "then I ")
    }

    func testAFieldWithoutAutocorrectionKeepsTheTypedWord() {
        makeController(before: "")
        document.allowsAutocorrection = false
        type("teh ")
        XCTAssertEqual(document.text, "teh ")
    }

    func testAWordInsideAnAddressStaysAsTyped() {
        makeController(before: "name@")
        type("teh ")
        XCTAssertEqual(document.text, "name@teh ")
    }

    func testPastedTextStaysAsPasted() {
        makeController(before: "")
        UIPasteboard.general.string = "teh "
        controller.keyboardView(keyboardView, edit: .paste)
        XCTAssertEqual(document.text, "teh ")
    }

    private func makeController(before: String, after: String = "") {
        keyboardView = KeyboardView()
        document = FakeDocument(before: before, after: after)
        spellChecker = FakeSpellChecker()
        controller = KeyboardTextController(
            keyboardView: keyboardView, document: document, spellChecker: spellChecker)
    }

    /// The controller deletes the text after the cursor in a delayed step, so the test waits.
    private func waitForDelayedEdits() {
        RunLoop.current.run(until: Date().addingTimeInterval(0.6))
    }

    func testTypingInsertsAtTheCursor() {
        makeController(before: "ab", after: "cd")
        controller.keyboardView(keyboardView, insert: "X")
        XCTAssertEqual(document.text, "abXcd")
    }

    func testSecondSpaceBecomesAPeriod() {
        makeController(before: "word")
        controller.keyboardView(keyboardView, insert: " ")
        controller.keyboardView(keyboardView, insert: " ")
        XCTAssertEqual(document.text, "word. ")
    }

    func testForwardDeleteRemovesTheNextCharacter() {
        makeController(before: "ab", after: "cd")
        controller.keyboardView(keyboardView, edit: .deleteForward)
        XCTAssertEqual(document.text, "abd")
        XCTAssertEqual(document.textBeforeCursor, "ab")
    }

    func testForwardDeleteRemovesAWholeEmoji() {
        makeController(before: "a", after: "😀b")
        controller.keyboardView(keyboardView, edit: .deleteForward)
        XCTAssertEqual(document.text, "ab")
    }

    func testArrowMovesAcrossAWholeEmoji() {
        makeController(before: "a", after: "😀b")
        controller.keyboardView(keyboardView, moveCursorBy: 1)
        XCTAssertEqual(document.textBeforeCursor, "a😀")
        controller.keyboardView(keyboardView, moveCursorBy: -1)
        XCTAssertEqual(document.textBeforeCursor, "a")
    }

    func testSelectAllThenTypingReplacesAllText() {
        makeController(before: "hello ", after: "world")
        controller.keyboardView(keyboardView, edit: .selectAll)
        XCTAssertTrue(keyboardView.selectAllActive)
        controller.keyboardView(keyboardView, insert: "X")
        waitForDelayedEdits()
        XCTAssertEqual(document.text, "X")
        XCTAssertFalse(keyboardView.selectAllActive)
    }

    func testSelectAllThenFastTypingKeepsEveryTypedCharacter() {
        makeController(before: "hello ", after: "world")
        controller.keyboardView(keyboardView, edit: .selectAll)
        controller.keyboardView(keyboardView, insert: "a")
        controller.keyboardView(keyboardView, insert: "b")
        controller.keyboardView(keyboardView, insert: "c")
        waitForDelayedEdits()
        XCTAssertEqual(document.text, "abc")
    }

    func testSelectAllThenBackspaceDeletesAllText() {
        makeController(before: "one\ntwo ", after: "three")
        controller.keyboardView(keyboardView, edit: .selectAll)
        controller.keyboardViewDeleteBackward(keyboardView)
        waitForDelayedEdits()
        XCTAssertEqual(document.text, "")
    }

    func testSelectAllThenCopyPutsAllTextOnTheClipboard() {
        makeController(before: "hello ", after: "world")
        controller.keyboardView(keyboardView, edit: .selectAll)
        controller.keyboardView(keyboardView, edit: .copy)
        XCTAssertEqual(UIPasteboard.general.string, "hello world")
        XCTAssertEqual(document.text, "hello world")
        XCTAssertTrue(keyboardView.selectAllActive)
    }

    func testSelectAllThenCutMovesAllTextToTheClipboard() {
        makeController(before: "hello ", after: "world")
        controller.keyboardView(keyboardView, edit: .selectAll)
        controller.keyboardView(keyboardView, edit: .cut)
        waitForDelayedEdits()
        XCTAssertEqual(UIPasteboard.general.string, "hello world")
        XCTAssertEqual(document.text, "")
    }

    func testSecondPressOfSelectAllTurnsItOff() {
        makeController(before: "hello")
        controller.keyboardView(keyboardView, edit: .selectAll)
        controller.keyboardView(keyboardView, edit: .selectAll)
        XCTAssertFalse(keyboardView.selectAllActive)
        controller.keyboardView(keyboardView, insert: "!")
        XCTAssertEqual(document.text, "hello!")
    }

    func testACursorMoveInTheAppTurnsSelectAllOff() {
        makeController(before: "hello ", after: "world")
        controller.keyboardView(keyboardView, edit: .selectAll)
        document.cursor = 2
        controller.documentDidChange()
        XCTAssertFalse(keyboardView.selectAllActive)
        controller.keyboardView(keyboardView, insert: "X")
        XCTAssertEqual(document.text, "heXllo world")
    }

    func testAChangedDocumentIsNeverReplaced() {
        makeController(before: "hello ", after: "world")
        controller.keyboardView(keyboardView, edit: .selectAll)
        // The app changes the text and does not tell the keyboard.
        document.text = "other text"
        document.cursor = 5
        controller.keyboardView(keyboardView, insert: "X")
        waitForDelayedEdits()
        XCTAssertEqual(document.text, "otherX text")
    }

    func testAMoveToAnotherFieldStopsTheReplacement() {
        makeController(before: "hello ", after: "world")
        controller.keyboardView(keyboardView, edit: .selectAll)
        controller.keyboardView(keyboardView, insert: "X")
        // The user moves to another field whose text also ends with "world".
        document.documentIdentifier = UUID()
        document.text = "KEEPworld"
        document.cursor = 9
        waitForDelayedEdits()
        XCTAssertEqual(document.text, "KEEPworld")
    }

    func testAnUnconfirmedCursorMoveDeletesNoText() {
        makeController(before: "hello ", after: "world")
        controller.keyboardView(keyboardView, edit: .selectAll)
        controller.keyboardViewDeleteBackward(keyboardView)
        // The cursor lands in a place the controller did not ask for.
        document.cursor = 3
        waitForDelayedEdits()
        XCTAssertEqual(document.text, "hello world")
    }

    func testSelectAllWithASelectionInTheAppStaysOff() {
        makeController(before: "hello ", after: "world")
        document.selectedText = "lo"
        controller.keyboardView(keyboardView, edit: .selectAll)
        XCTAssertFalse(keyboardView.selectAllActive)
    }

    func testSelectAllOnAnEmptyFieldStaysOff() {
        makeController(before: "")
        controller.keyboardView(keyboardView, edit: .selectAll)
        XCTAssertFalse(keyboardView.selectAllActive)
    }

    func testCopyWithoutFullAccessLeavesTheClipboardAlone() {
        makeController(before: "secret")
        UIPasteboard.general.string = "untouched"
        document.canUseClipboard = false
        controller.keyboardView(keyboardView, edit: .selectAll)
        controller.keyboardView(keyboardView, edit: .copy)
        XCTAssertEqual(UIPasteboard.general.string, "untouched")
    }
}

final class KeyboardTextLogicTests: XCTestCase {
    private func offset(_ command: EditCommand, _ before: String, _ after: String) -> Int {
        KeyboardTextLogic.cursorOffset(for: command, before: before, after: after)
    }

    func testHomeAndEndStayInsideTheLine() {
        XCTAssertEqual(offset(.lineStart, "ab\ncd", "ef\ngh"), -2)
        XCTAssertEqual(offset(.lineEnd, "ab\ncd", "ef\ngh"), 2)
        XCTAssertEqual(offset(.lineStart, "", "abc"), 0)
        XCTAssertEqual(offset(.lineEnd, "abc", ""), 0)
    }

    func testUpKeepsTheColumn() {
        // "abcd" above "ef|gh": the cursor sits at column 2 and goes to column 2 of the line above.
        XCTAssertEqual(offset(.lineUp, "abcd\nef", "gh"), -5)
    }

    func testUpStopsAtTheEndOfAShorterLine() {
        // "a" above "bcd|": the line above has one character, so the cursor lands after it.
        XCTAssertEqual(offset(.lineUp, "a\nbcd", ""), -4)
    }

    func testUpOnTheFirstLineGoesToTheLineStart() {
        XCTAssertEqual(offset(.lineUp, "abc", "def"), -3)
    }

    func testDownKeepsTheColumn() {
        // "ab|cd" above "efgh": the cursor sits at column 2 and goes to column 2 of the line below.
        XCTAssertEqual(offset(.lineDown, "ab", "cd\nefgh"), 5)
    }

    func testDownStopsAtTheEndOfAShorterLine() {
        XCTAssertEqual(offset(.lineDown, "abc", "d\ne"), 3)
    }

    func testDownOnTheLastLineGoesToTheLineEnd() {
        XCTAssertEqual(offset(.lineDown, "abc", "def"), 3)
    }

    func testCorrectableWordSkipsTextThatIsNotProse() {
        XCTAssertEqual(KeyboardTextLogic.correctableWord(before: "say teh"), "teh")
        XCTAssertEqual(KeyboardTextLogic.correctableWord(before: "dont"), "dont")
        XCTAssertEqual(KeyboardTextLogic.correctableWord(before: "(teh"), "teh")
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "iPhone"))
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "NASA"))
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "www.teh"))
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "file_teh"))
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "abc123"))
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "word "))
    }

    func testBestGuessTakesTheFirstCloseGuess() {
        XCTAssertEqual(KeyboardTextLogic.bestGuess(for: "teh", guesses: ["tea", "the"]), "tea")
        XCTAssertEqual(KeyboardTextLogic.bestGuess(for: "teh", guesses: ["tether", "the"]), "the")
        XCTAssertEqual(KeyboardTextLogic.bestGuess(for: "Recieve", guesses: ["receive"]), "Receive")
        XCTAssertNil(KeyboardTextLogic.bestGuess(for: "xyzzy", guesses: ["pizza", "a lot"]))
    }

    func testEditDistanceCountsASwapAsOneEdit() {
        XCTAssertEqual(KeyboardTextLogic.editDistance("teh", "the"), 1)
        XCTAssertEqual(KeyboardTextLogic.editDistance("cat", "cart"), 1)
        XCTAssertEqual(KeyboardTextLogic.editDistance("kitten", "sitting"), 3)
        XCTAssertEqual(KeyboardTextLogic.editDistance("same", "same"), 0)
    }

    func testAutomaticCapitalizationFollowsSentenceEnds() {
        XCTAssertTrue(KeyboardTextLogic.shouldAutoCapitalize(before: "", type: .sentences))
        XCTAssertTrue(KeyboardTextLogic.shouldAutoCapitalize(before: "Done. ", type: .sentences))
        XCTAssertTrue(KeyboardTextLogic.shouldAutoCapitalize(before: "line\n", type: .sentences))
        XCTAssertFalse(KeyboardTextLogic.shouldAutoCapitalize(before: "Done.", type: .sentences))
        XCTAssertFalse(KeyboardTextLogic.shouldAutoCapitalize(before: "word ", type: .sentences))
        XCTAssertFalse(KeyboardTextLogic.shouldAutoCapitalize(before: "", type: .none))
    }
}

@MainActor
final class KeyboardLayoutTests: XCTestCase {
    func testEveryLayerLoadsFromTheLayoutFile() {
        for style in [LayoutStyle.wide, .compact] {
            for layer in [KeyboardLayer.letters, .symbols, .more] {
                let layout = KeyboardLayout.make(style: style, layer: layer, showsGlobe: true)
                XCTAssertEqual(layout.rows.count, 6)
                XCTAssertEqual(layout.rows.count, layout.rowHeights.count)
                for row in layout.rows {
                    let width = row.reduce(0) { $0 + $1.weight }
                    XCTAssertLessThanOrEqual(width, layout.units + 0.0001)
                }
            }
        }
    }

    func testASymbolLayerHasOneKeyBackToTheLetters() {
        for style in [LayoutStyle.wide, .compact] {
            for layer in [KeyboardLayer.symbols, .more] {
                let layout = KeyboardLayout.make(style: style, layer: layer, showsGlobe: true)
                let count = layout.rows.joined().filter { $0.kind == .switchLayer(.letters) }.count
                XCTAssertEqual(count, 1)
            }
        }
    }

    func testHidingTheGlobeGivesItsWidthToTheSpaceBar() {
        let with = KeyboardLayout.make(style: .wide, layer: .letters, showsGlobe: true)
        let without = KeyboardLayout.make(style: .wide, layer: .letters, showsGlobe: false)
        let widthWith = with.rows[5].reduce(0) { $0 + $1.weight }
        let widthWithout = without.rows[5].reduce(0) { $0 + $1.weight }
        XCTAssertEqual(widthWith, widthWithout, accuracy: 0.0001)
        XCTAssertFalse(without.rows[5].contains { $0.kind == .globe })
    }

    func testShiftChangesTheCaseOnTheLettersLayerOnly() {
        let keyboardView = KeyboardView()
        keyboardView.shiftState = .on
        XCTAssertEqual(keyboardView.characterText("a"), "A")
        XCTAssertEqual(keyboardView.characterText("1"), "1")
        keyboardView.show(layer: .more)
        XCTAssertEqual(keyboardView.characterText("π"), "π")
        XCTAssertEqual(keyboardView.characterText("µ"), "µ")
    }

    func testTheWideLayoutStartsAtItsMinimumWidth() {
        XCTAssertEqual(KeyboardView.style(forWidth: 669), .wide)
        XCTAssertEqual(KeyboardView.style(forWidth: 466), .compact)
    }
}
