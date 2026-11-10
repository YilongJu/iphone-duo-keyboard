import UIKit

@MainActor
protocol KeyboardViewDelegate: AnyObject {
    func keyboardView(_ keyboardView: KeyboardView, insert text: String)
    func keyboardViewDeleteBackward(_ keyboardView: KeyboardView)
    func keyboardViewReturn(_ keyboardView: KeyboardView)
    func keyboardView(_ keyboardView: KeyboardView, moveCursorBy offset: Int)
    func keyboardView(_ keyboardView: KeyboardView, edit command: EditCommand)
    func keyboardViewDismiss(_ keyboardView: KeyboardView)
    /// Called on every finger down, so the owner can play the key click.
    func keyboardViewDidPressKey(_ keyboardView: KeyboardView)
}

/// Draws the keys and turns touches into typing actions.
/// The view picks the compact or the wide layout from its own width.
/// Every layout and size comes from `keyboard-layout.json`.
final class KeyboardView: UIView {
    private static var spec: KeyboardSpec.Metrics { KeyboardSpec.shared.metrics }

    /// The wide layout appears at this width in points and above.
    static var wideMinimumWidth: CGFloat { spec.wideMinimumWidth }

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

    /// Small text on the space bar, for a short notice such as "Copied".
    var spaceCaption: String? {
        didSet { if oldValue != spaceCaption { refreshLabels() } }
    }

    var shiftState: ShiftState = .off {
        didSet { if oldValue != shiftState { refreshLabels() } }
    }

    /// True while the select-all key is on. The key then draws in the pressed color.
    var selectAllActive = false {
        didSet { if oldValue != selectAllActive { refreshLabels() } }
    }

    /// True while shift is on because of automatic capitalization. Automatic shift makes the
    /// next letter upper case and leaves number and punctuation keys on their base character.
    private(set) var shiftIsAutomatic = false

    /// The owner calls this after each text change with the capitalization rule's result.
    func setAutomaticShift(_ capitalize: Bool) {
        guard shiftState != .locked else { return }
        shiftIsAutomatic = capitalize
        shiftState = capitalize ? .on : .off
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
        var latestX: CGFloat = 0
        var holdTimer: Timer?
        var startPoint: CGPoint = .zero
        /// True while the key will type its shifted character, after a long press or a slide up.
        var alternateActive = false
        var alternateFromHold = false

        init(keyView: KeyView) {
            self.keyView = keyView
        }
    }

    override init(frame: CGRect) {
        super.init(frame: frame)
        isMultipleTouchEnabled = true
        // iOS does not deliver a touch on a fully transparent point to a keyboard extension
        // (Apple Developer Forums thread 702798). This faint background makes the gaps between
        // the keys receive touches, and each touch then goes to the nearest key.
        backgroundColor = UIColor(white: 0.5, alpha: 0.02)
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
        let style = style(forWidth: width)
        let rowHeight: CGFloat
        if compactHeight {
            rowHeight = spec.landscapePhoneRowHeight
        } else {
            switch style {
            case .wide:
                let unit = width / KeyboardSpec.shared.wide.units
                rowHeight = min(max(unit * spec.wideRowHeightPerUnit, spec.wideRowHeightMin), spec.wideRowHeightMax)
            case .compact:
                rowHeight = spec.compactRowHeight
            }
        }
        return rowHeight * KeyboardLayout.totalRowHeight(style: style) + spec.topPadding + spec.bottomPadding
    }

