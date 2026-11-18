import UIKit

@MainActor
protocol KeyboardViewDelegate: AnyObject {
    func keyboardView(_ keyboardView: KeyboardView, insert text: String)
    func keyboardViewDeleteBackward(_ keyboardView: KeyboardView)
    func keyboardViewReturn(_ keyboardView: KeyboardView)
    func keyboardView(_ keyboardView: KeyboardView, moveCursorBy offset: Int)
    func keyboardView(_ keyboardView: KeyboardView, edit command: EditCommand)
    /// The user tapped a word in the candidate bar.
    func keyboardView(_ keyboardView: KeyboardView, didSelectCandidateAt index: Int)
    /// The user tapped an emoji in the prediction strip of the top row.
    func keyboardView(_ keyboardView: KeyboardView, didSelectTopRowEmoji emoji: String)
    /// The user tapped a predicted word in the prediction strip of the top row.
    func keyboardView(_ keyboardView: KeyboardView, didSelectPredictedWord word: String)
    func keyboardViewDismiss(_ keyboardView: KeyboardView)
    /// Called on every finger down, so the owner can play the key click.
    func keyboardViewDidPressKey(_ keyboardView: KeyboardView)
}

extension KeyboardViewDelegate {
    /// An owner that shows no predicted words needs no handler for a tap on one.
    func keyboardView(_ keyboardView: KeyboardView, didSelectPredictedWord word: String) {}
}

/// The rule for a finger that moves on a letter key with a slide character.
///
/// The rule reads the move from the point where the touch took the key: `dx` to the side and
/// `dy` up or down, in points. A move is vertical when `dy` is larger than `dx`.
/// 1. A vertical move longer than 0.4 of a letter row's height selects the slide character.
/// 2. A selected slide character stays selected until the finger comes back to less than half
///    of that distance from the start height. A move to the side does not end the selection.
/// 3. While the move is vertical, the touch stays with its key. A touch on any other text key
///    moves to the key under the finger, and a slide leaves its key after a few points: a
///    slide up from the top edge of "a" is over "q" at once. So a vertical move never moves
///    the touch, and a short one types the letter of the key where it started.
/// 4. A move that is not vertical can move the touch to the key under the finger, as on every
///    other text key. The new key then starts its own move at the point where the touch took it.
/// The rule holds no time, so a slow press never selects the slide character.
enum SlideGesture {
    /// The length of a slide that selects the slide character, as a part of a letter row's height.
    static let selectDistanceInRowHeights: CGFloat = 0.4

    /// What the touch does after a move.
    enum Step: Equatable {
        /// The key will type its slide character, and the touch stays with the key.
        case slideCharacter
        /// The key will type its letter, and the touch stays with the key.
        case letter
        /// The key will type its letter, and the touch moves to another text key when the finger is over one.
        case letterOrOtherKey
    }

    /// `selected` is true when the slide character is selected before this move.
    static func step(selected: Bool, dx: CGFloat, dy: CGFloat, rowHeight: CGFloat) -> Step {
        let selectDistance = rowHeight * selectDistanceInRowHeights
        let vertical = abs(dy) > abs(dx)
        let staysSelected = selected && abs(dy) >= selectDistance / 2
        let becomesSelected = !selected && vertical && abs(dy) > selectDistance
        if staysSelected || becomesSelected {
            return .slideCharacter
        }
        return vertical ? .letter : .letterOrOtherKey
    }
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

    /// The return key type of the field. The return key shows the symbol of the type, and the
    /// key is blue when the type does an action, such as search or send, in place of a line break.
    var returnKeyType: UIReturnKeyType = .default {
        didSet { if oldValue != returnKeyType { refreshLabels() } }
    }

    /// Small text on the space bar, for a short notice such as "Copied".
    var spaceCaption: String? {
        didSet { if oldValue != spaceCaption { refreshLabels() } }
    }

    var shiftState: ShiftState = .off {
        didSet { if oldValue != shiftState { refreshLabels() } }
    }

