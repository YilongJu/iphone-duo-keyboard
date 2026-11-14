import XCTest

@testable import DuoKeyboard

/// Tests of the C scorer (LanguageModel/duo_lm_scorer.c) with the model file of the app bundle,
/// inside the simulator. A model that does not load fails every test here.
@MainActor
final class LanguageModelScorerTests: XCTestCase {
    private static var loaded: KeyboardLanguageModel?

    private func model() throws -> KeyboardLanguageModel {
        if let loaded = Self.loaded { return loaded }
        let model = KeyboardLanguageModel.bundled(cacheCheckTolerance: nil)
        do {
            try model.loadNow()
        } catch let error as LanguageModelError {
            XCTFail("the bundled language model did not load: \(error.reason)")
            throw error
        }
        Self.loaded = model
        return model
    }

    private func scores(_ context: String, _ candidates: [String]) throws -> [CandidateScore] {
        let result = try model().score(LanguageModelPrompt(context: context, candidates: candidates))
        guard case .scores(let scores) = result else {
            XCTFail("the model did not score \(candidates) after \"\(context)\": \(result)")
            throw CocoaError(.featureUnsupported)
        }
        return scores
    }

    private let context = "I missed the early train this morning, so I think I will have to go to the office by"
    private let eight = [" bus", " car", " taxi", " bike", " the subway", " the next train", " public transport", " my own car"]

    func testTheBundledModelLoadsWithTwoThreads() throws {
        let model = try model()
        XCTAssertEqual(model.state, .ready)
        XCTAssertEqual(KeyboardLanguageModel.threads, 2)
        let info = try XCTUnwrap(model.scorerInfo)
        XCTAssertEqual(info.vocabulary, 49152)
    }

    func testEveryCandidateGetsAProbabilityAndTheLikelyOneIsHigher() throws {
        let values = try scores("I will take the", [" bus", " banana"])
        XCTAssertEqual(values.count, 2)
        for value in values {
            XCTAssertTrue(value.logProbability.isFinite && value.logProbability < 0, "\(value)")
            XCTAssertTrue(value.spaceAfter.isFinite && value.spaceAfter < 0, "\(value)")
        }
        XCTAssertGreaterThan(values[0].logProbability, values[1].logProbability)
    }

    func testACandidateGetsTheSameScoresAloneAndAmongEight() throws {
        let together = try scores(context, eight)
        for (index, candidate) in eight.enumerated() {
            let alone = try scores(context, [candidate])[0]
            XCTAssertEqual(alone.logProbability, together[index].logProbability, accuracy: 1e-3, candidate)
            XCTAssertEqual(alone.spaceAfter, together[index].spaceAfter, accuracy: 1e-3, candidate)
        }
    }

    func testCandidatesOfMoreThanOneCallOfTheModelGetTheSameScores() throws {
        // Eight candidates of several tokens each take more than the 31 tokens of one call.
        let long = (0..<8).map { " the most unbelievably extraordinary journey number \($0) of all" }
        let together = try scores(context, long)
        let before = try XCTUnwrap(model().scorerInfo).tokens_read
        _ = try scores(context, [long[7]])
        let after = try XCTUnwrap(model().scorerInfo).tokens_read
        XCTAssertLessThan(after - before, 40)
        let alone = try scores(context, [long[7]])[0]
        XCTAssertEqual(alone.logProbability, together[7].logProbability, accuracy: 1e-3)
        XCTAssertEqual(alone.spaceAfter, together[7].spaceAfter, accuracy: 1e-3)
    }

    func testAContextOfOneTokenMoreThanACallGivesTheNumbersOfLmScore() throws {
        // This context is 32 tokens with the start token, one more than a call of the scorer. The
        // scorer reads it as two calls of 16 tokens (call_size in LanguageModel/duo_lm_scorer.c).
        // lm_score gives -28.46739 and -0.02816 for " egg nns" on the macOS runner, in run
        // 43477574581 of scripts/lm-keyboard/scorer-probe. The simulator part of the app's
        // framework computes as that runner does (scripts/lm-keyboard/README.md, Table 7).
        let context = "To bridge this gap, we propose SHiFT, which synergizes the reasoning power of LLMs with the "
            + "structural representation capability of | ggnns |"
        let value = try scores(context, [" egg nns"])[0]
        XCTAssertEqual(value.logProbability, -28.46739, accuracy: 0.01)
        XCTAssertEqual(value.spaceAfter, -0.02816, accuracy: 0.01)
    }

