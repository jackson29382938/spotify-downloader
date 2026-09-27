import AppKit
import SwiftUI

@main
struct SpotDLDownloaderApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        WindowGroup("Media Downloader") {
            ContentView()
                .frame(minWidth: 820, minHeight: 620)
        }
        .defaultSize(width: 1140, height: 850)
        .windowResizability(.contentMinSize)

        Settings {
            SettingsView()
                .tint(Theme.accent)
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }
}
