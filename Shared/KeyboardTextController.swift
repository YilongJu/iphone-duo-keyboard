import UIKit

/// The text field that the keyboard types into. The keyboard extension wraps the system's
/// `UITextDocumentProxy`, and the host app's test field wraps a `UITextView`.
@MainActor
protocol KeyboardDocument: AnyObject {
    var textBeforeCursor: String { get }
    var textAfterCursor: String { get }
    /// The text the user selected in the app, or nil when the cursor is a plain insertion point.
    var selectedText: String? { get }
    var autocapitalizationType: UITextAutocapitalizationType { get }
    /// False in the keyboard extension while the user has Full Access turned off.
    var canUseClipboard: Bool { get }
    /// Identifies the text field. The value changes when the user moves to another field.
    var documentIdentifier: UUID { get }
    /// False for a field that asks for no autocorrection, such as a web address field.
    var allowsAutocorrection: Bool { get }
    func insertText(_ text: String)
    func deleteBackward()
    /// Moves the cursor. The offset counts UTF-16 units.
    func moveCursor(byUTF16Offset offset: Int)
}

/// Finds the text a person most likely meant for the text they typed.
@MainActor
protocol SpellChecking: AnyObject {
    /// Returns the text the person most likely meant. The result equals `typed` when the checker
    /// reads the text as typed, and it is nil when the checker cannot read the text at all.
    /// `typed` holds one word, or two words with one space between them, in lower case.
    /// A word may hold one symbol or digit key, as `KeyboardTextLogic.correctableWord` allows.
    /// `previousWord` is the lower-case word before `typed`, or an empty string. `textBefore` is
    /// the field's text right before the typed text, as the field holds it. The language model
    /// reads it as the context of the readings.
    func reading(previousWord: String, typed: String, textBefore: String) -> String?
    /// Stops the keyboard from changing this word again.
    func learn(_ word: String)
    /// True for a word the person brought back after a correction.
    func keeps(_ word: String) -> Bool
    /// The preferred capitals of the work area that is on, or nil without one.
    var preferredCapitals: PreferredCapitals? { get }
    /// Turns the work area on or off, and returns a short text that names the new state. The
    /// result is nil for a checker without a work area.
    func toggleWorkArea() -> String?
    /// The readings behind the last result of `reading`, for the typing log. The value is nil
    /// when the checker could not read the text. A checker that does not keep the readings also
    /// gives nil.
    var lastReadingDetail: ReadingDetail? { get }
}

extension SpellChecking {
    var preferredCapitals: PreferredCapitals? { nil }
    func toggleWorkArea() -> String? { nil }
    var lastReadingDetail: ReadingDetail? { nil }
}

/// A work area: the words of one field of work that the keyboard reads beside its lexicon, with
/// their preferred capitals. scripts/domain-pack/build_pack.py builds both files from public text
/// of the field, and docs/domain-pack-design.md describes them.
struct WorkArea {
    /// The name on the space bar when the person turns the area on or off.
    let title: String
    /// The words of the area as a supplement of the English lexicon (`duo_lexicon_set_supplement`).
    let supplement: TypingLexicon
    let capitals: PreferredCapitals

    /// The area "AI and software" of the app bundle.
    static func aiAndSoftware() -> WorkArea {
        WorkArea(
            title: "AI and software",
            supplement: TypingLexicon(resource: "supplement-ai-software", fullCheck: false),
            capitals: PreferredCapitals.bundled(resource: "supplement-ai-software"))
    }
}

/// English correction from the typing engine in Engine/duo_engine.c. The engine reads a
/// wrong neighbor key, also when that key is a symbol or a digit, a missing, extra or doubled
/// letter, swapped letters, and slips around the space bar, and it weighs each reading by how
/// common its words are. A language model then re-ranks the engine's best readings with the
/// text before them.
@MainActor
final class EngineSpellChecker: SpellChecking {
    private static let keptWordsKey = "englishKeptWords"
    /// True in the store after the person turned the work area off.
    private static let workAreaOffKey = "workAreaOff"
    private let engine: EnglishTypingEngine
    /// The work area of this checker, or nil. The engine reads its words while the area is on.
    private let workArea: WorkArea?
    private(set) var workAreaIsOn: Bool
    /// Re-ranks the engine's readings. Without it the engine's own choice stays.
    let reranker: EnglishReranker?
    /// Words the person brought back after a correction, kept across keyboard launches.
    private var keptWords: Set<String>
    /// The store of the kept words. A test passes a store of its own, so the words it brings
    /// back do not reach the keyboard or another test.
    private let store: UserDefaults
    /// The typing log reads the readings of the last result here. The corrections do not use it.
    private(set) var lastReadingDetail: ReadingDetail?

    /// With a work area, the checker lays the area's supplement over the engine's lexicon, unless
    /// the store says that the person turned the area off. The checker then owns the engine's
    /// supplement, so another checker must not share that engine.
    init(engine: EnglishTypingEngine, reranker: EnglishReranker?, store: UserDefaults, workArea: WorkArea? = nil) {
        self.engine = engine
        self.reranker = reranker
        self.store = store
        self.workArea = workArea
        // A phone on which nobody has brought a word back yet does not have the stored list.
        keptWords = Set(store.stringArray(forKey: Self.keptWordsKey) ?? [])
        // A store without the value gives false, so the area is on until the person turns it off.
        workAreaIsOn = workArea != nil && !store.bool(forKey: Self.workAreaOffKey)
        if let workArea {
            engine.setSupplement(workAreaIsOn ? workArea.supplement : nil)
        }
    }

    /// The engine with the English lexicon and the work area "AI and software" of the app bundle.
    static func bundled(reranker: EnglishReranker?) -> EngineSpellChecker {
        EngineSpellChecker(
            engine: EnglishTypingEngine(lexicon: TypingLexicon(resource: "lexicon-english", fullCheck: false)),
            reranker: reranker, store: .standard, workArea: .aiAndSoftware())
    }

