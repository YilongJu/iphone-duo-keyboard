import UIKit
import XCTest

@testable import DuoKeyboard

/// Tests of the reuse of the model's cache between requests (docs/kv-reuse-design.md), with the
/// model file of the app bundle. The model of these tests has the check of the cache with the
/// tolerance 0: after each request the scorer reads the same window and candidates again from an
/// empty cache, and a request whose numbers differ in any bit fails.
@MainActor
final class LanguageModelCacheTests: XCTestCase {
    private static var checked: KeyboardLanguageModel?

    private func model() throws -> KeyboardLanguageModel {
        if let checked = Self.checked { return checked }
        let model = KeyboardLanguageModel.bundled(cacheCheckTolerance: 0)
        do {
            try model.loadNow()
        } catch let error as LanguageModelError {
            XCTFail("the bundled language model did not load with the check: \(error.reason)")
            throw error
        }
        Self.checked = model
        return model
    }

    private func info() throws -> duo_lm_scorer_info {
        try XCTUnwrap(model().scorerInfo)
    }

    @discardableResult
    private func scores(_ prompt: LanguageModelPrompt, file: StaticString = #filePath, line: UInt = #line) throws
        -> [CandidateScore]
    {
        let result = try model().score(prompt)
        guard case .scores(let scores) = result else {
            XCTFail("the model did not score \(prompt.candidates) after \"\(prompt.context)\": \(result)", file: file, line: line)
            throw CocoaError(.featureUnsupported)
        }
        return scores
    }

    private func typed(_ before: String, _ span: String, _ readings: [String]) -> LanguageModelPrompt {
        LanguageModelPrompt.make(textBefore: before, typed: span, readings: readings)!
    }

    func testTheKeyboardReusesTheCache() {
        XCTAssertEqual(KeyboardLanguageModel.reuse.mode, DUO_LM_REUSE_PREFIX)
        XCTAssertEqual(KeyboardLanguageModel.reuse.slots, 1)
    }

    func testTheNextSpacePressReadsOnlyTheTokensAfterTheSharedStart() throws {
        let start = "I missed the early train this morning, so I think I will have to go to the office "
        try scores(typed(start, "by bys", ["by bus", "by bys", "by buys"]))
        let before = try info()
        try scores(typed(start + "by bus ", "and then", ["and then", "and than"]))
        let after = try info()
        // The two windows share the start token and every token of `start`.
        let reused = after.window_tokens_reused - before.window_tokens_reused
        let window = after.window_tokens - before.window_tokens
        XCTAssertGreaterThan(reused, 15, "\(reused) of \(window) window tokens came from the cache")
        XCTAssertLessThanOrEqual(reused, window - 2, "the model reads the last two tokens of a window at least")
        XCTAssertEqual(after.checked_requests - before.checked_requests, 1)
    }

    func testTheCacheGivesTheNumbersOfAFreshReadThroughTheEventsOfTheKeyboard() throws {
        let field = "We met at the station and walked to the old bridge "
        let before = try info()
        // Typing: each space press grows the text before the span.
        try scores(typed(field, "aftre", ["after", "aftre", "afire"]))
        try scores(typed(field + "after ", "lunch we", ["lunch we", "lunch wee"]))
        // A correction of the previous word: the text before the span ends in another word.
        try scores(typed(field + "afire ", "lunch we", ["lunch we", "lunch wee"]))
        // The apostrophe step: the stock prompt of the same text, then the typed prompt again.
        try scores(LanguageModelPrompt.makeStock(textBefore: field + "after lunch ", readings: ["we're", "were"]))
        try scores(typed(field + "after lunch ", "were going", ["we're going", "were going"]))
        // Delete: a shorter text before the span.
        try scores(typed("We met at the station and ", "walkde", ["walked", "walkde"]))
        // A cursor move: the text before the cursor ends in the middle of the field.
        try scores(typed("We met at ", "teh", ["the", "teh", "tech"]))
        // Paste: a long text appears before the span.
        let pasted = "We met at the station. The train was late again, as it is most days in the winter, "
            + "and the people on the platform stood close together to keep warm while they waited "
        try scores(typed(pasted, "for th", ["for the", "for th", "for tho"]))
        // A change of field: another text.
        try scores(typed("Dear Anna, thank you for your ", "lettr", ["letter", "lettr"]))
        // A line break in the text.
        try scores(typed("Dear Anna,\nthank you for your ", "lettr", ["letter", "lettr"]))
        // An empty field.
        try scores(typed("", "helo", ["hello", "helo", "help"]))
        try scores(typed("Hello ", "tehre", ["there", "tehre"]))
        // The stock prompt of an empty field: a window of the start token alone, which a call of
        // one token reads, and then a longer window, which reads the start token again.
        try scores(LanguageModelPrompt.makeStock(textBefore: "", readings: ["we're", "were"]))
        try scores(typed("We're ", "goign", ["going", "goign"]))
        let after = try info()
        XCTAssertEqual(after.checked_requests - before.checked_requests, 15)
        XCTAssertGreaterThan(after.window_tokens_reused, before.window_tokens_reused)
        XCTAssertEqual(after.checked_widest, 0)
    }

    func testAWindowThatMovesKeepsTheNumbersOfAFreshRead() throws {
        // More than 96 tokens before the span, so each press moves the 96-token window.
        var text = ""
        for sentence in 0..<12 {
            text += "On day \(sentence) we walked along the river and talked about the weather. "
        }
        let before = try info()
        for word in ["then", "we", "took", "the", "bus", "home"] {
            try scores(typed(text, word + "x", [word, word + "x"]))
            text += word + " "
        }
        let after = try info()
        XCTAssertEqual(after.checked_requests - before.checked_requests, 6)
        XCTAssertEqual(after.checked_widest, 0)
    }

    func testARefusedRequestLeavesTheCacheReady() throws {
        let model = try model()
        let start = "The meeting starts at nine and ends at "
        try scores(typed(start, "tne", ["ten", "tne"]))
        let tooLong = " " + String(repeating: "zq", count: 60)
        guard case .refused = model.score(LanguageModelPrompt(context: start + "| tne |", candidates: [tooLong])) else {
            return XCTFail("a candidate of more than 32 tokens must be refused")
        }
        let before = try info()
        try scores(typed(start + "ten ", "in teh", ["in the", "in teh"]))
        let after = try info()
        XCTAssertGreaterThan(after.window_tokens_reused - before.window_tokens_reused, 5)
        XCTAssertEqual(after.checked_widest, 0)
    }

    func testTypingWithEditsThroughTheControllerGivesTheNumbersOfAFreshRead() throws {
        let model = try model()
        let storeName = "LanguageModelCacheTests"
        UserDefaults().removePersistentDomain(forName: storeName)
        let store = try XCTUnwrap(UserDefaults(suiteName: storeName))
        let reranker = EnglishReranker(scorer: model, rule: KeyboardLanguageModel.rule)
        var errors: [String] = []
        reranker.onModelError = { errors.append($0) }
        let spellChecker = EngineSpellChecker(
            engine: EnglishTypingEngine(lexicon: TypingLexicon(resource: "lexicon-english", fullCheck: false)),
            reranker: reranker, store: store)
        let before = try info()

        func makeController(_ document: FakeDocument) -> (KeyboardView, KeyboardTextController) {
            let keyboardView = KeyboardView()
            let controller = KeyboardTextController(
                keyboardView: keyboardView, document: document, spellChecker: spellChecker,
                pinyinEngine: { PinyinEngine(dictionaryText: testDictionary) })
            return (keyboardView, controller)
        }
        func type(_ text: String, _ view: KeyboardView, _ controller: KeyboardTextController) {
            for character in text {
                controller.keyboardView(view, insert: String(character))
            }
        }

        let document = FakeDocument(before: "")
        let (view, controller) = makeController(document)
        type("we walkde to teh station and waited for the trian to arive ", view, controller)
        // One delete right after a correction brings the typed word back, and more deletes take
        // letters away.
        for _ in 0..<4 { controller.keyboardViewDeleteBackward(view) }
        type("ive and then we lfet ", view, controller)
        // A cursor move into the middle of the field, and typing there.
        document.moveCursor(byUTF16Offset: -10)
        type("qucikly ", view, controller)
        document.moveCursor(byUTF16Offset: 10)
        // A paste.
        document.insertText("The platform was full of people who had waited for an hour in the cold. ")
        type("nobdy knew wehn it would come ", view, controller)
        // Chinese mode and back.
        controller.keyboardView(view, edit: .toggleLanguage)
        type("nihao ", view, controller)
        controller.keyboardView(view, edit: .toggleLanguage)
        type("then we went hmoe ", view, controller)
        // Another field.
        let other = FakeDocument(before: "Dear Anna, thank you for your ")
        let (otherView, otherController) = makeController(other)
        type("lettr and the photso ", otherView, otherController)

        let after = try info()
        let statistics = reranker.statistics
        XCTAssertEqual(errors, [])
        XCTAssertEqual(statistics.failedCount, 0, statistics.lastProblem ?? "")
        XCTAssertGreaterThan(statistics.readCount, 10)
        XCTAssertEqual(after.checked_requests - before.checked_requests, after.requests - before.requests)
        XCTAssertGreaterThan(after.window_tokens_reused, before.window_tokens_reused)
        XCTAssertEqual(after.checked_widest, 0)
    }

    func testTheReportNamesTheShareOfReusedContextTokens() throws {
        let model = try model()
        try scores(typed("The report of the test names the ", "shrae", ["share", "shrae"]))
        let lines = model.reportLines(statistics: RerankStatistics())
        let line = try XCTUnwrap(lines.first { $0.contains("context tokens reused from the cache") }, "\(lines)")
        XCTAssertTrue(line.hasPrefix("reranker    "), line)
        XCTAssertTrue(line.contains("reuse mode prefix, 1 slots"), line)
        XCTAssertTrue(line.contains("%)"), line)
    }
}
