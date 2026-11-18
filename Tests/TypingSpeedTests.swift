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

    func testAWordThatGoesInAtOnceCountsWithAllItsCharacters() {
        var meter = TypingSpeedMeter()
        // A tap on a predicted word puts the rest of the word and a space in at once.
        meter.record(characters: 1, at: 0)
        meter.record(characters: 1, at: 1)
        meter.record(characters: 9, at: 2)
        XCTAssertEqual(meter.wordsPerMinute, 60)
    }
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

    private func makeKeyboard(width: CGFloat = 466, before: String = "") {
        let height = KeyboardView.preferredHeight(forWidth: width, compactHeight: false, device: .phone, landscape: false)
        keyboardView = KeyboardView(frame: CGRect(x: 0, y: 0, width: width, height: height))
        document = FakeDocument(before: before)
        controller = KeyboardTextController(
            keyboardView: keyboardView, document: document, spellChecker: FakeSpellChecker(),
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

    func testSelectAllHasTheWidthOfCutAndTheTypingSpeedIsWider() throws {
        for width in widths() {
            makeKeyboard(width: width)
            let selectAll = try keyView(.selectAll).hitFrame.width
            XCTAssertEqual(selectAll, try keyView(.cut).hitFrame.width, accuracy: 0.5, "\(width)")
            XCTAssertGreaterThan(keyboardView.typingSpeedView.frame.width, selectAll, "\(width)")
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
