import UIKit

/// A scroll view whose content is all buttons. UIKit by default lets a button keep a touch that
/// starts on the button, so a drag across the candidates would not scroll. This subclass hands
/// such a drag to the scroll view, and a plain tap still presses the button.
final class CandidateScrollView: UIScrollView {
    override func touchesShouldCancel(in view: UIView) -> Bool {
        true
    }
}

/// The candidate row: the Chinese candidates, or the proofreader's fix of a sentence. The row
/// lies in the place of the prediction strip, so the keys of the top row stay in view. The
/// words scroll sideways, and the first word is the one the space bar types. The proofreader's
/// fix has a caption at the left. The Chinese candidates have none, so they start at the left
/// end: the row does not show the typed Pinyin letters.
final class CandidateBar: UIView {
    /// Called with the index of the word the user tapped.
    var onSelect: ((Int) -> Void)?
    /// Called when the user tapped the caption at the row's left end.
    var onSelectComposition: (() -> Void)?

    private let compositionLabel = UILabel()
    /// The caption at the row's left end. The unit tests read this value.
    var caption: String { compositionLabel.text ?? "" }
    /// The left edge of the words in the row. The unit tests read this value.
    var wordsMinX: CGFloat { scrollView.frame.minX }
    private let scrollView = CandidateScrollView()
    private var buttons: [UIButton] = []
    /// Holds the ripples of the taps. The row clips them to its capsule.
    private let rippleHost = UIView()
    /// Count of ripples in the row now. The unit tests read this value.
    var rippleCount: Int { rippleHost.layer.sublayers?.count ?? 0 }
    /// The room between the row's left end and the words of a row without a caption, in points.
    static let wordsInset: CGFloat = 6

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = KeyColors.candidateRow
        layer.cornerRadius = 5
        clipsToBounds = true
        compositionLabel.font = .systemFont(ofSize: 15)
        compositionLabel.textColor = .secondaryLabel
        compositionLabel.isUserInteractionEnabled = true
        compositionLabel.addGestureRecognizer(
            UITapGestureRecognizer(target: self, action: #selector(compositionTapped)))
        addSubview(compositionLabel)
        scrollView.showsHorizontalScrollIndicator = false
        scrollView.delaysContentTouches = false
        scrollView.canCancelContentTouches = true
        scrollView.alwaysBounceHorizontal = true
        addSubview(scrollView)
        rippleHost.isUserInteractionEnabled = false
        addSubview(rippleHost)
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("CandidateBar is built in code only")
    }

    func show(composition: String, words: [String]) {
        compositionLabel.text = composition
        for button in buttons {
            button.removeFromSuperview()
        }
        buttons = words.enumerated().map { index, word in
            var configuration = UIButton.Configuration.plain()
            configuration.title = word
            configuration.contentInsets = NSDirectionalEdgeInsets(top: 0, leading: 10, bottom: 0, trailing: 10)
            configuration.titleTextAttributesTransformer = UIConfigurationTextAttributesTransformer { attributes in
                var attributes = attributes
                attributes.font = .systemFont(ofSize: 20)
                return attributes
            }
            // The first word is the one the space bar types, so it carries the accent color.
            configuration.baseForegroundColor = index == 0 ? .tintColor : .label
            let button = UIButton(configuration: configuration)
            button.tag = index
            button.addTarget(self, action: #selector(candidatePressed(_:event:)), for: .touchDown)
            button.addTarget(self, action: #selector(candidateTapped(_:)), for: .touchUpInside)
            scrollView.addSubview(button)
            return button
        }
        scrollView.contentOffset = .zero
        setNeedsLayout()
    }

    @objc private func compositionTapped() {
        onSelectComposition?()
    }

    /// Starts a ripple at the finger's place on a candidate. The circle reaches every corner of
    /// the candidate, and the row clips it. With Reduce Motion on, the row shows no ripple.
    @objc private func candidatePressed(_ sender: UIButton, event: UIEvent?) {
        guard !UIAccessibility.isReduceMotionEnabled else { return }
        // An action that the code sends has no touch. Its ripple starts in the middle of the word.
        let touch = event?.touches(for: sender)?.first?.location(in: rippleHost)
        let frame = rippleHost.convert(sender.bounds, from: sender)
        let point = touch ?? CGPoint(x: frame.midX, y: frame.midY)
        TapRipple.show(
            in: rippleHost.layer, at: point, radius: hypot(frame.width, frame.height), traits: traitCollection)
    }

    @objc private func candidateTapped(_ sender: UIButton) {
        onSelect?(sender.tag)
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        // The row is a capsule, so its ends follow the round top corners of the keyboard.
        layer.cornerRadius = bounds.height / 2
        rippleHost.frame = bounds
        let labelWidth = min(compositionLabel.intrinsicContentSize.width, bounds.width * 0.4)
        compositionLabel.frame = CGRect(x: 14, y: 0, width: labelWidth, height: bounds.height)
        // Without a caption the words start near the row's left end.
        let scrollX = labelWidth > 0 ? compositionLabel.frame.maxX + 8 : Self.wordsInset

        scrollView.frame = CGRect(x: scrollX, y: 0, width: max(bounds.width - scrollX - 10, 0), height: bounds.height)
        var x: CGFloat = 0
        for button in buttons {
            let width = max(button.intrinsicContentSize.width, 40)
            button.frame = CGRect(x: x, y: 0, width: width, height: bounds.height)
            x += width
        }
        scrollView.contentSize = CGSize(width: x, height: bounds.height)
    }
}
