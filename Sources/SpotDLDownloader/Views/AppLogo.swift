import AppKit
import SwiftUI

/// The download gesture sits in the open groove of a record.
/// Used when the packaged icon is unavailable, and for untiled marks.
struct AppLogoMark: Shape {
    func path(in rect: CGRect) -> Path {
        let side = min(rect.width, rect.height)
        let origin = CGPoint(x: rect.midX - side / 2, y: rect.midY - side / 2)
        func point(_ x: CGFloat, _ y: CGFloat) -> CGPoint {
            CGPoint(x: origin.x + side * x, y: origin.y + side * y)
        }

        var path = Path()
        path.addArc(
            center: point(0.5, 0.6),
            radius: side * 0.265,
            startAngle: .degrees(-140),
            endAngle: .degrees(-40),
            clockwise: true
        )
        path.move(to: point(0.5, 0.215))
        path.addLine(to: point(0.5, 0.515))
        path.move(to: point(0.395, 0.415))
        path.addLine(to: point(0.5, 0.52))
        path.addLine(to: point(0.605, 0.415))
        // A short stroke produces the same round center dot at every size.
        path.move(to: point(0.5, 0.64))
        path.addLine(to: point(0.5, 0.641))
        return path
    }
}

struct AppLogoView: View {
    var size: CGFloat = 32
    var showTile: Bool = true
    @Environment(\.colorScheme) private var colorScheme

    private static let packagedIcon: NSImage? = {
        guard let url = Bundle.main.url(forResource: "AppIcon", withExtension: "icns") else {
            return nil
        }
        return NSImage(contentsOf: url)
    }()

    var body: some View {
        Group {
            if showTile, let icon = Self.packagedIcon {
                Image(nsImage: icon)
                    .resizable()
                    .interpolation(.high)
                    .scaledToFit()
            } else {
                vectorLogo
            }
        }
        .frame(width: size, height: size)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Spotify Downloader")
    }

    private var vectorLogo: some View {
        ZStack {
            if showTile {
                RoundedRectangle(cornerRadius: size * 0.22, style: .continuous)
                    .fill(
                        LinearGradient(
                            colors: [Color(red: 0.14, green: 0.37, blue: 0.30), Color(red: 0.035, green: 0.17, blue: 0.14)],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .padding(size * 0.07)
            }
            AppLogoMark()
                .stroke(
                    LinearGradient(
                        colors: showTile || colorScheme == .dark
                            ? [Color(red: 0.95, green: 1, blue: 0.97), Color(red: 0.72, green: 0.96, blue: 0.83)]
                            : [Color(red: 0.14, green: 0.37, blue: 0.30), Color(red: 0.035, green: 0.17, blue: 0.14)],
                        startPoint: .top,
                        endPoint: .bottom
                    ),
                    style: StrokeStyle(lineWidth: size * 0.082, lineCap: .round, lineJoin: .round)
                )
        }
    }
}

struct AppLogoLockup: View {
    var logoSize: CGFloat = 30

    var body: some View {
        HStack(spacing: 9) {
            AppLogoView(size: logoSize)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 3) {
                Text("Spotify Downloader")
                    .font(.system(size: 13, weight: .semibold))
                    .lineLimit(1)
                Text("Your music, collected.")
                    .font(.system(size: 10.5, weight: .medium))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
        .accessibilityElement(children: .combine)
    }
}
