import UIKit
import XCTest

@testable import DuoKeyboard

/// A spell checker with fixed predicted words. Each list sits under "previous word|typed letters".
@MainActor
private final class PredictingSpellChecker: SpellChecking {
    var words: [String: [String]] = [:]
    /// Every call of `predictedWords`, as "previous word|typed letters".
    var requests: [String] = []
    var corrections: [String: String] = [:]
    var capitals: PreferredCapitals?

    func reading(previousWord: String, typed: String, textBefore: String) -> String? {
        corrections[typed] ?? typed
    }

    func predictedWords(previousWord: String, typed: String, limit: Int) -> [String] {
        requests.append("\(previousWord)|\(typed)")
        return Array((words["\(previousWord)|\(typed)"] ?? []).prefix(limit))
    }

    var preferredCapitals: PreferredCapitals? { capitals }

    func learn(_ word: String) {}

    func keeps(_ word: String) -> Bool { false }
}

/// The top row of keys: the small Select All key at the left, the typing speed, the prediction
/// strip, and the small keys Cut, Copy and Paste at the right. The row has no Home key and no
/// End key.
@MainActor
final class TopRowLayoutTests: XCTestCase {
    private static let topKinds: [KeyKind] = [.selectAll, .typingSpeed, .predictionStrip, .cut, .copy, .paste]

    func testTheTopRowHoldsSelectAllTheStripAndTheSmallKeysInEveryLayer() {
        for style in [LayoutStyle.compact, .wide, .split] {
            for layer in [KeyboardLayer.letters, .symbols, .more] {
                let layout = KeyboardLayout.make(style: style, layer: layer, showsGlobe: true)
                XCTAssertEqual(layout.rows[0].map(\.kind), Self.topKinds, "\(style) \(layer)")
                let others = layout.rows.dropFirst().joined().map(\.kind)
                XCTAssertFalse(others.contains(.predictionStrip), "\(style) \(layer)")
                let all = layout.rows.joined().map(\.kind)
                XCTAssertFalse(all.contains(.home), "\(style) \(layer)")
                XCTAssertFalse(all.contains(.end), "\(style) \(layer)")
            }
        }
    }

    func testSelectAllOfTheWideLayoutIsTwiceAsWideAsCutAndTheTypingSpeed() throws {
        // Select All and the typing speed share 2.3 key units. Select All takes two thirds of
        // them, and the typing speed takes one third, the width of Cut, Copy and Paste.
        let row = KeyboardLayout.make(style: .wide, layer: .letters, showsGlobe: true).rows[0]
        for kind in [KeyKind.typingSpeed, .cut, .copy, .paste] {
            XCTAssertEqual(try XCTUnwrap(row.first { $0.kind == kind }).weight, 2.3 / 3, accuracy: 0.0001, "\(kind)")
        }
        XCTAssertEqual(try XCTUnwrap(row.first { $0.kind == .selectAll }).weight, 2.3 * 2 / 3, accuracy: 0.0001)
        XCTAssertEqual(row.reduce(0) { $0 + $1.weight }, KeyboardSpec.shared.wide.units, accuracy: 0.0001)
    }

    func testASmallKeyOfTheCompactLayoutTakesThreeQuartersOfAKeyUnit() throws {
        let row = KeyboardLayout.make(style: .compact, layer: .letters, showsGlobe: true).rows[0]
        // Select All had 1.75 key units. The key now has the width of Cut, Copy and Paste, and
        // the typing speed takes the unit that became free.
        XCTAssertEqual(try XCTUnwrap(row.first { $0.kind == .selectAll }).weight, 0.75, accuracy: 0.0001)
        XCTAssertEqual(try XCTUnwrap(row.first { $0.kind == .typingSpeed }).weight, 1, accuracy: 0.0001)
        for kind in [KeyKind.cut, .copy, .paste] {
            XCTAssertEqual(try XCTUnwrap(row.first { $0.kind == kind }).weight, 0.75, accuracy: 0.0001, "\(kind)")
        }
        XCTAssertEqual(row.reduce(0) { $0 + $1.weight }, KeyboardSpec.shared.compact.units, accuracy: 0.0001)
    }

