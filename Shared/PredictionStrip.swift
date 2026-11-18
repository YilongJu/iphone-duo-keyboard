import UIKit

/// The ripple of a tap (key press feedback design C): a circle that grows from the touch point
/// and fades. The keys, the prediction strip and the candidate row draw the same ripple.
enum TapRipple {
    static let seconds = 0.46

    /// Starts a ripple of `radius` points at `point` in `layer`. The layer's owner clips it.
    static func show(in layer: CALayer, at point: CGPoint, radius: CGFloat, traits: UITraitCollection) {
        let ripple = CAShapeLayer()
        ripple.path = UIBezierPath(ovalIn: CGRect(x: -radius, y: -radius, width: 2 * radius, height: 2 * radius)).cgPath
        ripple.fillColor = KeyColors.ripple.resolvedColor(with: traits).cgColor
        ripple.position = point
        ripple.opacity = 0
        layer.addSublayer(ripple)
        CATransaction.begin()
        CATransaction.setCompletionBlock { ripple.removeFromSuperlayer() }
        let grow = CABasicAnimation(keyPath: "transform.scale")
        grow.fromValue = 0.1
        grow.toValue = 1
        let fade = CABasicAnimation(keyPath: "opacity")
        fade.fromValue = 0.9
        fade.toValue = 0
        let group = CAAnimationGroup()
        group.animations = [grow, fade]
        group.duration = seconds
        group.timingFunction = CAMediaTimingFunction(name: .easeOut)
        ripple.add(group, forKey: "ripple")
        CATransaction.commit()
    }
}

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

    /// The gap that a drawn key has above and below it, in points. The ripple of a tap stays
    /// inside the drawn height of the row.
    var rowInset: CGFloat = 0 {
        didSet { if oldValue != rowInset { setNeedsLayout() } }
    }

    private let scrollView = CandidateScrollView()
    /// Clips the ripples of the taps to the drawn row of the strip.
    private let rippleClip = UIView()
    /// Count of ripples in the strip now. The unit tests read this value.
    var rippleCount: Int { rippleClip.layer.sublayers?.count ?? 0 }
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
        rippleClip.isUserInteractionEnabled = false
        rippleClip.clipsToBounds = true
        addSubview(rippleClip)
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
            entry.addTarget(self, action: #selector(entryPressed(_:event:)), for: .touchDown)
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

    @objc private func entryPressed(_ sender: PredictionStripEntry, event: UIEvent?) {
        showRipple(for: sender, event: event)
        onPress?()
    }

    /// Starts a ripple at the finger's place on `entry`. The circle reaches every corner of the
    /// entry, and the drawn row of the strip clips it. With Reduce Motion on, the entry only fades.
    private func showRipple(for entry: PredictionStripEntry, event: UIEvent?) {
        guard !UIAccessibility.isReduceMotionEnabled else { return }
        // An action that the code sends has no touch. Its ripple starts in the middle of the text.
        let touch = event?.touches(for: entry)?.first?.location(in: rippleClip)
        let row = rippleClip.convert(entry.bounds, from: entry)
        let point = touch ?? CGPoint(x: row.midX, y: rippleClip.bounds.midY)
        TapRipple.show(
            in: rippleClip.layer, at: point, radius: hypot(row.width, rippleClip.bounds.height), traits: traitCollection)
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
        let drawnHeight = max(bounds.height - topInset - 2 * rowInset, 0)
        rippleClip.frame = CGRect(
            x: scrollView.frame.minX, y: topInset + rowInset, width: scrollView.frame.width, height: drawnHeight)
        rippleClip.layer.cornerRadius = min(12, min(rippleClip.bounds.width, drawnHeight) * 0.22)
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
