import UIKit
import XCTest

@testable import DuoKeyboard

/// Runs the keyboard's own typing code over the test cases in scripts/typing-evaluation/cases and
/// writes what the keyboard produced, one JSON object per line, for scripts/typing-evaluation/score.py.
///
/// The test runs only when the environment names an input folder and an output folder:
/// `TYPING_CASES_DIR` holds the case files, and `TYPING_OUTPUT_DIR` receives the outputs.
/// `xcodebuild test` passes a variable to the test process when its name starts with `TEST_RUNNER_`.
@MainActor
final class TypingEvaluationTests: XCTestCase {
    private struct EnglishCase: Decodable {
        let id: String
        let context: String
        let typed: String
    }

    private struct PinyinCase: Decodable {
        let id: String
        let typed: String
    }

    private struct Output: Encodable {
        let id: String
        let output: String
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

    private func loadCases<Case: Decodable>(_ type: Case.Type, from url: URL) throws -> [Case] {
        let decoder = JSONDecoder()
        return try String(contentsOf: url, encoding: .utf8)
            .split(separator: "\n")
            .map { try decoder.decode(Case.self, from: Data($0.utf8)) }
    }

    private func write(_ outputs: [Output], to url: URL) throws {
        let encoder = JSONEncoder()
        let lines = try outputs.map { String(decoding: try encoder.encode($0), as: UTF8.self) }
        try (lines.joined(separator: "\n") + "\n").write(to: url, atomically: true, encoding: .utf8)
    }

    /// Types each English case through the typing controller: the context is already in the
    /// field, then come the typed characters and one space, as a person would type them.
    func testEnglishCasesThroughTheTypingController() throws {
        let (casesFolder, outputFolder) = try folders()
        for half in ["dev", "test"] {
            let cases = try loadCases(EnglishCase.self, from: casesFolder.appendingPathComponent("english.\(half).jsonl"))
            var outputs: [Output] = []
            let spellChecker = EngineSpellChecker(
                engine: EnglishTypingEngine(lexicon: TypingLexicon(resource: "lexicon-english", fullCheck: false)))
            for item in cases {
                let before = item.context.isEmpty ? "" : item.context + " "
                let document = FakeDocument(before: before)
                let keyboardView = KeyboardView()
                let controller = KeyboardTextController(
                    keyboardView: keyboardView, document: document, spellChecker: spellChecker,
                    pinyinEngine: { PinyinEngine(dictionaryText: "") })
                for character in item.typed + " " {
                    controller.keyboardView(keyboardView, insert: String(character))
                }
                let produced = String(document.text.dropFirst(before.count)).trimmingCharacters(in: .whitespaces)
                outputs.append(Output(id: item.id, output: produced))
            }
            try write(outputs, to: outputFolder.appendingPathComponent("english.\(half).jsonl"))
        }
    }

    /// Types each Pinyin case into the Pinyin engine and takes the first candidate again and
    /// again, as the space bar does, until every typed letter is used.
    func testPinyinCasesThroughThePinyinEngine() throws {
        let (casesFolder, outputFolder) = try folders()
        let engine = PinyinEngine.bundled()
        for half in ["dev", "test"] {
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
