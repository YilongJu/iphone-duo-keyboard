import UIKit
import XCTest

@testable import DuoKeyboard

/// Space removal and space restore, typed through the controller into a text field in memory.
///
/// A mark is a punctuation character of `KeyboardTextLogic.marks`. Space removal deletes the one
/// space between a word and a mark as the mark is typed. Space restore puts that space back
/// when the next key shows that the person wanted the space.
@MainActor
final class SpaceBeforeMarkTests: XCTestCase {
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

    private func makeChineseController(before: String, after: String = "") {
        makeController(before: before, after: after)
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
    }

    private func type(_ text: String) {
        for character in text {
            controller.keyboardView(keyboardView, insert: String(character))
        }
    }

    private func delete() {
        controller.keyboardViewDeleteBackward(keyboardView)
    }

    /// The controller deletes the text after the cursor in a delayed step, so the test waits.
    private func waitForDelayedEdits() {
        RunLoop.current.run(until: Date().addingTimeInterval(0.6))
    }

    // MARK: Space removal

    func testEachASCIIMarkAfterAWordAndOneSpaceLosesTheSpace() {
        for mark in [",", ".", "?", "!", ";", ":", ")", "]", "}"] {
            makeController(before: "word ")
            type(mark)
            XCTAssertEqual(document.text, "word" + mark, mark)
        }
    }

    func testAMarkRightAfterAWordIsTypedAsBefore() {
        for mark in [",", ".", "?", "!", ";", ":", ")", "]", "}"] {
            makeController(before: "word")
            type(mark)
            XCTAssertEqual(document.text, "word" + mark, mark)
        }
    }

    func testACharacterThatIsNotAMarkKeepsTheSpace() {
        // A quotation mark after a space usually opens a quotation. The others open a group or
        // stand between two words.
        for text in ["\"", "'", "%", "(", "[", "{", "-", "/", "@", "&", "\u{2026}", "\u{201C}", "\u{2018}"] {
            makeController(before: "word ")
            type(text)
            XCTAssertEqual(document.text, "word " + text, text)
        }
    }

    func testEachFullWidthMarkInChineseModeLosesTheSpace() {
        // The key, and the full-width mark that the key types in Chinese mode.
        let marks = [
            (",", "\u{FF0C}"), (".", "\u{3002}"), ("?", "\u{FF1F}"), ("!", "\u{FF01}"), (":", "\u{FF1A}"),
            (";", "\u{FF1B}"), (")", "\u{FF09}"), (">", "\u{300B}"), ("\\", "\u{3001}"),
        ]
        for (key, mark) in marks {
            makeChineseController(before: "word ")
            type(key)
            XCTAssertEqual(document.text, "word" + mark, key)
            // A Chinese character before the space counts as a letter.
            makeChineseController(before: "\u{4F60}\u{597D} ")
            type(key)
            XCTAssertEqual(document.text, "\u{4F60}\u{597D}" + mark, key)
        }
    }

    func testAnOpeningFullWidthFormInChineseModeKeepsTheSpace() {
        for (key, opening) in [("(", "\u{FF08}"), ("<", "\u{300A}"), ("\"", "\u{201C}"), ("'", "\u{2018}")] {
            makeChineseController(before: "word ")
            type(key)
            XCTAssertEqual(document.text, "word " + opening, key)
        }
    }

    func testAClosingQuotationMarkInChineseModeLosesTheSpace() {
        makeChineseController(before: "")
        type("\"wo ")
        XCTAssertEqual(document.text, "\u{201C}\u{6211}")
        type(" ")
        XCTAssertEqual(document.text, "\u{201C}\u{6211} ")
        type("\"")
        XCTAssertEqual(document.text, "\u{201C}\u{6211}\u{201D}")

        makeChineseController(before: "")
        type("'wo ")
        type(" ")
        XCTAssertEqual(document.text, "\u{2018}\u{6211} ")
        type("'")
        XCTAssertEqual(document.text, "\u{2018}\u{6211}\u{2019}")
    }

