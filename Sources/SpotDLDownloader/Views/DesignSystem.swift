import ImageIO
import SwiftUI

/// Shared visual tokens so every panel uses the same rhythm, radius, and materials.
enum Theme {
    static let cornerRadius: CGFloat = 16
    static let innerRadius: CGFloat = 10
    static let cardPadding: CGFloat = 20
    static let sectionSpacing: CGFloat = 20
    static let contentMaxWidth: CGFloat = 980

    static let accent = adaptive(light: 0x14745B, dark: 0x73D8B5)
    static let canvas = adaptive(light: 0xF3F4F1, dark: 0x191D1C)
    static let surface = adaptive(light: 0xFDFEFC, dark: 0x232826)
    static let inset = adaptive(light: 0xF1F4F0, dark: 0x1B201E)
    static let border = adaptive(light: 0xDDE3DD, dark: 0x39413C)

    private static func adaptive(light: UInt32, dark: UInt32) -> Color {
        Color(nsColor: NSColor(name: nil) { appearance in
            let value = appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? dark : light
            return NSColor(
                red: CGFloat((value >> 16) & 0xff) / 255,
                green: CGFloat((value >> 8) & 0xff) / 255,
                blue: CGFloat(value & 0xff) / 255,
                alpha: 1
            )
        })
    }
}

/// A consistent container for every section in the main panel.
struct Card<Content: View>: View {
    var padding: CGFloat = Theme.cardPadding
    @ViewBuilder var content: () -> Content

    var body: some View {
        content()
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.cornerRadius))
            .overlay {
                RoundedRectangle(cornerRadius: Theme.cornerRadius)
                    .stroke(Theme.border.opacity(0.8), lineWidth: 1)
            }
            .shadow(color: .black.opacity(0.025), radius: 8, y: 3)
    }
}

/// A uniform titled header with an optional leading icon and trailing accessory.
struct SectionHeader<Trailing: View>: View {
    let title: String
    var systemImage: String?
    @ViewBuilder var trailing: () -> Trailing

    init(
        _ title: String,
        systemImage: String? = nil,
        @ViewBuilder trailing: @escaping () -> Trailing
    ) {
        self.title = title
        self.systemImage = systemImage
        self.trailing = trailing
    }

    var body: some View {
        HStack(spacing: 8) {
            if let systemImage {
                Image(systemName: systemImage)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Theme.accent)
                    .frame(width: 28, height: 28)
                    .background(Theme.accent.opacity(0.09), in: RoundedRectangle(cornerRadius: 8))
            }
            Text(title)
                .font(.headline)
            Spacer(minLength: 8)
            trailing()
        }
    }
}

extension SectionHeader where Trailing == EmptyView {
    init(_ title: String, systemImage: String? = nil) {
        self.init(title, systemImage: systemImage) { EmptyView() }
    }
}

/// A labeled control with a caption used across the settings and library panels.
struct SettingBlock<Content: View>: View {
    let title: String
    let help: String
    @ViewBuilder var content: () -> Content

    init(_ title: String, help: String, @ViewBuilder content: @escaping () -> Content) {
        self.title = title
        self.help = help
        self.content = content
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .fixedSize(horizontal: true, vertical: false)
            content()
            Text(help)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: 220, alignment: .leading)
        }
    }
}

/// Compact status pill reused by the progress and activity headers.
struct StatusBadge: View {
    let status: DownloadStatus

    var body: some View {
        Label(status.displayTitle, systemImage: status.systemImage)
            .font(.caption.weight(.medium))
            .foregroundStyle(status.tint)
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(status.tint.opacity(0.09), in: Capsule())
            .help(status.title)
    }
}

/// A calm introduction that makes each workspace's purpose clear.
struct PageHeading: View {
    let title: String
    let subtitle: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.system(size: 28, weight: .bold, design: .rounded))
                .tracking(-0.5)
            Text(subtitle)
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.bottom, 2)
        .accessibilityElement(children: .combine)
    }
}

struct EmptyState: View {
    let title: String
    let message: String
    let systemImage: String
    var compact = false

    var body: some View {
        Group {
            if compact {
                HStack(spacing: 16) {
                    icon
                    copy(alignment: .leading)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                VStack(spacing: 12) {
                    icon
                    copy(alignment: .center)
                }
                .frame(maxWidth: .infinity)
            }
        }
        .padding(.vertical, compact ? 12 : 24)
        .padding(.horizontal, compact ? 0 : 16)
        .accessibilityElement(children: .combine)
    }

    private var icon: some View {
        Image(systemName: systemImage)
            .font(.system(size: 25, weight: .light))
            .foregroundStyle(Theme.accent)
            .frame(width: 58, height: 58)
            .background(Theme.accent.opacity(0.08), in: RoundedRectangle(cornerRadius: 18))
    }

    private func copy(alignment: HorizontalAlignment) -> some View {
        VStack(alignment: alignment, spacing: 5) {
            Text(title).font(.headline)
            Text(message)
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(compact ? .leading : .center)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: compact ? nil : 360)
        }
    }
}

extension DownloadStatus {
    /// Diagnostic details remain available through `title` and the activity log.
    var displayTitle: String {
        switch self {
        case .ready: "Ready to download"
        case .idle: "Ready when you are"
        case .missingDependency: "Setup needed"
        case .failed: "Needs attention"
        default: title
        }
    }

    var tint: Color {
        switch self {
        case .ready, .succeeded, .running, .repairing: Theme.accent
        case .missingDependency, .failed: .orange
        default: .secondary
        }
    }
}

