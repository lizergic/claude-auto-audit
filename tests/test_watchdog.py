import json
import os
import glob
import pytest
import psutil
from unittest.mock import MagicMock, patch

import watchdog


@pytest.fixture
def patched_watchdog(nightmode_env, monkeypatch):
    monkeypatch.setattr(watchdog, "FLAG_FILE", nightmode_env["flag_file"])
    monkeypatch.setattr(watchdog, "LOCK_FILE", str(nightmode_env["tmp_path"] / "watchdog.lock"))
    monkeypatch.setattr(watchdog, "LOG_DIR", nightmode_env["watchdog_log_dir"])
    monkeypatch.setattr(watchdog, "CONFIG_PATH", os.path.join(nightmode_env["config_dir"], "config.json"))
    return watchdog


def make_mock_proc(pid, name, cmdline, rss, cwd="/tmp/project"):
    proc = MagicMock()
    proc.info = {
        "pid": pid,
        "name": name,
        "cmdline": cmdline,
        "memory_info": MagicMock(rss=rss),
    }
    proc.pid = pid
    proc.cwd.return_value = cwd
    proc.children.return_value = []
    return proc


class TestGetRamPercent:
    @patch("watchdog.psutil")
    def test_returns_percent(self, mock_psutil):
        mock_psutil.virtual_memory.return_value = MagicMock(percent=72.5)
        assert watchdog.get_ram_percent() == 72.5


class TestFindClaudeProcesses:
    @patch("watchdog.psutil")
    def test_finds_claude_node_processes(self, mock_psutil):
        procs = [
            make_mock_proc(100, "node.exe", ["node", "M:/npm-global/claude"], 500_000_000),
            make_mock_proc(200, "node.exe", ["node", "some-other-app"], 300_000_000),
            make_mock_proc(300, "node.exe", ["node", "M:/npm-global/claude"], 800_000_000),
            make_mock_proc(400, "chrome.exe", ["chrome"], 1_000_000_000),
        ]
        mock_psutil.process_iter.return_value = procs
        mock_psutil.NoSuchProcess = psutil.NoSuchProcess
        mock_psutil.AccessDenied = psutil.AccessDenied

        result = watchdog.find_claude_processes()
        assert len(result) == 2
        assert result[0]["pid"] == 300  # sorted biggest first
        assert result[1]["pid"] == 100

    @patch("watchdog.psutil")
    def test_returns_empty_when_no_claude(self, mock_psutil):
        procs = [make_mock_proc(100, "chrome.exe", ["chrome"], 500_000_000)]
        mock_psutil.process_iter.return_value = procs
        mock_psutil.NoSuchProcess = psutil.NoSuchProcess
        mock_psutil.AccessDenied = psutil.AccessDenied

        assert watchdog.find_claude_processes() == []


class TestGetProcessCwd:
    @patch("watchdog.psutil")
    def test_returns_cwd(self, mock_psutil):
        mock_proc = MagicMock()
        mock_proc.cwd.return_value = "M:/Github/my-project"
        mock_psutil.Process.return_value = mock_proc

        assert watchdog.get_process_cwd(1234) == "M:/Github/my-project"

    @patch("watchdog.psutil")
    def test_returns_unknown_on_error(self, mock_psutil):
        mock_psutil.Process.side_effect = psutil.NoSuchProcess(1234)
        mock_psutil.NoSuchProcess = psutil.NoSuchProcess
        mock_psutil.AccessDenied = psutil.AccessDenied

        assert watchdog.get_process_cwd(1234) == "unknown"


class TestLock:
    def test_acquire_and_release(self, patched_watchdog, nightmode_env):
        assert patched_watchdog.acquire_lock() is True
        lock_path = str(nightmode_env["tmp_path"] / "watchdog.lock")
        assert os.path.exists(lock_path)
        patched_watchdog.release_lock()
        assert not os.path.exists(lock_path)

    @patch("watchdog.psutil")
    def test_acquire_fails_when_locked_by_running_process(
        self, mock_psutil, patched_watchdog, nightmode_env
    ):
        lock_path = str(nightmode_env["tmp_path"] / "watchdog.lock")
        with open(lock_path, "w") as f:
            f.write(str(os.getpid()))
        mock_psutil.pid_exists.return_value = True

        assert patched_watchdog.acquire_lock() is False

    @patch("watchdog.psutil")
    def test_acquire_succeeds_on_stale_lock(
        self, mock_psutil, patched_watchdog, nightmode_env
    ):
        lock_path = str(nightmode_env["tmp_path"] / "watchdog.lock")
        with open(lock_path, "w") as f:
            f.write("99999")
        mock_psutil.pid_exists.return_value = False

        assert patched_watchdog.acquire_lock() is True


class TestLogEvent:
    def test_writes_jsonl(self, patched_watchdog, nightmode_env):
        patched_watchdog.log_event({"event": "test", "ram_percent": 85})
        files = glob.glob(os.path.join(nightmode_env["watchdog_log_dir"], "*.jsonl"))
        assert len(files) == 1
        with open(files[0]) as f:
            entry = json.loads(f.readline())
        assert entry["event"] == "test"
