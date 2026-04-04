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
