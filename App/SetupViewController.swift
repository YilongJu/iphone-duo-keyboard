import UIKit

/// The host app's only screen. The screen has four parts: setup steps, a field that uses the
/// system-selected keyboard, a field that always shows this app's keyboard, and the display
/// measurements that decide which layout appears.
final class SetupViewController: UIViewController, KeyboardViewDelegate {
    private let scrollView = UIScrollView()
    private let stack = UIStackView()
    private let diagnosticsLabel = UILabel()
    private let systemField = UITextView()
    private let previewField = UITextView()
    private let previewKeyboard = KeyboardView()
    private let previewContainer = UIInputView(frame: .zero, inputViewStyle: .keyboard)
    private var previousInsertWasSpace = false
    private var lastSpaceTime: TimeInterval = 0
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

        previewKeyboard.delegate = self
        previewKeyboard.showsGlobe = false
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
            updatePreviewAutoShift()
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
        let layout = KeyboardView.style(forWidth: view.bounds.width) == .wide ? "wide" : "compact"
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

    private func updatePreviewAutoShift() {
        let before = textBeforeCursor()
        let capitalize = KeyboardTextLogic.shouldAutoCapitalize(before: before, type: .sentences)
        previewKeyboard.setAutomaticShift(capitalize)
    }

    private func textBeforeCursor() -> String? {
        guard let range = previewField.selectedTextRange,
            let beforeRange = previewField.textRange(from: previewField.beginningOfDocument, to: range.start)
        else { return nil }
        return previewField.text(in: beforeRange)
    }

    private func textAfterCursor() -> String? {
        guard let range = previewField.selectedTextRange,
            let afterRange = previewField.textRange(from: range.end, to: previewField.endOfDocument)
        else { return nil }
        return previewField.text(in: afterRange)
    }

    // MARK: KeyboardViewDelegate

    func keyboardView(_ keyboardView: KeyboardView, insert text: String) {
        if text == " ", previousInsertWasSpace,
            ProcessInfo.processInfo.systemUptime - lastSpaceTime < 1.5,
            KeyboardTextLogic.shouldReplaceDoubleSpace(before: textBeforeCursor()) {
            previewField.deleteBackward()
            previewField.insertText(". ")
            previousInsertWasSpace = false
        } else {
            previewField.insertText(text)
            previousInsertWasSpace = text == " "
            lastSpaceTime = ProcessInfo.processInfo.systemUptime
        }
        updatePreviewAutoShift()
    }

    func keyboardViewDeleteBackward(_ keyboardView: KeyboardView) {
        previewField.deleteBackward()
        previousInsertWasSpace = false
        updatePreviewAutoShift()
    }

    func keyboardViewReturn(_ keyboardView: KeyboardView) {
        previewField.insertText("\n")
        previousInsertWasSpace = false
        updatePreviewAutoShift()
    }

    func keyboardView(_ keyboardView: KeyboardView, moveCursorBy offset: Int) {
        previousInsertWasSpace = false
        guard let range = previewField.selectedTextRange,
            let position = previewField.position(from: range.start, offset: offset)
        else { return }
        previewField.selectedTextRange = previewField.textRange(from: position, to: position)
    }

    func keyboardView(_ keyboardView: KeyboardView, edit command: EditCommand) {
        previousInsertWasSpace = false
        switch command {
        case .lineStart, .lineEnd, .lineUp, .lineDown:
            let offset = KeyboardTextLogic.cursorOffset(
                for: command, before: textBeforeCursor() ?? "", after: textAfterCursor() ?? "")
            self.keyboardView(keyboardView, moveCursorBy: offset)
        case .cut:
            previewField.cut(nil)
        case .copy:
            previewField.copy(nil)
        case .paste:
            previewField.paste(nil)
        }
        updatePreviewAutoShift()
    }

    func keyboardViewDismiss(_ keyboardView: KeyboardView) {
        previewField.resignFirstResponder()
    }

    func keyboardViewDidPressKey(_ keyboardView: KeyboardView) {
        UIDevice.current.playInputClick()
    }
}
