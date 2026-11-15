import CoreML
import Foundation
import os

/// The speed test of docs/model-speed-design.md. The person types "duo:speed" and a space, and
/// the keyboard runs every pair of `ModelSpeedCatalog` whose files are in place: one model and
/// one way to run it, on the same 486 requests of `model-speed-requests.tsv`, in order.
///
/// The test runs inside the keyboard extension, because the memory limit of the extension is the
/// one that counts. The keyboard frees its own model first (`onRunStart`) and loads it again
/// after (`onRunEnd`), so the process holds one test model at a time beside nothing else.
///
/// The result lines of each pair, a name in a column 12 wide and then the facts:
///   pair        the pair's number, its name, the model and the way to run it
///   load        the time of the load, the footprint right before and right after it, and the
///               memory that iOS still allows
///   first       the time of the first request, which pays for the first reads of the weights
///   request     the time of each later request, from the start of the request to its scores:
///               mean, median, 95th percentile and worst. This is the time a space press waits
///               when the model reads the whole request at the space.
///   candidates  the same for the candidate part of each request only. This is the time a space
///               press waits when the context part runs before the space.
///   window      the same for the context part of each request only
///   reuse       the context tokens that the cache already held, of all context tokens
///   memory      the highest footprint during the requests and the least memory iOS still allowed
///   agreement   the requests whose top candidate equals the top candidate of llama.cpp on the
///               same model at Q8_0 on the desktop. The top candidate has the highest log
///               probability plus space-after term.
/// A pair whose files are missing gives one "pair" line that says so. The last line starts with
/// "done". Each line also goes to the system log, subsystem com.yilongju.duokeyboard, category
/// speed.
@MainActor
final class ModelSpeedTest: LanguageModelMeasuring {
    /// Threads of llama.cpp, as the keyboard's model uses.
    nonisolated static let threads = KeyboardLanguageModel.threads
    nonisolated static let logger = Logger(subsystem: "com.yilongju.duokeyboard", category: "speed")

    /// Lines about the keyboard's own model before the test's lines.
    var keyboardLines: (@MainActor () -> [String])?
    var onRunStart: (@MainActor () -> Void)?
    var onRunEnd: (@MainActor () -> Void)?

    /// The folder of the downloaded models. Nil means the shared container of the app group.
    let modelsFolder: URL?
    /// The pairs to run, by runtime. Nil runs every pair of the catalog.
    let runtimes: Set<ModelSpeedCatalog.Runtime>?

    init(modelsFolder: URL? = nil, runtimes: Set<ModelSpeedCatalog.Runtime>? = nil) {
        self.modelsFolder = modelsFolder
        self.runtimes = runtimes
    }

    func resultLines() -> AsyncStream<String> {
        let (stream, continuation) = AsyncStream.makeStream(of: String.self)
        let emit: @Sendable (String) -> Void = { line in
            Self.logger.log("\(line, privacy: .public)")
            continuation.yield(line)
        }
        do {
            emit("test        speed of the language models, \(try ModelSpeedRun.textRequests().count) requests per pair")
        } catch {
            emit("test        speed of the language models, the requests did not load: \(error)")
        }
        for line in keyboardLines?() ?? [] { emit(line) }
        onRunStart?()
        let folder = modelsFolder ?? ModelSpeedCatalog.sharedFolder()
        let runtimes = self.runtimes
        let onRunEnd = self.onRunEnd
        let bundledModel = Bundle(for: ModelSpeedTest.self)
            .path(forResource: BundledLanguageModelTest.modelResource, ofType: "gguf")
        let (inner, innerContinuation) = AsyncStream.makeStream(of: String.self)
        Task { @MainActor in
            for await line in inner { emit(line) }
            onRunEnd?()
            continuation.finish()
        }
        let thread = Thread { @Sendable in
            ModelSpeedRun(
                folder: folder, bundledModelPath: bundledModel, runtimes: runtimes,
                emit: { innerContinuation.yield($0) }
            ).run()
            innerContinuation.finish()
        }
        // llama.cpp needs more than the 512 KB stack of a new thread, as in the language model test.
        thread.stackSize = 2 << 20
        thread.qualityOfService = .userInitiated
        thread.start()
        return stream
    }
}

/// One request of `model-speed-requests.tsv`: the context and the candidates, each candidate
/// with the space before it when the context is not empty, as speed_cli and kv_replay read them.
struct TextRequest: Equatable, Sendable {
    let context: String
    let candidates: [String]

