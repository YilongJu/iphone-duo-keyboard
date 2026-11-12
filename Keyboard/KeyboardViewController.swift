import UIKit

/// The system plays the key click only when the visible input view adopts this protocol.
extension UIInputView: @retroactive UIInputViewAudioFeedback {
    public var enableInputClicksWhenVisible: Bool { true }
}

/// The keyboard extension's entry point. iOS creates one instance when the keyboard appears.
/// The typing rules live in `KeyboardTextController`, which the host app's test field shares.
final class KeyboardViewController: UIInputViewController {
    /// The globe key is always visible. `needsInputModeSwitchKey` returns false on the iPhone Duo
    /// (Apple feedback FB25073949), and the Duo does not draw a globe button of its own.
    private let keyboardView = KeyboardView()
    private lazy var document = ProxyDocument(controller: self)
    /// The model that re-ranks the English corrections. It loads when the keyboard appears in
    /// English, and a memory warning frees it.
    private let languageModel = KeyboardLanguageModel.bundled()
    private lazy var reranker = EnglishReranker(scorer: languageModel, rule: KeyboardLanguageModel.rule)
    private lazy var textController = KeyboardTextController(
        keyboardView: keyboardView, document: document, spellChecker: EngineSpellChecker.bundled(reranker: reranker),
        pinyinEngine: { PinyinEngine.bundled() })
    private var heightConstraint: NSLayoutConstraint?

    override func viewDidLoad() {
        super.viewDidLoad()
        textController.proofreader = SystemModelProofreader()
        // The test loads its own model only when the person types "duo:lm" and a space. Its
        // first lines describe the model that re-ranks the corrections.
        let languageModelTest = BundledLanguageModelTest()
        languageModelTest.keyboardLines = { [languageModel, reranker] in
            languageModel.reportLines(statistics: reranker.statistics)
        }
        // The test loads its own copy of the model, so the keyboard frees its copy for the run and
        // loads it again after. Two copies at once could pass the memory limit of the keyboard.
        languageModelTest.onRunStart = { [languageModel] in
            languageModel.unload(reason: "the language model test runs")
        }
        languageModelTest.onRunEnd = { [weak self] in
            self?.textController.keyboardWillAppear()
        }
        textController.languageModelMeasurer = languageModelTest
        textController.languageModelLoader = languageModel
        languageModel.onEvent = { [weak self] event in
            self?.textController.show(event)
        }
        reranker.onModelError = { [weak self] reason in
            self?.textController.show(.modelError(reason))
        }
        // The typing log is off until the person types "duo:log" and a space. Its records stay in
        // the keyboard extension's own container. The log does not record in a field such as a
        // password field (docs/typing-log-design.md).
        let typingLog = TypingLog(store: FileTypingLogStore.inOwnContainer())
        typingLog.fieldIsLoggable = { [weak self] in
            self?.document.allowsTypingLog ?? false
        }
        textController.typingLog = typingLog
        textController.rememberLanguage()
        // iPadOS draws undo, redo and paste buttons over the keyboard's top left corner. This
        // request to drop them is honored for a text field's own input view. For a keyboard
        // extension the documentation does not say, so the first row also leaves that corner free.
        inputAssistantItem.leadingBarButtonGroups = []
        inputAssistantItem.trailingBarButtonGroups = []
        textController.onDismiss = { [weak self] in
            self?.dismissKeyboard()
        }
        keyboardView.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(keyboardView)
        NSLayoutConstraint.activate([
            keyboardView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            keyboardView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            keyboardView.topAnchor.constraint(equalTo: view.topAnchor),
            keyboardView.bottomAnchor.constraint(equalTo: view.bottomAnchor),
        ])
        keyboardView.globeButton.addTarget(
            self, action: #selector(handleInputModeList(from:with:)), for: .allTouchEvents)
    }

    override func viewWillAppear(_ animated: Bool) {
        super.viewWillAppear(animated)
        updateHeight()
        refreshFromDocument()
        textController.keyboardWillAppear()
    }

    override func didReceiveMemoryWarning() {
        super.didReceiveMemoryWarning()
        languageModel.unload(reason: "memory warning")
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        // The system's edge gestures hold back touches near the screen edges for a moment.
        // Without the delay, the keys at the edges respond as fast as the keys in the middle.
        for recognizer in view.window?.gestureRecognizers ?? [] {
            recognizer.delaysTouchesBegan = false
        }
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        textController.cancelPendingEdits()
    }

    override func viewWillLayoutSubviews() {
        super.viewWillLayoutSubviews()
        updateHeight()
    }

    override func textDidChange(_ textInput: UITextInput?) {
        super.textDidChange(textInput)
        refreshFromDocument()
    }

    override func selectionDidChange(_ textInput: UITextInput?) {
        super.selectionDidChange(textInput)
        textController.documentDidChange()
    }

    private func updateHeight() {
        // Before the first layout pass the view does not have a width, and the compact layout's
        // height stands in for one pass.
        let height = KeyboardView.preferredHeight(
            forWidth: view.bounds.width, compactHeight: traitCollection.verticalSizeClass == .compact)
        if let heightConstraint {
            if heightConstraint.constant != height {
                heightConstraint.constant = height
            }
        } else {
            let constraint = view.heightAnchor.constraint(equalToConstant: height)
            // Priority 999 lets the system's own temporary height constraint win during rotation.
            constraint.priority = UILayoutPriority(999)
            constraint.isActive = true
            heightConstraint = constraint
        }
    }

    private func refreshFromDocument() {
        // `.default` is the value UIKit documents for a text field that does not set a return key type.
        let returnKeyType = textDocumentProxy.returnKeyType ?? .default
        keyboardView.returnKeySymbol = KeyboardTextLogic.returnKeySymbol(for: returnKeyType)
        textController.documentDidChange()
    }
}

/// Lets the shared typing rules edit the app's text field through the system's document proxy.
@MainActor
final class ProxyDocument: KeyboardDocument {
    private unowned let controller: UIInputViewController

