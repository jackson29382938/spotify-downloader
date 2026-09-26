import SwiftUI

/// Apple Music toggle and playlist name, with a small note under the name
/// when a playlist with exactly that name already exists.
struct AppleMusicPlaylistField: View {
    var nameFieldWidth: CGFloat = 180

    @AppStorage("addToAppleMusic") private var addToAppleMusic = false
    @AppStorage("appleMusicPlaylistName") private var playlistName = Defaults.appleMusicPlaylistName
    @AppStorage("audioFormat") private var audioFormat = AudioFormat.mp3.rawValue
    @ObservedObject private var checker = AppleMusicPlaylistChecker.shared

    private var trimmedName: String {
        playlistName.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 8) {
                Toggle("Apple Music", isOn: $addToAppleMusic)
                    .toggleStyle(.checkbox)
                    .fixedSize()
                    .help("After each download, add the songs to this Apple Music playlist.")
                TextField("Playlist name", text: $playlistName)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: nameFieldWidth)
                    .disabled(!addToAppleMusic)
            }

            if addToAppleMusic {
                if checker.exists(trimmedName) {
                    Label(
                        "“\(trimmedName)” already exists. Songs will be added to it, skipping any already there.",
                        systemImage: "exclamationmark.circle.fill"
                    )
                    .font(.caption)
                    .foregroundStyle(.orange)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 6))
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: nameFieldWidth + 120, alignment: .leading)
                    .transition(.opacity)
                }
                if !(AudioFormat(rawValue: audioFormat) ?? .mp3).canImportIntoAppleMusic {
                    Label("Apple Music import needs MP3, M4A, or WAV.", systemImage: "exclamationmark.triangle.fill")
                        .font(.caption)
                        .foregroundStyle(.orange)
                }
            }
        }
        .animation(.easeOut(duration: 0.15), value: checker.exists(trimmedName))
        .task(id: addToAppleMusic ? trimmedName : "") {
            guard addToAppleMusic else { return }
            // Wait for typing to pause before asking Music for its playlists.
            try? await Task.sleep(nanoseconds: 400_000_000)
            guard !Task.isCancelled else { return }
            checker.refresh()
        }
    }
}
