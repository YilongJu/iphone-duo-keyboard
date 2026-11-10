import Foundation

/// One word the user can pick for the letters typed so far.
struct PinyinCandidate: Equatable {
    let word: String
    /// Count of typed letters this word stands for. The letters after them stay in the buffer.
    let consumedLetters: Int
}

/// Turns typed Pinyin letters into Simplified Chinese candidates.
///
/// The words come from `pinyin-dictionary.txt`, built from the Android Open Source Project's
/// Pinyin dictionary. The file lists the most frequent word first, and the engine keeps that order.
final class PinyinEngine {
    /// Words by spelling. A spelling joins its syllables with spaces, as in "ni hao".
    private var words: [String: [String]] = [:]
    /// Every one-syllable entry in file order, for a syllable the user has typed only in part.
    private var singles: [(syllable: String, word: String)] = []
    private var syllables: Set<String> = []
    private let longestSyllable: Int

    /// Reads dictionary text with one "syllables<TAB>word" entry per line.
    init(dictionaryText: String) {
        var longest = 0
        for line in dictionaryText.split(separator: "\n") {
            guard let tab = line.firstIndex(of: "\t") else { continue }
            let key = String(line[..<tab])
            let word = String(line[line.index(after: tab)...])
            words[key, default: []].append(word)
            if !key.contains(" ") {
                singles.append((key, word))
                syllables.insert(key)
                longest = max(longest, key.count)
            }
        }
        // "n" and "ng" are spellings of a few rare sounds. Inside a longer spelling they would
        // split words in the wrong place, so they count as syllables only when typed alone.
        syllables.remove("n")
        syllables.remove("ng")
        longestSyllable = longest
    }

    /// Loads the dictionary from the bundle. The keyboard cannot offer Chinese without the file,
    /// so a missing file stops the process.
    static func bundled() -> PinyinEngine {
        guard let url = Bundle(for: PinyinEngine.self).url(forResource: "pinyin-dictionary", withExtension: "txt")
        else {
            fatalError("pinyin-dictionary.txt is missing from the bundle")
        }
        do {
            return PinyinEngine(dictionaryText: try String(contentsOf: url, encoding: .utf8))
        } catch {
            fatalError("pinyin-dictionary.txt is unreadable: \(error)")
        }
    }

    /// Splits letters into whole syllables. `remainder` holds the letters at the end that do not
    /// form a whole syllable yet. The split covers as many letters as possible, and at each
    /// place it tries the longest syllable first.
    func segment(_ letters: String) -> (syllables: [String], remainder: String) {
        let characters = Array(letters)
        var end = characters.count
        while end > 0 {
            if let parsed = parse(characters, from: 0, to: end) {
                return (parsed, String(characters[end...]))
            }
            end -= 1
        }
        return ([], letters)
    }

    private func parse(_ characters: [Character], from start: Int, to end: Int) -> [String]? {
        if start == end { return [] }
        var length = min(longestSyllable, end - start)
        while length > 0 {
            let syllable = String(characters[start..<(start + length)])
            if syllables.contains(syllable), let rest = parse(characters, from: start + length, to: end) {
                return [syllable] + rest
            }
            length -= 1
        }
        return nil
    }

    /// The typed letters with a mark between syllables, as in "ni'hao", for the candidate bar.
    func display(for letters: String) -> String {
        let (parsed, remainder) = segment(letters)
        return (parsed + (remainder.isEmpty ? [] : [remainder])).joined(separator: "'")
    }

    /// Candidates for the typed letters: first the words for all syllables, then words for fewer
    /// leading syllables, down to single characters for the first syllable.
    func candidates(for letters: String, limit: Int = 60) -> [PinyinCandidate] {
        let (parsed, remainder) = segment(letters)
        var result: [PinyinCandidate] = []
        var seen: Set<String> = []
        func add(_ word: String, consumed: Int) {
            guard result.count < limit, seen.insert(word).inserted else { return }
            result.append(PinyinCandidate(word: word, consumedLetters: consumed))
        }
        if parsed.isEmpty {
            // The first syllable is incomplete, as in "zh". Offer the characters whose syllable starts that way.
            if remainder == "n" || remainder == "ng" {
                for word in words[remainder] ?? [] { add(word, consumed: remainder.count) }
            }
            for single in singles where single.syllable.hasPrefix(remainder) {
                if result.count >= limit { break }
                add(single.word, consumed: remainder.count)
            }
            return result
        }
        var count = parsed.count
        while count > 0 {
            let leading = parsed[0..<count]
            let consumed = leading.reduce(0) { $0 + $1.count }
            for word in words[leading.joined(separator: " ")] ?? [] {
                add(word, consumed: consumed)
            }
            count -= 1
        }
        return result
    }
}
