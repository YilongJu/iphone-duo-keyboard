import UIKit
import XCTest

@testable import DuoKeyboard

/// The engine reads a letter beside the comma key, typed right after a word, as the comma:
/// "hellom" for "hello," (`letter_for_comma` in Engine/duo_engine.h, docs/comma-slip-design.md).
@MainActor
final class CommaSlipEngineTests: XCTestCase {
    private static let engine = EnglishTypingEngine(lexicon: TypingLexicon(resource: "lexicon-english", fullCheck: false))

    func testALetterBesideTheCommaKeyAfterAWordReadsAsTheComma() {
        XCTAssertEqual(Self.engine.reading(previousWord: "", typed: "hellom"), "hello,")
        XCTAssertEqual(Self.engine.reading(previousWord: "say", typed: "hellom"), "hello,")
        XCTAssertEqual(Self.engine.reading(previousWord: "", typed: "say hellom"), "say hello,")
    }

    func testTheReadingsHoldTheCommaOnlyBeforeASpace() throws {
        let beforeSpace = try XCTUnwrap(Self.engine.readings(previousWord: "", typed: "hellom", limit: 8, endsWithSpace: true))
        XCTAssertEqual(beforeSpace.first { $0.chosen }?.text, "hello,", "\(beforeSpace)")
        // The text that the person ends with a mark or a line break gets no comma reading.
        let beforeMark = try XCTUnwrap(Self.engine.readings(previousWord: "", typed: "hellom", limit: 8, endsWithSpace: false))
        XCTAssertFalse(beforeMark.contains { $0.text.hasSuffix(",") }, "\(beforeMark)")
        XCTAssertEqual(beforeMark.first { $0.chosen }?.text, "hello", "\(beforeMark)")
    }

    func testRealWordsThatEndInALetterBesideTheCommaKeyStayAsTyped() {
        for word in ["form", "them", "seem", "call", "back", "skin", "from", "him", "tom", "been"] {
            XCTAssertEqual(Self.engine.reading(previousWord: "", typed: word), word, word)
        }
    }

    func testALetterThatRepeatsOrSitsBesideTheLetterBeforeItGetsNoComma() {
        // A doubled letter and an extra key beside the last letter explain these letters too.
        XCTAssertEqual(Self.engine.reading(previousWord: "", typed: "bostonn"), "boston")
        XCTAssertEqual(Self.engine.reading(previousWord: "a", typed: "breakl"), "break")
        XCTAssertEqual(Self.engine.reading(previousWord: "", typed: "hellol"), "hello")
    }

    func testAnEndingOfAContractionBeforeTheLetterGetsNoComma() {
        // The lexicon holds "ll", "re" and "ve" as the endings of "I'll", "you're" and "I've".
        // No person writes such an ending as a word before a comma, so "llm" is not "ll,".
        for typed in ["llm", "rek", "vem"] {
            let reading = Self.engine.reading(previousWord: "", typed: typed)
            XCTAssertEqual(reading?.contains(","), false, "\(typed) reads as \(reading ?? "nil")")
        }
        // A word of two letters that stands alone keeps its comma.
        XCTAssertEqual(Self.engine.reading(previousWord: "", typed: "usm"), "us,")
    }

    func testTheWordBeforeTheCommaMustBeTypedExactly() {
        // A slip inside the word as well would turn "itll" into "it," and not "it'll".
        XCTAssertEqual(Self.engine.reading(previousWord: "think", typed: "itll"), "it'll")
    }
}

/// The keyboard with the real engine and no language model: the comma goes into the field, a
/// backspace brings the typed letter back, and the next word is read alone.
@MainActor
final class CommaSlipKeyboardTests: XCTestCase {
    private static let engine = EnglishTypingEngine(lexicon: TypingLexicon(resource: "lexicon-english", fullCheck: false))
    private static let storeName = "CommaSlipKeyboardTests"

    private var keyboardView: KeyboardView!
    private var document: FakeDocument!
    private var spellChecker: EngineSpellChecker!
    private var controller: KeyboardTextController!

