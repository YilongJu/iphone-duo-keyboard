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

/// A spell checker with a fixed list of readings. A key holds one word, or two typed words
/// with one space between them. Text without its own key is read word by word.
@MainActor
final class FakeSpellChecker: SpellChecking {
    var corrections: [String: String] = [
        "teh": "the", "recieve": "receive", "th e": "the", "thequick": "the quick", "form teh": "from the",
    ]
    var learned: [String] = []
    /// Every call of `reading`, as "previous word|typed text".
    var requests: [String] = []

    func reading(previousWord: String, typed: String) -> String? {
        requests.append("\(previousWord)|\(typed)")
        if let whole = corrections[typed] { return whole }
        return typed.split(separator: " ").map { corrections[String($0)] ?? String($0) }
            .joined(separator: " ")
    }

    func learn(_ word: String) {
        learned.append(word)
    }

    func keeps(_ word: String) -> Bool {
        learned.contains(word)
    }
}

/// A proofreader with fixed answers. A sentence without an answer comes back unchanged.
@MainActor
final class FakeProofreader: SentenceProofreading {
    var answers: [String: String] = [:]
    var requests: [String] = []

    func proofread(_ sentence: String) async -> ProofreadResult {
        requests.append(sentence)
        return ProofreadResult(text: answers[sentence] ?? sentence, seconds: 0.5, note: nil)
    }
}

/// A language model test with fixed result lines. It does not load a model.
@MainActor
final class FakeLanguageModelMeasurer: LanguageModelMeasuring {
    var lines = ["model       fake", "done        every step ran"]
    /// Count of runs that were started.
    var runs = 0
    /// True keeps each run open after its lines, until `finish()`.
    var staysOpen = false
    private var openRun: AsyncStream<String>.Continuation?

    func resultLines() -> AsyncStream<String> {
        runs += 1
        let (stream, continuation) = AsyncStream.makeStream(of: String.self)
        for line in lines {
            continuation.yield(line)
        }
        if staysOpen {
            openRun = continuation
        } else {
            continuation.finish()
        }
        return stream
    }

    func finish() {
        openRun?.finish()
        openRun = nil
    }
}

@MainActor
final class KeyboardTextControllerTests: XCTestCase {
    private func makeMeasuringController(before: String) -> FakeLanguageModelMeasurer {
        makeController(before: before)
        let measurer = FakeLanguageModelMeasurer()
        controller.languageModelMeasurer = measurer
        return measurer
    }

    func testTheTriggerTextAndASpaceRunTheLanguageModelTestOnce() async {
        let measurer = makeMeasuringController(before: "")
        type("duo:lm ")
        await controller.languageModelTask?.value
        XCTAssertEqual(measurer.runs, 1)
        XCTAssertEqual(document.text, "duo:lm \nmodel       fake\ndone        every step ran")
        XCTAssertNil(controller.languageModelTask)
    }

    func testTheTriggerWorksAfterOtherTextAndWithACapital() async {
        let measurer = makeMeasuringController(before: "Notes of today.\n")
        type("Duo:lm ")
        await controller.languageModelTask?.value
        XCTAssertEqual(measurer.runs, 1)
        XCTAssertEqual(document.text, "Notes of today.\nDuo:lm \nmodel       fake\ndone        every step ran")
    }

    func testTheTestStartsAtTheSpaceAndNotBefore() async {
        let measurer = makeMeasuringController(before: "")
        type("duo:lm")
        XCTAssertEqual(measurer.runs, 0)
        type(" ")
        // The run has started before the keyboard types its first result line.
        XCTAssertEqual(measurer.runs, 1)
        XCTAssertEqual(document.text, "duo:lm ")
        await controller.languageModelTask?.value
        XCTAssertEqual(measurer.runs, 1)
    }

    func testOtherTextDoesNotRunTheLanguageModelTest() {
        // The trigger without its space, with a letter after it, with a sign or a letter
        // right before it, and with a space in place of the colon.
        for text in ["duo:lm", "duo:lmx ", "xduo:lm ", "/duo:lm ", "duo lm ", "duo:l ", "hello world "] {
            let measurer = makeMeasuringController(before: "")
            type(text)
            XCTAssertEqual(measurer.runs, 0, text)
            XCTAssertNil(controller.languageModelTask, text)
            XCTAssertEqual(document.text, text)
        }
    }

    func testTheTriggerTextIsPlainTextWithoutAMeasurer() {
        makeController(before: "")
        type("duo:lm ")
        XCTAssertNil(controller.languageModelTask)
        XCTAssertEqual(document.text, "duo:lm ")
    }

