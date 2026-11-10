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
enum LayoutStyle {
    case compact
    case wide
}

enum ShiftState {
    case off
    case on
    case locked
}

/// An editing action that the owner of the keyboard carries out on the text field.
enum EditCommand {
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
    }

    struct Row: Decodable {
        /// Row height as a fraction of a letter row.
        let height: CGFloat
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
        case .wide: return wide
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

    static func make(style: LayoutStyle, layer: KeyboardLayer, showsGlobe: Bool) -> KeyboardLayout {
        let styleSpec = KeyboardSpec.shared.style(style)
        let rowSpecs = styleSpec.rows(for: layer)
        let rows = rowSpecs.map { row in showsGlobe ? row.keys : withoutGlobe(row.keys) }
        return KeyboardLayout(rows: rows, rowHeights: rowSpecs.map { $0.height }, units: styleSpec.units)
    }

    /// Sum of the row heights of a style, in letter rows.
    static func totalRowHeight(style: LayoutStyle) -> CGFloat {
        KeyboardSpec.shared.style(style).letters.reduce(0) { $0 + $1.height }
    }

    /// Removes the globe key and gives its width to the space bar in the same row.
    private static func withoutGlobe(_ keys: [Key]) -> [Key] {
        guard let globe = keys.first(where: { $0.kind == .globe }) else { return keys }
        return keys.compactMap { key in
            switch key.kind {
            case .globe: return nil
            case .space: return Key(.space, key.weight + globe.weight)
            default: return key
            }
        }
    }
}
