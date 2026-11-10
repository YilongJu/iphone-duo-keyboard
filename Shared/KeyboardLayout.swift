import UIKit

/// The set of keys on screen. `letters` is the main layer, `symbols` is the layer behind the
/// ".?123" key, and `more` is the layer behind the "#+=" key on the symbols layer.
enum KeyboardLayer {
    case letters
    case symbols
    case more
}

/// `compact` is the phone-width layout (10 key units per row).
/// `wide` is the iPad-style layout (14.5 key units per row) for the unfolded display.
/// The devices whose keyboards differ. An iPhone, the iPhone Duo included, chooses its layout
/// from the keyboard's width alone. An iPad chooses by width and by the screen's orientation.
enum KeyboardDevice {
    case phone
    case pad

    /// The device this process runs on.
    static var current: KeyboardDevice {
        UIDevice.current.userInterfaceIdiom == .pad ? .pad : .phone
    }

    /// True when the screen is wider than it is high. Only the iPad rules read this value. On an
    /// iPhone Duo `UIScreen.main` reports the outer display, so the iPhone rules never use it.
    static var screenIsLandscape: Bool {
        let size = UIScreen.main.bounds.size
        return size.width > size.height
    }
}

/// `split` is the wide layout cut into a left half and a right half, with an empty middle.
/// The open phone in landscape uses the split layout, so each thumb reaches its half.
enum LayoutStyle {
    case compact
    case wide
    case split
}

enum ShiftState {
    case off
    case on
    case locked
}

/// An editing action that the owner of the keyboard carries out on the text field.
enum EditCommand {
    case toggleLanguage
    case selectAll
    case deleteForward
    case cut
    case copy
    case paste
    case lineStart
    case lineEnd
    case lineUp
    case lineDown
}

enum KeyKind: Equatable {
    /// One character. Letters are stored in lower case and the shift state decides the case.
    case character(String)
    /// A key with a base character and a shifted character, as on a hardware keyboard.
    case dual(String, String)
    case space
    case backspace
    case shift
    case capsLock
    case tab
    case returnKey
    case globe
    case dismiss
    case cursorLeft
    case cursorRight
    case cursorUp
    case cursorDown
    case home
    case end
    case selectAll
    case forwardDelete
    case cut
    case copy
    case paste
    /// The empty middle of the split layout. The view does not draw this key.
    case gap
    /// Switches between English and Simplified Chinese (Pinyin).
    case language
    case switchLayer(KeyboardLayer)

    /// Text keys commit on finger lift, and a finger can slide between them before lifting.
    var isTextKey: Bool {
        switch self {
        case .character, .dual, .space: return true
        default: return false
        }
    }

    /// Repeating keys act on finger down and repeat while the finger stays down.
    var repeats: Bool {
        switch self {
        case .backspace, .forwardDelete, .cursorLeft, .cursorRight, .cursorUp, .cursorDown: return true
        default: return false
        }
    }

    /// Function keys get the darker key color.
    var isFunctionKey: Bool {
        switch self {
        case .character, .dual, .space: return false
        default: return true
        }
    }

    /// The names that `keyboard-layout.json` uses in a key's "f" field.
    static func function(named name: String) -> KeyKind? {
        switch name {
        case "space": return .space
        case "backspace": return .backspace
        case "shift": return .shift
        case "capsLock": return .capsLock
        case "tab": return .tab
        case "return": return .returnKey
        case "globe": return .globe
        case "dismiss": return .dismiss
        case "left": return .cursorLeft
        case "right": return .cursorRight
        case "up": return .cursorUp
        case "down": return .cursorDown
        case "home": return .home
        case "end": return .end
        case "selectAll": return .selectAll
        case "forwardDelete": return .forwardDelete
        case "cut": return .cut
        case "copy": return .copy
        case "paste": return .paste
        case "language": return .language
        case "symbols": return .switchLayer(.symbols)
        case "letters": return .switchLayer(.letters)
        case "more": return .switchLayer(.more)
        default: return nil
        }
    }
}

