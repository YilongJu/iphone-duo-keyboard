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

    /// The symbol and digit keys that sit beside a letter key, in the wide layout or the compact
    /// layout of keyboard-layout.json. A finger that aims at the letter can land on one of them,
    /// as in "[lease" for "please" and "2hat" for "what". The script
    /// scripts/typing-evaluation/symbol_keys.py derives both sets from the key positions, and
    /// its check fails when a set here differs.
    static let symbolsBesideLetters: Set<Character> = Set(",-.0123456789;[")
    /// The keys of that set that autocorrection reads as a slip at any place in a word. The
    /// others end a word or join two words, so they count as a slip only in front of a word.
    static let symbolsInsideWords: Set<Character> = Set("0123456789[")

    /// The word right before the cursor, when autocorrection may change that word.
    /// The word may hold one symbol or digit key that sits beside a letter key, because that
    /// key can be a slip for the letter: a digit or "[" at any place, or one of "-", ";", ","
    /// and "." in front of the word. Such a word has two letters or more.
    /// The function returns nil for text that is probably not plain prose: a word with a capital
    /// after its first character, a word with any other digit or symbol in it, and a word that
    /// follows a character such as "@", "/" or "." with no space between.
    static func correctableWord(before: String) -> String? {
        var start = before.endIndex
        while start > before.startIndex {
            let previous = before.index(before: start)
            let character = before[previous]
            guard character.isASCII, character.isLetter || character == "'" || symbolsInsideWords.contains(character)
            else { break }
            start = previous
        }
        if start > before.startIndex, start < before.endIndex {
            let previous = before.index(before: start)
            if symbolsBesideLetters.contains(before[previous]) {
                start = previous
            }
        }
        var word = String(before[start...])
        // A capital right after a symbol key: the key is not read as a slip for the first
        // letter, and the word starts after the key, as "Teh" does in "[Teh". In a field that
        // capitalizes sentences or words, automatic shift turns off at a symbol key, so the
        // person asked for that capital and typed the key on purpose.
        if let symbol = word.first, symbolsBesideLetters.contains(symbol),
            let second = word.dropFirst().first, second.isUppercase {
            start = before.index(after: start)
            word = String(before[start...])
        }
        guard let first = word.first, word.last != "'" else { return nil }
        let symbolCount = word.filter { symbolsBesideLetters.contains($0) }.count
        if symbolCount == 0 {
            guard first.isLetter else { return nil }
        } else {
            let letterCount = word.filter { $0.isLetter }.count
            guard symbolCount == 1, letterCount >= 2, first != "'" else { return nil }
        }
        if start > before.startIndex {
            let preceding = before[before.index(before: start)]
            guard preceding.isWhitespace || "([{\"".contains(preceding) else { return nil }
            // A word with a symbol key does not follow another symbol key, as in "[;ike".
            guard symbolCount == 0 || !symbolsBesideLetters.contains(preceding) else { return nil }
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

    // MARK: Proofreading of a finished sentence

    /// The marks that end a sentence, in English and in Chinese.
    static let sentenceEnds: Set<Character> = [
        ".", "?", "!", "\u{2026}", "\u{3002}", "\u{FF1F}", "\u{FF01}",
    ]

    /// The marks that end a clause inside a sentence: comma, semicolon and colon in English
    /// and in Chinese, and the Chinese list comma.
    static let clauseEnds: Set<Character> = [
        ",", ";", ":", "\u{FF0C}", "\u{FF1B}", "\u{FF1A}", "\u{3001}",
    ]

    /// The text from the start of the current sentence to the mark right before the cursor, or
    /// nil. The mark is one that ends a sentence or a clause, so a comma also gives a result:
    /// the sentence as far as it is typed. Spaces after the mark do not count. The text needs
    /// three words, or four characters when it holds Chinese text, because a shorter one does
    /// not give a proofreader enough to read.
    static func finishedSentence(before text: String) -> String? {
        var body = Substring(text)
        while body.last == " " { body = body.dropLast() }
        guard let last = body.last, sentenceEnds.contains(last) || clauseEnds.contains(last) else { return nil }
        let inner = body.dropLast()
        var start = inner.endIndex
        while start > inner.startIndex {
            let previous = inner.index(before: start)
            if sentenceEnds.contains(inner[previous]) || inner[previous].isNewline { break }
            start = previous
        }
        var sentence = body[start...]
        while sentence.first == " " { sentence = sentence.dropFirst() }
        guard sentence.count <= 300 else { return nil }
        let holdsChinese = sentence.unicodeScalars.contains { $0.value >= 0x4E00 && $0.value <= 0x9FFF }
        let longEnough = holdsChinese ? sentence.count >= 4 : sentence.split(separator: " ").count >= 3
        return longEnough ? String(sentence) : nil
    }

    /// The proofreader's answer when it is a small fix of the sentence, or nil.
    ///
    /// A language model can rephrase a sentence or answer it in place of fixing it. This check
    /// keeps an answer only when it is the same sentence with a few words or characters
    /// changed: at most two units, or one unit in four for a longer sentence. A unit is a
    /// word, or a character in a sentence without spaces, as in Chinese.
    ///
    /// Each new word must also look like the word it replaces, as "from" looks like "form". A
    /// model that does not know a word can put an unrelated word in its place, as in "from
    /// correction" for "mautocoorection", and this check drops such an answer.
    static func acceptedProofreading(of original: String, answer: String) -> String? {
        var fixed = answer.trimmingCharacters(in: .whitespacesAndNewlines)
        for (open, close) in [("\"", "\""), ("\u{201C}", "\u{201D}")] where fixed.count >= 2
            && fixed.hasPrefix(open) && fixed.hasSuffix(close) && !original.hasPrefix(open) {
            fixed = String(fixed.dropFirst().dropLast())
        }
        guard !fixed.isEmpty, fixed != original, !fixed.contains(where: { $0.isNewline }) else { return nil }
        func units(_ text: String) -> [String] {
            let words = text.split(separator: " ").map(String.init)
            return words.count >= 3 ? words : text.map(String.init)
        }
        let before = units(original)
        let after = units(fixed)
        let allowed = max(2, before.count / 4)
        guard changedUnits(before, after) <= allowed else { return nil }
        return newWordsResembleOldWords(before, after) ? fixed : nil
    }

    /// True when the words that `after` adds look like the words it takes out of `before`.
    /// With the same count on both sides, each new word is compared with the old word at its
    /// place and may differ in two letters, or in a third of its letters. With different counts,
    /// as when one word becomes two, the words of each side are joined and compared the same way.
    static func newWordsResembleOldWords(_ before: [String], _ after: [String]) -> Bool {
        // Both lists run from the first changed word to the last. A loop over the difference
        // itself gives the words taken out from last to first.
        let difference = after.difference(from: before)
        func word(_ change: CollectionDifference<String>.Change) -> String {
            switch change {
            case .remove(_, let word, _), .insert(_, let word, _): return word
            }
        }
        let removed = difference.removals.map(word)
        let added = difference.insertions.map(word)
        func resembles(_ old: String, _ new: String) -> Bool {
            let limit = max(2, max(old.count, new.count) / 3)
            return changedUnits(old.map(String.init), new.map(String.init)) <= limit
        }
        if removed.count == added.count {
            return zip(removed, added).allSatisfy { resembles($0, $1) }
        }
        return resembles(removed.joined(), added.joined())
    }

    /// Count of units that differ between two lists: the fewest single changes, each one a
    /// unit put in, taken out or replaced, that turn the first list into the second.
    static func changedUnits(_ first: [String], _ second: [String]) -> Int {
        if first.isEmpty { return second.count }
        if second.isEmpty { return first.count }
        var previous = Array(0...second.count)
        for i in 1...first.count {
            var current = [i] + Array(repeating: 0, count: second.count)
            for j in 1...second.count {
                let replace = previous[j - 1] + (first[i - 1] == second[j - 1] ? 0 : 1)
                current[j] = min(replace, previous[j] + 1, current[j - 1] + 1)
            }
            previous = current
        }
        return previous[second.count]
    }

    /// Gives a corrected word its capital when a symbol key took the place of its first letter
    /// at a place where the keyboard types a capital by itself, such as the start of a sentence.
    /// Automatic shift leaves a symbol key on its base character and then turns off, so the
    /// typed text "[lease" does not show that the person meant "Please".
    /// `textBefore` is the text of the field before `typed`.
    static func capitalizingRepairedFirstLetters(
        in corrected: String, from typed: String, textBefore: String, type: UITextAutocapitalizationType
    ) -> String {
        let typedWords = typed.split(separator: " ")
        var words = corrected.split(separator: " ").map(String.init)
        guard words.count == typedWords.count else { return corrected }
        var before = textBefore
        for index in words.indices {
            if let typedFirst = typedWords[index].first, symbolsBesideLetters.contains(typedFirst),
                let first = words[index].first, first.isLetter,
                shouldAutoCapitalize(before: before, type: type) {
                words[index] = words[index].prefix(1).uppercased() + words[index].dropFirst()
            }
            before += words[index] + " "
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
