import SwiftUI

struct ProgressPanelView: View {
    @ObservedObject var viewModel: DownloadViewModel
    /// On the Download page the song list grows with the window.
    var fillsHeight = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 12) {
                SectionHeader("Progress", systemImage: "chart.bar.fill") {
                    StatusBadge(status: viewModel.status)
                }

                if !viewModel.progressItems.isEmpty || viewModel.status.isRunning {
                    VStack(alignment: .leading, spacing: 10) {
                    HStack {
                        Text(viewModel.progressSummary.title)
                            .font(.callout.weight(.medium))
                            .lineLimit(1)
                        Spacer()
                        Text(viewModel.progressSummary.statusText)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }

                    ProgressView(value: viewModel.progressSummary.progress)
                        .progressViewStyle(.linear)
                        .tint(progressTint(for: summaryState))
                        .animation(reduceMotion ? nil : .easeOut(duration: 0.25), value: viewModel.progressSummary.progress)
                    }
                }

                if viewModel.progressItems.isEmpty {
                    EmptyState(
                        title: viewModel.status.isRunning ? "Getting things ready" : "Follow every track",
                        message: viewModel.status.isRunning ? "Your tracks will appear here as they begin." : "Artwork, download progress, and results will appear here.",
                        systemImage: "waveform",
                        compact: true
                    )
                } else {
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 10) {
                            ForEach(viewModel.progressItems) { item in
                                ProgressSongRow(item: item)
                                if item.id != (viewModel.progressItems.last?.id ?? "") {
                                    Divider()
                                }
                            }
                        }
                    }
                    .frame(height: fillsHeight ? nil : min(CGFloat(viewModel.progressItems.count) * 83, 300))
                    .frame(maxHeight: fillsHeight ? CGFloat.infinity : nil)
                }
            }
            .frame(maxHeight: fillsHeight ? CGFloat.infinity : nil, alignment: .top)
        }
    }

    private var summaryState: ProgressItemState {
        if viewModel.status == .stopped {
            return .stopped
        }
        if viewModel.progressSummary.failed > 0 {
            return .failed
        }
        if viewModel.isPaused {
            return .paused
        }
        if viewModel.status.isRunning {
            return .running
        }
        if viewModel.progressSummary.finished > 0 {
            return .succeeded
        }
        return .queued
    }
}

private struct ProgressSongRow: View {
    let item: DownloadProgressItem
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            CoverView(urlString: item.coverURL)
                .frame(width: 44, height: 44)

            VStack(alignment: .leading, spacing: 5) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(title)
                        .font(.callout.weight(.medium))
                        .lineLimit(1)
                    Spacer()
                    Label(percentText, systemImage: item.state.systemImage)
                        .labelStyle(.titleAndIcon)
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(progressTint(for: item.state))
                        .fixedSize()
                }

                Text(item.detailText)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)

                ProgressView(value: item.progress)
                    .progressViewStyle(.linear)
                    .tint(progressTint(for: item.state))
                    .animation(reduceMotion ? nil : .easeOut(duration: 0.25), value: item.progress)
            }
        }
        .padding(.vertical, 5)
        .contentShape(Rectangle())
        .contextMenu {
            Button("Copy") {
                copyToPasteboard("\(title)\n\(item.detailText)")
            }
            if let path = item.path, path.isEmpty == false {
                Button("Copy File Path") {
                    copyToPasteboard(path)
                }
            }
        }
    }

    private var title: String {
        if let index = item.index {
            return "\(index). \(item.displayTitle)"
        }
        return item.displayTitle
    }

    private var percentText: String {
        "\(Int((item.progress * 100).rounded()))%"
    }
}
