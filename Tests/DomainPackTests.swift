import UIKit
import XCTest

@testable import DuoKeyboard

/// The rule of the preferred capitals, case by case (`PreferredCapitals.form` of
/// scripts/lm-rerank/rerank.py, which scripts/domain-pack/check_supplement.py checks with the
/// same cases).
final class PreferredCapitalsTests: XCTestCase {
    private let capitals = PreferredCapitals(table: """
        word\tzipf\tpreferred\teveryday\tnew
        gpu\t4.9\tGPU\t0\t0
        gpu's\t3.5\tGPU's\t0\t0
        pytorch\t4.3\tPyTorch\t0\t1
        vllm\t4.6\tvLLM\t0\t1
        rag\t4.6\tRAG\t1\t0
        tokenizer\t4.1\t\t0\t1

        """)

    private func form(_ typed: String, automatic: Bool = false, corrected: String? = nil) -> String {
        capitals.form(of: corrected ?? typed, typed: typed, automaticFirst: automatic)
    }

    func testLowerCaseStays() {
        XCTAssertEqual(form("gpu"), "gpu")
        XCTAssertEqual(form("pytorch"), "pytorch")
    }

    func testACapitalThatThePersonTypedGivesThePreferredForm() {
        XCTAssertEqual(form("Gpu"), "GPU")
        XCTAssertEqual(form("Pytorch"), "PyTorch")
        XCTAssertEqual(form("Vllm"), "vLLM")
        XCTAssertEqual(form("pyTorch"), "PyTorch")
        XCTAssertEqual(form("gPu"), "GPU")
    }

    func testTheKeyboardsOwnCapitalAtTheStartOfASentenceGivesThePreferredForm() {
        XCTAssertEqual(form("Gpu", automatic: true), "GPU")
        XCTAssertEqual(form("Pytorch", automatic: true), "PyTorch")
        XCTAssertEqual(form("Vllm", automatic: true), "vLLM")
    }

    func testACorrectedSlipKeepsTheCaseOfItsFirstLetter() {
        XCTAssertEqual(form("Pytorhc", corrected: "Pytorch"), "PyTorch")
        XCTAssertEqual(form("pytorhc", corrected: "pytorch"), "pytorch")
        // A slip of another length.
        XCTAssertEqual(form("Pytorc", automatic: true, corrected: "Pytorch"), "PyTorch")
        XCTAssertEqual(form("pytorcch", corrected: "pytorch"), "pytorch")
    }

    func testAllCapitalsAndThePreferredFormStay() {
        XCTAssertEqual(form("PYTORCH"), "PYTORCH")
        XCTAssertEqual(form("VLLM"), "VLLM")
        XCTAssertEqual(form("PyTorch"), "PyTorch")
        XCTAssertEqual(form("GPU"), "GPU")
    }

    func testTwoOrMoreCapitalsGiveTheNearerOfThePreferredFormAndAllCapitals() {
        XCTAssertEqual(form("PYTORCh"), "PYTORCH")
        XCTAssertEqual(form("PYtorch"), "PyTorch")
        XCTAssertEqual(form("VLlm"), "VLLM")
        XCTAssertEqual(form("vLLm"), "vLLM")
    }

    func testAnEverydayWordKeepsItsPlainCapital() {
        XCTAssertEqual(form("Rag", automatic: true), "Rag")
        XCTAssertEqual(form("Rag"), "Rag")
        XCTAssertEqual(form("rag"), "rag")
        XCTAssertEqual(form("RAG"), "RAG")
        XCTAssertEqual(form("rAg"), "RAG")
    }

    func testAWordWithoutAPreferredFormAndAWordOutsideTheTableNeverChange() {
        XCTAssertEqual(form("Tokenizer"), "Tokenizer")
        XCTAssertEqual(form("tokenizer"), "tokenizer")
        XCTAssertEqual(form("Monday"), "Monday")
        XCTAssertEqual(form("It", automatic: true), "It")
        XCTAssertEqual(form("us"), "us")
    }

    func testAnApostropheIsNotALetterOfTheRule() {
        XCTAssertEqual(form("Gpu's"), "GPU's")
        XCTAssertEqual(form("gpu's"), "gpu's")
        XCTAssertEqual(form("GPU'S"), "GPU'S")
        XCTAssertEqual(form("Gpus", automatic: true, corrected: "Gpu's"), "GPU's")
    }

