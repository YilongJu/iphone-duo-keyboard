import UIKit
import XCTest

@testable import DuoKeyboard

/// Runs the keyboard's own typing code over the test cases in scripts/typing-evaluation/cases and
/// writes what the keyboard produced, one JSON object per line, for scripts/typing-evaluation/score.py.
///
/// The test runs only when the environment names an input folder and an output folder:
/// `TYPING_CASES_DIR` holds the case files, and `TYPING_OUTPUT_DIR` receives the outputs.
/// `TYPING_HALVES` names the halves to type, "dev", "test" or "dev test", and without it the
/// test types both. `xcodebuild test` passes a variable to the test process when its name
/// starts with `TEST_RUNNER_`.
///
/// The English cases go through the keyboard as it ships, with the bundled language model
/// re-ranking the engine's readings, into `<name>.<half>.jsonl`. A model that does not load
/// fails the test. The same cases also go through the engine alone, as the keyboard types
/// before its model is ready, into `<name>.<half>.engine-only.jsonl`. Every correction that
/// went to the model is written to `<name>.<half>.trace.jsonl`, for scripts/lm-keyboard/compare.py.
@MainActor
final class TypingEvaluationTests: XCTestCase {
    private struct EnglishCase: Decodable {
        let id: String
        let context: String
        let typed: String
    }

    /// A case of english-apostrophe-words.*.jsonl, with the word after the target word.
    private struct ApostropheCase: Decodable {
        let id: String
        let context: String
        let typed: String
        let nextWord: String

        enum CodingKeys: String, CodingKey {
            case id, context, typed
            case nextWord = "next_word"
        }
    }

    private struct PinyinCase: Decodable {
        let id: String
        let typed: String
    }

    private struct Output: Encodable {
        let id: String
        let output: String
    }

    /// One correction that went to the model, in the field names of scripts/lm-keyboard/harness_trace.py.
    private struct TraceLine: Encodable {
        let id: String
        let step: Int
        let textBefore: String
        let context: String
        let readings: [TraceReading]
        /// "scores", or the reason the model gave no scores.
        let result: String
        let choice: String
        let milliseconds: Double
    }

    private struct TraceReading: Encodable {
        let text: String
        let candidate: String
        let engineScore: Double
        let slipCost: Double
        let asTyped: Bool
        let chosen: Bool
        let logProbability: Double?
        let spaceAfter: Double?
        /// The scores of the apostrophe step in its stock prompt, for the readings it asked about.
        let stepLogProbability: Double?
        let stepSpaceAfter: Double?
    }

    /// Collects the trace lines of one run, with the case that is typed now.
    private final class TraceRecorder {
        var caseID = ""
        var step = 0
        var lines: [TraceLine] = []

        func record(_ trace: RerankTrace) {
            var scores: [CandidateScore]?
            let result: String
            switch trace.result {
            case .scores(let values):
                scores = values
                result = "scores"
            case .notReady(let reason): result = "not ready: \(reason)"
            case .refused(let reason): result = "refused: \(reason)"
            case .failed(let reason): result = "model error: \(reason)"
            }
            let readings = trace.readings.indices.map { index in
                TraceReading(
                    text: trace.readings[index].text, candidate: trace.prompt.candidates[index],
                    engineScore: trace.readings[index].score, slipCost: trace.readings[index].slipCost,
                    asTyped: trace.readings[index].asTyped,
                    chosen: trace.readings[index].chosen, logProbability: scores?[index].logProbability,
                    spaceAfter: scores?[index].spaceAfter, stepLogProbability: trace.stepScores[index]?.logProbability,
                    stepSpaceAfter: trace.stepScores[index]?.spaceAfter)
            }
            lines.append(TraceLine(
                id: caseID, step: step, textBefore: trace.textBefore, context: trace.prompt.context, readings: readings,
                result: result, choice: trace.readings[trace.choice].text, milliseconds: trace.milliseconds))
            step += 1
        }
    }

    /// The bundled model, loaded once for every English run of this process.
    private static var model: KeyboardLanguageModel?

    private func loadedModel() throws -> KeyboardLanguageModel {
        if let model = Self.model { return model }
        let model = KeyboardLanguageModel.bundled()
        do {
            try model.loadNow()
        } catch let error as LanguageModelError {
            XCTFail("the bundled language model did not load: \(error.reason)")
            throw error
        }
        Self.model = model
        return model
    }

