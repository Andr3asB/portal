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

### Auslieferungspaket

`deploy/portal-v3.tar.gz`

---

## 2026-07-26 – Meilenstein 3 (Fortsetzung): NAS-Backup

### Was gebaut wurde

Tägliches Backup von `/data` auf Ugreen NAS via tar+ssh-Pipe:

- **`util/backup.py`**: tar lokal erstellen, via SSH als stdin zu `cat > /pfad/datei.tar.gz`
  auf NAS streichen. Kein rsync-Daemon nötig. 7 Generationen auf NAS, Cleanup via
  `ls -t | tail -n +8 | xargs -r rm -f` per Remote-SSH.

- **`util/scheduler.py`**: täglich 03:00 Uhr, kein Backup beim Container-Start
  (vermeidet Flood bei Restart).

- **`util/Dockerfile`**: `useradd -u 1001` hinzugefügt – SSH sucht das Home-Verzeichnis
  in `/etc/passwd`; ohne Eintrag scheitert der SSH-Login mit "No user exists for uid 1001".

- **`docker-compose.yml`**: `/srv/familienportal/ssh:/ssh:ro` in util eingebunden.

- **NAS-Setup**: SSH-Key `portal-backup@home02` (`id_ed25519`) auf Ugreen NAS in
  `/home/familienportal/.ssh/authorized_keys` hinterlegt. User `familienportal` (uid=1005).
  SSH im UGOS-Web-UI für diesen User aktiviert.

### Testergebnisse

- Manueller Backup-Lauf: ✅ `portal-20260726-2104.tar.gz` (19 KB) auf NAS erstellt
- `ls` auf NAS: ✅ Datei mit korrekter Größe und Timestamp sichtbar
- SSH ohne Passwort: ✅ BatchMode=yes funktioniert

### Stolpersteine

1. **UGOS rsync braucht setuid-root**: Ugreen UGOS nutzt einen Custom-rsync-Wrapper
   (`ug_start_server`), der `set euid as root` benötigt – für uid=1005 nicht erlaubt.
   rsync-Protokoll funktioniert daher nicht für `/volume2/`-Pfade ohne Root-Rechte.
   Lösung: rsync komplett verworfen, tar+ssh-Pipe verwendet (kein remoter rsync-Daemon).

2. **SSH-Port auf NAS**: Port 2222 (wie home02), nicht 22. Musste in `.env` + `backup.py`
   Defaults nachgezogen werden.

3. **"This account is currently not available"**: UGOS blockiert SSH per Nutzer.
   Lösung: Im UGOS-Web-UI SSH für User `familienportal` explizit aktivieren.

4. **"No user exists for uid 1001"**: SSH liest Home-Verzeichnis aus `/etc/passwd`.
   Im util-Container existierte uid=1001 ohne passwd-Eintrag.
   Lösung: `useradd -u 1001 -m -s /bin/sh portal` im Dockerfile.

### Auslieferungspaket

Direkt per `scp` auf den Server eingespielt (kein neues `.tar.gz`). Commit: `726ddab`

---

## 2026-07-27 – Erweiterungen: Dark Mode, Geholfen-Kalender, Hilfe-App, PWA-Fix

### Was gebaut wurde

- **Dark Mode** (`08_settings.py`, `teile/templates/`): Per-Nutzer-Einstellung, gespeichert
  in `users.dark_mode`. Toggle via `/einstellungen/<token>`. CSS Custom Properties in
  `base.html`, `prefers-color-scheme` als Startwert, danach DB-Wert maßgebend.

- **Geholfen: 30-Tage-Kalender** (`06_geholfen.py`): Übersichtsseite zeigt neben
  7-Tage-Punkte-Tabelle einen Kalender (letzte 30 Tage), wer an welchem Tag geholfen hat.

- **Hilfe-App** (`09_hilfe.py`, `hilfe.html`): Erklärungs- und Onboarding-Seite für alle
  Apps. Auto-Grant an alle Nutzer beim DB-Init. Jede neue Funktion muss hier dokumentiert werden.

- **PWA-Manifest per Nutzer** (`08_settings.py`): Route `/manifest/<home_token>.json` liefert
  ein personalisiertes Manifest mit `start_url: /p/<token>`. Öffnet die App bei "Zum
  Home-Bildschirm" direkt auf der persönlichen Startseite statt auf `/`.
  `base.html` verlinkt dynamisch auf `/manifest/<token>.json` wenn Nutzer eingeloggt.
  `01_start_token.py`: `g.token AS home_token` in der startseite-Query ergänzt.

- **Navigation: keine Sackgassen**: Alle Unterseiten der Geholfen-App haben Zurück-Links
  (`geholfen_uebersicht.html` → ← Geholfen, `geholfen_aufgaben.html` → ← Übersicht).
  Regel gilt generell: jede Unterseite braucht einen Zurück-Link, ⌂ ist kein Ersatz.

### Stolpersteine

1. **`docker compose restart` baut nicht neu**: Container liefen mit altem Image weiter.
   `restart` startet nur den vorhandenen Container neu – keine Bytecode-Änderungen wirksam.
   Lösung: immer `docker compose up -d --build portal`.

2. **Manifest-Route 404**: Gleiche Ursache – altes Image kannte die neue Route nicht.
   Nach `--build` sofort grün.

3. **`user.home_token` fehlte auf Startseite**: `01_start_token.py` hat eine eigene SELECT-Query
   (nicht über `grant()`). `home_token` musste dort explizit ergänzt werden.

---

## 2026-07-27 – Erweiterungen: Einkaufsliste, Rollen, Admin-Verbesserungen

