#!/usr/bin/env bash
# Cron wrapper for the daily TikTok Qur'an bot.
# Resolves its own location, activates a local virtualenv if present, runs the
# pipeline, and appends output to a dated log. Cron gets a minimal environment,
# so we set an explicit PATH that includes common ffmpeg locations.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

export PATH="/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:$PATH"

# Activate a virtualenv if one exists (.venv or venv).
if [ -f "$PROJECT_DIR/.venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$PROJECT_DIR/.venv/bin/activate"
elif [ -f "$PROJECT_DIR/venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$PROJECT_DIR/venv/bin/activate"
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/run-$(date +%Y%m%d).log"

echo "=== $(date '+%Y-%m-%d %H:%M:%S') starting daily run ===" >> "$LOG_FILE"
"$PYTHON_BIN" main.py "$@" >> "$LOG_FILE" 2>&1
STATUS=$?
echo "=== $(date '+%Y-%m-%d %H:%M:%S') finished with exit $STATUS ===" >> "$LOG_FILE"
exit $STATUS
