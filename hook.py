import sys
import json
import os
import re
import time
from datetime import datetime, timezone
import requests

NIGHTMODE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(NIGHTMODE_DIR)
FLAG_FILE = os.path.join(BASE_DIR, "nightmode.active")
LOG_DIR = os.path.join(BASE_DIR, "safety-logs")


def is_nightmode_active():
    return os.path.exists(FLAG_FILE)


def load_config():
    with open(os.path.join(NIGHTMODE_DIR, "config.json")) as f:
        return json.load(f)


def load_blocked_patterns():
    path = os.path.join(NIGHTMODE_DIR, "blocked-patterns.txt")
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


def log_entry(entry):
    os.makedirs(LOG_DIR, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join(LOG_DIR, f"{date_str}.jsonl")
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def main():
    if not is_nightmode_active():
        return

    hook_input = json.loads(sys.stdin.read())
    command = hook_input.get("tool_input", {}).get("command", "")
    session_id = hook_input.get("session_id", "")
    cwd = hook_input.get("cwd", "")

    if not command:
        return

    patterns = load_blocked_patterns()
    blocked, matched = check_blocked(command, patterns)
    if blocked:
        reason = f"Blocked by nightmode policy (pattern: {matched})"
        log_entry({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "cwd": cwd,
            "command": command,
            "classification": "BLOCKED",
            "reason": reason,
            "action": "blocked",
        })
        print(json.dumps(make_deny(reason)))
        return

    config = load_config()
    classification, reason, latency_ms = classify_command(command, config)

    if classification == "DANGEROUS":
        log_entry({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "cwd": cwd,
            "command": command,
            "classification": "DANGEROUS",
            "reason": reason,
            "action": "logged_and_approved",
            "model_latency_ms": latency_ms,
        })
    elif classification == "UNKNOWN":
        log_entry({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "cwd": cwd,
            "command": command,
            "classification": "UNKNOWN",
            "reason": reason,
            "action": "ollama_timeout_approved",
            "model_latency_ms": latency_ms,
        })

    print(json.dumps(make_allow()))


if __name__ == "__main__":
    main()
