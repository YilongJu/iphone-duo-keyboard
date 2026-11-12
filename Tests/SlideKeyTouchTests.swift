import UIKit
import XCTest

@testable import DuoKeyboard

/// A finger for the touch tests. UIKit makes a real touch only from the screen, so this one
/// reports the place that a test sets. Each new touch starts 0.01 seconds after the one before
/// it, so two taps on shift are a double tap however long the test machine takes.
final class FakeTouch: UITouch {
    private static var clock = ProcessInfo.processInfo.systemUptime

    var point: CGPoint
    private let time: TimeInterval

    init(at point: CGPoint) {
        self.point = point
        Self.clock += 0.01
        time = Self.clock
        super.init()
    }

    override func location(in view: UIView?) -> CGPoint { point }
    override var timestamp: TimeInterval { time }
}

/// Keeps the calls of a keyboard view that has no typing controller.
@MainActor
final class RecordingKeyboardDelegate: KeyboardViewDelegate {
    var inserted: [String] = []

    func keyboardView(_ keyboardView: KeyboardView, insert text: String) { inserted.append(text) }
    func keyboardViewDeleteBackward(_ keyboardView: KeyboardView) {}
    func keyboardViewReturn(_ keyboardView: KeyboardView) {}
    func keyboardView(_ keyboardView: KeyboardView, moveCursorBy offset: Int) {}
    func keyboardView(_ keyboardView: KeyboardView, edit command: EditCommand) {}
    func keyboardView(_ keyboardView: KeyboardView, didSelectCandidateAt index: Int) {}
    func keyboardViewDismiss(_ keyboardView: KeyboardView) {}
    func keyboardViewDidPressKey(_ keyboardView: KeyboardView) {}
}

/// The compact layout of the folded phone: the keys of its bottom row and the width of its
/// return key.
@MainActor
final class CompactLayoutTests: XCTestCase {
    func testTheCompactLettersHaveACommaKeyAndAPeriodKeyBesideANarrowReturnKey() {
        let row = KeyboardLayout.make(style: .compact, layer: .letters, showsGlobe: true).rows[5]
        XCTAssertEqual(
            row.map(\.kind),
            [.switchLayer(.symbols), .globe, .language, .space, .dual(",", "!"), .dual(".", "?"), .returnKey])
        XCTAssertEqual(row.map(\.weight), [1.25, 1.25, 1, 3, 1, 1, 1.5])
    }

    func testTheCompactReturnKeyIsOneAndAHalfUnitsWideOnEveryLayer() {
        for layer in [KeyboardLayer.letters, .symbols, .more] {
            let layout = KeyboardLayout.make(style: .compact, layer: layer, showsGlobe: true)
            XCTAssertEqual(layout.units, 10)
            XCTAssertEqual(layout.rows.joined().filter { $0.kind == .returnKey }.map(\.weight), [1.5])
            for row in layout.rows {
                XCTAssertLessThanOrEqual(row.reduce(0) { $0 + $1.weight }, 10.0001)
            }
            // The bottom row fills the layout, so the space bar took the width that the return key gave up.
            XCTAssertEqual(layout.rows[5].reduce(0) { $0 + $1.weight }, 10, accuracy: 0.0001)
        }
    }
}

/// The keyboard width of the folded phone in portrait, of the open phone in portrait, and of the
/// open phone in landscape, in points.
private let compactWidth: CGFloat = 466
private let wideWidth: CGFloat = 669
private let splitWidth: CGFloat = 951

/// Fingers on the keys of the compact letters layer: a slide up or down on a letter key with a
/// slide character, and the comma and period keys. The tests send touches to the keyboard view
/// and read the text that the typing controller wrote.
@MainActor
final class SlideKeyTouchTests: XCTestCase {
    private var keyboardView: KeyboardView!
    private var document: FakeDocument!
    private var spellChecker: FakeSpellChecker!
    private var controller: KeyboardTextController!

    private func makeView(width: CGFloat) -> KeyboardView {
        let height = KeyboardView.preferredHeight(
            forWidth: width, compactHeight: false, device: .phone, landscape: false)
        let view = KeyboardView(frame: CGRect(x: 0, y: 0, width: width, height: height))
        view.setNeedsLayout()
        view.layoutIfNeeded()
        return view
    }

