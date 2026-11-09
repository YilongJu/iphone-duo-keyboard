import UIKit

protocol KeyboardViewDelegate: AnyObject {
    func keyboardView(_ keyboardView: KeyboardView, insert text: String)
    func keyboardViewDeleteBackward(_ keyboardView: KeyboardView)
    func keyboardViewReturn(_ keyboardView: KeyboardView)
    func keyboardView(_ keyboardView: KeyboardView, moveCursorBy offset: Int)
    func keyboardViewDismiss(_ keyboardView: KeyboardView)
    /// Called on every finger down, so the owner can play the key click.
    func keyboardViewDidPressKey(_ keyboardView: KeyboardView)
}

/// Draws the keys and turns touches into typing actions.
/// The view picks the compact or the wide layout from its own width.
final class KeyboardView: UIView {
    /// The wide layout appears at this width in points and above.
    static let wideMinimumWidth: CGFloat = 600

    weak var delegate: KeyboardViewDelegate?

    /// A real button on top of the globe key. The keyboard extension connects the button to
    /// `handleInputModeList(from:with:)`, which needs a control and its touch events.
    let globeButton = UIButton(type: .custom)

    var showsGlobe = true {
        didSet { if oldValue != showsGlobe { rebuild() } }
    }

    var returnKeyTitle = "return" {
        didSet { if oldValue != returnKeyTitle { refreshLabels() } }
    }

    /// Small text on the space bar. The first test builds show the keyboard's measurements here.
    var spaceCaption: String? {
        didSet { if oldValue != spaceCaption { refreshLabels() } }
    }

    var shiftState: ShiftState = .off {
        didSet { if oldValue != shiftState { refreshLabels() } }
    }

    private(set) var style: LayoutStyle = .compact
    private(set) var currentLayer: KeyboardLayer = .letters

    private var layout = KeyboardLayout.make(style: .compact, layer: .letters, showsGlobe: true)
    private var rows: [[KeyView]] = []
    private var activeTouches: [UITouch: TouchState] = [:]
    private var repeatTimer: Timer?
    private var repeatingKind: KeyKind?
    private var lastShiftTapTime: TimeInterval = 0

    private final class TouchState {
        var keyView: KeyView
        /// True once the key's action ran, so lifting the finger does not run the action again.
        var committed = false
        var cursorMode = false
        var cursorAnchorX: CGFloat = 0
        var cursorTimer: Timer?

        init(keyView: KeyView) {
            self.keyView = keyView
        }
    }

    override init(frame: CGRect) {
        super.init(frame: frame)
        isMultipleTouchEnabled = true
        backgroundColor = .clear
        globeButton.accessibilityLabel = "Next keyboard"
        addSubview(globeButton)
        rebuild()
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("KeyboardView is built in code only")
    }

    // MARK: Sizing

    static func style(forWidth width: CGFloat) -> LayoutStyle {
        width >= wideMinimumWidth ? .wide : .compact
    }

    /// Keyboard height for a given keyboard width.
    /// `compactHeight` is true when the vertical size class is compact, as on a phone in landscape.
    /// The function does not read the screen size, because `UIScreen.main` reports the outer
    /// display on an iPhone Duo even while the keyboard is on the inner display.
    static func preferredHeight(forWidth width: CGFloat, compactHeight: Bool) -> CGFloat {
        let rowHeight: CGFloat
        if compactHeight {
            rowHeight = 38
        } else {
            switch style(forWidth: width) {
            case .wide:
                let unit = width / KeyboardLayout.wideUnits
                rowHeight = min(max(unit * 1.05, 46), 60)
            case .compact:
                rowHeight = 46
            }
        }
        return rowHeight * 5 + verticalPadding * 2
    }

    private static let verticalPadding: CGFloat = 4
    private static let horizontalPadding: CGFloat = 3

    // MARK: Building

    private func rebuild() {
        cancelAllTouches()
        for keyView in rows.joined() {
            keyView.removeFromSuperview()
        }
        layout = KeyboardLayout.make(style: style, layer: currentLayer, showsGlobe: showsGlobe)
        rows = layout.rows.map { row in
            row.map { key in
                let keyView = KeyView(key: key)
                addSubview(keyView)
                return keyView
            }
        }
        bringSubviewToFront(globeButton)
        refreshLabels()
        setNeedsLayout()
    }

    private func refreshLabels() {
        for keyView in rows.joined() {
            keyView.apply(display(for: keyView.key.kind))
        }
    }

