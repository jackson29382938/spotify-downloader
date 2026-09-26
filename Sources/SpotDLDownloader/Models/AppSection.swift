import Foundation

/// Top-level destinations shown in the sidebar. Each one is its own page
/// instead of a card in one long scrolling column.
enum AppSection: String, CaseIterable, Identifiable, Hashable {
    case download
    case queue
    case history
    case library
    case diagnostics

    var id: String { rawValue }

    var title: String {
        switch self {
        case .download:
            "Download"
        case .queue:
            "Preview Queue"
        case .history:
            "History"
        case .library:
            "Library Tools"
        case .diagnostics:
            "Diagnostics"
        }
    }

    var systemImage: String {
        switch self {
        case .download:
            "arrow.down.circle"
        case .queue:
            "list.bullet.rectangle"
        case .history:
            "clock.arrow.circlepath"
        case .library:
            "wand.and.sparkles"
        case .diagnostics:
            "stethoscope"
        }
    }
}
