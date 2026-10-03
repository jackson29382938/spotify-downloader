import json
import os
from pathlib import Path
import sys
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PySide6.QtCore import QObject, QSettings, Signal

from desktop.commands import DownloadOptions, parse_urls
from desktop.process import HelperProcess
from desktop.window import MainWindow
import spotify_dl as dl


URL = "https://open.spotify.com/track/abc123"


class FakeRunner(QObject):
    record = Signal(dict)
    line = Signal(str)
    completed = Signal(int, str)

    def __init__(self):
        super().__init__()
        self.busy = False
        self.calls = []
        self.cancel_reason = ""

    def start(self, args, timeout=0):
        assert not self.busy
        self.busy = True
        self.calls.append((args, timeout))

    def cancel(self, reason="Stopped; completed files have been kept."):
        self.cancel_reason = reason

    def finish(self, code=0, reason=""):
        self.busy = False
        self.completed.emit(code, reason)


@pytest.fixture
def window(qtbot, tmp_path):
    runner = FakeRunner()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    widget = MainWindow(runner, settings)
    widget.output.setText(str(tmp_path / "output"))
    widget.urls.setPlainText(URL)
    yield widget
    runner.busy = False
    widget.close()
    widget.deleteLater()


def test_arguments_preserve_paths_and_do_not_execute_input(tmp_path):
    output = str(tmp_path / "Music & $(echo injected)")
    args = DownloadOptions(output, cookies="firefox").arguments([URL])
    parsed = dl.parse_args(args)
    assert parsed.output_dir == output
    assert parsed.cookies_browser == "firefox"
    assert parsed.urls == [URL]
    assert parse_urls(URL + "\n" + URL) == [URL]
    with pytest.raises(ValueError):
        parse_urls("--output-dir=/tmp/wrong")
    with pytest.raises(ValueError):
        parse_urls(URL, "video")
    with pytest.raises(ValueError):
        parse_urls("https://www.youtube.com.evil.example/watch?v=x")


def test_preview_partial_errors_are_not_reported_as_success(window):
    window._download(True)
    window.runner.record.emit({"items": [{"tracks": [{"title": "A song", "artists": "Artist"}]}],
                               "errors": [{"message": "Network denied"}]})
    window.runner.finish()
    assert window.queue.rowCount() == 1
    assert "errors" in window.status.text()
    assert "Network denied" in window.activity.toPlainText()


def test_pause_resume_uses_original_options_and_skips_completed(window):
    window._download(False)
    assert not window.download_button.isEnabled()
    window._pause()
    assert not window.resume_button.isEnabled()  # wait for process exit
    window.runner.finish(130, window.runner.cancel_reason)
    assert window.resume_button.isEnabled()
    window.output.setText("another folder")
    window.urls.setPlainText("https://youtu.be/another")
    original_output = window.last_job[0].output
    window._resume()
    args = dl.parse_args(window.runner.calls[-1][0])
    assert args.urls == [URL]
    assert args.output_dir == original_output
    assert args.overwrite == "skip"


def test_retry_only_failed_sources_and_stop_clears_resume(window):
    second = "https://youtu.be/test"
    window.urls.setPlainText(URL + "\n" + second)
    window._download(False)
    window.runner.record.emit({"event": "source_finished", "source_url": second, "failed_count": 1})
    window.runner.finish(1)
    assert window.retry_button.isEnabled()
    window._retry()
    args = dl.parse_args(window.runner.calls[-1][0])
    assert args.urls == [second]
    assert args.overwrite == "skip"
    window._pause()
    window._stop()
    window.runner.finish(130, window.runner.cancel_reason)
    assert window.resume_job is None
    assert not window.resume_button.isEnabled()


def test_health_checks_inspect_individual_results(window):
    window._health(True)
    window.runner.record.emit({"ok": True, "checks": [
        {"name": "ffmpeg", "ok": True, "detail": "ready"},
        {"name": "Spotify reachable", "ok": False, "detail": "HTTP 403"}]})
    window.runner.finish()
    assert "errors" in window.status.text()
    assert window.checks.item(1, 1).text() == "Failed"


