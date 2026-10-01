"""Qt desktop interface. Long-running work belongs exclusively to the helper."""
from dataclasses import replace
import json
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .commands import DownloadOptions, parse_urls
from .process import HelperProcess


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    widget.verticalHeader().hide()
    widget.setAlternatingRowColors(True)
    return widget


class MainWindow(QMainWindow):
    def __init__(self, runner=None, settings=None):
        super().__init__()
        self.setWindowTitle("Spotify + YouTube Downloader")
        self.resize(1050, 800)
        self.settings = settings or QSettings("SpotifyDownloader", "Desktop")
        self.runner = runner or HelperProcess(self)
        self.runner.record.connect(self._record)
        self.runner.line.connect(self._log)
        self.runner.completed.connect(self._completed)
        self.operation = ""
        self.failed_urls = []
        self.resume_job = None
        self.last_job = None
        self.pause_requested = False
        self.protocol_failed = False
        self.received_payload = False
        self.rows = {}
        self.track_states = {}
        self.controls = []
        self.action_buttons = []
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self._download_tab()
        self._library_tab()
        self._history_tab()
        self._diagnostics_tab()
        self._restore()
        self._busy(False)

    def _page(self, title):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        self.tabs.addTab(page, title)
        return layout

    def _button(self, title, callback, layout, action=True):
        button = QPushButton(title)
        button.clicked.connect(callback)
        layout.addWidget(button)
        if action:
            self.action_buttons.append(button)
        return button

    def _download_tab(self):
        layout = self._page("Download")
        title = QLabel("Your links. Your library.")
        title.setStyleSheet("font-size: 25px; font-weight: bold; margin-bottom: 6px;")
        layout.addWidget(title)
        note = QLabel("Paste Spotify tracks, albums or playlists, or YouTube links. One per line.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.urls = QPlainTextEdit()
        self.urls.setPlaceholderText("https://open.spotify.com/track/…\nhttps://www.youtube.com/watch?v=…")
        self.urls.setMaximumHeight(120)
        layout.addWidget(self.urls)
        folder_row = QHBoxLayout()
        self.output = QLineEdit()
        self.output.setPlaceholderText("Output folder")
        self.output.setAccessibleName("Output folder")
        folder_row.addWidget(self.output)
        self._button("Choose folder…", self._choose_output, folder_row)
        self._button("Open folder", self._open_output, folder_row, action=False)
        layout.addLayout(folder_row)
        options = QHBoxLayout()
        left, right = QFormLayout(), QFormLayout()
        self.media = QComboBox()
        self.media.addItem("Audio", "audio")
        self.media.addItem("YouTube video (MP4)", "video")
        self.fmt = QComboBox()
        self.fmt.addItems(["mp3", "m4a", "flac", "opus", "ogg", "wav"])
        self.bitrate = QComboBox()
        self.bitrate.addItems(["128k", "192k", "256k", "320k", "0"])
        self.bitrate.setCurrentText("192k")
        self.threads = QSpinBox()
        self.threads.setRange(1, 16)
        self.threads.setValue(4)
        self.retries = QSpinBox()
        self.retries.setRange(0, 5)
        self.retries.setValue(2)
        self.overwrite = QComboBox()
        for label, value in [("Skip completed files", "skip"), ("Refresh metadata", "metadata"), ("Replace existing files", "force")]:
            self.overwrite.addItem(label, value)
        self.cookies = QComboBox()
        self.cookies.addItem("None", "")
        for browser in ["chrome", "firefox", "chromium", "edge", "brave", "opera"]:
            self.cookies.addItem(browser.title(), browser)
        self.cookies.setToolTip("Uses your local browser session for downloads. Preview does not use browser cookies.")
        self.lyrics = QCheckBox("Find and embed lyrics")
        self.lyrics.setChecked(True)
        for label, widget in [("Media", self.media), ("Format", self.fmt), ("Audio quality", self.bitrate), ("Existing files", self.overwrite)]:
            left.addRow(label, widget)
        for label, widget in [("Workers", self.threads), ("Extra attempts", self.retries), ("Browser cookies", self.cookies), ("Lyrics", self.lyrics)]:
            right.addRow(label, widget)
        options.addLayout(left)
        options.addLayout(right)
        layout.addLayout(options)
        self.media.currentIndexChanged.connect(self._media_changed)
        buttons = QHBoxLayout()
        self._button("Preview", lambda: self._download(True), buttons)
        self.download_button = self._button("Download", lambda: self._download(False), buttons)
        self.pause_button = self._button("Pause & keep completed", self._pause, buttons, action=False)
        self.resume_button = self._button("Resume", self._resume, buttons, action=False)
        self.retry_button = self._button("Retry failed sources", self._retry, buttons, action=False)
        self.stop_button = self._button("Stop & keep completed", self._stop, buttons, action=False)
        layout.addLayout(buttons)
        self.status = QLabel("Ready. Preview a link to inspect the queue.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)
        self.queue = table(["Title", "Artist", "Album", "Status"])
        layout.addWidget(self.queue, 1)
        disclaimer = QLabel("Download only media you own or have permission to store. Pause keeps completed files; an unfinished file may restart on resume.")
        disclaimer.setWordWrap(True)
        layout.addWidget(disclaimer)
        self.controls += [self.urls, self.output, self.media, self.fmt, self.bitrate, self.threads, self.retries, self.overwrite, self.cookies, self.lyrics]

    def _library_tab(self):
        layout = self._page("Library tools")
        note = QLabel("Scan local files for metadata matches, repair tags, or embed existing .lrc lyrics. Apple Music automation is available in the native macOS app only.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.library_folder = QLineEdit()
        self.library_folder.setPlaceholderText("Choose a local music folder")
        self.library_folder.setAccessibleName("Library folder")
        row = QHBoxLayout()
        row.addWidget(self.library_folder)
        self._button("Choose folder…", self._choose_library, row)
        layout.addLayout(row)
        buttons = QHBoxLayout()
        for title, command, apply in [("Scan metadata", "library", False), ("Apply metadata", "library", True),
                                       ("Embed .lrc lyrics", "embed-lrc", True), ("Clean lyrics timestamps", "clean-lyrics", True)]:
            self._button(title, lambda checked=False, c=command, a=apply: self._library(c, a), buttons)
        layout.addLayout(buttons)
        layout.addWidget(QLabel("Progress and results appear in Download and Activity. Metadata operations can need network access."))
        layout.addStretch()
        self.controls.append(self.library_folder)

    def _history_tab(self):
        layout = self._page("History")
        self.history = table(["Date", "Source", "Completed", "Failed", "Folder"])
        row = QHBoxLayout()
        self._button("Refresh history", self._refresh_history, row, action=False)
        layout.addLayout(row)
        layout.addWidget(self.history)
        self._refresh_history()

    def _diagnostics_tab(self):
        layout = self._page("Diagnostics & activity")
        row = QHBoxLayout()
        self._button("Local checks", lambda: self._health(False), row)
        self._button("Check network too", lambda: self._health(True), row)
        self._button("Copy activity", self._copy_activity, row, action=False)
        layout.addLayout(row)
        self.checks = table(["Check", "Result", "Details"])
        self.checks.setMaximumHeight(250)
        layout.addWidget(self.checks)
        self.activity = QPlainTextEdit()
        self.activity.setReadOnly(True)
        self.activity.document().setMaximumBlockCount(2000)
        layout.addWidget(self.activity, 1)

    def _restore(self):
        default = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation) or str(Path.home() / "Downloads")
        self.output.setText(self.settings.value("output", str(Path(default) / "Music")))
        for name, widget in [("format", self.fmt), ("bitrate", self.bitrate)]:
            value = self.settings.value(name, widget.currentText())
            if widget.findText(value) >= 0:
                widget.setCurrentText(value)

    def _save(self):
        self.settings.setValue("output", self.output.text())
        self.settings.setValue("format", self.fmt.currentText())
        self.settings.setValue("bitrate", self.bitrate.currentText())
        self.settings.sync()

    def _options(self):
        return DownloadOptions(self.output.text(), self.media.currentData(), self.fmt.currentText(), self.bitrate.currentText(),
                               self.threads.value(), self.retries.value(), self.overwrite.currentData(), self.lyrics.isChecked(), self.cookies.currentData())

    def _choose_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Output folder", self.output.text())
        if folder:
            self.output.setText(folder)

    def _choose_library(self):
        folder = QFileDialog.getExistingDirectory(self, "Music library", self.library_folder.text())
        if folder:
            self.library_folder.setText(folder)

    def _open_output(self):
        path = Path(self.output.text()).expanduser()
        if path.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.absolute())))
        else:
            self.status.setText("The output folder does not exist yet.")

    def _media_changed(self):
        audio = self.media.currentData() == "audio" and not self.runner.busy
        for widget in (self.fmt, self.bitrate, self.lyrics):
            widget.setEnabled(audio)

    def _busy(self, busy):
        for widget in self.controls + self.action_buttons:
            widget.setEnabled(not busy)
        self.stop_button.setEnabled(busy)
        self.pause_button.setEnabled(busy and self.operation == "download")
        self.resume_button.setEnabled(not busy and self.resume_job is not None)
        self.retry_button.setEnabled(not busy and bool(self.failed_urls))
        self._media_changed()

    def _start(self, operation, args, timeout=0):
        if self.runner.busy:
            return
        self.operation = operation
        self.pause_requested = False
        self.protocol_failed = False
        self.received_payload = False
        self.queue.setRowCount(0)
        self.rows.clear()
        self.track_states.clear()
        self.progress.setRange(0, 0)
        self.status.setText(f"Running {operation}…")
        self.runner.start(args, timeout)
        self._busy(True)

    def _download(self, preview):
        try:
            options = self._options()
            urls = parse_urls(self.urls.toPlainText(), options.media)
            args = options.arguments(urls, preview)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        if not preview and options.overwrite == "force":
            if QMessageBox.question(self, "Replace files?", "Existing matching files will be replaced. Continue?") != QMessageBox.StandardButton.Yes:
                return
        self._save()
        if not preview:
            self.last_job = (options, urls)
            self.resume_job = None
            self.failed_urls.clear()
        self._start("preview" if preview else "download", args, 120000 if preview else 0)

    def _pause(self):
        if self.operation == "download" and self.runner.busy:
            self.pause_requested = True
            self.resume_job = self.last_job
            self.runner.cancel("Paused; completed files have been kept.")
            self.pause_button.setEnabled(False)
            self.stop_button.setEnabled(False)

    def _stop(self):
        self.pause_requested = False
        self.resume_job = None
        self.runner.cancel()
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)

    def _resume(self):
        if not self.resume_job or self.runner.busy:
            return
        options, urls = self.resume_job
        self.resume_job = None
        self.last_job = (replace(options, overwrite="skip"), urls)
        self.failed_urls.clear()
        self._start("download", self.last_job[0].arguments(urls))

    def _retry(self):
        if not self.failed_urls or not self.last_job or self.runner.busy:
            return
        urls = self.failed_urls[:]
        options = replace(self.last_job[0], overwrite="skip")
        self.last_job = (options, urls)
        self.failed_urls.clear()
        self._start("download", options.arguments(urls))

    def _health(self, network):
        args = ["health", "--json", "--output-dir", self.output.text()]
        if not network:
            args.append("--no-network")
        self._start("health", args, 30000)

    def _library(self, command, apply):
        path = Path(self.library_folder.text()).expanduser()
        if not self.library_folder.text().strip() or not path.is_dir():
            self.status.setText("Choose an existing music folder.")
            return
        if apply:
            message = "This updates tags in local audio files. Back up your library first."
            if command == "embed-lrc":
                message += " Successfully embedded .lrc sidecar files are deleted."
            if QMessageBox.question(self, "Update local files?", message + " Continue?") != QMessageBox.StandardButton.Yes:
                return
        args = [command, "--json-events"]
        if command == "library" and apply:
            args.append("--apply")
        self.tabs.setCurrentIndex(0)
        self._start(command, args + ["--", str(path.absolute())])

    def _set_row(self, widget, row, values):
        if row >= widget.rowCount():
            widget.setRowCount(row + 1)
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            widget.setItem(row, column, item)

    def _record(self, record):
        if self.operation == "preview" and "items" in record:
            self.received_payload = True
            for item in record.get("items", []):
                for track in item.get("tracks", []):
                    self._set_row(self.queue, self.queue.rowCount(), [track.get("title", ""), track.get("artists", ""), track.get("album", ""), "Ready"])
            errors = record.get("errors", [])
            self.protocol_failed = bool(errors)
            for error in errors:
                self._log(f"Preview error: {error.get('message', '')}")
            self.status.setText(f"Preview: {self.queue.rowCount()} tracks, {len(errors)} errors.")
        elif self.operation == "health" and "checks" in record:
            self.received_payload = True
            self.checks.setRowCount(0)
            for check in record["checks"]:
                self._set_row(self.checks, self.checks.rowCount(), [check.get("name", ""), "Passed" if check.get("ok") else "Failed", check.get("detail", "")])
            self.protocol_failed = any(not check.get("ok") for check in record["checks"])
            self._log(json.dumps(record, ensure_ascii=False))
        elif record.get("event") == "track_progress":
            self.received_payload = True
            key = str(record.get("key", record.get("label", "unknown")))
            if key not in self.rows:
                self.rows[key] = self.queue.rowCount()
            state = str(record.get("state", "running"))
            self.track_states[key] = state
            self._set_row(self.queue, self.rows[key], [record.get("title", record.get("label", "")), record.get("artists", ""), record.get("album", ""), f"{state}: {record.get('message', '')}"])
            complete = sum(value in {"succeeded", "skipped", "failed"} for value in self.track_states.values())
            total = max(len(self.track_states), int(record.get("total") or 1))
            self.progress.setRange(0, total)
            self.progress.setValue(complete)
        elif record.get("event") == "source_finished":
            self.received_payload = True
            if record.get("failed_count", 0):
                self.protocol_failed = True
                url = record.get("source_url")
                if url and url not in self.failed_urls:
                    self.failed_urls.append(url)
        elif record.get("event") == "collection_finished":
            self.received_payload = True
            self.protocol_failed |= bool(record.get("failed_count", 0))
            self._log(f"Completed: {record.get('ok_count', 0)}; failed: {record.get('failed_count', 0)}")

    def _completed(self, code, reason):
        if reason:
            self.status.setText(reason)
        elif code or self.protocol_failed:
            self.status.setText("Finished with errors. See Diagnostics & activity for details.")
        elif not self.received_payload:
            self.status.setText("The helper returned no results. See Diagnostics & activity.")
        elif self.operation != "preview":
            self.status.setText("Checks passed." if self.operation == "health" else "Completed.")
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 100)
            self.progress.setValue(100 if code == 0 and not reason and not self.protocol_failed and self.received_payload else 0)
        self._log(f"{self.operation} exited with code {code}" + (f": {reason}" if reason else ""))
        self._busy(False)
        self._refresh_history()

    def _log(self, text):
        self.activity.appendPlainText(text)

    def _copy_activity(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.activity.toPlainText())

    def _refresh_history(self):
        # Reuse backend platform paths without importing heavy downloader modules into Qt.
        import os
        import sys
        if sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support" / "Spotify Downloader"
        elif os.name == "nt":
            base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Spotify Downloader"
        else:
            base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "spotify-downloader"
        path = base / "download-history.jsonl"
        self.history.setRowCount(0)
        try:
            # Read a bounded tail rather than loading years of history into the UI.
            with path.open("rb") as stream:
                size = stream.seek(0, 2)
                start = max(0, size - 1024 * 1024)
                stream.seek(start)
                if start:
                    stream.readline()
                lines = stream.read().decode("utf-8", errors="replace").splitlines()[-500:]
        except OSError:
            return
        for line in reversed(lines):
            try:
                item = json.loads(line)
                if not isinstance(item, dict):
                    continue
                self._set_row(self.history, self.history.rowCount(), [item.get("timestamp", ""), item.get("source_url", ""), item.get("ok_count", 0), item.get("failed_count", 0), item.get("output_folder", "")])
            except ValueError:
                continue

    def closeEvent(self, event):
        if self.runner.busy:
            answer = QMessageBox.question(self, "Download running", "Stop the current operation and keep completed files?")
            if answer == QMessageBox.StandardButton.Yes:
                self.runner.completed.connect(lambda *_: self.close())
                self._stop()
            event.ignore()
            return
        self._save()
        event.accept()