### Was gebaut wurde

- **Einkaufsliste** (`10_einkauf.py`, `einkauf.html`, `einkauf_laeden.html`):
  Gemeinsame Einkaufsliste für alle Nutzer. Kategorien (Obst & Gemüse, Kühlregal etc.),
  Angebot-Markierung mit Laden-Zuordnung, erledigte Einträge bleiben 6 Stunden sichtbar,
  Autocomplete aus Eintragshistorie (Datalist). Admin: Läden verwalten. Default-Läden beim
  DB-Init geseedet (Edeka, Rewe, Lidl, …). Auto-Grant an alle Nutzer.

- **Nutzer-Rollen** (`users.rolle`): Drei Rollen: `eltern`, `kind`, `gast` (Default).
  - Admin: Rollen-Radio-Gruppe im Bearbeitungsformular, Badge in Nutzerliste.
  - Geholfen: eltern + admin können mit "Als wer?"-Pill-Selektor Einträge für andere machen.
  - `_auto_grant_all()` für hilfe + einkauf setzt Grants ohne DB-Wipe.
  - Migration in `_init_db()`: `ALTER TABLE users ADD COLUMN rolle` (idempotent per try/except).

### Testergebnisse

- Einkaufsliste: Eintrag hinzufügen + Kategorie: ✅
- Eintrag als erledigt markieren (Fetch): ✅
- Angebot-Flag + Laden zuweisen: ✅
- Laden hinzufügen (Admin): ✅
- Rolle setzen + in Geholfen "Als wer?" sichtbar: ✅
- Auto-Grant für neue App-Slugs: ✅

---

## 2026-07-27 – Sicherheitshärtung (alle 5 Fixes)

### Ausgangspunkt

Opus 4.8-Review ergab 5 konkrete Schwachstellen. Dokumentiert in `sicherheit_haertung.md`
(jetzt umgesetzt und als Referenz archiviert).

### Was gebaut wurde

1. **Token-Redaktion in Logs** (`glogging_redact.py`): Gunicorn `RedactingLogger` ersetzt
   Tokens (`/p/<token>`, `/a/<slug>/<token>`) in Access-Log-Atomen durch `<redacted>`.
   Aktiviert via `--logger-class glogging_redact.RedactingLogger` im Dockerfile.

2. **Caddy Security-Headers** (`Caddyfile`): `Referrer-Policy: no-referrer`,
   `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `-Server`.

3. **SECRET_KEY aus Umgebung** (`app.py`):
   `app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)`
   (kein hardcoded Fallback mehr; ephemer wenn nicht in .env gesetzt).

4. **`to_int()` für alle Integer-Eingaben** (`00_kern.py`): Hilfsfunktion mit try/except,
   `default=None`. In `04_todo.py`, `06_geholfen.py`, `10_einkauf.py` überall eingesetzt.
   Verhindert `ValueError`/`TypeError` auf ungültige IDs in POST-Daten.

5. **`_clean_farbe()` für Farbfelder** (`03_admin.py`): Regex `^#[0-9a-fA-F]{6}$`.
   Verhindert CSS-Injection über benutzerdefinierte Farben.

   **Bonus – XSS via innerHTML** (`geholfen.html`): Ticker-Update verwendet jetzt DOM-API
   (`textContent`, `createElement`) statt `innerHTML`, sodass Nutzernamen/Aufgabennamen
   nicht als HTML interpretiert werden.

### Testergebnisse

- `curl -I https://portal.16schwaben.de/health` → alle 3 Security-Header vorhanden: ✅
- Access-Log: Token in `GET /p/<redacted>` korrekt geschwärzt: ✅
- `POST /a/geholfen/*/tippen/1` mit `{"fuer_user_id":"abc"}` → 200 (kein 500): ✅
- `POST /a/admin/*/user/neu` mit `farbe=<script>` → wird zu `#4a90d9`: ✅
- Testeinträge bereinigt: ✅

---

## 2026-07-27 – Meilenstein 4: Familie onboarden

### Was getan wurde

- WireGuard-Profile für alle Familienmitglieder eingerichtet (Andi).
- QR-Codes aus Admin-App bereitgestellt und verteilt.
- 4 Nutzer im System: Andi (eltern, Admin), Simone (eltern), Friederike (kind), Johannes (kind).
- Alle Nutzer haben Grants für alle relevanten Apps.

### Status

M4 abgeschlossen. Alle Familienmitglieder sind an Bord.

---

*Nächster Schritt: wunschgetrieben (M5) – Werkstatt-Backlog beobachten, neue Wünsche umsetzen.*

---

## 2026-07-27 – Werkstatt-Wünsche #6–#9 (portal-v4 + portal-v5)

### Was umgesetzt wurde

**Wunsch #6 – Leeres Block nach Farbbalken (Admin-Formular)**
- `admin_user_form.html`: `input[type=color]` (Color-Picker) entfernt.
  Der Color-Picker hatte außerdem irrtümlich `name="farbe"` – das Formular übergab
  den Picker-Wert statt des Hex-Textfelds. Fix: `name="farbe"` auf das Textfeld verschoben,
  Picker komplett entfernt. Neue JS-Funktionen `syncFarbe()` + `highlightPreset()` halten
  Preset-Buttons und Textfeld synchron.

**Wunsch #7 – App-Reihenfolge anpassbar (persistent, geräteübergreifend)**
- `grants`-Tabelle: neue Spalten `position` (INTEGER, DEFAULT 0) + `gruppe_id` (INTEGER, FK).
  Migration idempotent via `ALTER TABLE … ADD COLUMN` in `try/except`.
