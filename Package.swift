// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "SpotDLDownloader",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(
            name: "SpotDLDownloader",
            targets: ["SpotDLDownloader"]
        )
    ],
    targets: [
        .executableTarget(
            name: "SpotDLDownloader",
            path: "Sources/SpotDLDownloader"
        )
    ]
)