    func testASecondTriggerDoesNotStartTheTestWhileItRuns() async {
        let measurer = makeMeasuringController(before: "")
        measurer.staysOpen = true
        type("duo:lm ")
        type("duo:lm ")
        XCTAssertEqual(measurer.runs, 1)
        let run = controller.languageModelTask
        measurer.finish()
        await run?.value
        XCTAssertEqual(document.text, "duo:lm duo:lm \nmodel       fake\ndone        every step ran")
        // After the end of a run the trigger starts the test again.
        measurer.staysOpen = false
        type("\nduo:lm ")
        await controller.languageModelTask?.value
        XCTAssertEqual(measurer.runs, 2)
    }

    private func makeProofreadingController(before: String, answers: [String: String]) -> FakeProofreader {
        makeController(before: before)
        let proofreader = FakeProofreader()
        proofreader.answers = answers
        controller.proofreader = proofreader
        return proofreader
    }

    func testAFinishedSentenceGetsAFixThatATapApplies() async {
        let proofreader = makeProofreadingController(
            before: "Hi there. ", answers: ["I came form the office.": "I came from the office."])
        type("I came form the office.")
        await controller.proofreadTask?.value
        XCTAssertEqual(proofreader.requests, ["I came form the office."])
        XCTAssertEqual(controller.proofreadSuggestion?.corrected, "I came from the office.")
        // The text changes only on a tap.
        XCTAssertEqual(document.text, "Hi there. I came form the office.")
        controller.keyboardView(keyboardView, didSelectCandidateAt: 0)
        XCTAssertEqual(document.text, "Hi there. I came from the office.")
        XCTAssertNil(controller.proofreadSuggestion)
    }

    func testAFixKeepsTheSpaceTypedAfterTheSentence() async {
        _ = makeProofreadingController(before: "", answers: ["I came form the office.": "I came from the office."])
        type("I came form the office. ")
        await controller.proofreadTask?.value
        controller.keyboardView(keyboardView, didSelectCandidateAt: 0)
        XCTAssertEqual(document.text, "I came from the office. ")
    }

    func testAChineseFixMustKeepTheSoundOfEachCharacter() async {
        // "\u{5B89}" (an) for "\u{597D}" (hao) changes the sound, so the fix is the model's own idea.
        let sentence = "\u{4F60}\u{597D}\u{4F60}\u{597D}\u{3002}"
        _ = makeProofreadingController(before: "", answers: [sentence: "\u{4F60}\u{5B89}\u{4F60}\u{597D}\u{3002}"])
        document.insertText(sentence.dropLast().description)
        type("\u{3002}")
        await controller.proofreadTask?.value
        XCTAssertNil(controller.proofreadSuggestion)
    }

    func testAChineseFixWithTheSameSoundIsShown() async {
        // "\u{5C3C}" and "\u{4F60}" are both "ni" in the test dictionary.
        let sentence = "\u{5C3C}\u{597D}\u{4F60}\u{597D}\u{3002}"
        _ = makeProofreadingController(before: "", answers: [sentence: "\u{4F60}\u{597D}\u{4F60}\u{597D}\u{3002}"])
        document.insertText(sentence.dropLast().description)
        type("\u{3002}")
        await controller.proofreadTask?.value
        XCTAssertEqual(controller.proofreadSuggestion?.corrected, "\u{4F60}\u{597D}\u{4F60}\u{597D}\u{3002}")
    }

    func testACommaAlsoGetsAFix() async {
        let proofreader = makeProofreadingController(
            before: "", answers: ["I came form the office,": "I came from the office,"])
        type("I came form the office, ")
        await controller.proofreadTask?.value
        XCTAssertEqual(proofreader.requests, ["I came form the office,"])
        controller.keyboardView(keyboardView, didSelectCandidateAt: 0)
        XCTAssertEqual(document.text, "I came from the office, ")
    }

    func testTheNextKeyTakesTheFixAway() async {
        _ = makeProofreadingController(before: "", answers: ["I came form the office.": "I came from the office."])
        type("I came form the office.")
        await controller.proofreadTask?.value
        XCTAssertNotNil(controller.proofreadSuggestion)
        type(" N")
        XCTAssertNil(controller.proofreadSuggestion)
        XCTAssertEqual(document.text, "I came form the office. N")
    }

    func testAnAnswerThatRewritesTheSentenceIsNotShown() async {
        _ = makeProofreadingController(
            before: "", answers: ["I came form the office.": "Sure! Here is a better sentence: I arrived from work."])
        type("I came form the office.")
        await controller.proofreadTask?.value
        XCTAssertNil(controller.proofreadSuggestion)
    }