    func testAnASCIIMarkInChineseModeLosesTheSpace() {
        // Chinese mode has no full-width form for these two keys.
        for mark in ["]", "}"] {
            makeChineseController(before: "word ")
            type(mark)
            XCTAssertEqual(document.text, "word" + mark, mark)
        }
    }

    func testAMarkThatEndsAPinyinCompositionKeepsTheSpaceBeforeTheChineseWord() {
        makeChineseController(before: "word ")
        type("nihao,")
        XCTAssertEqual(document.text, "word \u{4F60}\u{597D}\u{FF0C}")
    }

    func testTwoSpacesATabAndALineBreakKeepTheTextAsTyped() {
        for before in ["word  ", "word\t", "word\n", "word\n ", "word \t", "word\t ", " ", "", "word\u{00A0}"] {
            for mark in [",", ".", ")"] {
                makeController(before: before)
                type(mark)
                XCTAssertEqual(document.text, before + mark, before.debugDescription)
            }
        }
    }

    func testASpaceAfterAnOpeningBracketAnEmojiOrAMarkStays() {
        for before in ["( ", "[ ", "{ ", "say \u{201C} ", "ok \u{1F600} ", "end. ", "one, ", "what? ", "a - ", "50% "] {
            for mark in [",", ".", ")"] {
                makeController(before: before)
                type(mark)
                XCTAssertEqual(document.text, before + mark, before)
            }
        }
    }

    func testASpaceAfterAClosingBracketAClosingQuoteOrADigitIsRemoved() {
        let starts = [
            "(word)", "[a]", "{a}", "\"word\"", "'word'", "\u{201C}word\u{201D}", "\u{2018}word\u{2019}", "room 5",
            "caf\u{00E9}",
        ]
        for start in starts {
            for mark in [",", ".", ")"] {
                makeController(before: start + " ")
                type(mark)
                XCTAssertEqual(document.text, start + mark, start)
            }
        }
    }

    func testAFieldWithoutAutocorrectionKeepsTheSpace() {
        for mark in [",", ".", "?", "!", ";", ":", ")", "]", "}"] {
            makeController(before: "word ")
            document.allowsAutocorrection = false
            type(mark)
            XCTAssertEqual(document.text, "word " + mark, mark)
        }
        makeChineseController(before: "word ")
        document.allowsAutocorrection = false
        type(",")
        XCTAssertEqual(document.text, "word \u{FF0C}")
    }

    func testAMarkTypedOverASelectionOfTheAppKeepsTheSpace() {
        // The typed mark replaces the selection, so the delete of the space must not run.
        makeController(before: "word ")
        document.selectedText = "x"
        type(",")
        XCTAssertEqual(document.text, "word ,")
    }

    // MARK: A mark in the middle of a sentence

    func testAMarkBeforeAWordPutsTheSpaceAfterTheMark() {
        for after in ["world", "2nd half", "\u{4E16}\u{754C}"] {
            makeController(before: "hello ", after: after)
            type(",")
            XCTAssertEqual(document.text, "hello, " + after, after)
            XCTAssertEqual(document.textBeforeCursor, "hello, ", after)
        }
        makeController(before: "(hello ", after: "world")
        type(")")
        XCTAssertEqual(document.text, "(hello) world")
        XCTAssertEqual(document.textBeforeCursor, "(hello) ")
    }

    func testAMarkBeforeTextThatDoesNotStartAWordOnlyLosesTheSpace() {
        for after in [" world", "\nworld", ")", ". Then", "\"word\""] {
            makeController(before: "hello ", after: after)
            type(",")
            XCTAssertEqual(document.text, "hello," + after, after.debugDescription)
            XCTAssertEqual(document.textBeforeCursor, "hello,", after.debugDescription)
        }
    }

    func testTheKeyAfterAMarkInTheMiddleOfASentenceDoesNotRestoreTheSpace() {
        makeController(before: "hello ", after: "world")
        type(".e")
        XCTAssertEqual(document.text, "hello. eworld")
        XCTAssertEqual(document.textBeforeCursor, "hello. e")
    }

