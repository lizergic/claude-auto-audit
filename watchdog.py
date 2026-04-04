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


def auto_commit(cwd, ram_percent):
    try:
        result = subprocess.run(
            ["git", "add", "-A"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return False, ""
        result = subprocess.run(
            ["git", "commit", "-m", f"nightmode: auto-save at {ram_percent}% memory"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return False, result.stdout
        import re as _re
        match = _re.search(r"\b([0-9a-f]{7,})\b", result.stdout)
        sha = match.group(1) if match else ""
        return True, sha
    except Exception:
        return False, ""


def kill_process_tree(pid):
    try:
        proc = psutil.Process(pid)
        children = proc.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        proc.terminate()
        return True
    except psutil.NoSuchProcess:
        return False


def shutdown_sequence(config):
    killed = []
    processes = find_claude_processes()

    for i, proc_info in enumerate(processes):
        remaining = len(processes) - i
        if remaining <= config["min_surviving_instances"]:
            log_event({
                "event": "shutdown_stopped",
                "reason": f"would breach min_surviving_instances ({config['min_surviving_instances']})",
                "ram_percent": get_ram_percent(),
            })
            break

        cwd = get_process_cwd(proc_info["pid"])
        ram_pct = get_ram_percent()
        success, sha = auto_commit(cwd, ram_pct)
        kill_ok = kill_process_tree(proc_info["pid"])

        if kill_ok:
            killed.append(proc_info)
            log_event({
                "event": "instance_killed",
                "pid": proc_info["pid"],
                "working_dir": cwd,
                "ram_percent": ram_pct,
                "commit_success": success,
                "commit_sha": sha,
            })

        time.sleep(10)
        ram_after = get_ram_percent()
        log_event({
            "event": "ram_after_kill",
            "ram_percent": ram_after,
        })

        if ram_after < config["ram_safe_threshold"]:
            break

    return killed


def main():
    config = load_config()

    if not acquire_lock():
        print("Another watchdog instance is running. Exiting.")
        sys.exit(1)

    log_event({"event": "watchdog_started"})

    try:
        while os.path.exists(FLAG_FILE):
            ram = get_ram_percent()

            if ram >= config["ram_kill_threshold"]:
                log_event({"event": "ram_critical", "ram_percent": ram})
                shutdown_sequence(config)
            elif ram >= config["ram_warning_threshold"]:
                log_event({"event": "ram_warning", "ram_percent": ram})

            time.sleep(config["watchdog_poll_interval_s"])
    finally:
        log_event({"event": "watchdog_stopped"})
        release_lock()


if __name__ == "__main__":
    main()