    static func read(_ text: String) throws -> [TextRequest] {
        try text.split(separator: "\n", omittingEmptySubsequences: true).enumerated().map { index, line in
            let fields = line.split(separator: "\t", omittingEmptySubsequences: false).map(String.init)
            guard fields.count >= 2, fields.count <= Int(DUO_LM_MAX_CANDIDATES) + 1 else {
                throw ModelSpeedError("request line \(index + 1) holds \(fields.count) fields")
            }
            let space = fields[0].isEmpty ? "" : " "
            return TextRequest(context: fields[0], candidates: fields.dropFirst().map { space + $0 })
        }
    }
}

/// Mean, median, 95th percentile and worst of a list of milliseconds, with the nearest rank of
/// `RerankStatistics.percentileMilliseconds`.
struct MillisecondStatistics: Equatable, Sendable {
    let mean: Double
    let median: Double
    let percentile95: Double
    let worst: Double

    init?(_ values: [Double]) {
        guard !values.isEmpty else { return nil }
        let sorted = values.sorted()
        func rank(_ fraction: Double) -> Double {
            let place = Int((fraction * Double(sorted.count)).rounded(.up))
            return sorted[min(max(place, 1), sorted.count) - 1]
        }
        mean = values.reduce(0, +) / Double(values.count)
        median = rank(0.5)
        percentile95 = rank(0.95)
        worst = sorted[sorted.count - 1]
    }

    var description: String {
        String(format: "mean %.1f ms, median %.1f ms, 95th percentile %.1f ms, worst %.1f ms",
               mean, median, percentile95, worst)
    }
}

/// The top candidate: the highest log probability plus space-after term, the first on a tie.
func topCandidate(_ scores: [CandidateScore]) -> Int {
    var best = 0
    for index in scores.indices where scores[index].logProbability + scores[index].spaceAfter
        > scores[best].logProbability + scores[best].spaceAfter
    {
        best = index
    }
    return best
}

/// One run of the speed test on its own thread.
struct ModelSpeedRun {
    let folder: URL?
    /// The keyboard's own model file in the bundle, for the pairs of the model "bundled".
    let bundledModelPath: String?
    let runtimes: Set<ModelSpeedCatalog.Runtime>?
    let emit: (String) -> Void

    private static var bundle: Bundle { Bundle(for: ModelSpeedBundleToken.self) }

    static func resource(_ name: String, _ type: String) throws -> URL {
        guard let url = bundle.url(forResource: name, withExtension: type) else {
            throw ModelSpeedError("\(name).\(type) is missing from the bundle")
        }
        return url
    }

    static func textRequests() throws -> [TextRequest] {
        try TextRequest.read(String(contentsOf: resource("model-speed-requests", "tsv"), encoding: .utf8))
    }

    func run() {
        let catalog: ModelSpeedCatalog
        let requests: [TextRequest]
        let references: [String: [Int]]
        do {
            catalog = try ModelSpeedCatalog.bundled()
            requests = try Self.textRequests()
            references = try JSONDecoder().decode(
                [String: [Int]].self, from: Data(contentsOf: Self.resource("model-speed-reference", "json")))
        } catch {
            emit("done        failed before the first pair: \(error)")
            return
        }
        emit("models      \(folder?.path ?? "no shared container: the process has no access to the app group \(ModelSpeedCatalog.appGroup)")")
        let pairs = catalog.pairs.filter { runtimes?.contains($0.runtime) ?? true }
        var ran = 0, missing = 0, failed = 0
        for (index, pair) in pairs.enumerated() {
            let title = "pair        \(index + 1)/\(pairs.count) \(pair.name), \(pair.model), \(pair.runtime.rawValue)"
            guard let reference = references[pair.reference], reference.count == requests.count else {
                emit("\(title): failed: the reference \(pair.reference) does not hold \(requests.count) top candidates")
                failed += 1
                continue
            }
            let location: URL
            if pair.model == "bundled" {
                guard let path = bundledModelPath else {
                    emit("\(title): failed: the keyboard's model file is missing from the bundle")
                    failed += 1
                    continue
                }
                location = URL(fileURLWithPath: path)
            } else {
                guard let model = catalog.model(id: pair.model) else {
                    emit("\(title): failed: the catalog has no model \(pair.model)")
                    failed += 1
                    continue
                }
                guard let folder, Self.present(model, in: folder) else {
                    emit("\(title): not downloaded")
                    missing += 1
                    continue
                }
                let file = pair.runtime.isLlama ? "model.gguf" : "model.mlmodelc"
                location = folder.appendingPathComponent(model.id, isDirectory: true).appendingPathComponent(file)
            }
            emit(title)
            do {
                if pair.runtime.isLlama {
                    try runLlama(pair: pair, path: location.path, requests: requests, reference: reference)
                } else {
                    guard let tokensName = pair.tokens else {
                        throw ModelSpeedError("a Core ML pair needs a token file")
                    }
                    let tokens = try TokenRequest.read(String(
                        contentsOf: Self.resource("model-speed-tokens.\(tokensName)", "tsv"), encoding: .utf8))
                    guard tokens.count == requests.count else {
                        throw ModelSpeedError("the token file holds \(tokens.count) requests, not \(requests.count)")
                    }
                    try runCoreML(pair: pair, url: location, requests: tokens, reference: reference)
                }
                ran += 1
            } catch {
                emit("failed      \(error)")
                failed += 1
            }
        }
        emit("done        \(ran) pairs ran, \(missing) not downloaded, \(failed) failed")
    }

