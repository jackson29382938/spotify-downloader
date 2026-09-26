import AppKit
import Foundation

/// Which page started the run that fills the progress list.
enum ProgressSource {
    case download
    case library
}

@MainActor
final class DownloadViewModel: ObservableObject {
    private enum DownloadStopAction {
        case none
        case pauseKeepCompleted
        case cancelDeleteCompleted
    }

    @Published var linkText: String = Defaults.testTrackURL
    @Published var status: DownloadStatus = .idle
    /// Activity lines, newest first, capped so long runs stay responsive.
    @Published private(set) var activityLines: [String] = []

    /// The activity log in reading order (oldest first), for copying.
    var logText: String {
        activityLines.reversed().joined(separator: "\n")
    }
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
    @Published var appleMusicMessage: String?
    @Published var appleMusicMessageIsError = false
    @Published var isAddingToAppleMusic = false
    @Published var progressSource = ProgressSource.download

    private let service = DownloadService()
    private let appleMusicService = AppleMusicService()
    private var cancelledByUser = false
    private var downloadStopAction = DownloadStopAction.none
    private var activeDownloadURLs = Set<String>()
    private var activeOutputFolder = ""
    private var previewedQueries: [String] = []
    private var outputLineBuffer = ""
    private var pendingOutputLines: [String] = []
    private var outputFlushScheduled = false

    private static let outputFlushInterval: TimeInterval = 0.15
    private static let maxActivityLines = 1_500
    private static let eventDecoder = JSONDecoder()

    var isDownloadRunning: Bool {
        if case .running = status { return true }
        return false
    }

    var isPaused: Bool {
        if case .paused = status { return true }
        return false
    }

    var canDownload: Bool {
        !status.isRunning
            && !isPreviewing
            && !isAddingToAppleMusic
            && (queueItems.contains { $0.state != .failed } || parsedQueries.isEmpty == false)
    }

