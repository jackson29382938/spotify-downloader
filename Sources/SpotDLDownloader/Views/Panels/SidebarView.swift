import SwiftUI

struct SidebarView: View {
    @ObservedObject var viewModel: DownloadViewModel

    @AppStorage("downloadFolderPath") private var downloadFolderPath = Defaults.downloadsPath
    @AppStorage("mediaKind") private var mediaKind = MediaKind.audio.rawValue
    @AppStorage("downloadThreads") private var downloadThreads = 4
    @AppStorage("audioFormat") private var audioFormat = AudioFormat.mp3.rawValue
    @AppStorage("trackNumberPrefix") private var trackNumberPrefix = true
    @AppStorage("allowClosestMatch") private var allowClosestMatch = false
    @AppStorage("libraryFolderPaths") private var libraryFolderPathsRaw = Defaults.musicPath

    private var libraryFolderPaths: [String] {
        libraryFolderPathsRaw
            .components(separatedBy: "\n")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    private var selectedMediaKind: MediaKind {
        MediaKind(rawValue: mediaKind) ?? .audio
    }

    private var selectedFormat: AudioFormat {
        AudioFormat(rawValue: audioFormat) ?? .mp3
    }

    var body: some View {
        List {
            Section("Status") {
                StatusRow(status: viewModel.status)
            }

            Section("Configuration") {
                Label(selectedMediaKind.label, systemImage: selectedMediaKind.systemImage)
                Label("\(max(1, downloadThreads)) concurrent", systemImage: "speedometer")
                Label(
                    selectedMediaKind == .video ? "MP4" : selectedFormat.rawValue.uppercased(),
                    systemImage: selectedMediaKind == .video ? "film" : "music.note"
                )
                Label(trackNumberPrefix ? "Track numbers" : "No prefixes", systemImage: "number")
                Label(allowClosestMatch ? "Closest fallback" : "Strict match", systemImage: "magnifyingglass")
                Label("\(viewModel.queueItems.count) queued", systemImage: "list.bullet.rectangle")
            }

            Section("Download Folder") {
                folderRow(path: downloadFolderPath, icon: "folder")
            }

            Section("Music Library") {
                if libraryFolderPaths.isEmpty {
                    Label("No folders", systemImage: "music.note.list")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(libraryFolderPaths, id: \.self) { path in
                        folderRow(path: path, icon: "music.note.list")
                    }
                }
            }

            Section("History") {
                Label(
                    viewModel.historyEntries.isEmpty
                        ? "No sessions yet"
                        : "\(viewModel.historyEntries.count) session\(viewModel.historyEntries.count == 1 ? "" : "s")",
                    systemImage: "clock.arrow.circlepath"
                )
                .foregroundStyle(viewModel.historyEntries.isEmpty ? .secondary : .primary)
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
        .navigationTitle("Media DL")
        .safeAreaInset(edge: .bottom) {
            VStack(spacing: 8) {
                Button {
                    viewModel.openFolder(path: downloadFolderPath)
                } label: {
                    Label("Open Folder", systemImage: "folder")
                        .frame(maxWidth: .infinity)
                }

                Button {
                    chooseDownloadFolder()
                } label: {
                    Label("Change Folder", systemImage: "folder.badge.gearshape")
                        .frame(maxWidth: .infinity)
                }

                Button {
                    viewModel.openFolder(path: Defaults.logsPath)
                } label: {
                    Label("Open Logs", systemImage: "doc.text.magnifyingglass")
                        .frame(maxWidth: .infinity)
                }
            }
            .buttonStyle(.bordered)
            .controlSize(.regular)
            .padding()
        }
        .navigationSplitViewColumnWidth(min: 200, ideal: 220, max: 280)
    }

    private func folderRow(path: String, icon: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Label(URL(fileURLWithPath: path).lastPathComponent, systemImage: icon)
            Text(path)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)
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
    }

    private var color: Color {
        switch status {
        case .ready, .succeeded:
            .green
        case .missingDependency, .failed:
            .orange
        case .running, .repairing:
            .accentColor
        case .cancelled:
            .secondary
        default:
            .primary
        }
    }
}
