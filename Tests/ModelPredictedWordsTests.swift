import UIKit
import XCTest

@testable import DuoKeyboard

/// A stand-in for the language model: it keeps each request for next-token numbers, and the test
/// answers the request when it wants to. No model file is read.
@MainActor
final class StandInPredictor: NextTokenScoring {
    /// The text of every request, in order.
    private(set) var contexts: [String] = []
    private var completions: [@MainActor @Sendable ([Float]?) -> Void] = []
    /// False acts as a model that is not loaded: each request gets nil at once.
    var isLoaded = true

    func nextTokens(after context: String, completion: @escaping @MainActor @Sendable ([Float]?) -> Void) {
        contexts.append(context)
        guard isLoaded else {
            completion(nil)
            return
        }
        completions.append(completion)
    }

    /// Answers the oldest request that waits, as the model's thread does, with numbers or with nil.
    func answer(_ numbers: [Float]?) {
        precondition(!completions.isEmpty, "no request waits for an answer")
        completions.removeFirst()(numbers)
    }

    var waitingCount: Int { completions.count }
}

/// The engine with the word table of the bundle: the order of the predicted words by the
/// numbers of a language model (`duo_predict_english_with_model`). The tests build the numbers
/// by hand, so no model runs.
@MainActor
final class ModelWordOrderTests: XCTestCase {
    private static let lexicon = TypingLexicon(resource: "lexicon-english", fullCheck: false)
    private static let engine = EnglishTypingEngine(
        lexicon: lexicon, supplement: TypingLexicon(resource: "supplement-ai-software", fullCheck: false),
        wordTable: WordTable(resource: EngineSpellChecker.wordTableResource))

    /// Numbers that give every token the log probability -30, and each named form of a word a
    /// higher one: -1 for the first, -2 for the second, and so on.
    static func numbers(
        favoring forms: [(word: String, form: Int32)], engine: EnglishTypingEngine, file: StaticString = #filePath,
        line: UInt = #line
    ) throws -> [Float] {
        let vocabulary = try XCTUnwrap(engine.wordTableVocabulary, file: file, line: line)
        var numbers = [Float](repeating: -30, count: vocabulary)
        for (place, entry) in forms.enumerated() {
            let token = try XCTUnwrap(
                engine.firstToken(ofWord: entry.word, form: entry.form), "\(entry.word) has no form \(entry.form)",
                file: file, line: line)
            numbers[token] = -Float(place + 1)
        }
        return numbers
    }

    func testTheWordTableOfTheBundleBelongsToTheLexiconAndTheWorkArea() {
        XCTAssertTrue(Self.engine.wordTableBelongsToTheLexicon)
        // The shipped model has 49,152 tokens (`LanguageModelScorerTests`).
        XCTAssertEqual(Self.engine.wordTableVocabulary, 49152)
        // Without the work area the table is not the table of the words that the engine reads.
        let plain = EnglishTypingEngine(
            lexicon: Self.lexicon, wordTable: WordTable(resource: EngineSpellChecker.wordTableResource))
        XCTAssertFalse(plain.wordTableBelongsToTheLexicon)
    }

    func testTheWordOfTheMostLikelyTokenComesFirst() throws {
        let numbers = try Self.numbers(
            favoring: [("tonight", DUO_FORM_LOWER), ("tomorrow", DUO_FORM_LOWER)], engine: Self.engine)
        let words = try XCTUnwrap(Self.engine.predictedWords(
            previousWord: "you", typed: "to", next: numbers, engineWeight: 0, capitalOnly: false, limit: 20))
        XCTAssertEqual(words.count, 20)
        XCTAssertEqual(words.first, EnglishTypingEngine.ModelWord(word: "tonight", form: DUO_FORM_LOWER))
        XCTAssertTrue(words.allSatisfy { $0.word.hasPrefix("to") && $0.word.count > 2 }, "\(words)")
        XCTAssertEqual(Set(words.map(\.word)).count, words.count, "\(words)")
        // Without a typed letter the same numbers order every word.
        let next = try XCTUnwrap(Self.engine.predictedWords(
            previousWord: "you", typed: "", next: numbers, engineWeight: 0, capitalOnly: false, limit: 3))
        XCTAssertEqual(next.first?.word, "tonight")
    }

