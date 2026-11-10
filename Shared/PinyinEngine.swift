import Foundation

/// One word or sentence the user can pick for the letters typed so far.
struct PinyinCandidate: Equatable {
    let word: String
    /// Count of typed letters this candidate stands for. The letters after them stay in the buffer.
    let consumedLetters: Int
}

/// Turns typed Pinyin letters into Simplified Chinese candidates.
///
/// The words come from `pinyin-dictionary.txt`, built from the Android Open Source Project's
/// Pinyin dictionary. Each line holds a spelling, a word and the word's frequency, with the most
/// frequent word first.
///
/// The first candidate is a whole sentence: the engine cuts all typed syllables into dictionary
/// words in the most likely way, where the likelihood of a cut is the product of its words'
/// frequencies. The candidates after that are single words for the leading syllables. A pick of
/// a shorter word leaves the other letters in the buffer, and the engine converts those again.
final class PinyinEngine {
    private struct Entry {
        let word: String
        /// Natural logarithm of the word's share of all word uses in the dictionary.
        let logProbability: Double
    }

    /// Entries by spelling. A spelling joins its syllables with spaces, as in "ni hao".
    private var entries: [String: [Entry]] = [:]
    /// Every one-syllable entry in file order, for a syllable the user has typed only in part.
    private var singles: [(syllable: String, word: String)] = []
    private var syllables: Set<String> = []
    private let longestSyllable: Int
    /// The longest word in the dictionary, counted in syllables.
    private let longestWord: Int

    /// Reads dictionary text with one "syllables<TAB>word<TAB>frequency" entry per line.
    /// A line that does not have these three fields stops the process, because a broken
    /// dictionary would give wrong candidates without any sign.
    init(dictionaryText: String) {
        var parsed: [(key: String, word: String, frequency: Double)] = []
        var total = 0.0
        for line in dictionaryText.split(separator: "\n") {
            let fields = line.split(separator: "\t")
            guard fields.count == 3, let frequency = Double(fields[2]), frequency > 0 else {
                fatalError("Bad dictionary line: \(line)")
            }
            parsed.append((String(fields[0]), String(fields[1]), frequency))
            total += frequency
        }
        var longestSyllable = 0
        var longestWord = 0
        for item in parsed {
            entries[item.key, default: []].append(
                Entry(word: item.word, logProbability: log(item.frequency / total)))
            if item.key.contains(" ") {
                longestWord = max(longestWord, item.word.count)
            } else {
                singles.append((item.key, item.word))
                syllables.insert(item.key)
                longestSyllable = max(longestSyllable, item.key.count)
                longestWord = max(longestWord, 1)
            }
        }
        // "n" and "ng" are spellings of a few rare sounds. Inside a longer spelling they would
        // split words in the wrong place, so they count as syllables only when typed alone.
        syllables.remove("n")
        syllables.remove("ng")
        self.longestSyllable = longestSyllable
        self.longestWord = longestWord
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

    /// The most likely sentence for the syllables, or nil when some syllable has no word at all.
    /// `best[i]` holds the most likely text for the first `i` syllables.
    func sentence(for syllables: [String]) -> String? {
        guard !syllables.isEmpty else { return nil }
        var best: [(text: String, logProbability: Double)?] = Array(repeating: nil, count: syllables.count + 1)
        best[0] = ("", 0)
        for end in 1...syllables.count {
            let earliestStart = max(0, end - longestWord)
            for start in earliestStart..<end {
                guard let prefix = best[start],
                    let top = entries[syllables[start..<end].joined(separator: " ")]?.first
                else { continue }
                let logProbability = prefix.logProbability + top.logProbability
                if let current = best[end], current.logProbability >= logProbability { continue }
                best[end] = (prefix.text + top.word, logProbability)
            }
        }
        return best[syllables.count]?.text
    }

    /// Candidates for the typed letters: first the most likely sentence for all syllables, then
    /// the words for all syllables, then words for fewer leading syllables, down to single
    /// characters for the first syllable.
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
                for entry in entries[remainder] ?? [] { add(entry.word, consumed: remainder.count) }
            }
            for single in singles where single.syllable.hasPrefix(remainder) {
                if result.count >= limit { break }
                add(single.word, consumed: remainder.count)
            }
            return result
        }
        let allLetters = parsed.reduce(0) { $0 + $1.count }
        if let sentence = sentence(for: parsed) {
            add(sentence, consumed: allLetters)
        }
        var count = parsed.count
        while count > 0 {
            let leading = parsed[0..<count]
            let consumed = leading.reduce(0) { $0 + $1.count }
            for entry in entries[leading.joined(separator: " ")] ?? [] {
                add(entry.word, consumed: consumed)
            }
            count -= 1
        }
        return result
    }
}