/// Square artwork thumbnail with a graceful placeholder. Images come from a
/// shared cache so scrolling long playlists does not refetch or re-decode art.
struct CoverView: View {
    let urlString: String

    @State private var image: NSImage?

    var body: some View {
        Group {
            if let image {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFill()
            } else {
                placeholder
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: Theme.innerRadius))
        .overlay {
            RoundedRectangle(cornerRadius: Theme.innerRadius)
                .stroke(.separator.opacity(0.6))
        }
        .task(id: urlString) {
            image = CoverImageCache.shared.cachedImage(for: urlString)
            if image == nil {
                let loadedImage = await CoverImageCache.shared.image(for: urlString)
                guard !Task.isCancelled else { return }
                image = loadedImage
            }
        }
    }

    private var placeholder: some View {
        ZStack {
            Rectangle()
                .fill(Theme.inset)
            Image(systemName: "music.note")
                .foregroundStyle(Theme.accent.opacity(0.7))
        }
    }
}

/// Downloads cover art once, downsamples it to thumbnail size off the main
/// thread, and keeps the result in memory.
@MainActor
final class CoverImageCache {
    static let shared = CoverImageCache()

    private let cache = NSCache<NSString, NSImage>()
    private var inFlight: [String: Task<CGImage?, Never>] = [:]

    private init() {
        cache.countLimit = 600
    }

    func cachedImage(for urlString: String) -> NSImage? {
        cache.object(forKey: urlString as NSString)
    }

    func image(for urlString: String) async -> NSImage? {
        guard urlString.isEmpty == false, let url = URL(string: urlString) else { return nil }
        if let cached = cachedImage(for: urlString) {
            return cached
        }
        let task: Task<CGImage?, Never>
        if let existing = inFlight[urlString] {
            task = existing
        } else {
            task = Task.detached(priority: .utility) { () -> CGImage? in
                guard let data = await CoverImageCache.download(url) else { return nil }
                return CoverImageCache.thumbnail(from: data)
            }
            inFlight[urlString] = task
        }
        guard let cgImage = await task.value else {
            inFlight[urlString] = nil
            return nil
        }
        inFlight[urlString] = nil
        if let cached = cachedImage(for: urlString) {
            return cached
        }
        let image = NSImage(cgImage: cgImage, size: NSSize(width: cgImage.width, height: cgImage.height))
        cache.setObject(image, forKey: urlString as NSString)
        return image
    }

    /// Streams at most 10 MB so an unexpected huge response is never held in memory.
    nonisolated private static func download(_ url: URL) async -> Data? {
        let limit = 10 * 1024 * 1024
        guard let (bytes, response) = try? await URLSession.shared.bytes(from: url) else { return nil }
        if let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) == false {
            return nil
        }
        if response.expectedContentLength > Int64(limit) {
            return nil
        }
        var data = Data()
        do {
            for try await byte in bytes {
                data.append(byte)
                if data.count > limit {
                    return nil
                }
            }
        } catch {
            return nil
        }
        return data
    }

    /// Returns nil for anything that is not a decodable image.
    nonisolated private static func thumbnail(from data: Data) -> CGImage? {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil) else { return nil }
        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: 160,
        ]
        return CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary)
    }
}

/// A wrapping layout that flows its subviews left-to-right and moves to a new
/// line when the available width runs out, so control strips reflow on resize
/// instead of being clipped at the edges.
struct FlowLayout: Layout {
    var horizontalSpacing: CGFloat = 16
    var verticalSpacing: CGFloat = 14

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        let sizes = subviews.map { $0.sizeThatFits(.unspecified) }

        var rowWidth: CGFloat = 0
        var rowHeight: CGFloat = 0
        var totalHeight: CGFloat = 0
        var widestRow: CGFloat = 0

        for size in sizes {
            let needed = rowWidth > 0 ? rowWidth + horizontalSpacing + size.width : size.width
            if rowWidth > 0, needed > maxWidth {
                totalHeight += rowHeight + verticalSpacing
                widestRow = max(widestRow, rowWidth)
                rowWidth = size.width
                rowHeight = size.height
            } else {
                rowWidth = needed
                rowHeight = max(rowHeight, size.height)
            }
        }
        totalHeight += rowHeight
        widestRow = max(widestRow, rowWidth)

        let resolvedWidth = maxWidth.isFinite ? maxWidth : widestRow
        return CGSize(width: resolvedWidth, height: totalHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let sizes = subviews.map { $0.sizeThatFits(.unspecified) }
        var x = bounds.minX
        var y = bounds.minY
        var rowHeight: CGFloat = 0

        for (index, subview) in subviews.enumerated() {
            let size = sizes[index]
            if x > bounds.minX, x + size.width > bounds.maxX {
                x = bounds.minX
                y += rowHeight + verticalSpacing
                rowHeight = 0
            }
            subview.place(at: CGPoint(x: x, y: y), anchor: .topLeading, proposal: ProposedViewSize(size))
            x += size.width + horizontalSpacing
            rowHeight = max(rowHeight, size.height)
        }
    }
}

/// Maps a progress item state to its tint, shared by every progress view.
func progressTint(for state: ProgressItemState) -> Color {
    switch state {
    case .succeeded, .skipped:
        .green
    case .failed:
        .orange
    case .cancelled, .stopped:
        .secondary
    case .paused:
        .secondary
    case .running:
        .accentColor
    case .queued:
        .secondary
    }
}

/// Puts plain text on the clipboard; used by right-click "Copy" actions.
func copyToPasteboard(_ text: String) {
    NSPasteboard.general.clearContents()
    NSPasteboard.general.setString(text, forType: .string)
}