    func testAnUnchangedSentenceAndAShortOneGetNoFix() async {
        let proofreader = makeProofreadingController(before: "", answers: [:])
        type("All is well here.")
        await controller.proofreadTask?.value
        XCTAssertNil(controller.proofreadSuggestion)
        type(" Ok.")
        await controller.proofreadTask?.value
        // "Ok." has one word, so the keyboard does not ask.
        XCTAssertEqual(proofreader.requests, ["All is well here."])
    }

    func testFinishedSentence() {
        XCTAssertEqual(KeyboardTextLogic.finishedSentence(before: "One. Two three four.  "), "Two three four.")
        XCTAssertEqual(KeyboardTextLogic.finishedSentence(before: "a\nIs it so here?"), "Is it so here?")
        XCTAssertNil(KeyboardTextLogic.finishedSentence(before: "Two three four"))
        // A comma, a semicolon and a colon also end a text to read. The text starts at the
        // sentence's start, so it holds the clauses before the mark.
        XCTAssertEqual(KeyboardTextLogic.finishedSentence(before: "One. Two three four, "), "Two three four,")
        XCTAssertEqual(KeyboardTextLogic.finishedSentence(before: "Two three four, five six;"), "Two three four, five six;")
        XCTAssertEqual(KeyboardTextLogic.finishedSentence(before: "Two three four\u{2026}"), "Two three four\u{2026}")
        XCTAssertEqual(
            KeyboardTextLogic.finishedSentence(before: "\u{4ECA}\u{5929}\u{5929}\u{6C14}\u{597D}\u{FF0C}"),
            "\u{4ECA}\u{5929}\u{5929}\u{6C14}\u{597D}\u{FF0C}")
        XCTAssertNil(KeyboardTextLogic.finishedSentence(before: "Two three."))
        XCTAssertEqual(
            KeyboardTextLogic.finishedSentence(before: "\u{4F60}\u{597D}\u{3002}\u{4ECA}\u{5929}\u{5929}\u{6C14}\u{597D}\u{3002}"),
            "\u{4ECA}\u{5929}\u{5929}\u{6C14}\u{597D}\u{3002}")
    }

    func testAcceptedProofreading() {
        let sentence = "I came form the office."
        XCTAssertEqual(KeyboardTextLogic.acceptedProofreading(of: sentence, answer: " I came from the office.\n"), "I came from the office.")
        XCTAssertEqual(KeyboardTextLogic.acceptedProofreading(of: sentence, answer: "\"I came from the office.\""), "I came from the office.")
        XCTAssertNil(KeyboardTextLogic.acceptedProofreading(of: sentence, answer: sentence))
        XCTAssertNil(KeyboardTextLogic.acceptedProofreading(of: sentence, answer: "I arrived here from my place of work today."))
        XCTAssertNil(KeyboardTextLogic.acceptedProofreading(of: sentence, answer: ""))
        // Chinese has no spaces, so the count is by character: one wrong character is a small fix.
        XCTAssertEqual(
            KeyboardTextLogic.acceptedProofreading(of: "\u{6211}\u{5728}\u{5BB6}\u{91CC}\u{3002}", answer: "\u{6211}\u{518D}\u{5BB6}\u{91CC}\u{3002}"),
            "\u{6211}\u{518D}\u{5BB6}\u{91CC}\u{3002}")
        XCTAssertEqual(KeyboardTextLogic.changedUnits(["a", "b", "c"], ["a", "x", "c", "d"]), 2)
        // A new word must look like the word it replaces. The first answer puts two unrelated
        // words in place of a misspelled one, and the second answer spells that word right.
        let long = "Right now not just period will trigger the all mautocoorection, it seems so."
        XCTAssertNil(KeyboardTextLogic.acceptedProofreading(
            of: long, answer: "Right now not just period will trigger the all from correction, it seems so."))
        XCTAssertNotNil(KeyboardTextLogic.acceptedProofreading(
            of: long, answer: "Right now not just period will trigger the all autocorrection, it seems so."))
        XCTAssertNotNil(KeyboardTextLogic.acceptedProofreading(of: "I saw teh quik fox.", answer: "I saw the quick fox."))
        XCTAssertNotNil(KeyboardTextLogic.acceptedProofreading(of: "I saw thequick fox today.", answer: "I saw the quick fox today."))
        XCTAssertNil(KeyboardTextLogic.acceptedProofreading(of: "I saw the quick fox.", answer: "I saw the lazy fox."))
    }

