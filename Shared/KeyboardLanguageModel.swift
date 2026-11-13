import Foundation
import os

/// The C scorer of LanguageModel/duo_lm_scorer.h with one loaded model.
///
/// One thread at a time uses an object: the thread that loads the model creates it, and the
/// main thread uses and frees it after that. The object is marked Sendable for that handover.
final class LanguageModelScorer: @unchecked Sendable {
    private let handle: OpaquePointer

    /// Loads the model. The error holds the reason when the model does not load.
    init(modelPath: String, threads: Int) throws {
        let errorSize = Int(DUO_LM_ERROR_SIZE)
        var error = [CChar](repeating: 0, count: errorSize)
        guard let opened = duo_lm_scorer_open(modelPath, Int32(threads), &error, errorSize) else {
            throw LanguageModelError(reason: String(cString: error))
        }
        handle = opened
    }

    deinit {
        duo_lm_scorer_close(handle)
    }

    /// Scores the candidates after the context, as `duo_lm_scorer_score` describes.
    func scores(context: String, candidates: [String]) -> CandidateScoringResult {
        let copies = candidates.map { strdup($0) }
        defer { copies.forEach { free($0) } }
        let pointers = copies.map { UnsafePointer<CChar>($0) }
        var scores = [duo_lm_score](repeating: duo_lm_score(), count: candidates.count)
        let errorSize = Int(DUO_LM_ERROR_SIZE)
        var error = [CChar](repeating: 0, count: errorSize)
        let result = pointers.withUnsafeBufferPointer { pointerBuffer in
            scores.withUnsafeMutableBufferPointer { scoreBuffer in
                duo_lm_scorer_score(
                    handle, context, pointerBuffer.baseAddress, Int32(candidates.count), scoreBuffer.baseAddress,
                    &error, errorSize)
            }
        }
        switch result {
        case 1:
            return .scores(scores.map { CandidateScore(logProbability: $0.log_probability, spaceAfter: $0.space_after) })
        case 0:
            return .refused(String(cString: error))
        default:
            return .failed(String(cString: error))
        }
    }

    var info: duo_lm_scorer_info { duo_lm_scorer_get_info(handle) }
}

struct LanguageModelError: Error, Equatable {
    let reason: String
}

/// The memory of this process, as iOS counts it against the limit of a keyboard.
struct ProcessMemory: Equatable, Sendable {
    static let bytesPerMB = 1_048_576.0

    /// The footprint: the value iOS holds against the limit.
    let footprintMB: Double
    /// The highest footprint of the process so far.
    let highestMB: Double
    /// The memory iOS still allows the process. The simulator does not set a limit and gives 0.
    let availableMB: Double

    /// The memory now, or nil when iOS refuses to say.
    static func now() -> ProcessMemory? {
        var info = task_vm_info_data_t()
        var count = mach_msg_type_number_t(MemoryLayout<task_vm_info_data_t>.size / MemoryLayout<integer_t>.size)
        let result = withUnsafeMutablePointer(to: &info) { pointer in
            pointer.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                task_info(mach_task_self_, task_flavor_t(TASK_VM_INFO), $0, &count)
            }
        }
        guard result == KERN_SUCCESS else { return nil }
        return ProcessMemory(
            footprintMB: Double(info.phys_footprint) / bytesPerMB,
            highestMB: Double(info.ledger_phys_footprint_peak) / bytesPerMB,
            availableMB: Double(os_proc_available_memory()) / bytesPerMB)
    }

    /// The memory in the words of the language model test's memory lines.
    var description: String {
        String(format: "footprint %.1f MB, highest %.1f MB, still allowed %.1f MB", footprintMB, highestMB, availableMB)
    }
}

/// A change of the language model that the space bar names.
enum LanguageModelEvent: Equatable {
    case ready
    /// The model did not load, for the reason given.
    case loadFailed(String)
    /// The model was freed, for the reason given, such as a memory warning.
    case freed(String)
    /// The model or its tokenizer did not score a correction, for the reason given.
    case modelError(String)
}

/// The time of a load, and the memory right before and right after it.
struct LanguageModelLoadMeasurement: Equatable, Sendable {
    let milliseconds: Double
    let before: ProcessMemory?
    let after: ProcessMemory?
}

/// The result of a load, which the loading thread hands to the main thread.
struct LanguageModelLoadOutcome: Sendable {
    let scorer: LanguageModelScorer?
    let error: String?
    let measurement: LanguageModelLoadMeasurement
}

/// Loads the language model of the English corrections.
@MainActor
protocol LanguageModelLoading: AnyObject {
    /// Starts a load on a thread of its own, unless the model is loaded or loading.
    func loadInBackground()
}

