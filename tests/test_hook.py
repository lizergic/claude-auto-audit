import json
import os
import pytest

import hook


@pytest.fixture
def patched_hook(nightmode_env, monkeypatch):
    monkeypatch.setattr(hook, "CONFIG_DIR", nightmode_env["config_dir"])
    monkeypatch.setattr(hook, "FLAG_FILE", nightmode_env["flag_file"])
    monkeypatch.setattr(hook, "LOG_DIR", nightmode_env["log_dir"])
    return hook


class TestMakeAllow:
    def test_structure(self):
        result = hook.make_allow()
        assert result == {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }


class TestMakeDeny:
    def test_structure(self):
        result = hook.make_deny("test reason")
        out = result["hookSpecificOutput"]
        assert out["permissionDecision"] == "deny"
        assert out["permissionDecisionReason"] == "test reason"


class TestIsNightmodeActive:
    def test_returns_false_when_no_flag(self, patched_hook):
        assert patched_hook.is_nightmode_active() is False

    def test_returns_true_when_flag_exists(self, patched_hook, nightmode_env):
        open(nightmode_env["flag_file"], "w").close()
        assert patched_hook.is_nightmode_active() is True


class TestLoadBlockedPatterns:
    def test_loads_patterns(self, patched_hook):
        patterns = patched_hook.load_blocked_patterns()
        assert len(patterns) == 1
        assert patterns[0] == "^git\\s+push(\\s|$)"

    def test_skips_comments_and_blanks(self, patched_hook, nightmode_env):
        path = os.path.join(nightmode_env["config_dir"], "blocked-patterns.txt")
        with open(path, "w") as f:
            f.write("# comment\n\n^rm\\s+-rf\n")
        patterns = patched_hook.load_blocked_patterns()
        assert patterns == ["^rm\\s+-rf"]

    def test_returns_empty_if_file_missing(self, patched_hook, nightmode_env):
        os.remove(os.path.join(nightmode_env["config_dir"], "blocked-patterns.txt"))
        assert patched_hook.load_blocked_patterns() == []


class TestCheckBlocked:
    def test_blocks_git_push(self):
        blocked, pattern = hook.check_blocked("git push origin main", ["^git\\s+push(\\s|$)"])
        assert blocked is True

    def test_blocks_bare_git_push(self):
        blocked, _ = hook.check_blocked("git push", ["^git\\s+push(\\s|$)"])
        assert blocked is True

    def test_allows_git_pull(self):
        blocked, _ = hook.check_blocked("git pull", ["^git\\s+push(\\s|$)"])
        assert blocked is False

    def test_allows_grep_git_push(self):
        blocked, _ = hook.check_blocked("grep 'git push' README.md", ["^git\\s+push(\\s|$)"])
        assert blocked is False


from unittest.mock import patch, MagicMock


class TestClassifyCommand:
    def make_config(self):
        return {
            "ollama_url": "http://localhost:11434",
            "model": "qwen2.5-coder:3b",
            "classification_timeout_ms": 3000,
        }

    @patch("hook.requests")
    def test_dangerous_classification(self, mock_requests):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "response": "DANGEROUS Recursively deletes directory contents"
        }
        mock_requests.post.return_value = mock_resp

        cls, reason, latency = hook.classify_command("rm -rf /", self.make_config())
        assert cls == "DANGEROUS"
        assert "DANGEROUS" in reason

    @patch("hook.requests")
    def test_safe_classification(self, mock_requests):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "SAFE Lists files in directory"}
        mock_requests.post.return_value = mock_resp

        cls, reason, latency = hook.classify_command("ls -la", self.make_config())
        assert cls == "SAFE"

    @patch("hook.requests")
    def test_timeout_returns_unknown(self, mock_requests):
        import requests as real_requests
        mock_requests.post.side_effect = real_requests.exceptions.Timeout("timed out")
        mock_requests.exceptions = real_requests.exceptions

        cls, reason, latency = hook.classify_command("some cmd", self.make_config())
        assert cls == "UNKNOWN"
        assert reason == "ollama_timeout"

    @patch("hook.requests")
    def test_connection_error_returns_unknown(self, mock_requests):
        import requests as real_requests
        mock_requests.post.side_effect = real_requests.exceptions.ConnectionError()
        mock_requests.exceptions = real_requests.exceptions

        cls, reason, latency = hook.classify_command("some cmd", self.make_config())
        assert cls == "UNKNOWN"

    @patch("hook.requests")
    def test_latency_is_measured(self, mock_requests):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "SAFE trivial command"}
        mock_requests.post.return_value = mock_resp

        _, _, latency = hook.classify_command("echo hi", self.make_config())
        assert isinstance(latency, int)
        assert latency >= 0
