import SwiftUI

/// Strict-to-flexible slider for how YouTube uploads are matched to tracks.
struct MatchFlexibilityControl: View {
    var sliderWidth: CGFloat = 150
    var showsHelp = false

    @AppStorage("matchFlexibility") private var matchFlexibility = MatchFlexibility.defaultValue

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 8) {
                Text("Match")
                Slider(value: $matchFlexibility, in: 0...1, step: 0.05) {
                    Text("Match flexibility")
                } minimumValueLabel: {
                    Image(systemName: "scope")
                        .help("Strict")
                } maximumValueLabel: {
                    Image(systemName: "circle.dashed")
                        .help("Flexible")
                }
                .labelsHidden()
                .frame(width: sliderWidth)
                Text(MatchFlexibility.label(for: matchFlexibility))
                    .font(.caption.weight(.medium))
                    .foregroundStyle(matchFlexibility >= 0.95 ? .orange : .secondary)
                    .frame(minWidth: 88, alignment: .leading)
            }
            .help(MatchFlexibility.help(for: matchFlexibility))

            if showsHelp {
                Text(MatchFlexibility.help(for: matchFlexibility))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}
