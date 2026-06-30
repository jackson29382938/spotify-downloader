import AppKit
import SwiftUI

struct SettingsView: View {
    @AppStorage("downloadFolderPath") private var downloadFolderPath = Defaults.downloadsPath
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
    @AppStorage("showDetailedActivity") private var showDetailedActivity = false

    var body: some View {
        Form {
            Section("Downloads") {
                SettingHelpRow(
                    title: "Download folder",
                    help: "All selected sources save here. Playlists and albums create their own subfolders."
                ) {
                    HStack {
                        TextField("Folder", text: $downloadFolderPath)
                        Button("Choose") {
                            if let chosen = FolderPicker.chooseFolder(startingAt: downloadFolderPath) {
                                downloadFolderPath = chosen
                            }
                        }
                    }
                }

                SettingHelpRow(
                    title: "Concurrent downloads",
                    help: "More workers can speed up playlists, but very high values may trigger service limits."
                ) {
                    Stepper(value: $downloadThreads, in: 1...16) {
                        Text("\(max(1, downloadThreads)) concurrent downloads")
                    }
                }
            }

            Section("Audio") {
                SettingHelpRow(
                    title: "Format",
                    help: "MP3 is most compatible. FLAC and WAV are lossless-style outputs and ignore bitrate."
                ) {
                    Picker("Format", selection: $audioFormat) {
                        ForEach(AudioFormat.allCases) { format in
                            Text(format.rawValue.uppercased()).tag(format.rawValue)
                        }
                    }
                }

                SettingHelpRow(
                    title: "Bitrate",
                    help: "Applies to lossy audio. Auto lets the downloader choose a sensible value."
                ) {
                    Picker("Bitrate", selection: $bitrate) {
                        ForEach(Bitrate.allCases) { option in
                            Text(option.label).tag(option.rawValue)
                        }
                    }
                }

                SettingHelpRow(
                    title: "Existing files",
                    help: "Skip keeps files, Metadata refreshes tags, Replace downloads again."
                ) {
                    Picker("Existing files", selection: $overwrite) {
                        ForEach(ExistingFileBehavior.allCases) { option in
                            Text(option.label).tag(option.rawValue)
                        }
                    }
                }

                SettingHelpRow(
                    title: "Track numbers",
                    help: "On saves playlist files like 01. Song - Artist.mp3 so Finder sorting matches playlist order."
                ) {
                    Toggle("Track numbers in filenames", isOn: $trackNumberPrefix)
                        .toggleStyle(.checkbox)
                }

                SettingHelpRow(
                    title: "Closest-match fallback",
                    help: "Off rejects uncertain matches. On may recover international tracks whose YouTube titles use another script."
                ) {
                    Toggle("Closest-match fallback", isOn: $allowClosestMatch)
                        .toggleStyle(.checkbox)
                }

                SettingHelpRow(
                    title: "Lyrics",
                    help: "Searches lyrics online and writes them to MP3, M4A, FLAC, Opus, and Ogg metadata when found."
                ) {
                    VStack(alignment: .leading, spacing: 4) {
                        Toggle("Search and apply lyrics", isOn: $searchLyrics)
                            .toggleStyle(.checkbox)
                        Toggle("Write .lrc sidecar file", isOn: $writeLRC)
                            .toggleStyle(.checkbox)
                            .disabled(!searchLyrics)
                    }
                }

                SettingHelpRow(
                    title: "Artwork",
                    help: "Downscale cover art before embedding, and optionally re-encode it as JPEG to shrink file size. Requires Pillow."
                ) {
                    VStack(alignment: .leading, spacing: 4) {
                        Picker("Cover art size", selection: $artworkMaxSize) {
                            ForEach(ArtworkMaxSize.allCases) { size in
                                Text(size.label).tag(size.rawValue)
                            }
                        }
                        Toggle("Convert cover art to JPEG", isOn: $artworkJpeg)
                            .toggleStyle(.checkbox)
                    }
                }

            }

            Section("Network") {
                SettingHelpRow(
                    title: "Browser cookies",
                    help: "Load cookies from a browser so yt-dlp can avoid bot-detection. Choose the browser you are signed into YouTube with."
                ) {
                    Picker("Cookies from browser", selection: $cookiesBrowser) {
                        ForEach(CookiesBrowser.allCases) { browser in
                            Text(browser.label).tag(browser.rawValue)
                        }
                    }
                }
            }

            Section("Diagnostics") {
                SettingHelpRow(
                    title: "Detailed activity",
                    help: "Shows the helper transcript in the main window below the progress bars."
                ) {
                    Toggle("Show detailed activity", isOn: $showDetailedActivity)
                        .toggleStyle(.checkbox)
                }

                SettingHelpRow(
                    title: "Debug logs",
                    help: "Adds detailed YouTube and per-track decisions to the rotating log for troubleshooting."
                ) {
                    Toggle("Debug logs", isOn: $debugLogging)
                        .toggleStyle(.checkbox)
                }

                Button("Open Logs Folder") {
                    FileManager.default.createDirectoryIfNeeded(atPath: Defaults.logsPath)
                    NSWorkspace.shared.open(URL(fileURLWithPath: Defaults.logsPath))
                }
            }
        }
        .formStyle(.grouped)
        .padding()
        .frame(width: 520)
    }
}

private struct SettingHelpRow<Content: View>: View {
    let title: String
    let help: String
    @ViewBuilder var content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            content()
            Text(help)
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(title)
    }
}