    func testTheStripOfTheSplitLayoutTakesTheWidthOfTheEmptyMiddle() throws {
        let gap = KeyboardSpec.shared.metrics.splitGapUnits
        for layer in [KeyboardLayer.letters, .symbols, .more] {
            let wide = KeyboardLayout.make(style: .wide, layer: layer, showsGlobe: true).rows[0]
            let split = KeyboardLayout.make(style: .split, layer: layer, showsGlobe: true).rows[0]
            let wideStrip = try XCTUnwrap(wide.first { $0.kind == .predictionStrip }).weight
            let splitStrip = try XCTUnwrap(split.first { $0.kind == .predictionStrip }).weight
            XCTAssertEqual(splitStrip, wideStrip + gap, accuracy: 0.0001, "\(layer)")
            XCTAssertFalse(split.contains { $0.kind == .gap }, "\(layer)")
            XCTAssertEqual(split.reduce(0) { $0 + $1.weight }, KeyboardSpec.shared.wide.units + gap, accuracy: 0.0001, "\(layer)")
        }
    }
}

/// The prediction strip: its place in the top row at each width of the phone, the predicted
/// words for the letters the person is typing, and a tap on a predicted word.
@MainActor
final class PredictionStripTests: XCTestCase {
    private var keyboardView: KeyboardView!
    private var document: FakeDocument!
    private var spellChecker: PredictingSpellChecker!
    private var controller: KeyboardTextController!

    /// The widths of the folded phone, the open phone in portrait, and the open phone in landscape.
    private static let compactWidth: CGFloat = 466
    private static let wideWidth: CGFloat = 669
    private static let splitWidth: CGFloat = 951

    private func makeKeyboard(width: CGFloat = PredictionStripTests.compactWidth, before: String = "", after: String = "") {
        let height = KeyboardView.preferredHeight(forWidth: width, compactHeight: false, device: .phone, landscape: false)
        keyboardView = KeyboardView(frame: CGRect(x: 0, y: 0, width: width, height: height))
        keyboardView.layoutIfNeeded()
        document = FakeDocument(before: before, after: after)
        spellChecker = PredictingSpellChecker()
        controller = KeyboardTextController(
            keyboardView: keyboardView, document: document, spellChecker: spellChecker,
            pinyinEngine: { PinyinEngine(dictionaryText: testDictionary) })
        controller.documentDidChange()
        keyboardView.layoutIfNeeded()
    }

    private func type(_ text: String) {
        for character in text {
            controller.keyboardView(keyboardView, insert: String(character))
        }
        keyboardView.layoutIfNeeded()
    }

    private func keyView(_ kind: KeyKind) throws -> KeyView {
        try XCTUnwrap(keyboardView.subviews.compactMap { $0 as? KeyView }.first { $0.key.kind == kind }, "\(kind)")
    }

    private func frame(of view: UIView) -> CGRect {
        view.convert(view.bounds, to: keyboardView)
    }

    /// The texts of the strip's entries from left to right.
    private func strip() -> [String] {
        keyboardView.predictionStrip.entries.map { $0.item.text }
    }

    /// A finger tap on the strip's entry at `index`: the finger comes down and lifts inside it.
    private func tapEntry(_ index: Int, file: StaticString = #filePath, line: UInt = #line) {
        let entries = keyboardView.predictionStrip.entries
        guard entries.indices.contains(index) else {
            XCTFail("The strip shows \(entries.count) entries", file: file, line: line)
            return
        }
        entries[index].sendActions(for: .touchDown)
        entries[index].sendActions(for: .touchUpInside)
    }

    /// A finger tap that reaches the keyboard view itself, as a tap on a key does.
    private func tap(_ point: CGPoint) {
        let touch = FakeTouch(at: point)
        keyboardView.touchesBegan([touch], with: nil)
        keyboardView.touchesEnded([touch], with: nil)
    }