/// One key. In `keyboard-layout.json` a key takes one of four forms:
/// `"a"` for a character, `["1", "!"]` for a base and a shifted character,
/// `{"c": "_", "w": 0.85}` for a character with a width, and `{"f": "shift", "w": 2.25}` for a function key.
struct Key: Decodable {
    let kind: KeyKind
    /// Width in key units. A letter key is 1 unit.
    let weight: CGFloat

    init(_ kind: KeyKind, _ weight: CGFloat = 1) {
        self.kind = kind
        self.weight = weight
    }

    private struct ObjectForm: Decodable {
        let c: String?
        let f: String?
        let w: CGFloat?
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let character = try? container.decode(String.self) {
            self.init(.character(character))
            return
        }
        if let pair = try? container.decode([String].self) {
            guard pair.count == 2 else {
                throw DecodingError.dataCorruptedError(
                    in: container, debugDescription: "A two-character key needs exactly two strings")
            }
            self.init(.dual(pair[0], pair[1]))
            return
        }
        let object = try container.decode(ObjectForm.self)
        if let character = object.c {
            self.init(.character(character), object.w ?? 1)
        } else if let name = object.f, let kind = KeyKind.function(named: name) {
            self.init(kind, object.w ?? 1)
        } else {
            throw DecodingError.dataCorruptedError(
                in: container, debugDescription: "Unknown key: \(object.f ?? "missing f and c")")
        }
    }
}

/// The content of `keyboard-layout.json`. The Swift keyboard and the HTML preview in
/// `docs/keyboard-preview.html` both read this one file.
struct KeyboardSpec: Decodable {
    struct Metrics: Decodable {
        let wideMinimumWidth: CGFloat
        /// The split layout appears at this width in points and above.
        let splitMinimumWidth: CGFloat
        /// Width of the empty middle of the split layout, in key units.
        let splitGapUnits: CGFloat
        let topPadding: CGFloat
        let bottomPadding: CGFloat
        let horizontalPadding: CGFloat
        /// Extra space left and right of the bottom row. The display's rounded corners cover the
        /// keyboard's bottom corners, and this space keeps the two corner keys fully visible.
        let bottomRowCornerInset: CGFloat
        let gapX: CGFloat
        let gapYWide: CGFloat
        let gapYCompact: CGFloat
        let wideRowHeightPerUnit: CGFloat
        let wideRowHeightMin: CGFloat
        let wideRowHeightMax: CGFloat
        let compactRowHeight: CGFloat
        let landscapePhoneRowHeight: CGFloat
        /// The tallest letter row of the wide and split layouts on an iPad, in points.
        let padWideRowHeightMax: CGFloat
        /// The widest letter key of the split layout on an iPad, in points. On a wide iPad the
        /// empty middle grows, so the keys of each half stay within reach of a thumb.
        let padSplitMaxKeyWidth: CGFloat
    }

    struct Row: Decodable {
        /// Row height as a fraction of a letter row.
        let height: CGFloat
        /// Count of keys in the left half of the split layout. A space bar at this place is
        /// cut in two, so each half gets a space bar. Only the wide rows carry this value.
        let split: Int?
        let keys: [Key]
    }

    struct Style: Decodable {
        let units: CGFloat
        let letters: [Row]
        let symbols: [Row]
        let more: [Row]

        func rows(for layer: KeyboardLayer) -> [Row] {
            switch layer {
            case .letters: return letters
            case .symbols: return symbols
            case .more: return more
            }
        }
    }

    let metrics: Metrics
    let wide: Style
    let compact: Style

    /// The keyboard cannot work without its layout file, so a missing or invalid file stops the process.
    static let shared: KeyboardSpec = {
        guard let url = Bundle(for: KeyboardView.self).url(forResource: "keyboard-layout", withExtension: "json")
        else {
            fatalError("keyboard-layout.json is missing from the bundle")
        }
        do {
            return try JSONDecoder().decode(KeyboardSpec.self, from: Data(contentsOf: url))
        } catch {
            fatalError("keyboard-layout.json is invalid: \(error)")
        }
    }()

