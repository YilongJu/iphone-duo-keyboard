import UIKit
import XCTest

@testable import DuoKeyboard

/// The meter of the typing speed: words per minute over the last seconds of a run of typing.
final class TypingSpeedMeterTests: XCTestCase {
    /// Types one character at each time.
    private func type(_ meter: inout TypingSpeedMeter, at times: [TimeInterval], characters: Int = 1) {
        for time in times {
            meter.record(characters: characters, at: time)
        }
    }

    func testFiveCharactersInOneSecondAreSixtyWordsPerMinute() {
        var meter = TypingSpeedMeter()
        // The first character starts the clock. 20 more characters follow in 4 seconds.
        type(&meter, at: (0...20).map { Double($0) * 0.2 })
        XCTAssertEqual(meter.wordsPerMinute, 60)
    }

    func testARunShorterThanTwoSecondsGivesNoSpeed() {
        var meter = TypingSpeedMeter()
        type(&meter, at: [0, 0.5, 1, 1.5])
        XCTAssertNil(meter.wordsPerMinute)
        type(&meter, at: [2])
        // 4 characters after the first one, in 2 seconds: 0.8 words in 2 seconds.
        XCTAssertEqual(meter.wordsPerMinute, 24)
    }

    func testALongRunCountsTheLastTenSecondsOnly() {
        var meter = TypingSpeedMeter()
        // 20 seconds at 1 character per second, and then 10 seconds at 4 characters per second.
        type(&meter, at: (0...20).map { Double($0) })
        XCTAssertEqual(meter.wordsPerMinute, 12)
        type(&meter, at: (1...40).map { 20 + Double($0) * 0.25 })
        XCTAssertEqual(meter.wordsPerMinute, 48)
    }

    func testADeletionTakesItsCharacterOutOfTheSpeed() {
        var meter = TypingSpeedMeter()
        type(&meter, at: (0...8).map { Double($0) * 0.5 })
        type(&meter, at: [4.5, 5], characters: -1)
        // 8 characters in, 2 out, in 5 seconds: 1.2 words in 5 seconds.
        XCTAssertEqual(meter.wordsPerMinute, 14)
    }

    func testMoreDeletionsThanCharactersGiveZero() {
        var meter = TypingSpeedMeter()
        type(&meter, at: [0, 1, 2, 3], characters: -1)
        XCTAssertEqual(meter.wordsPerMinute, 0)
    }

    func testAPauseStartsANewRunAndTheLastSpeedStaysUntilTheNewRunHasOne() {
        var meter = TypingSpeedMeter()
        type(&meter, at: (0...20).map { Double($0) * 0.2 })
        XCTAssertEqual(meter.wordsPerMinute, 60)
        // 30 seconds later a new run starts. Its first second gives no speed of its own.
        type(&meter, at: [34, 34.5, 35])
        XCTAssertEqual(meter.wordsPerMinute, 60)
        type(&meter, at: [35.5, 36])
        XCTAssertEqual(meter.wordsPerMinute, 24)
    }

    func testADeletionOfOlderTextDoesNotLowerTheSpeedOfTheTypingAfterIt() {
        var meter = TypingSpeedMeter()
        // 2 seconds of deletes take out text from before the run, and 16 characters follow.
        type(&meter, at: (0...16).map { Double($0) * 0.125 }, characters: -1)
        XCTAssertEqual(meter.wordsPerMinute, 0)
        type(&meter, at: (1...16).map { 2 + Double($0) * 0.25 })
        // 16 characters in the 6 seconds of the run.
        XCTAssertEqual(meter.wordsPerMinute, 32)
    }

    func testAChangeThatTakesOutAndPutsInCountsWithTheDifference() {
        var meter = TypingSpeedMeter()
        type(&meter, at: (0...20).map { Double($0) * 0.25 })
        XCTAssertEqual(meter.wordsPerMinute, 48)
        // A fix of a sentence that makes the text 2 characters longer, as one change.
        meter.record(characters: 2, at: 6)
        // 22 characters in 6 seconds.
        XCTAssertEqual(meter.wordsPerMinute, 44)
    }

