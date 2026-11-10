import SwiftUI
import UIKit

/// Host app for the stock-keyboard measurement. The app shows one text view with the default
/// text input traits, so the system keyboard treats the text view like any other text field.
///
/// The UI test sets two environment variables at launch.
/// - `EVAL_CONTEXTS_JSON`: a JSON array with the context string of each case, in typing order.
/// - `EVAL_TASK`: `english` or `pinyin`. The task decides which text changes count as key arrivals.
/// `EVAL_INLINE_PREDICTION` is optional. The value `no` turns inline predictions off in the text view.
/// `EVAL_CONTROL` is optional. The value `yes` turns every correction of the text view off, so
/// the text view holds exactly the characters of the keys that arrived.
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
    /// Number of times since the case was loaded that the text without the marked text gained a
    /// space at its end. Each space tap of the English keyboard adds one.
    let e: Int
    /// The longest time between two key arrivals since the case was loaded, in milliseconds.
    /// A key arrival is a moment the typed text grew: for English the text without the marked
    /// text, and for Pinyin the letters a to z of the text.
    let g: Int
    /// Every state of the text since the case was loaded, oldest first. Each entry is the text
    /// with the marked text between the two marks of `FieldViewController.markedBrackets`.
    let h: [String]
    /// The time of each entry of `h`, in milliseconds since the case was loaded.
    let ht: [Int]
}

/// The only screen. The "Next case" button loads the context of the next case into the text
/// view and puts the cursor at the end. The UI test then taps the keys of the software keyboard.
final class FieldViewController: UIViewController, UITextViewDelegate {
    /// The marks around marked text in a history entry: the white square brackets U+27E6 and U+27E7.
    static let markedBrackets = (open: "\u{27E6}", close: "\u{27E7}")
    /// Two growths of the typed text closer than this many milliseconds come from one tap, as
    /// when the keyboard replaces a word and then adds the space.
    static let sameTapMilliseconds = 20

    private let statusLabel = UILabel()
    private let nextButton = UIButton(type: .system)
    private let field = UITextView()
    private var contexts: [String] = []
    private var countsPinyinLetters = false
    private var caseIndex = -1
    private var history: [String] = []
    private var historyTimes: [Int] = []
    private var loadTime = Date()
    private var spaceArrivals = 0
    private var lastCommitted = ""
    private var typedLength = 0
    private var lastKeyArrival: Date?
    private var longestKeyGap = 0

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .systemBackground

        let environment = ProcessInfo.processInfo.environment
        guard let json = environment["EVAL_CONTEXTS_JSON"],
              let decoded = try? JSONDecoder().decode([String].self, from: Data(json.utf8)) else {
            fatalError("EVAL_CONTEXTS_JSON must hold a JSON array with one context string per case")
        }
        contexts = decoded
        switch environment["EVAL_TASK"] {
        case "english": countsPinyinLetters = false
        case "pinyin": countsPinyinLetters = true
        default: fatalError("EVAL_TASK must be english or pinyin")
        }

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

        // In a measurement run the text view keeps every text input trait at its default:
        // autocorrection, spell checking, capitalization of sentences and smart punctuation
        // follow the system settings.
        field.font = .systemFont(ofSize: 20)
        field.layer.borderWidth = 1
        field.layer.borderColor = UIColor.separator.cgColor
        field.accessibilityIdentifier = "evalField"
        field.delegate = self
        field.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(field)
        if environment["EVAL_INLINE_PREDICTION"] == "no" {
            field.inlinePredictionType = .no
        }
        if environment["EVAL_CONTROL"] == "yes" {
            // The control run: the keyboard must not change a typed character.
            field.autocorrectionType = .no
            field.spellCheckingType = .no
            field.autocapitalizationType = .none
            field.inlinePredictionType = .no
            field.smartQuotesType = .no
            field.smartDashesType = .no
            field.smartInsertDeleteType = .no
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
        historyTimes = []
        loadTime = Date()
        spaceArrivals = 0
        lastCommitted = field.text ?? ""
        typedLength = typedText(text: lastCommitted, committed: lastCommitted).count
        lastKeyArrival = nil
        longestKeyGap = 0
        updateStatus()
    }

    func textViewDidChange(_ textView: UITextView) {
        updateStatus()
    }

    func textViewDidChangeSelection(_ textView: UITextView) {
        updateStatus()
    }

    /// The text whose growth marks a key arrival.
    private func typedText(text: String, committed: String) -> String {
        if countsPinyinLetters {
            return text.filter({ $0.isASCII && $0.isLetter })
        }
        return committed
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
        let now = Date()
        if committed.hasSuffix(" ") && !lastCommitted.hasSuffix(" ") {
            spaceArrivals += 1
        }
        lastCommitted = committed
        let newTypedLength = typedText(text: text as String, committed: committed).count
        if newTypedLength > typedLength {
            if let last = lastKeyArrival {
                let gap = Int((now.timeIntervalSince(last) * 1000).rounded())
                if gap >= FieldViewController.sameTapMilliseconds {
                    longestKeyGap = max(longestKeyGap, gap)
                    lastKeyArrival = now
                }
            } else {
                lastKeyArrival = now
            }
        }
        typedLength = newTypedLength
        if history.last != annotated {
            history.append(annotated)
            historyTimes.append(Int((now.timeIntervalSince(loadTime) * 1000).rounded()))
        }
        let status = FieldStatus(
            i: caseIndex, m: field.markedTextRange != nil, t: text as String, c: committed,
            e: spaceArrivals, g: longestKeyGap, h: history, ht: historyTimes)
        guard let data = try? JSONEncoder().encode(status) else {
            fatalError("the field status did not encode as JSON")
        }
        statusLabel.text = String(decoding: data, as: UTF8.self)
    }
}
