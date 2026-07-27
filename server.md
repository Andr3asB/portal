# server.md – Aktueller Systemzustand

*Letzte Aktualisierung: 2026-07-27 (portal-v15: Aufgaben-Umbenennung + neue Rezepte-App)*

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

## Security-Headers (Caddy)

Caddy setzt folgende Headers auf alle Antworten:

```
Referrer-Policy: no-referrer
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
-Server  (entfernt)
```

## Umgebungsvariablen (.env auf dem Server)

Datei: `/srv/familienportal/.env` (nicht im Repo, nicht in Git)

```
UID=1001
GID=1001
SECRET_KEY=<zufälliger Hex-Key, 32 Bytes>
GUNICORN_RUN_DIR=/tmp
VAPID_PRIVATE_KEY=<base64url, einmalig generiert – niemals neu generieren!>
VAPID_PUBLIC_KEY=<base64url, Gegenstück zum Private Key>
VAPID_SUBJECT=mailto:andreas.bosch@gmail.com
```

**Wichtig:** VAPID_PRIVATE_KEY darf NICHT geändert werden, solange aktive Push-Abos existieren.
Ein neuer Private Key macht alle bestehenden Subscriptions ungültig (Nutzer müssen neu opt-in).
Key-Rotation → alle `push_abos` löschen, dann neu generieren.

SECRET_KEY wird aus der Umgebung gelesen; fehlt er, generiert Flask einen ephemeren Key
(Sessions überleben keinen Neustart ohne gesetzten Key).

## Code-Struktur (src/)

```
app.py               – Flask-App, lädt nummerierte Module aus teile/ automatisch;
                       lädt VAPID_PRIVATE_KEY/PUBLIC_KEY/SUBJECT aus .env
glogging_redact.py   – Gunicorn RedactingLogger: ersetzt Tokens in Logzeilen durch <redacted>
manage.py            – CLI: createadmin, adduser, addapp, grant, listusers,
                       listwuensche, listtodos, wunsch_erledigt, backlog
teile/
  __init__.py        – registriert 00_kern als teile.kern
  00_kern.py         – DB-Schema, get_db()/new_db(), grant(), new_token(), to_int(),
                       push_send() (VAPID, Thread), /health, _init_db(),
                       _auto_grant_all() (hilfe + einkauf an alle Nutzer)
  01_start_token.py  – / (Landing), /p/<token> (Startseite mit Gruppen),
                       POST /p/<token>/reorder, /gruppe/neu, /gruppe/<id>/umbenennen,
                       /gruppe/<id>/loeschen
  02_werkstatt.py    – POST /wunsch (JSON, identifiziert Nutzer über Token)
  03_admin.py        – /a/admin/<token>/ Admin-Bereich: Nutzer (mit Rolle), Grants,
                       QR-Codes, _clean_farbe() (Hex-Validierung)
  04_todo.py         – /a/todo/<token>/ Aufgabenliste; todos_neu() mit Push-Deep-Link
  05_werkstatt_app.py – /a/werkstatt/<token>/ Wunschliste; Admin: Priorität setzen,
                       erledigen, löschen; POST /titel/<id> (JSON) für Claude-Titel
  06_geholfen.py     – /a/geholfen/<token>/ Tipp-Grid + Übersicht (Kalender 30 Tage,
                       7-Tage-Stats) + Aufgaben; eltern/admin können für andere eintragen
  07_push.py         – /push/vapid-public-key, /push/subscribe, /push/unsubscribe
  08_settings.py     – /einstellungen/<token> (Dark Mode), /manifest/<token>.json
                       (personalisiertes PWA-Manifest mit Nutzer-Token als start_url)
  09_hilfe.py        – /a/hilfe/<token>/ Hilfe- und Erklärungsseite (alle Apps)
  10_einkauf.py      – /a/einkauf/<token>/ Gemeinsame Einkaufsliste mit Kategorien,
                       Läden, Angebot-Markierung; /a/einkauf/<token>/laeden (Admin)
  11_rezepte.py      – /a/rezepte/<token>/ Lieblingsrezepte (Zutaten + Zubereitung);
                       /zutat/<id>/einkaufen (JSON) setzt fehlende Zutat auf Einkaufsliste
  templates/
    base.html               – Grundlayout: App-Header (⌂ links, ☰ rechts), Hamburger-Menü
                              (Dark Mode, Hilfe, ✨ Wunsch), SW-Registration, Manifest-Link
    startseite.html         – Startseite: App-Kacheln in Gruppen, Drag-&-Drop Sortierung,
                              Edit-Mode (✎/✓), Gruppen anlegen/umbenennen/löschen
    denied.html             – Zugang verweigert / Landing ohne Token
    admin.html              – Nutzerverwaltung, Rollen-Badge, Grant-Chips, QR-Modal, Push-Abo-Badge
    admin_user_form.html    – Nutzer anlegen/bearbeiten (Farbe, Rolle, Admin-Flag)
    todo.html               – Aufgabenliste (neu, zuweisen, erledigen)
    werkstatt_app.html      – Wunschliste mit Admin-Aktionen
    geholfen.html           – Tipp-Grid (Fetch-AJAX), Ticker, "Als wer?"-Pill (eltern/admin)
    geholfen_uebersicht.html – 7-Tage-Statistik, Punkte pro Nutzer, 30-Tage-Kalender
    geholfen_aufgaben.html  – Aufgaben verwalten (hinzufügen, deaktivieren)
    hilfe.html              – Erklärungen zu allen Apps und Funktionen
    einkauf.html            – Einkaufsliste: Kategorien-Gruppen, Angebot, Laden, Autocomplete
    einkauf_laeden.html     – Laden-Verwaltung (Admin)
    rezepte.html            – Rezeptliste + Neu-Formular (Name, Zutaten je Zeile, Zubereitung)
    rezept_detail.html      – Ein Rezept: Zutaten mit "🛒 Fehlt"-Knopf, Zubereitung, Löschen
static/
  manifest.json      – PWA-Manifest (Fallback ohne Nutzer-Token)
  icon-192.png       – Generiert im Dockerfile (solid blue #4a90d9)
  icon-512.png
  sw.js              – Service Worker für Push-Benachrichtigungen
```

