import UIKit

/// The typing speed of the last seconds, in words per minute. One word is 5 characters, as in
/// the usual measure of typing speed.
///
/// The meter counts the new characters of the text. Each action of the person is one change of
/// the text: a key press, a tap on a predicted word or on a candidate, or a tap on the
/// proofreader's fix. A change counts with the characters that went in less the characters that
/// came out. So a tapped word counts with all its characters, and a fix of a sentence counts
/// only with the characters that the fix adds. A change that takes characters out, such as a
/// delete, takes the latest counted characters out of the count. The meter keeps the times and
/// the counts of the last seconds only. It keeps no text.
///
/// A run of typing starts with its first action and ends with a pause. The speed of a run is
/// its characters after the first action, over the time since the first action. A run longer
/// than the window counts only the characters and the time of the window.
struct TypingSpeedMeter {
    /// The speed covers at most this many seconds before the last action.
    static let windowSeconds = 10.0
    /// A time without an action that ends a run.
    static let pauseSeconds = 3.0
    /// A run gives a speed once it is this long, so two fast characters do not show 300.
    static let leastSeconds = 2.0
    static let charactersPerWord = 5.0

    /// The changes of the run inside the window, each with its time and its counted characters.
    /// The first entry is the start of the run or of the window, and holds no character.
    private var events: [(time: TimeInterval, characters: Int)] = []
    /// The speed of the current run, or of the last run that was long enough. It is nil before
    /// the first such run.
    private(set) var wordsPerMinute: Int?

    /// Counts one change of the text at `time`: `characters` went in, less those that came out.
    mutating func record(characters: Int, at time: TimeInterval) {
        if let last = events.last, time - last.time > Self.pauseSeconds {
            events = []
        }
        if events.isEmpty {
            // The first action of a run starts the clock, and the speed counts what follows.
            events = [(time, 0)]
            return
        }
        let start = max(events[0].time, time - Self.windowSeconds)
        if events[0].time < start {
            // The window left the start of the run behind, so the window's edge is the new start.
            events.removeAll { $0.time <= start }
            events.insert((start, 0), at: 0)
        }
        if characters >= 0 {
            events.append((time, characters))
        } else {
            // The characters that came out are the latest ones, so the latest counts go first.
            // Text from before the window is not in the count, and its deletion changes nothing.
            var left = -characters
            for index in events.indices.reversed() where left > 0 {
                let taken = min(events[index].characters, left)
                events[index].characters -= taken
                left -= taken
            }
            events.append((time, 0))
        }
        let seconds = time - start
        guard seconds >= Self.leastSeconds else { return }
        let count = events.reduce(0) { $0 + $1.characters }
        wordsPerMinute = Int((Double(count) / Self.charactersPerWord * 60 / seconds).rounded())
    }
}

/// A document that passes every call on to another document and reports each change of the
/// text: the count of characters that went in, or a negative count for a deletion.
final class MeteredDocument: KeyboardDocument {
    private let base: KeyboardDocument
    var onChange: (Int) -> Void = { _ in }

    init(base: KeyboardDocument) {
        self.base = base
    }

    var textBeforeCursor: String { base.textBeforeCursor }
    var textAfterCursor: String { base.textAfterCursor }
    var selectedText: String? { base.selectedText }
    var autocapitalizationType: UITextAutocapitalizationType { base.autocapitalizationType }
    var canUseClipboard: Bool { base.canUseClipboard }
    var documentIdentifier: UUID { base.documentIdentifier }
    var allowsAutocorrection: Bool { base.allowsAutocorrection }

    func insertText(_ text: String) {
        base.insertText(text)
        onChange(text.count)
    }

    func deleteBackward() {
        base.deleteBackward()
        onChange(-1)
    }

    func moveCursor(byUTF16Offset offset: Int) {
        base.moveCursor(byUTF16Offset: offset)
    }

    // Marked text is no typed character yet. The text that takes its place counts when it goes in.
    func setMarkedText(_ text: String) {
        base.setMarkedText(text)
    }

    func unmarkText() {
        base.unmarkText()
    }
}

/// The typing speed in the top row, between Select All and the prediction strip: the number of
/// words per minute, and "WPM" below it. The view is no key and takes no touch.
final class TypingSpeedView: UIView {
    let valueLabel = UILabel()
    let unitLabel = UILabel()
    /// The text of the number before the first speed.
    static let emptyText = "\u{2013}"

    /// The speed in words per minute, or nil before the first speed.
    var wordsPerMinute: Int? {
        didSet {
            guard oldValue != wordsPerMinute else { return }
            valueLabel.text = wordsPerMinute.map(String.init) ?? Self.emptyText
            accessibilityValue = wordsPerMinute.map { "\($0) words per minute" } ?? "no speed yet"
        }
    }
    /// The part at the top of the view that lies above the top row of keys, in points.
    var topInset: CGFloat = 0 {
        didSet { if oldValue != topInset { setNeedsLayout() } }
    }

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = KeyColors.surface
        isUserInteractionEnabled = false
        valueLabel.text = Self.emptyText
        valueLabel.textAlignment = .center
        valueLabel.textColor = KeyColors.text
        valueLabel.font = .monospacedDigitSystemFont(ofSize: 17, weight: .semibold)
        valueLabel.adjustsFontSizeToFitWidth = true
        valueLabel.minimumScaleFactor = 0.7
        addSubview(valueLabel)
        unitLabel.text = "WPM"
        unitLabel.textAlignment = .center
        unitLabel.textColor = .secondaryLabel
        unitLabel.font = .systemFont(ofSize: 9, weight: .medium)
        addSubview(unitLabel)
        isAccessibilityElement = true
        accessibilityLabel = "Typing speed"
        accessibilityValue = "no speed yet"
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("TypingSpeedView is built in code only")
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        // The number and the unit stand in the middle of the row's height, one above the other.
        let row = CGRect(x: 0, y: topInset, width: bounds.width, height: max(bounds.height - topInset, 0))
        let valueHeight = valueLabel.font.lineHeight
        let unitHeight = unitLabel.font.lineHeight
        let top = row.midY - (valueHeight + unitHeight) / 2
        valueLabel.frame = CGRect(x: 2, y: top, width: max(row.width - 4, 0), height: valueHeight)
        unitLabel.frame = CGRect(x: 0, y: top + valueHeight, width: row.width, height: unitHeight)
    }
}
