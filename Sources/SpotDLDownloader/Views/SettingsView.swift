import AppKit
import SwiftUI

/// Settings grouped into tabs (⌘,) instead of one long form.
struct SettingsView: View {
    var body: some View {
        TabView {
            GeneralSettingsTab()
                .tabItem { Label("General", systemImage: "gearshape") }
            AudioSettingsTab()
                .tabItem { Label("Audio", systemImage: "music.note") }
            LyricsSettingsTab()
                .tabItem { Label("Lyrics", systemImage: "text.quote") }
            YouTubeSettingsTab()
                .tabItem { Label("YouTube", systemImage: "play.rectangle") }
            AdvancedSettingsTab()
                .tabItem { Label("Advanced", systemImage: "wrench.and.screwdriver") }
        }
        .frame(width: 560)
        .frame(minHeight: 380)
    }
}

private struct GeneralSettingsTab: View {
    @AppStorage("downloadFolderPath") private var downloadFolderPath = Defaults.downloadsPath
    @AppStorage("downloadThreads") private var downloadThreads = 4
    @AppStorage("downloadRetries") private var downloadRetries = 2
    @AppStorage("overwrite") private var overwrite = ExistingFileBehavior.skip.rawValue
    @AppStorage("trackNumberPrefix") private var trackNumberPrefix = true

    var body: some View {
        Form {
            Section("Downloads") {
                SettingHelpRow(
                    title: "Download folder",
                    help: "All sources save here. Playlists and albums create their own subfolders."
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
                    help: "More workers speed up playlists, but high values make YouTube's bot check more likely. 2–4 is safest."
                ) {
                    Stepper(value: $downloadThreads, in: 1...16) {
                        Text("\(max(1, downloadThreads)) concurrent downloads")
                    }
                }

                SettingHelpRow(
                    title: "Failed-track retries",
                    help: "Extra attempts after a failed download. Each retry uses a different YouTube player client."
                ) {
                    Stepper(value: $downloadRetries, in: 0...5) {
                        Text("\(max(0, downloadRetries)) additional retr\(downloadRetries == 1 ? "y" : "ies")")
                    }
                }
            }

            Section("Files") {
                SettingHelpRow(
                    title: "Existing files",
                    help: "Skip keeps files, Metadata refreshes tags and lyrics, Replace downloads again."
                ) {
                    Picker("Existing files", selection: $overwrite) {
                        ForEach(ExistingFileBehavior.allCases) { option in
                            Text(option.label).tag(option.rawValue)
                        }
                    }
                }

                SettingHelpRow(
                    title: "Track numbers",
                    help: "Saves playlist files like 01. Song - Artist.mp3 so Finder sorting matches playlist order."
                ) {
                    Toggle("Track numbers in filenames", isOn: $trackNumberPrefix)
                }
            }
        }
        .formStyle(.grouped)
    }
}

private struct AudioSettingsTab: View {
    @AppStorage("audioFormat") private var audioFormat = AudioFormat.mp3.rawValue
    @AppStorage("bitrate") private var bitrate = Bitrate.kbps192.rawValue
    @AppStorage("artworkMaxSize") private var artworkMaxSize = ArtworkMaxSize.unlimited.rawValue
    @AppStorage("artworkJpeg") private var artworkJpeg = false

    var body: some View {
        Form {
            Section("Output") {
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
            }

            Section("Artwork") {
                SettingHelpRow(
                    title: "Artwork",
                    help: "Downscale cover art before embedding, and optionally re-encode it as JPEG to shrink files."
                ) {
                    VStack(alignment: .leading, spacing: 6) {
                        Picker("Cover art size", selection: $artworkMaxSize) {
                            ForEach(ArtworkMaxSize.allCases) { size in
                                Text(size.label).tag(size.rawValue)
                            }
                        }
                        Toggle("Convert cover art to JPEG", isOn: $artworkJpeg)
                    }
                }
            }

            Section("Apple Music") {
                SettingHelpRow(
                    title: "Apple Music playlist",
                    help: "After each audio download, adds the completed MP3, M4A, or WAV files to this playlist. If a playlist with exactly this name exists, songs go into it; otherwise it is created. macOS asks for permission the first time."
                ) {
                    AppleMusicPlaylistField(nameFieldWidth: 240)
                }
            }
        }
        .formStyle(.grouped)
    }
}

