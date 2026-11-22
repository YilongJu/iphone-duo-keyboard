import UIKit
import XCTest

@testable import DuoKeyboard

/// The page "What's new" of the app reads docs/changelog.md.
@MainActor
final class ChangelogTests: XCTestCase {
    private let sample = [
        "# Changelog",
        "",
        "This file lists the builds.",
        "",
        "## Build 12",
        "",
        "**What you notice**",
        "",
        "- The first point runs over",
        "  two lines with `code` in it.",
        "- A second point with a [link](other.md).",
        "",
        "## Build 11",
        "",
        "Commit `abc1234`, uploaded 2026-11-18 09:57 UTC.",
        "",
        "**Behind it**",
        "",
        "- A table follows.",
        "",
        "  | Order | Saved |",
        "  | --- | --- |",
        "  | Engine | 47.4% |",
        "",
        "  One sentence about the table.",
    ].joined(separator: "\n")

    func testTheParserReadsBuildsHeadingsBulletsAndTables() {
        let entries = Changelog.entries(of: sample)
        XCTAssertEqual(entries, [
            ChangelogEntry(build: 12, detail: nil, blocks: [
                .heading("What you notice"),
                .bullet("The first point runs over two lines with `code` in it."),
                .bullet("A second point with a [link](other.md)."),
            ]),
            ChangelogEntry(build: 11, detail: "Commit `abc1234`, uploaded 2026-11-18 09:57 UTC.", blocks: [
                .heading("Behind it"),
                .bullet("A table follows."),
                .table([["Order", "Saved"], ["Engine", "47.4%"]]),
                .paragraph("One sentence about the table."),
            ]),
        ])
    }

    func testALineIsCutIntoPlainBoldAndCodeSpans() {
        XCTAssertEqual(
            Changelog.spans(of: "The **bold** word, `code` and a [link](docs/x.md)."),
            [.plain("The "), .bold("bold"), .plain(" word, "), .code("code"), .plain(" and a link.")])
        // A sign without its partner stays as text.
        XCTAssertEqual(Changelog.spans(of: "5 * 3 and a ` alone"), [.plain("5 * 3 and a ` alone")])
    }

    func testThePageMarksTheInstalledBuild() {
        let entries = Changelog.entries(of: sample)
        let text = ChangelogViewController.text(of: entries, installedBuild: 11).string
        XCTAssertTrue(text.hasPrefix("Build 12\n"), text)
        XCTAssertTrue(text.contains("Build 11  installed\n"), text)
        XCTAssertFalse(text.contains("Build 12  installed"), text)
        // The marks of the file do not show, and the text of a link does.
        XCTAssertTrue(text.contains("\u{2022}\tThe first point runs over two lines with code in it.\n"), text)
        XCTAssertTrue(text.contains("A second point with a link.\n"), text)
        XCTAssertTrue(text.contains("Commit abc1234, uploaded 2026-11-18 09:57 UTC.\n"), text)
        XCTAssertTrue(text.contains("Engine  \u{00B7}  47.4%\n"), text)
        XCTAssertFalse(text.contains("**"), text)
        XCTAssertFalse(text.contains("---"), text)
    }

    func testTheAppHoldsTheChangelogWithItsNewestBuildFirst() throws {
        let entries = Changelog.bundled()
        XCTAssertGreaterThanOrEqual(entries.count, 14)
        // The builds count down without a gap, and every entry says what the person notices.
        for (entry, next) in zip(entries, entries.dropFirst()) {
            XCTAssertEqual(entry.build, next.build + 1)
        }
        for entry in entries {
            XCTAssertEqual(entry.blocks.first, .heading("What you notice"), "build \(entry.build)")
            XCTAssertTrue(entry.blocks.contains { if case .bullet = $0 { return true } else { return false } }, "build \(entry.build)")
        }
        // Every build before the newest one names its commit and its upload time.
        for entry in entries.dropFirst() {
            XCTAssertNotNil(entry.detail, "build \(entry.build)")
        }
        let page = ChangelogViewController(entries: entries, installedBuild: entries[0].build)
        page.loadViewIfNeeded()
        XCTAssertEqual(page.title, "What's new")
    }
}
