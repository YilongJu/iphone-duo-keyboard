import XCTest

@testable import DuoKeyboard

/// Answers the requests of a test session from a table, so the downloader never reaches the network.
final class StubURLProtocol: URLProtocol {
    nonisolated(unsafe) static var answers: [URL: (status: Int, body: Data)] = [:]
    nonisolated(unsafe) static var requested: [URL] = []

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let url = request.url, let answer = Self.answers[url] else {
            client?.urlProtocol(self, didFailWithError: URLError(.fileDoesNotExist))
            return
        }
        Self.requested.append(url)
        let response = HTTPURLResponse(url: url, statusCode: answer.status, httpVersion: "HTTP/1.1", headerFields: nil)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: answer.body)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

final class ModelSpeedDownloaderTests: XCTestCase {
    private var folder: URL!
    private var downloader: ModelSpeedDownloader!

    override func setUpWithError() throws {
        folder = FileManager.default.temporaryDirectory.appendingPathComponent("speed-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubURLProtocol.self]
        downloader = ModelSpeedDownloader(session: URLSession(configuration: configuration), folder: folder)
        StubURLProtocol.answers = [:]
        StubURLProtocol.requested = []
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: folder)
    }

    private func sha256(_ data: Data) throws -> String {
        let url = folder.appendingPathComponent("hash-\(UUID().uuidString)")
        try data.write(to: url)
        defer { try? FileManager.default.removeItem(at: url) }
        return try ModelSpeedDownloader.sha256(of: url)
    }

    /// A model of one file per entry, each served by the stub with status 200.
    private func model(_ files: [(path: String, body: Data)]) throws -> ModelSpeedCatalog.Model {
        var entries: [ModelSpeedCatalog.File] = []
        for (index, file) in files.enumerated() {
            let url = URL(string: "https://example.test/file\(index)")!
            StubURLProtocol.answers[url] = (200, file.body)
            entries.append(ModelSpeedCatalog.File(
                path: file.path, url: url, sha256: try sha256(file.body), bytes: Int64(file.body.count)))
        }
        return ModelSpeedCatalog.Model(id: "test-model", title: "Test model", files: entries)
    }

    private func contents(_ path: String) -> Data? {
        FileManager.default.contents(atPath: folder.appendingPathComponent("test-model").appendingPathComponent(path).path)
    }

    func testTheSHA256ValueOfAKnownText() throws {
        // The value of "abc" from FIPS 180-2, appendix B.1.
        XCTAssertEqual(
            try sha256(Data("abc".utf8)), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
    }

    func testEveryFileWithItsChecksumLandsInItsPlace() async throws {
        let model = try model([
            ("model.mlmodelc/model.mil", Data("program".utf8)),
            ("model.mlmodelc/weights/weight.bin", Data(repeating: 7, count: 5000)),
        ])
        try await downloader.download(model) { _ in }
        XCTAssertEqual(contents("model.mlmodelc/model.mil"), Data("program".utf8))
        XCTAssertEqual(contents("model.mlmodelc/weights/weight.bin"), Data(repeating: 7, count: 5000))
        XCTAssertTrue(ModelSpeedRun.present(model, in: folder))
    }

    func testAWrongChecksumLeavesNoFile() async throws {
        let good = try model([("model.gguf", Data("the right bytes".utf8))])
        let file = good.files[0]
        // The server sends other bytes of the same length.
        StubURLProtocol.answers[file.url] = (200, Data("the wrong bytes".utf8))
        do {
            try await downloader.download(good) { _ in }
            XCTFail("a file with another SHA-256 value was accepted")
        } catch let failure as ModelSpeedDownloader.Failure {
            guard case .checksum(let path, let expected, _) = failure else { return XCTFail("\(failure)") }
            XCTAssertEqual(path, "model.gguf")
            XCTAssertEqual(expected, file.sha256)
        }
        XCTAssertNil(contents("model.gguf"))
        XCTAssertFalse(ModelSpeedRun.present(good, in: folder))
    }

    func testAWrongSizeIsRefused() async throws {
        let good = try model([("model.gguf", Data("twelve bytes".utf8))])
        StubURLProtocol.answers[good.files[0].url] = (200, Data("short".utf8))
        do {
            try await downloader.download(good) { _ in }
            XCTFail("a file of another size was accepted")
        } catch let failure as ModelSpeedDownloader.Failure {
            XCTAssertEqual(failure, .size(file: "model.gguf", expected: 12, actual: 5))
        }
        XCTAssertNil(contents("model.gguf"))
    }

    func testAnAnswerOtherThan200IsRefused() async throws {
        let good = try model([("model.gguf", Data("body".utf8))])
        StubURLProtocol.answers[good.files[0].url] = (404, Data("body".utf8))
        do {
            try await downloader.download(good) { _ in }
            XCTFail("an answer with status 404 was accepted")
        } catch let failure as ModelSpeedDownloader.Failure {
            XCTAssertEqual(failure, .httpStatus(file: "model.gguf", status: 404))
        }
        XCTAssertNil(contents("model.gguf"))
    }

    func testAFileInPlaceIsKeptWithoutARequest() async throws {
        let body = Data("already here".utf8)
        let model = try model([("model.gguf", body)])
        let target = folder.appendingPathComponent("test-model/model.gguf")
        try FileManager.default.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
        try body.write(to: target)
        try await downloader.download(model) { _ in }
        XCTAssertEqual(StubURLProtocol.requested, [])
        XCTAssertEqual(contents("model.gguf"), body)
    }

    func testAFileInPlaceWithOtherBytesIsDownloadedAgain() async throws {
        let body = Data("the new bytes".utf8)
        let model = try model([("model.gguf", body)])
        let target = folder.appendingPathComponent("test-model/model.gguf")
        try FileManager.default.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("the old bytes".utf8).write(to: target)
        try await downloader.download(model) { _ in }
        XCTAssertEqual(StubURLProtocol.requested, [model.files[0].url])
        XCTAssertEqual(contents("model.gguf"), body)
    }

    func testAPathOutsideTheModelFolderIsRefused() throws {
        for path in ["../escape.gguf", "/absolute.gguf", "model.mlmodelc/../../escape", "a//b"] {
            let file = ModelSpeedCatalog.File(path: path, url: URL(string: "https://example.test/x")!, sha256: "", bytes: 0)
            let model = ModelSpeedCatalog.Model(id: "test-model", title: "Test model", files: [file])
            XCTAssertThrowsError(try downloader.destination(of: file, model: model), path)
        }
    }
}
