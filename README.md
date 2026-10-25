# Attendance Hub — ZKTeco / MB360 Plus (Django + Tailwind + htmx)

Collects punches from ZKTeco devices two ways, stores them locally, applies day/night/rotating shifts and exports to Excel/CSV.

| Mode | Who connects | Needs |
|---|---|---|
| **ADMS (push)** | device → this server (HTTP, `/iclock/*`) | the server reachable by the device; nothing to forward on the device side |
| **Pull** | this server → device (TCP 4370, pyzk) | the device reachable by IP + a port forward |

## Quick start (development)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DJANGO_DEBUG=1                      # dev only; production refuses to start without a real SECRET_KEY/ALLOWED_HOSTS
python manage.py migrate && python manage.py createsuperuser
python manage.py runserver 0.0.0.0:8000
```
No hardware? **+ Demo device** (pull simulator) and `python manage.py simulate_adms --push3 --poll 60` (fake ADMS device).

## Production
```bash
cp .env.example .env     # set DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS (domain AND server IP), DJANGO_TIME_ZONE
docker compose up -d --build
docker compose exec app python manage.py createsuperuser
```
The image builds Tailwind + htmx locally (no CDNs), runs gunicorn (WhiteNoise for static), migrates on start, exposes `/healthz`.
Without Docker: `npm install && npm run build`, `pip install -r requirements.txt`, `collectstatic`, then
`gunicorn config.wsgi -c gunicorn.conf.py`.

**Checklist**
- `python manage.py check --deploy` should be clean (`DJANGO_HTTPS=1`, `DJANGO_BEHIND_PROXY=1` when behind a proxy).
- Serve the **UI over HTTPS** and leave `/iclock/*` on plain HTTP (device firmware usually can't do TLS): see `deploy/Caddyfile.example`.
- `ADMS_ALLOWED_NETWORKS` restricts device traffic to your sites' addresses; unknown serials are refused until you click **Register**.
- Back up: `python manage.py backup_db --to /backups --keep 14` (cron it). Postgres: `DB_ENGINE=postgres` + `pg_dump`.
- SQLite (WAL) suits tens of devices; use PostgreSQL beyond that. Multi-worker: set `DJANGO_CACHE_DIR` so rate limits are shared.
- Device Comm Keys are stored in the database in plain text: protect the DB file and backups.
- Biometrics: by default the device is told it may upload templates/photos; they are discarded unread. Prefer the per-device
  profile **Minimal** once your device is confirmed working.
- Tests: `DJANGO_DEBUG=1 python manage.py test`; Django-free: `python -m unittest attendance.test_services attendance.test_adms attendance.test_shifts`.

## Setting up an ADMS device (MB360 Plus and similar)
1. Device: **Menu → Comm. → Cloud Server Setting**: server address = public IP/domain, port = the app's port (HTTP).
2. The device appears in the yellow **Unregistered device** box: **Register**. Its stored punches then upload.
3. **Details** shows last seen and stored punches; buttons request device info, fetch user names, or re-upload everything.
4. Nothing arrives? Open **Device activity**. Edit the device and try another **Data the device uploads** profile
   (Standard → Minimal → Legacy numeric). A line the server can't read is answered 400 so the device keeps it.
5. If every punch shows the same odd state (some "Plus" firmware always sends one fixed value), tick
   **Device doesn't record in/out state**. Shift reports never depend on it.

## Compatibility (be realistic)
Nothing here has been run against a physical device by me; the protocol follows ZKTeco's published PUSH SDK description and
open-source implementations. Confidence:

| Device / firmware | ADMS push | Pull (pyzk) |
|---|---|---|
| Classic push 2.x terminals (K40, F18, iClock, MB160/360/460 families) | expected to work | expected to work |
| MB360 **Plus** and other newer terminals | expected (2.x flow; 3.x registry/config answered best-effort) | likely, firmware dependent |
| 4G / Wi-Fi units behind carrier NAT | works (device dials out) | not reachable |
| Access-control panels (C3, inBio) | not supported | not supported |

Use **Test/Details** and **Device activity** as the bench checklist: handshake seen, punch accepted (`OK`), name list received,
clock difference sane, shift report matches reality.

## Shifts, reports, security notes
See the in-app Shifts card. Matching rule: a punch belongs to the shift whose window contains it; first = in, last = out.
Set `DJANGO_TIME_ZONE` to the devices' zone so *Absent* uses the right "now". The UI requires login; device endpoints don't
(ADMS has no authentication besides the serial), hence the allow-list, rate limit and register-first design.
"# attendance" 
