import SwiftUI

/// Shared visual tokens so every panel uses the same rhythm, radius, and materials.
enum Theme {
    static let cornerRadius: CGFloat = 12
    static let innerRadius: CGFloat = 8
    static let cardPadding: CGFloat = 16
    static let sectionSpacing: CGFloat = 18
    static let contentMaxWidth: CGFloat = 980
}

/// A consistent container for every section in the main panel.
struct Card<Content: View>: View {
    var padding: CGFloat = Theme.cardPadding
    @ViewBuilder var content: () -> Content

    var body: some View {
        content()
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: Theme.cornerRadius))
            .overlay {
                RoundedRectangle(cornerRadius: Theme.cornerRadius)
                    .stroke(.separator.opacity(0.45))
            }
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
                    .font(.headline)
                    .foregroundStyle(.secondary)
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
                .font(.caption)
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
        Label(status.title, systemImage: status.systemImage)
            .font(.caption.weight(.medium))
            .foregroundStyle(.secondary)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(.thinMaterial, in: Capsule())
    }
}

/// Square artwork thumbnail with a graceful placeholder.
struct CoverView: View {
    let urlString: String

    var body: some View {
        Group {
            if let url = URL(string: urlString), urlString.isEmpty == false {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .success(let image):
                        image
                            .resizable()
                            .scaledToFill()
                    default:
                        placeholder
                    }
                }
            } else {
                placeholder
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: Theme.innerRadius))
        .overlay {
            RoundedRectangle(cornerRadius: Theme.innerRadius)
                .stroke(.separator.opacity(0.6))
        }
    }

    private var placeholder: some View {
        ZStack {
            Rectangle()
                .fill(.quaternary)
            Image(systemName: "music.note")
                .foregroundStyle(.secondary)
        }
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
    case .cancelled:
        .secondary
    case .running:
        .accentColor
    case .queued:
        .secondary
    }
}
