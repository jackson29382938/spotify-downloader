"""Run the cross-platform desktop application, or its headless smoke check."""
import sys


def main():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from desktop.window import MainWindow

    app = QApplication(sys.argv)
    app.setOrganizationName("SpotifyDownloader")
    app.setApplicationName("Desktop")
    window = MainWindow()
    window.show()
    if "--smoke-test" in sys.argv:
        from tempfile import TemporaryDirectory
        output = TemporaryDirectory(prefix="spotify-desktop-smoke-")
        window.output.setText(output.name)
        window.runner.completed.connect(lambda code, reason: app.exit(
            1 if code or reason or window.protocol_failed or not window.received_payload else 0))
        QTimer.singleShot(0, lambda: window._health(False))
        QTimer.singleShot(40000, lambda: window.runner.cancel("Smoke check timed out."))
        result = app.exec()
        output.cleanup()
        return result
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
