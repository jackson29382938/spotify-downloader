import SwiftUI

/// Folds existing `.lrc` sidecar files into the songs they belong to.
struct EmbedLyricsView: View {
    @ObservedObject var viewModel: DownloadViewModel

    @AppStorage("libraryFolderPaths") private var libraryFolderPathsRaw = Defaults.musicPath
    @AppStorage("downloadFolderPath") private var downloadFolderPath = Defaults.downloadsPath
    @AppStorage("libraryRecursive") private var libraryRecursive = true
    @AppStorage("lyricsStyle") private var lyricsStyle = LyricsStyle.plain.rawValue
    @AppStorage("embedLRCKeepFiles") private var keepLRCFiles = false

    private var libraryFolders: [String] {
        libraryFolderPathsRaw
            .components(separatedBy: "\n")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    private var targetFolders: [String] {
        var folders = libraryFolders
        if folders.contains(downloadFolderPath) == false {
            folders.append(downloadFolderPath)
        }
        return folders
    }

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 12) {
                SectionHeader("Embed .lrc Lyrics", systemImage: "text.quote")

                Text("Finds songs with a matching .lrc file in your download folder and library folders, writes the lyrics inside the song, then removes the .lrc file.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                FlowLayout(horizontalSpacing: 22, verticalSpacing: 12) {
                    SettingBlock("Style", help: (LyricsStyle(rawValue: lyricsStyle) ?? .plain).help) {
                        Picker("Style", selection: $lyricsStyle) {
                            ForEach(LyricsStyle.allCases) { style in
                                Text(style.label).tag(style.rawValue)
                            }
                        }
                        .pickerStyle(.menu)
                        .labelsHidden()
                        .frame(width: 170)
                    }

                    SettingBlock("Sidecars", help: "Leave off to delete each .lrc once its lyrics are inside the song.") {
                        Toggle("Keep .lrc files", isOn: $keepLRCFiles)
                            .toggleStyle(.checkbox)
                            .fixedSize()
                    }
                }

                HStack {
                    Button {
                        viewModel.embedLRCFiles(
                            folders: targetFolders,
                            recursive: libraryRecursive,
                            keepLRC: keepLRCFiles,
                            lyricsStyle: LyricsStyle(rawValue: lyricsStyle) ?? .plain
                        )
                    } label: {
                        Label("Embed Lyrics", systemImage: "text.badge.plus")
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!viewModel.canRepairLibrary)

                    Spacer()

                    Text("\(targetFolders.count) folder\(targetFolders.count == 1 ? "" : "s")")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
    }
}
