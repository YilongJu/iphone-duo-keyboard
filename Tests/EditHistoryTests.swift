import UIKit
import XCTest

@testable import DuoKeyboard

/// The rules of the edit history: which steps join into one, and what a new step does to the
/// steps of the Redo key.
final class EditHistoryTests: XCTestCase {
    private func typing(_ text: String) -> EditStep {
        EditStep(removed: "", added: text, run: EditStep.typing(text))
    }

    private func deleting(_ text: String) -> EditStep {
        EditStep(removed: text, added: "", run: .deleting)
    }

    func testTheLettersOfOneWordAndTheSpaceAfterItAreOneStep() {
        var history = EditHistory()
        for character in "hello " {
            history.record(typing(String(character)))
        }
        XCTAssertEqual(history.undoSteps.map(\.added), ["hello "])
    }

    func testALetterAfterASpaceOrAMarkStartsANewStep() {
        var history = EditHistory()
        for character in "hi, you. ok" {
            history.record(typing(String(character)))
        }
        XCTAssertEqual(history.undoSteps.map(\.added), ["hi, ", "you. ", "ok"])
    }

    func testTheDeletesInARowAreOneStepWithTheDeletedTextInItsOrder() {
        var history = EditHistory()
        history.record(typing("a"))
        for character in "dlrow" {
            history.record(deleting(String(character)))
        }
        XCTAssertEqual(history.undoSteps.count, 2)
        XCTAssertEqual(history.undoSteps[1].removed, "world")
        XCTAssertEqual(history.undoSteps[1].added, "")
    }

    func testADeleteAfterTypingAndTypingAfterADeleteAreStepsOfTheirOwn() {
        var history = EditHistory()
        history.record(typing("a"))
        history.record(deleting("a"))
        history.record(typing("b"))
        XCTAssertEqual(history.undoSteps.count, 3)
    }

    func testASingleStepJoinsNoOtherStep() {
        var history = EditHistory()
        history.record(typing("teh "))
        history.record(EditStep(removed: "eh ", added: "he "))
        history.record(typing("x"))
        XCTAssertEqual(history.undoSteps.count, 3)
    }

    func testANewStepEmptiesTheStepsOfTheRedoKey() {
        var history = EditHistory()
        history.record(typing("one "))
        history.record(typing("two"))
        XCTAssertFalse(history.canRedo)
        XCTAssertEqual(history.stepBack()?.added, "two")
        XCTAssertTrue(history.canRedo)
        XCTAssertEqual(history.redoSteps.map(\.added), ["two"])
        history.record(typing("x"))
        XCTAssertFalse(history.canRedo)
        XCTAssertEqual(history.undoSteps.map(\.added), ["one ", "x"])
    }

    func testTheRedoKeyMakesTheStepsAgainInTheirOrder() {
        var history = EditHistory()
        history.record(typing("one "))
        history.record(typing("two "))
        history.record(typing("three"))
        XCTAssertEqual(history.stepBack()?.added, "three")
        XCTAssertEqual(history.stepBack()?.added, "two ")
        XCTAssertEqual(history.stepForward()?.added, "two ")
        XCTAssertEqual(history.stepForward()?.added, "three")
        XCTAssertNil(history.stepForward())
        XCTAssertEqual(history.undoSteps.map(\.added), ["one ", "two ", "three"])
    }

    func testTheHistoryKeepsItsNewestStepsOnly() {
        var history = EditHistory()
        for index in 0..<(EditHistory.limit + 5) {
            history.record(EditStep(removed: "", added: "\(index)"))
        }
        XCTAssertEqual(history.undoSteps.count, EditHistory.limit)
        XCTAssertEqual(history.undoSteps.first?.added, "5")
    }

    func testAStepLosesTheStartThatItsTwoTextsShare() {
        let step = EditStep(removed: "teh ", added: "the ").trimmed()
        XCTAssertEqual(step.removed, "eh ")
        XCTAssertEqual(step.added, "he ")
        XCTAssertTrue(EditStep(removed: "same", added: "same").trimmed().isEmpty)
    }

