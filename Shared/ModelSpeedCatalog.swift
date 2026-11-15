import Foundation

/// The files and the pairs of the speed test of docs/model-speed-design.md.
///
/// A pair is one model and one way to run it. The containing app downloads the files of the
/// test models into the shared container of the app group, and the keyboard reads them from
/// there. The keyboard itself has no network code: it only reads this catalog and the files.
/// `Shared/model-speed-catalog.json` holds the catalog, and scripts/model-speed/make_catalog.py
/// writes it from the files of the release model-speed-1 of this repository.
struct ModelSpeedCatalog: Codable, Equatable, Sendable {
    /// The app group that the app and the keyboard share. Both targets carry it in their
    /// entitlements (App/DuoKeyboard.entitlements and Keyboard/DuoKeyboardExtension.entitlements).
    static let appGroup = "group.com.yilongju.duokeyboard"
    /// The folder of the test models in the shared container.
    static let folderName = "ModelSpeed"

    /// One file of a model, with its fixed address and SHA-256 value.
    struct File: Codable, Equatable, Sendable {
        /// The place of the file under the model's folder, such as "model.gguf" or
        /// "model.mlmodelc/weights/weight.bin".
        let path: String
        let url: URL
        /// The SHA-256 value of the file, 64 lowercase hexadecimal digits.
        let sha256: String
        let bytes: Int64
    }

    /// A model to download: a GGUF file of llama.cpp or a compiled Core ML model.
    struct Model: Codable, Equatable, Sendable {
        /// The name of the model's folder in the shared container.
        let id: String
        let title: String
        let files: [File]

        var bytes: Int64 { files.reduce(0) { $0 + $1.bytes } }
    }

    /// The ways to run a model in the speed test.
    enum Runtime: String, Codable, Sendable {
        /// llama.cpp b4846 of the app's framework, on the processor only, 2 threads.
        case llamaProcessor = "llama-cpu"
        /// llama.cpp b4846 with Metal: the GPU runs every layer.
        case llamaMetal = "llama-metal"
        /// As llamaMetal, with GGML_METAL_NO_RESIDENCY=1, so llama.cpp keeps no residency set.
        case llamaMetalNoResidency = "llama-metal-no-residency"
        /// Core ML with the compute units CPU and GPU, on the flexible form of the model.
        case coreMLGPU = "coreml-gpu"
        /// Core ML with the compute units CPU and Neural Engine, on the fixed form of the model,
        /// whose shapes the Neural Engine can run.
        case coreMLNeuralEngine = "coreml-ane"
    }

    struct Pair: Codable, Equatable, Sendable {
        let name: String
        /// The id of a model of `models`, or "bundled" for the keyboard's own model file.
        let model: String
        let runtime: Runtime
        /// The tokens of the requests for a runtime without a tokenizer: the name of a file
        /// "model-speed-tokens.NAME.tsv" of the bundle.
        let tokens: String?
        /// The top candidates of llama.cpp on the same model at Q8_0 on the desktop, a key of
        /// "model-speed-reference.json" of the bundle.
        let reference: String
    }

    let release: String
    let models: [Model]
    let pairs: [Pair]

    func model(id: String) -> Model? { models.first { $0.id == id } }

    /// The catalog of the bundle.
    static func bundled() throws -> ModelSpeedCatalog {
        guard let url = Bundle(for: BundleToken.self).url(forResource: "model-speed-catalog", withExtension: "json") else {
            throw ModelSpeedError("model-speed-catalog.json is missing from the bundle")
        }
        return try JSONDecoder().decode(ModelSpeedCatalog.self, from: Data(contentsOf: url))
    }

    /// The folder of the test models in the shared container, or nil when the process has no
    /// access to the app group.
    static func sharedFolder() -> URL? {
        FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroup)?
            .appendingPathComponent(folderName, isDirectory: true)
    }
}

struct ModelSpeedError: Error, Equatable, CustomStringConvertible {
    let reason: String
    init(_ reason: String) { self.reason = reason }
    var description: String { reason }
}

/// Finds the bundle of this code: the app's or the keyboard's.
private final class BundleToken {}
