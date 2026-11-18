import UIKit

/// One entry of the prediction strip: an emoji or a predicted word. The entry is a control, so a
/// lift of the finger inside it selects it, and a drag hands the touch to the strip's scroll view.
final class PredictionStripEntry: UIControl {
    let item: PredictionStrip.Item
    /// The text of the entry.
    let label = UILabel()
    /// The part at the top of the entry that takes touches and holds no text, in points. The
    /// strip reaches up to the keyboard's edge, and the text stays at the height of the keys.
    var labelTopInset: CGFloat = 0 {
        didSet { if oldValue != labelTopInset { setNeedsLayout() } }
    }

    /// The font sizes of a predicted word and of an emoji, in points.
    static let wordFontSize: CGFloat = 17
    static let emojiFontSize: CGFloat = 20
    /// The room at each side of the text, and the least width of an entry, in points. An emoji
    /// gets less room at its sides, because the emoji of one word belong together.
    private static let wordPadding: CGFloat = 10
    private static let emojiPadding: CGFloat = 6
    private static let leastWidth: CGFloat = 34

    init(item: PredictionStrip.Item) {
        self.item = item
        super.init(frame: .zero)
        label.text = item.text
        label.textAlignment = .center
        label.textColor = KeyColors.text
        label.isUserInteractionEnabled = false
        switch item {
        case .emoji: label.font = .systemFont(ofSize: Self.emojiFontSize)
        case .word: label.font = .systemFont(ofSize: Self.wordFontSize)
        }
        addSubview(label)
        isAccessibilityElement = true
        accessibilityLabel = item.text
        accessibilityTraits = .button
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("PredictionStripEntry is built in code only")
    }

    /// The width that the entry takes in the strip.
    var preferredWidth: CGFloat {
        let padding: CGFloat
        switch item {
        case .emoji: padding = Self.emojiPadding
        case .word: padding = Self.wordPadding
        }
        return max((label.intrinsicContentSize.width + 2 * padding).rounded(.up), Self.leastWidth)
    }

    /// A pressed entry fades, as a pressed candidate of the candidate row does.
    override var isHighlighted: Bool {
        didSet { label.alpha = isHighlighted ? 0.4 : 1 }
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        label.frame = CGRect(x: 0, y: labelTopInset, width: bounds.width, height: max(bounds.height - labelTopInset, 0))
    }
}

/// The prediction strip: the part of the top row between Select All and Cut. It shows the emoji
/// of the English word before the cursor first, and then the predicted words. The entries scroll
/// sideways, as the Chinese candidates do, and a tap on an entry selects it.
///
/// The strip takes the full cell of its place in the row, so a touch in that cell never reaches
/// a key. The strip has the color of the keyboard's own background, so an empty strip looks like
/// a free part of the keyboard.
final class PredictionStrip: UIView {
    /// One entry of the strip.
    enum Item: Equatable {
        /// An emoji of the word before the cursor. A tap puts the emoji in place of that word.
        case emoji(String)
        /// A predicted word. A tap puts the word in place of the typed letters.
        case word(String)

        var text: String {
            switch self {
            case .emoji(let text), .word(let text): return text
            }
        }
    }

    /// Called when a finger comes down on an entry.
    var onPress: (() -> Void)?
    /// Called with the entry that the user tapped.
    var onSelect: ((Item) -> Void)?

    /// The entries from left to right.
    private(set) var items: [Item] = []
    /// The empty room at the left and the right end of the strip, in points: the gap that a
    /// drawn key has at its sides.
    var sideInset: CGFloat = 2 {
        didSet { if oldValue != sideInset { setNeedsLayout() } }
    }
    /// The part at the top of the strip that lies above the top row of keys, in points. An entry
    /// takes touches there, and its text stays inside the row.
    var topInset: CGFloat = 0 {
        didSet { if oldValue != topInset { setNeedsLayout() } }
    }

    private let scrollView = CandidateScrollView()
    /// The controls of `items`, in the same order.
    private(set) var entries: [PredictionStripEntry] = []
    /// The thin lines between two neighbor entries.
    private var separators: [UIView] = []

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = KeyColors.surface
        scrollView.showsHorizontalScrollIndicator = false
        scrollView.showsVerticalScrollIndicator = false
        scrollView.delaysContentTouches = false
        scrollView.canCancelContentTouches = true
        scrollView.alwaysBounceHorizontal = true
        addSubview(scrollView)
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("PredictionStrip is built in code only")
    }

    /// Shows new entries. The same entries as before stay as they are, so the strip does not
    /// scroll back to its start at a key press that changes nothing.
    func show(_ newItems: [Item]) {
        guard newItems != items else { return }
        items = newItems
        for entry in entries {
            // A finger can rest on an entry that leaves. That entry must not select anything.
            entry.removeTarget(nil, action: nil, for: .allEvents)
            entry.removeFromSuperview()
        }
        for separator in separators {
            separator.removeFromSuperview()
        }
        entries = newItems.map { item in
            let entry = PredictionStripEntry(item: item)
            entry.addTarget(self, action: #selector(entryPressed(_:)), for: .touchDown)
            entry.addTarget(self, action: #selector(entryTapped(_:)), for: .touchUpInside)
            scrollView.addSubview(entry)
            return entry
        }
        separators = newItems.dropFirst().map { _ in
            let separator = UIView()
            separator.backgroundColor = .separator
            separator.isUserInteractionEnabled = false
            scrollView.addSubview(separator)
            return separator
        }
        scrollView.contentOffset = .zero
        // The entries get their places at once, because a touch can arrive before the next
        // layout pass.
        layoutEntries()
    }

    @objc private func entryPressed(_ sender: PredictionStripEntry) {
        onPress?()
    }

    @objc private func entryTapped(_ sender: PredictionStripEntry) {
        // `onPress` can change the entries under the finger: it types the letter of a finger
        // that still rests on a key. The entry of the touch is then gone, and the tap selects
        // nothing.
        guard entries.contains(where: { $0 === sender }) else { return }
        onSelect?(sender.item)
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        layoutEntries()
    }

    private func layoutEntries() {
        scrollView.frame = bounds.insetBy(dx: min(sideInset, bounds.width / 2), dy: 0)
        let height = scrollView.bounds.height
        var x: CGFloat = 0
        for (index, entry) in entries.enumerated() {
            let width = entry.preferredWidth
            entry.frame = CGRect(x: x, y: 0, width: width, height: height)
            entry.labelTopInset = topInset
            if index > 0 {
                // A line of one pixel, half as high as the row, in the middle of the row's height.
                let lineWidth = 1 / max(traitCollection.displayScale, 1)
                let rowHeight = max(height - topInset, 0)
                separators[index - 1].frame = CGRect(
                    x: x - lineWidth / 2, y: topInset + rowHeight / 4, width: lineWidth, height: rowHeight / 2)
            }
            x += width
        }
        scrollView.contentSize = CGSize(width: x, height: height)
    }
}
