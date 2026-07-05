# cPanel Deployment Guide — novaapi.novarex.co.tz

This guide walks through deploying NOVA GeoRisk Platform (a FastAPI/ASGI application) to a cPanel-hosted server for the domain **novaapi.novarex.co.tz**.

**Read this first**: cPanel's Python Application Manager is built on Phusion Passenger. Passenger has supported ASGI applications directly only since version **6.0.9**. Before following the primary path below, check your Passenger version (§0). If it's older, skip to **§9 "Alternative: reverse-proxied uvicorn"** — that path works on any cPanel host regardless of Passenger version and is the more universally reliable option.

---

## §0. Prerequisites Check

Via cPanel Terminal or SSH:
```bash
passenger -v          # need >= 6.0.9 for the primary (passenger_wsgi.py) path
python3.12 --version  # confirm Python 3.12 is available (pyproject.toml requires >=3.12)
```
If cPanel's "Setup Python App" only offers up to Python 3.10/3.11, **stop and confirm with your hosting provider** whether 3.12 can be enabled (CloudLinux's Python Selector / EasyApache) before proceeding — the codebase uses `enum.StrEnum`, `datetime.UTC`, and `typing.Self`, all introduced in Python 3.11, and the project's own compatibility contract targets 3.12+.

---

## §1. Create the PostgreSQL Database

In cPanel → **PostgreSQL Databases**:
1. Create a database, e.g. `novarex_georisk` (cPanel will prefix it with your account username, e.g. `cpaneluser_georisk`).
2. Create a database user, e.g. `novarex_geouser` (also auto-prefixed), with a strong generated password.
3. Add the user to the database with **ALL PRIVILEGES**.
4. Note the final prefixed names — you'll need them for `DATABASE_URL`.

If your cPanel account doesn't expose "PostgreSQL Databases" (some shared hosts only offer MySQL), you'll need either a VPS/dedicated plan with PostgreSQL enabled, or an externally-hosted PostgreSQL instance (e.g. a managed Postgres add-on) reachable from the cPanel server — `DATABASE_URL` accepts any reachable host, not just `localhost`.

**PostGIS and pgcrypto are NOT required — confirmed, not assumed.** This platform stores geometry as validated GeoJSON in JSONB, not native PostGIS columns (a deliberate Sprint 7 decision), and generates every ID application-side (`uuid.uuid4()`), never via `pgcrypto`'s `gen_random_uuid()`. A stock PostgreSQL instance with **no extensions installed at all** is sufficient. `0000_baseline.py` attempts to enable both anyway (harmless if your host happens to have them, e.g. for a future sprint that might want them) but treats each as best-effort — the migration was patched after a real shared-hosting deployment failed with `extension "postgis" is not available: Could not open extension control file ... postgis.control`. If your PostgreSQL install lacks these `.control` files (common on shared/managed hosting where contrib extensions require the DBA/host to install them at the OS level), migrations will log a warning for each and continue normally — this is expected, not an error to chase down. See `MIGRATION_EXTENSION_FIX_REPORT.md` for the full trace and verification.

## §2. Upload the Application

Via cPanel File Manager, Git Version Control, or `scp`/`rsync` over SSH, place the full project (this ZIP's contents) at, e.g., `~/georisk-platform/` (NOT inside `public_html/` — cPanel's Python App Manager serves the app via Passenger regardless of where the code lives, and keeping it outside the web-servable document root avoids ever accidentally exposing source files).

## §3. Create the Python Application

