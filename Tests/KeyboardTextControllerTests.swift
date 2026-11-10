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

/// A small dictionary in the format of pinyin-dictionary.txt, most frequent word first.
let testDictionary = [
    "wo\t\u{6211}\t1000", "ni\t\u{4F60}\t900", "hao\t\u{597D}\t800", "ni hao\t\u{4F60}\u{597D}\t700",
    "zhong guo\t\u{4E2D}\u{56FD}\t600", "zhong\t\u{4E2D}\t500", "guo\t\u{56FD}\t400", "xian\t\u{5148}\t300",
    "men\t\u{4EEC}\t250", "xi\t\u{897F}\t200", "an\t\u{5B89}\t100", "n\t\u{55EF}\t10", "ni\t\u{5C3C}\t5",
].joined(separator: "\n")

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

    func testPinyinLettersWaitInTheBufferAndSpaceTypesTheFirstCandidate() {
        makeController(before: "")
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        type("nihao")
        XCTAssertEqual(document.text, "")
        XCTAssertEqual(controller.pinyinBuffer, "nihao")
        type(" ")
        XCTAssertEqual(document.text, "\u{4F60}\u{597D}")
        XCTAssertEqual(controller.pinyinBuffer, "")
    }

    func testADigitPicksACandidateAndTheRestStaysInTheBuffer() {
        makeController(before: "")
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        type("nihao")
        // Candidates: the phrase for "ni hao", then the two characters for "ni".
        type("2")
        XCTAssertEqual(document.text, "\u{4F60}")
        XCTAssertEqual(controller.pinyinBuffer, "hao")
    }

    func testChineseQuotationMarksOpenAndClose() {
        makeController(before: "")
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        type("\"wo \"")
        XCTAssertEqual(document.text, "\u{201C}\u{6211}\u{201D}")
    }

    func testAnApostropheSplitsTheSyllablesWhileTyping() {
        makeController(before: "")
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        type("xi'an ")
        XCTAssertEqual(document.text, "\u{897F}\u{5B89}")
    }

    func testBackspaceRemovesAPinyinLetterBeforeAnyText() {
        makeController(before: "a")
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        type("wo")
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(controller.pinyinBuffer, "w")
        XCTAssertEqual(document.text, "a")
    }

    func testPunctuationTypesTheWordAndTheChineseMark() {
        makeController(before: "")
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        type("nihao,")
        XCTAssertEqual(document.text, "\u{4F60}\u{597D}\u{FF0C}")
    }

    func testReturnTypesThePinyinLettersAsTheyAre() {
        makeController(before: "")
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        type("wo")
        controller.keyboardViewReturn(keyboardView)
        XCTAssertEqual(document.text, "wo")
    }

    func testEnglishTypingIsUnchangedAfterASwitchBack() {
        makeController(before: "")
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        type("teh ")
        XCTAssertEqual(document.text, "the ")
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
            keyboardView: keyboardView, document: document, spellChecker: spellChecker,
            pinyinEngine: { PinyinEngine(dictionaryText: testDictionary) })
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

final class PinyinEngineTests: XCTestCase {
    private let engine = PinyinEngine(dictionaryText: testDictionary)

    func testSegmentSplitsLettersIntoSyllables() {
        XCTAssertEqual(engine.segment("nihao").syllables, ["ni", "hao"])
        XCTAssertEqual(engine.segment("zhongguo").syllables, ["zhong", "guo"])
        XCTAssertEqual(engine.segment("nih").syllables, ["ni"])
        XCTAssertEqual(engine.segment("nih").remainder, "h")
        XCTAssertEqual(engine.segment("zh").remainder, "zh")
    }

    func testSegmentTakesTheLongestSyllableFirst() {
        XCTAssertEqual(engine.segment("xian").syllables, ["xian"])
        XCTAssertEqual(engine.segment("nimen").syllables, ["ni", "men"])
    }

    func testCandidatesPutTheWholePhraseFirst() {
        let words = engine.candidates(for: "nihao").map { $0.word }
        XCTAssertEqual(words, ["\u{4F60}\u{597D}", "\u{4F60}", "\u{5C3C}"])
        XCTAssertEqual(engine.candidates(for: "nihao").first?.consumedLetters, 5)
        XCTAssertEqual(engine.candidates(for: "nihao").last?.consumedLetters, 2)
    }

    func testTheFirstCandidateIsTheWholeSentence() {
        // "wo ni hao" is not a dictionary word. The most likely cut is "wo" plus the phrase "ni hao".
        let candidates = engine.candidates(for: "wonihao")
        XCTAssertEqual(candidates.first, PinyinCandidate(word: "\u{6211}\u{4F60}\u{597D}", consumedLetters: 7, spelling: "wo ni hao"))
        XCTAssertEqual(candidates.dropFirst().first, PinyinCandidate(word: "\u{6211}", consumedLetters: 2, spelling: "wo"))
    }

