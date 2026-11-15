import CoreML
import Foundation

/// The tokens of one request, as `speed_cli tokens` (scripts/model-speed/speed_cli.c) wrote them
/// with llama.cpp's tokenizer: the start token, every token of the context, and the tokens of each
/// candidate with the space before it.
struct TokenRequest: Equatable, Sendable {
    let start: Int32
    let context: [Int32]
    let candidates: [[Int32]]

    /// Reads a file of one request per line: "start TAB context TAB candidate 1 TAB ...", each a
    /// list of numbers with spaces.
    static func read(_ text: String) throws -> [TokenRequest] {
        var requests: [TokenRequest] = []
        for (index, line) in text.split(separator: "\n", omittingEmptySubsequences: true).enumerated() {
            let fields = line.split(separator: "\t", omittingEmptySubsequences: false)
            guard fields.count >= 3 else {
                throw ModelSpeedError("token line \(index + 1) holds \(fields.count) fields, and a request needs 3 or more")
            }
            func numbers(_ field: Substring) throws -> [Int32] {
                try field.split(separator: " ").map { part in
                    guard let value = Int32(part) else { throw ModelSpeedError("token line \(index + 1) holds \"\(part)\"") }
                    return value
                }
            }
            let start = try numbers(fields[0])
            guard start.count == 1 else { throw ModelSpeedError("token line \(index + 1) has \(start.count) start tokens") }
            let candidates = try fields.dropFirst(2).map(numbers)
            guard candidates.allSatisfy({ !$0.isEmpty }) else {
                throw ModelSpeedError("token line \(index + 1) has a candidate without tokens")
            }
            requests.append(TokenRequest(start: start[0], context: try numbers(fields[1]), candidates: candidates))
        }
        return requests
    }
}

/// The window rules of LanguageModel/duo_lm_scorer.c with the keyboard's reuse mode: the anchored
/// window with two slots (DUO_LM_REUSE_ANCHOR, 2 slots). scripts/model-speed/coreml/request_driver.py
/// holds the same rules, and its numbers match llama.cpp's on the desktop.
struct AnchoredWindowPlanner: Sendable {
    static let maxContextTokens = Int(DUO_LM_MAX_CONTEXT_TOKENS)
    static let anchorRefillTokens = Int(DUO_LM_ANCHOR_REFILL_TOKENS)
    /// MIN_UNREAD_TOKENS of duo_lm_scorer.c.
    static let minUnreadTokens = 2

    struct Slot: Equatable, Sendable {
        var tokens: [Int32] = []
        var count = 0
        var windowStart = 0
        var context: [Int32] = []
        var lastUse = 0
    }

    /// What one request reads: the window, from which token on, and which slot holds its cache.
    struct Plan: Equatable, Sendable {
        let window: [Int32]
        let windowStart: Int
        let kept: Int
        /// The slot of the request: the index into the slots as they were before the request.
        let slot: Int
    }

    private(set) var slots = [Slot(), Slot()]
    /// The order of the slots: `order[0]` is the slot of the cache, as slot 0 of the C scorer.
    private(set) var order = [0, 1]
    private(set) var requests = 0

    private static func sharedStart(_ first: ArraySlice<Int32>, _ second: ArraySlice<Int32>) -> Int {
        var length = 0
        var a = first.startIndex, b = second.startIndex
        while a < first.endIndex, b < second.endIndex, first[a] == second[b] {
            length += 1
            a += 1
            b += 1
        }
        return length
    }

    private static func plan(_ slot: Slot, context: [Int32]) -> (windowStart: Int, kept: Int) {
        let count = context.count
        var windowStart = count > maxContextTokens ? count - maxContextTokens : 0
        if count > maxContextTokens {
            let anchor = slot.windowStart
            let same = sharedStart(slot.context[...], context[...])
            let keeps = slot.count > 0 && same > anchor && count - anchor <= maxContextTokens
            windowStart = keeps ? anchor : count - anchorRefillTokens
        }
        if slot.count == 0 { return (windowStart, 0) }
        return (windowStart, 1 + sharedStart(slot.tokens[1..<slot.count], context[windowStart...]))
    }

