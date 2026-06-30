import SwiftUI

struct QueuePanelView: View {
    @ObservedObject var viewModel: DownloadViewModel

    @AppStorage("downloadFolderPath") private var downloadFolderPath = Defaults.downloadsPath

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 12) {
                SectionHeader("Preview Queue", systemImage: "list.bullet.rectangle") {
                    Button {
                        viewModel.clearCompletedQueueItems()
                    } label: {
                        Label("Clear Completed", systemImage: "checkmark.circle")
                    }
                    .disabled(viewModel.queueItems.contains { $0.state == .succeeded } == false)
                }

                if viewModel.queueItems.isEmpty {
                    Text("Preview links to inspect detected tracks, covers, output folders, and failures before downloading.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(12)
                        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: Theme.innerRadius))
                } else {
                    HStack(alignment: .top, spacing: 14) {
                        List(selection: $viewModel.selectedQueueItemID) {
                            ForEach(viewModel.queueItems) { item in
                                QueueRow(item: item)
                                    .tag(item.id)
                                    .contextMenu {
                                        Button("Reveal Output") {
                                            viewModel.revealOutput(for: item, fallbackFolder: downloadFolderPath)
                                        }
                                        Button("Remove") {
                                            viewModel.removeQueueItem(item)
                                        }
                                    }
                            }
                        }
                        .listStyle(.inset)
                        .frame(minHeight: 190)

                        QueueDetailView(
                            item: viewModel.selectedQueueItem,
                            fallbackFolder: downloadFolderPath,
                            revealOutput: { item in
                                viewModel.revealOutput(for: item, fallbackFolder: downloadFolderPath)
                            },
                            remove: { item in
                                viewModel.removeQueueItem(item)
                            }
                        )
                        .frame(minWidth: 300, maxWidth: 360)
                    }
                    .frame(minHeight: 230)
                }
            }
        }
    }
}

private struct QueueRow: View {
    let item: DownloadQueueItem

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: item.state.systemImage)
                .foregroundStyle(color)
                .frame(width: 16)

            VStack(alignment: .leading, spacing: 2) {
                Text(item.title)
                    .lineLimit(1)
                Text(subtitle)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
    }

    private var subtitle: String {
        if item.message.isEmpty == false {
            return "\(item.state.label) - \(item.message)"
        }
        if item.trackCount > 0 {
            return "\(item.state.label) - \(item.trackCount) track(s)"
        }
        return item.state.label
    }

    private var color: Color {
        switch item.state {
        case .succeeded:
            .green
        case .failed:
            .orange
        case .running:
            .accentColor
        default:
            .secondary
        }
    }
}

private struct QueueDetailView: View {
    let item: DownloadQueueItem?
    let fallbackFolder: String
    let revealOutput: (DownloadQueueItem) -> Void
    let remove: (DownloadQueueItem) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let item {
                HStack(alignment: .top, spacing: 12) {
                    CoverView(urlString: item.coverURL)
                        .frame(width: 72, height: 72)

                    VStack(alignment: .leading, spacing: 4) {
                        Text(item.title)
                            .font(.headline)
                            .lineLimit(2)
                        Text(item.detail.isEmpty ? item.url : item.detail)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                        Label(item.state.label, systemImage: item.state.systemImage)
                            .font(.caption.weight(.medium))
                            .foregroundStyle(item.state == .failed ? .orange : .secondary)
                    }
                }

                if item.message.isEmpty == false {
                    Text(item.message)
                        .font(.caption)
                        .foregroundStyle(.orange)
                        .fixedSize(horizontal: false, vertical: true)
                }

                VStack(alignment: .leading, spacing: 4) {
                    Text("Output")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text(item.outputFolder.isEmpty ? fallbackFolder : item.outputFolder)
                        .font(.caption)
                        .textSelection(.enabled)
                        .lineLimit(2)
                }

                HStack {
                    Button {
                        revealOutput(item)
                    } label: {
                        Label("Reveal", systemImage: "folder")
                    }
                    Button(role: .destructive) {
                        remove(item)
                    } label: {
                        Label("Remove", systemImage: "minus.circle")
                    }
                }

                Divider()

                Text("Tracks")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 6) {
                        ForEach(item.tracks.prefix(80)) { track in
                            HStack(spacing: 7) {
                                CoverView(urlString: track.coverURL)
                                    .frame(width: 28, height: 28)

                                VStack(alignment: .leading, spacing: 1) {
                                    Text(trackTitle(track))
                                        .font(.caption)
                                        .lineLimit(1)
                                    if track.artists.isEmpty == false {
                                        Text(track.artists)
                                            .font(.caption2)
                                            .foregroundStyle(.secondary)
                                            .lineLimit(1)
                                    }
                                }
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        if item.tracks.count > 80 {
                            Text("\(item.tracks.count - 80) more tracks")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
                .frame(minHeight: 80, maxHeight: 180)
            } else {
                Text("Select a previewed source to inspect tracks, artwork, output folder, and status.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(12)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: Theme.innerRadius))
    }

    private func trackTitle(_ track: PreviewTrack) -> String {
        if let position = track.position {
            return "\(position). \(track.title)"
        }
        return track.title
    }
}
