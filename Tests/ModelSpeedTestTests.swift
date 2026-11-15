import XCTest

@testable import DuoKeyboard

/// The speed test of the language models (Shared/ModelSpeedTest.swift) in the simulator.
///
/// The run test proves that every step runs and that every line comes out. It does not hold the
/// times against a limit: the simulator shares the processor of a virtual Mac and has no memory
/// limit. The workflow "Language model in the keyboard" can place downloaded models in the
/// folder of TEST_RUNNER_MODEL_SPEED_DIR, and the run then reads them too.
@MainActor
final class ModelSpeedTestTests: XCTestCase {
    func testTheCatalogNamesAModelAReferenceAndTokensForEveryPair() throws {
        let catalog = try ModelSpeedCatalog.bundled()
        let requests = try ModelSpeedRun.textRequests()
        XCTAssertEqual(requests.count, 486)
        let references = try JSONDecoder().decode(
            [String: [Int]].self, from: Data(contentsOf: ModelSpeedRun.resource("model-speed-reference", "json")))
        XCTAssertFalse(catalog.pairs.isEmpty)
        for pair in catalog.pairs {
            XCTAssertTrue(pair.model == "bundled" || catalog.model(id: pair.model) != nil, pair.model)
            XCTAssertEqual(references[pair.reference]?.count, requests.count, pair.reference)
            if !pair.runtime.isLlama {
                let name = try XCTUnwrap(pair.tokens, pair.name)
                let text = try String(contentsOf: ModelSpeedRun.resource("model-speed-tokens.\(name)", "tsv"), encoding: .utf8)
                let tokens = try TokenRequest.read(text)
                XCTAssertEqual(tokens.count, requests.count, name)
                // Each request has as many candidates in tokens as in text.
                XCTAssertEqual(tokens.map { $0.candidates.count }, requests.map { $0.candidates.count }, name)
            }
        }
        for model in catalog.models {
            XCTAssertFalse(model.files.isEmpty, model.id)
            for file in model.files {
                XCTAssertEqual(file.sha256.count, 64, file.path)
                XCTAssertTrue(file.url.absoluteString.hasPrefix(
                    "https://github.com/YilongJu/iphone-duo-keyboard/releases/download/\(catalog.release)/"), file.path)
            }
        }
    }

    /// The window rules of the Core ML route keep as many context tokens from the cache as the C
    /// scorer does: the C scorer of llama.cpp b4846 on the keyboard's file kept 14,918 of 18,403
    /// window tokens on these requests on the desktop (scripts/model-speed/desktop/jobs/speed.sh,
    /// run shipped.Q4_K_M.b4846), with the same tokenizer as SmolLM2-135M.
    func testTheWindowRulesKeepTheTokensOfTheCScorer() throws {
        let text = try String(contentsOf: ModelSpeedRun.resource("model-speed-tokens.smollm2-135m", "tsv"), encoding: .utf8)
        var planner = AnchoredWindowPlanner()
        var window = 0, kept = 0
        for request in try TokenRequest.read(text) {
            let plan = planner.next(start: request.start, context: request.context)
            window += plan.window.count
            kept += plan.kept
            XCTAssertLessThanOrEqual(plan.window.count, AnchoredWindowPlanner.maxContextTokens + 1)
        }
        XCTAssertEqual(window, 18403)
        XCTAssertEqual(kept, 14918)
    }

    /// The same check request by request: the C scorer on the keyboard's file keeps as many
    /// context tokens of the cache in each request as the window rules of the Core ML route.
    func testTheWindowRulesKeepTheTokensOfTheCScorerInEveryRequest() throws {
        let text = try String(contentsOf: ModelSpeedRun.resource("model-speed-tokens.smollm2-135m", "tsv"), encoding: .utf8)
        let tokens = try TokenRequest.read(text)
        let requests = try ModelSpeedRun.textRequests()
        let path = try XCTUnwrap(Bundle(for: ModelSpeedTest.self).path(
            forResource: BundledLanguageModelTest.modelResource, ofType: "gguf"))
        var error = [CChar](repeating: 0, count: Int(DUO_LM_ERROR_SIZE))
        let scorer = try XCTUnwrap(duo_lm_scorer_open(
            path, Int32(ModelSpeedTest.threads), KeyboardLanguageModel.reuse, &error, Int(DUO_LM_ERROR_SIZE)),
            String(cString: error))
        defer { duo_lm_scorer_close(scorer) }
        var planner = AnchoredWindowPlanner()
        var differing: [Int] = []
        for (index, request) in requests.enumerated() {
            let plan = planner.next(start: tokens[index].start, context: tokens[index].context)
            let copies = request.candidates.map { strdup($0) }
            defer { copies.forEach { free($0) } }
            let pointers = copies.map { UnsafePointer<CChar>($0) }
            var scores = [duo_lm_score](repeating: duo_lm_score(), count: request.candidates.count)
            let before = duo_lm_scorer_get_info(scorer)
            let result = pointers.withUnsafeBufferPointer { pointerBuffer in
                scores.withUnsafeMutableBufferPointer { scoreBuffer in
                    duo_lm_scorer_score(scorer, request.context, pointerBuffer.baseAddress, Int32(request.candidates.count),
                                        scoreBuffer.baseAddress, &error, Int(DUO_LM_ERROR_SIZE))
                }
            }
            XCTAssertEqual(result, 1, String(cString: error))
            let after = duo_lm_scorer_get_info(scorer)
            if after.window_tokens - before.window_tokens != plan.window.count
                || after.window_tokens_reused - before.window_tokens_reused != plan.kept
            {
                differing.append(index + 1)
            }
        }
        XCTAssertEqual(differing, [], "the requests whose window or kept tokens differ")
    }

