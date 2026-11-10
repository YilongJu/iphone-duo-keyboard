import UIKit

/// The text or icon one key shows.
struct KeyDisplay {
    var primary: String?
    var secondary: String?
    var symbolName: String?
    var primaryFontSize: CGFloat = 22
    /// A key drawn in the pressed color while a mode is on, such as shift.
    var emphasized = false
}

enum KeyColors {
    static let text = UIColor.label

    static let character = UIColor { traits in
        traits.userInterfaceStyle == .dark ? UIColor(white: 0.42, alpha: 1) : UIColor.white
    }

    static let function = UIColor { traits in
        traits.userInterfaceStyle == .dark
            ? UIColor(white: 0.27, alpha: 1)
            : UIColor(red: 0.68, green: 0.70, blue: 0.74, alpha: 1)
    }
}

/// One key. The view draws only. `KeyboardView` handles every touch.
final class KeyView: UIView {
    let key: Key
    /// The key's full cell, including the gaps around the drawn key. Touches map to cells.
    var hitFrame: CGRect = .zero

    var isHighlighted = false {
        didSet { updateBackground() }
    }

    private var emphasized = false
    private let primaryLabel = UILabel()
    private let secondaryLabel = UILabel()
    private let iconView = UIImageView()

    init(key: Key) {
        self.key = key
        super.init(frame: .zero)
        isUserInteractionEnabled = false
        layer.cornerRadius = 5
        layer.shadowColor = UIColor.black.cgColor
        layer.shadowOpacity = 0.3
        layer.shadowRadius = 0
        layer.shadowOffset = CGSize(width: 0, height: 1)

        for label in [primaryLabel, secondaryLabel] {
            label.textAlignment = .center
            label.textColor = KeyColors.text
            label.adjustsFontSizeToFitWidth = true
            label.minimumScaleFactor = 0.5
            addSubview(label)
        }
        iconView.contentMode = .center
        iconView.tintColor = KeyColors.text
        addSubview(iconView)
        updateBackground()
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("KeyView is built in code only")
    }

    func apply(_ display: KeyDisplay) {
        primaryLabel.text = display.primary
        primaryLabel.font = .systemFont(ofSize: display.primaryFontSize)
        secondaryLabel.text = display.secondary
        secondaryLabel.font = .systemFont(ofSize: 14)
        if let symbolName = display.symbolName {
            let configuration = UIImage.SymbolConfiguration(pointSize: 19, weight: .regular)
            let image = UIImage(systemName: symbolName, withConfiguration: configuration)
            // A wrong symbol name would leave the key blank, so a debug build stops here.
            assert(image != nil, "Unknown SF Symbol: \(symbolName)")
            iconView.image = image
        } else {
            iconView.image = nil
        }
        emphasized = display.emphasized
        updateBackground()
        setNeedsLayout()
    }

    /// Fades the key's text and icon. The space bar's cursor mode uses the fade.
    func setContentFaded(_ faded: Bool) {
        let alpha: CGFloat = faded ? 0.15 : 1
        primaryLabel.alpha = alpha
        secondaryLabel.alpha = alpha
        iconView.alpha = alpha
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        layer.shadowPath = UIBezierPath(roundedRect: bounds, cornerRadius: layer.cornerRadius).cgPath
        let content = bounds.insetBy(dx: 2, dy: 2)
        iconView.frame = content
        if secondaryLabel.text != nil {
            let topHeight = content.height * 0.42
            secondaryLabel.frame = CGRect(x: content.minX, y: content.minY, width: content.width, height: topHeight)
            primaryLabel.frame = CGRect(
                x: content.minX, y: content.minY + topHeight - 2,
                width: content.width, height: content.height - topHeight)
        } else {
            secondaryLabel.frame = .zero
            primaryLabel.frame = content
        }
    }

    private func updateBackground() {
        let pressed = isHighlighted != emphasized
        if key.kind.isFunctionKey {
            backgroundColor = pressed ? KeyColors.character : KeyColors.function
        } else {
            backgroundColor = pressed ? KeyColors.function : KeyColors.character
        }
    }
}