    func testAMarkInTheMiddleOfASentenceInChineseMode() {
        makeChineseController(before: "\u{4F60}\u{597D} ", after: "\u{4E16}\u{754C}")
        type(",")
        XCTAssertEqual(document.text, "\u{4F60}\u{597D}\u{FF0C} \u{4E16}\u{754C}")
        XCTAssertEqual(document.textBeforeCursor, "\u{4F60}\u{597D}\u{FF0C} ")
    }

    // MARK: Space restore

    func testALetterOrADigitAfterTheMarkRestoresTheSpace() {
        // The typed text, and the field after its mark.
        let texts = [
            ("open .env", "open."), ("is .5", "is."), ("word :D", "word:"), ("word ;p", "word;"),
            ("color !important", "color!"), ("word ,o", "word,"), ("word ?x", "word?"), ("a )b", "a)"),
            ("a ]b", "a]"), ("a }b", "a}"), ("room 5 .5", "room 5."), ("word .\u{00E9}", "word."),
        ]
        for (text, afterTheMark) in texts {
            makeController(before: "")
            type(String(text.dropLast()))
            XCTAssertEqual(document.text, afterTheMark, text)
            type(String(text.suffix(1)))
            XCTAssertEqual(document.text, text, text)
        }
    }

    func testAnEmoticonAfterAColonOrASemicolonRestoresTheSpace() {
        for mark in [":", ";"] {
            for next in [")", "(", "-", "'", "/", "\\", "|", "*", "]"] {
                makeController(before: "word ")
                type(mark)
                XCTAssertEqual(document.text, "word" + mark)
                type(next)
                XCTAssertEqual(document.text, "word " + mark + next, mark + next)
            }
        }
        makeController(before: "")
        type("word :)")
        XCTAssertEqual(document.text, "word :)")
        makeController(before: "")
        type("word ;-)")
        XCTAssertEqual(document.text, "word ;-)")
    }

    func testAnEqualsSignAfterThreeMarksAndASlashAfterAPeriodRestoreTheSpace() {
        for text in ["x !=", "x :=", "x ?=", "open ./"] {
            makeController(before: "")
            type(String(text.dropLast()))
            XCTAssertEqual(document.text, String(text.dropLast(3)) + String(text.dropLast().suffix(1)), text)
            type(String(text.suffix(1)))
            XCTAssertEqual(document.text, text, text)
        }
    }

    func testAKeyThatDoesNotShowAWantedSpaceLeavesTheSpaceRemoved() {
        // The typed text, and the text of the field.
        let texts = [
            ("wait ...", "wait..."), ("word ,,", "word,,"), ("what ?!", "what?!"), ("word ,=", "word,="),
            ("word .)", "word.)"), ("word ,-", "word,-"), ("word ?/", "word?/"), ("word !)", "word!)"),
            ("word ;=", "word;="), ("word .\"", "word.\""), ("word , ", "word, "), ("word .\n", "word.\n"),
            ("a )=", "a)="),
        ]
        for (text, expected) in texts {
            makeController(before: "")
            type(text)
            XCTAssertEqual(document.text, expected, text)
        }
    }

    func testAFullWidthMarkGetsNoSpaceRestore() {
        makeChineseController(before: "word ")
        type(",")
        XCTAssertEqual(document.text, "word\u{FF0C}")
        // The digit goes into the field, because the Pinyin buffer is empty.
        type("5")
        XCTAssertEqual(document.text, "word\u{FF0C}5")
    }

    func testASpaceRestoreHappensOnlyRightAfterTheSpaceRemoval() {
        makeController(before: "word ")
        type(",")
        controller.keyboardView(keyboardView, moveCursorBy: 0)
        type("o")
        XCTAssertEqual(document.text, "word,o")

        makeController(before: "word ")
        type(",,")
        type("o")
        XCTAssertEqual(document.text, "word,,o")
    }

