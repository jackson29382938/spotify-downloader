import SwiftUI

/// The handful of choices people change per download. Everything else lives
/// in the Settings window so the Download page stays short.
struct QuickOptionsView: View {
    @AppStorage("mediaKind") private var mediaKind = MediaKind.audio.rawValue
    @AppStorage("audioFormat") private var audioFormat = AudioFormat.mp3.rawValue
    @AppStorage("bitrate") private var bitrate = Bitrate.kbps192.rawValue
    @AppStorage("overwrite") private var overwrite = ExistingFileBehavior.skip.rawValue
    @AppStorage("searchLyrics") private var searchLyrics = true
    @AppStorage("cookiesBrowser") private var cookiesBrowser = CookiesBrowser.none.rawValue

    private var selectedMediaKind: MediaKind {
        MediaKind(rawValue: mediaKind) ?? .audio
    }

    private var overwriteOptions: [ExistingFileBehavior] {
        selectedMediaKind == .video ? [.skip, .force] : ExistingFileBehavior.allCases
    }

    private var overwriteSelection: Binding<String> {
        Binding(
            get: {
                let behavior = ExistingFileBehavior(rawValue: overwrite) ?? .skip
                return (selectedMediaKind == .video && behavior == .metadata ? .skip : behavior).rawValue
            },
            set: { overwrite = $0 }
        )
    }

    var body: some View {
        Card(padding: 12) {
            VStack(alignment: .leading, spacing: 10) {
                FlowLayout(horizontalSpacing: 16, verticalSpacing: 10) {
                    Picker("Media", selection: $mediaKind) {
                        ForEach(MediaKind.allCases) { kind in
                            Label(kind.label, systemImage: kind.systemImage).tag(kind.rawValue)
                        }
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                    .fixedSize()

                    if selectedMediaKind == .audio {
                        Picker("Format", selection: $audioFormat) {
                            ForEach(AudioFormat.allCases) { format in
                                Text(format.rawValue.uppercased()).tag(format.rawValue)
                            }
                        }
                        .fixedSize()

                        Picker("Quality", selection: $bitrate) {
                            ForEach(Bitrate.allCases) { option in
                                Text(option.label).tag(option.rawValue)
                            }
                        }
                        .fixedSize()
                    }

                    Picker("Existing", selection: overwriteSelection) {
                        ForEach(overwriteOptions) { option in
                            Text(option.label).tag(option.rawValue)
                        }
                    }
                    .fixedSize()
                    .help("Skip keeps files, Metadata refreshes tags and lyrics, Replace downloads again.")

                    if selectedMediaKind == .audio {
                        Toggle("Lyrics", isOn: $searchLyrics)
                            .toggleStyle(.checkbox)
                            .fixedSize()
                            .help("Embed lyrics inside each song. Style and .lrc options are in Settings > Lyrics.")

                        MatchFlexibilityControl()

                        AppleMusicPlaylistField()
                    }

                    SettingsLink {
                        Label("All Settings", systemImage: "gearshape")
                    }
                    .fixedSize()
                }

                statusNotes
            }
        }
    }

    @ViewBuilder
    private var statusNotes: some View {
        let cookies = CookiesBrowser(rawValue: cookiesBrowser) ?? .none
        if cookies != .none {
            Label("Using \(cookies.label) cookies for YouTube", systemImage: "lock.shield")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }
}
