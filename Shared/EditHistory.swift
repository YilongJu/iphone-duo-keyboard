import Foundation

/// One step of the edit history: the change that one action of the person made to the field.
///
/// A step changes the text right before the cursor, and the Pinyin letters that wait for a
/// candidate. The step takes `removed` out and puts `added` in its place. The Backward key takes
/// the newest step back: it takes `added` out and puts `removed` in. The Redo key makes the
/// step again.
struct EditStep: Equatable {
    /// How a step joins the step after it.
    enum Run: Equatable {
        /// Typed characters. `startsInWord` and `endsInWord` say whether the first and the last
        /// typed character are part of a word.
        case typing(startsInWord: Bool, endsInWord: Bool)
        /// Characters that the delete key took out.
        case deleting
        /// A step that joins no other step: a correction, a picked candidate, a tapped word or
        /// emoji, pasted text, cut text, or a change of all the text.
        case single
    }

    /// The state of the quote keys of Chinese mode: true while a quotation is open.
    struct Quotes: Equatable {
        var doubleIsOpen = false
        var singleIsOpen = false
    }

    /// The text right before the cursor that the step took out.
    var removed: String
    /// The text that the step put in its place.
    var added: String
    /// The Pinyin letters that waited for a candidate before the step and after it.
    var lettersBefore = ""
    var lettersAfter = ""
    var quotesBefore = Quotes()
    var quotesAfter = Quotes()
    var run: Run = .single
    /// The words that the keyboard stops correcting when the Backward key takes the step back.
    /// Only the step of a correction holds such words: the words as the person typed them.
    var keeps: [String] = []

    /// True for a step that changes no text and no Pinyin letters.
    var isEmpty: Bool {
        removed.isEmpty && added.isEmpty && lettersBefore == lettersAfter
    }

    /// True for a character that is part of a word: a letter, a digit or an apostrophe.
    static func isWordCharacter(_ character: Character) -> Bool {
        character.isLetter || character.isNumber || character == "'" || character == "\u{2019}"
    }

    /// The run of a step that typed `text`.
    static func typing(_ text: String) -> Run {
        .typing(
            startsInWord: text.first.map(isWordCharacter) ?? false,
            endsInWord: text.last.map(isWordCharacter) ?? false)
    }

    /// The same step without the characters that `removed` and `added` both start with. The
    /// keyboard then deletes and types only the part of the text that differs.
    func trimmed() -> EditStep {
        var common = 0
        for (old, new) in zip(removed, added) {
            guard old == new else { break }
            common += 1
        }
        guard common > 0 else { return self }
        var step = self
        step.removed = String(removed.dropFirst(common))
        step.added = String(added.dropFirst(common))
        return step
    }

    /// True when `next` goes into this step, so one press of the Backward key takes both back.
    /// The typed characters of one word are one step, together with the spaces and marks after
    /// the word. A letter after a space or a mark starts a new word, and a new step. The deletes
    /// of the delete key in a row are one step.
    func continues(with next: EditStep) -> Bool {
        switch (run, next.run) {
        case (.typing(_, let endsInWord), .typing(let startsInWord, _)):
            return endsInWord || !startsInWord
        case (.deleting, .deleting):
            return true
        default:
            return false
        }
    }

    /// The one step that does what this step and then `next` do, or nil when `next` does not
    /// start in the state that this step ends in.
    func joined(with next: EditStep) -> EditStep? {
        guard lettersAfter == next.lettersBefore else { return nil }
        var step = self
        if next.removed.count <= added.count {
            // The next step takes out only text that this step put in.
            guard added.hasSuffix(next.removed) else { return nil }
            step.added = String(added.dropLast(next.removed.count)) + next.added
        } else {
            // The next step takes out all that this step put in, and older text before it.
            guard next.removed.hasSuffix(added) else { return nil }
            step.removed = String(next.removed.dropLast(added.count)) + removed
            step.added = next.added
        }
        step.lettersAfter = next.lettersAfter
        step.quotesAfter = next.quotesAfter
        step.keeps += next.keeps
        if case .typing(let startsInWord, _) = run, case .typing(_, let endsInWord) = next.run {
            step.run = .typing(startsInWord: startsInWord, endsInWord: endsInWord)
        }
        return step
    }
}

/// The edit history of one text field: the steps that the Backward key can take back, and the
/// steps that the Redo key can make again.
///
/// iOS gives a keyboard no call for the undo of the app, so the keyboard keeps the steps of
/// its own edits. A new action of the person empties the steps of the Redo key, because the
/// text then goes on from a new state.
struct EditHistory: Equatable {
    /// The most steps that the Backward key can take back. An older step leaves the history.
    static let limit = 200

    /// The steps that the Backward key takes back, the newest one last.
    private(set) var undoSteps: [EditStep] = []
    /// The steps that the Redo key makes again, the next one last.
    private(set) var redoSteps: [EditStep] = []

    var canUndo: Bool { !undoSteps.isEmpty }
    var canRedo: Bool { !redoSteps.isEmpty }
    var isEmpty: Bool { undoSteps.isEmpty && redoSteps.isEmpty }

    /// Adds the step of a new action, and empties the steps of the Redo key. The step goes into
    /// the newest step when `EditStep.continues(with:)` says so.
    mutating func record(_ step: EditStep) {
        redoSteps = []
        if let last = undoSteps.last, last.continues(with: step), let joined = last.joined(with: step) {
            undoSteps[undoSteps.count - 1] = joined
            return
        }
        undoSteps.append(step)
        if undoSteps.count > Self.limit {
            undoSteps.removeFirst(undoSteps.count - Self.limit)
        }
    }

    /// Moves the newest step to the steps of the Redo key and returns it.
    @discardableResult
    mutating func stepBack() -> EditStep? {
        guard let step = undoSteps.popLast() else { return nil }
        redoSteps.append(step)
        return step
    }

    /// Moves the next step of the Redo key back to the steps of the Backward key and returns it.
    @discardableResult
    mutating func stepForward() -> EditStep? {
        guard let step = redoSteps.popLast() else { return nil }
        undoSteps.append(step)
        return step
    }

    mutating func clear() {
        undoSteps = []
        redoSteps = []
    }
}

/// One call of the keyboard that changes the text or the cursor of the document.
enum DocumentEdit: Equatable {
    case insert(String)
    case deleteBackward
    /// A move of the cursor by this count of UTF-16 units.
    case moveCursor(Int)
    /// The end of a composition: the marked text stays in the field as plain text.
    case unmark
}