    /// Plans one request and records its window in its slot, as the C scorer does after a read
    /// that worked.
    mutating func next(start: Int32, context: [Int32]) -> Plan {
        requests += 1
        var mine = Self.plan(slots[order[0]], context: context)
        let other = Self.plan(slots[order[1]], context: context)
        let mineKept = mine.kept > 1 ? mine.kept : 0
        let theirKept = other.kept > 1 ? other.kept : 0
        if theirKept > mineKept
            || (theirKept == mineKept && mineKept == 0 && slots[order[1]].lastUse < slots[order[0]].lastUse) {
            order.swapAt(0, 1)
            mine = other
        }
        let window = [start] + context[mine.windowStart...]
        let kept = max(0, min(mine.kept, window.count - Self.minUnreadTokens))
        let index = order[0]
        slots[index].tokens = window
        slots[index].count = window.count > 1 ? window.count : 0
        slots[index].windowStart = mine.windowStart
        slots[index].lastUse = requests
        slots[index].context = context
        return Plan(window: window, windowStart: mine.windowStart, kept: kept, slot: index)
    }
}

/// The scores of one request and the time of its two parts.
struct TimedScores: Sendable {
    let scores: [CandidateScore]
    let windowMilliseconds: Double
    let candidateMilliseconds: Double
    let windowTokens: Int
    let keptTokens: Int
    /// The calls of the request, and their tokens after padding to the sizes of the fixed form.
    let calls: Int
    let paddedTokens: Int
}

/// Scores requests with a converted Core ML model of scripts/model-speed/coreml/convert.py, in
/// either of its two forms (scripts/model-speed/coreml/scoring_model.py):
///   flexible  the shapes change from call to call, for the processor and the GPU
///   fixed     the model lists its shapes, for the Neural Engine. Each call is padded to the
///             smallest listed size that holds its tokens, and a part longer than the largest
///             size goes in several calls. The cache always has 512 cells, and the input
///             write_cells names the cell of each token.
/// The scorer finds the form from the inputs of the model.
///
/// Each slot of the planner has a Core ML state of its own, which holds the cache of its window.
/// A request has two parts: the window part reads the window tokens after the kept ones and
/// scores the last of them only, as the C scorer does. The candidate part reads every token of
/// every candidate, each candidate in cells of its own after the window. The attention mask lets
/// each candidate see the window and its own earlier tokens only, so the candidates share the
/// window as the sequences of llama.cpp do.
final class CoreMLSpeedScorer {
    /// A mask value that keeps a cell out of the attention: -30000 in half precision.
    private static let maskedBits: UInt16 = 0xF753
    /// 1 in half precision.
    private static let oneBits: UInt16 = 0x3C00
    /// CACHE_CELLS of scoring_model.py.
    static let cacheCells = 512
    /// FIRST_TOKENS of scoring_model.py.
    static let firstTokens = Int(DUO_LM_MAX_CANDIDATES)

    /// One token of a call: its id, position and cell, the cells it attends to, and its target.
    private struct Row {
        let token: Int32
        let position: Int
        let cell: Int
        let allowed: [Range<Int>]
        let target: Int32
    }

    private let model: MLModel
    private let states: [MLState]
    private var planner = AnchoredWindowPlanner()
    /// One shape of the fixed form: the tokens of a call and its scored tokens. A window shape
    /// scores fewer tokens than it reads, and a candidate shape scores every token.
    struct Shape: Equatable, Sendable {
        let tokens: Int
        let scored: Int
        var isWindow: Bool { scored < tokens }
    }

    /// The shapes of the fixed form, from small to large, or nil for the flexible form.
    let fixedShapes: [Shape]?