def test_unrecognized_json_does_not_count_as_result(window):
    window._health(False)
    window.runner.record.emit({"unexpected": "payload"})
    window.runner.finish()
    assert "no results" in window.status.text()


def test_helper_size_limit_aborts_overlong_record(qtbot):
    runner = HelperProcess(command=[sys.executable, "-c", "import os,time; os.write(1,b'x'*40+b'\\n'); time.sleep(60)"])
    runner.MAX_LINE = 16
    with qtbot.waitSignal(runner.completed, timeout=10000) as result:
        runner.start([])
    assert "safe record size" in result.args[1]
    assert not runner.busy


@pytest.mark.skipif(os.name != "nt", reason="Native Windows Job Object check")
def test_windows_helper_is_assigned_to_kill_on_close_job(qtbot, tmp_path):
    script = tmp_path / "windows_job.py"
    root = Path(__file__).resolve().parents[1]
    script.write_text(f"import sys\nsys.path.insert(0,{str(root)!r})\n"
                      "import ctypes,json\nfrom ctypes import wintypes\n"
                      "from desktop_helper import contain_process_tree\n"
                      "handle=contain_process_tree()\n"
                      "kernel=ctypes.WinDLL('kernel32',use_last_error=True)\n"
                      "kernel.GetCurrentProcess.restype=wintypes.HANDLE\n"
                      "kernel.IsProcessInJob.argtypes=[wintypes.HANDLE,wintypes.HANDLE,ctypes.POINTER(wintypes.BOOL)]\n"
                      "inside=wintypes.BOOL()\n"
                      "assert kernel.IsProcessInJob(kernel.GetCurrentProcess(),handle,ctypes.byref(inside))\n"
                      "print(json.dumps({'contained':bool(inside.value)}),flush=True)\n", encoding="utf-8")
    runner = HelperProcess(command=[sys.executable, str(script)])
    records = []
    runner.record.connect(records.append)
    with qtbot.waitSignal(runner.completed, timeout=5000) as result:
        runner.start([])
    assert result.args[0] == 0
    assert records == [{"contained": True}]


def test_progress_updates_same_row_and_preserves_failures(window):
    window._download(False)
    record = {"event": "track_progress", "key": "source1|track", "title": "Song", "total": 2}
    window.runner.record.emit({**record, "state": "running", "message": "Searching"})
    window.runner.record.emit({**record, "state": "failed", "message": "No match"})
    assert window.queue.rowCount() == 1
    assert window.progress.value() == 1
    window.runner.finish(1)
    assert "errors" in window.status.text()


def test_real_helper_health_exercises_qprocess_and_backend(qtbot, tmp_path):
    runner = HelperProcess()
    records = []
    runner.record.connect(records.append)
    with qtbot.waitSignal(runner.completed, timeout=30000) as result:
        runner.start(["health", "--json", "--no-network", "-o", str(tmp_path)])
    assert result.args == [0, ""]
    assert records[-1]["ok"] is True
    assert any(check["name"] == "yt-dlp-ejs" and check["ok"] for check in records[-1]["checks"])
    assert not runner.busy


def test_fragmented_utf8_and_final_record_without_newline(qtbot, tmp_path):
    script = tmp_path / "fragmented.py"
    data = json.dumps({"title": "音楽 🎶"}, ensure_ascii=False).encode("utf-8")
    script.write_text("import os,time\n" + f"data={data!r}\n" +
                      "for byte in data:\n os.write(1, bytes([byte])); time.sleep(.001)\n" +
                      "os.write(2,b'warning without newline')\n", encoding="utf-8")
    runner = HelperProcess(command=[sys.executable, str(script)])
    records, lines = [], []
    runner.record.connect(records.append)
    runner.line.connect(lines.append)
    with qtbot.waitSignal(runner.completed, timeout=5000):
        runner.start([])
    assert records == [{"title": "音楽 🎶"}]
    assert lines == ["warning without newline"]