/// The language model of the English corrections: the SmolLM2-135M fine-tune of the bundle,
/// loaded once and kept loaded until a memory warning frees it.
///
/// The keyboard asks for a load when it appears in English and when the person switches to
/// English, so Chinese typing never loads the model. A correction made before the model is
/// ready keeps the engine's choice. A model that does not load is named on the space bar.
@MainActor
final class KeyboardLanguageModel: CandidateScoring, LanguageModelLoading {
    /// Threads of each call of the model, the count measured on the iPhone Duo.
    nonisolated static let threads = 2

    /// The rule of the bundled model: the setting of scripts/lm-domain/candidate.json, which the
    /// one read of the confirmation set confirmed (docs/lm-domain-results.md). The weight is 1.5.
    /// A move away from the text as typed needs a lead of 1, a move back to it 4, and a move
    /// between two corrections 2. The model reads the typed format of `LanguageModelPrompt.make`.
    /// The apostrophe step has the scope and score of `RerankRule.distilgpt2WithApostrophes`
    /// (docs/apostrophe-words-design.md). It reads the stock prompt, at the lead 0.5 of
    /// candidate.json.
    nonisolated static let rule = RerankRule(
        weight: 1.5, marginFromTyped: 1, marginToTyped: 4, marginOther: 2, usesSpaceAfter: true,
        apostrophe: RerankRule.ApostropheStep(scope: .firstWordOfSpan, score: .modelLessSlipCost, margin: 0.5, prompt: .stock))

    enum State: Equatable {
        case notLoaded
        case loading
        case ready
        case loadFailed(String)
        case freed(String)
    }

    private(set) var state: State = .notLoaded
    private var scorer: LanguageModelScorer?
    /// Counts the loads, so a load that ends after a memory warning freed its model is dropped.
    private var generation = 0
    /// The model file, or nil when the bundle does not hold it.
    let modelPath: String?
    let modelName: String
    /// Receives each change of the model on the main thread.
    var onEvent: (LanguageModelEvent) -> Void = { _ in }

    /// The last load that worked: its time, and the memory right before and right after it.
    private(set) var lastLoad: LanguageModelLoadMeasurement?
    /// The memory right after the first correction that the model read, when the model's
    /// buffers for scores exist.
    private(set) var afterFirstScore: ProcessMemory?

    init(modelPath: String?, modelName: String) {
        self.modelPath = modelPath
        self.modelName = modelName
    }

    /// The model file of the bundle. scripts/ci/fetch_language_model.sh downloads it before the build.
    static func bundled() -> KeyboardLanguageModel {
        let name = BundledLanguageModelTest.modelResource
        return KeyboardLanguageModel(
            modelPath: Bundle(for: KeyboardLanguageModel.self).path(forResource: name, ofType: "gguf"),
            modelName: name)
    }

    private nonisolated static func open(path: String?, name: String) -> LanguageModelLoadOutcome {
        let before = ProcessMemory.now()
        let started = ProcessInfo.processInfo.systemUptime
        guard let path else {
            return LanguageModelLoadOutcome(
                scorer: nil, error: "\(name).gguf is missing from the bundle",
                measurement: LanguageModelLoadMeasurement(milliseconds: 0, before: before, after: before))
        }
        do {
            let scorer = try LanguageModelScorer(modelPath: path, threads: threads)
            let milliseconds = (ProcessInfo.processInfo.systemUptime - started) * 1000
            return LanguageModelLoadOutcome(
                scorer: scorer, error: nil,
                measurement: LanguageModelLoadMeasurement(milliseconds: milliseconds, before: before, after: ProcessMemory.now()))
        } catch let error as LanguageModelError {
            return LanguageModelLoadOutcome(
                scorer: nil, error: error.reason,
                measurement: LanguageModelLoadMeasurement(milliseconds: 0, before: before, after: ProcessMemory.now()))
        } catch {
            return LanguageModelLoadOutcome(
                scorer: nil, error: "\(error)",
                measurement: LanguageModelLoadMeasurement(milliseconds: 0, before: before, after: ProcessMemory.now()))
        }
    }

    func loadInBackground() {
        switch state {
        case .loading, .ready: return
        case .notLoaded, .loadFailed, .freed: break
        }
        generation += 1
        let loadGeneration = generation
        state = .loading
        let path = modelPath
        let name = modelName
        // A new thread gets a stack of 512 KB, and llama.cpp gets 2 MB here, as in the test.
        let thread = Thread { @Sendable in
            let outcome = KeyboardLanguageModel.open(path: path, name: name)
            Task { @MainActor in
                self.finishLoad(outcome, generation: loadGeneration)
            }
        }
        thread.stackSize = 2 << 20
        thread.qualityOfService = .userInitiated
        thread.start()
    }

