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

/// The scores of one request and the time of its two calls.
struct TimedScores: Sendable {
    let scores: [CandidateScore]
    let windowMilliseconds: Double
    let candidateMilliseconds: Double
    let windowTokens: Int
    let keptTokens: Int
}

/// Scores requests with a converted Core ML model of scripts/model-speed/coreml/convert.py.
///
/// Each slot of the planner has a Core ML state of its own, which holds the cache of its window.
/// A request makes two calls: the window call reads the window tokens after the kept ones, and
/// the candidate call reads every token of every candidate, each candidate in cells of its own
/// after the window. The attention mask lets each candidate see the window and its own earlier
/// tokens only, so the candidates share the window as the sequences of llama.cpp do.
final class CoreMLSpeedScorer {
    /// A mask value that keeps a cell out of the attention: -30000 in half precision.
    private static let maskedBits: UInt16 = 0xF753

    private let model: MLModel
    private let states: [MLState]
    private var planner = AnchoredWindowPlanner()

    init(compiledModel url: URL, computeUnits: MLComputeUnits) throws {
        let configuration = MLModelConfiguration()
        configuration.computeUnits = computeUnits
        model = try MLModel(contentsOf: url, configuration: configuration)
        states = [model.makeState(), model.makeState()]
    }

    private static func now() -> Double { ProcessInfo.processInfo.systemUptime * 1000 }

    private static func int32Array(_ values: [Int32]) throws -> MLMultiArray {
        let array = try MLMultiArray(shape: [1, NSNumber(value: values.count)], dataType: .int32)
        let pointer = array.dataPointer.bindMemory(to: Int32.self, capacity: values.count)
        for (index, value) in values.enumerated() { pointer[index] = value }
        return array
    }

    /// A mask of `rows` by `cells` in half precision. `allowed(row)` gives the cells that the
    /// row may attend to.
    private static func mask(rows: Int, cells: Int, allowed: (Int) -> [Range<Int>]) throws -> MLMultiArray {
        let array = try MLMultiArray(
            shape: [1, 1, NSNumber(value: rows), NSNumber(value: cells)], dataType: .float16)
        let strides = array.strides.map { $0.intValue }
        let pointer = array.dataPointer.bindMemory(to: UInt16.self, capacity: array.count)
        for row in 0..<rows {
            for cell in 0..<cells { pointer[row * strides[2] + cell * strides[3]] = maskedBits }
            for range in allowed(row) {
                for cell in range { pointer[row * strides[2] + cell * strides[3]] = 0 }
            }
        }
        return array
    }

    private func call(state: MLState, ids: [Int32], positions: [Int32], mask: MLMultiArray, targets: [Int32]) throws
        -> MLFeatureProvider
    {
        let input = try MLDictionaryFeatureProvider(dictionary: [
            "input_ids": MLFeatureValue(multiArray: try Self.int32Array(ids)),
            "position_ids": MLFeatureValue(multiArray: try Self.int32Array(positions)),
            "attention_mask": MLFeatureValue(multiArray: mask),
            "target_ids": MLFeatureValue(multiArray: try Self.int32Array(targets)),
        ])
        return try model.prediction(from: input, using: state)
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

    func score(_ request: TokenRequest) throws -> TimedScores {
        let plan = planner.next(start: request.start, context: request.context)
        let state = states[plan.slot]
        let count = plan.window.count
        let unread = count - plan.kept

        let windowStarted = Self.now()
        let windowMask = try Self.mask(rows: unread, cells: count) { row in [0..<(plan.kept + row + 1)] }
        let windowOutput = try call(
            state: state, ids: Array(plan.window[plan.kept...]), positions: (plan.kept..<count).map { Int32($0) },
            mask: windowMask, targets: [Int32](repeating: 0, count: unread))
        let lastLogits = try Self.output(windowOutput, "last_logits")
        let afterWindow = Self.value(try Self.output(windowOutput, "log_norm"), unread - 1)
        let candidatesStarted = Self.now()

        var tokens: [Int32] = [], targets: [Int32] = [], positions: [Int32] = [], firstRows: [Int] = []
        for candidate in request.candidates {
            firstRows.append(tokens.count)
            for (place, token) in candidate.enumerated() {
                tokens.append(token)
                targets.append(place + 1 < candidate.count ? candidate[place + 1] : 0)
                positions.append(Int32(count + place))
            }
        }
        var ownerFirstRow: [Int] = []
        for (owner, candidate) in request.candidates.enumerated() {
            ownerFirstRow += [Int](repeating: firstRows[owner], count: candidate.count)
        }
        let total = tokens.count
        let candidateMask = try Self.mask(rows: total, cells: count + total) { row in
            [0..<count, (count + ownerFirstRow[row])..<(count + row + 1)]
        }
        let candidateOutput = try call(
            state: state, ids: tokens, positions: positions, mask: candidateMask, targets: targets)
        let targetLogit = try Self.output(candidateOutput, "target_logit")
        let logNorm = try Self.output(candidateOutput, "log_norm")
        let spaceMass = try Self.output(candidateOutput, "space_log_mass")
        var scores: [CandidateScore] = []
        for (owner, candidate) in request.candidates.enumerated() {
            var logProbability = Self.value(lastLogits, Int(candidate[0])) - afterWindow
            for place in 0..<(candidate.count - 1) {
                let row = firstRows[owner] + place
                logProbability += Self.value(targetLogit, row) - Self.value(logNorm, row)
            }
            let last = firstRows[owner] + candidate.count - 1
            scores.append(CandidateScore(
                logProbability: logProbability, spaceAfter: Self.value(spaceMass, last) - Self.value(logNorm, last)))
        }
        let ended = Self.now()
        return TimedScores(
            scores: scores, windowMilliseconds: candidatesStarted - windowStarted,
            candidateMilliseconds: ended - candidatesStarted, windowTokens: count, keptTokens: plan.kept)
    }
}