    /// The text of the language key: both languages in a fixed order, as in the common
    /// "\u{6587}/A" sign. The language the keyboard types now is large, bold and in the full
    /// text color. The other language is small and gray. A press switches the two.
    static func languageKeyText(chineseActive: Bool) -> NSAttributedString {
        func part(_ text: String, active: Bool) -> NSAttributedString {
            NSAttributedString(string: text, attributes: [
                .font: UIFont.systemFont(ofSize: active ? 20 : 15, weight: active ? .bold : .regular),
                .foregroundColor: active ? KeyColors.text : UIColor.secondaryLabel,
            ])
        }
        let text = NSMutableAttributedString()
        text.append(part("\u{4E2D}", active: chineseActive))
        text.append(part("/", active: false))
        text.append(part("A", active: !chineseActive))
        return text
    }

    /// True while the keyboard types Chinese. The language key then shows the Chinese sign as the active one.
    var chineseActive = false {
        didSet { if oldValue != chineseActive { refreshLabels() } }
    }

    /// True while a Chinese quotation of the double quote key is open, so the key shows the
    /// closing quote. `chineseSingleQuoteIsOpen` is the same for the single quote key.
    var chineseDoubleQuoteIsOpen = false {
        didSet { if oldValue != chineseDoubleQuoteIsOpen { refreshLabels() } }
    }

    var chineseSingleQuoteIsOpen = false {
        didSet { if oldValue != chineseSingleQuoteIsOpen { refreshLabels() } }
    }

    /// True while Pinyin letters wait for a candidate. The apostrophe key then splits two
    /// syllables, as in "xi'an", so it shows the apostrophe.
    var pinyinLettersWait = false {
        didSet { if oldValue != pinyinLettersWait { refreshLabels() } }
    }

    /// The text a key shows for the character `character` that it types. In Chinese mode a
    /// punctuation key types a Chinese mark (`KeyboardTextLogic.chineseMark`), and the key shows
    /// that mark. Every other key shows its own character.
    func label(_ character: String) -> String {
        guard chineseActive, !(character == "'" && pinyinLettersWait) else { return character }
        return KeyboardTextLogic.chineseMark(
            forKey: character, doubleQuoteIsOpen: chineseDoubleQuoteIsOpen, singleQuoteIsOpen: chineseSingleQuoteIsOpen)
    }

    /// The candidate row: the Chinese candidates while the user composes a word, or the
    /// proofreader's fix. The row lies over the prediction strip, between Select All and Cut, so
    /// the keys of the top row stay in view and react.
    let candidateBar = CandidateBar()

    /// Shows the typed Pinyin and its candidate words, or hides the bar when `composition` is nil.
    func showCandidates(composition: String?, words: [String]) {
        if let composition {
            candidateBar.show(composition: composition, words: words)
            candidateBar.isHidden = false
        } else {
            if !candidateBar.isHidden {
                candidatesHiddenTime = ProcessInfo.processInfo.systemUptime
            }
            candidateBar.isHidden = true
        }
    }

    /// The prediction strip of the top row, in the place of the layout's `.predictionStrip` key.
    /// It shows the emoji of the English word before the cursor, and then the predicted words.
    let predictionStrip = PredictionStrip()

    /// The emoji of the English word before the cursor. They take the first places of the
    /// prediction strip.
    private(set) var topRowEmoji: [String] = []
    /// The predicted words of the prediction strip, the most probable word first.
    private(set) var predictedWords: [String] = []

    /// Shows the emoji and the predicted words in the prediction strip. The emoji come first.
    func showPredictionStrip(emoji: [String], words: [String]) {
        topRowEmoji = emoji
        predictedWords = words
        predictionStrip.show(emoji.map { PredictionStrip.Item.emoji($0) } + words.map { PredictionStrip.Item.word($0) })
    }

    /// The typing speed of the top row, in the place of the layout's `.typingSpeed` key.
    let typingSpeedView = TypingSpeedView()

    /// Shows the typing speed in words per minute, or no speed for nil.
    func showTypingSpeed(_ wordsPerMinute: Int?) {
        typingSpeedView.wordsPerMinute = wordsPerMinute
    }

    /// Count of ripples on screen now, in all keys. The unit tests read this value.
    var rippleCount: Int {
        subviews.compactMap { $0 as? KeyView }.reduce(0) { $0 + $1.rippleCount }
    }

    /// Called when the user tapped the typed Pinyin letters at the left end of the candidate row.
    var onSelectComposition: @MainActor () -> Void = {}

    /// The moment the candidate row last left the screen, on the clock of `UITouch.timestamp`.
    private var candidatesHiddenTime: TimeInterval = -1

