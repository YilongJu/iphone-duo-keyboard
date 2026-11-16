import UIKit

/// The host app's only screen. The screen has five parts: setup steps, a field that uses the
/// system-selected keyboard, a field that always shows this app's keyboard, the display
/// measurements that decide which layout appears, and the language model test.
final class SetupViewController: UIViewController, UITextViewDelegate {
    private let scrollView = UIScrollView()
    private let stack = UIStackView()
    private let diagnosticsLabel = UILabel()
    private let languageModelButton = UIButton(type: .system)
    private let languageModelResults = UITextView()
    private let languageModelTest = BundledLanguageModelTest()
    private let speedModelStatus = UITextView()
    private var speedModelButtons: [UIButton] = []
    private let systemField = UITextView()
    private let previewField = UITextView()
    private let previewKeyboard = KeyboardView()
    private let previewContainer = UIInputView(frame: .zero, inputViewStyle: .keyboard)
    private lazy var previewDocument = TextViewDocument(textView: previewField)
    /// The preview keyboard re-ranks its English corrections with the same model as the
    /// keyboard extension. The model loads when the preview keyboard appears in English.
    private let languageModel = KeyboardLanguageModel.bundled(cacheCheckTolerance: nil)
    private lazy var reranker = EnglishReranker(scorer: languageModel, rule: KeyboardLanguageModel.rule)
    private lazy var textController = KeyboardTextController(
        keyboardView: previewKeyboard, document: previewDocument,
        spellChecker: EngineSpellChecker.bundled(reranker: reranker), pinyinEngine: { PinyinEngine.bundled() })
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

        stack.addArrangedSubview(makeLabel("Language model test", style: .headline))
        var testConfiguration = UIButton.Configuration.filled()
        testConfiguration.title = "Run language model test"
        languageModelButton.configuration = testConfiguration
        languageModelButton.accessibilityIdentifier = "languageModelButton"
        languageModelButton.addAction(UIAction { [weak self] _ in
            self?.runLanguageModelTest()
        }, for: .touchUpInside)
        stack.addArrangedSubview(languageModelButton)
        // A text view lets the person select and copy the result lines.
        languageModelResults.isEditable = false
        languageModelResults.isScrollEnabled = false
        languageModelResults.font = .monospacedSystemFont(ofSize: 13, weight: .regular)
        languageModelResults.backgroundColor = .clear
        languageModelResults.textContainerInset = .zero
        languageModelResults.textContainer.lineFragmentPadding = 0
        languageModelResults.accessibilityIdentifier = "languageModelResults"
        languageModelResults.text = "The test runs in this app. For the keyboard's own numbers, "
            + "type duo:lm and a space with Duo Keyboard in the Notes app."
        stack.addArrangedSubview(languageModelResults)
        addSpeedModelSection()

        textController.proofreader = SystemModelProofreader()
        textController.languageModelLoader = languageModel
        languageModel.onEvent = { [weak self] event in
            self?.textController.show(event)
        }
        reranker.onModelError = { [weak self] reason in
            self?.textController.show(.modelError(reason))
        }
        languageModelTest.keyboardLines = { [languageModel, reranker] in
            languageModel.reportLines(statistics: reranker.statistics)
        }
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
            // The launch argument "-previewText good" types a word first, so a screenshot shows its emoji.
            if let text = UserDefaults.standard.string(forKey: "previewText") {
                previewField.insertText(text)
            }
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

    /// Runs the language model test in the app's own process and shows each result line when
    /// the line exists. iOS allows an app far more memory than a keyboard, so the numbers
    /// to hold against the keyboard's limit come from the same test inside the keyboard.
    private func runLanguageModelTest() {
        languageModelButton.isEnabled = false
        languageModelResults.text = ""
        let lines = languageModelTest.resultLines()
        Task { [weak self] in
            for await line in lines {
                guard let self else { return }
                self.languageModelResults.text = (self.languageModelResults.text ?? "") + line + "\n"
            }
            self?.languageModelButton.isEnabled = true
        }
    }