    var preferredCapitals: PreferredCapitals? {
        workAreaIsOn ? workArea?.capitals : nil
    }

    func toggleWorkArea() -> String? {
        guard let workArea else { return nil }
        workAreaIsOn.toggle()
        store.set(!workAreaIsOn, forKey: Self.workAreaOffKey)
        engine.setSupplement(workAreaIsOn ? workArea.supplement : nil)
        return "\(workArea.title) words \(workAreaIsOn ? "on" : "off")"
    }

    func reading(previousWord: String, typed: String, textBefore: String) -> String? {
        lastReadingDetail = nil
        guard let readings = engine.readings(
            previousWord: previousWord, typed: typed, limit: EnglishReranker.readingCount)
        else { return nil }
        guard let reranker else {
            lastReadingDetail = ReadingDetail(readings: readings, trace: nil)
            // EnglishTypingEngine.readings holds exactly one chosen reading.
            return readings.first { $0.chosen }!.text
        }
        // The model may not change a typed word that is new in the work area.
        let candidates = preferredCapitals?.keepingNewWords(readings, typed: typed) ?? readings
        let text = reranker.choose(readings: candidates, textBefore: textBefore, typed: typed)
        lastReadingDetail = ReadingDetail(readings: candidates, trace: reranker.lastTrace)
        return text
    }

    func learn(_ word: String) {
        guard keptWords.insert(word.lowercased()).inserted else { return }
        store.set(Array(keptWords), forKey: Self.keptWordsKey)
    }

    func keeps(_ word: String) -> Bool {
        keptWords.contains(word.lowercased())
    }
}

/// Turns the keys' actions into edits of the document. The keyboard extension and the host app's
/// test field share this class, so both type by the same rules.
///
/// Select all works inside the keyboard only. iOS does not let a keyboard set a selection in the
/// app, so the select-all key stores the text around the cursor as "all text". The next cut, copy,
/// delete or typed character then acts on that text. The app itself does not draw a highlight.
@MainActor
final class KeyboardTextController: NSObject, KeyboardViewDelegate {
    private let keyboardView: KeyboardView
    private let document: KeyboardDocument
    private let spellChecker: SpellChecking

    /// The last autocorrection. One backspace right after the correction brings the typed word back.
    private struct Correction {
        let original: String
        let corrected: String
        let terminator: String
    }

    private var lastCorrection: Correction?

    /// The word typed right before the current one, when one space followed it. `typed` holds
    /// the keys the person pressed and `shown` the text the field holds after any correction.
    /// The typing engine reads the two last words together, which lets it repair a slip around
    /// the space bar, such as "th e" for "the".
    private struct RecentWord {
        let typed: String
        let shown: String
        /// The end of the text before the cursor right after the word and its space. The next
        /// word is read together with this word only when the person typed it right here.
        let context: String
    }

    /// Count of characters that `RecentWord.context` holds.
    private static let recentContextLength = 48

    private var recentWord: RecentWord?

    /// The owner hides the keyboard here.
    var onDismiss: @MainActor () -> Void = {}

    private static let languageKey = "typesChinese"
    private var remembersLanguage = false

    /// Opens the keyboard in the language it typed last, and stores each later switch. iOS
    /// starts the keyboard anew each time it appears, so without this call the keyboard would
    /// open in English every time.
    func rememberLanguage() {
        remembersLanguage = true
        // A phone that never switched the language does not have the stored value, and the
        // keyboard then opens in English.
        guard UserDefaults.standard.bool(forKey: Self.languageKey), !chineseMode else { return }
        chineseMode = true
        keyboardView.chineseActive = true
        refreshCaption()
    }

    /// Reads each finished sentence, and the sentence that the person is still writing when they
    /// pause, and proposes a fix. Without a proofreader the keyboard does not propose anything.
    var proofreader: SentenceProofreading?

    /// A fix that the proofreader proposed for the sentence right before the cursor. The
    /// candidate row shows the fix, and a tap on it replaces the sentence.
    struct ProofreadSuggestion: Equatable {
        let original: String
        let corrected: String
    }

    private(set) var proofreadSuggestion: ProofreadSuggestion?
    /// The request that is running now. The tests wait for it.
    private(set) var proofreadTask: Task<Void, Never>?
    /// The sentence of the latest request, so one sentence is read once.
    private var proofreadSentence: String?
    /// The reasons for a missing answer that the space bar has shown already.
    private var shownProofreadNotes: Set<String> = []
    /// Seconds without a key press before the keyboard reads the sentence that the person is
    /// still writing. A sentence that ends in a mark is read at once.
    var proofreadPauseSeconds: Double = 1.0
    /// The wait for a pause in the typing. Each key press starts it again. The tests wait for it.
    private(set) var pauseTask: Task<Void, Never>?

    /// The text that starts the language model test when a space follows it.
    static let languageModelTrigger = "duo:lm"

    /// The text that turns the work area on or off when a space follows it.
    static let workAreaTrigger = "duo:work"

    /// The text that turns the typing log on or off when a space follows it.
    static let typingLogTrigger = "duo:log"
    /// The text that types the export of the typing log into the field when a space follows it.
    static let typingLogExportTrigger = "duo:logexport"
    /// The text that erases the typing log when a space follows it.
    static let typingLogClearTrigger = "duo:logclear"

    /// Records a random sample of the committed words while the person has the log turned on
    /// (docs/typing-log-design.md). Without a log the keyboard types the three trigger texts as
    /// any other text. The keyboard then does not record a word.
    var typingLog: TypingLog? {
        didSet {
            typingLog?.onProblem = { [weak self] reason in
                // The notice goes to the space bar at once, so it does not depend on a later
                // turn of the main queue. A command that meets a problem shows its own notice
                // right after this one.
                self?.showNotice("Typing log: \(reason)")
            }
        }
    }

