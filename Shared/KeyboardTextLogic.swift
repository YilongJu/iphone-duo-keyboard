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
            let trimmed = before.reversed().drop(while: { $0 == " " })
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
