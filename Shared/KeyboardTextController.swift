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
    func insertText(_ text: String)
    func deleteBackward()
    /// Moves the cursor. The offset counts UTF-16 units.
    func moveCursor(byUTF16Offset offset: Int)
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

    init(keyboardView: KeyboardView, document: KeyboardDocument) {
        self.keyboardView = keyboardView
        self.document = document
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
        let capitalize = KeyboardTextLogic.shouldAutoCapitalize(
            before: document.textBeforeCursor, type: document.autocapitalizationType)
        keyboardView.setAutomaticShift(capitalize)
    }

    private func refreshCaption() {
        keyboardView.selectAllActive = allText != nil
        keyboardView.spaceCaption = notice ?? (allText != nil ? "All text selected" : nil)
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
        if text == " ", previousInsertWasSpace, now - lastSpaceTime < 1.5,
            KeyboardTextLogic.shouldReplaceDoubleSpace(before: document.textBeforeCursor) {
            document.deleteBackward()
            document.insertText(". ")
            previousInsertWasSpace = false
        } else {
            document.insertText(text)
            previousInsertWasSpace = text == " "
            lastSpaceTime = now
        }
        updateAutoShift()
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
        if let snapshot = confirmedAllText() {
            replaceAllText(snapshot, with: text)
            return
        }
        insert(text)
    }

    func keyboardViewDeleteBackward(_ keyboardView: KeyboardView) {
        guard pending == nil else { return }
        if let snapshot = confirmedAllText() {
            replaceAllText(snapshot, with: nil)
            return
        }
        document.deleteBackward()
        previousInsertWasSpace = false
        updateAutoShift()
    }

    func keyboardViewReturn(_ keyboardView: KeyboardView) {
        self.keyboardView(keyboardView, insert: "\n")
    }

    func keyboardView(_ keyboardView: KeyboardView, moveCursorBy offset: Int) {
        guard pending == nil else { return }
        setAllText(nil)
        previousInsertWasSpace = false
        document.moveCursor(byUTF16Offset: utf16Offset(forCharacters: offset))
    }

    func keyboardView(_ keyboardView: KeyboardView, edit command: EditCommand) {
        guard pending == nil else { return }
        previousInsertWasSpace = false
        switch command {
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
