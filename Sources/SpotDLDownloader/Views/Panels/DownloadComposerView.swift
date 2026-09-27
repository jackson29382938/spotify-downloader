import SwiftUI

struct DownloadComposerView: View {
    @ObservedObject var viewModel: DownloadViewModel

    @AppStorage("downloadFolderPath") private var downloadFolderPath = Defaults.downloadsPath
    @AppStorage("mediaKind") private var mediaKind = MediaKind.audio.rawValue
    @AppStorage("downloadThreads") private var downloadThreads = 4
    @AppStorage("audioFormat") private var audioFormat = AudioFormat.mp3.rawValue
    @AppStorage("bitrate") private var bitrate = Bitrate.kbps192.rawValue
    @AppStorage("overwrite") private var overwrite = ExistingFileBehavior.skip.rawValue
    @AppStorage("trackNumberPrefix") private var trackNumberPrefix = true
    @AppStorage("matchFlexibility") private var matchFlexibility = MatchFlexibility.defaultValue
    @AppStorage("searchLyrics") private var searchLyrics = true
    @AppStorage("lyricsStyle") private var lyricsStyle = LyricsStyle.plain.rawValue
    @AppStorage("cookiesBrowser") private var cookiesBrowser = CookiesBrowser.none.rawValue
    @AppStorage("artworkMaxSize") private var artworkMaxSize = ArtworkMaxSize.unlimited.rawValue
    @AppStorage("artworkJpeg") private var artworkJpeg = false
    @AppStorage("debugLogging") private var debugLogging = false
    @AppStorage("addToAppleMusic") private var addToAppleMusic = false
    @AppStorage("appleMusicPlaylistName") private var appleMusicPlaylistName = Defaults.appleMusicPlaylistName
    @AppStorage("downloadRetries") private var downloadRetries = 2
    @State private var confirmDeleteCompleted = false
    @FocusState private var inputFocused: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var selectedMediaKind: MediaKind {
        MediaKind(rawValue: mediaKind) ?? .audio
    }

    private var selectedCookiesBrowser: CookiesBrowser {
        CookiesBrowser(rawValue: cookiesBrowser) ?? .none
    }

    private var selectedArtworkMaxSize: ArtworkMaxSize {
        ArtworkMaxSize(rawValue: artworkMaxSize) ?? .unlimited
    }

