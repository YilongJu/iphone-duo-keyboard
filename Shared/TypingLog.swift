import UIKit

/// The readings behind one result of a spell checker. The typing log records them with the word.
struct ReadingDetail {
    /// The readings that the engine gave for the typed span. With a work area, the readings that
    /// the model could choose from (`PreferredCapitals.keepingNewWords`).
    let readings: [EnglishReading]
    /// One score of the model per reading, in the order of `readings`. The value is nil when the
    /// model did not score the readings.
    let modelScores: [CandidateScore]?
    /// The scores of the apostrophe step in its own prompt, by reading index.
    let stepScores: [Int: CandidateScore]
    /// The index of the reading that the rule chose with the model's scores. The value is nil
    /// when the model did not score the readings.
    let modelChoice: Int?
    /// The reason when the model was asked and did not score the readings, or nil.
    let modelNote: String?
}

extension ReadingDetail {
    /// The detail of `readings` with the trace of the language model. `trace` is nil when the
    /// model was not asked, as with one reading or without a model.
    init(readings: [EnglishReading], trace: RerankTrace?) {
        var modelScores: [CandidateScore]?
        var modelChoice: Int?
        var modelNote: String?
        if let trace {
            switch trace.result {
            case .scores(let scores):
                modelScores = scores
                modelChoice = trace.choice
            case .notReady(let reason):
                modelNote = "not ready: \(reason)"
            case .refused(let reason):
                modelNote = "refused: \(reason)"
            case .failed(let reason):
                modelNote = "model error: \(reason)"
            }
        }
        self.init(
            readings: readings, modelScores: modelScores, stepScores: trace?.stepScores ?? [:],
            modelChoice: modelChoice, modelNote: modelNote)
    }
}

/// The rule that says in which text fields the typing log may record.
enum TypingLogPolicy {
    /// True when the log may record in a field with these traits. The field must say that it is
    /// not secure, and must not name a content type. The field must also ask for a keyboard for
    /// prose. A content type marks a field for a password, a code, a name or an address. A field
    /// that does not say whether it is secure, or does not name its keyboard type, is not logged.
    static func allowsLog(
        isSecureTextEntry: Bool?, textContentType: UITextContentType?, keyboardType: UIKeyboardType?
    ) -> Bool {
        guard isSecureTextEntry == false, textContentType == nil else { return false }
        switch keyboardType {
        case .default, .asciiCapable, .twitter:
            return true
        default:
            return false
        }
    }
}

/// One reading of a sampled word, as the typing log stores it. The numbers have three decimals.
struct TypingLogReading: Codable, Equatable {
    let text: String
    /// The engine's log probability of the reading, slips included (`EnglishReading.score`).
    let engine: Double
    /// The part of `engine` that the assumed slips cost (`EnglishReading.slipCost`).
    let slip: Double
    /// The model's log probability of the reading after the context, or nil when the model did
    /// not score the readings.
    let model: Double?
    /// The model's log probability of a space after the reading, or nil in the same case.
    let space: Double?
    /// The same two numbers in the stock prompt of the apostrophe step, when the step asked for
    /// them, or nil.
    let stockModel: Double?
    let stockSpace: Double?
}

