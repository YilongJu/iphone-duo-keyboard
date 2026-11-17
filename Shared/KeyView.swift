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

    // The light appearance is the "Keycap" look and the dark appearance the "Dark glass" look of
    // the key shape designs. The keyboard follows the phone's light or dark setting, which the
    // phone can switch at sunset and sunrise.

    /// The keyboard's own background, under the keys.
    static let surface = UIColor { traits in
        traits.userInterfaceStyle == .dark ? KeyColors.hex(0x17181C) : KeyColors.hex(0xDADDE3)
    }

    /// A letter key. In dark mode the key is a light tint over the dark background.
    static let character = UIColor { traits in
        traits.userInterfaceStyle == .dark ? UIColor(white: 1, alpha: 0.11) : UIColor.white
    }

    static let function = UIColor { traits in
        traits.userInterfaceStyle == .dark ? UIColor(white: 1, alpha: 0.05) : KeyColors.hex(0xC3C8D1)
    }

    /// The lower edge under a letter key and under a function key in light mode, which gives
    /// the key its depth. Dark mode draws no edge.
    static let characterEdge = UIColor { traits in
        traits.userInterfaceStyle == .dark ? .clear : KeyColors.hex(0xB9BEC8)
    }

    static let functionEdge = UIColor { traits in
        traits.userInterfaceStyle == .dark ? .clear : KeyColors.hex(0x9DA3AE)
    }

    /// The thin light line along the top of a key in dark mode. Light mode draws no line.
    static let topLine = UIColor { traits in
        traits.userInterfaceStyle == .dark ? UIColor(white: 1, alpha: 0.10) : .clear
    }

    /// The upper text of a two-character key, as the "!" of the "1" key.
    static let secondaryText = UIColor { traits in
        traits.userInterfaceStyle == .dark ? KeyColors.hex(0x9CA3AF) : KeyColors.hex(0x5B616C)
    }

    /// The tint that a pressed key takes and that fades after the lift (the "trail" of the key
    /// press feedback design C).
    static let trail = UIColor { traits in
        traits.userInterfaceStyle == .dark ? UIColor(red: 1, green: 170 / 255, blue: 60 / 255, alpha: 0.42) : KeyColors.hex(0xFFE2B8)
    }

    /// The ripple that spreads from the touch point of a key press.
    static let ripple = UIColor { traits in
        traits.userInterfaceStyle == .dark
            ? UIColor(red: 1, green: 196 / 255, blue: 120 / 255, alpha: 0.5)
            : UIColor(red: 217 / 255, green: 119 / 255, blue: 6 / 255, alpha: 0.32)
    }

    /// The candidate row of Chinese mode and the row of a sentence fix. The row lies over the top
    /// row of keys, so its color is opaque in both modes; the dark function key color is a tint.
    static let candidateRow = UIColor { traits in
        traits.userInterfaceStyle == .dark ? KeyColors.hex(0x26272C) : KeyColors.hex(0xC3C8D1)
    }

    /// The capsule under the emoji of the top row.
    static let capsule = UIColor { traits in
        traits.userInterfaceStyle == .dark ? KeyColors.hex(0x2A2C32) : UIColor.white
    }

    private static func hex(_ value: Int) -> UIColor {
        UIColor(
            red: CGFloat((value >> 16) & 0xFF) / 255, green: CGFloat((value >> 8) & 0xFF) / 255,
            blue: CGFloat(value & 0xFF) / 255, alpha: 1)
    }
}

/// One key. The view draws only. `KeyboardView` handles every touch.
final class KeyView: UIView {
    let key: Key
    /// The key's full cell, including the gaps around the drawn key. Touches map to cells.
    var hitFrame: CGRect = .zero

    /// A pressed key keeps its pressed color at least this long, so a quick tap still shows.
    static let shortestPressSeconds = 0.08
    /// After the lift the pressed color fades back over this time.
    static let releaseFadeSeconds = 0.2
    /// After the lift the trail tint fades over this time.
    static let trailFadeSeconds = 0.8

    var isHighlighted = false {
        didSet {
            guard isHighlighted != oldValue else {
                updateBackground()
                return
            }
            if isHighlighted {
                pressedAt = CACurrentMediaTime()
                background.layer.removeAllAnimations()
                trailView.layer.removeAllAnimations()
                // The blue return key keeps its own pressed blue and gets no tint.
                trailView.alpha = performsAction ? 0 : 1
                updateBackground()
            } else {
                UIView.animate(
                    withDuration: Self.trailFadeSeconds, delay: 0,
                    options: [.curveEaseInOut, .allowUserInteraction, .beginFromCurrentState]
                ) {
                    self.trailView.alpha = 0
                }
                // The color the key has now goes in at once, so `drawnColor` reads it; only the
                // drawing on screen fades.
                let held = CACurrentMediaTime() - pressedAt
                UIView.animate(
                    withDuration: Self.releaseFadeSeconds, delay: max(0, Self.shortestPressSeconds - held),
                    options: [.curveEaseOut, .allowUserInteraction, .beginFromCurrentState]
                ) {
                    self.updateBackground()
                }
            }
        }
    }