    /// True when every file of the model is in place with its size. The app checked each SHA-256
    /// value at the download.
    static func present(_ model: ModelSpeedCatalog.Model, in folder: URL) -> Bool {
        let base = folder.appendingPathComponent(model.id, isDirectory: true)
        return model.files.allSatisfy { file in
            let path = base.appendingPathComponent(file.path).path
            guard let size = (try? FileManager.default.attributesOfItem(atPath: path))?[.size] as? NSNumber else {
                return false
            }
            return size.int64Value == file.bytes
        }
    }

    private static func now() -> Double { ProcessInfo.processInfo.systemUptime * 1000 }

    private func emitLoad(milliseconds: Double, before: ProcessMemory?, after: ProcessMemory?) {
        guard let before, let after else {
            emit(String(format: "load        %.1f ms, the footprint is not known", milliseconds))
            return
        }
        emit(String(
            format: "load        %.1f ms, footprint %.1f MB before and %.1f MB after, still allowed %.1f MB",
            milliseconds, before.footprintMB, after.footprintMB, after.availableMB))
    }

    /// The lines after the load, from the times of each request.
    private func emitRequests(
        first: Double, totals: [Double], candidates: [Double], windows: [Double], windowTokens: Int, keptTokens: Int,
        highest: Double, leastAllowed: Double, agreeing: Int, count: Int
    ) {
        emit(String(format: "first       request %.1f ms", first))
        let later = { (values: [Double]) in MillisecondStatistics(Array(values.dropFirst()))?.description ?? "none" }
        emit("request     \(later(totals))")
        emit("candidates  \(later(candidates))")
        emit("window      \(later(windows))")
        emit(String(format: "reuse       %d of %d context tokens from the cache (%.1f%%)", keptTokens, windowTokens,
                    windowTokens > 0 ? 100 * Double(keptTokens) / Double(windowTokens) : 0))
        emit(String(format: "memory      highest footprint %.1f MB during the requests, least still allowed %.1f MB",
                    highest, leastAllowed))
        emit(String(format: "agreement   %d of %d top candidates (%.1f%%) equal llama.cpp Q8_0 on the desktop",
                    agreeing, count, 100 * Double(agreeing) / Double(count)))
    }