    override func didReceiveMemoryWarning() {
        super.didReceiveMemoryWarning()
        languageModel.unload(reason: "memory warning")
    }

    // MARK: Speed test models

    /// One button per test model of the speed test (docs/model-speed-design.md). A tap downloads
    /// the model into the shared container of the app group. The keyboard then runs it when the
    /// person types duo:speed and a space.
    private func addSpeedModelSection() {
        stack.addArrangedSubview(makeLabel("Speed test models", style: .headline))
        speedModelStatus.isEditable = false
        speedModelStatus.isScrollEnabled = false
        speedModelStatus.font = .monospacedSystemFont(ofSize: 13, weight: .regular)
        speedModelStatus.backgroundColor = .clear
        speedModelStatus.textContainerInset = .zero
        speedModelStatus.textContainer.lineFragmentPadding = 0
        speedModelStatus.accessibilityIdentifier = "speedModelStatus"
        let catalog: ModelSpeedCatalog
        do {
            catalog = try ModelSpeedCatalog.bundled()
        } catch {
            speedModelStatus.text = "The catalog did not load: \(error)"
            stack.addArrangedSubview(speedModelStatus)
            return
        }
        guard let folder = ModelSpeedCatalog.sharedFolder() else {
            speedModelStatus.text = "This build has no access to the app group \(ModelSpeedCatalog.appGroup)."
            stack.addArrangedSubview(speedModelStatus)
            return
        }
        let downloader = ModelSpeedDownloader(session: .shared, folder: folder)
        for model in catalog.models {
            var configuration = UIButton.Configuration.bordered()
            configuration.title = String(format: "Download %@ (%.0f MB)", model.title, Double(model.bytes) / 1_048_576)
            let button = UIButton(configuration: configuration, primaryAction: UIAction { [weak self] _ in
                self?.download(model, with: downloader)
            })
            button.accessibilityIdentifier = "download-\(model.id)"
            speedModelButtons.append(button)
            stack.addArrangedSubview(button)
        }
        var removeConfiguration = UIButton.Configuration.bordered()
        removeConfiguration.title = "Remove every speed test model"
        let removeButton = UIButton(configuration: removeConfiguration, primaryAction: UIAction { [weak self] _ in
            guard let self else { return }
            do {
                for model in catalog.models { try downloader.remove(model) }
                self.speedModelStatus.text = "Every speed test model is removed."
            } catch {
                self.speedModelStatus.text = "The removal failed: \(error)"
            }
        })
        speedModelButtons.append(removeButton)
        stack.addArrangedSubview(removeButton)
        speedModelStatus.text = "Tap a model to download it. Then type duo:speed and a space with Duo Keyboard "
            + "in the Notes app. The keyboard runs every model that is in place."
        stack.addArrangedSubview(speedModelStatus)
    }

    private func download(_ model: ModelSpeedCatalog.Model, with downloader: ModelSpeedDownloader) {
        speedModelButtons.forEach { $0.isEnabled = false }
        speedModelStatus.text = ""
        Task { [weak self] in
            do {
                try await downloader.download(model) { line in
                    Task { @MainActor in self?.appendSpeedStatus(line) }
                }
            } catch {
                self?.appendSpeedStatus("\(model.title): failed: \(error)")
            }
            self?.speedModelButtons.forEach { $0.isEnabled = true }
        }
    }

    private func appendSpeedStatus(_ line: String) {
        speedModelStatus.text = (speedModelStatus.text ?? "") + line + "\n"
    }

    // MARK: UITextViewDelegate

    func textViewDidChangeSelection(_ textView: UITextView) {
        textController.documentDidChange()
    }

    func textViewDidBeginEditing(_ textView: UITextView) {
        // The preview keyboard appears with its field.
        if textView === previewField {
            textController.keyboardWillAppear()
        }
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