    private var keyboardView: KeyboardView!
    private var document: FakeDocument!
    private var spellChecker: FakeSpellChecker!
    private var controller: KeyboardTextController!

    private func type(_ text: String) {
        for character in text {
            controller.keyboardView(keyboardView, insert: String(character))
        }
    }

    func testSelectAllThenPinyinReplacesAllTextInChineseMode() {
        makeController(before: "hello ", after: "world")
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        controller.keyboardView(keyboardView, edit: .selectAll)
        XCTAssertTrue(keyboardView.selectAllActive)
        type("nihao")
        waitForDelayedEdits()
        // The old text is gone, and the letters wait in the Pinyin buffer as usual.
        XCTAssertEqual(document.text, "")
        XCTAssertEqual(controller.pinyinBuffer, "nihao")
        type(" ")
        XCTAssertEqual(document.text, "\u{4F60}\u{597D}")
    }

    func testSelectAllThenPinyinWithTheCursorAtTheEndInChineseMode() {
        makeController(before: "hello")
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        controller.keyboardView(keyboardView, edit: .selectAll)
        type("wo ")
        XCTAssertEqual(document.text, "\u{6211}")
    }

    func testSelectAllThenBackspaceDeletesAllTextInChineseMode() {
        makeController(before: "\u{4F60}\u{597D}", after: "\u{6211}")
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        controller.keyboardView(keyboardView, edit: .selectAll)
        controller.keyboardViewDeleteBackward(keyboardView)
        waitForDelayedEdits()
        XCTAssertEqual(document.text, "")
    }

    func testSelectAllThenCopyAndCutWorkInChineseMode() {
        makeController(before: "\u{4F60}\u{597D}", after: "\u{6211}")
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        controller.keyboardView(keyboardView, edit: .selectAll)
        controller.keyboardView(keyboardView, edit: .copy)
        XCTAssertEqual(UIPasteboard.general.string, "\u{4F60}\u{597D}\u{6211}")
        XCTAssertTrue(keyboardView.selectAllActive)
        controller.keyboardView(keyboardView, edit: .cut)
        waitForDelayedEdits()
        XCTAssertEqual(document.text, "")
    }

    func testSelectAllThenPasteReplacesAllTextInChineseMode() {
        makeController(before: "\u{4F60}\u{597D}")
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        UIPasteboard.general.string = "nihao"
        controller.keyboardView(keyboardView, edit: .selectAll)
        controller.keyboardView(keyboardView, edit: .paste)
        // Pasted text goes in as it is. It does not pass through the Pinyin buffer.
        XCTAssertEqual(document.text, "nihao")
        XCTAssertEqual(controller.pinyinBuffer, "")
    }

    func testAPickOfAShorterWordLeavesTheRestForANewSentence() {
        makeController(before: "")
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        type("wonihao")
        let candidates = PinyinEngine(dictionaryText: testDictionary).candidates(for: "wonihao")
        let shorter = candidates.firstIndex { $0.word == "\u{6211}" }!
        controller.keyboardView(keyboardView, didSelectCandidateAt: shorter)
        XCTAssertEqual(document.text, "\u{6211}")
        XCTAssertEqual(controller.pinyinBuffer, "nihao")
        type(" ")
        XCTAssertEqual(document.text, "\u{6211}\u{4F60}\u{597D}")
        XCTAssertEqual(controller.pinyinBuffer, "")
    }

    func testATapOnTheTypedPinyinTypesTheLettersAndSelectsNothing() {
        makeController(before: "\u{4F60}\u{597D}")
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        type("nihao")
        keyboardView.onSelectComposition()
        XCTAssertEqual(document.text, "\u{4F60}\u{597D}nihao")
        XCTAssertEqual(controller.pinyinBuffer, "")
        XCTAssertFalse(keyboardView.selectAllActive)
        // The next letter joins the text. It does not replace the text.
        type("w ")
        XCTAssertEqual(document.text, "\u{4F60}\u{597D}nihao\u{6211}")
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

    func testASpaceTypedInsideAWordIsRepaired() {
        makeController(before: "")
        type("th e ")
        XCTAssertEqual(document.text, "the ")
    }

    func testAJoinedWordKeepsTheCapitalOfItsFirstTypedLetter() {
        makeController(before: "")
        type("Th e ")
        XCTAssertEqual(document.text, "The ")
    }

    func testAMissingSpaceIsRepaired() {
        makeController(before: "")
        type("thequick ")
        XCTAssertEqual(document.text, "the quick ")
    }

    func testTheNextWordReadsTheTypedLettersOfTheWordBeforeIt() {
        makeController(before: "")
        type("teh cat ")
        XCTAssertEqual(document.text, "the cat ")
        // The second request holds the keys the person pressed, and the field holds "the".
        XCTAssertEqual(spellChecker.requests, ["|teh", "|teh cat"])
    }

    func testTwoWordsReadTogetherCanChangeTheFirstWord() {
        makeController(before: "")
        type("form teh ")
        XCTAssertEqual(document.text, "from the ")
    }

    func testBackspaceAfterAJoinBringsBackTheShownText() {
        makeController(before: "")
        type("th e ")
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "th e")
        type(" ")
        XCTAssertEqual(document.text, "th e ")
    }

