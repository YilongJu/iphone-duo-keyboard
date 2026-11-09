import UIKit

/// The system plays the key click only when the visible input view adopts this protocol.
extension UIInputView: @retroactive UIInputViewAudioFeedback {
    public var enableInputClicksWhenVisible: Bool { true }
}

/// The keyboard extension's entry point. iOS creates one instance when the keyboard appears.
final class KeyboardViewController: UIInputViewController, KeyboardViewDelegate {
    /// The globe key is always visible. `needsInputModeSwitchKey` returns false on the iPhone Duo
    /// (Apple feedback FB25073949), and the Duo does not draw a globe button of its own.
    private let keyboardView = KeyboardView()
    private var heightConstraint: NSLayoutConstraint?
    private var previousInsertWasSpace = false
    private var lastSpaceTime: TimeInterval = 0

    override func viewDidLoad() {
        super.viewDidLoad()
        keyboardView.delegate = self
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
    }

    override func viewWillLayoutSubviews() {
        super.viewWillLayoutSubviews()
        updateHeight()
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        updateMeasurementCaption()
    }

    override func textDidChange(_ textInput: UITextInput?) {
        super.textDidChange(textInput)
        refreshFromDocument()
    }

    override func selectionDidChange(_ textInput: UITextInput?) {
        super.selectionDidChange(textInput)
        updateAutoShift()
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

    /// Shows the keyboard's own measurements on the space bar. The wide layout's threshold
    /// rests on published simulator numbers, and this caption gives the numbers from a real device.
    private func updateMeasurementCaption() {
        func name(_ sizeClass: UIUserInterfaceSizeClass) -> String {
            switch sizeClass {
            case .regular: return "R"
            case .compact: return "C"
            default: return "?"
            }
        }
        let insets = view.safeAreaInsets
        keyboardView.spaceCaption = "\(Int(view.bounds.width))x\(Int(view.bounds.height))"
            + " h\(name(traitCollection.horizontalSizeClass)) v\(name(traitCollection.verticalSizeClass))"
            + " safe \(Int(insets.left))/\(Int(insets.right))/\(Int(insets.bottom))"
            + " globe \(needsInputModeSwitchKey ? 1 : 0)"
    }

    private func refreshFromDocument() {
        let returnKeyType = textDocumentProxy.returnKeyType ?? .default
        keyboardView.returnKeyTitle = KeyboardTextLogic.returnKeyTitle(for: returnKeyType)
        updateAutoShift()
    }

    private func updateAutoShift() {
        let type = textDocumentProxy.autocapitalizationType ?? .sentences
        let capitalize = KeyboardTextLogic.shouldAutoCapitalize(
            before: textDocumentProxy.documentContextBeforeInput, type: type)
        keyboardView.setAutomaticShift(capitalize)
    }

    // MARK: KeyboardViewDelegate

    func keyboardView(_ keyboardView: KeyboardView, insert text: String) {
        let proxy = textDocumentProxy
        if text == " ", previousInsertWasSpace,
            ProcessInfo.processInfo.systemUptime - lastSpaceTime < 1.5,
            KeyboardTextLogic.shouldReplaceDoubleSpace(before: proxy.documentContextBeforeInput) {
            proxy.deleteBackward()
            proxy.insertText(". ")
            previousInsertWasSpace = false
        } else {
            proxy.insertText(text)
            previousInsertWasSpace = text == " "
            lastSpaceTime = ProcessInfo.processInfo.systemUptime
        }
        updateAutoShift()
    }

    func keyboardViewDeleteBackward(_ keyboardView: KeyboardView) {
        textDocumentProxy.deleteBackward()
        previousInsertWasSpace = false
        updateAutoShift()
    }

    func keyboardViewReturn(_ keyboardView: KeyboardView) {
        textDocumentProxy.insertText("\n")
        previousInsertWasSpace = false
        updateAutoShift()
    }

    func keyboardView(_ keyboardView: KeyboardView, moveCursorBy offset: Int) {
        textDocumentProxy.adjustTextPosition(byCharacterOffset: offset)
        previousInsertWasSpace = false
    }

    func keyboardViewDismiss(_ keyboardView: KeyboardView) {
        dismissKeyboard()
    }

    func keyboardViewDidPressKey(_ keyboardView: KeyboardView) {
        UIDevice.current.playInputClick()
    }
}
