import UIKit
import XCTest

@testable import DuoKeyboard

/// The apostrophe step of the re-ranking rule, case by case (`apostrophe_step` of
/// scripts/lm-rerank/rerank.py).
final class ApostropheStepRuleTests: XCTestCase {
    private func reading(_ text: String, _ score: Double, typed: Bool = false, chosen: Bool = false,
                         slipCost: Double = 0) -> EnglishReading {
        EnglishReading(text: text, score: score, slipCost: slipCost, asTyped: typed, chosen: chosen)
    }

    private func model(_ values: Double...) -> [CandidateScore] {
        values.map { CandidateScore(logProbability: $0, spaceAfter: 0) }
    }

    private func rule(_ scope: RerankRule.ApostropheStep.Scope, _ score: RerankRule.ApostropheStep.Score = .model,
                      margin: Double = 2, usesSpaceAfter: Bool = true) -> RerankRule {
        RerankRule(weight: 1.0, marginFromTyped: 24, marginToTyped: 0, marginOther: 2, usesSpaceAfter: usesSpaceAfter,
                   apostrophe: RerankRule.ApostropheStep(scope: scope, score: score, margin: margin))
    }

    @MainActor
    func testTheKeyboardUsesTheSettingChosenOnTheDevHalf() {
        XCTAssertEqual(RerankRule.distilgpt2WithApostrophes, RerankRule(
            weight: 1.0, marginFromTyped: 24, marginToTyped: 0, marginOther: 2, usesSpaceAfter: true,
            apostrophe: RerankRule.ApostropheStep(scope: .firstWordOfSpan, score: .modelLessSlipCost, margin: 1)))
        // The keyboard's rule, tuned for its SmolLM2 model, holds the same scope and score with
        // the stock prompt and the lead that the dev grid picks for that model.
        XCTAssertEqual(KeyboardLanguageModel.rule.apostrophe,
                       RerankRule.ApostropheStep(scope: .firstWordOfSpan, score: .modelLessSlipCost, margin: 4, prompt: .stock))
    }

    func testTheReadingWithTheApostropheNeedsOnlyTheModelLead() {
        // The engine puts "it's going" 5 below the text as typed. The model score alone decides.
        let readings = [reading("its going", -10, typed: true, chosen: true), reading("it's going", -15)]
        XCTAssertEqual(rule(.firstWordOfSpan).choose(readings, model(-12, -10.01)), 0)
        XCTAssertEqual(rule(.firstWordOfSpan).choose(readings, model(-12, -10)), 1)
        // Without the step, the margin from the text as typed applies to the combined score.
        XCTAssertEqual(RerankRule.distilgpt2.choose(readings, model(-12, -10)), 0)
    }

    func testTheSlipCostCountsWithTheScoreThatTakesItOff() {
        let readings = [reading("its going", -10, typed: true, chosen: true), reading("it's going", -15, slipCost: 0.5)]
        XCTAssertEqual(rule(.firstWordOfSpan).choose(readings, model(-12, -10)), 1)
        XCTAssertEqual(rule(.firstWordOfSpan, .modelLessSlipCost).choose(readings, model(-12, -10)), 0)
        XCTAssertEqual(rule(.firstWordOfSpan, .modelLessSlipCost).choose(readings, model(-12, -9.5)), 1)
    }

    func testAWordAloneStaysWhenTheStepWaitsForTheNextWord() {
        let readings = [reading("its", -10, typed: true, chosen: true), reading("it's", -11)]
        XCTAssertEqual(rule(.firstWordOfSpan).choose(readings, model(-12, -1)), 0)
        XCTAssertEqual(rule(.everyCorrection).choose(readings, model(-12, -1)), 1)
    }

