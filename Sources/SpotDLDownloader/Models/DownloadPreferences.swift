import Foundation

enum MediaKind: String, CaseIterable, Identifiable {
    case audio
    case video

    var id: String { rawValue }

    var label: String {
        switch self {
        case .audio:
            "Audio"
        case .video:
            "YouTube Video"
        }
    }

    var systemImage: String {
        switch self {
        case .audio:
            "music.note"
        case .video:
            "video"
        }
    }
}

enum AudioFormat: String, CaseIterable, Identifiable {
    case mp3
    case m4a
    case flac
    case opus
    case ogg
    case wav

    var id: String { rawValue }
}

enum Bitrate: String, CaseIterable, Identifiable {
    case auto
    case kbps320 = "320k"
    case kbps256 = "256k"
    case kbps192 = "192k"
    case kbps160 = "160k"
    case kbps128 = "128k"
    case disable

    var id: String { rawValue }

    var label: String {
        switch self {
        case .auto:
            "Auto"
        case .disable:
            "Disable"
        default:
            rawValue
        }
    }
}

enum ExistingFileBehavior: String, CaseIterable, Identifiable {
    case skip
    case metadata
    case force

    var id: String { rawValue }

    var label: String {
        switch self {
        case .skip:
            "Skip"
        case .metadata:
            "Metadata"
        case .force:
            "Replace"
        }
    }
}

enum Defaults {
    static let testTrackURL = "https://open.spotify.com/track/1gQzzNczLJ05y9KVx40hVU?si=45ba5354a24e4bca"
    static let testVideoURL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    static var downloadsPath: String {
        FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first?.path
            ?? (NSHomeDirectory() + "/Downloads")
    }

    static var logsPath: String {
        NSHomeDirectory() + "/Library/Logs/Spotify Downloader"
    }
}
