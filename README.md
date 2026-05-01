# claude-auto-audit

A local, auditable alternative to Claude Code's built-in auto / bypass-permissions mode. Three components:

1. **Command Safety Gate** — PreToolUse hook that classifies every Bash command via a local AI (Qwen 3B). Hard-blocks `git push`, logs dangerous commands, allows everything else.
2. **RAM Watchdog** *(optional)* — Polls system RAM every 30s. When >85%, gracefully kills Claude instances (biggest first, commits work before killing, never kills the last one).
3. **Morning Report** — Summary of session activity: dangerous commands, blocks, watchdog kills, branch status.

> Anthropic's first-party auto-permissions mode is fine for most people. Use this if you want a local, file-on-disk audit trail for everything Claude tried to run, classified by a model you control.

## Install

Clone into your Claude config dir (so logs and flag files live alongside Claude's own state):

```bash
cd ~/.claude   # or wherever your CLAUDE_CONFIG_DIR points
git clone https://github.com/<your-user>/claude-auto-audit.git
cd claude-auto-audit

python -m venv .venv
.venv/bin/pip install psutil requests pytest      # Unix
# .venv/Scripts/pip install psutil requests pytest  # Windows
```

Install [Ollama](https://ollama.com) and pull the classification model:

```bash
ollama pull qwen2.5-coder:3b
```

Register the hook in your Claude Code `settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "python /absolute/path/to/claude-auto-audit/hook.py" }
        ]
      }
    ]
  }
}
```

Optional — add a shell alias:

```bash
alias caudit="bash ~/.claude/claude-auto-audit/caudit.sh"
```

## Quick Start

```bash
# From a separate terminal (not inside Claude Code):
caudit on                  # starts Ollama, warms model (~60s first time), activates hook (+ watchdog if enabled)
caudit on --no-watchdog    # same, but skip the RAM watchdog
caudit status              # check if active

# Run your Claude Code instances. Walk away.

caudit off                 # deactivates everything, prints session report
```

## How It Works

### Command Safety Gate (hook.py)

Fires on every `Bash` tool call via the `PreToolUse` hook.

- **Audit OFF:** Instant pass-through (no output, no overhead)
- **Audit ON:**
  - Checks command against blocked patterns (`blocked-patterns.txt`)
  - If blocked (e.g. `git push`): **denied**, logged
  - Otherwise: sends to Qwen 3B via Ollama for SAFE/DANGEROUS classification
  - DANGEROUS: **allowed** but logged with reason
  - SAFE: **allowed**, no log
  - Ollama timeout: **allowed**, logged as UNKNOWN (fail-open)

### RAM Watchdog (watchdog.py) — optional

Runs as a background process when enabled. Polls RAM every 30 seconds.

| RAM % | Action |
|-------|--------|
| < 80% | Nothing |
| 80-85% | Log warning |
| 85%+ | Begin graceful shutdown |

Shutdown sequence: finds Claude instances sorted by memory (biggest first), runs `git add -A && git commit` in each working directory, then kills the process tree. Waits 10s between kills. Stops when RAM < 75% or only 1 instance remains. Never kills the last instance.

**Disable it** either by setting `"watchdog_enabled": false` in `config.json`, or by passing `--no-watchdog` to `caudit on`. The hook still works without it — the watchdog is purely a safety net for unattended sessions.

### Morning Report (morning_report.py)

Run automatically by `caudit off`, or manually:

```bash
caudit report              # today + yesterday's logs
caudit report 2026-04-03   # specific date
```

## Configuration

`config.json`:

| Key | Default | Description |
|-----|---------|-------------|
| `ollama_url` | `http://localhost:11434` | Ollama API endpoint |
| `model` | `qwen2.5-coder:3b` | Model for command classification |
| `classification_timeout_ms` | `5000` | Max time to wait for Ollama response |
| `watchdog_enabled` | `true` | Start the RAM watchdog when `caudit on` runs |
| `watchdog_poll_interval_s` | `30` | RAM check interval |
| `ram_warning_threshold` | `80` | Log warning above this % |
| `ram_kill_threshold` | `85` | Start killing instances above this % |
| `ram_safe_threshold` | `75` | Stop killing when RAM drops below this % |
| `min_surviving_instances` | `1` | Never kill below this many instances |

### Blocked Patterns

`blocked-patterns.txt` — one regex per line, `#` for comments:

```
^git\s+push(\s|$)
```

### Ollama binary

`caudit.sh` looks for `ollama` on `PATH`. Override with `OLLAMA_BIN=/path/to/ollama`.

## File Layout

Scripts resolve paths relative to their own location. Flag files and logs live one directory up from `claude-auto-audit/`:

```
<parent-dir>/
  auto-audit.active             # exists = audit on
  watchdog.lock                 # watchdog PID (runtime)
  safety-logs/YYYY-MM-DD.jsonl  # command classification logs
  watchdog-logs/YYYY-MM-DD.jsonl # RAM watchdog logs
  claude-auto-audit/
    hook.py            # PreToolUse hook
    watchdog.py        # RAM watchdog (optional)
    morning_report.py  # session summary
    caudit.sh          # on/off toggle
    config.json        # thresholds and model config
    blocked-patterns.txt
    .venv/             # Python venv (psutil, requests, pytest)
    tests/
```

## Running Tests

```bash
cd claude-auto-audit
.venv/bin/python -m pytest tests/ -v       # Unix
# .venv/Scripts/python -m pytest tests/ -v   # Windows
```

## Hardware Notes

- Qwen 3B takes ~60s to cold-load into VRAM (tested on GTX 1660 Ti, 6 GB). `caudit on` handles this automatically.
- Once warm, classification takes ~1.5-3.5s per command.
- The model uses ~2 GB VRAM. Ollama unloads it after inactivity, so daytime VRAM is free for other things.