    func testASymbolSlipAfterASpaceIsReadAsBeforeTheSpaceRemoval() {
        makeController(before: "")
        spellChecker.corrections[";ike"] = "like"
        type("tell ;")
        XCTAssertEqual(document.text, "tell;")
        type("ike ")
        XCTAssertEqual(document.text, "tell like ")
        XCTAssertEqual(spellChecker.requests, ["|tell", "|tell ;ike"])
        XCTAssertEqual(spellChecker.textsBefore, ["", ""])
        type("yuo ")
        XCTAssertEqual(spellChecker.requests.last, "tell|;ike yuo")
    }

    func testEachSymbolSlipKeyAfterAWordInTheFieldIsReadAsBefore() {
        for (typed, meant) in [(";ike", "like"), (",ore", "more"), (".ike", "like")] {
            makeController(before: "I ")
            spellChecker.corrections[typed] = meant
            type(typed + " ")
            XCTAssertEqual(document.text, "I \(meant) ", typed)
            XCTAssertEqual(spellChecker.requests, ["i|\(typed)"], typed)
            XCTAssertEqual(spellChecker.textsBefore, ["I "], typed)
        }
    }

    func testASymbolSlipAfterACorrectedWordIsReadWithTheTypedLetters() {
        makeController(before: "")
        spellChecker.corrections[";ike"] = "like"
        type("teh ;ike ")
        XCTAssertEqual(document.text, "the like ")
        XCTAssertEqual(spellChecker.requests, ["|teh", "|teh ;ike"])
    }

    // MARK: The delete key

    func testDeleteRightAfterASpaceRemovalBringsTheSpaceBackAndTheNextMarkStays() {
        for mark in [",", ".", "?", "!", ";", ":", ")", "]", "}"] {
            makeController(before: "word ")
            type(mark)
            XCTAssertEqual(document.text, "word" + mark, mark)
            delete()
            XCTAssertEqual(document.text, "word ", mark)
            XCTAssertEqual(keyboardView.spaceCaption, "Kept the space", mark)
            type(mark)
            XCTAssertEqual(document.text, "word " + mark, mark)
            // The kept mark is plain text: the next key and the next delete do not move the space.
            type("x")
            XCTAssertEqual(document.text, "word " + mark + "x", mark)
            delete()
            delete()
            XCTAssertEqual(document.text, "word ", mark)
        }
    }

    func testAnotherMarkIsAlsoKeptAfterTheSpaceCameBack() {
        makeController(before: "word ")
        type(",")
        delete()
        type(".")
        XCTAssertEqual(document.text, "word .")
    }

    func testTheSpaceIsKeptForTheNextKeyOnly() {
        makeController(before: "word ")
        type(",")
        delete()
        XCTAssertEqual(document.text, "word ")
        type("x")
        delete()
        XCTAssertEqual(document.text, "word ")
        type(",")
        XCTAssertEqual(document.text, "word,")
    }

    func testACursorMoveAfterTheSpaceCameBackEndsTheKeptSpace() {
        makeController(before: "word ")
        type(",")
        delete()
        controller.keyboardView(keyboardView, moveCursorBy: 0)
        type(",")
        XCTAssertEqual(document.text, "word,")

        makeController(before: "ab word ")
        type(",")
        delete()
        // The person taps in the app at another place and then at the end again.
        document.cursor = 2
        controller.documentDidChange()
        document.cursor = document.text.utf16.count
        controller.documentDidChange()
        type(",")
        XCTAssertEqual(document.text, "ab word,")
    }

    func testDeleteAfterASpaceRestoreIsAPlainDelete() {
        makeController(before: "word ")
        type(",o")
        XCTAssertEqual(document.text, "word ,o")
        delete()
        XCTAssertEqual(document.text, "word ,")
        delete()
        XCTAssertEqual(document.text, "word ")
        XCTAssertNil(keyboardView.spaceCaption)
    }

    func testDeleteAfterAnotherKeyIsAPlainDelete() {
        makeController(before: "word ")
        type(", ")
        XCTAssertEqual(document.text, "word, ")
        delete()
        XCTAssertEqual(document.text, "word,")
        delete()
        XCTAssertEqual(document.text, "word")
        XCTAssertNil(keyboardView.spaceCaption)
    }

