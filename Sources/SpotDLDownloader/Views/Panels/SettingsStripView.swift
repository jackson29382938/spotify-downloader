import SwiftUI

struct SettingsStripView: View {
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
    @AppStorage("debugLogging") private var debugLogging = false

    private var selectedMediaKind: MediaKind {
        MediaKind(rawValue: mediaKind) ?? .audio
    }

    private var selectedCookiesBrowser: CookiesBrowser {
        CookiesBrowser(rawValue: cookiesBrowser) ?? .none
    }

    private var selectedOverwrite: ExistingFileBehavior {
        let behavior = ExistingFileBehavior(rawValue: overwrite) ?? .skip
        return selectedMediaKind == .video && behavior == .metadata ? .skip : behavior
    }

    private var overwriteOptions: [ExistingFileBehavior] {
        selectedMediaKind == .video ? [.skip, .force] : ExistingFileBehavior.allCases
    }

    private var overwriteSelection: Binding<String> {
        Binding(
            get: { selectedOverwrite.rawValue },
            set: { overwrite = $0 }
        )
    }

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 14) {
                SectionHeader("Download Options", systemImage: "slider.horizontal.3")

                FlowLayout(horizontalSpacing: 18, verticalSpacing: 14) {
                    SettingBlock("Media", help: "Spotify sources download as audio; direct YouTube URLs can also be saved as MP4 video.") {
                        Picker("Media", selection: $mediaKind) {
                            ForEach(MediaKind.allCases) { kind in
                                Label(kind.label, systemImage: kind.systemImage).tag(kind.rawValue)
                            }
                        }
                        .pickerStyle(.menu)
                        .labelsHidden()
                        .frame(width: 150)
                    }

                    SettingBlock("Concurrent Downloads", help: "Parallel workers for playlist and album downloads. Four is a conservative default.") {
                        Stepper(value: $downloadThreads, in: 1...16) {
                            Text("\(max(1, downloadThreads))")
                                .monospacedDigit()
                        }
                        .frame(width: 120)
                    }

                    if selectedMediaKind == .audio {
                        SettingBlock("Format", help: "MP3 has the broadest player compatibility; lossless formats ignore bitrate.") {
                            Picker("Format", selection: $audioFormat) {
                                ForEach(AudioFormat.allCases) { format in
                                    Text(format.rawValue.uppercased()).tag(format.rawValue)
                                }
                            }
                            .pickerStyle(.menu)
                            .labelsHidden()
                            .frame(width: 110)
                        }

                        SettingBlock("Bitrate", help: "Applies to lossy audio formats. Auto lets yt-dlp choose.") {
                            Picker("Bitrate", selection: $bitrate) {
                                ForEach(Bitrate.allCases) { option in
                                    Text(option.label).tag(option.rawValue)
                                }
                            }
                            .pickerStyle(.menu)
                            .labelsHidden()
                            .frame(width: 120)
                        }
                    }
                }

                SettingBlock("Existing Files", help: "Skip keeps files, Metadata refreshes tags, Replace downloads again.") {
                    Picker("Existing Files", selection: overwriteSelection) {
                        ForEach(overwriteOptions) { option in
                            Text(option.label).tag(option.rawValue)
                        }
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                    .frame(maxWidth: 320)
                }

                FlowLayout(horizontalSpacing: 22, verticalSpacing: 14) {
                    SettingBlock("Filenames", help: "On keeps playlist order visible in Finder, for example 01. Song - Artist.mp3.") {
                        Toggle("Track numbers", isOn: $trackNumberPrefix)
                            .toggleStyle(.checkbox)
                            .fixedSize()
                    }

                    SettingBlock("Matching", help: "Off rejects uncertain YouTube matches. On can recover international tracks with different scripts.") {
                        Toggle("Closest fallback", isOn: $allowClosestMatch)
                            .toggleStyle(.checkbox)
                            .fixedSize()
                    }

                    SettingBlock("Lyrics", help: "Searches lyrics and writes them to supported audio metadata.") {
                        VStack(alignment: .leading, spacing: 5) {
                            Toggle("Search lyrics", isOn: $searchLyrics)
                                .toggleStyle(.checkbox)
                                .fixedSize()
                            Toggle(".lrc sidecar", isOn: $writeLRC)
                                .toggleStyle(.checkbox)
                                .fixedSize()
                                .disabled(!searchLyrics)
                        }
                    }

                    SettingBlock("Cookies", help: "Load cookies from a browser so yt-dlp can avoid bot-detection.") {
                        Picker("Cookies", selection: $cookiesBrowser) {
                            ForEach(CookiesBrowser.allCases) { browser in
                                Text(browser.label).tag(browser.rawValue)
                            }
                        }
                        .pickerStyle(.menu)
                        .labelsHidden()
                        .frame(width: 110)
                    }

                    SettingBlock("Diagnostics", help: "Adds verbose per-track and yt-dlp detail to the rotating log file.") {
                        Toggle("Debug logs", isOn: $debugLogging)
                            .toggleStyle(.checkbox)
                            .fixedSize()
                    }
                }

                if selectedCookiesBrowser != .none {
                    Label("Cookies: \(selectedCookiesBrowser.label)", systemImage: "lock.shield")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
    }
}
