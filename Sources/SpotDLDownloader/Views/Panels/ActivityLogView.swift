import SwiftUI

struct ActivityLogView: View {
    @ObservedObject var viewModel: DownloadViewModel

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 10) {
                SectionHeader("Activity", systemImage: "text.alignleft") {
                    StatusBadge(status: viewModel.status)
                }

                ScrollViewReader { proxy in
                    ScrollView {
                        Text(viewModel.logText.isEmpty ? "Waiting." : viewModel.logText)
                            .font(.system(.caption, design: .monospaced))
                            .foregroundStyle(viewModel.logText.isEmpty ? .secondary : .primary)
                            .frame(maxWidth: .infinity, alignment: .topLeading)
                            .textSelection(.enabled)
                            .padding(12)
                            .id("log-bottom")
                    }
                    .frame(minHeight: 240)
                    .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: Theme.innerRadius))
                    .overlay {
                        RoundedRectangle(cornerRadius: Theme.innerRadius)
                            .stroke(.separator.opacity(0.65))
                    }
                    .onChange(of: viewModel.logText) {
                        proxy.scrollTo("log-bottom", anchor: .bottom)
                    }
                }
            }
        }
    }
}
