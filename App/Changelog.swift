import UIKit

/// One build of docs/changelog.md: its number, the line with its commit and upload time, and
/// its text as blocks.
struct ChangelogEntry: Equatable {
    enum Block: Equatable {
        /// A line in bold alone, as "What you notice".
        case heading(String)
        case bullet(String)
        case paragraph(String)
        /// The rows of a table, the header row first. Each row holds its cells.
        case table([[String]])
    }

    let build: Int
    /// The line "Commit ..., uploaded ...", or nil for an entry that does not hold it yet.
    var detail: String?
    var blocks: [Block] = []
}

/// Reads docs/changelog.md, which ships in the app, for the page "What's new".
enum Changelog {
    /// The entries of the changelog of the app bundle, the newest build first. The file ships
    /// with the app, so a missing file stops the process.
    static func bundled() -> [ChangelogEntry] {
        guard let url = Bundle(for: ChangelogViewController.self).url(forResource: "changelog", withExtension: "md"),
            let text = try? String(contentsOf: url, encoding: .utf8)
        else { fatalError("changelog.md is missing from the bundle") }
        return entries(of: text)
    }

    /// The build number of the installed app, or nil for a build without a number of its own.
    static var installedBuild: Int? {
        (Bundle(for: ChangelogViewController.self).object(forInfoDictionaryKey: "CFBundleVersion") as? String).flatMap(Int.init)
    }

    /// The entries of a changelog text in the form of docs/changelog.md. An entry starts with
    /// a line "## Build N". The text before the first entry describes the file and is left out.
    /// - A line "Commit ..." is the entry's detail.
    /// - A line that is all bold, as "**What you notice**", is a heading.
    /// - A line that starts with "- " starts a bullet, and the lines after it belong to it.
    /// - Lines that start with "|" are the rows of a table. The row of dashes is left out.
    /// - Other lines form a paragraph. An empty line ends a bullet or a paragraph.
    static func entries(of text: String) -> [ChangelogEntry] {
        var entries: [ChangelogEntry] = []
        /// True while the next plain line continues the last bullet or paragraph.
        var continues = false
        for rawLine in text.split(separator: "\n", omittingEmptySubsequences: false) {
            let line = rawLine.trimmingCharacters(in: .whitespaces)
            if line.hasPrefix("## Build "), let build = Int(line.dropFirst("## Build ".count)) {
                entries.append(ChangelogEntry(build: build))
                continues = false
                continue
            }
            guard !entries.isEmpty else { continue }
            let last = entries.count - 1
            if line.isEmpty {
                continues = false
            } else if line.hasPrefix("Commit "), entries[last].detail == nil, entries[last].blocks.isEmpty {
                entries[last].detail = line
            } else if line.hasPrefix("**"), line.hasSuffix("**"), line.count > 4, !line.dropFirst(2).dropLast(2).contains("**") {
                entries[last].blocks.append(.heading(String(line.dropFirst(2).dropLast(2))))
                continues = false
            } else if line.hasPrefix("- ") {
                entries[last].blocks.append(.bullet(String(line.dropFirst(2))))
                continues = true
            } else if line.hasPrefix("|") {
                let cells = line.split(separator: "|").map { $0.trimmingCharacters(in: .whitespaces) }
                continues = false
                // The row of dashes only separates the header row from the others.
                if cells.allSatisfy({ !$0.isEmpty && $0.allSatisfy { $0 == "-" || $0 == ":" } }) { continue }
                if case .table(let rows) = entries[last].blocks.last {
                    entries[last].blocks[entries[last].blocks.count - 1] = .table(rows + [cells])
                } else {
                    entries[last].blocks.append(.table([cells]))
                }
            } else if continues, case .bullet(let text) = entries[last].blocks.last {
                entries[last].blocks[entries[last].blocks.count - 1] = .bullet(text + " " + line)
            } else if continues, case .paragraph(let text) = entries[last].blocks.last {
                entries[last].blocks[entries[last].blocks.count - 1] = .paragraph(text + " " + line)
            } else {
                entries[last].blocks.append(.paragraph(line))
                continues = true
            }
        }
        return entries
    }

    /// One span of a line: plain text, bold text between two pairs of stars, or code between
    /// two backticks. A link "[text](address)" gives its text.
    enum Span: Equatable {
        case plain(String)
        case bold(String)
        case code(String)
    }

    static func spans(of line: String) -> [Span] {
        var spans: [Span] = []
        var plain = ""
        var rest = Substring(line)
        func flush() {
            if !plain.isEmpty { spans.append(.plain(plain)) }
            plain = ""
        }
        while let first = rest.first {
            if rest.hasPrefix("**"), let end = rest.dropFirst(2).range(of: "**") {
                flush()
                spans.append(.bold(String(rest.dropFirst(2)[..<end.lowerBound])))
                rest = rest[end.upperBound...]
            } else if first == "`", let end = rest.dropFirst().firstIndex(of: "`") {
                flush()
                spans.append(.code(String(rest.dropFirst()[..<end])))
                rest = rest[rest.index(after: end)...]
            } else if first == "[", let close = rest.range(of: "]("), let end = rest[close.upperBound...].firstIndex(of: ")") {
                plain += rest[rest.index(after: rest.startIndex)..<close.lowerBound]
                rest = rest[rest.index(after: end)...]
            } else {
                plain.append(first)
                rest = rest.dropFirst()
            }
        }
        flush()
        return spans
    }
}

