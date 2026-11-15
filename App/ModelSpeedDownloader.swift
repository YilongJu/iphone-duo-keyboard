import CryptoKit
import Foundation

/// Downloads the files of a test model of the speed test into the shared container of the app
/// group, where the keyboard reads them (Shared/ModelSpeedTest.swift).
///
/// Each file has a fixed address and a fixed SHA-256 value in `ModelSpeedCatalog`. A file goes
/// to its place only after its size and its SHA-256 value match, so the keyboard never reads a
/// part of a file or a wrong file. A file that is already in place and matches is kept. Only the
/// app has this code: the keyboard has no network code.
final class ModelSpeedDownloader: Sendable {
    enum Failure: Error, Equatable, CustomStringConvertible {
        case httpStatus(file: String, status: Int)
        case size(file: String, expected: Int64, actual: Int64)
        case checksum(file: String, expected: String, actual: String)
        case badPath(String)

        var description: String {
            switch self {
            case .httpStatus(let file, let status): return "\(file): the server answered with status \(status)"
            case .size(let file, let expected, let actual): return "\(file): \(actual) bytes, expected \(expected)"
            case .checksum(let file, let expected, let actual):
                return "\(file): the SHA-256 value is \(actual), expected \(expected)"
            case .badPath(let path): return "the path \(path) leaves the model's folder"
            }
        }
    }

    let session: URLSession
    let folder: URL

    /// `folder` is the folder of the test models, `ModelSpeedCatalog.sharedFolder()` in the app.
    init(session: URLSession, folder: URL) {
        self.session = session
        self.folder = folder
    }

    /// The SHA-256 value of a file in lowercase hexadecimal digits, read in pieces of 4 MB so
    /// that a file of several hundred MB never sits in memory whole.
    static func sha256(of url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hasher = SHA256()
        while let piece = try handle.read(upToCount: 4 << 20), !piece.isEmpty {
            hasher.update(data: piece)
        }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    /// The place of a file of a model. A path with ".." or a leading "/" is refused, so a
    /// catalog entry cannot write outside the model's folder.
    func destination(of file: ModelSpeedCatalog.File, model: ModelSpeedCatalog.Model) throws -> URL {
        let parts = file.path.split(separator: "/", omittingEmptySubsequences: false)
        guard !file.path.hasPrefix("/"), !parts.isEmpty, !parts.contains(where: { $0.isEmpty || $0 == "." || $0 == ".." })
        else {
            throw Failure.badPath(file.path)
        }
        return folder.appendingPathComponent(model.id, isDirectory: true).appendingPathComponent(file.path)
    }

    /// True when the file is in place with its size and SHA-256 value.
    func isInPlace(_ file: ModelSpeedCatalog.File, model: ModelSpeedCatalog.Model) throws -> Bool {
        let url = try destination(of: file, model: model)
        guard let size = (try? FileManager.default.attributesOfItem(atPath: url.path))?[.size] as? NSNumber,
            size.int64Value == file.bytes
        else { return false }
        return try Self.sha256(of: url) == file.sha256
    }

    /// Downloads every file of `model` that is not in place. `progress` gets a line per file.
    func download(_ model: ModelSpeedCatalog.Model, progress: @Sendable (String) -> Void) async throws {
        for (index, file) in model.files.enumerated() {
            let target = try destination(of: file, model: model)
            if try isInPlace(file, model: model) {
                progress("\(model.title): file \(index + 1) of \(model.files.count) is in place")
                continue
            }
            progress("\(model.title): downloading file \(index + 1) of \(model.files.count), \(file.bytes / 1_048_576) MB")
            let (temporary, response) = try await session.download(from: file.url)
            defer { try? FileManager.default.removeItem(at: temporary) }
            if let http = response as? HTTPURLResponse, http.statusCode != 200 {
                throw Failure.httpStatus(file: file.path, status: http.statusCode)
            }
            guard let sizeNumber = (try FileManager.default.attributesOfItem(atPath: temporary.path))[.size] as? NSNumber
            else {
                throw ModelSpeedError("\(file.path): the downloaded file has no size")
            }
            let size = sizeNumber.int64Value
            guard size == file.bytes else {
                throw Failure.size(file: file.path, expected: file.bytes, actual: size)
            }
            let actual = try Self.sha256(of: temporary)
            guard actual == file.sha256 else {
                throw Failure.checksum(file: file.path, expected: file.sha256, actual: actual)
            }
            try FileManager.default.createDirectory(
                at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
            if FileManager.default.fileExists(atPath: target.path) {
                try FileManager.default.removeItem(at: target)
            }
            try FileManager.default.moveItem(at: temporary, to: target)
        }
        progress("\(model.title): every file is in place")
    }

    /// Removes the files of a model.
    func remove(_ model: ModelSpeedCatalog.Model) throws {
        let base = folder.appendingPathComponent(model.id, isDirectory: true)
        if FileManager.default.fileExists(atPath: base.path) {
            try FileManager.default.removeItem(at: base)
        }
    }
}
