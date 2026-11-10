import UIKit

/// A scroll view whose content is all buttons. UIKit by default lets a button keep a touch that
/// starts on the button, so a drag across the candidates would not scroll. This subclass hands
/// such a drag to the scroll view, and a plain tap still presses the button.
final class CandidateScrollView: UIScrollView {
    override func touchesShouldCancel(in view: UIView) -> Bool {
        true
    }
}

/// The row of Chinese candidates. The typed Pinyin sits at the left, and the candidate words
/// scroll sideways to its right. The first word is the one the space bar types.
final class CandidateBar: UIView {
    /// Called with the index of the word the user tapped.
    var onSelect: ((Int) -> Void)?
    /// Called when the user tapped the typed letters at the row's left end.
    var onSelectComposition: (() -> Void)?

    private let compositionLabel = UILabel()
    private let scrollView = CandidateScrollView()
    private var buttons: [UIButton] = []

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = KeyColors.function
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

    @objc private func candidateTapped(_ sender: UIButton) {
        onSelect?(sender.tag)
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        let labelWidth = min(compositionLabel.intrinsicContentSize.width, bounds.width * 0.4)
        compositionLabel.frame = CGRect(x: 10, y: 0, width: labelWidth, height: bounds.height)
        let scrollX = compositionLabel.frame.maxX + 8
        scrollView.frame = CGRect(x: scrollX, y: 0, width: max(bounds.width - scrollX, 0), height: bounds.height)
        var x: CGFloat = 0
        for button in buttons {
            let width = max(button.intrinsicContentSize.width, 40)
            button.frame = CGRect(x: x, y: 0, width: width, height: bounds.height)
            x += width
        }
        scrollView.contentSize = CGSize(width: x, height: bounds.height)
    }
}