    func testTwoStepsJoinOnlyWhenTheSecondStartsWhereTheFirstEnds() {
        // The second step takes out part of what the first put in.
        let joined = EditStep(removed: "", added: "hello").joined(with: EditStep(removed: "lo", added: "p"))
        XCTAssertEqual(joined?.removed, "")
        XCTAssertEqual(joined?.added, "help")
        // The second step takes out all of it, and older text before it.
        let longer = EditStep(removed: "x", added: "ab").joined(with: EditStep(removed: "yab", added: "z"))
        XCTAssertEqual(longer?.removed, "yx")
        XCTAssertEqual(longer?.added, "z")
        // The text of the second step is not the text that the first step left.
        XCTAssertNil(EditStep(removed: "", added: "hello").joined(with: EditStep(removed: "xx", added: "")))
        // Other Pinyin letters wait than the second step starts with.
        XCTAssertNil(
            EditStep(removed: "", added: "", lettersBefore: "", lettersAfter: "ni")
                .joined(with: EditStep(removed: "", added: "", lettersBefore: "n", lettersAfter: "nh")))
    }
}

/// The Backward key and the Redo key of the top row.
@MainActor
final class BackwardKeyTests: XCTestCase {
    private var keyboardView: KeyboardView!
    private var document: FakeDocument!
    private var spellChecker: FakeSpellChecker!
    private var controller: KeyboardTextController!

    private func makeController(before: String, after: String = "") {
        keyboardView = KeyboardView()
        document = FakeDocument(before: before, after: after)
        spellChecker = FakeSpellChecker()
        controller = KeyboardTextController(
            keyboardView: keyboardView, document: document, spellChecker: spellChecker,
            pinyinEngine: { PinyinEngine(dictionaryText: testDictionary) })
    }

    private func type(_ text: String) {
        for character in text {
            controller.keyboardView(keyboardView, insert: String(character))
        }
    }

    private func delete(_ count: Int = 1) {
        for _ in 0..<count {
            controller.keyboardViewDeleteBackward(keyboardView)
        }
    }

    private func backward() {
        controller.keyboardView(keyboardView, edit: .undo)
    }

    private func redo() {
        controller.keyboardView(keyboardView, edit: .redo)
    }

    /// The controller deletes the text after the cursor in a delayed step, so the test waits.
    private func waitForDelayedEdits() {
        RunLoop.current.run(until: Date().addingTimeInterval(0.6))
    }

    // MARK: Typing

    func testBackwardTakesBackOneWordAtATimeAndRedoBringsEachWordAgain() {
        makeController(before: "")
        type("hello world")
        XCTAssertTrue(keyboardView.canUndo)
        XCTAssertFalse(keyboardView.showsRedo)
        backward()
        XCTAssertEqual(document.text, "hello ")
        XCTAssertTrue(keyboardView.showsRedo)
        backward()
        XCTAssertEqual(document.text, "")
        XCTAssertFalse(keyboardView.canUndo)
        redo()
        XCTAssertEqual(document.text, "hello ")
        XCTAssertTrue(keyboardView.showsRedo)
        redo()
        XCTAssertEqual(document.text, "hello world")
        XCTAssertFalse(keyboardView.showsRedo)
        XCTAssertTrue(keyboardView.canUndo)
    }

    func testBackwardTakesBackOnlyTheTextThatTheKeyboardTyped() {
        makeController(before: "Dear all, ")
        type("hi")
        backward()
        XCTAssertEqual(document.text, "Dear all, ")
        backward()
        XCTAssertEqual(document.text, "Dear all, ")
        XCTAssertEqual(keyboardView.spaceCaption, "Nothing to undo")
    }