    init(compiledModel url: URL, computeUnits: MLComputeUnits) throws {
        let configuration = MLModelConfiguration()
        configuration.computeUnits = computeUnits
        model = try MLModel(contentsOf: url, configuration: configuration)
        let inputs = model.modelDescription.inputDescriptionsByName
        if inputs["write_cells"] != nil {
            // Core ML matches the listed shapes of the inputs by their place in the lists.
            guard let tokens = inputs["input_ids"]?.multiArrayConstraint?.shapeConstraint.enumeratedShapes,
                let scored = inputs["score_rows"]?.multiArrayConstraint?.shapeConstraint.enumeratedShapes,
                !tokens.isEmpty, tokens.count == scored.count
            else {
                throw ModelSpeedError("the fixed Core ML model lists no matching shapes of input_ids and score_rows")
            }
            fixedShapes = zip(tokens, scored).map { Shape(tokens: $0[1].intValue, scored: $1[1].intValue) }
                .sorted { $0.tokens < $1.tokens }
        } else {
            fixedShapes = nil
        }
        states = [model.makeState(), model.makeState()]
    }

    /// "flexible shapes" or the fixed shapes, for the result lines.
    var formDescription: String {
        guard let fixedShapes else { return "flexible shapes" }
        let window = fixedShapes.filter(\.isWindow).map { String($0.tokens) }.joined(separator: ", ")
        let candidates = fixedShapes.filter { !$0.isWindow }.map { String($0.tokens) }.joined(separator: ", ")
        return "fixed shapes of \(window) window tokens and \(candidates) candidate tokens"
    }

    private static func now() -> Double { ProcessInfo.processInfo.systemUptime * 1000 }

    private static func int32Array(_ values: [Int32]) throws -> MLMultiArray {
        let array = try MLMultiArray(shape: [1, NSNumber(value: values.count)], dataType: .int32)
        let pointer = array.dataPointer.bindMemory(to: Int32.self, capacity: values.count)
        for (index, value) in values.enumerated() { pointer[index] = value }
        return array
    }

    /// A half-precision array of `shape` whose last two axes are `rows` by `cells`, filled with
    /// `fill`, and with `mark(row)` set to `value` in each row.
    private static func grid(
        shape: [Int], fill: UInt16, value: UInt16, mark: (Int) -> [Range<Int>]
    ) throws -> MLMultiArray {
        let array = try MLMultiArray(shape: shape.map { NSNumber(value: $0) }, dataType: .float16)
        let strides = array.strides.map { $0.intValue }
        let rowStride = strides[strides.count - 2], cellStride = strides[strides.count - 1]
        let rows = shape[shape.count - 2], cells = shape[shape.count - 1]
        let pointer = array.dataPointer.bindMemory(to: UInt16.self, capacity: array.count)
        for row in 0..<rows {
            for cell in 0..<cells { pointer[row * rowStride + cell * cellStride] = fill }
            for range in mark(row) {
                for cell in range { pointer[row * rowStride + cell * cellStride] = value }
            }
        }
        return array
    }

    private static func output(_ provider: MLFeatureProvider, _ name: String) throws -> MLMultiArray {
        guard let array = provider.featureValue(for: name)?.multiArrayValue else {
            throw ModelSpeedError("the Core ML model gave no output \(name)")
        }
        return array
    }

    /// The value at `index` of the last axis of an output of shape [1, N].
    private static func value(_ array: MLMultiArray, _ index: Int) -> Double {
        array[[0, NSNumber(value: index)]].doubleValue
    }

    /// The outputs of one call and the count of its real rows.
    private struct CallOutput {
        let targetLogit: MLMultiArray
        let logNorm: MLMultiArray
        let spaceMass: MLMultiArray
        let firstLogit: MLMultiArray
        let rows: Int
    }

