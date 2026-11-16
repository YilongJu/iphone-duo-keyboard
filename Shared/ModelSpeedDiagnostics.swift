import Foundation
import MetricKit

/// Receives the diagnostics that MetricKit delivers after the process ended in an abnormal way
/// (a crash, a hang, a memory limit), and keeps one line per diagnostic in `file`. iOS delivers
/// them at a later launch, so the next "duo:speed" shows why an earlier run stopped. iOS 27
/// delivers a memory exception diagnostic when an app extension passes its memory limit.
final class ModelSpeedDiagnostics: NSObject, MXMetricManagerSubscriber {
    let file: URL
    private let lock = NSLock()

    init(file: URL) {
        self.file = file
        super.init()
    }

    /// Subscribes, and keeps the diagnostics that iOS delivered before this launch.
    func start() {
        MXMetricManager.shared.add(self)
        record(MXMetricManager.shared.pastDiagnosticPayloads)
    }

    func didReceive(_ payloads: [MXDiagnosticPayload]) {
        record(payloads)
    }

    private func record(_ payloads: [MXDiagnosticPayload]) {
        let lines = payloads.flatMap { Self.lines(fromJSON: $0.jsonRepresentation()) }
        guard !lines.isEmpty else { return }
        lock.lock()
        defer { lock.unlock() }
        do {
            try Self.append(lines, to: file)
        } catch {
            ModelSpeedTest.logger.error("the diagnostics file: \(String(describing: error), privacy: .public)")
        }
    }

    /// Adds the lines that the file does not hold yet. MetricKit hands out the past payloads again
    /// at each launch.
    static func append(_ lines: [String], to file: URL) throws {
        let known = try saved(file)
        let new = lines.filter { !known.contains($0) }
        guard !new.isEmpty else { return }
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try (known + new).joined(separator: "\n").appending("\n").write(to: file, atomically: true, encoding: .utf8)
    }

    /// The lines in the file, or none when the file does not exist.
    static func saved(_ file: URL) throws -> [String] {
        guard FileManager.default.fileExists(atPath: file.path) else { return [] }
        return try String(contentsOf: file, encoding: .utf8).split(separator: "\n").map(String.init)
    }

    /// One line per diagnostic of a payload: its kind, the end of the payload's time span, and
    /// the plain values of its metadata, such as the exception type, the signal or the
    /// termination reason. The call stacks are left out.
    static func lines(fromJSON data: Data) -> [String] {
        guard let payload = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
            return ["diagnostic  a MetricKit payload that is not a JSON object"]
        }
        let end = payload["timeStampEnd"].map { "\($0)" } ?? "an unknown time"
        var lines: [String] = []
        for key in payload.keys.sorted() where key.hasSuffix("Diagnostics") {
            guard let items = payload[key] as? [[String: Any]] else { continue }
            for item in items {
                let metadata = item["diagnosticMetaData"] as? [String: Any] ?? [:]
                let values = metadata.keys.sorted().compactMap { name -> String? in
                    let value = metadata[name]
                    if value is [Any] || value is [String: Any] { return nil }
                    return "\(name) \(value.map { "\($0)" } ?? "none")"
                }
                lines.append("diagnostic  \(key) up to \(end): " + values.joined(separator: ", "))
            }
        }
        return lines
    }
}
