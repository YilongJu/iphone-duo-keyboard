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

    /// How far the drawn background stays in from the left and the right edge of the key, in
    /// points. The top row of keys frees room for emoji this way. The texts and the icon keep
    /// their place, because they lay out in the whole key.
    var backgroundInsets: (left: CGFloat, right: CGFloat) = (0, 0) {
        didSet { setNeedsLayout() }
    }

    private var emphasized = false
    /// The drawn key: its color, its round corners and its shadow.
    private let background = UIView()
    private let primaryLabel = UILabel()
    private let secondaryLabel = UILabel()
    private let slideCharacterLabel = UILabel()
    private let iconView = UIImageView()

    init(key: Key) {
        self.key = key
        super.init(frame: .zero)
        isUserInteractionEnabled = false
        background.isUserInteractionEnabled = false
        background.layer.cornerRadius = 5
        background.layer.shadowColor = UIColor.black.cgColor
        background.layer.shadowOpacity = 0.3
        background.layer.shadowRadius = 0
        background.layer.shadowOffset = CGSize(width: 0, height: 1)
        addSubview(background)

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

    func apply(_ display: KeyDisplay) {
        primaryLabel.font = .systemFont(ofSize: display.primaryFontSize)
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
        emphasized = display.emphasized
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

    /// How far the drawn background can move in from each side of the key while the icon and
    /// the texts stay inside it with a margin of 6 points, in points.
    var roomToShrinkBackground: CGFloat {
        let iconWidth = iconView.image?.size.width ?? 0
        let textWidth = [primaryLabel, secondaryLabel, slideCharacterLabel]
            .map { $0.text == nil ? 0 : $0.intrinsicContentSize.width }.max() ?? 0
        return max(0, (bounds.width - max(iconWidth, textWidth)) / 2 - 6)
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        background.frame = CGRect(
            x: bounds.minX + backgroundInsets.left, y: bounds.minY,
            width: max(0, bounds.width - backgroundInsets.left - backgroundInsets.right), height: bounds.height)
        background.layer.shadowPath = UIBezierPath(
            roundedRect: background.bounds, cornerRadius: background.layer.cornerRadius).cgPath
        let content = bounds.insetBy(dx: 2, dy: 2)
        defer {
            for label in [primaryLabel, secondaryLabel, slideCharacterLabel] {
                guard let text = label.text, KeyboardTextLogic.fullWidthMarks.contains(text), !label.frame.isEmpty else {
                    continue
                }
                let offset = Self.offsetToCenter(text, font: label.font, size: label.frame.size)
                label.frame = label.frame.offsetBy(dx: offset.dx, dy: offset.dy)
            }
        }
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
        if key.kind.isFunctionKey {
            background.backgroundColor = pressed ? KeyColors.character : KeyColors.function
        } else {
            background.backgroundColor = pressed ? KeyColors.function : KeyColors.character
        }
    }

    // MARK: Full-width marks

    /// The moves that center a drawn mark in its label, by the text, the font size and the label size.
    private static var centeringOffsets: [String: CGVector] = [:]

    /// The move that puts the drawn ink of `text` in the middle of a label of `size`. A font
    /// draws a full-width mark such as "，" in a corner of its square, and a centered label
    /// centers the square, so the mark looks low and left. The function draws the text as a
    /// UILabel draws it and measures its dark pixels, and the result holds for every font.
    static func offsetToCenter(_ text: String, font: UIFont, size: CGSize) -> CGVector {
        let cacheKey = "\(text)|\(font.fontName)|\(font.pointSize)|\(size.width)|\(size.height)"
        if let cached = centeringOffsets[cacheKey] { return cached }
        let scale: CGFloat = 2
        let width = Int((size.width * scale).rounded(.up)), height = Int((size.height * scale).rounded(.up))
        var pixels = [UInt8](repeating: 255, count: width * height * 4)
        let label = UILabel(frame: CGRect(origin: .zero, size: size))
        label.font = font
        label.text = text
        label.textAlignment = .center
        label.textColor = .black
        pixels.withUnsafeMutableBytes { buffer in
            guard let context = CGContext(
                data: buffer.baseAddress, width: width, height: height, bitsPerComponent: 8, bytesPerRow: width * 4,
                space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
            else { preconditionFailure("No bitmap of \(width) by \(height) pixels for \(text)") }
            context.translateBy(x: 0, y: CGFloat(height))
            context.scaleBy(x: scale, y: -scale)
            UIGraphicsPushContext(context)
            label.drawText(in: label.bounds)
            UIGraphicsPopContext()
        }
        var minX = width, maxX = -1, minY = height, maxY = -1
        for y in 0..<height {
            for x in 0..<width where pixels[(y * width + x) * 4] < 200 {
                minX = min(minX, x)
                maxX = max(maxX, x)
                minY = min(minY, y)
                maxY = max(maxY, y)
            }
        }
        // Each full-width mark has a glyph on iOS, so a mark that draws nothing is a bug.
        precondition(maxX >= 0, "\(text) draws no pixels in \(font.fontName)")
        let inkMiddle = CGPoint(x: CGFloat(minX + maxX + 1) / 2 / scale, y: CGFloat(minY + maxY + 1) / 2 / scale)
        let offset = CGVector(dx: size.width / 2 - inkMiddle.x, dy: size.height / 2 - inkMiddle.y)
        centeringOffsets[cacheKey] = offset
        return offset
    }
}
