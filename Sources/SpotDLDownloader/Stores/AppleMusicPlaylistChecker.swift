import Combine
import Foundation

/// Knows which Apple Music playlist names already exist, so the playlist field
/// can warn before a download adds songs to one of them.
@MainActor
final class AppleMusicPlaylistChecker: ObservableObject {
    static let shared = AppleMusicPlaylistChecker()

    /// Names read from Music (only while Music is open) plus names this app
    /// has imported into before, so the note also works with Music closed.
    @Published private(set) var knownNames: Set<String>

    private let service = AppleMusicService()
    private static let rememberedNamesKey = "appleMusicKnownPlaylistNames"

    private init() {
        knownNames = Set(UserDefaults.standard.stringArray(forKey: Self.rememberedNamesKey) ?? [])
    }

    func exists(_ name: String) -> Bool {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty == false && knownNames.contains(trimmed)
    }

    func refresh() {
        service.existingPlaylistNames { [weak self] names in
            DispatchQueue.main.async {
                guard let self, names.isEmpty == false else { return }
                self.knownNames.formUnion(names)
            }
        }
    }

    func remember(_ name: String) {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.isEmpty == false, knownNames.contains(trimmed) == false else { return }
        knownNames.insert(trimmed)
        UserDefaults.standard.set(Array(knownNames.prefix(200)), forKey: Self.rememberedNamesKey)
    }
}
