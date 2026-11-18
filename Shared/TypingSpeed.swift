import UIKit

/// The typing speed of the last seconds, in words per minute. One word is 5 characters, as in
/// the usual measure of typing speed.
///
/// The meter counts the characters that go into the text, less the characters that come out
/// again. A tapped predicted word counts with all its characters, so the number shows what the
/// predictions save. The meter keeps the times and the counts of the last seconds only. It keeps
/// no text.
///
/// A run of typing starts with its first character and ends with a pause. The speed of a run is
/// its characters after the first one, over the time since the first one. A run longer than the
/// window counts only the characters and the time of the window.
struct TypingSpeedMeter {
    /// The speed covers at most this many seconds before the last character.
    static let windowSeconds = 10.0
    /// A time without a character that ends a run.
    static let pauseSeconds = 3.0
    /// A run gives a speed once it is this long, so two fast characters do not show 300.
    static let leastSeconds = 2.0
    static let charactersPerWord = 5.0

    /// The characters of the run, each with its time. The first entry is the start of the run
    /// and holds no character.
    private var events: [(time: TimeInterval, characters: Int)] = []
    /// The speed of the current run, or of the last run that was long enough. It is nil before
    /// the first such run.
    private(set) var wordsPerMinute: Int?

    /// Counts `characters` that went into the text at `time`. A negative count is a deletion.
    mutating func record(characters: Int, at time: TimeInterval) {
        if let last = events.last, time - last.time > Self.pauseSeconds {
            events = []
        }
        if events.isEmpty {
            // The first character of a run starts the clock, and the speed counts what follows.
            events = [(time, 0)]
            return
        }
        events.append((time, characters))
        let start = max(events[0].time, time - Self.windowSeconds)
        let seconds = time - start
        guard seconds >= Self.leastSeconds else { return }
        let count = events.reduce(0) { $0 + ($1.time > start ? $1.characters : 0) }
        events.removeAll { $0.time < start }
        if events.first?.time != start {
            // The window left the start of the run behind, so the window's edge is the new start.
            events.insert((start, 0), at: 0)
        }
        wordsPerMinute = Int((Double(max(count, 0)) / Self.charactersPerWord * 60 / seconds).rounded())
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
