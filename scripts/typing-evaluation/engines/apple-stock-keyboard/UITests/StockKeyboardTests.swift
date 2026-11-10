import UIKit
import XCTest

/// Types the evaluation cases on the software keyboard of the iOS Simulator and records the text
/// that the text view of the host app holds.
///
/// The test taps key positions on the screen. It never calls typeText, because typeText sends
/// key events the way a hardware keyboard does and skips the touch path of the keyboard.
///
/// The test reads four environment variables. `xcodebuild` passes a variable to the test process
/// when its name starts with `TEST_RUNNER_`.
/// - `EVAL_TASK`: `english` or `pinyin`.
/// - `EVAL_CASES_FILE`: a JSON Lines file with the cases to type.
/// - `EVAL_OUTPUT_DIR`: the folder that receives `detail.jsonl`, the accessibility trees and the screenshots.
/// - `EVAL_TAP_MODE`: `single` sends one XCUICoordinate tap for each key. `batch` sends the taps
///   of one case as one synthesized event.
/// `EVAL_INLINE_PREDICTION` is optional. The value `no` turns inline predictions off in the text view.
@MainActor
final class StockKeyboardTests: XCTestCase {
    private struct EvalCase: Decodable {
        let id: String
        let category: String
        let typed: String
        let context: String?
    }

