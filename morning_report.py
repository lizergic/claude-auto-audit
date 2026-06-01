import json
import os
import sys
import subprocess
from datetime import datetime, timedelta, timezone

NIGHTMODE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(NIGHTMODE_DIR)
SAFETY_LOG_DIR = os.path.join(BASE_DIR, "safety-logs")
WATCHDOG_LOG_DIR = os.path.join(BASE_DIR, "watchdog-logs")


def read_log_file(path):
    if not os.path.exists(path):
        return []
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def read_safety_logs(date_str):
    return read_log_file(os.path.join(SAFETY_LOG_DIR, f"{date_str}.jsonl"))


def read_watchdog_logs(date_str):
    return read_log_file(os.path.join(WATCHDOG_LOG_DIR, f"{date_str}.jsonl"))


def get_active_repos(safety_logs, watchdog_logs):
    repos = set()
    for entry in safety_logs:
        if entry.get("cwd"):
            repos.add(entry["cwd"])
    for entry in watchdog_logs:
        if entry.get("working_dir"):
            repos.add(entry["working_dir"])
    return repos


def get_branch_status(repo_path):
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "main..HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        lines = [l for l in result.stdout.strip().split("\n") if l]
        if not lines:
            return None
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return {
            "branch": branch.stdout.strip(),
            "commits_ahead": len(lines),
        }
    except Exception:
        return None


def format_time(timestamp_str):
    try:
        dt = datetime.fromisoformat(timestamp_str)
        return dt.strftime("%H:%M")
    except Exception:
        return "??:??"


def format_report(safety_logs, watchdog_logs, branch_statuses):
    dangerous = [e for e in safety_logs if e.get("action") == "logged_and_approved"]
    blocked = [e for e in safety_logs if e.get("action") == "blocked"]
    timeouts = [e for e in safety_logs if e.get("action") == "ollama_timeout_approved"]
    kills = [e for e in watchdog_logs if e.get("event") == "instance_killed"]

    all_timestamps = [e.get("timestamp", "") for e in safety_logs + watchdog_logs]
    all_timestamps = sorted([t for t in all_timestamps if t])
    if all_timestamps:
        start = format_time(all_timestamps[0])
        end = format_time(all_timestamps[-1])
        time_range = f"{start} - {end} UTC"
    else:
        time_range = "no activity"

    lines = []
    lines.append(f"=== NIGHT MODE REPORT ({time_range}) ===")
    lines.append("")
    lines.append(
        f"Commands classified: {len(safety_logs)} | "
        f"Watchdog kills: {len(kills)} | "
        f"Blocked: {len(blocked)} | "
        f"Timeouts: {len(timeouts)}"
    )

    if dangerous:
        lines.append("")
        lines.append("DANGEROUS COMMANDS (logged, allowed):")
        for e in dangerous:
            t = format_time(e.get("timestamp", ""))
            lines.append(f'  [{t}] {e["command"]}  -> "{e.get("reason", "")}"')

    if blocked:
        lines.append("")
        lines.append("BLOCKED:")
        for e in blocked:
            t = format_time(e.get("timestamp", ""))
            lines.append(f'  [{t}] {e["command"]}  -> "{e.get("reason", "")}"')

    if timeouts:
        lines.append("")
        lines.append("OLLAMA TIMEOUTS (approved by default):")
        for e in timeouts:
            t = format_time(e.get("timestamp", ""))
            lines.append(f'  [{t}] {e["command"]}')

    if kills:
        lines.append("")
        lines.append("WATCHDOG:")
        for e in kills:
            t = format_time(e.get("timestamp", ""))
            sha = e.get("commit_sha", "none")
            committed = f"committed ({sha})" if e.get("commit_success") else "commit failed"
            lines.append(
                f'  [{t}] Killed PID {e["pid"]} at {e["ram_percent"]}% RAM -> {committed}'
            )
        for e in watchdog_logs:
            if e.get("event") == "ram_after_kill":
                t = format_time(e.get("timestamp", ""))
                lines.append(f'  [{t}] RAM dropped to {e["ram_percent"]}%')

    if branch_statuses:
        lines.append("")
        lines.append("BRANCHES WITH WORK:")
        for bs in branch_statuses:
            branch = bs["branch"] or "(detached)"
            lines.append(f"  {branch:<30} {bs['commits_ahead']} commits ahead")

    if not (dangerous or blocked or kills or timeouts):
        lines.append("")
        lines.append("Clean night. No dangerous commands, blocks, or watchdog events.")

    return "\n".join(lines)


def main():
    now = datetime.now(timezone.utc)
    dates = []
    if len(sys.argv) > 1:
        dates = [sys.argv[1]]
    else:
        dates = [
            now.strftime("%Y-%m-%d"),
            (now - timedelta(days=1)).strftime("%Y-%m-%d"),
        ]

    all_safety = []
    all_watchdog = []
    for date_str in dates:
        all_safety.extend(read_safety_logs(date_str))
        all_watchdog.extend(read_watchdog_logs(date_str))

    repos = get_active_repos(all_safety, all_watchdog)
    branch_statuses = []
    for repo in repos:
        status = get_branch_status(repo)
        if status:
            branch_statuses.append(status)

    print(format_report(all_safety, all_watchdog, branch_statuses))


if __name__ == "__main__":
    main()
