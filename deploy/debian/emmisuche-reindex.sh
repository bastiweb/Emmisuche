#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/emmisuche}"
ENV_FILE="${ENV_FILE:-/etc/emmisuche/emmisuche.env}"
LOG_FILE="${LOG_FILE:-/var/log/emmisuche/reindex.log}"
LOCK_FILE="${LOCK_FILE:-/var/lib/emmisuche/reindex.lock}"

umask 027

if [[ -r "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
  set +a
fi

mkdir -p "$(dirname "${LOG_FILE}")" "$(dirname "${LOCK_FILE}")"
cd "${APP_DIR}"

{
  printf '\n[%s] Starting nightly reindex\n' "$(date --iso-8601=seconds)"
  flock -n "${LOCK_FILE}" "${APP_DIR}/.venv/bin/python" "${APP_DIR}/scripts/manage.py" reindex
  printf '[%s] Nightly reindex finished\n' "$(date --iso-8601=seconds)"
} >> "${LOG_FILE}" 2>&1
