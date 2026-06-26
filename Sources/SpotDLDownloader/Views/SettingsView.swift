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
    @AppStorage("debugLogging") private var debugLogging = false

    var body: some View {
        Form {
            Section("Downloads") {
                HStack {
                    TextField("Folder", text: $downloadFolderPath)
                    Button("Choose") {
                        if let chosen = FolderPicker.chooseFolder(startingAt: downloadFolderPath) {
                            downloadFolderPath = chosen
                        }
                    }
                }

                Stepper(value: $downloadThreads, in: 1...16) {
                    Text("\(max(1, downloadThreads)) concurrent downloads")
                }
            }

            Section("Audio") {
                Picker("Format", selection: $audioFormat) {
                    ForEach(AudioFormat.allCases) { format in
                        Text(format.rawValue.uppercased()).tag(format.rawValue)
                    }
                }

                Picker("Bitrate", selection: $bitrate) {
                    ForEach(Bitrate.allCases) { option in
                        Text(option.label).tag(option.rawValue)
                    }
                }

                Picker("Existing files", selection: $overwrite) {
                    ForEach(ExistingFileBehavior.allCases) { option in
                        Text(option.label).tag(option.rawValue)
                    }
                }

                Toggle("Track numbers in filenames", isOn: $trackNumberPrefix)
                    .toggleStyle(.checkbox)

                Toggle("Closest-match fallback", isOn: $allowClosestMatch)
                    .toggleStyle(.checkbox)

                Toggle("Debug logs", isOn: $debugLogging)
                    .toggleStyle(.checkbox)
            }

            Section("Diagnostics") {
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
