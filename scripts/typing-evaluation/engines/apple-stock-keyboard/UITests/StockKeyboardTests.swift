import UIKit
import XCTest

/// Types the evaluation cases on the software keyboard of the iOS Simulator and records the text
/// that the text view of the host app holds.
///
/// The test taps key positions on the screen. It never calls typeText, because typeText sends
/// key events the way a hardware keyboard does and skips the touch path of the keyboard.
///
/// The test reads these environment variables. `xcodebuild` passes a variable to the test process
/// when its name starts with `TEST_RUNNER_`.
/// - `EVAL_TASK`: `english` or `pinyin`.
/// - `EVAL_CASES_FILE`: a JSON Lines file with the cases to type.
/// - `EVAL_OUTPUT_DIR`: the folder that receives `detail.jsonl`, the accessibility trees and the screenshots.
/// - `EVAL_KEY_INTERVAL`: the key interval, the seconds between two touch-downs.
/// - `EVAL_TAP_MODE`: `paced` sends one synthesized event for each tap and waits for each event.
///   `paced-open` sends each event at its time and does not wait for the event before it.
///   `batch` sends the taps of one case as one synthesized event.
/// - `EVAL_INLINE_PREDICTION`: optional. The value `no` turns inline predictions off in the text view.
@MainActor
final class StockKeyboardTests: XCTestCase {
    private struct EvalCase: Decodable {
        let id: String
        let category: String
        let typed: String
        let context: String?
    }

    /// The state that the host app shows in its status label. FieldStatus in the host app
    /// explains each field.
    private struct FieldStatus: Decodable {
        let i: Int
        let m: Bool
        let t: String
        let c: String
        let e: Int
        let h: [String]
        let ht: [Int]
    }

    private typealias Read = (status: FieldStatus, met: Bool)

    private struct Key {
        let type: XCUIElement.ElementType
        let label: String
        let identifier: String
        let frame: CGRect
    }

    private struct Failure: Error, CustomStringConvertible {
        let description: String
        init(_ description: String) { self.description = description }
    }

    private enum TapMode: String {
        case paced
        case pacedOpen = "paced-open"
        case batch
    }

    /// Seconds a finger stays down on a key.
    private let hold = 0.06

    private var app: XCUIApplication!
    private var outputFolder: URL!
    private var tapMode = TapMode.paced
    private var keyInterval = 0.0
    private var letterCentres: [Character: CGPoint] = [:]
    private var spaceCentre = CGPoint.zero
    private var nextCentre = CGPoint.zero
    private var tapCount = 0
    private var statusReads = 0

