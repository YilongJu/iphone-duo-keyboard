import XCTest

@testable import DuoKeyboard

/// Tests of the C typing engine through its Swift wrappers, on the lexicon files that ship.
@MainActor
final class TypingEngineTests: XCTestCase {
    private static let english = EnglishTypingEngine(lexicon: TypingLexicon(resource: "lexicon-english", fullCheck: false))
    private static let pinyin = PinyinTypingEngine(lexicon: TypingLexicon(resource: "lexicon-pinyin", fullCheck: false))

    /// The app opens its lexicon files without the full check. This test runs the full check on
    /// the same files, which proves that the engine cannot read outside them. A file that does
    /// not pass stops the test process.
    func testTheBundledLexiconsPassTheFullCheck() {
        _ = TypingLexicon(resource: "lexicon-english", fullCheck: true)
        _ = TypingLexicon(resource: "lexicon-pinyin", fullCheck: true)
    }

    func testEnglishReadsAKnownWordAsTyped() {
        XCTAssertEqual(Self.english.reading(previousWord: "", typed: "the"), "the")
        XCTAssertEqual(Self.english.reading(previousWord: "", typed: "good morning"), "good morning")
    }

    func testEnglishRepairsLetterSlips() {
        XCTAssertEqual(Self.english.reading(previousWord: "", typed: "teh"), "the")
        XCTAssertEqual(Self.english.reading(previousWord: "will", typed: "recieve"), "receive")
        XCTAssertEqual(Self.english.reading(previousWord: "", typed: "hello wrold"), "hello world")
        XCTAssertEqual(Self.english.reading(previousWord: "", typed: "dont"), "don't")
    }

    func testEnglishRepairsSlipsAroundTheSpaceBar() {
        XCTAssertEqual(Self.english.reading(previousWord: "", typed: "thequick"), "the quick")
        XCTAssertEqual(Self.english.reading(previousWord: "", typed: "th e"), "the")
        XCTAssertEqual(Self.english.reading(previousWord: "", typed: "tob e"), "to be")
        XCTAssertEqual(Self.english.reading(previousWord: "the", typed: "qu ick"), "quick")
    }

    func testEnglishKeepsTextItCannotRead() {
        // A capital, two digits in one word and a double space are outside the engine's input.
        XCTAssertNil(Self.english.reading(previousWord: "", typed: "Teh"))
        XCTAssertNil(Self.english.reading(previousWord: "", typed: "teh22"))
        XCTAssertNil(Self.english.reading(previousWord: "", typed: "th  e"))
        XCTAssertNil(Self.english.reading(previousWord: "", typed: ""))
    }

    func testEnglishRepairsASymbolOrDigitKeyInPlaceOfTheFirstLetter() {
        XCTAssertEqual(Self.english.reading(previousWord: "", typed: "[lease"), "please")
        XCTAssertEqual(Self.english.reading(previousWord: "", typed: "0lease"), "please")
        XCTAssertEqual(Self.english.reading(previousWord: "", typed: "-lease"), "please")
        XCTAssertEqual(Self.english.reading(previousWord: "i", typed: ";ike"), "like")
        XCTAssertEqual(Self.english.reading(previousWord: "", typed: ",ore"), "more")
        XCTAssertEqual(Self.english.reading(previousWord: "", typed: "2hat"), "what")
        XCTAssertEqual(Self.english.reading(previousWord: "", typed: "hello [lease"), "hello please")
        XCTAssertEqual(Self.english.reading(previousWord: "", typed: "tell ;ike"), "tell like")
    }

    func testEnglishRepairsADigitOrABracketInsideAWord() {
        XCTAssertEqual(Self.english.reading(previousWord: "", typed: "wh3n"), "when")
        XCTAssertEqual(Self.english.reading(previousWord: "", typed: "y0u"), "you")
        XCTAssertEqual(Self.english.reading(previousWord: "", typed: "sho2"), "show")
        XCTAssertEqual(Self.english.reading(previousWord: "", typed: "hel["), "help")
        XCTAssertEqual(Self.english.reading(previousWord: "", typed: "peo[le"), "people")
    }

