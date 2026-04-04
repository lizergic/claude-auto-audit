import os
import sys
import json
import time
import subprocess
from datetime import datetime, timezone

import psutil

FLAG_FILE = "M:/.claude-liz/nightmode.active"
LOCK_FILE = "M:/.claude-liz/watchdog.lock"
LOG_DIR = "M:/.claude-liz/watchdog-logs"
CONFIG_PATH = "M:/.claude-liz/nightmode/config.json"


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def get_ram_percent():
    return psutil.virtual_memory().percent


def find_claude_processes():
    results = []
    for proc in psutil.process_iter(["pid", "name", "cmdline", "memory_info"]):
        try:
            name = proc.info["name"] or ""
            if name.lower() not in ("node.exe", "claude.exe"):
                continue
            cmdline = " ".join(proc.info["cmdline"] or [])
            if "claude" not in cmdline.lower():
                continue
            results.append({
                "pid": proc.info["pid"],
                "memory_bytes": proc.info["memory_info"].rss,
                "cmdline": cmdline,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return sorted(results, key=lambda x: x["memory_bytes"], reverse=True)


def get_process_cwd(pid):
    try:
        return psutil.Process(pid).cwd()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return "unknown"


def acquire_lock():
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE) as f:
                old_pid = int(f.read().strip())
            if psutil.pid_exists(old_pid):
                return False
        except (ValueError, FileNotFoundError):
            pass
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    return True


def release_lock():
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)


def log_event(event):
    os.makedirs(LOG_DIR, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join(LOG_DIR, f"{date_str}.jsonl")
    event["timestamp"] = datetime.now(timezone.utc).isoformat()
    with open(path, "a") as f:
        f.write(json.dumps(event) + "\n")