    private func widths() -> [CGFloat] {
        // An iPad chooses its layout by the orientation of the screen, so only the compact
        // width gives the same layout there.
        KeyboardDevice.current == .phone ? [Self.compactWidth, Self.wideWidth, Self.splitWidth] : [Self.compactWidth]
    }

    // MARK: Place

    func testTheStripLiesBetweenTheTypingSpeedAndCutAtEveryWidth() throws {
        for width in widths() {
            makeKeyboard(width: width)
            let strip = keyboardView.predictionStrip
            XCTAssertFalse(strip.isHidden, "\(width)")
            let selectAll = try keyView(.selectAll).hitFrame
            let cut = try keyView(.cut).hitFrame
            // The typing speed stands between Select All and the strip.
            XCTAssertEqual(strip.frame.minX, try keyView(.typingSpeed).hitFrame.maxX, accuracy: 0.5, "\(width)")
            XCTAssertGreaterThan(strip.frame.minX, selectAll.maxX, "\(width)")
            XCTAssertEqual(strip.frame.maxX, cut.minX, accuracy: 0.5, "\(width)")
            // The strip reaches from the keyboard's upper edge to the lower edge of the top row.
            XCTAssertEqual(strip.frame.minY, 0, accuracy: 0.5, "\(width)")
            XCTAssertEqual(strip.frame.maxY, selectAll.maxY, accuracy: 0.5, "\(width)")
            // The place of the strip in the row draws no key.
            XCTAssertTrue(try keyView(.predictionStrip).isHidden, "\(width)")
        }
    }

    func testTheStripOfTheOpenPhoneInLandscapeCrossesTheEmptyMiddle() throws {
        try XCTSkipUnless(KeyboardDevice.current == .phone, "An iPad chooses its layout by the orientation of the screen")
        makeKeyboard(width: Self.wideWidth)
        let wide = keyboardView.predictionStrip.frame.width
        makeKeyboard(width: Self.splitWidth)
        XCTAssertEqual(keyboardView.style, .split)
        let split = keyboardView.predictionStrip.frame
        XCTAssertGreaterThan(split.width, wide + 200)
        // The strip covers the middle of the keyboard, where the letter rows have no keys.
        XCTAssertLessThan(split.minX, Self.splitWidth / 2 - 100)
        XCTAssertGreaterThan(split.maxX, Self.splitWidth / 2 + 100)
    }

    func testTheStripStaysInEveryLayer() {
        makeKeyboard()
        let letters = keyboardView.predictionStrip.frame
        for layer in [KeyboardLayer.symbols, .more] {
            keyboardView.show(layer: layer)
            keyboardView.layoutIfNeeded()
            XCTAssertFalse(keyboardView.predictionStrip.isHidden, "\(layer)")
            XCTAssertEqual(keyboardView.predictionStrip.frame, letters, "\(layer)")
        }
    }

    func testTheEntriesStandSideBySideInsideTheStrip() throws {
        for width in widths() {
            makeKeyboard(width: width, before: "See you ")
            spellChecker.words["you|to"] = ["tomorrow", "today", "tonight"]
            type("to")
            let entries = keyboardView.predictionStrip.entries
            XCTAssertEqual(entries.count, 3, "\(width)")
            let row = try keyView(.selectAll).hitFrame
            var edge = keyboardView.predictionStrip.frame.minX
            for entry in entries {
                let box = frame(of: entry)
                XCTAssertGreaterThanOrEqual(box.minX, edge - 0.5, "\(width)")
                XCTAssertGreaterThan(box.width, 30, "\(width)")
                edge = box.maxX
                // The text stays at the height of the keys of the row.
                let text = frame(of: entry.label)
                XCTAssertGreaterThanOrEqual(text.minY, row.minY - 0.5, "\(width)")
                XCTAssertLessThanOrEqual(text.maxY, row.maxY + 0.5, "\(width)")
            }
        }
    }

    // MARK: Predicted words

