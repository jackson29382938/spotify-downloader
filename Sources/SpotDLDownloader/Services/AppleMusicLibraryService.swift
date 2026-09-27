import Foundation

enum AppleMusicLibraryKind: String, CaseIterable, Identifiable {
    case playlist, album, song

    var id: String { rawValue }
    var title: String { rawValue.capitalized }
}

struct AppleMusicLibraryItem: Identifiable {
    let kind: AppleMusicLibraryKind
    let id: String
    let title: String
    let detail: String
    let paths: [String]

    var selectionID: String { kind.rawValue + ":" + id }
}

enum AppleMusicLibraryError: LocalizedError {
    case failed(String)

    var errorDescription: String? {
        switch self {
        case .failed(let message): message
        }
    }
}

/// Reads local file tracks from Music. Cloud-only songs have no editable file
/// location, so they are intentionally left out of album and song results.
final class AppleMusicLibraryService {
    private static let supportedExtensions: Set<String> = ["mp3", "m4a", "flac", "opus", "ogg", "wav", "aac"]

    private static func isLocalAudioFile(_ path: String) -> Bool {
        var isDirectory = ObjCBool(false)
        return supportedExtensions.contains(URL(fileURLWithPath: path).pathExtension.lowercased())
            && FileManager.default.fileExists(atPath: path, isDirectory: &isDirectory)
            && !isDirectory.boolValue
    }

    func browse(
        kind: AppleMusicLibraryKind,
        query: String,
        completion: @escaping (Result<[AppleMusicLibraryItem], AppleMusicLibraryError>) -> Void
    ) {
        run(script: Self.browseScript, arguments: [kind.rawValue, query]) { result in
            completion(result.map { Self.parseItems($0, kind: kind) })
        }
    }

    func playlistPaths(
        id: String,
        completion: @escaping (Result<[String], AppleMusicLibraryError>) -> Void
    ) {
        run(script: Self.playlistPathsScript, arguments: [id]) { result in
            completion(result.flatMap { output in
                let rows = output.components(separatedBy: Self.recordSeparator)
                guard rows.first == "FOUND" else {
                    return .failure(.failed("This playlist could not be found in Music. Refresh the list and try again."))
                }
                return .success(Array(rows.dropFirst()).filter(Self.isLocalAudioFile))
            })
        }
    }

    private func run(
        script: String,
        arguments: [String],
        completion: @escaping (Result<String, AppleMusicLibraryError>) -> Void
    ) {
        let process = Process()
        let pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        process.arguments = ["-e", script] + arguments
        process.standardOutput = pipe
        process.standardError = pipe
        do {
            try process.run()
        } catch {
            completion(.failure(.failed("Could not open Music: \(error.localizedDescription)")))
            return
        }
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 60) {
            if process.isRunning { process.terminate() }
        }
        DispatchQueue.global(qos: .userInitiated).async {
            let output = String(decoding: pipe.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
                .trimmingCharacters(in: .whitespacesAndNewlines)
            process.waitUntilExit()
            DispatchQueue.main.async {
                if process.terminationStatus == 0 {
                    completion(.success(output))
                } else {
                    completion(.failure(.failed(output.isEmpty ? "Music did not respond. Check its Automation permission and try again." : output)))
                }
            }
        }
    }

    private static let recordSeparator = "\u{1E}"
    private static let fieldSeparator = "\u{1F}"

    static func parseItems(_ output: String, kind: AppleMusicLibraryKind) -> [AppleMusicLibraryItem] {
        let rows = output.components(separatedBy: recordSeparator)
            .map { $0.components(separatedBy: fieldSeparator) }
        if kind == .playlist {
            return rows.filter { $0.count >= 3 && $0[0] == "P" }.map {
                AppleMusicLibraryItem(kind: .playlist, id: $0[1], title: $0[2], detail: "Playlist", paths: [])
            }.sorted { $0.title.localizedStandardCompare($1.title) == .orderedAscending }
        }
        if kind == .song {
            return rows.filter { $0.count >= 4 && $0[0] == "S" && isLocalAudioFile($0[3]) }.map {
                AppleMusicLibraryItem(kind: .song, id: $0[3], title: $0[1], detail: $0[2], paths: [$0[3]])
            }.sorted { $0.title.localizedStandardCompare($1.title) == .orderedAscending }
        }
        var albums: [String: (title: String, artist: String, paths: [String])] = [:]
        for row in rows where row.count >= 4 && row[0] == "A" && isLocalAudioFile(row[3]) {
            let key = row[1] + fieldSeparator + row[2]
            var album = albums[key] ?? (row[1], row[2], [])
            if !album.paths.contains(row[3]) { album.paths.append(row[3]) }
            albums[key] = album
        }
        return albums.map { key, album in
            AppleMusicLibraryItem(kind: .album, id: key, title: album.title, detail: album.artist, paths: album.paths)
        }.sorted { $0.title.localizedStandardCompare($1.title) == .orderedAscending }
    }

    private static let browseScript = #"""
    on run argv
        set requestedKind to item 1 of argv
        set queryText to item 2 of argv
        set fieldSeparator to ASCII character 31
        set recordSeparator to ASCII character 30
        set outputRows to {}
        tell application "Music"
            if requestedKind is "playlist" then
                repeat with musicPlaylist in (every user playlist whose smart is false and special kind is none)
                    set end of outputRows to "P" & fieldSeparator & (id of musicPlaylist as text) & fieldSeparator & (name of musicPlaylist) & fieldSeparator & ""
                end repeat
            else
                if requestedKind is "album" then
                    set foundTracks to (search library playlist 1 for queryText only albums)
                else
                    set foundTracks to (search library playlist 1 for queryText only songs)
                end if
                repeat with musicTrack in foundTracks
                    try
                        set localPath to POSIX path of (location of musicTrack)
                        if requestedKind is "album" then
                            set albumName to album of musicTrack
                            set albumArtist to album artist of musicTrack
                            if albumArtist is "" then set albumArtist to artist of musicTrack
                            if albumName is not "" then set end of outputRows to "A" & fieldSeparator & albumName & fieldSeparator & albumArtist & fieldSeparator & localPath
                        else
                            set end of outputRows to "S" & fieldSeparator & (name of musicTrack) & fieldSeparator & (artist of musicTrack) & fieldSeparator & localPath
                        end if
                    end try
                end repeat
            end if
        end tell
        set AppleScript's text item delimiters to recordSeparator
        return outputRows as text
    end run
    """#

    private static let playlistPathsScript = #"""
    on run argv
        set requestedID to item 1 of argv
        set recordSeparator to ASCII character 30
        set localPaths to {}
        set foundPlaylist to false
        tell application "Music"
            repeat with musicPlaylist in every user playlist
                if (id of musicPlaylist as text) is requestedID then
                    set foundPlaylist to true
                    repeat with musicTrack in every track of musicPlaylist
                        try
                            set end of localPaths to POSIX path of (location of musicTrack)
                        end try
                    end repeat
                    exit repeat
                end if
            end repeat
        end tell
        if not foundPlaylist then return "MISSING"
        set AppleScript's text item delimiters to recordSeparator
        return "FOUND" & recordSeparator & (localPaths as text)
    end run
    """#
}
