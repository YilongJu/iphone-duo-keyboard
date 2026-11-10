import Foundation

/// One word or sentence the user can pick for the letters typed so far.
struct PinyinCandidate: Equatable {
    let word: String
    /// Count of typed characters this candidate stands for. The characters after them stay in the buffer.
    let consumedLetters: Int
    /// The candidate's syllables joined with spaces, as in "ni hao". The engine learns picks by spelling.
    let spelling: String
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
///
/// Three more rules:
/// - The engine remembers each pick, and a remembered word comes first for its spelling.
/// - Letters that do not form syllables count as first letters, so "nh" offers the words whose
///   syllables start with "n" and "h".
/// - An apostrophe in the letters forces a syllable break, so "xi'an" is two syllables.
final class PinyinEngine {
    private struct Entry {
        let word: String
        /// Natural logarithm of the word's share of all word uses in the dictionary.
        let logProbability: Double
    }

    /// Entries by spelling. A spelling joins its syllables with spaces, as in "ni hao".
    private var entries: [String: [Entry]] = [:]
    /// Words of two or more syllables by the first letters of their syllables, as in "nh".
    private var wordsByFirstLetters: [String: [(word: String, spelling: String)]] = [:]
    /// Every one-syllable entry in file order, for a syllable the user has typed only in part.
    private var singles: [(syllable: String, word: String)] = []
    private var syllables: Set<String> = []
    private let longestSyllable: Int
    /// The longest word in the dictionary, counted in syllables.
    private var longestWord: Int

    /// Words the user picked, by spelling, with the latest pick first.
    private(set) var learnedWords: [String: [String]]
    private let saveLearnedWords: ([String: [String]]) -> Void

    /// A learned word counts as this likely at least. The value is above the likelihood of any
    /// two dictionary words together, which puts a learned phrase ahead of the same syllables
    /// cut into separate words.
    private static let learnedLogProbability = -1.5
    private static let learnedWordsPerSpelling = 4
    private static let learnedSpellingLimit = 3000
    /// The engine learns a phrase of this many syllables at most, so whole long sentences do not fill the store.
    static let longestLearnedPhrase = 8

    /// One syllable of the typed letters, with the count of typed characters it covers.
    /// The count includes an apostrophe typed after the syllable.
    private struct Unit {
        let syllable: String
        let characters: Int
    }

    /// Reads dictionary text with one "syllables<TAB>word<TAB>frequency" entry per line.
    /// A line that does not have these three fields stops the process, because a broken
    /// dictionary would give wrong candidates without any sign.
    init(
        dictionaryText: String,
        learnedWords: [String: [String]] = [:],
        saveLearnedWords: @escaping ([String: [String]]) -> Void = { _ in }
    ) {
        self.learnedWords = learnedWords
        self.saveLearnedWords = saveLearnedWords
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
        var longestWord = 1
        for item in parsed {
            entries[item.key, default: []].append(
                Entry(word: item.word, logProbability: log(item.frequency / total)))
            if item.key.contains(" ") {
                longestWord = max(longestWord, item.word.count)
                let firstLetters = String(item.key.split(separator: " ").compactMap { $0.first })
                wordsByFirstLetters[firstLetters, default: []].append((item.word, item.key))
            } else {
                singles.append((item.key, item.word))
                syllables.insert(item.key)
                longestSyllable = max(longestSyllable, item.key.count)
            }
        }
        // "n" and "ng" are spellings of a few rare sounds. Inside a longer spelling they would
        // split words in the wrong place, so they count as syllables only when typed alone.
        syllables.remove("n")
        syllables.remove("ng")
        self.longestSyllable = longestSyllable
        self.longestWord = max(longestWord, Self.longestLearnedPhrase)
    }

    private static let learnedWordsKey = "pinyinLearnedWords"

    /// Loads the dictionary from the bundle and the learned words from the keyboard's own
    /// settings store on the phone. The keyboard cannot offer Chinese without the dictionary
    /// file, so a missing file stops the process.
    static func bundled() -> PinyinEngine {
        guard let url = Bundle(for: PinyinEngine.self).url(forResource: "pinyin-dictionary", withExtension: "txt")
        else {
            fatalError("pinyin-dictionary.txt is missing from the bundle")
        }
        // A phone that has not learned any word yet does not have the stored value.
        let stored = UserDefaults.standard.dictionary(forKey: learnedWordsKey) as? [String: [String]] ?? [:]
        do {
            return PinyinEngine(
                dictionaryText: try String(contentsOf: url, encoding: .utf8),
                learnedWords: stored,
                saveLearnedWords: { UserDefaults.standard.set($0, forKey: learnedWordsKey) })
        } catch {
            fatalError("pinyin-dictionary.txt is unreadable: \(error)")
        }
    }

    // MARK: Syllables

