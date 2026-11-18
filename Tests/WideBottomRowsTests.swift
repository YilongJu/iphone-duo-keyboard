import UIKit
import XCTest

@testable import DuoKeyboard

/// The two bottom rows of the wide layout: no arrow keys, comma, period and slash as wide as a
/// letter key, a longer space bar, and an empty place at the right end of the bottom row.
@MainActor
final class WideBottomRowsTests: XCTestCase {
    private static let layers: [KeyboardLayer] = [.letters, .symbols, .more]

    // MARK: Layout file

    func testTheWideAndTheSplitLayoutHaveNoArrowKeys() {
        for style in [LayoutStyle.wide, .split] {
            for layer in Self.layers {
                let kinds = KeyboardLayout.make(style: style, layer: layer, showsGlobe: true).rows.joined().map(\.kind)
                for arrow in [KeyKind.cursorLeft, .cursorRight, .cursorUp, .cursorDown] {
                    XCTAssertFalse(kinds.contains(arrow), "\(arrow) \(style) \(layer)")
                }
            }
        }
    }

    func testCommaPeriodAndSlashOfTheWideLettersAreAsWideAsALetterKey() throws {
        let row = KeyboardLayout.make(style: .wide, layer: .letters, showsGlobe: true).rows[4]
        let letter = try XCTUnwrap(row.first { $0.kind == .character("m") }).weight
        XCTAssertEqual(letter, 1, accuracy: 0.0001)
        for kind in [KeyKind.dual(",", "<"), .dual(".", ">"), .dual("/", "?")] {
            XCTAssertEqual(try XCTUnwrap(row.first { $0.kind == kind }, "\(kind)").weight, letter, accuracy: 0.0001, "\(kind)")
        }
        // The row still ends with the second shift key, and it fills the layout.
        XCTAssertEqual(row.last?.kind, .shift)
        XCTAssertEqual(row.reduce(0) { $0 + $1.weight }, KeyboardSpec.shared.wide.units, accuracy: 0.0001)
    }

    func testTheSpaceBarOfTheWideBottomRowIsLongerThanWithTheArrowKeys() throws {
        // With the arrow keys the space bar had 6.5 key units in the letters and 7.6 in the
        // symbol layers.
        let lengths: [(KeyboardLayer, CGFloat, CGFloat)] = [(.letters, 6.5, 7.2), (.symbols, 7.6, 8.3), (.more, 7.6, 8.3)]
        for (layer, before, now) in lengths {
            let row = KeyboardLayout.make(style: .wide, layer: layer, showsGlobe: true).rows[5]
            let space = try XCTUnwrap(row.first { $0.kind == .space }, "\(layer)").weight
            XCTAssertGreaterThan(space, before, "\(layer)")
            XCTAssertEqual(space, now, accuracy: 0.0001, "\(layer)")
            XCTAssertEqual(row.reduce(0) { $0 + $1.weight }, KeyboardSpec.shared.wide.units, accuracy: 0.0001, "\(layer)")
        }
    }

    func testTheWideBottomRowEndsWithTheKeyThatHidesTheKeyboardAndAnEmptyPlace() throws {
        for layer in Self.layers {
            let row = KeyboardLayout.make(style: .wide, layer: layer, showsGlobe: true).rows[5]
            XCTAssertEqual(row.suffix(2).map(\.kind), [.dismiss, .empty], "\(layer)")
            // The place has room for two keys of the width of a letter key.
            XCTAssertEqual(try XCTUnwrap(row.last).weight, 2, accuracy: 0.0001, "\(layer)")
        }
    }

    func testTheCompactLayoutKeepsItsRows() {
        // The compact layout never had arrow keys, and it gets no empty place.
        for layer in Self.layers {
            let kinds = KeyboardLayout.make(style: .compact, layer: layer, showsGlobe: true).rows.joined().map(\.kind)
            XCTAssertFalse(kinds.contains(.empty), "\(layer)")
        }
    }

    // MARK: Touches

    private func tap(_ point: CGPoint, on keyboardView: KeyboardView) {
        let touch = FakeTouch(at: point)
        keyboardView.touchesBegan([touch], with: nil)
        keyboardView.touchesEnded([touch], with: nil)
    }

    func testATouchInTheEmptyPlaceOrInTheCornerBesideItPressesNoKey() throws {
        // An iPad chooses its layout by the orientation of the screen, so the widths of the open
        // phone give the wide and the split layout only on a phone.
        try XCTSkipUnless(KeyboardDevice.current == .phone)
        for width in [CGFloat(669), 951] {
            let height = KeyboardView.preferredHeight(forWidth: width, compactHeight: false, device: .phone, landscape: false)
            let keyboardView = KeyboardView(frame: CGRect(x: 0, y: 0, width: width, height: height))
            let document = FakeDocument(before: "hello")
            let controller = KeyboardTextController(
                keyboardView: keyboardView, document: document, spellChecker: FakeSpellChecker(),
                pinyinEngine: { PinyinEngine(dictionaryText: testDictionary) })
            var hidden = 0
            controller.onDismiss = { hidden += 1 }
            controller.documentDidChange()
            keyboardView.layoutIfNeeded()
            let keys = keyboardView.subviews.compactMap { $0 as? KeyView }
            let empty = try XCTUnwrap(keys.first { $0.key.kind == .empty }, "\(width)")
            let dismiss = try XCTUnwrap(keys.first { $0.key.kind == .dismiss }, "\(width)")
            XCTAssertTrue(empty.isHidden, "\(width)")
            XCTAssertFalse(dismiss.isHidden, "\(width)")
            // The empty place is the last cell of the bottom row, right of the key that hides
            // the keyboard.
            XCTAssertEqual(empty.hitFrame.minX, dismiss.hitFrame.maxX, accuracy: 0.5, "\(width)")
            let cell = empty.hitFrame
            for x in [cell.minX + 1, cell.midX, cell.maxX - 1, keyboardView.bounds.maxX - 1] {
                for y in [cell.minY + 1, cell.midY, keyboardView.bounds.maxY - 1] {
                    tap(CGPoint(x: x, y: y), on: keyboardView)
                }
            }
            XCTAssertEqual(hidden, 0, "\(width)")
            XCTAssertEqual(document.text, "hello", "\(width)")
            tap(CGPoint(x: dismiss.hitFrame.midX, y: dismiss.hitFrame.midY), on: keyboardView)
            XCTAssertEqual(hidden, 1, "\(width)")
        }
    }
}
