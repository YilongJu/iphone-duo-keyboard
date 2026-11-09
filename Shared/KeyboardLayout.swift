import UIKit

/// The set of keys on screen. `letters` is the main layer, `symbols` is the layer behind the ".?123" key.
enum KeyboardLayer {
    case letters
    case symbols
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
        case .backspace, .cursorLeft, .cursorRight: return true
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
}

struct Key {
    let kind: KeyKind
    /// Width in key units. A letter key is 1 unit.
    let weight: CGFloat

    init(_ kind: KeyKind, _ weight: CGFloat = 1) {
        self.kind = kind
        self.weight = weight
    }
}

struct KeyboardLayout {
    let rows: [[Key]]
    /// Width of the widest row in key units. Narrower rows are centered.
    let units: CGFloat

    static let compactUnits: CGFloat = 10
    static let wideUnits: CGFloat = 14.5

    static func make(style: LayoutStyle, layer: KeyboardLayer, showsGlobe: Bool) -> KeyboardLayout {
        switch (style, layer) {
        case (.wide, .letters):
            return KeyboardLayout(rows: wideLetters(showsGlobe: showsGlobe), units: wideUnits)
        case (.wide, .symbols):
            return KeyboardLayout(rows: wideSymbols(showsGlobe: showsGlobe), units: wideUnits)
        case (.compact, .letters):
            return KeyboardLayout(rows: compactLetters(showsGlobe: showsGlobe), units: compactUnits)
        case (.compact, .symbols):
            return KeyboardLayout(rows: compactSymbols(showsGlobe: showsGlobe), units: compactUnits)
        }
    }

    private static func chars(_ text: String, weight: CGFloat = 1) -> [Key] {
        text.map { Key(.character(String($0)), weight) }
    }

    private static func duals(_ pairs: [(String, String)]) -> [Key] {
        pairs.map { Key(.dual($0.0, $0.1)) }
    }

    // MARK: Wide layout, 14.5 units per row

    private static func wideLetters(showsGlobe: Bool) -> [[Key]] {
        let numberRow = duals([
            ("`", "~"), ("1", "!"), ("2", "@"), ("3", "#"), ("4", "$"), ("5", "%"), ("6", "^"),
            ("7", "&"), ("8", "*"), ("9", "("), ("0", ")"), ("-", "_"), ("=", "+"),
        ]) + [Key(.backspace, 1.5)]
        let topRow = [Key(.tab, 1.5)] + chars("qwertyuiop") + duals([("[", "{"), ("]", "}"), ("\\", "|")])
        let homeRow = [Key(.capsLock, 1.75)] + chars("asdfghjkl") + duals([(";", ":"), ("'", "\"")])
            + [Key(.returnKey, 1.75)]
        let bottomRow = [Key(.shift, 2.25)] + chars("zxcvbnm") + duals([(",", "<"), (".", ">"), ("/", "?")])
            + [Key(.shift, 2.25)]
        return [numberRow, topRow, homeRow, bottomRow, wideControlRow(showsGlobe: showsGlobe, layerKey: .symbols)]
    }

    private static func wideSymbols(showsGlobe: Bool) -> [[Key]] {
        let currencyRow = chars("€£¥₩₹¢§°•…–×÷") + [Key(.backspace, 1.5)]
        let topRow = [Key(.tab, 1.5)] + chars("!@#$%^&*(){}|")
        let homeRow = [Key(.switchLayer(.letters), 1.75)] + chars("-_=+/\\:;'\"~") + [Key(.returnKey, 1.75)]
        let bottomRow = [Key(.switchLayer(.letters), 2.25)] + chars("<>[]?,.`¿¡") + [Key(.switchLayer(.letters), 2.25)]
        return [currencyRow, topRow, homeRow, bottomRow, wideControlRow(showsGlobe: showsGlobe, layerKey: .letters)]
    }

    private static func wideControlRow(showsGlobe: Bool, layerKey: KeyboardLayer) -> [Key] {
        var row: [Key] = []
        if showsGlobe {
            row.append(Key(.globe, 1.25))
        }
        row.append(Key(.switchLayer(layerKey), 1.25))
        row.append(Key(.cursorLeft, 1))
        row.append(Key(.space, showsGlobe ? 7.5 : 8.75))
        row.append(Key(.cursorRight, 1))
        row.append(Key(.switchLayer(layerKey), 1.25))
        row.append(Key(.dismiss, 1.25))
        return row
    }

    // MARK: Compact layout, 10 units per row

    private static func compactLetters(showsGlobe: Bool) -> [[Key]] {
        let bottomRow = [Key(.shift, 1.5)] + chars("zxcvbnm") + [Key(.backspace, 1.5)]
        return [
            chars("1234567890"),
            chars("qwertyuiop"),
            chars("asdfghjkl"),
            bottomRow,
            compactControlRow(showsGlobe: showsGlobe, layerKey: .symbols, extra: "."),
        ]
    }

    private static func compactSymbols(showsGlobe: Bool) -> [[Key]] {
        let bottomRow = chars("_\\|~<>.,?!", weight: 0.85) + [Key(.backspace, 1.5)]
        return [
            chars("1234567890"),
            chars("-/:;()$&@\""),
            chars("[]{}#%^*+="),
            bottomRow,
            compactControlRow(showsGlobe: showsGlobe, layerKey: .letters, extra: "'"),
        ]
    }

    private static func compactControlRow(showsGlobe: Bool, layerKey: KeyboardLayer, extra: String) -> [Key] {
        var row: [Key] = [Key(.switchLayer(layerKey), 1.25)]
        if showsGlobe {
            row.append(Key(.globe, 1.25))
        }
        row.append(Key(.space, showsGlobe ? 4 : 5.25))
        row.append(Key(.character(extra), 1))
        row.append(Key(.returnKey, 2.5))
        return row
    }
}