    func testTheModelPicksTheFormOfAWord() throws {
        // The capital form of "python" is more likely than its lower-case form.
        let numbers = try Self.numbers(
            favoring: [("python", DUO_FORM_CAPITAL), ("python", DUO_FORM_LOWER)], engine: Self.engine)
        let words = try XCTUnwrap(Self.engine.predictedWords(
            previousWord: "use", typed: "py", next: numbers, engineWeight: 0, capitalOnly: false, limit: 5))
        XCTAssertEqual(words.first, EnglishTypingEngine.ModelWord(word: "python", form: DUO_FORM_CAPITAL))
        // A word of the work area has its preferred capitals as a third form.
        let preferred = try Self.numbers(favoring: [("pytorch", DUO_FORM_PREFERRED)], engine: Self.engine)
        let area = try XCTUnwrap(Self.engine.predictedWords(
            previousWord: "use", typed: "py", next: preferred, engineWeight: 0, capitalOnly: false, limit: 5))
        XCTAssertEqual(area.first, EnglishTypingEngine.ModelWord(word: "pytorch", form: DUO_FORM_PREFERRED))
    }

    func testATypedCapitalAllowsOnlyFormsWithACapital() throws {
        // The lower-case form is the most likely one, and a typed capital rules it out.
        let numbers = try Self.numbers(
            favoring: [("tomorrow", DUO_FORM_LOWER), ("today", DUO_FORM_CAPITAL)], engine: Self.engine)
        let free = try XCTUnwrap(Self.engine.predictedWords(
            previousWord: "", typed: "to", next: numbers, engineWeight: 0, capitalOnly: false, limit: 5))
        XCTAssertEqual(free.first, EnglishTypingEngine.ModelWord(word: "tomorrow", form: DUO_FORM_LOWER))
        let capital = try XCTUnwrap(Self.engine.predictedWords(
            previousWord: "", typed: "to", next: numbers, engineWeight: 0, capitalOnly: true, limit: 5))
        XCTAssertEqual(capital.first, EnglishTypingEngine.ModelWord(word: "today", form: DUO_FORM_CAPITAL))
        XCTAssertFalse(capital.contains { $0.form == DUO_FORM_LOWER && $0.word != "i" && !$0.word.hasPrefix("i'") }, "\(capital)")
    }

    func testAnEngineWeightOfOneGivesTheEnginesOrder() throws {
        let numbers = try Self.numbers(favoring: [("tonight", DUO_FORM_LOWER)], engine: Self.engine)
        for (previous, typed) in [("you", "to"), ("thank", "y"), ("", "wh"), ("see", "")] {
            let mixed = try XCTUnwrap(Self.engine.predictedWords(
                previousWord: previous, typed: typed, next: numbers, engineWeight: 1, capitalOnly: false, limit: 20))
            XCTAssertEqual(
                mixed.map(\.word), Self.engine.predictedWords(previousWord: previous, typed: typed, limit: 20),
                "\(previous) \(typed)")
        }
    }

    func testNumbersOfAnotherVocabularyAndAnEngineWithoutATableGiveNil() throws {
        let numbers = try Self.numbers(favoring: [], engine: Self.engine)
        XCTAssertNil(Self.engine.predictedWords(
            previousWord: "", typed: "to", next: Array(numbers.dropLast()), engineWeight: 0, capitalOnly: false, limit: 5))
        let plain = EnglishTypingEngine(lexicon: Self.lexicon)
        XCTAssertNil(plain.predictedWords(
            previousWord: "", typed: "to", next: numbers, engineWeight: 0, capitalOnly: false, limit: 5))
        XCTAssertNil(plain.firstToken(ofWord: "today", form: DUO_FORM_LOWER))
        XCTAssertNil(Self.engine.firstToken(ofWord: "qqqqzz", form: DUO_FORM_LOWER))
        // A word of the lexicon alone has no preferred form.
        XCTAssertNil(Self.engine.firstToken(ofWord: "today", form: DUO_FORM_PREFERRED))
    }
}

/// The prediction strip with the order of the language model. The keyboard's own spell checker
/// asks a stand-in model for the numbers of the text before the word. Until the numbers are
/// there, the strip shows the engine's order.
@MainActor
final class ModelPredictedWordsTests: XCTestCase {
    private static let storeName = "ModelPredictedWordsTests"
    private var keyboardView: KeyboardView!
    private var document: FakeDocument!
    private var predictor: StandInPredictor!
    private var engine: EnglishTypingEngine!
    private var checker: EngineSpellChecker!
    private var controller: KeyboardTextController!