    init(controller: UIInputViewController) {
        self.controller = controller
    }

    private var proxy: UITextDocumentProxy { controller.textDocumentProxy }

    // The proxy returns nil for an empty context, and an empty string means the same here.
    var textBeforeCursor: String { proxy.documentContextBeforeInput ?? "" }
    var textAfterCursor: String { proxy.documentContextAfterInput ?? "" }
    var selectedText: String? {
        // An empty selection and a missing selection both mean a plain insertion point.
        guard let selected = proxy.selectedText, !selected.isEmpty else { return nil }
        return selected
    }

    /// `.sentences` is the value UIKit documents for a text field that does not set the trait.
    var autocapitalizationType: UITextAutocapitalizationType { proxy.autocapitalizationType ?? .sentences }

    /// iOS gives a keyboard the clipboard only when the user turns on Full Access.
    var canUseClipboard: Bool { controller.hasFullAccess }

    var documentIdentifier: UUID { proxy.documentIdentifier }

    /// A field can turn autocorrection off, and a field for an address or a number does not hold prose.
    var allowsAutocorrection: Bool {
        if proxy.autocorrectionType == .no { return false }
        switch proxy.keyboardType {
        case .URL, .emailAddress, .numberPad, .phonePad, .decimalPad, .asciiCapableNumberPad, .numbersAndPunctuation:
            return false
        default:
            return true
        }
    }

    /// False for a field whose text the typing log must not record (`TypingLogPolicy`). A field
    /// for a password, a code, a name or an address is such a field. The system gives a field
    /// without a content type as nil, in one or two levels of Optional.
    var allowsTypingLog: Bool {
        TypingLogPolicy.allowsLog(
            isSecureTextEntry: proxy.isSecureTextEntry, textContentType: proxy.textContentType ?? nil,
            keyboardType: proxy.keyboardType)
    }

    func insertText(_ text: String) {
        proxy.insertText(text)
    }

    func deleteBackward() {
        proxy.deleteBackward()
    }

    func moveCursor(byUTF16Offset offset: Int) {
        proxy.adjustTextPosition(byCharacterOffset: offset)
    }
}
