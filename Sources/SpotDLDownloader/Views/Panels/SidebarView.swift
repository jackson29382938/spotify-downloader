import SwiftUI

struct SidebarView: View {
    @ObservedObject var viewModel: DownloadViewModel
    @Binding var selection: AppSection?

    @AppStorage("downloadFolderPath") private var downloadFolderPath = Defaults.downloadsPath

    var body: some View {
        List(selection: $selection) {
            Section("Workspace") {
                ForEach(AppSection.allCases) { section in
                    Label(section.title, systemImage: section.systemImage)
                        .font(.system(size: 13, weight: selection == section ? .semibold : .regular))
                        .padding(.vertical, 5)
                        .badge(badgeCount(for: section))
                        .tag(section)
                }
            }

        }
        .listStyle(.sidebar)
        .safeAreaInset(edge: .top) {
            AppLogoLockup(logoSize: 42)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 16)
                .padding(.top, 18)
                .padding(.bottom, 20)
        }
        .safeAreaInset(edge: .bottom) {
            VStack(alignment: .leading, spacing: 14) {
                StatusRow(status: viewModel.status)
                if viewModel.progressSummary.total > 0 {
                    Text(viewModel.progressSummary.statusText)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
                Divider()
                VStack(alignment: .leading, spacing: 6) {
                    Text("SAVE TO")
                        .font(.system(size: 10, weight: .semibold))
                        .tracking(1)
                        .foregroundStyle(.secondary)
                    Label(URL(fileURLWithPath: downloadFolderPath).lastPathComponent, systemImage: "folder")
                        .font(.callout.weight(.medium))
                        .lineLimit(1)
                        .help(downloadFolderPath)
                }
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
            }
            .buttonStyle(.bordered)
            .controlSize(.regular)
            .padding()
        }
        .navigationSplitViewColumnWidth(min: 200, ideal: 220, max: 280)
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
        Label(status.displayTitle, systemImage: status.systemImage)
            .font(.caption.weight(.medium))
            .foregroundStyle(status.tint)
            .lineLimit(2)
            .help(status.title)
    }
}