    func testDeleteAfterACursorMoveOrAnEditCommandIsAPlainDelete() {
        makeController(before: "word ")
        type(",")
        controller.keyboardView(keyboardView, moveCursorBy: 0)
        delete()
        XCTAssertEqual(document.text, "word")

        makeController(before: "word ")
        type(",")
        controller.keyboardView(keyboardView, edit: .lineEnd)
        delete()
        XCTAssertEqual(document.text, "word")

        makeController(before: "word ")
        type(",")
        UIPasteboard.general.string = "!"
        controller.keyboardView(keyboardView, edit: .paste)
        XCTAssertEqual(document.text, "word,!")
        delete()
        XCTAssertEqual(document.text, "word,")
        delete()
        XCTAssertEqual(document.text, "word")
    }

    func testDeleteAfterACursorMoveByTheAppIsAPlainDelete() {
        makeController(before: "ab word ")
        type(",")
        XCTAssertEqual(document.text, "ab word,")
        document.cursor = 2
        controller.documentDidChange()
        delete()
        XCTAssertEqual(document.text, "a word,")

        // The person taps at another place and then right after the mark again.
        makeController(before: "ab word ")
        type(",")
        document.cursor = 2
        controller.documentDidChange()
        document.cursor = document.text.utf16.count
        controller.documentDidChange()
        delete()
        XCTAssertEqual(document.text, "ab word")
    }

    func testDeleteAfterATextChangeByTheAppIsAPlainDelete() {
        makeController(before: "word ")
        type(",")
        // The app changes the text and does not tell the keyboard.
        document.text = "other,"
        document.cursor = 6
        delete()
        XCTAssertEqual(document.text, "other")
    }

    func testASelectionOfTheAppEndsTheStateOfTheSpaceRemoval() {
        // Delete acts on the selection. The field in memory deletes one character.
        makeController(before: "hello ", after: "world")
        type(",")
        XCTAssertEqual(document.text, "hello, world")
        document.selectedText = "world"
        delete()
        XCTAssertEqual(document.text, "hello,world")
        XCTAssertNil(keyboardView.spaceCaption)

        makeController(before: "word ")
        type(",")
        document.selectedText = "x"
        type("o")
        XCTAssertEqual(document.text, "word,o")

        makeController(before: "word ")
        type(",")
        delete()
        XCTAssertEqual(document.text, "word ")
        document.selectedText = "x"
        controller.documentDidChange()
        document.selectedText = nil
        controller.documentDidChange()
        type(",")
        XCTAssertEqual(document.text, "word,")
    }

    func testDeleteAfterACandidateChoiceIsAPlainDelete() {
        makeChineseController(before: "word ")
        type(",")
        XCTAssertEqual(document.text, "word\u{FF0C}")
        controller.keyboardView(keyboardView, didSelectCandidateAt: 0)
        delete()
        XCTAssertEqual(document.text, "word")
    }

    func testDeleteBringsTheSpaceBackInChineseMode() {
        makeChineseController(before: "word ")
        type(",")
        delete()
        XCTAssertEqual(document.text, "word ")
        XCTAssertEqual(keyboardView.spaceCaption, "Kept the space")
        type(",")
        XCTAssertEqual(document.text, "word \u{FF0C}")
    }

    func testDeleteAfterAMarkInTheMiddleOfASentenceBringsTheTextBack() {
        makeController(before: "hello ", after: "world")
        type(",")
        XCTAssertEqual(document.text, "hello, world")
        delete()
        XCTAssertEqual(document.text, "hello world")
        XCTAssertEqual(document.textBeforeCursor, "hello ")
        XCTAssertEqual(keyboardView.spaceCaption, "Kept the space")
        type(",")
        XCTAssertEqual(document.text, "hello ,world")
        XCTAssertEqual(document.textBeforeCursor, "hello ,")
    }

    // MARK: The other typing rules

    func testACorrectionAtTheSpaceAndThenAMark() {
        makeController(before: "")
        type("teh ,")
        XCTAssertEqual(document.text, "the,")
        XCTAssertEqual(spellChecker.requests, ["|teh"])
        // Delete brings the space back. The correction of the word stays.
        delete()
        XCTAssertEqual(document.text, "the ")
        XCTAssertEqual(spellChecker.learned, [])
    }

