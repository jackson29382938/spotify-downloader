import SwiftUI

struct HistoryView: View {
    @ObservedObject var viewModel: DownloadViewModel

    @State private var searchText = ""

    private var filteredEntries: [HistoryEntry] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard query.isEmpty == false else { return viewModel.historyEntries }
        return viewModel.historyEntries.filter { entry in
            entry.sourceURL.lowercased().contains(query)
                || entry.outputFolder.lowercased().contains(query)
                || entry.format.lowercased().contains(query)
        }
    }

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 12) {
                SectionHeader("Download History", systemImage: "clock.arrow.circlepath") {
                    HStack(spacing: 8) {
                        Button {
                            viewModel.loadHistory()
                        } label: {
                            Label("Refresh", systemImage: "arrow.clockwise")
                        }
                        Button(role: .destructive) {
                            viewModel.clearHistory()
                        } label: {
                            Label("Clear History", systemImage: "trash")
                        }
                        .disabled(viewModel.historyEntries.isEmpty)
                    }
                }

                if viewModel.historyEntries.isEmpty {
                    EmptyState(title: "A home for your listening history", message: "Completed sessions appear here with their source, format, and results.", systemImage: "clock.arrow.circlepath")
                } else {
                    TextField("Filter by link, folder, or format", text: $searchText)
                        .textFieldStyle(.roundedBorder)
                        .controlSize(.large)

                    if filteredEntries.isEmpty {
                        EmptyState(title: "No matching downloads", message: "Try a different link, folder name, or format.", systemImage: "magnifyingglass", compact: true)
                    } else {
                        VStack(spacing: 0) {
                            ForEach(Array(filteredEntries.enumerated()), id: \.element.id) { index, entry in
                                HistoryRow(entry: entry) {
                                    viewModel.revealHistoryEntry(entry)
                                }
                                if index < filteredEntries.count - 1 {
                                    Divider().padding(.leading, 12)
                                }
                            }
                        }
                        .background(Theme.inset, in: RoundedRectangle(cornerRadius: Theme.innerRadius))
                        .overlay {
                            RoundedRectangle(cornerRadius: Theme.innerRadius)
                                .stroke(Theme.border)
                        }
                    }
                }
            }
        }
    }
}

private struct HistoryRow: View {
    let entry: HistoryEntry
    let reveal: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: entry.isVideo ? "film" : "music.note")
                .foregroundStyle(Theme.accent)
                .frame(width: 34, height: 34)
                .background(Theme.accent.opacity(0.08), in: RoundedRectangle(cornerRadius: 9))

            VStack(alignment: .leading, spacing: 2) {
                Text(entry.sourceURL)
                    .font(.callout.weight(.medium))
                    .lineLimit(1)
                    .truncationMode(.middle)
                HStack(spacing: 8) {
                    Text(entry.displayDate)
                    Text("·")
                    Text(entry.isVideo ? "MP4" : entry.format.uppercased())
                    Text("·")
                    Text(entry.summary)
                        .foregroundStyle(entry.failedCount > 0 ? .orange : .secondary)
                }
                .font(.caption2)
                .foregroundStyle(.secondary)
                .lineLimit(1)
            }

            Spacer()

            Button {
                reveal()
            } label: {
                Image(systemName: "arrow.up.forward.app")
                    .foregroundStyle(.secondary)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Reveal download folder")
            .help("Reveal output folder in Finder")
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 12)
    }
}
