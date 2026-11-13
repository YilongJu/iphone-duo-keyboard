import UIKit
import XCTest

@testable import DuoKeyboard

/// A language model with fixed answers. It records every prompt.
@MainActor
final class FakeScorer: CandidateScoring {
    var answer: (LanguageModelPrompt) -> CandidateScoringResult
    private(set) var prompts: [LanguageModelPrompt] = []

    init(answer: @escaping (LanguageModelPrompt) -> CandidateScoringResult) {
        self.answer = answer
    }

    func score(_ prompt: LanguageModelPrompt) -> CandidateScoringResult {
        prompts.append(prompt)
        return answer(prompt)
    }

    /// Answers that put the candidate `word` far ahead of every other candidate. The match
    /// ignores the leading space and the capitals of the prompt.
    static func favoring(_ word: String) -> (LanguageModelPrompt) -> CandidateScoringResult {
        { prompt in
            .scores(prompt.candidates.map {
                let text = $0.trimmingCharacters(in: .whitespaces).lowercased()
                return CandidateScore(logProbability: text == word ? 0 : -1000, spaceAfter: 0)
            })
        }
    }
}

/// A loader that counts its calls.
@MainActor
final class FakeLoader: LanguageModelLoading {
    private(set) var loads = 0

    func loadInBackground() {
        loads += 1
    }
}

/// The rule of scripts/lm-rerank/rerank.py `choose()`, case by case.
final class RerankRuleTests: XCTestCase {
    private func reading(_ text: String, _ score: Double, typed: Bool = false, chosen: Bool = false) -> EnglishReading {
        EnglishReading(text: text, score: score, slipCost: 0, asTyped: typed, chosen: chosen)
    }

    private func model(_ values: Double...) -> [CandidateScore] {
        values.map { CandidateScore(logProbability: $0, spaceAfter: 0) }
    }

    private let rule = RerankRule.distilgpt2

    func testTheTunedSettingsAreThoseOfTheHarness() {
        XCTAssertEqual(rule, RerankRule(weight: 1.0, marginFromTyped: 24, marginToTyped: 0, marginOther: 2, usesSpaceAfter: true))
        // The setting and the lead of scripts/lm-domain/candidate.json.
        XCTAssertEqual(KeyboardLanguageModel.rule,
                       RerankRule(weight: 1.5, marginFromTyped: 1, marginToTyped: 4, marginOther: 2, usesSpaceAfter: true,
                                  apostrophe: RerankRule.ApostropheStep(
                                      scope: .firstWordOfSpan, score: .modelLessSlipCost, margin: 0.5, prompt: .stock)))
    }

    func testTheStockStepDecidesWithTheScoresOfItsOwnPrompt() {
        let stock = RerankRule(
            weight: 1.0, marginFromTyped: 0, marginToTyped: 4, marginOther: 2, usesSpaceAfter: false,
            apostrophe: RerankRule.ApostropheStep(scope: .firstWordOfSpan, score: .model, margin: 1, prompt: .stock))
        let readings = [reading("were going", -10, typed: true, chosen: true), reading("we're going", -15)]
        // The scores of the margins keep the text as typed, and so would a step that read them.
        var asked: [[Int]] = []
        let choice = stock.choose(readings, model(-5, -20)) { indices in
            asked.append(indices)
            return self.model(-6, -4)
        }
        XCTAssertEqual(asked, [[0, 1]])
        XCTAssertEqual(choice, 1)
        // Without an answer of the stock prompt the choice of the margins stays.
        XCTAssertEqual(stock.choose(readings, model(-5, -20)) { _ in nil }, 0)
        // A lead under the margin keeps the choice.
        XCTAssertEqual(stock.choose(readings, model(-5, -20)) { _ in self.model(-6, -5.01) }, 0)
    }

    func testTheSmolLM2RuleNeedsALeadOfOneAwayFromTheTextAsTyped() {
        let smollm2 = KeyboardLanguageModel.rule
        let readings = [reading("teh", -10, typed: true, chosen: true), reading("the", -12)]
        // The weight is 1.5. "teh" has -55 and "the" -54.015, then -54: a lead of 0.985, then exactly 1.
        XCTAssertEqual(smollm2.choose(readings, model(-30, -28.01)), 0)
        XCTAssertEqual(smollm2.choose(readings, model(-30, -28)), 1)
        // A move back to the text as typed needs a lead of 4: 3.98 keeps the choice, and 4.01 replaces it.
        let back = [reading("thr", -10, chosen: true), reading("the", -11, typed: true)]
        XCTAssertEqual(smollm2.choose(back, model(-6, -2.68)), 0)
        XCTAssertEqual(smollm2.choose(back, model(-6, -2.66)), 1)
    }

