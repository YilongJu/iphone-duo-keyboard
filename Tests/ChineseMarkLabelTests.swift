import UIKit
import XCTest

@testable import DuoKeyboard

/// The labels of the punctuation keys in Chinese mode: each key shows the Chinese mark that it
/// types, and the quote keys show the quote that comes next. In English mode the keys show
/// their ASCII marks.
@MainActor
final class ChineseMarkLabelTests: XCTestCase {
    private var keyboardView: KeyboardView!
    private var document: FakeDocument!
    private var controller: KeyboardTextController!

    private func makeKeyboard(width: CGFloat = 466, chinese: Bool = true) {
        let height = KeyboardView.preferredHeight(forWidth: width, compactHeight: false, device: .phone, landscape: false)
        keyboardView = KeyboardView(frame: CGRect(x: 0, y: 0, width: width, height: height))
        keyboardView.setNeedsLayout()
        keyboardView.layoutIfNeeded()
        document = FakeDocument(before: "")
        controller = KeyboardTextController(
            keyboardView: keyboardView, document: document, spellChecker: FakeSpellChecker(),
            pinyinEngine: { PinyinEngine(dictionaryText: testDictionary) })
        if chinese {
            controller.keyboardView(keyboardView, edit: .toggleLanguage)
        }
    }

    private func type(_ text: String) {
        for character in text {
            controller.keyboardView(keyboardView, insert: String(character))
        }
    }

    private func shown(_ kind: KeyKind) throws -> (primary: String?, secondary: String?, slideCharacter: String?) {
        let keyView = try XCTUnwrap(
            keyboardView.subviews.compactMap { $0 as? KeyView }.first { $0.key.kind == kind }, "\(kind)")
        return keyView.shownTexts
    }

    private func assertShown(
        _ kind: KeyKind, primary: String?, secondary: String? = nil, slide: String? = nil,
        file: StaticString = #filePath, line: UInt = #line
    ) throws {
        let texts = try shown(kind)
        XCTAssertEqual(texts.primary, primary, "\(kind)", file: file, line: line)
        XCTAssertEqual(texts.secondary, secondary, "\(kind)", file: file, line: line)
        XCTAssertEqual(texts.slideCharacter, slide, "\(kind)", file: file, line: line)
    }

    // MARK: The compact letters

    func testTheCompactLetterKeysShowTheChineseMarks() throws {
        makeKeyboard()
        try assertShown(.dual(",", "!"), primary: "\u{FF0C}", secondary: "\u{FF01}")
        try assertShown(.dual(".", "?"), primary: "\u{3002}", secondary: "\u{FF1F}")
        try assertShown(.slide("n", ";"), primary: "n", slide: "\u{FF1B}")
        try assertShown(.slide("m", ":"), primary: "m", slide: "\u{FF1A}")
        try assertShown(.slide("h", "("), primary: "h", slide: "\u{FF08}")
        try assertShown(.slide("j", ")"), primary: "j", slide: "\u{FF09}")
        try assertShown(.slide("k", "'"), primary: "k", slide: "\u{2018}")
        try assertShown(.slide("l", "\""), primary: "l", slide: "\u{201C}")
        try assertShown(.dual("1", "!"), primary: "1", secondary: "\u{FF01}")
        try assertShown(.dual("9", "("), primary: "9", secondary: "\u{FF08}")
        try assertShown(.dual("0", ")"), primary: "0", secondary: "\u{FF09}")
    }

    func testMarksThatStayASCIIInChineseModeKeepTheirLabels() throws {
        makeKeyboard()
        try assertShown(.slide("a", "@"), primary: "a", slide: "@")
        try assertShown(.slide("x", "-"), primary: "x", slide: "-")
        try assertShown(.slide("b", "/"), primary: "b", slide: "/")
        try assertShown(.dual("2", "@"), primary: "2", secondary: "@")
    }

    func testEnglishModeShowsTheASCIIMarks() throws {
        makeKeyboard(chinese: false)
        try assertShown(.dual(",", "!"), primary: ",", secondary: "!")
        try assertShown(.slide("l", "\""), primary: "l", slide: "\"")
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        try assertShown(.dual(",", "!"), primary: "\u{FF0C}", secondary: "\u{FF01}")
        controller.keyboardView(keyboardView, edit: .toggleLanguage)
        try assertShown(.dual(",", "!"), primary: ",", secondary: "!")
        try assertShown(.slide("l", "\""), primary: "l", slide: "\"")
    }

    func testTheQuoteKeysShowTheQuoteThatComesNext() throws {
        makeKeyboard()
        type("\"")
        XCTAssertEqual(document.text, "\u{201C}")
        try assertShown(.slide("l", "\""), primary: "l", slide: "\u{201D}")
        type("\"")
        try assertShown(.slide("l", "\""), primary: "l", slide: "\u{201C}")
        type("'")
        XCTAssertEqual(document.text, "\u{201C}\u{201D}\u{2018}")
        try assertShown(.slide("k", "'"), primary: "k", slide: "\u{2019}")
    }