    func testEnglishKeepsASymbolOrDigitTypedOnPurpose() {
        for typed in ["[note", "[art", "[it", ".net", ".com", ",and", ",but", "-ish", "2nd", "3rd", "7am", "4am", "5pm", "mp3", "h2o"] {
            XCTAssertEqual(Self.english.reading(previousWord: "", typed: typed), typed)
        }
        // A word after an opening bracket is still repaired, and the bracket stays.
        XCTAssertEqual(Self.english.reading(previousWord: "", typed: "[teh"), "[the")
    }

    func testEnglishNeverDropsATypedSymbol() {
        // "[please" without the bracket is "please", and the engine does not read it that way.
        for typed in ["[please", "p[lease", "pp[lease", "a[pple", "app[le", "0open", "to0o"] {
            XCTAssertEqual(Self.english.reading(previousWord: "", typed: typed), typed)
        }
        // The same letters with the symbol key in place of one of them are repaired.
        XCTAssertEqual(Self.english.reading(previousWord: "", typed: "a[ple"), "apple")
        XCTAssertEqual(Self.english.reading(previousWord: "", typed: "ap[le"), "apple")
    }

    func testEnglishRefusesTextWithOtherSymbols() {
        // More than one symbol key in a word, fewer than two letters beside a symbol key, a
        // punctuation key after the first place, and a key that is not beside a letter.
        for typed in ["a1b2", "[[teh", "[a", "4k", "a;b", "teh;", "te-h", "te#h", "teh [a"] {
            XCTAssertNil(Self.english.reading(previousWord: "", typed: typed), typed)
        }
    }

    func testPinyinReadsASentence() {
        let readings = Self.pinyin.candidates(for: "jintiantianqizenmeyang", limit: 10)
        XCTAssertEqual(readings.first?.text, "\u{4ECA}\u{5929}\u{5929}\u{6C14}\u{600E}\u{4E48}\u{6837}")
        XCTAssertEqual(readings.first?.consumedLetters, 22)
    }

    func testPinyinRepairsSlipsInALongSentence() {
        // "zenmyang" misses a letter, "shoujj" holds a wrong letter, and "nihsi" holds two swapped letters.
        XCTAssertEqual(
            Self.pinyin.candidates(for: "jintiantianqizenmyang", limit: 1).first?.text,
            "\u{4ECA}\u{5929}\u{5929}\u{6C14}\u{600E}\u{4E48}\u{6837}")
        XCTAssertEqual(
            Self.pinyin.candidates(for: "woxiangmaiyigexindeshoujj", limit: 1).first?.text,
            "\u{6211}\u{60F3}\u{4E70}\u{4E00}\u{4E2A}\u{65B0}\u{7684}\u{624B}\u{673A}")
        XCTAssertEqual(Self.pinyin.candidates(for: "nihsi", limit: 1).first?.text, "\u{4F60}\u{662F}")
    }

    func testPinyinWordsThatMatchTheLettersComeBeforeRepairedWords() {
        let readings = Self.pinyin.candidates(for: "nihao", limit: 6)
        XCTAssertEqual(readings.first?.text, "\u{4F60}\u{597D}")
        XCTAssertEqual(readings.first?.consumedLetters, 5)
        // The words for "ni" follow the words for "nihao". A word for other letters, such as
        // "bihao", does not stand between them.
        XCTAssertTrue(readings.dropFirst(2).allSatisfy { $0.consumedLetters == 2 }, "\(readings)")
        XCTAssertTrue(readings.contains { $0.text == "\u{4F60}" })
    }

