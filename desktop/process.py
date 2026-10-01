"""Asynchronous, bounded, UTF-8-safe communication with an isolated helper."""
import json
import os
from pathlib import Path
import signal
import sys

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal


class HelperProcess(QObject):
    record = Signal(dict)
    line = Signal(str)
    completed = Signal(int, str)
    MAX_LINE = 16 * 1024 * 1024

    def __init__(self, parent=None, command=None):
        super().__init__(parent)
        root = Path(__file__).resolve().parents[1]
        if command is not None:
            self.command = command
        elif getattr(sys, "frozen", False):
            helper = Path(sys.executable).parent / "helper" / ("spotify-helper.exe" if os.name == "nt" else "spotify-helper")
            self.command = [str(helper)]
        else:
            self.command = [sys.executable, "-u", str(root / "desktop_helper.py")]
        self.process = QProcess(self)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONUNBUFFERED", "1")
        environment.insert("PYTHONIOENCODING", "utf-8")
        environment.insert("TERM", "dumb")
        self.process.setProcessEnvironment(environment)
        self.process.readyReadStandardOutput.connect(lambda: self._read(False))
        self.process.readyReadStandardError.connect(lambda: self._read(True))
        self.process.finished.connect(self._finish)
        self.process.errorOccurred.connect(self._error)
        self.process.started.connect(self._started)
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self._timeout)
        self.kill_timer = QTimer(self)
        self.kill_timer.setSingleShot(True)
        self.kill_timer.timeout.connect(self._kill_tree)
        self._active = False
        self._pid = 0
        self._buffers = [bytearray(), bytearray()]
        self._reason = ""
        self._isolated = False

    @property
    def busy(self):
        return self._active

    def start(self, arguments, timeout_ms=0):
        if self.busy:
            raise RuntimeError("Another operation is still running.")
        self._active = True
        self._buffers = [bytearray(), bytearray()]
        self._reason = ""
        self._pid = 0
        self._isolated = False
        self.process.setProgram(self.command[0])
        self.process.setArguments(self.command[1:] + list(arguments))
        self.process.start()
        if timeout_ms:
            self.deadline.start(timeout_ms)

    def _started(self):
        self._pid = int(self.process.processId())
        if self._reason:
            self.process.write(b"cancel\n")

    def cancel(self, reason="Stopped; completed files have been kept."):
        if not self.busy:
            return
        self._reason = reason
        self.deadline.stop()
        self.process.write(b"cancel\n")
        if not self.kill_timer.isActive():
            self.kill_timer.start(5000)

    def _timeout(self):
        self.cancel("The operation timed out. Check network access and diagnostics.")

    def _kill_tree(self):
        # The helper starts a dedicated POSIX session before importing the backend.
        if os.name != "nt" and self._pid and self._isolated:
            try:
                os.killpg(self._pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        # Windows: helper's kill-on-close Job Object terminates descendants too.
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()

    def _read(self, stderr):
        data = self.process.readAllStandardError() if stderr else self.process.readAllStandardOutput()
        buffer = self._buffers[int(stderr)]
        buffer.extend(bytes(data))
        while b"\n" in buffer:
            raw, _, rest = buffer.partition(b"\n")
            buffer[:] = rest
            if len(raw) > self.MAX_LINE:
                self.cancel("Helper output exceeded the safe record size.")
                continue
            self._dispatch(raw, stderr)
        if len(buffer) > self.MAX_LINE:
            buffer.clear()
            self.cancel("Helper output exceeded the safe record size.")

    def _dispatch(self, raw, stderr=False):
        text = raw.decode("utf-8", errors="replace").strip()
        if not text:
            return
        if not stderr:
            try:
                record = json.loads(text)
                if isinstance(record, dict):
                    if record.get("event") == "helper_ready":
                        self._isolated = record.get("pid") == self._pid
                        return
                    self.record.emit(record)
                    return
            except ValueError:
                pass
        self.line.emit(text[:4000])

    def _error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._reason = f"Could not start the downloader: {self.process.errorString()}"
            self._finish(-1)

    def _finish(self, code, status=None):
        if not self._active:
            return
        self.deadline.stop()
        self.kill_timer.stop()
        self._read(False)
        self._read(True)
        for index, buffer in enumerate(self._buffers):
            if buffer:
                self._dispatch(bytes(buffer), bool(index))
                buffer.clear()
        self._active = False
        # A helper can finish before a spawned FFmpeg process has exited.
        self._kill_tree()
        self._pid = 0
        if status == QProcess.ExitStatus.CrashExit and not self._reason:
            self._reason = "The downloader process crashed. See the activity log."
        self.completed.emit(int(code), self._reason)