    /// Opens a layer from code. The keys themselves switch layers during normal use.
    func show(layer: KeyboardLayer) {
        guard layer != currentLayer else { return }
        currentLayer = layer
        rebuild()
    }

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
            return KeyDisplay(primary: characterText(character), primaryFontSize: letterSize)
        case .dual(let base, let shifted):
            return KeyDisplay(primary: base, secondary: shifted, primaryFontSize: 19)
        case .space:
            if let spaceCaption {
                return KeyDisplay(primary: spaceCaption, primaryFontSize: 13)
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
        case .cursorUp:
            return KeyDisplay(symbolName: "arrow.up")
        case .cursorDown:
            return KeyDisplay(symbolName: "arrow.down")
        case .home:
            return KeyDisplay(primary: "Home", primaryFontSize: wordSize)
        case .end:
            return KeyDisplay(primary: "End", primaryFontSize: wordSize)
        case .selectAll:
            return KeyDisplay(primary: "Select All", primaryFontSize: wordSize, emphasized: selectAllActive)
        case .forwardDelete:
            return KeyDisplay(symbolName: "delete.right")
        case .cut:
            return KeyDisplay(symbolName: "scissors")
        case .copy:
            return KeyDisplay(symbolName: "doc.on.doc")
        case .paste:
            return KeyDisplay(symbolName: "doc.on.clipboard")
        case .switchLayer(let target):
            let title: String
            switch target {
            case .letters: title = "ABC"
            case .symbols: title = style == .wide ? ".?123" : "123"
            case .more: title = "#+="
            }
            return KeyDisplay(primary: title, primaryFontSize: wordSize)
        }
    }

    /// The text a character key shows and types. Shift changes the case on the letters layer
    /// only, so a symbol such as "π" on another layer keeps its form.
    func characterText(_ character: String) -> String {
        let isLetter = !character.isEmpty && character.allSatisfy { $0.isLetter }
        return currentLayer == .letters && isLetter && shiftState != .off ? character.uppercased() : character
    }

    // MARK: Layout

    private struct Metrics {
        let originX: CGFloat
        let width: CGFloat
        /// Height of a letter row. A row's own height is this value times the row's height fraction.
        let rowHeight: CGFloat
        /// Top edge of each row, plus the bottom edge of the last row.
        let rowEdges: [CGFloat]
    }

    private func metrics() -> Metrics? {
        guard !rows.isEmpty else { return nil }
        let spec = Self.spec
        let left = safeAreaInsets.left + spec.horizontalPadding
        let right = safeAreaInsets.right + spec.horizontalPadding
        let width = bounds.width - left - right
        let height = bounds.height - spec.topPadding - spec.bottomPadding
        let totalFraction = layout.rowHeights.reduce(0, +)
        guard width > 0, height > 0, totalFraction > 0 else { return nil }
        let rowHeight = height / totalFraction
        var edges: [CGFloat] = [spec.topPadding]
        for fraction in layout.rowHeights {
            edges.append((edges.last ?? spec.topPadding) + fraction * rowHeight)
        }
        return Metrics(originX: left, width: width, rowHeight: rowHeight, rowEdges: edges)
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        let wantedStyle = Self.style(forWidth: bounds.width)
        if wantedStyle != style {
            style = wantedStyle
            rebuild()
        }
        guard let metrics = metrics() else { return }
        let spec = Self.spec
        let gapY = style == .wide ? spec.gapYWide : spec.gapYCompact
        globeButton.isHidden = true
        for (rowIndex, row) in rows.enumerated() {
            let rowWeight = row.reduce(0) { $0 + $1.key.weight }
            let rowInset = rowIndex == rows.count - 1 ? spec.bottomRowCornerInset : 0
            let unit = (metrics.width - rowInset * 2) / layout.units
            var x = metrics.originX + rowInset + (layout.units - rowWeight) / 2 * unit
            let y = metrics.rowEdges[rowIndex]
            let height = metrics.rowEdges[rowIndex + 1] - y
            for keyView in row {
                let width = keyView.key.weight * unit
                let cell = CGRect(x: x, y: y, width: width, height: height)
                keyView.hitFrame = cell
                keyView.frame = cell.insetBy(dx: spec.gapX, dy: gapY)
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
        // A touch above the first row maps to the first row, and a touch below the last row to the last row.
        let rowIndex = rows.indices.last(where: { point.y >= metrics.rowEdges[$0] }) ?? 0
        func distance(_ keyView: KeyView) -> CGFloat {
            let frame = keyView.hitFrame
            if point.x < frame.minX { return frame.minX - point.x }
            if point.x > frame.maxX { return point.x - frame.maxX }
            return 0
        }
        return rows[rowIndex].min { distance($0) < distance($1) }
    }

    // MARK: Touches

    override func willMove(toWindow newWindow: UIWindow?) {
        super.willMove(toWindow: newWindow)
        if newWindow == nil {
            // Timers hold the view, so every timer stops when the keyboard leaves the screen.
            cancelAllTouches()
            stopRepeating()
        }
    }

    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) {
        for touch in touches.sorted(by: { $0.timestamp < $1.timestamp }) {
            // A second finger down commits the first finger's key, so fast typing keeps its order.
            commitPendingTextTouches()
            let point = touch.location(in: self)
            guard let keyView = keyView(at: point) else { continue }
            let state = TouchState(keyView: keyView)
            state.startPoint = point
            state.latestX = point.x
            activeTouches[touch] = state
            keyView.isHighlighted = true
            delegate?.keyboardViewDidPressKey(self)

            let kind = keyView.key.kind
            switch kind {
            case _ where kind.repeats:
                state.committed = true
                perform(kind)
                startRepeating(kind)
            case .shift:
                state.committed = true
                handleShiftTap(at: touch.timestamp)
            case .capsLock:
                state.committed = true
                shiftIsAutomatic = false
                shiftState = shiftState == .locked ? .off : .locked
            case .dual, .space:
                startHoldTimer(state)
            default:
                break
            }
        }
    }

    override func touchesMoved(_ touches: Set<UITouch>, with event: UIEvent?) {
        for touch in touches {
            guard let state = activeTouches[touch] else { continue }
            let point = touch.location(in: self)
            state.latestX = point.x
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
            if case .dual = state.keyView.key.kind {
                updateAlternate(state, at: point)
                if state.alternateActive { continue }
            }
            guard let target = keyView(at: point), target !== state.keyView, target.key.kind.isTextKey else {
                continue
            }
            state.holdTimer?.invalidate()
            state.holdTimer = nil
            state.keyView.isHighlighted = false
            state.keyView = target
            state.startPoint = point
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
            // iOS cancels a touch when a second finger makes the system check for a two-finger
            // gesture. A cancelled touch on a text key still types the key, so fast typing with
            // two fingers does not drop letters.
            finish(state, commit: state.keyView.key.kind.isTextKey && !state.cursorMode)
        }
    }

    private func finish(_ state: TouchState, commit: Bool) {
        state.holdTimer?.invalidate()
        state.holdTimer = nil
        if state.cursorMode {
            setCursorModeAppearance(false)
        }
        let kind = state.keyView.key.kind
        if kind.repeats && kind == repeatingKind {
            stopRepeating()
        }
        state.keyView.isHighlighted = false
        let useAlternate = state.alternateActive
        if useAlternate {
            setAlternate(state, active: false)
        }
        if commit && !state.committed {
            state.committed = true
            if useAlternate {
                performAlternate(kind)
            } else {
                perform(kind)
            }
        }
    }

    private func commitPendingTextTouches() {
        for state in activeTouches.values where !state.committed && state.keyView.key.kind.isTextKey {
            state.committed = true
            state.holdTimer?.invalidate()
            state.holdTimer = nil
            state.keyView.isHighlighted = false
            let kind = state.keyView.key.kind
            if state.alternateActive {
                setAlternate(state, active: false)
                performAlternate(kind)
            } else {
                perform(kind)
            }
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
        shiftIsAutomatic = false
        if shiftState == .locked {
            shiftState = .off
            lastShiftTapTime = 0
        } else if isDoubleTap {
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

    // MARK: Long press and slide up

    private func startHoldTimer(_ state: TouchState) {
        state.holdTimer = Timer.scheduledTimer(
            timeInterval: 0.4, target: self, selector: #selector(holdTimerFired(_:)),
            userInfo: state, repeats: false)
    }

    /// A finger held for 0.4 seconds selects the shifted character on a key with two characters,
    /// and turns the keyboard into a cursor trackpad on the space bar.
    @objc private func holdTimerFired(_ timer: Timer) {
        guard let state = timer.userInfo as? TouchState, !state.committed else { return }
        state.holdTimer = nil
        switch state.keyView.key.kind {
        case .dual:
            state.alternateFromHold = true
            setAlternate(state, active: true)
        case .space:
            state.committed = true
            state.cursorMode = true
            state.cursorAnchorX = state.latestX
            setCursorModeAppearance(true)
        default:
            break
        }
    }

    /// A slide up on a key with two characters selects the shifted character.
    /// A slide back down returns to the base character.
    private func updateAlternate(_ state: TouchState, at point: CGPoint) {
        guard let metrics = metrics() else { return }
        let dx = point.x - state.startPoint.x
        let dy = point.y - state.startPoint.y
        let threshold = max(14, metrics.rowHeight * 0.35)
        if !state.alternateActive {
            let leftKeyUpward = point.y < state.keyView.hitFrame.minY && dy < -8
            if abs(dx) < abs(dy), dy < -threshold || leftKeyUpward {
                setAlternate(state, active: true)
            }
        } else if !state.alternateFromHold, dy > -threshold / 2 {
            setAlternate(state, active: false)
        }
    }

    private func setAlternate(_ state: TouchState, active: Bool) {
        state.alternateActive = active
        if !active {
            state.alternateFromHold = false
        }
        guard case .dual(_, let shifted) = state.keyView.key.kind else { return }
        if active {
            state.holdTimer?.invalidate()
            state.holdTimer = nil
            state.keyView.apply(KeyDisplay(primary: shifted, primaryFontSize: 26))
        } else {
            state.keyView.apply(display(for: state.keyView.key.kind))
        }
    }

    private func performAlternate(_ kind: KeyKind) {
        guard case .dual(_, let shifted) = kind else { return }
        lastShiftTapTime = 0
        delegate?.keyboardView(self, insert: shifted)
    }

    // MARK: Actions

    private func perform(_ kind: KeyKind) {
        // Any other key between two shift taps ends the double-tap window for caps lock.
        lastShiftTapTime = 0
        switch kind {
        case .character(let character):
            let text = characterText(character)
            // Shift resets before the delegate call, because the delegate may turn shift on again.
            if shiftState == .on { shiftState = .off }
            delegate?.keyboardView(self, insert: text)
        case .dual(let base, let shifted):
            let text = shiftState == .on && !shiftIsAutomatic ? shifted : base
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
        case .cursorUp:
            delegate?.keyboardView(self, edit: .lineUp)
        case .cursorDown:
            delegate?.keyboardView(self, edit: .lineDown)
        case .home:
            delegate?.keyboardView(self, edit: .lineStart)
        case .end:
            delegate?.keyboardView(self, edit: .lineEnd)
        case .selectAll:
            delegate?.keyboardView(self, edit: .selectAll)
        case .forwardDelete:
            delegate?.keyboardView(self, edit: .deleteForward)
        case .cut:
            delegate?.keyboardView(self, edit: .cut)
        case .copy:
            delegate?.keyboardView(self, edit: .copy)
        case .paste:
            delegate?.keyboardView(self, edit: .paste)
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
}