    func testAWordThatGoesInAtOnceCountsWithAllItsCharacters() {
        var meter = TypingSpeedMeter()
        // A tap on a predicted word puts the rest of the word and a space in at once.
        meter.record(characters: 1, at: 0)
        meter.record(characters: 1, at: 1)
        meter.record(characters: 9, at: 2)
        XCTAssertEqual(meter.wordsPerMinute, 60)
    }
}

/// A spell checker that reads every word as typed and has fixed predicted words. Each list sits
/// under "previous word|typed letters".
@MainActor
private final class WordsChecker: SpellChecking {
    var words: [String: [String]] = [:]

    func reading(previousWord: String, typed: String, textBefore: String) -> String? { typed }

    func predictedWords(previousWord: String, typed: String, limit: Int) -> [String] {
        Array((words["\(previousWord)|\(typed)"] ?? []).prefix(limit))
    }

    func learn(_ word: String) {}

    func keeps(_ word: String) -> Bool { false }
}

/// The typing speed in the top row: its place, what it counts, and the small Select All key
/// with its icon beside it.
@MainActor
final class TypingSpeedTests: XCTestCase {
    private var keyboardView: KeyboardView!
    private var document: FakeDocument!
    private var controller: KeyboardTextController!
    /// The time of the controller's clock, in seconds.
    private var now: TimeInterval = 0

    private static let widths: [CGFloat] = [466, 669, 951]

    private func makeKeyboard(width: CGFloat = 466, before: String = "", spellChecker: SpellChecking? = nil) {
        let height = KeyboardView.preferredHeight(forWidth: width, compactHeight: false, device: .phone, landscape: false)
        keyboardView = KeyboardView(frame: CGRect(x: 0, y: 0, width: width, height: height))
        document = FakeDocument(before: before)
        controller = KeyboardTextController(
            keyboardView: keyboardView, document: document, spellChecker: spellChecker ?? FakeSpellChecker(),
            pinyinEngine: { PinyinEngine(dictionaryText: testDictionary) })
        now = 0
        controller.typingClock = { [unowned self] in self.now }
        controller.documentDidChange()
        keyboardView.layoutIfNeeded()
    }

    /// Types `text`, one character each quarter of a second.
    private func type(_ text: String) {
        for character in text {
            controller.keyboardView(keyboardView, insert: String(character))
            now += 0.25
        }
    }

    private func keyView(_ kind: KeyKind) throws -> KeyView {
        try XCTUnwrap(keyboardView.subviews.compactMap { $0 as? KeyView }.first { $0.key.kind == kind }, "\(kind)")
    }

    private func tap(_ point: CGPoint) {
        let touch = FakeTouch(at: point)
        keyboardView.touchesBegan([touch], with: nil)
        keyboardView.touchesEnded([touch], with: nil)
    }

    private func widths() -> [CGFloat] {
        // An iPad chooses its layout by the orientation of the screen, so only the compact
        // width gives the same layout there.
        KeyboardDevice.current == .phone ? Self.widths : [466]
    }

    // MARK: Place

    func testTheTypingSpeedLiesBetweenSelectAllAndTheStripAtEveryWidth() throws {
        for width in widths() {
            makeKeyboard(width: width)
            let speed = keyboardView.typingSpeedView
            XCTAssertFalse(speed.isHidden, "\(width)")
            XCTAssertEqual(speed.frame.minX, try keyView(.selectAll).hitFrame.maxX, accuracy: 0.5, "\(width)")
            XCTAssertEqual(speed.frame.maxX, keyboardView.predictionStrip.frame.minX, accuracy: 0.5, "\(width)")
            // The place of the typing speed in the row draws no key.
            XCTAssertTrue(try keyView(.typingSpeed).isHidden, "\(width)")
            // The number and the unit stay at the height of the keys of the row.
            let row = try keyView(.selectAll).hitFrame
            for label in [speed.valueLabel, speed.unitLabel] {
                let box = label.convert(label.bounds, to: keyboardView)
                XCTAssertGreaterThanOrEqual(box.minY, row.minY - 0.5, "\(width)")
                XCTAssertLessThanOrEqual(box.maxY, row.maxY + 0.5, "\(width)")
            }
        }
    }