- Neue Route `POST /p/<token>/reorder` (JSON `{items:[{grant_id, gruppe_id, position}]}`).
  Ownership-Prüfung: jeder grant_id und gruppe_id wird vor Update gegen `user_id` validiert.
- `startseite.html`: Pointer-Events Drag-&-Drop (~130 Zeilen JS). 8px-Threshold vor Ghost-Start,
  `setPointerCapture` für Touch-Zuverlässigkeit, Placeholder-Div als Drop-Ziel.
  `saveLayout()` liest DOM-Reihenfolge → sendet an `/reorder`.

**Wunsch #8 – App-Gruppen auf Startseite, „Allgemein" immer zuletzt**
- Neue Tabelle `home_gruppen` (id, user_id, name, position). Schema in `00_kern.py`.
- `startseite()` baut `gruppen_list` + `allgemein`-Liste. SQL ordnet:
  `ORDER BY (g.gruppe_id IS NULL), gruppe_pos, g.gruppe_id, g.position, a.id`
  (benannte Gruppen vor Allgemein, innerhalb nach position).
- Neue Routen: `POST /p/<token>/gruppe/neu`, `…/umbenennen`, `…/loeschen`.
  Löschen setzt betroffene grants auf `gruppe_id=NULL` (Fallback Allgemein).
- `startseite.html`: Edit-Mode (✎ / ✓ Fertig), Gruppen-Header mit Rename/Delete,
  „+ Gruppe"-Button, virtuelle Allgemein-Sektion (`data-gruppe-id=""`).

**Wunsch #9 – ⌂ links, ☰ rechts, Hamburger-Menü mit Dark Mode / Hilfe / ✨**
- `base.html` komplett überarbeitet: Bottom-Bar entfernt, neues `.app-header` mit `.nav-bar`.
  Blöcke `nav_left` (Default: ⌂), `nav_title`, `header_extra` für Template-Erweiterung.
- Hamburger-Panel rechts (slide-in, `min(300px, 82vw)`): 🏠 Startseite, 🌙 Dark Mode,
  ❓ Hilfe (via `user.hilfe_token`), ✨ Verbesserungsvorschlag.
- Dark Mode Toggle: jetzt im Hamburger-Menü (war vormals im Bottom-Bar).
- `grant()` in `00_kern.py` um `hilfe_token`-Subquery erweitert → in allen App-Seiten verfügbar.
- Alle 8 App-Templates auf `{% block nav_left %}` / `{% block nav_title %}` /
  `{% block header_extra %}` umgestellt (keine eigenen `<header>`-Tags mehr).