    /// True for a touch on the first row that must not press a key: a touch in a layout without
    /// the strip's place, where the candidate row lies over the first row's keys. A touch on an
    /// empty part of the candidate row would reach the key under it, and a tap aimed at a
    /// candidate would reach that key when the row has just left. The key at the left is Select
    /// All, and the next typed character would then replace all the text. In a layout with the
    /// strip's place the candidate row covers no key, and a touch in the strip's cell never
    /// reaches a key.
    private func candidateRowTakesTouch(at point: CGPoint, time: TimeInterval) -> Bool {
        guard !rows.joined().contains(where: { $0.key.kind == .predictionStrip }) else { return false }
        guard let metrics = metrics(), point.y < metrics.rowEdges[1] else { return false }
        return !candidateBar.isHidden || time - candidatesHiddenTime < 0.5
    }

    /// True while the candidate row shows, and for half a second after it leaves. The row lies
    /// over the prediction strip, so a tap aimed at a candidate must not select an entry of the
    /// strip.
    private var candidateRowCoversTheStrip: Bool {
        !candidateBar.isHidden || ProcessInfo.processInfo.systemUptime - candidatesHiddenTime < 0.5
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
    /// The width of the empty middle that the current keys were built with, in key units.
    private var builtSplitGap: CGFloat?
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
        /// True while the key will type its alternate character: the shifted character of a
        /// two-character key after a long press or a slide up or down, and the slide character
        /// of a letter key after a slide up or down.
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
        // (Apple Developer Forums thread 702798). The keyboard's own background makes the gaps
        // between the keys receive touches, and each touch then goes to the nearest key.
        backgroundColor = KeyColors.surface
        globeButton.accessibilityLabel = "Next keyboard"
        addSubview(globeButton)
        candidateBar.isHidden = true
        candidateBar.onSelect = { [weak self] index in
            guard let self else { return }
            self.delegate?.keyboardView(self, didSelectCandidateAt: index)
        }
        candidateBar.onSelectComposition = { [weak self] in
            self?.onSelectComposition()
        }
        addSubview(candidateBar)
        predictionStrip.onPress = { [weak self] in
            guard let self, !self.candidateRowCoversTheStrip else { return }
            // A finger on the strip commits the key of a finger that still rests on a letter,
            // as a second finger on a key does, so the letter comes before the tap.
            self.commitPendingTextTouches()
            self.delegate?.keyboardViewDidPressKey(self)
        }
        predictionStrip.onSelect = { [weak self] item in
            guard let self, !self.candidateRowCoversTheStrip else { return }
            switch item {
            case .emoji(let emoji): self.delegate?.keyboardView(self, didSelectTopRowEmoji: emoji)
            case .word(let word): self.delegate?.keyboardView(self, didSelectPredictedWord: word)
            }
        }
        addSubview(predictionStrip)
        addSubview(typingSpeedView)
        rebuild()
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("KeyboardView is built in code only")
    }

    // MARK: Sizing

    /// The layout for a keyboard width.
    ///
    /// An iPhone, the iPhone Duo included, chooses by width alone: compact, then wide, then split.
    /// An iPad gets the two layouts of the open iPhone Duo: wide in portrait and split in
    /// landscape. A keyboard narrower than the wide layout's minimum is compact on both.
    static func style(
        forWidth width: CGFloat, device: KeyboardDevice = .current,
        landscape: Bool = KeyboardDevice.screenIsLandscape
    ) -> LayoutStyle {
        if device == .pad {
            guard width >= wideMinimumWidth else { return .compact }
            return landscape ? .split : .wide
        }
        if width >= spec.splitMinimumWidth { return .split }
        return width >= wideMinimumWidth ? .wide : .compact
    }

    /// Width of the first row's left end that stays empty, in points: the layout file's width
    /// for an iPad, which is 0 today, and 0 on an iPhone.
    static func shortcutButtonsWidth(style: LayoutStyle, device: KeyboardDevice = .current) -> CGFloat {
        device == .pad && style != .compact ? spec.padShortcutButtonsWidth : 0
    }