    func testNewTypingHidesTheRedoKey() {
        makeController(before: "")
        type("hello world")
        backward()
        XCTAssertTrue(keyboardView.showsRedo)
        type("x")
        XCTAssertFalse(keyboardView.showsRedo)
        XCTAssertFalse(controller.history.canRedo)
        XCTAssertEqual(document.text, "hello x")
        // The Redo key has no step now, so the text stays.
        redo()
        XCTAssertEqual(document.text, "hello x")
    }

    func testADeleteAlsoHidesTheRedoKey() {
        makeController(before: "")
        type("hello world")
        backward()
        XCTAssertTrue(keyboardView.showsRedo)
        delete()
        XCTAssertFalse(keyboardView.showsRedo)
        XCTAssertEqual(document.text, "hello")
    }

    func testAKeyThatChangesNoTextKeepsTheRedoKey() {
        makeController(before: "")
        type("hello world")
        backward()
        controller.keyboardView(keyboardView, edit: .selectAll)
        controller.keyboardView(keyboardView, edit: .selectAll)
        XCTAssertTrue(keyboardView.showsRedo)
        redo()
        XCTAssertEqual(document.text, "hello world")
    }

    func testBackwardWithoutAStepChangesNoText() {
        makeController(before: "hello")
        XCTAssertFalse(keyboardView.canUndo)
        backward()
        XCTAssertEqual(document.text, "hello")
        XCTAssertEqual(keyboardView.spaceCaption, "Nothing to undo")
    }

    // MARK: Deletes

    func testBackwardBringsBackTheTextOfTheDeletesInARow() {
        makeController(before: "hello world")
        delete(3)
        XCTAssertEqual(document.text, "hello wo")
        backward()
        XCTAssertEqual(document.text, "hello world")
        redo()
        XCTAssertEqual(document.text, "hello wo")
    }

    func testTypingAfterADeleteIsAStepOfItsOwn() {
        makeController(before: "")
        type("helo")
        delete()
        type("lo")
        XCTAssertEqual(document.text, "hello")
        backward()
        XCTAssertEqual(document.text, "hel")
        backward()
        XCTAssertEqual(document.text, "helo")
        backward()
        XCTAssertEqual(document.text, "")
    }

    func testBackwardBringsBackTheCharacterOfTheForwardDelete() {
        makeController(before: "ab", after: "cd")
        controller.keyboardView(keyboardView, edit: .deleteForward)
        XCTAssertEqual(document.text, "abd")
        backward()
        XCTAssertEqual(document.text, "abcd")
        XCTAssertEqual(document.textBeforeCursor, "abc")
        redo()
        XCTAssertEqual(document.text, "abd")
        XCTAssertEqual(document.textBeforeCursor, "ab")
    }

    // MARK: Changes that the keyboard makes by itself

    func testBackwardTakesBackACorrectionAndKeepsTheSpaceAfterTheWord() {
        makeController(before: "")
        type("teh ")
        XCTAssertEqual(document.text, "the ")
        backward()
        XCTAssertEqual(document.text, "teh ")
        // The person took the correction back, so the keyboard keeps the word as typed.
        XCTAssertEqual(spellChecker.learned, ["teh"])
        XCTAssertEqual(keyboardView.spaceCaption, "Kept teh")
        backward()
        XCTAssertEqual(document.text, "")
        redo()
        XCTAssertEqual(document.text, "teh ")
        redo()
        XCTAssertEqual(document.text, "the ")
    }

    func testAWordAfterATakenBackCorrectionStaysAsTyped() {
        makeController(before: "")
        type("teh ")
        backward()
        type("teh ")
        XCTAssertEqual(document.text, "teh teh ")
    }

    func testBackwardTakesBackASpaceRemovalAndLeavesTheTextAsTyped() {
        makeController(before: "")
        type("word .")
        XCTAssertEqual(document.text, "word.")
        backward()
        XCTAssertEqual(document.text, "word .")
        backward()
        XCTAssertEqual(document.text, "")
    }

