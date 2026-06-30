import Foundation

struct PreviewResponse: Decodable {
    let generatedAt: String
    let sunnifyParity: String
    let items: [PreviewItem]
    let errors: [PreviewErrorItem]

    enum CodingKeys: String, CodingKey {
        case generatedAt = "generated_at"
        case sunnifyParity = "sunnify_parity"
        case items
        case errors
    }
}

struct PreviewItem: Decodable {
    let url: String
    let kind: String
    let title: String
    let detail: String
    let trackCount: Int
    let coverURL: String
    let outputFolder: String
    let tracks: [PreviewTrack]

    enum CodingKeys: String, CodingKey {
        case url
        case kind
        case title
        case detail
        case trackCount = "track_count"
        case coverURL = "cover_url"
        case outputFolder = "output_folder"
        case tracks
    }
}

struct PreviewTrack: Decodable, Identifiable, Equatable {
    var id: String {
        spotifyID.isEmpty ? "\(position ?? 0)-\(title)-\(artists)" : spotifyID
    }

    let position: Int?
    let title: String
    let artists: String
    let album: String
    let spotifyID: String
    let durationSeconds: Double?
    let coverURL: String

    enum CodingKeys: String, CodingKey {
        case position
        case title
        case artists
        case album
        case spotifyID = "spotify_id"
        case durationSeconds = "duration_seconds"
        case coverURL = "cover_url"
    }
}

struct PreviewErrorItem: Decodable {
    let url: String
    let message: String
}

struct HelperHealthReport: Decodable {
    let ok: Bool
    let generatedAt: String
    let sunnifyParity: String
    let python: String
    let platform: String
    let checks: [HelperHealthCheck]

    enum CodingKeys: String, CodingKey {
        case ok
        case generatedAt = "generated_at"
        case sunnifyParity = "sunnify_parity"
        case python
        case platform
        case checks
    }
}

struct HelperHealthCheck: Decodable, Identifiable {
    var id: String { name }

    let name: String
    let ok: Bool
    let detail: String
}

enum ProgressItemState: String, Codable {
    case queued
    case running
    case succeeded
    case failed
    case skipped
    case cancelled

    var label: String {
        switch self {
        case .queued:
            "Queued"
        case .running:
            "Running"
        case .succeeded:
            "Complete"
        case .failed:
            "Failed"
        case .skipped:
            "Skipped"
        case .cancelled:
            "Cancelled"
        }
    }

    var systemImage: String {
        switch self {
        case .queued:
            "tray"
        case .running:
            "arrow.down.circle.fill"
        case .succeeded:
            "checkmark.circle.fill"
        case .failed:
            "exclamationmark.triangle.fill"
        case .skipped:
            "forward.end.fill"
        case .cancelled:
            "stop.circle.fill"
        }
    }
}

struct DownloadProgressItem: Identifiable, Equatable {
    var id: String
    var index: Int?
    var total: Int?
    var title: String
    var artists: String
    var album: String
    var label: String
    var coverURL: String
    var progress: Double
    var state: ProgressItemState
    var message: String
    var path: String?
    var skipped: Bool

    var displayTitle: String {
        title.isEmpty ? label : title
    }

    var detailText: String {
        if artists.isEmpty {
            return message.isEmpty ? state.label : message
        }
        if message.isEmpty {
            return artists
        }
        return "\(artists) - \(message)"
    }
}

struct DownloadProgressSummary: Equatable {
    var title: String = "Ready"
    var total: Int = 0
    var completed: Int = 0
    var failed: Int = 0
    var skipped: Int = 0
    var progress: Double = 0

    var finished: Int {
        completed + failed + skipped
    }

    var statusText: String {
        guard total > 0 else { return title }
        let failedText = failed > 0 ? ", \(failed) failed" : ""
        let skippedText = skipped > 0 ? ", \(skipped) skipped" : ""
        return "\(finished)/\(total) finished\(failedText)\(skippedText)"
    }
}

struct DownloadProgressEvent: Decodable {
    let event: String
    let key: String?
    let index: Int?
    let total: Int?
    let label: String?
    let title: String?
    let artists: String?
    let album: String?
    let coverURL: String?
    let progress: Double?
    let state: ProgressItemState?
    let message: String?
    let path: String?
    let skipped: Bool?
    let trackCount: Int?
    let selectedCount: Int?
    let okCount: Int?
    let failedCount: Int?
    let outputFolder: String?

    enum CodingKeys: String, CodingKey {
        case event
        case key
        case index
        case total
        case label
        case title
        case artists
        case album
        case coverURL = "cover_url"
        case progress
        case state
        case message
        case path
        case skipped
        case trackCount = "track_count"
        case selectedCount = "selected_count"
        case okCount = "ok_count"
        case failedCount = "failed_count"
        case outputFolder = "output_folder"
    }
}

enum QueueItemState: String {
    case queued
    case previewed
    case running
    case succeeded
    case failed

    var label: String {
        switch self {
        case .queued:
            "Queued"
        case .previewed:
            "Previewed"
        case .running:
            "Running"
        case .succeeded:
            "Complete"
        case .failed:
            "Failed"
        }
    }

    var systemImage: String {
        switch self {
        case .queued:
            "tray"
        case .previewed:
            "doc.text.magnifyingglass"
        case .running:
            "arrow.down.circle.fill"
        case .succeeded:
            "checkmark.circle.fill"
        case .failed:
            "exclamationmark.triangle.fill"
        }
    }
}

struct DownloadQueueItem: Identifiable, Equatable {
    let id: UUID
    var url: String
    var kind: String
    var title: String
    var detail: String
    var trackCount: Int
    var coverURL: String
    var outputFolder: String
    var tracks: [PreviewTrack]
    var state: QueueItemState
    var message: String

    init(url: String) {
        self.id = UUID()
        self.url = url
        self.kind = "url"
        self.title = URL(string: url)?.host ?? url
        self.detail = url
        self.trackCount = 0
        self.coverURL = ""
        self.outputFolder = ""
        self.tracks = []
        self.state = .queued
        self.message = ""
    }

    init(preview: PreviewItem) {
        self.id = UUID()
        self.url = preview.url
        self.kind = preview.kind
        self.title = preview.title
        self.detail = preview.detail
        self.trackCount = preview.trackCount
        self.coverURL = preview.coverURL
        self.outputFolder = preview.outputFolder
        self.tracks = preview.tracks
        self.state = .previewed
        self.message = ""
    }

    init(error: PreviewErrorItem) {
        self.id = UUID()
        self.url = error.url
        self.kind = "error"
        self.title = URL(string: error.url)?.host ?? error.url
        self.detail = error.url
        self.trackCount = 0
        self.coverURL = ""
        self.outputFolder = ""
        self.tracks = []
        self.state = .failed
        self.message = error.message
    }
}
