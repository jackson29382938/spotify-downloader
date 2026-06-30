import SwiftUI

struct LibraryRepairView: View {
    @ObservedObject var viewModel: DownloadViewModel

    @AppStorage("searchLyrics") private var searchLyrics = true
    @AppStorage("libraryFolderPaths") private var libraryFolderPathsRaw = Defaults.musicPath
    @AppStorage("libraryRecursive") private var libraryRecursive = true
    @AppStorage("libraryArtwork") private var libraryArtwork = true
    @AppStorage("libraryOverwriteArtwork") private var libraryOverwriteArtwork = false
    @AppStorage("libraryConfidence") private var libraryConfidence = 0.72
    @AppStorage("libraryRename") private var libraryRename = false
    @AppStorage("libraryRenamePattern") private var libraryRenamePattern = Defaults.defaultRenamePattern

    private var renamePattern: String? {
        libraryRename ? libraryRenamePattern : nil
    }

    /// Persisted as newline-separated paths; newlines can't appear in macOS paths.
    private var folders: [String] {
        get {
            libraryFolderPathsRaw
                .components(separatedBy: "\n")
                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { !$0.isEmpty }
        }
    }

    private func setFolders(_ paths: [String]) {
        libraryFolderPathsRaw = paths
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .joined(separator: "\n")
    }

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 14) {
                SectionHeader("Library Cleanup", systemImage: "wand.and.sparkles") {
                    Text("\(Int((libraryConfidence * 100).rounded()))% confidence")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }

                folderList

                FlowLayout(horizontalSpacing: 22, verticalSpacing: 14) {
                    SettingBlock("Scope", help: "Subfolders stay included for normal music-library layouts.") {
                        Toggle("Subfolders", isOn: $libraryRecursive)
                            .toggleStyle(.checkbox)
                            .fixedSize()
                    }

                    SettingBlock("Artwork", help: "Adds missing cover art; replacement is opt-in.") {
                        VStack(alignment: .leading, spacing: 5) {
                            Toggle("Artwork", isOn: $libraryArtwork)
                                .toggleStyle(.checkbox)
                                .fixedSize()
                            Toggle("Replace artwork", isOn: $libraryOverwriteArtwork)
                                .toggleStyle(.checkbox)
                                .fixedSize()
                                .disabled(!libraryArtwork)
                        }
                    }

                    SettingBlock("Match", help: "Higher confidence means fewer automatic corrections.") {
                        Slider(value: $libraryConfidence, in: 0.55...0.95, step: 0.01)
                            .frame(width: 160)
                    }

                    SettingBlock("Rename", help: "When applying, rename files using tokens like {track_number}, {title}, {artist}, {album}, {year}, {genre}.") {
                        VStack(alignment: .leading, spacing: 5) {
                            Toggle("Rename files", isOn: $libraryRename)
                                .toggleStyle(.checkbox)
                                .fixedSize()
                            TextField("Pattern", text: $libraryRenamePattern)
                                .textFieldStyle(.roundedBorder)
                                .frame(width: 220)
                                .disabled(!libraryRename)
                        }
                    }
                }

                HStack {
                    Button {
                        viewModel.repairLibrary(
                            folders: folders,
                            apply: false,
                            recursive: libraryRecursive,
                            searchLyrics: searchLyrics,
                            updateArtwork: libraryArtwork,
                            overwriteArtwork: libraryOverwriteArtwork,
                            minConfidence: libraryConfidence
                        )
                    } label: {
                        Label("Scan Library", systemImage: "magnifyingglass")
                    }
                    .disabled(!viewModel.canRepairLibrary || folders.isEmpty)

                    Button {
                        viewModel.repairLibrary(
                            folders: folders,
                            apply: true,
                            recursive: libraryRecursive,
                            searchLyrics: searchLyrics,
                            updateArtwork: libraryArtwork,
                            overwriteArtwork: libraryOverwriteArtwork,
                            minConfidence: libraryConfidence,
                            renamePattern: renamePattern
                        )
                    } label: {
                        Label("Apply Repairs", systemImage: "wand.and.sparkles")
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!viewModel.canRepairLibrary || folders.isEmpty)

                    Spacer()

                    Label("Title, artist, album, genre, artwork, lyrics", systemImage: "tag")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    private var folderList: some View {
        VStack(alignment: .leading, spacing: 6) {
            if folders.isEmpty {
                Text("No folders added. Click Add Folder to choose a music library folder.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10)
                    .background(.thinMaterial, in: RoundedRectangle(cornerRadius: Theme.innerRadius))
            } else {
                VStack(spacing: 0) {
                    ForEach(Array(folders.enumerated()), id: \.offset) { index, path in
                        HStack(spacing: 10) {
                            Image(systemName: "folder.fill")
                                .foregroundStyle(.secondary)
                                .frame(width: 16)

                            VStack(alignment: .leading, spacing: 1) {
                                Text(URL(fileURLWithPath: path).lastPathComponent)
                                    .font(.callout.weight(.medium))
                                    .lineLimit(1)
                                Text(path)
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(1)
                            }

                            Spacer()

                            Button {
                                viewModel.openExistingFolder(path: path)
                            } label: {
                                Image(systemName: "arrow.up.forward.app")
                                    .foregroundStyle(.secondary)
                            }
                            .buttonStyle(.plain)
                            .help("Open in Finder")

                            Button {
                                var updated = folders
                                updated.remove(at: index)
                                setFolders(updated)
                            } label: {
                                Image(systemName: "minus.circle.fill")
                                    .foregroundStyle(.red.opacity(0.8))
                            }
                            .buttonStyle(.plain)
                            .help("Remove folder")
                        }
                        .padding(.horizontal, 10)
                        .padding(.vertical, 8)

                        if index < folders.count - 1 {
                            Divider().padding(.leading, 36)
                        }
                    }
                }
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: Theme.innerRadius))
                .overlay {
                    RoundedRectangle(cornerRadius: Theme.innerRadius)
                        .stroke(.separator.opacity(0.5))
                }
            }

            Button {
                addFolder()
            } label: {
                Label("Add Folder", systemImage: "plus.circle")
            }
        }
    }

    private func addFolder() {
        let start = folders.last ?? Defaults.musicPath
        if let chosen = FolderPicker.chooseFolder(startingAt: start) {
            guard folders.contains(chosen) == false else { return }
            setFolders(folders + [chosen])
        }
    }
}
