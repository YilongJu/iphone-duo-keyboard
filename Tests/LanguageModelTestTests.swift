import XCTest

@testable import DuoKeyboard

/// Runs the language model test on the model file of the app bundle, inside the simulator.
///
/// The test proves that llama.cpp loads the model and that every step of the measurement
/// runs. It does not assert the model's answers or the times: the times of a simulator on a
/// Mac say little about an iPhone, and the memory limit of a keyboard exists only on a device.
@MainActor
final class LanguageModelTestTests: XCTestCase {
    func testTheBundledModelLoadsAndEveryStepRuns() async throws {
        var lines: [String] = []
        for await line in BundledLanguageModelTest().resultLines() {
            lines.append(line)
        }
        let report = lines.joined(separator: "\n")
        // The GitHub workflow names a folder and keeps the report as a file of the run.
        // `xcodebuild test` passes a variable to the test process when its name starts with `TEST_RUNNER_`.
        if let folder = ProcessInfo.processInfo.environment["LANGUAGE_MODEL_OUTPUT_DIR"] {
            let url = URL(fileURLWithPath: folder)
            try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
            try (report + "\n").write(
                to: url.appendingPathComponent("simulator.txt"), atomically: true, encoding: .utf8)
        }
        XCTAssertEqual(lines.last, "done        every step ran", report)
        XCTAssertFalse(report.contains("failed"), report)
        XCTAssertTrue(lines.contains { $0.hasPrefix("process     app") }, report)
        XCTAssertTrue(lines.contains { $0.hasPrefix("candidates  4 threads: context") }, report)
    }
}
