import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


@pytest.fixture
def audit_env(tmp_path):
    """Temporary auto-audit directory structure for tests."""
    config_dir = tmp_path / "claude-auto-audit"
    config_dir.mkdir()
    log_dir = tmp_path / "safety-logs"
    log_dir.mkdir()
    watchdog_log_dir = tmp_path / "watchdog-logs"
    watchdog_log_dir.mkdir()

    config = {
        "ollama_url": "http://localhost:11434",
        "model": "qwen2.5-coder:3b",
        "classification_timeout_ms": 3000,
        "watchdog_poll_interval_s": 30,
        "ram_warning_threshold": 80,
        "ram_kill_threshold": 85,
        "ram_safe_threshold": 75,
        "min_surviving_instances": 1,
    }
    (config_dir / "config.json").write_text(json.dumps(config))
    (config_dir / "blocked-patterns.txt").write_text("^git\\s+push(\\s|$)\n")

    flag_file = tmp_path / "auto-audit.active"

    return {
        "tmp_path": tmp_path,
        "config_dir": str(config_dir),
        "log_dir": str(log_dir),
        "watchdog_log_dir": str(watchdog_log_dir),
        "flag_file": str(flag_file),
        "config": config,
    }
