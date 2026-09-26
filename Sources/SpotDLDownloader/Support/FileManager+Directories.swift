import Foundation

extension FileManager {
    /// Creates the folder (and any parents) when it is missing. Throws when the
    /// folder cannot be created, or when a file already sits at that path.
    func createDirectoryIfNeeded(atPath path: String) throws {
        var isDirectory = ObjCBool(false)
        if fileExists(atPath: path, isDirectory: &isDirectory) {
            guard isDirectory.boolValue else {
                throw CocoaError(.fileWriteFileExists, userInfo: [NSFilePathErrorKey: path])
            }
            return
        }
        try createDirectory(at: URL(fileURLWithPath: path), withIntermediateDirectories: true)
    }
}