    /// Splits the typed characters into whole syllables. An apostrophe forces a break.
    /// `remainder` holds the characters at the end that do not form a whole syllable yet.
    private func split(_ letters: String) -> (units: [Unit], remainder: String) {
        var units: [Unit] = []
        var rest = Substring(letters)
        while !rest.isEmpty {
            let chunkEnd = rest.firstIndex(of: "'") ?? rest.endIndex
            let chunk = Array(rest[..<chunkEnd])
            let hasApostrophe = chunkEnd < rest.endIndex
            // The chunk's longest run of whole syllables, counted from its start.
            var end = chunk.count
            var parsed: [String]?
            while end > 0 {
                parsed = parse(chunk, from: 0, to: end)
                if parsed != nil { break }
                end -= 1
            }
            let chunkSyllables = parsed ?? []
            for (index, syllable) in chunkSyllables.enumerated() {
                let isLast = index == chunkSyllables.count - 1
                let closesChunk = isLast && end == chunk.count && hasApostrophe
                units.append(Unit(syllable: syllable, characters: syllable.count + (closesChunk ? 1 : 0)))
            }
            if end < chunk.count {
                // Letters that are not a whole syllable end the split.
                let consumed = chunkSyllables.reduce(0) { $0 + $1.count }
                return (units, String(rest.dropFirst(consumed)))
            }
            rest = hasApostrophe ? rest[rest.index(after: chunkEnd)...] : rest[chunkEnd...]
        }
        return (units, "")
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

    /// The whole syllables of the typed characters, and the characters after them.
    func segment(_ letters: String) -> (syllables: [String], remainder: String) {
        let (units, remainder) = split(letters)
        return (units.map { $0.syllable }, remainder)
    }

    /// The typed letters with a mark between syllables, as in "ni'hao", for the candidate bar.
    func display(for letters: String) -> String {
        let (units, remainder) = split(letters)
        let rest = remainder.replacingOccurrences(of: "'", with: "")
        return (units.map { $0.syllable } + (rest.isEmpty ? [] : [rest])).joined(separator: "'")
    }

    // MARK: Words

    /// The words for a spelling: the learned words first, then the dictionary's words.
    private func words(for spelling: String) -> [String] {
        let learned = learnedWords[spelling] ?? []
        let known = (entries[spelling] ?? []).map { $0.word }.filter { !learned.contains($0) }
        return learned + known
    }

    /// The most likely word for a spelling and its likelihood, or nil for an unknown spelling.
    private func topWord(for spelling: String) -> Entry? {
        let top = entries[spelling]?.first
        guard let learned = learnedWords[spelling]?.first else { return top }
        return Entry(word: learned, logProbability: max(top?.logProbability ?? Self.learnedLogProbability, Self.learnedLogProbability))
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
                    let top = topWord(for: syllables[start..<end].joined(separator: " "))
                else { continue }
                let logProbability = prefix.logProbability + top.logProbability
                if let current = best[end], current.logProbability >= logProbability { continue }
                best[end] = (prefix.text + top.word, logProbability)
            }
        }
        return best[syllables.count]?.text
    }

    /// Candidates for the typed letters, in this order: the most likely sentence for all
    /// syllables, the words for all syllables, words for fewer leading syllables down to single
    /// characters, and the words whose syllables start with the typed letters.
    func candidates(for letters: String, limit: Int = 60) -> [PinyinCandidate] {
        let (units, remainder) = split(letters)
        var result: [PinyinCandidate] = []
        var seen: Set<String> = []
        func add(_ word: String, consumed: Int, spelling: String) {
            guard result.count < limit, seen.insert(word).inserted else { return }
            result.append(PinyinCandidate(word: word, consumedLetters: consumed, spelling: spelling))
        }
        func addFirstLetterWords() {
            let firstLetters = letters.replacingOccurrences(of: "'", with: "")
            guard firstLetters.count >= 2 else { return }
            for match in wordsByFirstLetters[firstLetters] ?? [] {
                if result.count >= limit { break }
                add(match.word, consumed: letters.count, spelling: match.spelling)
            }
        }
        if units.isEmpty {
            // The letters do not start with a whole syllable, as in "nh" or "zh".
            addFirstLetterWords()
            if remainder == "n" || remainder == "ng" {
                for word in words(for: remainder) { add(word, consumed: remainder.count, spelling: remainder) }
            }
            for single in singles where single.syllable.hasPrefix(remainder) {
                if result.count >= limit { break }
                add(single.word, consumed: remainder.count, spelling: single.syllable)
            }
            return result
        }
        let parsed = units.map { $0.syllable }
        let allCharacters = units.reduce(0) { $0 + $1.characters }
        if let sentence = sentence(for: parsed) {
            add(sentence, consumed: allCharacters, spelling: parsed.joined(separator: " "))
        }
        var count = units.count
        while count > 0 {
            let spelling = parsed[0..<count].joined(separator: " ")
            let consumed = units[0..<count].reduce(0) { $0 + $1.characters }
            for word in words(for: spelling) {
                add(word, consumed: consumed, spelling: spelling)
            }
            count -= 1
        }
        addFirstLetterWords()
        return result
    }

    // MARK: Learning

    /// Remembers that the user picked `word` for `spelling`. The word then comes first for
    /// that spelling, and the sentence search prefers the word.
    func learn(spelling: String, word: String) {
        let syllableCount = spelling.split(separator: " ").count
        guard syllableCount >= 1, syllableCount <= Self.longestLearnedPhrase, syllableCount == word.count else { return }
        var words = learnedWords[spelling] ?? []
        if words.first == word { return }
        words.removeAll { $0 == word }
        words.insert(word, at: 0)
        if learnedWords[spelling] == nil, learnedWords.count >= Self.learnedSpellingLimit {
            // The store is full, so one stored spelling makes room. Dictionary order is arbitrary.
            if let dropped = learnedWords.keys.first { learnedWords[dropped] = nil }
        }
        learnedWords[spelling] = Array(words.prefix(Self.learnedWordsPerSpelling))
        saveLearnedWords(learnedWords)
    }
}