    private func makeKeyboard(
        width: CGFloat = compactWidth, before: String = "",
        autocapitalization: UITextAutocapitalizationType = .none
    ) {
        keyboardView = makeView(width: width)
        document = FakeDocument(before: before)
        document.autocapitalizationType = autocapitalization
        spellChecker = FakeSpellChecker()
        controller = KeyboardTextController(
            keyboardView: keyboardView, document: document, spellChecker: spellChecker,
            pinyinEngine: { PinyinEngine(dictionaryText: testDictionary) })
        controller.documentDidChange()
    }

    // MARK: Places on the keyboard

    /// The cells of the keys on screen, row by row from the top, and from left to right in a row.
    private func cells(of view: KeyboardView) -> [[CGRect]] {
        let frames = view.subviews.compactMap { $0 as? KeyView }.filter { !$0.isHidden }.map(\.hitFrame)
        let tops = Set(frames.map { $0.minY.rounded() }).sorted()
        return tops.map { top in frames.filter { $0.minY.rounded() == top }.sorted { $0.minX < $1.minX } }
    }

    private func cell(row: Int, column: Int, of view: KeyboardView? = nil) throws -> CGRect {
        let rows = cells(of: view ?? keyboardView)
        guard rows.indices.contains(row), rows[row].indices.contains(column) else {
            throw MissingKey(text: "The keyboard has no key at row \(row), column \(column)")
        }
        return rows[row][column]
    }

    /// The cell of a letter key. In the compact layout the rows A to L and Q to P start with a
    /// letter. Every other letter row starts with one function key.
    private func cell(_ letter: Character, of view: KeyboardView? = nil) throws -> CGRect {
        let view: KeyboardView = view ?? keyboardView
        for (row, letters) in [(2, "qwertyuiop"), (3, "asdfghjkl"), (4, "zxcvbnm")] {
            if let index = Array(letters).firstIndex(of: letter) {
                let firstColumn = view.style == .compact && row != 4 ? 0 : 1
                return try cell(row: row, column: firstColumn + index, of: view)
            }
        }
        throw MissingKey(text: "\(letter) is not a letter key")
    }

    private struct MissingKey: Error {
        let text: String
    }

    /// The texts that the key of a cell shows now, from the top of the key to its bottom.
    private func shownTexts(at cell: CGRect) throws -> [String] {
        let keyViews = keyboardView.subviews.compactMap { $0 as? KeyView }
        guard let keyView = keyViews.first(where: { $0.hitFrame == cell }) else {
            throw MissingKey(text: "The keyboard has no key with the cell \(cell)")
        }
        keyView.layoutIfNeeded()
        let labels = keyView.subviews.compactMap { $0 as? UILabel }.filter { $0.text != nil && !$0.frame.isEmpty }
        return labels.sorted { $0.frame.midY < $1.frame.midY }.compactMap(\.text)
    }

    private var shiftKey: CGRect { get throws { try cell(row: 4, column: 0) } }
    private var commaKey: CGRect { get throws { try cell(row: 5, column: 4) } }
    private var periodKey: CGRect { get throws { try cell(row: 5, column: 5) } }

    // MARK: Fingers

    private func press(_ point: CGPoint, on view: KeyboardView? = nil) -> FakeTouch {
        let touch = FakeTouch(at: point)
        (view ?? keyboardView).touchesBegan([touch], with: nil)
        return touch
    }

    private func press(_ cell: CGRect, on view: KeyboardView? = nil) -> FakeTouch {
        press(CGPoint(x: cell.midX, y: cell.midY), on: view)
    }

    /// Moves a finger in steps of 2 points, as a real finger gives many small moves. `rows` is
    /// the vertical part in letter row heights, and a value below zero is a move up. `keys` is
    /// the part to the side in widths of the key the finger started on.
    private func drag(_ touch: FakeTouch, rows: CGFloat = 0, keys: CGFloat = 0, from cell: CGRect, on view: KeyboardView? = nil) {
        let dx = keys * cell.width
        let dy = rows * cell.height
        let steps = max(1, Int((max(abs(dx), abs(dy)) / 2).rounded(.up)))
        let start = touch.point
        for step in 1...steps {
            let part = CGFloat(step) / CGFloat(steps)
            touch.point = CGPoint(x: start.x + dx * part, y: start.y + dy * part)
            (view ?? keyboardView).touchesMoved([touch], with: nil)
        }
    }

    private func lift(_ touch: FakeTouch, from view: KeyboardView? = nil) {
        (view ?? keyboardView).touchesEnded([touch], with: nil)
    }

    private func tap(_ cell: CGRect) {
        lift(press(cell))
    }

    private func tap(_ letters: String) throws {
        for letter in letters {
            tap(try cell(letter))
        }
    }

