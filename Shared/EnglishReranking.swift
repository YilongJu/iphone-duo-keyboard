import Foundation

/// One reading of the typed span by the English typing engine (`duo_english_readings` in
/// Engine/duo_engine.c).
struct EnglishReading: Equatable {
    let text: String
    /// The engine's log probability of the reading, slips included: the number that
    /// `duo_correct_english` compares.
    let score: Double
    /// The part of `score` that the assumed slips cost, as a positive number.
    let slipCost: Double
    /// True for the text exactly as typed.
    let asTyped: Bool
    /// True for the reading that the engine chooses by itself.
    let chosen: Bool
}

/// The language model's two numbers for one candidate text, as natural logarithms.
struct CandidateScore: Equatable {
    /// Probability of the candidate's tokens right after the context.
    let logProbability: Double
    /// Probability that the token after the candidate starts with a space, which is what the
    /// person typed after the word.
    let spaceAfter: Double
}

/// The answer of a language model to one prompt.
enum CandidateScoringResult: Equatable {
    /// One score per candidate, in the order of the prompt.
    case scores([CandidateScore])
    /// The model is not loaded yet, was freed, or did not load. The engine's choice stays.
    case notReady(String)
    /// The prompt is outside the model's limits, such as a candidate of more than 32 tokens.
    case refused(String)
    /// The model or its tokenizer did not do its part. The keyboard names this on the space bar.
    case failed(String)
}

/// Scores the candidates of a prompt with a language model.
@MainActor
protocol CandidateScoring: AnyObject {
    func score(_ prompt: LanguageModelPrompt) -> CandidateScoringResult
}

/// The text that the language model reads for one correction: a context, and one candidate per
/// reading of the typed span.
///
/// `make` is the only place that decides this text. A model with another input format, such as
/// a fine-tuned model that reads the text before the word, the typed letters and then the
/// candidate, comes in by a change of `make` and of the model file. The rule's weight and margins
/// were tuned for distilgpt2 with this format, so a new model needs its own tuning as well.
struct LanguageModelPrompt: Equatable {
    /// The text the model reads after its start token. The scorer keeps the last 96 tokens.
    let context: String
    /// One text per reading, in the order of the readings. The model reads each one right after
    /// the context, so a candidate holds the space that separates it from the context.
    let candidates: [String]

    /// The format of the distilgpt2 tuning in scripts/lm-rerank/rerank.py: the text before the
    /// span without the spaces at its end, then one space and the reading. Both texts get the
    /// capitals a person sees in the field: the word "I" with its contractions, and the first
    /// letter of the field. A reading that opens the field follows the start token directly.
    ///
    /// `textBefore` is the field's text before the typed span, `typed` the span as typed, in
    /// lower case, and `readings` the engine's readings of the span. This format does not read
    /// `typed`, and a fine-tuned format may.
    static func make(textBefore: String, typed: String, readings: [String]) -> LanguageModelPrompt {
        var end = textBefore.endIndex
        while end > textBefore.startIndex, textBefore[textBefore.index(before: end)] == " " {
            end = textBefore.index(before: end)
        }
        let before = String(textBefore[..<end])
        let opensField = before.isEmpty
        return LanguageModelPrompt(
            context: withAutomaticCapitals(before, opensField: true),
            candidates: readings.map { (opensField ? "" : " ") + withAutomaticCapitals($0, opensField: opensField) })
    }

    /// `language_model_text` of scripts/lm-rerank/rerank.py: words split at single spaces.
    static func withAutomaticCapitals(_ text: String, opensField: Bool) -> String {
        let words = text.split(separator: " ", omittingEmptySubsequences: false).map { word -> String in
            word == "i" || word.hasPrefix("i'") ? "I" + word.dropFirst() : String(word)
        }
        let joined = words.joined(separator: " ")
        guard opensField, let first = joined.first else { return joined }
        return first.uppercased() + joined.dropFirst()
    }
}

/// The rule that picks one reading from the engine score and the language model's scores.
/// `choose` is `choose()` of scripts/lm-rerank/rerank.py.
struct RerankRule: Equatable {
    /// How much the model's log probabilities count against the engine score.
    let weight: Double
    /// How much higher another reading's combined score must be before it replaces the engine's
    /// choice, when the engine kept the text as typed.
    let marginFromTyped: Double
    /// The same, when the other reading is the text as typed.
    let marginToTyped: Double
    /// The same, for a move from one correction to another.
    let marginOther: Double
    /// True adds the probability of a space after the reading to its model score.
    let usesSpaceAfter: Bool
    /// The apostrophe step after the margins, or nil without it. `apostrophe_step` of
    /// scripts/lm-rerank/rerank.py.
    let apostrophe: ApostropheStep?

    /// The step that compares the choice with the readings of the same typed letters and other
    /// apostrophes, the twins, as "it's going" for the typed "its going".
    struct ApostropheStep: Equatable {
        enum Scope: Equatable {
            /// Every correction, and a twin may change any word of the span.
            case everyCorrection
            /// A span of two or more typed words, and a twin changes the first word alone. The
            /// model then reads the word after the changed word, and "its" alone stays as typed.
            case firstWordOfSpan
        }