    func testTheStepWaitingForTheNextWordChangesOnlyTheFirstWord() {
        // "think it's" changes the last word, which the model sees without the word after it.
        let readings = [reading("think its", -10, typed: true, chosen: true), reading("think it's", -11),
                        reading("it's going", -30)]
        XCTAssertEqual(rule(.firstWordOfSpan).choose(readings, model(-12, -1, -2)), 0)
        XCTAssertEqual(rule(.everyCorrection).choose(readings, model(-12, -1, -2)), 1)
        XCTAssertTrue(RerankRule.isTwin("it's going", of: "its going", scope: .firstWordOfSpan))
        XCTAssertFalse(RerankRule.isTwin("its go'ing", of: "its going", scope: .firstWordOfSpan))
        XCTAssertFalse(RerankRule.isTwin("it's", of: "its", scope: .firstWordOfSpan))
        XCTAssertFalse(RerankRule.isTwin("its going", of: "its going", scope: .everyCorrection))
    }

    func testTheStepAlsoTakesAnApostropheAway() {
        let readings = [reading("it's tail", -10, typed: true, chosen: true), reading("its tail", -16)]
        XCTAssertEqual(rule(.firstWordOfSpan).choose(readings, model(-15, -12)), 1)
        XCTAssertEqual(rule(.firstWordOfSpan).choose(readings, model(-15, -13.5)), 0)
    }

    func testTheSpaceAfterCountsInTheStepWhenTheRuleUsesIt() {
        let readings = [reading("were here", -10, typed: true, chosen: true), reading("we're here", -12)]
        let scores = [CandidateScore(logProbability: -5, spaceAfter: -3), CandidateScore(logProbability: -5, spaceAfter: -1)]
        XCTAssertEqual(rule(.firstWordOfSpan).choose(readings, scores), 1)
        XCTAssertEqual(rule(.firstWordOfSpan, usesSpaceAfter: false).choose(readings, scores), 0)
    }

    func testTheStepComparesTheApostropheFormOfTheTypedLettersWithACorrection() {
        // The engine reads the typed "hows it" as "how it". "how's it" spells the typed letters.
        let readings = [reading("how it", -10, chosen: true), reading("how's it", -11), reading("hows it", -18, typed: true)]
        // "how's it" leads by 1 in the model score: the step needs 2.
        XCTAssertEqual(rule(.firstWordOfSpan).choose(readings, model(-6, -5, -30)), 0)
        // A lead of 2.5 is under the margin between two corrections in the combined score, 1.5
        // against 2, and enough for the step.
        XCTAssertEqual(rule(.firstWordOfSpan).choose(readings, model(-6, -3.5, -30)), 1)
        XCTAssertEqual(RerankRule.distilgpt2.choose(readings, model(-6, -3.5, -30)), 0)
    }

    func testTheTextAsTypedIsNeverATwin() {
        // The engine reads "whats up" as "what's up". The model prefers the typed text, and the
        // step does not move back to it.
        let readings = [reading("what's up", -9, chosen: true), reading("whats up", -19, typed: true)]
        XCTAssertEqual(rule(.firstWordOfSpan).choose(readings, model(-9, -1)), 0)
    }

    func testOfTwoTwinsTheOneWithTheHigherStepScoreCountsAndTheFirstOnATie() {
        let readings = [reading("shell be", -10, typed: true, chosen: true), reading("she'll be", -12),
                        reading("he'll be", -13), reading("s'hell be", -14)]
        XCTAssertEqual(rule(.firstWordOfSpan).choose(readings, model(-10, -7, -9, -6)), 3)
        XCTAssertEqual(rule(.firstWordOfSpan).choose(readings, model(-10, -7, -9, -7)), 1)
    }

    func testTheStepNeedsTheModel() {
        let readings = [reading("its going", -10, typed: true, chosen: true), reading("it's going", -15)]
        let withoutModel = RerankRule(
            weight: 0, marginFromTyped: 24, marginToTyped: 0, marginOther: 2, usesSpaceAfter: true,
            apostrophe: RerankRule.ApostropheStep(scope: .firstWordOfSpan, score: .model, margin: 1))
        XCTAssertEqual(withoutModel.choose(readings, model(-12, -1)), 0)
    }
}

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
            engine: Self.engine,
            reranker: EnglishReranker(scorer: FakeScorer(answer: FakeScorer.favoring(text)), rule: .distilgpt2WithApostrophes),
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
            engine: Self.engine, reranker: EnglishReranker(scorer: scorer, rule: .distilgpt2WithApostrophes),
            store: UserDefaults(suiteName: Self.storeName)!)
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