    /// Loads the model on the calling thread, for the tests. Throws the reason when the model
    /// does not load.
    func loadNow() throws {
        precondition(state != .loading, "a load is running on its own thread")
        if state == .ready { return }
        generation += 1
        state = .loading
        let outcome = Self.open(path: modelPath, name: modelName)
        finishLoad(outcome, generation: generation)
        if let error = outcome.error {
            throw LanguageModelError(reason: error)
        }
    }

    private func finishLoad(_ outcome: LanguageModelLoadOutcome, generation loadGeneration: Int) {
        // A memory warning freed the model while it loaded, so the new model goes away at once.
        guard loadGeneration == generation, state == .loading else { return }
        if let scorer = outcome.scorer {
            self.scorer = scorer
            lastLoad = outcome.measurement
            state = .ready
            onEvent(.ready)
        } else {
            let reason = outcome.error ?? "the scorer gave no reason"
            state = .loadFailed(reason)
            onEvent(.loadFailed(reason))
        }
    }

    /// Frees the model, as on a memory warning. The next load starts over.
    func unload(reason: String) {
        switch state {
        case .ready, .loading:
            generation += 1
            scorer = nil
            state = .freed(reason)
            onEvent(.freed(reason))
        case .notLoaded, .loadFailed, .freed:
            return
        }
    }

    func score(_ prompt: LanguageModelPrompt) -> CandidateScoringResult {
        guard let scorer else {
            switch state {
            case .notLoaded: return .notReady("the model is not loaded")
            case .loading: return .notReady("the model is loading")
            case .loadFailed(let reason): return .notReady("the model did not load: \(reason)")
            case .freed(let reason): return .notReady("the model was freed: \(reason)")
            case .ready: preconditionFailure("a ready model has a scorer")
            }
        }
        let result = scorer.scores(context: prompt.context, candidates: prompt.candidates)
        if case .scores = result, afterFirstScore == nil {
            afterFirstScore = ProcessMemory.now()
        }
        return result
    }

    /// The counts of the C scorer, while a model is loaded.
    var scorerInfo: duo_lm_scorer_info? { scorer?.info }

    /// Result lines for the language model test (`duo:lm`), in its format: a name in a column
    /// 12 wide, then the facts. LanguageModelTest.swift describes the "reranker" lines.
    func reportLines(statistics: RerankStatistics) -> [String] {
        func format(_ value: Double?) -> String { value.map { String(format: "%.1f ms", $0) } ?? "none" }
        var lines: [String] = []
        let stateText: String
        switch state {
        case .notLoaded: stateText = "not loaded"
        case .loading: stateText = "loading"
        case .ready: stateText = String(format: "loaded in %.0f ms", lastLoad?.milliseconds ?? 0)
        case .loadFailed(let reason): stateText = "load failed: \(reason)"
        case .freed(let reason): stateText = "freed: \(reason)"
        }
        lines.append("reranker    \(modelName), \(Self.threads) threads, \(stateText)")
        if let load = lastLoad, let before = load.before, let after = load.after {
            var memory = String(
                format: "reranker    footprint %.1f MB before the load, %.1f MB after it", before.footprintMB,
                after.footprintMB)
            if let first = afterFirstScore {
                memory += String(format: ", %.1f MB after the first correction", first.footprintMB)
            }
            lines.append(memory)
        }
        lines.append(
            "reranker    \(statistics.readCount) corrections read by the model, time added to each space press: "
                + "mean \(format(statistics.meanMilliseconds)), median \(format(statistics.percentileMilliseconds(0.5))), "
                + "95th percentile \(format(statistics.percentileMilliseconds(0.95))), "
                + "worst \(format(statistics.readCount > 0 ? statistics.worstMilliseconds : nil))")
        lines.append(
            "reranker    the model changed \(statistics.changedCount) of \(statistics.readCount) choices, "
                + "\(statistics.notReadyCount) corrections came while the model was not ready, "
                + "\(statistics.refusedCount) were outside its limits, \(statistics.failedCount) gave a model error")
        if let info = scorerInfo {
            lines.append(
                "reranker    start token \(info.start_token), \(info.requests) requests, \(info.tokens_read) tokens read, "
                    + "\(info.space_repairs) space and \(info.line_break_repairs) line break tokens put in place of -1")
        }
        if let problem = statistics.lastProblem {
            lines.append("reranker    last problem: \(problem)")
        }
        if let now = ProcessMemory.now() {
            lines.append("memory      before the test, with the keyboard's model: \(now.description)")
        }
        return lines
    }
}
