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
    private let appSpeedButton = UIButton(type: .system)
    private let appSpeedResults = UITextView()
    /// The progress line of the running test, written again every 2 seconds.
    private let appSpeedProgress = UILabel()
    /// The pair the app's run starts at, as in "duo:speed6". Empty starts at the first pair.
    private let appSpeedStart = UITextField()
    /// The record of the app's run, so a run that stopped goes on at the next tap, as in the
    /// keyboard. It is apart from the keyboard's record, in the app's own container.
    private let appSpeedFolder = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        .appendingPathComponent("model-speed-progress-app", isDirectory: true)
    /// The MetricKit diagnostics of the app, such as a crash during an earlier run.
    private let appDiagnostics = ModelSpeedDiagnostics(
        file: FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("model-speed-diagnostics-app.txt"))
    private let systemField = UITextView()
    private let previewField = UITextView()
    private let previewKeyboard = KeyboardView()
    private let previewContainer = UIInputView(frame: .zero, inputViewStyle: .keyboard)
    private lazy var previewDocument = TextViewDocument(textView: previewField)
    /// The preview keyboard re-ranks its English corrections with the same model as the
    /// keyboard extension. The model loads when the preview keyboard appears in English.
    private let languageModel = KeyboardLanguageModel.bundled(device: DUO_LM_DEVICE_GPU, cacheCheckTolerance: nil)
    private lazy var reranker = EnglishReranker(scorer: languageModel, rule: KeyboardLanguageModel.rule)
    private lazy var textController = KeyboardTextController(
        keyboardView: previewKeyboard, document: previewDocument,
        spellChecker: EngineSpellChecker.bundled(reranker: reranker, predictor: languageModel), pinyinEngine: { PinyinEngine.bundled() })
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
        // The launch argument "-returnKeyType search" or "-returnKeyType send" gives the field that
        // return key type, for a screenshot of the blue return key.
        switch UserDefaults.standard.string(forKey: "returnKeyType") {
        case nil: break
        case "search": previewField.returnKeyType = .search
        case "send": previewField.returnKeyType = .send
        case let other?: fatalError("Unknown launch argument -returnKeyType \(other)")
        }
        previewKeyboard.returnKeyType = previewField.returnKeyType
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
        addAppSpeedTest()
    }

    /// Runs the Core ML pairs of the speed test in this app, which iOS allows far more memory
    /// than a keyboard and which is in the foreground. When a pair runs here and stops the
    /// keyboard, the cause is the keyboard's limits and not the model or the code.
    private func addAppSpeedTest() {
        appDiagnostics.start()
        stack.addArrangedSubview(makeLabel("Core ML pairs in this app", style: .headline))
        var configuration = UIButton.Configuration.filled()
        configuration.title = "Run the Core ML pairs in this app"
        appSpeedButton.configuration = configuration
        appSpeedButton.accessibilityIdentifier = "appSpeedButton"
        appSpeedButton.addAction(UIAction { [weak self] _ in
            self?.runAppSpeedTest()
        }, for: .touchUpInside)
        appSpeedStart.placeholder = "Start at pair (empty: the first pair)"
        appSpeedStart.keyboardType = .numberPad
        appSpeedStart.borderStyle = .roundedRect
        appSpeedStart.accessibilityIdentifier = "appSpeedStart"
        stack.addArrangedSubview(appSpeedStart)
        stack.addArrangedSubview(appSpeedButton)
        appSpeedProgress.font = .monospacedSystemFont(ofSize: 13, weight: .semibold)
        appSpeedProgress.numberOfLines = 0
        appSpeedProgress.accessibilityIdentifier = "appSpeedProgress"
        stack.addArrangedSubview(appSpeedProgress)
        var resetConfiguration = UIButton.Configuration.bordered()
        resetConfiguration.title = "Delete the record of the app's run"
        stack.addArrangedSubview(UIButton(configuration: resetConfiguration, primaryAction: UIAction { [weak self] _ in
            guard let self else { return }
            do {
                try ModelSpeedProgress.reset(self.appSpeedFolder)
                self.appSpeedResults.text = "The record is deleted. The next run starts at the first pair."
            } catch {
                self.appSpeedResults.text = "The record was not deleted: \(error)"
            }
        }))
        var copyConfiguration = UIButton.Configuration.bordered()
        copyConfiguration.title = "Copy the result lines"
        stack.addArrangedSubview(UIButton(configuration: copyConfiguration, primaryAction: UIAction { [weak self] _ in
            UIPasteboard.general.string = self?.appSpeedResults.text
        }))
        appSpeedResults.isEditable = false
        appSpeedResults.isScrollEnabled = false
        appSpeedResults.font = .monospacedSystemFont(ofSize: 13, weight: .regular)
        appSpeedResults.backgroundColor = .clear
        appSpeedResults.textContainerInset = .zero
        appSpeedResults.textContainer.lineFragmentPadding = 0
        appSpeedResults.accessibilityIdentifier = "appSpeedResults"
        appSpeedResults.text = "Runs pairs 13 to 22 in this app. Keep the app open: the screen stays on during the run. "
            + "After a stop, tap the button again: the run shows the kept lines and goes on."
        stack.addArrangedSubview(appSpeedResults)
    }

    private func runAppSpeedTest() {
        appSpeedButton.isEnabled = false
        appSpeedResults.text = ""
        // The screen stays on, so the app stays in the foreground for the whole run.
        UIApplication.shared.isIdleTimerDisabled = true
        let test = ModelSpeedTest(
            runtimes: [.coreMLGPU, .coreMLNeuralEngine], progressFolder: appSpeedFolder,
            diagnosticsFile: appDiagnostics.file)
        appSpeedStart.resignFirstResponder()
        let startText = (appSpeedStart.text ?? "").trimmingCharacters(in: .whitespaces)
        if !startText.isEmpty {
            guard let start = Int(startText) else {
                appSpeedResults.text = "The start pair \"\(startText)\" is not a number."
                UIApplication.shared.isIdleTimerDisabled = false
                appSpeedButton.isEnabled = true
                return
            }
            test.startPair = start
        }
        let lines = test.resultLines()
        let ticker = Task { [weak self] in
            while !Task.isCancelled {
                self?.appSpeedProgress.text = test.progressCaption()
                try? await Task.sleep(nanoseconds: 2_000_000_000)
            }
        }
        Task { [weak self] in
            for await line in lines {
                guard let self else { return }
                self.appSpeedResults.text = (self.appSpeedResults.text ?? "") + line + "\n"
            }
            ticker.cancel()
            self?.appSpeedProgress.text = "The run ended."
            UIApplication.shared.isIdleTimerDisabled = false
            self?.appSpeedButton.isEnabled = true
        }
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

    func setMarkedText(_ text: String) {
        textView.setMarkedText(text, selectedRange: NSRange(location: text.utf16.count, length: 0))
    }

    func unmarkText() {
        textView.unmarkText()
    }
}
