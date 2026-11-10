import Foundation

#if canImport(FoundationModels)
import FoundationModels
#endif

/// The answer to one proofreading request.
struct ProofreadResult {
    /// The sentence as the model returned it, or nil when the model gave no answer.
    let text: String?
    /// Seconds from the request to the answer.
    let seconds: Double
    /// The reason for a missing answer, in words a person can read, or nil.
    let note: String?
}

/// Reads one finished sentence and returns it with its typing errors fixed.
@MainActor
protocol SentenceProofreading: AnyObject {
    func proofread(_ sentence: String) async -> ProofreadResult
}

/// Proofreading by the language model that iOS runs on the device (Apple's Foundation Models
/// framework, iOS 26 and later, on devices with Apple Intelligence). The model runs in a system
/// process, so its memory does not count against the keyboard, and the text does not leave the
/// device.
@MainActor
final class SystemModelProofreader: SentenceProofreading {
    static let instructions = """
        You fix typing errors in one sentence. Fix a wrong word that is a typing slip, such as \
        "form" for "from", a misspelled word, and a wrong Chinese character with the same sound. \
        Do not rephrase, do not change the meaning, the tone or the punctuation style, and do not \
        add or remove information. Answer with the corrected sentence only, without quotation \
        marks and without any comment. When the sentence has no error, answer with the sentence \
        exactly as given.
        """

    func proofread(_ sentence: String) async -> ProofreadResult {
        #if canImport(FoundationModels)
        if #available(iOS 26.0, *) {
            return await askSystemModel(sentence)
        }
        #endif
        return ProofreadResult(text: nil, seconds: 0, note: "the on-device model needs iOS 26")
    }

    #if canImport(FoundationModels)
    @available(iOS 26.0, *)
    private func askSystemModel(_ sentence: String) async -> ProofreadResult {
        let model = SystemLanguageModel.default
        switch model.availability {
        case .available:
            break
        case .unavailable(.appleIntelligenceNotEnabled):
            return ProofreadResult(text: nil, seconds: 0, note: "turn on Apple Intelligence in Settings")
        case .unavailable(.modelNotReady):
            return ProofreadResult(text: nil, seconds: 0, note: "the model is still downloading")
        case .unavailable(.deviceNotEligible):
            return ProofreadResult(text: nil, seconds: 0, note: "this device cannot run Apple Intelligence")
        case .unavailable(let reason):
            return ProofreadResult(text: nil, seconds: 0, note: "model off (\(reason))")
        }
        let start = Date()
        do {
            // A new session for each sentence, so an earlier sentence cannot leak into this answer.
            let session = LanguageModelSession(instructions: Self.instructions)
            let response = try await session.respond(to: sentence)
            return ProofreadResult(text: response.content, seconds: Date().timeIntervalSince(start), note: nil)
        } catch {
            return ProofreadResult(
                text: nil, seconds: Date().timeIntervalSince(start), note: String(describing: error))
        }
    }
    #endif
}
