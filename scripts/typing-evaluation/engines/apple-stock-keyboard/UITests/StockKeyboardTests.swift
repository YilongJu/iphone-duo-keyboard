import UIKit
import XCTest

/// Types the evaluation cases on the software keyboard of the iOS Simulator and records the text
/// that the text view of the host app holds.
///
/// The test taps key positions on the screen. It never calls typeText, because typeText sends
/// key events the way a hardware keyboard does and skips the touch path of the keyboard.
///
/// The keyboard changes its corrections with the time between taps, so the test sends the taps
/// at a fixed key interval and records the rhythm that arrived. The test types each case once,
/// because the keyboard learns from the text a person types. Only a case that ended with an
/// error, or whose last space did not arrive, goes into a second pass.
///
/// The test reads these environment variables. `xcodebuild` passes a variable to the test process
/// when its name starts with `TEST_RUNNER_`.
/// - `EVAL_TASK`: `english` or `pinyin`.
/// - `EVAL_CASES_FILE`: a JSON Lines file with the cases to type.
/// - `EVAL_OUTPUT_DIR`: the folder that receives `attempts.jsonl`, the accessibility trees and the screenshots.
/// - `EVAL_KEY_INTERVAL`: the key interval, the seconds between two touch-downs.
/// - `EVAL_INLINE_PREDICTION`: optional. The value `no` turns inline predictions off in the text view.
/// - `EVAL_CONTROL`: `yes` or `no`. The value `yes` makes the host app turn every correction off,
///   so the text view must hold exactly the typed characters. That run checks the taps.
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
        let g: Int
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

    /// Seconds a finger stays down on a key.
    private let hold = 0.06
    /// A case keeps its rhythm when the longest time between two key arrivals stays under
    /// this many key intervals.
    private let rhythmLimit = 1.5
    /// Each case is typed in at most this many passes.
    private let passLimit = 2
    /// The test starts the host app again after an error, at most this many times.
    private let relaunchLimit = 8

    private var app: XCUIApplication!
    private var outputFolder: URL!
    private var task = ""
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
        task = try variable("EVAL_TASK")
        guard task == "english" || task == "pinyin" else {
            throw Failure("EVAL_TASK must be english or pinyin, and the value is \(task)")
        }
        guard let interval = Double(try variable("EVAL_KEY_INTERVAL")), interval > hold else {
            throw Failure("EVAL_KEY_INTERVAL must be a number of seconds above \(hold)")
        }
        keyInterval = interval
        continueAfterFailure = true
        outputFolder = URL(fileURLWithPath: try variable("EVAL_OUTPUT_DIR"))
        try FileManager.default.createDirectory(at: outputFolder, withIntermediateDirectories: true)

        let decoder = JSONDecoder()
        let cases = try String(contentsOfFile: try variable("EVAL_CASES_FILE"), encoding: .utf8)
            .split(separator: "\n")
            .map { try decoder.decode(EvalCase.self, from: Data($0.utf8)) }
        print("EVAL_START task=\(task) key_interval=\(interval) control=\(control) cases=\(cases.count)")

        app = XCUIApplication()
        app.launchEnvironment["EVAL_TASK"] = task
        if let inlinePrediction = environment["EVAL_INLINE_PREDICTION"] {
            app.launchEnvironment["EVAL_INLINE_PREDICTION"] = inlinePrediction
        }
        let control = try variable("EVAL_CONTROL")
        guard control == "yes" || control == "no" else {
            throw Failure("EVAL_CONTROL must be yes or no, and the value is \(control)")
        }
        app.launchEnvironment["EVAL_CONTROL"] = control

        let attemptsURL = outputFolder.appendingPathComponent("attempts.jsonl")
        FileManager.default.createFile(atPath: attemptsURL.path, contents: nil)
        let attemptsFile = try FileHandle(forWritingTo: attemptsURL)
        defer { try? attemptsFile.close() }
        func write(_ record: [String: Any]) throws {
            attemptsFile.write(try JSONSerialization.data(withJSONObject: record, options: [.sortedKeys]))
            attemptsFile.write(Data("\n".utf8))
        }

        let runStart = Date()
        var pending = cases
        var relaunches = 0
        var firstLaunch = true
        for pass in 1...passLimit where !pending.isEmpty {
            print("EVAL_PASS \(pass) cases=\(pending.count)")
            var again: [EvalCase] = []
            var remaining = pending
            while !remaining.isEmpty {
                var done = 0
                do {
                    try launch(contexts: remaining.map { $0.context ?? "" }, first: firstLaunch)
                    firstLaunch = false
                    for (position, item) in remaining.enumerated() {
                        let caseStart = Date()
                        var record = try typeCase(item, position: position)
                        record["pass"] = pass
                        record["seconds"] = (Date().timeIntervalSince(caseStart) * 100).rounded() / 100
                        try write(record)
                        done = position + 1
                        print("EVAL_CASE pass=\(pass) \(position + 1)/\(remaining.count) \(item.id) typed=[\(item.typed)] after=[\(record["after_committed"] ?? "")] complete=\(record["complete"] ?? "") longest_gap_ms=\(record["longest_key_gap_ms"] ?? "") seconds=\(record["seconds"] ?? "")")
                        if record["complete"] as? Bool != true {
                            again.append(item)
                        }
                    }
                } catch {
                    // An error stops the typing of this launch: a status read that never came
                    // back, a tap the test daemon refused, or a case that did not load. The
                    // case goes into the next pass, and a new launch types the cases after it.
                    relaunches += 1
                    print("EVAL_NOTE pass=\(pass) position=\(done) relaunch=\(relaunches) error: \(error)")
                    try? XCUIScreen.main.screenshot().pngRepresentation.write(to: outputFolder.appendingPathComponent("screen-error-\(relaunches).png"))
                    guard relaunches <= relaunchLimit else {
                        throw error
                    }
                    if done < remaining.count {
                        let failed = remaining[done]
                        try write(["id": failed.id, "category": failed.category, "typed": failed.typed, "pass": pass, "error": "\(error)"])
                        again.append(failed)
                        done += 1
                    }
                }
                remaining = Array(remaining.dropFirst(done))
            }
            pending = again
        }
        let seconds = Date().timeIntervalSince(runStart)
        print(String(format: "EVAL_DONE cases=%ld left_incomplete=%ld relaunches=%ld taps=%ld status_reads=%ld seconds=%.1f",
                     cases.count, pending.count, relaunches, tapCount, statusReads, seconds))
        try saveDiagnostics("after-last-case")
    }

    // MARK: - One case

    /// Loads the case at the given position of the launched list, types it and returns what the
    /// text view held.
    private func typeCase(_ item: EvalCase, position: Int) throws -> [String: Any] {
        var record: [String: Any] = ["id": item.id, "category": item.category, "typed": item.typed]
        if let context = item.context {
            record["context"] = context
        }
        // The "Next case" button loads the context of this case into the text view.
        _ = try tap([nextCentre])
        let loaded = try waitForStatus(timeout: 30) { $0.i == position }
        guard loaded.met else {
            throw Failure("the host app shows case \(loaded.status.i), and the test is at case \(position)")
        }

        var spaceTaps = 1
        var sendTimes: [Double]
        var after: Read
        var complete: Bool
        if task == "english" {
            // The typed characters and one space go in at one rhythm. The space ends the word
            // and applies the correction. The host app counts each space that arrives, so the
            // count tells when the last space is in the text.
            sendTimes = try tap(try points(for: item.typed) + [spaceCentre])
            let spaces = item.typed.filter({ $0 == " " }).count + 1
            after = try waitForStatus(timeout: 90) { $0.e >= spaces }
            complete = after.met
        } else {
            // A person reads the candidates before the space. The test waits until the marked
            // text holds every typed letter, and then one space takes the first candidate.
            sendTimes = try tap(try points(for: item.typed))
            let composed = try waitForStatus(timeout: 30) { status in
                status.m && status.t.filter({ $0.isASCII && $0.isLetter }) == item.typed
            }
            record["letters_shown_before_space"] = composed.met
            after = composed
            spaceTaps = 0
            // The first candidate can cover only the first letters. The test taps space again
            // while the keyboard still holds marked text, so every letter gets a candidate.
            repeat {
                let reference = after.status
                sendTimes += try tap([spaceCentre])
                spaceTaps += 1
                after = try waitForStatus(timeout: 15) { $0.c != reference.c || $0.m != reference.m }
            } while after.met && after.status.m && spaceTaps < 12
            complete = after.met && !after.status.m
        }

        record["after"] = after.status.t
        record["after_committed"] = after.status.c
        record["after_marked"] = after.status.m
        record["complete"] = complete
        record["space_taps"] = spaceTaps
        record["longest_key_gap_ms"] = after.status.g
        record["rhythm_kept"] = Double(after.status.g) <= rhythmLimit * keyInterval * 1000
        record["history"] = after.status.h
        record["history_ms"] = after.status.ht
        record["send_ms"] = sendTimes.map { Int(($0 * 1000).rounded()) }
        return record
    }

    // MARK: - Launch and keyboard

    /// Starts the host app with the contexts of the cases to type, and finds the keyboard.
    /// XCUIApplication.launch() ends a running instance of the app first.
    private func launch(contexts: [String], first: Bool) throws {
        let contextsJSON = try JSONEncoder().encode(contexts)
        app.launchEnvironment["EVAL_CONTEXTS_JSON"] = String(decoding: contextsJSON, as: UTF8.self)
        app.launch()
        try findKeyboard(printTree: first)
        if first {
            try warmUp()
        }
    }

    /// Waits for the software keyboard and reads the position of each letter key, the space key
    /// and the "Next case" button.
    private func findKeyboard(printTree: Bool) throws {
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
        // The keyboard takes a few seconds to settle after it appears.
        Thread.sleep(forTimeInterval: 3)
        if printTree {
            try saveDiagnostics("keyboard-shown")
            print("EVAL_TREE_BEGIN")
            print(app.debugDescription)
            print("EVAL_TREE_END")
        }

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
    private func warmUp() throws {
        let word = task == "english" ? "teh" : "nihao"
        for attempt in 1...3 {
            let start = try readStatus()
            _ = try tap(try points(for: word))
            let before = try waitForStatus(timeout: 30) { status in
                String(status.t.dropFirst(start.t.count)).lowercased().filter({ $0.isASCII && $0.isLetter }) == word
            }
            if attempt == 1 {
                try saveDiagnostics("warm-up-before-space")
            }
            _ = try tap([spaceCentre])
            let after = try waitForStatus(timeout: 30) { $0.t != before.status.t || $0.m != before.status.m }
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

    /// Taps the points in order, one synthesized event for each tap, one key interval apart.
    /// Returns the time each tap was sent, in seconds since the first tap.
    private func tap(_ points: [CGPoint]) throws -> [Double] {
        tapCount += points.count
        let values = points.map { NSValue(cgPoint: $0) }
        return try EventSynthesis.tapPointsPaced(values, interval: keyInterval, hold: hold).map { $0.doubleValue }
    }

    /// Reads the status label of the host app. A busy simulator can leave the label out of
    /// reach for a while, so the read waits up to two minutes before it gives up.
    private func readStatus() throws -> FieldStatus {
        statusReads += 1
        let element = app.staticTexts["evalStatus"]
        let deadline = Date().addingTimeInterval(120)
        while !element.waitForExistence(timeout: 10) {
            guard Date() < deadline else {
                throw Failure("the status label of the host app stayed out of reach for two minutes")
            }
        }
        let label = element.label
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
