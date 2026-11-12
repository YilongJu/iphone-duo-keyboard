import UIKit
import XCTest

@testable import DuoKeyboard

/// A store of the typing log in memory.
@MainActor
final class FakeTypingLogStore: TypingLogStoring {
    struct Failure: Error {}

    var isOn: Bool {
        didSet { switchWrites += 1 }
    }
    var records: [String] = []
    /// Count of times the log stored the switch.
    private(set) var switchWrites = 0
    /// Count of calls of `writeRecords`, with those that failed.
    private(set) var writeAttempts = 0
    /// True makes every write fail.
    var failsWrites = false

    init(isOn: Bool) {
        self.isOn = isOn
    }

    func readRecords() throws -> [String] {
        records
    }

    func writeRecords(_ records: [String]) throws {
        writeAttempts += 1
        if failsWrites { throw Failure() }
        self.records = records
    }

    func removeRecords() throws {
        records = []
    }
}

/// The answers that a test gives the typing log.
final class TypingLogAnswers {
    /// The value of the random source. The log samples a word when the value is below
    /// `TypingLog.samplingProbability`, so 0 samples every word.
    var random = 0.0
    /// Count of values that the log took from the random source.
    var draws = 0
    /// False for a field that the log may not record in, such as a password field.
    var loggable = true
}

/// The typing log in the keyboard's own typing code. The tests cover the commands, the sampling,
/// the limits, and the marks of a backspace and a revert. They also cover the fields that the
/// log may not record in.
@MainActor
final class TypingLogTests: XCTestCase {
    private var keyboardView: KeyboardView!
    private var document: FakeDocument!
    private var controller: KeyboardTextController!
    private var store: FakeTypingLogStore!
    private var answers: TypingLogAnswers!
    private var typingLog: TypingLog!

    /// The hour of the fixed time that the tests give the log.
    private let hour = "2023-11-14T22:00:00Z"

    /// A keyboard with a typing log that samples every word, in a field that may be logged.
    /// Without `spellChecker` the keyboard reads the words with a `FakeSpellChecker`.
    private func makeController(
        before: String, on: Bool = true, spellChecker: SpellChecking? = nil,
        recordLimit: Int = TypingLog.standardRecordLimit
    ) {
        keyboardView = KeyboardView()
        document = FakeDocument(before: before)
        let checker: SpellChecking = spellChecker ?? FakeSpellChecker()
        controller = KeyboardTextController(
            keyboardView: keyboardView, document: document, spellChecker: checker,
            pinyinEngine: { PinyinEngine(dictionaryText: testDictionary) })
        store = FakeTypingLogStore(isOn: on)
        let answers = TypingLogAnswers()
        self.answers = answers
        typingLog = TypingLog(
            store: store,
            random: {
                answers.draws += 1
                return answers.random
            },
            now: { Date(timeIntervalSince1970: 1_700_000_000) }, recordLimit: recordLimit)
        typingLog.fieldIsLoggable = { answers.loggable }
        controller.typingLog = typingLog
    }

    private func type(_ text: String) {
        for character in text {
            controller.keyboardView(keyboardView, insert: String(character))
        }
    }

    private func pressBackspace(times: Int = 1) {
        for _ in 0..<times {
            controller.keyboardViewDeleteBackward(keyboardView)
        }
    }

    /// The keyboard leaves the screen, as in `viewWillDisappear` of the keyboard extension.
    private func hideKeyboard() {
        controller.cancelPendingEdits()
    }

    private func decoded(_ lines: [String]) throws -> [TypingLogRecord] {
        try lines.map { try JSONDecoder().decode(TypingLogRecord.self, from: Data($0.utf8)) }
    }

    /// The records of the store.
    private func storedRecords() throws -> [TypingLogRecord] {
        try decoded(store.records)
    }