    override func setUp() {
        super.setUp()
        UserDefaults().removePersistentDomain(forName: Self.storeName)
    }

    override func tearDown() {
        UserDefaults().removePersistentDomain(forName: Self.storeName)
        super.tearDown()
    }

    private func makeKeyboard(before: String) {
        keyboardView = KeyboardView(frame: CGRect(x: 0, y: 0, width: 466, height: 280))
        document = FakeDocument(before: before)
        predictor = StandInPredictor()
        engine = EnglishTypingEngine(
            lexicon: TypingLexicon(resource: "lexicon-english", fullCheck: false),
            wordTable: WordTable(resource: EngineSpellChecker.wordTableResource))
        checker = EngineSpellChecker(
            engine: engine, reranker: nil, store: UserDefaults(suiteName: Self.storeName)!, workArea: .aiAndSoftware(),
            predictor: predictor)
        controller = KeyboardTextController(
            keyboardView: keyboardView, document: document, spellChecker: checker,
            pinyinEngine: { PinyinEngine(dictionaryText: testDictionary) })
        controller.documentDidChange()
    }

    private func type(_ text: String) {
        for character in text {
            controller.keyboardView(keyboardView, insert: String(character))
        }
    }

    private func numbers(favoring forms: [(word: String, form: Int32)]) throws -> [Float] {
        try ModelWordOrderTests.numbers(favoring: forms, engine: engine)
    }

    /// The engine's order as the strip writes it: each word in the form that the typed letters
    /// ask for, as "I" for "i".
    private func enginesOrder(previousWord: String, typed: String) -> [String] {
        engine.predictedWords(previousWord: previousWord, typed: typed.lowercased(), limit: 20).map {
            KeyboardTextLogic.predictedWord($0, typed: typed)
        }
    }

    func testTheStripShowsTheEnginesOrderUntilTheModelAnswers() throws {
        makeKeyboard(before: "See you ")
        // The model reads the text before the word, without the space at its end.
        XCTAssertEqual(predictor.contexts, ["See you"])
        XCTAssertEqual(keyboardView.predictedWords, enginesOrder(previousWord: "you", typed: ""))
        predictor.answer(try numbers(favoring: [("tonight", DUO_FORM_LOWER), ("soon", DUO_FORM_LOWER)]))
        XCTAssertEqual(Array(keyboardView.predictedWords.prefix(2)), ["tonight", "soon"])
        XCTAssertEqual(keyboardView.predictedWords.count, 20)
    }

    func testTypedLettersFilterTheModelsOrderWithoutANewRequest() throws {
        makeKeyboard(before: "See you ")
        predictor.answer(try numbers(favoring: [("soon", DUO_FORM_LOWER), ("tonight", DUO_FORM_LOWER), ("tomorrow", DUO_FORM_LOWER)]))
        type("t")
        XCTAssertEqual(Array(keyboardView.predictedWords.prefix(2)), ["tonight", "tomorrow"])
        type("o")
        XCTAssertEqual(Array(keyboardView.predictedWords.prefix(2)), ["tonight", "tomorrow"])
        XCTAssertTrue(keyboardView.predictedWords.allSatisfy { $0.hasPrefix("to") }, "\(keyboardView.predictedWords)")
        // The text before the word did not change, so the model was asked once.
        XCTAssertEqual(predictor.contexts, ["See you"])
    }

    func testATapAsksTheModelForTheNextWord() throws {
        makeKeyboard(before: "See you ")
        predictor.answer(try numbers(favoring: [("tonight", DUO_FORM_LOWER)]))
        let entry = try XCTUnwrap(keyboardView.predictionStrip.entries.first)
        entry.sendActions(for: .touchDown)
        entry.sendActions(for: .touchUpInside)
        XCTAssertEqual(document.text, "See you tonight ")
        XCTAssertEqual(predictor.contexts, ["See you", "See you tonight"])
        predictor.answer(try numbers(favoring: [("then", DUO_FORM_LOWER)]))
        XCTAssertEqual(keyboardView.predictedWords.first, "then")
    }

