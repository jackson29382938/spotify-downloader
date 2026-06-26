import AppKit
import Foundation

@MainActor
final class DownloadViewModel: ObservableObject {
    @Published var linkText: String = Defaults.testTrackURL
    @Published var status: DownloadStatus = .idle
    @Published var logText: String = ""
    @Published var lastCommand: String = ""
    @Published var errorMessage: String?

    private let service = DownloadService()
    private var cancelledByUser = false

    var canDownload: Bool {
        !status.isRunning && parsedQueries.isEmpty == false
    }

    var parsedQueries: [String] {
        linkText
            .components(separatedBy: .newlines)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    func checkDownloader() {
        status = .checking
        service.checkDependencies { [weak self] result in
            DispatchQueue.main.async {
                guard let self else { return }
                switch result {
                case .success(let version):
                    self.status = .ready(version: version)
                case .failure(let error):
                    self.status = .missingDependency(error.localizedDescription)
                    self.errorMessage = "Install dependencies with: python3 -m pip install -r requirements.txt"
                }
            }
        }
    }

    func startDownload(
        outputFolder: String,
        mediaKind: MediaKind,
        threads: Int,
        format: AudioFormat,
        bitrate: Bitrate,
        overwrite: ExistingFileBehavior,
        trackNumberPrefix: Bool,
        allowClosestMatch: Bool,
        debugLogging: Bool
    ) {
        let queries = parsedQueries
        guard queries.isEmpty == false else {
            errorMessage = "Paste at least one Spotify or YouTube link."
            return
        }

        FileManager.default.createDirectoryIfNeeded(atPath: outputFolder)

        let command = DownloadCommand(
            queries: queries,
            outputFolder: outputFolder,
            mediaKind: mediaKind,
            threads: threads,
            format: format,
            bitrate: bitrate,
            overwrite: overwrite,
            trackNumberPrefix: trackNumberPrefix,
            allowClosestMatch: allowClosestMatch,
            debugLogging: debugLogging
        )

        cancelledByUser = false
        errorMessage = nil
        logText = ""
        lastCommand = command.displayString
        status = .running(startedAt: Date())
        appendLog("$ \(command.displayString)\n\n")

        do {
            try service.download(
                command: command,
                output: { [weak self] text in
                    DispatchQueue.main.async {
                        self?.appendLog(text)
                    }
                },
                completion: { [weak self] code in
                    DispatchQueue.main.async {
                        guard let self else { return }
                        if self.cancelledByUser {
                            self.status = .cancelled
                        } else if code == 0 {
                            self.status = .succeeded
                        } else {
                            self.status = .failed(code: code)
                            self.errorMessage = "The downloader exited with code \(code)."
                        }
                    }
                }
            )
        } catch {
            status = .failed(code: 1)
            errorMessage = error.localizedDescription
            appendLog("\n\(error.localizedDescription)\n")
        }
    }

    func cancelDownload() {
        cancelledByUser = true
        service.cancel()
    }

    func resetSampleLink(for mediaKind: MediaKind) {
        linkText = mediaKind == .video ? Defaults.testVideoURL : Defaults.testTrackURL
    }

    func clearLog() {
        logText = ""
    }

    func openFolder(path: String) {
        FileManager.default.createDirectoryIfNeeded(atPath: path)
        NSWorkspace.shared.open(URL(fileURLWithPath: path))
    }

    private func appendLog(_ text: String) {
        logText += text
    }
}