    func testBackwardTakesBackThePeriodOfTwoSpaces() {
        makeController(before: "")
        type("word  ")
        XCTAssertEqual(document.text, "word. ")
        backward()
        XCTAssertEqual(document.text, "word  ")
        redo()
        XCTAssertEqual(document.text, "word. ")
    }

    func testBackwardTakesBackATappedPredictedWord() {
        makeController(before: "")
        type("hel")
        controller.keyboardView(keyboardView, didSelectPredictedWord: "hello")
        XCTAssertEqual(document.text, "hello ")
        backward()
        XCTAssertEqual(document.text, "hel")
        redo()
        XCTAssertEqual(document.text, "hello ")
    }

    // MARK: Select all

    func testBackwardBringsBackAllTheTextThatAKeyReplaced() {
        makeController(before: "hello world")
        controller.keyboardView(keyboardView, edit: .selectAll)
        type("x")
        XCTAssertEqual(document.text, "x")
        backward()
        XCTAssertEqual(document.text, "hello world")
        redo()
        XCTAssertEqual(document.text, "x")
    }

    func testBackwardBringsBackAllTheTextAlsoWithTextAfterTheCursor() {
        makeController(before: "hello", after: " world")
        controller.keyboardView(keyboardView, edit: .selectAll)
        delete()
        waitForDelayedEdits()
        XCTAssertEqual(document.text, "")
        backward()
        XCTAssertEqual(document.text, "hello world")
        XCTAssertEqual(document.textBeforeCursor, "hello world")
    }

    // MARK: The place of the cursor

    func testAMoveOfTheCursorByAKeyEmptiesTheHistory() {
        makeController(before: "")
        type("hello world")
        backward()
        XCTAssertTrue(keyboardView.showsRedo)
        controller.keyboardView(keyboardView, moveCursorBy: -1)
        XCTAssertFalse(keyboardView.canUndo)
        XCTAssertFalse(keyboardView.showsRedo)
        backward()
        XCTAssertEqual(document.text, "hello ")
    }

    func testATouchInTheFieldEmptiesTheHistory() {
        makeController(before: "")
        type("hello world")
        backward()
        document.tap(atUTF16Offset: 2)
        controller.documentDidChange()
        XCTAssertFalse(keyboardView.canUndo)
        XCTAssertFalse(keyboardView.showsRedo)
        backward()
        redo()
        XCTAssertEqual(document.text, "hello ")
    }

    func testAChangeOfTheTextByTheAppEmptiesTheHistory() {
        makeController(before: "")
        type("hello world")
        backward()
        // The app takes the text out of its field, as a chat app does after it sent the text.
        document.text = ""
        document.cursor = 0
        controller.documentDidChange()
        XCTAssertFalse(keyboardView.canUndo)
        XCTAssertFalse(keyboardView.showsRedo)
        redo()
        XCTAssertEqual(document.text, "")
    }

    func testAChangeOfTheTextThatTheFieldDidNotReportStillStopsBackward() {
        makeController(before: "")
        type("hello")
        document.text = "other"
        document.cursor = 5
        backward()
        XCTAssertEqual(document.text, "other")
        XCTAssertFalse(keyboardView.canUndo)
    }

    func testTheHistoryDoesNotGoOnInAnotherTextField() {
        makeController(before: "")
        type("abc")
        delete(3)
        XCTAssertEqual(document.text, "")
        // Another field with the same text before the cursor.
        document.documentIdentifier = UUID()
        controller.documentDidChange()
        XCTAssertFalse(keyboardView.canUndo)
        backward()
        XCTAssertEqual(document.text, "")
    }

    func testTheKeyboardThatLeavesTheScreenEmptiesTheHistory() {
        makeController(before: "")
        type("hello")
        controller.cancelPendingEdits()
        XCTAssertFalse(keyboardView.canUndo)
    }

    // MARK: Chinese

