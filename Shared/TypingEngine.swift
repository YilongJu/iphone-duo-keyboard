import Foundation

/// A lexicon file of the C typing engine (Engine/duo_engine.c), mapped into memory.
///
/// The file stays on disk and iOS reads its pages when the engine touches them, so a large
/// lexicon does not count against the keyboard's memory limit the way loaded data does.
final class TypingLexicon {
    /// The mapped file. The C lexicon points into these bytes, so the object keeps them alive.
    private let file: NSData
    fileprivate var lexicon = duo_lexicon()

    /// Maps `<resource>.bin` from the bundle. The keyboard cannot type without its lexicon, so
    /// a missing or invalid file stops the process.
    ///
    /// `fullCheck` reads the whole file once and proves that the engine cannot read outside it.
    /// The unit tests run the full check on the files that ship. The app opens the same files
    /// without it, because the full check costs time at every keyboard launch.
    init(resource: String, fullCheck: Bool) {
        guard let url = Bundle(for: TypingLexicon.self).url(forResource: resource, withExtension: "bin") else {
            fatalError("\(resource).bin is missing from the bundle")
        }
        do {
            file = try NSData(contentsOf: url, options: .alwaysMapped)
        } catch {
            fatalError("\(resource).bin is unreadable: \(error)")
        }
        let opened = fullCheck
            ? duo_lexicon_open(&lexicon, file.bytes, file.length)
            : duo_lexicon_open_checked_before(&lexicon, file.bytes, file.length)
        guard opened == 1 else {
            fatalError("\(resource).bin is not a valid lexicon file")
        }
    }

    fileprivate static func text(of result: inout duo_result) -> String {
        withUnsafePointer(to: &result.text) { pointer in
            pointer.withMemoryRebound(to: CChar.self, capacity: Int(DUO_TEXT_SIZE)) { String(cString: $0) }
        }
    }
}

/// A word table of the C typing engine (`duo_word_table`), mapped into memory. For each word of
/// the English lexicon and of the work area's supplement, and for each form of the word, the
/// table holds the first token that the language model reads for the form, and the word share.
/// The engine orders the predicted words by the model's numbers with it
/// (`duo_predict_english_with_model`). scripts/typing-engine/build_word_table.py writes the file.
final class WordTable {
    /// The mapped file. The C table points into these bytes, so the object keeps them alive.
    private let file: NSData
    fileprivate var table = duo_word_table()

    /// Maps `<resource>.bin` from the bundle. The file ships inside the app, so a missing or
    /// invalid file is a fault of the build and stops the process.
    init(resource: String) {
        guard let url = Bundle(for: WordTable.self).url(forResource: resource, withExtension: "bin") else {
            fatalError("\(resource).bin is missing from the bundle")
        }
        do {
            file = try NSData(contentsOf: url, options: .alwaysMapped)
        } catch {
            fatalError("\(resource).bin is unreadable: \(error)")
        }
        guard duo_word_table_open(&table, file.bytes, file.length) == 1 else {
            fatalError("\(resource).bin is not a valid word table")
        }
    }

    /// Count of tokens of the vocabulary that the table belongs to.
    var vocabulary: Int { Int(table.vocabulary) }
}

/// English autocorrection through the C typing engine.
final class EnglishTypingEngine {
    /// The mapped lexicon file. The engine's tables point into its bytes.
    private let lexicon: TypingLexicon
    /// The word table for the model's order of the predicted words, or nil for an engine that
    /// orders them by its own statistics only.
    private let wordTable: WordTable?
    /// The engine's own copy of the lexicon's tables, with the supplement laid over them. Two
    /// engines can share one lexicon file and differ in their supplement.
    private var tables: duo_lexicon
    /// The supplement that is laid over the lexicon now, or nil.
    private(set) var supplement: TypingLexicon?
    /// The supplement's tables at a fixed place in memory, because the C engine keeps a pointer
    /// to them for as long as the supplement is on.
    private let supplementTables = UnsafeMutablePointer<duo_lexicon>.allocate(capacity: 1)
    private var params = duo_english_params()

    /// `supplement` is a small lexicon of words that the main lexicon lacks or holds at too low
    /// a frequency, as the words of a work area (`duo_lexicon_set_supplement`).
    init(lexicon: TypingLexicon, supplement: TypingLexicon? = nil, wordTable: WordTable? = nil) {
        self.lexicon = lexicon
        self.wordTable = wordTable
        tables = lexicon.lexicon
        supplementTables.initialize(to: duo_lexicon())
        setSupplement(supplement)
    }