/// One sampled word of the typing log. The export writes one record per line.
struct TypingLogRecord: Codable, Equatable {
    /// The start of the hour in which the key came, in UTC. The log does not keep a finer time.
    let hour: String
    /// The end of the field's text before the typed span, `TypingLog.contextLength` characters
    /// at most.
    let context: String
    /// The keys that the person pressed for the span. The span is the committed word. The span
    /// also holds the word before it when the keyboard read the two words together.
    let typed: String
    /// The text of the span in the field right before the key that ended the word. It differs
    /// from `typed` when the keyboard changed the first word of the span at an earlier key.
    let inField: String
    /// The text of the span in the field after the correction.
    let shown: String
    /// The key that ended the word.
    let end: String
    /// True when the keyboard changed the text of the span at this key.
    let changed: Bool
    /// True for a word that the person brought back after an earlier correction. The keyboard
    /// keeps such a word as typed and does not ask for its readings.
    let kept: Bool
    /// The readings of the typed span. The list is empty when the keyboard did not ask for them.
    let readings: [TypingLogReading]
    /// The index in `readings` of the text as typed, or nil without readings.
    let asTyped: Int?
    /// The index in `readings` of the engine's own choice, or nil without readings.
    let engineChoice: Int?
    /// The index in `readings` of the choice with the model's scores. The value is nil when the
    /// model did not score the readings.
    let modelChoice: Int?
    /// The reason when the model was asked and did not score the readings, or nil.
    let modelNote: String?
    /// True when the person deleted the last character of the span with the backspace key,
    /// before the next committed word.
    var backspaced: Bool
    /// True when the person brought the typed text back with one backspace right after the
    /// correction.
    var reverted: Bool
}

/// The first line of an export.
struct TypingLogHeader: Codable, Equatable {
    /// What the text is.
    let file: String
    /// Count of record lines after this line.
    let records: Int
    /// Count of records in the log. The export holds the newest of them that fit its limit.
    let stored: Int
    /// The share of committed words that the log samples.
    let samplingProbability: Double
}

/// Keeps the switch and the records of the typing log between two launches of the keyboard.
@MainActor
protocol TypingLogStoring: AnyObject {
    /// True after the person turned the log on. A store without the value gives false, so the
    /// log is off in a new install.
    var isOn: Bool { get set }
    /// The stored records, oldest first, one line of JSON per record. A store without records
    /// gives an empty list.
    func readRecords() throws -> [String]
    /// Puts `records` in place of the stored records.
    func writeRecords(_ records: [String]) throws
    /// Erases the stored records.
    func removeRecords() throws
}

/// The store of the typing log on the phone. The switch is in the settings of the process, and
/// the records are in one file. Both stay in the container of the process that runs this code.
/// The keyboard extension does not share that container with the app or with an app group.
@MainActor
final class FileTypingLogStore: TypingLogStoring {
    private static let switchKey = "typingLogOn"
    static let fileName = "typing-log.jsonl"

    private let settings: UserDefaults
    let fileURL: URL

    init(settings: UserDefaults, fileURL: URL) {
        self.settings = settings
        self.fileURL = fileURL
    }

    /// The store in the container of this process: its own settings, and the file
    /// typing-log.jsonl in its Application Support folder.
    static func inOwnContainer() -> FileTypingLogStore {
        guard let folder = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first else {
            fatalError("this process does not have an Application Support folder")
        }
        return FileTypingLogStore(settings: .standard, fileURL: folder.appendingPathComponent(fileName))
    }

    var isOn: Bool {
        get { settings.bool(forKey: Self.switchKey) }
        set { settings.set(newValue, forKey: Self.switchKey) }
    }

    func readRecords() throws -> [String] {
        // The file does not exist on a phone before the log saves its first record.
        guard FileManager.default.fileExists(atPath: fileURL.path) else { return [] }
        let text = try String(contentsOf: fileURL, encoding: .utf8)
        return text.split(separator: "\n").map(String.init)
    }

