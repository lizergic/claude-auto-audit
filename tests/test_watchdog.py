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
            make_mock_proc(100, "node.exe", ["node", "/usr/local/bin/claude"], 500_000_000),
            make_mock_proc(200, "node.exe", ["node", "some-other-app"], 300_000_000),
            make_mock_proc(300, "node.exe", ["node", "/usr/local/bin/claude"], 800_000_000),
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
        mock_proc.cwd.return_value = "/home/user/project"
        mock_psutil.Process.return_value = mock_proc

        assert watchdog.get_process_cwd(1234) == "/home/user/project"

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


class TestAutoCommit:
    @patch("watchdog.subprocess")
    def test_successful_commit(self, mock_subprocess):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "[main abc1234] nightmode: auto-save at 87% memory"
        mock_subprocess.run.return_value = mock_result

        success, sha = watchdog.auto_commit("/tmp/project", 87)
        assert success is True
        assert "abc1234" in sha

    @patch("watchdog.subprocess")
    def test_failed_commit(self, mock_subprocess):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "nothing to commit"
        mock_subprocess.run.return_value = mock_result

        success, sha = watchdog.auto_commit("/tmp/project", 87)
        assert success is False


class TestKillProcessTree:
    @patch("watchdog.psutil")
    def test_kills_process_and_children(self, mock_psutil):
        child1 = MagicMock()
        child2 = MagicMock()
        proc = MagicMock()
        proc.children.return_value = [child1, child2]
        mock_psutil.Process.return_value = proc

        result = watchdog.kill_process_tree(1234)
        assert result is True
        child1.terminate.assert_called_once()
        child2.terminate.assert_called_once()
        proc.terminate.assert_called_once()

    @patch("watchdog.psutil")
    def test_handles_already_dead_process(self, mock_psutil):
        mock_psutil.Process.side_effect = psutil.NoSuchProcess(1234)
        mock_psutil.NoSuchProcess = psutil.NoSuchProcess

        result = watchdog.kill_process_tree(1234)
        assert result is False


class TestShutdownSequence:
    @patch("watchdog.time")
    @patch("watchdog.log_event")
    @patch("watchdog.get_process_cwd", return_value="/tmp/project")
    @patch("watchdog.kill_process_tree", return_value=True)
    @patch("watchdog.auto_commit", return_value=(True, "abc1234"))
    @patch("watchdog.find_claude_processes")
    @patch("watchdog.get_ram_percent")
    def test_kills_biggest_instance_first(
        self, mock_ram, mock_find, mock_commit, mock_kill, mock_cwd, mock_log, mock_time
    ):
        mock_ram.side_effect = [87, 71]  # before kill, after kill (71 < 75 = safe)
        mock_find.return_value = [
            {"pid": 300, "memory_bytes": 800_000_000, "cmdline": "node claude"},
            {"pid": 100, "memory_bytes": 500_000_000, "cmdline": "node claude"},
        ]

        config = {"ram_kill_threshold": 85, "ram_safe_threshold": 75, "min_surviving_instances": 1}
        killed = watchdog.shutdown_sequence(config)

        assert len(killed) == 1
        assert killed[0]["pid"] == 300

    @patch("watchdog.time")
    @patch("watchdog.log_event")
    @patch("watchdog.get_process_cwd", return_value="/tmp/project")
    @patch("watchdog.kill_process_tree")
    @patch("watchdog.auto_commit")
    @patch("watchdog.find_claude_processes")
    @patch("watchdog.get_ram_percent", return_value=90)
    def test_never_kills_last_instance(
        self, mock_ram, mock_find, mock_commit, mock_kill, mock_cwd, mock_log, mock_time
    ):
        mock_find.return_value = [
            {"pid": 100, "memory_bytes": 500_000_000, "cmdline": "node claude"},
        ]

        config = {"ram_kill_threshold": 85, "ram_safe_threshold": 75, "min_surviving_instances": 1}
        killed = watchdog.shutdown_sequence(config)

        assert len(killed) == 0
        mock_kill.assert_not_called()

    @patch("watchdog.time")
    @patch("watchdog.log_event")
    @patch("watchdog.get_process_cwd", return_value="/tmp/project")
    @patch("watchdog.kill_process_tree", return_value=True)
    @patch("watchdog.auto_commit", return_value=(True, "abc1234"))
    @patch("watchdog.find_claude_processes")
    @patch("watchdog.get_ram_percent")
    def test_stops_when_ram_drops_below_safe(
        self, mock_ram, mock_find, mock_commit, mock_kill, mock_cwd, mock_log, mock_time
    ):
        # Iteration 1: ram_pct=90, kill PID 300, sleep, ram_after=82 (>75, continue)
        # Iteration 2: ram_pct=70, kill PID 200, sleep, ram_after=60 (<75, stop)
        mock_ram.side_effect = [90, 82, 70, 60]
        mock_find.return_value = [
            {"pid": 300, "memory_bytes": 800_000_000, "cmdline": "node claude"},
            {"pid": 200, "memory_bytes": 600_000_000, "cmdline": "node claude"},
            {"pid": 100, "memory_bytes": 500_000_000, "cmdline": "node claude"},
        ]

        config = {"ram_kill_threshold": 85, "ram_safe_threshold": 75, "min_surviving_instances": 1}
        killed = watchdog.shutdown_sequence(config)

        assert len(killed) == 2
        assert killed[0]["pid"] == 300
        assert killed[1]["pid"] == 200