    func testBackwardTakesBackAPickedCandidateAndBringsTheLettersBack() {
        makeController(before: "")
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        type("nihao")
        type(" ")
        XCTAssertEqual(document.text, "\u{4F60}\u{597D}")
        backward()
        // The letters wait for a candidate again, and the field shows them as marked text.
        XCTAssertEqual(controller.pinyinBuffer, "nihao")
        XCTAssertEqual(document.markedText, "nihao")
        XCTAssertEqual(document.text, "nihao")
        XCTAssertTrue(keyboardView.showsRedo)
        // The letters of one syllable run are one step.
        backward()
        XCTAssertEqual(controller.pinyinBuffer, "")
        XCTAssertEqual(document.text, "")
        redo()
        XCTAssertEqual(controller.pinyinBuffer, "nihao")
        XCTAssertEqual(document.text, "nihao")
        redo()
        XCTAssertEqual(controller.pinyinBuffer, "")
        XCTAssertEqual(document.text, "\u{4F60}\u{597D}")
        XCTAssertFalse(keyboardView.showsRedo)
    }

    func testBackwardBringsBackTheLetterThatTheDeleteKeyTookOutOfThePinyinLetters() {
        makeController(before: "")
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        type("nih")
        delete()
        XCTAssertEqual(controller.pinyinBuffer, "ni")
        backward()
        XCTAssertEqual(controller.pinyinBuffer, "nih")
        XCTAssertEqual(document.markedText, "nih")
    }

    func testBackwardAfterASwitchToEnglishBringsTheLettersAndChineseModeBack() {
        makeController(before: "")
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        type("ni")
        // The switch types the letters as plain text.
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        XCTAssertFalse(controller.chineseMode)
        XCTAssertEqual(document.text, "ni")
        XCTAssertEqual(document.markedText, "")
        backward()
        XCTAssertTrue(controller.chineseMode)
        XCTAssertEqual(controller.pinyinBuffer, "ni")
        XCTAssertEqual(document.markedText, "ni")
    }
}

/// The Backward key and the Redo key in the top row of keys.
@MainActor
final class BackwardKeyLayoutTests: XCTestCase {
    private var keyboardView: KeyboardView!
    private var document: FakeDocument!
    private var controller: KeyboardTextController!

    /// The widths of the folded phone, the open phone in portrait, and the open phone in landscape.
    private static let widths: [CGFloat] = [466, 669, 951]

    private func makeKeyboard(width: CGFloat = 466, before: String = "") {
        let height = KeyboardView.preferredHeight(forWidth: width, compactHeight: false, device: .phone, landscape: false)
        keyboardView = KeyboardView(frame: CGRect(x: 0, y: 0, width: width, height: height))
        document = FakeDocument(before: before)
        controller = KeyboardTextController(
            keyboardView: keyboardView, document: document, spellChecker: FakeSpellChecker(),
            pinyinEngine: { PinyinEngine(dictionaryText: testDictionary) })
        controller.documentDidChange()
        keyboardView.layoutIfNeeded()
    }

    private func type(_ text: String) {
        for character in text {
            controller.keyboardView(keyboardView, insert: String(character))
        }
    }

    private func keyView(_ kind: KeyKind) throws -> KeyView {
        try XCTUnwrap(keyboardView.subviews.compactMap { $0 as? KeyView }.first { $0.key.kind == kind }, "\(kind)")
    }

    private func tap(_ kind: KeyKind) throws {
        let cell = try keyView(kind).hitFrame
        tap(CGPoint(x: cell.midX, y: cell.midY))
    }

    private func tap(_ point: CGPoint) {
        let touch = FakeTouch(at: point)
        keyboardView.touchesBegan([touch], with: nil)
        keyboardView.touchesEnded([touch], with: nil)
        keyboardView.layoutIfNeeded()
    }

