import sys
import json
import os
import re
import time
from datetime import datetime, timezone
import requests

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


def classify_command(command, config):
    url = f"{config['ollama_url']}/api/generate"
    prompt = (
        "Classify this bash command as SAFE or DANGEROUS.\n"
        "DANGEROUS = destructive, irreversible, or affects external systems.\n"
        f"Command: {command}\n"
        "Respond with exactly one line: SAFE or DANGEROUS followed by a brief reason."
    )
    timeout_s = config["classification_timeout_ms"] / 1000
    start = time.time()
    try:
        resp = requests.post(
            url,
            json={"model": config["model"], "prompt": prompt, "stream": False},
            timeout=timeout_s,
        )
        resp.raise_for_status()
        latency_ms = int((time.time() - start) * 1000)
        text = resp.json().get("response", "").strip()
        if text.upper().startswith("DANGEROUS"):
            return "DANGEROUS", text, latency_ms
        return "SAFE", text, latency_ms
    except Exception:
        latency_ms = int((time.time() - start) * 1000)
        return "UNKNOWN", "ollama_timeout", latency_ms