    private var pressedAt: CFTimeInterval = 0

    private var emphasized = false
    private var performsAction = false
    /// The drawn key: its color, its round corners and its lower edge, which is a shadow.
    private let background = UIView()
    /// The trail tint over the drawn key. It shows while the key is pressed and fades after the lift.
    private let trailView = UIView()
    /// Clips the ripples to the key's round corners.
    private let rippleClip = UIView()
    /// Clips the top line to the key's round corners.
    private let topLineClip = UIView()
    private let topLine = UIView()
    private let primaryLabel = UILabel()
    private let secondaryLabel = UILabel()
    private let slideCharacterLabel = UILabel()
    private let iconView = UIImageView()

    init(key: Key) {
        self.key = key
        super.init(frame: .zero)
        isUserInteractionEnabled = false
        background.isUserInteractionEnabled = false
        background.layer.shadowOpacity = 1
        background.layer.shadowRadius = 0
        addSubview(background)
        trailView.isUserInteractionEnabled = false
        trailView.backgroundColor = KeyColors.trail
        trailView.alpha = 0
        addSubview(trailView)
        rippleClip.isUserInteractionEnabled = false
        rippleClip.clipsToBounds = true
        addSubview(rippleClip)
        topLineClip.isUserInteractionEnabled = false
        topLineClip.clipsToBounds = true
        topLine.backgroundColor = KeyColors.topLine
        topLineClip.addSubview(topLine)
        addSubview(topLineClip)

        for label in [primaryLabel, secondaryLabel] {
            label.textAlignment = .center
            label.textColor = KeyColors.text
            label.adjustsFontSizeToFitWidth = true
            label.minimumScaleFactor = 0.5
            addSubview(label)
        }
        secondaryLabel.textColor = KeyColors.secondaryText
        slideCharacterLabel.textAlignment = .center
        slideCharacterLabel.textColor = .secondaryLabel
        slideCharacterLabel.font = .systemFont(ofSize: Self.slideCharacterFontSize)
        addSubview(slideCharacterLabel)
        iconView.contentMode = .center
        iconView.tintColor = KeyColors.text
        addSubview(iconView)
        updateBackground()
        // A shadow takes a fixed color, so the edge changes by hand with light and dark mode.
        registerForTraitChanges([UITraitUserInterfaceStyle.self]) { (key: KeyView, _: UITraitCollection) in
            key.updateEdge()
        }
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
    var drawnColor: UIColor? { background.backgroundColor }

    /// How strong the trail tint is now, from 0 to 1. The unit tests read this value.
    var trailStrength: CGFloat { trailView.alpha }

    /// The ripple of a key press (key press feedback design C): a circle that grows from the
    /// touch point and fades, inside the key's round shape only.
    static let rippleSeconds = 0.46

    /// Starts a ripple at `point`, in the key's coordinates. With Reduce Motion on, the key shows
    /// only its trail tint.
    func showRipple(at point: CGPoint) {
        guard !UIAccessibility.isReduceMotionEnabled, !performsAction else { return }
        // The circle reaches every corner of the key from any touch point.
        let radius = hypot(bounds.width, bounds.height)
        let ripple = CAShapeLayer()
        ripple.path = UIBezierPath(ovalIn: CGRect(x: -radius, y: -radius, width: 2 * radius, height: 2 * radius)).cgPath
        ripple.fillColor = KeyColors.ripple.resolvedColor(with: traitCollection).cgColor
        ripple.position = point
        ripple.opacity = 0
        rippleClip.layer.addSublayer(ripple)
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
        group.duration = Self.rippleSeconds
        group.timingFunction = CAMediaTimingFunction(name: .easeOut)
        ripple.add(group, forKey: "ripple")
        CATransaction.commit()
    }

    /// Count of ripples in this key now. The unit tests read this value.
    var rippleCount: Int { rippleClip.layer.sublayers?.count ?? 0 }

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
        background.frame = bounds
        // Round corners of up to 12 points, less on the small keys of the compact layout.
        let radius = min(12, min(bounds.width, bounds.height) * 0.22)
        background.layer.cornerRadius = radius
        background.layer.shadowOffset = CGSize(width: 0, height: bounds.height >= 50 ? 3 : 2)
        background.layer.shadowPath = UIBezierPath(roundedRect: background.bounds, cornerRadius: radius).cgPath
        trailView.frame = bounds
        trailView.layer.cornerRadius = radius
        rippleClip.frame = bounds
        rippleClip.layer.cornerRadius = radius
        topLineClip.frame = bounds
        topLineClip.layer.cornerRadius = radius
        topLine.frame = CGRect(x: 0, y: 0, width: bounds.width, height: 1)
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

    private func updateEdge() {
        let edge = key.kind.isFunctionKey || performsAction ? KeyColors.functionEdge : KeyColors.characterEdge
        background.layer.shadowColor = edge.resolvedColor(with: traitCollection).cgColor
    }

    private func updateBackground() {
        updateEdge()
        let pressed = isHighlighted != emphasized
        if performsAction {
            background.backgroundColor = pressed ? KeyColors.actionPressed : KeyColors.action
        } else if key.kind.isFunctionKey {
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