    private func widths() -> [CGFloat] {
        // An iPad chooses its layout by the orientation of the screen, so only the compact
        // width gives the same layout there.
        KeyboardDevice.current == .phone ? Self.widths : [466]
    }

    func testTheSmallKeysOfTheTopRowHaveOneWidthInEachLayout() throws {
        for style in [LayoutStyle.compact, .wide, .split] {
            let row = KeyboardLayout.make(style: style, layer: .letters, showsGlobe: true).rows[0]
            let cut = try XCTUnwrap(row.first { $0.kind == .cut }).weight
            for kind in [KeyKind.selectAll, .undo, .redo, .copy, .paste] {
                XCTAssertEqual(try XCTUnwrap(row.first { $0.kind == kind }).weight, cut, accuracy: 0.0001, "\(style) \(kind)")
            }
        }
    }

    func testTheHiddenRedoKeyGivesItsWidthToTheStrip() throws {
        for style in [LayoutStyle.compact, .wide, .split] {
            let row = KeyboardLayout.make(style: style, layer: .letters, showsGlobe: true).rows[0]
            let redo = try XCTUnwrap(row.firstIndex { $0.kind == .redo })
            let strip = try XCTUnwrap(row.firstIndex { $0.kind == .predictionStrip })
            XCTAssertEqual(KeyboardLayout.drawnWeights(of: row, showsRedo: true), row.map(\.weight), "\(style)")
            let hidden = KeyboardLayout.drawnWeights(of: row, showsRedo: false)
            XCTAssertEqual(hidden[redo], 0, "\(style)")
            XCTAssertEqual(hidden[strip], row[strip].weight + row[redo].weight, accuracy: 0.0001, "\(style)")
            XCTAssertEqual(hidden.reduce(0, +), row.reduce(0) { $0 + $1.weight }, accuracy: 0.0001, "\(style)")
        }
    }

    func testTheBackwardKeyStandsRightOfTheTypingSpeedAtEveryWidth() throws {
        for width in widths() {
            makeKeyboard(width: width)
            let backward = try keyView(.undo)
            XCTAssertFalse(backward.isHidden, "\(width)")
            XCTAssertEqual(backward.shownSymbolName, "arrow.uturn.backward", "\(width)")
            XCTAssertEqual(backward.hitFrame.minX, keyboardView.typingSpeedView.frame.maxX, accuracy: 0.5, "\(width)")
            XCTAssertEqual(backward.hitFrame.width, try keyView(.cut).hitFrame.width, accuracy: 0.5, "\(width)")
        }
    }

    func testTheRedoKeyShowsRightOfTheBackwardKeyOnlyWhileAStepCanBeMadeAgain() throws {
        for width in widths() {
            makeKeyboard(width: width)
            let backward = try keyView(.undo)
            let redo = try keyView(.redo)
            let strip = keyboardView.predictionStrip
            // Without a step to make again, the key is hidden and the strip starts right of
            // the Backward key.
            XCTAssertTrue(redo.isHidden, "\(width)")
            XCTAssertEqual(strip.frame.minX, backward.hitFrame.maxX, accuracy: 0.5, "\(width)")
            let widthWithoutRedo = strip.frame.width

            type("hello")
            keyboardView.layoutIfNeeded()
            XCTAssertTrue(redo.isHidden, "\(width)")

            try tap(.undo)
            XCTAssertEqual(document.text, "", "\(width)")
            XCTAssertFalse(redo.isHidden, "\(width)")
            XCTAssertEqual(redo.shownSymbolName, "arrow.uturn.forward", "\(width)")
            XCTAssertEqual(redo.hitFrame.minX, backward.hitFrame.maxX, accuracy: 0.5, "\(width)")
            XCTAssertEqual(redo.hitFrame.width, backward.hitFrame.width, accuracy: 0.5, "\(width)")
            XCTAssertEqual(strip.frame.minX, redo.hitFrame.maxX, accuracy: 0.5, "\(width)")
            XCTAssertEqual(strip.frame.width, widthWithoutRedo - redo.hitFrame.width, accuracy: 0.5, "\(width)")
            XCTAssertEqual(strip.frame.maxX, try keyView(.cut).hitFrame.minX, accuracy: 0.5, "\(width)")

            try tap(.redo)
            XCTAssertEqual(document.text, "hello", "\(width)")
            XCTAssertTrue(redo.isHidden, "\(width)")
            XCTAssertEqual(strip.frame.minX, backward.hitFrame.maxX, accuracy: 0.5, "\(width)")
            XCTAssertEqual(strip.frame.width, widthWithoutRedo, accuracy: 0.5, "\(width)")
        }
    }