def test_helper_stops_when_parent_control_pipe_closes(qtbot, tmp_path):
    root = Path(__file__).resolve().parents[1]
    script = tmp_path / "owner_loss.py"
    script.write_text(f"import sys,time\nsys.path.insert(0,{str(root)!r})\n"
                      "import spotify_dl\nfrom desktop_helper import main\n"
                      "spotify_dl.main=lambda: time.sleep(60)\nraise SystemExit(main())\n", encoding="utf-8")
    runner = HelperProcess(command=[sys.executable, str(script)])
    # Wait for containment handshake (consumed internally) before dropping stdin.
    runner.start([])
    qtbot.waitUntil(lambda: runner._isolated, timeout=10000)
    with qtbot.waitSignal(runner.completed, timeout=10000):
        runner.process.closeWriteChannel()
    assert not runner.busy


def test_failed_start_completes_once_and_can_retry(qtbot, tmp_path):
    runner = HelperProcess(command=[str(tmp_path / "missing-executable")])
    results = []
    runner.completed.connect(lambda *args: results.append(args))
    with qtbot.waitSignal(runner.completed, timeout=5000):
        runner.start([])
    assert len(results) == 1
    assert "Could not start" in results[0][1]
    assert not runner.busy
    runner.command = [sys.executable, "-c", "print('{}')"]
    with qtbot.waitSignal(runner.completed, timeout=5000):
        runner.start([])
    assert len(results) == 2


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group assertion; Windows containment uses Job Objects")
def test_timeout_kills_helper_and_descendant(qtbot, tmp_path):
    script = tmp_path / "tree.py"
    script.write_text("import os,sys,time,json,subprocess\nos.setsid()\n"
                      "print(json.dumps({'event':'helper_ready','pid':os.getpid()}),flush=True)\n"
                      "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
                      "print(json.dumps({'child':child.pid}),flush=True)\ntime.sleep(60)\n")
    runner = HelperProcess(command=[sys.executable, str(script)])
    records = []
    runner.record.connect(records.append)
    with qtbot.waitSignal(runner.completed, timeout=10000) as result:
        runner.start([], timeout_ms=300)
    assert "timed out" in result.args[1]
    child = records[0]["child"]
    def stopped():
        if sys.platform != "linux":
            # macOS has no /proc. Check the actual descendant's process state.
            status = subprocess.run(["ps", "-p", str(child), "-o", "stat="], capture_output=True, text=True, check=False)
            return not status.stdout.strip() or status.stdout.strip().startswith("Z")
        try:
            return Path(f"/proc/{child}/stat").read_text().split()[2] == "Z"
        except FileNotFoundError:
            return True
    qtbot.waitUntil(stopped, timeout=3000)
    assert not runner.busy


def test_network_403_is_failed_diagnostics(tmp_path):
    with patch.object(dl.req, "get", return_value=SimpleNamespace(status_code=403)):
        report = dl.health_diagnostics(str(tmp_path))
    assert not report["ok"]
    assert not next(check for check in report["checks"] if check["name"] == "Spotify reachable")["ok"]


def test_missing_javascript_runtime_is_failed_diagnostics(tmp_path):
    with patch.object(dl, "find_js_runtimes", return_value={}):
        assert not dl.health_diagnostics(str(tmp_path), probe_network=False)["ok"]


def test_preview_errors_set_cli_failure_exit(tmp_path, capsys):
    with patch.object(dl, "setup_logging"), patch.object(dl, "preview_sources", return_value=([], [{"message": "failed"}])):
        assert dl.main(["preview", URL]) == 1
    assert json.loads(capsys.readouterr().out)["errors"]


def test_windows_exe_runtime_and_ffmpeg_discovery(tmp_path):
    # Replace the backend's os reference without changing pathlib's platform.
    fake_os = SimpleNamespace(name="nt", environ=os.environ, access=os.access, X_OK=os.X_OK)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "node.exe").touch()
    (bin_dir / "ffmpeg.exe").touch()
    with patch.object(dl, "os", fake_os), patch.object(dl, "app_support_dir", return_value=tmp_path):
        assert ("node", bin_dir / "node.exe") in dl.js_runtime_candidates()
        assert dl.find_ffmpeg_location() == str(bin_dir / "ffmpeg.exe")