## Datenbankschema (SQLite, WAL)

| Tabelle | Inhalt |
|---------|--------|
| `users` | id, name, farbe, is_admin, ki_key, dark_mode, rolle ('eltern'/'kind'/'gast') |
| `apps` | id, slug, name, emoji, beschreibung |
| `grants` | id, user_id, app_id, token (UNIQUE), position (sort), gruppe_id (FK home_gruppen) |
| `home_gruppen` | id, user_id, name, position – per-user app groups |
| `push_abos` | id, user_id, endpoint, p256dh, auth, geraet |
| `wuensche` | id, text, titel, prioritaet, user_id, app_slug, erstellt, erledigt, erledigt_am |
| `todos` | id, inhalt, erstellt_von, zugewiesen_an, privat, erledigt, erledigt_am, erstellt |
| `geholfen_aufgaben` | id, name, emoji, gewichtung, aktiv |
| `geholfen_eintraege` | id, aufgabe_id, user_id, zeitstempel |
| `einkauf_laeden` | id, name, aktiv |
| `einkauf_eintraege` | id, name, kategorie, angebot, laden_id, erledigt, erledigt_am, erstellt, erstellt_von |
| `rezepte` | id, name, anleitung, erstellt_von, erstellt |
| `rezept_zutaten` | id, rezept_id (FK rezepte, cascade), name, position |

App `slug='home'` = persönliche Startseite. URL-Schema: `/p/<token>`.
Andere Apps: `/a/<slug>/<token>/`.

## App-Slugs (Core)

| Slug | Name | Emoji | Beschreibung | Auto-Grant |
|------|------|-------|--------------|------------|
| `home` | Portal | 🏠 | Persönliche Startseite | – |
| `admin` | Verwaltung | ⚙️ | Nutzerverwaltung, Grants | – |
| `todo` | Aufgaben | ✅ | Aufgabenliste | – |
| `werkstatt` | Werkstatt | 💡 | Verbesserungswünsche | – |
| `geholfen` | Geholfen | 🙋 | Geholfen-Protokoll | – |
| `einkauf` | Einkauf | 🛒 | Gemeinsame Einkaufsliste | ✅ alle |
| `hilfe` | Hilfe | ❓ | Erklärungen und Tipps | ✅ alle |
| `rezepte` | Rezepte | 🍲 | Lieblingsrezepte | – |