    func testTypedLettersShowTheirPredictedWords() {
        makeKeyboard(before: "See you ")
        spellChecker.words["you|t"] = ["to", "the", "tomorrow"]
        spellChecker.words["you|to"] = ["tomorrow", "today", "tonight"]
        type("t")
        XCTAssertEqual(strip(), ["to", "the", "tomorrow"])
        type("o")
        XCTAssertEqual(strip(), ["tomorrow", "today", "tonight"])
        XCTAssertEqual(spellChecker.requests.last, "you|to")
    }

    func testLettersRightAfterAnEmojiShowTheirPredictedWords() {
        // An emoji is no word, so the letters after it start a word, with no word before it.
        makeKeyboard(before: "nice \u{1F44D}")
        spellChecker.words["|t"] = ["to", "the", "that"]
        type("t")
        XCTAssertEqual(strip(), ["to", "the", "that"])
        XCTAssertEqual(spellChecker.requests.last, "|t")
    }

    func testAWordAndOneSpaceShowTheWordsAfterThatWord() {
        makeKeyboard(before: "See you ")
        spellChecker.words["you|"] = ["are", "can"]
        controller.documentDidChange()
        XCTAssertEqual(keyboardView.predictedWords, ["are", "can"])
        XCTAssertEqual(spellChecker.requests.last, "you|")
    }

    func testTextWithoutAWordBeforeTheCursorShowsNoPredictedWords() {
        // The start of the text, a mark, two spaces and a line break have no word before them.
        for before in ["", "See you. ", "See you, ", "See you  ", "See you\n"] {
            makeKeyboard(before: before)
            spellChecker.requests = []
            controller.documentDidChange()
            XCTAssertEqual(keyboardView.predictedWords, [], before)
            XCTAssertEqual(spellChecker.requests, [], before)
        }
    }

    func testTheStripHoldsUpToTwentyPredictedWords() {
        makeKeyboard()
        spellChecker.words["|x"] = (1...30).map { "x" + String(repeating: "a", count: $0) }
        type("x")
        XCTAssertEqual(KeyboardTextController.predictedWordCount, 20)
        XCTAssertEqual(keyboardView.predictedWords.count, 20)
    }

    func testTheEmojiOfAWordComeBeforeItsPredictedWords() {
        makeKeyboard()
        spellChecker.words["|good"] = ["goodbye", "goodness"]
        type("good")
        XCTAssertEqual(strip(), ["\u{1F44D}", "\u{1F44F}", "goodbye", "goodness"])
        // After the space, the word before the cursor still shows its emoji, and no letter is typed.
        type(" ")
        XCTAssertEqual(strip(), ["\u{1F44D}", "\u{1F44F}"])
    }

    func testAPredictedWordTakesTheTypedCapitals() {
        makeKeyboard()
        spellChecker.words["|to"] = ["tomorrow", "today"]
        type("To")
        XCTAssertEqual(keyboardView.predictedWords, ["Tomorrow", "Today"])
        makeKeyboard()
        spellChecker.words["|to"] = ["tomorrow", "today"]
        type("TO")
        XCTAssertEqual(keyboardView.predictedWords, ["TOMORROW", "TODAY"])
        // The checker gets the typed letters in lower case.
        XCTAssertEqual(spellChecker.requests.last, "|to")
    }

    func testTheWordIAndItsContractionsGetTheirCapital() {
        makeKeyboard()
        spellChecker.words["|i"] = ["in", "i'm", "it"]
        type("i")
        XCTAssertEqual(keyboardView.predictedWords, ["in", "I'm", "it"])
    }

    func testAWordOfTheWorkAreaGetsItsPreferredForm() {
        let capitals = PreferredCapitals(entries: ["pytorch": PreferredCapitals.Entry(preferred: "PyTorch", everyday: false)])
        makeKeyboard()
        spellChecker.capitals = capitals
        spellChecker.words["|py"] = ["python", "pytorch"]
        type("py")
        XCTAssertEqual(keyboardView.predictedWords, ["python", "pytorch"])
        makeKeyboard()
        spellChecker.capitals = capitals
        spellChecker.words["|py"] = ["python", "pytorch"]
        type("Py")
        XCTAssertEqual(keyboardView.predictedWords, ["Python", "PyTorch"])
    }

