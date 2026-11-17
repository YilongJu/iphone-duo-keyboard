import CoreML
import Foundation
import os

/// The speed test of docs/model-speed-design.md. The person types "duo:speed" and a space, and
/// the keyboard runs every pair of `ModelSpeedCatalog` whose files are in place: one model and
/// one way to run it, on the same 486 requests of `model-speed-requests.tsv`, in order.
///
/// The test runs inside the keyboard extension, because the memory limit of the extension is the
/// one that counts. The keyboard frees its own model first and keeps it freed until the run ends
/// (`onRunStart`, `onRunEnd`), so the process holds one test model at a time beside nothing else.
///
/// Before each pair that runs, the test pauses for `pauseSeconds` and then waits until the
/// thermal state of the phone is nominal, for at most `coolingLimitSeconds`.
///
/// The result lines of each pair, a name in a column 12 wide and then the facts:
///   pair        the pair's number, its name, the model and the way to run it
///   load        the time of the load, the time of a second load after a close, the share of the
///               weight file that was in memory before the first load, the footprint right
///               before the first load and right after the second, and the memory that iOS
///               still allows. The requests run on the model of the second load.
///   first       the time of the first request, which pays for the first reads of the weights
///   request     the time of each later request, from its tokens to its scores: mean, median,
///               95th percentile and worst. This is the time a space press waits when the model
///               reads the whole request at the space. The tokenizer is left out, because the
///               Core ML pairs read tokens made in advance.
///   candidates  the same for the candidate part of each request only. This is the time a space
///               press waits when the context part runs before the space.
///   window      the same for the context part of each request only
///   reuse       the context tokens that the cache already held, of all context tokens
///   memory      the highest footprint during the loads and during the requests, sampled every
///               2 ms on a thread of its own, the highest footprint of the process so far as
///               iOS counts it and whether this pair set it, and the least memory iOS still
///               allowed
///   agreement   the requests whose top candidate equals the top candidate of llama.cpp on the
///               same model at Q8_0 on the desktop. The top candidate has the highest log
///               probability plus space-after term.
///   tokenizer   the time of llama.cpp's tokenizer per request, which the request time leaves out
///   processor   the processor time of the whole process per request, and its ratio to the
///               request time: about the count of busy threads
///   units       where the model ran: llama.cpp's device and threads, and for Metal whether
///               llama.cpp kept residency sets; for Core ML the compute units, the form of the
///               model, the calls, and Core ML's plan of the devices of its operations
///   heat        the thermal state at the start of the pair and the worst during it, and the pause
/// A pair whose files are missing gives one "pair" line that says so. A pair that fails gives a
/// "failed" line after its "pair" line. The last line starts with "done". Each line also goes to
/// the system log, subsystem com.yilongju.duokeyboard, category speed.
///
/// With a progress folder, the test keeps its record until "duo:speedreset": each later
/// "duo:speed" shows the lines of the pairs that ended in earlier runs and runs only the rest.
/// A pair that was running when a run stopped (iOS stopped the keyboard, or the keyboard
/// crashed) runs again, and a pair that stopped `ModelSpeedProgress.stopLimit` runs is skipped.
@MainActor
final class ModelSpeedTest: LanguageModelMeasuring {
    /// Threads of llama.cpp, as the keyboard's model uses.
    nonisolated static let threads = KeyboardLanguageModel.threads
    nonisolated static let logger = Logger(subsystem: "com.yilongju.duokeyboard", category: "speed")

    /// Lines about the keyboard's own model before the test's lines.
    var keyboardLines: (@MainActor () -> [String])?
    /// Frees the keyboard's model and calls `ready` once no thread holds a copy of it.
    var onRunStart: (@MainActor (_ ready: @escaping @MainActor () -> Void) -> Void)?
    var onRunEnd: (@MainActor () -> Void)?

    /// The folder of the downloaded models. Nil means the shared container of the app group.
    let modelsFolder: URL?
    /// The pairs to run, by runtime. Nil runs every pair of the catalog.
    let runtimes: Set<ModelSpeedCatalog.Runtime>?
    /// The folder that records which pairs started and ended and keeps their lines, or nil for a
    /// run that always starts at the first pair.
    let progressFolder: URL?
    let pauseSeconds: Double
    let coolingLimitSeconds: Double
    /// Where the run is now.
    let status = ModelSpeedStatus()
    /// The file of the MetricKit diagnostics (`ModelSpeedDiagnostics`), whose lines each run
    /// shows near its start. Nil shows none.
    let diagnosticsFile: URL?
    /// The pair to start at, counting from 1, for the next run. The pairs before it that did not
    /// end in an earlier run are skipped, and the start pair runs even after earlier stops. Nil
    /// starts at the first pair.
    var startPair: Int?
    private var running = false