    deinit {
        supplementTables.deinitialize(count: 1)
        supplementTables.deallocate()
    }

    /// Lays a supplement over the lexicon, or takes the supplement off with nil. A file that
    /// the engine refuses as a supplement is a fault of the build, so it stops the process.
    func setSupplement(_ supplement: TypingLexicon?) {
        self.supplement = supplement
        guard let supplement else {
            duo_lexicon_set_supplement(&tables, nil)
            return
        }
        supplementTables.pointee = supplement.lexicon
        guard duo_lexicon_set_supplement(&tables, supplementTables) == 1 else {
            fatalError("the supplement is not a valid supplement of the English lexicon")
        }
    }

    /// Reads typed text and returns the text the person most likely meant. The result equals
    /// `typed` when the engine reads the text as typed. The engine reads the text as text that
    /// the person ends with a space, so the result can end in a comma that takes the place of the
    /// last typed letter, as "hello," for "hellom".
    ///
    /// `typed` holds one or two words in lower case: letters, apostrophes and single spaces.
    /// A word of two or more letters may also hold one symbol or digit key that sits beside a
    /// letter key, which the engine reads as a slip for that letter or as typed on purpose.
    /// `previousWord` is the word before the typed text, in lower case, or an empty string.
    /// Text with any other character is outside the engine's input, and the result is nil.
    func reading(previousWord: String, typed: String) -> String? {
        var result = duo_result()
        guard duo_correct_english(&tables, &params, previousWord, typed, &result) == 1 else { return nil }
        return TypingLexicon.text(of: &result)
    }

    /// The readings of typed text that the person ends with a space: `readings` with
    /// `endsWithSpace` true.
    func readings(previousWord: String, typed: String, limit: Int) -> [EnglishReading]? {
        readings(previousWord: previousWord, typed: typed, limit: limit, endsWithSpace: true)
    }

    /// The readings of typed text that the engine's search keeps, best score first, up to
    /// `limit`: the text as typed, and the best reading for each last word. Exactly one reading
    /// is the text as typed, and exactly one is the reading that `reading` returns for the same
    /// text before a space. The input rules are those of `reading`, and the result is nil for
    /// text outside them.
    ///
    /// `endsWithSpace` says that the person typed a space after the text. Only then does the
    /// engine also read the last typed letter as a slip for the comma key beside it, as "hello,"
    /// for "hellom" (`last_letter_as_comma`). A person who ends the text with a mark or a line
    /// break did not mean a comma right before it.
    func readings(previousWord: String, typed: String, limit: Int, endsWithSpace: Bool) -> [EnglishReading]? {
        precondition(limit >= 2, "the list holds the text as typed and the engine's choice")
        var buffer = [duo_reading](repeating: duo_reading(), count: limit)
        var callParams = params
        callParams.last_letter_as_comma = endsWithSpace ? 1 : 0
        let count = buffer.withUnsafeMutableBufferPointer { pointer in
            duo_english_readings(&tables, &callParams, previousWord, typed, pointer.baseAddress, Int32(limit))
        }
        guard count > 0 else { return nil }
        let readings = (0..<Int(count)).map { index in
            EnglishReading(
                text: withUnsafePointer(to: &buffer[index].text) { pointer in
                    pointer.withMemoryRebound(to: CChar.self, capacity: Int(DUO_TEXT_SIZE)) { String(cString: $0) }
                },
                score: Double(buffer[index].score), slipCost: Double(buffer[index].slip_cost),
                asTyped: buffer[index].as_typed == 1, chosen: buffer[index].chosen == 1)
        }
        // Engine/duo_engine.h promises both marks. A list without them is a fault of the engine.
        precondition(readings.filter { $0.chosen }.count == 1, "readings of \(typed) need one chosen reading")
        precondition(readings.filter { $0.asTyped }.count == 1, "readings of \(typed) need the text as typed")
        return readings
    }

    /// The words of the lexicon and its supplement that start with the letters `typed` and are
    /// longer than them, most probable first after the word `previousWord`, up to `limit` words
    /// (`duo_predict_english`). The prediction strip shows these words.
    ///
    /// `typed` holds lower-case letters and apostrophes, and `previousWord` is the word before
    /// them in lower case, or an empty string. Other typed text, and more letters than the
    /// engine reads, give no words.
    func predictedWords(previousWord: String, typed: String, limit: Int) -> [String] {
        guard limit > 0 else { return [] }
        var buffer = [duo_predicted_word](repeating: duo_predicted_word(), count: limit)
        let count = buffer.withUnsafeMutableBufferPointer { pointer in
            duo_predict_english(&tables, &params, previousWord, typed, pointer.baseAddress, Int32(limit))
        }
        return (0..<Int(count)).map { index in
            withUnsafePointer(to: &buffer[index].text) { pointer in
                pointer.withMemoryRebound(to: CChar.self, capacity: Int(DUO_PREDICTED_WORD_SIZE)) { String(cString: $0) }
            }
        }
    }

