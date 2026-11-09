import SwiftUI
import UIKit

@main
struct DuoKeyboardApp: App {
    var body: some Scene {
        WindowGroup {
            SetupScreen()
                .ignoresSafeArea(.keyboard)
        }
    }
}

/// Wraps the UIKit setup screen for the SwiftUI app lifecycle.
struct SetupScreen: UIViewControllerRepresentable {
    func makeUIViewController(context: Context) -> SetupViewController {
        SetupViewController()
    }

    func updateUIViewController(_ controller: SetupViewController, context: Context) {}
}
