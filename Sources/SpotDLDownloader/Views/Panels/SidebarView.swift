import SwiftUI

struct SidebarView: View {
    @ObservedObject var viewModel: DownloadViewModel
    @Binding var selection: AppSection?

    @AppStorage("downloadFolderPath") private var downloadFolderPath = Defaults.downloadsPath

    var body: some View {
        List(selection: $selection) {
            Section {
                ForEach(AppSection.allCases) { section in
                    Label(section.title, systemImage: section.systemImage)
                        .badge(badgeCount(for: section))
                        .tag(section)
                }
            }

            Section("Status") {
                StatusRow(status: viewModel.status)
                if viewModel.progressSummary.total > 0 {
                    Text(viewModel.progressSummary.statusText)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            }

            Section("Download Folder") {
                VStack(alignment: .leading, spacing: 4) {
                    Label(URL(fileURLWithPath: downloadFolderPath).lastPathComponent, systemImage: "folder")
                    Text(downloadFolderPath)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .truncationMode(.middle)
                }
            }
        }
        .listStyle(.sidebar)
        .safeAreaInset(edge: .top) {
            AppLogoLockup(logoSize: 32)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 16)
                .padding(.top, 12)
                .padding(.bottom, 8)
        }
        .safeAreaInset(edge: .bottom) {
            HStack(spacing: 8) {
                Button {
                    viewModel.openFolder(path: downloadFolderPath)
                } label: {
                    Label("Open", systemImage: "folder")
                        .frame(maxWidth: .infinity)
                }
                .help("Open the download folder in Finder")

                Button {
                    chooseDownloadFolder()
                } label: {
                    Label("Change", systemImage: "folder.badge.gearshape")
                        .frame(maxWidth: .infinity)
                }
                .help("Choose a different download folder")
            }
            .buttonStyle(.bordered)
            .controlSize(.regular)
            .padding()
        }
        .navigationSplitViewColumnWidth(min: 200, ideal: 230, max: 300)
    }

    /// Small counts next to each destination so state is visible without opening the page.
    private func badgeCount(for section: AppSection) -> Int {
        switch section {
        case .download:
            viewModel.progressSource == .download ? viewModel.progressSummary.failed : 0
        case .queue:
            viewModel.queueItems.count
        case .history:
            0
        case .library:
            0
        case .diagnostics:
            (viewModel.healthReport?.checks.filter { !$0.ok }.count) ?? 0
        }
    }

    private func chooseDownloadFolder() {
        if let chosen = FolderPicker.chooseFolder(startingAt: downloadFolderPath) {
            downloadFolderPath = chosen
        }
    }
}

private struct StatusRow: View {
    let status: DownloadStatus

    var body: some View {
        Label(status.title, systemImage: status.systemImage)
            .foregroundStyle(color)
            .lineLimit(2)
    }

    private var color: Color {
        switch status {
        case .ready, .succeeded:
            .green
        case .missingDependency, .failed:
            .orange
        case .running, .repairing:
            .accentColor
        case .paused, .cancelled:
            .secondary
        default:
            .primary
        }
    }
}
