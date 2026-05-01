#!/bin/bash
set -e

AUDIT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(dirname "$AUDIT_DIR")"
FLAG_FILE="$BASE_DIR/auto-audit.active"
LOCK_FILE="$BASE_DIR/watchdog.lock"

# Auto-detect venv python (Windows vs Unix layout), fall back to system python
if [ -f "$AUDIT_DIR/.venv/Scripts/python.exe" ]; then
  PYTHON="$AUDIT_DIR/.venv/Scripts/python.exe"
elif [ -f "$AUDIT_DIR/.venv/bin/python" ]; then
  PYTHON="$AUDIT_DIR/.venv/bin/python"
elif command -v python3 > /dev/null 2>&1; then
  PYTHON="python3"
elif command -v python > /dev/null 2>&1; then
  PYTHON="python"
elif command -v py > /dev/null 2>&1; then
  PYTHON="py"
else
  echo "Error: no python interpreter found (tried .venv, python3, python, py)" >&2
  exit 1
fi

OLLAMA="${OLLAMA_BIN:-ollama}"
# Read config via stdin so we don't have to pass MinGW paths through Windows Python
MODEL="$(cd "$AUDIT_DIR" && "$PYTHON" -c "import json; print(json.load(open('config.json'))['model'])")"
WATCHDOG_ENABLED="$(cd "$AUDIT_DIR" && "$PYTHON" -c "import json; print(str(json.load(open('config.json')).get('watchdog_enabled', True)).lower())")"

# CLI flag overrides config: caudit on --no-watchdog
for arg in "$@"; do
  if [ "$arg" = "--no-watchdog" ]; then
    WATCHDOG_ENABLED="false"
  fi
done

case "${1:-}" in
  on)
    # Start Ollama if not responding
    if ! curl -s --max-time 2 http://localhost:11434/api/tags > /dev/null 2>&1; then
      echo "Starting Ollama..."
      "$OLLAMA" serve &
      disown
      # Wait for Ollama to be ready
      for i in {1..15}; do
        if curl -s --max-time 2 http://localhost:11434/api/tags > /dev/null 2>&1; then
          break
        fi
        sleep 1
      done
    fi

    # Ensure model is available and warm it up (~60s cold load)
    echo "Ensuring $MODEL is available..."
    "$OLLAMA" pull "$MODEL"
    echo "Warming up model (first load takes ~60s)..."
    curl -s http://localhost:11434/api/generate -d "{\"model\":\"$MODEL\",\"prompt\":\"hello\",\"stream\":false,\"options\":{\"num_predict\":1}}" > /dev/null 2>&1
    echo "Model warm."

    # NOW activate — hook is a no-op until this file exists
    touch "$FLAG_FILE"

    if [ "$WATCHDOG_ENABLED" = "true" ]; then
      "$PYTHON" "$AUDIT_DIR/watchdog.py" &
      disown
      echo "Watchdog started (PID: $!)"
    else
      echo "Watchdog disabled (config.watchdog_enabled=false or --no-watchdog)."
    fi

    echo ""
    echo "Auto-audit active. Safe to leave Claude running."
    ;;

  off)
    # Remove flag file (watchdog will exit on next poll)
    rm -f "$FLAG_FILE"

    # Kill watchdog if running
    if [ -f "$LOCK_FILE" ]; then
      WATCHDOG_PID=$(cat "$LOCK_FILE" 2>/dev/null)
      if [ -n "$WATCHDOG_PID" ] && kill -0 "$WATCHDOG_PID" 2>/dev/null; then
        kill "$WATCHDOG_PID" 2>/dev/null || true
        echo "Watchdog stopped (PID: $WATCHDOG_PID)"
      fi
      rm -f "$LOCK_FILE"
    fi

    echo "Auto-audit off. Welcome back."
    echo ""

    # Show morning report
    "$PYTHON" "$AUDIT_DIR/morning_report.py"
    ;;

  status)
    if [ -f "$FLAG_FILE" ]; then
      echo "Auto-audit: ACTIVE"
      if [ -f "$LOCK_FILE" ]; then
        echo "Watchdog: running (PID: $(cat "$LOCK_FILE"))"
      elif [ "$WATCHDOG_ENABLED" = "true" ]; then
        echo "Watchdog: not running"
      else
        echo "Watchdog: disabled"
      fi
    else
      echo "Auto-audit: OFF"
    fi
    ;;

  report)
    "$PYTHON" "$AUDIT_DIR/morning_report.py" "${2:-}"
    ;;

  *)
    echo "Usage: caudit {on [--no-watchdog]|off|status|report [YYYY-MM-DD]}"
    exit 1
    ;;
esac
