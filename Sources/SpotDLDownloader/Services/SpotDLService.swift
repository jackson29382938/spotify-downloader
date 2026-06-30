import Foundation

final class DownloadService {
    private var process: Process?

    var isRunning: Bool {
        process?.isRunning ?? false
    }

    func checkDependencies(completion: @escaping (Result<String, DownloadServiceError>) -> Void) {
        runOneShot(arguments: ProjectPaths.downloaderInvocationPrefix + ["doctor"]) { result in
            switch result {
            case .success(let output):
                let firstLine = output
                    .components(separatedBy: .newlines)
                    .first?
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                completion(.success(firstLine?.isEmpty == false ? firstLine! : "yt-dlp ready"))
            case .failure(let error):
                completion(.failure(error))
            }
        }
    }

    func preview(
        queries: [String],
        outputFolder: String,
        mediaKind: MediaKind,
        completion: @escaping (Result<PreviewResponse, DownloadServiceError>) -> Void
    ) {
        let arguments = ProjectPaths.downloaderInvocationPrefix + [
            "preview",
            "--json",
            "--media", mediaKind.rawValue,
            "--output-dir", URL(fileURLWithPath: outputFolder).standardizedFileURL.path
        ] + queries

        runOneShot(arguments: arguments) { result in
            completion(Self.decodeResult(result, as: PreviewResponse.self))
        }
    }

    func health(
        outputFolder: String,
        completion: @escaping (Result<HelperHealthReport, DownloadServiceError>) -> Void
    ) {
        let arguments = ProjectPaths.downloaderInvocationPrefix + [
            "health",
            "--json",
            "--output-dir", URL(fileURLWithPath: outputFolder).standardizedFileURL.path
        ]

        runOneShot(arguments: arguments) { result in
            completion(Self.decodeResult(result, as: HelperHealthReport.self))
        }
    }

    func download(
        command: DownloadCommand,
        output: @escaping (String) -> Void,
        completion: @escaping (Int32) -> Void
    ) throws {
        try runStreaming(arguments: command.arguments, output: output, completion: completion)
    }

    func repairLibrary(
        folders: [String],
        apply: Bool,
        recursive: Bool,
        searchLyrics: Bool,
        updateArtwork: Bool,
        overwriteArtwork: Bool,
        minConfidence: Double,
        renamePattern: String? = nil,
        output: @escaping (String) -> Void,
        completion: @escaping (Int32) -> Void
    ) throws {
        let folderPaths = folders.map { URL(fileURLWithPath: $0).standardizedFileURL.path }
        var arguments = ProjectPaths.downloaderInvocationPrefix
            + ["library"]
            + folderPaths
            + ["--json-events", "--min-confidence", String(format: "%.2f", max(0, min(1, minConfidence)))]

        if apply {
            arguments.append("--apply")
        }
        if !recursive {
            arguments.append("--no-recursive")
        }
        if !searchLyrics {
            arguments.append("--no-lyrics")
        }
        if !updateArtwork {
            arguments.append("--no-artwork")
        }
        if overwriteArtwork {
            arguments.append("--overwrite-artwork")
        }
        if apply, let renamePattern, renamePattern.trimmingCharacters(in: .whitespaces).isEmpty == false {
            arguments.append(contentsOf: ["--rename-pattern", renamePattern])
        }

        try runStreaming(arguments: arguments, output: output, completion: completion)
    }

    func installFFmpeg(
        output: @escaping (String) -> Void,
        completion: @escaping (Int32) -> Void
    ) throws {
        let arguments = ProjectPaths.downloaderInvocationPrefix + ["ffmpeg-install", "--json-events"]
        try runStreaming(arguments: arguments, output: output, completion: completion)
    }

    func downloadHistory() -> [HistoryEntry] {
        let path = Defaults.historyPath
        guard let contents = try? String(contentsOfFile: path, encoding: .utf8) else {
            return []
        }
        let decoder = JSONDecoder()
        var entries: [HistoryEntry] = []
        for line in contents.components(separatedBy: .newlines) {
            let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
            guard trimmed.isEmpty == false, let data = trimmed.data(using: .utf8) else { continue }
            if let entry = try? decoder.decode(HistoryEntry.self, from: data) {
                entries.append(entry)
            }
        }
        return entries.reversed()
    }

    func clearHistory() {
        try? FileManager.default.removeItem(atPath: Defaults.historyPath)
    }