    func testTheEngineChoiceStaysWhenItHasTheHighestCombinedScore() {
        let readings = [reading("the", -10, chosen: true), reading("teh", -20, typed: true), reading("ten", -12)]
        XCTAssertEqual(rule.choose(readings, model(-3, -9, -4)), 0)
    }

    func testAMoveFromOneCorrectionToAnotherNeedsTheOtherMargin() {
        let readings = [reading("the", -10, chosen: true), reading("teh", -20, typed: true), reading("ten", -11)]
        // "ten" leads by 1.5 and then by exactly 2.
        XCTAssertEqual(rule.choose(readings, model(-5, -9, -2.5)), 0)
        XCTAssertEqual(rule.choose(readings, model(-5, -9, -3 + 1)), 2)
    }

    func testAMoveAwayFromTheTextAsTypedNeedsTheMarginFromTyped() {
        let readings = [reading("teh", -10, typed: true, chosen: true), reading("the", -12)]
        // "teh" has -40 and "the" -16.01, then -16: a lead of 23.99, then exactly 24.
        XCTAssertEqual(rule.choose(readings, model(-30, -4.01)), 0)
        XCTAssertEqual(rule.choose(readings, model(-30, -4)), 1)
    }

    func testAMoveBackToTheTextAsTypedNeedsNoMargin() {
        let readings = [reading("thr", -10, chosen: true), reading("the", -11, typed: true)]
        XCTAssertEqual(rule.choose(readings, model(-5, -4)), 0)
        XCTAssertEqual(rule.choose(readings, model(-5, -3.99)), 1)
    }

    func testTheFirstOfTwoEqualReadingsWins() {
        let readings = [reading("a", -10, chosen: true), reading("b", -10), reading("c", -10)]
        XCTAssertEqual(rule.choose(readings, model(-9, -1, -1)), 1)
    }

    func testTheSpaceAfterCountsOnlyWhenTheRuleUsesIt() {
        let readings = [reading("the", -10, chosen: true), reading("then", -10)]
        let scores = [CandidateScore(logProbability: -5, spaceAfter: -4), CandidateScore(logProbability: -5, spaceAfter: -1)]
        XCTAssertEqual(rule.choose(readings, scores), 1)
        let withoutSpace = RerankRule(weight: 1, marginFromTyped: 24, marginToTyped: 0, marginOther: 2, usesSpaceAfter: false)
        XCTAssertEqual(withoutSpace.choose(readings, scores), 0)
    }

    func testTheWeightScalesTheModelScore() {
        let readings = [reading("the", -10, chosen: true), reading("then", -13)]
        let half = RerankRule(weight: 0.5, marginFromTyped: 24, marginToTyped: 0, marginOther: 2, usesSpaceAfter: false)
        // The model gives "then" 10 more. Weight 1 makes the lead 7, and weight 0.5 makes it 2.
        XCTAssertEqual(rule.choose(readings, model(-20, -10)), 1)
        XCTAssertEqual(half.choose(readings, model(-20, -10)), 1)
        XCTAssertEqual(half.choose(readings, model(-20, -10.01)), 0)
    }

    func testStatisticsGiveTheMedianAndTheWorstTime() {
        var statistics = RerankStatistics()
        for milliseconds in [10.0, 30.0, 20.0, 40.0] {
            statistics.recordRead(milliseconds: milliseconds, changed: milliseconds == 30)
        }
        XCTAssertEqual(statistics.readCount, 4)
        XCTAssertEqual(statistics.meanMilliseconds, 25)
        XCTAssertEqual(statistics.percentileMilliseconds(0.5), 20)
        XCTAssertEqual(statistics.percentileMilliseconds(0.95), 40)
        XCTAssertEqual(statistics.worstMilliseconds, 40)
        XCTAssertEqual(statistics.changedCount, 1)
    }
}

