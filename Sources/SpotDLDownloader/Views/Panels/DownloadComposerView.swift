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
    @AppStorage("allowClosestMatch") private var allowClosestMatch = false
    @AppStorage("searchLyrics") private var searchLyrics = true
    @AppStorage("writeLRC") private var writeLRC = true
    @AppStorage("cookiesBrowser") private var cookiesBrowser = CookiesBrowser.none.rawValue
    @AppStorage("artworkMaxSize") private var artworkMaxSize = ArtworkMaxSize.unlimited.rawValue
    @AppStorage("artworkJpeg") private var artworkJpeg = false
    @AppStorage("debugLogging") private var debugLogging = false

    private var selectedMediaKind: MediaKind {
        MediaKind(rawValue: mediaKind) ?? .audio
    }

    private var selectedCookiesBrowser: CookiesBrowser {
        CookiesBrowser(rawValue: cookiesBrowser) ?? .none
    }

    private var selectedArtworkMaxSize: ArtworkMaxSize {
        ArtworkMaxSize(rawValue: artworkMaxSize) ?? .unlimited
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
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 4) {
                        Label(
                            selectedMediaKind == .video ? "YouTube Video Links" : "Spotify or YouTube Audio Links",
                            systemImage: selectedMediaKind == .video ? "video" : "link"
                        )
                        .font(.title2.weight(.semibold))
                        .labelStyle(.titleAndIcon)

                        Text("\(viewModel.parsedQueries.count) queued · one link per line")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }

                    Spacer()

                    actionButtons
                }

                TextEditor(text: $viewModel.linkText)
                    .font(.system(.body, design: .monospaced))
                    .scrollContentBackground(.hidden)
                    .padding(10)
                    .frame(minHeight: 120)
                    .background(.thinMaterial, in: RoundedRectangle(cornerRadius: Theme.innerRadius))
                    .overlay {
                        RoundedRectangle(cornerRadius: Theme.innerRadius)
                            .stroke(.separator.opacity(0.7))
                    }

                if let errorMessage = viewModel.errorMessage {
                    Label(errorMessage, systemImage: "exclamationmark.triangle.fill")
                        .font(.callout)
                        .foregroundStyle(.orange)
                }
            }
        }
    }

    private var actionButtons: some View {
        HStack(spacing: 10) {
            if viewModel.status.isRunning {
                Button(role: .destructive) {
                    viewModel.cancelDownload()
                } label: {
                    Label("Cancel", systemImage: "stop.fill")
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

            Button {
                viewModel.retryFailedItems(
                    outputFolder: downloadFolderPath,
                    mediaKind: selectedMediaKind,
                    threads: downloadThreads,
                    format: selectedFormat,
                    bitrate: selectedBitrate,
                    overwrite: selectedOverwrite,
                    trackNumberPrefix: trackNumberPrefix,
                    allowClosestMatch: allowClosestMatch,
                    searchLyrics: searchLyrics,
                    writeLRC: writeLRC,
                    cookiesBrowser: selectedCookiesBrowser,
                    artworkMaxSize: selectedArtworkMaxSize,
                    artworkJpeg: artworkJpeg,
                    debugLogging: debugLogging
                )
            } label: {
                Label("Retry Failed", systemImage: "arrow.clockwise")
            }
            .disabled(!viewModel.canRetryFailed)

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
                    searchLyrics: searchLyrics,
                    writeLRC: writeLRC,
                    cookiesBrowser: selectedCookiesBrowser,
                    artworkMaxSize: selectedArtworkMaxSize,
                    artworkJpeg: artworkJpeg,
                    debugLogging: debugLogging
                )
            } label: {
                Label("Download", systemImage: "arrow.down.circle.fill")
            }
            .buttonStyle(.borderedProminent)
            .disabled(!viewModel.canDownload)
        }
    }
}