    func testAFirstLetterTypedAsASymbolKeyCountsAsTheKeyboardsOwnCapital() {
        // The keyboard read "[" as "p" and typed the capital of the sentence start by itself.
        XCTAssertEqual(form("[ytorch", corrected: "Pytorch"), "PyTorch")
        // Inside a sentence the keyboard types no capital, so the word stays in lower case.
        XCTAssertEqual(form("[ytorch", corrected: "pytorch"), "pytorch")
    }

    func testTheModelMayNotChangeATypedWordThatIsNewInThePack() {
        func reading(_ text: String, typed: Bool = false, chosen: Bool = false) -> EnglishReading {
            EnglishReading(text: text, score: 0, slipCost: 0, asTyped: typed, chosen: chosen)
        }
        func kept(_ readings: [EnglishReading], _ typed: String) -> [String] {
            capitals.keepingNewWords(readings, typed: typed).map { $0.text }
        }
        XCTAssertEqual(kept([reading("pytorch", typed: true, chosen: true), reading("porch"), reading("torch")], "pytorch"), ["pytorch"])
        // The engine's own choice stays, and so does a reading that keeps the new word.
        XCTAssertEqual(
            kept([reading("the pytorch", typed: true), reading("the porch", chosen: true), reading("they pytorch"), reading("the torch")],
                 "the pytorch"),
            ["the pytorch", "the porch", "they pytorch"])
        // A slip is not a word of the pack, so every reading stays.
        XCTAssertEqual(kept([reading("pytorhc", typed: true), reading("pytorch", chosen: true), reading("porch")], "pytorhc"),
                       ["pytorhc", "pytorch", "porch"])
        // A word that the base lexicon also holds is not protected.
        XCTAssertEqual(kept([reading("gpu", typed: true, chosen: true), reading("gnu")], "gpu"), ["gpu", "gnu"])
    }

    func testEachWordOfASpanGetsItsForm() {
        XCTAssertEqual(capitals.latch("Pytorch is", typed: "Pytorhc is", textBefore: "", type: .sentences), "PyTorch is")
        XCTAssertEqual(capitals.latch("the gpu", typed: "the gpu", textBefore: "I use ", type: .sentences), "the gpu")
        // A field without automatic capitals: the person typed the capital.
        XCTAssertEqual(capitals.latch("Rag", typed: "Rag", textBefore: "", type: .none), "Rag")
        // A joined word takes the capital of the first typed word.
        XCTAssertEqual(capitals.latch("Pytorch", typed: "Py torch", textBefore: "I use ", type: .sentences), "PyTorch")
    }

    func testAWordWithACapitalAfterItsFirstLetterIsFound() {
        XCTAssertEqual(KeyboardTextLogic.wordWithInnerCapital(before: "I use pyTorch"), "pyTorch")
        XCTAssertEqual(KeyboardTextLogic.wordWithInnerCapital(before: "GPu"), "GPu")
        XCTAssertNil(KeyboardTextLogic.wordWithInnerCapital(before: "I use Pytorch"))
        XCTAssertNil(KeyboardTextLogic.wordWithInnerCapital(before: "see x.pyTorch"))
        XCTAssertNil(KeyboardTextLogic.wordWithInnerCapital(before: "I use pyTorch "))
    }
}

/// The supplement of the English lexicon, with the files that ship (`duo_lexicon_set_supplement`).
final class SupplementEngineTests: XCTestCase {
    private static let lexicon = TypingLexicon(resource: "lexicon-english", fullCheck: false)
    private static let supplement = TypingLexicon(resource: "supplement-ai-software", fullCheck: true)

    private func reading(_ typed: String, after previous: String = "the", withSupplement: Bool) -> String? {
        let engine = EnglishTypingEngine(lexicon: Self.lexicon, supplement: withSupplement ? Self.supplement : nil)
        return engine.reading(previousWord: previous, typed: typed)
    }

    func testAWordOfTheSupplementStaysAsTyped() {
        for (word, without) in [("pytorch", "porch"), ("llm", "ll"), ("ultrathink", "ultra think"), ("ultracode", "ultra code"),
                                ("agentic", "magnetic"), ("evals", "evils")] {
            XCTAssertEqual(reading(word, withSupplement: false), without, word)
            XCTAssertEqual(reading(word, withSupplement: true), word, word)
        }
    }

