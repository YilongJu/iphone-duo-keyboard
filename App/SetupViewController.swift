import UIKit

/// The host app's only screen. The screen has four parts: setup steps, a field that uses the
/// system-selected keyboard, a field that always shows this app's keyboard, and the display
/// measurements that decide which layout appears.
final class SetupViewController: UIViewController, UITextViewDelegate {
    private let scrollView = UIScrollView()
    private let stack = UIStackView()
    private let diagnosticsLabel = UILabel()
    private let systemField = UITextView()
    private let previewField = UITextView()
    private let previewKeyboard = KeyboardView()
    private let previewContainer = UIInputView(frame: .zero, inputViewStyle: .keyboard)
    private lazy var previewDocument = TextViewDocument(textView: previewField)
    private lazy var textController = KeyboardTextController(
        keyboardView: previewKeyboard, document: previewDocument, spellChecker: EngineSpellChecker.bundled(),
        pinyinEngine: { PinyinEngine.bundled() })
    private var didAutoFocus = false

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .systemGroupedBackground

        scrollView.translatesAutoresizingMaskIntoConstraints = false
        scrollView.keyboardDismissMode = .interactive
        view.addSubview(scrollView)
        stack.axis = .vertical
        stack.spacing = 12
        stack.translatesAutoresizingMaskIntoConstraints = false
        scrollView.addSubview(stack)
        NSLayoutConstraint.activate([
            scrollView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            scrollView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            scrollView.topAnchor.constraint(equalTo: view.topAnchor),
            scrollView.bottomAnchor.constraint(equalTo: view.keyboardLayoutGuide.topAnchor),
            stack.leadingAnchor.constraint(equalTo: scrollView.frameLayoutGuide.leadingAnchor, constant: 20),
            stack.trailingAnchor.constraint(equalTo: scrollView.frameLayoutGuide.trailingAnchor, constant: -20),
            stack.topAnchor.constraint(equalTo: scrollView.contentLayoutGuide.topAnchor, constant: 16),
            stack.bottomAnchor.constraint(equalTo: scrollView.contentLayoutGuide.bottomAnchor, constant: -16),
        ])

        stack.addArrangedSubview(makeLabel("Duo Keyboard", style: .largeTitle, bold: true))
        stack.addArrangedSubview(makeLabel(
            "1. Open Settings, then General, then Keyboard, then Keyboards.\n"
                + "2. Tap Add New Keyboard and choose Duo Keyboard.\n"
                + "3. In any app, hold the globe key and choose Duo Keyboard.",
            style: .body))

        var settingsConfiguration = UIButton.Configuration.filled()
        settingsConfiguration.title = "Open Settings"
        let settingsButton = UIButton(configuration: settingsConfiguration, primaryAction: UIAction { _ in
            guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
            UIApplication.shared.open(url)
        })
        stack.addArrangedSubview(settingsButton)

        stack.addArrangedSubview(makeLabel("Field with the system-selected keyboard", style: .headline))
        configure(systemField, identifier: "systemField")
        stack.addArrangedSubview(systemField)

        stack.addArrangedSubview(makeLabel("Field that always shows Duo Keyboard", style: .headline))
        configure(previewField, identifier: "previewField")
        stack.addArrangedSubview(previewField)

        stack.addArrangedSubview(makeLabel("Display measurements", style: .headline))
        diagnosticsLabel.numberOfLines = 0
        diagnosticsLabel.font = .monospacedSystemFont(ofSize: 13, weight: .regular)
        diagnosticsLabel.accessibilityIdentifier = "diagnostics"
        stack.addArrangedSubview(diagnosticsLabel)