    func testAKeptWordDoesNotStopTheCorrectionOfTheNextWord() {
        makeController(before: "")
        type("teh ")
        controller.keyboardViewDeleteBackward(keyboardView)
        type(" recieve ")
        XCTAssertEqual(document.text, "teh receive ")
    }

    func testTheCheckerGetsTheWordBeforeTheTypedTextAsContext() {
        makeController(before: "I will ")
        type("recieve ")
        XCTAssertEqual(document.text, "I will receive ")
        XCTAssertEqual(spellChecker.requests, ["will|recieve"])
    }

    func testAWordAfterACursorMoveIsReadAlone() {
        makeController(before: "")
        type("form ")
        controller.keyboardView(keyboardView, moveCursorBy: 0)
        type("teh ")
        // "form teh" together would become "from the". After a cursor move the keyboard does
        // not know that the person typed the two words one after the other.
        XCTAssertEqual(document.text, "form the ")
    }

    func testAWordAfterACursorMoveByTheAppIsReadAlone() {
        makeController(before: "form teh\n")
        type("form ")
        // The person taps right after the first "teh". The app moves the cursor, and the
        // keyboard only hears that the document changed.
        document.cursor = 8
        controller.documentDidChange()
        type(" ")
        XCTAssertEqual(document.text, "form the \nform ")
        XCTAssertEqual(spellChecker.requests.last, "form|teh")
    }

    func testTwoWordsReadTogetherCanBringBackTheTypedLetters() {
        makeController(before: "")
        spellChecker.corrections = ["fro": "for", "fro yo": "fro yo"]
        type("fro ")
        XCTAssertEqual(document.text, "for ")
        type("yo ")
        XCTAssertEqual(document.text, "fro yo ")
    }

    func testOneLetterAloneDoesNotGoToTheChecker() {
        makeController(before: "")
        type("x ")
        XCTAssertEqual(document.text, "x ")
        XCTAssertEqual(spellChecker.requests, [])
    }

    func testRestoringCapitals() {
        XCTAssertEqual(KeyboardTextLogic.restoringCapitals(in: "the", from: "Teh"), "The")
        XCTAssertEqual(KeyboardTextLogic.restoringCapitals(in: "the quick", from: "Thequick"), "The quick")
        XCTAssertEqual(KeyboardTextLogic.restoringCapitals(in: "from the", from: "form Teh"), "from The")
        XCTAssertEqual(KeyboardTextLogic.restoringCapitals(in: "i think i'm", from: "i thnik im"), "I think I'm")
        XCTAssertEqual(KeyboardTextLogic.restoringCapitals(in: "in", from: "in"), "in")
    }

    func testWordBeforeSpace() {
        XCTAssertEqual(KeyboardTextLogic.wordBeforeSpace(at: "I Will "), "will")
        XCTAssertEqual(KeyboardTextLogic.wordBeforeSpace(at: "end. "), "")
        XCTAssertEqual(KeyboardTextLogic.wordBeforeSpace(at: "will"), "")
        XCTAssertEqual(KeyboardTextLogic.wordBeforeSpace(at: ""), "")
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

    // MARK: A symbol or digit key in place of a letter

    func testASymbolKeyInPlaceOfTheFirstLetterIsRepaired() {
        makeController(before: "Hello ")
        spellChecker.corrections["[lease"] = "please"
        type("[lease ")
        XCTAssertEqual(document.text, "Hello please ")
        XCTAssertEqual(spellChecker.requests, ["hello|[lease"])
    }

    func testBackspaceBringsBackAWordWithASymbolKeyAndKeepsIt() {
        makeController(before: "Hello ")
        spellChecker.corrections["[lease"] = "please"
        type("[lease ")
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "Hello [lease")
        XCTAssertEqual(spellChecker.learned, ["[lease"])
        type(" ")
        XCTAssertEqual(document.text, "Hello [lease ")
    }