    func testACursorInsideAWordShowsNoPredictedWords() {
        makeKeyboard(before: "to", after: "day")
        spellChecker.words["|to"] = ["tomorrow"]
        controller.documentDidChange()
        XCTAssertEqual(keyboardView.predictedWords, [])
        XCTAssertEqual(spellChecker.requests, [])
    }

    func testTextThatIsNoPlainWordShowsNoPredictedWords() {
        for before in ["@to", "2to", "iPh", "a.to", "to-"] {
            makeKeyboard(before: before)
            spellChecker.words["|to"] = ["tomorrow"]
            spellChecker.words["|iph"] = ["iphone"]
            controller.documentDidChange()
            XCTAssertEqual(keyboardView.predictedWords, [], before)
        }
        // An opening bracket or quote before the letters is plain text.
        for before in ["(to", "\"to", "say \u{201C}to"] {
            makeKeyboard(before: before)
            spellChecker.words["|to"] = ["tomorrow"]
            controller.documentDidChange()
            XCTAssertEqual(keyboardView.predictedWords, ["tomorrow"], before)
        }
    }

    func testChineseModeAndAFieldWithoutAutocorrectionShowNoPredictedWords() {
        makeKeyboard()
        document.allowsAutocorrection = false
        spellChecker.words["|to"] = ["tomorrow"]
        type("to")
        XCTAssertEqual(keyboardView.predictedWords, [])
        makeKeyboard()
        spellChecker.words["|hao"] = ["haole"]
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        type("hao")
        XCTAssertEqual(keyboardView.predictedWords, [])
    }

    // MARK: A tap on a predicted word

    func testATapPutsTheWordInPlaceOfTheTypedLettersAndAddsASpace() {
        for width in widths() {
            makeKeyboard(width: width, before: "See you ")
            spellChecker.words["you|to"] = ["tomorrow", "today", "tonight"]
            type("to")
            tapEntry(1)
            XCTAssertEqual(document.text, "See you today ", "\(width)")
            XCTAssertEqual(strip(), [], "\(width)")
        }
    }

    func testATapKeepsTheTypedCapital() {
        makeKeyboard()
        spellChecker.words["|to"] = ["tomorrow"]
        type("To")
        tapEntry(0)
        XCTAssertEqual(document.text, "Tomorrow ")
    }