## Sicherheitskonventionen (verpflichtend)

- **Ganzzahlen**: immer `to_int()` aus `teile.kern` – nie `int()` direkt auf Nutzereingaben
- **Farben**: immer `_clean_farbe()` aus `03_admin.py` (Regex `^#[0-9a-fA-F]{6}$`)
- **DOM**: `textContent` / `createElement` statt `innerHTML` für Nutzerdaten in JS
- **Logs**: Gunicorn RedactingLogger scrubbt Tokens aus Access-Logs
- **Headers**: Caddy setzt Security-Headers auf alle Antworten
- **Löschen-Sicherheitsabfrage** (app-übergreifend verpflichtend, seit Wunsch
  „Einkauf löschen"): jedes echte (nicht reversible) Löschen fragt nach –
  `onsubmit="return confirm({{ ('„' ~ text|truncate(40) ~ '“ löschen?')|tojson|forceescape }})"`
  auf dem Lösch-`<form>`. `|forceescape` ist Pflicht, sonst bricht `tojson`
  das HTML-Attribut auf (siehe Journal 2026-07-27). Reversible Toggles
  (aktiv/inaktiv, Grant-Entzug) brauchen keine Abfrage.

## Nutzer (Stand 2026-07-27)

| ID | Name | Rolle | Admin | Startseiten-URL |
|----|------|-------|-------|-----------------|
| 1 | Andi | eltern | ✅ | über Admin-App abrufbar (QR-Code) |
| 2 | Simone | eltern | – | über Admin-App abrufbar (QR-Code) |
| 3 | Friederike | kind | – | über Admin-App abrufbar (QR-Code) |
| 4 | Johannes | kind | – | über Admin-App abrufbar (QR-Code) |

Alle 4 Nutzer haben Grants für: home, geholfen, todo, werkstatt, einkauf, hilfe, rezepte.
Andi + Simone haben Rolle 'eltern' → sehen "Als wer?"-Selektor in Geholfen.

## util-Aufgaben

| Aufgabe | Zeitplan | Details |
|---------|----------|---------|
| SQLite-Snapshot | stündlich | 24 Slots in `/data/snapshots/` |
| Zertifikats-Watcher | täglich 04:00 + einmalig beim Start | prüft mtime, löst Caddy-Reload aus |
| NAS-Backup | täglich 03:00 | tar+ssh-Pipe → Ugreen NAS 10.60.0.4:2222, User `familienportal`, Pfad `/volume2/portal.16schwaben.de_Backup/`, 7 Generationen |

SSH-Key für Backup: `/srv/familienportal/ssh/id_ed25519` (bind-mount als `/ssh/id_ed25519` im Container, read-only). Public Key auf NAS in `/home/familienportal/.ssh/authorized_keys`.

## Bekannte Issues

- **Gunicorn 26 Control Socket**: `[Errno 13] Permission denied: '/.gunicorn'` beim Start.
  Nicht-fatal (1 Worker, App läuft stabil). Ursache: Gunicorn 26 hardcoded `os.sep + '.gunicorn'`
  als Control-Socket-Verzeichnis, `GUNICORN_RUN_DIR` wird ignoriert.
  Workaround: bleibt bis zu einem Gunicorn-Fix oder Downgrade auf 21.x.

## Deployment-Ablauf

**Wichtig:** Code-Änderungen erfordern `--build`, nicht nur `restart`. Templates und Python-Dateien
sind im Image eingebacken. `restart` startet nur den vorhandenen Container neu.

```bash
# Paket bauen (von lokalem Rechner)
tar czf deploy/portal-vN.tar.gz --exclude='deploy' --exclude='.git' \
  --exclude='*.db' --exclude='data' --exclude='.env' \
  --exclude='__pycache__' --exclude='*.pyc' .

# Auf Server laden
scp -P 2222 deploy/portal-vN.tar.gz claude@10.0.0.100:/srv/familienportal/

# Auf Server entpacken + Container neu bauen + starten
ssh -p 2222 claude@10.0.0.100 "cd /srv/familienportal && tar xzf portal-vN.tar.gz"
ssh -p 2222 claude@10.0.0.100 "cd /srv/familienportal && docker compose up -d --build"

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