    override func setUp() {
        super.setUp()
        UserDefaults().removePersistentDomain(forName: Self.storeName)
    }

    override func tearDown() {
        UserDefaults().removePersistentDomain(forName: Self.storeName)
        super.tearDown()
    }

    private func makeController(before: String) {
        keyboardView = KeyboardView()
        document = FakeDocument(before: before)
        spellChecker = EngineSpellChecker(
            engine: Self.engine, reranker: nil, store: UserDefaults(suiteName: Self.storeName)!)
        controller = KeyboardTextController(
            keyboardView: keyboardView, document: document, spellChecker: spellChecker,
            pinyinEngine: { PinyinEngine(dictionaryText: testDictionary) })
    }

    private func type(_ text: String) {
        for character in text {
            controller.keyboardView(keyboardView, insert: String(character))
        }
    }

    func testASpaceAfterALetterBesideTheCommaKeyTypesTheComma() {
        makeController(before: "")
        type("hellom ")
        XCTAssertEqual(document.text, "hello, ")
    }

    func testTheCommaFollowsAWordReadTogetherWithTheWordBeforeIt() {
        makeController(before: "")
        type("say hellom ")
        XCTAssertEqual(document.text, "say hello, ")
    }

    func testBackspaceBringsBackTheTypedLetterAndTheKeyboardKeepsIt() {
        makeController(before: "")
        type("hellom ")
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "hellom")
        XCTAssertTrue(spellChecker.keeps("hellom"))
        type(" ")
        XCTAssertEqual(document.text, "hellom ")
    }

    func testTheWordAfterTheCommaIsReadAlone() {
        makeController(before: "")
        type("hellom wrold ")
        XCTAssertEqual(document.text, "hello, world ")
        // The word after the comma got its own correction, so the backspace takes back that one alone.
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "hello, wrold")
    }

    func testASpaceTypedOneKeyLateAfterTheLetterTakesTheCommaBackOut() {
        // "letm" alone reads as "let,". With the next word, "letm e" reads as "let me", which
        // keeps every typed letter, so the letter was a slip of the space.
        makeController(before: "")
        type("letm ")
        XCTAssertEqual(document.text, "let, ")
        type("e ")
        XCTAssertEqual(document.text, "let me ")
        makeController(before: "")
        type("asl eep ")
        XCTAssertEqual(document.text, "asleep ")
    }

    func testTheCapitalOfTheTypedWordStays() {
        makeController(before: "")
        type("Hellom ")
        XCTAssertEqual(document.text, "Hello, ")
        makeController(before: "I said ")
        type("Hellom ")
        XCTAssertEqual(document.text, "I said Hello, ")
    }

    func testAWordEndedByAMarkGetsNoComma() {
        // A person who types a mark after the word did not mean a comma before it.
        for (mark, expected) in [(".", "hello."), (",", "hello,"), ("!", "hello!"), ("\n", "hello\n")] {
            makeController(before: "")
            type("hellom" + mark)
            XCTAssertEqual(document.text, expected, mark)
        }
    }

    func testARealWordStaysAsTypedBeforeASpace() {
        for word in ["form", "them", "seem", "call", "back", "skin", "from", "him"] {
            makeController(before: "I ")
            type(word + " ")
            XCTAssertEqual(document.text, "I \(word) ", word)
        }
    }
}

/// A spell checker that records whether each reading was for text before a space.
@MainActor
private final class RecordingSpellChecker: SpellChecking {
    var corrections: [String: String] = [:]
    /// Every call, as "previous word|typed text|space" or "...|mark".
    var requests: [String] = []

    func reading(previousWord: String, typed: String, textBefore: String) -> String? {
        XCTFail("the keyboard asks with endsWithSpace")
        return nil
    }

