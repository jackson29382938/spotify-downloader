import Foundation
import XCTest
@testable import SpotDLDownloader

final class AppleMusicLibraryServiceTests: XCTestCase {
    func testAlbumResultsGroupLocalSongsAndExcludeUnsupportedFiles() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let first = folder.appendingPathComponent("first.mp3")
        let second = folder.appendingPathComponent("second.m4a")
        let protected = folder.appendingPathComponent("protected.m4p")
        for file in [first, second, protected] { try Data("audio".utf8).write(to: file) }

        let field = "\u{1F}"
        let record = "\u{1E}"
        let output = [first, second, protected].map { "A\(field)Album\(field)Artist\(field)\($0.path)" }
            .joined(separator: record)
        let items = AppleMusicLibraryService.parseItems(output, kind: .album)

        XCTAssertEqual(items.count, 1)
        XCTAssertEqual(Set(items[0].paths), Set([first.path, second.path]))
    }

    func testPlaylistRowsKeepDistinctMusicIDs() {
        let field = "\u{1F}"
        let record = "\u{1E}"
        let output = ["P\(field)1\(field)Favorites\(field)", "P\(field)2\(field)Favorites\(field)"]
            .joined(separator: record)
        let items = AppleMusicLibraryService.parseItems(output, kind: .playlist)

        XCTAssertEqual(items.count, 2)
        XCTAssertEqual(Set(items.map(\.id)), Set(["1", "2"]))
    }
}