    func writeRecords(_ records: [String]) throws {
        try FileManager.default.createDirectory(
            at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        let text = records.map { $0 + "\n" }.joined()
        try Data(text.utf8).write(to: fileURL, options: .atomic)
        // A backup of the phone, in iCloud or on a computer, does not take the file. The write
        // puts a new file in place of the old one, so each write sets the mark again.
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        var url = fileURL
        try url.setResourceValues(values)
    }

    func removeRecords() throws {
        guard FileManager.default.fileExists(atPath: fileURL.path) else { return }
        try FileManager.default.removeItem(at: fileURL)
    }
}

/// A log of a random sample of the words that the person commits (docs/typing-log-design.md).
/// A person later counts the typing slips of the sample by hand. The log is off until the person
/// turns it on.
///
/// A committed word is a word that a word terminator ends and that the keyboard may correct.
/// The log samples each committed word with the probability `samplingProbability`, changed or
/// not. A sampled word becomes a pending record, which the log holds in memory. The pending
/// records go to the store when the keyboard moves to another field or leaves the screen. So a
/// key press does not write to the disk. A field that may not be logged does not get a record.
/// The pending records of such a field do not reach the store.
@MainActor
final class TypingLog {
    /// The share of committed words that the log samples.
    nonisolated static let samplingProbability = 0.1
    /// Count of records that the log keeps. A new record takes the place of the oldest one.
    nonisolated static let standardRecordLimit = 300
    /// Count of characters of record lines that an export holds at most.
    nonisolated static let standardExportCharacterLimit = 150_000
    /// Count of characters of the field's text before the typed span that a record keeps.
    nonisolated static let contextLength = 60
    /// The text of `TypingLogHeader.file`.
    nonisolated static let exportTitle = "Duo Keyboard typing log. Each line after this one holds one sampled word as JSON."

    private let store: TypingLogStoring
    /// Gives a value from 0 up to 1, without 1, with equal chance. A test passes a fixed value.
    private let random: () -> Double
    private let now: () -> Date
    let recordLimit: Int
    let exportCharacterLimit: Int

    /// Answers whether the log may record in the field that the keyboard types into now. The
    /// owner sets it. Without an answer the log does not record.
    var fieldIsLoggable: () -> Bool = { false }
    /// Receives the reason when the store did not read, write or erase. The owner shows it on
    /// the space bar.
    var onProblem: (String) -> Void = { _ in }

    private(set) var isOn: Bool

    /// A sampled word that the store does not hold yet.
    private struct PendingRecord {
        let id: Int
        /// The field in which the person typed the word.
        let field: UUID
        var record: TypingLogRecord
    }

    private var pending: [PendingRecord] = []
    private var nextID = 0

    /// The last sampled word, while the log can still tell where the word stands in its field.
    /// A backspace into the word and a revert of its correction mark its pending record.
    private struct LastSampledWord {
        let id: Int
        let field: UUID
        /// The end of the field's text up to the end of the word.
        let anchor: String
        /// True when `anchor` is the whole text before the cursor at the end of the word.
        let wholeText: Bool

        /// True when the cursor stands right after the word.
        func ends(_ textBefore: String) -> Bool {
            wholeText ? textBefore == anchor : textBefore.hasSuffix(anchor)
        }
    }

    private var lastSampled: LastSampledWord?

    /// The records of the store, read once and then kept here, or nil before the first read.
    private var stored: [String]?

    init(
        store: TypingLogStoring, random: @escaping () -> Double = { Double.random(in: 0..<1) },
        now: @escaping () -> Date = { Date() }, recordLimit: Int = TypingLog.standardRecordLimit,
        exportCharacterLimit: Int = TypingLog.standardExportCharacterLimit
    ) {
        precondition(recordLimit > 0, "the log keeps one record or more")
        self.store = store
        self.random = random
        self.now = now
        self.recordLimit = recordLimit
        self.exportCharacterLimit = exportCharacterLimit
        isOn = store.isOn
    }

    /// Count of sampled words that the store does not hold yet. The tests read it.
    var pendingCount: Int { pending.count }

    /// True while the log can still mark the last sampled word.
    var followsAWord: Bool { isOn && lastSampled != nil }

    // MARK: Commands

    /// Turns the log on or off, stores the switch, and returns a short text that names the new
    /// state. The words sampled before the switch stay.
    func toggle() -> String {
        isOn.toggle()
        store.isOn = isOn
        lastSampled = nil
        return isOn ? "Typing log on" : "Typing log off"
    }

