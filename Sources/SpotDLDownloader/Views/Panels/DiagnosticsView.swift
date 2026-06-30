import SwiftUI

struct DiagnosticsView: View {
    @ObservedObject var viewModel: DownloadViewModel

    @AppStorage("downloadFolderPath") private var downloadFolderPath = Defaults.downloadsPath

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 12) {
                SectionHeader("Diagnostics", systemImage: "stethoscope") {
                    Button {
                        viewModel.refreshHealth(outputFolder: downloadFolderPath)
                    } label: {
                        Label(viewModel.isCheckingHealth ? "Checking" : "Refresh", systemImage: "arrow.clockwise")
                    }
                    .disabled(viewModel.isCheckingHealth)
                }

                if let report = viewModel.healthReport {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Label(report.ok ? "Ready" : "Needs attention", systemImage: report.ok ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
                                .foregroundStyle(report.ok ? .green : .orange)
                            Spacer()
                            Text("Sunnify parity \(report.sunnifyParity)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }

                        Text("Python \(report.python) · \(report.platform)")
                            .font(.caption)
                            .foregroundStyle(.secondary)

                        if ffmpegMissing(in: report) {
                            HStack(spacing: 10) {
                                Button {
                                    viewModel.installFFmpeg()
                                } label: {
                                    Label(viewModel.isInstallingFFmpeg ? "Installing ffmpeg…" : "Install FFmpeg", systemImage: "arrow.down.app")
                                }
                                .disabled(viewModel.isInstallingFFmpeg)

                                if viewModel.isInstallingFFmpeg {
                                    ProgressView()
                                        .controlSize(.small)
                                }

                                if let status = viewModel.ffmpegInstallStatus {
                                    Text(status)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                            .padding(8)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: Theme.innerRadius))
                        }

                        LazyVGrid(columns: [GridItem(.adaptive(minimum: 210), spacing: 10)], spacing: 8) {
                            ForEach(report.checks) { check in
                                HStack(alignment: .top, spacing: 8) {
                                    Image(systemName: check.ok ? "checkmark.circle.fill" : "xmark.octagon.fill")
                                        .foregroundStyle(check.ok ? .green : .orange)
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(check.name)
                                            .font(.caption.weight(.medium))
                                        Text(check.detail)
                                            .font(.caption2)
                                            .foregroundStyle(.secondary)
                                            .lineLimit(2)
                                    }
                                }
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(8)
                                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: Theme.innerRadius))
                            }
                        }
                    }
                } else {
                    Text("Run diagnostics to check ffmpeg, yt-dlp, logs, history, and the helper environment.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    private func ffmpegMissing(in report: HelperHealthReport) -> Bool {
        report.checks.contains { $0.name == "ffmpeg" && !$0.ok }
    }
}
