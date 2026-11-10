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
    /// `previousWord` is the lower-case word before `typed`, or an empty string.
    func reading(previousWord: String, typed: String) -> String?
    /// Stops the keyboard from changing this word again.
    func learn(_ word: String)
    /// True for a word the person brought back after a correction.
    func keeps(_ word: String) -> Bool
}

/// English correction from the typing engine in Engine/duo_engine.c. The engine reads a
/// wrong neighbor key, also when that key is a symbol or a digit, a missing, extra or doubled
/// letter, swapped letters, and slips around the space bar, and it weighs each reading by how
/// common its words are.
@MainActor
final class EngineSpellChecker: SpellChecking {
    private static let keptWordsKey = "englishKeptWords"
    private let engine: EnglishTypingEngine
    /// Words the person brought back after a correction, kept across keyboard launches.
    private var keptWords: Set<String>

    init(engine: EnglishTypingEngine) {
        self.engine = engine
        // A phone on which nobody has brought a word back yet does not have the stored list.
        keptWords = Set(UserDefaults.standard.stringArray(forKey: Self.keptWordsKey) ?? [])
    }

    /// The engine with the English lexicon of the app bundle.
    static func bundled() -> EngineSpellChecker {
        EngineSpellChecker(engine: EnglishTypingEngine(lexicon: TypingLexicon(resource: "lexicon-english", fullCheck: false)))
    }

    func reading(previousWord: String, typed: String) -> String? {
        engine.reading(previousWord: previousWord, typed: typed)
    }

    func learn(_ word: String) {
        guard keptWords.insert(word.lowercased()).inserted else { return }
        UserDefaults.standard.set(Array(keptWords), forKey: Self.keptWordsKey)
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
    }

    /// The owner calls this when the app's text or cursor changed.
    func documentDidChange() {
        if let allText, allText != currentText() {
            setAllText(nil)
        }
        updateAutoShift()
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
            ?? (allText != nil ? "All text selected" : (chineseMode ? "\u{62FC}\u{97F3}" : nil))
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
            }
            return
        }

        let followedBySpace = terminator == " "
        // A word the person brought back after a correction stays as typed.
        guard !spellChecker.keeps(word) else {
            if followedBySpace { recentWord = RecentWord(typed: word, shown: word, context: contextAfterSpace()) }
            return
        }
        var typedSpan = word
        var shownSpan = word
        if let earlier, !spellChecker.keeps(earlier.typed), !spellChecker.keeps(earlier.shown),
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
            ? spellChecker.reading(previousWord: previousWord, typed: typedSpan.lowercased()) : nil
        // A reading of two words together replaces an earlier reading of the first word alone,
        // also when it brings back the letters the person typed. Without a reading the shown
        // text stays, and only a lone "i" gets its capital.
        let restored = reading.map { KeyboardTextLogic.restoringCapitals(in: $0, from: typedSpan) }
            ?? KeyboardTextLogic.restoringCapitals(in: shownSpan, from: shownSpan)
        // A word whose first letter was typed as a symbol key gets the capital that the
        // keyboard types by itself at that place, as in "[lease" at the start of a sentence.
        let final = KeyboardTextLogic.capitalizingRepairedFirstLetters(
            in: restored, from: typedSpan, textBefore: String(before.dropLast(shownSpan.count)),
            type: document.autocapitalizationType)
        let finalWords = final.split(separator: " ")
        if final != shownSpan {
            deleteBackward(count: shownSpan.count)
            document.insertText(final)
            lastCorrection = Correction(original: shownSpan, corrected: final, terminator: terminator)
            showNotice("\(shownSpan) \u{2192} \(final)")
        }
        if followedBySpace, let last = finalWords.last {
            // After a correction that joined or split words, the last shown word counts as typed
            // that way, so the next correction does not take the same keys apart again.
            let sameCount = finalWords.count == typedWords.count
            recentWord = RecentWord(
                typed: sameCount ? word : String(last), shown: String(last), context: contextAfterSpace())
        }
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
        selectCandidate(at: index)
    }

    func keyboardViewDeleteBackward(_ keyboardView: KeyboardView) {
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
            document.deleteBackward()
        }
        recentWord = nil
        updateAutoShift()
    }

    func keyboardViewReturn(_ keyboardView: KeyboardView) {
        self.keyboardView(keyboardView, insert: "\n")
    }

    func keyboardView(_ keyboardView: KeyboardView, moveCursorBy offset: Int) {
        guard pending == nil else { return }
        setAllText(nil)
        commitPinyinLetters()
        previousInsertWasSpace = false
        lastCorrection = nil
        recentWord = nil
        document.moveCursor(byUTF16Offset: utf16Offset(forCharacters: offset))
    }

    func keyboardView(_ keyboardView: KeyboardView, edit command: EditCommand) {
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
