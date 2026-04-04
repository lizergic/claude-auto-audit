# Night Mode

Safe unattended Claude Code operation overnight. Three components:

1. **Command Safety Gate** — PreToolUse hook that classifies every Bash command via local AI (Qwen 3B). Hard-blocks `git push`, logs dangerous commands, allows everything else.
2. **RAM Watchdog** — Polls system RAM every 30s. When >85%, gracefully kills Claude instances (biggest first, commits work before killing, never kills the last one).
3. **Morning Report** — Summary of overnight activity: dangerous commands, blocks, watchdog kills, branch status.

## Quick Start

```bash
# From a separate terminal (not inside Claude Code):
nightmode on      # starts Ollama, warms model (~60s first time), activates hook + watchdog
nightmode status   # check if active

# Run your Claude Code instances in full access mode. Sleep.

nightmode off      # deactivates everything, prints morning report
```

If the `nightmode` alias isn't available (new terminal needed after first setup), use:
```bash
bash M:/.claude-liz/nightmode/nightmode.sh on
```

## How It Works

### Command Safety Gate (hook.py)

Registered as a `PreToolUse` hook in `M:/.claude-liz/settings.json`. Fires on every `Bash` tool call.

- **Night mode OFF:** Instant pass-through (no output, no overhead)
- **Night mode ON:**
  - Checks command against blocked patterns (`blocked-patterns.txt`)
  - If blocked (e.g. `git push`): **denied**, logged
  - Otherwise: sends to Qwen 3B via Ollama for SAFE/DANGEROUS classification
  - DANGEROUS: **allowed** but logged with reason
  - SAFE: **allowed**, no log
  - Ollama timeout: **allowed**, logged as UNKNOWN (fail-open)

### RAM Watchdog (watchdog.py)

Runs as a background process. Polls RAM every 30 seconds.

| RAM % | Action |
|-------|--------|
| < 80% | Nothing |
| 80-85% | Log warning |
| 85%+ | Begin graceful shutdown |

Shutdown sequence: finds Claude instances sorted by memory (biggest first), runs `git add -A && git commit` in each working directory, then kills the process tree. Waits 10s between kills. Stops when RAM < 75% or only 1 instance remains. Never kills the last instance.

### Morning Report (morning_report.py)

Run automatically by `nightmode off`, or manually:
```bash
nightmode report              # today + yesterday's logs
nightmode report 2026-04-03   # specific date
```

## Configuration

`M:/.claude-liz/nightmode/config.json`:

| Key | Default | Description |
|-----|---------|-------------|
| `ollama_url` | `http://localhost:11434` | Ollama API endpoint |
| `model` | `qwen2.5-coder:3b` | Model for command classification |
| `classification_timeout_ms` | `5000` | Max time to wait for Ollama response |
| `watchdog_poll_interval_s` | `30` | RAM check interval |
| `ram_warning_threshold` | `80` | Log warning above this % |
| `ram_kill_threshold` | `85` | Start killing instances above this % |
| `ram_safe_threshold` | `75` | Stop killing when RAM drops below this % |
| `min_surviving_instances` | `1` | Never kill below this many instances |

### Blocked Patterns

`M:/.claude-liz/nightmode/blocked-patterns.txt` — one regex per line, `#` for comments:
```
^git\s+push(\s|$)
```

## File Layout

```
M:/.claude-liz/
  nightmode.active              # exists = night mode on
  watchdog.lock                 # watchdog PID (runtime)
  safety-logs/YYYY-MM-DD.jsonl  # command classification logs
  watchdog-logs/YYYY-MM-DD.jsonl # RAM watchdog logs
  nightmode/
    hook.py            # PreToolUse hook
    watchdog.py        # RAM watchdog
    morning_report.py  # overnight summary
    nightmode.sh       # on/off toggle
    config.json        # thresholds and model config
    blocked-patterns.txt
    .venv/             # Python venv (psutil, requests, pytest)
    tests/             # 47 tests
```

## Running Tests

```bash
cd M:/.claude-liz/nightmode
.venv/Scripts/python -m pytest tests/ -v
```

## Hardware Notes

- Qwen 3B takes ~60s to cold-load into VRAM (GTX 1660 Ti, 6 GB). `nightmode on` handles this automatically.
- Once warm, classification takes ~1.5-3.5s per command.
- The model uses ~2 GB VRAM. Ollama unloads it after inactivity, so daytime VRAM is free for other things.