    func testTheSentencePrefersAPhraseOverItsSingleCharacters() {
        XCTAssertEqual(engine.sentence(for: ["zhong", "guo", "ni", "hao"]), "\u{4E2D}\u{56FD}\u{4F60}\u{597D}")
        XCTAssertNil(engine.sentence(for: ["zhong", "qi"]))
    }

    func testAPickOfAShorterWordLeavesTheRestForANewSentence() {
        let afterFirstPick = engine.candidates(for: "nihao")
        XCTAssertEqual(afterFirstPick.first?.word, "\u{4F60}\u{597D}")
    }

    func testFirstLettersOfferTheWordsThatStartThatWay() {
        let candidates = engine.candidates(for: "nh")
        XCTAssertEqual(candidates.first, PinyinCandidate(word: "\u{4F60}\u{597D}", consumedLetters: 2, spelling: "ni hao"))
        XCTAssertEqual(engine.candidates(for: "zg").first?.word, "\u{4E2D}\u{56FD}")
    }

    func testAnApostropheForcesASyllableBreak() {
        XCTAssertEqual(engine.segment("xian").syllables, ["xian"])
        XCTAssertEqual(engine.segment("xi'an").syllables, ["xi", "an"])
        let candidates = engine.candidates(for: "xi'an")
        XCTAssertEqual(candidates.first?.word, "\u{897F}\u{5B89}")
        XCTAssertEqual(candidates.first?.consumedLetters, 5)
        XCTAssertEqual(engine.display(for: "xi'an"), "xi'an")
    }

    func testALearnedWordComesFirstAndIsSaved() {
        var saved: [String: [String]] = [:]
        let learning = PinyinEngine(dictionaryText: testDictionary, saveLearnedWords: { saved = $0 })
        XCTAssertEqual(learning.candidates(for: "ni").first?.word, "\u{4F60}")
        learning.learn(spelling: "ni", word: "\u{5C3C}")
        XCTAssertEqual(learning.candidates(for: "ni").first?.word, "\u{5C3C}")
        XCTAssertEqual(saved["ni"], ["\u{5C3C}"])
        let reloaded = PinyinEngine(dictionaryText: testDictionary, learnedWords: saved)
        XCTAssertEqual(reloaded.candidates(for: "ni").first?.word, "\u{5C3C}")
    }

    func testALearnedPhraseBecomesTheSentence() {
        let learning = PinyinEngine(dictionaryText: testDictionary)
        XCTAssertEqual(learning.sentence(for: ["wo", "men"]), "\u{6211}\u{4EEC}")
        learning.learn(spelling: "wo men", word: "\u{6211}\u{95E8}")
        XCTAssertEqual(learning.sentence(for: ["wo", "men"]), "\u{6211}\u{95E8}")
    }

    func testAnIncompleteSyllableOffersCharactersThatStartThatWay() {
        let words = engine.candidates(for: "zh").map { $0.word }
        XCTAssertEqual(words, ["\u{4E2D}"])
    }

    func testDisplayMarksTheSyllables() {
        XCTAssertEqual(engine.display(for: "nihaoz"), "ni'hao'z")
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
        XCTAssertEqual(KeyboardView.style(forWidth: 678), .wide)
        XCTAssertEqual(KeyboardView.style(forWidth: 466), .compact)
    }

    func testTheOpenPhoneInLandscapeGetsTheSplitLayout() {
        XCTAssertEqual(KeyboardView.style(forWidth: 951), .split)
    }

    func testEverySplitRowHasOneEmptyMiddleAndTheSameWidth() {
        for layer in [KeyboardLayer.letters, .symbols, .more] {
            let layout = KeyboardLayout.make(style: .split, layer: layer, showsGlobe: true)
            XCTAssertEqual(layout.units, 20.5)
            for row in layout.rows {
                XCTAssertEqual(row.filter { $0.kind == .gap }.count, 1)
                XCTAssertEqual(row.reduce(0) { $0 + $1.weight }, 20.5, accuracy: 0.0001)
            }
        }
    }

    func testTheSplitLettersKeepEachHandsKeysTogether() {
        let layout = KeyboardLayout.make(style: .split, layer: .letters, showsGlobe: true)
        func leftHalf(_ row: Int) -> [KeyKind] {
            Array(layout.rows[row].prefix { $0.kind != .gap }.map { $0.kind })
        }
        XCTAssertEqual(leftHalf(1).last, .dual("5", "%"))
        XCTAssertEqual(leftHalf(2).last, .character("t"))
        XCTAssertEqual(leftHalf(3).last, .character("g"))
        XCTAssertEqual(leftHalf(4).last, .character("b"))
        // The bottom row has a space bar on each side of the middle.
        XCTAssertEqual(layout.rows[5].filter { $0.kind == .space }.count, 2)
        XCTAssertEqual(leftHalf(5).last, .space)
    }
}