private struct LyricsSettingsTab: View {
    @AppStorage("searchLyrics") private var searchLyrics = true
    @AppStorage("lyricsStyle") private var lyricsStyle = LyricsStyle.plain.rawValue
    @AppStorage("writeLRCSidecar") private var writeLRCSidecar = false

    private var selectedStyle: LyricsStyle {
        LyricsStyle(rawValue: lyricsStyle) ?? .plain
    }

    var body: some View {
        Form {
            Section("Embedded lyrics") {
                SettingHelpRow(
                    title: "Lyrics",
                    help: "Looks up lyrics on LRCLib and writes them inside each song (MP3, M4A, FLAC, Opus, Ogg)."
                ) {
                    Toggle("Embed lyrics in songs", isOn: $searchLyrics)
                }

                SettingHelpRow(title: "Lyrics style", help: selectedStyle.help) {
                    Picker("Style", selection: $lyricsStyle) {
                        ForEach(LyricsStyle.allCases) { style in
                            Text(style.label).tag(style.rawValue)
                        }
                    }
                    .pickerStyle(.radioGroup)
                    .disabled(!searchLyrics)
                }
            }

            Section("Sidecar files") {
                SettingHelpRow(
                    title: ".lrc sidecar",
                    help: "Off by default: lyrics already live inside the song. Turn on only if a player needs separate .lrc files."
                ) {
                    Toggle("Also save a .lrc file next to each song", isOn: $writeLRCSidecar)
                        .disabled(!searchLyrics)
                }

                Text("Already have .lrc files? Use Library Tools > Embed .lrc Lyrics to move them into your songs.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
    }
}

private struct YouTubeSettingsTab: View {
    @AppStorage("cookiesBrowser") private var cookiesBrowser = CookiesBrowser.none.rawValue
    @AppStorage("allowClosestMatch") private var allowClosestMatch = false

    var body: some View {
        Form {
            Section("Access") {
                SettingHelpRow(
                    title: "Browser cookies",
                    help: "Fixes \"Sign in to confirm you're not a bot\". Choose the browser where you're signed in to YouTube."
                ) {
                    Picker("Cookies from browser", selection: $cookiesBrowser) {
                        ForEach(CookiesBrowser.allCases) { browser in
                            Text(browser.label).tag(browser.rawValue)
                        }
                    }
                }

                Text("HTTP 403 errors usually mean yt-dlp has no JavaScript runtime. Install one with `brew install deno`, then check Diagnostics.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Section("Matching") {
                SettingHelpRow(
                    title: "Closest-match fallback",
                    help: "Off rejects uncertain matches. On may recover international tracks whose YouTube titles use another script."
                ) {
                    Toggle("Closest-match fallback", isOn: $allowClosestMatch)
                }
            }
        }
        .formStyle(.grouped)
    }
}

private struct AdvancedSettingsTab: View {
    @AppStorage("debugLogging") private var debugLogging = false

    var body: some View {
        Form {
            Section("Diagnostics") {
                SettingHelpRow(
                    title: "Debug logs",
                    help: "Adds detailed YouTube and per-track decisions to the rotating log for troubleshooting."
                ) {
                    Toggle("Debug logs", isOn: $debugLogging)
                }

                Button("Open Logs Folder") {
                    try? FileManager.default.createDirectoryIfNeeded(atPath: Defaults.logsPath)
                    NSWorkspace.shared.open(URL(fileURLWithPath: Defaults.logsPath))
                }
            }
        }
        .formStyle(.grouped)
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