    /// Runs the language model test. Without a measurer the trigger text is typed as any
    /// other text, and the test does not load a model.
    var languageModelMeasurer: LanguageModelMeasuring?
    /// The run of the test that is under way now. The tests wait for it.
    private(set) var languageModelTask: Task<Void, Never>?

    /// Loads the language model of the English corrections. The controller asks for a load
    /// when the keyboard appears in English and when the person switches to English, so
    /// Chinese typing never loads the model.
    var languageModelLoader: LanguageModelLoading?

    /// A short text that stays on the space bar while the keyboard types English, such as the
    /// words that the language model did not load. A notice and select all still come first.
    private var englishCaption: String?

    private var previousInsertWasSpace = false
    private var lastSpaceTime: TimeInterval = 0
    private var notice: String?

    /// The document's text at the moment the user pressed select all.
    private struct AllText: Equatable {
        let before: String
        let after: String
        var text: String { before + after }
    }

    private var allText: AllText?

    /// A replacement of all text that waits for the document to confirm a cursor move.
    private struct PendingReplacement {
        let snapshot: AllText
        /// Text that goes in as it is after the delete, such as pasted text.
        var rawInsert: String?
        /// Typed characters that wait for the delete. They then take the normal typing path, so
        /// a Pinyin letter reaches the Pinyin buffer and an English word gets autocorrection.
        var typed: [String]
        let documentIdentifier: UUID
        var attempts = 0
    }

    private var pending: PendingReplacement?

    /// True while the keyboard types Simplified Chinese through Pinyin.
    private(set) var chineseMode = false
    /// The Pinyin letters typed so far that are not Chinese text yet.
    private(set) var pinyinBuffer = ""
    private var pinyinCandidates: [PinyinCandidate] = []
    /// The candidates picked since the buffer was last empty.
    private var sessionPicks: [PinyinCandidate] = []
    /// True after an opening quotation mark, so the next one closes.
    private var doubleQuoteIsOpen = false
    private var singleQuoteIsOpen = false
    private let makePinyinEngine: @MainActor () -> PinyinEngine
    /// The dictionary loads on the first switch to Chinese, so English typing does not pay for the load.
    private lazy var pinyinEngine: PinyinEngine = makePinyinEngine()

    /// Chinese forms of the punctuation keys.
    private static let chinesePunctuation: [String: String] = [
        ",": "\u{FF0C}", ".": "\u{3002}", "?": "\u{FF1F}", "!": "\u{FF01}", ":": "\u{FF1A}",
        ";": "\u{FF1B}", "(": "\u{FF08}", ")": "\u{FF09}", "<": "\u{300A}", ">": "\u{300B}", "\\": "\u{3001}",
    ]

    init(
        keyboardView: KeyboardView, document: KeyboardDocument, spellChecker: SpellChecking,
        pinyinEngine: @escaping @MainActor () -> PinyinEngine
    ) {
        self.keyboardView = keyboardView
        self.document = document
        self.spellChecker = spellChecker
        self.makePinyinEngine = pinyinEngine
        super.init()
        keyboardView.delegate = self
        // A tap on the typed Pinyin letters types them as plain letters.
        keyboardView.onSelectComposition = { [weak self] in
            self?.commitPinyinLetters()
        }
    }

    /// The owner calls this when the app's text or cursor changed.
    func documentDidChange() {
        if let allText, allText != currentText() {
            setAllText(nil)
        }
        updateAutoShift()
        // Typing log: the sampled words of another field go to the store. A field that may not
        // be logged loses its sampled words.
        typingLog?.fieldChanged(to: document.documentIdentifier)
    }

    // MARK: State shown on the keyboard

    private func updateAutoShift() {
        // Pinyin letters are lower case, so Chinese typing does not use automatic capitals.
        let capitalize = !chineseMode && KeyboardTextLogic.shouldAutoCapitalize(
            before: document.textBeforeCursor, type: document.autocapitalizationType)
        keyboardView.setAutomaticShift(capitalize)
    }

    private func refreshCaption() {
        keyboardView.selectAllActive = allText != nil
        keyboardView.spaceCaption = notice
            ?? (allText != nil ? "All text selected" : (chineseMode ? "\u{62FC}\u{97F3}" : englishCaption))
    }

    /// The owner calls this when the keyboard appears.
    func keyboardWillAppear() {
        if !chineseMode { languageModelLoader?.loadInBackground() }
    }

    /// Names a change of the language model on the space bar. A model that did not load also
    /// leaves a caption that stays until a later load works.
    func show(_ event: LanguageModelEvent) {
        switch event {
        case .ready:
            englishCaption = nil
            refreshCaption()
        case .loadFailed(let reason):
            englishCaption = "No language model"
            showNotice("Language model did not load: \(reason)")
        case .freed(let reason):
            showNotice("Language model freed: \(reason)")
        case .modelError(let reason):
            // The error comes in the middle of a correction, which shows its own notice right
            // after. The error's notice waits for that one, so the correction does not hide it.
            Task { @MainActor [weak self] in
                self?.showNotice("Language model error: \(reason)")
            }
        }
    }