    /// A record of a word that the keyboard did not ask a reading for, or asked a fake checker.
    private func expectedRecord(
        context: String, typed: String, inField: String? = nil, shown: String? = nil, end: String = " ",
        kept: Bool = false, backspaced: Bool = false, reverted: Bool = false
    ) -> TypingLogRecord {
        let field = inField ?? typed
        let text = shown ?? field
        return TypingLogRecord(
            hour: hour, context: context, typed: typed, inField: field, shown: text, end: end, changed: text != field,
            kept: kept, readings: [], asTyped: nil, engineChoice: nil, modelChoice: nil, modelNote: nil,
            backspaced: backspaced, reverted: reverted)
    }

    // MARK: The switch

    func testTheLogIsOffInANewInstallAndRecordsNothing() {
        makeController(before: "", on: false)
        XCTAssertFalse(typingLog.isOn)
        type("teh cat ")
        pressBackspace()
        XCTAssertEqual(document.text, "the cat")
        hideKeyboard()
        XCTAssertEqual(typingLog.pendingCount, 0)
        XCTAssertEqual(store.records, [])
        XCTAssertEqual(store.writeAttempts, 0)
        XCTAssertEqual(answers.draws, 0)
    }

    func testTheCommandTurnsTheLogOnAndOffAndLeavesTheField() {
        makeController(before: "Notes. ", on: false)
        type("duo:log ")
        XCTAssertEqual(document.text, "Notes. ")
        XCTAssertTrue(typingLog.isOn)
        XCTAssertTrue(store.isOn)
        XCTAssertEqual(keyboardView.spaceCaption, "Typing log on")
        // A new keyboard reads the stored switch.
        XCTAssertTrue(TypingLog(store: store).isOn)
        // A capital first letter also counts, because the keyboard capitalizes the start of a sentence.
        type("Duo:log ")
        XCTAssertEqual(document.text, "Notes. ")
        XCTAssertFalse(typingLog.isOn)
        XCTAssertFalse(store.isOn)
        XCTAssertEqual(keyboardView.spaceCaption, "Typing log off")
        XCTAssertFalse(TypingLog(store: store).isOn)
        XCTAssertEqual(store.switchWrites, 2)
        // The command text itself is not a sampled word.
        hideKeyboard()
        XCTAssertEqual(store.records, [])
    }

    func testTheCommandInsideALongerTextIsTypedAsText() {
        // A sign or a letter right before the command, and a letter after it. Also a missing
        // letter, a space in place of the colon, and the command without its space.
        for text in ["@duo:log ", "xduo:log ", "duo:logs ", "duo:lo ", "duo log ", "duo:log"] {
            makeController(before: "", on: false)
            type(text)
            XCTAssertEqual(document.text, text)
            XCTAssertFalse(typingLog.isOn, text)
            XCTAssertEqual(store.switchWrites, 0, text)
        }
    }

    func testTheCommandsArePlainTextWithoutALog() {
        for text in ["duo:log ", "duo:logexport ", "duo:logclear "] {
            makeController(before: "", on: false)
            controller.typingLog = nil
            type(text)
            XCTAssertEqual(document.text, text)
            XCTAssertFalse(typingLog.isOn, text)
        }
    }

    func testTheLongerCommandsDoNotTurnTheLogOnOrOff() throws {
        for on in [false, true] {
            makeController(before: "", on: on)
            type("duo:logexport ")
            XCTAssertEqual(typingLog.isOn, on)
            // The export of an empty log is its first line alone.
            let lines = document.text.split(separator: "\n").map(String.init)
            XCTAssertEqual(lines.count, 1)
            XCTAssertTrue(document.text.hasSuffix("\n"))
            let header = try JSONDecoder().decode(TypingLogHeader.self, from: Data(try XCTUnwrap(lines.first).utf8))
            XCTAssertEqual(header.records, 0)
            type("duo:logclear ")
            XCTAssertEqual(typingLog.isOn, on)
            XCTAssertEqual(store.isOn, on)
            XCTAssertEqual(store.switchWrites, 0)
            XCTAssertEqual(keyboardView.spaceCaption, "Typing log erased")
        }
    }

    // MARK: Sampling