    private func display(for kind: KeyKind) -> KeyDisplay {
        let letterSize: CGFloat = style == .wide ? 24 : 23
        let wordSize: CGFloat = 16
        switch kind {
        case .character(let character):
            let text = isLetter(character) && shiftState != .off ? character.uppercased() : character
            return KeyDisplay(primary: text, primaryFontSize: letterSize)
        case .dual(let base, let shifted):
            return KeyDisplay(primary: base, secondary: shifted, primaryFontSize: 19)
        case .space:
            if let spaceCaption {
                return KeyDisplay(primary: spaceCaption, primaryFontSize: 11)
            }
            return KeyDisplay(primary: style == .compact ? "space" : nil, primaryFontSize: wordSize)
        case .backspace:
            return KeyDisplay(symbolName: "delete.left")
        case .shift:
            switch shiftState {
            case .off: return KeyDisplay(symbolName: "shift")
            case .on: return KeyDisplay(symbolName: "shift.fill", emphasized: true)
            case .locked: return KeyDisplay(symbolName: "capslock.fill", emphasized: true)
            }
        case .capsLock:
            let locked = shiftState == .locked
            return KeyDisplay(symbolName: locked ? "capslock.fill" : "capslock", emphasized: locked)
        case .tab:
            return KeyDisplay(symbolName: "arrow.right.to.line")
        case .returnKey:
            return KeyDisplay(primary: returnKeyTitle, primaryFontSize: wordSize)
        case .globe:
            return KeyDisplay(symbolName: "globe")
        case .dismiss:
            return KeyDisplay(symbolName: "keyboard.chevron.compact.down")
        case .cursorLeft:
            return KeyDisplay(symbolName: "arrow.left")
        case .cursorRight:
            return KeyDisplay(symbolName: "arrow.right")
        case .switchLayer(let target):
            let title: String
            switch target {
            case .letters: title = "ABC"
            case .symbols: title = style == .wide ? ".?123" : "123"
            }
            return KeyDisplay(primary: title, primaryFontSize: wordSize)
        }
    }

    private func isLetter(_ text: String) -> Bool {
        !text.isEmpty && text.allSatisfy { $0.isLetter }
    }

    // MARK: Layout

    private struct Metrics {
        let originX: CGFloat
        let originY: CGFloat
        let unit: CGFloat
        let rowHeight: CGFloat
    }

    private func metrics() -> Metrics? {
        guard !rows.isEmpty else { return nil }
        let left = safeAreaInsets.left + Self.horizontalPadding
        let right = safeAreaInsets.right + Self.horizontalPadding
        let width = bounds.width - left - right
        let height = bounds.height - Self.verticalPadding * 2
        guard width > 0, height > 0 else { return nil }
        return Metrics(
            originX: left,
            originY: Self.verticalPadding,
            unit: width / layout.units,
            rowHeight: height / CGFloat(rows.count))
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        let wantedStyle = Self.style(forWidth: bounds.width)
        if wantedStyle != style {
            style = wantedStyle
            rebuild()
        }
        guard let metrics = metrics() else { return }
        let gapX: CGFloat = 3
        let gapY: CGFloat = style == .wide ? 3.5 : 5
        globeButton.isHidden = true
        for (rowIndex, row) in rows.enumerated() {
            let rowWeight = row.reduce(0) { $0 + $1.key.weight }
            var x = metrics.originX + (layout.units - rowWeight) / 2 * metrics.unit
            let y = metrics.originY + CGFloat(rowIndex) * metrics.rowHeight
            for keyView in row {
                let width = keyView.key.weight * metrics.unit
                let cell = CGRect(x: x, y: y, width: width, height: metrics.rowHeight)
                keyView.hitFrame = cell
                keyView.frame = cell.insetBy(dx: gapX, dy: gapY)
                if keyView.key.kind == .globe {
                    globeButton.frame = cell
                    globeButton.isHidden = false
                }
                x += width
            }
        }
    }

    private func keyView(at point: CGPoint) -> KeyView? {
        guard let metrics = metrics() else { return nil }
        let rawIndex = Int(((point.y - metrics.originY) / metrics.rowHeight).rounded(.down))
        let rowIndex = min(max(rawIndex, 0), rows.count - 1)
        func distance(_ keyView: KeyView) -> CGFloat {
            let frame = keyView.hitFrame
            if point.x < frame.minX { return frame.minX - point.x }
            if point.x > frame.maxX { return point.x - frame.maxX }
            return 0
        }
        return rows[rowIndex].min { distance($0) < distance($1) }
    }

