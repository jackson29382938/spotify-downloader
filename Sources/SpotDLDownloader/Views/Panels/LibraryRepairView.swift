import SwiftUI

struct LibraryRepairView: View {
    @ObservedObject var viewModel: DownloadViewModel

    @AppStorage("searchLyrics") private var searchLyrics = true
    @AppStorage("lyricsStyle") private var lyricsStyle = LyricsStyle.plain.rawValue
    @AppStorage("libraryCleanupFolderPaths") private var libraryFolderPathsRaw = ""
    @AppStorage("libraryRecursive") private var libraryRecursive = true
    @AppStorage("libraryArtwork") private var libraryArtwork = true
    @AppStorage("libraryOverwriteArtwork") private var libraryOverwriteArtwork = false
    @AppStorage("libraryConfidence") private var libraryConfidence = 0.72
    @AppStorage("libraryRename") private var libraryRename = false
    @AppStorage("libraryRenamePattern") private var libraryRenamePattern = Defaults.defaultRenamePattern
    @State private var musicSelections: [AppleMusicLibraryItem] = []
    @State private var showingMusicPicker = false

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

    private var selections: [String] {
        folders + musicSelections.flatMap(\.paths)
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
                musicSelectionList

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
                            folders: selections,
                            apply: false,
                            recursive: libraryRecursive,
                            searchLyrics: searchLyrics,
                            lyricsStyle: LyricsStyle(rawValue: lyricsStyle) ?? .plain,
                            updateArtwork: libraryArtwork,
                            overwriteArtwork: libraryOverwriteArtwork,
                            minConfidence: libraryConfidence
                        )
                    } label: {
                        Label("Scan Library", systemImage: "magnifyingglass")
                    }
                    .disabled(!viewModel.canRepairLibrary || selections.isEmpty)

                    Button {
                        viewModel.repairLibrary(
                            folders: selections,
                            apply: true,
                            recursive: libraryRecursive,
                            searchLyrics: searchLyrics,
                            lyricsStyle: LyricsStyle(rawValue: lyricsStyle) ?? .plain,
                            updateArtwork: libraryArtwork,
                            overwriteArtwork: libraryOverwriteArtwork,
                            minConfidence: libraryConfidence,
                            renamePattern: renamePattern
                        )
                    } label: {
                        Label("Apply Repairs", systemImage: "wand.and.sparkles")
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!viewModel.canRepairLibrary || selections.isEmpty)

                    Spacer()

                    Label("Title, artist, album, genre, artwork, lyrics", systemImage: "tag")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .sheet(isPresented: $showingMusicPicker) {
            MusicLibraryPickerView(selectedIDs: Set(musicSelections.map(\.selectionID))) { item in
                guard !musicSelections.contains(where: { $0.selectionID == item.selectionID }) else { return }
                musicSelections.append(item)
            }
        }
        .onAppear {
            let defaults = UserDefaults.standard
            if defaults.object(forKey: "libraryCleanupFolderPaths") == nil,
               let previous = defaults.string(forKey: "libraryFolderPaths"),
               !previous.isEmpty,
               previous != Defaults.musicPath {
                libraryFolderPathsRaw = previous
            }
        }
    }

    private var folderList: some View {
        VStack(alignment: .leading, spacing: 6) {
            if folders.isEmpty && musicSelections.isEmpty {
                Text("Choose a folder or add playlists, albums, or songs from Music.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10)
                    .background(.thinMaterial, in: RoundedRectangle(cornerRadius: Theme.innerRadius))
            } else if !folders.isEmpty {
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

    private var musicSelectionList: some View {
        VStack(alignment: .leading, spacing: 6) {
            if !musicSelections.isEmpty {
                ForEach(musicSelections, id: \.selectionID) { item in
                    HStack(spacing: 10) {
                        Image(systemName: item.kind == .playlist ? "music.note.list" : item.kind == .album ? "square.stack" : "music.note")
                            .foregroundStyle(.secondary)
                            .frame(width: 16)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(item.title).font(.callout.weight(.medium)).lineLimit(1)
                            Text("Music \(item.kind.title.lowercased()) · \(item.paths.count) local song\(item.paths.count == 1 ? "" : "s")")
                                .font(.caption2).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button {
                            musicSelections.removeAll { $0.selectionID == item.selectionID }
                        } label: {
                            Image(systemName: "minus.circle.fill").foregroundStyle(.red.opacity(0.8))
                        }
                        .buttonStyle(.plain)
                        .help("Remove selection")
                    }
                    .padding(.horizontal, 10)
                    .padding(.vertical, 8)
                }
            }
            Button {
                showingMusicPicker = true
            } label: {
                Label("Add from Apple Music", systemImage: "music.note")
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

private struct MusicLibraryPickerView: View {
    @Environment(\.dismiss) private var dismiss
    let selectedIDs: Set<String>
    let onAdd: (AppleMusicLibraryItem) -> Void

    @State private var kind = AppleMusicLibraryKind.playlist
    @State private var query = ""
    @State private var items: [AppleMusicLibraryItem] = []
    @State private var isLoading = false
    @State private var hasSearched = false
    @State private var pendingID: String?
    @State private var errorMessage: String?
    private let service = AppleMusicLibraryService()

    private var visibleItems: [AppleMusicLibraryItem] {
        kind == .playlist && !query.isEmpty
            ? items.filter { $0.title.localizedCaseInsensitiveContains(query) }
            : items
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Choose from Apple Music").font(.title2.weight(.semibold))
                Spacer()
                Button("Done") { dismiss() }
            }
            Picker("Type", selection: $kind) {
                ForEach(AppleMusicLibraryKind.allCases) { option in
                    Text(option.title).tag(option)
                }
            }
            .pickerStyle(.segmented)

            HStack {
                TextField(kind == .playlist ? "Filter playlists" : "Search \(kind.title.lowercased())s", text: $query)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { search() }
                if kind != .playlist {
                    Button("Search") { search() }
                        .disabled(query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isLoading)
                }
            }

            if let errorMessage {
                Text(errorMessage).foregroundStyle(.red).font(.callout)
            } else if kind != .playlist && items.isEmpty && !isLoading {
                Text(hasSearched
                     ? "No local audio files matched. Songs available only through Apple Music cannot be repaired."
                     : "Search your Music library, then add the local songs you want to clean up.")
                    .foregroundStyle(.secondary)
            }

            if isLoading { ProgressView("Reading Music library…") }

            List(visibleItems) { item in
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(item.title).font(.callout.weight(.medium))
                        Text(item.detail).font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button(selectedIDs.contains(item.selectionID) ? "Added" : "Add") {
                        add(item)
                    }
                    .disabled(selectedIDs.contains(item.selectionID) || pendingID != nil)
                }
            }
            Text("Only songs with a local audio file can be repaired. Music may ask for permission to share your library.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .padding(20)
        .frame(minWidth: 580, minHeight: 470)
        .onAppear { search() }
        .onChange(of: kind) {
            query = ""
            items = []
            isLoading = false
            hasSearched = false
            errorMessage = nil
            if kind == .playlist { search() }
        }
        .onChange(of: query) {
            if kind != .playlist {
                items = []
                isLoading = false
                hasSearched = false
            }
        }
    }

    private func search() {
        let term = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard kind == .playlist || !term.isEmpty else { return }
        let requestedKind = kind
        isLoading = true
        hasSearched = false
        errorMessage = nil
        service.browse(kind: requestedKind, query: term) { result in
            guard kind == requestedKind,
                  (kind == .playlist || query.trimmingCharacters(in: .whitespacesAndNewlines) == term) else { return }
            isLoading = false
            hasSearched = true
            switch result {
            case .success(let found): items = found
            case .failure(let error): errorMessage = error.localizedDescription
            }
        }
    }

    private func add(_ item: AppleMusicLibraryItem) {
        guard item.kind == .playlist else {
            onAdd(item)
            return
        }
        pendingID = item.id
        errorMessage = nil
        service.playlistPaths(id: item.id) { result in
            pendingID = nil
            switch result {
            case .success(let paths):
                if paths.isEmpty {
                    errorMessage = "This playlist has no local audio files to repair."
                } else {
                    onAdd(AppleMusicLibraryItem(kind: .playlist, id: item.id, title: item.title, detail: item.detail, paths: paths))
                }
            case .failure(let error): errorMessage = error.localizedDescription
            }
        }
    }
}