    func testTheModelsFormOfAWordShows() throws {
        makeKeyboard(before: "I use ")
        predictor.answer(try numbers(favoring: [
            ("python", DUO_FORM_CAPITAL), ("pytorch", DUO_FORM_PREFERRED), ("i", DUO_FORM_LOWER), ("the", DUO_FORM_LOWER),
        ]))
        XCTAssertEqual(Array(keyboardView.predictedWords.prefix(4)), ["Python", "PyTorch", "I", "the"])
        // A tap types the word in that form.
        let entry = try XCTUnwrap(keyboardView.predictionStrip.entries.first)
        entry.sendActions(for: .touchDown)
        entry.sendActions(for: .touchUpInside)
        XCTAssertEqual(document.text, "I use Python ")
    }

    func testATypedCapitalShowsFormsWithACapital() throws {
        makeKeyboard(before: "See you. ")
        // After a mark, no word comes before the cursor, so the strip is empty and asks nothing.
        XCTAssertEqual(predictor.contexts, [])
        type("T")
        XCTAssertEqual(predictor.contexts, ["See you."])
        predictor.answer(try numbers(favoring: [("tomorrow", DUO_FORM_LOWER), ("thanks", DUO_FORM_CAPITAL), ("the", DUO_FORM_CAPITAL)]))
        XCTAssertEqual(Array(keyboardView.predictedWords.prefix(2)), ["Thanks", "The"])
        XCTAssertTrue(keyboardView.predictedWords.allSatisfy { $0.first?.isUppercase == true }, "\(keyboardView.predictedWords)")
    }

    func testLettersInCapitalsGiveWordsInCapitals() throws {
        makeKeyboard(before: "See you ")
        predictor.answer(try numbers(favoring: [("tonight", DUO_FORM_CAPITAL)]))
        type("TO")
        XCTAssertEqual(keyboardView.predictedWords.first, "TONIGHT")
    }

    func testTheFirstWordOfAFieldKeepsTheEnginesOrder() {
        makeKeyboard(before: "")
        type("to")
        XCTAssertEqual(predictor.contexts, [])
        XCTAssertEqual(keyboardView.predictedWords, enginesOrder(previousWord: "", typed: "to"))
    }

    func testAModelThatIsNotLoadedLeavesTheEnginesOrder() {
        makeKeyboard(before: "")
        predictor.isLoaded = false
        type("See you ")
        XCTAssertEqual(keyboardView.predictedWords, enginesOrder(previousWord: "you", typed: ""))
        // The same text is asked once, also when no numbers came.
        type("t")
        XCTAssertEqual(predictor.contexts.filter { $0 == "See you" }.count, 1)
        XCTAssertEqual(keyboardView.predictedWords, enginesOrder(previousWord: "you", typed: "t"))
    }

    func testAnAnswerForAnEarlierTextChangesNothing() throws {
        makeKeyboard(before: "See you ")
        type("soon ")
        XCTAssertEqual(predictor.contexts, ["See you", "See you soon"])
        let before = keyboardView.predictedWords
        // The answer for "See you" comes late. The strip predicts for "See you soon" now.
        predictor.answer(try numbers(favoring: [("tonight", DUO_FORM_LOWER)]))
        XCTAssertEqual(keyboardView.predictedWords, before)
        predictor.answer(try numbers(favoring: [("enough", DUO_FORM_LOWER)]))
        XCTAssertEqual(keyboardView.predictedWords.first, "enough")
    }

    func testTheEngineWeightAndTheFormRuleAreSettings() throws {
        makeKeyboard(before: "I use ")
        checker.predictionSettings = EngineSpellChecker.PredictionSettings(engineWeight: 1, modelPicksTheForm: false)
        predictor.answer(try numbers(favoring: [("python", DUO_FORM_CAPITAL)]))
        // With the weight 1 the engine's values order the words, and the typed capitals give the form.
        XCTAssertEqual(keyboardView.predictedWords, enginesOrder(previousWord: "use", typed: ""))
        checker.predictionSettings = EngineSpellChecker.PredictionSettings(engineWeight: 0, modelPicksTheForm: false)
        controller.documentDidChange()
        XCTAssertEqual(keyboardView.predictedWords.first, "python")
    }
}
