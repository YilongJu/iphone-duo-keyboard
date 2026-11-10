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

/// Finds the correction for a misspelled word.
@MainActor
protocol SpellChecking: AnyObject {
    /// Returns the corrected word, or nil when the word is fine or the checker has no close guess.
    func correction(for word: String) -> String?
    /// Stops the checker from flagging this word again.
    func learn(_ word: String)
}

/// English spelling from the system's own spell checker.
@MainActor
final class SystemSpellChecker: SpellChecking {
    private let checker = UITextChecker()
    private let language = "en_US"

    func correction(for word: String) -> String? {
        let range = NSRange(location: 0, length: word.utf16.count)
        let misspelled = checker.rangeOfMisspelledWord(
            in: word, range: range, startingAt: 0, wrap: false, language: language)
        guard misspelled.location != NSNotFound else { return nil }
        let guesses = checker.guesses(forWordRange: range, in: word, language: language) ?? []
        return KeyboardTextLogic.bestGuess(for: word, guesses: guesses)
    }

    func learn(_ word: String) {
        UITextChecker.learnWord(word)
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
    /// Words the user brought back after a correction. Autocorrection leaves these alone.
    private var keptWords: Set<String> = []

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
        var insert: String?
        let documentIdentifier: UUID
        var attempts = 0
    }

    private var pending: PendingReplacement?

    /// True while the keyboard types Simplified Chinese through Pinyin.
    private(set) var chineseMode = false
    /// The Pinyin letters typed so far that are not Chinese text yet.
    private(set) var pinyinBuffer = ""
    private var pinyinCandidates: [PinyinCandidate] = []
    private let makePinyinEngine: @MainActor () -> PinyinEngine
    /// The dictionary loads on the first switch to Chinese, so English typing does not pay for the load.
    private lazy var pinyinEngine: PinyinEngine = makePinyinEngine()

    /// Chinese forms of the punctuation keys.
    private static let chinesePunctuation: [String: String] = [
        ",": "\u{FF0C}", ".": "\u{3002}", "?": "\u{FF1F}", "!": "\u{FF01}", ":": "\u{FF1A}",
        ";": "\u{FF1B}", "(": "\u{FF08}", ")": "\u{FF09}", "\\": "\u{3001}",
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

    /// Deletes the stored text and then inserts `text`, if any.
    /// The caller passes a snapshot that `confirmedAllText()` just returned.
    private func replaceAllText(_ snapshot: AllText, with text: String?) {
        setAllText(nil)
        previousInsertWasSpace = false
        guard !snapshot.after.isEmpty else {
            // The cursor is at the end of the text, so the delete needs no cursor move.
            deleteBackward(count: snapshot.before.count)
            finishReplacement(insert: text)
            return
        }
        // A keyboard can delete backward only. The cursor moves to the end of the text first.
        // The delete waits for the document to confirm the cursor's new place, so a move that
        // did not happen as expected does not delete any text.
        document.moveCursor(byUTF16Offset: snapshot.after.utf16.count)
        pending = PendingReplacement(
            snapshot: snapshot, insert: text, documentIdentifier: document.documentIdentifier)
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
            finishReplacement(insert: replacement.insert)
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
        pinyinBuffer.removeFirst(candidate.consumedLetters)
        refreshCandidates()
    }

    /// Types the buffered letters as plain letters and empties the buffer.
    private func commitPinyinLetters() {
        guard !pinyinBuffer.isEmpty else { return }
        document.insertText(pinyinBuffer)
        pinyinBuffer = ""
        refreshCandidates()
    }

    /// Handles a typed character while the keyboard types Chinese.
    /// Returns false when the character should go through the normal typing path.
    private func handleChineseInput(_ text: String) -> Bool {
        if text.count == 1, let letter = text.lowercased().first, letter.isASCII, letter.isLetter {
            // A buffer of 30 letters covers any phrase in the dictionary.
            guard pinyinBuffer.count < 30 else { return true }
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
        return false
    }

    private func deleteBackward(count: Int) {
        for _ in 0..<count {
            document.deleteBackward()
        }
    }

    private func finishReplacement(insert text: String?) {
        if let text {
            document.insertText(text)
        }
        updateAutoShift()
    }

    // MARK: Typing

    private func insert(_ text: String) {
        let now = ProcessInfo.processInfo.systemUptime
        if text == " ", !chineseMode, previousInsertWasSpace, now - lastSpaceTime < 1.5,
            KeyboardTextLogic.shouldReplaceDoubleSpace(before: document.textBeforeCursor) {
            document.deleteBackward()
            document.insertText(". ")
            previousInsertWasSpace = false
        } else {
            correctLastWord(beforeTyping: text)
            document.insertText(text)
            previousInsertWasSpace = text == " "
            lastSpaceTime = now
        }
        updateAutoShift()
    }

    /// Replaces a misspelled word right before the cursor, when `terminator` ends that word.
    private func correctLastWord(beforeTyping terminator: String) {
        lastCorrection = nil
        guard !chineseMode, KeyboardTextLogic.wordTerminators.contains(terminator), document.allowsAutocorrection,
            let word = KeyboardTextLogic.correctableWord(before: document.textBeforeCursor),
            !keptWords.contains(word.lowercased())
        else { return }
        let corrected: String?
        if word == "i" {
            corrected = "I"
        } else if word.count >= 2 {
            corrected = spellChecker.correction(for: word)
        } else {
            corrected = nil
        }
        guard let corrected, corrected != word else { return }
        deleteBackward(count: word.count)
        document.insertText(corrected)
        lastCorrection = Correction(original: word, corrected: corrected, terminator: terminator)
        showNotice("\(word) \u{2192} \(corrected)")
    }

    /// Brings back the word the user typed, when the cursor still sits right after the correction.
    private func undoLastCorrection() -> Bool {
        guard let correction = lastCorrection else { return false }
        lastCorrection = nil
        let typed = correction.corrected + correction.terminator
        guard document.textBeforeCursor.hasSuffix(typed) else { return false }
        deleteBackward(count: typed.count)
        document.insertText(correction.original)
        keptWords.insert(correction.original.lowercased())
        spellChecker.learn(correction.original)
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
            // A replacement is still running. The typed text joins the text that waits for insertion.
            replacement.insert = (replacement.insert ?? "") + text
            pending = replacement
            return
        }
        if chineseMode, allText == nil, handleChineseInput(text) {
            updateAutoShift()
            return
        }
        if let snapshot = confirmedAllText() {
            replaceAllText(snapshot, with: text)
            return
        }
        insert(text)
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
            replaceAllText(snapshot, with: nil)
            return
        }
        previousInsertWasSpace = false
        if !undoLastCorrection() {
            document.deleteBackward()
        }
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
        document.moveCursor(byUTF16Offset: utf16Offset(forCharacters: offset))
    }

    func keyboardView(_ keyboardView: KeyboardView, edit command: EditCommand) {
        guard pending == nil else { return }
        previousInsertWasSpace = false
        lastCorrection = nil
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
                    replaceAllText(snapshot, with: nil)
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
                replaceAllText(snapshot, with: text)
            } else {
                document.insertText(text)
            }
        case .deleteForward:
            if let snapshot = confirmedAllText() {
                replaceAllText(snapshot, with: nil)
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