    func testSelectAllOfTheClosedPhoneHasTheWidthOfCutAndTheTypingSpeedIsWider() throws {
        makeKeyboard(width: 466)
        let selectAll = try keyView(.selectAll).hitFrame.width
        XCTAssertEqual(selectAll, try keyView(.cut).hitFrame.width, accuracy: 0.5)
        XCTAssertGreaterThan(keyboardView.typingSpeedView.frame.width, selectAll)
    }

    func testSelectAllOfTheOpenPhoneIsTwiceAsWideAsCutAndTheTypingSpeed() throws {
        try XCTSkipUnless(KeyboardDevice.current == .phone)
        for width in Self.widths where width > 466 {
            makeKeyboard(width: width)
            let cut = try keyView(.cut).hitFrame.width
            XCTAssertEqual(try keyView(.selectAll).hitFrame.width, 2 * cut, accuracy: 1, "\(width)")
            XCTAssertEqual(keyboardView.typingSpeedView.frame.width, cut, accuracy: 0.5, "\(width)")
        }
    }

    func testAThreeDigitTypingSpeedFitsItsPlaceAtEveryWidth() throws {
        for width in widths() {
            makeKeyboard(width: width)
            let speed = keyboardView.typingSpeedView
            speed.wordsPerMinute = 188
            speed.layoutIfNeeded()
            let label = speed.valueLabel
            let smallest = label.font.withSize(label.font.pointSize * label.minimumScaleFactor)
            let needed = ("188" as NSString).size(withAttributes: [.font: smallest]).width
            XCTAssertGreaterThanOrEqual(label.frame.width, needed, "\(width)")
            XCTAssertGreaterThanOrEqual(label.frame.minX, -0.5, "\(width)")
            XCTAssertLessThanOrEqual(label.frame.maxX, speed.bounds.maxX + 0.5, "\(width)")
        }
    }

    func testSelectAllShowsItsIcon() throws {
        makeKeyboard()
        XCTAssertEqual(try keyView(.selectAll).shownImageName, "select-all")
        XCTAssertNotNil(UIImage(named: "select-all"))
    }

    func testATouchOnTheTypingSpeedPressesNoKey() throws {
        for width in widths() {
            makeKeyboard(width: width, before: "hello")
            let speed = keyboardView.typingSpeedView.frame
            let row = try keyView(.selectAll).hitFrame
            // The left end of the typing speed sits right beside Select All.
            for x in [speed.minX + 1, speed.midX, speed.maxX - 1] {
                for y in [1, row.midY, row.maxY - 1] {
                    tap(CGPoint(x: x, y: y))
                }
            }
            XCTAssertFalse(keyboardView.selectAllActive, "\(width)")
            XCTAssertEqual(document.text, "hello", "\(width)")
            tap(CGPoint(x: row.midX, y: row.midY))
            XCTAssertTrue(keyboardView.selectAllActive, "\(width)")
        }
    }

    // MARK: Speed

    func testTheTopRowShowsNoSpeedBeforeTheFirstRun() {
        makeKeyboard()
        XCTAssertNil(keyboardView.typingSpeedView.wordsPerMinute)
        XCTAssertEqual(keyboardView.typingSpeedView.valueLabel.text, TypingSpeedView.emptyText)
        XCTAssertEqual(keyboardView.typingSpeedView.unitLabel.text, "WPM")
    }

    func testTypedCharactersShowTheirSpeed() {
        makeKeyboard()
        // 11 characters, one each quarter of a second: 10 characters after the first, in 2.5 seconds.
        type("hello world")
        XCTAssertEqual(document.text.count, 11)
        XCTAssertEqual(keyboardView.typingSpeedView.wordsPerMinute, 48)
        XCTAssertEqual(keyboardView.typingSpeedView.valueLabel.text, "48")
    }

