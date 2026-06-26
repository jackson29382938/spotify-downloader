import Foundation

struct DownloadCommand {
    var queries: [String]
    var outputFolder: String
    var mediaKind: MediaKind
    var threads: Int
    var format: AudioFormat
    var bitrate: Bitrate
    var overwrite: ExistingFileBehavior
    var trackNumberPrefix: Bool
    var allowClosestMatch: Bool
    var debugLogging: Bool

    var displayString: String {
        arguments.map { value in
            value.contains(" ") ? "\"\(value)\"" : value
        }.joined(separator: " ")
    }

    var arguments: [String] {
        var values = ProjectPaths.downloaderInvocationPrefix + [
            "download",
            "--media", mediaKind.rawValue,
            "--threads", "\(max(1, threads))",
            "--format", format.rawValue,
            "--bitrate", bitrate.rawValue,
            "--overwrite", overwrite.rawValue,
            "--output-dir", URL(fileURLWithPath: outputFolder).standardizedFileURL.path
        ]

        if !trackNumberPrefix {
            values.append("--no-track-number-prefix")
        }

        if allowClosestMatch {
            values.append("--allow-closest-match")
        }

        if debugLogging {
            values.append("--debug-log")
        }

        return values + queries
    }
}