**Hilfe-App aktualisiert (portal-v5)**
- Referenzen auf die alte Bottom-Bar korrigiert (☰ statt „Leiste unten").
- Neue Sektion: „🗂️ Apps sortieren & gruppieren" (Drag-&-Drop, Gruppen).

### Testergebnisse (via curl + JS-Injection)

- `GET /p/<token>` → alle DOM-Elemente vorhanden: nav-bar, menu-btn, gruppe-section,
  allgemein-section, edit-toggle, menu-panel, Dark Mode, Hilfe-Link, Wunsch-Overlay: ✅
- Hamburger öffnet / schließt sich korrekt: ✅
- Edit-Mode togglet "✎ Apps anpassen" ↔ "✓ Fertig": ✅
- `POST /p/<token>/reorder` → `{"ok":true}`: ✅
- `POST /p/<token>/gruppe/neu` → `{"id":…,"ok":true}`: ✅
- `POST /p/<token>/gruppe/<id>/umbenennen` → `{"ok":true}`: ✅
- `POST /p/<token>/gruppe/<id>/loeschen` → `{"ok":true}`: ✅
- Admin-Formular: kein `input[type=color]` mehr – nur text/radio/checkbox: ✅
- Hilfe-Link im Hamburger-Menü vorhanden: ✅
- `/health` → `{"status":"ok"}` nach deploy: ✅

### Auslieferungspakete

- `deploy/portal-v4.tar.gz` – Wünsche #6–#9 (Navigation + Gruppen + Sortierung)
- `deploy/portal-v5.tar.gz` – Hilfe-App-Update (Navigationsreferenzen + neue Sektion)

---

## 2026-07-27 – Werkstatt: ID / Titel / Priorität / Sortierung (portal-v6)

### Was gebaut wurde

- **Sichtbare ID**: Jeder Wunsch zeigt einen `#id`-Badge (grau, klein).
- **KI-Titel**: Neues Feld `titel` in `wuensche`; Endpunkt `POST /titel/<id>` (JSON,
  Admin-Token). Claude setzt Titel wenn der User „Lies dir alle Wünsche durch" sagt.
  Titel (max. 80 Zeichen) erscheint als fette Überschrift, der Originaltext darunter in Grau.
- **Priorität**: Feld `prioritaet` (niedrig/mittel/hoch/sehr_hoch). Admin wählt per Dropdown
  direkt in der Karte (`onchange` → sofortiger POST). Farbiges Badge: grün/gelb/orange/rot.
- **Sortierung**: Offene Wünsche nach Priorität absteigend, dann nach Erstelldatum desc.
  Erledigte nach `erledigt_am` desc (neues Feld, bei Toggle gesetzt/gelöscht).
- **Zwei Sektionen**: „Offen" und „Erledigt" klar getrennt in `werkstatt_app.html`.
- **DB-Migrationen** in `00_kern.py`: `titel TEXT`, `prioritaet TEXT`, `erledigt_am DATETIME`
  zu `wuensche`. Bestehende erledigte Wünsche bekommen `erledigt_am = erstellt` als Fallback.

### Testergebnisse

- Werkstatt lädt, ID-Badges sichtbar, Titel aller 15 Wünsche gesetzt: ✅
- Sortierung: Wunsch #10 (Prio hoch) steht an erster Stelle: ✅
- Prio-Dropdown → `POST /prioritaet/<id>` → 302 Redirect: ✅
- `POST /titel/<id>` (JSON) → `{"ok":true}`, UTF-8 korrekt in DB: ✅
- Erledigt-Sektion sortiert nach erledigt_am desc: ✅
- `/health` → `{"ok":true}` nach deploy: ✅

### Auslieferungspaket

`deploy/portal-v6.tar.gz`

---

## 2026-07-27 – Wunsch #10: Rollen-Berechtigungen für Todos (portal-v7)

### Was gebaut wurde

- **Erstellen**: alle Nutzer (unverändert)
- **Abhaken**: Eltern/Admin → jedes Todo; Kind/Gast → nur eigene (erstellt_von oder zugewiesen_an)
- **Löschen**: ausschließlich Eltern/Admin (Kind/Gast erhalten 403)
- **Sichtbarkeit**: Eltern/Admin sehen alle Todos (auch private); Kind/Gast nur eigene/zugewiesene/öffentliche (unverändert)
- **Template** (`todo.html`): Löschen-Button nur wenn `darf_loeschen`; Abhaken-Button nur wenn berechtigt, sonst dezenter Ghost-Kreis. `darf_loeschen` wird aus dem Backend übergeben.
- **Hilfe-App**: Todos-Beschreibung um Hinweis auf Löschen-Berechtigung ergänzt.

### Testergebnisse

- Friederike (kind) versucht löschen → HTTP 403: ✅
- Friederike hakt eigenes Todo ab → HTTP 302: ✅
- Andi (eltern/admin) löscht Friederikes Todo → HTTP 302: ✅
- `/health` → `{"ok":true}`: ✅

### Auslieferungspaket

`deploy/portal-v7.tar.gz`

---

## 2026-07-27 – Wunsch #17: SSL-Fehler über WireGuard (Analyse)

### Fehlerbild

Andi: „seit dem Security-Update funktioniert die App nicht mehr über WireGuard,
Browser zeigt 'Diese Verbindung ist nicht sicher'."

### Analyse

- Zertifikat/Caddy direkt geprüft (von diesem Rechner, LAN): TLS-Handshake sauber,
  Cert gültig bis 24.10.2026, korrekter SAN. Kein serverseitiges TLS-Problem.
- Caddy-Logs komplett durchsucht: nur 3 Fehleinträge, alle vom Vorabend
  (Docker-DNS-Aussetzer `lookup portal on 127.0.0.11:53` während eines Redeploys,
  502, kein TLS-Fehler) – nicht die Ursache.
- **Kernbefund**: `portal.16schwaben.de` war öffentlich (1.1.1.1/8.8.8.8) nicht
  auflösbar (NXDOMAIN) – nur intern per Pi-hole (`10.0.0.194` → `10.0.0.200`).
  Das war so beabsichtigt (Bauplan §2.1: kein öffentlicher Zugriff), führte aber
  offenbar dazu, dass WireGuard-Clients die Domain nie zuverlässig auflösen
  konnten, sobald sie nicht Pi-hole als DNS nutzen.
- Andi bestätigt: Fehler trat **wiederholt/dauerhaft** auf, nicht nur einmalig –
  Redeploy-Fenster-Kollision als alleinige Ursache damit ausgeschlossen.

### Fix (von Andi vorgenommen, außerhalb des Repos)

Öffentlicher DNS-Record für `portal.16schwaben.de` gesetzt → zeigt jetzt auf
`84.135.184.50` (öffentliche WAN-IP, vermutlich per Dynamic-DNS bei
domainoffensive.de). Damit können WireGuard-Clients die Domain auch ohne
Pi-hole auflösen. Nach Andis Einschätzung hat es damit „vermutlich nie
richtig funktioniert".

### Offene Punkte / Beobachtung

- **Sicherheitsfrage (noch zu klären mit Andi):** Ein öffentlicher DNS-Record
  auf die WAN-IP ist nur unkritisch, solange **kein Port-Forwarding** auf
  `home02`/Caddy eingerichtet ist – sonst wäre das Portal entgegen Bauplan §2.1
  („aus dem Internet nicht erreichbar") direkt aus dem Internet erreichbar,
  und das Token-ohne-Login-Modell setzt aber ausdrücklich ein vertrauenswürdiges
  Netz voraus. Muss mit Andi verifiziert werden, sobald relevant.
- Getroffene Vereinbarung: Fehler wird beobachtet. Tritt er nach einem
  DNS-Flush auf einem Client erneut auf, gehen wir erneut in Analyse
  (dann vermutlich weiter Richtung WireGuard-DNS-Push/Split-DNS-Konfiguration
  auf dem UniFi-Gateway – liegt außerhalb des Schreibbereichs dieses Projekts).
- Wunsch #17 bleibt bis zur Bestätigung offen (nicht über `manage.py
  wunsch_erledigt` abgeschlossen).

---

## 2026-07-27 – Fix: Neue Gruppe war kein Drop-Ziel (portal-v8)

### Fehlerbild

Andi: Neue App-Gruppe angelegt, aber die erste App ließ sich nicht per
Drag & Drop hineinziehen – „die Gruppe wird nicht erkannt".

### Ursache

`startseite.html`: Das Drag & Drop ermittelt das Ziel über
`document.elementFromPoint(x, y)`. Eine leere `.gruppe-grid` (CSS Grid ohne
Kind-Kacheln) kollabiert auf 0px Höhe – der Zeiger trifft beim Ziehen also nie
auf das Grid-Element selbst, sondern auf etwas dahinter (z. B. die
Gruppen-Section ohne die Klasse `.gruppe-grid`). `targetGrid` blieb dadurch
immer `null`, sobald eine Gruppe komplett leer war.

### Fix

`.edit-mode .grid { min-height: 100px; }` ergänzt – im Edit-Modus hat jede
Gruppe (auch eine leere) eine Mindesthöhe und ist damit ein gültiges,
erreichbares Drop-Ziel. Außerhalb des Edit-Modus keine Auswirkung (keine
unnötige Leerfläche beim normalen Ansehen der Startseite).

### Testergebnisse (Playwright, von diesem Rechner, gegen echten Stack)

Test mit eigens angelegtem Wegwerf-Nutzer `ZZZ_E2E_Test` (danach vollständig
gelöscht, cascade über `ON DELETE CASCADE`), damit keine echten Familiendaten
angefasst werden:

- Neue Gruppe angelegt → Grid-Bounding-Box vorher 0px, nach Fix 100px hoch: ✅
- Kachel per simuliertem Pointer-Drag in die leere Gruppe gezogen: ✅
  (`TILE_MOVED_INTO_NEW_GROUP` = true, per DOM-Check direkt nach Drop)
- Seite neu geladen → Zuordnung bleibt bestehen (Server-seitig über
  `/p/<token>/reorder` gespeichert): ✅
- Screenshots angesehen (Mid-Drag + nach Reload): Kachel sitzt sauber in der
  neuen Gruppe, kein visueller Nebeneffekt auf andere Gruppen.
- Test-Nutzer danach restlos entfernt, verbleibende Nutzer/Gruppen geprüft
  (nur die 4 echten Familienmitglieder + Andis reale Gruppen übrig).

### Auslieferungspaket

`deploy/portal-v8.tar.gz` – nur `portal` neu gebaut/gestartet, `caddy`
unverändert durchgelaufen (kein unnötiger Neustart, siehe Wunsch #17).

---

## 2026-07-27 – Wunsch #14: Einkaufsliste – Buttons statt Dropdowns (portal-v9)

### Was gebaut wurde

`einkauf.html` / `10_einkauf.py` (Backend unverändert, reine Frontend-Umstellung):

- Kategorie-Auswahl (Neues Item): `<select>` ersetzt durch eine horizontal
  scrollbare Reihe von Chip-Buttons (`.btn-row` / `.chip-btn`). Muss aktiv
  angeklickt werden (kein Default) – `+ Hinzufügen` bleibt deaktiviert, bis
  eine Kategorie gewählt ist.
- „% Angebot" ist jetzt selbst ein Chip-Button (Toggle) statt Checkbox; beim
  Aktivieren erscheint die Markt-Buttonreihe (ebenfalls `<select>` ersetzt).
  Ist Angebot aktiv, bleibt `+ Hinzufügen` zusätzlich deaktiviert, bis ein
  Markt gewählt wurde. Toggelt man Angebot wieder aus, wird die
  Marktauswahl zurückgesetzt.
- Gleiche Umstellung im bestehenden „Angebot markieren"-Formular pro Artikel
  (Markt-Dropdown → Buttons, Submit deaktiviert bis Markt gewählt). Beim
  Entfernen eines bestehenden Angebots ist keine Auswahl nötig.
- Bug beim Bauen entdeckt und gleich mitgefixt: Der Enter-Tastendruck im
  Namensfeld rief bisher `form.submit()` direkt auf – das hätte den
  deaktivierten Button umgangen und die Validierung ausgehebelt. Jetzt
  `submitBtn.click()`, was bei `disabled` korrekt nichts tut.

### Testergebnisse (Playwright, von diesem Rechner, gegen echten Stack)

Test mit eigens angelegtem Wegwerf-Nutzer `ZZZ_E2E_Test2` (Grant nur auf
`einkauf`), danach restlos entfernt:

- `#add-form` enthält 0 `<select>`-Elemente mehr: ✅
- Name allein eingegeben, ohne Kategorie → Button bleibt deaktiviert: ✅
- Enter-Taste bei fehlender Kategorie → keine Navigation/Submit ausgelöst: ✅
- Kategorie gewählt → Button aktiviert: ✅
- „% Angebot" umgeschaltet, kein Markt gewählt → Button wieder deaktiviert: ✅
- Markt gewählt → Button aktiviert, Absenden erfolgreich, Artikel erscheint
  mit `% Aldi`-Badge in der richtigen Kategorie: ✅
- Bestehenden Artikel („Käse") nachträglich per Buttons als Angebot („Rewe")
  markiert – Submit vorher deaktiviert, nachher aktiviert, Badge korrekt: ✅
- Screenshots angesehen: Buttons sitzen sauber nebeneinander, scrollbar bei
  Platzmangel, aktive Auswahl farblich hervorgehoben.
- Nach dem Test: Test-Artikel gelöscht, „Käse" zurück auf Ursprungszustand
  (kein Angebot) gesetzt – dabei einen Encoding-Stolperstein gefunden (siehe
  unten) –, Test-Nutzer restlos entfernt. Nur echte Familiendaten übrig.

### Stolperstein

`UPDATE ... WHERE name='Käse'` über `ssh … docker exec … python3 -c "…"`
traf keine Zeile – Umlaute gehen durch die verschachtelten Shell-Ebenen
(lokale Bash → SSH → Python-String) verloren/kaputt. Lösung: beim
Aufräumen über SQL immer über die numerische ID filtern, nie über Text mit
Sonderzeichen quer durch mehrere Shells.

### Auslieferungspaket

`deploy/portal-v9.tar.gz` – nur `portal` neu gebaut/gestartet.

---

## 2026-07-27 – Wunsch #14 Korrektur: Buttons umbrechen statt horizontal scrollen (portal-v10)

Andi: Die Button-Reihen (Kategorie, Markt) sollen bei Platzmangel umbrechen,
nicht horizontal scrollen.

### Fix

`.btn-row`: `overflow-x:auto` (+ Scrollbar-Verstecken) entfernt, stattdessen
`flex-wrap:wrap`. Betrifft Kategorie- und Markt-Buttons im Neu-Formular
sowie im „Angebot markieren"-Formular pro Artikel gleichermaßen (eine
gemeinsame CSS-Klasse).

### Testergebnisse

Playwright, Wegwerf-Nutzer (danach entfernt): `flex-wrap` berechnet zu
`wrap`, `scrollWidth === clientWidth` (kein horizontaler Überlauf mehr),
Reihe wächst stattdessen in der Höhe. Screenshot angesehen: Kategorien und
Märkte brechen sauber in mehrere Zeilen um, alle Buttons auf einen Blick
sichtbar.

**Beobachtung (keine Aktion nötig):** Beim Testen fiel auf, dass in der
echten Liste inzwischen ein Artikel „Test" (Angebot, Aldi) sowie eine
geänderte Marktzuordnung bei „Sprühsahne" existieren, die nicht aus meinen
Tests stammen – vermutlich Andis eigener Test des Buttons-Features nach
portal-v9. Nicht angefasst, da es sich um echte/aktuelle Nutzung handeln
könnte und nicht eindeutig als Testartefakt erkennbar ist.

### Auslieferungspaket

`deploy/portal-v10.tar.gz` – nur `portal` neu gebaut/gestartet.

---

## 2026-07-27 – Fix: Angebot-Markierung ließ sich nicht entfernen/nachträglich setzen (portal-v11)

Andi meldete zwei zusammenhängende Bugs im „Angebot markieren"-Feature aus
Wunsch #14:

1. Beim Entfernen einer Angebot-Markierung wurde nur der Markt gelöscht,
   die Markierung selbst blieb bestehen.
2. Die Markierung ließ sich bei bereits erledigten (abgehakten) Artikeln
   gar nicht erst nachträglich setzen.

### Ursache #1 (Backend, `10_einkauf.py`)

`angebot = 1 if request.form.get("angebot") else 0` – klassischer
Python-Fallstrick: `request.form.get(...)` liefert bei einem versteckten
Feld mit `value="0"` den **String** `"0"`, und `bool("0")` ist `True` (jeder
nicht-leere String ist wahr). Das „Entfernen"-Formular schickt genau dieses
`value="0"`, und `angebot` wurde dadurch **immer** auf 1 gesetzt – unabhängig
vom tatsächlich gesendeten Wert. Nur `laden_id` (kein eigenes verstecktes
Feld beim Entfernen) wurde korrekt auf `None` gesetzt. Betraf `add()` und
`set_angebot()` gleichermaßen. Fix: `request.form.get("angebot") == "1"`
statt reiner Wahrheitsprüfung.

Live-Daten bestätigten die Diagnose vor dem Fix: `Sprühsahne` und `Test`
standen genau in diesem kaputten Zwischenzustand (`angebot=1, laden_id=NULL`)
– vermutlich Andis eigener, gescheiterter Versuch, die Markierung zu
entfernen. Nach dem Fix beide auf `angebot=0` zurückgesetzt (das war
erkennbar die eigentliche Absicht).

### Ursache #2 (Frontend, `einkauf.html`)

Der „%"-Button samt Angebot-Formular existierte nur im Template-Block für
offene Artikel, nicht im separaten Block für erledigte Artikel – schlicht
vergessen bei Wunsch #14, weil beide Blöcke unabhängige Kopien waren (genau
die Art Bug, die Code-Duplikation begünstigt). Fix: beide Blöcke zu einem
gemeinsamen Jinja-Makro `item_card(item, token, laeden)` zusammengefasst,
das von offenen wie erledigten Artikeln gleichermaßen verwendet wird –
künftige Änderungen an der Artikel-Darstellung landen automatisch in
beiden Listen.