        enum Score: Equatable {
            /// The model's log probability, with the space-after term when the rule uses it.
            case model
            /// The same, less the reading's slip cost.
            case modelLessSlipCost
        }

        let scope: Scope
        let score: Score
        /// The lead in step score that the best twin needs to replace the choice.
        let margin: Double
    }

    init(weight: Double, marginFromTyped: Double, marginToTyped: Double, marginOther: Double, usesSpaceAfter: Bool,
         apostrophe: ApostropheStep? = nil) {
        self.weight = weight
        self.marginFromTyped = marginFromTyped
        self.marginToTyped = marginToTyped
        self.marginOther = marginOther
        self.usesSpaceAfter = usesSpaceAfter
        self.apostrophe = apostrophe
    }

    /// The setting tuned for distilgpt2 Q3_K_M on the dev half (scripts/lm-rerank/README.md).
    static let distilgpt2 = RerankRule(
        weight: 1.0, marginFromTyped: 24, marginToTyped: 0, marginOther: 2, usesSpaceAfter: true)

    /// The distilgpt2 setting with the apostrophe step, its scope, score and margin chosen on the
    /// dev half of cases/english-apostrophe-words (docs/apostrophe-words-design.md). The keyboard
    /// uses this rule.
    static let distilgpt2WithApostrophes = RerankRule(
        weight: 1.0, marginFromTyped: 24, marginToTyped: 0, marginOther: 2, usesSpaceAfter: true,
        apostrophe: ApostropheStep(scope: .firstWordOfSpan, score: .modelLessSlipCost, margin: 1))

    /// Engine score plus the weighted model score.
    func combined(_ reading: EnglishReading, _ score: CandidateScore) -> Double {
        reading.score + weight * (score.logProbability + (usesSpaceAfter ? score.spaceAfter : 0.0))
    }

    /// The index of the reading to show. `scores` holds one score per reading, in the same
    /// order. The engine's choice stays unless the reading with the highest combined score,
    /// the first one on a tie, is higher by the margin of the move.
    func choose(_ readings: [EnglishReading], _ scores: [CandidateScore]) -> Int {
        precondition(readings.count == scores.count, "one score per reading")
        guard let chosen = readings.firstIndex(where: { $0.chosen }) else {
            preconditionFailure("the readings hold no chosen reading")
        }
        let combinedScores = readings.indices.map { combined(readings[$0], scores[$0]) }
        var best = 0
        for index in combinedScores.indices.dropFirst() where combinedScores[index] > combinedScores[best] {
            best = index
        }
        var choice = chosen
        if best != chosen {
            let margin = readings[chosen].asTyped
                ? marginFromTyped : (readings[best].asTyped ? marginToTyped : marginOther)
            if combinedScores[best] - combinedScores[chosen] >= margin { choice = best }
        }
        // With weight 0 the harness does not ask the model, and the step needs the model.
        guard let apostrophe, weight != 0 else { return choice }
        return apostropheStep(apostrophe, readings, scores, choice: choice)
    }

    /// Whether `text` is a twin of the typed text: the same letters and other apostrophes. In
    /// the scope `firstWordOfSpan` only the first word may differ, and the span holds two words
    /// or more. `is_twin` of scripts/lm-rerank/rerank.py.
    static func isTwin(_ text: String, of typed: String, scope: ApostropheStep.Scope) -> Bool {
        guard text != typed else { return false }
        func letters(_ word: Substring) -> String { word.replacingOccurrences(of: "'", with: "") }
        switch scope {
        case .everyCorrection:
            return letters(Substring(text)) == letters(Substring(typed))
        case .firstWordOfSpan:
            let words = text.split(separator: " ", omittingEmptySubsequences: false)
            let typedWords = typed.split(separator: " ", omittingEmptySubsequences: false)
            return typedWords.count >= 2 && words.count == typedWords.count
                && Array(words.dropFirst()) == Array(typedWords.dropFirst()) && letters(words[0]) == letters(typedWords[0])
        }
    }

    /// The model score, with the space-after term when the rule uses it, and less the slip cost
    /// for the score `modelLessSlipCost`. The engine's word statistics do not count: they come
    /// from a list of word pairs without a single contraction.
    private func stepScore(_ step: ApostropheStep, _ reading: EnglishReading, _ score: CandidateScore) -> Double {
        let value = score.logProbability + (usesSpaceAfter ? score.spaceAfter : 0.0)
        return step.score == .modelLessSlipCost ? value - reading.slipCost : value
    }