    func testTypeCases() throws {
        let environment = ProcessInfo.processInfo.environment
        func variable(_ name: String) throws -> String {
            guard let value = environment[name] else {
                throw Failure("the environment variable \(name) is not set")
            }
            return value
        }
        let task = try variable("EVAL_TASK")
        guard task == "english" || task == "pinyin" else {
            throw Failure("EVAL_TASK must be english or pinyin, and the value is \(task)")
        }
        guard let mode = TapMode(rawValue: try variable("EVAL_TAP_MODE")) else {
            throw Failure("EVAL_TAP_MODE must be paced, paced-open or batch")
        }
        guard let interval = Double(try variable("EVAL_KEY_INTERVAL")), interval > hold else {
            throw Failure("EVAL_KEY_INTERVAL must be a number of seconds above \(hold)")
        }
        tapMode = mode
        keyInterval = interval
        continueAfterFailure = true
        outputFolder = URL(fileURLWithPath: try variable("EVAL_OUTPUT_DIR"))
        try FileManager.default.createDirectory(at: outputFolder, withIntermediateDirectories: true)

        let decoder = JSONDecoder()
        let cases = try String(contentsOfFile: try variable("EVAL_CASES_FILE"), encoding: .utf8)
            .split(separator: "\n")
            .map { try decoder.decode(EvalCase.self, from: Data($0.utf8)) }
        print("EVAL_START task=\(task) mode=\(mode.rawValue) key_interval=\(interval) cases=\(cases.count)")

        app = XCUIApplication()
        let contexts = cases.map { $0.context ?? "" }
        let contextsJSON = try JSONEncoder().encode(contexts)
        app.launchEnvironment["EVAL_CONTEXTS_JSON"] = String(decoding: contextsJSON, as: UTF8.self)
        if let inlinePrediction = environment["EVAL_INLINE_PREDICTION"] {
            app.launchEnvironment["EVAL_INLINE_PREDICTION"] = inlinePrediction
        }
        app.launch()

        try findKeyboard()
        try warmUp(task: task)

        let detailURL = outputFolder.appendingPathComponent("detail.jsonl")
        FileManager.default.createFile(atPath: detailURL.path, contents: nil)
        let detailFile = try FileHandle(forWritingTo: detailURL)
        defer { try? detailFile.close() }

        let runStart = Date()
        tapCount = 0
        statusReads = 0
        for (index, item) in cases.enumerated() {
            let caseStart = Date()
            var record: [String: Any] = ["id": item.id, "category": item.category, "typed": item.typed]
            if let context = item.context {
                record["context"] = context
            }

            // The "Next case" button loads the context of this case into the text view.
            _ = try tap([nextCentre])
            var loaded = try waitForStatus(timeout: 20) { $0.i == index }
            if !loaded.met && loaded.status.i == index - 1 {
                print("EVAL_NOTE case \(index): the Next tap did not arrive, tapping again")
                _ = try tap([nextCentre])
                loaded = try waitForStatus(timeout: 20) { $0.i == index }
            }
            guard loaded.met else {
                try saveDiagnostics("case-index-mismatch")
                throw Failure("the host app shows case \(loaded.status.i), and the test is at case \(index)")
            }

            // The typed characters and one space go in at one rhythm.
            // English: the space ends the word and applies the correction.
            // Pinyin: the space takes the first candidate.
            let sendTimes = try tap(try points(for: item.typed) + [spaceCentre])
            var spaceTaps = 1
            var after: Read
            if task == "english" {
                // The host app counts each space that arrives, so the count tells when the
                // last space is in the text. A stalled simulator can deliver taps seconds late.
                let spaces = item.typed.filter({ $0 == " " }).count + 1
                after = try waitForStatus(timeout: 60) { $0.e >= spaces }
            } else {
                // After the space the text view holds Chinese text outside the marked text.
                after = try waitForStatus(timeout: 8) { !$0.c.isEmpty }
                // The first candidate can cover only the first letters. The test taps space
                // again while the keyboard still holds marked text, so every letter gets a candidate.
                while after.status.m && spaceTaps < 12 {
                    let reference = after.status
                    _ = try tap([spaceCentre])
                    spaceTaps += 1
                    after = try waitForStatus(timeout: 8) { $0.c != reference.c || $0.m != reference.m }
                    if !after.met { break }
                }
            }

            record["after"] = after.status.t
            record["after_committed"] = after.status.c
            record["after_marked"] = after.status.m
            record["after_as_expected"] = after.met
            record["space_taps"] = spaceTaps
            record["history"] = after.status.h
            record["history_ms"] = after.status.ht
            record["send_ms"] = sendTimes.map { Int(($0 * 1000).rounded()) }
            record["seconds"] = (Date().timeIntervalSince(caseStart) * 100).rounded() / 100
            let line = try JSONSerialization.data(withJSONObject: record, options: [.sortedKeys])
            detailFile.write(line)
            detailFile.write(Data("\n".utf8))
            print("EVAL_CASE \(index + 1)/\(cases.count) \(item.id) typed=[\(item.typed)] after=[\(after.status.c)] marked=\(after.status.m) expected=\(after.met) spaces=\(spaceTaps) seconds=\(record["seconds"] ?? "")")
        }
        let seconds = Date().timeIntervalSince(runStart)
        print(String(format: "EVAL_DONE cases=%ld taps=%ld status_reads=%ld seconds=%.1f seconds_per_case=%.2f",
                     cases.count, tapCount, statusReads, seconds, seconds / Double(max(cases.count, 1))))
        try saveDiagnostics("after-last-case")
    }

    // MARK: - Keyboard

    /// Waits for the software keyboard and reads the position of each letter key, the space key
    /// and the "Next case" button.
    private func findKeyboard() throws {
        let field = app.textViews["evalField"]
        guard field.waitForExistence(timeout: 90) else {
            try saveDiagnostics("field-missing")
            throw Failure("the text view of the host app did not appear")
        }
        let keyboard = app.keyboards.firstMatch
        if !keyboard.waitForExistence(timeout: 30) {
            field.tap()
            guard keyboard.waitForExistence(timeout: 30) else {
                try saveDiagnostics("keyboard-missing")
                throw Failure("the software keyboard did not appear")
            }
        }
        // The first appearance of the keyboard on a new simulator takes a few seconds to settle.
        Thread.sleep(forTimeInterval: 3)
        try saveDiagnostics("keyboard-shown")
        print("EVAL_TREE_BEGIN")
        print(app.debugDescription)
        print("EVAL_TREE_END")

        let keys = try readKeys()
        for letter in "abcdefghijklmnopqrstuvwxyz" {
            // The label of a letter key is the letter, in upper case while shift is on.
            guard let key = keys.first(where: { $0.type == .key && $0.label.lowercased() == String(letter) }) else {
                throw Failure("the keyboard does not show the key \(letter)")
            }
            letterCentres[letter] = CGPoint(x: key.frame.midX, y: key.frame.midY)
        }
        // The space key carries the identifier "space" on the English and the Pinyin keyboard.
        // Its label changes with the language and with the state of the keyboard.
        guard let space = keys.first(where: { $0.identifier == "space" }) else {
            throw Failure("the keyboard does not show a key with the identifier space")
        }
        spaceCentre = CGPoint(x: space.frame.midX, y: space.frame.midY)
        let nextFrame = app.buttons["evalNext"].frame
        guard !nextFrame.isEmpty else {
            throw Failure("the Next case button is missing")
        }
        nextCentre = CGPoint(x: nextFrame.midX, y: nextFrame.midY)
        print("EVAL_KEYS q=\(letterCentres["q"]!) m=\(letterCentres["m"]!) space=\(spaceCentre) next=\(nextCentre)")
    }