    func testASampledUnchangedWordIsRecorded() throws {
        makeController(before: "I saw ")
        type("cat ")
        XCTAssertEqual(document.text, "I saw cat ")
        // The record waits in memory. A key press does not write to the store.
        XCTAssertEqual(typingLog.pendingCount, 1)
        XCTAssertEqual(store.writeAttempts, 0)
        hideKeyboard()
        XCTAssertEqual(try storedRecords(), [expectedRecord(context: "I saw ", typed: "cat")])
        XCTAssertEqual(typingLog.pendingCount, 0)
        XCTAssertEqual(store.writeAttempts, 1)
    }

    func testASampledChangedWordIsRecordedWithTheTypedAndTheShownText() throws {
        makeController(before: "I saw ")
        type("teh.")
        XCTAssertEqual(document.text, "I saw the.")
        hideKeyboard()
        let records = try storedRecords()
        XCTAssertEqual(records, [expectedRecord(context: "I saw ", typed: "teh", shown: "the", end: ".")])
        XCTAssertEqual(records.first?.changed, true)
    }

    func testTheSecondWordOfASpanIsRecordedWithTheKeysOfBothWords() throws {
        makeController(before: "")
        type("teh cat ")
        XCTAssertEqual(document.text, "the cat ")
        hideKeyboard()
        XCTAssertEqual(try storedRecords(), [
            expectedRecord(context: "", typed: "teh", shown: "the"),
            // The keyboard changed "teh" at the first space, so the second space did not change the text.
            expectedRecord(context: "", typed: "teh cat", inField: "the cat"),
        ])
    }

    func testAnUnsampledWordIsNotRecorded() throws {
        makeController(before: "")
        // A value that is not below the probability does not sample the word.
        answers.random = TypingLog.samplingProbability
        type("teh cat ")
        XCTAssertEqual(document.text, "the cat ")
        XCTAssertEqual(answers.draws, 2)
        XCTAssertEqual(typingLog.pendingCount, 0)
        answers.random = TypingLog.samplingProbability - 0.001
        type("dog ")
        XCTAssertEqual(answers.draws, 3)
        hideKeyboard()
        XCTAssertEqual(try storedRecords().map { $0.typed }, ["cat dog"])
    }

    func testTheContextOfARecordHoldsTheLastSixtyCharacters() throws {
        let before = String(repeating: "word ", count: 20)
        makeController(before: before)
        type("cat ")
        hideKeyboard()
        let context = try XCTUnwrap(storedRecords().first?.context)
        XCTAssertEqual(context.count, TypingLog.contextLength)
        XCTAssertEqual(context, String(before.suffix(60)))
    }

    func testTheHourOfARecordIsTheStartOfTheHourInUTC() {
        XCTAssertEqual(TypingLog.hourText(of: Date(timeIntervalSince1970: 1_700_000_000)), hour)
        XCTAssertEqual(TypingLog.hourText(of: Date(timeIntervalSince1970: 1_699_999_200)), hour)
        XCTAssertEqual(TypingLog.hourText(of: Date(timeIntervalSince1970: 1_699_999_199)), "2023-11-14T21:00:00Z")
    }

    func testAKeptWordIsRecordedAsKept() throws {
        makeController(before: "")
        type("teh ")
        pressBackspace()
        type(" ")
        XCTAssertEqual(document.text, "teh ")
        hideKeyboard()
        XCTAssertEqual(try storedRecords(), [
            expectedRecord(context: "", typed: "teh", shown: "the", reverted: true),
            expectedRecord(context: "", typed: "teh", kept: true),
        ])
    }

    // MARK: Readings