/// The page "What's new" of the app: the entries of the changelog, the newest build first. The
/// entry of the installed build carries a mark.
final class ChangelogViewController: UIViewController {
    private let textView = UITextView()
    private let entries: [ChangelogEntry]
    private let installedBuild: Int?

    init(entries: [ChangelogEntry] = Changelog.bundled(), installedBuild: Int? = Changelog.installedBuild) {
        self.entries = entries
        self.installedBuild = installedBuild
        super.init(nibName: nil, bundle: nil)
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("ChangelogViewController is built in code only")
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        title = "What's new"
        view.backgroundColor = .systemBackground
        navigationItem.rightBarButtonItem = UIBarButtonItem(
            systemItem: .done, primaryAction: UIAction { [weak self] _ in self?.dismiss(animated: true) })
        textView.isEditable = false
        textView.alwaysBounceVertical = true
        textView.textContainerInset = UIEdgeInsets(top: 16, left: 16, bottom: 24, right: 16)
        textView.attributedText = Self.text(of: entries, installedBuild: installedBuild)
        textView.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(textView)
        NSLayoutConstraint.activate([
            textView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            textView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            textView.topAnchor.constraint(equalTo: view.topAnchor),
            textView.bottomAnchor.constraint(equalTo: view.bottomAnchor),
        ])
    }

    /// The text of the page. The unit tests read its string.
    static func text(of entries: [ChangelogEntry], installedBuild: Int?) -> NSAttributedString {
        let body = UIFont.preferredFont(forTextStyle: .body)
        let bold = UIFont.systemFont(ofSize: body.pointSize, weight: .semibold)
        let code = UIFont.monospacedSystemFont(ofSize: body.pointSize * 0.9, weight: .regular)
        let title = UIFont.systemFont(ofSize: UIFont.preferredFont(forTextStyle: .title2).pointSize, weight: .bold)
        let small = UIFont.preferredFont(forTextStyle: .footnote)
        let result = NSMutableAttributedString()

        func style(spacingBefore: CGFloat = 0, indent: CGFloat = 0) -> NSParagraphStyle {
            let style = NSMutableParagraphStyle()
            style.paragraphSpacingBefore = spacingBefore
            style.paragraphSpacing = 4
            style.headIndent = indent
            style.tabStops = [NSTextTab(textAlignment: .left, location: indent)]
            return style
        }
        func add(_ text: String, font: UIFont, color: UIColor = .label, style paragraph: NSParagraphStyle) {
            result.append(NSAttributedString(
                string: text, attributes: [.font: font, .foregroundColor: color, .paragraphStyle: paragraph]))
        }
        func addLine(_ line: String, prefix: String = "", style paragraph: NSParagraphStyle, allBold: Bool = false) {
            if !prefix.isEmpty { add(prefix, font: body, style: paragraph) }
            for span in Changelog.spans(of: line) {
                switch span {
                case .plain(let text): add(text, font: allBold ? bold : body, style: paragraph)
                case .bold(let text): add(text, font: bold, style: paragraph)
                case .code(let text): add(text, font: code, color: .secondaryLabel, style: paragraph)
                }
            }
            add("\n", font: body, style: paragraph)
        }

        for (index, entry) in entries.enumerated() {
            let heading = style(spacingBefore: index == 0 ? 0 : 28)
            add("Build \(entry.build)", font: title, style: heading)
            if entry.build == installedBuild {
                add("  installed", font: small, color: .tintColor, style: heading)
            }
            add("\n", font: title, style: heading)
            if let detail = entry.detail {
                var line = ""
                for span in Changelog.spans(of: detail) {
                    switch span {
                    case .plain(let text), .bold(let text), .code(let text): line += text
                    }
                }
                add(line + "\n", font: small, color: .secondaryLabel, style: style())
            }
            for block in entry.blocks {
                switch block {
                case .heading(let text):
                    add(text + "\n", font: bold, style: style(spacingBefore: 12))
                case .bullet(let text):
                    addLine(text, prefix: "\u{2022}\t", style: style(indent: 16))
                case .paragraph(let text):
                    addLine(text, style: style(spacingBefore: 4))
                case .table(let rows):
                    for (row, cells) in rows.enumerated() {
                        addLine(cells.joined(separator: "  \u{00B7}  "), style: style(indent: 16), allBold: row == 0)
                    }
                }
            }
        }
        return result
    }
}