/// The text the model reads, built the way scripts/lm-rerank/rerank.py builds it.
final class LanguageModelPromptTests: XCTestCase {
    func testTheTypedSpanStandsBetweenBarsAfterTheTextBeforeIt() {
        // The example of scripts/lm-finetune/README.md, Table 14.
        let prompt = try? XCTUnwrap(LanguageModelPrompt.make(textBefore: "how much ", typed: "sutar", readings: ["sugar", "star"]))
        XCTAssertEqual(prompt?.context, "How much | sutar |")
        XCTAssertEqual(prompt?.candidates, [" sugar", " star"])
    }

    func testTheContextAndTheReadingsGetTheCapitalsAPersonSeesAndTheTypedSpanStays() {
        let prompt = LanguageModelPrompt.make(
            textBefore: "can i take my shirt off it's so ", typed: "i hto", readings: ["i hot", "i'm hot", "i hto"])
        XCTAssertEqual(prompt?.context, "Can I take my shirt off it's so | i hto |")
        XCTAssertEqual(prompt?.candidates, [" I hot", " I'm hot", " I hto"])
    }

    func testAnEmptyTextBeforeTheSpanLeavesTheTypedSpanAlone() {
        let prompt = LanguageModelPrompt.make(textBefore: "", typed: "i thnik", readings: ["i think", "the"])
        XCTAssertEqual(prompt?.context, "| i thnik |")
        // The reading opens the field, so it gets the field's capital, after one space.
        XCTAssertEqual(prompt?.candidates, [" I think", " The"])
        // Spaces alone also leave the text before the span empty.
        XCTAssertEqual(LanguageModelPrompt.make(textBefore: "  ", typed: "teh", readings: ["the"])?.context, "| teh |")
    }

    func testOnlyTheSpacesAtTheEndAreDropped() {
        let prompt = LanguageModelPrompt.make(textBefore: "dear tom,\n", typed: "teh", readings: ["the"])
        XCTAssertEqual(prompt?.context, "Dear tom,\n | teh |")
        XCTAssertEqual(prompt?.candidates, [" the"])
    }

    func testABarInTheTextGivesNoPrompt() {
        XCTAssertNil(LanguageModelPrompt.make(textBefore: "a | b ", typed: "teh", readings: ["the"]))
        XCTAssertNil(LanguageModelPrompt.make(textBefore: "a ", typed: "te|h", readings: ["the"]))
    }

    func testTheStockPromptHoldsNoTypedSpan() {
        let prompt = LanguageModelPrompt.makeStock(textBefore: "i think ", readings: ["were going", "we're going"])
        XCTAssertEqual(prompt.context, "I think")
        XCTAssertEqual(prompt.candidates, [" were going", " we're going"])
        let opening = LanguageModelPrompt.makeStock(textBefore: "", readings: ["were going"])
        XCTAssertEqual(opening.context, "")
        XCTAssertEqual(opening.candidates, ["Were going"])
    }

    func testAnIOnlyAfterASpaceGetsItsCapital() {
        XCTAssertEqual(LanguageModelPrompt.withAutomaticCapitals("ok, i think (i know) i'd go", opensField: false),
                       "ok, I think (i know) I'd go")
        XCTAssertEqual(LanguageModelPrompt.withAutomaticCapitals("in it", opensField: true), "In it")
    }
}

/// The re-ranking inside the keyboard's own typing code, with the real engine and a fake model.
@MainActor
final class EnglishRerankingTests: XCTestCase {
    private static let engine = EnglishTypingEngine(lexicon: TypingLexicon(resource: "lexicon-english", fullCheck: false))
    private static let storeName = "EnglishRerankingTests"

    private var keyboardView: KeyboardView!
    private var document: FakeDocument!
    private var scorer: FakeScorer!
    private var reranker: EnglishReranker!
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

    private func makeController(before: String, after: String = "", answer: @escaping (LanguageModelPrompt) -> CandidateScoringResult) {
        keyboardView = KeyboardView()
        document = FakeDocument(before: before, after: after)
        scorer = FakeScorer(answer: answer)
        reranker = EnglishReranker(scorer: scorer, rule: KeyboardLanguageModel.rule)
        spellChecker = EngineSpellChecker(
            engine: Self.engine, reranker: reranker, store: UserDefaults(suiteName: Self.storeName)!)
        controller = KeyboardTextController(
            keyboardView: keyboardView, document: document, spellChecker: spellChecker,
            pinyinEngine: { PinyinEngine(dictionaryText: testDictionary) })
    }