    init(modelsFolder: URL? = nil, runtimes: Set<ModelSpeedCatalog.Runtime>? = nil, progressFolder: URL? = nil,
         diagnosticsFile: URL? = nil,
         pauseSeconds: Double = 20, coolingLimitSeconds: Double = 180) {
        self.modelsFolder = modelsFolder
        self.runtimes = runtimes
        self.progressFolder = progressFolder
        self.diagnosticsFile = diagnosticsFile
        self.pauseSeconds = pauseSeconds
        self.coolingLimitSeconds = coolingLimitSeconds
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
        if let diagnosticsFile {
            do {
                let saved = try ModelSpeedDiagnostics.saved(diagnosticsFile)
                if saved.isEmpty { emit("diagnostic  none: MetricKit has delivered no diagnostic of this keyboard") }
                for line in saved { emit(line) }
            } catch {
                emit("diagnostic  the diagnostics file did not load: \(error)")
            }
        }
        let folder = modelsFolder ?? ModelSpeedCatalog.sharedFolder()
        let bundledModel = Bundle(for: ModelSpeedTest.self)
            .path(forResource: BundledLanguageModelTest.modelResource, ofType: "gguf")
        let runtimes = self.runtimes, progressFolder = self.progressFolder, startPair = self.startPair
        let pauseSeconds = self.pauseSeconds, coolingLimitSeconds = self.coolingLimitSeconds
        let onRunEnd = self.onRunEnd
        let status = self.status
        status.start()
        status.setPauseLimit(pauseSeconds + coolingLimitSeconds)
        running = true
        let (inner, innerContinuation) = AsyncStream.makeStream(of: String.self)
        Task { @MainActor [weak self] in
            for await line in inner { emit(line) }
            self?.running = false
            onRunEnd?()
            continuation.finish()
        }
        let start: @MainActor () -> Void = {
            let thread = Thread { @Sendable in
                ModelSpeedRun(
                    folder: folder, bundledModelPath: bundledModel, runtimes: runtimes, progressFolder: progressFolder,
                    pauseSeconds: pauseSeconds, coolingLimitSeconds: coolingLimitSeconds, status: status,
                    startPair: startPair, checkpoint: { _ in }, emit: { innerContinuation.yield($0) }
                ).run()
                innerContinuation.finish()
            }
            // llama.cpp needs more than the 512 KB stack of a new thread, as in the language model test.
            thread.stackSize = 2 << 20
            thread.qualityOfService = .userInitiated
            thread.start()
        }
        if let onRunStart {
            onRunStart(start)
        } else {
            start()
        }
        return stream
    }

    /// The progress line while a run is under way, and nil after its end.
    func progressText() -> String? {
        running ? status.line() : nil
    }