    func testASampledWordHoldsItsReadingsWithTheEngineAndTheModelScores() throws {
        let storeName = "TypingLogTests"
        UserDefaults().removePersistentDomain(forName: storeName)
        defer { UserDefaults().removePersistentDomain(forName: storeName) }
        let scorer = FakeScorer { prompt in
            .scores(prompt.candidates.indices.map { CandidateScore(logProbability: -Double($0) - 1.25, spaceAfter: -0.5) })
        }
        let reranker = EnglishReranker(scorer: scorer, rule: KeyboardLanguageModel.rule)
        var traces: [RerankTrace] = []
        reranker.onTrace = { traces.append($0) }
        let checker = EngineSpellChecker(
            engine: EnglishTypingEngine(lexicon: TypingLexicon(resource: "lexicon-english", fullCheck: false)),
            reranker: reranker, store: try XCTUnwrap(UserDefaults(suiteName: storeName)))
        makeController(before: "this is a ", spellChecker: checker)
        type("teh ")
        hideKeyboard()
        let record = try XCTUnwrap(storedRecords().first)
        let trace = try XCTUnwrap(traces.last)
        XCTAssertGreaterThan(record.readings.count, 1)
        XCTAssertEqual(record.readings.map { $0.text }, trace.readings.map { $0.text })
        for (index, reading) in record.readings.enumerated() {
            XCTAssertEqual(reading.engine, trace.readings[index].score, accuracy: 0.001)
            XCTAssertEqual(reading.slip, trace.readings[index].slipCost, accuracy: 0.001)
            XCTAssertEqual(reading.model, -Double(index) - 1.25)
            XCTAssertEqual(reading.space, -0.5)
            XCTAssertNil(reading.stockModel)
            XCTAssertNil(reading.stockSpace)
        }
        XCTAssertEqual(record.asTyped, trace.readings.firstIndex { $0.asTyped })
        XCTAssertEqual(record.engineChoice, trace.readings.firstIndex { $0.chosen })
        XCTAssertEqual(record.modelChoice, trace.choice)
        XCTAssertNil(record.modelNote)
        XCTAssertEqual(record.typed, "teh")
        XCTAssertEqual(record.context, "this is a ")
        // The log does not change the correction: the field holds the reading of the trace.
        XCTAssertEqual(record.shown.lowercased(), trace.readings[trace.choice].text)
        XCTAssertEqual(document.text, "this is a \(record.shown) ")
    }

    func testAModelThatIsNotReadyLeavesTheRecordWithoutModelScores() throws {
        let storeName = "TypingLogTests"
        UserDefaults().removePersistentDomain(forName: storeName)
        defer { UserDefaults().removePersistentDomain(forName: storeName) }
        let scorer = FakeScorer { _ in .notReady("the model is loading") }
        let checker = EngineSpellChecker(
            engine: EnglishTypingEngine(lexicon: TypingLexicon(resource: "lexicon-english", fullCheck: false)),
            reranker: EnglishReranker(scorer: scorer, rule: KeyboardLanguageModel.rule),
            store: try XCTUnwrap(UserDefaults(suiteName: storeName)))
        makeController(before: "", spellChecker: checker)
        type("teh ")
        XCTAssertEqual(document.text, "the ")
        hideKeyboard()
        let record = try XCTUnwrap(storedRecords().first)
        XCTAssertGreaterThan(record.readings.count, 1)
        XCTAssertTrue(record.readings.allSatisfy { $0.model == nil && $0.space == nil })
        XCTAssertNil(record.modelChoice)
        XCTAssertEqual(record.modelNote, "not ready: the model is loading")
        let engineChoice = try XCTUnwrap(record.engineChoice)
        XCTAssertEqual(record.readings[engineChoice].text, "the")
        let asTyped = try XCTUnwrap(record.asTyped)
        XCTAssertEqual(record.readings[asTyped].text, "teh")
        XCTAssertEqual(record.shown, "the")
        XCTAssertTrue(record.changed)
    }

    // MARK: Fields that the log may not record in

    func testNothingIsRecordedInASecureFieldWhileTheLogIsOn() {
        makeController(before: "")
        answers.loggable = false
        type("teh cat ")
        pressBackspace(times: 2)
        XCTAssertEqual(document.text, "the ca")
        XCTAssertTrue(typingLog.isOn)
        XCTAssertEqual(typingLog.pendingCount, 0)
        XCTAssertEqual(answers.draws, 0)
        hideKeyboard()
        XCTAssertEqual(store.records, [])
        XCTAssertEqual(store.writeAttempts, 0)
    }

