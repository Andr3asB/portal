# server.md – Aktueller Systemzustand

*Letzte Aktualisierung: 2026-07-26 (Meilenstein 2 abgeschlossen)*

## Host

| Eigenschaft | Wert |
|-------------|------|
| Hostname | `home02` |
| IP | `10.0.0.100` |
| SSH | `ssh -p 2222 claude@10.0.0.100` |
| Projektverzeichnis | `/srv/familienportal/` |
| User `claude` | uid=1001, gid=1001, Gruppe `docker` |

## Stack `familienportal`

| Container | Image / Build | IP | Status |
|-----------|---------------|----|--------|
| `portal` | `familienportal-portal` (eigenes Build) | nur intern (172.30.x.x) | ✅ healthy |
| `caddy` | `caddy:2-alpine` | intern 172.30.0.10, macvlan **10.0.0.200** | ✅ healthy |
| `util` | `familienportal-util` (eigenes Build) | nur intern | ✅ up |

### Netzwerk

| Netz | Typ | Details |
|------|-----|---------|
| `familienportal_intern` | Bridge | Subnet 172.30.0.0/24 |
| `mvl` | macvlan (external) | Parent `eno1`, Bereich 10.0.0.192/26 |

Caddy hat statische IP 172.30.0.10 (intern, für Admin-API) + 10.0.0.200 (macvlan, für LAN).
Portal und util hängen ausschließlich im internen Bridge-Netz.

### Volumes

| Volume | Typ | Inhalt |
|--------|-----|--------|
| `/srv/familienportal/data` | Bind-Mount | SQLite DB, Snapshots |
| `certbot-domainoffensive_iobroker-certs` | extern (read-only) | TLS-Zertifikate, Subpath `portal.16schwaben.de/` |
| `familienportal_caddy_data` | named | Caddy interne Daten |

### Zertifikat

- Datei: `/certs/fullchain.pem` + `/certs/privkey.pem` (EC P-256)
- Volume: `certbot-domainoffensive_iobroker-certs`, Subpath `portal.16schwaben.de/`
- Docker unterstützt `subpath` (Version 29.6.2) → wird genutzt
- Gültig bis: 24.10.2026 (Certbot erneuert automatisch)
- Caddy Admin-API: `http://172.30.0.10:2019` (nur internes Netz – IP-Adresse, nicht Hostname)

## Caddy Admin-API

Bind-Adresse: `172.30.0.10:2019` (nur Bridge-Netz, nicht auf macvlan-IP 10.0.0.200).
Zugriff von außen: nicht möglich. util erreicht sie direkt via IP.

**Wichtig:** Anfragen müssen `http://172.30.0.10:2019` als URL benutzen (nicht `http://caddy:2019`),
weil Caddy den Host-Header gegen die Bind-Adresse prüft.

## Umgebungsvariablen (.env auf dem Server)

Datei: `/srv/familienportal/.env` (nicht im Repo, nicht in Git)

```
UID=1001
GID=1001
SECRET_KEY=<zufälliger Hex-Key, 32 Bytes>
GUNICORN_RUN_DIR=/tmp
```

## Code-Struktur (src/)

```
app.py               – Flask-App, lädt nummerierte Module aus teile/ automatisch
manage.py            – CLI: createadmin, adduser, addapp, grant, listusers,
                       listwuensche, listtodos, wunsch_erledigt, backlog
teile/
  __init__.py        – registriert 00_kern als teile.kern
  00_kern.py         – DB-Schema, get_db()/new_db(), grant(), new_token(),
                       push_send()-Stub, /health, _init_db()
  01_start_token.py  – / (Landing), /p/<token> (Startseite)
  02_werkstatt.py    – POST /wunsch (JSON, identifiziert Nutzer über Token)
  03_admin.py        – /a/admin/<token>/ Admin-Bereich: Nutzer, Grants, QR
  04_todo.py         – /a/todo/<token>/ Aufgabenliste; todos_neu() öffentlich
  05_werkstatt_app.py – /a/werkstatt/<token>/ Wunschliste (Admin: erledigt/löschen)
  06_geholfen.py     – /a/geholfen/<token>/ Tipp-Grid + Übersicht + Aufgaben
  templates/
    base.html               – Grundlayout: safe-area, ⌂ + ✨ Bottom-Bar
    startseite.html         – Persönliche Startseite mit App-Kacheln
    denied.html             – Zugang verweigert / Landing ohne Token
    admin.html              – Nutzerverwaltung, Grant-Chips, QR-Modal
    admin_user_form.html    – Nutzer anlegen/bearbeiten (Farbe, Admin-Flag)
    todo.html               – Aufgabenliste (neu, zuweisen, erledigen)
    werkstatt_app.html      – Wunschliste mit Admin-Aktionen
    geholfen.html           – Tipp-Grid (Fetch-AJAX), Ticker
    geholfen_uebersicht.html – 7-Tage-Statistik, Punkte pro Nutzer
    geholfen_aufgaben.html  – Aufgaben verwalten (hinzufügen, deaktivieren)
static/
  manifest.json      – PWA-Manifest
  icon-192.png       – Generiert im Dockerfile (solid blue #4a90d9)
  icon-512.png
```