    // MARK: Touches

    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) {
        for touch in touches {
            // A second finger down commits the first finger's key, so fast typing keeps its order.
            commitPendingTextTouches()
            let point = touch.location(in: self)
            guard let keyView = keyView(at: point) else { continue }
            let state = TouchState(keyView: keyView)
            activeTouches[touch] = state
            keyView.isHighlighted = true
            delegate?.keyboardViewDidPressKey(self)

            let kind = keyView.key.kind
            switch kind {
            case .backspace, .cursorLeft, .cursorRight:
                state.committed = true
                perform(kind)
                startRepeating(kind)
            case .shift:
                state.committed = true
                handleShiftTap(at: touch.timestamp)
            case .capsLock:
                state.committed = true
                shiftState = shiftState == .locked ? .off : .locked
            case .space:
                state.cursorAnchorX = point.x
                state.cursorTimer = Timer.scheduledTimer(
                    timeInterval: 0.4, target: self, selector: #selector(cursorTimerFired(_:)),
                    userInfo: state, repeats: false)
            default:
                break
            }
        }
    }

    override func touchesMoved(_ touches: Set<UITouch>, with event: UIEvent?) {
        for touch in touches {
            guard let state = activeTouches[touch] else { continue }
            let point = touch.location(in: self)
            if state.cursorMode {
                let pointsPerCharacter: CGFloat = 10
                let offset = Int((point.x - state.cursorAnchorX) / pointsPerCharacter)
                if offset != 0 {
                    state.cursorAnchorX += CGFloat(offset) * pointsPerCharacter
                    delegate?.keyboardView(self, moveCursorBy: offset)
                }
                continue
            }
            guard !state.committed, state.keyView.key.kind.isTextKey else { continue }
            guard let target = keyView(at: point), target !== state.keyView, target.key.kind.isTextKey else {
                continue
            }
            state.cursorTimer?.invalidate()
            state.cursorTimer = nil
            state.keyView.isHighlighted = false
            state.keyView = target
            target.isHighlighted = true
        }
    }

    override func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent?) {
        for touch in touches {
            guard let state = activeTouches.removeValue(forKey: touch) else { continue }
            finish(state, commit: true)
        }
    }

    override func touchesCancelled(_ touches: Set<UITouch>, with event: UIEvent?) {
        for touch in touches {
            guard let state = activeTouches.removeValue(forKey: touch) else { continue }
            finish(state, commit: false)
        }
    }

    private func finish(_ state: TouchState, commit: Bool) {
        state.cursorTimer?.invalidate()
        state.cursorTimer = nil
        if state.cursorMode {
            setCursorModeAppearance(false)
        }
        let kind = state.keyView.key.kind
        if kind.repeats {
            stopRepeating()
        }
        state.keyView.isHighlighted = false
        if commit && !state.committed {
            state.committed = true
            perform(kind)
        }
    }

    private func commitPendingTextTouches() {
        for state in activeTouches.values where !state.committed && state.keyView.key.kind.isTextKey {
            state.committed = true
            state.cursorTimer?.invalidate()
            state.cursorTimer = nil
            state.keyView.isHighlighted = false
            perform(state.keyView.key.kind)
        }
    }

    private func cancelAllTouches() {
        let states = Array(activeTouches.values)
        activeTouches.removeAll()
        for state in states {
            finish(state, commit: false)
        }
    }

    private func handleShiftTap(at timestamp: TimeInterval) {
        let isDoubleTap = timestamp - lastShiftTapTime < 0.35
        lastShiftTapTime = timestamp
        if isDoubleTap {
            shiftState = .locked
        } else {
            shiftState = shiftState == .off ? .on : .off
        }
    }

    private func setCursorModeAppearance(_ active: Bool) {
        for keyView in rows.joined() {
            keyView.setContentFaded(active)
        }
    }

    // MARK: Actions

    private func perform(_ kind: KeyKind) {
        switch kind {
        case .character(let character):
            let text = isLetter(character) && shiftState != .off ? character.uppercased() : character
            // Shift resets before the delegate call, because the delegate may turn shift on again.
            if shiftState == .on { shiftState = .off }
            delegate?.keyboardView(self, insert: text)
        case .dual(let base, let shifted):
            let text = shiftState == .on ? shifted : base
            if shiftState == .on { shiftState = .off }
            delegate?.keyboardView(self, insert: text)
        case .space:
            delegate?.keyboardView(self, insert: " ")
        case .tab:
            delegate?.keyboardView(self, insert: "\t")
        case .backspace:
            delegate?.keyboardViewDeleteBackward(self)
        case .returnKey:
            delegate?.keyboardViewReturn(self)
        case .cursorLeft:
            delegate?.keyboardView(self, moveCursorBy: -1)
        case .cursorRight:
            delegate?.keyboardView(self, moveCursorBy: 1)
        case .dismiss:
            delegate?.keyboardViewDismiss(self)
        case .switchLayer(let target):
            currentLayer = target
            rebuild()
        case .shift, .capsLock, .globe:
            // Shift and caps lock act on finger down. The globe button handles the globe key.
            break
        }
    }

    private func startRepeating(_ kind: KeyKind) {
        stopRepeating()
        repeatingKind = kind
        repeatTimer = Timer.scheduledTimer(
            timeInterval: 0.45, target: self, selector: #selector(repeatDelayFired(_:)),
            userInfo: nil, repeats: false)
    }

    private func stopRepeating() {
        repeatTimer?.invalidate()
        repeatTimer = nil
        repeatingKind = nil
    }

    @objc private func repeatDelayFired(_ timer: Timer) {
        repeatTimer = Timer.scheduledTimer(
            timeInterval: 0.08, target: self, selector: #selector(repeatFired(_:)),
            userInfo: nil, repeats: true)
    }

    @objc private func repeatFired(_ timer: Timer) {
        guard let kind = repeatingKind else { return }
        perform(kind)
    }

    /// A finger held on the space bar for 0.4 seconds turns the keyboard into a cursor trackpad.
    @objc private func cursorTimerFired(_ timer: Timer) {
        guard let state = timer.userInfo as? TouchState, !state.committed else { return }
        state.committed = true
        state.cursorMode = true
        setCursorModeAppearance(true)
    }
}
