import json
import os
import pytest

import morning_report


@pytest.fixture
def patched_report(nightmode_env, monkeypatch):
    monkeypatch.setattr(morning_report, "SAFETY_LOG_DIR", nightmode_env["log_dir"])
    monkeypatch.setattr(morning_report, "WATCHDOG_LOG_DIR", nightmode_env["watchdog_log_dir"])
    return morning_report


@pytest.fixture
def sample_safety_logs(nightmode_env):
    path = os.path.join(nightmode_env["log_dir"], "2026-04-02.jsonl")
    entries = [
        {
            "timestamp": "2026-04-02T05:14:32+00:00",
            "session_id": "s1",
            "cwd": "/tmp/project",
            "command": "rm -rf node_modules/",
            "classification": "DANGEROUS",
            "reason": "Recursively deletes directory contents",
            "action": "logged_and_approved",
            "model_latency_ms": 850,
        },
        {
            "timestamp": "2026-04-02T08:55:00+00:00",
            "session_id": "s2",
            "cwd": "/tmp/project",
            "command": "git push origin feature/auth",
            "classification": "BLOCKED",
            "reason": "Blocked by nightmode policy",
            "action": "blocked",
        },
    ]
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return path


@pytest.fixture
def sample_watchdog_logs(nightmode_env):
    path = os.path.join(nightmode_env["watchdog_log_dir"], "2026-04-02.jsonl")
    entries = [
        {
            "timestamp": "2026-04-02T10:12:05+00:00",
            "event": "instance_killed",
            "pid": 18244,
            "working_dir": "/tmp/project",
            "ram_percent": 87,
            "commit_success": True,
            "commit_sha": "a1b2c3d",
        },
        {
            "timestamp": "2026-04-02T10:12:15+00:00",
            "event": "ram_after_kill",
            "ram_percent": 71,
        },
    ]
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return path


class TestReadLogs:
    def test_read_safety_logs(self, patched_report, sample_safety_logs):
        logs = patched_report.read_safety_logs("2026-04-02")
        assert len(logs) == 2
        assert logs[0]["command"] == "rm -rf node_modules/"

    def test_read_watchdog_logs(self, patched_report, sample_watchdog_logs):
        logs = patched_report.read_watchdog_logs("2026-04-02")
        assert len(logs) == 2

    def test_read_missing_date_returns_empty(self, patched_report):
        assert patched_report.read_safety_logs("2099-01-01") == []


class TestFormatReport:
    def test_shows_dangerous_commands(self, patched_report, sample_safety_logs, sample_watchdog_logs):
        safety = patched_report.read_safety_logs("2026-04-02")
        watchdog_logs = patched_report.read_watchdog_logs("2026-04-02")
        report = patched_report.format_report(safety, watchdog_logs, [])

        assert "rm -rf node_modules/" in report
        assert "DANGEROUS" in report

    def test_shows_blocked_commands(self, patched_report, sample_safety_logs, sample_watchdog_logs):
        safety = patched_report.read_safety_logs("2026-04-02")
        watchdog_logs = patched_report.read_watchdog_logs("2026-04-02")
        report = patched_report.format_report(safety, watchdog_logs, [])

        assert "git push" in report
        assert "BLOCKED" in report

    def test_shows_watchdog_kills(self, patched_report, sample_safety_logs, sample_watchdog_logs):
        safety = patched_report.read_safety_logs("2026-04-02")
        watchdog_logs = patched_report.read_watchdog_logs("2026-04-02")
        report = patched_report.format_report(safety, watchdog_logs, [])

        assert "18244" in report
        assert "87%" in report

    def test_clean_night_message(self, patched_report):
        report = patched_report.format_report([], [], [])
        assert "Clean night" in report