    func style(_ style: LayoutStyle) -> Style {
        switch style {
        case .wide, .split: return wide
        case .compact: return compact
        }
    }
}

struct KeyboardLayout {
    let rows: [[Key]]
    /// Height of each row as a fraction of a letter row.
    let rowHeights: [CGFloat]
    /// Width of the widest row in key units. Narrower rows are centered.
    let units: CGFloat

    /// `splitGap` is the width of the split layout's empty middle in key units. Without a
    /// value the layout file's width applies, as on the iPhone.
    static func make(
        style: LayoutStyle, layer: KeyboardLayer, showsGlobe: Bool, splitGap: CGFloat? = nil
    ) -> KeyboardLayout {
        let styleSpec = KeyboardSpec.shared.style(style)
        let rowSpecs = styleSpec.rows(for: layer)
        let gap = splitGap ?? KeyboardSpec.shared.metrics.splitGapUnits
        let rows = rowSpecs.map { row -> [Key] in
            let keys = style == .split ? splitRow(row, gap: gap) : row.keys
            return showsGlobe ? keys : withoutGlobe(keys)
        }
        let units = style == .split ? styleSpec.units + gap : styleSpec.units
        return KeyboardLayout(rows: rows, rowHeights: rowSpecs.map { $0.height }, units: units)
    }

    /// Width of a style's widest row in key units.
    static func units(style: LayoutStyle, splitGap: CGFloat? = nil) -> CGFloat {
        let spec = KeyboardSpec.shared
        return style == .split
            ? spec.wide.units + (splitGap ?? spec.metrics.splitGapUnits) : spec.style(style).units
    }

    /// Width of the split layout's empty middle on an iPad of the given keyboard width, in key
    /// units. The middle takes the width that the keys do not need at their widest allowed
    /// size, and it is never narrower than the middle of the layout file.
    static func padSplitGap(forWidth width: CGFloat) -> CGFloat {
        let spec = KeyboardSpec.shared
        return max(spec.metrics.splitGapUnits, width / spec.metrics.padSplitMaxKeyWidth - spec.wide.units)
    }

    /// Puts the empty middle into a row at the row's split point.
    private static func splitRow(_ row: KeyboardSpec.Row, gap: CGFloat) -> [Key] {
        guard let split = row.split, row.keys.indices.contains(split) else {
            fatalError("A wide row in keyboard-layout.json needs a valid split value")
        }
        var keys = Array(row.keys[..<split])
        let middle = row.keys[split]
        if middle.kind == .space {
            // The two space bars meet the middle of the row from both sides.
            let total = row.keys.reduce(0) { $0 + $1.weight }
            let before = keys.reduce(0) { $0 + $1.weight }
            let left = min(max(total / 2 - before, 1), middle.weight - 1)
            keys += [Key(.space, left), Key(.gap, gap), Key(.space, middle.weight - left)]
        } else {
            keys += [Key(.gap, gap), middle]
        }
        return keys + row.keys[(split + 1)...]
    }

    /// Sum of the row heights of a style, in letter rows.
    static func totalRowHeight(style: LayoutStyle) -> CGFloat {
        KeyboardSpec.shared.style(style).letters.reduce(0) { $0 + $1.height }
    }

    /// Removes the globe key and gives its width to the space bar in the same row.
    private static func withoutGlobe(_ keys: [Key]) -> [Key] {
        guard let globe = keys.first(where: { $0.kind == .globe }) else { return keys }
        var gaveGlobeWidth = false
        return keys.compactMap { key in
            switch key.kind {
            case .globe: return nil
            // In the split layout the globe sits in the left half, so the first space bar grows.
            case .space where !gaveGlobeWidth:
                gaveGlobeWidth = true
                return Key(.space, key.weight + globe.weight)
            default: return key
            }
        }
    }
}
