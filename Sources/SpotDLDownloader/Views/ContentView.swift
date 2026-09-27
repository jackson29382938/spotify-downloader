import SwiftUI

struct ContentView: View {
    @StateObject private var viewModel = DownloadViewModel()

    @AppStorage("downloadFolderPath") private var downloadFolderPath = Defaults.downloadsPath
    @AppStorage("mediaKind") private var mediaKind = MediaKind.audio.rawValue
    @AppStorage("selectedSection") private var selectedSectionRaw = AppSection.download.rawValue

    private var selectedMediaKind: MediaKind {
        MediaKind(rawValue: mediaKind) ?? .audio
    }

    private var selectedSection: Binding<AppSection?> {
        Binding(
            get: { AppSection(rawValue: selectedSectionRaw) ?? .download },
            set: { selectedSectionRaw = ($0 ?? .download).rawValue }
        )
    }

    private var currentSection: AppSection {
        AppSection(rawValue: selectedSectionRaw) ?? .download
    }

    var body: some View {
        NavigationSplitView {
            SidebarView(viewModel: viewModel, selection: selectedSection)
        } detail: {
            detail(for: currentSection)
                .background(Theme.canvas)
                .navigationTitle(currentSection.title)
                .toolbar { toolbarContent }
        }
        .tint(Theme.accent)
        // Every label, status, and error in the window can be selected and copied.
        .textSelection(.enabled)
        .task {
            viewModel.checkDownloader()
            viewModel.refreshHealth(outputFolder: downloadFolderPath)
            viewModel.loadHistory()
        }
    }

    @ViewBuilder
    private func detail(for section: AppSection) -> some View {
        switch section {
        case .download:
            Page {
                PageHeading(title: "Your music, ready to go.", subtitle: "Save tracks, albums, and playlists to your library.")
                DownloadComposerView(viewModel: viewModel)
                QuickOptionsView()
                if viewModel.progressSource == .download {
                    ProgressPanelView(viewModel: viewModel)
                }
            }
        case .queue:
            Page {
                PageHeading(title: "A look before you listen.", subtitle: "Review tracks and artwork before starting a download.")
                QueuePanelView(viewModel: viewModel)
            }
        case .history:
            Page {
                PageHeading(title: "Your recent downloads", subtitle: "Find finished sessions and jump back to their files.")
                HistoryView(viewModel: viewModel)
            }
        case .library:
            Page {
                PageHeading(title: "Care for your collection.", subtitle: "Refresh artwork, tidy metadata, and bring lyrics into your songs.")
                LibraryRepairView(viewModel: viewModel)
                EmbedLyricsView(viewModel: viewModel)
                if viewModel.progressSource == .library {
                    ProgressPanelView(viewModel: viewModel, fillsHeight: false)
                }
            }
        case .diagnostics:
            Page {
                PageHeading(title: "Everything behind the music", subtitle: "Check the downloader and review recent activity.")
                DiagnosticsView(viewModel: viewModel)
                ActivityLogView(viewModel: viewModel)
            }
        }
    }

    @ToolbarContentBuilder
    private var toolbarContent: some ToolbarContent {
        ToolbarItemGroup {
            if currentSection == .download {
                Button {
                    viewModel.resetSampleLink(for: selectedMediaKind)
                } label: {
                    Label(selectedMediaKind == .video ? "Sample Video" : "Test Track", systemImage: selectedMediaKind.systemImage)
                }
            }

            if currentSection == .diagnostics {
                Button {
                    viewModel.clearLog()
                } label: {
                    Label("Clear Log", systemImage: "trash")
                }
                .disabled(viewModel.activityLines.isEmpty)
            }

            if currentSection == .diagnostics {
                Button {
                    viewModel.copyDiagnostics()
                } label: {
                    Label("Copy Diagnostics", systemImage: "doc.on.doc")
                }
            }

            SettingsLink {
                Label("Settings", systemImage: "gearshape")
            }
        }
    }
}

/// Shared page chrome: consistent padding and width, optionally scrollable.
private struct Page<Content: View>: View {
    var scrolls = true
    @ViewBuilder var content: () -> Content

    var body: some View {
        if scrolls {
            ScrollView {
                stack
            }
        } else {
            stack
        }
    }

    private var stack: some View {
        VStack(alignment: .leading, spacing: Theme.sectionSpacing) {
            content()
        }
        .padding(24)
        .frame(maxWidth: Theme.contentMaxWidth, maxHeight: scrolls ? nil : CGFloat.infinity, alignment: .topLeading)
        .frame(maxWidth: .infinity, alignment: .top)
    }
}
