import Foundation
import XCTest
@testable import SpotDLDownloader

final class DownloadServiceTests: XCTestCase {
    func testOutputLinesPreserveUtf8AcrossReadBoundaries() {
        var lines = ProcessOutputLines()
        let bytes = Data("Café\nlast".utf8)

        XCTAssertEqual(lines.append(Data(bytes.prefix(4))), [])
        XCTAssertEqual(lines.append(Data(bytes.dropFirst(4))), ["Café\n"])
        XCTAssertEqual(lines.finish(), "last")
    }

    func testOneShotDrainsLargeOutputBeforeWaitingForExit() {
        let finished = expectation(description: "large helper output finishes")
        let service = DownloadService()
        service.runOneShot(arguments: ["/bin/sh", "-c", "printf '%0100000d' 0"]) { result in
            switch result {
            case .success(let output):
                XCTAssertEqual(output.count, 100_000)
            case .failure(let error):
                XCTFail(error.localizedDescription)
            }
            finished.fulfill()
        }
        wait(for: [finished], timeout: 5)
    }

    func testOneShotKeepsStderrOutOfJsonStdout() {
        let finished = expectation(description: "helper output finishes")
        let service = DownloadService()
        service.runOneShot(arguments: ["/bin/sh", "-c", "printf 'progress\\n' >&2; printf '{\"ok\":true}\\n'"]) { result in
            switch result {
            case .success(let output):
                XCTAssertEqual(output.trimmingCharacters(in: .whitespacesAndNewlines), "{\"ok\":true}")
            case .failure(let error):
                XCTFail(error.localizedDescription)
            }
            finished.fulfill()
        }
        wait(for: [finished], timeout: 5)
    }
}