    func progressCaption() -> String? {
        running ? status.caption() : nil
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

/// Samples the footprint of the process every 2 ms on a thread of its own, so a peak inside a
/// request counts too. `take()` gives the highest footprint and the least memory still allowed
/// since the last `take()`, and starts over.
final class FootprintSampler: @unchecked Sendable {
    static let intervalMicroseconds: UInt32 = 2000
    private let lock = NSLock()
    private var highest = 0.0
    private var leastAllowed = Double.greatestFiniteMagnitude
    private var stopped = false

    init() {
        let thread = Thread { [self] in
            while true {
                let memory = ProcessMemory.now()
                lock.lock()
                if stopped {
                    lock.unlock()
                    return
                }
                if let memory {
                    highest = max(highest, memory.footprintMB)
                    leastAllowed = min(leastAllowed, memory.availableMB)
                }
                lock.unlock()
                usleep(Self.intervalMicroseconds)
            }
        }
        thread.qualityOfService = .userInitiated
        thread.start()
    }

    func take() -> (highest: Double, leastAllowed: Double) {
        // One reading of this thread, so a phase shorter than the interval still counts.
        let memory = ProcessMemory.now()
        lock.lock()
        defer { lock.unlock() }
        if let memory {
            highest = max(highest, memory.footprintMB)
            leastAllowed = min(leastAllowed, memory.availableMB)
        }
        let result = (highest, leastAllowed)
        highest = 0
        leastAllowed = Double.greatestFiniteMagnitude
        return result
    }

    func stop() {
        lock.lock()
        stopped = true
        lock.unlock()
    }
}

/// The record of the speed test in a folder, kept until "duo:speedreset" deletes the folder.
/// `progress.txt` holds "run SIGNATURE" first, then "start N" and "end N" for each pair, and
/// "at N DONE FOOTPRINT ALLOWED" checkpoints: the requests of pair N done so far (-1 while the
/// model loads), the footprint and the memory still allowed in MB, so a stop leaves its place. Each
/// `pair-N.txt` holds the result lines of pair N, written as the pair gives them, so a later
/// run shows them again without running the pair.
struct ModelSpeedProgress {
    /// A pair that stopped this many runs (iOS stopped the keyboard, or the keyboard crashed) is
    /// skipped, so one pair that always stops the keyboard cannot keep the rest from running.
    static let stopLimit = 2

    let folder: URL
    let signature: String

    var file: URL { folder.appendingPathComponent("progress.txt") }

    func linesFile(_ index: Int) -> URL { folder.appendingPathComponent("pair-\(index).txt") }

    /// The pairs that ended, for each pair that started without an end the number of runs it
    /// stopped, and the last checkpoint of each such pair as text. Nil when no record of the same
    /// pairs exists, so the run starts at the first pair.
    func earlierRuns() throws -> (ended: Set<Int>, stops: [Int: Int], lastPlace: [Int: String])? {
        guard FileManager.default.fileExists(atPath: file.path) else { return nil }
        let lines = try String(contentsOf: file, encoding: .utf8).split(separator: "\n").map(String.init)
        guard lines.first == "run \(signature)" else { return nil }
        var ended = Set<Int>(), starts: [Int: Int] = [:], places: [Int: String] = [:]
        for line in lines.dropFirst() {
            // A run that reached its last pair ends its record with "done". The pairs it ended
            // still count, so the next run shows their kept lines.
            if line == "done" { continue }
            let parts = line.split(separator: " ").map(String.init)
            guard parts.count >= 2, let index = Int(parts[1]) else {
                throw ModelSpeedError("the progress file holds the line \"\(line)\"")
            }
            switch (parts[0], parts.count) {
            case ("start", 2):
                starts[index, default: 0] += 1
                places[index] = "before the load"
            case ("end", 2): ended.insert(index)
            case ("at", 3), ("at", 5):
                guard let done = Int(parts[2]) else {
                    throw ModelSpeedError("the progress file holds the line \"\(line)\"")
                }
                var place = done < 0 ? "during the load" : "after \(done) requests"
                if parts.count == 5 {
                    place += ", footprint \(parts[3]) MB, still allowed \(parts[4]) MB"
                }
                places[index] = place
            default: throw ModelSpeedError("the progress file holds the line \"\(line)\"")
            }
        }
        let open = starts.filter { !ended.contains($0.key) }
        return (ended, open, places.filter { open[$0.key] != nil })
    }

    /// The checkpoint line of pair `index` after `done` requests (-1 while the model loads).
    static func checkpoint(_ index: Int, done: Int) -> String {
        guard let memory = ProcessMemory.now() else { return "at \(index) \(done)" }
        return String(format: "at %d %d %.1f %.1f", index, done, memory.footprintMB, memory.availableMB)
    }

    /// Deletes every earlier record and starts the record of a new run.
    func begin() throws {
        try Self.reset(folder)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try "run \(signature)\n".write(to: file, atomically: true, encoding: .utf8)
    }

    func append(_ line: String) throws {
        try Self.append(line, to: file)
    }

    /// Starts the file of the result lines of pair `index` again, empty.
    func startLines(_ index: Int) throws {
        try Data().write(to: linesFile(index))
    }

    func appendLine(_ line: String, pair index: Int) throws {
        try Self.append(line, to: linesFile(index))
    }

    func savedLines(_ index: Int) throws -> [String] {
        try String(contentsOf: linesFile(index), encoding: .utf8).split(separator: "\n").map(String.init)
    }

    /// Deletes the record, so the next run starts at the first pair.
    static func reset(_ folder: URL) throws {
        if FileManager.default.fileExists(atPath: folder.path) {
            try FileManager.default.removeItem(at: folder)
        }
    }

    private static func append(_ line: String, to url: URL) throws {
        let handle = try FileHandle(forWritingTo: url)
        defer { try? handle.close() }
        try handle.seekToEnd()
        try handle.write(contentsOf: Data((line + "\n").utf8))
    }

    /// A short value of the pairs and the requests, so a changed catalog starts a new run.
    static func signature(of pairs: [ModelSpeedCatalog.Pair], requests: Int) -> String {
        var hash: UInt64 = 0xcbf2_9ce4_8422_2325
        let text = "\(requests)\n" + pairs.map { "\($0.name)|\($0.model)|\($0.runtime.rawValue)" }.joined(separator: "\n")
        for byte in text.utf8 {
            hash ^= UInt64(byte)
            hash = hash &* 0x100_0000_01b3
        }
        return String(format: "%016llx", hash)
    }
}

/// Where a run of the speed test is now, for the progress line that the keyboard keeps at the
/// end of the result lines. The run's thread writes it, and the main thread reads it.
final class ModelSpeedStatus: @unchecked Sendable {
    enum Step: Equatable {
        case starting
        case keptLines
        case pausing
        case loading
        case requests
    }

    private let lock = NSLock()
    private var pair = 0, pairs = 0, step = Step.starting, done = 0, requests = 0
    private var started: Double = 0, stepStarted: Double = 0

    private static func now() -> Double { ProcessInfo.processInfo.systemUptime }

    func start() {
        lock.lock()
        defer { lock.unlock() }
        pair = 0
        pairs = 0
        step = .starting
        started = Self.now()
        stepStarted = started
    }

    /// `pair` counts from 1.
    func set(pair: Int, of pairs: Int, step: Step) {
        lock.lock()
        defer { lock.unlock() }
        if self.pair != pair || self.step != step { stepStarted = Self.now() }
        self.pair = pair
        self.pairs = pairs
        self.step = step
    }

    /// `index` counts from 0: the request that starts now.
    func setRequest(_ index: Int, of requests: Int) {
        lock.lock()
        defer { lock.unlock() }
        if step != .requests { stepStarted = Self.now() }
        step = .requests
        done = index
        self.requests = requests
    }

    /// The longest pause before a pair, for the progress line.
    private var pauseLimit: Double = 0
    /// Counts the reads, so the caption's mark turns at each read.
    private var reads = 0

    func setPauseLimit(_ seconds: Double) {
        lock.lock()
        defer { lock.unlock() }
        pauseLimit = seconds
    }

    private func parts() -> (bar: String, place: String, step: String, clock: String) {
        let now = Self.now()
        let total = Int(now - started)
        let clock = String(format: "%d:%02d:%02d", total / 3600, total / 60 % 60, total % 60)
        let inStep = Int(now - stepStarted)
        let step: String
        // The share of the current pair that is done: the requests are the work of a pair.
        var share = 0.0
        switch self.step {
        case .starting: step = "starting"
        case .keptLines: step = "typing the kept lines"
        case .pausing: step = "cooling \(inStep) s of at most \(Int(pauseLimit)) s"
        case .loading: step = "loading \(inStep) s"
        case .requests:
            step = "request \(done) of \(requests)"
            share = requests > 0 ? Double(done) / Double(requests) : 0
        }
        let width = 20
        let place = pairs > 0 ? "pair \(pair) of \(pairs)" : ""
        let filled = pairs > 0 ? Int(Double(width) * (Double(pair - 1) + share) / Double(pairs)) : 0
        let bar = "[" + String(repeating: "#", count: filled) + String(repeating: "-", count: width - filled) + "]"
        return (bar, place, step, clock)
    }

    /// One line of ASCII text: a bar of the pairs and the requests, the pair, the step with its
    /// seconds, and the time since the start.
    func line() -> String {
        lock.lock()
        defer { lock.unlock() }
        let (bar, place, step, clock) = parts()
        guard !place.isEmpty else { return "progress    \(step), \(clock) since the start" }
        return "progress    \(bar) \(place), \(step), \(clock) since the start"
    }

    /// A short text for the space bar, with a mark that turns at each read.
    func caption() -> String {
        lock.lock()
        defer { lock.unlock() }
        reads += 1
        let marks = ["\u{25D0}", "\u{25D3}", "\u{25D1}", "\u{25D2}"]
        let (_, _, step, clock) = parts()
        let place = pairs > 0 ? "\(pair)/\(pairs) " : ""
        return "\(marks[reads % marks.count]) Speed test \(place)\(step) \(clock)"
    }
}

/// One run of the speed test on its own thread.
struct ModelSpeedRun {
    let folder: URL?
    /// The keyboard's own model file in the bundle, for the pairs of the model "bundled".
    let bundledModelPath: String?
    let runtimes: Set<ModelSpeedCatalog.Runtime>?
    let progressFolder: URL?
    let pauseSeconds: Double
    let coolingLimitSeconds: Double
    let status: ModelSpeedStatus
    /// The pair to start at, counting from 1, or nil for the first pair.
    let startPair: Int?
    /// Writes a checkpoint of the running pair: the requests done, or -1 while the model loads.
    let checkpoint: (Int) -> Void
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

    /// The facts of one pair that come before its requests run.
    private struct Setting {
        let pause: Double
        let thermalAtStart: ProcessInfo.ThermalState
        let peakBefore: Double
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
        emit("llama.cpp   \(String(cString: duo_lm_scorer_system_info()).trimmingCharacters(in: .whitespaces))")
        emit("Core ML     devices of this machine: \(CoreMLComputePlan.availableDevices())")
        let pairs = catalog.pairs.filter { runtimes?.contains($0.runtime) ?? true }
        var progress: ModelSpeedProgress?
        var earlierRuns: (ended: Set<Int>, stops: [Int: Int], lastPlace: [Int: String])?
        do {
            if let progressFolder {
                let record = ModelSpeedProgress(
                    folder: progressFolder, signature: ModelSpeedProgress.signature(of: pairs, requests: requests.count))
                earlierRuns = try record.earlierRuns()
                if earlierRuns == nil { try record.begin() }
                progress = record
            }
        } catch {
            emit("done        failed before the first pair: the progress file: \(error)")
            return
        }
        if let earlierRuns {
            emit("resume      \(earlierRuns.ended.count) pairs ended in earlier runs, and their lines follow from the "
                 + "record. Type duo:speedreset and a space to delete the record and start at the first pair.")
        }
        if let startPair {
            guard (1...pairs.count).contains(startPair) else {
                emit("done        failed before the first pair: there is no pair \(startPair), the pairs are 1 to \(pairs.count)")
                return
            }
            emit("start       pair \(startPair): the pairs before it that did not end in earlier runs are skipped")
        }
        let sampler = FootprintSampler()
        defer { sampler.stop() }
        var ran = 0, missing = 0, failed = 0, earlier = 0, skipped = 0, beforeStart = 0
        for (index, pair) in pairs.enumerated() {
            let title = "pair        \(index + 1)/\(pairs.count) \(pair.name), \(pair.model), \(pair.runtime.rawValue)"
            if let earlierRuns, let progress, earlierRuns.ended.contains(index) {
                status.set(pair: index + 1, of: pairs.count, step: .keptLines)
                do {
                    for line in try progress.savedLines(index) { emit(line) }
                } catch {
                    emit("\(title): ended in an earlier run, and its lines did not load: \(error)")
                }
                earlier += 1
                continue
            }
            if let startPair, index + 1 < startPair {
                emit("\(title): skipped: before the start pair \(startPair)")
                beforeStart += 1
                continue
            }
            let stops = earlierRuns?.stops[index] ?? 0
            let lastPlace = earlierRuns?.lastPlace[index].map { "; the last stop came \($0)" } ?? ""
            if stops >= ModelSpeedProgress.stopLimit, index + 1 != startPair {
                emit("\(title): skipped: \(stops) earlier runs stopped during this pair\(lastPlace)")
                skipped += 1
                continue
            }
            // Each line of this pair also goes to the record. A pair that is not downloaded gets
            // no "end", so a later run tries it again.
            let pairEmit: (String) -> Void = { line in
                self.emit(line)
                do {
                    try progress?.appendLine(line, pair: index)
                } catch {
                    self.emit("failed      the progress file: \(error)")
                }
            }
            let pairRun = ModelSpeedRun(
                folder: folder, bundledModelPath: bundledModelPath, runtimes: runtimes, progressFolder: progressFolder,
                pauseSeconds: pauseSeconds, coolingLimitSeconds: coolingLimitSeconds, status: status,
                startPair: startPair,
                checkpoint: { done in
                    do {
                        try progress?.append(ModelSpeedProgress.checkpoint(index, done: done))
                    } catch {
                        self.emit("failed      the progress file: \(error)")
                    }
                },
                emit: pairEmit)
            var downloaded = true
            do {
                try progress?.append("start \(index)")
                try progress?.startLines(index)
            } catch {
                emit("done        failed at pair \(index + 1): the progress file: \(error)")
                return
            }
            defer {
                if downloaded {
                    do {
                        try progress?.append("end \(index)")
                    } catch {
                        emit("failed      the progress file: \(error)")
                    }
                }
            }
            if stops > 0 {
                pairEmit("\(title): runs again: \(stops) earlier runs stopped during this pair\(lastPlace)")
            }
            status.set(pair: index + 1, of: pairs.count, step: .starting)
            let result = pairRun.runPair(
                index: index, pairCount: pairs.count, pair: pair, title: title, catalog: catalog, requests: requests, references: references,
                sampler: sampler)
            switch result {
            case .ran: ran += 1
            case .failed: failed += 1
            case .missing:
                missing += 1
                downloaded = false
            }
        }
        do {
            try progress?.append("done")
        } catch {
            emit("failed      the progress file: \(error)")
        }
        emit("done        \(ran) pairs ran, \(missing) not downloaded, \(failed) failed"
             + (earlier > 0 ? ", \(earlier) ended in earlier runs" : "")
             + (skipped > 0 ? ", \(skipped) skipped after \(ModelSpeedProgress.stopLimit) stops" : "")
             + (beforeStart > 0 ? ", \(beforeStart) before the start pair" : ""))
    }

    private enum PairResult { case ran, failed, missing }

    /// Runs one pair and gives its lines to `emit`.
    private func runPair(
        index: Int, pairCount: Int, pair: ModelSpeedCatalog.Pair, title: String, catalog: ModelSpeedCatalog, requests: [TextRequest],
        references: [String: [Int]], sampler: FootprintSampler
    ) -> PairResult {
        guard let reference = references[pair.reference], reference.count == requests.count else {
            emit("\(title): failed: the reference \(pair.reference) does not hold \(requests.count) top candidates")
            return .failed
        }
        let location: URL
        if pair.model == "bundled" {
            guard let path = bundledModelPath else {
                emit("\(title): failed: the keyboard's model file is missing from the bundle")
                return .failed
            }
            location = URL(fileURLWithPath: path)
        } else {
            guard let model = catalog.model(id: pair.model) else {
                emit("\(title): failed: the catalog has no model \(pair.model)")
                return .failed
            }
            guard let folder, Self.present(model, in: folder) else {
                emit("\(title): not downloaded")
                return .missing
            }
            let file = pair.runtime.isLlama ? "model.gguf" : "model.mlmodelc"
            location = folder.appendingPathComponent(model.id, isDirectory: true).appendingPathComponent(file)
        }
        emit(title)
        status.set(pair: index + 1, of: pairCount, step: .pausing)
        let setting = coolDown()
        status.set(pair: index + 1, of: pairCount, step: .loading)
        do {
            if pair.runtime.isLlama {
                try runLlama(pair: pair, path: location.path, requests: requests, reference: reference,
                             setting: setting, sampler: sampler)
            } else {
                guard let tokensName = pair.tokens else {
                    throw ModelSpeedError("a Core ML pair needs a token file")
                }
                let tokens = try TokenRequest.read(String(
                    contentsOf: Self.resource("model-speed-tokens.\(tokensName)", "tsv"), encoding: .utf8))
                guard tokens.count == requests.count else {
                    throw ModelSpeedError("the token file holds \(tokens.count) requests, not \(requests.count)")
                }
                try runCoreML(pair: pair, url: location, requests: tokens, reference: reference,
                              setting: setting, sampler: sampler)
            }
            return .ran
        } catch {
            emit("failed      \(error)")
            return .failed
        }
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

    static func name(_ state: ProcessInfo.ThermalState) -> String {
        switch state {
        case .nominal: return "nominal"
        case .fair: return "fair"
        case .serious: return "serious"
        case .critical: return "critical"
        @unknown default: return "unknown (\(state.rawValue))"
        }
    }

    /// Pauses for `pauseSeconds`, then waits until the thermal state is nominal, for at most
    /// `coolingLimitSeconds` more.
    private func coolDown() -> Setting {
        let started = Self.now()
        Thread.sleep(forTimeInterval: pauseSeconds)
        while ProcessInfo.processInfo.thermalState != .nominal, Self.now() - started < 1000 * (pauseSeconds + coolingLimitSeconds) {
            Thread.sleep(forTimeInterval: 5)
        }
        return Setting(
            pause: (Self.now() - started) / 1000, thermalAtStart: ProcessInfo.processInfo.thermalState,
            peakBefore: ProcessMemory.now()?.highestMB ?? 0)
    }

    /// The share of the file's pages in memory, for the load line.
    private static func residentText(_ path: String) -> String {
        let share = duo_speed_resident_share(path)
        if share == -2 { return "the weight file is empty" }
        if share < 0 { return "the share of the weight file in memory is not known (mincore refused)" }
        return String(format: "%.0f%% of the weight file in memory before the first load", 100 * share)
    }

    private func emitLoad(first: Double, again: Double, resident: String, before: ProcessMemory?, after: ProcessMemory?) {
        let times = String(format: "load        %.1f ms, again %.1f ms after a close; %@", first, again, resident)
        guard let before, let after else {
            emit("\(times); the footprint is not known")
            return
        }
        emit(times + String(
            format: "; footprint %.1f MB before and %.1f MB after, still allowed %.1f MB",
            before.footprintMB, after.footprintMB, after.availableMB))
    }

    /// The times and facts of the requests of one pair.
    private struct Requests {
        var totals: [Double] = [], candidates: [Double] = [], windows: [Double] = []
        var tokenizer: [Double] = [], processor: [Double] = []
        var windowTokens = 0, keptTokens = 0, agreeing = 0
        var worstThermal = ProcessInfo.ThermalState.nominal

        mutating func noteThermal() {
            let state = ProcessInfo.processInfo.thermalState
            if state.rawValue > worstThermal.rawValue { worstThermal = state }
        }
    }

    /// The lines after the load, from the times of each request.
    private func emitRequests(
        _ requests: Requests, count: Int, loadHighest: Double, requestMemory: (highest: Double, leastAllowed: Double),
        setting: Setting, tokenizerLine: String, units: String
    ) {
        emit(String(format: "first       request %.1f ms", requests.totals[0]))
        let later = { (values: [Double]) in MillisecondStatistics(Array(values.dropFirst()))?.description ?? "none" }
        emit("request     \(later(requests.totals))")
        emit("candidates  \(later(requests.candidates))")
        emit("window      \(later(requests.windows))")
        emit(String(format: "reuse       %d of %d context tokens from the cache (%.1f%%)", requests.keptTokens,
                    requests.windowTokens,
                    requests.windowTokens > 0 ? 100 * Double(requests.keptTokens) / Double(requests.windowTokens) : 0))
        let peak = ProcessMemory.now()?.highestMB ?? 0
        let peakText = peak > setting.peakBefore + 0.05
            ? String(format: "process peak %.1f MB, set during this pair", peak)
            : String(format: "process peak %.1f MB, set before this pair", peak)
        emit(String(
            format: "memory      highest footprint %.1f MB during the requests and %.1f MB during the loads, sampled every 2 ms; %@; least still allowed %.1f MB",
            requestMemory.highest, loadHighest, peakText, requestMemory.leastAllowed))
        emit(String(format: "agreement   %d of %d top candidates (%.1f%%) equal llama.cpp Q8_0 on the desktop",
                    requests.agreeing, count, 100 * Double(requests.agreeing) / Double(count)))
        emit(tokenizerLine)
        let processor = requests.processor.dropFirst().reduce(0, +)
        let wall = requests.totals.dropFirst().reduce(0, +) + requests.tokenizer.dropFirst().reduce(0, +)
        emit(String(format: "processor   %.1f ms of processor time per request in the mean, %.2f times the time of the request with its tokenizer, all threads of the process",
                    processor / Double(max(requests.processor.count - 1, 1)), wall > 0 ? processor / wall : 0))
        emit("units       \(units)")
        emit(String(format: "heat        thermal state %@ at the start and %@ at the worst, after a pause of %.0f s",
                    Self.name(setting.thermalAtStart), Self.name(requests.worstThermal), setting.pause))
    }

    private func runLlama(pair: ModelSpeedCatalog.Pair, path: String, requests: [TextRequest], reference: [Int],
                          setting: Setting, sampler: FootprintSampler) throws {
        let device: duo_lm_device = pair.runtime == .llamaProcessor ? DUO_LM_DEVICE_CPU : DUO_LM_DEVICE_GPU
        // llama.cpp reads the variable each time it takes the Metal device, at each open.
        if pair.runtime == .llamaMetalNoResidency {
            setenv("GGML_METAL_NO_RESIDENCY", "1", 1)
        }
        defer { if pair.runtime == .llamaMetalNoResidency { unsetenv("GGML_METAL_NO_RESIDENCY") } }
        let resident = Self.residentText(path)
        let errorSize = Int(DUO_LM_ERROR_SIZE)
        var error = [CChar](repeating: 0, count: errorSize)
        let reuse = KeyboardLanguageModel.reuse
        func open() throws -> OpaquePointer {
            guard let scorer = duo_lm_scorer_open_on(path, Int32(ModelSpeedTest.threads), reuse, device, &error, errorSize)
            else {
                throw ModelSpeedError(String(cString: error))
            }
            return scorer
        }
        let before = ProcessMemory.now()
        _ = sampler.take()
        checkpoint(-1)
        var started = Self.now()
        let firstScorer = try open()
        let first = Self.now() - started
        duo_lm_scorer_close(firstScorer)
        started = Self.now()
        let scorer = try open()
        let again = Self.now() - started
        defer { duo_lm_scorer_close(scorer) }
        let residency = String(cString: duo_lm_scorer_residency_note())
        emitLoad(first: first, again: again, resident: resident, before: before, after: ProcessMemory.now())
        let loadHighest = sampler.take().highest
        var timed = Requests()
        for (index, request) in requests.enumerated() {
            status.setRequest(index, of: requests.count)
            if index % 10 == 0 { checkpoint(index) }
            let copies = request.candidates.map { strdup($0) }
            defer { copies.forEach { free($0) } }
            let pointers = copies.map { UnsafePointer<CChar>($0) }
            var scores = [duo_lm_score](repeating: duo_lm_score(), count: request.candidates.count)
            let beforeInfo = duo_lm_scorer_get_info(scorer)
            let processorStarted = duo_speed_process_milliseconds()
            let requestStarted = Self.now()
            let result = pointers.withUnsafeBufferPointer { pointerBuffer in
                scores.withUnsafeMutableBufferPointer { scoreBuffer in
                    duo_lm_scorer_score(
                        scorer, request.context, pointerBuffer.baseAddress, Int32(request.candidates.count),
                        scoreBuffer.baseAddress, &error, errorSize)
                }
            }
            let total = Self.now() - requestStarted
            let processor = duo_speed_process_milliseconds() - processorStarted
            guard result == 1 else {
                throw ModelSpeedError("request \(index + 1) gave \(result): \(String(cString: error))")
            }
            let afterInfo = duo_lm_scorer_get_info(scorer)
            let tokenizer = afterInfo.tokenize_milliseconds - beforeInfo.tokenize_milliseconds
            timed.totals.append(total - tokenizer)
            timed.tokenizer.append(tokenizer)
            timed.processor.append(processor)
            timed.windows.append(afterInfo.window_milliseconds - beforeInfo.window_milliseconds)
            timed.candidates.append(afterInfo.candidate_milliseconds - beforeInfo.candidate_milliseconds)
            timed.noteThermal()
            let top = topCandidate(scores.map { CandidateScore(logProbability: $0.log_probability, spaceAfter: $0.space_after) })
            if top == reference[index] { timed.agreeing += 1 }
        }
        let info = duo_lm_scorer_get_info(scorer)
        timed.windowTokens = info.window_tokens
        timed.keptTokens = info.window_tokens_reused
        let tokenizerLine = "tokenizer   " + (MillisecondStatistics(Array(timed.tokenizer.dropFirst()))?.description ?? "none")
            + ", left out of the request time"
        let units = pair.runtime == .llamaProcessor
            ? "llama.cpp, processor, \(ModelSpeedTest.threads) threads"
            : "llama.cpp, Metal, " + (residency.isEmpty ? "no line of llama.cpp about residency sets" : residency)
        emitRequests(
            timed, count: requests.count, loadHighest: loadHighest, requestMemory: sampler.take(), setting: setting,
            tokenizerLine: tokenizerLine, units: units)
    }

    private func runCoreML(pair: ModelSpeedCatalog.Pair, url: URL, requests: [TokenRequest], reference: [Int],
                           setting: Setting, sampler: FootprintSampler) throws {
        let units = pair.runtime.computeUnits
        let resident = Self.residentText(url.appendingPathComponent("weights/weight.bin").path)
        let before = ProcessMemory.now()
        _ = sampler.take()
        checkpoint(-1)
        // Core ML hands out Objective-C objects that stay alive until their autorelease pool
        // drains. This thread has no pool of its own, so each step gets one, and the footprint
        // shows only what the model keeps.
        var started = Self.now()
        var first = 0.0
        try autoreleasepool {
            let firstScorer = try CoreMLSpeedScorer(compiledModel: url, computeUnits: units)
            first = Self.now() - started
            withExtendedLifetime(firstScorer) {}
        }
        started = Self.now()
        let scorer = try autoreleasepool { try CoreMLSpeedScorer(compiledModel: url, computeUnits: units) }
        let again = Self.now() - started
        emitLoad(first: first, again: again, resident: resident, before: before, after: ProcessMemory.now())
        let loadHighest = sampler.take().highest
        var timed = Requests()
        var calls = 0, padded = 0, tokens = 0
        for (index, request) in requests.enumerated() {
            status.setRequest(index, of: requests.count)
            if index % 10 == 0 { checkpoint(index) }
            let processorStarted = duo_speed_process_milliseconds()
            let requestStarted = Self.now()
            let result = try autoreleasepool { try scorer.score(request) }
            timed.totals.append(Self.now() - requestStarted)
            timed.processor.append(duo_speed_process_milliseconds() - processorStarted)
            timed.windows.append(result.windowMilliseconds)
            timed.candidates.append(result.candidateMilliseconds)
            timed.windowTokens += result.windowTokens
            timed.keptTokens += result.keptTokens
            timed.noteThermal()
            calls += result.calls
            padded += result.paddedTokens
            tokens += result.windowTokens - result.keptTokens + request.candidates.reduce(0) { $0 + $1.count }
            if topCandidate(result.scores) == reference[index] { timed.agreeing += 1 }
        }
        let requestMemory = sampler.take()
        let plan: String
        do {
            plan = try autoreleasepool { try CoreMLComputePlan.summary(of: url, computeUnits: units) }
        } catch {
            plan = "the compute plan did not load: \(error)"
        }
        emitRequests(
            timed, count: requests.count, loadHighest: loadHighest, requestMemory: requestMemory, setting: setting,
            tokenizerLine: "tokenizer   none: the tokens come from the token file",
            units: "Core ML, \(pair.runtime.computeUnitsName), \(scorer.formDescription), \(calls) calls of "
                + "\(padded) tokens after padding for \(tokens) tokens; plan: \(plan)")
    }
}

extension ModelSpeedCatalog.Runtime {
    var isLlama: Bool {
        switch self {
        case .llamaProcessor, .llamaMetal, .llamaMetalNoResidency: return true
        case .coreMLGPU, .coreMLNeuralEngine: return false
        }
    }

    var computeUnits: MLComputeUnits {
        switch self {
        case .coreMLGPU: return .cpuAndGPU
        case .coreMLNeuralEngine: return .cpuAndNeuralEngine
        case .llamaProcessor, .llamaMetal, .llamaMetalNoResidency: preconditionFailure("\(rawValue) is not Core ML")
        }
    }

    var computeUnitsName: String {
        switch self {
        case .coreMLGPU: return "compute units CPU and GPU"
        case .coreMLNeuralEngine: return "compute units CPU and Neural Engine"
        case .llamaProcessor, .llamaMetal, .llamaMetalNoResidency: preconditionFailure("\(rawValue) is not Core ML")
        }
    }
}

private final class ModelSpeedBundleToken {}

/// "duo:speedreset" and a space: deletes the record of the speed test, so the next "duo:speed"
/// starts at the first pair.
@MainActor
final class ModelSpeedReset: LanguageModelMeasuring {
    let progressFolder: URL

    init(progressFolder: URL) {
        self.progressFolder = progressFolder
    }

    func resultLines() -> AsyncStream<String> {
        let (stream, continuation) = AsyncStream.makeStream(of: String.self)
        do {
            try ModelSpeedProgress.reset(progressFolder)
            continuation.yield("reset       the record of the speed test is deleted. The next duo:speed starts at the first pair.")
        } catch {
            continuation.yield("reset       failed: \(error)")
        }
        continuation.finish()
        return stream
    }
}