    /// The text of the export and the count of records in it. The first line is a
    /// `TypingLogHeader`, and each line after it is one record, oldest first. The export holds
    /// the newest records whose lines fit in `exportCharacterLimit` characters. The pending
    /// records go to the store first. `field` is the field of the keyboard now.
    func export(field: UUID) -> (text: String, records: Int) {
        if !pending.isEmpty {
            _ = allows(field)
            save(keeping: nil)
        }
        var lines: [String] = []
        do {
            lines = try storedLines()
        } catch {
            onProblem("the stored records were not read: \(error.localizedDescription)")
        }
        // Records that the store did not take are still pending, and the export holds them too.
        lines.append(contentsOf: pending.map { Self.line(of: $0.record) })
        var newest: [String] = []
        var size = 0
        for line in lines.reversed() {
            guard size + line.count + 1 <= exportCharacterLimit else { break }
            newest.append(line)
            size += line.count + 1
        }
        let header = TypingLogHeader(
            file: Self.exportTitle, records: newest.count, stored: lines.count,
            samplingProbability: Self.samplingProbability)
        let text = ([Self.line(of: header)] + Array(newest.reversed())).joined(separator: "\n") + "\n"
        return (text, newest.count)
    }

    /// Erases every record: the pending ones and those of the store.
    func clear() {
        pending = []
        lastSampled = nil
        stored = []
        do {
            try store.removeRecords()
        } catch {
            onProblem("the stored records were not erased: \(error.localizedDescription)")
        }
    }

    // MARK: Words

    /// A key ended a word that the keyboard may correct. The log samples the word with the
    /// probability `samplingProbability`, while the log is on and may record in the field.
    ///
    /// `typed` is the typed span. `inField` is the text that the field held for the span.
    /// `shown` is the text that the field holds now. `terminator` is the key, which the keyboard
    /// types next. `textBefore` is the field's text before the span. `detail` holds the readings
    /// of the span, or nil when the keyboard did not ask for them. `kept` marks a word that the
    /// keyboard keeps as typed. `field` identifies the field.
    func wordCommitted(
        typed: String, inField: String, shown: String, terminator: String, textBefore: String,
        detail: ReadingDetail?, kept: Bool, field: UUID
    ) {
        guard isOn else { return }
        // A new committed word ends the marks on the word before it.
        lastSampled = nil
        guard allows(field) else { return }
        // The word "duo" before a colon starts a command of the keyboard, as in "duo:log".
        if terminator == ":", typed.split(separator: " ").last?.lowercased() == "duo" { return }
        guard random() < Self.samplingProbability else { return }
        var readings: [TypingLogReading] = []
        if let detail {
            for (index, reading) in detail.readings.enumerated() {
                let model = detail.modelScores?[index]
                let step = detail.stepScores[index]
                readings.append(TypingLogReading(
                    text: reading.text, engine: roundedToThousandths(reading.score),
                    slip: roundedToThousandths(reading.slipCost),
                    model: model.map { roundedToThousandths($0.logProbability) },
                    space: model.map { roundedToThousandths($0.spaceAfter) },
                    stockModel: step.map { roundedToThousandths($0.logProbability) },
                    stockSpace: step.map { roundedToThousandths($0.spaceAfter) }))
            }
        }
        let context = String(textBefore.suffix(Self.contextLength))
        let record = TypingLogRecord(
            hour: Self.hourText(of: now()), context: context, typed: typed, inField: inField, shown: shown,
            end: terminator, changed: shown != inField, kept: kept, readings: readings,
            asTyped: detail?.readings.firstIndex(where: { $0.asTyped }),
            engineChoice: detail?.readings.firstIndex(where: { $0.chosen }),
            modelChoice: detail?.modelChoice, modelNote: detail?.modelNote, backspaced: false, reverted: false)
        nextID += 1
        pending.append(PendingRecord(id: nextID, field: field, record: record))
        if pending.count > recordLimit {
            pending.removeFirst(pending.count - recordLimit)
        }
        lastSampled = LastSampledWord(
            id: nextID, field: field, anchor: context + shown, wholeText: textBefore.count <= Self.contextLength)
    }

