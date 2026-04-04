#!/bin/bash
set -e

NIGHTMODE_DIR="M:/.claude-liz/nightmode"
FLAG_FILE="M:/.claude-liz/nightmode.active"
LOCK_FILE="M:/.claude-liz/watchdog.lock"
PYTHON="M:/.claude-liz/nightmode/.venv/Scripts/python.exe"
OLLAMA="M:/Ollama/ollama.exe"
MODEL="qwen2.5-coder:3b"

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

    # Start watchdog in background
    "$PYTHON" "$NIGHTMODE_DIR/watchdog.py" &
    disown
    echo "Watchdog started (PID: $!)"

    echo ""
    echo "Night mode active. Safe to sleep."
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

    echo "Night mode off. Welcome back."
    echo ""

    # Show morning report
    "$PYTHON" "$NIGHTMODE_DIR/morning_report.py"
    ;;

  status)
    if [ -f "$FLAG_FILE" ]; then
      echo "Night mode: ACTIVE"
      if [ -f "$LOCK_FILE" ]; then
        echo "Watchdog: running (PID: $(cat "$LOCK_FILE"))"
      else
        echo "Watchdog: not running"
      fi
    else
      echo "Night mode: OFF"
    fi
    ;;

  report)
    "$PYTHON" "$NIGHTMODE_DIR/morning_report.py" "${2:-}"
    ;;

  *)
    echo "Usage: nightmode {on|off|status|report [YYYY-MM-DD]}"
    exit 1
    ;;
esac