    func testAMarkRightAfterATypoStillCorrectsTheWord() {
        makeController(before: "")
        type("teh,")
        XCTAssertEqual(document.text, "the,")
        // The mark followed the word, so delete brings the typed word back as before.
        delete()
        XCTAssertEqual(document.text, "teh")
        XCTAssertEqual(spellChecker.learned, ["teh"])
    }

    func testAMarkAfterTheDoubleSpacePeriodKeepsItsSpace() {
        makeController(before: "word")
        type("  ")
        XCTAssertEqual(document.text, "word. ")
        type(",")
        XCTAssertEqual(document.text, "word. ,")
    }

    func testTwoSpacesAfterASpaceRemovalDoNotTypeAPeriod() {
        makeController(before: "")
        type("word ,  ")
        XCTAssertEqual(document.text, "word,  ")
    }

    func testTheSecondSpaceAfterTheSpaceCameBackDoesNotTypeAPeriod() {
        makeController(before: "")
        type("word ,")
        delete()
        type(" ")
        XCTAssertEqual(document.text, "word  ")
    }

    func testAPeriodAfterASpaceStillGivesACapitalAfterTheNextSpace() {
        makeController(before: "")
        document.autocapitalizationType = .sentences
        type("word .")
        XCTAssertEqual(document.text, "word.")
        XCTAssertEqual(keyboardView.shiftState, .off)
        type(" ")
        XCTAssertEqual(document.text, "word. ")
        XCTAssertEqual(keyboardView.shiftState, .on)
        XCTAssertTrue(keyboardView.shiftIsAutomatic)
    }

    func testAMarkAfterASpaceStartsTheProofreadingOfTheSentence() async {
        makeController(before: "")
        let proofreader = FakeProofreader()
        proofreader.answers = ["I came form the office,": "I came from the office,"]
        controller.proofreader = proofreader
        type("I came form the office ,")
        await controller.proofreadTask?.value
        XCTAssertEqual(document.text, "I came form the office,")
        XCTAssertEqual(proofreader.requests, ["I came form the office,"])
        controller.keyboardView(keyboardView, didSelectCandidateAt: 0)
        XCTAssertEqual(document.text, "I came from the office,")
    }

    func testAMarkThatReplacesAllTextIsTypedOnce() {
        // The cursor is at the end of the text, so the replacement needs no cursor move.
        makeController(before: "word ")
        controller.keyboardView(keyboardView, edit: .selectAll)
        type(",")
        XCTAssertEqual(document.text, ",")

        makeController(before: "hello ", after: "world")
        controller.keyboardView(keyboardView, edit: .selectAll)
        type(",")
        waitForDelayedEdits()
        XCTAssertEqual(document.text, ",")
    }

    func testCharactersThatWaitForAReplacementGetSpaceRemovalOnce() {
        makeController(before: "hello ", after: "world")
        controller.keyboardView(keyboardView, edit: .selectAll)
        // The first character starts the replacement, and the others wait for its delete.
        type("a ,")
        waitForDelayedEdits()
        XCTAssertEqual(document.text, "a,")
        delete()
        XCTAssertEqual(document.text, "a ")

        makeController(before: "hello ", after: "world")
        controller.keyboardView(keyboardView, edit: .selectAll)
        type("a ,b")
        waitForDelayedEdits()
        XCTAssertEqual(document.text, "a ,b")
    }

    func testSelectAllAfterASpaceRemovalReplacesTheTextAsBefore() {
        makeController(before: "word ")
        type(",")
        controller.keyboardView(keyboardView, edit: .selectAll)
        delete()
        XCTAssertEqual(document.text, "")
        type("word ,")
        XCTAssertEqual(document.text, "word,")
    }
}

