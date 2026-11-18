import UIKit
import XCTest

@testable import DuoKeyboard

/// The English emoji in the top row of keys. The emoji take the first places of the prediction
/// strip, which lies between the Select All key and the Cut key. The keys of the row keep their
/// place and their size when emoji come and go. A tap on an emoji types it, and every other
/// touch on the row reaches its key at once, with no pause after the emoji leave.
@MainActor
final class TopRowEmojiTests: XCTestCase {
    private var keyboardView: KeyboardView!
    private var document: FakeDocument!
    private var controller: KeyboardTextController!

    /// The widths of the folded phone, the open phone in portrait, and the open phone in landscape.
    private static let compactWidth: CGFloat = 466
    private static let wideWidth: CGFloat = 669
    private static let splitWidth: CGFloat = 951

    private static let topKinds: [KeyKind] = [.selectAll, .cut, .copy, .paste]

    private func makeKeyboard(width: CGFloat) {
        let height = KeyboardView.preferredHeight(forWidth: width, compactHeight: false, device: .phone, landscape: false)
        keyboardView = KeyboardView(frame: CGRect(x: 0, y: 0, width: width, height: height))
        keyboardView.overrideUserInterfaceStyle = .light
        keyboardView.layoutIfNeeded()
        document = FakeDocument(before: "")
        controller = KeyboardTextController(
            keyboardView: keyboardView, document: document, spellChecker: FakeSpellChecker(),
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

    /// The emoji labels outside the keys and the candidate row, from left to right.
    private func emojiLabels() -> [UILabel] {
        keyboardView.layoutIfNeeded()
        var views: [UIView] = keyboardView.subviews.filter { !($0 is KeyView) && !($0 is CandidateBar) }
        var labels: [UILabel] = []
        while let view = views.popLast() {
            if view.isHidden { continue }
            if let label = view as? UILabel, let text = label.text, !text.isEmpty { labels.append(label) }
            views += view.subviews
        }
        return labels.sorted { frame(of: $0).minX < frame(of: $1).minX }
    }

    /// The frames of the icon and the texts of a key, in the coordinates of the keyboard view.
    private func contentFrames(_ keyView: KeyView) -> [CGRect] {
        keyView.layoutIfNeeded()
        var frames: [CGRect] = []
        var views = keyView.subviews
        while let view = views.popLast() {
            views += view.subviews
            if view.isHidden { continue }
            if let label = view as? UILabel, label.text?.isEmpty == false {
                frames.append(frame(of: label))
            } else if let imageView = view as? UIImageView, let image = imageView.image {
                // The icon view fills the key and draws its image in the middle.
                let full = frame(of: imageView)
                frames.append(CGRect(
                    x: full.midX - image.size.width / 2, y: full.midY - image.size.height / 2,
                    width: image.size.width, height: image.size.height))
            }
        }
        return frames.sorted { ($0.minX, $0.minY) < ($1.minX, $1.minY) }
    }

    /// The drawn background of a key: the first view of the key, the key itself included, that
    /// has a background color, in the coordinates of the keyboard view.
    private func drawnFrame(_ keyView: KeyView) throws -> CGRect {
        keyView.layoutIfNeeded()
        var views: [UIView] = [keyView]
        while !views.isEmpty {
            let view = views.removeFirst()
            if let color = view.backgroundColor, color.cgColor.alpha > 0, !view.isHidden {
                return frame(of: view)
            }
            views += view.subviews
        }
        throw MissingBackground(kind: keyView.key.kind)
    }

    private struct MissingBackground: Error {
        let kind: KeyKind
    }

    private func allContentFrames() throws -> [[CGRect]] {
        try Self.topKinds.map { contentFrames(try keyView($0)) }
    }

    private func allDrawnFrames() throws -> [CGRect] {
        try Self.topKinds.map { try drawnFrame(try keyView($0)) }
    }

    /// A finger tap that reaches the keyboard view itself, as a tap on a key does.
    private func tap(_ point: CGPoint) {
        let touch = FakeTouch(at: point)
        keyboardView.touchesBegan([touch], with: nil)
        keyboardView.touchesEnded([touch], with: nil)
    }

    /// The strip's entries that hold an emoji, from left to right.
    private func emojiEntries() -> [PredictionStripEntry] {
        keyboardView.predictionStrip.entries.filter {
            if case .emoji = $0.item { return true }
            return false
        }
    }

    private func widths() throws -> [CGFloat] {
        guard KeyboardDevice.current == .phone else { return [Self.compactWidth] }
        return [Self.compactWidth, Self.wideWidth]
    }

    // MARK: Place

    func testTheEmojiTakeTheFirstPlacesOfThePredictionStrip() throws {
        for width in try widths() {
            makeKeyboard(width: width)
            type("good ")
            let labels = emojiLabels()
            XCTAssertEqual(labels.compactMap(\.text), ["\u{1F44D}", "\u{1F44F}"], "\(width)")
            let selectAll = try drawnFrame(try keyView(.selectAll))
            let cut = try drawnFrame(try keyView(.cut))
            let row = try keyView(.selectAll).hitFrame
            let strip = keyboardView.predictionStrip.frame
            // The first emoji starts at the left end of the strip, right after Select All.
            let first = frame(of: emojiEntries()[0])
            XCTAssertEqual(first.minX, strip.minX, accuracy: 4, "\(width)")
            for label in labels {
                let box = frame(of: label)
                XCTAssertGreaterThanOrEqual(box.minX, selectAll.maxX, "\(width)")
                XCTAssertLessThanOrEqual(box.maxX, cut.minX, "\(width)")
                XCTAssertGreaterThanOrEqual(box.minY, row.minY - 0.5, "\(width)")
                XCTAssertLessThanOrEqual(box.maxY, row.maxY + 0.5, "\(width)")
            }
        }
    }

    func testTheKeyIconsAndLabelsDoNotMoveWhenEmojiComeAndGo() throws {
        for width in try widths() {
            makeKeyboard(width: width)
            let without = try allContentFrames()
            type("good ")
            XCTAssertEqual(emojiLabels().count, 2, "\(width)")
            XCTAssertEqual(try allContentFrames(), without, "\(width)")
            type("x")
            XCTAssertEqual(emojiLabels().count, 0, "\(width)")
            XCTAssertEqual(try allContentFrames(), without, "\(width)")
        }
    }

    func testEveryTopRowKeyKeepsItsBackgroundWhenEmojiComeAndGo() throws {
        for width in try widths() {
            makeKeyboard(width: width)
            let before = try allDrawnFrames()
            type("good ")
            XCTAssertEqual(emojiLabels().count, 2, "\(width)")
            XCTAssertEqual(try allDrawnFrames(), before, "\(width)")
            type("x")
            XCTAssertEqual(emojiLabels().count, 0, "\(width)")
            XCTAssertEqual(try allDrawnFrames(), before, "\(width)")
        }
    }

    func testTheSplitLayoutShowsTheEmojiAtTheLeftEndOfItsStrip() throws {
        try XCTSkipUnless(KeyboardDevice.current == .phone, "An iPad chooses its layout by the orientation of the screen")
        makeKeyboard(width: Self.splitWidth)
        XCTAssertEqual(keyboardView.style, .split)
        let before = try allDrawnFrames()
        let contents = try allContentFrames()
        type("good ")
        XCTAssertEqual(emojiLabels().count, 2)
        XCTAssertEqual(try allDrawnFrames(), before)
        XCTAssertEqual(try allContentFrames(), contents)
        let selectAll = try drawnFrame(try keyView(.selectAll))
        // The strip crosses the empty middle. The emoji stay in the left half, beside Select All.
        for label in emojiLabels() {
            XCTAssertGreaterThanOrEqual(frame(of: label).minX, selectAll.maxX)
            XCTAssertLessThan(frame(of: label).maxX, Self.splitWidth / 2)
        }
    }

    // MARK: Touches

    func testATapOnAnEmojiTypesTheEmoji() throws {
        for width in try widths() {
            makeKeyboard(width: width)
            type("good ")
            let entry = try XCTUnwrap(emojiEntries().first, "\(width)")
            entry.sendActions(for: .touchDown)
            entry.sendActions(for: .touchUpInside)
            XCTAssertEqual(document.text, "\u{1F44D} ", "\(width)")
        }
    }

    func testAnEmojiTakesTheFullHeightOfTheRowAndTheEdgeAboveIt() throws {
        // A finger that lands a little above or below the emoji still types it.
        for width in try widths() {
            makeKeyboard(width: width)
            type("good ")
            let row = try keyView(.selectAll).hitFrame
            let box = frame(of: try XCTUnwrap(emojiEntries().first, "\(width)"))
            XCTAssertEqual(box.minY, 0, accuracy: 0.5, "\(width)")
            XCTAssertEqual(box.maxY, row.maxY, accuracy: 0.5, "\(width)")
        }
    }

    func testTheKeysBesideTheEmojiKeepWorking() throws {
        for width in try widths() {
            makeKeyboard(width: width)
            type("good ")
            XCTAssertEqual(emojiLabels().count, 2)
            // The Paste key reacts while emoji show.
            UIPasteboard.general.string = "x"
            let paste = try drawnFrame(try keyView(.paste))
            tap(CGPoint(x: paste.midX, y: paste.midY))
            XCTAssertEqual(document.text, "good x", "\(width)")
            // Select All reacts while emoji show.
            type(" good ")
            XCTAssertEqual(emojiLabels().count, 2)
            let selectAll = try drawnFrame(try keyView(.selectAll))
            tap(CGPoint(x: selectAll.midX, y: selectAll.midY))
            XCTAssertTrue(keyboardView.selectAllActive, "\(width)")
        }
    }

    func testATouchOnTheStripBesideTheEmojiPressesNoKey() throws {
        // A touch in the strip that lands on no entry reaches the keyboard view. The keys beside
        // the strip are Select All and Cut, and neither of them reacts.
        for width in try widths() {
            makeKeyboard(width: width)
            type("good ")
            let strip = keyboardView.predictionStrip.frame
            let row = try keyView(.selectAll).hitFrame
            UIPasteboard.general.string = "old"
            tap(CGPoint(x: strip.maxX - 1, y: row.midY))
            tap(CGPoint(x: strip.minX + 1, y: row.midY))
            XCTAssertEqual(document.text, "good ", "\(width)")
            XCTAssertFalse(keyboardView.selectAllActive, "\(width)")
            XCTAssertEqual(UIPasteboard.general.string, "old", "\(width)")
        }
    }

    func testTheTopRowWorksRightAfterTheEmojiLeave() throws {
        makeKeyboard(width: Self.compactWidth)
        type("good ")
        XCTAssertEqual(emojiLabels().count, 2)
        type("x")
        XCTAssertEqual(emojiLabels().count, 0)
        // No pause: the very next touch on Select All reaches the key.
        let selectAll = try drawnFrame(try keyView(.selectAll))
        tap(CGPoint(x: selectAll.midX, y: selectAll.midY))
        XCTAssertTrue(keyboardView.selectAllActive)
    }

    func testASecondFingerOnAnEmojiThatALetterTookAwayTypesNoEmoji() throws {
        // A second finger commits the letter of the first finger, and the letter ends the word,
        // so the emoji leave as the second finger lands on their place.
        makeKeyboard(width: Self.compactWidth)
        UIPasteboard.general.items = []
        type("good ")
        let entry = try XCTUnwrap(emojiEntries().first)
        let letterKey = try keyView(.slide("x", "-")).hitFrame
        let letter = FakeTouch(at: CGPoint(x: letterKey.midX, y: letterKey.midY))
        keyboardView.touchesBegan([letter], with: nil)
        entry.sendActions(for: .touchDown)
        entry.sendActions(for: .touchUpInside)
        keyboardView.touchesEnded([letter], with: nil)
        XCTAssertEqual(document.text, "good x")
        XCTAssertEqual(emojiLabels().count, 0)
    }

    // MARK: Other text

    func testChineseModeAndFieldsWithoutAutocorrectionShowNoTopRowEmoji() throws {
        makeKeyboard(width: Self.compactWidth)
        document.allowsAutocorrection = false
        type("good ")
        XCTAssertEqual(emojiLabels().count, 0)
        makeKeyboard(width: Self.compactWidth)
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        type("hao")
        XCTAssertEqual(emojiLabels().count, 0)
    }
}