    /// A run that stopped goes on after its last pair: the pairs that ended are not run again,
    /// and the pair that was running is skipped. A run that ended starts over.
    func testTheProgressFileResumesAStoppedRunOnly() throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("speed-progress-\(UUID().uuidString).txt")
        defer { try? FileManager.default.removeItem(at: file) }
        let progress = ModelSpeedProgress(file: file, signature: "abc")
        XCTAssertNil(try progress.stoppedRun())
        try progress.begin()
        for line in ["start 0", "end 0", "start 1", "end 1", "start 2"] { try progress.append(line) }
        let stopped = try XCTUnwrap(try progress.stoppedRun())
        XCTAssertEqual(stopped.ended, [0, 1])
        XCTAssertEqual(stopped.stopped, [2])
        // A second run that skipped pair 2 and stopped during pair 4 skips both next time.
        for line in ["start 3", "end 3", "start 4"] { try progress.append(line) }
        let again = try XCTUnwrap(try progress.stoppedRun())
        XCTAssertEqual(again.ended, [0, 1, 3])
        XCTAssertEqual(again.stopped, [2, 4])
        XCTAssertNil(try ModelSpeedProgress(file: file, signature: "other").stoppedRun())
        try progress.append("done")
        XCTAssertNil(try progress.stoppedRun())
    }

    /// A hold keeps the keyboard's model from loading until the hold ends.
    func testAHoldKeepsTheKeyboardModelFromLoading() async throws {
        let model = KeyboardLanguageModel(modelPath: nil, modelName: "none", cacheCheckTolerance: nil)
        var ready = false
        model.hold(reason: "a test") { ready = true }
        XCTAssertTrue(ready)
        model.loadInBackground()
        XCTAssertEqual(model.state, .notLoaded)
        XCTAssertEqual(model.runningLoads, 0)
        model.release()
        model.loadInBackground()
        XCTAssertEqual(model.state, .loading)
    }

    /// The two forms of the Core ML model of SmolLM2-135M give the same top candidate in nearly
    /// every request, so the padding and the cells of the fixed form are right. Runs only where
    /// TEST_RUNNER_MODEL_SPEED_DIR holds both models.
    func testTheFixedAndTheFlexibleCoreMLModelsAgree() throws {
        guard let named = ProcessInfo.processInfo.environment["MODEL_SPEED_DIR"] else {
            throw XCTSkip("MODEL_SPEED_DIR is not set")
        }
        let folder = URL(fileURLWithPath: named)
        let flexibleURL = folder.appendingPathComponent("smollm2-135m.coreml-gpu-int4/model.mlmodelc")
        let fixedURL = folder.appendingPathComponent("smollm2-135m.coreml-ane-int4/model.mlmodelc")
        guard FileManager.default.fileExists(atPath: flexibleURL.path), FileManager.default.fileExists(atPath: fixedURL.path)
        else {
            throw XCTSkip("the two Core ML models of SmolLM2-135M are not in \(named)")
        }
        let flexible = try CoreMLSpeedScorer(compiledModel: flexibleURL, computeUnits: .cpuOnly)
        let fixed = try CoreMLSpeedScorer(compiledModel: fixedURL, computeUnits: .cpuOnly)
        XCTAssertNil(flexible.fixedShapes)
        XCTAssertEqual(fixed.fixedShapes?.map { [$0.tokens, $0.scored] },
                       [[8, 1], [12, 12], [16, 2], [24, 24], [32, 3], [40, 40], [56, 56], [64, 4]])
        let text = try String(contentsOf: ModelSpeedRun.resource("model-speed-tokens.smollm2-135m", "tsv"), encoding: .utf8)
        let requests = Array(try TokenRequest.read(text).prefix(100))
        var same = 0, widest = 0.0
        for request in requests {
            let one = try autoreleasepool { try flexible.score(request) }
            let other = try autoreleasepool { try fixed.score(request) }
            XCTAssertEqual(one.windowTokens, other.windowTokens)
            XCTAssertEqual(one.keptTokens, other.keptTokens)
            if topCandidate(one.scores) == topCandidate(other.scores) { same += 1 }
            for (a, b) in zip(one.scores, other.scores) {
                widest = max(widest, abs(a.logProbability - b.logProbability), abs(a.spaceAfter - b.spaceAfter))
            }
        }
        XCTAssertGreaterThanOrEqual(same, 95, "widest difference \(widest)")
    }

    func testTheStatisticsUseTheNearestRank() throws {
        let statistics = try XCTUnwrap(MillisecondStatistics([5, 1, 4, 2, 3, 10, 6, 7, 8, 9]))
        XCTAssertEqual(statistics.mean, 5.5)
        XCTAssertEqual(statistics.median, 5)
        XCTAssertEqual(statistics.percentile95, 10)
        XCTAssertEqual(statistics.worst, 10)
        XCTAssertNil(MillisecondStatistics([]))
    }

    func testTheTopCandidateHasTheHighestSum() {
        let scores = [
            CandidateScore(logProbability: -3, spaceAfter: -1), CandidateScore(logProbability: -2, spaceAfter: -1.5),
            CandidateScore(logProbability: -1, spaceAfter: -2.5),
        ]
        XCTAssertEqual(topCandidate(scores), 1)
    }

    func testTheSpeedTestRunsEveryPairAndPrintsEveryLine() async throws {
        let folder: URL
        if let named = ProcessInfo.processInfo.environment["MODEL_SPEED_DIR"] {
            folder = URL(fileURLWithPath: named)
        } else {
            folder = FileManager.default.temporaryDirectory.appendingPathComponent("no-speed-models-\(UUID().uuidString)")
        }
        var lines: [String] = []
        for await line in ModelSpeedTest(modelsFolder: folder).resultLines() {
            lines.append(line)
        }
        let report = lines.joined(separator: "\n")
        if let output = ProcessInfo.processInfo.environment["LANGUAGE_MODEL_OUTPUT_DIR"] {
            let url = URL(fileURLWithPath: output)
            try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
            try (report + "\n").write(to: url.appendingPathComponent("speed-simulator.txt"), atomically: true, encoding: .utf8)
        }
        let catalog = try ModelSpeedCatalog.bundled()
        XCTAssertEqual(lines.first, "test        speed of the language models, 486 requests per pair", report)
        let last = try XCTUnwrap(lines.last)
        XCTAssertTrue(last.hasPrefix("done        "), report)
        // Each pair that ran gives its eight lines in order. In the simulator llama.cpp's Metal
        // device does not load the model (run 43666561240), so only a Metal pair may fail, with
        // one "failed" line in place of its eight.
        let pairLines = lines.indices.filter { lines[$0].hasPrefix("pair        ") }
        XCTAssertEqual(pairLines.count, catalog.pairs.count, report)
        var ran = 0, metalFailures = 0
        for index in pairLines where !lines[index].hasSuffix(": not downloaded") {
            if lines[index].contains(", llama-metal"), lines[index + 1].hasPrefix("failed      ") {
                metalFailures += 1
                continue
            }
            let block = lines[(index + 1)...].prefix(8).map { String($0.prefix(12)) }
            XCTAssertEqual(
                block, ["load        ", "first       ", "request     ", "candidates  ", "window      ", "reuse       ",
                        "memory      ", "agreement   "], lines[index])
            ran += 1
        }
        // The keyboard's own model is in the bundle, so its processor pair always runs.
        XCTAssertGreaterThanOrEqual(ran, 1, report)
        XCTAssertEqual(last, "done        \(ran) pairs ran, \(pairLines.count - ran - metalFailures) not downloaded, "
            + "\(metalFailures) failed", report)
        // The keyboard's file on the processor agrees with the same file on the desktop. The
        // simulator's arm64 products differ from the desktop's x86 products in their last digits,
        // and that moved the top candidate in 2 of 486 requests in run 43666561240.
        let shipped = try XCTUnwrap(lines.firstIndex { $0.hasSuffix("bundled, llama-cpu") }, report)
        let agreement = try XCTUnwrap(lines[shipped...].first { $0.hasPrefix("agreement   ") })
        let agreeing = try XCTUnwrap(Int(agreement.split(separator: " ")[1]), agreement)
        XCTAssertGreaterThanOrEqual(agreeing, 480, agreement)
    }
}
