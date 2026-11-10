import Foundation

/// Runs the language model test and hands out its result as lines of text.
@MainActor
protocol LanguageModelMeasuring: AnyObject {
    /// Starts one run of the test. The stream gives each result line as soon as the line
    /// exists, and it ends when the test is over and the model is freed.
    func resultLines() -> AsyncStream<String>
}

/// The language model test on the model file of the bundle. LanguageModel/duo_lm_probe.h
/// describes the test and each of its result lines.
///
/// The test only measures. It loads its own copy of the model when a run starts and frees it
/// when the run ends, beside the model that re-ranks the English corrections.
///
/// Before the test's own lines come the lines of `keyboardLines`, which describe that model in
/// this process. Each starts with "reranker" or "memory":
///
///   reranker    the model, its threads, and its state: loaded with the time of the load, not
///               loaded, loading, freed with the reason, or "load failed" with the reason
///   reranker    the footprint right before the load, right after it, and right after the first
///               correction that the model read, when the model's buffers for scores exist
///   reranker    the corrections the model read and the time each one added to its space
///               press, from the start of the model's text to the choice: mean, median, 95th
///               percentile of the last 2,000, and worst
///   reranker    how often the model changed the engine's choice, and the corrections that kept
///               the engine's choice because the model was not ready, because the text was
///               outside the model's limits, or because of a model error
///   reranker    the requests, the tokens the model read, and the tokens put in place of -1
///   memory      the memory of the process right before the test loads its own copy
@MainActor
final class BundledLanguageModelTest: LanguageModelMeasuring {
    /// Name of the model file in the bundle, without ".gguf". scripts/ci/fetch_language_model.sh
    /// downloads the file before the build.
    static let modelResource = "distilgpt2.Q3_K_M"

    /// Lines about the model that re-ranks the English corrections in this process. Without
    /// it the result holds the test's own lines only.
    var keyboardLines: (@MainActor () -> [String])?

    func resultLines() -> AsyncStream<String> {
        let (stream, continuation) = AsyncStream.makeStream(of: String.self)
        for line in Self.deviceLines() {
            continuation.yield(line)
        }
        for line in keyboardLines?() ?? [] {
            continuation.yield(line)
        }
        guard let path = Bundle(for: BundledLanguageModelTest.self)
            .path(forResource: Self.modelResource, ofType: "gguf")
        else {
            // A missing file is a result line. The keyboard keeps running.
            continuation.yield("model       failed: \(Self.modelResource).gguf is missing from the bundle")
            continuation.finish()
            return stream
        }
        // The test takes several seconds, so it runs on its own thread and the keys keep
        // answering. A new thread gets a stack of 512 KB, and llama.cpp gets 2 MB here.
        let thread = Thread { @Sendable in
            Self.run(modelPath: path, continuation: continuation)
        }
        thread.stackSize = 2 << 20
        thread.qualityOfService = .userInitiated
        thread.start()
        return stream
    }

    /// The device, the system and the kind of process, as the first lines of the result.
    private static func deviceLines() -> [String] {
        var systemInfo = utsname()
        uname(&systemInfo)
        let model = withUnsafeBytes(of: systemInfo.machine) { bytes in
            String(decoding: bytes.prefix(while: { $0 != 0 }), as: UTF8.self)
        }
        let version = ProcessInfo.processInfo.operatingSystemVersion
        // The keyboard runs in an extension bundle (.appex) and the host app in an app bundle.
        let process = Bundle.main.bundleURL.pathExtension == "appex" ? "keyboard" : "app"
        return [
            "test        language model, llama.cpp b4846, processor only",
            "device      \(model)",
            "system      iOS \(version.majorVersion).\(version.minorVersion).\(version.patchVersion)",
            "process     \(process)",
        ]
    }

    /// Runs the C test on the calling thread and ends the stream after its last line.
    private nonisolated static func run(modelPath: String, continuation: AsyncStream<String>.Continuation) {
        let sink = Unmanaged.passRetained(LineSink(continuation: continuation))
        // The C test reports a failed step as a result line, so its return value adds nothing here.
        _ = duo_lm_measure(modelPath, { text, pointer in
            guard let text, let pointer else { return }
            let receiver = Unmanaged<LineSink>.fromOpaque(pointer).takeUnretainedValue()
            receiver.continuation.yield(String(cString: text))
        }, sink.toOpaque())
        sink.release()
        continuation.finish()
    }
}

/// Carries the stream through the C test, which hands each line to a C function.
private final class LineSink {
    let continuation: AsyncStream<String>.Continuation

    init(continuation: AsyncStream<String>.Continuation) {
        self.continuation = continuation
    }
}
