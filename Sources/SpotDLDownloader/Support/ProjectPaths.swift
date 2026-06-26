import Foundation

enum ProjectPaths {
    static var resourcesURL: URL {
        Bundle.main.resourceURL ?? rootURL
    }

    static var bundledDownloaderURL: URL {
        resourcesURL
            .appendingPathComponent("downloader")
            .appendingPathComponent("spotify_dl")
    }

    static var bundledBinURL: URL {
        resourcesURL.appendingPathComponent("bin")
    }

    static var bundledFFmpegURL: URL {
        bundledBinURL.appendingPathComponent("ffmpeg")
    }

    static var downloaderInvocationPrefix: [String] {
        if FileManager.default.isExecutableFile(atPath: bundledDownloaderURL.path) {
            return [bundledDownloaderURL.path]
        }

        if FileManager.default.isExecutableFile(atPath: projectVirtualEnvPythonURL.path) {
            return [projectVirtualEnvPythonURL.path, sourceDownloaderScriptURL.path]
        }

        return ["python3", sourceDownloaderScriptURL.path]
    }

    private static var rootURL: URL {
        let bundleRoot = Bundle.main.bundleURL
            .deletingLastPathComponent()
            .deletingLastPathComponent()

        let sourceRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()

        let candidates = [
            bundleRoot,
            URL(fileURLWithPath: FileManager.default.currentDirectoryPath),
            sourceRoot
        ]

        return candidates.first { candidate in
            FileManager.default.fileExists(atPath: candidate.appendingPathComponent("spotify_dl.py").path)
        } ?? sourceRoot
    }

    private static var sourceDownloaderScriptURL: URL {
        rootURL.appendingPathComponent("spotify_dl.py")
    }

    private static var projectVirtualEnvPythonURL: URL {
        rootURL
            .appendingPathComponent(".venv")
            .appendingPathComponent("bin")
            .appendingPathComponent("python")
    }
}
