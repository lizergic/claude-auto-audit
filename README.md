# Night Mode

Safe unattended Claude Code operation overnight. Three components:

1. **Command Safety Gate** — PreToolUse hook that classifies every Bash command via local AI (Qwen 3B). Hard-blocks `git push`, logs dangerous commands, allows everything else.
2. **RAM Watchdog** — Polls system RAM every 30s. When >85%, gracefully kills Claude instances (biggest first, commits work before killing, never kills the last one).
3. **Morning Report** — Summary of overnight activity: dangerous commands, blocks, watchdog kills, branch status.

> Anthropic has since shipped a first-party auto-permissions system in Claude Code itself, so this mostly lives on as a portfolio piece. Still works fine if you want a local, auditable version you own end-to-end.

## Install

Clone into your Claude config dir (so logs and flag files live alongside Claude's own state):

```bash
cd ~/.claude   # or wherever your CLAUDE_CONFIG_DIR points
git clone https://github.com/<your-user>/nightmode.git
cd nightmode

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
          { "type": "command", "command": "python /absolute/path/to/nightmode/hook.py" }
        ]
      }
    ]
  }
}
```

Optional — add a shell alias:

```bash
alias nightmode="bash ~/.claude/nightmode/nightmode.sh"
```

## Quick Start

```bash
# From a separate terminal (not inside Claude Code):
nightmode on      # starts Ollama, warms model (~60s first time), activates hook + watchdog
nightmode status  # check if active

# Run your Claude Code instances in full access mode. Sleep.

nightmode off     # deactivates everything, prints morning report
```

## How It Works

### Command Safety Gate (hook.py)

Fires on every `Bash` tool call via the `PreToolUse` hook.

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

`config.json`:

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

`blocked-patterns.txt` — one regex per line, `#` for comments:

```
^git\s+push(\s|$)
```

### Ollama binary

`nightmode.sh` looks for `ollama` on `PATH`. Override with `OLLAMA_BIN=/path/to/ollama`.

## File Layout

Scripts resolve paths relative to their own location. Flag files and logs live one directory up from `nightmode/`:

```
<parent-dir>/
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
    tests/
```

## Running Tests

```bash
cd nightmode
.venv/bin/python -m pytest tests/ -v       # Unix
# .venv/Scripts/python -m pytest tests/ -v   # Windows
```

## Hardware Notes

- Qwen 3B takes ~60s to cold-load into VRAM (tested on GTX 1660 Ti, 6 GB). `nightmode on` handles this automatically.
- Once warm, classification takes ~1.5-3.5s per command.
- The model uses ~2 GB VRAM. Ollama unloads it after inactivity, so daytime VRAM is free for other things.