    /// The cells of a row's keys after the row's left group moved right by `reserve` points.
    /// The left group is the keys before the empty middle of a split row, or the whole row.
    /// The group keeps its right edge, so its keys get narrower by the same share.
    static func cells(_ cells: [CGRect], leftGroupCount: Int, movedRightBy reserve: CGFloat) -> [CGRect] {
        guard reserve > 0, leftGroupCount > 0, let first = cells.first else { return cells }
        let groupEnd = cells[leftGroupCount - 1].maxX
        let oldWidth = groupEnd - first.minX
        guard oldWidth > reserve else { return cells }
        let scale = (oldWidth - reserve) / oldWidth
        return cells.enumerated().map { index, cell in
            guard index < leftGroupCount else { return cell }
            return CGRect(
                x: first.minX + reserve + (cell.minX - first.minX) * scale, y: cell.minY,
                width: cell.width * scale, height: cell.height)
        }
    }

    /// Width of the split layout's empty middle in key units, or nil for the layout file's width.
    static func splitGap(forWidth width: CGFloat, device: KeyboardDevice = .current) -> CGFloat? {
        device == .pad ? KeyboardLayout.padSplitGap(forWidth: width) : nil
    }

    /// Keyboard height for a given keyboard width.
    /// `compactHeight` is true when the vertical size class is compact, as on a phone in landscape.
    /// The function does not read the screen size, because `UIScreen.main` reports the outer
    /// display on an iPhone Duo even while the keyboard is on the inner display.
    static func preferredHeight(
        forWidth width: CGFloat, compactHeight: Bool, device: KeyboardDevice = .current,
        landscape: Bool = KeyboardDevice.screenIsLandscape
    ) -> CGFloat {
        let style = style(forWidth: width, device: device, landscape: landscape)
        let rowHeight: CGFloat
        if compactHeight {
            rowHeight = spec.landscapePhoneRowHeight
        } else {
            switch style {
            case .wide, .split:
                let units = KeyboardLayout.units(style: style, splitGap: splitGap(forWidth: width, device: device))
                let unit = width / units
                let tallest = device == .pad ? spec.padWideRowHeightMax : spec.wideRowHeightMax
                rowHeight = min(max(unit * spec.wideRowHeightPerUnit, spec.wideRowHeightMin), tallest)
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
        builtSplitGap = style == .split ? Self.splitGap(forWidth: bounds.width) : nil
        layout = KeyboardLayout.make(
            style: style, layer: currentLayer, showsGlobe: showsGlobe, splitGap: builtSplitGap)
        rows = layout.rows.map { row in
            row.map { key in
                let keyView = KeyView(key: key)
                // The empty middle and the place of the prediction strip are no keys.
                keyView.isHidden = key.kind == .gap || key.kind == .predictionStrip || key.kind == .typingSpeed
                addSubview(keyView)
                return keyView
            }
        }
        bringSubviewToFront(typingSpeedView)
        bringSubviewToFront(predictionStrip)
        bringSubviewToFront(globeButton)
        bringSubviewToFront(candidateBar)
        refreshLabels()
        setNeedsLayout()
    }

    private func refreshLabels() {
        for keyView in rows.joined() {
            keyView.apply(display(for: keyView.key.kind))
        }
    }

    private func display(for kind: KeyKind) -> KeyDisplay {
        let letterSize: CGFloat = style == .compact ? 23 : 24
        let wordSize: CGFloat = 16
        switch kind {
        case .character(let character):
            return KeyDisplay(primary: label(characterText(character)), primaryFontSize: letterSize)
        case .dual(let base, let shifted):
            return KeyDisplay(primary: label(base), secondary: label(shifted), primaryFontSize: 19)
        case .slide(let letter, let slideCharacter):
            return KeyDisplay(
                primary: characterText(letter), slideCharacter: label(slideCharacter), primaryFontSize: letterSize)
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
            return KeyDisplay(
                symbolName: KeyboardTextLogic.returnKeySymbol(for: returnKeyType),
                performsAction: KeyboardTextLogic.returnKeyPerformsAction(for: returnKeyType))
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
            return KeyDisplay(imageName: "select-all", emphasized: selectAllActive)
        case .forwardDelete:
            return KeyDisplay(symbolName: "delete.right")
        case .gap, .predictionStrip, .typingSpeed:
            return KeyDisplay()
        case .language:
            return KeyDisplay(styledPrimary: Self.languageKeyText(chineseActive: chineseActive))
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
            case .symbols: title = style == .compact ? "123" : ".?123"
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
        // On an iPad the empty middle of the split layout depends on the width, so a new width
        // can need new keys although the style stays. On an iPhone the middle is always nil.
        let wantedGap = wantedStyle == .split ? Self.splitGap(forWidth: bounds.width) : nil
        if wantedStyle != style || wantedGap != builtSplitGap {
            style = wantedStyle
            rebuild()
        }
        guard let metrics = metrics() else { return }
        let spec = Self.spec
        let gapY = style == .compact ? spec.gapYCompact : spec.gapYWide
        globeButton.isHidden = true
        let shortcutButtons = Self.shortcutButtonsWidth(style: style)
        candidateBar.frame = CGRect(
            x: metrics.originX + shortcutButtons, y: metrics.rowEdges[0],
            width: metrics.width - shortcutButtons, height: metrics.rowEdges[1] - metrics.rowEdges[0]
        ).insetBy(dx: spec.gapX + 4, dy: gapY)
        var stripCell: CGRect?
        var speedCell: CGRect?
        for (rowIndex, row) in rows.enumerated() {
            let rowWeight = row.reduce(0) { $0 + $1.key.weight }
            let rowInset = rowIndex == rows.count - 1 ? spec.bottomRowCornerInset : 0
            let unit = (metrics.width - rowInset * 2) / layout.units
            var x = metrics.originX + rowInset + (layout.units - rowWeight) / 2 * unit
            let y = metrics.rowEdges[rowIndex]
            let height = metrics.rowEdges[rowIndex + 1] - y
            var cells: [CGRect] = []
            for keyView in row {
                let width = keyView.key.weight * unit
                cells.append(CGRect(x: x, y: y, width: width, height: height))
                x += width
            }
            if rowIndex == 0 {
                // The first row leaves the corner that the iPad's own buttons cover.
                let leftGroup = row.firstIndex { $0.key.kind == .gap } ?? row.count
                cells = Self.cells(cells, leftGroupCount: leftGroup, movedRightBy: shortcutButtons)
            }
            for (keyView, cell) in zip(row, cells) {
                keyView.hitFrame = cell
                keyView.frame = cell.insetBy(dx: spec.gapX, dy: gapY)
                if keyView.key.kind == .predictionStrip {
                    stripCell = cell
                }
                if keyView.key.kind == .typingSpeed {
                    speedCell = cell
                }
                if keyView.key.kind == .globe {
                    globeButton.frame = cell
                    globeButton.isHidden = false
                }
            }
        }
        // The strip takes its cell and the keyboard's edge above it, so a touch a little above
        // the top row still reaches an entry. A layout without the strip's place hides the strip.
        if let stripCell {
            predictionStrip.frame = CGRect(x: stripCell.minX, y: 0, width: stripCell.width, height: stripCell.maxY)
            predictionStrip.sideInset = spec.gapX
            predictionStrip.topInset = stripCell.minY
            predictionStrip.rowInset = gapY
            // The candidate row takes the drawn part of the strip's cell, so Select All, Cut,
            // Copy and Paste stay in view beside it.
            candidateBar.frame = stripCell.insetBy(dx: spec.gapX, dy: gapY)
        }
        predictionStrip.isHidden = stripCell == nil
        // The typing speed takes its cell and the keyboard's edge above it, as the strip does.
        if let speedCell {
            typingSpeedView.frame = CGRect(x: speedCell.minX, y: 0, width: speedCell.width, height: speedCell.maxY)
            typingSpeedView.topInset = speedCell.minY
        }
        typingSpeedView.isHidden = speedCell == nil
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
        let row = rows[rowIndex]
        // A touch in the cell of the prediction strip belongs to the strip. The key beside the
        // strip is Select All or Cut, so such a touch never goes to the nearest key.
        if let strip = row.first(where: { $0.key.kind == .predictionStrip }),
            point.x >= strip.hitFrame.minX, point.x < strip.hitFrame.maxX {
            return nil
        }
        // The typing speed is no key. A touch in its cell presses no key, so a finger that
        // misses Select All does not press it by the rule of the nearest key.
        if let speed = row.first(where: { $0.key.kind == .typingSpeed }),
            point.x >= speed.hitFrame.minX, point.x < speed.hitFrame.maxX {
            return nil
        }
        // A touch in the empty middle of the split layout goes to the nearest real key.
        return row.filter { $0.key.kind != .gap && $0.key.kind != .predictionStrip && $0.key.kind != .typingSpeed }
            .min { distance($0) < distance($1) }
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
            if candidateRowTakesTouch(at: point, time: touch.timestamp) { continue }
            guard let keyView = keyView(at: point) else { continue }
            let state = TouchState(keyView: keyView)
            state.startPoint = point
            state.latestX = point.x
            activeTouches[touch] = state
            keyView.isHighlighted = true
            keyView.showRipple(at: keyView.convert(point, from: self))
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
            switch state.keyView.key.kind {
            case .dual:
                updateAlternate(state, at: point)
                if state.alternateActive { continue }
            case .slide:
                // `SlideGesture` holds the rule. Only a move that is not vertical goes on to
                // the code below, which moves the touch to the key under the finger.
                guard let metrics = metrics() else { continue }
                let step = SlideGesture.step(
                    selected: state.alternateActive, dx: point.x - state.startPoint.x,
                    dy: point.y - state.startPoint.y, rowHeight: metrics.rowHeight)
                if (step == .slideCharacter) != state.alternateActive {
                    setAlternate(state, active: step == .slideCharacter)
                }
                if step != .letterOrOtherKey { continue }
            default:
                break
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

    // MARK: Long press and slide

    /// Seconds a finger rests on a key before the long press starts.
    private static let holdDelay: TimeInterval = 0.3

    private func startHoldTimer(_ state: TouchState) {
        let timer = Timer(
            timeInterval: Self.holdDelay, target: self, selector: #selector(holdTimerFired(_:)),
            userInfo: state, repeats: false)
        // The common modes include the mode that the run loop uses while a finger moves, so the
        // long press also starts when the finger does not rest fully still.
        RunLoop.main.add(timer, forMode: .common)
        state.holdTimer = timer
    }

    /// A finger held for 0.3 seconds selects the shifted character on a key with two characters,
    /// and turns the keyboard into a cursor trackpad on the space bar. A letter key with a slide
    /// character has no long press, so a slow press on a letter never types a symbol.
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

    /// A slide up or down on a key with two characters selects the shifted character.
    /// A slide back to the start returns to the base character.
    private func updateAlternate(_ state: TouchState, at point: CGPoint) {
        guard let metrics = metrics() else { return }
        let dx = point.x - state.startPoint.x
        let dy = point.y - state.startPoint.y
        let threshold = max(14, metrics.rowHeight * 0.35)
        if !state.alternateActive {
            let frame = state.keyView.hitFrame
            let leftKey = (point.y < frame.minY || point.y > frame.maxY) && abs(dy) > 8
            if abs(dx) < abs(dy), abs(dy) > threshold || leftKey {
                setAlternate(state, active: true)
            }
        } else if !state.alternateFromHold, abs(dy) < threshold / 2 {
            setAlternate(state, active: false)
        }
    }

    private func setAlternate(_ state: TouchState, active: Bool) {
        state.alternateActive = active
        if !active {
            state.alternateFromHold = false
        }
        guard let alternate = state.keyView.key.kind.alternateCharacter else { return }
        if active {
            state.holdTimer?.invalidate()
            state.holdTimer = nil
            state.keyView.apply(KeyDisplay(primary: label(alternate), primaryFontSize: 26))
        } else {
            state.keyView.apply(display(for: state.keyView.key.kind))
        }
    }

    /// Types the alternate character of a key. The shift state stays as it is: the owner sets
    /// it again after each text change, so an automatic shift is still on for the next letter
    /// when the text before the cursor still asks for a capital.
    private func performAlternate(_ kind: KeyKind) {
        guard let alternate = kind.alternateCharacter else { return }
        lastShiftTapTime = 0
        delegate?.keyboardView(self, insert: alternate)
    }

    // MARK: Actions

    private func perform(_ kind: KeyKind) {
        // Any other key between two shift taps ends the double-tap window for caps lock.
        lastShiftTapTime = 0
        switch kind {
        case .character(let character), .slide(let character, _):
            // Shift, in each of its states, changes the case of a letter with a slide character
            // and never selects the slide character.
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
        case .language:
            delegate?.keyboardView(self, edit: .toggleLanguage)
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
        case .shift, .capsLock, .globe, .gap, .predictionStrip, .typingSpeed:
            // Shift and caps lock act on finger down. The globe button handles the globe key.
            // The prediction strip handles the touches in its own place.
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