/// The pure rules of space removal and space restore in `KeyboardTextLogic`.
final class SpaceRemovalRuleTests: XCTestCase {
    private func removal(
        _ text: String, before: String, after: String = "", allowsAutocorrection: Bool = true
    ) -> KeyboardTextLogic.SpaceRemovalForm? {
        KeyboardTextLogic.spaceRemoval(
            typing: text, before: before, after: after, allowsAutocorrection: allowsAutocorrection)
    }

    func testTheMarkListHoldsTheClosingFormsAndNoOpeningForm() {
        XCTAssertEqual(KeyboardTextLogic.asciiMarks, Set(",.?!;:)]}"))
        XCTAssertEqual(
            KeyboardTextLogic.chineseMarks,
            Set("\u{FF0C}\u{3002}\u{FF1F}\u{FF01}\u{FF1B}\u{FF1A}\u{FF09}\u{3001}\u{300B}\u{201D}\u{2019}"))
        XCTAssertEqual(KeyboardTextLogic.marks.count, 20)
        for other in "\"'%([{<>-/@#&*=+_~\u{2026}\u{FF08}\u{300A}\u{201C}\u{2018} \n" {
            XCTAssertFalse(KeyboardTextLogic.marks.contains(other), String(other))
        }
    }

    func testEveryMarkAfterAWordAndOneSpaceGetsSpaceRemoval() {
        for mark in KeyboardTextLogic.marks {
            XCTAssertEqual(removal(String(mark), before: "word "), .markOnly, String(mark))
            XCTAssertNil(removal(String(mark), before: "word"), String(mark))
        }
    }

    func testTextThatIsNotOneMarkGetsNoSpaceRemoval() {
        for text in ["\"", "'", "%", "(", "a", "5", " ", "\n", "", ",,", ", ", "\u{FF08}", "\u{201C}", "\u{2018}"] {
            XCTAssertNil(removal(text, before: "word "), text.debugDescription)
        }
    }

    func testTheTextBeforeTheCursorMustEndWithExactlyOneSpace() {
        for before in ["word  ", "word\t", "word\n", "word\n ", "word\t ", "word \t", " ", "", "word\u{00A0}", "word\u{3000}"] {
            XCTAssertNil(removal(",", before: before), before.debugDescription)
        }
    }

    func testTheCharacterBeforeTheSpaceMustEndAWordOrCloseAGroup() {
        for before in ["word ", "Word ", "caf\u{00E9} ", "\u{4F60}\u{597D} ", "room 5 ", "x\u{00B2} "] {
            XCTAssertEqual(removal(",", before: before), .markOnly, before)
        }
        for before in ["a) ", "a] ", "a} ", "\"a\" ", "'a' ", "\u{201C}a\u{201D} ", "\u{2018}a\u{2019} "] {
            XCTAssertEqual(removal(",", before: before), .markOnly, before)
        }
        let others = [
            "( ", "[ ", "{ ", "\u{201C} ", "\u{2018} ", "end. ", "one, ", "what? ", "no! ", "a; ", "a: ", "a - ", "50% ",
            "ok \u{1F600} ", "1\u{FE0F}\u{20E3} ", "\u{2139}\u{FE0F} ", "a\u{FF09} ", "a\u{3002} ", "a/ ", "a@ ",
        ]
        for before in others {
            XCTAssertNil(removal(",", before: before), before)
        }
    }

    func testAFieldWithoutAutocorrectionGetsNoSpaceRemoval() {
        for mark in KeyboardTextLogic.marks {
            XCTAssertNil(removal(String(mark), before: "word ", allowsAutocorrection: false), String(mark))
        }
    }

    func testALetterOrADigitAfterTheCursorPutsTheSpaceAfterTheMark() {
        for after in ["world", "World", "2nd", "\u{4E16}\u{754C}", "\u{00E9}t\u{00E9}", "a"] {
            XCTAssertEqual(removal(",", before: "hello ", after: after), .markThenSpace, after)
        }
        for after in ["", " world", "\nworld", "\tworld", ")", ". Then", "\"word\"", "\u{1F600}", "1\u{FE0F}\u{20E3}", "-a"] {
            XCTAssertEqual(removal(",", before: "hello ", after: after), .markOnly, after.debugDescription)
        }
        // The text after the cursor does not start a space removal by itself.
        XCTAssertNil(removal(",", before: "hello", after: "world"))
        XCTAssertNil(removal(",", before: "hello  ", after: "world"))
    }

