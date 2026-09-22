import Foundation

struct AppleMusicImportResult {
    let playlistName: String
    let addedCount: Int
    let failedCount: Int
}

enum AppleMusicImportError: LocalizedError {
    case noCompatibleFiles
    case automationPermissionDenied
    case launchFailed(String)
    case importFailed(String)
    case invalidResponse

    var errorDescription: String? {
        switch self {
        case .noCompatibleFiles:
            "No Apple Music-compatible audio files were completed. Use MP3, M4A, or WAV."
        case .automationPermissionDenied:
            "Allow Spotify Downloader to control Music in System Settings › Privacy & Security › Automation, then try again."
        case .launchFailed(let details):
            "Could not open Apple Music: \(details)"
        case .importFailed(let details):
            details.isEmpty ? "Apple Music could not import the downloaded files." : details
        case .invalidResponse:
            "Apple Music finished importing, but the app could not read the result."
        }
    }
}

final class AppleMusicService {
    private static let compatibleExtensions = Set(["mp3", "m4a", "wav"])

    func addToNewPlaylist(
        filePaths: [String],
        playlistBaseName: String,
        completion: @escaping (Result<AppleMusicImportResult, AppleMusicImportError>) -> Void
    ) {
        let compatiblePaths = uniqueCompatiblePaths(from: filePaths)
        guard compatiblePaths.isEmpty == false else {
            completion(.failure(.noCompatibleFiles))
            return
        }

        let requestedName = playlistBaseName.trimmingCharacters(in: .whitespacesAndNewlines)
        let baseName = requestedName.isEmpty ? Defaults.appleMusicPlaylistName : requestedName
        let process = Process()
        let outputPipe = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        process.arguments = ["-e", Self.importScript, baseName] + compatiblePaths
        process.standardOutput = outputPipe
        process.standardError = outputPipe

        process.terminationHandler = { process in
            let data = outputPipe.fileHandleForReading.readDataToEndOfFile()
            let output = String(data: data, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""

            guard process.terminationStatus == 0 else {
                let normalizedOutput = output.lowercased()
                if normalizedOutput.contains("-1743") || normalizedOutput.contains("not authorized") {
                    completion(.failure(.automationPermissionDenied))
                } else {
                    completion(.failure(.importFailed(output)))
                }
                return
            }

            let fields = output.components(separatedBy: "\t")
            guard fields.count >= 3,
                  let addedCount = Int(fields[fields.count - 2]),
                  let failedCount = Int(fields[fields.count - 1]) else {
                completion(.failure(.invalidResponse))
                return
            }
            completion(
                .success(
                    AppleMusicImportResult(
                        playlistName: fields.dropLast(2).joined(separator: "\t"),
                        addedCount: addedCount,
                        failedCount: failedCount
                    )
                )
            )
        }

        do {
            try process.run()
        } catch {
            completion(.failure(.launchFailed(error.localizedDescription)))
        }
    }

    private func uniqueCompatiblePaths(from filePaths: [String]) -> [String] {
        var seen = Set<String>()
        return filePaths.compactMap { path in
            let standardizedPath = URL(fileURLWithPath: path).standardizedFileURL.path
            let pathExtension = URL(fileURLWithPath: standardizedPath).pathExtension.lowercased()
            guard Self.compatibleExtensions.contains(pathExtension),
                  FileManager.default.fileExists(atPath: standardizedPath),
                  seen.insert(standardizedPath).inserted else {
                return nil
            }
            return standardizedPath
        }
    }

    private static let importScript = #"""
    on run argv
        set requestedName to item 1 of argv
        set filePaths to items 2 thru (count argv) of argv

        tell application "Music"
            set playlistName to requestedName
            set suffixNumber to 2
            repeat while exists user playlist playlistName
                set playlistName to requestedName & " " & suffixNumber
                set suffixNumber to suffixNumber + 1
            end repeat

            set newPlaylist to make new user playlist with properties {name:playlistName}
            set addedCount to 0
            set failedCount to 0
            repeat with filePath in filePaths
                try
                    add (POSIX file (contents of filePath) as alias) to newPlaylist
                    set addedCount to addedCount + 1
                on error
                    set failedCount to failedCount + 1
                end try
            end repeat

            if addedCount is 0 then
                delete newPlaylist
                error "Apple Music could not import any of the downloaded files."
            end if

            activate
            return playlistName & tab & addedCount & tab & failedCount
        end tell
    end run
    """#
}