    /// A press on the middle of a key, a move up or down, and a lift.
    private func slide(_ cell: CGRect, rows: CGFloat) {
        let touch = press(cell)
        drag(touch, rows: rows, from: cell)
        lift(touch)
    }

    // MARK: A slide on a letter key

    func testASlideUpOrDownOnALetterKeyTypesItsSlideCharacter() throws {
        makeKeyboard()
        slide(try cell("a"), rows: -0.5)
        slide(try cell("a"), rows: 0.5)
        XCTAssertEqual(document.text, "@@")
        // Each letter of the rows A to L and Z to M has its own slide character.
        for letter in "sdfghjklzxcvbnm" {
            slide(try cell(letter), rows: -0.5)
        }
        XCTAssertEqual(document.text, "@@#$&*()'\"%-+=/;:")
    }

    func testAShortVerticalMoveTypesTheLetter() throws {
        makeKeyboard()
        slide(try cell("a"), rows: -0.3)
        slide(try cell("m"), rows: 0.3)
        XCTAssertEqual(document.text, "am")
    }

    func testASlideBackToTheStartTypesTheLetter() throws {
        makeKeyboard()
        let key = try cell("d")
        XCTAssertEqual(try shownTexts(at: key), ["$", "d"])
        let touch = press(key)
        drag(touch, rows: -0.6, from: key)
        // The key shows the selected slide character alone.
        XCTAssertEqual(try shownTexts(at: key), ["$"])
        drag(touch, rows: 0.5, from: key)
        XCTAssertEqual(try shownTexts(at: key), ["$", "d"])
        lift(touch)
        XCTAssertEqual(document.text, "d")
    }

    func testAKeyOfTheTopLetterRowHasNoSlideCharacter() throws {
        makeKeyboard()
        // A move down from "q" goes to the key under the finger, as a move from every key
        // without a slide character does. The move also goes a little to the right, because
        // the middle of "q" is over the left edge of "a".
        let key = try cell("q")
        let touch = press(key)
        drag(touch, rows: 0.6, keys: 0.25, from: key)
        lift(touch)
        XCTAssertEqual(document.text, "a")
    }

    func testASlowPressOnALetterKeyTypesTheLetter() throws {
        makeKeyboard()
        let touch = press(try cell("a"))
        RunLoop.current.run(until: Date().addingTimeInterval(0.45))
        lift(touch)
        XCTAssertEqual(document.text, "a")
    }

    // MARK: The key that a moving touch belongs to

    func testAVerticalMoveStaysWithItsKey() throws {
        makeKeyboard()
        let key = try cell("a")
        // The finger lands 2 points under the top edge of "a" and moves up, so it is over "q" at once.
        let nearTopEdge = CGPoint(x: key.midX, y: key.minY + 2)
        var touch = press(nearTopEdge)
        drag(touch, rows: -0.3, from: key)
        lift(touch)
        XCTAssertEqual(document.text, "a")

        touch = press(nearTopEdge)
        drag(touch, rows: -0.5, from: key)
        lift(touch)
        XCTAssertEqual(document.text, "a@")

        // A move down from the bottom row of letters does not go to the space bar.
        let bottomKey = try cell("b")
        touch = press(CGPoint(x: bottomKey.midX, y: bottomKey.maxY - 2))
        drag(touch, rows: 0.3, from: bottomKey)
        lift(touch)
        XCTAssertEqual(document.text, "a@b")
    }

    func testAMoveToTheSideStillGoesToTheKeyUnderTheFinger() throws {
        makeKeyboard()
        let key = try cell("a")
        var touch = press(key)
        drag(touch, keys: 1, from: key)
        lift(touch)
        XCTAssertEqual(document.text, "s")

        // The new key starts its own move at its left edge, so a slide up from there types the
        // slide character of "s".
        touch = press(key)
        drag(touch, keys: 0.6, from: key)
        drag(touch, rows: -0.5, from: key)
        lift(touch)
        XCTAssertEqual(document.text, "s#")
    }

    // MARK: Shift

    func testShiftAndALetterKeyTypeTheCapitalAndNeverTheSlideCharacter() throws {
        // Manual shift.
        makeKeyboard()
        tap(try shiftKey)
        XCTAssertEqual(keyboardView.shiftState, .on)
        try tap("aa")
        XCTAssertEqual(document.text, "Aa")

        // Caps lock, after two quick taps on shift.
        makeKeyboard()
        tap(try shiftKey)
        tap(try shiftKey)
        XCTAssertEqual(keyboardView.shiftState, .locked)
        try tap("az")
        XCTAssertEqual(document.text, "AZ")

        // Automatic shift at the start of a sentence.
        makeKeyboard(autocapitalization: .sentences)
        XCTAssertEqual(keyboardView.shiftState, .on)
        XCTAssertTrue(keyboardView.shiftIsAutomatic)
        try tap("az")
        XCTAssertEqual(document.text, "Az")
    }

