import UIKit
import XCTest

@testable import DuoKeyboard

/// The lower rows of the wide layout: no arrow keys, comma, period and slash as wide as a
/// letter key, a longer space bar, the return key at the right end of the bottom row, and the
/// newline key at the right end of the home row.
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

    func testTheWideBottomRowEndsWithTheKeyThatHidesTheKeyboardAndTheReturnKey() throws {
        for style in [LayoutStyle.wide, .split] {
            for layer in Self.layers {
                let rows = KeyboardLayout.make(style: style, layer: layer, showsGlobe: true).rows
                XCTAssertEqual(rows[5].suffix(2).map(\.kind), [.dismiss, .returnKey], "\(style) \(layer)")
                // The return key is as wide as two letter keys.
                XCTAssertEqual(try XCTUnwrap(rows[5].last).weight, 2, accuracy: 0.0001, "\(style) \(layer)")
                // The layer has no other return key and no empty place.
                let kinds = rows.joined().map(\.kind)
                XCTAssertEqual(kinds.filter { $0 == .returnKey }.count, 1, "\(style) \(layer)")
                XCTAssertFalse(kinds.contains(.empty), "\(style) \(layer)")
            }
        }
    }

    func testTheNewlineKeyHasTheFormerPlaceOfTheReturnKey() throws {
        // The return key ended the home row of the letters with 1.35 key units, and the fourth
        // row of the symbol layers with 1.5.
        let widths: [(KeyboardLayer, CGFloat)] = [(.letters, 1.35), (.symbols, 1.5), (.more, 1.5)]
        for style in [LayoutStyle.wide, .split] {
            for (layer, width) in widths {
                let rows = KeyboardLayout.make(style: style, layer: layer, showsGlobe: true).rows
                let last = try XCTUnwrap(rows[3].last, "\(style) \(layer)")
                XCTAssertEqual(last.kind, .newline, "\(style) \(layer)")
                XCTAssertEqual(last.weight, width, accuracy: 0.0001, "\(style) \(layer)")
                XCTAssertEqual(rows.joined().filter { $0.kind == .newline }.count, 1, "\(style) \(layer)")
            }
        }
    }

    func testTheCompactLayoutKeepsItsRows() {
        // The compact layout never had arrow keys. It has no empty place and no newline key,
        // and its return key stays in the bottom row.
        for layer in Self.layers {
            let rows = KeyboardLayout.make(style: .compact, layer: layer, showsGlobe: true).rows
            let kinds = rows.joined().map(\.kind)
            XCTAssertFalse(kinds.contains(.empty), "\(layer)")
            XCTAssertFalse(kinds.contains(.newline), "\(layer)")
            XCTAssertEqual(rows[5].last?.kind, .returnKey, "\(layer)")
        }
    }

    // MARK: The newline key's text

    func testTheNewlineKeyTypesALineBreakThatAnActionFieldDoesNotReadAsItsAction() {
        XCTAssertEqual(KeyboardTextLogic.newlineText(for: .default), "\n")
        let actionTypes: [UIReturnKeyType] = [
            .go, .google, .join, .next, .route, .search, .send, .yahoo, .done, .emergencyCall, .continue,
        ]
        for type in actionTypes {
            // The field reads "\n" as its action, so the key types the line separator there.
            XCTAssertEqual(KeyboardTextLogic.newlineText(for: type), "\u{2028}", "return key type \(type.rawValue)")
        }
        XCTAssertEqual(Character("\u{2028}").isNewline, true)
        XCTAssertTrue(KeyboardTextLogic.wordTerminators.contains("\u{2028}"))
        XCTAssertNotNil(UIImage(systemName: KeyboardTextLogic.newlineKeySymbol))
    }

    // MARK: Touches

    private func tap(_ point: CGPoint, on keyboardView: KeyboardView) {
        let touch = FakeTouch(at: point)
        keyboardView.touchesBegan([touch], with: nil)
        keyboardView.touchesEnded([touch], with: nil)
    }

    private func tap(_ key: KeyView, on keyboardView: KeyboardView) {
        tap(CGPoint(x: key.hitFrame.midX, y: key.hitFrame.midY), on: keyboardView)
    }

    private func makeKeyboard(width: CGFloat, before: String = "") -> (KeyboardView, FakeDocument, KeyboardTextController) {
        let height = KeyboardView.preferredHeight(forWidth: width, compactHeight: false, device: .phone, landscape: false)
        let keyboardView = KeyboardView(frame: CGRect(x: 0, y: 0, width: width, height: height))
        let document = FakeDocument(before: before)
        let controller = KeyboardTextController(
            keyboardView: keyboardView, document: document, spellChecker: FakeSpellChecker(),
            pinyinEngine: { PinyinEngine(dictionaryText: testDictionary) })
        controller.documentDidChange()
        keyboardView.layoutIfNeeded()
        return (keyboardView, document, controller)
    }

    private func key(_ kind: KeyKind, of keyboardView: KeyboardView, _ context: String) throws -> KeyView {
        let keys = keyboardView.subviews.compactMap { $0 as? KeyView }.filter { $0.key.kind == kind && !$0.isHidden }
        XCTAssertEqual(keys.count, 1, "\(kind) keys, \(context)")
        return try XCTUnwrap(keys.first, context)
    }

    func testATouchInTheLowerRightCornerPressesTheReturnKey() throws {
        // An iPad chooses its layout by the orientation of the screen, so the widths of the open
        // phone give the wide and the split layout only on a phone.
        try XCTSkipUnless(KeyboardDevice.current == .phone)
        for width in [CGFloat(669), 951] {
            let (keyboardView, document, controller) = makeKeyboard(width: width)
            var hidden = 0
            controller.onDismiss = { hidden += 1 }
            let returnKey = try key(.returnKey, of: keyboardView, "\(width)")
            let dismiss = try key(.dismiss, of: keyboardView, "\(width)")
            // The return key is the last cell of the bottom row, right of the key that hides
            // the keyboard.
            XCTAssertEqual(returnKey.hitFrame.minX, dismiss.hitFrame.maxX, accuracy: 0.5, "\(width)")
            XCTAssertGreaterThan(returnKey.hitFrame.midY, try key(.newline, of: keyboardView, "\(width)").hitFrame.maxY, "\(width)")
            tap(returnKey, on: keyboardView)
            XCTAssertEqual(document.text, "\n", "\(width)")
            tap(CGPoint(x: keyboardView.bounds.maxX - 1, y: keyboardView.bounds.maxY - 1), on: keyboardView)
            XCTAssertEqual(document.text, "\n\n", "\(width)")
            XCTAssertEqual(hidden, 0, "\(width)")
            tap(dismiss, on: keyboardView)
            XCTAssertEqual(hidden, 1, "\(width)")
        }
    }

    func testTheNewlineKeyTypesALineBreakInAFieldWithoutAnAction() throws {
        try XCTSkipUnless(KeyboardDevice.current == .phone)
        for width in [CGFloat(669), 951] {
            // The view holds its controller weakly, so the test keeps the controller.
            let (keyboardView, document, controller) = makeKeyboard(width: width)
            XCTAssertTrue(keyboardView.delegate === controller)
            XCTAssertEqual(keyboardView.returnKeyType, .default)
            for layer in Self.layers {
                keyboardView.show(layer: layer)
                keyboardView.layoutIfNeeded()
                let newline = try key(.newline, of: keyboardView, "\(width) \(layer)")
                XCTAssertEqual(newline.shownSymbolName, KeyboardTextLogic.newlineKeySymbol, "\(width) \(layer)")
                let before = document.text
                tap(newline, on: keyboardView)
                XCTAssertEqual(document.text, before + "\n", "\(width) \(layer)")
            }
        }
    }

    func testTheNewlineKeyTypesTheLineSeparatorInAFieldWithAnAction() throws {
        try XCTSkipUnless(KeyboardDevice.current == .phone)
        let (keyboardView, document, controller) = makeKeyboard(width: 669)
        XCTAssertTrue(keyboardView.delegate === controller)
        keyboardView.returnKeyType = .send
        let newline = try key(.newline, of: keyboardView, "send")
        // The newline key keeps its symbol while the return key shows the field's action.
        XCTAssertEqual(newline.shownSymbolName, KeyboardTextLogic.newlineKeySymbol)
        XCTAssertEqual(try key(.returnKey, of: keyboardView, "send").shownSymbolName, "paperplane")
        tap(newline, on: keyboardView)
        XCTAssertEqual(document.text, "\u{2028}")
        // The return key still gives the field its "\n", which the field reads as its action.
        tap(try key(.returnKey, of: keyboardView, "send"), on: keyboardView)
        XCTAssertEqual(document.text, "\u{2028}\n")
    }

    func testTheNewlineKeyTypesThePinyinLettersAsTheyAre() throws {
        try XCTSkipUnless(KeyboardDevice.current == .phone)
        for type in [UIReturnKeyType.default, .send] {
            let (keyboardView, document, controller) = makeKeyboard(width: 669)
            keyboardView.returnKeyType = type
            controller.keyboardView(keyboardView, edit: .toggleLanguage)
            controller.keyboardView(keyboardView, insert: "w")
            controller.keyboardView(keyboardView, insert: "o")
            XCTAssertEqual(controller.pinyinBuffer, "wo")
            // As the return key does, the newline key puts the waiting letters in the text and
            // adds no line break.
            tap(try key(.newline, of: keyboardView, "\(type.rawValue)"), on: keyboardView)
            XCTAssertEqual(document.text, "wo", "\(type.rawValue)")
            XCTAssertEqual(controller.pinyinBuffer, "", "\(type.rawValue)")
        }
    }
}
