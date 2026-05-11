#!/usr/bin/env bash
set -Eeuo pipefail

APP_USER="${APP_USER:-emmisuche}"
APP_GROUP="${APP_GROUP:-emmisuche}"
APP_DIR="${APP_DIR:-/opt/emmisuche}"
CONFIG_DIR="${CONFIG_DIR:-/etc/emmisuche}"
STATE_DIR="${STATE_DIR:-/var/lib/emmisuche}"
LOG_DIR="${LOG_DIR:-/var/log/emmisuche}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this installer as root, for example: sudo deploy/debian/install.sh" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y --no-install-recommends \
  bash \
  ca-certificates \
  cron \
  curl \
  build-essential \
  libxml2-dev \
  libxslt1-dev \
  python3 \
  python3-pip \
  python3-venv \
  rsync

if ! getent group "${APP_GROUP}" >/dev/null; then
  addgroup --system "${APP_GROUP}"
fi

if ! id -u "${APP_USER}" >/dev/null 2>&1; then
  adduser \
    --system \
    --ingroup "${APP_GROUP}" \
    --home "${STATE_DIR}" \
    --no-create-home \
    --shell /usr/sbin/nologin \
    "${APP_USER}"
fi

install -d -o root -g root -m 0755 "${APP_DIR}"
rsync -a --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude 'data' \
  "${REPO_DIR}/" "${APP_DIR}/"

python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/python" -m pip install --upgrade pip wheel
"${APP_DIR}/.venv/bin/pip" install --requirement "${APP_DIR}/requirements.txt"

chown -R root:root "${APP_DIR}"
find "${APP_DIR}" -type d -exec chmod 0755 {} +
find "${APP_DIR}" -type f -exec chmod 0644 {} +
find "${APP_DIR}/.venv/bin" -type f -exec chmod 0755 {} +
chmod 0755 "${APP_DIR}/scripts/start.sh" "${APP_DIR}/deploy/debian/install.sh" "${APP_DIR}/deploy/debian/emmisuche-reindex.sh"
chmod -R go-w "${APP_DIR}"

install -d -o root -g "${APP_GROUP}" -m 0750 "${CONFIG_DIR}"
install -d -o "${APP_USER}" -g "${APP_GROUP}" -m 0750 "${STATE_DIR}" "${LOG_DIR}"

if [[ ! -f "${CONFIG_DIR}/emmisuche.env" ]]; then
  install -o root -g "${APP_GROUP}" -m 0640 \
    "${APP_DIR}/deploy/debian/emmisuche.env.example" \
    "${CONFIG_DIR}/emmisuche.env"
else
  chown root:"${APP_GROUP}" "${CONFIG_DIR}/emmisuche.env"
  chmod 0640 "${CONFIG_DIR}/emmisuche.env"
fi

install -o root -g root -m 0644 \
  "${APP_DIR}/deploy/debian/emmisuche.service" \
  /etc/systemd/system/emmisuche.service

install -o root -g root -m 0755 \
  "${APP_DIR}/deploy/debian/emmisuche-reindex.sh" \
  /usr/local/sbin/emmisuche-reindex

install -o root -g root -m 0644 \
  "${APP_DIR}/deploy/debian/emmisuche-reindex.cron" \
  /etc/cron.d/emmisuche-reindex

systemctl daemon-reload
systemctl enable --now emmisuche.service
systemctl restart cron.service

echo "Installed Emmi recipe search without Docker."
echo "Review ${CONFIG_DIR}/emmisuche.env, then run: systemctl restart emmisuche"
echo "Nightly reindex is installed at /etc/cron.d/emmisuche-reindex."
