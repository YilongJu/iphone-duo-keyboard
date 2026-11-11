import UIKit
import XCTest

@testable import DuoKeyboard

/// The answer filter of the sentence proofreader takes a fix of one apostrophe.
final class ApostropheProofreadingTests: XCTestCase {
    func testTheFilterAcceptsAnApostropheFix() {
        XCTAssertEqual(KeyboardTextLogic.acceptedProofreading(
            of: "I think its going to rain.", answer: "I think it's going to rain."), "I think it's going to rain.")
        XCTAssertEqual(KeyboardTextLogic.acceptedProofreading(of: "Its raining.", answer: "It's raining."), "It's raining.")
        XCTAssertEqual(KeyboardTextLogic.acceptedProofreading(
            of: "The dog wagged it's tail.", answer: "The dog wagged its tail."), "The dog wagged its tail.")
    }
}

/// The keyboard reads a word without an apostrophe again when the next word follows, with the
/// real engine and a fake model.
@MainActor
final class ApostropheWordsKeyboardTests: XCTestCase {
    private static let engine = EnglishTypingEngine(lexicon: TypingLexicon(resource: "lexicon-english", fullCheck: false))
    private static let storeName = "ApostropheWordsKeyboardTests"

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

    private func makeController(before: String, after: String = "", favoring text: String) {
        keyboardView = KeyboardView()
        document = FakeDocument(before: before, after: after)
        spellChecker = EngineSpellChecker(
            engine: Self.engine, reranker: EnglishReranker(scorer: FakeScorer(answer: FakeScorer.favoring(text))),
            store: UserDefaults(suiteName: Self.storeName)!)
        controller = KeyboardTextController(
            keyboardView: keyboardView, document: document, spellChecker: spellChecker,
            pinyinEngine: { PinyinEngine(dictionaryText: testDictionary) })
    }

    private func type(_ text: String) {
        for character in text {
            controller.keyboardView(keyboardView, insert: String(character))
        }
    }

    func testTheEngineReadsTheApostropheFormOfAWordWithTheNextWord() throws {
        let readings = try XCTUnwrap(Self.engine.readings(previousWord: "think", typed: "its going", limit: 8))
        XCTAssertTrue(readings.contains { $0.text == "it's going" }, "\(readings)")
        let back = try XCTUnwrap(Self.engine.readings(previousWord: "wagged", typed: "it's tail", limit: 8))
        XCTAssertTrue(back.contains { $0.text == "its tail" }, "\(back)")
        // The engine's own choice stays as typed.
        XCTAssertEqual(Self.engine.reading(previousWord: "think", typed: "its going"), "its going")
    }

    func testTheNextWordTurnsItsIntoItWithAnApostrophe() {
        makeController(before: "I think ", favoring: "it's going")
        type("its ")
        // The text before the word alone does not decide: the model gives both forms one score.
        XCTAssertEqual(document.text, "I think its ")
        type("going ")
        XCTAssertEqual(document.text, "I think it's going ")
    }

    func testAModestModelLeadIsEnoughForTheApostropheFormAfterTheNextWord() {
        // The model puts "it's going" 2 ahead of "its going", far under the margin of 24 from the
        // text as typed. The apostrophe step needs 1 after the slip cost of 0.5.
        keyboardView = KeyboardView()
        document = FakeDocument(before: "I think ")
        let scorer = FakeScorer(answer: { prompt in
            .scores(prompt.candidates.map {
                switch $0.trimmingCharacters(in: .whitespaces).lowercased() {
                case "it's going": return CandidateScore(logProbability: -4, spaceAfter: 0)
                case "its going": return CandidateScore(logProbability: -6, spaceAfter: 0)
                default: return CandidateScore(logProbability: -1000, spaceAfter: 0)
                }
            })
        })
        spellChecker = EngineSpellChecker(
            engine: Self.engine, reranker: EnglishReranker(scorer: scorer), store: UserDefaults(suiteName: Self.storeName)!)
        controller = KeyboardTextController(
            keyboardView: keyboardView, document: document, spellChecker: spellChecker,
            pinyinEngine: { PinyinEngine(dictionaryText: testDictionary) })
        type("its going ")
        XCTAssertEqual(document.text, "I think it's going ")
    }

    func testTheTextAfterTheCursorStaysAndTheCursorStaysAfterTheSpace() {
        makeController(before: "I think ", after: "\nsee you", favoring: "it's going")
        type("its going ")
        XCTAssertEqual(document.textBeforeCursor, "I think it's going ")
        XCTAssertEqual(document.textAfterCursor, "\nsee you")
    }

    func testBackspaceBringsBackBothTypedWordsAndTheKeyboardKeepsThem() {
        makeController(before: "I think ", favoring: "it's going")
        type("its going ")
        XCTAssertEqual(document.text, "I think it's going ")
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "I think its going")
        XCTAssertTrue(spellChecker.keeps("its"))
        // The person took the correction back, so the keyboard does not make it again.
        type(" and its going ")
        XCTAssertEqual(document.text, "I think its going and its going ")
    }

    func testAModelThatPrefersTheWordWithoutTheApostropheKeepsIt() {
        makeController(before: "the dog wagged ", favoring: "its tail")
        type("its tail ")
        XCTAssertEqual(document.text, "the dog wagged its tail ")
    }

    func testTheNextWordTakesAWrongApostropheAway() {
        makeController(before: "the dog wagged ", favoring: "its tail")
        type("it's tail ")
        XCTAssertEqual(document.text, "the dog wagged its tail ")
    }
}