@pytest.mark.parametrize("workers", [1, 4])
def test_cancelled_playlist_does_not_queue_tracks(tmp_path, workers):
    collection = dl.SpotifyCollection(name="Cancelled", tracks=[dl.Track("Song", "Artist")], use_subfolder=True)
    args = dl.parse_args(["download", "--threads", str(workers), URL])
    options = dl.RunOptions.from_args(args)
    dl.STOP_EVENT.set()
    try:
        with patch.object(dl, "download_track") as download:
            dl.download_collection(collection, options, str(tmp_path), workers, 1)
        download.assert_not_called()
    finally:
        dl.STOP_EVENT.clear()


def test_queue_survives_restart_without_auto_start_or_cookies(window, qtbot):
    window.cookies.setCurrentIndex(window.cookies.findData("firefox"))
    window._download(False)
    saved = json.loads(window.settings.value("pending_job"))
    assert saved["options"]["cookies"] == ""
    runner = FakeRunner()
    recovered = MainWindow(runner, window.settings)
    qtbot.addWidget(recovered)
    assert runner.calls == []
    assert recovered.resume_button.isEnabled()
    recovered._resume()
    args = dl.parse_args(runner.calls[-1][0])
    assert args.urls == [URL]
    assert args.overwrite == "skip"
    assert args.cookies_browser is None
    runner.finish(0)
    recovered.close()


def test_success_clears_saved_queue_but_failure_keeps_it(window):
    window._download(False)
    window.runner.record.emit({"event": "source_finished", "source_url": URL, "failed_count": 1})
    window.runner.finish(1)
    assert window.settings.value("pending_job")
    assert window.resume_button.isEnabled()
    window._resume()
    window.runner.record.emit({"event": "source_finished", "source_url": URL, "failed_count": 0})
    window.runner.finish()
    assert window.settings.value("pending_job") is None
    assert not window.resume_button.isEnabled()


def test_explicit_stop_discards_recovery(window):
    window._download(False)
    window._stop()
    window.runner.finish(130, window.runner.cancel_reason)
    assert window.settings.value("pending_job") is None
    assert not window.resume_button.isEnabled()


@pytest.mark.parametrize("saved", ['{', '{"version": 99}', '{"version": 1, "options": {}, "urls": ["--evil"]}'])
def test_corrupt_saved_queue_is_ignored(window, qtbot, saved):
    window.settings.setValue("pending_job", saved)
    recovered = MainWindow(FakeRunner(), window.settings)
    qtbot.addWidget(recovered)
    assert recovered.resume_job is None
    assert recovered.settings.value("pending_job") is None
    recovered.close()


def test_selected_match_is_visible_with_reason_and_duration(window):
    window._download(False)
    window.runner.record.emit({"event": "match_selected", "title": "Song", "artists": "Artist",
                              "candidate_title": "Artist — Song (official)", "candidate_duration": 181,
                              "expected_duration": 180, "reason": "title and duration match",
                              "candidate_url": "https://youtu.be/example"})
    assert window.matches.rowCount() == 1
    assert "181" in window.matches.item(0, 2).text()
    assert "https://youtu.be/example" in window.matches.item(0, 3).text()


def test_dependency_help_matches_destination_os():
    with patch.object(dl.sys, "platform", "darwin"):
        assert "brew install ffmpeg node" in dl.dependency_install_help()
    with patch.object(dl.sys, "platform", "win32"), patch.object(dl.os, "name", "nt"):
        assert "winget" in dl.dependency_install_help()
    with patch.object(dl.sys, "platform", "linux"), patch.object(dl.os, "name", "posix"):
        assert "sudo apt install ffmpeg" in dl.dependency_install_help()


def test_stopping_diagnostics_preserves_paused_download(window):
    window._download(False)
    window._pause()
    window.runner.finish(130, window.runner.cancel_reason)
    saved = window.settings.value("pending_job")
    window._health(False)
    window._stop()
    window.runner.finish(130, window.runner.cancel_reason)
    assert window.settings.value("pending_job") == saved
    assert window.resume_button.isEnabled()


def test_closing_download_saves_recovery_queue(window):
    from PySide6.QtWidgets import QMessageBox
    window._download(False)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        window.close()
    assert window.pause_requested
    window.runner.finish(130, window.runner.cancel_reason)
    assert window.settings.value("pending_job")