    func testADeleteThatBringsTheClosingQuoteBackShowsItOnTheKey() throws {
        // The first space types the candidate and the second one a space. The closing quote then
        // takes the place of that space, and a delete brings the space back.
        makeKeyboard()
        type("\"wo  \"")
        XCTAssertEqual(document.text, "\u{201C}\u{6211}\u{201D}")
        try assertShown(.slide("l", "\""), primary: "l", slide: "\u{201C}")
        controller.keyboardViewDeleteBackward(keyboardView)
        XCTAssertEqual(document.text, "\u{201C}\u{6211} ")
        try assertShown(.slide("l", "\""), primary: "l", slide: "\u{201D}")
        type("\"")
        XCTAssertEqual(document.text, "\u{201C}\u{6211} \u{201D}")
    }

    func testTheApostropheKeyShowsTheApostropheWhilePinyinLettersWait() throws {
        // Between Pinyin letters the key splits two syllables, as in "xi'an".
        makeKeyboard()
        type("xi")
        try assertShown(.slide("k", "'"), primary: "k", slide: "'")
        type(" ")
        try assertShown(.slide("k", "'"), primary: "k", slide: "\u{2018}")
    }

    // MARK: The symbol layers

    func testTheCompactSymbolLayersShowTheChineseMarks() throws {
        makeKeyboard()
        keyboardView.show(layer: .symbols)
        let marks: [(String, String)] = [
            (":", "\u{FF1A}"), (";", "\u{FF1B}"), ("(", "\u{FF08}"), (")", "\u{FF09}"), ("\"", "\u{201C}"),
            (".", "\u{3002}"), (",", "\u{FF0C}"), ("?", "\u{FF1F}"), ("!", "\u{FF01}"), ("'", "\u{2018}"),
        ]
        for (ascii, chinese) in marks {
            try assertShown(.character(ascii), primary: chinese)
        }
        for ascii in ["-", "/", "$", "&", "@", "[", "]", "{", "}", "#", "%", "^", "*", "+", "=", "`", "_"] {
            try assertShown(.character(ascii), primary: ascii)
        }
        keyboardView.show(layer: .more)
        try assertShown(.character("\\"), primary: "\u{3001}")
        try assertShown(.character("<"), primary: "\u{300A}")
        try assertShown(.character(">"), primary: "\u{300B}")
        try assertShown(.character("|"), primary: "|")
        try assertShown(.character("~"), primary: "~")
    }

    // MARK: The wide layout

    func testTheWideLetterKeysShowTheChineseMarks() throws {
        try XCTSkipUnless(KeyboardDevice.current == .phone, "An iPad chooses its layout by the orientation of the screen")
        makeKeyboard(width: 669)
        XCTAssertEqual(keyboardView.style, .wide)
        try assertShown(.dual(";", ":"), primary: "\u{FF1B}", secondary: "\u{FF1A}")
        try assertShown(.dual("'", "\""), primary: "\u{2018}", secondary: "\u{201C}")
        try assertShown(.dual(",", "<"), primary: "\u{FF0C}", secondary: "\u{300A}")
        try assertShown(.dual(".", ">"), primary: "\u{3002}", secondary: "\u{300B}")
        try assertShown(.dual("/", "?"), primary: "/", secondary: "\u{FF1F}")
        try assertShown(.dual("\\", "|"), primary: "\u{3001}", secondary: "|")
        try assertShown(.dual("[", "{"), primary: "[", secondary: "{")
    }

    // MARK: Typing

    func testEachChineseLabelIsTheTextTheKeyTypes() throws {
        // The label and the text come from one table, so a key never types a mark it does not show.
        makeKeyboard()
        keyboardView.show(layer: .symbols)
        for ascii in [":", ";", "(", ")", ".", ",", "?", "!"] {
            let label = try XCTUnwrap(try shown(.character(ascii)).primary)
            let before = document.text
            type(ascii)
            XCTAssertEqual(document.text, before + label, ascii)
        }
    }
}

/// The full-width Chinese marks on the keys. A font draws "，" and "。" in the lower left of their
/// square, so the key moves the label until the drawn mark sits in the middle of the key. The
/// tests draw a label as UIKit draws it and measure the middle of its dark pixels.
@MainActor
final class ChineseMarkCenteringTests: XCTestCase {
    private var keyboardView: KeyboardView!
    private var controller: KeyboardTextController!

    /// How far, in points, the middle of a drawn mark may lie from the middle of its key.
    private static let tolerance: CGFloat = 1.5

    private func makeKeyboard(chinese: Bool) {
        let height = KeyboardView.preferredHeight(forWidth: 466, compactHeight: false, device: .phone, landscape: false)
        keyboardView = KeyboardView(frame: CGRect(x: 0, y: 0, width: 466, height: height))
        keyboardView.overrideUserInterfaceStyle = .light
        keyboardView.layoutIfNeeded()
        controller = KeyboardTextController(
            keyboardView: keyboardView, document: FakeDocument(before: ""), spellChecker: FakeSpellChecker(),
            pinyinEngine: { PinyinEngine(dictionaryText: testDictionary) })
        if chinese {
            controller.keyboardView(keyboardView, edit: .toggleLanguage)
        }
    }