    func testASlideTypesTheSlideCharacterInEveryShiftState() throws {
        makeKeyboard()
        tap(try shiftKey)
        slide(try cell("a"), rows: -0.5)
        XCTAssertEqual(document.text, "@")

        makeKeyboard()
        tap(try shiftKey)
        tap(try shiftKey)
        slide(try cell("s"), rows: -0.5)
        try tap("s")
        XCTAssertEqual(document.text, "#S")

        makeKeyboard(autocapitalization: .sentences)
        slide(try cell("h"), rows: -0.5)
        XCTAssertEqual(document.text, "(")
    }

    /// The keyboard view leaves the shift state alone when a slide types a character. The owner
    /// sets the automatic shift again from the text, so the next letter still gets its capital
    /// when the text asks for one.
    func testASlideLeavesAnAutomaticShiftOn() throws {
        let view = makeView(width: compactWidth)
        let delegate = RecordingKeyboardDelegate()
        view.delegate = delegate
        view.setAutomaticShift(true)

        let key = try cell("a", of: view)
        var touch = press(key, on: view)
        drag(touch, rows: -0.5, from: key, on: view)
        lift(touch, from: view)
        XCTAssertEqual(delegate.inserted, ["@"])
        XCTAssertEqual(view.shiftState, .on)
        XCTAssertTrue(view.shiftIsAutomatic)

        // A two-character key does the same.
        let digit = try cell(row: 1, column: 0, of: view)
        touch = press(digit, on: view)
        drag(touch, rows: 0.5, from: digit, on: view)
        lift(touch, from: view)
        XCTAssertEqual(delegate.inserted, ["@", "!"])
        XCTAssertEqual(view.shiftState, .on)

        lift(press(key, on: view), from: view)
        XCTAssertEqual(delegate.inserted, ["@", "!", "A"])
        XCTAssertEqual(view.shiftState, .off)
    }

    // MARK: Two fingers and a cancelled touch

    func testASecondFingerTypesTheSlideCharacterOfTheFirstFinger() throws {
        makeKeyboard()
        let key = try cell("a")
        let first = press(key)
        drag(first, rows: -0.6, from: key)
        let second = press(try cell("s"))
        XCTAssertEqual(document.text, "@")
        lift(second)
        lift(first)
        XCTAssertEqual(document.text, "@s")
    }

    func testASecondFingerTypesTheLetterOfAFirstFingerThatDidNotSlide() throws {
        makeKeyboard()
        let first = press(try cell("a"))
        let second = press(try cell("s"))
        XCTAssertEqual(document.text, "a")
        lift(first)
        lift(second)
        XCTAssertEqual(document.text, "as")
    }

    func testACancelledTouchTypesWhatTheKeyShows() throws {
        makeKeyboard()
        let key = try cell("a")
        var touch = press(key)
        drag(touch, rows: -0.6, from: key)
        keyboardView.touchesCancelled([touch], with: nil)
        touch = press(key)
        keyboardView.touchesCancelled([touch], with: nil)
        XCTAssertEqual(document.text, "@a")
    }

    // MARK: The typing rules behind the keys

    func testChineseModeTypesTheChineseFormOfASlideCharacter() throws {
        makeKeyboard()
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        slide(try cell("h"), rows: -0.5)
        slide(try cell("j"), rows: -0.5)
        slide(try cell("n"), rows: -0.5)
        slide(try cell("m"), rows: -0.5)
        XCTAssertEqual(document.text, "\u{FF08}\u{FF09}\u{FF1B}\u{FF1A}")
        // The quotation mark opens and then closes.
        slide(try cell("l"), rows: -0.5)
        slide(try cell("l"), rows: -0.5)
        XCTAssertEqual(document.text, "\u{FF08}\u{FF09}\u{FF1B}\u{FF1A}\u{201C}\u{201D}")
    }

