import SwiftUI

struct ContentView: View {
    @StateObject private var viewModel = DownloadViewModel()

    @AppStorage("downloadFolderPath") private var downloadFolderPath = Defaults.downloadsPath
    @AppStorage("mediaKind") private var mediaKind = MediaKind.audio.rawValue
    @AppStorage("showDetailedActivity") private var showDetailedActivity = false

    private var selectedMediaKind: MediaKind {
        MediaKind(rawValue: mediaKind) ?? .audio
    }

    var body: some View {
        NavigationSplitView {
            SidebarView(viewModel: viewModel)
        } detail: {
            mainPanel
        }
        .task {
            viewModel.checkDownloader()
            viewModel.refreshHealth(outputFolder: downloadFolderPath)
            viewModel.loadHistory()
        }
    }

    private var mainPanel: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.sectionSpacing) {
                DownloadComposerView(viewModel: viewModel)
                ProgressPanelView(viewModel: viewModel)
                QueuePanelView(viewModel: viewModel)
                SettingsStripView()
                LibraryRepairView(viewModel: viewModel)
                HistoryView(viewModel: viewModel)
                if showDetailedActivity {
                    ActivityLogView(viewModel: viewModel)
                }
                DiagnosticsView(viewModel: viewModel)
            }
            .padding(24)
            .frame(maxWidth: Theme.contentMaxWidth, alignment: .leading)
        }
        .navigationTitle("Media Downloader")
        .toolbar {
            ToolbarItemGroup {
                Button {
                    viewModel.resetSampleLink(for: selectedMediaKind)
                } label: {
                    Label(selectedMediaKind == .video ? "Sample Video" : "Test Track", systemImage: selectedMediaKind.systemImage)
                }

                if showDetailedActivity {
                    Button {
                        viewModel.clearLog()
                    } label: {
                        Label("Clear Log", systemImage: "trash")
                    }
                    .disabled(viewModel.logText.isEmpty)
                }

                Button {
                    viewModel.copyDiagnostics()
                } label: {
                    Label("Copy Diagnostics", systemImage: "doc.on.doc")
                }
            }
        }
    }
}