    func testAFieldThatTurnsSecureLosesItsPendingRecords() throws {
        // The keyboard hears of a change of the field.
        makeController(before: "")
        type("teh ")
        XCTAssertEqual(typingLog.pendingCount, 1)
        answers.loggable = false
        controller.documentDidChange()
        XCTAssertEqual(typingLog.pendingCount, 0)
        hideKeyboard()
        XCTAssertEqual(store.records, [])

        // The keyboard leaves the screen.
        makeController(before: "")
        type("teh ")
        answers.loggable = false
        hideKeyboard()
        XCTAssertEqual(typingLog.pendingCount, 0)
        XCTAssertEqual(store.records, [])
        XCTAssertEqual(store.writeAttempts, 0)

        // The person types the next word.
        makeController(before: "")
        type("teh ")
        answers.loggable = false
        type("cat ")
        XCTAssertEqual(typingLog.pendingCount, 0)
        answers.loggable = true
        type("dog ")
        hideKeyboard()
        XCTAssertEqual(try storedRecords().map { $0.typed }, ["cat dog"])

        // The person asks for the export.
        makeController(before: "")
        type("teh ")
        answers.loggable = false
        XCTAssertEqual(typingLog.export(field: document.documentIdentifier).records, 0)
        XCTAssertEqual(store.records, [])
    }

    func testTheRecordsOfTheFieldBeforeGoToTheStoreWhenTheNextFieldIsSecure() throws {
        makeController(before: "")
        type("teh ")
        // The person moves to a password field.
        document.documentIdentifier = UUID()
        answers.loggable = false
        controller.documentDidChange()
        XCTAssertEqual(try storedRecords().map { $0.typed }, ["teh"])
        XCTAssertEqual(typingLog.pendingCount, 0)
    }

    func testTheRecordsGoToTheStoreWhenTheKeyboardMovesToAnotherField() throws {
        makeController(before: "")
        type("teh ")
        controller.documentDidChange()
        // The same field: the record still waits.
        XCTAssertEqual(store.records, [])
        XCTAssertEqual(typingLog.pendingCount, 1)
        document.documentIdentifier = UUID()
        controller.documentDidChange()
        XCTAssertEqual(try storedRecords().map { $0.typed }, ["teh"])
        XCTAssertEqual(typingLog.pendingCount, 0)
    }

    func testTheLogMayRecordOnlyInAnOpenFieldForProse() {
        func allows(
            secure: Bool? = false, content: UITextContentType? = nil, keyboard: UIKeyboardType? = .default
        ) -> Bool {
            TypingLogPolicy.allowsLog(isSecureTextEntry: secure, textContentType: content, keyboardType: keyboard)
        }
        XCTAssertTrue(allows())
        XCTAssertTrue(allows(keyboard: .asciiCapable))
        XCTAssertTrue(allows(keyboard: .twitter))
        XCTAssertFalse(allows(secure: true))
        // A field that does not say whether it is secure counts as secure.
        XCTAssertFalse(allows(secure: nil))
        let contentTypes: [UITextContentType] = [
            .password, .newPassword, .oneTimeCode, .username, .emailAddress, .telephoneNumber, .creditCardNumber, .name,
        ]
        for content in contentTypes {
            XCTAssertFalse(allows(content: content), content.rawValue)
        }
        let keyboardTypes: [UIKeyboardType] = [
            .URL, .emailAddress, .numberPad, .phonePad, .namePhonePad, .decimalPad, .asciiCapableNumberPad,
            .numbersAndPunctuation, .webSearch,
        ]
        for keyboard in keyboardTypes {
            XCTAssertFalse(allows(keyboard: keyboard), "\(keyboard.rawValue)")
        }
        XCTAssertFalse(allows(keyboard: nil))
    }

    // MARK: Limits

    func testTheLimitDropsTheOldestRecord() throws {
        makeController(before: "", recordLimit: 3)
        type("one two three ")
        hideKeyboard()
        XCTAssertEqual(try storedRecords().map { $0.typed }, ["one", "one two", "two three"])
        type("four five ")
        hideKeyboard()
        XCTAssertEqual(try storedRecords().map { $0.typed }, ["two three", "three four", "four five"])

        // The records that wait in memory have the same limit.
        makeController(before: "", recordLimit: 3)
        type("one two three four five ")
        XCTAssertEqual(typingLog.pendingCount, 3)
        hideKeyboard()
        XCTAssertEqual(try storedRecords().map { $0.typed }, ["two three", "three four", "four five"])
    }

