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
    private let lexicon: TypingLexicon
    private var params = duo_english_params()

    init(lexicon: TypingLexicon) {
        self.lexicon = lexicon
    }

    /// Reads typed text and returns the text the person most likely meant. The result equals
    /// `typed` when the engine reads the text as typed.
    ///
    /// `typed` holds one or two words in lower case: letters, apostrophes and single spaces.
    /// `previousWord` is the word before the typed text, in lower case, or an empty string.
    /// Text with any other character is outside the engine's input, and the result is nil.
    func reading(previousWord: String, typed: String) -> String? {
        var result = duo_result()
        guard duo_correct_english(&lexicon.lexicon, &params, previousWord, typed, &result) == 1 else { return nil }
        return TypingLexicon.text(of: &result)
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