    func testALetterOrADigitRestoresTheSpaceOfEveryASCIIMark() {
        for mark in KeyboardTextLogic.asciiMarks {
            for next in ["a", "Z", "0", "9", "\u{00E9}", "\u{03C0}"] {
                XCTAssertTrue(KeyboardTextLogic.restoresSpace(beforeMark: String(mark), typing: next), "\(mark)\(next)")
            }
        }
    }

    func testAnEmoticonRestoresTheSpaceOfAColonAndASemicolonOnly() {
        for next in KeyboardTextLogic.emoticonCharacters {
            for mark in KeyboardTextLogic.asciiMarks {
                let expected = mark == ":" || mark == ";" || (mark == "." && next == "/")
                XCTAssertEqual(
                    KeyboardTextLogic.restoresSpace(beforeMark: String(mark), typing: String(next)), expected,
                    "\(mark)\(next)")
            }
        }
        XCTAssertEqual(KeyboardTextLogic.emoticonCharacters, Set(")(-'/\|*]"))
    }

    func testAnEqualsSignRestoresTheSpaceOfThreeMarks() {
        for mark in KeyboardTextLogic.asciiMarks {
            XCTAssertEqual(
                KeyboardTextLogic.restoresSpace(beforeMark: String(mark), typing: "="), "!:?".contains(mark),
                String(mark))
        }
    }

    func testASlashRestoresTheSpaceOfAPeriod() {
        XCTAssertTrue(KeyboardTextLogic.restoresSpace(beforeMark: ".", typing: "/"))
        for mark in [",", "?", "!", ")", "]", "}"] {
            XCTAssertFalse(KeyboardTextLogic.restoresSpace(beforeMark: mark, typing: "/"), mark)
        }
    }

    func testOtherKeysDoNotRestoreTheSpace() {
        for mark in KeyboardTextLogic.asciiMarks {
            for next in [" ", "\n", ".", ",", "!", "?", "\"", "%", "@", "#", "}", "\u{1F600}", "", "ab"] {
                XCTAssertFalse(KeyboardTextLogic.restoresSpace(beforeMark: String(mark), typing: next), "\(mark)\(next)")
            }
        }
        XCTAssertFalse(KeyboardTextLogic.restoresSpace(beforeMark: "", typing: "a"))
        XCTAssertFalse(KeyboardTextLogic.restoresSpace(beforeMark: "..", typing: "a"))
    }

    func testAChineseMarkGetsNoSpaceRestoreExceptTheApostropheForm() {
        for mark in KeyboardTextLogic.chineseMarks where mark != "\u{2019}" {
            for next in ["a", "5", ")", "=", "/"] {
                XCTAssertFalse(KeyboardTextLogic.restoresSpace(beforeMark: String(mark), typing: next), "\(mark)\(next)")
            }
        }
        // U+2019 is also the apostrophe of "’90s" and "’n’".
        XCTAssertTrue(KeyboardTextLogic.restoresSpace(beforeMark: "\u{2019}", typing: "9"))
        XCTAssertTrue(KeyboardTextLogic.restoresSpace(beforeMark: "\u{2019}", typing: "n"))
        XCTAssertFalse(KeyboardTextLogic.restoresSpace(beforeMark: "\u{2019}", typing: ")"))
    }

    func testLetterOrDigit() {
        for character in "aZ5\u{00E9}\u{4F60}\u{03C0}\u{00BD}" {
            XCTAssertTrue(KeyboardTextLogic.isLetterOrDigit(character), String(character))
        }
        for character in [" ", ".", ")", "\"", "\u{1F600}", "1\u{FE0F}\u{20E3}", "\u{2139}\u{FE0F}", "\n", "_"] as [Character] {
            XCTAssertFalse(KeyboardTextLogic.isLetterOrDigit(character), String(character))
        }
    }
}