    private var selectedLyricsStyle: LyricsStyle {
        LyricsStyle(rawValue: lyricsStyle) ?? .plain
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

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .center) {
                    VStack(alignment: .leading, spacing: 4) {
                        Label(
                            selectedMediaKind == .video ? "Add video links" : "Add your links",
                            systemImage: selectedMediaKind == .video ? "video" : "link"
                        )
                        .font(.headline)
                        .labelStyle(.titleAndIcon)

                        Text(selectedMediaKind == .video ? "YouTube · one link per line" : "Spotify or YouTube · one link per line")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }

                    Spacer()

                    Text("\(viewModel.parsedQueries.count) link\(viewModel.parsedQueries.count == 1 ? "" : "s")")
                        .font(.caption.weight(.medium).monospacedDigit())
                        .foregroundStyle(Theme.accent)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 5)
                        .background(Theme.accent.opacity(0.08), in: Capsule())
                }

                ZStack(alignment: .topLeading) {
                    TextEditor(text: $viewModel.linkText)
                        .font(.system(size: 13, design: .monospaced))
                        .scrollContentBackground(.hidden)
                        .focused($inputFocused)
                        .accessibilityLabel("Links to download, one per line")
                    if viewModel.linkText.isEmpty {
                        Text("Paste a song, album, or playlist link…")
                            .font(.system(size: 13, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .padding(.horizontal, 5)
                            .padding(.top, 1)
                            .allowsHitTesting(false)
                    }
                }
                    .padding(12)
                    .frame(height: 128)
                    .background(Theme.inset, in: RoundedRectangle(cornerRadius: Theme.innerRadius))
                    .overlay {
                        RoundedRectangle(cornerRadius: Theme.innerRadius)
                            .stroke(inputFocused ? Theme.accent.opacity(0.8) : Theme.border, lineWidth: inputFocused ? 1.5 : 1)
                    }
                    .animation(reduceMotion ? nil : .easeOut(duration: 0.15), value: inputFocused)

                actionButtons

                if let errorMessage = viewModel.errorMessage {
                    Label(errorMessage, systemImage: "exclamationmark.triangle.fill")
                        .font(.callout)
                        .foregroundStyle(.orange)
                }

                if let appleMusicMessage = viewModel.appleMusicMessage {
                    Label(
                        appleMusicMessage,
                        systemImage: viewModel.appleMusicMessageIsError ? "exclamationmark.triangle.fill" : "music.note.list"
                    )
                    .font(.callout)
                    .foregroundStyle(viewModel.appleMusicMessageIsError ? .orange : .secondary)
                }
            }
        }
        .confirmationDialog(
            "Stop this download and delete completed files?",
            isPresented: $confirmDeleteCompleted,
            titleVisibility: .visible
        ) {
            Button("Stop & Delete Completed", role: .destructive) {
                viewModel.cancelAndDeleteCompleted()
            }
            Button("Keep Downloading", role: .cancel) {}
        } message: {
            Text("Only files completed during this run will be deleted. Files that existed before this download will be kept.")
        }
    }

    private var actionButtons: some View {
        FlowLayout(horizontalSpacing: 10, verticalSpacing: 10) {
            if viewModel.isDownloadRunning {
                Menu {
                    Button {
                        viewModel.pauseAndKeepCompleted()
                    } label: {
                        Label("Pause & Keep Completed", systemImage: "pause.fill")
                    }

                    Button {
                        viewModel.stopAndKeepCompleted()
                    } label: {
                        Label("Stop & Keep Completed", systemImage: "stop.fill")
                    }

                    Divider()

                    Button(role: .destructive) {
                        confirmDeleteCompleted = true
                    } label: {
                        Label("Stop & Delete Completed", systemImage: "trash")
                    }
                } label: {
                    Label("Pause / Stop", systemImage: "pause.circle")
                }
            }

            Button {
                viewModel.previewQueue(
                    outputFolder: downloadFolderPath,
                    mediaKind: selectedMediaKind
                )
            } label: {
                Label(viewModel.isPreviewing ? "Previewing" : "Preview", systemImage: "doc.text.magnifyingglass")
            }
            .disabled(viewModel.status.isRunning || viewModel.isPreviewing || viewModel.parsedQueries.isEmpty)

            if viewModel.canRetryFailed {
                retryButton
            }

            downloadButton
        }
        .controlSize(.large)
    }

    private var retryButton: some View {
            Button {
                viewModel.retryFailedItems(
                    outputFolder: downloadFolderPath,
                    mediaKind: selectedMediaKind,
                    threads: downloadThreads,
                    format: selectedFormat,
                    bitrate: selectedBitrate,
                    overwrite: selectedOverwrite,
                    trackNumberPrefix: trackNumberPrefix,
                    allowClosestMatch: matchFlexibility >= 1,
                    matchFlexibility: matchFlexibility,
                    searchLyrics: searchLyrics,
                    lyricsStyle: selectedLyricsStyle,
                    cookiesBrowser: selectedCookiesBrowser,
                    artworkMaxSize: selectedArtworkMaxSize,
                    artworkJpeg: artworkJpeg,
                    debugLogging: debugLogging,
                    addToAppleMusic: addToAppleMusic,
                    appleMusicPlaylistName: appleMusicPlaylistName,
                    retries: downloadRetries
                )
            } label: {
                Label("Retry Failed", systemImage: "arrow.clockwise")
            }
            .disabled(!viewModel.canRetryFailed)
    }

    private var downloadButton: some View {
            Button {
                viewModel.startDownload(
                    outputFolder: downloadFolderPath,
                    mediaKind: selectedMediaKind,
                    threads: downloadThreads,
                    format: selectedFormat,
                    bitrate: selectedBitrate,
                    overwrite: selectedOverwrite,
                    trackNumberPrefix: trackNumberPrefix,
                    allowClosestMatch: matchFlexibility >= 1,
                    matchFlexibility: matchFlexibility,
                    searchLyrics: searchLyrics,
                    lyricsStyle: selectedLyricsStyle,
                    cookiesBrowser: selectedCookiesBrowser,
                    artworkMaxSize: selectedArtworkMaxSize,
                    artworkJpeg: artworkJpeg,
                    debugLogging: debugLogging,
                    addToAppleMusic: addToAppleMusic,
                    appleMusicPlaylistName: appleMusicPlaylistName,
                    retries: downloadRetries
                )
            } label: {
                Label(
                    viewModel.isPaused ? "Resume" : "Download",
                    systemImage: viewModel.isPaused ? "play.circle.fill" : "arrow.down.circle.fill"
                )
            }
            .buttonStyle(.borderedProminent)
            .keyboardShortcut(.return, modifiers: .command)
            .disabled(!viewModel.canDownload)
    }
}