    var canRetryFailed: Bool {
        !status.isRunning && !isAddingToAppleMusic && queueItems.contains { $0.state == .failed }
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

    static func selectedQueries(
        editor: [String], previewed: [String], queue: [DownloadQueueItem], override: [String]?
    ) -> [String] {
        if let override { return override }
        let runnable = queue.filter { $0.state != .failed }.map(\.url)
        return editor != previewed || runnable.isEmpty ? editor : runnable
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
        previewedQueries = queries
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
                guard self.parsedQueries == queries else {
                    self.queueItems = self.parsedQueries.map { DownloadQueueItem(url: $0) }
                    self.previewedQueries = []
                    return
                }
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
        matchFlexibility: Double,
        searchLyrics: Bool,
        lyricsStyle: LyricsStyle,
        writeLRC: Bool,
        cookiesBrowser: CookiesBrowser,
        artworkMaxSize: ArtworkMaxSize,
        artworkJpeg: Bool,
        debugLogging: Bool,
        addToAppleMusic: Bool,
        appleMusicPlaylistName: String,
        retries: Int,
        queriesOverride: [String]? = nil
    ) {
        let editorChanged = parsedQueries != previewedQueries
        let queries = Self.selectedQueries(
            editor: parsedQueries, previewed: previewedQueries,
            queue: queueItems, override: queriesOverride
        )
        guard queries.isEmpty == false else {
            errorMessage = "Paste at least one Spotify or YouTube link."
            return
        }

        if editorChanged || queueItems.map(\.url) != queries {
            queueItems = queries.map { DownloadQueueItem(url: $0) }
            selectedQueueItemID = queueItems.first?.id
            previewedQueries = parsedQueries
        }

        do {
            try FileManager.default.createDirectoryIfNeeded(atPath: outputFolder)
        } catch {
            errorMessage = "Could not use the download folder \(outputFolder): \(error.localizedDescription) Choose another folder in the sidebar."
            return
        }

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
            matchFlexibility: matchFlexibility,
            searchLyrics: searchLyrics,
            lyricsStyle: lyricsStyle,
            writeLRC: writeLRC,
            cookiesBrowser: cookiesBrowser,
            artworkMaxSize: artworkMaxSize,
            artworkJpeg: artworkJpeg,
            debugLogging: debugLogging,
            retries: retries
        )

        cancelledByUser = false
        downloadStopAction = .none
        activeDownloadURLs = Set(queries)
        activeOutputFolder = URL(fileURLWithPath: outputFolder).standardizedFileURL.path
        resetOutputState()
        errorMessage = nil
        appleMusicMessage = nil
        appleMusicMessageIsError = false
        activityLines.removeAll()
        progressSource = .download
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
                        switch self.downloadStopAction {
                        case .pauseKeepCompleted:
                            self.status = .paused
                            self.updateQueueItems(
                                for: self.activeDownloadURLs,
                                state: .queued,
                                message: "Paused — press Download to resume"
                            )
                            self.finishRunningProgressItems(as: .paused, message: "Paused")
                        case .cancelDeleteCompleted:
                            let deletion = self.deleteCompletedFilesFromActiveRun()
                            self.status = .cancelled
                            let deletionMessage = deletion.failed == 0
                                ? "Cancelled · deleted \(deletion.deleted) completed file\(deletion.deleted == 1 ? "" : "s")"
                                : "Cancelled · deleted \(deletion.deleted), could not delete \(deletion.failed)"
                            self.updateQueueItems(for: self.activeDownloadURLs, state: .failed, message: deletionMessage)
                            self.finishRunningProgressItems(as: .cancelled, message: "Cancelled")
                            if deletion.failed > 0 {
                                self.errorMessage = "Some completed files could not be deleted. Check the activity log for details."
                            }
                        case .none:
                            if code == 0 {
                                self.status = .succeeded
                                self.finishRunningQueueItems(as: .succeeded, message: "Complete")
                                self.recalculateProgressSummary()
                            } else {
                                self.status = .failed(code: code)
                                self.errorMessage = "The downloader exited with code \(code)."
                                self.finishRunningQueueItems(as: .failed, message: "Exit \(code)")
                                self.finishRunningProgressItems(as: .failed, message: "Exit \(code)")
                            }
                        }
                        self.loadHistory()
                        if self.downloadStopAction == .none, addToAppleMusic, mediaKind == .audio {
                            self.addCompletedFilesToAppleMusic(playlistBaseName: appleMusicPlaylistName)
                        }
                        self.activeDownloadURLs.removeAll()
                        self.activeOutputFolder = ""
                        self.downloadStopAction = .none
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
        matchFlexibility: Double,
        searchLyrics: Bool,
        lyricsStyle: LyricsStyle,
        writeLRC: Bool,
        cookiesBrowser: CookiesBrowser,
        artworkMaxSize: ArtworkMaxSize,
        artworkJpeg: Bool,
        debugLogging: Bool,
        addToAppleMusic: Bool,
        appleMusicPlaylistName: String,
        retries: Int
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
            matchFlexibility: matchFlexibility,
            searchLyrics: searchLyrics,
            lyricsStyle: lyricsStyle,
            writeLRC: writeLRC,
            cookiesBrowser: cookiesBrowser,
            artworkMaxSize: artworkMaxSize,
            artworkJpeg: artworkJpeg,
            debugLogging: debugLogging,
            addToAppleMusic: addToAppleMusic,
            appleMusicPlaylistName: appleMusicPlaylistName,
            retries: retries,
            queriesOverride: failedURLs
        )
    }

    private func addCompletedFilesToAppleMusic(playlistBaseName: String) {
        let paths = progressItems.compactMap { item -> String? in
            guard item.state == .succeeded || item.state == .skipped else { return nil }
            return item.path
        }
        appleMusicMessage = "Adding \(paths.count) track\(paths.count == 1 ? "" : "s") to Apple Music…"
        appleMusicMessageIsError = false
        isAddingToAppleMusic = true

        appleMusicService.addToPlaylist(filePaths: paths, playlistName: playlistBaseName) { [weak self] result in
            DispatchQueue.main.async {
                guard let self else { return }
                self.isAddingToAppleMusic = false
                switch result {
                case .success(let importResult):
                    AppleMusicPlaylistChecker.shared.remember(importResult.playlistName)
                    let tracks = "track\(importResult.addedCount == 1 ? "" : "s")"
                    let target = importResult.reusedExistingPlaylist
                        ? "your existing playlist “\(importResult.playlistName)”"
                        : "new playlist “\(importResult.playlistName)”"
                    let presentText = importResult.alreadyPresentCount > 0
                        ? " · \(importResult.alreadyPresentCount) already there"
                        : ""
                    let failureText = importResult.failedCount > 0
                        ? " · \(importResult.failedCount) could not be added"
                        : ""
                    self.appleMusicMessage = "Added \(importResult.addedCount) \(tracks) to \(target)\(presentText)\(failureText)."
                    self.appleMusicMessageIsError = importResult.failedCount > 0
                case .failure(let error):
                    self.appleMusicMessage = error.localizedDescription
                    self.appleMusicMessageIsError = true
                }
            }
        }
    }

    func repairLibrary(
        folders: [String],
        apply: Bool,
        recursive: Bool,
        searchLyrics: Bool,
        lyricsStyle: LyricsStyle,
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
        resetOutputState()
        errorMessage = nil
        activityLines.removeAll()
        progressSource = .library
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
                lyricsStyle: lyricsStyle,
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

    /// Moves lyrics from `.lrc` sidecar files into the matching audio files.
    func embedLRCFiles(folders: [String], recursive: Bool, keepLRC: Bool, lyricsStyle: LyricsStyle) {
        runLyricsTask(
            folders: folders,
            title: "Embedding Lyrics",
            commandName: "embed-lrc",
            failureMessage: "Some lyrics could not be embedded. See the progress list for details."
        ) { service, validFolders, output, completion in
            try service.embedLRCFiles(
                folders: validFolders,
                recursive: recursive,
                keepLRC: keepLRC,
                lyricsStyle: lyricsStyle,
                output: output,
                completion: completion
            )
        }
    }

    /// Rewrites lyrics tags that contain [00:12.34] timestamps as clean text.
    func cleanLyricsTimestamps(folders: [String], recursive: Bool) {
        runLyricsTask(
            folders: folders,
            title: "Removing Lyric Timestamps",
            commandName: "clean-lyrics",
            failureMessage: "Some lyrics could not be cleaned. See the progress list for details."
        ) { service, validFolders, output, completion in
            try service.cleanLyricsTimestamps(
                folders: validFolders,
                recursive: recursive,
                output: output,
                completion: completion
            )
        }
    }

    private func runLyricsTask(
        folders: [String],
        title: String,
        commandName: String,
        failureMessage: String,
        start: (DownloadService, [String], @escaping (String) -> Void, @escaping (Int32) -> Void) throws -> Void
    ) {
        let validFolders = folders.filter { FileManager.default.fileExists(atPath: $0) }
        guard validFolders.isEmpty == false else {
            errorMessage = "Choose at least one existing music folder."
            return
        }

        cancelledByUser = false
        resetOutputState()
        errorMessage = nil
        activityLines.removeAll()
        progressSource = .library
        progressItems = []
        progressSummary = DownloadProgressSummary(title: title)
        let folderArgs = validFolders.map { "\"\($0)\"" }.joined(separator: " ")
        lastCommand = "\(commandName) \(folderArgs)"
        status = .repairing(startedAt: Date())
        appendLog("$ \(lastCommand)\n\n")

        do {
            try start(
                service,
                validFolders,
                { [weak self] text in
                    DispatchQueue.main.async {
                        self?.processOutput(text)
                    }
                },
                { [weak self] code in
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
                            self.errorMessage = failureMessage
                            self.recalculateProgressSummary()
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

    func pauseAndKeepCompleted() {
        guard isDownloadRunning else { return }
        downloadStopAction = .pauseKeepCompleted
        service.cancel()
    }

    func cancelAndDeleteCompleted() {
        guard isDownloadRunning else { return }
        downloadStopAction = .cancelDeleteCompleted
        service.cancel()
    }

    func cancelDownload() {
        cancelledByUser = true
        service.cancel()
    }

    private func deleteCompletedFilesFromActiveRun() -> (deleted: Int, failed: Int) {
        let root = URL(fileURLWithPath: activeOutputFolder).standardizedFileURL.path
        guard root.isEmpty == false else { return (0, 0) }
        let rootPrefix = root.hasSuffix("/") ? root : root + "/"
        let allowedExtensions = Set(["mp3", "m4a", "flac", "opus", "ogg", "wav", "mp4", "webm", "mkv"])
        var deleted = 0
        var failed = 0

        for index in progressItems.indices where progressItems[index].state == .succeeded {
            guard let path = progressItems[index].path else { continue }
            let fileURL = URL(fileURLWithPath: path).standardizedFileURL
            let standardizedPath = fileURL.path
            var isDirectory = ObjCBool(false)
            let exists = FileManager.default.fileExists(atPath: standardizedPath, isDirectory: &isDirectory)
            guard standardizedPath.hasPrefix(rootPrefix),
                  allowedExtensions.contains(fileURL.pathExtension.lowercased()),
                  (!exists || !isDirectory.boolValue),
                  progressItems[index].createdThisRun else {
                failed += 1
                appendLog("Kept completed file because it was not verified as a new file from this run: \(standardizedPath)\n")
                continue
            }

            do {
                if exists {
                    try FileManager.default.removeItem(atPath: standardizedPath)
                    deleted += 1
                }
                progressItems[index].state = .cancelled
                progressItems[index].message = "Deleted after cancellation"
                progressItems[index].path = nil
            } catch {
                failed += 1
                appendLog("Could not delete \(standardizedPath): \(error.localizedDescription)\n")
                continue
            }

            let lrcPath = fileURL.deletingPathExtension().appendingPathExtension("lrc").path
            do {
                if FileManager.default.fileExists(atPath: lrcPath) {
                    try FileManager.default.removeItem(atPath: lrcPath)
                }
            } catch {
                failed += 1
                appendLog("Could not delete \(lrcPath): \(error.localizedDescription)\n")
            }
        }
        recalculateProgressSummary()
        return (deleted, failed)
    }

    func loadHistory() {
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let entries = DownloadService.downloadHistory()
            DispatchQueue.main.async {
                self?.historyEntries = entries
            }
        }
    }

    func clearHistory() {
        service.clearHistory()
        historyEntries = []
    }

    func installFFmpeg() {
        guard !isInstallingFFmpeg else { return }
        isInstallingFFmpeg = true
        ffmpegInstallStatus = "Installing ffmpeg with Homebrew…"

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
        activityLines.removeAll()
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
        do {
            try FileManager.default.createDirectoryIfNeeded(atPath: path)
        } catch {
            errorMessage = "Could not open \(path): \(error.localizedDescription)"
            return
        }
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
            pendingOutputLines.append(String(outputLineBuffer[..<newlineRange.lowerBound]))
            outputLineBuffer.removeSubrange(outputLineBuffer.startIndex...newlineRange.lowerBound)
        }
        guard outputFlushScheduled == false, pendingOutputLines.isEmpty == false else { return }
        outputFlushScheduled = true
        DispatchQueue.main.asyncAfter(deadline: .now() + Self.outputFlushInterval) { [weak self] in
            self?.drainPendingOutput()
        }
    }

    private func flushOutputBuffer() {
        if outputLineBuffer.isEmpty == false {
            pendingOutputLines.append(outputLineBuffer)
            outputLineBuffer = ""
        }
        drainPendingOutput()
    }

    private func resetOutputState() {
        outputLineBuffer = ""
        pendingOutputLines.removeAll()
    }

    /// Applies every buffered helper line in one pass. The helper can print
    /// thousands of lines for a big playlist; publishing once per batch keeps
    /// SwiftUI from redrawing the whole window for each line.
    private func drainPendingOutput() {
        outputFlushScheduled = false
        guard pendingOutputLines.isEmpty == false else { return }
        let lines = pendingOutputLines
        pendingOutputLines.removeAll(keepingCapacity: true)

        var items = progressItems
        var summary = progressSummary
        var indexByID = Dictionary(items.enumerated().map { ($1.id, $0) }, uniquingKeysWith: { first, _ in first })
        var itemsChanged = false
        var needsSort = false
        var logLines: [String] = []

        for line in lines {
            guard let event = decodeProgressEvent(from: line) else {
                logLines.append(line)
                continue
            }
            switch event.event {
            case "collection_start":
                summary = DownloadProgressSummary(
                    title: event.title ?? "Downloading",
                    total: event.selectedCount ?? event.trackCount ?? event.total ?? summary.total
                )
            case "collection_finished":
                summary.completed = event.okCount ?? summary.completed
                summary.failed = event.failedCount ?? summary.failed
                itemsChanged = true
            case "track_progress":
                if Self.upsertProgressItem(from: event, into: &items, indexByID: &indexByID) {
                    needsSort = true
                }
                itemsChanged = true
            case "source_finished":
                if let url = event.sourceURL {
                    let failed = event.failedCount ?? 0
                    let warnings = event.warningCount ?? 0
                    let message = failed > 0
                        ? "\(failed) failed, \(event.okCount ?? 0) completed"
                        : (warnings > 0 ? "Completed with \(warnings) metadata warning\(warnings == 1 ? "" : "s")" : "Complete")
                    updateQueueItems(for: [url], state: failed > 0 ? .failed : .succeeded, message: message)
                }
            default:
                break
            }
        }

        if needsSort {
            items.sort(by: Self.progressOrder)
        }
        if itemsChanged {
            progressItems = items
            progressSummary = Self.summarize(items, base: summary)
        } else if summary != progressSummary {
            progressSummary = summary
        }
        appendLogLines(logLines)
    }

    private func decodeProgressEvent(from line: String) -> DownloadProgressEvent? {
        let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.hasPrefix("{"), let data = trimmed.data(using: .utf8) else { return nil }
        return try? Self.eventDecoder.decode(DownloadProgressEvent.self, from: data)
    }

    /// Updates or inserts one song's row. Returns true when the order may have
    /// changed, so the caller sorts once per batch instead of once per event.
    private static func upsertProgressItem(
        from event: DownloadProgressEvent,
        into items: inout [DownloadProgressItem],
        indexByID: inout [String: Int]
    ) -> Bool {
        let fallbackID = event.label ?? event.title ?? UUID().uuidString
        let id = event.key?.isEmpty == false ? event.key! : fallbackID
        let state = event.state ?? .running
        let progress = max(0, min(1, event.progress ?? (state == .succeeded || state == .skipped ? 1 : 0)))

        if let existingIndex = indexByID[id] {
            var item = items[existingIndex]
            let previousIndex = item.index
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
            item.createdThisRun = event.createdThisRun ?? item.createdThisRun
            items[existingIndex] = item
            return item.index != previousIndex
        }

        items.append(
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
                skipped: event.skipped ?? false,
                createdThisRun: event.createdThisRun ?? false
            )
        )
        indexByID[id] = items.count - 1
        return true
    }

    private static func progressOrder(_ left: DownloadProgressItem, _ right: DownloadProgressItem) -> Bool {
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

    private static func summarize(_ items: [DownloadProgressItem], base: DownloadProgressSummary) -> DownloadProgressSummary {
        var summary = base
        var completed = 0
        var failed = 0
        var skipped = 0
        var progressSum = 0.0
        for item in items {
            switch item.state {
            case .succeeded:
                completed += 1
            case .failed, .cancelled:
                failed += 1
            case .skipped:
                skipped += 1
            default:
                break
            }
            progressSum += item.progress
        }
        let total = max(base.total, items.count)
        summary.completed = completed
        summary.failed = failed
        summary.skipped = skipped
        summary.total = total
        let progress = total > 0 ? min(1, progressSum / Double(total)) : 0
        summary.progress = summary.finished >= total && total > 0 ? 1 : progress
        return summary
    }

    private func recalculateProgressSummary() {
        progressSummary = Self.summarize(progressItems, base: progressSummary)
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
        appendLogLines(text.components(separatedBy: "\n"))
    }

    /// Adds lines newest-first and drops the oldest past the cap. The full log
    /// stays on disk in ~/Library/Logs/Spotify Downloader.
    private func appendLogLines(_ lines: [String]) {
        let meaningful = lines.filter { $0.trimmingCharacters(in: .whitespaces).isEmpty == false }
        guard meaningful.isEmpty == false else { return }
        var updated = activityLines
        updated.insert(contentsOf: meaningful.reversed(), at: 0)
        if updated.count > Self.maxActivityLines {
            updated.removeLast(updated.count - Self.maxActivityLines)
        }
        activityLines = updated
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

    private func finishRunningQueueItems(as state: QueueItemState, message: String) {
        queueItems = queueItems.map { item in
            var copy = item
            if activeDownloadURLs.contains(copy.url) && copy.state == .running {
                copy.state = state
                copy.message = message
            }
            return copy
        }
    }
}
