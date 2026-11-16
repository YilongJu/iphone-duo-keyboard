import Foundation

/// The emoji that the keyboard offers for a word: at most two for each word, for English and for
/// Chinese. scripts/emoji-table/build_emoji_table.py builds the table emoji-suggestions.tsv from
/// the Unicode CLDR emoji annotations, and docs/emoji-suggestions.md describes it.
struct EmojiSuggestions {
    private let englishTable: [String: [String]]
    private let chineseTable: [String: [String]]

    /// Reads a table in the format of emoji-suggestions.tsv: a line holds the language "en" or
    /// "zh", the word and its emoji, with a tab between the three and one space between two
    /// emoji. A line that starts with "#" is a note. A line in another form stops the process,
    /// because the table ships with the app and a wrong line is a build error.
    init(table: String) {
        var english: [String: [String]] = [:]
        var chinese: [String: [String]] = [:]
        for line in table.split(whereSeparator: \.isNewline) where !line.hasPrefix("#") {
            let parts = line.split(separator: "\t", omittingEmptySubsequences: false).map(String.init)
            let emoji = parts.count == 3 ? parts[2].split(separator: " ").map(String.init) : []
            guard parts.count == 3, !parts[1].isEmpty, (1...2).contains(emoji.count) else {
                fatalError("emoji-suggestions.tsv: wrong line \(line)")
            }
            switch parts[0] {
            case "en": english[parts[1]] = emoji
            case "zh": chinese[parts[1]] = emoji
            default: fatalError("emoji-suggestions.tsv: unknown language in \(line)")
            }
        }
        englishTable = english
        chineseTable = chinese
    }

    /// The table of the app bundle. The file ships with the keyboard, so a missing file stops the process.
    static let bundled: EmojiSuggestions = {
        guard let url = Bundle(for: KeyboardTextController.self).url(forResource: "emoji-suggestions", withExtension: "tsv"),
            let table = try? String(contentsOf: url, encoding: .utf8)
        else { fatalError("emoji-suggestions.tsv is missing from the bundle") }
        return EmojiSuggestions(table: table)
    }()

    /// The emoji of an English word. The table holds lower-case words, so "Good" finds "good".
    func english(for word: String) -> [String] {
        englishTable[word.lowercased()] ?? []
    }

    /// The emoji of a Chinese word, such as a Pinyin candidate.
    func chinese(for word: String) -> [String] {
        chineseTable[word] ?? []
    }
}