    private func runLlama(pair: ModelSpeedCatalog.Pair, path: String, requests: [TextRequest], reference: [Int]) throws {
        let device: duo_lm_device = pair.runtime == .llamaProcessor ? DUO_LM_DEVICE_CPU : DUO_LM_DEVICE_GPU
        // llama.cpp reads the variable when it creates a buffer of the Metal device.
        if pair.runtime == .llamaMetalNoResidency {
            setenv("GGML_METAL_NO_RESIDENCY", "1", 1)
        }
        defer { if pair.runtime == .llamaMetalNoResidency { unsetenv("GGML_METAL_NO_RESIDENCY") } }
        let before = ProcessMemory.now()
        let started = Self.now()
        let errorSize = Int(DUO_LM_ERROR_SIZE)
        var error = [CChar](repeating: 0, count: errorSize)
        let reuse = KeyboardLanguageModel.reuse
        guard let scorer = duo_lm_scorer_open_on(path, Int32(ModelSpeedTest.threads), reuse, device, &error, errorSize)
        else {
            throw ModelSpeedError("the model did not load: \(String(cString: error))")
        }
        defer { duo_lm_scorer_close(scorer) }
        emitLoad(milliseconds: Self.now() - started, before: before, after: ProcessMemory.now())
        var totals: [Double] = [], candidates: [Double] = [], windows: [Double] = []
        var highest = 0.0, leastAllowed = Double.greatestFiniteMagnitude, agreeing = 0
        for (index, request) in requests.enumerated() {
            let copies = request.candidates.map { strdup($0) }
            defer { copies.forEach { free($0) } }
            let pointers = copies.map { UnsafePointer<CChar>($0) }
            var scores = [duo_lm_score](repeating: duo_lm_score(), count: request.candidates.count)
            let beforeInfo = duo_lm_scorer_get_info(scorer)
            let requestStarted = Self.now()
            let result = pointers.withUnsafeBufferPointer { pointerBuffer in
                scores.withUnsafeMutableBufferPointer { scoreBuffer in
                    duo_lm_scorer_score(
                        scorer, request.context, pointerBuffer.baseAddress, Int32(request.candidates.count),
                        scoreBuffer.baseAddress, &error, errorSize)
                }
            }
            let total = Self.now() - requestStarted
            guard result == 1 else {
                throw ModelSpeedError("request \(index + 1) gave \(result): \(String(cString: error))")
            }
            let afterInfo = duo_lm_scorer_get_info(scorer)
            totals.append(total)
            windows.append(afterInfo.window_milliseconds - beforeInfo.window_milliseconds)
            candidates.append(afterInfo.candidate_milliseconds - beforeInfo.candidate_milliseconds)
            if let memory = ProcessMemory.now() {
                highest = max(highest, memory.footprintMB)
                leastAllowed = min(leastAllowed, memory.availableMB)
            }
            let top = topCandidate(scores.map { CandidateScore(logProbability: $0.log_probability, spaceAfter: $0.space_after) })
            if top == reference[index] { agreeing += 1 }
        }
        let info = duo_lm_scorer_get_info(scorer)
        emitRequests(
            first: totals[0], totals: totals, candidates: candidates, windows: windows,
            windowTokens: info.window_tokens, keptTokens: info.window_tokens_reused, highest: highest,
            leastAllowed: leastAllowed, agreeing: agreeing, count: requests.count)
    }

    private func runCoreML(pair: ModelSpeedCatalog.Pair, url: URL, requests: [TokenRequest], reference: [Int]) throws {
        let units: MLComputeUnits = pair.runtime == .coreMLGPU ? .cpuAndGPU : .all
        let before = ProcessMemory.now()
        let started = Self.now()
        let scorer = try CoreMLSpeedScorer(compiledModel: url, computeUnits: units)
        emitLoad(milliseconds: Self.now() - started, before: before, after: ProcessMemory.now())
        var totals: [Double] = [], candidates: [Double] = [], windows: [Double] = []
        var highest = 0.0, leastAllowed = Double.greatestFiniteMagnitude, agreeing = 0
        var windowTokens = 0, keptTokens = 0
        for (index, request) in requests.enumerated() {
            let requestStarted = Self.now()
            let result = try scorer.score(request)
            totals.append(Self.now() - requestStarted)
            windows.append(result.windowMilliseconds)
            candidates.append(result.candidateMilliseconds)
            windowTokens += result.windowTokens
            keptTokens += result.keptTokens
            if let memory = ProcessMemory.now() {
                highest = max(highest, memory.footprintMB)
                leastAllowed = min(leastAllowed, memory.availableMB)
            }
            if topCandidate(result.scores) == reference[index] { agreeing += 1 }
        }
        emitRequests(
            first: totals[0], totals: totals, candidates: candidates, windows: windows, windowTokens: windowTokens,
            keptTokens: keptTokens, highest: highest, leastAllowed: leastAllowed, agreeing: agreeing,
            count: requests.count)
    }
}

extension ModelSpeedCatalog.Runtime {
    var isLlama: Bool {
        switch self {
        case .llamaProcessor, .llamaMetal, .llamaMetalNoResidency: return true
        case .coreMLGPU, .coreMLAll: return false
        }
    }
}

private final class ModelSpeedBundleToken {}
