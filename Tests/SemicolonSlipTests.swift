import UIKit
import XCTest

@testable import DuoKeyboard

/// The engine reads a semicolon between two letters as a slip for the apostrophe key beside it:
/// "don;t" for "don't" (`semicolon_for_apostrophe` in Engine/duo_engine.h).
@MainActor
final class SemicolonSlipEngineTests: XCTestCase {
    private static let engine = EnglishTypingEngine(lexicon: TypingLexicon(resource: "lexicon-english", fullCheck: false))

    func testASemicolonBetweenTwoLettersReadsAsTheApostrophe() {
        let pairs = [
            ("don;t", "don't"), ("can;t", "can't"), ("it;s", "it's"), ("i;m", "i'm"), ("we;re", "we're"),
            ("they;ll", "they'll"), ("you;ve", "you've"), ("didn;t", "didn't"), ("isn;t", "isn't"),
            ("that;s", "that's"), ("let;s", "let's"), ("i;d", "i'd"), ("he;d", "he'd"), ("we;d", "we'd"),
            ("o;clock", "o'clock"), ("today;s", "today's"),
        ]
        for (typed, intended) in pairs {
            XCTAssertEqual(Self.engine.reading(previousWord: "", typed: typed), intended, typed)
        }
        XCTAssertEqual(Self.engine.reading(previousWord: "i", typed: "don;t know"), "don't know")
    }

    func testASemicolonTypedOnPurposeBetweenTwoWordsStaysAsTyped() {
        for typed in ["yes;no", "word;next", "one;two", "this;that", "hour;and", "see;over"] {
            XCTAssertEqual(Self.engine.reading(previousWord: "", typed: typed), typed, typed)
        }
    }

    func testASemicolonAfterALetterIsNeverReadAsALetter() {
        // The key "l" also sits beside the semicolon key. A semicolon in front of a word can be
        // a slip for it, and a semicolon after a letter cannot: "hour;and" would give "hour land".
        XCTAssertEqual(Self.engine.reading(previousWord: "", typed: ";ike"), "like")
        XCTAssertNotEqual(Self.engine.reading(previousWord: "", typed: "wou;d"), "would")
        XCTAssertNotEqual(Self.engine.reading(previousWord: "", typed: "so;id"), "solid")
    }

    func testTheTypedTextWithASemicolonCountsAsAnUnknownWord() throws {
        let readings = try XCTUnwrap(Self.engine.readings(previousWord: "", typed: "don;t", limit: 8))
        XCTAssertEqual(readings.first { $0.chosen }?.text, "don't")
        XCTAssertEqual(readings.first { $0.asTyped }?.text, "don;t")
        // The rule of the language model keeps the correction of an unknown typed word.
        XCTAssertTrue(readings.allSatisfy { !$0.typedWordsKnown })
    }
}

/// `KeyboardTextLogic.correctableWord` takes a semicolon between two letters into the word.
final class SemicolonSlipWordTests: XCTestCase {
    func testAWordHoldsASemicolonBetweenTwoLetters() {
        XCTAssertEqual(KeyboardTextLogic.correctableWord(before: "I don;t"), "don;t")
        XCTAssertEqual(KeyboardTextLogic.correctableWord(before: "I;m"), "I;m")
        XCTAssertEqual(KeyboardTextLogic.correctableWord(before: "say didn't;t"), "didn't;t")
    }

    func testASemicolonAtTheEndOrAfterASpaceIsNoPartOfAWord() {
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "word;"))
        XCTAssertEqual(KeyboardTextLogic.correctableWord(before: "word; next"), "next")
        // A semicolon in front of a word is still the slip for the first letter.
        XCTAssertEqual(KeyboardTextLogic.correctableWord(before: "I ;ike"), ";ike")
    }

    func testAWordHoldsOneSymbolKeyAtTheMost() {
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "a;b;c"))
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "don;t2"))
        XCTAssertNil(KeyboardTextLogic.correctableWord(before: "a;;b"))
    }
}

/// The keyboard with the real engine: the semicolon key ends a word, and the letters right
/// after it make one word with the semicolon in it.
@MainActor
final class SemicolonSlipKeyboardTests: XCTestCase {
    private static let engine = EnglishTypingEngine(lexicon: TypingLexicon(resource: "lexicon-english", fullCheck: false))
    private static let storeName = "SemicolonSlipKeyboardTests"

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

