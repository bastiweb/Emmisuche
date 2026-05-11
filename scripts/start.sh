#!/bin/sh
set -e

run_scheduled_reindex_loop() {
  echo "Scheduled reindex enabled: runs daily at 01:00 (${TZ:-container local time})."
  while true; do
    now_epoch="$(date +%s)"
    next_epoch="$(date -d "today 01:00:00" +%s)"
    if [ "$next_epoch" -le "$now_epoch" ]; then
      next_epoch="$(date -d "tomorrow 01:00:00" +%s)"
    fi

    sleep_seconds=$((next_epoch - now_epoch))
    next_run_human="$(date -d "@$next_epoch" +"%Y-%m-%d %H:%M:%S %Z")"
    echo "Next scheduled reindex at ${next_run_human}."
    sleep "$sleep_seconds"

    echo "Running scheduled reindex..."
    if ! python scripts/manage.py reindex; then
      echo "Scheduled reindex failed; will retry at next 01:00 run."
    fi
  done
}

echo "Initializing database..."
python scripts/manage.py init-db

if [ "${AUTO_REINDEX_ON_START:-false}" = "true" ]; then
  LIMIT="${AUTO_REINDEX_LIMIT:-200}"
  echo "Running startup reindex (limit=${LIMIT})..."
  if ! python scripts/manage.py reindex --limit "${LIMIT}"; then
    echo "Startup reindex failed; continuing to start web server."
  fi
fi

run_scheduled_reindex_loop &
SCHEDULER_PID="$!"

cleanup() {
  if [ -n "${SCHEDULER_PID:-}" ]; then
    kill "$SCHEDULER_PID" 2>/dev/null || true
  fi
}

trap cleanup INT TERM EXIT

echo "Starting web server..."
uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}" &
WEB_PID="$!"

wait "$WEB_PID"
exit "$?"