    /// The twin with the highest step score, the first one on a tie, replaces the choice when its
    /// step score leads by the margin. The text as typed is never a twin.
    private func apostropheStep(_ step: ApostropheStep, _ readings: [EnglishReading], _ scores: [CandidateScore], choice: Int) -> Int {
        guard let typed = readings.first(where: { $0.asTyped }) else {
            preconditionFailure("the readings hold no reading as typed")
        }
        var twin: Int?
        for index in readings.indices where index != choice && !readings[index].asTyped
            && Self.isTwin(readings[index].text, of: typed.text, scope: step.scope) {
            if let current = twin, stepScore(step, readings[index], scores[index]) <= stepScore(step, readings[current], scores[current]) {
                continue
            }
            twin = index
        }
        guard let twin else { return choice }
        let lead = stepScore(step, readings[twin], scores[twin]) - stepScore(step, readings[choice], scores[choice])
        return lead >= step.margin ? twin : choice
    }
}

/// One correction that went to the language model, for a test that compares the keyboard
/// with the harness of scripts/lm-rerank.
struct RerankTrace {
    let textBefore: String
    let prompt: LanguageModelPrompt
    let readings: [EnglishReading]
    let result: CandidateScoringResult
    /// The reading the keyboard shows.
    let choice: Int
    /// Time from the start of the prompt to the choice.
    let milliseconds: Double
}

/// Counts and times of the corrections that the language model read in this process.
struct RerankStatistics {
    /// Count of times kept for the median and the 95th percentile.
    static let recentLimit = 2000

    private(set) var readCount = 0
    private(set) var totalMilliseconds = 0.0
    private(set) var worstMilliseconds = 0.0
    private(set) var recentMilliseconds: [Double] = []
    /// Corrections where the model changed the engine's choice.
    private(set) var changedCount = 0
    private(set) var notReadyCount = 0
    private(set) var refusedCount = 0
    private(set) var failedCount = 0
    private(set) var lastProblem: String?

    mutating func recordRead(milliseconds: Double, changed: Bool) {
        readCount += 1
        totalMilliseconds += milliseconds
        worstMilliseconds = max(worstMilliseconds, milliseconds)
        recentMilliseconds.append(milliseconds)
        if recentMilliseconds.count > Self.recentLimit { recentMilliseconds.removeFirst() }
        if changed { changedCount += 1 }
    }

    mutating func recordNotReady(_ reason: String) {
        notReadyCount += 1
        lastProblem = "not ready: \(reason)"
    }

    mutating func recordRefused(_ reason: String) {
        refusedCount += 1
        lastProblem = "refused: \(reason)"
    }

    mutating func recordFailed(_ reason: String) {
        failedCount += 1
        lastProblem = "model error: \(reason)"
    }

    var meanMilliseconds: Double? { readCount > 0 ? totalMilliseconds / Double(readCount) : nil }

    /// The value below which `fraction` of the recent times fall, by the nearest rank.
    func percentileMilliseconds(_ fraction: Double) -> Double? {
        guard !recentMilliseconds.isEmpty else { return nil }
        let sorted = recentMilliseconds.sorted()
        let rank = Int((fraction * Double(sorted.count)).rounded(.up))
        return sorted[min(max(rank, 1), sorted.count) - 1]
    }
}

/// Re-ranks the English engine's readings with a language model, by the tuned rule.
@MainActor
final class EnglishReranker {
    /// Readings per correction that the model scores, as in the tuning.
    static let readingCount = 8

    private let scorer: CandidateScoring
    let rule: RerankRule
    private(set) var statistics = RerankStatistics()
    /// Receives each correction that had more than one reading. A test sets it.
    var onTrace: ((RerankTrace) -> Void)?
    /// Receives the reason when the model or its tokenizer did not do its part. The owner shows
    /// it on the space bar.
    var onModelError: (String) -> Void = { _ in }

    init(scorer: CandidateScoring, rule: RerankRule = .distilgpt2WithApostrophes) {
        self.scorer = scorer
        self.rule = rule
    }

    /// The text to show for the typed span. `textBefore` is the field's text before the span.
    /// With one reading, or while the model cannot score, the engine's choice stays.
    func choose(readings: [EnglishReading], textBefore: String, typed: String) -> String {
        guard let chosen = readings.firstIndex(where: { $0.chosen }) else {
            preconditionFailure("the readings hold no chosen reading")
        }
        guard readings.count > 1 else { return readings[chosen].text }
        let started = ProcessInfo.processInfo.systemUptime
        let prompt = LanguageModelPrompt.make(textBefore: textBefore, typed: typed, readings: readings.map { $0.text })
        let result = scorer.score(prompt)
        var choice = chosen
        switch result {
        case .scores(let scores):
            precondition(scores.count == readings.count, "the model gave \(scores.count) scores for \(readings.count) readings")
            choice = rule.choose(readings, scores)
        case .notReady(let reason):
            statistics.recordNotReady(reason)
        case .refused(let reason):
            statistics.recordRefused(reason)
        case .failed(let reason):
            statistics.recordFailed(reason)
            onModelError(reason)
        }
        let milliseconds = (ProcessInfo.processInfo.systemUptime - started) * 1000
        if case .scores = result {
            statistics.recordRead(milliseconds: milliseconds, changed: choice != chosen)
        }
        onTrace?(RerankTrace(
            textBefore: textBefore, prompt: prompt, readings: readings, result: result, choice: choice,
            milliseconds: milliseconds))
        return readings[choice].text
    }
}
