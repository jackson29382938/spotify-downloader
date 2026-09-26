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

    var canImportIntoAppleMusic: Bool {
        switch self {
        case .mp3, .m4a, .wav:
            true
        case .flac, .opus, .ogg:
            false
        }
    }
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

enum CookiesBrowser: String, CaseIterable, Identifiable {
    case none
    case safari
    case chrome
    case firefox
    case edge

    var id: String { rawValue }

    var label: String {
        switch self {
        case .none:
            "Off"
        case .safari:
            "Safari"
        case .chrome:
            "Chrome"
        case .firefox:
            "Firefox"
        case .edge:
            "Edge"
        }
    }

    /// The value passed to `--cookies-browser`, or nil when disabled.
    var flagValue: String? {
        self == .none ? nil : rawValue
    }
}

/// How loosely YouTube uploads are matched to a track (0 = strict, 1 = loose).
enum MatchFlexibility {
    /// Same as the helper's default: the long-standing strict rules.
    static let defaultValue = 0.25

    static func label(for value: Double) -> String {
        switch value {
        case ..<0.15:
            "Strictest"
        case ..<0.4:
            "Strict"
        case ..<0.6:
            "Balanced"
        case ..<0.95:
            "Flexible"
        default:
            "Anything close"
        }
    }

    static func help(for value: Double) -> String {
        switch value {
        case ..<0.4:
            "Title, artist, and length must all agree. Fewest wrong songs; obscure tracks may fail."
        case ..<0.6:
            "Allows longer length differences and titles that match most of their words."
        case ..<0.95:
            "Also accepts uploads that don't name the artist when the title and length agree."
        default:
            "Falls back to the result closest in length. Check results: this can pick the wrong song."
        }
    }
}

/// How lyrics are written into the song's standard lyrics tag.
enum LyricsStyle: String, CaseIterable, Identifiable {
    case plain
    case synced

    var id: String { rawValue }

    var label: String {
        switch self {
        case .plain:
            "Plain text"
        case .synced:
            "Timestamped (LRC)"
        }
    }

    var help: String {
        switch self {
        case .plain:
            "Clean lyrics text, which is what Apple Music shows. MP3s also keep line timing in a hidden SYLT frame for players that use it. Apple Music cannot scroll lyrics for your own files."
        case .synced:
            "Timestamped lines for players that scroll lyrics (Poweramp, MusicBee, foobar2000, Jellyfin, Navidrome). Apple Music shows the [00:12.34] timestamps as plain text."
        }
    }
}

enum ArtworkMaxSize: String, CaseIterable, Identifiable {
    case unlimited
    case px600 = "600"
    case px1200 = "1200"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .unlimited:
            "Original"
        case .px600:
            "600 px"
        case .px1200:
            "1200 px"
        }
    }

    /// The value passed to `--artwork-max-size`.
    var flagValue: String { rawValue }
}

enum Defaults {
    static let testTrackURL = "https://open.spotify.com/track/1gQzzNczLJ05y9KVx40hVU?si=45ba5354a24e4bca"
    static let testVideoURL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    static var downloadsPath: String {
        FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first?.path
            ?? (NSHomeDirectory() + "/Downloads")
    }

    static var musicPath: String {
        FileManager.default.urls(for: .musicDirectory, in: .userDomainMask).first?.path
            ?? (NSHomeDirectory() + "/Music")
    }

    static var logsPath: String {
        NSHomeDirectory() + "/Library/Logs/Spotify Downloader"
    }

    static var appSupportPath: String {
        NSHomeDirectory() + "/Library/Application Support/Spotify Downloader"
    }

    static var historyPath: String {
        appSupportPath + "/download-history.jsonl"
    }

    static var ffmpegInstallPath: String {
        appSupportPath + "/bin/ffmpeg"
    }

    static let defaultRenamePattern = "{track_number}. {title} - {artist}"
    static let appleMusicPlaylistName = "Spotify Downloads"
}