    func testOneDeleteAfterATapBringsTheTypedLettersBack() {
        makeKeyboard(before: "See you ")
        spellChecker.words["you|to"] = ["tomorrow"]
        type("to")
        tapEntry(0)
        XCTAssertEqual(document.text, "See you tomorrow ")
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "See you to")
        // The strip shows the words of the typed letters again.
        XCTAssertEqual(strip(), ["tomorrow"])
        // The next delete is a plain delete.
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "See you t")
    }

    func testAKeyAfterATapEndsTheWayBack() {
        makeKeyboard(before: "See you ")
        spellChecker.words["you|to"] = ["tomorrow"]
        type("to")
        tapEntry(0)
        type("a")
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "See you tomorrow ")
    }

    func testATapRunsNoCorrection() {
        makeKeyboard()
        spellChecker.corrections["teh"] = "the"
        spellChecker.corrections["tehran"] = "the ran"
        spellChecker.corrections["tehran is"] = "the ran is"
        spellChecker.words["|teh"] = ["tehran"]
        type("teh")
        tapEntry(0)
        XCTAssertEqual(document.text, "tehran ")
        // The next word is read alone, so the tapped word stays as it is.
        type("is ")
        XCTAssertEqual(document.text, "tehran is ")
    }

    func testAMarkAfterATappedWordTakesThePlaceOfItsSpace() {
        makeKeyboard(before: "See you ")
        spellChecker.words["you|to"] = ["tomorrow"]
        type("to")
        tapEntry(0)
        type(".")
        XCTAssertEqual(document.text, "See you tomorrow.")
    }

    func testASecondSpaceRightAfterATapGivesAPeriod() {
        makeKeyboard(before: "See you ")
        spellChecker.words["you|to"] = ["tomorrow"]
        type("to")
        tapEntry(0)
        type(" ")
        XCTAssertEqual(document.text, "See you tomorrow. ")
    }

    func testATapRightAfterASpaceTypesTheWordAndOneDeleteTakesItOutAgain() {
        makeKeyboard(before: "See you ")
        spellChecker.words["you|"] = ["are", "can"]
        controller.documentDidChange()
        tapEntry(1)
        XCTAssertEqual(document.text, "See you can ")
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "See you ")
        // The next delete is a plain delete.
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "See you")
    }

    func testTapsChainFromOnePredictedWordToTheNext() {
        // Each tap leaves a word and one space before the cursor, so the strip predicts again.
        makeKeyboard(before: "See ")
        spellChecker.words["see|"] = ["you", "the"]
        spellChecker.words["you|"] = ["tomorrow", "soon"]
        spellChecker.words["tomorrow|"] = ["morning", "at"]
        controller.documentDidChange()
        tapEntry(0)
        XCTAssertEqual(document.text, "See you ")
        XCTAssertEqual(keyboardView.predictedWords, ["tomorrow", "soon"])
        tapEntry(0)
        XCTAssertEqual(document.text, "See you tomorrow ")
        XCTAssertEqual(keyboardView.predictedWords, ["morning", "at"])
        tapEntry(1)
        XCTAssertEqual(document.text, "See you tomorrow at ")
        // One backspace takes back the last tap only.
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "See you tomorrow ")
        XCTAssertEqual(keyboardView.predictedWords, ["morning", "at"])
    }

    func testATapOnAWordForOtherTextTypesNothing() {
        // Other letters before the cursor, and text that the strip predicts no word for.
        makeKeyboard(before: "See you xy")
        controller.keyboardView(keyboardView, didSelectPredictedWord: "tomorrow")
        XCTAssertEqual(document.text, "See you xy")
        makeKeyboard(before: "See you. ")
        controller.keyboardView(keyboardView, didSelectPredictedWord: "tomorrow")
        XCTAssertEqual(document.text, "See you. ")
    }

    func testAFormWithASignGoesInForItsTypedLetters() {
        // A preferred form can hold a sign, as "Next.js" for "nextjs".
        makeKeyboard()
        spellChecker.capitals = PreferredCapitals(
            entries: ["nextjs": PreferredCapitals.Entry(preferred: "Next.js", everyday: false)])
        spellChecker.words["|nextj"] = ["nextjs"]
        type("Nextj")
        XCTAssertEqual(keyboardView.predictedWords, ["Next.js"])
        tapEntry(0)
        XCTAssertEqual(document.text, "Next.js ")
    }

    // MARK: The candidate row in the strip's place

    func testTheCandidateRowOfChineseLiesInTheStripsPlaceAtEveryWidth() throws {
        for width in widths() {
            makeKeyboard(width: width)
            controller.keyboardView(keyboardView, edit: .toggleLanguage)
            type("hao")
            let row = keyboardView.candidateBar
            XCTAssertFalse(row.isHidden, "\(width)")
            // The row stays between Select All and Cut, and those keys stay in view.
            XCTAssertGreaterThanOrEqual(row.frame.minX, try keyView(.selectAll).hitFrame.maxX, "\(width)")
            XCTAssertLessThanOrEqual(row.frame.maxX, try keyView(.cut).hitFrame.minX, "\(width)")
            XCTAssertTrue(keyboardView.predictionStrip.frame.contains(row.frame), "\(width)")
            for kind in [KeyKind.selectAll, .cut, .copy, .paste] {
                XCTAssertFalse(try keyView(kind).isHidden, "\(kind) \(width)")
            }
        }
    }

    func testTheKeysOfTheTopRowReactWhileTheCandidateRowShows() throws {
        for width in widths() {
            makeKeyboard(width: width)
            controller.keyboardView(keyboardView, edit: .toggleLanguage)
            type("hao")
            XCTAssertFalse(keyboardView.candidateBar.isHidden, "\(width)")
            UIPasteboard.general.string = "x"
            let paste = try keyView(.paste).hitFrame
            tap(CGPoint(x: paste.midX, y: paste.midY))
            XCTAssertTrue(document.text.hasSuffix("x"), "\(width): \(document.text)")
        }
    }

    func testTheProofreadersFixLiesInTheStripsPlace() async throws {
        makeKeyboard()
        let proofreader = FakeProofreader()
        proofreader.answers = ["I came form the office": "I came from the office"]
        controller.proofreader = proofreader
        controller.proofreadPauseSeconds = 0.05
        type("I came form the office ")
        await controller.pauseTask?.value
        await controller.proofreadTask?.value
        keyboardView.layoutIfNeeded()
        let row = keyboardView.candidateBar
        XCTAssertFalse(row.isHidden)
        XCTAssertGreaterThanOrEqual(row.frame.minX, try keyView(.selectAll).hitFrame.maxX)
        XCTAssertLessThanOrEqual(row.frame.maxX, try keyView(.cut).hitFrame.minX)
        for kind in [KeyKind.selectAll, .cut, .copy, .paste] {
            XCTAssertFalse(try keyView(kind).isHidden, "\(kind)")
        }
    }

    // MARK: The ripple of a tap

    func testAFingerOnAnEntryStartsARippleInTheStrip() {
        makeKeyboard(before: "See you ")
        spellChecker.words["you|to"] = ["tomorrow", "today", "tonight"]
        type("to")
        let strip = keyboardView.predictionStrip
        XCTAssertEqual(strip.rippleCount, 0)
        strip.entries[1].sendActions(for: .touchDown)
        XCTAssertEqual(strip.rippleCount, UIAccessibility.isReduceMotionEnabled ? 0 : 1)
    }

    func testAFingerOnACandidateStartsARippleInTheCandidateRow() throws {
        makeKeyboard()
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        type("hao")
        let row = keyboardView.candidateBar
        var views: [UIView] = [row]
        var buttons: [UIButton] = []
        while let view = views.popLast() {
            if let button = view as? UIButton { buttons.append(button) } else { views += view.subviews }
        }
        let first = try XCTUnwrap(buttons.first { $0.tag == 0 }, "The dictionary of the tests has a word for hao")
        XCTAssertEqual(row.rippleCount, 0)
        first.sendActions(for: .touchDown)
        XCTAssertEqual(row.rippleCount, UIAccessibility.isReduceMotionEnabled ? 0 : 1)
    }

    // MARK: Touches

    func testATouchInTheCellOfTheStripPressesNoKey() throws {
        for width in widths() {
            makeKeyboard(width: width, before: "hello")
            UIPasteboard.general.string = "x"
            let strip = keyboardView.predictionStrip.frame
            let row = try keyView(.selectAll).hitFrame
            // The ends of the strip sit right beside Select All and Cut.
            for x in [strip.minX + 1, strip.midX, strip.maxX - 1] {
                for y in [1, row.midY, row.maxY - 1] {
                    tap(CGPoint(x: x, y: y))
                }
            }
            XCTAssertFalse(keyboardView.selectAllActive, "\(width)")
            XCTAssertEqual(document.text, "hello", "\(width)")
            XCTAssertEqual(UIPasteboard.general.string, "x", "\(width)")
        }
    }

    func testSelectAllAndTheSmallKeysReactBesideTheStrip() throws {
        for width in widths() {
            makeKeyboard(width: width, before: "See you ")
            spellChecker.words["you|to"] = ["tomorrow", "today", "tonight"]
            type("to")
            UIPasteboard.general.string = "x"
            let paste = try keyView(.paste).hitFrame
            tap(CGPoint(x: paste.midX, y: paste.midY))
            XCTAssertEqual(document.text, "See you tox", "\(width)")
            let selectAll = try keyView(.selectAll).hitFrame
            tap(CGPoint(x: selectAll.midX, y: selectAll.midY))
            XCTAssertTrue(keyboardView.selectAllActive, "\(width)")
        }
    }

    func testALetterUnderAnotherFingerGoesInBeforeTheTapAndTheOldEntrySelectsNothing() throws {
        // A finger rests on a letter key. A second finger comes down on an entry, which types
        // the letter first. The letter changes the typed letters, so the entry under the second
        // finger is gone, and its lift selects nothing.
        makeKeyboard(before: "See you ")
        spellChecker.words["you|to"] = ["tomorrow"]
        spellChecker.words["you|tox"] = ["toxic"]
        type("to")
        let old = try XCTUnwrap(keyboardView.predictionStrip.entries.first)
        let letterKey = try keyView(.slide("x", "-")).hitFrame
        let letter = FakeTouch(at: CGPoint(x: letterKey.midX, y: letterKey.midY))
        keyboardView.touchesBegan([letter], with: nil)
        old.sendActions(for: .touchDown)
        XCTAssertEqual(document.text, "See you tox")
        old.sendActions(for: .touchUpInside)
        keyboardView.touchesEnded([letter], with: nil)
        XCTAssertEqual(document.text, "See you tox")
        XCTAssertEqual(strip(), ["toxic"])
    }
}