    func testAPunctuationKeyInPlaceOfTheFirstLetterIsRepaired() {
        // The semicolon, the comma and the period end a word, and each can also be a slip.
        for (typed, meant) in [(";ike", "like"), (",ore", "more"), (".ike", "like"), ("-lease", "please")] {
            makeController(before: "I ")
            spellChecker.corrections[typed] = meant
            type(typed + " ")
            XCTAssertEqual(document.text, "I \(meant) ")
            XCTAssertEqual(spellChecker.requests, ["i|\(typed)"])
        }
    }

    func testADigitKeyInPlaceOfALetterIsRepaired() {
        makeController(before: "")
        spellChecker.corrections = ["2hat": "what", "wh3n": "when", "sho2": "show"]
        type("2hat ")
        XCTAssertEqual(document.text, "what ")
        type("Wh3n ")
        XCTAssertEqual(document.text, "what When ")
        type("sho2.")
        XCTAssertEqual(document.text, "what When show.")
    }

    func testAWordAfterAPunctuationSlipIsStillReadWithTheWordBeforeIt() {
        makeController(before: "")
        spellChecker.corrections[";ike"] = "like"
        type("tell ;ike ")
        XCTAssertEqual(document.text, "tell like ")
        // The semicolon ends a word, and it does not end the reading of the two words together.
        XCTAssertEqual(spellChecker.requests, ["|tell", "|tell ;ike"])
        type("yuo ")
        XCTAssertEqual(spellChecker.requests.last, "tell|;ike yuo")
    }

    func testAWordAfterABracketSlipIsReadWithTheKeysThePersonPressed() {
        makeController(before: "")
        spellChecker.corrections["[lease"] = "please"
        type("[lease send ")
        XCTAssertEqual(document.text, "please send ")
        XCTAssertEqual(spellChecker.requests, ["|[lease", "|[lease send"])
    }

    func testASymbolTypedOnPurposeStaysWhenTheCheckerReadsTheTextAsTyped() {
        for typed in ["[note", ".net", ",and", "2nd", "mp3"] {
            makeController(before: "see ")
            type(typed + " ")
            XCTAssertEqual(document.text, "see \(typed) ")
            XCTAssertEqual(spellChecker.requests, ["see|\(typed)"])
        }
    }

    func testAWordAfterABracketIsStillCorrected() {
        makeController(before: "")
        spellChecker.corrections["[teh"] = "[the"
        type("[teh ")
        XCTAssertEqual(document.text, "[the ")
    }

    func testAWordWithACapitalAfterABracketIsCorrectedWithoutTheBracket() {
        // The capital shows that the person typed the bracket on purpose.
        makeController(before: "")
        type("[Teh ")
        XCTAssertEqual(document.text, "[The ")
        XCTAssertEqual(spellChecker.requests, ["|teh"])
    }

    func testAKeptWordStaysAsTypedAfterASymbolKey() {
        makeController(before: "")
        spellChecker.corrections["[teh"] = "[the"
        type("teh ")
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(spellChecker.learned, ["teh"])
        type(" [teh ")
        XCTAssertEqual(document.text, "teh [teh ")
    }

    func testTextWithASymbolThatIsNotProseDoesNotGoToTheChecker() {
        // More than one symbol or digit, one letter only, a capital after a digit, a symbol key
        // that is not beside a letter, and a word inside an address.
        for text in ["abc123", "x86", "[a", "4k", "[;ike", "2Hat", "#teh", "te_h", "name@[lease", "www.[lease", "a;ike"] {
            // The field already holds the text, and the space asks for a correction of its end.
            makeController(before: text)
            spellChecker.corrections = ["[lease": "please", ";ike": "like", "teh": "the"]
            type(" ")
            XCTAssertEqual(document.text, text + " ", text)
            XCTAssertEqual(spellChecker.requests, [], text)
        }
    }

    func testASymbolSlipAtTheStartOfASentenceGetsTheCapital() {
        makeController(before: "")
        document.autocapitalizationType = .sentences
        spellChecker.corrections["[lease"] = "please"
        type("[lease ")
        XCTAssertEqual(document.text, "Please ")
        // The reading of the two words together keeps that capital.
        type("send ")
        XCTAssertEqual(document.text, "Please send ")
        type("it. ")
        type("[lease ")
        XCTAssertEqual(document.text, "Please send it. Please ")
    }