    /// Reads every key and button inside the keyboard from one snapshot of the app.
    private func readKeys() throws -> [Key] {
        var keys: [Key] = []
        func visit(_ node: XCUIElementSnapshot, insideKeyboard: Bool) {
            let inside = insideKeyboard || node.elementType == .keyboard
            if inside && (node.elementType == .key || node.elementType == .button) {
                keys.append(Key(type: node.elementType, label: node.label, identifier: node.identifier, frame: node.frame))
            }
            for child in node.children {
                visit(child, insideKeyboard: inside)
            }
        }
        visit(try app.snapshot(), insideKeyboard: false)
        return keys
    }

    /// Types one known word before the cases, prints the field text, and saves the accessibility
    /// tree while the keyboard shows its suggestions. The printed line proves in the run log that
    /// key taps reach the keyboard and that the keyboard changes the text.
    private func warmUp(task: String) throws {
        let word = task == "english" ? "teh" : "nihao"
        for attempt in 1...3 {
            let start = try readStatus()
            _ = try tap(try points(for: word))
            let before = try waitForStatus(timeout: 20) { status in
                String(status.t.dropFirst(start.t.count)).lowercased().filter({ $0.isASCII && $0.isLetter }) == word
            }
            if attempt == 1 {
                try saveDiagnostics("warm-up-before-space")
            }
            _ = try tap([spaceCentre])
            let after = try waitForStatus(timeout: 20) { $0.t != before.status.t || $0.m != before.status.m }
            print("EVAL_WARMUP attempt=\(attempt) typed=[\(word)] start=[\(start.t)] before_space=[\(before.status.t)] marked=\(before.status.m) letters_arrived=\(before.met) after_space=[\(after.status.t)] marked_after=\(after.status.m)")
            if before.met && after.met {
                try saveDiagnostics("warm-up-after-space")
                return
            }
            Thread.sleep(forTimeInterval: 3)
        }
        try saveDiagnostics("warm-up-incomplete")
        throw Failure("the warm-up word did not reach the text view in three attempts")
    }

    // MARK: - Taps and reads

    private func points(for typed: String) throws -> [CGPoint] {
        try typed.map { (character: Character) -> CGPoint in
            if character == " " {
                return spaceCentre
            }
            guard let centre = letterCentres[character] else {
                throw Failure("the keyboard does not hold a key for the character \(character)")
            }
            return centre
        }
    }

    /// Taps the points in order at the key interval. Returns the time each tap was sent, in
    /// seconds since the first tap.
    private func tap(_ points: [CGPoint]) throws -> [Double] {
        tapCount += points.count
        let values = points.map { NSValue(cgPoint: $0) }
        switch tapMode {
        case .paced:
            return try EventSynthesis.tapPointsPaced(values, interval: keyInterval, hold: hold, waitForCompletion: true).map { $0.doubleValue }
        case .pacedOpen:
            return try EventSynthesis.tapPointsPaced(values, interval: keyInterval, hold: hold, waitForCompletion: false).map { $0.doubleValue }
        case .batch:
            let starts = points.indices.map { Double($0) * keyInterval }
            try EventSynthesis.tapPoints(values, starts: starts.map { NSNumber(value: $0) }, hold: hold)
            return starts
        }
    }

    private func readStatus() throws -> FieldStatus {
        statusReads += 1
        let label = app.staticTexts["evalStatus"].label
        guard let status = try? JSONDecoder().decode(FieldStatus.self, from: Data(label.utf8)) else {
            throw Failure("the status label does not hold JSON: \(label)")
        }
        return status
    }

    /// Reads the status until the condition holds or the time runs out. Returns the last status
    /// and whether the condition held.
    private func waitForStatus(timeout: TimeInterval, _ condition: (FieldStatus) -> Bool) throws -> Read {
        let deadline = Date().addingTimeInterval(timeout)
        var status = try readStatus()
        while !condition(status) && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.1)
            status = try readStatus()
        }
        return (status, condition(status))
    }

    /// Saves the accessibility tree of the app and a screenshot under the given name.
    private func saveDiagnostics(_ name: String) throws {
        try app.debugDescription.write(to: outputFolder.appendingPathComponent("tree-\(name).txt"), atomically: true, encoding: .utf8)
        try XCUIScreen.main.screenshot().pngRepresentation.write(to: outputFolder.appendingPathComponent("screen-\(name).png"))
    }
}
