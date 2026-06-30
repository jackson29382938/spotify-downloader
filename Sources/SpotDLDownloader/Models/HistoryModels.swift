import Foundation

/// One recorded download session, matching the JSONL schema written by the
/// Python helper's `append_history`.
struct HistoryEntry: Decodable, Identifiable {
    let id: UUID
    let timestamp: String
    let sourceURL: String
    let media: String
    let format: String
    let bitrate: String
    let outputFolder: String
    let okCount: Int
    let failedCount: Int
    let failed: [String]

    enum CodingKeys: String, CodingKey {
        case timestamp
        case sourceURL = "source_url"
        case media
        case format
        case bitrate
        case outputFolder = "output_folder"
        case okCount = "ok_count"
        case failedCount = "failed_count"
        case failed
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = UUID()
        timestamp = try container.decodeIfPresent(String.self, forKey: .timestamp) ?? ""
        sourceURL = try container.decodeIfPresent(String.self, forKey: .sourceURL) ?? ""
        media = try container.decodeIfPresent(String.self, forKey: .media) ?? "audio"
        format = try container.decodeIfPresent(String.self, forKey: .format) ?? ""
        bitrate = try container.decodeIfPresent(String.self, forKey: .bitrate) ?? ""
        outputFolder = try container.decodeIfPresent(String.self, forKey: .outputFolder) ?? ""
        okCount = try container.decodeIfPresent(Int.self, forKey: .okCount) ?? 0
        failedCount = try container.decodeIfPresent(Int.self, forKey: .failedCount) ?? 0
        failed = try container.decodeIfPresent([String].self, forKey: .failed) ?? []
    }

    /// A human-friendly timestamp parsed from the ISO-8601 string.
    var displayDate: String {
        let isoFormatter = ISO8601DateFormatter()
        isoFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let date = isoFormatter.date(from: timestamp)
            ?? ISO8601DateFormatter().date(from: timestamp)
        guard let date else { return timestamp }
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .short
        return formatter.string(from: date)
    }

    var summary: String {
        let failedText = failedCount > 0 ? " · \(failedCount) failed" : ""
        return "\(okCount) downloaded\(failedText)"
    }

    var isVideo: Bool { media == "video" }
}