    func testTheExportHoldsTheNewestRecordsThatFitItsLimit() throws {
        makeController(before: "")
        type("one two three ")
        hideKeyboard()
        let lines = store.records
        XCTAssertEqual(lines.count, 3)
        func export(limit: Int) throws -> (header: TypingLogHeader, lines: [String]) {
            let text = TypingLog(store: store, exportCharacterLimit: limit).export(field: UUID()).text
            let all = text.split(separator: "\n").map(String.init)
            let header = try JSONDecoder().decode(TypingLogHeader.self, from: Data(try XCTUnwrap(all.first).utf8))
            return (header, Array(all.dropFirst()))
        }
        // Each record line counts with its line break.
        let newest = try export(limit: lines[2].count + 1)
        XCTAssertEqual(newest.lines, [lines[2]])
        XCTAssertEqual(newest.header.records, 1)
        XCTAssertEqual(newest.header.stored, 3)
        let two = try export(limit: lines[1].count + lines[2].count + 2)
        XCTAssertEqual(two.lines, [lines[1], lines[2]])
        XCTAssertEqual(try export(limit: lines[2].count).lines, [])
        let all = try export(limit: TypingLog.standardExportCharacterLimit)
        XCTAssertEqual(all.lines, lines)
        XCTAssertEqual(all.header.records, 3)
    }

    // MARK: Export and erasure

    func testTheExportCommandTypesTheExportAndTheClearCommandEmptiesTheStore() throws {
        makeController(before: "")
        type("teh cat ")
        type("duo:logexport ")
        XCTAssertEqual(keyboardView.spaceCaption, "Typing log: 2 records typed")
        // The export first moves the records to the store.
        XCTAssertEqual(store.records.count, 2)
        XCTAssertTrue(document.text.hasPrefix("the cat {"), document.text)
        XCTAssertTrue(document.text.hasSuffix("}\n"), document.text)
        let exported = String(document.text.dropFirst("the cat ".count))
        let lines = exported.split(separator: "\n").map(String.init)
        XCTAssertEqual(lines.count, 3)
        let header = try JSONDecoder().decode(TypingLogHeader.self, from: Data(try XCTUnwrap(lines.first).utf8))
        XCTAssertEqual(header, TypingLogHeader(
            file: TypingLog.exportTitle, records: 2, stored: 2, samplingProbability: TypingLog.samplingProbability))
        XCTAssertEqual(Array(lines.dropFirst()), store.records)
        // The word "duo" of the command is not a record.
        XCTAssertEqual(try decoded(Array(lines.dropFirst())).map { $0.typed }, ["teh", "teh cat"])

        type("duo:logclear ")
        XCTAssertEqual(keyboardView.spaceCaption, "Typing log erased")
        XCTAssertEqual(document.text, "the cat " + exported)
        XCTAssertEqual(store.records, [])
        XCTAssertEqual(typingLog.pendingCount, 0)
        XCTAssertEqual(typingLog.export(field: document.documentIdentifier).records, 0)
        // The commands leave the switch as it was.
        XCTAssertTrue(typingLog.isOn)
        XCTAssertEqual(store.switchWrites, 0)
    }

    func testTheClearCommandAlsoErasesTheRecordsThatWaitInMemory() {
        makeController(before: "")
        type("teh ")
        XCTAssertEqual(typingLog.pendingCount, 1)
        type("duo:logclear ")
        XCTAssertEqual(document.text, "the ")
        XCTAssertEqual(typingLog.pendingCount, 0)
        hideKeyboard()
        XCTAssertEqual(store.records, [])
    }