    /// One predicted word in the order of the language model: the word as the lexicon holds it,
    /// and the form with the highest value for the model, one of `DUO_FORM_LOWER`,
    /// `DUO_FORM_CAPITAL` and `DUO_FORM_PREFERRED`.
    struct ModelWord: Equatable {
        let word: String
        let form: Int32
    }

    /// The predicted words in the order of the language model (`duo_predict_english_with_model`),
    /// highest value first, up to `limit` words. `next` holds the model's log probability of
    /// every token right after the text before the word. `engineWeight` is the share of the
    /// engine's own value in the order, from 0 to 1. With `capitalOnly`, only a form that starts
    /// with a capital counts.
    ///
    /// The result is nil for an engine without a word table, and for numbers of another
    /// vocabulary than the table's. Typed text outside the engine's input gives no words.
    func predictedWords(
        previousWord: String, typed: String, next: [Float], engineWeight: Float, capitalOnly: Bool, limit: Int
    ) -> [ModelWord]? {
        guard let wordTable, limit > 0, next.count == wordTable.vocabulary else { return nil }
        var buffer = [duo_predicted_word](repeating: duo_predicted_word(), count: limit)
        let count = next.withUnsafeBufferPointer { numbers in
            buffer.withUnsafeMutableBufferPointer { pointer in
                duo_predict_english_with_model(
                    &tables, &params, &wordTable.table, numbers.baseAddress, Int32(next.count), engineWeight,
                    previousWord, typed, capitalOnly ? 1 : 0, pointer.baseAddress, Int32(limit))
            }
        }
        return (0..<Int(count)).map { index in
            let text = withUnsafePointer(to: &buffer[index].text) { pointer in
                pointer.withMemoryRebound(to: CChar.self, capacity: Int(DUO_PREDICTED_WORD_SIZE)) { String(cString: $0) }
            }
            return ModelWord(word: text, form: buffer[index].form)
        }
    }

    /// The first token of a form of a word in the word table, or nil when the engine has no
    /// table, does not hold the word, or the word has no such form. The unit tests build the
    /// numbers of a model with it.
    func firstToken(ofWord word: String, form: Int32) -> Int? {
        guard let wordTable else { return nil }
        let token = duo_word_table_token(&tables, &wordTable.table, word, form)
        return token >= 0 ? Int(token) : nil
    }

    /// True when the word table was built for the words of this lexicon and of the supplement
    /// that is laid over it now: the table's hash of all word texts equals theirs. The unit
    /// tests check the files that ship. The engine itself compares only the counts of words.
    var wordTableBelongsToTheLexicon: Bool {
        guard let wordTable else { return false }
        return duo_word_table_hash(&tables) == wordTable.table.words_hash
    }

    /// Count of tokens of the vocabulary of the word table, or nil without a table.
    var wordTableVocabulary: Int? { wordTable?.vocabulary }
}

/// One reading of typed Pinyin letters by the C typing engine.
struct PinyinReading {
    let text: String
    /// Count of typed letters the reading stands for, from the first letter on.
    let consumedLetters: Int
    /// Natural logarithm of the reading's likelihood, less the cost of the slips it assumes.
    let score: Float
}

/// Pinyin conversion through the C typing engine.
final class PinyinTypingEngine {
    private let lexicon: TypingLexicon
    private var params = duo_pinyin_params()

    init(lexicon: TypingLexicon) {
        self.lexicon = lexicon
    }

    /// Reads typed Pinyin letters and returns candidates. The first candidate reads all the
    /// letters as one sentence, slips included. The candidates after it are words for the first
    /// letters only, longest first. The list is empty for text that is not all letters a to z.
    func candidates(for letters: String, limit: Int) -> [PinyinReading] {
        guard limit > 0 else { return [] }
        var results = [duo_result](repeating: duo_result(), count: limit)
        let count = results.withUnsafeMutableBufferPointer { buffer in
            duo_convert_pinyin(&lexicon.lexicon, &params, letters, buffer.baseAddress, Int32(limit))
        }
        return (0..<Int(count)).map { index in
            PinyinReading(
                text: TypingLexicon.text(of: &results[index]),
                consumedLetters: Int(results[index].consumed), score: results[index].score)
        }
    }
}