    /// Reads `rows` in calls. With `scoreAll` every row is scored, and otherwise only the last
    /// row of the last call. Returns the outputs of each call and adds its padded size to `padded`.
    private func run(state: MLState, rows: [Row], firstIDs: [Int32], scoreAll: Bool, padded: inout Int) throws
        -> [CallOutput]
    {
        var groups: [ArraySlice<Row>] = []
        let kind = fixedShapes?.filter { $0.isWindow != scoreAll }
        if let kind {
            guard let largest = kind.last?.tokens else {
                throw ModelSpeedError("the fixed Core ML model has no shape for this part")
            }
            var begin = 0
            while begin < rows.count {
                groups.append(rows[begin..<min(begin + largest, rows.count)])
                begin += largest
            }
        } else {
            groups = [rows[...]]
        }
        var first = firstIDs
        first += [Int32](repeating: 0, count: Self.firstTokens - first.count)
        var outputs: [CallOutput] = []
        for group in groups {
            let rows = Array(group)
            let count = rows.count
            let size: Int, scoredCount: Int, cells: Int
            if let kind {
                guard let fitting = kind.first(where: { $0.tokens >= count }) else {
                    throw ModelSpeedError("a call of \(count) tokens fits no shape of the model")
                }
                size = fitting.tokens
                scoredCount = fitting.scored
                cells = Self.cacheCells
            } else {
                size = count
                scoredCount = scoreAll ? count : 1
                cells = rows.map(\.cell).max()! + 1
            }
            guard let highest = rows.map(\.cell).max(), highest < Self.cacheCells else {
                throw ModelSpeedError("a request needs more than \(Self.cacheCells) cells")
            }
            padded += size
            let mask = try Self.grid(shape: [1, 1, size, cells], fill: Self.maskedBits, value: 0) { row in
                // A padding row attends to cell 0 only, so its sum of weights stays finite.
                row < count ? rows[row].allowed : [0..<1]
            }
            func padding<T>(_ values: [T], _ zero: T) -> [T] { values + [T](repeating: zero, count: size - count) }
            var dictionary: [String: MLFeatureValue] = [
                "input_ids": MLFeatureValue(multiArray: try Self.int32Array(padding(rows.map(\.token), 0))),
                "position_ids": MLFeatureValue(multiArray: try Self.int32Array(padding(rows.map { Int32($0.position) }, 0))),
                "attention_mask": MLFeatureValue(multiArray: mask),
                "first_ids": MLFeatureValue(multiArray: try Self.int32Array(first)),
            ]
            if kind != nil {
                dictionary["write_cells"] = MLFeatureValue(multiArray: try Self.grid(
                    shape: [1, size, cells], fill: 0, value: Self.oneBits
                ) { row in row < count ? [rows[row].cell..<(rows[row].cell + 1)] : [] })
            }
            if scoreAll {
                dictionary["score_rows"] = MLFeatureValue(multiArray: try Self.int32Array((0..<size).map { Int32($0) }))
                dictionary["target_ids"] = MLFeatureValue(multiArray: try Self.int32Array(padding(rows.map(\.target), 0)))
            } else {
                // The last token, as often as the shape asks.
                dictionary["score_rows"] = MLFeatureValue(multiArray: try Self.int32Array(
                    [Int32](repeating: Int32(count - 1), count: scoredCount)))
                dictionary["target_ids"] = MLFeatureValue(multiArray: try Self.int32Array(
                    [Int32](repeating: 0, count: scoredCount)))
            }
            let result = try model.prediction(from: try MLDictionaryFeatureProvider(dictionary: dictionary), using: state)
            outputs.append(CallOutput(
                targetLogit: try Self.output(result, "target_logit"), logNorm: try Self.output(result, "log_norm"),
                spaceMass: try Self.output(result, "space_log_mass"), firstLogit: try Self.output(result, "first_logit"),
                rows: count))
        }
        return outputs
    }

