import UIKit
import XCTest

@testable import DuoKeyboard

/// The key form `{"c": "a", "a": "@"}` of `keyboard-layout.json`: a letter with a slide character.
@MainActor
final class SlideKeyFormTests: XCTestCase {
    private func key(_ json: String) throws -> Key {
        try JSONDecoder().decode(Key.self, from: Data(json.utf8))
    }

    func testALetterWithASlideCharacterDecodes() throws {
        let plain = try key(#"{"c": "a", "a": "@"}"#)
        XCTAssertEqual(plain.kind, .slide("a", "@"))
        XCTAssertEqual(plain.weight, 1)
        let wide = try key(#"{"c": "l", "a": "\"", "w": 1.25}"#)
        XCTAssertEqual(wide.kind, .slide("l", "\""))
        XCTAssertEqual(wide.weight, 1.25)
    }

    func testTheOtherKeyFormsStillDecode() throws {
        XCTAssertEqual(try key(#""a""#).kind, .character("a"))
        XCTAssertEqual(try key(#"["1", "!"]"#).kind, .dual("1", "!"))
        XCTAssertEqual(try key(#"{"c": "_", "w": 0.85}"#).kind, .character("_"))
        XCTAssertEqual(try key(#"{"c": "1", "s": "!", "w": 0.9}"#).kind, .dual("1", "!"))
        XCTAssertEqual(try key(#"{"f": "shift", "w": 2.25}"#).kind, .shift)
    }

    func testAKeyFormThatTheKeyboardDoesNotKnowStopsDecoding() {
        for json in [
            #"{"a": "@"}"#, #"{"c": "a", "s": "A", "a": "@"}"#, #"{"f": "shift", "a": "@"}"#,
            #"{"c": "a", "f": "shift", "a": "@"}"#, #"{"f": "slide"}"#, #"{"w": 1}"#, #"["a"]"#, "1",
        ] {
            XCTAssertThrowsError(try key(json), json)
        }
    }

    func testALetterWithASlideCharacterIsATextKey() {
        let kind = KeyKind.slide("a", "@")
        XCTAssertTrue(kind.isTextKey)
        XCTAssertFalse(kind.isFunctionKey)
        XCTAssertFalse(kind.repeats)
        XCTAssertEqual(kind.alternateCharacter, "@")
        XCTAssertEqual(KeyKind.dual("1", "!").alternateCharacter, "!")
        XCTAssertNil(KeyKind.character("a").alternateCharacter)
        XCTAssertNil(KeyKind.space.alternateCharacter)
    }

    /// The slide characters of the compact letters, as the layout file holds them now. They are
    /// those of the iPad keyboard of iOS.
    func testTheCompactLettersHoldTheirSlideCharacters() {
        let rows = KeyboardLayout.make(style: .compact, layer: .letters, showsGlobe: true).rows
        XCTAssertEqual(rows[2].map(\.kind), "qwertyuiop".map { KeyKind.character(String($0)) })
        XCTAssertEqual(
            rows[3].map(\.kind),
            zip("asdfghjkl", "@#$&*()'\"").map { KeyKind.slide(String($0), String($1)) })
        XCTAssertEqual(
            rows[4].map(\.kind),
            [KeyKind.shift] + zip("zxcvbnm", "%-+=/;:").map { KeyKind.slide(String($0), String($1)) } + [KeyKind.backspace])
    }

    func testOnlyTheCompactLettersHaveSlideCharacters() {
        for style in [LayoutStyle.compact, .wide, .split] {
            for layer in [KeyboardLayer.letters, .symbols, .more] {
                let keys = KeyboardLayout.make(style: style, layer: layer, showsGlobe: true).rows.joined()
                let slideKeys = keys.filter { if case .slide = $0.kind { return true } else { return false } }
                XCTAssertEqual(slideKeys.count, style == .compact && layer == .letters ? 16 : 0)
            }
        }
    }
}

/// `SlideGesture.step`: what a finger move does on a letter key with a slide character.
/// A letter row of the compact layout is 46 points high, so a slide selects the slide
/// character after more than 18.4 points and lets it go under 9.2 points.
final class SlideGestureTests: XCTestCase {
    private func step(selected: Bool = false, dx: CGFloat = 0, dy: CGFloat) -> SlideGesture.Step {
        SlideGesture.step(selected: selected, dx: dx, dy: dy, rowHeight: 46)
    }

    func testAVerticalMoveOverTheSelectDistanceSelectsTheSlideCharacter() {
        XCTAssertEqual(step(dy: -19), .slideCharacter)
        XCTAssertEqual(step(dy: 19), .slideCharacter)
        XCTAssertEqual(step(dx: 12, dy: -30), .slideCharacter)
    }

    func testAShortVerticalMoveKeepsTheLetterAndTheKey() {
        XCTAssertEqual(step(dy: -18), .letter)
        XCTAssertEqual(step(dy: 18), .letter)
        XCTAssertEqual(step(dy: -1), .letter)
        XCTAssertEqual(step(dx: 5, dy: 10), .letter)
    }

    func testAMoveThatIsNotVerticalCanGoToAnotherKey() {
        XCTAssertEqual(step(dx: 20, dy: 0), .letterOrOtherKey)
        XCTAssertEqual(step(dx: -30, dy: 25), .letterOrOtherKey)
        XCTAssertEqual(step(dx: 19, dy: 19), .letterOrOtherKey)
        XCTAssertEqual(step(dy: 0), .letterOrOtherKey)
    }

    func testASelectedSlideCharacterStaysUntilTheFingerIsBackNearTheStartHeight() {
        XCTAssertEqual(step(selected: true, dy: -10), .slideCharacter)
        XCTAssertEqual(step(selected: true, dy: 10), .slideCharacter)
        // A move to the side does not end the selection.
        XCTAssertEqual(step(selected: true, dx: 40, dy: -10), .slideCharacter)
        XCTAssertEqual(step(selected: true, dy: -9), .letter)
        XCTAssertEqual(step(selected: true, dx: 40, dy: -9), .letterOrOtherKey)
    }

    func testTheSelectDistanceFollowsTheRowHeight() {
        XCTAssertEqual(SlideGesture.selectDistanceInRowHeights, 0.4)
        XCTAssertEqual(SlideGesture.step(selected: false, dx: 0, dy: 14, rowHeight: 34), .slideCharacter)
        XCTAssertEqual(SlideGesture.step(selected: false, dx: 0, dy: 14, rowHeight: 46), .letter)
    }
}

/// What a letter key with a slide character shows.
@MainActor
final class SlideKeyDrawingTests: XCTestCase {
    private func makeView(width: CGFloat) -> KeyboardView {
        let height = KeyboardView.preferredHeight(
            forWidth: width, compactHeight: false, device: .phone, landscape: false)
        let view = KeyboardView(frame: CGRect(x: 0, y: 0, width: width, height: height))
        view.setNeedsLayout()
        view.layoutIfNeeded()
        return view
    }

    private func keyViews(of view: KeyboardView) -> [KeyView] {
        view.subviews.compactMap { $0 as? KeyView }
    }

    private func keyView(_ kind: KeyKind, of view: KeyboardView) throws -> KeyView {
        try XCTUnwrap(keyViews(of: view).first { $0.key.kind == kind })
    }

    func testALetterKeyShowsItsSlideCharacterAndShiftChangesTheLetterOnly() throws {
        let view = makeView(width: 466)
        XCTAssertEqual(view.style, .compact)
        var shown = try keyView(.slide("a", "@"), of: view).shownTexts
        XCTAssertEqual(shown.primary, "a")
        XCTAssertEqual(shown.slideCharacter, "@")
        XCTAssertNil(shown.secondary)

        view.shiftState = .on
        shown = try keyView(.slide("a", "@"), of: view).shownTexts
        XCTAssertEqual(shown.primary, "A")
        XCTAssertEqual(shown.slideCharacter, "@")
    }

    func testTheSlideCharacterIsSmallAndAboveTheLetter() throws {
        let view = makeView(width: 466)
        let key = try keyView(.slide("m", ":"), of: view)
        key.layoutIfNeeded()
        let labels = key.subviews.compactMap { $0 as? UILabel }
        let slide = try XCTUnwrap(labels.first { $0.text == ":" })
        let letter = try XCTUnwrap(labels.first { $0.text == "m" })
        XCTAssertEqual(slide.font.pointSize, 11)
        XCTAssertEqual(slide.textColor, UIColor.secondaryLabel)
        XCTAssertEqual(slide.textAlignment, .center)
        XCTAssertEqual(slide.frame.midX, key.bounds.midX, accuracy: 0.01)
        XCTAssertLessThan(slide.frame.maxY, key.bounds.midY)
        // The letter sits a little under the middle of the key.
        XCTAssertGreaterThan(letter.frame.midY, key.bounds.midY)
        XCTAssertLessThan(letter.frame.midY, key.bounds.midY + 6)
    }

    func testTheOtherKeysShowNoSlideCharacter() throws {
        let compact = makeView(width: 466)
        let digit = try keyView(.dual("1", "!"), of: compact).shownTexts
        XCTAssertEqual(digit.primary, "1")
        XCTAssertEqual(digit.secondary, "!")
        XCTAssertNil(digit.slideCharacter)
        XCTAssertNil(try keyView(.character("q"), of: compact).shownTexts.slideCharacter)
        let comma = try keyView(.dual(",", "!"), of: compact).shownTexts
        XCTAssertEqual(comma.primary, ",")
        XCTAssertEqual(comma.secondary, "!")

        try XCTSkipUnless(KeyboardDevice.current == .phone, "An iPad chooses its layout by the orientation of the screen")
        for width: CGFloat in [669, 951] {
            let view = makeView(width: width)
            XCTAssertNotEqual(view.style, .compact)
            XCTAssertTrue(keyViews(of: view).allSatisfy { $0.shownTexts.slideCharacter == nil })
            // A letter of the wide layout keeps the whole key, as a key without a slide character does.
            let letter = try keyView(.character("a"), of: view)
            letter.layoutIfNeeded()
            let label = try XCTUnwrap(letter.subviews.compactMap { $0 as? UILabel }.first { $0.text == "a" })
            XCTAssertEqual(label.frame, letter.bounds.insetBy(dx: 2, dy: 2))
        }
    }
}
