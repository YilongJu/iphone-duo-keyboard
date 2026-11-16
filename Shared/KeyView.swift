import UIKit

/// The text or icon one key shows.
struct KeyDisplay {
    var primary: String?
    /// Text with its own fonts and colors. The key draws this text in place of `primary`.
    var styledPrimary: NSAttributedString?
    var secondary: String?
    /// The slide character of a letter key: small gray text at the top of the key. A slide up
    /// or down on the key types this character.
    var slideCharacter: String?
    var symbolName: String?
    var primaryFontSize: CGFloat = 22
    /// A key drawn in the pressed color while a mode is on, such as shift.
    var emphasized = false
    /// The return key of a field whose return key does an action, such as search or send, in
    /// place of a line break. The key is blue with a white symbol.
    var performsAction = false
}

enum KeyColors {
    static let text = UIColor.label

    /// The return key that does the field's action. The system blue adapts to light mode and
    /// dark mode.
    static let action = UIColor.systemBlue

    /// The pressed return key that does the field's action: the system blue of the appearance
    /// with 80 percent of its brightness, as a letter key turns darker when pressed.
    static let actionPressed = UIColor { traits in
        let color = UIColor.systemBlue.resolvedColor(with: traits)
        var red: CGFloat = 0, green: CGFloat = 0, blue: CGFloat = 0, alpha: CGFloat = 0
        guard color.getRed(&red, green: &green, blue: &blue, alpha: &alpha) else {
            fatalError("The system blue has no red, green and blue parts: \(color)")
        }
        return UIColor(red: red * 0.8, green: green * 0.8, blue: blue * 0.8, alpha: alpha)
    }

    /// The symbol and the text on the blue return key.
    static let actionText = UIColor.white

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
    private var performsAction = false
    private let primaryLabel = UILabel()
    private let secondaryLabel = UILabel()
    private let slideCharacterLabel = UILabel()
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
        slideCharacterLabel.textAlignment = .center
        slideCharacterLabel.textColor = .secondaryLabel
        slideCharacterLabel.font = .systemFont(ofSize: Self.slideCharacterFontSize)
        addSubview(slideCharacterLabel)
        iconView.contentMode = .center
        iconView.tintColor = KeyColors.text
        addSubview(iconView)
        updateBackground()
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("KeyView is built in code only")
    }

    /// The font size of the slide character, in points.
    static let slideCharacterFontSize: CGFloat = 11

    /// The text the key shows now: the main text, the upper text of a two-character key, and
    /// the slide character. The unit tests read these values.
    var shownTexts: (primary: String?, secondary: String?, slideCharacter: String?) {
        (primaryLabel.text, secondaryLabel.text, slideCharacterLabel.text)
    }

    /// The name of the SF Symbol the key shows now, or nil. The unit tests read this value.
    private(set) var shownSymbolName: String?

    /// The color of the drawn key now. The unit tests read this value, so the tests do not
    /// depend on which view draws the key.
    var drawnColor: UIColor? { backgroundColor }

    func apply(_ display: KeyDisplay) {
        primaryLabel.font = .systemFont(ofSize: display.primaryFontSize)
        // The color goes before the text, because styled text brings its own colors and a color
        // set after the styled text would replace them.
        let contentColor = display.performsAction ? KeyColors.actionText : KeyColors.text
        primaryLabel.textColor = contentColor
        iconView.tintColor = contentColor
        if let styled = display.styledPrimary {
            primaryLabel.attributedText = styled
        } else {
            primaryLabel.attributedText = nil
            primaryLabel.text = display.primary
        }
        secondaryLabel.text = display.secondary
        secondaryLabel.font = .systemFont(ofSize: 14)
        slideCharacterLabel.text = display.slideCharacter
        if let symbolName = display.symbolName {
            let configuration = UIImage.SymbolConfiguration(pointSize: 19, weight: .regular)
            let image = UIImage(systemName: symbolName, withConfiguration: configuration)
            // A wrong symbol name would leave the key blank, so a debug build stops here.
            assert(image != nil, "Unknown SF Symbol: \(symbolName)")
            iconView.image = image
        } else {
            iconView.image = nil
        }
        shownSymbolName = display.symbolName
        emphasized = display.emphasized
        performsAction = display.performsAction
        updateBackground()
        setNeedsLayout()
    }

    /// Fades the key's text and icon. The space bar's cursor mode uses the fade.
    func setContentFaded(_ faded: Bool) {
        let alpha: CGFloat = faded ? 0.15 : 1
        primaryLabel.alpha = alpha
        secondaryLabel.alpha = alpha
        slideCharacterLabel.alpha = alpha
        iconView.alpha = alpha
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        layer.shadowPath = UIBezierPath(roundedRect: bounds, cornerRadius: layer.cornerRadius).cgPath
        let content = bounds.insetBy(dx: 2, dy: 2)
        iconView.frame = content
        slideCharacterLabel.frame = .zero
        if slideCharacterLabel.text != nil {
            // The slide character sits at the top centre of the key and the letter a little
            // lower, as on the iPad keyboard of iOS. The letter keeps its full frame, so a
            // short key does not cut the letter.
            let topHeight = min(13, content.height * 0.4)
            slideCharacterLabel.frame = CGRect(x: content.minX, y: content.minY, width: content.width, height: topHeight)
            secondaryLabel.frame = .zero
            primaryLabel.frame = content.offsetBy(dx: 0, dy: min(4, content.height * 0.12))
        } else if secondaryLabel.text != nil {
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
        if performsAction {
            backgroundColor = pressed ? KeyColors.actionPressed : KeyColors.action
        } else if key.kind.isFunctionKey {
            backgroundColor = pressed ? KeyColors.character : KeyColors.function
        } else {
            backgroundColor = pressed ? KeyColors.function : KeyColors.character
        }
    }
}
