import Foundation

extension FileManager {
    func createDirectoryIfNeeded(atPath path: String) {
        guard fileExists(atPath: path) == false else { return }
        try? createDirectory(
            at: URL(fileURLWithPath: path),
            withIntermediateDirectories: true
        )
    }
}