    private func runStreaming(
        arguments: [String],
        output: @escaping (String) -> Void,
        completion: @escaping (Int32) -> Void
    ) throws {
        guard process == nil || process?.isRunning == false else {
            throw DownloadServiceError.alreadyRunning
        }

        let newProcess = Process()
        newProcess.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        newProcess.arguments = arguments
        newProcess.environment = Self.processEnvironment()

        let standardOutput = Pipe()
        let standardError = Pipe()
        newProcess.standardOutput = standardOutput
        newProcess.standardError = standardError

        standardOutput.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            guard !data.isEmpty, let text = String(data: data, encoding: .utf8) else { return }
            output(Self.cleaned(text))
        }

        standardError.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            guard !data.isEmpty, let text = String(data: data, encoding: .utf8) else { return }
            output(Self.cleaned(text))
        }

        newProcess.terminationHandler = { [weak self] process in
            standardOutput.fileHandleForReading.readabilityHandler = nil
            standardError.fileHandleForReading.readabilityHandler = nil
            self?.process = nil
            completion(process.terminationStatus)
        }

        try newProcess.run()
        process = newProcess
    }

    func cancel() {
        process?.terminate()
    }

    private func runOneShot(
        arguments: [String],
        completion: @escaping (Result<String, DownloadServiceError>) -> Void
    ) {
        let newProcess = Process()
        newProcess.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        newProcess.arguments = arguments
        newProcess.environment = Self.processEnvironment()

        let pipe = Pipe()
        newProcess.standardOutput = pipe
        newProcess.standardError = pipe

        newProcess.terminationHandler = { process in
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let output = String(data: data, encoding: .utf8) ?? ""
            if process.terminationStatus == 0 {
                completion(.success(output))
            } else {
                completion(.failure(.commandFailed(output.trimmingCharacters(in: .whitespacesAndNewlines))))
            }
        }

        do {
            try newProcess.run()
        } catch {
            completion(.failure(.launchFailed(error.localizedDescription)))
        }
    }

    private static func decodeResult<T: Decodable>(
        _ result: Result<String, DownloadServiceError>,
        as type: T.Type
    ) -> Result<T, DownloadServiceError> {
        switch result {
        case .success(let output):
            return decodeOutput(output, as: type)
        case .failure(.commandFailed(let output)):
            if case .success(let decoded) = decodeOutput(output, as: type) {
                return .success(decoded)
            }
            return .failure(.commandFailed(output))
        case .failure(let error):
            return .failure(error)
        }
    }

    private static func decodeOutput<T: Decodable>(
        _ output: String,
        as type: T.Type
    ) -> Result<T, DownloadServiceError> {
        guard let data = output.data(using: .utf8) else {
            return .failure(.commandFailed("The downloader returned non-UTF-8 output."))
        }
        do {
            return .success(try JSONDecoder().decode(T.self, from: data))
        } catch {
            return .failure(.commandFailed("Could not parse downloader output: \(error.localizedDescription)\n\(output)"))
        }
    }

    private static func processEnvironment() -> [String: String] {
        var environment = ProcessInfo.processInfo.environment
        let extraPaths = [
            ProjectPaths.bundledBinURL.path,
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/Library/Frameworks/Python.framework/Versions/Current/bin",
            "/Library/Frameworks/Python.framework/Versions/3.13/bin",
            "/Library/Frameworks/Python.framework/Versions/3.12/bin",
            "/Library/Frameworks/Python.framework/Versions/3.11/bin",
            "/usr/bin",
            "/bin",
            "/usr/sbin",
            "/sbin"
        ]
        let existingPath = environment["PATH"] ?? ""
        environment["PATH"] = (extraPaths + [existingPath]).filter { !$0.isEmpty }.joined(separator: ":")
        environment["PYTHONUNBUFFERED"] = "1"
        environment["TERM"] = "dumb"
        if FileManager.default.isExecutableFile(atPath: ProjectPaths.bundledFFmpegURL.path) {
            environment["SPOTIFY_DOWNLOADER_FFMPEG"] = ProjectPaths.bundledFFmpegURL.path
        }
        return environment
    }

    private static func cleaned(_ text: String) -> String {
        text.replacingOccurrences(
            of: #"\u{001B}\[[0-9;?]*[ -/]*[@-~]"#,
            with: "",
            options: .regularExpression
        )
    }
}

enum DownloadServiceError: LocalizedError {
    case alreadyRunning
    case launchFailed(String)
    case commandFailed(String)

    var errorDescription: String? {
        switch self {
        case .alreadyRunning:
            "A download is already running."
        case .launchFailed(let details):
            "Could not start the downloader: \(details)"
        case .commandFailed(let details):
            details.isEmpty ? "The downloader returned an error." : details
        }
    }
}
