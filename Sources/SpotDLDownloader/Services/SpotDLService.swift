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

    func download(
        command: DownloadCommand,
        output: @escaping (String) -> Void,
        completion: @escaping (Int32) -> Void
    ) throws {
        guard process == nil || process?.isRunning == false else {
            throw DownloadServiceError.alreadyRunning
        }

        let newProcess = Process()
        newProcess.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        newProcess.arguments = command.arguments
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
