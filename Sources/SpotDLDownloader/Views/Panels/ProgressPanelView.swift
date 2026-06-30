import SwiftUI

struct ProgressPanelView: View {
    @ObservedObject var viewModel: DownloadViewModel

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 12) {
                SectionHeader("Progress", systemImage: "chart.bar.fill") {
                    StatusBadge(status: viewModel.status)
                }

                VStack(alignment: .leading, spacing: 8) {
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
                }

                if viewModel.progressItems.isEmpty {
                    Label(viewModel.status.title, systemImage: viewModel.status.systemImage)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.vertical, 4)
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
                    .frame(maxHeight: 260)
                }
            }
        }
    }

    private var summaryState: ProgressItemState {
        if viewModel.progressSummary.failed > 0 {
            return .failed
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

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            CoverView(urlString: item.coverURL)
                .frame(width: 38, height: 38)

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