    func testAStoreThatDoesNotWriteIsNamedOnTheSpaceBarAndTheRecordsStay() throws {
        makeController(before: "")
        store.failsWrites = true
        type("cat ")
        hideKeyboard()
        XCTAssertEqual(store.writeAttempts, 1)
        XCTAssertEqual(store.records, [])
        XCTAssertEqual(typingLog.pendingCount, 1)
        // The notice of the problem comes after the notice of a command, as a model error does.
        RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        XCTAssertTrue(
            keyboardView.spaceCaption?.hasPrefix("Typing log: the records were not saved") ?? false,
            String(describing: keyboardView.spaceCaption))
        // The export still holds the record, and the next save stores it.
        XCTAssertEqual(typingLog.export(field: document.documentIdentifier).records, 1)
        store.failsWrites = false
        hideKeyboard()
        XCTAssertEqual(try storedRecords().map { $0.typed }, ["cat"])
        XCTAssertEqual(typingLog.pendingCount, 0)
    }

    func testAProblemOfTheLogIsNamedOnTheSpaceBar() {
        makeController(before: "")
        typingLog.onProblem("the store is full")
        XCTAssertEqual(keyboardView.spaceCaption, "Typing log: the store is full")
    }

    func testTheKeyboardThatLeavesTheScreenAsksTheStoreToWriteOnce() {
        makeController(before: "")
        store.failsWrites = true
        type("cat ")
        XCTAssertEqual(store.writeAttempts, 0)
        XCTAssertNil(keyboardView.spaceCaption)
        hideKeyboard()
        XCTAssertEqual(store.writeAttempts, 1)
        XCTAssertEqual(keyboardView.spaceCaption, "Typing log: the records were not saved: \(FakeTypingLogStore.Failure().localizedDescription)")
    }