    func score(_ request: TokenRequest) throws -> TimedScores {
        guard request.candidates.count <= Self.firstTokens else {
            throw ModelSpeedError("a request holds \(request.candidates.count) candidates, more than \(Self.firstTokens)")
        }
        let plan = planner.next(start: request.start, context: request.context)
        let state = states[plan.slot]
        let count = plan.window.count
        var padded = 0

        let windowStarted = Self.now()
        let windowRows = (plan.kept..<count).map { index in
            Row(token: plan.window[index], position: index, cell: index, allowed: [0..<(index + 1)], target: 0)
        }
        let windowOutputs = try run(
            state: state, rows: windowRows, firstIDs: request.candidates.map { $0[0] }, scoreAll: false,
            padded: &padded)
        let last = windowOutputs[windowOutputs.count - 1]
        let afterWindow = Self.value(last.logNorm, 0)
        let firstLogit = last.firstLogit
        let candidatesStarted = Self.now()

        var rows: [Row] = [], firstRows: [Int] = []
        for candidate in request.candidates {
            firstRows.append(rows.count)
            for (place, token) in candidate.enumerated() {
                let cell = count + rows.count
                rows.append(Row(
                    token: token, position: count + place, cell: cell,
                    allowed: [0..<count, (count + firstRows[firstRows.count - 1])..<(cell + 1)],
                    target: place + 1 < candidate.count ? candidate[place + 1] : 0))
            }
        }
        let candidateOutputs = try run(state: state, rows: rows, firstIDs: [], scoreAll: true, padded: &padded)
        // The row of each candidate token: the call that holds it and its place in the call.
        var places: [(output: Int, row: Int)] = []
        for (index, output) in candidateOutputs.enumerated() {
            places += (0..<output.rows).map { (index, $0) }
        }
        func number(_ row: Int, _ array: KeyPath<CallOutput, MLMultiArray>) -> Double {
            let place = places[row]
            return Self.value(candidateOutputs[place.output][keyPath: array], place.row)
        }
        var scores: [CandidateScore] = []
        for (owner, candidate) in request.candidates.enumerated() {
            var logProbability = Self.value(firstLogit, owner) - afterWindow
            for place in 0..<(candidate.count - 1) {
                let row = firstRows[owner] + place
                logProbability += number(row, \.targetLogit) - number(row, \.logNorm)
            }
            let lastRow = firstRows[owner] + candidate.count - 1
            scores.append(CandidateScore(
                logProbability: logProbability, spaceAfter: number(lastRow, \.spaceMass) - number(lastRow, \.logNorm)))
        }
        let ended = Self.now()
        return TimedScores(
            scores: scores, windowMilliseconds: candidatesStarted - windowStarted,
            candidateMilliseconds: ended - candidatesStarted, windowTokens: count, keptTokens: plan.kept,
            calls: windowOutputs.count + candidateOutputs.count, paddedTokens: padded)
    }
}

/// Core ML's plan for a compiled model: which device each operation prefers, from MLComputePlan.
enum CoreMLComputePlan {
    private final class Box: @unchecked Sendable {
        var result: Result<MLComputePlan, Error>?
    }

    /// The devices of this machine that Core ML can use.
    static func availableDevices() -> String {
        MLModel.availableComputeDevices.map(name).joined(separator: ", ")
    }

    private static func name(_ device: MLComputeDevice) -> String {
        switch device {
        case .cpu: return "processor"
        case .gpu: return "GPU"
        case .neuralEngine: return "Neural Engine"
        @unknown default: return "an unknown device"
        }
    }

    /// One line: per device, the operations that prefer it and their share of the estimated cost.
    static func summary(of url: URL, computeUnits: MLComputeUnits) throws -> String {
        let configuration = MLModelConfiguration()
        configuration.computeUnits = computeUnits
        let box = Box()
        let done = DispatchSemaphore(value: 0)
        Task.detached {
            do {
                box.result = .success(try await MLComputePlan.load(contentsOf: url, configuration: configuration))
            } catch {
                box.result = .failure(error)
            }
            done.signal()
        }
        done.wait()
        guard let plan = try box.result?.get() else { throw ModelSpeedError("MLComputePlan gave no result") }
        guard case .program(let program) = plan.modelStructure else {
            throw ModelSpeedError("the compute plan holds no ML program")
        }
        var operations: [String: Int] = [:], costs: [String: Double] = [:]
        var total = 0
        func walk(_ block: MLModelStructure.Program.Block) {
            for operation in block.operations {
                if let usage = plan.deviceUsage(for: operation) {
                    let device = name(usage.preferred)
                    operations[device, default: 0] += 1
                    costs[device, default: 0] += plan.estimatedCost(of: operation)?.weight ?? 0
                }
                total += 1
                for inner in operation.blocks { walk(inner) }
            }
        }
        for function in program.functions.values { walk(function.block) }
        let costTotal = costs.values.reduce(0, +)
        let parts = ["Neural Engine", "GPU", "processor"].map { device in
            String(format: "%@ %ld (%.1f%% of the cost)", device, operations[device] ?? 0,
                   costTotal > 0 ? 100 * (costs[device] ?? 0) / costTotal : 0)
        }
        return "\(parts.joined(separator: ", ")); \(total) operations, the rest have no device"
    }
}
