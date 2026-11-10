import UIKit

/// Text rules shared by the keyboard extension and the in-app preview.
enum KeyboardTextLogic {
    /// True when the next letter should be upper case, given the text before the cursor.
    static func shouldAutoCapitalize(before: String?, type: UITextAutocapitalizationType) -> Bool {
        switch type {
        case .none:
            return false
        case .allCharacters:
            return true
        case .words:
            guard let last = before?.last else { return true }
            return last.isWhitespace
        case .sentences:
            guard let before, !before.isEmpty else { return true }
            guard let last = before.last else { return true }
            if last.isNewline { return true }
            guard last.isWhitespace else { return false }
            let trimmed = before.reversed().drop(while: { $0 == " " || $0 == "\t" })
            guard let sentenceEnd = trimmed.first else { return true }
            return sentenceEnd == "." || sentenceEnd == "!" || sentenceEnd == "?" || sentenceEnd.isNewline
        @unknown default:
            return false
        }
    }

    /// True when a second space should turn the previous space into a period and a space.
    static func shouldReplaceDoubleSpace(before: String?) -> Bool {
        guard let before, before.hasSuffix(" ") else { return false }
        guard let previous = before.dropLast().last else { return false }
        return previous.isLetter || previous.isNumber || ")]\"'".contains(previous)
    }

    /// Cursor movement for the home, end, up and down keys, as an offset from the cursor.
    /// The offset counts UTF-16 units, the unit `adjustTextPosition(byCharacterOffset:)` uses.
    ///
    /// A line here is the text between two line breaks. iOS does not tell a keyboard where a
    /// long paragraph wraps on screen, so up and down move between paragraphs' lines only.
    static func cursorOffset(for command: EditCommand, before: String, after: String) -> Int {
        let lineStart = before.lastIndex(where: { $0.isNewline }).map { before.index(after: $0) } ?? before.startIndex
        let column = before[lineStart...].utf16.count
        let lineEnd = after.firstIndex(where: { $0.isNewline }) ?? after.endIndex
        let rest = after[..<lineEnd].utf16.count
        switch command {
        case .lineStart:
            return -column
        case .lineEnd:
            return rest
        case .lineUp:
            guard lineStart > before.startIndex else { return -column }
            let head = before[..<before.index(before: lineStart)]
            let previousStart = head.lastIndex(where: { $0.isNewline }).map { head.index(after: $0) } ?? head.startIndex
            let previousLength = head[previousStart...].utf16.count
            return -(column + 1 + max(previousLength - column, 0))
        case .lineDown:
            guard lineEnd < after.endIndex else { return rest }
            let tail = after[after.index(after: lineEnd)...]
            let nextEnd = tail.firstIndex(where: { $0.isNewline }) ?? tail.endIndex
            let nextLength = tail[..<nextEnd].utf16.count
            return rest + 1 + min(column, nextLength)
        case .cut, .copy, .paste, .selectAll, .deleteForward, .toggleLanguage:
            return 0
        }
    }

    // MARK: Autocorrection

    /// A character that ends a word. Autocorrection looks at the word when one of these arrives.
    static let wordTerminators: Set<String> = [" ", ".", ",", "!", "?", ";", ":", "\n"]

    /// The word right before the cursor, when autocorrection may change that word.
    /// The function returns nil for text that is probably not plain prose: a word with a capital
    /// after its first letter, a word with a digit or symbol in it, and a word that follows a
    /// character such as "@", "/" or "." with no space between.
    static func correctableWord(before: String) -> String? {
        var start = before.endIndex
        while start > before.startIndex {
            let previous = before.index(before: start)
            let character = before[previous]
            guard character.isASCII, character.isLetter || character == "'" else { break }
            start = previous
        }
        let word = String(before[start...])
        guard let first = word.first, first.isLetter, word.last != "'" else { return nil }
        if start > before.startIndex {
            let preceding = before[before.index(before: start)]
            guard preceding.isWhitespace || "([{\"".contains(preceding) else { return nil }
        }
        guard word.dropFirst().allSatisfy({ !$0.isUppercase }) else { return nil }
        return word
    }

    /// The lower-case word that ends `text`, when one space follows it, or an empty string.
    /// The typing engine reads this word as the context of the text typed after it.
    static func wordBeforeSpace(at text: String) -> String {
        guard text.hasSuffix(" ") else { return "" }
        let head = text.dropLast()
        var start = head.endIndex
        while start > head.startIndex {
            let previous = head.index(before: start)
            let character = head[previous]
            guard character.isASCII, character.isLetter || character == "'" else { break }
            start = previous
        }
        return head[start...].lowercased()
    }

    /// Gives corrected lower-case words the capitals of the typed words. A typed word that
    /// starts with a capital gives its capital to the word in the same place, or to the first
    /// word when the correction changed the count of words. The word "i" and its contractions
    /// always get their capital.
    static func restoringCapitals(in corrected: String, from typed: String) -> String {
        let typedWords = typed.split(separator: " ")
        var words = corrected.split(separator: " ").map(String.init)
        func capitalized(_ word: String) -> String {
            word.prefix(1).uppercased() + word.dropFirst()
        }
        func startsWithCapital(_ word: Substring) -> Bool {
            word.first?.isUppercase ?? false
        }
        if words.count == typedWords.count {
            for index in words.indices where startsWithCapital(typedWords[index]) {
                words[index] = capitalized(words[index])
            }
        } else if let first = typedWords.first, startsWithCapital(first), !words.isEmpty {
            words[0] = capitalized(words[0])
        }
        for index in words.indices where words[index] == "i" || words[index].hasPrefix("i'") {
            words[index] = capitalized(words[index])
        }
        return words.joined(separator: " ")
    }

    static func returnKeyTitle(for type: UIReturnKeyType) -> String {
        switch type {
        case .go: return "go"
        case .google, .search, .yahoo: return "search"
        case .join: return "join"
        case .next: return "next"
        case .route: return "route"
        case .send: return "send"
        case .done: return "done"
        case .continue: return "continue"
        case .emergencyCall: return "call"
        case .default: return "return"
        @unknown default: return "return"
        }
    }
}