    /// The person brought back the text `original` in place of `corrected`, with one backspace
    /// right after the correction. Marks the last sampled word when the correction was its own.
    func correctionReverted(original: String, corrected: String, field: UUID) {
        guard isOn, let word = lastSampled, word.field == field, allows(field),
            let index = pending.firstIndex(where: { $0.id == word.id })
        else { return }
        let record = pending[index].record
        // A correction of a word that the log did not see does not mark the sampled word.
        guard record.inField == original, record.shown == corrected else { return }
        pending[index].record.reverted = true
        // The field holds the typed text again, without the key that ended the word.
        lastSampled = LastSampledWord(
            id: word.id, field: field, anchor: record.context + original, wholeText: word.wholeText)
    }

    /// The backspace key deletes the character before the cursor next. `textBefore` is the text
    /// before the cursor now. Marks the last sampled word when the cursor stands right after
    /// the word. The key then deletes the last character of the word.
    func backspace(textBefore: String, field: UUID) {
        guard isOn, let word = lastSampled, word.field == field, word.ends(textBefore), allows(field),
            let index = pending.firstIndex(where: { $0.id == word.id })
        else { return }
        pending[index].record.backspaced = true
        // The word changes now, so the log does not know its place any more.
        lastSampled = nil
    }

    // MARK: Path to the store

    /// The keyboard may type into another field now. The pending records of every other field
    /// go to the store. The pending records of this field are dropped when the log may not
    /// record in the field.
    func fieldChanged(to field: UUID) {
        guard !pending.isEmpty else { return }
        _ = allows(field)
        save(keeping: field)
    }

    /// The keyboard leaves the screen. The pending records go to the store. The records of this
    /// field are dropped first when the log may not record in the field any more.
    func keyboardWillHide(field: UUID) {
        guard !pending.isEmpty else { return }
        _ = allows(field)
        save(keeping: nil)
    }

    /// Asks whether the log may record in the field of the keyboard now. A field that may not
    /// be logged loses its pending records, so they do not reach the store.
    private func allows(_ field: UUID) -> Bool {
        if fieldIsLoggable() { return true }
        pending.removeAll { $0.field == field }
        if lastSampled?.field == field { lastSampled = nil }
        return false
    }

    private func storedLines() throws -> [String] {
        if let stored { return stored }
        let lines = try store.readRecords()
        stored = lines
        return lines
    }

    /// Writes the pending records to the store, except those of the field `field`, which stay
    /// pending. The store keeps the newest `recordLimit` records. When the store does not read
    /// or write, the records stay pending for the next call.
    private func save(keeping field: UUID?) {
        let leaving = pending.filter { $0.field != field }
        guard !leaving.isEmpty else { return }
        do {
            var lines = try storedLines()
            lines.append(contentsOf: leaving.map { Self.line(of: $0.record) })
            if lines.count > recordLimit {
                lines.removeFirst(lines.count - recordLimit)
            }
            try store.writeRecords(lines)
            stored = lines
            pending.removeAll { $0.field != field }
            if let word = lastSampled, word.field != field { lastSampled = nil }
        } catch {
            onProblem("the records were not saved: \(error.localizedDescription)")
        }
    }

    // MARK: Text of a record

    /// The start of the hour of `date` in UTC, as in "2026-11-11T14:00:00Z".
    nonisolated static func hourText(of date: Date) -> String {
        let hour = (date.timeIntervalSince1970 / 3600).rounded(.down) * 3600
        return ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: hour))
    }

    /// One line of JSON for a record, or for the first line of an export. The keys stand in the
    /// order of their names.
    private nonisolated static func line<Value: Encodable>(of value: Value) -> String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        encoder.nonConformingFloatEncodingStrategy = .convertToString(
            positiveInfinity: "inf", negativeInfinity: "-inf", nan: "nan")
        do {
            return String(decoding: try encoder.encode(value), as: UTF8.self)
        } catch {
            // A record holds text, numbers and marks only. A record that does not encode is a
            // fault of this file.
            preconditionFailure("the typing log did not encode a record: \(error)")
        }
    }
}

/// `value` with three decimals, which is enough to compare two readings.
private func roundedToThousandths(_ value: Double) -> Double {
    (value * 1000).rounded() / 1000
}