    private func folders() throws -> (cases: URL, output: URL) {
        let environment = ProcessInfo.processInfo.environment
        guard let cases = environment["TYPING_CASES_DIR"], let output = environment["TYPING_OUTPUT_DIR"] else {
            throw XCTSkip("TYPING_CASES_DIR and TYPING_OUTPUT_DIR are not set")
        }
        let outputURL = URL(fileURLWithPath: output)
        try FileManager.default.createDirectory(at: outputURL, withIntermediateDirectories: true)
        return (URL(fileURLWithPath: cases), outputURL)
    }

    private func halves() throws -> [String] {
        guard let value = ProcessInfo.processInfo.environment["TYPING_HALVES"] else { return ["dev", "test"] }
        let halves = value.split(separator: " ").map(String.init)
        guard !halves.isEmpty, halves.allSatisfy({ $0 == "dev" || $0 == "test" }) else {
            XCTFail("TYPING_HALVES must name dev, test or both, and it is \"\(value)\"")
            throw CocoaError(.featureUnsupported)
        }
        return halves
    }

    private func loadCases<Case: Decodable>(_ type: Case.Type, from url: URL) throws -> [Case] {
        let decoder = JSONDecoder()
        return try String(contentsOf: url, encoding: .utf8)
            .split(separator: "\n")
            .map { try decoder.decode(Case.self, from: Data($0.utf8)) }
    }

    private func write<Line: Encodable>(_ lines: [Line], to url: URL) throws {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        encoder.nonConformingFloatEncodingStrategy = .convertToString(
            positiveInfinity: "inf", negativeInfinity: "-inf", nan: "nan")
        let text = try lines.map { String(decoding: try encoder.encode($0), as: UTF8.self) }
        try (text.joined(separator: "\n") + "\n").write(to: url, atomically: true, encoding: .utf8)
    }

    /// Types each English case through the typing controller: the context is already in the
    /// field, then come the typed characters and one space, as a person would type them.
    func testEnglishCasesThroughTheTypingController() throws {
        try typeEnglishCases(named: "english")
    }

    /// The cases with a symbol or digit key in place of a letter have their own files. A cases
    /// folder without those files skips them.
    func testEnglishSymbolCasesThroughTheTypingController() throws {
        let (casesFolder, _) = try folders()
        let first = casesFolder.appendingPathComponent("english-symbols.dev.jsonl")
        guard FileManager.default.fileExists(atPath: first.path) else {
            throw XCTSkip("english-symbols.dev.jsonl is not in the cases folder")
        }
        try typeEnglishCases(named: "english-symbols")
    }

    private func type(_ cases: [EnglishCase], with spellChecker: SpellChecking, before: (EnglishCase) -> Void) -> [Output] {
        cases.map { item in
            before(item)
            let start = item.context.isEmpty ? "" : item.context + " "
            let document = FakeDocument(before: start)
            let keyboardView = KeyboardView()
            let controller = KeyboardTextController(
                keyboardView: keyboardView, document: document, spellChecker: spellChecker,
                pinyinEngine: { PinyinEngine(dictionaryText: "") })
            for character in item.typed + " " {
                controller.keyboardView(keyboardView, insert: String(character))
            }
            let produced = String(document.text.dropFirst(start.count)).trimmingCharacters(in: .whitespaces)
            return Output(id: item.id, output: produced)
        }
    }

    private func typeEnglishCases(named name: String) throws {
        let (casesFolder, outputFolder) = try folders()
        let halves = try halves()
        let model = try loadedModel()
        let engine = EnglishTypingEngine(lexicon: TypingLexicon(resource: "lexicon-english", fullCheck: false))
        // The person keeps no word in these runs, and the words of other tests stay out.
        let storeName = "TypingEvaluationTests"
        UserDefaults().removePersistentDomain(forName: storeName)
        let store = try XCTUnwrap(UserDefaults(suiteName: storeName))
        for half in halves {
            let cases = try loadCases(EnglishCase.self, from: casesFolder.appendingPathComponent("\(name).\(half).jsonl"))

            let reranker = EnglishReranker(scorer: model, rule: KeyboardLanguageModel.rule)
            let recorder = TraceRecorder()
            reranker.onTrace = { recorder.record($0) }
            let shipping = EngineSpellChecker(engine: engine, reranker: reranker, store: store)
            let outputs = type(cases, with: shipping) { item in
                recorder.caseID = item.id
                recorder.step = 0
            }
            try write(outputs, to: outputFolder.appendingPathComponent("\(name).\(half).jsonl"))
            try write(recorder.lines, to: outputFolder.appendingPathComponent("\(name).\(half).trace.jsonl"))
            let report = model.reportLines(statistics: reranker.statistics).joined(separator: "\n") + "\n"
            try report.write(
                to: outputFolder.appendingPathComponent("\(name).\(half).reranker.txt"), atomically: true, encoding: .utf8)

            // Every correction with more than one reading must have gone through the model.
            let statistics = reranker.statistics
            XCTAssertEqual(statistics.notReadyCount + statistics.refusedCount + statistics.failedCount, 0,
                           "\(name) \(half): \(statistics.lastProblem ?? "")")
            XCTAssertEqual(statistics.readCount, recorder.lines.count, "\(name) \(half)")
            XCTAssertGreaterThan(statistics.readCount, 0, "\(name) \(half)")

            let engineOnly = EngineSpellChecker(engine: engine, reranker: nil, store: store)
            let engineOutputs = type(cases, with: engineOnly) { _ in }
            try write(engineOutputs, to: outputFolder.appendingPathComponent("\(name).\(half).engine-only.jsonl"))
        }
    }