    func testPinyinKeepsTextItCannotRead() {
        XCTAssertTrue(Self.pinyin.candidates(for: "ni'hao", limit: 5).isEmpty)
        XCTAssertTrue(Self.pinyin.candidates(for: "", limit: 5).isEmpty)
        XCTAssertTrue(Self.pinyin.candidates(for: "nihao", limit: 0).isEmpty)
    }

    // MARK: The candidate list of the keyboard

    private func bundledEngine() -> PinyinEngine {
        let url = Bundle(for: PinyinEngine.self).url(forResource: "pinyin-dictionary", withExtension: "txt")!
        let engine = PinyinEngine(dictionaryText: try! String(contentsOf: url, encoding: .utf8))
        engine.decoder = Self.pinyin
        return engine
    }

    func testALongSentenceWithASlipAtItsEndIsRepaired() {
        let first = bundledEngine().candidates(for: "woxiangmaiyigexindeshoujj").first
        XCTAssertEqual(first?.word, "\u{6211}\u{60F3}\u{4E70}\u{4E00}\u{4E2A}\u{65B0}\u{7684}\u{624B}\u{673A}")
        XCTAssertEqual(first?.consumedLetters, 25)
    }

    func testLettersOfAnUnfinishedSyllableStayInTheBuffer() {
        let engine = bundledEngine()
        // "h" may start the next syllable, so the first candidate does not use the letter up.
        XCTAssertEqual(engine.candidates(for: "nih").first, PinyinCandidate(word: "\u{4F60}", consumedLetters: 2, spelling: "ni"))
        // "tq" are the first letters of the next word.
        XCTAssertEqual(engine.candidates(for: "jintiantq").first, PinyinCandidate(word: "\u{4ECA}\u{5929}", consumedLetters: 7, spelling: "jintian"))
    }

    func testLettersAtTheEndThatChangeTheTextAreReadAsASlip() {
        let engine = bundledEngine()
        let wrongKey = engine.candidates(for: "nihap")
        XCTAssertEqual(wrongKey.first?.word, "\u{4F60}\u{597D}")
        XCTAssertEqual(wrongKey.first?.consumedLetters, 5)
        // The reading of the whole syllables alone comes second, and it leaves "p" in the buffer.
        XCTAssertEqual(wrongKey.dropFirst().first?.consumedLetters, 4)
        let missingLetter = engine.candidates(for: "shouj").first
        XCTAssertEqual(missingLetter?.word, "\u{624B}\u{673A}")
        XCTAssertEqual(missingLetter?.consumedLetters, 5)
    }

    func testFirstLettersStillOfferTheirWords() {
        let engine = bundledEngine()
        XCTAssertEqual(engine.candidates(for: "nh").first?.word, "\u{4F60}\u{597D}")
        XCTAssertEqual(engine.candidates(for: "zg").first?.word, "\u{8FD9}\u{4E2A}")
    }

    func testAnApostropheStillForcesASyllableBreak() {
        let first = bundledEngine().candidates(for: "xi'an").first
        XCTAssertEqual(first?.word, "\u{897F}\u{5B89}")
        XCTAssertEqual(first?.consumedLetters, 5)
    }

    func testAPickForLettersWithAnApostropheComesFirstTheNextTime() {
        let engine = bundledEngine()
        let picked = engine.candidates(for: "xi'an").first { $0.word == "\u{897F}\u{5CB8}" }!
        engine.learn(spelling: picked.spelling, word: picked.word)
        XCTAssertEqual(engine.candidates(for: "xi'an").first?.word, "\u{897F}\u{5CB8}")
    }

    func testAPickIsRememberedUnderTheTypedLetters() {
        let engine = bundledEngine()
        engine.learn(spelling: "ni hao", word: "\u{62DF}\u{597D}")
        XCTAssertEqual(engine.learnedWords["nihao"], ["\u{62DF}\u{597D}"])
        XCTAssertEqual(engine.candidates(for: "nihao").first?.word, "\u{62DF}\u{597D}")
    }
}
