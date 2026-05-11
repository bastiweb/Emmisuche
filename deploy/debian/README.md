# Debian Deployment

This folder contains a non-Docker deployment for a normal Debian server. It keeps
the application code in `/opt/emmisuche`, configuration in `/etc/emmisuche`,
SQLite state in `/var/lib/emmisuche`, and service logs in the system journal.

## Included files

- `install.sh` installs system packages, creates a Python virtual environment,
  copies the app to `/opt/emmisuche`, installs the systemd service, and installs
  the nightly reindex cron.
- `emmisuche.service` runs the FastAPI app as a dedicated unprivileged user with
  systemd hardening.
- `emmisuche.env.example` is the production environment template.
- `emmisuche-reindex.sh` is the cron-safe reindex wrapper.
- `emmisuche-reindex.cron` runs the wrapper every night at 01:00.
- `nginx-emmisuche.conf` is an optional reverse-proxy example with security
  headers.

## Install

Run from the repository root on Debian:

```bash
sudo deploy/debian/install.sh
```

Then review the environment file:

```bash
sudo editor /etc/emmisuche/emmisuche.env
sudo systemctl restart emmisuche
```

Keep quotes around values that contain spaces or shell punctuation because the
same file is read by systemd, Python, and the cron wrapper.

Check service status:

```bash
systemctl status emmisuche
journalctl -u emmisuche -f
```

The app listens on `127.0.0.1:8910` by default. Put Nginx, Caddy, or another TLS
terminating reverse proxy in front of it for internet exposure.

## Nightly Reindex

The installer writes `/etc/cron.d/emmisuche-reindex`:

```cron
0 1 * * * emmisuche /usr/local/sbin/emmisuche-reindex
```

The wrapper uses `flock` so a slow reindex cannot overlap with the next run.
Logs are appended to `/var/log/emmisuche/reindex.log`.

Run it manually:

```bash
sudo -u emmisuche /usr/local/sbin/emmisuche-reindex
```

## Security Defaults

The deployment uses these security controls:

- dedicated `emmisuche` system user with no login shell
- app code owned by root under `/opt/emmisuche`
- writable state restricted to `/var/lib/emmisuche` and `/var/log/emmisuche`
- environment file installed as `0640 root:emmisuche`
- systemd sandboxing: `NoNewPrivileges`, `ProtectSystem=strict`,
  `ProtectHome=true`, private `/tmp`, empty Linux capability set, native syscall
  architecture, and a service-oriented syscall filter
- localhost-only app bind by default, intended to sit behind a TLS reverse proxy
- reverse proxy example includes common browser security headers

## Optional Nginx

Install Nginx and copy the example:

```bash
sudo apt-get install nginx
sudo cp deploy/debian/nginx-emmisuche.conf /etc/nginx/sites-available/emmisuche
sudo ln -s /etc/nginx/sites-available/emmisuche /etc/nginx/sites-enabled/emmisuche
sudo nginx -t
sudo systemctl reload nginx
```

Edit `server_name` and TLS settings before exposing the site publicly. Use
Let's Encrypt or another trusted certificate provider for HTTPS.

## Update an Existing Install

Re-run the installer from a fresh checkout:

```bash
sudo deploy/debian/install.sh
sudo systemctl restart emmisuche
```

The installer preserves `/etc/emmisuche/emmisuche.env` and
`/var/lib/emmisuche/recipes.db`.