/// The predicted words of the keyboard's own spell checker, from the lexicon that ships.
@MainActor
final class PredictedWordsOfTheLexiconTests: XCTestCase {
    private static let storeName = "PredictedWordsOfTheLexiconTests"
    private var keyboardView: KeyboardView!
    private var document: FakeDocument!
    private var controller: KeyboardTextController!

    override func setUp() {
        super.setUp()
        UserDefaults().removePersistentDomain(forName: Self.storeName)
    }

    override func tearDown() {
        UserDefaults().removePersistentDomain(forName: Self.storeName)
        super.tearDown()
    }

    private func makeKeyboard(before: String) {
        keyboardView = KeyboardView(frame: CGRect(x: 0, y: 0, width: 466, height: 280))
        document = FakeDocument(before: before)
        let checker = EngineSpellChecker(
            engine: EnglishTypingEngine(lexicon: TypingLexicon(resource: "lexicon-english", fullCheck: false)),
            reranker: nil, store: UserDefaults(suiteName: Self.storeName)!, workArea: .aiAndSoftware())
        controller = KeyboardTextController(
            keyboardView: keyboardView, document: document, spellChecker: checker,
            pinyinEngine: { PinyinEngine(dictionaryText: testDictionary) })
        controller.documentDidChange()
    }