    private func type(_ text: String) {
        for character in text {
            controller.keyboardView(keyboardView, insert: String(character))
        }
    }

    /// A reading of `typed` that is neither the engine's choice nor the text as typed.
    private func otherReading(previousWord: String, typed: String) throws -> String {
        let readings = try XCTUnwrap(Self.engine.readings(previousWord: previousWord, typed: typed, limit: 8))
        return try XCTUnwrap(readings.first { !$0.chosen && !$0.asTyped }?.text, "\(readings)")
    }

    func testTheReadingsHoldTheEngineChoice() {
        let inputs: [(String, String)] = [
            ("", "teh"), ("will", "recieve"), ("", "hello wrold"), ("", "dont"), ("", "thequick"), ("", "th e"),
            ("", "tob e"), ("the", "qu ick"), ("", "[lease"), ("", "0lease"), ("i", ";ike"), ("", "2hat"),
            ("", "wh3n"), ("", "[note"), ("", ".net"), ("", "mp3"), ("", "[teh"), ("", "the"), ("", "good morning"),
            ("a", "teh"), ("said", "th e"),
        ]
        for (previousWord, typed) in inputs {
            let readings = Self.engine.readings(previousWord: previousWord, typed: typed, limit: 8)
            XCTAssertEqual(readings?.first { $0.chosen }?.text, Self.engine.reading(previousWord: previousWord, typed: typed), typed)
            XCTAssertEqual(readings?.first { $0.asTyped }?.text, typed, typed)
            XCTAssertLessThanOrEqual(readings?.count ?? 0, 8, typed)
        }
        // Text outside the engine's input has no readings, as it has no reading.
        XCTAssertNil(Self.engine.readings(previousWord: "", typed: "Teh", limit: 8))
    }

    func testTheModelCanReplaceTheEngineChoice() throws {
        let other = try otherReading(previousWord: "a", typed: "teh")
        makeController(before: "this is a ", answer: FakeScorer.favoring(other))
        type("teh ")
        XCTAssertEqual(document.text, "this is a \(other) ")
        let prompt = try XCTUnwrap(scorer.prompts.last)
        XCTAssertEqual(prompt.context, "This is a | teh |")
        XCTAssertTrue(prompt.candidates.contains(" \(other)"), "\(prompt)")
        XCTAssertEqual(reranker.statistics.readCount, 1)
        XCTAssertEqual(reranker.statistics.changedCount, 1)
    }

