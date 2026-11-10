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
    /// A remark for the person, in words they can read, or nil: the reason for a missing
    /// answer, or the reason the larger model did not answer.
    let note: String?
    /// The model that answered: "cloud" or "device". Empty without an answer.
    var source = ""
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
        "form" for "from", a misspelled word, a letter typed as the symbol or digit key next to \
        it, such as "[lay" for "play", and a wrong Chinese character with the same sound. The \
        text can be a sentence that is not finished yet. \
        Do not rephrase, do not change the meaning, the tone or the punctuation style, and do not \
        add or remove information. Answer with the corrected sentence only, without quotation \
        marks and without any comment. When the sentence has no error, answer with the sentence \
        exactly as given.

        Examples:
        Text: help where are you form.
        Answer: help where are you from.
        Text: I will sent it too you tomorrow,
        Answer: I will send it to you tomorrow,
        Text: She said the [lan is good.
        Answer: She said the plan is good.
        Text: The meeting starts at noon.
        Answer: The meeting starts at noon.
        Text: \u{6211}\u{4EEC}\u{660E}\u{5929}\u{518D}\u{5317}\u{4EAC}\u{89C1}\u{9762}\u{3002}
        Answer: \u{6211}\u{4EEC}\u{660E}\u{5929}\u{5728}\u{5317}\u{4EAC}\u{89C1}\u{9762}\u{3002}
        """

    /// The larger model on Apple's Private Cloud Compute servers answers a finished sentence
    /// when it is available. The model on the device answers a clause that ends in a comma,
    /// because the cloud model has a daily limit, and it answers everything when the cloud
    /// model is not available: without a network, without Apple's permission for this app, or
    /// over the daily limit.
    func proofread(_ sentence: String) async -> ProofreadResult {
        #if canImport(FoundationModels)
        var cloudNote: String?
        if #available(iOS 27.0, *), let last = sentence.last, KeyboardTextLogic.sentenceEnds.contains(last) {
            let cloud = await askCloudModel(sentence)
            if cloud.text != nil { return cloud }
            cloudNote = cloud.note
        }
        if #available(iOS 26.0, *) {
            var result = await askSystemModel(sentence)
            if result.text != nil, let cloudNote {
                result = ProofreadResult(text: result.text, seconds: result.seconds, note: cloudNote, source: result.source)
            }
            return result
        }
        #endif
        return ProofreadResult(text: nil, seconds: 0, note: "the on-device model needs iOS 26")
    }

    /// Cuts a model's answer down to the corrected text.
    private static func cleaned(_ answer: String) -> String {
        var text = answer.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.hasPrefix("Answer:") {
            text = String(text.dropFirst("Answer:".count))
        }
        return text
    }

    #if canImport(FoundationModels)
    @available(iOS 27.0, *)
    private func askCloudModel(_ sentence: String) async -> ProofreadResult {
        let model = PrivateCloudComputeLanguageModel()
        guard case .available = model.availability else {
            return ProofreadResult(text: nil, seconds: 0, note: "cloud model off (\(model.availability))")
        }
        let start = Date()
        do {
            let session = LanguageModelSession(model: model, instructions: Self.instructions)
            let response = try await session.respond(to: "Text: \(sentence)\nAnswer:")
            return ProofreadResult(
                text: Self.cleaned(response.content), seconds: Date().timeIntervalSince(start),
                note: nil, source: "cloud")
        } catch {
            return ProofreadResult(
                text: nil, seconds: Date().timeIntervalSince(start), note: "cloud model: \(error)")
        }
    }

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
            // The most likely answer each time, so one sentence always gets the same fix.
            let response = try await session.respond(
                to: "Text: \(sentence)\nAnswer:", options: GenerationOptions(sampling: .greedy))
            return ProofreadResult(
                text: Self.cleaned(response.content), seconds: Date().timeIntervalSince(start),
                note: nil, source: "device")
        } catch {
            return ProofreadResult(
                text: nil, seconds: Date().timeIntervalSince(start), note: String(describing: error))
        }
    }
    #endif
}