cPanel → **Setup Python App** → **Create Application**:
- **Python version**: 3.12 (see §0)
- **Application root**: `georisk-platform` (the directory from §2, relative to your home directory)
- **Application URL**: `novaapi.novarex.co.tz` (see §5 for domain mapping if this subdomain doesn't exist yet)
- **Application startup file**: `passenger_wsgi.py`
- **Application Entry point**: `application`

Click **Create**. cPanel provisions a dedicated virtualenv and shows you its activation command (something like `source /home/CPANELUSER/virtualenv/georisk-platform/3.12/bin/activate`) — note this path; `deploy.sh` tries to auto-detect it but can be overridden with `PYTHON_VENV=<path> ./deploy.sh` if auto-detection picks the wrong one.

## §4. Configure Environment Variables

Two options — pick one:
- **cPanel's Python App UI** has an "Environment variables" section — you can enter each variable there instead of a `.env` file. This keeps secrets out of the filesystem entirely.
- **Or**, copy `.env.production.example` to `.env` inside the application root and fill in real values (this is what `deploy.sh` and `passenger_wsgi.py` expect by default via pydantic-settings' `env_file=".env"`).

At minimum, set:
```
ENVIRONMENT=production
DATABASE_URL=postgresql+asyncpg://<prefixed_user>:<password>@localhost:5432/<prefixed_db>
JWT_SECRET_KEY=<output of: python3 -c "import secrets; print(secrets.token_urlsafe(64))">
CORS_ALLOWED_ORIGINS=https://novarex.co.tz,https://www.novarex.co.tz
```
See `.env.production.example` for the complete, commented list (Redis, SMTP, USGS/NASA/Copernicus, Google Earth Engine — all optional, all fail honestly if left unset).

**Redis note**: many shared cPanel hosts do not provide Redis. `REDIS_URL`/`REDIS_CACHE_URL`/`REDIS_RATELIMIT_URL` are declared Settings, but before assuming the app runs fine without Redis, check `/health/ready`'s behavior in your specific environment (it pings Redis and returns `503` if unreachable) — if Redis is unavailable, either provision it (many cPanel/WHM hosts offer it as an addon, or run `redis-server` yourself if you have shell access and a persistent process allowance) or confirm with the team whether `/health/ready`'s Redis check should be relaxed for this deployment.

## §5. Domain / Subdomain Mapping

If `novaapi.novarex.co.tz` is a new subdomain:
1. cPanel → **Domains** (or **Subdomains** on older cPanel themes) → create `novaapi` as a subdomain of `novarex.co.tz`.
2. Point its document root at the application root you chose in §3 (cPanel's Python App setup usually does this automatically when you specify the Application URL there — verify under **Domains** that `novaapi.novarex.co.tz` resolves to the right document root).
3. Ensure DNS (an A record or CNAME for `novaapi`) is configured, either in cPanel's **Zone Editor** if this account manages the zone, or with whoever manages `novarex.co.tz`'s DNS otherwise.

## §6. SSL Configuration

cPanel → **SSL/TLS Status** (or **AutoSSL**):
1. Confirm `novaapi.novarex.co.tz` is listed and run **AutoSSL** (free Let's Encrypt-backed certificate) if not already issued.
2. If AutoSSL isn't available on this hosting plan, use **SSL/TLS → Manage SSL sites** to install a certificate manually (self-purchased or another CA).
3. Force HTTPS: cPanel → **Domains** → toggle "Force HTTPS Redirect" for `novaapi.novarex.co.tz`, or add the redirect rule in `.htaccess` if the Python App's reverse-proxy config doesn't already do this (Passenger-managed apps on cPanel typically get an auto-generated `.htaccess` in the document root — check it after app creation).
4. Once SSL is live, double-check `CORS_ALLOWED_ORIGINS` uses `https://` (not `http://`) for every listed origin.

## §7. First Deployment

Via SSH/Terminal:
```bash
cd ~/georisk-platform
cp .env.production.example .env
nano .env   # fill in real values from §4
chmod +x deploy.sh
./deploy.sh
```
This installs dependencies into the cPanel-managed virtualenv, runs `alembic upgrade head` (applies all 17 migrations, `0000_baseline` → `0016_remote_sensing`), touches Passenger's restart file, and runs a health check against `https://novaapi.novarex.co.tz/health/ready`. Confirm it prints `Health check PASSED`.

## §8. Restart Procedures

- **Routine restart** (after a config change, not a full redeploy): `touch ~/georisk-platform/tmp/restart.txt` — Passenger watches this file and reloads the app on its next request.
- **Full redeploy** (new code): re-upload changed files, then re-run `./deploy.sh` (or `./deploy.sh --skip-install` if `requirements.txt` didn't change, to skip the pip install step and speed things up).
- **Force-kill if the app is stuck**: cPanel → **Setup Python App** → find the application → **Restart**. This is a harder restart than touching `restart.txt` and is the right tool if the app appears hung rather than just needing to pick up new code.

## §9. Alternative: Reverse-Proxied Uvicorn (if Passenger < 6.0.9)

If §0's Passenger version check came back too old, `passenger_wsgi.py` will not work — Passenger will attempt to call the app the plain-WSGI way (2 positional args) and every request will error. Use this instead:

1. Do **not** set `passenger_wsgi.py` as the app's startup file in cPanel's Python App UI — or better, delete/disable the cPanel Python App entry entirely for this domain and handle process management yourself.
2. Run the app as a persistent background process via `startup.py`:
   ```bash
   source ~/virtualenv/georisk-platform/3.12/bin/activate
   cd ~/georisk-platform
   PORT=8001 nohup python3 startup.py > ~/georisk-platform/logs/uvicorn.log 2>&1 &
   ```
   For a durable setup (survives reboots), use `supervisord` if your hosting plan allows a persistent user-level process manager, or ask your host to add a `systemd --user` unit — most shared cPanel plans do **not** allow arbitrary long-running background processes outside of what cPanel's own Application Manager supervises, so **confirm this is permitted on your specific plan** before relying on it; a VPS/dedicated cPanel license gives you full control here, a shared reseller plan may not.
3. Configure a reverse proxy from `novaapi.novarex.co.tz` to `127.0.0.1:8001`. On an Apache-fronted cPanel server, add to the subdomain's `.htaccess` (via **Include Editor** in WHM, or File Manager if you have direct `.htaccess` access):
   ```apache
   RewriteEngine On
   RewriteCond %{HTTP:Upgrade} !=websocket [NC]
   RewriteRule /(.*) http://127.0.0.1:8001/$1 [P,L]
   ```
   (Requires `mod_proxy`/`mod_proxy_http` enabled in WHM → Apache Configuration — ask your host if you don't have WHM access yourself.)
4. Health-check and SSL steps (§6-§7) are unchanged — SSL terminates at Apache/Nginx either way; only the app-process-management differs.

## §10. Cron Jobs

cPanel → **Cron Jobs**. No cron job is currently required for core functionality — there is no scheduled batch job in this codebase (Data Acquisition's `AcquisitionJob` is triggered on-demand via its `actions/execute` endpoint, not a scheduler). Recommended crons for operational health, not correctness:

```cron
# Nightly database backup (see §11) at 02:00 server time
0 2 * * * /home/CPANELUSER/georisk-platform/scripts/backup_db.sh >> /home/CPANELUSER/georisk-platform/logs/backup.log 2>&1

# Hourly health check, alert if down (adjust to your monitoring tool of choice)
0 * * * * curl -sf https://novaapi.novarex.co.tz/health/ready > /dev/null || echo "georisk-api unhealthy at $(date)" | mail -s "novaapi health check failed" you@novarex.co.tz
```

## §11. Backup Procedures

**Database** — cPanel's PostgreSQL databases are included in cPanel's own account-level backup (Backup Wizard) if your host has that enabled; do not rely on that alone. Add an explicit dump:
```bash
#!/usr/bin/env bash
# scripts/backup_db.sh — create this file if you want the cron above to work;
# it is a thin wrapper, not part of the application itself.
set -euo pipefail
source ~/georisk-platform/.env
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR=~/backups/georisk
mkdir -p "$BACKUP_DIR"
pg_dump "$DATABASE_URL" --format=custom --file="$BACKUP_DIR/georisk_${TIMESTAMP}.dump"
find "$BACKUP_DIR" -name "*.dump" -mtime +30 -delete   # keep 30 days
```
Note: `pg_dump` needs the plain `postgresql://` scheme, not `postgresql+asyncpg://` — strip the `+asyncpg` when passing `DATABASE_URL` to `pg_dump`, or maintain a second plain connection string for backup tooling.

**Restore** (verify this actually works before you need it for real):
```bash
pg_restore --clean --if-exists -d "<plain_postgresql_url>" "$BACKUP_DIR/georisk_<timestamp>.dump"
```

**Application code** — kept in version control (git) separately from this deployment; the ZIP release itself (`NOVA_GEORISK_RELEASE_v1.0.zip`) is the point-in-time artifact for this release and should be retained alongside the release notes.

---

## Quick Reference

| Task | Command |
|---|---|
| Deploy / redeploy | `./deploy.sh` |
| Redeploy, skip pip install | `./deploy.sh --skip-install` |
| Apply new migrations only | `PYTHONPATH=src alembic upgrade head` |
| Check migration status | `PYTHONPATH=src alembic current` |
| Restart (soft) | `touch tmp/restart.txt` |
| Restart (hard) | cPanel → Setup Python App → Restart |
| Health check | `curl https://novaapi.novarex.co.tz/health/ready` |
| Tail logs (Passenger path) | check cPanel's Python App page → "Log file" link, or `~/georisk-platform/logs/` if `LOG_LEVEL`/log file redirection is configured |