    /// Types the words with and without an apostrophe in two ways: the typed word and a space,
    /// and then also the next word and a space, so the keyboard reads the two words together.
    /// The outputs go to `english-apostrophe-words.<half>.jsonl` and
    /// `english-apostrophe-words.<half>.next-word.jsonl`, with the model and with the engine alone.
    /// A cases folder without the files skips them.
    func testEnglishApostropheWordCasesThroughTheTypingController() throws {
        let (casesFolder, outputFolder) = try folders()
        let name = "english-apostrophe-words"
        guard FileManager.default.fileExists(atPath: casesFolder.appendingPathComponent("\(name).dev.jsonl").path) else {
            throw XCTSkip("\(name).dev.jsonl is not in the cases folder")
        }
        let model = try loadedModel()
        let engine = EnglishTypingEngine(lexicon: TypingLexicon(resource: "lexicon-english", fullCheck: false))
        let storeName = "TypingEvaluationTests"
        UserDefaults().removePersistentDomain(forName: storeName)
        let store = try XCTUnwrap(UserDefaults(suiteName: storeName))
        for half in try halves() {
            let cases = try loadCases(ApostropheCase.self, from: casesFolder.appendingPathComponent("\(name).\(half).jsonl"))
            for (suffix, withNextWord) in [("", false), (".next-word", true)] {
                let typedCases = cases.map {
                    EnglishCase(id: $0.id, context: $0.context, typed: withNextWord ? $0.typed + " " + $0.nextWord : $0.typed)
                }
                let reranker = EnglishReranker(scorer: model, rule: KeyboardLanguageModel.rule)
                let shipping = EngineSpellChecker(engine: engine, reranker: reranker, store: store)
                try write(type(typedCases, with: shipping) { _ in },
                          to: outputFolder.appendingPathComponent("\(name).\(half)\(suffix).jsonl"))
                let statistics = reranker.statistics
                XCTAssertEqual(statistics.notReadyCount + statistics.refusedCount + statistics.failedCount, 0,
                               "\(name) \(half)\(suffix): \(statistics.lastProblem ?? "")")
                XCTAssertGreaterThan(statistics.readCount, 0, "\(name) \(half)\(suffix)")
                let engineOnly = EngineSpellChecker(engine: engine, reranker: nil, store: store)
                try write(type(typedCases, with: engineOnly) { _ in },
                          to: outputFolder.appendingPathComponent("\(name).\(half)\(suffix).engine-only.jsonl"))
            }
        }
    }

    /// Types each Pinyin case into the Pinyin engine and takes the first candidate again and
    /// again, as the space bar does, until every typed letter is used.
    func testPinyinCasesThroughThePinyinEngine() throws {
        let (casesFolder, outputFolder) = try folders()
        let engine = PinyinEngine.bundled()
        for half in try halves() {
            let cases = try loadCases(PinyinCase.self, from: casesFolder.appendingPathComponent("pinyin.\(half).jsonl"))
            var outputs: [Output] = []
            for item in cases {
                var letters = item.typed
                var produced = ""
                while !letters.isEmpty {
                    guard let first = engine.candidates(for: letters).first, first.consumedLetters > 0 else {
                        // The engine has no candidate, so the letters go in as plain letters.
                        produced += letters
                        break
                    }
                    produced += first.word
                    letters.removeFirst(first.consumedLetters)
                }
                outputs.append(Output(id: item.id, output: produced))
            }
            try write(outputs, to: outputFolder.appendingPathComponent("pinyin.\(half).jsonl"))
        }
    }
}