    func testASlipIsCorrectedIntoAWordOfTheSupplement() {
        XCTAssertNotEqual(reading("pytorhc", withSupplement: false), "pytorch")
        for (typed, word) in [("pytorhc", "pytorch"), ("ultrathnik", "ultrathink"), ("ultrathinl", "ultrathink"),
                              ("ultracoed", "ultracode"), ("gpuu", "gpu"), ("tokenizr", "tokenizer")] {
            XCTAssertEqual(reading(typed, withSupplement: true), word, typed)
        }
    }

    func testEverydayWordsNearAWordOfTheSupplementStay() {
        for word in ["ultra", "ultrathin", "ultrasound", "porch", "all", "evils", "rope", "got", "lore"] {
            XCTAssertEqual(reading(word, withSupplement: true), word, word)
        }
        XCTAssertEqual(reading("teh", after: "", withSupplement: true), "the")
        XCTAssertEqual(reading("ultra think", after: "", withSupplement: true), "ultra think")
    }

    func testAWordOfTheSupplementIsAKnownWordBeforeTheNextWord() {
        XCTAssertEqual(reading("pytorch modle", after: "", withSupplement: true), "pytorch model")
        XCTAssertEqual(reading("ultrathink about", after: "", withSupplement: true), "ultrathink about")
        XCTAssertEqual(reading("modle", after: "pytorch", withSupplement: true), "model")
    }

    func testTakingTheSupplementOffBringsTheBaseReadingsBack() {
        let engine = EnglishTypingEngine(lexicon: Self.lexicon, supplement: Self.supplement)
        XCTAssertEqual(engine.reading(previousWord: "the", typed: "pytorch"), "pytorch")
        engine.setSupplement(nil)
        XCTAssertEqual(engine.reading(previousWord: "the", typed: "pytorch"), "porch")
        engine.setSupplement(Self.supplement)
        XCTAssertEqual(engine.reading(previousWord: "the", typed: "pytorch"), "pytorch")
    }

    func testTheReadingsHoldAWordOfTheSupplementForTheLanguageModel() throws {
        let engine = EnglishTypingEngine(lexicon: Self.lexicon, supplement: Self.supplement)
        let readings = try XCTUnwrap(engine.readings(previousWord: "the", typed: "pytorhc", limit: 8))
        XCTAssertEqual(readings.first { $0.chosen }?.text, "pytorch")
        XCTAssertEqual(readings.filter { $0.text == "pytorch" }.count, 1)
    }
}

/// The work area in the keyboard: its words, their capitals, the undo, and the switch.
@MainActor
final class WorkAreaKeyboardTests: XCTestCase {
    private static let lexicon = TypingLexicon(resource: "lexicon-english", fullCheck: false)
    private static let workArea = WorkArea.aiAndSoftware()
    private static let storeName = "WorkAreaKeyboardTests"

    private var keyboardView: KeyboardView!
    private var document: FakeDocument!
    private var spellChecker: EngineSpellChecker!
    private var controller: KeyboardTextController!

    override func setUp() {
        super.setUp()
        UserDefaults().removePersistentDomain(forName: Self.storeName)
    }

    override func tearDown() {
        UserDefaults().removePersistentDomain(forName: Self.storeName)
        super.tearDown()
    }

    /// A keyboard with the engine alone, in a field that capitalizes sentences.
    private func makeController(before: String, workArea: WorkArea? = WorkAreaKeyboardTests.workArea) {
        keyboardView = KeyboardView()
        document = FakeDocument(before: before)
        document.autocapitalizationType = .sentences
        spellChecker = EngineSpellChecker(
            engine: EnglishTypingEngine(lexicon: Self.lexicon), reranker: nil,
            store: UserDefaults(suiteName: Self.storeName)!, workArea: workArea)
        controller = KeyboardTextController(
            keyboardView: keyboardView, document: document, spellChecker: spellChecker,
            pinyinEngine: { PinyinEngine(dictionaryText: testDictionary) })
    }

    private func type(_ text: String) {
        for character in text {
            controller.keyboardView(keyboardView, insert: String(character))
        }
    }

    func testTheWorkAreaIsOnByDefaultAndItsWordsStay() {
        makeController(before: "I trained it with ")
        XCTAssertTrue(spellChecker.workAreaIsOn)
        type("pytorch and the llm ")
        XCTAssertEqual(document.text, "I trained it with pytorch and the llm ")
    }

    func testWithoutAWorkAreaTheKeyboardChangesTheSameWords() {
        makeController(before: "I trained the ", workArea: nil)
        XCTAssertFalse(spellChecker.workAreaIsOn)
        type("pytorch ")
        XCTAssertEqual(document.text, "I trained the porch ")
    }