    func testBackspaceBringsBackTheTypedTextAfterAModelChoiceAndKeepsIt() throws {
        let other = try otherReading(previousWord: "a", typed: "teh")
        makeController(before: "this is a ", answer: FakeScorer.favoring(other))
        type("teh ")
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "this is a teh")
        XCTAssertTrue(spellChecker.keeps("teh"))
        type(" ")
        XCTAssertEqual(document.text, "this is a teh ")
    }

    func testAKeptWordDoesNotReachTheModel() throws {
        let other = try otherReading(previousWord: "a", typed: "teh")
        makeController(before: "this is a ", answer: FakeScorer.favoring(other))
        spellChecker.learn("teh")
        type("teh ")
        XCTAssertEqual(document.text, "this is a teh ")
        XCTAssertTrue(scorer.prompts.isEmpty, "\(scorer.prompts)")
        // A word read with a kept word before it is read alone.
        type("cta ")
        XCTAssertTrue(scorer.prompts.allSatisfy { $0.context == "This is a teh | cta |" }, "\(scorer.prompts)")
    }

    func testTheTwoWordReadingGoesToTheModelWithTheTextBeforeBothWords() {
        makeController(before: "I said ", answer: FakeScorer.favoring("the"))
        var traces: [RerankTrace] = []
        reranker.onTrace = { traces.append($0) }
        type("th e ")
        XCTAssertEqual(document.text, "I said the ")
        let last = traces.last
        XCTAssertEqual(last?.textBefore, "I said ")
        XCTAssertEqual(last?.prompt.context, "I said | th e |")
        // The readings of the two typed words together.
        XCTAssertTrue(last?.readings.contains { $0.asTyped && $0.text == "th e" } ?? false, "\(String(describing: last))")
    }

    func testTheWordsTypedDuringASelectAllReplacementGoToTheModel() throws {
        let other = try otherReading(previousWord: "", typed: "teh")
        makeController(before: "hello ", after: "world", answer: FakeScorer.favoring(other))
        controller.keyboardView(keyboardView, edit: .selectAll)
        type("teh ")
        RunLoop.current.run(until: Date().addingTimeInterval(0.6))
        XCTAssertEqual(document.text, "\(other) ")
        // The field was empty when the model read the word, so the reading opens the field.
        XCTAssertEqual(scorer.prompts.last?.context, "| teh |")
    }

    func testABarBeforeTheWordKeepsTheEngineChoice() {
        makeController(before: "a | b ", answer: FakeScorer.favoring("tech"))
        let engineChoice = try? XCTUnwrap(Self.engine.reading(previousWord: "b", typed: "teh"))
        type("teh ")
        XCTAssertEqual(document.text, "a | b \(engineChoice ?? "") ")
        XCTAssertTrue(scorer.prompts.isEmpty)
        XCTAssertEqual(reranker.statistics.refusedCount, 1)
    }

    func testPinyinTypingDoesNotUseTheModel() {
        makeController(before: "", answer: FakeScorer.favoring("the"))
        let loader = FakeLoader()
        controller.languageModelLoader = loader
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        controller.keyboardWillAppear()
        type("nihao wo,")
        XCTAssertEqual(document.text, "\u{4F60}\u{597D}\u{6211}\u{FF0C}")
        XCTAssertTrue(scorer.prompts.isEmpty)
        XCTAssertEqual(loader.loads, 0)
        // A switch back to English asks for the model, and so does the next appearance.
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        XCTAssertEqual(loader.loads, 1)
        controller.keyboardWillAppear()
        XCTAssertEqual(loader.loads, 2)
    }

    func testTheEngineChoiceStaysWhileTheModelIsNotReady() {
        makeController(before: "", answer: { _ in .notReady("the model is loading") })
        type("teh ")
        XCTAssertEqual(document.text, "the ")
        XCTAssertEqual(reranker.statistics.notReadyCount, 1)
        XCTAssertEqual(reranker.statistics.readCount, 0)
    }

    func testAModelErrorIsNamedOnTheSpaceBar() {
        makeController(before: "", answer: { _ in .failed("llama_decode returned 1") })
        let controller: KeyboardTextController = self.controller
        reranker.onModelError = { [weak controller] in controller?.show(.modelError($0)) }
        type("teh ")
        XCTAssertEqual(document.text, "the ")
        // The error notice comes after the notice of the correction, so the correction does not hide it.
        RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        XCTAssertEqual(keyboardView.spaceCaption, "Language model error: llama_decode returned 1")
        XCTAssertEqual(reranker.statistics.failedCount, 1)
    }

    func testAModelThatDoesNotLoadIsNamedOnTheSpaceBar() {
        makeController(before: "", answer: FakeScorer.favoring("the"))
        let model = KeyboardLanguageModel(modelPath: "/missing/model.gguf", modelName: "missing")
        let controller: KeyboardTextController = self.controller
        model.onEvent = { [weak controller] in controller?.show($0) }
        XCTAssertThrowsError(try model.loadNow()) { error in
            XCTAssertTrue((error as? LanguageModelError)?.reason.hasPrefix("the model did not load") ?? false, "\(error)")
        }
        guard case .loadFailed = model.state else { return XCTFail("\(model.state)") }
        XCTAssertTrue(keyboardView.spaceCaption?.hasPrefix("Language model did not load: ") ?? false,
                      String(describing: keyboardView.spaceCaption))
        // After the notice the caption stays in English, and Chinese shows its own caption.
        RunLoop.current.run(until: Date().addingTimeInterval(2.7))
        XCTAssertEqual(keyboardView.spaceCaption, "No language model")
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        XCTAssertEqual(keyboardView.spaceCaption, "\u{62FC}\u{97F3}")
        guard case .notReady(let reason) = model.score(LanguageModelPrompt(context: "", candidates: ["a", "b"])) else {
            return XCTFail("a model that did not load must not score")
        }
        XCTAssertTrue(reason.hasPrefix("the model did not load: "), reason)
    }

    func testAModelFileMissingFromTheBundleIsNamed() {
        let model = KeyboardLanguageModel(modelPath: nil, modelName: "absent")
        XCTAssertThrowsError(try model.loadNow()) { error in
            XCTAssertEqual(error as? LanguageModelError, LanguageModelError(reason: "absent.gguf is missing from the bundle"))
        }
    }
}
