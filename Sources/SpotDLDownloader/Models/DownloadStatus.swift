import Foundation

enum DownloadStatus: Equatable {
    case idle
    case checking
    case ready(version: String)
    case missingDependency(String)
    case running(startedAt: Date)
    case repairing(startedAt: Date)
    case succeeded
    case failed(code: Int32)
    case cancelled

    var title: String {
        switch self {
        case .idle:
            "Idle"
        case .checking:
            "Checking downloader"
        case .ready(let version):
            "Ready: \(version)"
        case .missingDependency:
            "Missing dependency"
        case .running:
            "Downloading"
        case .repairing:
            "Repairing Library"
        case .succeeded:
            "Complete"
        case .failed(let code):
            "Failed: exit \(code)"
        case .cancelled:
            "Cancelled"
        }
    }

    var systemImage: String {
        switch self {
        case .idle:
            "circle"
        case .checking:
            "clock"
        case .ready:
            "checkmark.circle.fill"
        case .missingDependency:
            "exclamationmark.triangle.fill"
        case .running:
            "arrow.down.circle.fill"
        case .repairing:
            "wand.and.sparkles"
        case .succeeded:
            "checkmark.seal.fill"
        case .failed:
            "xmark.octagon.fill"
        case .cancelled:
            "stop.circle.fill"
        }
    }

    var isRunning: Bool {
        if case .running = self {
            return true
        }
        if case .repairing = self {
            return true
        }
        return false
    }
}
