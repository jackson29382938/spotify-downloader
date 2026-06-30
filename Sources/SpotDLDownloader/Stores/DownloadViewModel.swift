import AppKit
import Foundation

@MainActor
final class DownloadViewModel: ObservableObject {
    @Published var linkText: String = Defaults.testTrackURL
    @Published var status: DownloadStatus = .idle
    @Published var logText: String = ""
    @Published var lastCommand: String = ""
    @Published var errorMessage: String?
    @Published var queueItems: [DownloadQueueItem] = []
    @Published var selectedQueueItemID: DownloadQueueItem.ID?
    @Published var healthReport: HelperHealthReport?
    @Published var isPreviewing = false
    @Published var isCheckingHealth = false
    @Published var progressItems: [DownloadProgressItem] = []
    @Published var progressSummary = DownloadProgressSummary()
    @Published var historyEntries: [HistoryEntry] = []
    @Published var isInstallingFFmpeg = false
    @Published var ffmpegInstallStatus: String?

    private let service = DownloadService()
    private var cancelledByUser = false
    private var activeDownloadURLs = Set<String>()
    private var outputLineBuffer = ""

    var canDownload: Bool {
        !status.isRunning && (queueItems.contains { $0.state != .failed } || parsedQueries.isEmpty == false)
    }

    var canRetryFailed: Bool {
        !status.isRunning && queueItems.contains { $0.state == .failed }
    }

    var canRepairLibrary: Bool {
        !status.isRunning
    }