    func testTextsWithLoneSpacePiecesGiveScores() throws {
        // These texts give a lone space piece in the GPT-2 vocabulary (scripts/lm-rerank/README.md).
        // The SmolLM2 vocabulary has its own merges, so the count of repairs is not fixed here.
        let values = try scores("he said", [" ich", " itch", " ike", " uring"])
        XCTAssertTrue(values.allSatisfy { $0.logProbability.isFinite }, "\(values)")
    }

    func testALineBreakInTheContextGetsTheLineBreakToken() throws {
        let before = try XCTUnwrap(model().scorerInfo).line_break_repairs
        let values = try scores("Dear John,\nthank you for the", [" letter", " lettre"])
        XCTAssertTrue(values.allSatisfy { $0.logProbability.isFinite }, "\(values)")
        XCTAssertGreaterThan(try XCTUnwrap(model().scorerInfo).line_break_repairs, before)
        XCTAssertGreaterThan(values[0].logProbability, values[1].logProbability)
    }

    func testALongContextKeepsItsLastTokens() throws {
        let long = String(repeating: "We walked along the river and talked about the weather. ", count: 30) + "Then we took the"
        let values = try scores(long, [" bus", " banana"])
        XCTAssertGreaterThan(values[0].logProbability, values[1].logProbability)
    }

    func testRequestsOutsideTheLimitsAreRefused() throws {
        let model = try model()
        let long = " " + String(repeating: "zq", count: 60)
        guard case .refused(let reason) = model.score(LanguageModelPrompt(context: "the", candidates: [long])) else {
            return XCTFail("a candidate of more than 32 tokens must be refused")
        }
        XCTAssertTrue(reason.contains("the limit is 1 to 32"), reason)
        let nine = Array(repeating: " bus", count: 9)
        guard case .refused = model.score(LanguageModelPrompt(context: "the", candidates: nine)) else {
            return XCTFail("nine candidates must be refused")
        }
        // The model still scores after a refused request.
        XCTAssertEqual(try scores("I will take the", [" bus"]).count, 1)
    }

    func testAMemoryWarningFreesTheModelAndALaterLoadBringsItBack() throws {
        let model = KeyboardLanguageModel.bundled(cacheCheckTolerance: nil)
        var events: [LanguageModelEvent] = []
        model.onEvent = { events.append($0) }
        try model.loadNow()
        model.unload(reason: "memory warning")
        XCTAssertEqual(model.state, .freed("memory warning"))
        XCTAssertNil(model.scorerInfo)
        XCTAssertEqual(model.score(LanguageModelPrompt(context: "", candidates: ["a", "b"])),
                       .notReady("the model was freed: memory warning"))
        model.loadInBackground()
        let deadline = Date().addingTimeInterval(30)
        while model.state == .loading, Date() < deadline {
            RunLoop.current.run(until: Date().addingTimeInterval(0.05))
        }
        XCTAssertEqual(model.state, .ready)
        XCTAssertEqual(events, [.ready, .freed("memory warning"), .ready])
    }

    func testTheReportNamesTheTimeAndTheMemory() throws {
        let model = try model()
        var statistics = RerankStatistics()
        statistics.recordRead(milliseconds: 21.5, changed: false)
        let lines = model.reportLines(statistics: statistics)
        XCTAssertTrue(lines[0].hasPrefix("reranker    smollm2-lora-domain-s100-seed1.Q4_K_M, 2 threads, loaded in "), lines[0])
        XCTAssertTrue(lines.contains { $0.contains("footprint") && $0.contains("before the load") }, "\(lines)")
        XCTAssertTrue(lines.contains { $0.contains("1 corrections read by the model") && $0.contains("mean 21.5 ms") }, "\(lines)")
        XCTAssertTrue(lines.allSatisfy { $0.count > 12 && $0.prefix(12).last == " " }, "\(lines)")
        XCTAssertFalse(lines.joined().contains("failed"), "\(lines)")
    }
}
