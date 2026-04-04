import sys
import json
import os
import re
import time
from datetime import datetime, timezone

CONFIG_DIR = "M:/.claude-liz/nightmode"
FLAG_FILE = "M:/.claude-liz/nightmode.active"
LOG_DIR = "M:/.claude-liz/safety-logs"


def is_nightmode_active():
    return os.path.exists(FLAG_FILE)


def load_config():
    with open(os.path.join(CONFIG_DIR, "config.json")) as f:
        return json.load(f)


def load_blocked_patterns():
    path = os.path.join(CONFIG_DIR, "blocked-patterns.txt")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [
            line.strip()
            for line in f
            if line.strip() and not line.strip().startswith("#")
        ]


def check_blocked(command, patterns):
    for pattern in patterns:
        if re.search(pattern, command):
            return True, pattern
    return False, None


def make_allow():
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
    }


def make_deny(reason):
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
