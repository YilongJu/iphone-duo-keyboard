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

/// English autocorrection through the C typing engine.
final class EnglishTypingEngine {
    /// The mapped lexicon file. The engine's tables point into its bytes.
    private let lexicon: TypingLexicon
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
    init(lexicon: TypingLexicon, supplement: TypingLexicon? = nil) {
        self.lexicon = lexicon
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
    /// `typed` when the engine reads the text as typed.
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

    /// The readings of typed text that the engine's search keeps, best score first, up to
    /// `limit`: the text as typed, and the best reading for each last word. Exactly one reading
    /// is the text as typed, and exactly one is the reading that `reading` returns. The input
    /// rules are those of `reading`, and the result is nil for text outside them.
    func readings(previousWord: String, typed: String, limit: Int) -> [EnglishReading]? {
        precondition(limit >= 2, "the list holds the text as typed and the engine's choice")
        var buffer = [duo_reading](repeating: duo_reading(), count: limit)
        let count = buffer.withUnsafeMutableBufferPointer { pointer in
            duo_english_readings(&tables, &params, previousWord, typed, pointer.baseAddress, Int32(limit))
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