    func testTheFileStoreKeepsTheSwitchAndTheRecords() throws {
        let suite = "TypingLogFileStoreTests"
        UserDefaults().removePersistentDomain(forName: suite)
        defer { UserDefaults().removePersistentDomain(forName: suite) }
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("TypingLogTests-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: folder) }
        let fileURL = folder.appendingPathComponent(FileTypingLogStore.fileName)
        let settings = try XCTUnwrap(UserDefaults(suiteName: suite))

        let fileStore = FileTypingLogStore(settings: settings, fileURL: fileURL)
        // A new install: the log is off, and the file does not exist.
        XCTAssertFalse(fileStore.isOn)
        XCTAssertEqual(try fileStore.readRecords(), [])
        try fileStore.removeRecords()
        fileStore.isOn = true
        let lines = ["{\"typed\":\"teh\"}", "{\"context\":\"two\\nlines \",\"typed\":\"cat\"}"]
        try fileStore.writeRecords(lines)

        let again = FileTypingLogStore(settings: settings, fileURL: fileURL)
        XCTAssertTrue(again.isOn)
        XCTAssertEqual(try again.readRecords(), lines)
        // A backup of the phone does not take the file.
        let values = try URL(fileURLWithPath: fileURL.path).resourceValues(forKeys: [.isExcludedFromBackupKey])
        XCTAssertEqual(values.isExcludedFromBackup, true)
        try again.writeRecords([lines[1]])
        XCTAssertEqual(try again.readRecords(), [lines[1]])
        try again.removeRecords()
        XCTAssertEqual(try again.readRecords(), [])
        XCTAssertFalse(FileManager.default.fileExists(atPath: fileURL.path))
    }

    // MARK: Backspace and revert

    func testARevertOfTheCorrectionMarksTheRecord() throws {
        makeController(before: "I saw ")
        type("teh ")
        pressBackspace()
        XCTAssertEqual(document.text, "I saw teh")
        hideKeyboard()
        XCTAssertEqual(try storedRecords(), [expectedRecord(context: "I saw ", typed: "teh", shown: "the", reverted: true)])
    }

    func testABackspaceIntoTheTypedWordAfterARevertMarksTheRecordToo() throws {
        makeController(before: "I saw ")
        type("teh ")
        pressBackspace(times: 2)
        XCTAssertEqual(document.text, "I saw te")
        hideKeyboard()
        XCTAssertEqual(try storedRecords(), [
            expectedRecord(context: "I saw ", typed: "teh", shown: "the", backspaced: true, reverted: true),
        ])
    }

    func testABackspaceIntoALoggedWordMarksTheRecord() throws {
        makeController(before: "I saw ")
        type("cat ")
        pressBackspace(times: 2)
        XCTAssertEqual(document.text, "I saw ca")
        hideKeyboard()
        XCTAssertEqual(try storedRecords(), [expectedRecord(context: "I saw ", typed: "cat", backspaced: true)])
    }

    func testABackspaceThatOnlyDeletesTheSpaceDoesNotMarkTheRecord() throws {
        makeController(before: "I saw ")
        type("cat ")
        pressBackspace()
        XCTAssertEqual(document.text, "I saw cat")
        hideKeyboard()
        XCTAssertEqual(try storedRecords(), [expectedRecord(context: "I saw ", typed: "cat")])
    }

    func testABackspaceIntoTheWordThroughLaterLettersMarksTheRecord() throws {
        // The field holds more text than the context of a record. So the log finds the word by
        // the end of the text before the cursor.
        let before = String(repeating: "word ", count: 20)
        makeController(before: before)
        type("cat do")
        pressBackspace(times: 4)
        XCTAssertEqual(document.text, before + "ca")
        hideKeyboard()
        let records = try storedRecords()
        XCTAssertEqual(records.map { $0.typed }, ["cat"])
        XCTAssertEqual(records.map { $0.backspaced }, [true])
    }

    func testABackspaceAfterTheNextCommittedWordDoesNotMarkTheRecord() throws {
        makeController(before: "")
        type("cat ")
        // The next word is not sampled.
        answers.random = 1
        type("dog ")
        // The last of the six backspaces deletes the "t" of "cat".
        pressBackspace(times: 6)
        XCTAssertEqual(document.text, "ca")
        hideKeyboard()
        XCTAssertEqual(try storedRecords(), [expectedRecord(context: "", typed: "cat")])
    }

    // MARK: The other commands

    func testTheLanguageModelTestIsUnchangedWithTheLogOn() async {
        makeController(before: "")
        let measurer = FakeLanguageModelMeasurer()
        controller.languageModelMeasurer = measurer
        type("duo:lm ")
        await controller.languageModelTask?.value
        XCTAssertEqual(measurer.runs, 1)
        XCTAssertEqual(document.text, "duo:lm \nmodel       fake\ndone        every step ran")
        XCTAssertNil(controller.languageModelTask)
        XCTAssertTrue(typingLog.isOn)
        hideKeyboard()
        XCTAssertEqual(store.records, [])
    }

    func testTheWorkAreaCommandIsUnchangedWithTheLogOn() throws {
        let storeName = "TypingLogTests"
        UserDefaults().removePersistentDomain(forName: storeName)
        defer { UserDefaults().removePersistentDomain(forName: storeName) }
        let checker = EngineSpellChecker(
            engine: EnglishTypingEngine(lexicon: TypingLexicon(resource: "lexicon-english", fullCheck: false)),
            reranker: nil, store: try XCTUnwrap(UserDefaults(suiteName: storeName)), workArea: .aiAndSoftware())
        makeController(before: "", spellChecker: checker)
        document.autocapitalizationType = .sentences
        type("duo:work ")
        XCTAssertEqual(document.text, "")
        XCTAssertFalse(checker.workAreaIsOn)
        XCTAssertNil(checker.preferredCapitals)
        type("the pytorch ")
        XCTAssertEqual(document.text, "the porch ")
        XCTAssertTrue(typingLog.isOn)
        hideKeyboard()
        // The log holds the two words and their readings by the engine alone.
        let records = try storedRecords()
        XCTAssertEqual(records.map { $0.typed }, ["the", "the pytorch"])
        XCTAssertEqual(records.map { $0.shown }, ["the", "the porch"])
        XCTAssertEqual(records.map { $0.changed }, [false, true])
        let last = try XCTUnwrap(records.last)
        XCTAssertEqual(last.readings[try XCTUnwrap(last.engineChoice)].text, "the porch")
        XCTAssertEqual(last.readings[try XCTUnwrap(last.asTyped)].text, "the pytorch")
        XCTAssertNil(last.modelChoice)
        XCTAssertTrue(last.readings.allSatisfy { $0.model == nil })
    }
}