### Testergebnisse (Playwright, Wegwerf-Nutzer, danach entfernt)

- Artikel ohne Angebot-Toggle hinzugefügt → kein Badge: ✅ (Regressionstest
  für die `add()`-Hälfte desselben Bugs, betraf auch das normale Hinzufügen)
- Artikel mit Angebot+Markt hinzugefügt → Badge „% Rewe": ✅
- Angebot über „Entfernen" entfernt → Badge verschwindet vollständig
  (vorher: Markt weg, Badge „% " blieb stehen): ✅
- Artikel abgehakt (erledigt) → Reload → „%"-Button jetzt auch im
  Erledigt-Block vorhanden: ✅
- Dort nachträglich Markt gewählt und markiert → Badge „% Edeka" korrekt: ✅
- Screenshots angesehen, Testartikel + Testnutzer restlos entfernt.

### Auslieferungspaket

`deploy/portal-v11.tar.gz` – nur `portal` neu gebaut/gestartet.

---

## 2026-07-27 – Fix: Layout des „Angebot markieren"-Formulars (portal-v12)

Andi (per Screenshot, iPhone Dark Mode): Das aufgeklappte Markt-Auswahl-
Formular sah unaufgeräumt aus – Buttons überlappten optisch den Artikel
darüber.

### Ursache

`.item-card` ist eine Flex-**Reihe** (Checkbox, Name, Badge, %-Toggle,
Angebot-Formular, Löschen – alle nebeneinander) ohne `flex-wrap`. Das
aufgeklappte `.angebot-form` mit der mehrzeiligen Markt-Buttonreihe wurde
dadurch als hoher Flex-Item MITTEN in dieser einen Reihe gequetscht;
`align-items:center` zentrierte die kurzen Elemente (Name, Checkbox) in der
Mitte der dadurch sehr hohen Zeile, während der Markt-Button-Block optisch
"nach oben" auszubrechen schien – sah wie ein Überlapp mit der Karte
darüber aus, war aber dieselbe Karte.

### Fix

- `.item-card` bekommt `flex-wrap:wrap`.
- `.angebot-form`: `flex:1 0 100%` (erzwingt Umbruch auf eine eigene volle
  Zeile), `flex-direction:column`, dezente Trennlinie (`border-top`) und
  Abstand nach oben.
- Kleines Label „Markt wählen" ergänzt (Konsistenz mit dem Haupt-Formular).
- Submit-Button (`Angebot`/`Entfernen`) bleibt kompakt (`align-self:flex-start`)
  statt über die volle Breite gestreckt.

### Testergebnisse (Playwright, Dark Mode wie im Screenshot, Wegwerf-Nutzer)

- Bounding-Box-Check: Formular beginnt jetzt unterhalb der Namenszeile
  (kein Overlap mehr) – vorher lag es mitten in derselben Zeile: ✅
- Screenshot (Dark Mode, iPhone-Breite) angesehen: Name, Markt-Auswahl,
  Angebot-Button und Löschen-Button sauber untereinander, mit dezenter
  Trennlinie. Test-Artikel und Test-Nutzer restlos entfernt.

### Auslieferungspaket

`deploy/portal-v12.tar.gz` – nur `portal` neu gebaut/gestartet.

---

## 2026-07-27 – App-übergreifend: Sicherheitsabfrage vor Löschen (portal-v13/v14)

Andi: Löschen in der Einkaufsliste soll eine Sicherheitsabfrage haben, wie
bei Todos – und die UX dafür soll **über alle Apps hinweg gleich sein**
(als dauerhafte Konvention gemerkt, siehe `CLAUDE.md`/Projekt-Notiz unten).

### Bestandsaufnahme (vor dem Fix)

- `todo.html`: offene Todos hatten `confirm('Todo löschen?')`, erledigte
  Todos hatten **gar keine** Sicherheitsabfrage – Inkonsistenz sogar
  innerhalb derselben App.
- `werkstatt_app.html`: hatte bereits `confirm('Wunsch #<id> löschen?')`.
- `startseite.html` (Gruppe löschen): hatte bereits eine JS-`confirm()`
  mit Namen + Konsequenz-Hinweis.
- `einkauf.html`: **keine** Sicherheitsabfrage beim Löschen (der gemeldete
  Bug).
- Reversible Toggle-Aktionen (Markt/Aufgabe aktiv/inaktiv in
  `einkauf_laeden.html` / `geholfen_aufgaben.html`, Grant-Entzug in
  `admin.html`) bewusst **ausgenommen** – das sind keine echten
  Löschvorgänge, sondern mit einem Klick rückgängig machbar.

### Vereinheitlichtes Muster (jetzt überall gleich)

Natives `confirm()` im `onsubmit` des Lösch-`<form>`:

```
onsubmit="return confirm({{ ('„' ~ text|truncate(40) ~ '“ löschen?')|tojson|forceescape }})"
```

- Immer die konkrete Bezeichnung des Eintrags in der Frage (nicht nur
  „Löschen?"), in „…“-Anführungszeichen, auf 40 Zeichen gekürzt.
- Bei Löschvorgängen mit nicht offensichtlicher Nebenwirkung (Gruppe
  löschen verschiebt Apps statt sie zu löschen) zusätzliche zweite Zeile
  mit der Konsequenz.
- Angewendet in `todo.html` (beide Formulare), `werkstatt_app.html`
  (beide Formulare), `einkauf.html` (gemeinsames Makro `item_card`,
  betrifft offene + erledigte Artikel automatisch), `startseite.html`
  (Gruppe löschen, Formulierung an den neuen Stil angeglichen).

### Stolperstein: `tojson` in einem HTML-Attribut

Erster Versuch brach: `{{ text|tojson }}` direkt in `onsubmit="…"` liefert
einen Jinja-`Markup`-String, der **bewusst nicht** HTML-escaped wird (er
ist für die Einbettung in `<script>`-Blöcke gedacht). Innerhalb eines
doppelt gequoteten HTML-Attributs beendet das eingebettete `"` das
Attribut vorzeitig – der Browser bekam ein kaputtes `onsubmit="return
confirm("`, das JS parste nicht, der `return`-Wert war `undefined` (nicht
`false`) → das Formular wurde **trotzdem** abgeschickt, ganz ohne
Dialog. Live an echten Todos beobachtet (Löschen ohne jede Rückfrage).
Fix: zusätzlich `|forceescape` anhängen, das erzwingt HTML-Escaping auch
für als „sicher" markierte Werte – der Browser bekommt `&#34;…&#34;`,
entschärft das beim Parsen korrekt zurück zu `"`, und `confirm()` erhält
den richtigen String.

### Testergebnisse (Playwright, Dialog-Events abgefangen, Wegwerf-Admin-Nutzer)

Für alle vier Stellen (Todo, Werkstatt, Einkauf, Startseite-Gruppe)
geprüft:

- Dialog-Text enthält die richtige Bezeichnung: ✅ (z. B. `„ZZZ_Item_…“
  löschen?`)
- Abbrechen (dismiss) → Eintrag bleibt bestehen: ✅
- Bestätigen (accept) → Eintrag verschwindet: ✅

Alle Testartikel/-todos/-wünsche/-gruppen sowie der Wegwerf-Nutzer
danach restlos entfernt.

### Auslieferungspaket

`deploy/portal-v14.tar.gz` (v13 hatte noch den `tojson`-Escaping-Bug,
direkt in v14 korrigiert, bevor an Andi ausgeliefert) – nur `portal` neu
gebaut/gestartet.

---

## 2026-07-27 – Wunsch #11 + #16: Aufgaben-Umbenennung + Rezepte-App (portal-v15)

### Wunsch #11: Todos → Aufgaben (reine Umbenennung, keine Architekturänderung)

Slug, Tabelle (`todos`), URL-Präfix (`/a/todo/…`) und Funktionsnamen
(`todos_neu()`) bleiben unverändert – nur der für Nutzer sichtbare Name
ändert sich:

- `todo.html`: Nav-Titel „✅ Todos" → „✅ Aufgaben", Eingabe-Platzhalter
  „Neues Todo…" → „Neue Aufgabe…"
- `04_todo.py`: Push-Titel „Neues Todo 📋" → „Neue Aufgabe 📋"
- `hilfe.html`: Beschreibungstext angepasst
- `00_kern.py`: `_CORE_APPS`-Eintrag auf „Aufgaben" geändert; da
  `INSERT OR IGNORE` bestehende Zeilen nicht anfasst, zusätzlich ein
  einmaliges `UPDATE apps SET name='Aufgaben' WHERE slug='todo' AND
  name='Todos'` in `_init_db()` ergänzt (läuft bei jedem Start, ist nach
  dem ersten Mal ein No-op – gleiches Muster wie der bestehende
  `wuensche.erledigt_am`-Fixup).

App-Kachel auf der Startseite zeigt automatisch den neuen Namen (kommt aus
`apps.name`), keine Änderung an `startseite.html` nötig.

### Wunsch #16: Neue App „Rezepte" 🍲

Neue Tabellen `rezepte` (Name, Anleitung, Ersteller) und `rezept_zutaten`
(je Rezept eine Zutatenliste mit Position). Neues Modul
`teile/11_rezepte.py`:

- `/a/rezepte/<token>/` – Liste aller Rezepte + Neu-Formular (Name,
  Zutaten als Textarea – eine Zutat pro Zeile –, Zubereitung als
  Freitext)
- `/a/rezepte/<token>/<id>` – Rezept-Ansicht: Zutatenliste, je Zutat ein
  „🛒 Fehlt"-Knopf, Zubereitung, Löschen-Knopf
- `/a/rezepte/<token>/zutat/<id>/einkaufen` (POST, JSON) – legt die
  fehlende Zutat direkt in `einkauf_eintraege` an (Kategorie „Sonstiges"),
  kein Import zwischen den App-Modulen nötig, einfacher direkter
  INSERT wie überall sonst auch (Apps teilen sich ohnehin dieselbe DB)
- Löschen mit der app-übergreifenden Sicherheitsabfrage-Konvention aus dem
  letzten Fix (`|tojson|forceescape`)
- Detail-Seite hat einen `←`-Zurück-Link zur Rezeptliste (Konvention:
  keine Sackgassen, siehe Gedächtnis-Notiz)
- Hilfe-App um einen Rezepte-Eintrag in der App-Liste sowie einen eigenen
  Erklärabschnitt ergänzt (Konvention: neue Features immer dokumentieren)
- App bei allen 4 echten Nutzern manuell freigeschaltet (gleiches
  Vorgehen wie bei den bisherigen neuen Apps – kein Auto-Grant für
  `rezepte`, nur `hilfe`+`einkauf` sind auto-granted)

### Testergebnisse (Playwright, Wegwerf-Nutzer, danach restlos entfernt)

- Aufgaben: Nav-Titel, Eingabe-Platzhalter und Kachel auf der Startseite
  zeigen „Aufgaben", nirgends mehr „Todos": ✅
- Rezept anlegen mit 3 Zutaten + 3-zeiliger Zubereitung → Weiterleitung
  zur Detail-Seite, alle 3 Zutaten und der vollständige Text (mit
  Zeilenumbrüchen) korrekt angezeigt: ✅
- „🛒 Fehlt" angeklickt → Button wechselt sofort zu „✓ Auf Liste"
  (AJAX, ohne Reload), Zutat landet tatsächlich in
  `einkauf_eintraege`: ✅ (per DB-Check verifiziert)
- Zurück-Link von der Detail- zur Listenansicht vorhanden und korrekt: ✅
- Rezept löschen: Abbrechen behält das Rezept, Bestätigen löscht es und
  leitet zur Liste zurück, Rezept dort verschwunden: ✅
- Test-Rezept, Test-Zutat-Einkaufseintrag und Wegwerf-Nutzer danach
  restlos entfernt.

### Auslieferungspaket

`deploy/portal-v15.tar.gz` – nur `portal` neu gebaut/gestartet.