    func testASymbolSlipInsideASentenceGetsNoCapital() {
        makeController(before: "Then ")
        document.autocapitalizationType = .sentences
        spellChecker.corrections["[lease"] = "please"
        type("[lease ")
        XCTAssertEqual(document.text, "Then please ")
    }

    func testCorrectableWordTakesOneSymbolKeyBesideALetter() {
        XCTAssertEqual(KeyboardTextLogic.correctableWord(before: "say [lease"), "[lease")
        XCTAssertEqual(KeyboardTextLogic.correctableWord(before: "say ;ike"), ";ike")
        XCTAssertEqual(KeyboardTextLogic.correctableWord(before: "say ,ore"), ",ore")
        XCTAssertEqual(KeyboardTextLogic.correctableWord(before: ".ike"), ".ike")
        XCTAssertEqual(KeyboardTextLogic.correctableWord(before: "-lease"), "-lease")
        XCTAssertEqual(KeyboardTextLogic.correctableWord(before: "2hat"), "2hat")
        XCTAssertEqual(KeyboardTextLogic.correctableWord(before: "say Wh3n"), "Wh3n")
        XCTAssertEqual(KeyboardTextLogic.correctableWord(before: "hel["), "hel[")
        XCTAssertEqual(KeyboardTextLogic.correctableWord(before: "(2hat"), "2hat")
        XCTAssertEqual(KeyboardTextLogic.correctableWord(before: "don'5"), "don'5")
        // One symbol key at most, with two letters or more.
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "[[lease"))
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: ";lea5e"))
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "a1b2"))
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "[a"))
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "say ;"))
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "24"))
        // A punctuation key counts as a slip only in front of a word, after a space.
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "a;ike"))
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "e.g"))
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "well-known"))
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "ike;"))
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "[;ike"))
        // A capital right after a symbol key: the word starts after the key, and only an
        // opening bracket may stand right before a word.
        XCTAssertEqual(KeyboardTextLogic.correctableWord(before: "[Teh"), "Teh")
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: ";Ike"))
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "2Hat"))
        // The rules for text that is not prose still hold.
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "[LEase"))
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "2hAT"))
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "name@2hat"))
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "path/[lease"))
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "#2hat"))
    }

    func testCapitalsWithASymbolKeyInTheTypedWord() {
        XCTAssertEqual(KeyboardTextLogic.restoringCapitals(in: "hello please", from: "Hello [lease"), "Hello please")
        XCTAssertEqual(KeyboardTextLogic.restoringCapitals(in: "when", from: "Wh3n"), "When")
        XCTAssertEqual(KeyboardTextLogic.restoringCapitals(in: "[note", from: "[note"), "[note")
        func capitalized(_ corrected: String, _ typed: String, after before: String) -> String {
            KeyboardTextLogic.capitalizingRepairedFirstLetters(
                in: corrected, from: typed, textBefore: before, type: .sentences)
        }
        XCTAssertEqual(capitalized("please", "[lease", after: ""), "Please")
        XCTAssertEqual(capitalized("please", "[lease", after: "Done. "), "Please")
        XCTAssertEqual(capitalized("please", "[lease", after: "then "), "please")
        XCTAssertEqual(capitalized("please send", "[lease send", after: ""), "Please send")
        XCTAssertEqual(capitalized("tell like", "tell ;ike", after: ""), "tell like")
        // A symbol that stays in the text, and a word typed with its own first letter, do not change.
        XCTAssertEqual(capitalized("[note", "[note", after: ""), "[note")
        XCTAssertEqual(capitalized("the", "teh", after: ""), "the")
        XCTAssertEqual(
            KeyboardTextLogic.capitalizingRepairedFirstLetters(in: "please", from: "[lease", textBefore: "", type: .none),
            "please")
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

    func testALongRunOfLettersThatEndsOutsideASyllableIsCutAtOnce() {
        // A search that tries every cut of these 79 letters would not finish.
        let letters = String(repeating: "an", count: 39) + "z"
        let cut = engine.segment(letters)
        XCTAssertEqual(cut.syllables.count, 39)
        XCTAssertEqual(cut.remainder, "z")
    }

    func testTheCutGoesBackWhenTheLongestSyllableLeavesLettersThatDoNotFit() {
        let small = PinyinEngine(dictionaryText: "xi\t\u{897F}\t10\nxian\t\u{5148}\t9\nang\t\u{6602}\t8")
        // "xian" leaves "g", which is not a syllable, so the cut is "xi" and "ang".
        XCTAssertEqual(small.segment("xiang").syllables, ["xi", "ang"])
        XCTAssertEqual(small.segment("xiang").remainder, "")
        XCTAssertEqual(engine.segment("xianguo").syllables, ["xian", "guo"])
        XCTAssertEqual(engine.segment("xiani").syllables, ["xian"])
        XCTAssertEqual(engine.segment("xiani").remainder, "i")
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

    func testAnIPadGetsTheWideLayoutInPortraitAndTheSplitLayoutInLandscape() {
        // 744 and 1133 points are the two widths of the iPad mini, the iPad this keyboard is
        // made for. The other widths belong to larger iPads, which follow the same rule.
        for width in [744, 820, 1032] as [CGFloat] {
            XCTAssertEqual(KeyboardView.style(forWidth: width, device: .pad, landscape: false), .wide)
        }
        for width in [1133, 1180, 1376] as [CGFloat] {
            XCTAssertEqual(KeyboardView.style(forWidth: width, device: .pad, landscape: true), .split)
        }
        // A floating or very narrow keyboard keeps the compact layout.
        XCTAssertEqual(KeyboardView.style(forWidth: 320, device: .pad, landscape: true), .compact)
    }

    func testTheFirstRowOfAnIPadLeavesTheCornerOfTheSystemButtons() {
        XCTAssertEqual(KeyboardView.shortcutButtonsWidth(style: .wide, device: .pad), 140)
        XCTAssertEqual(KeyboardView.shortcutButtonsWidth(style: .split, device: .pad), 140)
        XCTAssertEqual(KeyboardView.shortcutButtonsWidth(style: .compact, device: .pad), 0)
        for style in [LayoutStyle.compact, .wide, .split] {
            XCTAssertEqual(KeyboardView.shortcutButtonsWidth(style: style, device: .phone), 0)
        }
        // Three keys of 100 points, then the empty middle, then one key.
        let row = [0, 100, 200, 300, 700].map { CGRect(x: CGFloat($0), y: 0, width: 100, height: 40) }
        let moved = KeyboardView.cells(row, leftGroupCount: 3, movedRightBy: 150)
        XCTAssertEqual(moved[0].minX, 150, accuracy: 0.001)
        XCTAssertEqual(moved[0].width, 50, accuracy: 0.001)
        XCTAssertEqual(moved[2].maxX, 300, accuracy: 0.001)
        XCTAssertEqual(moved[3], row[3])
        XCTAssertEqual(moved[4], row[4])
        // Without a reserve, as on an iPhone, every cell stays.
        XCTAssertEqual(KeyboardView.cells(row, leftGroupCount: 3, movedRightBy: 0), row)
    }

    func testTheIPadRulesDoNotChangeTheIPhoneLayouts() {
        // The iPhone rules read the width only, so the screen's orientation changes nothing.
        for landscape in [false, true] {
            XCTAssertEqual(KeyboardView.style(forWidth: 466, device: .phone, landscape: landscape), .compact)
            XCTAssertEqual(KeyboardView.style(forWidth: 669, device: .phone, landscape: landscape), .wide)
            XCTAssertEqual(KeyboardView.style(forWidth: 678, device: .phone, landscape: landscape), .wide)
            XCTAssertEqual(KeyboardView.style(forWidth: 951, device: .phone, landscape: landscape), .split)
        }
        XCTAssertNil(KeyboardView.splitGap(forWidth: 951, device: .phone))
        // The heights of the four iPhone Duo keyboards, as they were before the iPad rules.
        XCTAssertEqual(KeyboardView.preferredHeight(forWidth: 669, compactHeight: false, device: .phone, landscape: false), 289.1, accuracy: 0.1)
        XCTAssertEqual(KeyboardView.preferredHeight(forWidth: 951, compactHeight: false, device: .phone, landscape: true), 290.6, accuracy: 0.1)
    }

    func testTheSplitKeysOfAnIPadStayWithinReachOfAThumb() {
        // On an iPad mini in landscape the keys stop at 52 points and the middle takes the rest.
        let gap = KeyboardLayout.padSplitGap(forWidth: 1133)
        XCTAssertEqual(1133 / (14.5 + gap), 52, accuracy: 0.001)
        let layout = KeyboardLayout.make(style: .split, layer: .letters, showsGlobe: true, splitGap: gap)
        XCTAssertEqual(layout.units, 14.5 + gap, accuracy: 0.001)
        for row in layout.rows {
            XCTAssertEqual(row.reduce(0) { $0 + $1.weight }, 14.5 + gap, accuracy: 0.001)
        }
        // A narrow split keyboard keeps the middle of the layout file.
        XCTAssertEqual(KeyboardLayout.padSplitGap(forWidth: 951), 6)
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
