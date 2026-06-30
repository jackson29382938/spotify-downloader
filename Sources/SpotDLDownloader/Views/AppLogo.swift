import SwiftUI

/// Simple vector mark: rounded tile, download arrow, and audio waves.
struct AppLogoMark: Shape {
    func path(in rect: CGRect) -> Path {
        let scale = min(rect.width, rect.height)
        let origin = CGPoint(
            x: rect.midX - scale / 2,
            y: rect.midY - scale / 2
        )
        let box = CGRect(origin: origin, size: CGSize(width: scale, height: scale))
        let inset = box.width * 0.0625
        let tile = box.insetBy(dx: inset, dy: inset)
        let corner = tile.width * 0.21875

        var path = Path(roundedRect: tile, cornerRadius: corner)

        let centerX = tile.midX
        let arrowTop = tile.minY + tile.height * 0.171875
        let arrowStemBottom = tile.minY + tile.height * 0.453125
        let arrowWingY = tile.minY + tile.height * 0.359375
        let arrowWingX = tile.width * 0.09375

        path.move(to: CGPoint(x: centerX, y: arrowTop))
        path.addLine(to: CGPoint(x: centerX, y: arrowStemBottom))
        path.move(to: CGPoint(x: centerX - arrowWingX, y: arrowWingY))
        path.addLine(to: CGPoint(x: centerX, y: arrowStemBottom))
        path.addLine(to: CGPoint(x: centerX + arrowWingX, y: arrowWingY))

        func wave(y: CGFloat, amplitude: CGFloat, phase: CGFloat) -> Path {
            var wavePath = Path()
            let left = tile.minX + tile.width * 0.265625
            let right = tile.maxX - tile.width * 0.265625
            let mid = tile.midX
            let baseY = tile.minY + tile.height * y
            wavePath.move(to: CGPoint(x: left, y: baseY))
            wavePath.addQuadCurve(
                to: CGPoint(x: mid, y: baseY + tile.height * amplitude),
                control: CGPoint(x: left + tile.width * phase, y: baseY - tile.height * amplitude * 0.35)
            )
            wavePath.addQuadCurve(
                to: CGPoint(x: right, y: baseY),
                control: CGPoint(x: right - tile.width * phase, y: baseY + tile.height * amplitude * 1.35)
            )
            return wavePath
        }

        path.addPath(wave(y: 0.609375, amplitude: 0.0625, phase: 0.125))
        path.addPath(wave(y: 0.71875, amplitude: 0.078125, phase: 0.15625))
        return path
    }
}

struct AppLogoView: View {
    var size: CGFloat = 32
    var showTile: Bool = true

    var body: some View {
        ZStack {
            if showTile {
                RoundedRectangle(cornerRadius: size * 0.22, style: .continuous)
                    .fill(
                        LinearGradient(
                            colors: [Color(red: 0.12, green: 0.84, blue: 0.38), Color(red: 0.09, green: 0.61, blue: 0.27)],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
            }

            AppLogoMark()
                .stroke(
                    .white,
                    style: StrokeStyle(
                        lineWidth: size * (showTile ? 0.055 : 0.07),
                        lineCap: .round,
                        lineJoin: .round
                    )
                )
                .padding(size * (showTile ? 0.18 : 0.04))
        }
        .frame(width: size, height: size)
        .accessibilityLabel("Spotify Downloader")
    }
}

struct AppLogoLockup: View {
    var logoSize: CGFloat = 30

    var body: some View {
        HStack(spacing: 10) {
            AppLogoView(size: logoSize)
            VStack(alignment: .leading, spacing: 1) {
                Text("Spotify Downloader")
                    .font(.headline)
                    .lineLimit(1)
                Text("Media Downloader")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
    }
}
