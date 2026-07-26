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

## 2026-07-26 – Meilenstein 2: Zentrale Dienste

### Was gebaut wurde

Vier App-Module + zugehörige Templates auf Basis des M1-Fundaments:

- **Admin** (`03_admin.py`): Nutzerverwaltung, Grant-Chips (toggle aktiv/inaktiv),
  QR-Code-Generator (via `segno`) für Startseiten-Link, Nutzerprofil-Editor (Farbe, Admin-Flag).
  Eigene Farbe/Admin-Status kann nicht selbst entzogen werden.

- **Todos** (`04_todo.py`): Aufgabenliste mit Zuweisung an andere Nutzer, privat-Flag
  (nur Ersteller + Assignee + Admin), erledigen/wiederherstellen, löschen (Owner/Admin).
  Öffentliche Funktion `todos_neu()` für Cross-App-Erstellung (z.B. Geholfen, zukünftiger Scanner).

- **Werkstatt-App** (`05_werkstatt_app.py`): Wunschliste-Ansicht für den ✨-Button.
  Admin kann Wünsche als erledigt markieren oder löschen. Für alle sichtbar (gefiltert nach Grants).

- **Geholfen** (`06_geholfen.py`): Tipp-Grid für Haushaltsaufgaben. AJAX via Fetch-API
  (`X-Requested-With: fetch`), Toast-Benachrichtigung ohne Reload. Übersicht: 7-Tage-Statistik
  (Punkte gewichtet). Aufgabenverwaltung: Emoji + Name + Gewichtung, aktiv/inaktiv.
  Seeded mit 8 Standard-Aufgaben.

- **Kern** (`00_kern.py`) erweitert: Tabellen `todos`, `geholfen_aufgaben`, `geholfen_eintraege`
  ins Schema aufgenommen. Seed für Core-Apps + Default-Aufgaben in `_init_db()`.

- **manage.py** erweitert: `listtodos`, `wunsch_erledigt`, `backlog` (kombinierte Rückstandsansicht).

- **requirements.txt**: `segno>=1.6` ergänzt (QR-Codes, serverseitig als SVG).

### Testergebnisse

- Alle 4 Apps: ✅ HTTP 200
- Startseite zeigt alle 4 App-Kacheln korrekt: ✅
- Admin: 2 Nutzerkarten (Andi + Simone): ✅
- Todo: Form + Sektionen vorhanden: ✅
- Werkstatt: Wunschliste geladen: ✅
- Geholfen: 8 Tipp-Buttons vorhanden: ✅
- POST /wunsch (JSON): `{"ok":true}` ✅
- POST /a/todo/*/neu → 302 Redirect: ✅
- POST /a/geholfen/*/tippen/1 → `{"ok":true,"aufgabe":"Tisch decken"}`: ✅
- Testdaten restlos entfernt: ✅

### Stolpersteine

1. **05_werkstatt_app.py: doppelter DB-Aufruf** – Copy-Paste-Fehler: `get_db().execute()` zweimal
   innerhalb von `loeschen()` aufgerufen ohne Variable. Zweite Verbindung war ein neues Objekt
   ohne `.commit()`. Lösung: `db = get_db()` einmalig zuweisen.

2. **manage.py grant druckte falsches Token** – Manage.py erstellte neuen Grant (Token A),
   Andi togglete danach im Admin-Panel den Grant (revoke → neu-grant = Token B).
   manage.py-Ausgabe zeigte Token A, DB enthielt Token B. Kein Bug in der Logik –
   normales Verhalten bei Admin-Toggle-Funktion. Startseite verlinkete korrekt auf Token B.

3. **Segno-Dependency**: `segno>=1.6` musste zu requirements.txt ergänzt werden, da
   `segno.make()` für SVG-QR-Codes benötigt wird (keine OS-Pakete, pure Python).

### Auslieferungspaket

`deploy/portal-v2.tar.gz` – enthält src/ (alle Module + Templates), util/, docker-compose.yml,
Caddyfile, .env.example, bauplan.md, CLAUDE.md, server.md, journal.md

---

## 2026-07-26 – Meilenstein 3: Push-Benachrichtigungen (VAPID)

### Was gebaut wurde

Web-Push-Infrastruktur vollständig integriert:

- **Service Worker** (`static/sw.js`): Empfängt `push`-Events, zeigt Systembenachrichtigungen
  mit Icon und Vibration; `notificationclick` öffnet Deep-Link.

- **Push-Subscription-API** (`07_push.py`):
  - `GET /push/vapid-public-key` – liefert VAPID-Public-Key für Frontend
  - `POST /push/subscribe` – speichert Subscription in `push_abos`;
    `ON CONFLICT(endpoint)` aktualisiert vorhandene Abos
  - `POST /push/unsubscribe` – entfernt Subscription

- **push_send()** (`00_kern.py`): Echte Implementierung statt Stub.
  Spawnt Daemon-Thread (nicht-blockierend), sendet via `pywebpush.webpush()` an alle
  Geräte des Nutzers. Expired Subscriptions (HTTP 404/410) werden automatisch bereinigt.
  Graceful degradation wenn VAPID_PRIVATE_KEY fehlt.

- **Todo-Zuweisung**: `todos_neu()` sucht den Todo-Token des Zugewiesenen und
  sendet Push mit Deep-Link-URL.

- **Startseite**: Push-Opt-in-Banner (erscheint nur bei `Notification.permission === 'default'`
  und noch nicht abonniert).

- **Admin**: Push-Abo-Zähler-Badge (🔔 N) neben Nutzernamen.

- **VAPID-Keys**: In Container mit `cryptography`-Library generiert, in `.env` eingetragen.

### Testergebnisse

- `GET /push/vapid-public-key` → 87-Zeichen-Base64url-Key: ✅
- `POST /push/subscribe` ohne Daten → 400: ✅
- `POST /push/subscribe` mit ungültigem Token → 403: ✅
- `GET /static/sw.js` → 200, push-EventListener vorhanden: ✅
- Startseite: SW-Registration + Push-Banner vorhanden: ✅

### Stolpersteine

Keine – `pywebpush>=2.0` akzeptiert base64url-kodierte Roh-Keys direkt.
Die Schlüssel wurden über `cryptography.hazmat` generiert (direkter als py_vapid).

### Noch offen (M3-Fortsetzung)

- rsync-Backup auf NAS (Andi richtet NAS ein, dann einrichten)
- Familie onboarden (WireGuard-Profile → Andi, dann QR-Codes ausgeben)

### Auslieferungspaket

`deploy/portal-v3.tar.gz`

---

*Nächster Schritt: rsync-Backup auf NAS (wenn NAS bereit), dann Familie onboarden*
