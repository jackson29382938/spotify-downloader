import SwiftUI

struct ContentView: View {
    @StateObject private var viewModel = DownloadViewModel()

    @AppStorage("downloadFolderPath") private var downloadFolderPath = Defaults.downloadsPath
    @AppStorage("mediaKind") private var mediaKind = MediaKind.audio.rawValue
    @AppStorage("downloadThreads") private var downloadThreads = 4
    @AppStorage("audioFormat") private var audioFormat = AudioFormat.mp3.rawValue
    @AppStorage("bitrate") private var bitrate = Bitrate.kbps192.rawValue
    @AppStorage("overwrite") private var overwrite = ExistingFileBehavior.skip.rawValue
    @AppStorage("trackNumberPrefix") private var trackNumberPrefix = true
    @AppStorage("allowClosestMatch") private var allowClosestMatch = false
    @AppStorage("debugLogging") private var debugLogging = false

    private var selectedMediaKind: MediaKind {
        MediaKind(rawValue: mediaKind) ?? .audio
    }

    private var selectedFormat: AudioFormat {
        AudioFormat(rawValue: audioFormat) ?? .mp3
    }

    private var selectedBitrate: Bitrate {
        Bitrate(rawValue: bitrate) ?? .kbps192
    }

    private var selectedOverwrite: ExistingFileBehavior {
        let behavior = ExistingFileBehavior(rawValue: overwrite) ?? .skip
        return selectedMediaKind == .video && behavior == .metadata ? .skip : behavior
    }

    private var overwriteOptions: [ExistingFileBehavior] {
        selectedMediaKind == .video ? [.skip, .force] : ExistingFileBehavior.allCases
    }

    private var overwriteSelection: Binding<String> {
        Binding(
            get: { selectedOverwrite.rawValue },
            set: { overwrite = $0 }
        )
    }

    var body: some View {
        NavigationSplitView {
            sidebar
        } detail: {
            mainPanel
        }
        .task {
            viewModel.checkDownloader()
        }
    }