    func testATappedPredictedWordCountsWithAllItsCharacters() {
        let checker = WordsChecker()
        checker.words["you|to"] = ["tomorrow"]
        makeKeyboard(spellChecker: checker)
        // 10 characters: 9 after the first, in 2.25 seconds.
        type("See you to")
        XCTAssertEqual(keyboardView.typingSpeedView.wordsPerMinute, 48)
        XCTAssertEqual(keyboardView.predictedWords, ["tomorrow"])
        controller.keyboardView(keyboardView, didSelectPredictedWord: "tomorrow")
        XCTAssertEqual(document.text, "See you tomorrow ")
        // The tap adds 7 characters to the 2 typed letters of the word. All 17 characters of
        // the text count but the first: 16 characters in 2.5 seconds.
        XCTAssertEqual(keyboardView.typingSpeedView.wordsPerMinute, 77)
    }

    func testTheProofreadersFixCountsOnlyWithTheCharactersItAdds() async {
        makeKeyboard()
        let proofreader = FakeProofreader()
        proofreader.answers = ["I came form the office": "I came from the office"]
        controller.proofreader = proofreader
        controller.proofreadPauseSeconds = 0.05
        // 23 characters: 22 after the first, in 5.5 seconds.
        type("I came form the office ")
        XCTAssertEqual(keyboardView.typingSpeedView.wordsPerMinute, 48)
        await controller.pauseTask?.value
        await controller.proofreadTask?.value
        // The person taps the fix 8 seconds after the first character. The fix puts 23
        // characters in place of 23 characters, so the fix adds no character.
        now = 8
        controller.keyboardView(keyboardView, didSelectCandidateAt: 0)
        XCTAssertEqual(document.text, "I came from the office ")
        // Still 22 characters, now in 8 seconds. A fix counted as new text would give 68.
        XCTAssertEqual(keyboardView.typingSpeedView.wordsPerMinute, 33)
    }

    func testTheFirstActionOfARunCountsNoCharacterAlsoWhenItEditsTheTextTwice() {
        let checker = WordsChecker()
        checker.words["you|to"] = ["tomorrow"]
        makeKeyboard(spellChecker: checker)
        type("See you to")
        // A pause ends the run. The clock of this test moves at every reading, as a real clock
        // does, so the two edits of the tap would get two times.
        now = 20
        controller.typingClock = { [unowned self] in
            self.now += 0.0001
            return self.now
        }
        controller.keyboardView(keyboardView, didSelectPredictedWord: "tomorrow")
        XCTAssertEqual(document.text, "See you tomorrow ")
        now += 0.25
        type("at noon st")
        // The tap starts the new run, and the 10 characters after it take 2.5 seconds. With
        // the characters of the tap, the speed would be over 80.
        XCTAssertEqual(keyboardView.typingSpeedView.wordsPerMinute, 48)
    }

    func testPinyinLettersKeepARunOfTypingGoing() {
        makeKeyboard()
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        // The letters wait outside the text, so they add no character, and the run goes on.
        type("ni")
        now = 2.5
        controller.keyboardView(keyboardView, insert: " ")
        XCTAssertEqual(document.text, "\u{4F60}")
        // One character in the 2.5 seconds after the first key press.
        XCTAssertEqual(keyboardView.typingSpeedView.wordsPerMinute, 5)
    }

    func testPastedTextDoesNotCount() throws {
        makeKeyboard()
        type("hello world")
        XCTAssertEqual(keyboardView.typingSpeedView.wordsPerMinute, 48)
        UIPasteboard.general.string = String(repeating: "x", count: 200)
        let paste = try keyView(.paste).hitFrame
        tap(CGPoint(x: paste.midX, y: paste.midY))
        XCTAssertEqual(document.text.count, 211)
        XCTAssertEqual(keyboardView.typingSpeedView.wordsPerMinute, 48)
    }

    func testADeleteLowersTheSpeed() {
        makeKeyboard()
        type("hello world")
        for _ in 0..<5 {
            controller.keyboardViewDeleteBackward(keyboardView)
            now += 0.25
        }
        // 10 characters in and 5 out after the first character, in 3.75 seconds.
        XCTAssertEqual(keyboardView.typingSpeedView.wordsPerMinute, 16)
    }
}