    func testASpaceAfterAContractionWithASemicolonTypesTheApostrophe() {
        for (typed, shown) in [("don;t ", "don't "), ("it;s ", "it's "), ("can;t ", "can't "), ("they;ll ", "they'll ")] {
            makeController(before: "")
            type(typed)
            XCTAssertEqual(document.text, shown, typed)
        }
    }

    func testTheWordGetsItsCapital() {
        makeController(before: "")
        type("Don;t ")
        XCTAssertEqual(document.text, "Don't ")
        makeController(before: "")
        type("I;m ")
        XCTAssertEqual(document.text, "I'm ")
    }

    func testAMarkAfterTheWordAlsoFixesIt() {
        makeController(before: "I ")
        type("don;t.")
        XCTAssertEqual(document.text, "I don't.")
    }

    func testAFirstPartThatTheSemicolonKeyCorrectedIsReadAsTyped() {
        // The semicolon key ends "isn", and the keyboard reads that part alone as another word.
        // At the space the engine reads the keys "isn;t".
        makeController(before: "")
        type("isn;")
        XCTAssertNotEqual(document.text, "isn;")
        type("t ")
        XCTAssertEqual(document.text, "isn't ")
        makeController(before: "it ")
        type("didn;t work ")
        XCTAssertEqual(document.text, "it didn't work ")
    }

    func testTheNextWordKeepsTheFix() {
        makeController(before: "")
        type("it;s clear ")
        XCTAssertEqual(document.text, "it's clear ")
        makeController(before: "")
        type("I don;t know ")
        XCTAssertEqual(document.text, "I don't know ")
    }

    func testASemicolonTypedOnPurposeStays() {
        makeController(before: "")
        type("yes; no ")
        XCTAssertEqual(document.text, "yes; no ")
        makeController(before: "")
        type("one;two ")
        XCTAssertEqual(document.text, "one;two ")
    }

    func testBackspaceBringsBackTheSemicolonAndTheKeyboardKeepsIt() {
        makeController(before: "")
        type("don;t ")
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "don;t")
        XCTAssertTrue(spellChecker.keeps("don;t"))
        type(" ")
        XCTAssertEqual(document.text, "don;t ")
    }
}

/// The keyboard with a fixed list of readings: which keys the correction hands to the checker.
@MainActor
final class SemicolonSlipControllerTests: XCTestCase {
    private var keyboardView: KeyboardView!
    private var document: FakeDocument!
    private var spellChecker: FakeSpellChecker!
    private var controller: KeyboardTextController!

    private func makeController(before: String) {
        keyboardView = KeyboardView()
        document = FakeDocument(before: before)
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

    func testTheCheckerReadsTheKeysOfTheWholeWord() {
        makeController(before: "")
        spellChecker.corrections = ["didn": "did", "didn;t": "didn't"]
        type("didn;")
        XCTAssertEqual(document.text, "did;")
        type("t ")
        // The field held "did;t", and the person pressed the keys "didn;t".
        XCTAssertEqual(spellChecker.requests, ["|didn", "|didn;t"])
        XCTAssertEqual(document.text, "didn't ")
    }

    func testTheReadAheadOfTheSpaceReadsTheSameKeys() {
        makeController(before: "")
        spellChecker.corrections = ["didn": "did", "didn;t": "didn't"]
        type("didn;t")
        XCTAssertEqual(spellChecker.readAheads.last, "|didn;t|")
    }

    func testADeleteAfterTheSemicolonForgetsTheKeysOfTheFirstPart() {
        makeController(before: "")
        spellChecker.corrections = ["didn": "did"]
        type("didn;t")
        XCTAssertEqual(document.text, "did;t")
        // The person deletes the letter and types it again. The field's text is then the typed text.
        controller.keyboardViewDeleteBackward(keyboardView)
        spellChecker.requests = []
        type("t ")
        XCTAssertEqual(spellChecker.requests, ["|did;t"])
    }

    func testTheWordAfterASpaceIsReadTogetherWithTheKeysOfTheFixedWord() {
        makeController(before: "")
        spellChecker.corrections = ["don;t": "don't"]
        type("don;t know ")
        XCTAssertEqual(spellChecker.requests, ["|don", "|don;t", "|don;t know"])
        XCTAssertEqual(document.text, "don't know ")
    }
}