    private var sidebar: some View {
        List {
            Section("Download") {
                StatusRow(status: viewModel.status)
                Label(selectedMediaKind.label, systemImage: selectedMediaKind.systemImage)
                Label("\(max(1, downloadThreads)) concurrent", systemImage: "speedometer")
                Label(
                    selectedMediaKind == .video ? "MP4" : selectedFormat.rawValue.uppercased(),
                    systemImage: selectedMediaKind == .video ? "film" : "music.note"
                )
                Label(trackNumberPrefix ? "Track numbers" : "No prefixes", systemImage: "number")
                Label(allowClosestMatch ? "Closest fallback" : "Strict match", systemImage: "magnifyingglass")
            }

            Section("Folder") {
                VStack(alignment: .leading, spacing: 6) {
                    Label(URL(fileURLWithPath: downloadFolderPath).lastPathComponent, systemImage: "folder")
                    Text(downloadFolderPath)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            }
        }
        .listStyle(.sidebar)
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

    private var mainPanel: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    downloadComposer
                    settingsStrip
                    logPanel
                }
                .padding(24)
                .frame(maxWidth: 980, alignment: .leading)
            }
        }
        .navigationTitle("Media Downloader")
        .toolbar {
            ToolbarItemGroup {
                Button {
                    viewModel.resetSampleLink(for: selectedMediaKind)
                } label: {
                    Label(selectedMediaKind == .video ? "Sample Video" : "Test Track", systemImage: selectedMediaKind.systemImage)
                }

                Button {
                    viewModel.clearLog()
                } label: {
                    Label("Clear Log", systemImage: "trash")
                }
                .disabled(viewModel.logText.isEmpty)
            }
        }
    }

    private var downloadComposer: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(selectedMediaKind == .video ? "YouTube Video Links" : "Spotify or YouTube Audio Links")
                        .font(.title2.weight(.semibold))
                    Text("\(viewModel.parsedQueries.count) queued")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Spacer()

                HStack(spacing: 10) {
                    if viewModel.status.isRunning {
                        Button(role: .destructive) {
                            viewModel.cancelDownload()
                        } label: {
                            Label("Cancel", systemImage: "stop.fill")
                        }
                    }

                    Button {
                        viewModel.startDownload(
                            outputFolder: downloadFolderPath,
                            mediaKind: selectedMediaKind,
                            threads: downloadThreads,
                            format: selectedFormat,
                            bitrate: selectedBitrate,
                            overwrite: selectedOverwrite,
                            trackNumberPrefix: trackNumberPrefix,
                            allowClosestMatch: allowClosestMatch,
                            debugLogging: debugLogging
                        )
                    } label: {
                        Label("Download", systemImage: "arrow.down.circle.fill")
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!viewModel.canDownload)
                }
            }

            TextEditor(text: $viewModel.linkText)
                .font(.system(.body, design: .monospaced))
                .scrollContentBackground(.hidden)
                .padding(10)
                .frame(minHeight: 120)
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 8))
                .overlay {
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(.separator.opacity(0.7))
                }

            if let errorMessage = viewModel.errorMessage {
                Label(errorMessage, systemImage: "exclamationmark.triangle.fill")
                    .font(.callout)
                    .foregroundStyle(.orange)
            }
        }
    }

    private var settingsStrip: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top, spacing: 18) {
                settingBlock("Media") {
                    Picker("Media", selection: $mediaKind) {
                        ForEach(MediaKind.allCases) { kind in
                            Label(kind.label, systemImage: kind.systemImage).tag(kind.rawValue)
                        }
                    }
                    .pickerStyle(.menu)
                    .labelsHidden()
                    .frame(width: 150)
                }

                settingBlock("Concurrent Downloads") {
                    Stepper(value: $downloadThreads, in: 1...16) {
                        Text("\(max(1, downloadThreads))")
                            .monospacedDigit()
                    }
                    .frame(width: 120)
                }

                if selectedMediaKind == .audio {
                    settingBlock("Format") {
                        Picker("Format", selection: $audioFormat) {
                            ForEach(AudioFormat.allCases) { format in
                                Text(format.rawValue.uppercased()).tag(format.rawValue)
                            }
                        }
                        .pickerStyle(.menu)
                        .labelsHidden()
                        .frame(width: 110)
                    }

                    settingBlock("Bitrate") {
                        Picker("Bitrate", selection: $bitrate) {
                            ForEach(Bitrate.allCases) { option in
                                Text(option.label).tag(option.rawValue)
                            }
                        }
                        .pickerStyle(.menu)
                        .labelsHidden()
                        .frame(width: 120)
                    }
                }

                Spacer(minLength: 0)
            }

            settingBlock("Existing Files") {
                Picker("Existing Files", selection: overwriteSelection) {
                    ForEach(overwriteOptions) { option in
                        Text(option.label).tag(option.rawValue)
                    }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(maxWidth: 320)
            }

            HStack(alignment: .top, spacing: 22) {
                settingBlock("Filenames") {
                    Toggle("Track numbers", isOn: $trackNumberPrefix)
                        .toggleStyle(.checkbox)
                        .fixedSize()
                }

                settingBlock("Matching") {
                    Toggle("Closest fallback", isOn: $allowClosestMatch)
                        .toggleStyle(.checkbox)
                        .fixedSize()
                }

                settingBlock("Diagnostics") {
                    Toggle("Debug logs", isOn: $debugLogging)
                        .toggleStyle(.checkbox)
                        .fixedSize()
                }

                Spacer(minLength: 0)
            }
        }
        .padding(14)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
    }

    private func settingBlock<Content: View>(
        _ title: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .fixedSize(horizontal: true, vertical: false)
            content()
        }
    }

    private var logPanel: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Activity")
                    .font(.headline)
                Spacer()
                StatusBadge(status: viewModel.status)
            }

            ScrollViewReader { proxy in
                ScrollView {
                    Text(viewModel.logText.isEmpty ? "Waiting." : viewModel.logText)
                        .font(.system(.caption, design: .monospaced))
                        .foregroundStyle(viewModel.logText.isEmpty ? .secondary : .primary)
                        .frame(maxWidth: .infinity, alignment: .topLeading)
                        .textSelection(.enabled)
                        .padding(12)
                        .id("log-bottom")
                }
                .frame(minHeight: 240)
                .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 8))
                .overlay {
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(.separator.opacity(0.65))
                }
                .onChange(of: viewModel.logText) {
                    proxy.scrollTo("log-bottom", anchor: .bottom)
                }
            }
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
        case .running:
            .accentColor
        case .cancelled:
            .secondary
        default:
            .primary
        }
    }
}

private struct StatusBadge: View {
    let status: DownloadStatus

    var body: some View {
        Label(status.title, systemImage: status.systemImage)
            .font(.caption.weight(.medium))
            .foregroundStyle(.secondary)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(.thinMaterial, in: Capsule())
    }
}
