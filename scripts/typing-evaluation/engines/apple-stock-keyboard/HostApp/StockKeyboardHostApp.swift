import SwiftUI
import UIKit

/// Host app for the stock-keyboard measurement. The app shows one text view with the default
/// text input traits, so the system keyboard treats the text view like any other text field.
@main
struct StockKeyboardHostApp: App {
    var body: some Scene {
        WindowGroup {
            FieldScreen()
                .ignoresSafeArea(.keyboard)
        }
    }
}

/// Wraps the UIKit screen for the SwiftUI app lifecycle.
struct FieldScreen: UIViewControllerRepresentable {
    func makeUIViewController(context: Context) -> FieldViewController {
        FieldViewController()
    }

    func updateUIViewController(_ controller: FieldViewController, context: Context) {}
}

/// The state of the text view, shown as JSON in the status label. The UI test reads the label.
struct FieldStatus: Codable {
    /// Index of the loaded case. The value is -1 before the first case.
    let i: Int
    /// True while the text view holds marked text. The Pinyin keyboard marks the letters before
    /// the person picks a candidate. The English keyboard marks an inline prediction, the gray
    /// text that the person has not accepted.
    let m: Bool
    /// The text of the text view, with the marked text.
    let t: String
    /// The text of the text view without the marked text.
    let c: String
    /// Every state of the text since the case was loaded, oldest first. Each entry is the text
    /// with the marked text between the two marks of `FieldViewController.markedBrackets`.
    let h: [String]
}

/// The only screen. The "Next case" button loads the context of the next case into the text
/// view and puts the cursor at the end. The UI test then taps the keys of the software keyboard.
final class FieldViewController: UIViewController, UITextViewDelegate {
    /// The marks around marked text in a history entry: the white square brackets U+27E6 and U+27E7.
    static let markedBrackets = (open: "\u{27E6}", close: "\u{27E7}")

    private let statusLabel = UILabel()
    private let nextButton = UIButton(type: .system)
    private let field = UITextView()
    private var contexts: [String] = []
    private var caseIndex = -1
    private var history: [String] = []

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .systemBackground

        let environment = ProcessInfo.processInfo.environment
        guard let json = environment["EVAL_CONTEXTS_JSON"],
              let decoded = try? JSONDecoder().decode([String].self, from: Data(json.utf8)) else {
            fatalError("EVAL_CONTEXTS_JSON must hold a JSON array with one context string per case")
        }
        contexts = decoded

        statusLabel.numberOfLines = 0
        statusLabel.font = .monospacedSystemFont(ofSize: 8, weight: .regular)
        statusLabel.accessibilityIdentifier = "evalStatus"
        statusLabel.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(statusLabel)

        nextButton.setTitle("Next case", for: .normal)
        nextButton.backgroundColor = .systemGray5
        nextButton.accessibilityIdentifier = "evalNext"
        nextButton.addTarget(self, action: #selector(loadNextCase), for: .touchUpInside)
        nextButton.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(nextButton)

        // The text view keeps every text input trait at its default: autocorrection, spell
        // checking, capitalization of sentences and smart punctuation follow the system settings.
        field.font = .systemFont(ofSize: 20)
        field.layer.borderWidth = 1
        field.layer.borderColor = UIColor.separator.cgColor
        field.accessibilityIdentifier = "evalField"
        field.delegate = self
        field.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(field)
        // A run that measures the keyboard without inline predictions sets this variable to "no".
        if environment["EVAL_INLINE_PREDICTION"] == "no" {
            field.inlinePredictionType = .no
        }

        let safeArea = view.safeAreaLayoutGuide
        NSLayoutConstraint.activate([
            statusLabel.topAnchor.constraint(equalTo: safeArea.topAnchor, constant: 4),
            statusLabel.leadingAnchor.constraint(equalTo: safeArea.leadingAnchor, constant: 12),
            statusLabel.trailingAnchor.constraint(equalTo: safeArea.trailingAnchor, constant: -12),
            statusLabel.heightAnchor.constraint(equalToConstant: 96),
            nextButton.topAnchor.constraint(equalTo: statusLabel.bottomAnchor, constant: 4),
            nextButton.leadingAnchor.constraint(equalTo: safeArea.leadingAnchor, constant: 12),
            nextButton.trailingAnchor.constraint(equalTo: safeArea.trailingAnchor, constant: -12),
            nextButton.heightAnchor.constraint(equalToConstant: 56),
            field.topAnchor.constraint(equalTo: nextButton.bottomAnchor, constant: 8),
            field.leadingAnchor.constraint(equalTo: safeArea.leadingAnchor, constant: 12),
            field.trailingAnchor.constraint(equalTo: safeArea.trailingAnchor, constant: -12),
            field.heightAnchor.constraint(equalToConstant: 150),
        ])
        updateStatus()
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        field.becomeFirstResponder()
    }

    @objc private func loadNextCase() {
        caseIndex += 1
        precondition(caseIndex < contexts.count, "the UI test asked for case \(caseIndex) of \(contexts.count)")
        field.unmarkText()
        let context = contexts[caseIndex]
        field.text = context.isEmpty ? "" : context + " "
        field.selectedRange = NSRange(location: (field.text as NSString).length, length: 0)
        if !field.isFirstResponder {
            field.becomeFirstResponder()
        }
        history = []
        updateStatus()
    }

    func textViewDidChange(_ textView: UITextView) {
        updateStatus()
    }

    func textViewDidChangeSelection(_ textView: UITextView) {
        updateStatus()
    }

    private func updateStatus() {
        let text = (field.text ?? "") as NSString
        var committed = text as String
        var annotated = text as String
        if let marked = field.markedTextRange {
            let start = field.offset(from: field.beginningOfDocument, to: marked.start)
            let range = NSRange(location: start, length: field.offset(from: marked.start, to: marked.end))
            let brackets = FieldViewController.markedBrackets
            committed = text.replacingCharacters(in: range, with: "")
            annotated = text.replacingCharacters(in: range, with: brackets.open + text.substring(with: range) + brackets.close)
        }
        if history.last != annotated {
            history.append(annotated)
        }
        let status = FieldStatus(i: caseIndex, m: field.markedTextRange != nil, t: text as String, c: committed, h: history)
        guard let data = try? JSONEncoder().encode(status) else {
            fatalError("the field status did not encode as JSON")
        }
        statusLabel.text = String(decoding: data, as: UTF8.self)
    }
}