    /// The state that the host app shows in its status label.
    private struct FieldStatus: Decodable {
        let i: Int
        let m: Bool
        let t: String
    }

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
        case single
        case batch
    }

    /// Seconds a finger stays down in batch mode.
    private let hold = 0.06
    /// Seconds between two touch-downs in batch mode.
    private let keyInterval = 0.16
    /// Names the space key carries in the accessibility tree.
    private let spaceNames = ["space", "空格"]

    private var app: XCUIApplication!
    private var outputFolder: URL!
    private var tapMode = TapMode.single
    private var letterCentres: [Character: CGPoint] = [:]
    private var spaceCentre = CGPoint.zero
    private var nextCentre = CGPoint.zero
    private var tapCount = 0
    private var statusReads = 0

    func testTypeCases() throws {
        let environment = ProcessInfo.processInfo.environment
        guard let task = environment["EVAL_TASK"], let casesPath = environment["EVAL_CASES_FILE"],
              let outputPath = environment["EVAL_OUTPUT_DIR"], let modeName = environment["EVAL_TAP_MODE"] else {
            throw Failure("EVAL_TASK, EVAL_CASES_FILE, EVAL_OUTPUT_DIR and EVAL_TAP_MODE must be set")
        }
        guard task == "english" || task == "pinyin" else {
            throw Failure("EVAL_TASK must be english or pinyin, and the value is \(task)")
        }
        guard let mode = TapMode(rawValue: modeName) else {
            throw Failure("EVAL_TAP_MODE must be single or batch, and the value is \(modeName)")
        }
        tapMode = mode
        continueAfterFailure = true
        outputFolder = URL(fileURLWithPath: outputPath)
        try FileManager.default.createDirectory(at: outputFolder, withIntermediateDirectories: true)

        let decoder = JSONDecoder()
        let cases = try String(contentsOfFile: casesPath, encoding: .utf8)
            .split(separator: "\n")
            .map { try decoder.decode(EvalCase.self, from: Data($0.utf8)) }
        print("EVAL_START task=\(task) mode=\(mode.rawValue) cases=\(cases.count)")

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
            var record: [String: Any] = ["id": item.id, "category": item.category, "typed": item.typed, "tap_mode": mode.rawValue]
            if let context = item.context {
                record["context"] = context
            }

            // The "Next case" button loads the context of this case into the text view.
            try tap([nextCentre])
            var loaded = try waitForStatus(timeout: 6) { $0.i == index }
            if !loaded.met && loaded.status.i == index - 1 {
                print("EVAL_NOTE case \(index): the Next tap did not arrive, tapping again")
                try tap([nextCentre])
                loaded = try waitForStatus(timeout: 6) { $0.i == index }
            }
            guard loaded.met else {
                try saveDiagnostics("case-index-mismatch")
                throw Failure("the host app shows case \(loaded.status.i), and the test is at case \(index)")
            }

            try tap(try points(for: item.typed))
            let lastToken = item.typed.split(separator: " ").last.map(String.init) ?? ""
            let before: (status: FieldStatus, met: Bool)
            if task == "english" {
                before = try waitForStatus(timeout: 2) { $0.t.lowercased().hasSuffix(lastToken) }
            } else {
                before = try waitForStatus(timeout: 2) { status in
                    status.m && status.t.filter({ $0.isASCII && $0.isLetter }) == item.typed
                }
            }
            record["before_space"] = before.status.t
            record["before_space_marked"] = before.status.m
            record["before_space_as_expected"] = before.met

            // English: one space ends the word and applies the correction.
            // Pinyin: space takes the first candidate. The test taps space again while the
            // keyboard still holds marked text, so every typed letter gets a first candidate.
            var spaceTaps = 0
            var previous = before.status
            var after = before
            repeat {
                try tap([spaceCentre])
                spaceTaps += 1
                let reference = previous
                if task == "english" {
                    after = try waitForStatus(timeout: 3) { $0.t != reference.t && $0.t.hasSuffix(" ") }
                } else {
                    after = try waitForStatus(timeout: 3) { $0.t != reference.t || $0.m != reference.m }
                }
                let changed = after.status.t != previous.t || after.status.m != previous.m
                previous = after.status
                if !changed { break }
            } while task == "pinyin" && after.status.m && spaceTaps < 12

            record["after"] = after.status.t
            record["after_marked"] = after.status.m
            record["after_as_expected"] = after.met
            record["space_taps"] = spaceTaps
            record["seconds"] = (Date().timeIntervalSince(caseStart) * 100).rounded() / 100
            let line = try JSONSerialization.data(withJSONObject: record, options: [.sortedKeys])
            detailFile.write(line)
            detailFile.write(Data("\n".utf8))
            print("EVAL_CASE \(index + 1)/\(cases.count) \(item.id) typed=[\(item.typed)] before=[\(before.status.t)] after=[\(after.status.t)] marked=\(after.status.m) spaces=\(spaceTaps) seconds=\(record["seconds"] ?? "")")
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
                let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
                try springboard.debugDescription.write(to: outputFolder.appendingPathComponent("tree-springboard.txt"), atomically: true, encoding: .utf8)
                throw Failure("the software keyboard did not appear")
            }
        }
        // The first appearance of the keyboard on a new simulator takes a few seconds to settle.
        Thread.sleep(forTimeInterval: 3)
        try saveDiagnostics("keyboard-shown")
        print("EVAL_TREE_BEGIN")
        print(app.debugDescription)
        print("EVAL_TREE_END")

        var keys = try readKeys()
        if !holdsAllLetters(keys) {
            // A new simulator can show a one-time introduction over the keys.
            for title in ["Continue", "继续"] where app.buttons[title].exists {
                print("EVAL_NOTE tapping the button \(title) to close an introduction")
                app.buttons[title].tap()
                Thread.sleep(forTimeInterval: 2)
            }
            keys = try readKeys()
            try saveDiagnostics("keyboard-second-look")
        }
        for key in keys {
            print("EVAL_KEY type=\(key.type.rawValue) label=[\(key.label)] identifier=[\(key.identifier)] frame=\(key.frame)")
        }
        guard holdsAllLetters(keys) else {
            throw Failure("the keyboard does not show the 26 letter keys")
        }
        for letter in "abcdefghijklmnopqrstuvwxyz" {
            guard let key = keys.first(where: { isLetterKey($0, letter) }) else {
                throw Failure("the keyboard does not show the key \(letter)")
            }
            letterCentres[letter] = CGPoint(x: key.frame.midX, y: key.frame.midY)
        }
        if let named = keys.first(where: { spaceNames.contains($0.identifier.lowercased()) || spaceNames.contains($0.label.lowercased()) }) {
            spaceCentre = CGPoint(x: named.frame.midX, y: named.frame.midY)
            print("EVAL_SPACE_KEY found by name: label=[\(named.label)] identifier=[\(named.identifier)] frame=\(named.frame)")
        } else {
            // The space key is the widest key of the keyboard.
            guard let widest = keys.filter({ $0.type == .key }).max(by: { $0.frame.width < $1.frame.width }) else {
                throw Failure("the keyboard does not show a space key")
            }
            spaceCentre = CGPoint(x: widest.frame.midX, y: widest.frame.midY)
            print("EVAL_SPACE_KEY found as the widest key: label=[\(widest.label)] identifier=[\(widest.identifier)] frame=\(widest.frame)")
        }
        let nextFrame = app.buttons["evalNext"].frame
        guard !nextFrame.isEmpty else {
            throw Failure("the Next case button is missing")
        }
        nextCentre = CGPoint(x: nextFrame.midX, y: nextFrame.midY)
    }

    private func isLetterKey(_ key: Key, _ letter: Character) -> Bool {
        key.type == .key && (key.label.lowercased() == String(letter) || key.identifier.lowercased() == String(letter))
    }

    private func holdsAllLetters(_ keys: [Key]) -> Bool {
        "abcdefghijklmnopqrstuvwxyz".allSatisfy { letter in
            keys.contains(where: { isLetterKey($0, letter) })
        }
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
            try tap(try points(for: word))
            let before = try waitForStatus(timeout: 8) { status in
                String(status.t.dropFirst(start.t.count)).lowercased().filter({ $0.isASCII && $0.isLetter }) == word
            }
            if attempt == 1 {
                try saveDiagnostics("warm-up-before-space")
            }
            try tap([spaceCentre])
            let after = try waitForStatus(timeout: 8) { $0.t != before.status.t || $0.m != before.status.m }
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

    private func tap(_ points: [CGPoint]) throws {
        tapCount += points.count
        switch tapMode {
        case .single:
            let origin = app.coordinate(withNormalizedOffset: CGVector(dx: 0, dy: 0))
            for point in points {
                origin.withOffset(CGVector(dx: point.x, dy: point.y)).tap()
            }
        case .batch:
            let starts = points.indices.map { NSNumber(value: Double($0) * keyInterval) }
            try EventSynthesis.tapPoints(points.map { NSValue(cgPoint: $0) }, starts: starts, hold: hold)
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
    private func waitForStatus(timeout: TimeInterval, _ condition: (FieldStatus) -> Bool) throws -> (status: FieldStatus, met: Bool) {
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