    func testASlideCharacterEndsThePinyinWordAsATappedMarkDoes() throws {
        makeKeyboard()
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        try tap("nihao")
        XCTAssertEqual(controller.pinyinBuffer, "nihao")
        slide(try cell("m"), rows: -0.5)
        XCTAssertEqual(document.text, "\u{4F60}\u{597D}\u{FF1A}")

        // The apostrophe of "k" splits two syllables, as the apostrophe of the symbols layer does.
        makeKeyboard()
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        try tap("xi")
        slide(try cell("k"), rows: -0.5)
        try tap("an")
        XCTAssertEqual(controller.pinyinBuffer, "xi'an")
        tap(try cell(row: 5, column: 3))
        XCTAssertEqual(document.text, "\u{897F}\u{5B89}")
    }

    func testASlideCharacterAfterATypoGivesTheCorrectionOfTheTappedSymbol() throws {
        // The semicolon ends a word, so the word before it is corrected.
        makeKeyboard()
        try tap("teh")
        slide(try cell("n"), rows: -0.5)
        let bySlide = document.text
        let requestsBySlide = spellChecker.requests

        makeKeyboard()
        try tap("teh")
        controller.keyboardView(keyboardView, insert: ";")
        XCTAssertEqual(bySlide, "the;")
        XCTAssertEqual(bySlide, document.text)
        XCTAssertEqual(requestsBySlide, spellChecker.requests)

        // The at sign does not end a word, so the typed word stays, by a slide and by a tap.
        makeKeyboard()
        try tap("teh")
        slide(try cell("a"), rows: -0.5)
        XCTAssertEqual(document.text, "teh@")
        XCTAssertEqual(spellChecker.requests, [])
    }

    // MARK: The comma key and the period key

    func testTheCommaKeyAndThePeriodKeyTypeTheirTwoCharacters() throws {
        makeKeyboard()
        tap(try commaKey)
        tap(try periodKey)
        slide(try commaKey, rows: -0.5)
        slide(try periodKey, rows: -0.5)
        slide(try commaKey, rows: 0.5)
        XCTAssertEqual(document.text, ",.!?!")
    }

    func testALongPressOnTheCommaKeyOrThePeriodKeyTypesTheUpperCharacter() throws {
        makeKeyboard()
        for key in [try commaKey, try periodKey] {
            let touch = press(key)
            RunLoop.current.run(until: Date().addingTimeInterval(0.45))
            lift(touch)
        }
        XCTAssertEqual(document.text, "!?")
    }

    func testShiftOnTheCommaKeyAndThePeriodKey() throws {
        // Manual shift types the upper character, as on every two-character key.
        makeKeyboard()
        tap(try shiftKey)
        tap(try commaKey)
        tap(try shiftKey)
        tap(try periodKey)
        XCTAssertEqual(document.text, "!?")

        // Automatic shift and caps lock type the comma and the period.
        makeKeyboard(autocapitalization: .sentences)
        XCTAssertTrue(keyboardView.shiftIsAutomatic)
        tap(try commaKey)
        XCTAssertEqual(document.text, ",")

        makeKeyboard()
        tap(try shiftKey)
        tap(try shiftKey)
        XCTAssertEqual(keyboardView.shiftState, .locked)
        tap(try commaKey)
        tap(try periodKey)
        XCTAssertEqual(document.text, ",.")
    }

    func testATypoBeforeTheCommaKeyIsCorrected() throws {
        makeKeyboard()
        try tap("teh")
        slide(try periodKey, rows: -0.5)
        XCTAssertEqual(document.text, "the?")

        makeKeyboard()
        try tap("teh")
        tap(try commaKey)
        XCTAssertEqual(document.text, "the,")
    }

    // MARK: The wide layout and the split layout

    /// The letter keys of the wide layout and of the split layout have no slide character. A
    /// move up from "a" goes to "q", and a slide on the comma key types its upper character.
    func testTheWideLayoutAndTheSplitLayoutKeepTheirKeys() throws {
        try XCTSkipUnless(KeyboardDevice.current == .phone, "An iPad chooses its layout by the orientation of the screen")
        for (width, style) in [(wideWidth, LayoutStyle.wide), (splitWidth, .split)] {
            makeKeyboard(width: width)
            XCTAssertEqual(keyboardView.style, style)
            try tap("a")
            slide(try cell("a"), rows: -0.6)
            slide(try cell("m"), rows: -0.3)
            XCTAssertEqual(document.text, "aqm")
        }
        makeKeyboard(width: wideWidth)
        // In the wide layout the comma key follows "m" in the row of "z".
        slide(try cell(row: 4, column: 8), rows: -0.5)
        XCTAssertEqual(document.text, "<")
    }
}
