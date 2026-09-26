import Foundation

struct AppleMusicImportResult {
    let playlistName: String
    /// True when songs went into a playlist that already had this exact name.
    let reusedExistingPlaylist: Bool
    let addedCount: Int
    let failedCount: Int
    /// Songs that were already in the existing playlist and were not added twice.
    let alreadyPresentCount: Int
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

    /// Adds files to the playlist with exactly this name, creating it only
    /// when no such playlist exists yet.
    func addToPlaylist(
        filePaths: [String],
        playlistName: String,
        completion: @escaping (Result<AppleMusicImportResult, AppleMusicImportError>) -> Void
    ) {
        let compatiblePaths = uniqueCompatiblePaths(from: filePaths)
        guard compatiblePaths.isEmpty == false else {
            completion(.failure(.noCompatibleFiles))
            return
        }

        let requestedName = playlistName.trimmingCharacters(in: .whitespacesAndNewlines)
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

            // name <tab> created|existing <tab> added <tab> failed <tab> already present
            let fields = output.components(separatedBy: "\t")
            guard fields.count >= 5,
                  let addedCount = Int(fields[fields.count - 3]),
                  let failedCount = Int(fields[fields.count - 2]),
                  let alreadyPresentCount = Int(fields[fields.count - 1]) else {
                completion(.failure(.invalidResponse))
                return
            }
            completion(
                .success(
                    AppleMusicImportResult(
                        playlistName: fields.dropLast(4).joined(separator: "\t"),
                        reusedExistingPlaylist: fields[fields.count - 4] == "existing",
                        addedCount: addedCount,
                        failedCount: failedCount,
                        alreadyPresentCount: alreadyPresentCount
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

    /// Names of the user's regular playlists. Returns an empty list without
    /// launching Music when it is not already open.
    func existingPlaylistNames(completion: @escaping ([String]) -> Void) {
        let process = Process()
        let outputPipe = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        process.arguments = ["-e", Self.playlistNamesScript]
        process.standardOutput = outputPipe
        process.standardError = FileHandle.nullDevice
        process.terminationHandler = { process in
            let data = outputPipe.fileHandleForReading.readDataToEndOfFile()
            guard process.terminationStatus == 0 else {
                completion([])
                return
            }
            let names = String(decoding: data, as: UTF8.self)
                .components(separatedBy: .newlines)
                .filter { $0.isEmpty == false }
            completion(names)
        }
        do {
            try process.run()
        } catch {
            completion([])
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

    private static let playlistNamesScript = #"""
    if application "Music" is running then
        tell application "Music"
            try
                set playlistNames to name of every user playlist whose smart is false and special kind is none
            on error
                set playlistNames to name of every user playlist
            end try
        end tell
        set AppleScript's text item delimiters to linefeed
        return playlistNames as text
    end if
    return ""
    """#

    private static let importScript = #"""
    on run argv
        set requestedName to item 1 of argv
        set filePaths to items 2 thru (count argv) of argv

        tell application "Music"
            -- Reuse a regular playlist with exactly this name (case-sensitive).
            try
                set candidates to every user playlist whose name is requestedName and smart is false and special kind is none
            on error
                set candidates to every user playlist whose name is requestedName
            end try
            set targetPlaylist to missing value
            considering case
                repeat with candidate in candidates
                    if (name of candidate) is requestedName then
                        set targetPlaylist to contents of candidate
                        exit repeat
                    end if
                end repeat
            end considering

            set reusedPlaylist to targetPlaylist is not missing value
            set existingPaths to {}
            if reusedPlaylist then
                try
                    repeat with trackLocation in (get location of every file track of targetPlaylist)
                        try
                            set end of existingPaths to POSIX path of (contents of trackLocation)
                        end try
                    end repeat
                end try
            else
                set targetPlaylist to make new user playlist with properties {name:requestedName}
            end if

            set addedCount to 0
            set failedCount to 0
            set presentCount to 0
            repeat with filePath in filePaths
                set posixPath to contents of filePath
                if existingPaths contains posixPath then
                    set presentCount to presentCount + 1
                else
                    try
                        add (POSIX file posixPath as alias) to targetPlaylist
                        set addedCount to addedCount + 1
                    on error
                        set failedCount to failedCount + 1
                    end try
                end if
            end repeat

            if addedCount is 0 and presentCount is 0 then
                if not reusedPlaylist then delete targetPlaylist
                error "Apple Music could not import any of the downloaded files."
            end if

            if reusedPlaylist then
                set playlistState to "existing"
            else
                set playlistState to "created"
            end if
            activate
            return (name of targetPlaylist) & tab & playlistState & tab & addedCount & tab & failedCount & tab & presentCount
        end tell
    end run
    """#
}
