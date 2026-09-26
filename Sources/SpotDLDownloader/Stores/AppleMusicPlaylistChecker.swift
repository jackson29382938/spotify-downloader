import Combine
import Foundation

/// Knows which Apple Music playlist names already exist, so the playlist field
/// can warn before a download adds songs to one of them.
@MainActor
final class AppleMusicPlaylistChecker: ObservableObject {
    static let shared = AppleMusicPlaylistChecker()

    /// Playlists currently in Music, read while Music is open. When a refresh
    /// finds Music open, this replaces the previous list, so deleted playlists
    /// stop showing as existing.
    @Published private(set) var liveNames: Set<String>?
    /// Names this app imported into before; only used while Music is closed.
    @Published private(set) var rememberedNames: Set<String>

    private let service = AppleMusicService()
    private static let rememberedNamesKey = "appleMusicKnownPlaylistNames"

    private init() {
        rememberedNames = Set(UserDefaults.standard.stringArray(forKey: Self.rememberedNamesKey) ?? [])
    }

    func exists(_ name: String) -> Bool {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.isEmpty == false else { return false }
        return (liveNames ?? rememberedNames).contains(trimmed)
    }

    func refresh() {
        service.existingPlaylistNames { [weak self] names in
            DispatchQueue.main.async {
                guard let self else { return }
                guard let names else {
                    // Music is closed: fall back to remembered names.
                    self.liveNames = nil
                    return
                }
                let live = Set(names)
                self.liveNames = live
                // Forget remembered playlists that no longer exist in Music.
                self.rememberedNames.formIntersection(live)
                self.saveRememberedNames()
            }
        }
    }

    func remember(_ name: String) {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.isEmpty == false else { return }
        liveNames?.insert(trimmed)
        guard rememberedNames.contains(trimmed) == false else { return }
        rememberedNames.insert(trimmed)
        saveRememberedNames()
    }

    private func saveRememberedNames() {
        UserDefaults.standard.set(Array(rememberedNames.prefix(200)), forKey: Self.rememberedNamesKey)
    }
}