    /// Shows a short message on the space bar for 2.5 seconds.
    private func showNotice(_ text: String) {
        notice = text
        refreshCaption()
        NSObject.cancelPreviousPerformRequests(withTarget: self, selector: #selector(clearNotice), object: nil)
        perform(#selector(clearNotice), with: nil, afterDelay: 2.5)
    }

    @objc private func clearNotice() {
        notice = nil
        refreshCaption()
    }

    // MARK: All text

    private func currentText() -> AllText {
        AllText(before: document.textBeforeCursor, after: document.textAfterCursor)
    }

    private func setAllText(_ value: AllText?) {
        allText = value
        refreshCaption()
    }

    /// Returns the stored text only when the document still holds exactly that text around the
    /// cursor. A document that changed since then clears the stored text.
    private func confirmedAllText() -> AllText? {
        guard let allText else { return nil }
        if allText == currentText(), document.selectedText == nil {
            return allText
        }
        setAllText(nil)
        return nil
    }

    /// Deletes the stored text. After the delete, `rawInsert` goes in as it is, and `typed`
    /// goes through the normal typing path.
    /// The caller passes a snapshot that `confirmedAllText()` just returned.
    private func replaceAllText(_ snapshot: AllText, typed: String? = nil, rawInsert: String? = nil) {
        setAllText(nil)
        previousInsertWasSpace = false
        recentWord = nil
        let typedCharacters = typed.map { [$0] } ?? []
        guard !snapshot.after.isEmpty else {
            // The cursor is at the end of the text, so the delete needs no cursor move.
            deleteBackward(count: snapshot.before.count)
            finishReplacement(typed: typedCharacters, rawInsert: rawInsert)
            return
        }
        // A keyboard can delete backward only. The cursor moves to the end of the text first.
        // The delete waits for the document to confirm the cursor's new place, so a move that
        // did not happen as expected does not delete any text.
        document.moveCursor(byUTF16Offset: snapshot.after.utf16.count)
        pending = PendingReplacement(
            snapshot: snapshot, rawInsert: rawInsert, typed: typedCharacters,
            documentIdentifier: document.documentIdentifier)
        scheduleReplacementCheck()
    }

    private func scheduleReplacementCheck() {
        perform(#selector(finishPendingReplacement), with: nil, afterDelay: 0.08, inModes: [.common])
    }

    @objc private func finishPendingReplacement() {
        guard var replacement = pending else { return }
        let after = replacement.snapshot.after
        let sameDocument = document.documentIdentifier == replacement.documentIdentifier
        if sameDocument, document.selectedText == nil, document.textBeforeCursor.hasSuffix(after) {
            pending = nil
            deleteBackward(count: after.count + replacement.snapshot.before.count)
            finishReplacement(typed: replacement.typed, rawInsert: replacement.rawInsert)
        } else if sameDocument, replacement.attempts < 5 {
            // The document reports a cursor move with a delay, so the check runs again.
            replacement.attempts += 1
            pending = replacement
            scheduleReplacementCheck()
        } else {
            // The cursor's place stayed unconfirmed. The text stays as it is, and the typed
            // text that waited for the replacement is dropped.
            pending = nil
            showNotice("Select all did not finish")
            updateAutoShift()
        }
    }

    /// Stops a replacement that still waits for its cursor move. The owner calls this when the
    /// keyboard leaves the screen.
    func cancelPendingEdits() {
        NSObject.cancelPreviousPerformRequests(
            withTarget: self, selector: #selector(finishPendingReplacement), object: nil)
        pending = nil
        setAllText(nil)
        commitPinyinLetters()
        // Typing log: the keyboard leaves the screen, so the sampled words go to the store.
        typingLog?.keyboardWillHide(field: document.documentIdentifier)
    }

    // MARK: Proofreading of a sentence

    /// Starts a request when a sentence has just ended right before the cursor.
    private func proofreadFinishedSentence() {
        proofread(KeyboardTextLogic.finishedSentence(before: document.textBeforeCursor))
    }

    /// Waits for a pause in the typing, then reads the sentence that the person is still
    /// writing. Each key press calls this, so the wait starts again with every key.
    private func proofreadAfterAPause() {
        pauseTask?.cancel()
        guard proofreader != nil else { return }
        let seconds = proofreadPauseSeconds
        pauseTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
            guard let self, !Task.isCancelled else { return }
            self.proofread(KeyboardTextLogic.unfinishedSentence(before: self.document.textBeforeCursor))
        }
    }

    private func proofread(_ found: String?) {
        guard let proofreader, pinyinBuffer.isEmpty, pending == nil,
            let sentence = found, sentence != proofreadSentence
        else { return }
        proofreadSentence = sentence
        proofreadTask?.cancel()
        proofreadTask = Task { [weak self] in
            let result = await proofreader.proofread(sentence)
            guard let self, !Task.isCancelled else { return }
            self.showProofreading(result, of: sentence)
        }
    }

    private func showProofreading(_ result: ProofreadResult, of sentence: String) {
        // The space bar names each remark once, so a device without a model stays quiet.
        if let note = result.note, shownProofreadNotes.insert(note).inserted {
            showNotice("Proofreader: \(note)")
        }
        guard let answer = result.text else { return }
        // The person may have typed on while the model read the sentence. The fix is shown only
        // while the same sentence still ends right before the cursor.
        guard pinyinBuffer.isEmpty,
            KeyboardTextLogic.sentenceToProofread(before: document.textBeforeCursor) == sentence,
            let corrected = KeyboardTextLogic.acceptedProofreading(of: sentence, answer: answer)
        else { return }
        // In Chinese text a typing slip gives a character with the same sound, so a fix may
        // only put a character with the same sound in its place.
        let holdsChinese = sentence.unicodeScalars.contains { $0.value >= 0x4E00 && $0.value <= 0x9FFF }
        if holdsChinese, !pinyinEngine.keepsTheSounds(from: sentence, to: corrected) { return }
        proofreadSuggestion = ProofreadSuggestion(original: sentence, corrected: corrected)
        // A cloud marks the model on Apple's servers and a star the model on the device. The
        // number is the time the model took.
        let mark = result.source == "cloud" ? "\u{2601}\u{FE0E}" : "\u{2726}"
        keyboardView.showCandidates(composition: String(format: "%@ %.1f s", mark, result.seconds), words: [corrected])
    }

    /// Replaces the sentence right before the cursor with the proposed fix.
    private func applyProofreadSuggestion() {
        guard let suggestion = proofreadSuggestion else { return }
        clearProofreadSuggestion()
        let before = document.textBeforeCursor
        let spaces = before.reversed().prefix(while: { $0 == " " }).count
        guard before.dropLast(spaces).hasSuffix(suggestion.original) else { return }
        deleteBackward(count: suggestion.original.count + spaces)
        document.insertText(suggestion.corrected + String(repeating: " ", count: spaces))
        lastCorrection = nil
        recentWord = nil
        // The fixed sentence is not read again.
        proofreadSentence = suggestion.corrected
        updateAutoShift()
    }

    /// Takes the proposed fix off the candidate row. Every key press except a space calls this first.
    private func clearProofreadSuggestion() {
        guard proofreadSuggestion != nil else { return }
        proofreadSuggestion = nil
        if pinyinBuffer.isEmpty {
            keyboardView.showCandidates(composition: nil, words: [])
        }
    }

    // MARK: Language model test

    /// Starts the language model test when the trigger text stands right before the cursor
    /// as a word of its own. The keyboard then types the space and each result line on a
    /// line of its own. The test only measures, and the trigger is the only way to start it.
    /// A capital first letter also counts, because the keyboard capitalizes the start of a
    /// sentence. Returns false when the space should be typed by the normal rules.
    private func startLanguageModelTest() -> Bool {
        guard let languageModelMeasurer, languageModelTask == nil else { return false }
        let before = document.textBeforeCursor
        guard before.lowercased().hasSuffix(Self.languageModelTrigger) else { return false }
        // A letter or another sign right before the trigger makes it part of a longer text.
        if let preceding = before.dropLast(Self.languageModelTrigger.count).last, !preceding.isWhitespace {
            return false
        }
        // The trigger is a command and not a word of prose, so the space after it does not
        // start a correction, and a backspace does not bring an earlier correction back.
        lastCorrection = nil
        recentWord = nil
        previousInsertWasSpace = false
        document.insertText(" ")
        showNotice("Language model test is running")
        // The run starts here, before the task below gets its turn on the main thread.
        let lines = languageModelMeasurer.resultLines()
        languageModelTask = Task { [weak self] in
            for await line in lines {
                self?.document.insertText("\n" + line)
            }
            self?.languageModelTask = nil
            self?.updateAutoShift()
        }
        return true
    }

    // MARK: Work area

    /// Turns the work area on or off when the trigger text stands right before the cursor as a
    /// word of its own, takes the trigger text out of the field, and names the new state on the
    /// space bar. A capital first letter also counts, as for the language model test. Returns
    /// false when the space should be typed by the normal rules.
    private func toggleWorkArea() -> Bool {
        let before = document.textBeforeCursor
        guard before.lowercased().hasSuffix(Self.workAreaTrigger) else { return false }
        if let preceding = before.dropLast(Self.workAreaTrigger.count).last, !preceding.isWhitespace {
            return false
        }
        guard let state = spellChecker.toggleWorkArea() else { return false }
        lastCorrection = nil
        recentWord = nil
        previousInsertWasSpace = false
        deleteBackward(count: Self.workAreaTrigger.count)
        showNotice(state)
        return true
    }

    // MARK: Typing log

    /// True when `trigger` ends the text `before` as a word of its own. A capital first letter
    /// also counts, as for the language model test.
    private func ends(_ before: String, withCommand trigger: String) -> Bool {
        guard before.lowercased().hasSuffix(trigger) else { return false }
        if let preceding = before.dropLast(trigger.count).last, !preceding.isWhitespace {
            return false
        }
        return true
    }

    /// Runs a command of the typing log when its trigger text stands right before the cursor.
    /// The commands are the switch, the export and the erasure. The keyboard takes the trigger
    /// text out of the field and names the result on the space bar. The export goes into the
    /// field at the cursor, so the person can select and copy the text. Returns false when the
    /// space should be typed by the normal rules.
    private func runTypingLogCommand() -> Bool {
        guard let typingLog else { return false }
        // A trigger does not end in another trigger, so one text matches one command at most.
        let triggers = [Self.typingLogTrigger, Self.typingLogExportTrigger, Self.typingLogClearTrigger]
        let before = document.textBeforeCursor
        guard let trigger = triggers.first(where: { ends(before, withCommand: $0) }) else { return false }
        lastCorrection = nil
        recentWord = nil
        previousInsertWasSpace = false
        deleteBackward(count: trigger.count)
        switch trigger {
        case Self.typingLogExportTrigger:
            let export = typingLog.export(field: document.documentIdentifier)
            document.insertText(export.text)
            let count = export.records == 1 ? "1 record" : "\(export.records) records"
            showNotice("Typing log: \(count) typed")
        case Self.typingLogClearTrigger:
            typingLog.clear()
            showNotice("Typing log erased")
        default:
            showNotice(typingLog.toggle())
        }
        return true
    }

    /// Hands a committed word to the typing log. `typed` is the typed span, and `inField` is
    /// the text that the field held for the span. `shown` is the text that the field holds now.
    /// `before` is the text before the cursor when the key `terminator` came, which ends in
    /// `inField`. `askedChecker` says that the spell checker just read the span. The log
    /// does not change the field.
    private func logCommittedWord(
        typed: String, inField: String, shown: String, terminator: String, before: String, askedChecker: Bool,
        kept: Bool
    ) {
        guard let typingLog, typingLog.isOn else { return }
        typingLog.wordCommitted(
            typed: typed, inField: inField, shown: shown, terminator: terminator,
            textBefore: String(before.dropLast(inField.count)),
            detail: askedChecker ? spellChecker.lastReadingDetail : nil, kept: kept,
            field: document.documentIdentifier)
    }

    /// Tells the typing log that the backspace key deletes the character before the cursor next.
    private func logBackspace() {
        guard let typingLog, typingLog.followsAWord else { return }
        typingLog.backspace(textBefore: document.textBeforeCursor, field: document.documentIdentifier)
    }

    // MARK: Chinese

    private func refreshCandidates() {
        if pinyinBuffer.isEmpty {
            pinyinCandidates = []
            keyboardView.showCandidates(composition: nil, words: [])
        } else {
            pinyinCandidates = pinyinEngine.candidates(for: pinyinBuffer)
            keyboardView.showCandidates(
                composition: pinyinEngine.display(for: pinyinBuffer), words: pinyinCandidates.map { $0.word })
        }
    }

    /// Types the candidate at `index` and keeps the letters the candidate did not cover.
    private func selectCandidate(at index: Int) {
        guard pinyinCandidates.indices.contains(index) else { return }
        let candidate = pinyinCandidates[index]
        document.insertText(candidate.word)
        pinyinEngine.learn(spelling: candidate.spelling, word: candidate.word)
        sessionPicks.append(candidate)
        pinyinBuffer.removeFirst(candidate.consumedLetters)
        if pinyinBuffer.isEmpty {
            // Several picks in a row made one phrase. The engine learns the phrase as a whole,
            // so the same letters give that phrase as the first candidate next time.
            if sessionPicks.count > 1 {
                pinyinEngine.learn(
                    spelling: sessionPicks.map { $0.spelling }.joined(separator: " "),
                    word: sessionPicks.map { $0.word }.joined())
            }
            sessionPicks = []
        }
        refreshCandidates()
    }

    /// Types the buffered letters as plain letters and empties the buffer.
    private func commitPinyinLetters() {
        sessionPicks = []
        guard !pinyinBuffer.isEmpty else { return }
        document.insertText(pinyinBuffer)
        pinyinBuffer = ""
        refreshCandidates()
    }

    /// Handles a typed character while the keyboard types Chinese.
    /// Returns false when the character should go through the normal typing path.
    private func handleChineseInput(_ text: String) -> Bool {
        if text == "'", !pinyinBuffer.isEmpty {
            // An apostrophe between Pinyin letters forces a syllable break, as in "xi'an".
            if !pinyinBuffer.hasSuffix("'") {
                pinyinBuffer.append("'")
                refreshCandidates()
            }
            return true
        }
        if text.count == 1, let letter = text.lowercased().first, letter.isASCII, letter.isLetter {
            // The typing engine reads up to 120 letters, and a clause of 20 characters takes
            // about 60, so 80 letters cover a long clause.
            guard pinyinBuffer.count < 80 else { return true }
            pinyinBuffer.append(letter)
            refreshCandidates()
            return true
        }
        if !pinyinBuffer.isEmpty {
            if text == " " {
                if pinyinCandidates.isEmpty { commitPinyinLetters() } else { selectCandidate(at: 0) }
                return true
            }
            if text == "\n" {
                commitPinyinLetters()
                return true
            }
            if let digit = Int(text), (1...9).contains(digit) {
                selectCandidate(at: digit - 1)
                return true
            }
            // Punctuation ends the word: the best candidates go in first, then the punctuation.
            while !pinyinBuffer.isEmpty, !pinyinCandidates.isEmpty {
                selectCandidate(at: 0)
            }
            commitPinyinLetters()
        }
        if let chinese = Self.chinesePunctuation[text] {
            document.insertText(chinese)
            return true
        }
        if text == "\"" {
            document.insertText(doubleQuoteIsOpen ? "\u{201D}" : "\u{201C}")
            doubleQuoteIsOpen.toggle()
            return true
        }
        if text == "'" {
            document.insertText(singleQuoteIsOpen ? "\u{2019}" : "\u{2018}")
            singleQuoteIsOpen.toggle()
            return true
        }
        return false
    }

    private func deleteBackward(count: Int) {
        for _ in 0..<count {
            document.deleteBackward()
        }
    }

    private func finishReplacement(typed: [String], rawInsert: String?) {
        if let rawInsert {
            document.insertText(rawInsert)
        }
        for character in typed {
            typeCharacter(character)
        }
        updateAutoShift()
    }

    /// Types one character from a key: through the Pinyin buffer while the keyboard types
    /// Chinese, and through the English typing rules otherwise.
    private func typeCharacter(_ text: String) {
        if chineseMode, handleChineseInput(text) {
            updateAutoShift()
            return
        }
        insert(text)
    }

    // MARK: Typing

    private func insert(_ text: String) {
        if text == " ", startLanguageModelTest() {
            updateAutoShift()
            return
        }
        if text == " ", !chineseMode, toggleWorkArea() {
            updateAutoShift()
            return
        }
        if text == " ", !chineseMode, runTypingLogCommand() {
            updateAutoShift()
            return
        }
        let now = ProcessInfo.processInfo.systemUptime
        if text == " ", !chineseMode, previousInsertWasSpace, now - lastSpaceTime < 1.5,
            KeyboardTextLogic.shouldReplaceDoubleSpace(before: document.textBeforeCursor) {
            document.deleteBackward()
            document.insertText(". ")
            previousInsertWasSpace = false
            recentWord = nil
        } else {
            correctLastWord(beforeTyping: text)
            document.insertText(text)
            previousInsertWasSpace = text == " "
            lastSpaceTime = now
        }
        updateAutoShift()
    }

    /// Corrects the text right before the cursor, when `terminator` ends a word.
    /// The correction reads the last word, and the word before it when the person typed that
    /// word right before with one space between the two.
    private func correctLastWord(beforeTyping terminator: String) {
        lastCorrection = nil
        guard KeyboardTextLogic.wordTerminators.contains(terminator) else { return }
        let earlier = recentWord
        recentWord = nil
        guard !chineseMode, document.allowsAutocorrection else { return }
        let before = document.textBeforeCursor
        guard let word = KeyboardTextLogic.correctableWord(before: before) else {
            // A comma, period or semicolon key right after a space can be a slip for the first
            // letter of the next word, as in ";ike" for "like". The word before stays ready, so
            // the two words are still read together.
            if let earlier, terminator.count == 1, let key = terminator.first,
                KeyboardTextLogic.symbolsBesideLetters.contains(key), before.hasSuffix(earlier.context) {
                recentWord = earlier
            } else if let capitals = spellChecker.preferredCapitals,
                let cased = KeyboardTextLogic.wordWithInnerCapital(before: before), !spellChecker.keeps(cased) {
                // A word with a capital after its first letter is not read for slips. A word of
                // the work area still gets the form that its typed capitals are nearest to, as
                // "PyTorch" for "pyTorch".
                let form = capitals.form(
                    of: cased, typed: cased,
                    automaticFirst: KeyboardTextLogic.shouldAutoCapitalize(
                        before: String(before.dropLast(cased.count)), type: document.autocapitalizationType))
                if form != cased {
                    deleteBackward(count: cased.count)
                    document.insertText(form)
                    lastCorrection = Correction(original: cased, corrected: form, terminator: terminator)
                    showNotice("\(cased) \u{2192} \(form)")
                }
            }
            return
        }

        let followedBySpace = terminator == " "
        // A word the person brought back after a correction stays as typed.
        guard !keepsAsTyped(word) else {
            if followedBySpace { recentWord = RecentWord(typed: word, shown: word, context: contextAfterSpace()) }
            // Typing log: a kept word is a committed word that the keyboard did not change.
            logCommittedWord(
                typed: word, inField: word, shown: word, terminator: terminator, before: before, askedChecker: false,
                kept: true)
            return
        }
        var typedSpan = word
        var shownSpan = word
        if let earlier, !keepsAsTyped(earlier.typed), !keepsAsTyped(earlier.shown),
            before.hasSuffix(earlier.context + word),
            KeyboardTextLogic.correctableWord(before: String(before.dropLast(word.count + 1))) == earlier.shown {
            typedSpan = earlier.typed + " " + word
            shownSpan = earlier.shown + " " + word
        }
        let typedWords = typedSpan.split(separator: " ")

        let previousWord = KeyboardTextLogic.wordBeforeSpace(at: String(before.dropLast(shownSpan.count)))
        // One letter alone is a word such as "a" or "I", or a label, so the checker reads a
        // single letter only together with the word before it.
        let reading = typedSpan.count >= 2
            ? spellChecker.reading(
                previousWord: previousWord, typed: typedSpan.lowercased(),
                textBefore: String(before.dropLast(shownSpan.count))) : nil
        // A reading of two words together replaces an earlier reading of the first word alone,
        // also when it brings back the letters the person typed. Without a reading the shown
        // text stays, and only a lone "i" gets its capital.
        let restored = reading.map { KeyboardTextLogic.restoringCapitals(in: $0, from: typedSpan) }
            ?? KeyboardTextLogic.restoringCapitals(in: shownSpan, from: shownSpan)
        // A word whose first letter was typed as a symbol key gets the capital that the
        // keyboard types by itself at that place, as in "[lease" at the start of a sentence.
        let repaired = KeyboardTextLogic.capitalizingRepairedFirstLetters(
            in: restored, from: typedSpan, textBefore: String(before.dropLast(shownSpan.count)),
            type: document.autocapitalizationType)
        // A word of the work area gets the form that the typed capitals ask for: "Pytorch" and
        // "Pytorhc" become "PyTorch", and "pytorch" stays in lower case.
        let final = spellChecker.preferredCapitals?.latch(
            repaired, typed: typedSpan, textBefore: String(before.dropLast(shownSpan.count)),
            type: document.autocapitalizationType) ?? repaired
        let finalWords = final.split(separator: " ")
        if final != shownSpan {
            deleteBackward(count: shownSpan.count)
            document.insertText(final)
            lastCorrection = Correction(original: shownSpan, corrected: final, terminator: terminator)
            showNotice("\(shownSpan) \u{2192} \(final)")
        }
        // Typing log: the committed word, with or without a change.
        logCommittedWord(
            typed: typedSpan, inField: shownSpan, shown: final, terminator: terminator, before: before,
            askedChecker: typedSpan.count >= 2, kept: false)
        if followedBySpace, let last = finalWords.last {
            // After a correction that joined or split words, the last shown word counts as typed
            // that way, so the next correction does not take the same keys apart again.
            let sameCount = finalWords.count == typedWords.count
            recentWord = RecentWord(
                typed: sameCount ? word : String(last), shown: String(last), context: contextAfterSpace())
        }
    }

    /// True for a word the person brought back after a correction. A kept word also stays as
    /// typed right after a symbol key, as "teh" does in "[teh".
    private func keepsAsTyped(_ word: String) -> Bool {
        if spellChecker.keeps(word) { return true }
        guard let first = word.first, KeyboardTextLogic.symbolsBesideLetters.contains(first) else { return false }
        return spellChecker.keeps(String(word.dropFirst()))
    }

    /// The end of the text before the cursor, with the space that the keyboard types next.
    private func contextAfterSpace() -> String {
        String((document.textBeforeCursor + " ").suffix(Self.recentContextLength))
    }

    /// Brings back the text the field held before the last correction, when the cursor still
    /// sits right after the correction.
    private func undoLastCorrection() -> Bool {
        guard let correction = lastCorrection else { return false }
        lastCorrection = nil
        recentWord = nil
        let typed = correction.corrected + correction.terminator
        guard document.textBeforeCursor.hasSuffix(typed) else { return false }
        deleteBackward(count: typed.count)
        document.insertText(correction.original)
        for word in correction.original.split(separator: " ") {
            spellChecker.learn(String(word))
        }
        showNotice("Kept \(correction.original)")
        // Typing log: the person brought the typed text back.
        typingLog?.correctionReverted(
            original: correction.original, corrected: correction.corrected, field: document.documentIdentifier)
        return true
    }

    /// Converts a count of characters into the UTF-16 offset the document expects.
    /// An emoji is one character and two or more UTF-16 units.
    private func utf16Offset(forCharacters count: Int) -> Int {
        if count >= 0 {
            let passed = document.textAfterCursor.prefix(count)
            return passed.utf16.count + (count - passed.count)
        }
        let passed = document.textBeforeCursor.suffix(-count)
        return -(passed.utf16.count + (-count - passed.count))
    }

    // MARK: KeyboardViewDelegate

    func keyboardView(_ keyboardView: KeyboardView, insert text: String) {
        // A person types a space after a period out of habit, so a space keeps the fix on the
        // row. The fix then replaces the sentence and keeps the spaces after it.
        if text != " " { clearProofreadSuggestion() }
        defer {
            proofreadFinishedSentence()
            proofreadAfterAPause()
        }
        if var replacement = pending {
            // A replacement is still running. The typed character joins the ones that wait for the delete.
            replacement.typed.append(text)
            pending = replacement
            return
        }
        if let snapshot = confirmedAllText() {
            replaceAllText(snapshot, typed: text)
            return
        }
        typeCharacter(text)
    }

    func keyboardView(_ keyboardView: KeyboardView, didSelectCandidateAt index: Int) {
        defer { proofreadAfterAPause() }
        if proofreadSuggestion != nil {
            applyProofreadSuggestion()
            return
        }
        selectCandidate(at: index)
    }

    func keyboardViewDeleteBackward(_ keyboardView: KeyboardView) {
        clearProofreadSuggestion()
        defer { proofreadAfterAPause() }
        guard pending == nil else { return }
        if !pinyinBuffer.isEmpty {
            pinyinBuffer.removeLast()
            refreshCandidates()
            return
        }
        if let snapshot = confirmedAllText() {
            replaceAllText(snapshot)
            return
        }
        previousInsertWasSpace = false
        if !undoLastCorrection() {
            // Typing log: a backspace into a sampled word marks its record.
            logBackspace()
            document.deleteBackward()
        }
        recentWord = nil
        updateAutoShift()
    }

    func keyboardViewReturn(_ keyboardView: KeyboardView) {
        self.keyboardView(keyboardView, insert: "\n")
    }

    func keyboardView(_ keyboardView: KeyboardView, moveCursorBy offset: Int) {
        clearProofreadSuggestion()
        guard pending == nil else { return }
        setAllText(nil)
        commitPinyinLetters()
        previousInsertWasSpace = false
        lastCorrection = nil
        recentWord = nil
        document.moveCursor(byUTF16Offset: utf16Offset(forCharacters: offset))
    }

    func keyboardView(_ keyboardView: KeyboardView, edit command: EditCommand) {
        clearProofreadSuggestion()
        guard pending == nil else { return }
        previousInsertWasSpace = false
        lastCorrection = nil
        recentWord = nil
        commitPinyinLetters()
        switch command {
        case .toggleLanguage:
            setAllText(nil)
            chineseMode.toggle()
            keyboardView.chineseActive = chineseMode
            refreshCaption()
            if remembersLanguage {
                UserDefaults.standard.set(chineseMode, forKey: Self.languageKey)
            }
            if !chineseMode { languageModelLoader?.loadInBackground() }
        case .selectAll:
            if allText != nil {
                setAllText(nil)
            } else {
                let current = currentText()
                if document.selectedText != nil {
                    // A selection made in the app already answers cut and copy, and the
                    // keyboard cannot see where that selection sits in the stored text.
                    showNotice("Clear the selection first")
                } else if current.text.isEmpty {
                    showNotice("No text to select")
                } else {
                    setAllText(current)
                }
            }
        case .lineStart, .lineEnd, .lineUp, .lineDown:
            setAllText(nil)
            let offset = KeyboardTextLogic.cursorOffset(
                for: command, before: document.textBeforeCursor, after: document.textAfterCursor)
            if offset != 0 {
                document.moveCursor(byUTF16Offset: offset)
            }
        case .cut, .copy:
            guard document.canUseClipboard else {
                showNotice("Turn on Full Access in Settings")
                return
            }
            if let snapshot = confirmedAllText() {
                UIPasteboard.general.string = snapshot.text
                if command == .cut {
                    replaceAllText(snapshot)
                    showNotice("Cut all text")
                } else {
                    showNotice("Copied all text")
                }
            } else if let selected = document.selectedText, !selected.isEmpty {
                UIPasteboard.general.string = selected
                if command == .cut {
                    document.deleteBackward()
                    showNotice("Cut")
                } else {
                    showNotice("Copied")
                }
            } else {
                showNotice("Select text first")
            }
        case .paste:
            guard document.canUseClipboard else {
                showNotice("Turn on Full Access in Settings")
                return
            }
            guard let text = UIPasteboard.general.string, !text.isEmpty else {
                showNotice("Clipboard is empty")
                return
            }
            if let snapshot = confirmedAllText() {
                replaceAllText(snapshot, rawInsert: text)
            } else {
                document.insertText(text)
            }
        case .deleteForward:
            if let snapshot = confirmedAllText() {
                replaceAllText(snapshot)
                return
            }
            // Apple's keyboard guide gives this pattern: move one character right, then delete backward.
            guard let next = document.textAfterCursor.first else { return }
            document.moveCursor(byUTF16Offset: String(next).utf16.count)
            document.deleteBackward()
        }
        updateAutoShift()
    }

    func keyboardViewDismiss(_ keyboardView: KeyboardView) {
        cancelPendingEdits()
        onDismiss()
    }

    func keyboardViewDidPressKey(_ keyboardView: KeyboardView) {
        UIDevice.current.playInputClick()
    }
}