    private func type(_ text: String) {
        for character in text {
            controller.keyboardView(keyboardView, insert: String(character))
        }
    }

    func testTheWordsOfTheLexiconShowForTypedLetters() {
        makeKeyboard(before: "Thank ")
        type("y")
        XCTAssertEqual(keyboardView.predictedWords.first, "you")
        makeKeyboard(before: "See you ")
        type("to")
        XCTAssertTrue(keyboardView.predictedWords.contains("tomorrow"), "\(keyboardView.predictedWords)")
        XCTAssertFalse(keyboardView.predictedWords.contains("to"))
        XCTAssertEqual(keyboardView.predictedWords.count, 20)
    }

    func testAWordOfTheWorkAreaShowsInItsPreferredForm() {
        makeKeyboard(before: "I use ")
        type("Py")
        XCTAssertTrue(keyboardView.predictedWords.contains("PyTorch"), "\(keyboardView.predictedWords)")
        XCTAssertTrue(keyboardView.predictedWords.contains("Python"), "\(keyboardView.predictedWords)")
    }

    func testTheWordsAfterAWordShowRightAfterItsSpace() {
        makeKeyboard(before: "Thank ")
        XCTAssertTrue(keyboardView.predictedWords.prefix(3).contains("you"), "\(keyboardView.predictedWords)")
        XCTAssertEqual(keyboardView.predictedWords.count, 20)
    }

    func testATapOnAWordOfTheLexiconGoesIntoTheField() throws {
        makeKeyboard(before: "Thank ")
        type("y")
        let entry = try XCTUnwrap(keyboardView.predictionStrip.entries.first)
        entry.sendActions(for: .touchDown)
        entry.sendActions(for: .touchUpInside)
        XCTAssertEqual(document.text, "Thank you ")
    }
}