    func testATypedCharacterHidesTheRedoKeyAndLeavesTheOtherKeysInPlace() throws {
        for width in widths() {
            makeKeyboard(width: width)
            type("hello world")
            try tap(.undo)
            let redo = try keyView(.redo)
            XCTAssertFalse(redo.isHidden, "\(width)")
            let keys = keyboardView.subviews.compactMap { $0 as? KeyView }
            // The Redo key and the place of the strip change their width. Every other key stays.
            func others(_ keys: [KeyView]) -> [CGRect] {
                keys.filter { $0.key.kind != .redo && $0.key.kind != .predictionStrip }.map(\.frame)
            }
            let frames = others(keys)
            type("x")
            keyboardView.layoutIfNeeded()
            XCTAssertTrue(redo.isHidden, "\(width)")
            // The keyboard keeps its key views, so a finger that is down on a key keeps its key.
            let keysAfter = keyboardView.subviews.compactMap { $0 as? KeyView }
            XCTAssertEqual(keysAfter.count, keys.count, "\(width)")
            XCTAssertTrue(zip(keysAfter, keys).allSatisfy { $0 === $1 }, "\(width)")
            XCTAssertEqual(others(keysAfter), frames, "\(width)")
        }
    }

    func testATouchInThePlaceOfTheHiddenRedoKeyPressesNoKey() throws {
        for width in widths() {
            makeKeyboard(width: width)
            type("hello")
            let backward = try keyView(.undo).hitFrame
            // The hidden key has no width. The place right of the Backward key is the strip.
            XCTAssertEqual(try keyView(.redo).hitFrame.width, 0, accuracy: 0.01, "\(width)")
            for x in [backward.maxX + 1, backward.maxX + backward.width / 2, backward.maxX + backward.width - 1] {
                tap(CGPoint(x: x, y: backward.midY))
            }
            XCTAssertEqual(document.text, "hello", "\(width)")
            XCTAssertTrue(keyboardView.canUndo, "\(width)")
        }
    }

    func testTheBackwardKeyIsGrayWhileTheHistoryHoldsNoStep() throws {
        makeKeyboard()
        let backward = try keyView(.undo)
        XCTAssertTrue(backward.isDimmed)
        type("a")
        XCTAssertFalse(backward.isDimmed)
        try tap(.undo)
        XCTAssertTrue(backward.isDimmed)
        XCTAssertFalse(try keyView(.redo).isDimmed)
    }

    func testTheTwoKeysStayInEveryLayer() throws {
        makeKeyboard()
        type("hello")
        try tap(.undo)
        for layer in [KeyboardLayer.symbols, .more, .letters] {
            keyboardView.show(layer: layer)
            keyboardView.layoutIfNeeded()
            XCTAssertFalse(try keyView(.undo).isHidden, "\(layer)")
            XCTAssertFalse(try keyView(.redo).isHidden, "\(layer)")
            XCTAssertTrue(try keyView(.undo).isDimmed, "\(layer)")
        }
        try tap(.redo)
        XCTAssertEqual(document.text, "hello")
        XCTAssertTrue(try keyView(.redo).isHidden)
        XCTAssertFalse(try keyView(.undo).isDimmed)
    }
}