    func reading(previousWord: String, typed: String, textBefore: String, endsWithSpace: Bool) -> String? {
        requests.append("\(previousWord)|\(typed)|\(endsWithSpace ? "space" : "mark")")
        let reading = corrections[typed] ?? typed
        // A checker reads a comma in place of a letter only before a space.
        return !endsWithSpace && KeyboardTextLogic.readsLastLetterAsComma(reading, typed: typed) ? typed : reading
    }

    func learn(_ word: String) {}

    func keeps(_ word: String) -> Bool { false }
}

@MainActor
final class CommaSlipControllerTests: XCTestCase {
    private var keyboardView: KeyboardView!
    private var document: FakeDocument!
    private var spellChecker: RecordingSpellChecker!
    private var controller: KeyboardTextController!

    private func makeController(before: String) {
        keyboardView = KeyboardView()
        document = FakeDocument(before: before)
        spellChecker = RecordingSpellChecker()
        spellChecker.corrections = ["hellom": "hello,", "tell hellom": "tell hello,", "sya hellom": "say hello,"]
        controller = KeyboardTextController(
            keyboardView: keyboardView, document: document, spellChecker: spellChecker,
            pinyinEngine: { PinyinEngine(dictionaryText: testDictionary) })
    }

    private func type(_ text: String) {
        for character in text {
            controller.keyboardView(keyboardView, insert: String(character))
        }
    }

    func testTheKeyboardSaysWhetherASpaceEndsTheWord() {
        makeController(before: "")
        type("hellom ")
        XCTAssertEqual(spellChecker.requests, ["|hellom|space"])
        makeController(before: "")
        type("hellom.")
        XCTAssertEqual(spellChecker.requests, ["|hellom|mark"])
        XCTAssertEqual(document.text, "hellom.")
    }

    func testTheNextWordIsNotReadTogetherWithTheComma() {
        makeController(before: "")
        spellChecker.corrections["hellom world"] = "hello world"
        type("hellom world ")
        XCTAssertEqual(document.text, "hello, world ")
        // The reading of the two words together takes out the typed "m", so the comma stays.
        // The word is then read alone, and no word comes before it.
        XCTAssertEqual(spellChecker.requests, ["|hellom|space", "|hellom world|space", "|world|space"])
    }

    func testAReadingThatMovesTheSpaceReplacesTheComma() {
        makeController(before: "")
        spellChecker.corrections["letm"] = "let,"
        spellChecker.corrections["letm e"] = "let me"
        type("letm e ")
        XCTAssertEqual(document.text, "let me ")
        XCTAssertEqual(spellChecker.requests, ["|letm|space", "|letm e|space"])
        // A backspace brings back the text that the field showed before this correction.
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "let, e")
    }

    func testACommaAfterTwoWordsReadTogetherKeepsTheFirstWordsCorrection() {
        makeController(before: "")
        spellChecker.corrections["sya"] = "say"
        type("sya hellom ")
        XCTAssertEqual(document.text, "say hello, ")
        XCTAssertEqual(spellChecker.requests, ["|sya|space", "|sya hellom|space"])
    }

    func testReadsLastLetterAsComma() {
        XCTAssertTrue(KeyboardTextLogic.readsLastLetterAsComma("hello,", typed: "hellom"))
        XCTAssertTrue(KeyboardTextLogic.readsLastLetterAsComma("say hello,", typed: "sya hellom"))
        XCTAssertFalse(KeyboardTextLogic.readsLastLetterAsComma("hello", typed: "hellom"))
        XCTAssertFalse(KeyboardTextLogic.readsLastLetterAsComma("more", typed: ",ore"))
    }

    func testMovesOnlySpaces() {
        XCTAssertTrue(KeyboardTextLogic.movesOnlySpaces("let me", typed: "letm e"))
        XCTAssertTrue(KeyboardTextLogic.movesOnlySpaces("asleep", typed: "asl eep"))
        XCTAssertFalse(KeyboardTextLogic.movesOnlySpaces("hello world", typed: "hellom world"))
        XCTAssertFalse(KeyboardTextLogic.movesOnlySpaces("letm e", typed: "letm e"))
    }
}