    var selectedQueueItem: DownloadQueueItem? {
        guard let selectedQueueItemID else { return queueItems.first }
        return queueItems.first { $0.id == selectedQueueItemID }
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

    func refreshHealth(outputFolder: String) {
        isCheckingHealth = true
        service.health(outputFolder: outputFolder) { [weak self] result in
            DispatchQueue.main.async {
                guard let self else { return }
                self.isCheckingHealth = false
                switch result {
                case .success(let report):
                    self.healthReport = report
                case .failure(let error):
                    self.errorMessage = error.localizedDescription
                }
            }
        }
    }

    func previewQueue(outputFolder: String, mediaKind: MediaKind) {
        let queries = parsedQueries
        guard queries.isEmpty == false else {
            errorMessage = "Paste at least one Spotify or YouTube link."
            return
        }

        isPreviewing = true
        errorMessage = nil
        queueItems = queries.map { DownloadQueueItem(url: $0) }
        selectedQueueItemID = queueItems.first?.id

        service.preview(
            queries: queries,
            outputFolder: outputFolder,
            mediaKind: mediaKind
        ) { [weak self] result in
            DispatchQueue.main.async {
                guard let self else { return }
                self.isPreviewing = false
                switch result {
                case .success(let response):
                    self.queueItems = response.items.map { DownloadQueueItem(preview: $0) }
                        + response.errors.map { DownloadQueueItem(error: $0) }
                    self.selectedQueueItemID = self.queueItems.first?.id
                    if let firstError = response.errors.first {
                        self.errorMessage = firstError.message
                    }
                case .failure(let error):
                    self.errorMessage = error.localizedDescription
                    self.queueItems = queries.map { url in
                        var item = DownloadQueueItem(url: url)
                        item.state = .failed
                        item.message = error.localizedDescription
                        return item
                    }
                    self.selectedQueueItemID = self.queueItems.first?.id
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
        searchLyrics: Bool,
        writeLRC: Bool,
        cookiesBrowser: CookiesBrowser,
        artworkMaxSize: ArtworkMaxSize,
        artworkJpeg: Bool,
        debugLogging: Bool,
        queriesOverride: [String]? = nil
    ) {
        let queries = queriesOverride
            ?? (queueItems.isEmpty ? parsedQueries : queueItems.filter { $0.state != .failed }.map(\.url))
        guard queries.isEmpty == false else {
            errorMessage = "Paste at least one Spotify or YouTube link."
            return
        }

        if queueItems.isEmpty || Set(queueItems.map(\.url)) != Set(queries) {
            queueItems = queries.map { DownloadQueueItem(url: $0) }
            selectedQueueItemID = queueItems.first?.id
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
            searchLyrics: searchLyrics,
            writeLRC: writeLRC,
            cookiesBrowser: cookiesBrowser,
            artworkMaxSize: artworkMaxSize,
            artworkJpeg: artworkJpeg,
            debugLogging: debugLogging
        )

        cancelledByUser = false
        activeDownloadURLs = Set(queries)
        outputLineBuffer = ""
        errorMessage = nil
        logText = ""
        progressItems = []
        progressSummary = DownloadProgressSummary(title: "Starting", total: queries.count)
        lastCommand = command.displayString
        status = .running(startedAt: Date())
        updateQueueItems(for: activeDownloadURLs, state: .running, message: "Downloading")
        appendLog("$ \(command.displayString)\n\n")

        do {
            try service.download(
                command: command,
                output: { [weak self] text in
                    DispatchQueue.main.async {
                        self?.processOutput(text)
                    }
                },
                completion: { [weak self] code in
                    DispatchQueue.main.async {
                        guard let self else { return }
                        self.flushOutputBuffer()
                        if self.cancelledByUser {
                            self.status = .cancelled
                            self.updateQueueItems(for: self.activeDownloadURLs, state: .failed, message: "Cancelled")
                            self.finishRunningProgressItems(as: .cancelled, message: "Cancelled")
                        } else if code == 0 {
                            self.status = .succeeded
                            self.updateQueueItems(for: self.activeDownloadURLs, state: .succeeded, message: "Complete")
                            self.recalculateProgressSummary()
                            self.loadHistory()
                        } else {
                            self.status = .failed(code: code)
                            self.errorMessage = "The downloader exited with code \(code)."
                            self.updateQueueItems(for: self.activeDownloadURLs, state: .failed, message: "Exit \(code)")
                            self.finishRunningProgressItems(as: .failed, message: "Exit \(code)")
                        }
                        self.activeDownloadURLs.removeAll()
                    }
                }
            )
        } catch {
            status = .failed(code: 1)
            errorMessage = error.localizedDescription
            updateQueueItems(for: activeDownloadURLs, state: .failed, message: error.localizedDescription)
            activeDownloadURLs.removeAll()
            appendLog("\n\(error.localizedDescription)\n")
        }
    }

    func retryFailedItems(
        outputFolder: String,
        mediaKind: MediaKind,
        threads: Int,
        format: AudioFormat,
        bitrate: Bitrate,
        overwrite: ExistingFileBehavior,
        trackNumberPrefix: Bool,
        allowClosestMatch: Bool,
        searchLyrics: Bool,
        writeLRC: Bool,
        cookiesBrowser: CookiesBrowser,
        artworkMaxSize: ArtworkMaxSize,
        artworkJpeg: Bool,
        debugLogging: Bool
    ) {
        let failedURLs = queueItems.filter { $0.state == .failed }.map(\.url)
        guard failedURLs.isEmpty == false else { return }
        startDownload(
            outputFolder: outputFolder,
            mediaKind: mediaKind,
            threads: threads,
            format: format,
            bitrate: bitrate,
            overwrite: overwrite,
            trackNumberPrefix: trackNumberPrefix,
            allowClosestMatch: allowClosestMatch,
            searchLyrics: searchLyrics,
            writeLRC: writeLRC,
            cookiesBrowser: cookiesBrowser,
            artworkMaxSize: artworkMaxSize,
            artworkJpeg: artworkJpeg,
            debugLogging: debugLogging,
            queriesOverride: failedURLs
        )
    }

    func repairLibrary(
        folders: [String],
        apply: Bool,
        recursive: Bool,
        searchLyrics: Bool,
        updateArtwork: Bool,
        overwriteArtwork: Bool,
        minConfidence: Double,
        renamePattern: String? = nil
    ) {
        let validFolders = folders.filter { FileManager.default.fileExists(atPath: $0) }
        guard validFolders.isEmpty == false else {
            errorMessage = "Choose at least one existing music library folder."
            return
        }

        cancelledByUser = false
        outputLineBuffer = ""
        errorMessage = nil
        logText = ""
        progressItems = []
        progressSummary = DownloadProgressSummary(title: apply ? "Applying Library Cleanup" : "Scanning Library")
        let folderArgs = validFolders.map { "\"\($0)\"" }.joined(separator: " ")
        lastCommand = "library \(apply ? "--apply " : "")\(folderArgs)"
        status = .repairing(startedAt: Date())
        appendLog("$ \(lastCommand)\n\n")

        do {
            try service.repairLibrary(
                folders: validFolders,
                apply: apply,
                recursive: recursive,
                searchLyrics: searchLyrics,
                updateArtwork: updateArtwork,
                overwriteArtwork: overwriteArtwork,
                minConfidence: minConfidence,
                renamePattern: renamePattern,
                output: { [weak self] text in
                    DispatchQueue.main.async {
                        self?.processOutput(text)
                    }
                },
                completion: { [weak self] code in
                    DispatchQueue.main.async {
                        guard let self else { return }
                        self.flushOutputBuffer()
                        if self.cancelledByUser {
                            self.status = .cancelled
                            self.finishRunningProgressItems(as: .cancelled, message: "Cancelled")
                        } else if code == 0 {
                            self.status = .succeeded
                            self.recalculateProgressSummary()
                        } else {
                            self.status = .failed(code: code)
                            self.errorMessage = "Library cleanup exited with code \(code)."
                            self.finishRunningProgressItems(as: .failed, message: "Exit \(code)")
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

    func loadHistory() {
        historyEntries = service.downloadHistory()
    }

    func clearHistory() {
        service.clearHistory()
        historyEntries = []
    }

    func installFFmpeg() {
        guard !isInstallingFFmpeg else { return }
        isInstallingFFmpeg = true
        ffmpegInstallStatus = "Downloading ffmpeg…"

        do {
            try service.installFFmpeg(
                output: { [weak self] text in
                    DispatchQueue.main.async {
                        self?.processOutput(text)
                    }
                },
                completion: { [weak self] code in
                    DispatchQueue.main.async {
                        guard let self else { return }
                        self.isInstallingFFmpeg = false
                        if code == 0 {
                            self.ffmpegInstallStatus = "ffmpeg installed."
                            self.refreshHealth(outputFolder: Defaults.downloadsPath)
                        } else {
                            self.ffmpegInstallStatus = "ffmpeg install failed (exit \(code))."
                        }
                    }
                }
            )
        } catch {
            isInstallingFFmpeg = false
            ffmpegInstallStatus = error.localizedDescription
            errorMessage = error.localizedDescription
        }
    }

    func revealHistoryEntry(_ entry: HistoryEntry) {
        openExistingFolder(path: entry.outputFolder)
    }

    func resetSampleLink(for mediaKind: MediaKind) {
        linkText = mediaKind == .video ? Defaults.testVideoURL : Defaults.testTrackURL
    }

    func clearLog() {
        logText = ""
    }

    func removeQueueItem(_ item: DownloadQueueItem) {
        queueItems.removeAll { $0.id == item.id }
        if selectedQueueItemID == item.id {
            selectedQueueItemID = queueItems.first?.id
        }
    }

    func clearCompletedQueueItems() {
        queueItems.removeAll { $0.state == .succeeded }
        if let selectedQueueItemID, queueItems.contains(where: { $0.id == selectedQueueItemID }) == false {
            self.selectedQueueItemID = queueItems.first?.id
        }
    }

    func openFolder(path: String) {
        FileManager.default.createDirectoryIfNeeded(atPath: path)
        NSWorkspace.shared.open(URL(fileURLWithPath: path))
    }

    func openExistingFolder(path: String) {
        guard FileManager.default.fileExists(atPath: path) else {
            errorMessage = "Choose an existing folder."
            return
        }
        NSWorkspace.shared.open(URL(fileURLWithPath: path))
    }

    func revealOutput(for item: DownloadQueueItem, fallbackFolder: String) {
        let folder = item.outputFolder.isEmpty ? fallbackFolder : item.outputFolder
        openFolder(path: folder)
    }

    func copyDiagnostics() {
        var lines = [
            "Status: \(status.title)",
            "Last command: \(lastCommand)",
            "Log folder: \(Defaults.logsPath)"
        ]
        if let healthReport {
            lines.append("Sunnify parity: \(healthReport.sunnifyParity)")
            lines.append("Python: \(healthReport.python)")
            lines.append("Platform: \(healthReport.platform)")
            lines.append(contentsOf: healthReport.checks.map { "\($0.ok ? "OK" : "FAIL") \($0.name): \($0.detail)" })
        }
        if queueItems.isEmpty == false {
            lines.append("Queue:")
            lines.append(contentsOf: queueItems.map { "\($0.state.label): \($0.title) - \($0.url) \($0.message)" })
        }
        if progressItems.isEmpty == false {
            lines.append("Progress: \(progressSummary.statusText)")
            lines.append(contentsOf: progressItems.map { "\($0.state.label): \($0.displayTitle) - \($0.detailText)" })
        }
        if logText.isEmpty == false {
            lines.append("Activity:")
            lines.append(logText)
        }

        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(lines.joined(separator: "\n"), forType: .string)
    }

    private func processOutput(_ text: String) {
        outputLineBuffer += text
        while let newlineRange = outputLineBuffer.range(of: "\n") {
            let line = String(outputLineBuffer[..<newlineRange.lowerBound])
            outputLineBuffer.removeSubrange(outputLineBuffer.startIndex...newlineRange.lowerBound)
            processOutputLine(line)
        }
    }

    private func flushOutputBuffer() {
        guard outputLineBuffer.isEmpty == false else { return }
        processOutputLine(outputLineBuffer)
        outputLineBuffer = ""
    }

    private func processOutputLine(_ line: String) {
        if let event = decodeProgressEvent(from: line) {
            applyProgressEvent(event)
            return
        }

        if line.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            appendLog("\n")
        } else {
            appendLog(line + "\n")
        }
    }

    private func decodeProgressEvent(from line: String) -> DownloadProgressEvent? {
        let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.hasPrefix("{"), let data = trimmed.data(using: .utf8) else { return nil }
        return try? JSONDecoder().decode(DownloadProgressEvent.self, from: data)
    }

    private func applyProgressEvent(_ event: DownloadProgressEvent) {
        switch event.event {
        case "collection_start":
            progressSummary = DownloadProgressSummary(
                title: event.title ?? "Downloading",
                total: event.selectedCount ?? event.trackCount ?? event.total ?? progressSummary.total
            )
        case "collection_finished":
            progressSummary.completed = event.okCount ?? progressSummary.completed
            progressSummary.failed = event.failedCount ?? progressSummary.failed
            recalculateProgressSummary()
        case "track_progress":
            upsertProgressItem(from: event)
        default:
            break
        }
    }

    private func upsertProgressItem(from event: DownloadProgressEvent) {
        let fallbackID = event.label ?? event.title ?? UUID().uuidString
        let id = event.key?.isEmpty == false ? event.key! : fallbackID
        let state = event.state ?? .running
        let progress = max(0, min(1, event.progress ?? (state == .succeeded || state == .skipped ? 1 : 0)))

        if let existingIndex = progressItems.firstIndex(where: { $0.id == id }) {
            var item = progressItems[existingIndex]
            item.index = event.index ?? item.index
            item.total = event.total ?? item.total
            item.title = event.title?.isEmpty == false ? event.title! : item.title
            item.artists = event.artists?.isEmpty == false ? event.artists! : item.artists
            item.album = event.album?.isEmpty == false ? event.album! : item.album
            item.label = event.label?.isEmpty == false ? event.label! : item.label
            item.coverURL = event.coverURL?.isEmpty == false ? event.coverURL! : item.coverURL
            item.progress = progress
            item.state = state
            item.message = event.message ?? item.message
            item.path = event.path ?? item.path
            item.skipped = event.skipped ?? item.skipped
            progressItems[existingIndex] = item
        } else {
            progressItems.append(
                DownloadProgressItem(
                    id: id,
                    index: event.index,
                    total: event.total,
                    title: event.title ?? event.label ?? "Download",
                    artists: event.artists ?? "",
                    album: event.album ?? "",
                    label: event.label ?? event.title ?? "Download",
                    coverURL: event.coverURL ?? "",
                    progress: progress,
                    state: state,
                    message: event.message ?? state.label,
                    path: event.path,
                    skipped: event.skipped ?? false
                )
            )
        }

        progressItems.sort { left, right in
            switch (left.index, right.index) {
            case let (.some(lhs), .some(rhs)):
                return lhs == rhs ? left.displayTitle < right.displayTitle : lhs < rhs
            case (.some, .none):
                return true
            case (.none, .some):
                return false
            case (.none, .none):
                return left.displayTitle < right.displayTitle
            }
        }
        recalculateProgressSummary()
    }

    private func recalculateProgressSummary() {
        let completed = progressItems.filter { $0.state == .succeeded }.count
        let failed = progressItems.filter { $0.state == .failed || $0.state == .cancelled }.count
        let skipped = progressItems.filter { $0.state == .skipped }.count
        let total = max(progressSummary.total, progressItems.count)
        let averageProgress = progressItems.reduce(0) { $0 + $1.progress }
        let progress = total > 0 ? min(1, averageProgress / Double(total)) : 0

        progressSummary.completed = completed
        progressSummary.failed = failed
        progressSummary.skipped = skipped
        progressSummary.total = total
        progressSummary.progress = progressSummary.finished >= total && total > 0 ? 1 : progress
    }

    private func finishRunningProgressItems(as state: ProgressItemState, message: String) {
        progressItems = progressItems.map { item in
            var copy = item
            if copy.state == .running || copy.state == .queued {
                copy.state = state
                copy.message = message
                copy.progress = 1
            }
            return copy
        }
        recalculateProgressSummary()
    }

    private func appendLog(_ text: String) {
        logText += text
    }

    private func updateQueueItems(for urls: Set<String>, state: QueueItemState, message: String) {
        guard urls.isEmpty == false else { return }
        queueItems = queueItems.map { item in
            var copy = item
            if urls.contains(copy.url) {
                copy.state = state
                copy.message = message
            }
            return copy
        }
    }
}