## Datenbankschema (SQLite, WAL)

| Tabelle | Inhalt |
|---------|--------|
| `users` | id, name, farbe, is_admin, ki_key |
| `apps` | id, slug, name, emoji, beschreibung |
| `grants` | id, user_id, app_id, token (UNIQUE pro user+app) |
| `push_abos` | id, user_id, endpoint, p256dh, auth, geraet |
| `wuensche` | id, text, user_id, app_slug, erstellt, erledigt |
| `todos` | id, inhalt, erstellt_von, zugewiesen_an, privat, erledigt, erledigt_am, erstellt |
| `geholfen_aufgaben` | id, name, emoji, gewichtung, aktiv |
| `geholfen_eintraege` | id, aufgabe_id, user_id, zeitstempel |

App `slug='home'` = persönliche Startseite. URL-Schema: `/p/<token>`.
Andere Apps: `/a/<slug>/<token>/`.

## App-Slugs (Core)

| Slug | Name | Emoji | Beschreibung |
|------|------|-------|--------------|
| `home` | Portal | 🏠 | Persönliche Startseite |
| `admin` | Verwaltung | ⚙️ | Nutzerverwaltung, Grants |
| `todo` | Todos | ✅ | Aufgabenliste |
| `werkstatt` | Werkstatt | 💡 | Verbesserungswünsche |
| `geholfen` | Geholfen | 🙋 | Geholfen-Protokoll |

## Nutzer (Stand 2026-07-26)

| ID | Name | Farbe | Admin | Startseiten-URL |
|----|------|-------|-------|-----------------|
| 1 | Andi | #3498db | ✅ | `https://portal.16schwaben.de/p/l71US-2m8bVk004JUERd-pVs` |
| 2 | Simone | (unbekannt) | – | (über Admin-App abrufbar) |

Weitere Familienmitglieder werden über `manage.py adduser` oder den Admin-Bereich (`/a/admin/`) angelegt.

## util-Aufgaben

| Aufgabe | Zeitplan | Details |
|---------|----------|---------|
| SQLite-Snapshot | stündlich | 24 Slots in `/data/snapshots/` |
| Zertifikats-Watcher | täglich 04:00 + einmalig beim Start | prüft mtime, löst Caddy-Reload aus |

Tägliches Backup (rsync auf zweiten Rechner) noch nicht eingerichtet – Meilenstein 3.

## Bekannte Issues

- **Gunicorn 26 Control Socket**: `[Errno 13] Permission denied: '/.gunicorn'` beim Start.
  Nicht-fatal (1 Worker, App läuft stabil). Ursache: Gunicorn 26 hardcoded `os.sep + '.gunicorn'`
  als Control-Socket-Verzeichnis, `GUNICORN_RUN_DIR` wird ignoriert.
  Workaround: bleibt bis zu einem Gunicorn-Fix oder Downgrade auf 21.x.

## Deployment-Ablauf

```bash
# Paket bauen (von lokalem Rechner)
tar czf deploy/portal-vN.tar.gz --exclude='deploy' --exclude='.git' \
  --exclude='*.db' --exclude='data' --exclude='.env' \
  --exclude='__pycache__' --exclude='*.pyc' .

# Auf Server laden
scp -P 2222 deploy/portal-vN.tar.gz claude@10.0.0.100:/srv/familienportal/

# Auf Server entpacken + Container neu bauen + starten
ssh -p 2222 claude@10.0.0.100 "cd /srv/familienportal && tar xzf portal-vN.tar.gz"
ssh -p 2222 claude@10.0.0.100 "cd /srv/familienportal && docker compose build --no-cache portal util"
ssh -p 2222 claude@10.0.0.100 "cd /srv/familienportal && docker compose up -d"

# Testen (von lokalem Rechner, NICHT vom Host)
curl -s https://portal.16schwaben.de/health
```

## manage.py – Wichtige Befehle

```bash
docker exec portal python manage.py createadmin "Name" "#farbe"
docker exec portal python manage.py adduser    "Name" "#farbe"
docker exec portal python manage.py addapp     slug "App-Name" "emoji"
docker exec portal python manage.py grant      <user_id> <app_slug>
docker exec portal python manage.py listusers
docker exec portal python manage.py listwuensche
docker exec portal python manage.py listtodos
docker exec portal python manage.py wunsch_erledigt <id>
docker exec portal python manage.py backlog
```