    func testASlipInLowerCaseBecomesTheWordInLowerCase() {
        makeController(before: "I trained it with ")
        type("pytorhc ")
        XCTAssertEqual(document.text, "I trained it with pytorch ")
    }

    func testASlipWithATypedCapitalBecomesThePreferredForm() {
        makeController(before: "I trained it with ")
        type("Pytorhc ")
        XCTAssertEqual(document.text, "I trained it with PyTorch ")
    }

    func testATypedCapitalOnARightWordGivesThePreferredForm() {
        makeController(before: "we need one more ")
        type("Gpu ")
        XCTAssertEqual(document.text, "we need one more GPU ")
    }

    func testTheStartOfASentenceGivesThePreferredForm() {
        makeController(before: "")
        type("Pytorch is fast. Gpus are not cheap ")
        XCTAssertEqual(document.text, "PyTorch is fast. GPUs are not cheap ")
    }

    func testASymbolKeyInPlaceOfTheFirstLetterGivesThePreferredFormAtTheStartOfTheField() {
        makeController(before: "")
        type("[ytorch ")
        XCTAssertEqual(document.text, "PyTorch ")
        makeController(before: "we use ")
        type("[ytorch ")
        XCTAssertEqual(document.text, "we use pytorch ")
    }

    func testACapitalInsideAWordGivesThePreferredForm() {
        makeController(before: "I trained it with ")
        type("pyTorch ")
        XCTAssertEqual(document.text, "I trained it with PyTorch ")
    }

    func testAllCapitalsStay() {
        makeController(before: "I trained it with ")
        type("PYTORCH ")
        XCTAssertEqual(document.text, "I trained it with PYTORCH ")
    }

    func testAnOrdinaryWordKeepsItsTypedCase() {
        makeController(before: "")
        type("It was Monday and Tom saw us ")
        XCTAssertEqual(document.text, "It was Monday and Tom saw us ")
    }

    func testBackspaceBringsTheTypedCapitalsBackAndTheKeyboardKeepsThem() {
        makeController(before: "I trained it with ")
        type("Pytorch ")
        XCTAssertEqual(document.text, "I trained it with PyTorch ")
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "I trained it with Pytorch")
        XCTAssertTrue(spellChecker.keeps("Pytorch"))
        type(" and Pytorch ")
        XCTAssertEqual(document.text, "I trained it with Pytorch and Pytorch ")
    }

    func testBackspaceAlsoBringsBackAWordWithACapitalInside() {
        makeController(before: "I trained it with ")
        type("pyTorch ")
        XCTAssertEqual(document.text, "I trained it with PyTorch ")
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "I trained it with pyTorch")
        type(" and pyTorch ")
        XCTAssertEqual(document.text, "I trained it with pyTorch and pyTorch ")
    }

    func testTheRequestedWordsStayOneWordAndTheirSlipsAreCorrected() {
        makeController(before: "please ")
        type("ultrathink about this and use ultracode ")
        XCTAssertEqual(document.text, "please ultrathink about this and use ultracode ")
        makeController(before: "please ")
        type("ultrathnik ")
        XCTAssertEqual(document.text, "please ultrathink ")
        makeController(before: "use ")
        type("ultracoed ")
        XCTAssertEqual(document.text, "use ultracode ")
        makeController(before: "an ")
        type("ultrathin ultrasound ultra ")
        XCTAssertEqual(document.text, "an ultrathin ultrasound ultra ")
    }

    func testTheTriggerTurnsTheWorkAreaOffAndOnAndTheStoreRemembersIt() {
        makeController(before: "")
        type("duo:work ")
        XCTAssertEqual(document.text, "")
        XCTAssertFalse(spellChecker.workAreaIsOn)
        XCTAssertNil(spellChecker.preferredCapitals)
        type("the pytorch ")
        XCTAssertEqual(document.text, "the porch ")
        // A new keyboard reads the stored switch.
        makeController(before: "the ")
        XCTAssertFalse(spellChecker.workAreaIsOn)
        type("duo:work ")
        XCTAssertEqual(document.text, "the ")
        XCTAssertTrue(spellChecker.workAreaIsOn)
        type("pytorch ")
        XCTAssertEqual(document.text, "the pytorch ")
    }

    func testTheTriggerInsideALongerTextIsTypedAsText() {
        makeController(before: "@")
        type("duo:work ")
        XCTAssertEqual(document.text, "@duo:work ")
        XCTAssertTrue(spellChecker.workAreaIsOn)
    }
}
