#!/bin/sh
set -e

echo "Initializing database..."
python scripts/manage.py init-db

if [ "${AUTO_REINDEX_ON_START:-true}" = "true" ]; then
  LIMIT="${AUTO_REINDEX_LIMIT:-200}"
  echo "Running startup reindex (limit=${LIMIT})..."
  if ! python scripts/manage.py reindex --limit "${LIMIT}"; then
    echo "Startup reindex failed; continuing to start web server."
  fi
fi

echo "Starting web server..."
exec uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"