        textController.proofreader = SystemModelProofreader()
        textController.rememberLanguage()
        textController.onDismiss = { [weak self] in
            self?.previewField.resignFirstResponder()
        }
        previewField.delegate = self
        previewKeyboard.showsGlobe = false
        // The launch argument "-layer symbols" or "-layer more" opens that layer for a screenshot.
        switch UserDefaults.standard.string(forKey: "layer") {
        case "symbols": previewKeyboard.show(layer: .symbols)
        case "more": previewKeyboard.show(layer: .more)
        default: break
        }
        previewKeyboard.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        previewContainer.allowsSelfSizing = false
        previewContainer.addSubview(previewKeyboard)
        previewField.inputView = previewContainer
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        updatePreviewKeyboardSize()
        updateDiagnostics()
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        // The launch argument lets an automated run capture the keyboard in a screenshot.
        if !didAutoFocus, ProcessInfo.processInfo.arguments.contains("-focusPreviewField") {
            didAutoFocus = true
            previewField.becomeFirstResponder()
            textController.documentDidChange()
        }
    }

    private func makeLabel(_ text: String, style: UIFont.TextStyle, bold: Bool = false) -> UILabel {
        let label = UILabel()
        label.text = text
        label.numberOfLines = 0
        let base = UIFont.preferredFont(forTextStyle: style)
        label.font = bold ? .systemFont(ofSize: base.pointSize, weight: .bold) : base
        return label
    }

    private func configure(_ field: UITextView, identifier: String) {
        field.font = .preferredFont(forTextStyle: .body)
        field.isScrollEnabled = false
        field.layer.cornerRadius = 10
        field.backgroundColor = .secondarySystemGroupedBackground
        field.textContainerInset = UIEdgeInsets(top: 12, left: 8, bottom: 12, right: 8)
        field.accessibilityIdentifier = identifier
        field.heightAnchor.constraint(greaterThanOrEqualToConstant: 72).isActive = true
    }

    private func updatePreviewKeyboardSize() {
        let width = view.bounds.width
        guard width > 0 else { return }
        let height = KeyboardView.preferredHeight(
            forWidth: width, compactHeight: traitCollection.verticalSizeClass == .compact)
            + view.safeAreaInsets.bottom
        let size = CGSize(width: width, height: height)
        guard previewContainer.frame.size != size else { return }
        previewContainer.frame = CGRect(origin: .zero, size: size)
        previewKeyboard.frame = CGRect(
            x: 0, y: 0, width: width, height: height - view.safeAreaInsets.bottom)
        previewKeyboard.autoresizingMask = [.flexibleWidth]
        if previewField.isFirstResponder {
            previewField.reloadInputViews()
        }
    }

    private func updateDiagnostics() {
        let screen = view.window?.windowScene?.screen
        let screenSize = screen?.bounds.size ?? .zero
        let layout: String
        switch KeyboardView.style(forWidth: view.bounds.width) {
        case .compact: layout = "compact"
        case .wide: layout = "wide"
        case .split: layout = "split"
        }
        let idiom = traitCollection.userInterfaceIdiom == .pad ? "pad" : "phone"
        let sizeClass = traitCollection.horizontalSizeClass == .regular ? "regular" : "compact"
        let heightClass = traitCollection.verticalSizeClass == .regular ? "regular" : "compact"
        var systemInfo = utsname()
        uname(&systemInfo)
        let model = withUnsafeBytes(of: systemInfo.machine) { bytes in
            String(decoding: bytes.prefix(while: { $0 != 0 }), as: UTF8.self)
        }
        diagnosticsLabel.text = [
            "window     \(Int(view.bounds.width)) x \(Int(view.bounds.height)) pt",
            "screen     \(Int(screenSize.width)) x \(Int(screenSize.height)) pt, scale \(screen?.scale ?? 0)",
            "idiom      \(idiom)",
            "width      \(sizeClass) size class",
            "height     \(heightClass) size class",
            "layout     \(layout) (wide starts at \(Int(KeyboardView.wideMinimumWidth)) pt)",
            "model      \(model)",
            "system     iOS \(UIDevice.current.systemVersion)",
        ].joined(separator: "\n")
    }

    // MARK: UITextViewDelegate

    func textViewDidChangeSelection(_ textView: UITextView) {
        textController.documentDidChange()
    }
}

/// Lets the shared typing rules edit the host app's test field.
@MainActor
final class TextViewDocument: KeyboardDocument {
    private let textView: UITextView

    init(textView: UITextView) {
        self.textView = textView
    }

    var textBeforeCursor: String {
        guard let selection = textView.selectedTextRange,
            let range = textView.textRange(from: textView.beginningOfDocument, to: selection.start)
        else { return "" }
        return textView.text(in: range) ?? ""
    }

    var textAfterCursor: String {
        guard let selection = textView.selectedTextRange,
            let range = textView.textRange(from: selection.end, to: textView.endOfDocument)
        else { return "" }
        return textView.text(in: range) ?? ""
    }

    var selectedText: String? {
        guard let selection = textView.selectedTextRange, !selection.isEmpty else { return nil }
        return textView.text(in: selection)
    }

    var autocapitalizationType: UITextAutocapitalizationType { textView.autocapitalizationType }

    var canUseClipboard: Bool { true }

    let documentIdentifier = UUID()

    var allowsAutocorrection: Bool { true }

    func insertText(_ text: String) {
        textView.insertText(text)
    }

    func deleteBackward() {
        textView.deleteBackward()
    }

    func moveCursor(byUTF16Offset offset: Int) {
        guard let selection = textView.selectedTextRange else { return }
        let origin = offset < 0 ? selection.start : selection.end
        // A move past either end of the text stops at that end.
        let target = textView.position(from: origin, offset: offset)
            ?? (offset < 0 ? textView.beginningOfDocument : textView.endOfDocument)
        textView.selectedTextRange = textView.textRange(from: target, to: target)
    }
}
