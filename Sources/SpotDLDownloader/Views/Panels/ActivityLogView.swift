import SwiftUI

struct ActivityLogView: View {
    @ObservedObject var viewModel: DownloadViewModel

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 10) {
                SectionHeader("Activity", systemImage: "text.alignleft") {
                    Text("Newest first")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    StatusBadge(status: viewModel.status)
                }

                ScrollView {
                    if viewModel.activityLines.isEmpty {
                        Text("Waiting.")
                            .foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .topLeading)
                            .padding(12)
                    } else {
                        // Lazy rows: only the lines on screen are laid out.
                        LazyVStack(alignment: .leading, spacing: 2) {
                            ForEach(Array(viewModel.activityLines.enumerated()), id: \.offset) { _, line in
                                Text(line)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                        .font(.system(.caption, design: .monospaced))
                        .textSelection(.enabled)
                        .padding(12)
                    }
                }
                .frame(minHeight: 240, maxHeight: 520)
                .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: Theme.innerRadius))
                .overlay {
                    RoundedRectangle(cornerRadius: Theme.innerRadius)
                        .stroke(.separator.opacity(0.65))
                }
            }
        }
    }
}