    private func keyView(_ kind: KeyKind) throws -> KeyView {
        let keyView = try XCTUnwrap(
            keyboardView.subviews.compactMap { $0 as? KeyView }.first { $0.key.kind == kind }, "\(kind)")
        keyView.layoutIfNeeded()
        return keyView
    }

    private func label(_ text: String, of keyView: KeyView) throws -> UILabel {
        try XCTUnwrap(keyView.subviews.compactMap { $0 as? UILabel }.first { $0.text == text }, text)
    }

    /// The middle of the dark pixels that `label` draws, in the coordinates of its key.
    private func inkMiddle(of label: UILabel, in keyView: KeyView) throws -> CGPoint {
        let scale: CGFloat = 2
        let size = keyView.bounds.size
        let width = Int(size.width * scale), height = Int(size.height * scale)
        var pixels = [UInt8](repeating: 255, count: width * height * 4)
        try pixels.withUnsafeMutableBytes { buffer in
            let context = try XCTUnwrap(CGContext(
                data: buffer.baseAddress, width: width, height: height, bitsPerComponent: 8, bytesPerRow: width * 4,
                space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
            // UIKit draws with the origin at the top left.
            context.translateBy(x: 0, y: CGFloat(height))
            context.scaleBy(x: scale, y: -scale)
            UIGraphicsPushContext(context)
            label.traitCollection.performAsCurrent {
                context.translateBy(x: label.frame.minX, y: label.frame.minY)
                label.drawText(in: label.bounds)
            }
            UIGraphicsPopContext()
        }
        var minX = width, maxX = -1, minY = height, maxY = -1
        for y in 0..<height {
            for x in 0..<width where pixels[(y * width + x) * 4] < 128 {
                minX = min(minX, x)
                maxX = max(maxX, x)
                minY = min(minY, y)
                maxY = max(maxY, y)
            }
        }
        guard maxX >= 0 else { throw NoInk(text: label.text ?? "") }
        return CGPoint(x: CGFloat(minX + maxX + 1) / 2 / scale, y: CGFloat(minY + maxY + 1) / 2 / scale)
    }

    private struct NoInk: Error {
        let text: String
    }

    func testTheFullWidthMarksOfTheSymbolLayersLookCenteredOnTheirKeys() throws {
        makeKeyboard(chinese: true)
        let marks: [(KeyboardLayer, String, String)] = [
            (.symbols, ",", "\u{FF0C}"), (.symbols, ".", "\u{3002}"), (.symbols, "?", "\u{FF1F}"),
            (.symbols, "!", "\u{FF01}"), (.symbols, ":", "\u{FF1A}"), (.symbols, ";", "\u{FF1B}"),
            (.symbols, "(", "\u{FF08}"), (.symbols, ")", "\u{FF09}"), (.more, "\\", "\u{3001}"),
            (.more, "<", "\u{300A}"), (.more, ">", "\u{300B}"),
        ]
        for (layer, ascii, mark) in marks {
            keyboardView.show(layer: layer)
            keyboardView.layoutIfNeeded()
            let key = try keyView(.character(ascii))
            let middle = try inkMiddle(of: try label(mark, of: key), in: key)
            XCTAssertEqual(middle.x, key.bounds.midX, accuracy: Self.tolerance, mark)
            XCTAssertEqual(middle.y, key.bounds.midY, accuracy: Self.tolerance, mark)
        }
    }

    func testTheMarksOfTheLetterKeysLookCenteredAcrossTheirKeys() throws {
        makeKeyboard(chinese: true)
        for (kind, mark) in [
            (KeyKind.dual(",", "!"), "\u{FF0C}"), (.dual(",", "!"), "\u{FF01}"), (.dual(".", "?"), "\u{3002}"),
            (.dual(".", "?"), "\u{FF1F}"), (.slide("n", ";"), "\u{FF1B}"), (.slide("m", ":"), "\u{FF1A}"),
        ] {
            let key = try keyView(kind)
            let middle = try inkMiddle(of: try label(mark, of: key), in: key)
            XCTAssertEqual(middle.x, key.bounds.midX, accuracy: Self.tolerance, mark)
        }
    }

    func testEnglishMarksKeepTheirPlace() throws {
        makeKeyboard(chinese: false)
        keyboardView.show(layer: .symbols)
        keyboardView.layoutIfNeeded()
        for ascii in [",", ".", "?", "!", ":", ";", "(", ")"] {
            let key = try keyView(.character(ascii))
            XCTAssertEqual(try label(ascii, of: key).frame, key.bounds.insetBy(dx: 2, dy: 2), ascii)
        }
    }
}
