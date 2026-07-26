# journal.md – Bau-Journal

---

## 2026-07-26 – Meilenstein 1: Fundament

### Was gebaut wurde

Vollständiger Docker-Stack `familienportal` auf `home02` (10.0.0.100):

- **portal**: Python 3.12 + Flask 3 + Gunicorn (1 Worker, 4 Threads, WAL-SQLite)
  - Token-System (`/p/<token>` persönliche Startseite, `/` Denied/Landing)
  - ✨ Verbesserungswünsche (`POST /wunsch`, gespeichert in `wuensche`-Tabelle)
  - Mobil-First: safe-area-insets, 100dvh, große Tippziele
  - PWA: Manifest + Icons (generiert im Dockerfile, kein Pillow)
  - `manage.py`: CLI für createadmin / adduser / addapp / grant / listusers / listwuensche
- **caddy**: TLS-Terminierung, Zertifikat aus Volume `certbot-domainoffensive_iobroker-certs`
  (subpath `portal.16schwaben.de/`, Docker 29.6.2 unterstützt subpath)
  Admin-API an 172.30.0.10:2019 (nur internes Bridge-Netz)
- **util**: Python-Scheduler – stündliche SQLite-Snapshots + täglicher Zertifikats-Watcher

Netz: internes Bridge `familienportal_intern` (172.30.0.0/24), caddy zusätzlich
im macvlan `mvl` auf **10.0.0.200** (von Andi bestätigt).

Erster Admin-User `Andi` angelegt.

### Testergebnisse

- HTTPS-Aufruf von Andis Rechner: ✅ HTTP 200, TLS valid bis 24.10.2026
- Startseite `/p/<token>`: ✅ Name, Farbe, safe-area, Manifest, ⌂, ✨
- ✨ Wunsch-Endpoint: ✅ Gespeichert + über manage.py sichtbar
- Zertifikats-Watcher: ✅ Caddy-Reload via Admin-API (Status 200)
- Snapshots: ✅ in `/data/snapshots/`
- Healthchecks: ✅ alle drei Container healthy/up

### Stolpersteine

1. **Dockerfile: mehrzeiliges CMD/RUN** – Docker 26 parst keine Zeilenumbrüche in
   `CMD`-Anweisungen und interpretiert Folgezeilen als neue Instruktionen.
   Lösung: CMD in einer Zeile, Python-Hilfsskript (`generate_icons.py`) ausgelagert.

2. **Caddy Admin-API: 403 Forbidden** – Caddy prüft den HTTP `Host`-Header gegen
   die konfigurierte Bind-Adresse. Anfrage an `http://caddy:2019` liefert
   `"host not allowed: caddy:2019"`. Lösung: URL direkt als IP `http://172.30.0.10:2019`.

3. **Gunicorn 26 Control Socket** (`/.gunicorn`): Gunicorn 26 erstellt einen
   Control-Socket für Arbiter↔Worker-IPC unter `os.sep + '.gunicorn'` –
   hardcoded, nicht konfigurierbar. Als uid=1001 kein Schreibrecht auf `/`.
   Nicht-fatal (App läuft, healthcheck grün). Bleibt als Known Issue.

4. **Teile-Module: Python-Identifier-Kollision** – Dateinamen wie `00_kern.py`
   können nicht mit `from teile.00_kern import ...` importiert werden (ungültige
   Python-Syntax). Lösung: `teile/__init__.py` registriert das Modul via
   `importlib` als `teile.kern` in `sys.modules`.

### Auslieferungspaket

`deploy/portal-v1.tar.gz` – enthält src/, util/, docker-compose.yml, Caddyfile, .env.example

---

*Nächster Schritt: Meilenstein 2 – Zentrale Dienste (Admin, Todos, Werkstatt, Geholfen)*
