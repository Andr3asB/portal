# server.md – Aktueller Systemzustand

*Letzte Aktualisierung: 2026-08-11 (portal-v206: Backup repariert - Live-DB nicht mehr im Archiv, Wiederherstellung laeuft ueber die Snapshots, siehe unten)*

## ⚠️ Wiederherstellung aus einem Backup (geaendert mit v206)

Die Backup-Tarballs auf dem NAS enthalten **keine `./portal.db` mehr**. Die
Datenbank liegt darin unter `./snapshots/portal-<zeitstempel>.db` - den
**neuesten** davon nach `/data/portal.db` kopieren, dann `portal` neu starten.

Grund: `tar` las die Live-Datenbank, waehrend das Portal hineinschrieb. Das
brach an drei von sechs Naechten mit `tar exit 1` ab (07./08./10.08.2026) und
lieferte auch an den uebrigen keine garantiert konsistente Datei. Die
Snapshots daneben entstehen ueber `sqlite3.Connection.backup()` und sind
WAL-korrekt in sich stimmig. Details im journal.md, 11.08.2026.

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

## hae-Server-Relay (Caddy, Wunsch #62)

Zweiter interner Site-Block, ebenfalls nur auf `172.30.0.10` gebunden (Port `2021`,
nie auf 10.0.0.200 oder von außen erreichbar): reicht Anfragen von `portal` 1:1 an
den hae-Server weiter (`10.0.0.199:443`, IP statt Hostname, siehe
Umgebungsvariablen-Abschnitt für die Begründung). `portal` ruft
`http://caddy:2021/api/workouts` auf, der `api-key`-Header bleibt beim
Durchreichen erhalten.

## Security-Headers (Caddy)

Caddy setzt folgende Headers auf alle Antworten:

```
Referrer-Policy: no-referrer
X-Content-Type-Options: nosniff
Content-Security-Policy: frame-ancestors https://wir4.16schwaben.de
-Server  (entfernt)
```

**Wunsch #107 (2026-08-02): Einbettung in Home Assistant per iFrame.**
Andi wollte das Portal als iFrame ins Home-Dashboard (Home Assistant unter
`https://wir4.16schwaben.de`, Kiosk-Bildschirm 24" Portrait im Esszimmer,
Linux/Chrome, KEINE Android-Kiosk-App) einbetten.

- **Ursache/Blocker:** `X-Frame-Options: DENY` verbot bis dahin JEDES
  Einbetten, unabhängig von der Quelle - der einzige technische Blocker.
- **Fix:** `X-Frame-Options` ersetzt durch
  `Content-Security-Policy: frame-ancestors https://wir4.16schwaben.de` -
  erlaubt Einbetten NUR von dieser einen Quelle, alle anderen bleiben
  weiterhin blockiert (kein pauschales `frame-ancestors *`, das wäre ein
  Sicherheitsrückschritt gegenüber vorher). `frame-ancestors` ersetzt
  `X-Frame-Options` auf allen relevanten modernen Browsern (Chrome, Safari)
  vollständig - beide gleichzeitig zu setzen wäre widersprüchlich, ein
  zusätzliches `X-Frame-Options: DENY` würde weiterhin blocken, selbst wenn
  die CSP es erlaubt.
- **Sonst keine Code-Änderung nötig:** kein Frame-Busting-JS im Portal
  vorhanden (`grep` bestätigt), PWA-Manifest (`display:standalone`) ist für
  die iFrame-Einbettung irrelevant (wirkt nur bei "Zum Home-Bildschirm
  hinzufügen"), Service Worker/Sync-Polling funktionieren unverändert
  innerhalb des iFrames (gleicher Origin, keine Drittanbieter-Cookie-
  Problematik, da first-party).
- **Verifiziert:** Header per `curl -I` bestätigt. Zusätzlich mit einer
  lokalen Testseite auf einer NICHT erlaubten Quelle (`http://localhost`)
  geprüft, dass das Einbetten dort weiterhin blockiert wird (Netzwerk-Log
  zeigt die geblockte Anfrage, direkter Abruf derselben URL liefert dagegen
  sauber 200) - die eigentliche Freigabe für `wir4.16schwaben.de` selbst
  konnte von hier aus nicht getestet werden (kein Zugriff auf dieses
  System), sollte aber nach demselben Mechanismus funktionieren.
- **Noch offene, bewusst NICHT automatisch entschiedene Punkte** (Andis
  Entscheidung, keine Pflicht zur Umsetzung):
  - **Welche URL genau eingebettet wird.** Das Portal ist pro Nutzer über
    eigene Tokens personalisiert (`/p/<token>` zeigt Namen/Gruß/eigene
    Gruppen des jeweiligen Nutzers). Für einen gemeinsamen Küchen-/
    Esszimmer-Bildschirm bietet sich eher ein bestimmter, bewusst gewählter
    Token an (z. B. Andis eigener, oder ein eigens dafür angelegter
    zusätzlicher Nutzer/Grant) statt zufällig irgendeinen personalisierten
    Link zu verwenden - Andi muss diese URL selbst im Home-Assistant-
    Dashboard hinterlegen.
  - **Layout auf einem breiten 24"-Portrait-Bildschirm.** Alle Templates
    sind mobile-first mit Grid/Flexbox responsiv gebaut (kein einziges
    `max-width` auf der ganzen Seite), rendern auf einem breiten Bildschirm
    also technisch fehlerfrei, aber ggf. recht breit/spärlich gefüllt statt
    optimiert (z. B. die App-Kacheln würden sich in sehr viele Spalten
    aufteilen). Kein Blocker, aber ein möglicher Folge-Wunsch, falls das
    optisch stört.
  - **Push-Banner beim ersten Öffnen:** Falls für den gewählten Token noch
    kein Push-Abo besteht, erscheint einmalig der "Benachrichtigungen
    aktivieren"-Banner auf der Startseite - für einen dauerhaft offenen
    Kiosk-Bildschirm vermutlich unerwünscht, lässt sich aber durch
    einmaliges Wegtippen oder durch Aktivieren/Ablehnen der Browser-
    Berechtigung dauerhaft loswerden, keine Code-Änderung nötig.

### Wie der Esszimmer-Bildschirm startet (Stand 2026-08-06)

```
/usr/lib/chromium/chromium \
  --kiosk --noerrdialogs --disable-translate \
  --disable-gpu --disable-software-rasterizer \
  --disable-features=TranslateUI \
  https://wir4.16schwaben.de/
```

Meldet sich als `Mozilla/5.0 (X11; CrOS x86_64 …)`. Drei Eigenschaften, die
für den Sitzungsumbau (Wunsch #140) zählen:

- **Kein `--user-data-dir`, kein `--incognito`** → Standardprofil, bleibt über
  Neustarts erhalten. Deshalb überlebt dort ein Sitzungs-Cookie (live
  gemessen: 134 Anfragen, **eine** Sitzung).
- **Geladen wird Home Assistant, nicht das Portal.** Das Portal hängt als
  iFrame im HA-Dashboard, und diese iFrame-Adresse trägt weiterhin den Token.
  **Der Kiosk hängt damit nie am Cookie** – selbst nach einem Profilverlust
  oder Neuaufsetzen holt er sich beim nächsten Start über den Token eine neue
  Sitzung. Das ist die Rückfallebene, die den Bildschirm unabhängig von allem
  Neuen macht.
- **`--kiosk` heißt: keine Adresszeile, keine Bedienung.** Erschiene dort je
  ein Anmeldebildschirm, könnte niemand etwas dagegen tun. Die Regel
  „**niemals automatisch auf eine Anmeldeseite umleiten**" ist deshalb
  verbindlich und nicht bloß Vorsicht: fehlende Autorisierung führt weiterhin
  zu `denied.html` bzw. `abort(403)`.

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
OPENROUTER_API_KEY=<Key von openrouter.ai, mit Ausgabenlimit im OpenRouter-Konto>
HAE_API_URL=http://caddy:2021/api/workouts
HAE_API_KEY=<Read-Token vom hae-Server, NICHT der Write-Token der iPhone-Automation>
TOKEN_KEY=<32 Byte Hex, Schluessel fuer die Token-Verschluesselung (Wunsch #129)>
SITZUNG_AUSSTELLEN=1     # Wunsch #140, Stufe 1
CSRF_MODUS=scharf        # Wunsch #140, Stufe 2: aus | beobachten | scharf
PORTAL_ORIGIN=           # leer = aus der Anfrage ableiten
SITZUNG_KONSUMIEREN=1    # Wunsch #140, Stufe 3
TOKENFREIE_URLS=1        # Wunsch #140, Stufe 4
CSP_MODUS=scharf         # Wunsch #142, Stufe 5: aus | beobachten | scharf
GEBURTSTAGS_ERINNERUNGEN=1  # Wunsch #145: taeglicher Erinnerungs-Lauf
KI_GUTHABEN_WACHT=1         # Wunsch #183: stuendlicher Blick aufs OpenRouter-Guthaben
```

`PORTAL_ORIGIN`, `GEBURTSTAGS_ERINNERUNGEN` und `KI_GUTHABEN_WACHT` stehen
heute NICHT in der echten `.env` - sie greifen mit ihrer Voreinstellung (leer
bzw. 1). Sie sind hier aufgefuehrt, weil man sie dort eintragen kann und die
Voreinstellung dann uebersteuert wird; `env_file: .env` reicht jede Zeile
durch.

Die vier `#140`-Schalter sind die Notausstiege der jeweiligen Umbaustufe: auf
`0` setzen, `docker compose up -d portal`, fertig - kein Rebuild, kein Paket.
`TOKENFREIE_URLS=0` stellt die Links mit Token wieder her; die token-freien
Routen bleiben dabei bestehen, werden aber von nichts mehr verlinkt.

**Wichtig:** VAPID_PRIVATE_KEY darf NICHT geändert werden, solange aktive Push-Abos existieren.
Ein neuer Private Key macht alle bestehenden Subscriptions ungültig (Nutzer müssen neu opt-in).
Key-Rotation → alle `push_abos` löschen, dann neu generieren.

OPENROUTER_API_KEY ist ein gemeinsamer Server-Key für alle Nutzer – das Kontingent
pro Nutzer wird NICHT von OpenRouter selbst begrenzt, sondern von der App über
`users.ki_token_limit` + `ki_nutzung` durchgesetzt (siehe `ki_anfrage()` in
`00_kern.py`). Das Ausgabenlimit im OpenRouter-Konto selbst ist das globale
Backstop-Netz für den Fall, dass die App-Logik einen Fehler hätte.

SECRET_KEY wird aus der Umgebung gelesen; fehlt er, generiert Flask einen ephemeren Key
(Sessions überleben keinen Neustart ohne gesetzten Key).

HAE_API_URL zeigt bewusst auf den caddy-internen Relay (`:2021`, siehe
Caddyfile-Abschnitt), nicht direkt auf `health-api.16schwaben.de` – `portal`
hängt nur im Bridge-Netz und kann die macvlan-IP des hae-Servers
(10.0.0.199, gleicher Host) nicht selbst erreichen. Siehe journal.md
2026-07-29 für die volle Herleitung.

## Externe Python-Abhängigkeiten mit Asset-Inhalt

- **`dicebear-core` + `dicebear-styles`** (Tierbaukasten, Mensch-Figur,
  2026-07-29): rendert Avataaars-SVGs komplett lokal/offline, keine
  Netzwerkanfrage zur Laufzeit. **Wichtig**: nicht zu verwechseln mit dem
  gleichnamigen Drittanbieter-Wrapper `dicebear` auf PyPI (von jvherck),
  der nur die öffentliche `api.dicebear.com`-API aufruft – der wird hier
  NICHT verwendet. Avataaars-Stil von Pablo Stanley, Lizenz "Free for
  personal and commercial use" (avataaars.com), Engine MIT-lizenziert.
  Style-Optionsschema (Frisuren/Farben/etc.) liegt als JSON in
  `dicebear-styles` und wird einmalig beim Modulimport geladen
  (`_AVATAAARS_STYLE` in `15_tierbaukasten.py`).

## Externe Frontend-Assets (lokal gebündelt, Wunsch #119)

- **`twemoji.min.js`** (`src/static/twemoji.min.js`, Version 14.0.2) +
  passende SVG-Grafiken (`src/static/twemoji/svg/<codepoint>.svg`, 84
  Dateien, ~250 KB): ersetzt jedes im DOM erkannte Emoji-Zeichen durch ein
  `<img class="emoji">` mit lokal gehostetem SVG, unabhängig davon, ob das
  Betriebssystem des Betrachters eine Color-Emoji-Schriftart mitbringt (auf
  manchen Linux-Chrome-Installationen, u. a. Kiosk-Aufbauten, fehlt diese -
  Emoji blieben dort komplett unsichtbar). Aufruf in `base.html`, läuft
  einmalig nach dem initialen Seitenaufbau (`twemoji.parse(document.body,
  {base:'/static/twemoji/', folder:'svg', ext:'.svg'})`) - `folder:''`
  funktioniert NICHT (leerer String ist in JS falsy, twemoji.js faellt
  dann still auf seinen 72x72-PNG-Standardordner zurueck, live als Bug
  gefunden - deshalb "svg" als echter Unterordnername, Dateien liegen
  entsprechend unter .../twemoji/svg/, nicht direkt unter .../twemoji/).
  Erfasst NUR zu diesem Zeitpunkt bereits im DOM vorhandene Emoji, nicht
  später per JS neu eingefügten Text (z. B. Toast-Nachrichten) - bewusst
  so entschieden,
  deckt die weit überwiegende Mehrheit ab (serverseitig gerenderte
  Templates), volle Laufzeit-Abdeckung wäre ein deutlich größerer Eingriff
  gewesen. Nur die Codepoints heruntergeladen, die im Portal tatsächlich
  vorkommen (kein kompletter Font/keine komplette Twemoji-Sammlung - wäre
  unnötig groß). 15 im Portal verwendete Zeichen (← ↑ → ⋮ ⌂ ▲ ▸ ▼ ○ ★ ☰ ✎
  ✓ ✕ ⠿) haben keine Twemoji-Grafik, weil Twemoji sie nicht als "Emoji"
  führt (reine Text-Symbole) - unproblematisch, die rendern schon ohne
  Emoji-Font überall normal, genau die "sicheren" Zeichen also.
  **Achtung, Stolperfalle (Wunsch #122):** ob ein Zeichen "reines
  Textsymbol" oder "Emoji" ist, lässt sich NICHT am Aussehen ablesen. ◀ ▶
  (U+25C0/U+25B6) sehen aus wie ▲ ▼, werden von Twemoji aber sehr wohl
  umgewandelt - die fehlenden SVGs ergaben zwei 404er und zwei leere
  Drehknöpfe im Tierbaukasten (erst bei Wunsch #122 aufgefallen, seit
  Wunsch #119 vorhanden). **Bei jedem neuen Zeichen deshalb prüfen, ob
  `raw.githubusercontent.com/twitter/twemoji/master/assets/svg/<cp>.svg`
  existiert (HTTP 200), und die Seite anschließend live auf 404er
  kontrollieren** - der reine Blick ins Template genügt nicht. Code MIT-lizenziert,
  Grafiken CC-BY 4.0 (Twitter/Twemoji) - Attribution laut deren eigener
  README per Erwähnung im Quellcode ausreichend (siehe Kommentar in
  base.html).

## Externe Datenquellen zur Laufzeit (APIs)

Alle drei werden zur Laufzeit per `urllib` abgefragt (kein zusätzliches
pip-Paket) und sind so gebaut, dass ein Ausfall nur ein „gerade nicht
abrufbar"-Kästchen erzeugt statt eines Fehlers.

| Quelle | Genutzt von | Auth | Abruf | Anmerkung |
|--------|-------------|------|-------|-----------|
| hae-Server (`HAE_API_URL`, über Caddy-Relay `:2021`) | `14_sportschau.py` | `api-key`-Header aus `.env` | live je Seitenaufruf | Eigener Server im Haus, siehe „hae-Server-Relay" oben |
| handball.net Widget-API (`www.handball.net/a/sportdata/1/widgets/…`) | `18_tvb.py` (Spiele, Tabelle) | keine | live je Seitenaufruf (Antworten 5–10 KB) | Inoffiziell: das ist der Endpunkt, den handball.net für seine einbettbaren Vereins-Widgets selbst aufruft. Nur `table`, `schedule`, `team-schedule` existieren – **kein** Kader/Spieler-Endpunkt, und `club/<id>/schedule` (Wunsch #151, s.u.) |
| Open Food Facts (`world.openfoodfacts.org/api/v2/product/<ean>.json`) | `10_einkauf.py` (Barcode-Erfassung, Wunsch #143) | keine | live je Scan, nichts gecacht | Freie Produktdatenbank, rund 420.000 Produkte fuer Deutschland. Unbekannte Codes beantwortet sie mit HTTP 404 - das ist der Normalfall bei Nicht-Lebensmitteln, kein Fehler. Der Code wird vorher gegen `\A[0-9]{6,14}\Z` geprueft, weil er in den Pfad der Abfrage eingesetzt wird |
| HPI-API der HBL (`hpi.handball-bundesliga.de/api/…`) | `18_tvb.py` (Kader) | keine | gecacht in `tvb_kader`, max. 6 h alt | Handball Performance Index, offizielle Leistungskennzahl der Liga. Antwort ~400 KB (ganze Liga) – deshalb Cache, anders als bei handball.net |

Gemeinsam gilt: Bilder/Assets dieser Quellen werden **nicht** eingebunden
(z. B. Spielerfotos vom CDN `images.dc.prod.cloud.atriumsports.com`) – das
Portal lädt im Frontend nichts von fremden Hosts, siehe Wunsch #119 und
die Privacy-Überlegung dazu in `18_tvb.py`.

## Code-Struktur (src/)

```
app.py               – Flask-App, lädt nummerierte Module aus teile/ automatisch;
                       lädt VAPID_PRIVATE_KEY/PUBLIC_KEY/SUBJECT + OPENROUTER_API_KEY aus .env
glogging_redact.py   – Gunicorn RedactingLogger: ersetzt Tokens in Logzeilen durch <redacted>
manage.py            – CLI: createadmin, adduser, addapp, grant, listusers,
                       listwuensche, listtodos, wunsch_erledigt, backlog,
                       ki_modell/ki_stimme/listki (Wunsch #81: Modell/Stimme je
                       KI-Zweck bzw. je Vokabeln-Sprache ohne Deploy ändern)
teile/
  __init__.py        – registriert 00_kern als teile.kern, seit Wunsch #90
                       zusaetzlich 04_todo als teile.todo (erster Cross-Modul-
                       Import ausserhalb von kern - kinderplan braucht
                       serien_pool_liste()/serie_einsortieren())
  00_kern.py         – DB-Schema, get_db()/new_db(), grant(), new_token(), to_int(),
                       push_send() (VAPID, Thread), ki_anfrage() (generischer KI-Aufruf
                       über OpenRouter, Token-Kontingent pro Nutzer/Monat über
                       users.ki_token_limit, protokolliert in ki_nutzung – von jedem
                       KI-Feature nutzbar, nicht nur Rezept-Import; optionaler
                       `bilder`-Parameter für Vision-Eingabe, Wunsch #80),
                       ki_modell_fuer(zweck) (Wunsch #81 – Grundprinzip: Modell
                       je Verwendungszweck kommt aus ki_konfiguration statt fest
                       im Code, Fallback KI_MODELL), ki_stimme_fuer(sprache_id) +
                       ki_text_zu_sprache() (TTS über OpenRouter /audio/speech,
                       mp3→pcm-Fallback + WAV-Verpackung falls das Modell nur
                       PCM liefert, siehe Bekannte Issues), /health, _init_db(),
                       _auto_grant_all() (hilfe + einkauf an alle Nutzer),
                       @app.after_request setzt Service-Worker-Allowed: / nur
                       fuer /static/sw.js (siehe sw.js weiter unten)
  01_start_token.py  – / (Landing), /p/<token> (Startseite mit Gruppen),
                       POST /p/<token>/reorder (Apps), /gruppe/reorder (Gruppen selbst),
                       /gruppe/neu, /gruppe/<id>/umbenennen, /gruppe/<id>/loeschen.
                       `.tile` in startseite.html: `touch-action:none` gilt seit
                       Wunsch #103 nur noch mit `.edit-mode` davor (statt immer) -
                       vorher blockierte es das normale Scrollen der Seite, sobald
                       der Finger beim Wischen auf einer Kachel aufsetzte, auch
                       ausserhalb des Bearbeiten-Modus, wo der Pointer-Drag dafuer
                       gar nicht aktiv ist.
  02_werkstatt.py    – POST /wunsch (JSON, identifiziert Nutzer über Token);
                       _ansicht_aus_pfad() verdichtet window.location.pathname
                       zu "app_slug/unterseite", token-frei (Wunsch #47).
                       Wunsch #152: nimmt zusaetzlich `prioritaet` entgegen,
                       uebernimmt sie aber NUR von einem Admin und nur aus
                       WUNSCH_PRIORITAETEN (Kern). Die Auswahl im ✨-Dialog
                       steht in base.html hinter `user.is_admin` - darauf
                       darf man sich nicht verlassen, /wunsch nimmt JSON und
                       ein selbstgebauter POST umgeht jedes Template. Ein
                       unerlaubter Wert wird zu NULL, der Wunsch selbst wird
                       trotzdem gespeichert (ein still verworfener Vorschlag
                       waere der schlechtere Ausgang). Voreinstellung im
                       Dialog ist `zurueckgestellt` = die einzige Prioritaet,
                       die ein Sammelauftrag nie anfasst.
  03_admin.py        – /a/admin/<token>/ Admin-Bereich: Nutzer (mit Rolle), Grants,
                       QR-Codes, _clean_farbe() (Hex-Validierung).
                       Wunsch #154: /geraete listet alle Sitzungen mit Person,
                       Geraet, Anmeldung und letzter Benutzung;
                       /geraete/<sid>/abmelden entfernt GENAU EINE Sitzung.
                       Unterschied zu "Neuer Zugang + QR": dort werden alle
                       Token neu erzeugt und damit saemtliche Geraete des
                       Nutzers ausgesperrt - hier bleibt der Link gueltig.
                       `_geraet_lesbar()` prueft von speziell nach allgemein
                       (Edge/Opera nennen sich auch "Chrome", jeder Chrome
                       nennt sich auch "Safari").
  04_todo.py         – /a/todo/<token>/ Aufgabenliste; todos_neu() mit Push-Deep-Link;
                       Ziel: Person (zugewiesen_an, wie bisher) ODER eine/mehrere
                       Rollen bzw. "alle" (zugewiesen_rollen, kommagetrennt,
                       Sentinel "alle" – Wunsch #39); nur Rollen/Alle-Ziel landet
                       initial im Backlog statt Offen; /status/<id> (4 Stufen:
                       backlog/offen/in_arbeit/erledigt) – Kind/Gast dürfen auch bei
                       passender Rolle/"alle" ändern, nicht nur bei eigener Zuweisung,
                       seit Wunsch #214 aber NICHT mehr bei privat=1: der
                       Weg über die Rollenzuweisung ist der einzige, der an
                       `_visible_todos` vorbeiführt – ein privates Todo mit
                       Rollenziel war unsichtbar und trotzdem änderbar (F-06);
                       /bearbeiten/<id> (Wunsch #43: alle Felder – Text, Ziel
                       Person/Rolle(n)/Alle, Privat – gleiche UX wie /neu; Eltern
                       alle/Kinder eigene bzw. rollenpassende; Status bleibt beim
                       Bearbeiten unangetastet; nur Textänderungen landen im Verlauf).
                       Wiederkehrende Aufgaben-Vorlagen/Pool (Wunsch #90):
                       /serien (GET+POST, Template todo_serien.html) verwaltet
                       todo_serien (Inhalt + Wiederkehr-Regel: 'intervall' X Tage
                       ODER 'wochentag', mehrere Wochentage gleichzeitig moeglich
                       seit Wunsch #112 - `feste_wochentage` kommagetrennt statt
                       des alten `fester_wochentag`, siehe Migrations-Kommentar in
                       00_kern.py). serien_pool_fuer_tag()/serie_einsortieren()
                       sind fuer andere Module gedacht (importiert von kinderplan
                       ueber den Alias teile.todo, siehe teile/__init__.py) - eine
                       eingesetzte Instanz ist ein normales todos-Row mit
                       serie_id+plan_tag gesetzt (Wunsch #92, echtes Datum statt
                       Wochentag-Zahl), taucht mit 🔁-Chip in der normalen
                       Todo-Liste auf. Seit Wunsch #113 ist die Pool-
                       Verfuegbarkeit PRO KALENDERTAG zu pruefen
                       (`serie_verfuegbar_am()`, ersetzt das alte, nur einmal
                       global auswertbare `_serie_ist_im_pool()`): Anker fuer
                       'intervall' ist jetzt der zuletzt EINGEPLANTE Tag
                       (MAX(plan_tag), nicht mehr der Erledigt-Zeitpunkt), und
                       Verfuegbarkeit ist periodisch (Differenz zum Anker muss
                       ein positives Vielfaches von intervall_tage sein) statt
                       "einmal Schwelle erreicht, fuer immer verfuegbar" - eine
                       Serie laesst sich dadurch mehrere Tage im Voraus einplanen,
                       auch wenn eine fruehere Instanz noch offen ist. Ein Tag,
                       der bereits eine eigene Instanz dieser Serie hat, wird nie
                       nochmal angeboten (unabhaengig vom Intervall/Wochentag).
                       Eingabeformular seit Wunsch #93 hinter "+ Neue Aufgabe"
                       eingeklappt (gleiches Muster wie einkauf.html, Wunsch
                       #85: sessionStorage `todo_formular_offen`). "🔍 Filtern"
                       (Wunsch #94) nach Benutzer (erstellt_von ODER
                       zugewiesen_an) und/oder Status, rein clientseitig ueber
                       data-status/data-nutzer je Aufgabenkarte - bewusst ueber
                       sessionStorage (`todo_filter`) persistent ueber Reloads
                       hinweg, bis explizit zurueckgesetzt (anders als Einkaufs
                       Filtern, Wunsch #87, das sich bei jedem Reload zuruecksetzt)
  05_werkstatt_app.py – /a/werkstatt/<token>/ Wunschliste; Admin: Priorität setzen
                       (niedrig/mittel/hoch/sehr_hoch/zurueckgestellt – Wunsch #61;
                       zurueckgestellt sortiert als letztes, siehe Docstring am
                       Dateianfang: solche Wünsche NIE automatisiert umsetzen, auch
                       nicht bei "implementiere alle Wünsche"), erledigen, löschen;
                       POST /titel/<id> (JSON) für Claude-Titel. Wunsch #101: Karte
                       antippen klappt eine Detailansicht auf (Wunsch, Benutzer,
                       Wunsch-/Implementierungsdatum, `umsetzung` - was genau
                       implementiert wurde). `umsetzung` wird NICHT über die Web-UI
                       gesetzt, sondern über `manage.py wunsch_erledigt <id>
                       "Beschreibung"` (zweites CLI-Argument optional, siehe
                       manage.py) - ab jetzt bei jedem Wunsch-Abschluss mitgeben.
                       `_de_datum()`-Jinja-Filter formatiert die SQLite-Zeitstempel
                       ("YYYY-MM-DD HH:MM:SS") lesbar als "DD.MM.YYYY, HH:MM Uhr".
  06_geholfen.py     – /a/geholfen/<token>/ Tipp-Grid + 10-Tage-Heatmap (erst
                       Eltern, dann Kinder, je alphabetisch – Wunsch #44);
                       /verlauf (letzte 50 Einträge, eigene Seite, Eltern/Admin
                       können je Eintrag Zeit/Nutzer/Aufgabe bearbeiten oder löschen
                       über /eintrag/<id>/bearbeiten + /eintrag/<id>/loeschen);
                       /uebersicht (Kalender 30 Tage, 7-Tage-Stats, admin-only)
                       + Aufgaben; eltern/admin können für andere eintragen;
                       /aufgaben unterstützt seit Wunsch #96 auch Umbenennen
                       (action=umbenennen, eigenes ✏️-Panel je Aufgabe)
  07_push.py         – /push/vapid-public-key, /push/subscribe, /push/unsubscribe
  08_settings.py     – /einstellungen/<token> (Dark Mode), /manifest/<token>.json
                       (personalisiertes PWA-Manifest mit Nutzer-Token als start_url)
  09_hilfe.py        – /a/hilfe/<token>/ Hilfe- und Erklärungsseite (alle Apps)
  10_einkauf.py      – /a/einkauf/<token>/ Gemeinsame Einkaufsliste mit Kategorien
                       (aus einkauf_kategorien, editierbar), Läden, Angebot-
                       Markierung;
                       **Barcode (Wunsch #143):** /barcode nimmt ein FOTO
                       entgegen und liest den Code SERVERSEITIG (zxing-cpp).
                       Nicht im Browser, weil `BarcodeDetector` weder auf iOS
                       noch in Chrome unter Windows existiert (beides
                       nachgemessen) - sie fehlt also ausgerechnet auf den
                       Geraeten, mit denen eingekauft wird. Das Foto-Muster ist
                       dasselbe wie beim Rezept-/Vokabel-Import, bewusst OHNE
                       capture="environment" (Wunsch #106). Danach
                       Open-Food-Facts-Abfrage und KI-Kategorie; beides sind
                       Zutaten, keine Voraussetzungen - faellt eines aus,
                       kommt trotzdem so viel zurueck wie moeglich. Gespeichert
                       wird NICHTS, das Ergebnis fuellt nur das Formular vor.
                       **Live-Aktualisierung (Wunsch #146):** /stand liefert
                       den Fingerabdruck, das Frontend tauscht bei Aenderung
                       nur `#einkauf-liste` aus statt neu zu laden - deshalb
                       laeuft das auch im Einkaufsmodus, ohne Scrollposition
                       und Modus zu verlieren; /bearbeiten/<id> speichert Name+Kategorie+Angebot
                       in einem Rutsch (ein Edit-Panel, ein Speichern-Button);
                       _clean_angebot() erzwingt konsistenten Zustand (nie Angebot=1
                       ohne gültigen Markt); _kategorien_aktiv()/_clean_kategorie_id()
                       (Fallback auf "Sonstiges" bei ungültiger/inaktiver Kategorie);
                       Artikel mit deaktivierter Kategorie fallen unter "Ohne
                       Kategorie", statt zu verschwinden;
                       /a/einkauf/<token>/laeden (Admin, Hamburger-Menü);
                       /a/einkauf/<token>/kategorien (Admin, Wunsch #37: anlegen/
                       umbenennen/deaktivieren, Hamburger-Menü); /kategorien/reorder
                       (Admin, JSON, Wunsch #38: Sortierreihenfolge per Drag & Drop,
                       gleiches Pointer-Events-Muster wie home_gruppen). Eintragen-
                       Formular standardmässig eingeklappt hinter einem "+ Neu"-Knopf,
                       bleibt nach dem Oeffnen ueber mehrere Eintraege/Reloads offen
                       (sessionStorage-Flag `einkauf_formular_offen`, Wunsch #85).
                       Angebot kann mehrere Maerkte gleichzeitig haben (Wunsch #86):
                       n:m-Tabelle einkauf_eintrag_laeden statt des alten einzelnen
                       laden_id-Felds (bleibt als totes Altfeld liegen); Markt-Chips
                       toggeln unabhaengig, Auswahl als kommagetrennte laden_ids im
                       Formular. "Filtern"-Knopf (Wunsch #87 Teil 1) neben "+ Neu":
                       clientseitiger Filter nach Markt und/oder "Nur Angebote" ueber
                       data-angebot/data-laeden an jeder Artikelkarte, kein Server-
                       Roundtrip, setzt sich bei jedem Reload zurueck. "🛒 Einkauf
                       starten" (Wunsch #87 Teil 2): Marktwahl, dann body.einkaufsmodus
                       blendet Formular/Filter/Knopfleiste aus, zeigt nur Artikel
                       relevant fuer den gewaehlten Markt (eigene Angebote + Artikel
                       ohne Marktbindung; Angebote bei ANDEREM Markt bleiben bewusst
                       ausgeblendet - fuer einen anderen Einkaufstrip vorgemerkt),
                       groessere Tap-Flaechen fuer die Bedienung im Laden.
                       /stand (Wunsch #100, JSON): kompakter Sync-Fingerabdruck
                       "Anzahl:juengster-geaendert-Zeitstempel" (_stand()) - das
                       Frontend pollt das alle 30s sowie sofort bei visibilitychange/
                       pageshow (App aus dem Hintergrund zurueck) und laedt bei
                       Aenderung neu, ausser das Namensfeld hat Text oder ein
                       Bearbeiten-Panel ist offen (dann naechster Versuch) oder der
                       Einkaufsmodus laeuft gerade (bewusst nicht stoeren). `geaendert`-
                       Spalte wird bei jedem INSERT/UPDATE explizit gesetzt, nicht ueber
                       einen Spalten-Default (SQLite erlaubt bei ALTER TABLE ADD COLUMN
                       keinen nicht-konstanten Default, siehe Bekannte Issues).
                       Offline-faehig (apps.offline_faehig=1): Abhaken und
                       Neu-Eintragen laufen ueber eine lokale Warteschlange
                       in localStorage (siehe "Offline-Faehigkeit" unten und
                       Bekannte Issues) - /erledigt/<eid> nimmt dafuer ein
                       explizites `ziel` (0/1) entgegen und SETZT darauf,
                       statt reinem Toggle (idempotent, sicher wiederholbar).
                       Bearbeiten/Loeschen bewusst NICHT offline-sicher
                       (keine Warteschlange), zeigen aber vorher einen
                       Toast statt der Browser-eigenen Fehlerseite
                       (`pruefeVerbindungOderZeigeHinweis()`/
                       `pruefeLoeschenOnline()` in einkauf.html - beim
                       Loeschen VOR dem confirm()-Dialog geprueft, damit
                       nicht erst gefragt wird und die Aktion dann doch
                       nicht geht)
  00_kern.py         – ist_oeffentliche_url()/ip_ist_oeffentlich() (Wunsch
                       #127, umgezogen hierher mit #203): SSRF-Schutz fuer
                       JEDE vom Client vorgegebene Ziel-URL, die der Server
                       selbst aufruft. 11_rezepte.py importiert die alten
                       Namen zurueck, 07_push.py prueft `endpoint` beim
                       Registrieren (POST /push/subscribe) damit. KEIN
                       DNS-Rebinding-Pinning beim Push-Weg - pywebpush loest
                       selbst auf, das Pinning aus 11_rezepte.py laesst sich
                       nicht uebernehmen ohne pywebpush nachzubauen.
  00_kern.py         – _kontingent_reservieren()/_kontingent_freigeben()/
                       _kontingent_korrigieren() (Wunsch #206, Sicherheitsaudit
                       11.08.2026): atomare Kontingentpruefung fuer BEIDE
                       KI-Kontingente (ki_nutzung/tokens, ki_tts_nutzung/
                       zeichen). BEGIN IMMEDIATE auf new_db() (NICHT g.db,
                       NICHT ueber den Netzwerkaufruf gehalten - SQLite kennt
                       nur eine Schreibsperre fuers ganze File, ein 30s-Lock
                       waere ein Denial-of-Service fuers ganze Portal
                       gewesen). ki_anfrage() reserviert mit max_tokens und
                       korrigiert danach auf den echten Verbrauch;
                       ki_text_zu_sprache() reserviert mit len(text) - das ist
                       dort schon der Endwert, keine Korrektur noetig
                       (_tts_nutzung_protokollieren() ist deshalb entfallen).
  00_kern.py         – rate_ueberschritten()/client_ip() (Wunsch #207,
                       Sicherheitsaudit 11.08.2026): gleitendes Fenster im
                       Speicher, keine externe Abhaengigkeit, bewusst NICHT
                       global angewendet (haette die Offline-Warteschlange der
                       Einkaufsliste treffen koennen) - nur an /wunsch (8/min)
                       und /csp-bericht (30/min). client_ip() liest
                       X-Forwarded-For, weil portal nur hinter Caddy haengt
                       und request.remote_addr sonst immer Caddys Bridge-IP
                       zeigt - seit Wunsch #210 (Audit F-02) den **LETZTEN**
                       Eintrag der Kette, nicht den ersten. Caddy HAENGT die
                       Adresse seines Gegenuebers an einen vorhandenen Header
                       AN; alles links davon hat der Absender selbst
                       geschrieben. Mit `[0]` konnte sich jede Anfrage einen
                       eigenen Eimer aussuchen, die Bremse griff nie.
                       **NICHT** umgesetzt wurde der im Befund vorgeschlagene
                       `trusted_proxies static private_ranges` im Caddyfile:
                       die Geraete der Familie stehen selbst in privaten
                       Netzen (10.10.0.0/24 ueber das UniFi-Gateway), Caddy
                       wuerde also ausgerechnet die Absender als
                       vertrauenswuerdige Proxys einstufen, gegen die die
                       Bremse schuetzt. Caddys Vorgabe "keinem Proxy
                       vertrauen" ist fuer genau einen Hop richtig.
                       _RATE_TREFFER (Modul-Dict) wird in
                       tests/conftest.py per autouse-Fixture vor jedem Test
                       geleert, sonst teilen sich alle Tests im selben Lauf
                       ein Kontingent.
  02_werkstatt.py    – POST /wunsch, der Eingang fuer alle ✨-Wuensche.
                       Wunsch #204 (Sicherheitsaudit 11.08.2026): ohne Token
                       UND ohne Sitzungs-Cookie jetzt 403 statt eines anonym
                       gespeicherten Wunsches - echte Anonymitaet
                       (user_id NULL) gibt es seither nicht mehr.
                       Wunsch #161: KI-Ueberschrift im Hintergrund-Thread.
                       Wunsch #187: ersatz_titel() leitet aus dem ersten Satz
                       eine Ueberschrift ab, falls kein KI-Titel da ist -
                       ANZEIGEWERT, nicht gespeichert (ein echter Titel
                       gewinnt sofort, es gibt kein Provisorium in der DB).
                       Trennt bewusst NICHT am Doppelpunkt: "UI: Die Knoepfe
                       …" ergaebe sonst die Ueberschrift "UI". 05_werkstatt_
                       app.py zieht die Funktion ueber den Alias
                       `teile.werkstatt` (teile/__init__.py).
                       Nachtragen im Bestand: `manage.py titel_nachtragen
                       [anzahl|alle]` - ohne Argument wird nur gezaehlt, weil
                       der Lauf echte Tokens aus dem Kontingent des Urhebers
                       kostet (~160-320 je Wunsch, gemessen).
  16_vokabeln.py     – /a/vokabeln/<token>/ ... Wunsch #194: unregelmaessige
                       Verben. Zwei OPTIONALE Spalten an `vokabeln`
                       (simple_past, perfect) statt einer eigenen Tabelle -
                       Kapitel, Freigaben, Sessions, Versuche, Aussprache und
                       Statistik haengen alle an `vokabeln`. Ein Eintrag IST
                       ein Verb, wenn BEIDE gefuellt sind (`_IST_VERB`);
                       `fremd` ist dann der Infinitiv. Kein Typ-Merker - der
                       waere eine zweite Wahrheit neben den Feldern. Halbe
                       Paare werden ueberall verworfen (_verbformen_lesen(),
                       Foto-Import), sonst gaebe es im Training eine Frage
                       ohne Antwort. VERB_ABFRAGEN definiert die sechs
                       waehlbaren Richtungen; mindestens eine angekreuzte
                       schaltet das Training auf Verben um - deshalb gibt es
                       KEINEN zusaetzlichen Hauptschalter. verb_aufgaben()
                       baut je Verb und Richtung EINE Aufgabe. Der
                       SQL-Filter im Lernstart ist nur eine Abkuerzung, die
                       Korrektheit kommt aus verb_aufgaben(). Foto-Import:
                       eigener Prompt (_verben_per_ki) statt eines Schalters
                       im Vokabel-Prompt - ein Modell, das beide Vorlagen
                       gleichzeitig erklaert bekommt, liefert Mischformen.
                       Wunsch #195: SPRACHEN_MIT_VERBFORMEN = {"Englisch"} -
                       nur dort werden die Felder ueberhaupt angezeigt (und
                       auch da eingeklappt, <details>). Live gibt es FUENF
                       Sprachen, die Voreinstellung im Formular ist
                       Daenisch - der Block ist also meistens weg. Das
                       Ausblenden im Browser ist Bequemlichkeit:
                       _verbformen_lesen(db, sprache_id) und der Foto-Import
                       verwerfen Formen an einer Sprache ohne Stammformen
                       serverseitig, auch beim Sprachwechsel im
                       Bearbeiten-Formular.
  manage.py          – wunsch_erledigt <id> "<umsetzung>" [tokens] - das
                       dritte Argument ist der Tokenverbrauch der Umsetzung
                       (Wunsch #188), NACH der Umsetzung eingetragen, nicht
                       vorab geschaetzt. wuensche.tokens: NULL = nicht
                       erfasst, 0 = wirklich null. Die Detailansicht laesst
                       die Zeile bei NULL weg; in der Vorlage steht deshalb
                       `is not none`, nicht `if w.tokens` - sonst
                       verschwaende eine echte 0.
  manage.py          – wunsch_neu <app> "<titel>" "<text>" legt einen Wunsch
                       an, IMMER ohne Prioritaet und bewusst ohne Schalter
                       dafuer: der stuendliche Lauf (#157) arbeitet alles ab,
                       was eine Prioritaet ausser 'zurueckgestellt' traegt -
                       ein Befehl, der beides koennte, wuerde sich selbst
                       beauftragen. wunsch_aktion <id> <art> "<text>" haengt
                       eine Aktion an (bei art=frage mit demselben Push wie
                       ueber die Oberflaeche, #166). Beide in
                       tests/test_manage_wunsch_befehle.py gewaechtert.
  05_werkstatt_app.py- /a/werkstatt/<token>/ Uebersicht aller Wuensche.
                       verlauf_stand(liste) sagt, was auf die EINGEKLAPPTE
                       Karte gehoert: Anzahl der Aktionen und ob eine
                       Rueckfrage offen ist. "Offen" heisst: auf die 'frage'
                       folgt keine 'antwort' - es zaehlt die REIHENFOLGE, nicht
                       das Vorkommen (eine neue Frage nach einer alten Antwort
                       ist wieder offen; 'notiz'/'plan' beenden nichts).
                       Vorher steckte der ganze Verlauf in der Detailansicht,
                       eine wartende Rueckfrage war bei ~190 Karten unsichtbar.
  11_rezepte.py      – /a/rezepte/<token>/ Lieblingsrezepte (Zutaten in
                       rezept_zutaten, Zubereitungsschritte einzeln in
                       rezept_schritte, Portionen als rezepte.portionen,
                       Kategorie 'kochen'/'backen' als rezepte.kategorie –
                       Wunsch #55, KATEGORIEN-Dict + _clean_kategorie() als
                       einzige Quelle der gültigen Werte);
                       Wunsch #184: kategorie_symbol() ordnet der Kategorie
                       ihr Listensymbol zu (kochen 🍳, backen 🍰, ohne
                       Kategorie 🍲 - bewusst NICHT 'im Zweifel kochen',
                       sonst sieht man der Liste die fehlende Einordnung
                       nicht mehr an). 12_essensplan.py importiert die
                       Funktion ueber den Alias `teile.rezepte`
                       (teile/__init__.py) - dieselben Rezepte duerfen nicht
                       je nach Seite ein anderes Zeichen tragen. Die Zeichen
                       sind dieselben wie in den KATEGORIEN-Labels; ein Test
                       haelt beide zusammen.
                       Wunsch #185: die drei Anlegewege stehen in rezepte.html
                       als eine Flex-Zeile (.anlegen-zeile) statt als drei
                       Blockzeilen. Bewusst OHNE Aufklappen - das haette zwei
                       bisher sichtbare Wege versteckt. Die Knoepfe sind <a>,
                       nicht <button>: die globale 44px-Regel aus base.html
                       (#169) greift bei ihnen NICHT, min-height steht an der
                       Klasse.
                       /neu (GET+POST, Wunsch #48: eigene Unterseite statt
                       dauerhaft sichtbarem Formular auf der Übersicht);
                       /importieren (GET+POST): Rezept per URL – JSON-LD
                       (schema.org/Recipe) zuerst, ki_anfrage() als Fallback nur
                       wenn keins gefunden wird; SSRF-Schutz (_ist_oeffentliche_url:
                       nur http/https, Ziel-IP darf nicht privat/intern sein);
                       Ergebnis landet vorausgefüllt in rezept_neu.html, nie direkt
                       gespeichert; /<rid>/bearbeiten (GET+POST): nutzt dasselbe
                       Formular wie /neu (bearbeiten-Parameter unterscheidet Titel/
                       Ziel-Route), Zutaten/Schritte werden beim Speichern komplett
                       ersetzt; /zutat/<id>/einkaufen (JSON) setzt fehlende Zutat
                       auf Einkaufsliste; /<rid>/bewerten (JSON, Wunsch #52): 1-5
                       Sterne pro Nutzer+Rezept, UPSERT über UNIQUE(rezept_id,
                       user_id), gibt neuen Durchschnitt zurück; /<rid>/wunsch/toggle
                       (JSON, Wunsch #65): "Wünsch ich mir"-Markierung, max. 5 pro
                       Nutzer (MAX_REZEPT_WUENSCHE), ruft bereinige_erfuellte_
                       rezeptwuensche() (00_kern.py) vor jeder Anzeige/Änderung auf;
                       /importieren-bild (GET+POST, Wunsch #97): Rezept per Foto
                       (Kamera/Mediathek) – _rezept_per_ki_bild() ruft ki_anfrage()
                       mit Bildeingabe (eigener KI-Zweck "rezepte_foto_import",
                       unabhängig vom URL-Import konfigurierbar), gleiche Datei-
                       Validierung wie beim Vokabeln-Foto-Import (_FOTO_MAX_BYTES
                       8 MB, _FOTO_MIME jpg/png/heic); Ergebnis landet wie beim
                       URL-Import nur vorausgefüllt in rezept_neu.html, keine
                       eigene Prüf-Ansicht nötig (anders als Vokabeln-Foto-Import,
                       wo ein Foto mehrere Vokabelpaare liefert)
  12_essensplan.py   – /a/essensplan/<token>/ 14-Tage-Ansicht (aktuelle + folgende
                       Woche ab Wochenmontag), pro Tag Slots "mittag"/"abend";
                       liefert vergangene_tage/aktuelle_rest/naechste_woche als
                       getrennte Listen fürs Template (Wunsch #40/#41/#42: eigene
                       Wochen-Überschriften, vergangene Tage einklappbar);
                       POST /eintrag speichert Rezept-Verweis oder Freitext pro
                       Tag+Mahlzeit (UNIQUE auf tag+mahlzeit, Upsert); POST
                       /verschieben (JSON) verschiebt/tauscht Einträge per Drag &
                       Drop auf einen beliebigen anderen Slot (Tag und/oder
                       Mahlzeit dürfen sich unterscheiden); Tages-Status
                       (vergangen/heute/zukunft) wird bei jedem Aufruf aus
                       date.today() berechnet, nicht gespeichert
  13_kinderplan.py   – /a/kinderplan/<token>/ Aufgabenplan: Kinder UND
                       Eltern (Wunsch #91, vorher nur Kinder - Eltern konnten
                       zwar fremde Plaene verwalten, hatten aber keinen
                       eigenen). Seit Wunsch #92 rollierende 14-Tage-Liste
                       (aktuelle+naechste Woche, vergangene Tage einklappbar)
                       wie 12_essensplan.py, keine Wochentag-Grid-Ansicht mehr:
                       Geholfen-Aufgaben haengen seit Wunsch #115 an einem
                       echten Einzeltermin (kinderplan_eintraege.plan_tag,
                       ISO-Datum) statt einer fortlaufenden woechentlichen Regel
                       (kinderplan_eintraege.wochentag, bleibt als zusaetzliche,
                       nicht mehr fuer die Anzeige genutzte Spalte bestehen) -
                       /zuweisen schreibt nur noch fuer den einen angeklickten
                       Tag (vorher: gilt fuer JEDEN Tag mit demselben
                       Wochentag). Andi hat sich nach Rueckfrage bewusst fuer
                       die radikalere Migration entschieden: ALLE bestehenden
                       Wochenroutinen wurden beim Deploy einmalig zu Einzel-
                       terminen fuer das damals sichtbare 14-Tage-Fenster
                       materialisiert (kein automatisches Fortsetzen mehr
                       danach) - Gegenteil der Wunsch-#92-Entscheidung
                       ("bestehende Routine bleibt automatisch bestehen").
                       /abhaken weiterhin direkt in geholfen_eintraege.
                       Todo-Pool-Instanzen (Wunsch #90) haengen ebenfalls an
                       einem echten Kalendertag (todos.plan_tag, ISO-Datum -
                       ersetzt das urspruengliche todos.wochentag, das nie mit
                       Produktivdaten gefuellt war und als totes Altfeld liegen
                       bleibt): /serie_einsortieren (Pool-Vorlage aus teile.todo
                       fuer eine Person+Datum einsetzen, einmalig), /serie_
                       erledigen/<id> (Status-Toggle, schreibt direkt in todos)
                       und /serie_zuruecklegen/<id> (Wunsch #114: echtes
                       Loeschen der todos-Zeile statt Toggle - macht die
                       Vorlage fuer betroffene Tage wieder verfuegbar gemaess
                       serie_verfuegbar_am()). _gesperrter_tag_datum() (vorher
                       _gesperrter_wochentag()) sperrt ab 20 Uhr DEUTSCHER Zeit
                       (ZoneInfo("Europe/Berlin"), siehe Bekannte Issues -
                       Container laeuft in UTC) den naechsten echten Kalendertag
                       fuer Kinder, Eltern/Admin ausgenommen. Bewusst KEIN
                       Drag & Drop zwischen Tagen (anders als Essensplan) - fuer
                       einen ersten Wurf zurueckgestellt, technisch inzwischen
                       fuer beide Eintragsarten gleichermassen moeglich (kein
                       struktureller Grund mehr dagegen seit #115).
                       Seit Wunsch #113 werden die "🔁 Aus Pool holen"-Kandidaten
                       PRO TAG einzeln berechnet (`serien_pool_fuer_tag()`, einmal
                       je sichtbarem Kalendertag statt einmal global) - dadurch
                       zeigt jeder Tag nur die fuer GENAU ihn gueltigen Serien.
  14_sportschau.py   – /a/sportschau/<token>/ Trainings-Heatmap (Wunsch #62),
                       Zeitraum waehlbar per ?tage=14/30/60/90 (Wunsch #95,
                       `_TAGE_STANDARD`=14 Default + `_TAGE_OPTIONEN`-Liste,
                       ungueltiger/fehlender Wert faellt sicher auf Standard
                       zurueck; vorher feste `_TAGE_ANZAHL`-Konstante seit
                       Wunsch #78), eine Zeile pro Trainingsart. Ruft
                       live GET /api/workouts vom hae-Server ab (kein
                       Speichern in portal.db), URL/Key aus HAE_API_URL/
                       HAE_API_KEY (.env), UTC→Europe/Berlin per zoneinfo.
                       `_ART_KORREKTUREN` (Wunsch #75) korrigiert schlechte
                       deutsche Übersetzungen des hae-Servers per Substring
                       ("Ausführen"→"Laufen", "Spaziergang"→"Gehen"),
                       unbekannte Werte bleiben unverändert. Zusätzlich
                       Schritte-Balkendiagramm (Wunsch #77): eigener Endpoint
                       `/api/metrics/step_count` (aus HAE_API_URL abgeleitet,
                       `from`/`to` als Unix-Millisekunden statt ISO-Datum –
                       andere Konvention als /api/workouts, siehe
                       journal.md 2026-07-30), stündliche Schritt-Buckets
                       werden Tagen zugeordnet und per Zeitüberlappung mit
                       Workout-Fenstern in Trainings-/Sonstige-Schritte
                       aufgeteilt (Näherung auf Stundenbasis). `_hae_workouts`
                       schlägt end_date einen Tag auf, bevor die Anfrage raus
                       geht (Wunsch #88, siehe Bekannte Issues - hae-Server
                       parst ein bare-date endDate als Mitternacht, "heute"
                       wäre sonst immer ausgeschlossen). Gestapelte Balken in
                       `sportschau.html`: Training-Segment steht im Markup VOR
                       dem Sonstige-Segment, damit es im flex-column-Stack oben
                       liegt und Sonstige (flex:1) die Basis bildet (Wunsch #89
                       - Reihenfolge im Markup bestimmt oben/unten). Rechts
                       neben der Überschrift "Schritte je Tag" steht der
                       Durchschnitt für den gewählten Zeitraum OHNE den
                       heutigen Tag (Wunsch #98 - der ist meist noch nicht
                       vorbei und würde den Schnitt verzerren). Die Y-Achsen-
                       Beschriftung der Gridlines sitzt seit Wunsch #99 links
                       (`left:0` statt `right:0`) statt über den interessanten
                       jüngsten Balken (vorgestern/gestern/heute stehen rechts,
                       da `tage` älteste zuerst sortiert) - überlagert jetzt
                       nur noch die ältesten, uninteressanteren Tage links,
                       Balkenausrichtung zum Trainings-Chart bleibt gleich.
                       Trainingsanteil im Schritte-Balken + Legenden-Punkt
                       fest gruen (`#34c759`, Wunsch #102) statt `var(--farbe)`
                       - vorher zufaellig blau, weil das Andis persoenliche
                       Nutzerfarbe ist, jetzt konsistent mit der bereits
                       gruenen Heatmap oben. `_gridlines(max_wert, schritt)`
                       (Wunsch #108) liefert immer eine 0-Linie zusaetzlich zu
                       den `schritt`-Abstands-Linien - vorher gab es erst ab
                       2000 Schritten ueberhaupt eine Linie. Heatmap-Zellen
                       stecken seit Wunsch #109 in einer `.heatmap-cell-col`
                       (streckt sich wie `.steps-bar-col`), die Zelle selbst
                       ist begrenzt+zentriert statt selbst das max-width zu
                       tragen - vorher fuellte die Zeile auf breiten
                       Bildschirmen nicht die volle Breite aus und lag nicht
                       mehr mit dem Schritte-Chart darunter uebereinander;
                       gleicher gap-Wert (3px) in beiden fuer pixelgenaue
                       Ausrichtung. `_wochen_ansicht()` (Wunsch #110) gruppiert
                       tage/schritte_balken nach ISO-Kalenderwoche fuer eine
                       zusaetzliche, GitHub-artige Wochenansicht (7 Zeilen
                       Mo-So per CSS Grid mit `grid-auto-flow:column`, eine
                       Spalte je Woche, Schritte pro Woche aufsummiert zu
                       einem Balken je Woche) - rein CSS-gesteuert per Media
                       Query umgeschaltet (Umschaltpunkt haengt von
                       `tage_anzahl` ab: `tage_anzahl * 25 + 80` Pixel), Server
                       liefert immer beide Ansichten gleichzeitig, kein
                       Server-Roundtrip beim Umschalten. Bewusst OHNE eigene
                       Wochentag-Beschriftungsspalte links neben dem Grid
                       (Wochentag/Datum nur per Tooltip) - eine solche Spalte
                       verschiebt den Grid-Start nach rechts und bricht die
                       Ausrichtung mit dem Schritte-Wochenchart darunter
                       (das keine solche Spalte hat), live als Bug gefunden
                       und wieder entfernt. Nur Andi granted (persönliche
                       Fitnessdaten)
  15_tierbaukasten.py – /a/tierbaukasten/<token>/ eigene Figur aus
                       Bausteinen (Wunsch #64, Assistent+Mensch+Körperbau
                       Wunsch #66): Kategorie Mensch/Tier (tier_typ='mensch'
                       ist kein eigenes Schema-Feld, nur ein zusätzlicher
                       erlaubter Wert – ALLE_TYPEN = TIERE|{'mensch'}).
                       Tiere: handgezeichnetes SVG, Körperfarbe,
                       Muster+Musterfarbe, Körperbau (0-100), Accessoires
                       (kommagetrennte Liste, mehrere gleichzeitig –
                       Wunsch #69). Mensch: DiceBear/Avataaars (Feedback
                       von Friederike, nicht über Werkstatt-App – siehe
                       journal.md 2026-07-29), rendert serverseitig via
                       `dicebear-core`+`dicebear-styles` (offline, keine
                       Netzwerkanfrage), Auswahlwerte gesammelt als JSON in
                       `dicebear_optionen`; /vorschau-mensch (POST, JSON)
                       liefert bei jeder Änderung ein frisch gerendertes
                       SVG für die Live-Vorschau. /speichern (POST),
                       /bearbeiten/<id> (POST, Wunsch #201 – holt die Figur
                       zurück in denselben Assistenten statt ein zweites
                       Formular aufzumachen; fremde Figur = 403, `erstellt`
                       bleibt stehen, weil die Galerie danach sortiert),
                       /loeschen/<id> (POST, nur eigene Kreationen).
                       Anlegen und Bearbeiten teilen sich `_kreation_aus_form()`
                       und schreiben beide ALLE Spalten aus `_SPALTEN` – sonst
                       überlebte beim Wechsel Mensch→Tier das alte
                       `dicebear_optionen` und die Galerie zeichnete weiter den
                       Avatar zu einer Zeile, die Tier sagt. Jeder
                       Nutzer sieht nur seine eigene Galerie. Galerie-Vorschau
                       (Macro figur_vorschau) rendert jede Kreation ueber
                       eigenen suffixierten Clip-Pfad (`suffix='-'~kreation.id`),
                       damit mehrere gespeicherte Tiere derselben Art keine
                       doppelten SVG-IDs erzeugen - koerper_vorne(typ, suffix='')
                       muss diesen Suffix mit an seine Element-IDs weitergeben,
                       sonst laeuft der Clip-Pfad der Galerie ins Leere und das
                       Muster verschwindet (Wunsch #83, siehe Bekannte Issues)
  16_vokabeln.py     – /a/vokabeln/<token>/ Vokabeln lernen (Wunsch #73,
                       kompletter Neubau – Wunsch #67 war ein Fehlversuch):
                       Sprachen global (Standard Englisch/Latein, neue per
                       Wunsch), pro Nutzer auf /sprachen aktivierbar;
                       Kapitel pro Nutzer auf /kapitel (anlegen/umbenennen/
                       deaktivieren, wie einkauf_kategorien ohne Reorder);
                       Vokabel = fremd+deutsch+sprache_id+optional mehrere
                       Kapitel, /neu + /<id>/bearbeiten + /<id>/loeschen
                       (Formular auf Hauptseite bzw. inline ✏️-Panel wie
                       geholfen_verlauf); zuletzt gewählte Sprache bleibt
                       im Eintragen-Formular per localStorage vorbelegt.
                       /lernen (Sprache+Kapitel/Alle/Ohne-Kapitel-Auswahl)
                       + /lernen/start (legt vokabel_sessions-Zeile an,
                       schliesst automatisch eine evtl. noch offene Session
                       desselben Nutzers); Trainer fragt zufaellig Deutsch
                       oder Fremdsprache ab, falsche Antworten wandern ans
                       Ende der Warteschlange, /versuch (JSON) protokolliert
                       jeden Versuch, /session/<id>/beenden schliesst die
                       Sitzung (Button + pagehide/sendBeacon). /auswertung
                       (Wunsch #79): Trainingszeit je Sprache (nur Sessions
                       mit mindestens einem Versuch zaehlen) + richtig/
                       falsch je Kapitel (ueber vokabel_kapitel_zuordnung,
                       Status "gelernt"/"schwierig" nach letztem Versuch pro
                       Vokabel); ?fuer=<user_id> fuer Eltern/Admin
                       (`_darf_andere_sehen`), serverseitig erzwungen, Kinder
                       sehen immer nur sich selbst. /foto-import (Wunsch #80,
                       GET+POST) + /foto-import/speichern: Foto hochladen
                       (max. 8 MB, JPG/PNG/HEIC), KI (ki_anfrage mit `bilder`)
                       extrahiert Vokabelpaare als JSON, landet zur Kontrolle
                       in vokabel_foto_pruefen.html (jede Zeile editierbar/
                       abwaehlbar, ein Kapitel fuer den ganzen Stapel), nie
                       direkt gespeichert. /wort/<vid>/audio (Wunsch #81):
                       KI-Aussprache des fremdsprachigen Worts, per
                       ki_text_zu_sprache() erzeugt und dauerhaft unter
                       DATA_DIR/vokabel_audio/<sprache_id>/<hash>.audio
                       gecacht (Schluessel: normalisierter Text, nicht
                       vokabel_id); send_file(..., download_name=...) gibt
                       explizit die passende Dateiendung vor - iOS/Safari
                       verlaesst sich beim Formaterkennen zusaetzlich zu
                       Content-Type auf die Endung im Dateinamen. Jeder
                       Nutzer sieht sonst nur seine eigenen Vokabeln/Kapitel/
                       Sessions. 🔊-Knopf fuer /wort/<vid>/audio auch direkt
                       in der Vokabelliste auf der Hauptseite, nicht nur im
                       Trainer (Wunsch #84)
  17_packliste.py    – /a/packliste/<token>/ Packlisten fuer Reisen/Ausfluege
                       (Wunsch #111), bewusst sehr aehnlich zu 10_einkauf.py
                       aufgebaut, drei Unterschiede (vorab per Rueckfrage mit
                       Andi geklaert, siehe Docstring am Dateianfang):
                       (1) Ziele (packlisten_ziele: Reisen/Ausfluege) statt
                       Maerkte - genau wie Maerkte nur anlegen/deaktivieren,
                       bewusst OHNE Umbenennen (Andi nannte es explizit "wie
                       ein Markt", Laeden koennen ebenfalls nicht umbenannt
                       werden); (2) ein Eintrag gehoert zu GENAU EINEM Ziel
                       (nicht wie Angebote bei mehreren Maerkten) - die
                       Uebersicht zeigt deshalb IMMER nur ein aktives Ziel
                       gleichzeitig (`?ziel=<id>`, Default: erstes aktives
                       Ziel, `_aktives_ziel()`) - anders als die Einkaufsliste
                       (eine einzige Dauerliste) ist eine Packliste zeitlich
                       an eine Reise gebunden; (3) ein Eintrag kann zusaetzlich
                       einer Person zugeordnet sein (`person_id`, NULL =
                       "allgemein"). "🧳 Packen starten" (Packmodus, analog zu
                       Einkaufs "Einkauf starten" Wunsch #87 Teil 2): Person
                       waehlen, zeigt dann deren Eintraege PLUS alle
                       allgemeinen; "🌐 Allgemein" zeigt NUR die allgemeinen.
                       Kategorien (packlisten_kategorien, vorbelegt: Anreise/
                       Kleidung/Bad & Hygiene/FeWo-Küche/Reiseapotheke/
                       Technik/Freizeit/Sonstiges) anlegen/umbenennen/
                       deaktivieren/pos.-sortierbar wie bei Einkauf (identischer
                       Code, nur Tabellennamen getauscht). Bewusst NICHT Teil
                       von Version 1 (keine Anforderung, spaeterer Einkaufs-
                       Wunsch): Offline-Faehigkeit, automatische
                       Synchronisierung (Wunsch #100), "Filtern"-Knopf
                       (Wunsch #87 Teil 1) - koennen bei Bedarf per eigenem
                       Folge-Wunsch nachgezogen werden. Wunsch #116:
                       `_aktives_ziel_fuer_index()` merkt das zuletzt
                       geoeffnete Ziel PRO NUTZER (packlisten_nutzer_ziel,
                       server-seitig per UPSERT - bewusst nicht sessionStorage
                       wie sonst ueblich, da "von einem Benutzer" gemeint ist,
                       nicht "in diesem Browser-Tab"); ohne explizites `?ziel=`
                       wird die Merkung geladen, mit explizitem `?ziel=` wird
                       sie aktualisiert. Wunsch #117/#118: `_darf_verwalten()`
                       erlaubt Ziele/Kategorien-Verwaltung jetzt fuer Eltern
                       UND Admin (vorher nur Admin, gleiches Muster wie
                       13_kinderplan.py) - Menuepunkte in base.html
                       entsprechend sichtbar.
  18_tvb.py           – /a/tvb/<token>/ Naechste Spiele, Ergebnisse und
                       Handball-Bundesliga-Tabelle des TVB Stuttgart
                       (Wunsch #120). Reiner Anzeige-Modus (keine
                       Nutzereingaben). Daten kommen live per On-the-fly-
                       Abruf (urllib, kein neues pip-Paket, Timeout 8s,
                       "fehler"-Flag statt Crash - gleiches Muster wie
                       `_hae_workouts()` in 14_sportschau.py) von
                       handball.net, dem Datenportal des Deutschen
                       Handballbunds - es gibt keine dokumentierte Public
                       API dafuer (OpenLigaDB hat kein Handball), genutzt
                       wird der unauthentifizierte Endpunkt, den
                       handball.net selbst fuer seine einbettbaren Vereins-
                       Widgets aufruft (gefunden per Analyse von
                       `handball.net/widgets/embed/v1.js`):
                       `tournament/sr.competition.149/table` (komplette,
                       immer aktuelle Tabelle) sowie `team/sr.competitor.
                       6272-143352/team-schedule` sowie `tournament/.../
                       schedule` (TVB Stuttgarts Spiele). Das Spielplan-
                       Widget liefert laut Doku nur ein kleines Fenster
                       (ca. naechste 3 Spiele, vermutlich keine
                       vergangenen Ergebnisse mehr sobald ein Spieltag aus
                       dem Fenster faellt) - deshalb neue Tabelle
                       tvb_spiele: jedes bei einem Seitenaufruf gesehene
                       TVB-Spiel wird per UPSERT gespeichert, damit einmal
                       gesehene Ergebnisse dauerhaft sichtbar bleiben.
                       Wunsch #151: dritte Quelle NUR fuer die Profis,
                       `club/sr.competitor.6272/schedule` - der einzige
                       Endpunkt, der alle Wettbewerbe zusammenfuehrt.
                       handball.net vergibt je Wettbewerb eine eigene
                       Team-ID (HBL -143352, DHB-Pokal -143228), deshalb
                       konnten Liga- und Team-Spielplan den Pokal
                       prinzipiell nicht liefern - er fehlte lautlos.
                       Zuordnung ueber `_ist_vereins_spiel()` per Praefix
                       `sr.competitor.6272-` (Bindestrich zwingend, sonst
                       matcht sr.competitor.62721). Ablage unter derselben
                       team_id wie die Ligaspiele (fuer die Familie sind
                       das "die Profis", keine zweite Mannschaft);
                       unterschieden wird ueber die Spalte `wettbewerb`,
                       angezeigt nur bei Abweichung vom Ligennamen.
                       Testspiele fehlen und bleiben es (Nachtrag zu #151):
                       Sie FINDEN STATT (S-Cup Altensteig u.a.), aber keine
                       Quelle veroeffentlicht sie maschinenlesbar -
                       handball.net fuehrt nur Pflichtspiele, die
                       Vereinsseite tvbstuttgart.de bindet dasselbe Widget
                       ein (gleiche Luecke), und in der
                       Freundschaftsspiel-Liste von handball-world.news
                       kommt der TVB in der ganzen Saison 2026/27 nicht vor.
                       Sie stehen nur als Fließtext in Nachrichten.
                       Andi hat einen Handeintrag ausdruecklich ABGELEHNT
                       ("wenn es nicht automatisch geht dann brauche ich die
                       Daten nicht") - nicht erneut vorschlagen.
                       Bewusst kein Cron-Job dafuer (Randfall "niemand
                       oeffnet die App an einem Spieltag" fuer eine
                       Familien-App hinnehmbar, siehe journal.md).
                       Wunsch #121: Unterseite /kader zeigt den Kader mit
                       statistischen Werten. handball.net hat dafuer KEINEN
                       Endpunkt (kader/squad/roster/players/statistics alle
                       404) - Quelle ist deshalb die HPI-API der HBL
                       (hpi.handball-bundesliga.de/api, ebenfalls
                       unauthentifiziert, gefunden ueber das Statistik-
                       Dashboard auf opel-hbl.de): /api/tournament/1 ->
                       Saisonliste, /api/index/season/<id> -> alle ~390
                       Liga-Spieler mit HPI-Werten, TVB gefiltert ueber
                       team.sportradar_id == 6272 (dieselbe ID wie in
                       _TEAM_ID, kein zweites Vereins-Mapping).
                       `_kader_saison_waehlen()` nimmt die NEUESTE Saison,
                       die ueberhaupt TVB-Spieler liefert - die HPI-Liste
                       enthaelt nur Spieler, die auch gespielt haben, eine
                       frisch begonnene Saison ist also leer und es wird
                       auf die Vorsaison zurueckgefallen (Saisonname steht
                       deshalb sichtbar ueber der Tabelle; Neuzugaenge
                       fehlen dann bis zum ersten Spiel, Abgaenge stehen
                       noch drin - ohne echte Kaderquelle nicht loesbar).
                       Anders als bei den Spielen wird der Kader in
                       tvb_kader ZWISCHENGESPEICHERT (_KADER_MAX_ALTER_
                       STUNDEN = 6), weil die Antwort ~400 KB gross ist,
                       wovon nur 22 Spieler gebraucht werden - beim
                       Neuladen wird die Tabelle geleert und neu gefuellt
                       (Kader = Momentaufnahme, Abgaenge sollen
                       verschwinden - bewusst KEIN UPSERT wie bei
                       tvb_spiele, wo alte Zeilen gerade erhalten bleiben
                       sollen). Spielerfotos liefert die API zwar mit
                       (externes CDN images.dc.prod.cloud.atriumsports.com),
                       werden aber bewusst NICHT eingebunden: das Portal
                       laedt nichts von fremden Hosts (siehe Wunsch #119)
                       und jedes Foto wuerde die IPs der Familie an einen
                       Dritt-Server melden.
                       Wunsch #122: `?team=<id>` schaltet zwischen ALLEN
                       Mannschaften um (Umschalter-Chips oben, jede Seite
                       gleich aufgebaut). Profis und Unterbau sind auf
                       handball.net ZWEI Vereinsobjekte:
                       sr.competitor.6272 (nur Profis) und
                       handball4all.wuerttemberg.131 (17 Mannschaften: 2./
                       3./4. Herren + Jugend A bis F) - _AMATEUR_VEREIN_ID.
                       Die Mannschaftsliste gibt es NICHT als API
                       (club/<id>/teams -> 404, club/<id>/schedule zeigt nur
                       Teams mit Spielen in 14 Tagen), deshalb wird die
                       Vereinsseite geparst (_mannschaften_von_handball_net)
                       und in tvb_mannschaften gespeichert, erneuert alle
                       _MANNSCHAFTEN_MAX_ALTER_STUNDEN (24) - schlaegt das
                       Parsen fehl, bleibt der alte Stand stehen statt der
                       Umschalter zu verschwinden. `_kurzlabel()` baut aus
                       der langen Liga-Bezeichnung das Chip-Label
                       ("maennliche B-Jugend Bezirksoberliga Staffel 2" ->
                       "mB BOL 2"), Doppelungen werden durchnummeriert.
                       `_turnier_id_sichern()` holt die Liga-ID FAUL - erst
                       wenn eine Mannschaft geoeffnet wird, dann dauerhaft
                       gemerkt: bevorzugt aus den Spieldaten (kostenlos
                       mitgeliefert), sonst von der /tabelle-Seite. Alle 17
                       auf einmal zu holen haette den Seitenaufbau
                       desjenigen, der die 24h-Aktualisierung ausloest, um
                       ~17 s verzoegert. Unbekanntes/fehlendes ?team faellt
                       immer auf die Profis zurueck. Der Kader-Knopf
                       erscheint NUR bei den Profis (HPI ist eine reine
                       Bundesliga-Kennzahl).
                       Wunsch #123: Kopfzeile richtet sich nach der
                       gewaehlten Mannschaft (kopf_verein/kopf_liga) - nur
                       die 1. Mannschaft heisst "TVB Stuttgart" und spielt
                       in der "Handball-Bundesliga", alle uebrigen laufen
                       unter "TV Bittenfeld" mit ihrer eigenen Liga
                       (_liga_ohne_verband, also ohne den Praefix
                       "Baden-Wuerttembergischer Handball-Verband - ").
                       Wunsch #124: /mannschaften blendet Altersklassen
                       PRO NUTZER aus (tvb_ausgeblendet, bewusst ohne
                       Admin-Pruefung - der Wunsch sagt ausdruecklich
                       "jeder Nutzer", und es aendert nur die eigene
                       Ansicht). Gespeichert wird das AUSGEBLENDETE, nicht
                       das Sichtbare: eine naechste Saison neu
                       dazukommende Klasse ist damit automatisch sichtbar
                       statt stillschweigend versteckt. Die Profis sind
                       nicht abwaehlbar (_sichtbare_mannschaften), sonst
                       koennte der Umschalter leer werden. Ein Direktlink
                       auf eine ausgeblendete Mannschaft funktioniert
                       weiter - sie taucht nur nicht im Umschalter auf.
                       Schluessel je Klasse ist das Kuerzel aus
                       _ALTERSKLASSEN (mA, gE, ...), NICHT die
                       Liga-Bezeichnung: "gemischte Jugend E" und
                       "gemischte E-Jugend" sind dieselbe Klasse in zwei
                       Schreibweisen und muessen auf denselben Haken
                       fallen.
  19_sitzung.py      – Sitzungs-Cookies (Wunsch #140). Stellt beim
                       Aufloesen eines Pfad-Tokens ein Cookie aus, das seit
                       Stufe 3 als Nachweis gilt.
                       **Geraeteuebernahme (Stufe 4):** Gehoert die
                       vorhandene Sitzung einem ANDEREN Nutzer, wird sie
                       geloescht und ersetzt - wer seinen Link oeffnet,
                       uebernimmt das Geraet. Ohne das hielte der Vorrang des
                       Pfad-Tokens nur eine Seite lang: token-frei ist
                       /a/einkauf/ fuer alle dieselbe Adresse, ab dem ersten
                       Klick entscheidet allein das Cookie.
                       Schalter SITZUNG_AUSSTELLEN in der .env, Notausstieg
                       ohne Rebuild. Cookie: Secure, HttpOnly, SameSite=Lax,
                       Path=/, KEIN Domain (sonst ginge es an Home Assistant
                       mit), Max-Age 1 Jahr. SameSite=Lax traegt im
                       HA-iFrame, weil wir4 und portal Subdomains derselben
                       Domain sind (same-site). Gespeichert wird nur
                       token_lookup(wert), nie der Klartext.
  01_start_token.py  – ... zusaetzlich `/start` (Wunsch #140, Stufe 3):
                       derselbe Einstieg ohne Token in der Adresse, Nutzer
                       kommt aus dem Sitzungs-Cookie. `/p/<token>` bleibt
                       gueltig und hat Vorrang.
                       **Weiterleitung (Stufe 4):** /p/<token> leitet auf
                       /start um - aber ERST, wenn dieses Geraet bewiesen hat,
                       dass es das Cookie annimmt und zurueckschickt (das
                       mitgesendete Cookie zeigt auf denselben Nutzer).
                       Sofortiges Umleiten haette ein Aussperr-Fenster: Nimmt
                       ein Browser das Cookie nicht an (Privatmodus, voller
                       Speicher), landet man auf /start ohne Sitzung, bekommt
                       403, und der erneute QR-Scan fuehrt in dieselbe
                       Weiterleitung - der Link waere fuer dieses Geraet tot.
                       So bleibt ein Geraet ohne funktionierende Cookies
                       dauerhaft beim Token-Link.
  20_csrf.py         – CSRF-Riegel (Wunsch #140, Stufe 2). Ein
                       before_request, null Template-Aenderungen. Prueft
                       `Sec-Fetch-Site` (primaer, weil
                       `Referrer-Policy: no-referrer` den `Origin`-Header auf
                       `null` setzen kann) und faellt sonst auf `Origin`
                       zurueck. **`same-site` wird ABGELEHNT** - Home
                       Assistant laeuft unter derselben Domain, ein POST von
                       dort waere same-site aber nicht same-origin; der Kiosk
                       ist nicht betroffen, weil die Seite IM iFrame
                       Portal-Origin hat. Schalter CSRF_MODUS:
                       aus | beobachten | scharf. Im Beobachtungsmodus wird
                       nur protokolliert (grep-Wort "CSRF-Verdacht"), nichts
                       blockiert. Der Riegel geht bewusst scharf, BEVOR ab
                       Stufe 3 ein Cookie autorisiert - solange jede Anfrage
                       noch ihren Pfad-Token traegt, kann er nichts
                       kaputtmachen.
  21_csp.py          – Content-Security-Policy mit Nonce (Wunsch #142). Wunsch
                       #205 (Sicherheitsaudit 11.08.2026): _log_sicher()
                       entfernt Steuerzeichen aus den drei gemeldeten Feldern
                       vor dem Loggen - sonst liess sich per eingebettetem
                       Zeilenumbruch eine gefaelschte, eigenstaendig
                       aussehende Log-Zeile einschleusen (der Endpunkt ist
                       absichtlich unauthentifiziert, siehe bericht()).
                       Die CSP steht seit Stufe 5 HIER und nicht mehr im
                       Caddyfile: das Nonce muss je Anfrage neu erzeugt und in
                       dieselbe Antwort geschrieben werden, in der es auch in
                       den <script>-Tags steht - Caddy sieht die Vorlage nicht.
                       Stellt `csp_nonce` als Kontextvariable bereit (der Wert
                       enthaelt das fuehrende Leerzeichen, daher
                       `<script` + Ausdruck + `>` ohne Leerzeichen davor).
                       Schalter CSP_MODUS: aus | beobachten | scharf.
                       `beobachten` laesst die alte Regel gelten und schickt
                       die strenge nur als Report-Only mit - Verstoesse landen
                       ueber /csp-bericht im Log (grep-Wort "CSP-Verstoss"),
                       blockiert wird nichts. Der Modus ist hier mehr wert als
                       beim CSRF-Riegel: ein uebersehener Inline-Handler faellt
                       sonst erst auf, wenn jemand den Knopf drueckt.
                       style-src behaelt bewusst 'unsafe-inline' (rund 200
                       style-Attribute; Style-Injektion ist ungleich harmloser
                       als Script-Injektion).
  22_kassenbuch.py   – /a/kassenbuch/<token>/ Taschengeld-Kassenbuch je Kind
                       (Wunsch #144). Buchhaltungsprinzip statt CRUD: ein
                       Eintrag ist nach dem Speichern UNVERAENDERLICH,
                       "Loeschen" heisst Stornieren (storniert=1, Zeile
                       bleibt fuer immer stehen, zaehlt aber nicht mehr zum
                       Kontostand) - keine separate Aenderungs-Historie noetig,
                       weil erstellt_von/erstellt und storniert_von/
                       storniert_am direkt auf der Zeile stehen. Der
                       Startbetrag ist selbst ein Eintrag (art='start').
                       Wunsch #216: Er laesst sich EINMALIG richtigstellen,
                       solange `_start_korrektur_offen()` gilt - gueltiger
                       Start vorhanden und KEINE gueltige (nicht stornierte)
                       Buchung daneben. Stornierte Buchungen halten das
                       Fenster offen (Fall #202). Die Richtigstellung laeuft
                       ueber dieselbe Route /start und ueberschreibt NICHTS:
                       alter Start wird storniert, neuer angelegt - damit
                       erscheint sie im Pruefprotokoll von selbst als
                       angelegt/storniert/angelegt, ohne neue Ereignisart.
                       Deshalb hat 22_kassenbuch.py jetzt ZWEI UPDATEs, beide
                       nur auf die Storno-Spalten (test_kassenbuch_
                       unveraenderlich.py prueft den Inhalt, nicht die Zahl).
                       EIN Feld `person` statt getrennter
                       Empfaenger/Absender-Felder - die Formular-Beschriftung
                       wechselt clientseitig zwischen "Von wem?"/"An wen?" je
                       nach gewaehlter Art (kbArtGewaehlt() in kassenbuch.html).
                       Zugriff (seit Wunsch #212 POSITIV formuliert ueber
                       `_darf_aufsicht(user)` = is_admin oder rolle=='eltern',
                       geprueft in index(), kind_buch() UND pruefprotokoll()):
                       Kinder sehen NUR ihr eigenes Buch, Eltern/Admin sehen
                       ueber index() eine Uebersicht aller Kinder und koennen
                       jedes Buch READ-ONLY oeffnen, aber nichts eintragen/
                       stornieren (eigene_buch-Pruefung serverseitig, nicht
                       nur im Template versteckt). ALLE anderen Rollen -
                       insbesondere `gast`, der Schema-Default - bekommen
                       ueberall 403. Vorher stand dort dreimal "wer kein Kind
                       ist, darf", also eine negative Liste; der Auto-Grant
                       laeuft seit #212 mit rollen=('eltern','kind').
                       Wunsch #153: Pruefprotokoll unter
                       /kind/<id>/pruefung, NUR fuer Eltern/Admin (Kinder
                       bekommen 403, auch aufs eigene). Der Unterschied zum
                       Kassenbuch ist die SORTIERUNG: das Buch nach `datum`
                       (Tag des Geldflusses), das Protokoll nach `erstellt`/
                       `storniert_am` (Zeitpunkt der Erfassung) - erst darin
                       faellt ein Nachtrag oder ein schnelles Storno auf.
                       Eine Zeile erzeugt darum bis zu ZWEI Ereignisse
                       (`_pruefprotokoll()`): Anlegen und Stornieren sind
                       zwei Handlungen mit eigener Zeit und eigenem Urheber.
                       Markierung "nachgetragen" wenn datum < Erfassungstag
                       (in ORTSZEIT verglichen, sonst waere nachts jeder
                       Eintrag markiert), Markierung "nicht von X selbst"
                       wenn erstellt_von != user_id - heute unmoeglich,
                       wird aber geprueft statt angenommen.
                       `_rechenprobe()` liefert die Summanden einzeln, damit
                       sich der Saldo nachzaehlen laesst; ihr `stimmt`-Feld
                       kann sichtbar scheitern - eine Probe, die nicht
                       scheitern kann, beweist nichts.
  03_admin.py        – ... Wunsch #140 Stufe 6: zeigt KEINE Zugangsadressen
                       mehr an. `_zugang_anzeigen()` ist die einzige Stelle,
                       an der ein Link je zu sehen ist - beim Anlegen eines
                       Nutzers und bei "Neuer Zugang + QR" (vormals "Zugaenge
                       neu", Wunsch #131). Bewusst ohne Redirect danach: ein
                       Redirect muesste den Token ueber die Adresszeile oder
                       die Flask-Session weiterreichen, beides waere genau das,
                       was der Umbau abschaffen sollte. Die Route `/qr.svg`
                       ist ersatzlos entfallen (sie musste den Token aus der DB
                       holen), der QR-Code steckt als data:-URI in der Antwort.
  23_geburtstage.py  – /a/geburtstage/<token>/ Gemeinsame Geburtstagsliste
                       Wunsch #158: /bearbeiten aendert Name/Tag/Monat/Jahr/
                       Notiz. Berechtigung ueber `_darf_aendern()` - dieselbe
                       Regel wie beim Loeschen (Urheber, Eltern, Admin), weil
                       der Eintrag fuer alle gilt. `erstellt_von` wird NICHT
                       mitgeschrieben, sonst verloere der Eintragende die
                       Zustaendigkeit, sobald jemand anderes einen Tippfehler
                       behebt. Die Pruefung teilen sich Anlegen und Bearbeiten
                       (`_eingaben_lesen()`). `geburtstag_gesendet` wird beim
                       Aendern NICHT geleert - die Tabelle schluesselt auf den
                       VERSANDTAG, eine Korrektur kann also keine kuenftige
                       Erinnerung unterdruecken.
  24_ki_budget.py    – /a/admin/<token>/ki  KI-Verbrauch je Nutzer und
                       OpenRouter-Guthaben (Wunsch #183). Nur Admins.
                       Zwei Guthaben-Begriffe, die nicht dasselbe sind:
                       `/api/v1/credits` = Konto (gekauft minus Gesamt-
                       verbrauch), `/api/v1/key` = Limit DIESES Schluessels
                       mit monatlichem Reset. `guthaben_lesen()` nimmt den
                       KLEINEREN - ist eines von beiden leer, geht keine
                       Anfrage mehr durch; nur aufs Konto zu schauen
                       uebersieht ein aufgebrauchtes Monatslimit.
                       Betraege sind USD, nicht EUR (der Wunsch sagt Euro).
                       `guthaben_pruefen()` laeuft stuendlich als Daemon-
                       Thread (Schalter `KI_GUTHABEN_WACHT`, im Test 0) und
                       legt bei <= 1,00 USD EINE Aufgabe fuer den ersten
                       Admin an + Push. Deduplizierung ueber
                       `_aufgabe_schon_offen()`: solange eine offene Aufgabe
                       mit der Marke existiert, entsteht keine zweite.
                       Antwortet OpenRouter nicht, passiert NICHTS - ein
                       Netzwerkfehler ist kein leeres Konto.
                       (Wunsch #145). Eingetragen wird fuer alle, EINGESTELLT
                       fuer sich: Ausblenden, Erinnerung am Tag und
                       Vorlauf-Erinnerung stehen je (user_id, geburtstag_id).
                       `_tage_bis()` rechnet ueber den Jahreswechsel und weicht
                       beim 29. Februar in Nicht-Schaltjahren auf den 1. Maerz
                       aus. Der taegliche Versand laeuft in einem
                       Hintergrund-Thread HIER und nicht in `util`, weil
                       push_send() und die VAPID-Schluessel im Portal liegen -
                       in util muesste man das Geheimnis duplizieren oder einen
                       weiteren Endpunkt absichern. Unkritisch, weil Gunicorn
                       mit EINEM Worker laeuft; gegen Wiederholung nach einem
                       Neustart schuetzt `geburtstag_gesendet`. Schalter
                       GEBURTSTAGS_ERINNERUNGEN (im Test immer 0 - ein Thread,
                       der nebenher in dieselbe SQLite-Datei schreibt, liess
                       die Fixtures mit "database is locked" auflaufen).
  templates/
    base.html               – Grundlayout: App-Header (⌂ links, ☰ rechts), Hamburger-Menü
                              (Dark Mode, Hilfe, ✨ Wunsch), SW-Registration, Manifest-Link;
                              ✨-Handler lädt die Seite neu, wenn die Werkstatt-Seite
                              selbst gerade offen ist und die Meldung erfolgreich
                              gespeichert wurde (Wunsch #60, kein Cross-Device-Sync)
    startseite.html         – Startseite: App-Kacheln in Gruppen, Drag-&-Drop Sortierung,
                              Edit-Mode (✎/✓), Gruppen anlegen/umbenennen/löschen
    denied.html             – Zugang verweigert / Landing ohne Token
    admin.html              – Nutzerverwaltung, Rollen-Badge, Grant-Chips, QR-Modal, Push-Abo-Badge
    admin_user_form.html    – Nutzer anlegen/bearbeiten (Farbe, Rolle, Admin-Flag)
    admin_zugang.html       – Wunsch #140 Stufe 6: zeigt EINEN frisch erzeugten
                              Zugang (Link, QR als data:-URI, Kopierknopf) mit
                              deutlichem "Nur jetzt sichtbar"-Hinweis. Die
                              einzige Seite im Portal, die je einen Token
                              anzeigt
    todo.html               – Aufgabenliste (neu, zuweisen an Person/Rolle(n)/Alle,
                              erledigen; ✏️-Panel bearbeitet dieselben Felder wie das
                              Neu-Formular, gemeinsames Macro ziel_auswahl())
    werkstatt_app.html      – Wunschliste mit Admin-Aktionen; Karte antippen
                              klappt Detailansicht auf (Wunsch #101: Wunsch,
                              Benutzer, Wunsch-/Implementierungsdatum, Umsetzung).
                              `.wunsch-card` braucht `flex-wrap:wrap` (Wunsch #104 -
                              fehlte, das `flex:1 0 100%`-Detailpanel darunter konnte
                              deshalb nicht in eine eigene Zeile umbrechen und
                              quetschte sich stattdessen mit in die Kopfzeile, auf
                              schmalen Bildschirmen (iPhone) deutlich sichtbar).
                              Die Klassennamen `.wunsch-card`/`.wunsch-actions`
                              kollidierten ausserdem mit den gleichnamigen Klassen
                              des globalen ✨-Formulars in base.html (Wunsch #105 -
                              siehe dort, base.html nutzt seit dem Fix eigene
                              `.wunsch-modal-*`-Namen)
    geholfen.html           – Tipp-Grid (Fetch-AJAX, kompakte Kacheln), 10-Tage-Heatmap
                              je Nutzer (eltern/kind), "Als wer?"-Pill (eltern/admin)
    geholfen_verlauf.html   – Letzte 50 Einträge, eigene Seite (Menü: "Zuletzt geholfen")
    geholfen_uebersicht.html – 7-Tage-Statistik, Punkte pro Nutzer, 30-Tage-Kalender
                              (Menü: "Statistik", admin-only)
    geholfen_aufgaben.html  – Aufgaben verwalten (hinzufügen, deaktivieren,
                              umbenennen über ✏️-Panel je Aufgabe – Wunsch #96)
    hilfe.html              – Erklärungen zu allen Apps und Funktionen; Inhaltsverzeichnis
                              am Anfang mit Sprunglinks zu allen 13 Kapiteln (id="kapitel-N",
                              Wunsch #57) + fixer Nach-oben-Button (Wunsch #56)
    einkauf.html            – Einkaufsliste: Kategorien-Gruppen (+ "Ohne Kategorie"-
                              Fallback), Angebot, Laden, Autocomplete; letzte Kategorie/
                              Angebot/Markt-Auswahl im Hinzufügen-Formular bleibt über
                              sessionStorage tabübergreifend bis zum Tab-/Browser-Schluss
                              erhalten (Wunsch #58, kein Serverfeld)
    einkauf_laeden.html     – Laden-Verwaltung (Admin)
    einkauf_kategorien.html – Kategorien-Verwaltung (Admin, Wunsch #37): anlegen,
                              ✏️-Panel zum Umbenennen, aktivieren/deaktivieren;
                              ⠿-Drag&Drop zum Umsortieren (Wunsch #38, großzügiger
                              Tap-Target seit Wunsch #46)
    packliste.html          – Packliste (Wunsch #111): Ziel-Umschalter oben
                              (immer nur ein Ziel aktiv), Kategorie-Gruppen wie
                              Einkauf, "🧳 Packen starten" (Personenwahl, dann
                              body.packmodus wie Einkaufs Einkaufsmodus),
                              Person-Badge je Eintrag (Nutzerfarbe, "22"-Alpha-
                              Suffix fürs transparente Hintergrund-Hex); letzte
                              Kategorie/Person-Auswahl bleibt übers Hinzufügen-
                              Formular hinweg per sessionStorage erhalten
                              (gleiches Muster wie Einkaufs Wunsch #58)
    packliste_ziele.html    – Ziel-Verwaltung (Admin) - anlegen/aktivieren/
                              deaktivieren, bewusst ohne Umbenennen (wie
                              einkauf_laeden.html)
    packliste_kategorien.html – Kategorien-Verwaltung (Admin) - Code praktisch
                              identisch zu einkauf_kategorien.html (anlegen,
                              ✏️-Panel umbenennen, aktivieren/deaktivieren,
                              ⠿-Drag&Drop zum Umsortieren)
    tvb.html                – TVB Stuttgart (Wunsch #120): drei Kacheln
                              "Nächste Spiele"/"Ergebnisse"/"Tabelle",
                              TVB Stuttgart per .tvb-Klasse fett bzw. Tabellen-
                              zeile hervorgehoben (var(--surface-2)); jede
                              Kachel zeigt bei Abruffehler eine eigene 📡-
                              Meldung statt die ganze Seite abzubrechen
                              (gleiches Muster wie sportschau.html).
                              Wunsch #121: .kader-btn ganz oben verlinkt die
                              Kader-Unterseite (zusaetzlich als Menuepunkt in
                              base.html, zeigt_tvb_items).
                              Wunsch #122: .team-leiste ganz oben ist der
                              Mannschafts-Umschalter - eine EINZEILIGE,
                              horizontal scrollbare Chip-Leiste
                              (overflow-x:auto, Scrollbalken ausgeblendet),
                              kein Umbruch: 18 Chips wuerden sonst vier
                              Zeilen fuellen und den Inhalt nach unten
                              schieben. Chips sind 40px hoch (dieselbe
                              Antippflaeche wie die Zeitraum-Knoepfe der
                              Sportschau). Darunter .team-liga mit Name +
                              ausgeschriebener Liga der gewaehlten
                              Mannschaft. Die Hervorhebung der eigenen
                              Mannschaft vergleicht gegen `gewaehlt.name`
                              statt fest gegen "TVB Stuttgart".
                              Wunsch #125: .team-scroll-hinweis links/rechts
                              im .team-leiste-wrap - weicher Verlauf in
                              var(--bg) plus ‹/›, je Seite nur eingeblendet,
                              wenn dort wirklich noch etwas kommt (JS setzt
                              .kann-links/.kann-rechts am Wrap beim Scrollen
                              und beim Resize). pointer-events:none, damit
                              die Chips darunter antippbar bleiben - der
                              Hinweis zeigt nur an, er ist kein Bedienelement.
                              Dasselbe Skript scrollt beim Laden die aktive
                              Mannschaft in den sichtbaren Bereich
    tvb_mannschaften.html   – Altersklassen aus-/einblenden (Wunsch #124):
                              je Klasse eine Checkbox mit Anzahl Mannschaften,
                              "Alle an"/"Alle aus", Profis fest angehakt und
                              disabled ("immer sichtbar"). Eigener
                              ←-Zurueck-Link, POST/Redirect/GET mit
                              ?gespeichert=1 als Bestaetigung
    tvb_kader.html          – Kader mit Spielerwerten (Wunsch #121): nach
                              Position gruppiert (Tor → Kreisläufer, deutsche
                              Labels aus _POSITIONEN), je Spieler HPI-Schnitt,
                              letzter Wert mit ▲/▼-Trend (gruen/rot) sowie
                              Spieltage/Aktionen; Saisonname ueber der Liste,
                              Legende unten erklaert den HPI. Eigener
                              ←-Zurueck-Link (nav_left) zur TVB-Hauptseite.
                              ▲/▼ sind normale Unicode-Zeichen, keine Emoji -
                              brauchen also (wie ★☰✎✓✕) keine Twemoji-SVG
    kassenbuch_uebersicht.html – Nur fuer Eltern/Admin (Wunsch #144): Kachel
                              je Kind mit Namen + Kontostand, Link zur
                              Detailansicht. Kind ohne Startbetrag zeigt
                              "noch nicht eingerichtet" statt eines Betrags
    kassenbuch.html         – Kassenbuch-Detailansicht, dient sowohl dem
                              Kind selbst (eigenes_buch=True, mit Formularen)
                              als auch Eltern/Admin (eigenes_buch=False,
                              read-only) - dieselbe Vorlage, `eigenes_buch`
                              blendet Eintrags-/Storno-Formulare aus. Vor dem
                              ersten Startbetrag nur das Setup-Formular, kein
                              Kontostand. Art-Wahl (Einnahme/Ausgabe) aendert
                              per kbArtGewaehlt() live die Beschriftung des
                              Personen-Felds ("Von wem?"/"An wen?")
    rezepte.html            – Rezeptliste + "+ Neues Rezept"-Button (Wunsch #48);
                              Live-Suche über Titel+Zutaten ab 3 Zeichen (Wunsch #49)
                              + Kategorie-Filter-Chips (Wunsch #55), beide Filter
                              kombiniert über data-suche/data-kategorie-Attribute;
                              zeigt Durchschnittsbewertung je Karte (Wunsch #54);
                              Wunschliste-Knopf als Ja/Nein-Chip "Wünschen?"/"✓
                              Gewünscht" statt Stern (Wunsch #72, kollidierte
                              optisch mit der ⭐-Bewertung), Filter-Chip "📌
                              Gewünscht"
    rezept_neu.html         – Neu-/Bearbeiten-Formular als eigene Unterseite (Name,
                              Portionen, Kategorie-Chips Keine/Kochen/Backen,
                              Zutaten je Zeile, Zubereitung je Zeile = ein Schritt),
                              "← Zurück" zur Übersicht bzw. Detailseite im
                              Bearbeiten-Modus; zeigt bei per URL importierten
                              Rezepten einen Hinweis-Banner ("bitte prüfen") – nicht
                              beim Bearbeiten, obwohl dieselbe vorbelegt-Struktur
                              genutzt wird (bearbeiten-Parameter unterscheidet)
    rezept_importieren.html – URL-Eingabe für den Rezept-Import, zeigt Fehler
                              (nicht abrufbar, kein Rezept erkannt, KI-Kontingent
                              aufgebraucht) statt eines 500ers
    rezept_bild_importieren.html – Foto-Upload für den Rezept-Import (Wunsch #97,
                              Kamera oder Mediathek), zeigt dieselben Fehlerarten
                              wie rezept_importieren.html. Datei-Input bewusst OHNE
                              capture="environment" (Wunsch #106 - das Attribut
                              zwingt iOS Safari zur Kamera, ohne Mediathek-Option)
    rezept_detail.html      – Ein Rezept: Info-Abschnitt oben (Portionen +
                              Durchschnittsbewertung + eigener Sterne-Picker,
                              Wunsch #52/#53, plus Ja/Nein-Wunschliste-Knopf seit
                              Wunsch #72) über der Zutatenliste; Zutaten mit
                              "🛒 Fehlt"-Knopf, Zubereitung als nummerierte Schritte,
                              "✏️ Bearbeiten"/"🗑️ Löschen" nebeneinander
    essensplan.html         – 14-Tage-Ansicht (2 Wochen) mit "Aktuelle Woche"/"Nächste
                              Woche"-Überschriften, je Tag Mittag+Abend-Slot mit
                              Rezept-Auswahl oder Freitext, ⠿-Drag&Drop zum Verschieben,
                              vergangen/heute/zukunft-Styling, vergangene Tage in
                              <details>-Block einklappbar (tag_karte-Macro für alle
                              drei Tages-Listen)
    kinderplan.html         – Aufgabenplan: Wochentag-Karten, Aufgaben-Chips zum
                              Zuweisen, Abhaken für heute, Wessen-Plan-Umschalter
    sportschau.html         – Trainings-Heatmap (Wunsch #62), Zeilen sind
                              Trainingsarten; Name steht in eigener Zeile über
                              den Heatmap-Zellen statt fester Breite mit
                              Ellipsis (Wunsch #74 – geholfen.html hat kurze
                              Namen und ist davon nicht betroffen, dort
                              unverändert); darunter gestapeltes
                              Balkendiagramm Schritte je Tag (Wunsch #77,
                              reines CSS/Flexbox, keine Chart-Bibliothek),
                              Hilfslinien alle 2000 Schritte, native
                              `title`-Tooltips je Balken (gleiches Muster wie
                              `title` auf `.heatmap-cell`)
    tierbaukasten.html      – SVG-Tierbaukasten (Wunsch #64), 3-Schritte-
                              Assistent + Mensch-Figur + Ansichten-Rotation
                              (Wunsch #66): Jinja-Macros pro Typ (Kopf/Körper
                              fest positioniert), Farben per CSS Custom
                              Properties (--koerper-farbe/--muster-farbe/
                              --koerperbau-scale), dieselben Macros für
                              Bau-Vorschau (JS-Umschaltung, alle 3 Ansichten
                              im DOM) und Galerie (nur Vorderansicht,
                              statisch). Ansichten: "vorne" voll editierbar
                              (Farbe/Muster/mehrere Accessoires – Wunsch #69),
                              "hinten" = gleiche Körperform ohne Gesicht,
                              "seite" = eigene vereinfachte Silhouette;
                              Muster in allen drei Ansichten sichtbar (Wunsch
                              #68 – je Ansicht ein eigener, korrekt im DOM
                              positionierter muster-container-<ansicht> mit
                              eigenem Clip-Pfad, siehe Bekannte Issues),
                              Accessoires nur in der Vorderansicht (feste
                              Positionen passen nicht zu Seiten-/Rückansicht).
                              Mensch-Figur (Feedback von Friederike,
                              2026-07-29) läuft NICHT über diese SVG-Macros,
                              sondern zeigt ein serverseitig per DiceBear/
                              Avataaars gerendertes SVG (per Fetch,
                              `#mensch-vorschau-svg`), eigener
                              Anpassungsbereich `#mensch-anpassung` mit
                              Farbschwatches/Selects/Chips statt Farbwähler/
                              Muster/Körperbau/Tier-Accessoires; keine
                              Seiten-/Rückansicht (Avataaars liefert nur
                              eine Frontalansicht)
    vokabeln.html           – Hauptseite (Wunsch #73, Neubau): inline
                              Eintragen-Formular (Sprache-Chips, Fremd/Deutsch,
                              Kapitel-Checkboxen), Live-Suche über fremd+deutsch,
                              Liste mit ✏️-Panel je Vokabel (wie geholfen_verlauf)
    vokabel_sprachen.html   – Sprachen pro Nutzer aktivieren/deaktivieren
                              (Toggle-Switches, Auto-Submit)
    vokabel_kapitel.html    – Kapitel anlegen/umbenennen/deaktivieren, gleiches
                              Muster wie einkauf_kategorien.html (ohne Reorder)
    vokabel_lernen.html     – Trainer-Chooser: Sprache (Chips) + Kapitel
                              (Checkboxen, "Alle" deaktiviert die Einzelauswahl)
    vokabel_training.html   – Trainer: Warteschlange als JSON im Script-Block
                              (`|tojson` OHNE forceescape, siehe Bekannte Issues),
                              zufällige Abfragerichtung, falsche Antworten ans
                              Ende der Warteschlange, /versuch je Antwort,
                              Sitzungsende per Button, pagehide + sendBeacon;
                              "🔊 Anhören"-Knopf nach jeder Antwort (Wunsch #81,
                              spielt /wort/<vid>/audio über `new Audio()` ab)
    vokabel_foto_import.html – Foto-Upload (Wunsch #80): Sprache-Chips,
                              gleiches Fehler-Anzeige-Muster wie
                              rezept_importieren.html. Datei-Input bewusst OHNE
                              capture="environment" (Wunsch #106, siehe
                              rezept_bild_importieren.html für die Begründung)
    vokabel_foto_pruefen.html – Von der KI erkannte Vokabelpaare zur Kontrolle:
                              jede Zeile mit Checkbox (behalten/verwerfen) +
                              editierbaren Fremd-/Deutsch-Feldern, ein
                              gemeinsames Kapitel für den ganzen Stapel,
                              speichert erst bei explizitem Absenden
    vokabel_auswertung.html – Auswertung (Wunsch #79): Balken für Trainingszeit
                              je Sprache (Einzelfarbe var(--farbe)), gestapelter
                              Balken richtig/falsch je Kapitel (Grün/Rot 1:1 aus
                              vokabel_training.html), Wortlisten-Chips gelernt/
                              schwierig/ungeübt; Nutzer-Pills nur für Eltern/Admin
static/
  manifest.json      – PWA-Manifest (Fallback ohne Nutzer-Token)
  icon-192.png       – Generiert im Dockerfile (weiße "16" auf Marken-Blau, kein Pillow)
  icon-512.png
  favicon-32.png     – Browser-Tab-Icon
  favicon-16.png
  sw.js              – Service Worker für Push-Benachrichtigungen + Offline-
                       Caching (Network-first/Cache-Fallback fuer eigene
                       GET-Requests, siehe Kapitel "Offline-Faehigkeit" unten).
                       Registrierung in base.html mit `{scope:'/'}` -
                       braucht den Service-Worker-Allowed-Header von 00_kern.py,
                       sonst bleibt der Scope auf /static/ beschraenkt
```

### Offline-Fähigkeit

Rein-App-Infrastruktur (kein ✨-Wunsch, per Chat-Anfrage 2026-07-31): jede
App hat ein `apps.offline_faehig`-Flag (Default 0, per Migration in
`00_kern.py` gesetzt, NICHT per `manage.py` frei umschaltbar - das ist eine
Entwicklerentscheidung, ob die App offline sicher ist, kein Admin-Setting).
`manage.py listapps` zeigt den Stand. Aktuell `hilfe` (rein statischer Text)
und `einkauf` (siehe unten) offline_faehig=1, alle anderen Apps werden auf
der Startseite grau + nicht anklickbar, sobald `navigator.onLine` false ist.
Der Service Worker selbst cached opportunistisch JEDE besuchte Seite
(unabhängig vom Flag, technisch harmlos) - die eigentliche Sperre ist reines
Startseiten-Kachel-Gating, nicht der Service Worker.

**Offline-Schreiben (bisher nur `einkauf`):** Formulare/POST laufen normal
NIE über den Service Worker (der fängt nur GET ab) und scheitern offline
einfach. Für `einkauf` gibt es zusätzlich eine clientseitige Warteschlange
(`localStorage`, Schlüssel `einkauf_offline_queue`) für Abhaken und
Neu-Eintragen: schlägt der Live-Request fehl, landet die Aktion dort statt
zu scheitern, wird synchronisiert bei `online`-Event oder beim nächsten
Laden der Seite (siehe `10_einkauf.py`/`einkauf.html` und journal.md
2026-07-31). Bearbeiten/Löschen sind bewusst NICHT Teil davon - laufen
weiterhin als normales natives Formular, zeigen aber vor dem Absenden
einen Toast statt der Browser-eigenen Fehlerseite, wenn `navigator.onLine`
false ist (`pruefeVerbindungOderZeigeHinweis()`/`pruefeLoeschenOnline()`,
Löschen prüft VOR dem `confirm()`-Dialog).

## Adressen ohne Token (Wunsch #140, Stufe 4)

Seit v120/v121 steht in keiner ausgelieferten Seite mehr ein Zugangstoken.
**Alte Links mit Token bleiben unveraendert gueltig** - sie sind der
Ersteinstieg (QR-Code) und die Rueckfallebene.

Jede Route hat zwei Regeln: die alte mit `<token>` und eine token-freie
Zwillingsregel. Beide landen in derselben View-Funktion; `grant()` entscheidet
wie seit Stufe 3, ob Pfad-Token oder Cookie zaehlt:

```python
@bp.route("/a/tvb/", defaults={"token": None})
@bp.route("/a/tvb/<token>/")
def index(token): ...
```

Adressen werden ausschliesslich aus diesen vier Bausteinen gebaut (alle in
`00_kern.py`, als Jinja-Globals registriert). **Wer eine Adresse von Hand
zusammensetzt, umgeht den Notausstieg-Schalter.**

| Baustein | wofuer |
|---|---|
| `tp` | Wegstueck in der GERADE offenen App: `/a/todo{{ tp }}neu` |
| `app_pfad(slug, token)` | Link in eine ANDERE App (Startseite-Kacheln, Hilfe-Knopf) |
| `start_pfad(home_token)` | der ⌂-Knopf |
| `manifest_pfad(home_token)` | das PWA-Manifest |

`tp` kommt aus `request.view_args`, NICHT aus der Template-Variablen `token` -
die Links sollen der Adresszeile folgen, und view_args sagt genau, was dort
steht.

**Fallstricke, die hier schon einmal zugeschlagen haben:**

- `{{ token }}` rendert bei `None` die Zeichenkette **"None"**. Fuer JS
  deshalb immer `{{ (token or '')|tojson }}`, nie `'{{ token }}'`.
- Sichtbarkeits-Bedingungen in Vorlagen pruefen `user`, nie `token` - sonst
  verschwindet auf token-freien Seiten das halbe Menue.
- Die vier Endpunkte mit Token im JSON-Body (`/wunsch`, `/push/subscribe`,
  `/push/unsubscribe`, `/settings/darkmode`) haben keinen Pfad-Token und
  muessen ueber `aktueller_nutzer()` gehen. Der faellt wie `grant()` aufs
  Cookie zurueck. Ohne ihn: stilles 403, kein sichtbarer Fehler.
- `sw.js` cacht token-freie Adressen fuer alle Nutzer gleich. Jede Seite
  meldet dem Service Worker ueber `postMessage` den aktuellen Nutzer; beim
  Wechsel wirft er den Seiten-Cache weg. Sonst saehe auf einem geteilten
  Geraet der naechste Nutzer offline die Seiten des vorigen.
- **`/p/<token>` ist NIE im Cache.** Die Route antwortet mit 302; eine
  Navigation hat `redirect: 'manual'`, die Antwort kommt als opaqueredirect an
  und `resp.ok` ist false. Weil PWA und alte Lesezeichen genau dort starten,
  liefert `sw.js` bei einer fehlschlagenden **Navigation** ersatzweise die
  gecachte `/start`. Ohne diesen Zweig ist jeder Offline-Start eine Sackgasse,
  die sich durch Benutzen nicht heilt. Nur fuer Navigationen - `fetch()`-
  Aufrufe erwarten JSON.
- `CACHE_NAME` steht auf `portal-cache-v2`. **Nicht ohne Not hochziehen:** Ein
  Namenswechsel wirft den gesamten Offline-Bestand weg, jede Seite braucht
  danach wieder einen Online-Besuch. In v122 war das beabsichtigt (die alten
  Eintraege trugen Token in den Links), sah im Alltag aber wie ein Dauerfehler
  aus.
- Das PWA-Manifest haengt token-frei am Cookie und braucht deshalb
  `crossorigin="use-credentials"` am `<link>` - sonst holt der Browser es
  ohne Cookies und bekommt 404.

Die Verwaltungsseite (`admin.html`) zeigt weiterhin absichtlich die vollen
Links her - dafuer ist sie da. Dass sie das tut, ist ein eigener Befund aus
der Sicherheitsanalyse und Gegenstand von Stufe 6 (echtes Hashing).

## Datenbankschema (SQLite, WAL)

| Tabelle | Inhalt |
|---------|--------|
| `users` | id, name, farbe, is_admin, ki_key (ungenutzt), dark_mode, rolle ('eltern'/'kind'/'gast'), ki_token_limit (Monats-Kontingent für ki_anfrage(), Default 100000, im Admin editierbar), ki_tts_zeichen_limit (Monats-Kontingent für ki_text_zu_sprache(), Default 50000 Zeichen, Wunsch #136, im Admin editierbar) |
| `ki_nutzung` | id, user_id, feature (z. B. "rezepte_import"), tokens, erstellt – Verbrauchs-Log für ki_anfrage(), gemeinsames Kontingent über alle KI-Features |
| `ki_tts_nutzung` | id, user_id, feature ("vokabeln_tts"), zeichen, erstellt – Verbrauchs-Log für ki_text_zu_sprache() (Wunsch #136). EIGENE Tabelle, nicht in ki_nutzung: die zählt SUM(tokens) ohne Feature-Filter, Zeichen und Tokens dürfen sich nicht vermischen |
| `apps` | id, slug, name, emoji, beschreibung |
| `grants` | id, user_id, app_id, **token_lookup** (UNIQUE, HMAC-SHA256 des Tokens – findet die Zeile, nicht umkehrbar), position (sort), gruppe_id (FK home_gruppen) – Wunsch #140 Stufe 6: `token_enc` ist entfallen, es gibt **keinen** Weg mehr zum Klartext. Ein Link ist nur im Moment seiner Erzeugung sichtbar (`_zugang_anzeigen()` in `03_admin.py`) |
| `home_gruppen` | id, user_id, name, position – per-user app groups |
| `sitzungen` | id, user_id (FK users, cascade), kennung_lookup (UNIQUE, HMAC des Cookie-Werts – der Klartext steht NIE in der DB), erstellt, gesehen, ablauf (NULL = läuft nie ab, z. B. Kiosk), quelle ('token'/'ha'), geraet (User-Agent, gekürzt) – Wunsch #140 Stufe 1: Sitzungs-Cookies. Eigene Tabelle statt signiertem Cookie, weil nur so ein Widerruf je Gerät möglich ist |
| `push_abos` | id, user_id, endpoint, p256dh, auth, geraet |
| `wuensche` | id, text, titel, prioritaet, user_id, app_slug, ansicht (app_slug/unterseite, token-frei – Wunsch #47), erstellt, erledigt, erledigt_am, umsetzung (Wunsch #101: was genau implementiert wurde, gesetzt über `manage.py wunsch_erledigt <id> "Text"`) |
| `todos` | id, inhalt, erstellt_von, zugewiesen_an, zugewiesen_rollen (TEXT, kommagetrennt, Sentinel "alle" – Wunsch #39, exklusiv zu zugewiesen_an), privat, erledigt, erledigt_am, erstellt, status ('backlog'/'offen'/'in_arbeit'/'erledigt', mit erledigt synchron gehalten), serie_id (FK todo_serien, NULL bei normalen Todos – Wunsch #90), wochentag (totes Altfeld – urspr. 0=Mo..6=So für Wunsch #90, nie mit Produktivdaten gefüllt, durch plan_tag ersetzt – Wunsch #92), plan_tag (ISO-Datum, nur bei serie_id gesetzt – Wunsch #92) |
| `todo_serien` | id, inhalt, wiederkehr_typ ('intervall'/'wochentag'), intervall_tage, fester_wochentag (totes Altfeld seit Wunsch #112, ersetzt durch feste_wochentage), feste_wochentage (kommagetrennt, z. B. "1,3,5", mehrere Wochentage gleichzeitig – Wunsch #112), aktiv, erstellt_von, erstellt – Wunsch #90, Pool-Vorlagen fuer wiederkehrende Aufgaben |
| `todo_historie` | id, todo_id (FK todos, cascade), alter_inhalt, geaendert_von, geaendert_am |
| `geholfen_aufgaben` | id, name, emoji, gewichtung, aktiv |
| `geholfen_eintraege` | id, aufgabe_id, user_id, zeitstempel |
| `einkauf_laeden` | id, name, aktiv |
| `einkauf_kategorien` | id, name (UNIQUE), position, aktiv |
| `einkauf_eintraege` | id, name, kategorie (Alttext, historisch), kategorie_id (FK einkauf_kategorien), angebot, laden_id, erledigt, erledigt_am, erstellt, erstellt_von, geaendert (Wunsch #100: bei jedem INSERT/UPDATE explizit gesetzt, Grundlage für den /stand-Sync-Fingerabdruck) |
| `packlisten_ziele` | id, name (UNIQUE), aktiv – Wunsch #111, wie einkauf_laeden aber ohne Umbenennen |
| `packlisten_kategorien` | id, name (UNIQUE), position, aktiv – Wunsch #111, identisch zu einkauf_kategorien |
| `packlisten_eintraege` | id, name, ziel_id (FK packlisten_ziele, cascade – ein Eintrag gehört zu GENAU EINEM Ziel), kategorie_id (FK packlisten_kategorien), person_id (FK users, SET NULL – NULL = "allgemein"), gepackt, gepackt_am, erstellt, erstellt_von |
| `packlisten_nutzer_ziel` | user_id (PK, FK users, cascade), ziel_id (FK packlisten_ziele, cascade) – Wunsch #116, zuletzt geöffnetes Ziel pro Nutzer, per UPSERT gepflegt |
| `rezepte` | id, name, portionen (Freitext, z. B. "4" oder "4-6 Portionen"), kategorie ('kochen'/'backen'/NULL – Wunsch #55), quelle_url (NULL außer bei URL-Import – Wunsch #63), anleitung (totes Altfeld, siehe Bekannte Issues), erstellt_von, erstellt |
| `rezept_zutaten` | id, rezept_id (FK rezepte, cascade), name, position |
| `rezept_schritte` | id, rezept_id (FK rezepte, cascade), text, position – ein Zubereitungsschritt pro Zeile, analog zu rezept_zutaten |
| `rezept_bewertungen` | id, rezept_id (FK rezepte, cascade), user_id (FK users, cascade), sterne (1-5), erstellt; UNIQUE(rezept_id, user_id) – eine Bewertung pro Nutzer und Rezept, editierbar per Upsert |
| `rezept_wuensche` | id, rezept_id (FK rezepte, cascade), user_id (FK users, cascade), erstellt; UNIQUE(rezept_id, user_id) – "Wünsch ich mir"-Markierung, max. 5 aktive pro Nutzer (Wunsch #65), automatisch entfernt sobald das Rezept nach der Markierung auf dem Essensplan war und der Tag vorbei ist |
| `essensplan_eintraege` | id, tag (ISO-Datum), mahlzeit ('mittag'/'abend'), rezept_id (FK rezepte), text, erstellt_von, erstellt; UNIQUE(tag, mahlzeit) |
| `kinderplan_eintraege` | id, user_id (FK users, cascade), aufgabe_id (FK geholfen_aufgaben, cascade), wochentag (0=Mo..6=So, seit Wunsch #115 nur noch informativ/nicht mehr fuer die Anzeige genutzt), plan_tag (ISO-Datum, Wunsch #115 - der eigentliche Einzeltermin), position, erstellt; UNIQUE(user_id,aufgabe_id,plan_tag) |
| `tierbaukasten_kreationen` | id, user_id (FK users, cascade), tier_typ (auch 'mensch' – Wunsch #66, keine eigene Kategorie-Spalte), koerper_farbe, muster (NULL/streifen/punkte/flecken), muster_farbe, accessoire (kommagetrennte Liste, z. B. "hut,brille" – Wunsch #69), koerperbau (0-100, Default 50 – Wunsch #66), dicebear_optionen (JSON, nur bei tier_typ='mensch' befüllt, siehe DiceBear-Notiz unten), name, erstellt – Wunsch #64 |
| `vokabel_sprachen` | id, name (UNIQUE), aktiv – global, Standard Englisch+Latein, neue per Wunsch – Wunsch #73 |
| `vokabel_sprachen_nutzer` | user_id (FK users, cascade), sprache_id (FK vokabel_sprachen, cascade); UNIQUE(user_id,sprache_id) – welche Sprachen ein Nutzer aktiviert hat |
| `vokabel_kapitel` | id, user_id (FK users, cascade), name, aktiv, erstellt – pro Nutzer, gruppiert eigene Vokabeln |
| `vokabeln` | id, user_id (FK users, cascade), sprache_id (FK vokabel_sprachen, cascade), fremd, deutsch, erstellt – Wunsch #73 (ersetzt das alte liste_id/quelle/ziel-Schema aus Wunsch #67 vollständig, Migration siehe journal.md 2026-07-30) |
| `vokabel_kapitel_zuordnung` | vokabel_id (FK vokabeln, cascade), kapitel_id (FK vokabel_kapitel, cascade); UNIQUE(vokabel_id,kapitel_id) – m:n, eine Vokabel kann mehreren Kapiteln oder keinem angehören |
| `vokabel_sessions` | id, user_id (FK users, cascade), sprache_id (FK vokabel_sprachen), gestartet, beendet (NULL = noch offen) – ein Trainer-Durchgang |
| `vokabel_versuche` | id, session_id (FK vokabel_sessions, cascade), vokabel_id (FK vokabeln, cascade), richtig (0/1), beantwortet – ein protokollierter Abfrage-Versuch |
| `ki_konfiguration` | zweck (PK, z. B. "rezepte_import"/"vokabeln_ocr"/"rezepte_foto_import" – Wunsch #97), modell – Wunsch #81 (Grundprinzip): Modellwahl je KI-Zweck in der DB statt fest im Code, per `manage.py ki_modell` änderbar |
| `ki_stimmen` | sprache_id (PK, FK vokabel_sprachen, cascade), modell, stimme – Wunsch #81: TTS-Modell/Stimme je Vokabeln-Sprache, per `manage.py ki_stimme` änderbar |
| `tvb_spiele` | id (PK, handball.net-Spiel-ID), team_id (Wunsch #122 – ohne die würden sich die Spiele aller 18 Mannschaften vermischen; Altbestand einmalig auf die Profi-ID gesetzt), spieltag, heim, gast, heim_tore, gast_tore, anstoss (ISO, Europe/Berlin), ort, status ('Pre'/'Live'/'Ended'), wettbewerb (Wunsch #151 – Name des Wettbewerbs; NULL bei Altbestand, weil nachtraeglich nicht rekonstruierbar), aktualisiert_am – Wunsch #120: Opportunistic-Cache, jedes bei einem Seitenaufruf gesehene TVB-Spiel wird per UPSERT gespeichert, da die Datenquelle selbst nur ein kleines Zeitfenster liefert |
| `tvb_ausgeblendet` | user_id (FK users, cascade), altersklasse (Kürzel aus `_ALTERSKLASSEN`, z. B. „mC"/„gE"); PK(user_id, altersklasse) – Wunsch #124: welche Altersklassen DIESER Nutzer im Umschalter ausgeblendet hat. Gespeichert wird bewusst das Ausgeblendete, nicht das Sichtbare (neue Klassen sind dann automatisch sichtbar) |
| `tvb_mannschaften` | team_id (PK, handball.net-Team-ID), name, liga (volle Bezeichnung), kurz (Chip-Label, z. B. „mB BOL 2"), altersklasse (Kürzel für den Nutzerfilter, Wunsch #124 – bei den Profis „Profis"), turnier_id (Liga-ID für die Tabelle, anfangs NULL – wird bei der ersten Ansicht der Mannschaft nachgeholt), position (Reihenfolge im Umschalter, 0 = Profis), ist_profi, aktualisiert_am – Wunsch #122: Registry aller 18 Mannschaften, alle 24 h aus der Vereinsseite neu geparst |
| `tvb_kader` | spieler_id (PK, HPI-Spieler-ID), vorname, nachname, position (englisch wie von der API geliefert, Übersetzung erst im Template über `_POSITIONEN`), hpi_schnitt, hpi_bestwert, hpi_letzter, hpi_trend (1/-1), spieltage, aktionen, saison_name, aktualisiert_am – Wunsch #121: Zeit-Cache (6 h) für die ~400 KB grosse HPI-Antwort; beim Neuladen wird die Tabelle geleert und neu gefüllt (Kader = Momentaufnahme, kein UPSERT – anders als `tvb_spiele`) |
| `geburtstage` | id, name, tag, monat, jahr (NULL = unbekannt), notiz, erstellt_von (FK users, **ON DELETE SET NULL** – der Geburtstag gehört der Familie, nicht dem Eintragenden), erstellt – Wunsch #145. tag/monat als ZAHLEN statt Datum: jährliche Wiederholung, Jahr oft unbekannt |
| `geburtstag_einstellungen` | user_id, geburtstag_id, ausgeblendet, erinnerung (am Tag), vorlauf_tage (NULL = keine Vorab-Erinnerung); PK(user_id, geburtstag_id) – die Einstellungen sind PRO NUTZER, fehlende Zeile = Standard |
| `geburtstag_gesendet` | user_id, geburtstag_id, art ('tag'/'vorlauf'), datum; PK über alle vier – ohne diese Tabelle schickte ein Container-Neustart am selben Tag dieselbe Erinnerung erneut |
| `vokabel_kapitel_freigabe` | kapitel_id (FK vokabel_kapitel, cascade), user_id (FK users, cascade – WER es zusaetzlich sehen darf), erstellt; PK(kapitel_id, user_id) – Wunsch #150. Geteilt wird das KAPITEL, nicht die Vokabel: spaeter hinzugefuegte Vokabeln wandern automatisch mit. Eigentuemer bleibt `vokabel_kapitel.user_id` |
| `rezept_gekocht` | id, rezept_id (FK rezepte, CASCADE), tag, mahlzeit, markiert_von (FK users, SET NULL), markiert_am; UNIQUE(rezept_id, tag, mahlzeit) – Wunsch #162. BEWUSST eine eigene Tabelle statt eines Haekchens auf essensplan_eintraege: ein Planeintrag wird ueberschrieben, verschoben (#35) und geloescht, die Historie muss das ueberleben. Haengt am REZEPT, nicht am Plan; Freitext-Eintraege koennen deshalb nicht abgehakt werden |
| `wunsch_aktionen` | id, wunsch_id (FK wuensche, CASCADE), art ('frage'/'antwort'/'plan'/'umsetzung'/'notiz'), text, user_id (FK users, SET NULL), erstellt – Wunsch #161: Verlauf je Wunsch. `wuensche.umsetzung` BLEIBT daneben bestehen, sie traegt die Abschluesse von ~150 alten Wuenschen, die es als Aktion nie geben wird. `manage.py wunsch_erledigt` schreibt ab #161 beides |
| `kassenbuch_eintraege` | id, user_id (FK users, cascade – das Kind, dem das Buch gehört), art ('start'/'einnahme'/'ausgabe'), betrag_cent (immer POSITIV, Vorzeichen kommt aus `art` – keine Fließkomma-Rundungsfehler), person ("Von wem?"/"An wen?", je EIN Feld für beide Richtungen), zweck, datum, erstellt_von, erstellt, storniert, storniert_von, storniert_am – Wunsch #144: unveränderlicher Ledger, "Löschen" = Stornieren (Zeile bleibt stehen, zählt aber nicht mehr zum Kontostand); der Start-Eintrag ist nie stornierbar |

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
| `hilfe` | Hilfe | ❓ | Erklärungen und Tipps (seit Wunsch #15 keine Startseiten-Kachel, nur Hamburger-Menü) | ✅ alle |
| `rezepte` | Rezepte | 🍲 | Lieblingsrezepte | – |
| `essensplan` | Essensplan | 🍽️ | Wochenplan fürs Essen | – |
| `kinderplan` | Aufgabenplan | 🗓️ | Wiederkehrende Aufgaben wochentagsweise planen | – |
| `sportschau` | Sportschau | 🏃 | Trainings-Heatmap vom hae-Server (Wunsch #62) | – (nur Andi) |
| `tierbaukasten` | Tierbaukasten | 🐾 | Eigene Figur (Mensch/Tier) aus Bausteinen, 3-Schritte-Assistent (Wunsch #64+#66+#69) | – (alle vier granted) |
| `vokabeln` | Vokabeln | 📚 | Vokabeln lernen mit Sprachen, Kapiteln und Trainer (Wunsch #73) | – (Andi, Simone, Friederike granted) |
| `packliste` | Packliste | 🧳 | Packlisten für Reisen/Ausflüge, je Ziel eine eigene Liste (Wunsch #111) | – (zunächst nur Andi als Urheber) |
| `tvb` | TVB | 🤾 | Nächste Spiele, Ergebnisse und Handball-Bundesliga-Tabelle des TVB Stuttgart (Wunsch #120) | – (alle vier granted) |
| `kassenbuch` | Kassenbuch | 🐷 | Taschengeld-Buchführung je Kind, Eltern/Admin sehen alle read-only (Wunsch #144) | ✅ alle |
| `geburtstage` | Geburtstage | 🎂 | Gemeinsame Geburtstagsliste; Ausblenden und Erinnerungen gelten je Nutzer (Wunsch #145) | ✅ alle |

## Testdatenbank leeren (conftest.py)

Seit Wunsch #162 **umgekehrt**: Die Fixture zaehlt nicht mehr auf, was geleert
wird, sondern was STEHEN BLEIBT (`BLEIBT` = die Seed-Tabellen: apps,
einkauf_kategorien, einkauf_laeden, geholfen_aufgaben, ki_konfiguration,
ki_stimmen, packlisten_kategorien, vokabel_sprachen). Alles andere wird
geleert.

Grund: Die alte Aufzaehlung musste bei jeder neuen Tabelle nachgezogen werden,
und wer es vergass, merkte nichts - der Bestand lief still ueber alle Tests
hinweg mit. Dreimal passiert: Geburtstage (#145, Zaehlungen drifteten),
Wuensche (#161, ein global zaehlender Test sah 4 statt 0), Essensplan (#162,
UNIQUE(tag, mahlzeit) kollidierte). Immer derselbe Grund: die Tabelle haengt
nicht per `ON DELETE CASCADE` am Nutzer.

**Wer eine neue SEED-Tabelle anlegt, traegt sie in `BLEIBT` ein.** Vergisst man
das, fehlen die Stammdaten und die Tests schlagen sofort und laut fehl - diese
Fehlerrichtung ist die richtige, die alte war es nicht.

## Werkstatt-Karte (Wunsch #182)

`.wunsch-actions` steht in einer EIGENEN Zeile (`flex-basis:100%`), nicht als
Spalte neben dem Text. Grund: Die Spalte hatte `flex-shrink:0` und gab keinen
Platz her - mit dem 185px breiten Prio-Picker aus #180 blieben auf einem 375er
iPhone rund 120px fuer den Wunschtext.

`.wunsch-text` ist auf vier Zeilen gedeckelt (`-webkit-line-clamp`). Der
Deckel faellt bei `.wunsch-card.offen` weg - sonst waere der Text auch
aufgeklappt gekuerzt und das Aufklappen wirkungslos. Die Klasse `offen` traegt
die KARTE und folgt dem Detail-Panel; laufen beide auseinander, bleibt der
Text gekuerzt, ohne dass jemand den Grund sieht.
`tests/test_werkstatt_ansicht.py` waechtert alles drei.

## Umsortieren per Ziehen (Wunsch #178)

`window.ziehSortierung({griff, eintrag, platzhalter, idAus, speichern})` in
`base.html` - der gemeinsame Helfer fuer alle neuen Sortierungen.

**Altbestand:** `packliste_kategorien.html` und `einkauf_laeden.html` haben je
eine eigene, fast wortgleiche Fassung derselben ~120 Zeilen. Sie wurden bei
#178 bewusst NICHT migriert (funktionieren, und ein Umbau war ohne sichtbaren
Browser nicht pruefbar). Wer sie anfasst, stellt sie bitte auf den Helfer um.

**`gruppe:`** (optional, Wunsch #181): Ohne diese Angabe sucht der Helfer die
Einfuegestelle ueber ALLE passenden Elemente der Seite. In einer nach
Kategorien gruppierten Liste springt ein Eintrag dann beim Ziehen ans
Listenende in die Nachbarkategorie - der naechste Kandidat unterhalb der
letzten Zeile ist deren erster Eintrag, und der steht hinter deren
Ueberschrift. Wer gruppierte Listen sortierbar macht, MUSS `gruppe` angeben.

Sortiert wird nur INNERHALB einer Gruppe. Ein Wechsel der Kategorie per Ziehen
waere folgenlos: Die Gruppierung kommt serverseitig aus `kategorie_id`, der
Eintrag spraenge beim naechsten Laden zurueck.

`packlisten_eintraege.position`: Reihenfolge je Ziel. **Neue Eintraege gehen
ans Ende** (`MAX(position)+1`) - auf 0 wuerde jeder neue Eintrag die von Hand
sortierte Liste durcheinanderschieben.

## Umschalter ohne Seitensprung (Wunsch #171)

Formular mit `data-fetch="funktionsname"` -> der Absende-Verteiler in
`base.html` schickt es per fetch mit `Accept: application/json` und uebergibt
die Antwort an die genannte Funktion. Serverseitig entscheidet der gemeinsame
Helfer `antwort_oder_weiter(ziel_url, **daten)` in `00_kern.py`: JSON bei
diesem Accept-Kopf, sonst Weiterleitung wie bisher.

**Nicht jeder Umschalter darf fetch benutzen.** Kriterium:

> Aendert der Umschalter die Reihenfolge oder Gruppierung der Liste?

- **Nein** -> fetch (gekocht im Essensplan, Storno im Kassenbuch)
- **Ja**  -> Weiterleitung mit `#anker` auf die eigene Karte (erledigt und
  Prioritaet in der Werkstatt, Erinnerungen bei den Geburtstagen)

Eine Karte, die an Ort und Stelle umspringt, waehrend die Sortierung veraltet,
ist schlimmer als ein Sprung - man handelt dann auf einer Liste, die nicht
mehr stimmt. Wer einen Anker setzt, muss das Sprungziel als `id` an der Karte
haben; `tests/test_umschalter_ohne_sprung.py` prueft beides.

Der Formularweg bleibt in beiden Faellen funktionsfaehig (Zurueck-Taste, kein
Javascript) - das ist kein toter Code.

## Icon-Knoepfe benennen (Wunsch #175)

Jeder `<button>`, dessen Beschriftung nur aus Zeichen besteht (Emoji, Pfeil,
✓), braucht ein `aria-label`. Wo zusaetzlich ein `title` steht, sind **beide
Texte identisch** - zwei verschiedene Texte am selben Knopf laden dazu ein,
einen zu pflegen und den anderen zu vergessen, und vergessen wird immer der,
den niemand sieht.

`tests/test_aria_labels.py` waechtert Vorhandensein, Gleichheit und dass der
Name kein Platzhalter ist ("Knopf", "...").

## Lange Vorgaenge anzeigen (Wunsch #176)

Formulare, deren Absenden spuerbar dauert (KI-Anfrage), tragen
`data-arbeitet="Wird gelesen …"`. Der Absende-Verteiler in `base.html`
deaktiviert dann den Submit-Knopf und beschriftet ihn um.

Zwei Fallen, beide gewaechtert in `tests/test_arbeitet_anzeige.py`:

1. **Reihenfolge.** Das Signal kommt NACH `data-bestaetigen` und
   `data-absenden`. Ein Knopf, der nach einem abgebrochenen Absenden
   deaktiviert stehen bliebe, ist schlimmer als kein Signal - die Seite sieht
   aus, als arbeite sie.
2. **Zurueck-Navigation.** Ein `pageshow`-Handler (`e.persisted`) macht den
   Knopf wieder frei; sonst bleibt er nach Zurueck fuer immer tot.

## Darstellung hell/dunkel (Wunsch #172)

`users.dark_mode`: **0 = immer hell, 1 = immer dunkel, 2 = wie das Geraet**
(Spalten-Default seit #172). Der Menue-Knopf schaltet im Kreis 2 -> 0 -> 1 -> 2.

- `body.dark` traegt die dunklen Werte; `body.auto` bekommt sie NUR innerhalb
  von `@media (prefers-color-scheme: dark)`. Steht `body.auto` ausserhalb,
  ist die Automatik in Wahrheit ein Dauer-Dunkelmodus.
- Die zwoelf Farbwerte stehen in `base.html` in EINER Jinja-Variablen
  (`{% set dunkle_werte %}`) und werden zweimal ausgegeben. Zwei getippte
  Bloecke wuerden auseinanderlaufen, ohne dass es auffaellt - kaum jemand
  sieht beide Modi nebeneinander. `tests/test_darkmode.py` waechtert das.
- **Bestehende Konten wurden bewusst NICHT migriert.** Ob eine 0 eine bewusste
  Wahl war oder nie beruehrt wurde, laesst sich nicht unterscheiden; fremde
  Einstellungen ohne Rueckfrage umzustellen ist nicht unsere Entscheidung.

## Globale UI-Regeln in base.html (verpflichtend)

Fuenf Regeln gelten portalweit und duerfen von keiner Vorlage ueberschrieben
werden. `tests/test_tippflaeche.py` waechtert die ersten vier,
`tests/test_kopfzeile_bleibt.py` die fuenfte:

| Regel | Wunsch | Warum |
|---|---|---|
| `button::before` >= 44x44px | #169 | Tippziele waren 17-33px hoch |
| `input,select,textarea { font-size: max(16px,1em) }` | #170 | iOS zoomt unter 16px beim Fokus hinein |
| `.main { max-width:720px; margin:0 auto }` | #173 | Zeilen liefen ueber die ganze Monitorbreite |
| `:focus-visible` Ring + `:focus:not(:focus-visible){outline:none}` | #174 | Tastaturnutzer sahen nicht, wo sie stehen |
| `.app-header { position:sticky; top:0; z-index:100 }` + `html { scroll-padding-top }` | #186 | Navigation war auf langen Seiten nicht erreichbar |
| `body { overscroll-behavior-y: contain }` + Ziehgeste in base.html | #196 | in der installierten PWA gab es kein Neuladen |
| `[hidden] { display: none !important }` | #199 | eine Klasse mit eigenem `display` schlug das Attribut |

**Aufrufkonvention des Verteilers (Wunsch #200):**
`fn.apply(el, args.concat([el, ereignis]))` - die Werte aus `data-args`
kommen ZUERST, dann das Element, dann das Ereignis. Eine Funktion, deren
erster Parameter ein Element ist, darf also KEIN `data-args` bekommen.
`tests/test_verteiler_argumente.py` waechtert das ueber alle Vorlagen; der
Fehler war in vokabeln.html monatelang unsichtbar, weil das Formular die
Sprache selbst vorwaehlte und der Chip nie gebraucht wurde.

**Zur fuenften gehoert das `scroll-padding-top` untrennbar dazu.** Ohne es
landet jedes Sprungziel (`#wunsch-<id>` aus #171, `#gb-<id>`, die
Hilfe-Kapitel) UNTER der stehenden Leiste: Die Navigation waere erreichbar
und das Ziel dafuer unsichtbar. Ein zu kleiner Wert ist schlimmer als gar
keiner - es sieht dann fast richtig aus. `z-index: 100` liegt bewusst unter
dem Hamburger-Overlay (200) und dem ✨-Dialog (300).

**Achtung Spezifitaet:** Die Schriftregel ist ein ELEMENT-Selektor (0,0,1).
Jede Klassenregel (`.add-input`, 0,1,0) schlaegt sie, unabhaengig von der
Reihenfolge - deshalb ist sie nur eine Untergrenze fuer klassenlose Felder,
und die Vorlagenwerte wurden zusaetzlich auf 16px angehoben. Der Waechter
prueft die Vorlagen deshalb einzeln, `base.html` eingeschlossen (dessen
eigene `.wunsch-prio-select` stand auf 15px).

Die zweite Haelfte der Fokus-Regel ist kein Beiwerk: Sie stellt den alten
Zustand fuer MAUSklicks wieder her. Ohne sie saehen Maus-Nutzer ueberall neue
Rahmen.

## Tippfläche (verpflichtend, seit Wunsch #169)

Jeder `button` bekommt in `base.html` per `button::before` eine unsichtbare,
zentrierte Trefferfläche von mindestens 44×44 px (`max(100%, 44px)` je Achse,
`button { position:relative }` als Bezugsrahmen). Optik unverändert.

**Kein Template darf ein eigenes `button::before`/`::after` definieren** -
das ersätze die Fläche, und der Knopf wäre still wieder klein (ein Tipp
daneben fühlt sich wie eigenes Zittern an, nie wie ein Fehler).
`tests/test_tippflaeche.py` wächtert beides. Wer ein Knopf-Pseudo-Element
braucht, nimmt ein anderes oder übernimmt die Fläche mit.

## Lösch-Symbol (verpflichtend, seit Wunsch #160)

Jedes Bedienelement, das einen Datensatz **entfernt**, trägt 🗑️ – nie ✕,
nie nur Text:

```html
<form method="post" action="/a/<app>{{ tp }}loeschen/{{ x.id }}"
      data-bestaetigen="„...“ löschen?">
  <button class="..." type="submit" title="Löschen">🗑️</button>
</form>
```

Vor #160 war es uneinheitlich: 🗑️ in acht Vorlagen, ✕ in vier
(Aufgaben, Werkstatt 2×, Tierbaukasten), reiner Text in einer (Geburtstage).
Entstanden ist das nicht durch eine Entscheidung, sondern durch Abschreiben
von der jeweils benachbarten Datei – deshalb wächtert
`tests/test_loeschen_symbol.py` es jetzt über ALLE Vorlagen. Er sucht über die
ROUTE (`action="...loeschen..."`), nicht über die Beschriftung; sonst fände er
nur, was ohnehin schon richtig heißt.

**Ausnahme Kassenbuch.** Dort gibt es kein Löschen, sondern ein **Storno**:
die Zeile bleibt fuer immer stehen und zählt nur nicht mehr zum Kontostand
(Wünsche #144/#153/#156). Ein Mülleimer würde etwas anderes versprechen, als
die App tut. Ein eigener Test hält fest, dass diese Ausnahme absichtlich ist.

## Aktionsknöpfe (verpflichtend, seit Wunsch #155)

Aktionen einer Seite stehen **oben im `<main>`** als `.top-aktionen`-Zeile,
Vorbild `todo.html`:

```html
<div class="top-aktionen">
  <a class="top-aktion" href="...">+ Neues Mitglied</a>
</div>
```

```css
.top-aktionen { display:flex; gap:8px; margin-bottom:14px; }
.top-aktion {
  flex:1; display:block; text-align:center; text-decoration:none;
  background:none; border:1.5px solid var(--farbe); color:var(--farbe);
  border-radius:12px; padding:12px 10px; font-size:14px; font-weight:600;
}
```

**Nie auf das farbige Kopfband.** Der Block `header_extra` in `base.html`, der
das ermöglichte, ist ersatzlos entfallen – `admin.html` war zuletzt die einzige
Vorlage, die ihn noch benutzte. Ein Template, das ihn wieder definiert, würde
NICHTS rendern (der Knopf verschwände lautlos); `tests/test_kopfleiste.py`
fängt genau das ab und prüft zusätzlich, dass zwischen `</header>` und
`<main>` keine Schaltfläche steht.

## Hamburger-Menü (verpflichtende Struktur, seit Wunsch #32)

Gilt in `base.html` für das ganze Portal, immer in dieser Reihenfolge:

1. **Startseite** – immer ganz oben.
2. `<div class="menu-divider">` + Einträge der **gerade geöffneten App**
   (z. B. Geholfen: „Zuletzt geholfen"/„Statistik"; Einkauf: „Märkte
   verwalten"). Nur rendern, wenn mindestens ein Eintrag zutrifft – sonst
   keine leeren Trennstriche.
3. `<div class="menu-divider">` + **allgemeine Einträge**, die überall
   gelten (Dark Mode, Hilfe, Verbesserungsvorschlag).

Neue App-spezifische Menüpunkte gehören in Abschnitt 2, per
`{% if app_slug == '<slug>' %}`-Guard – niemals einfach oben oder unten
anhängen.

## Sicherheitskonventionen (verpflichtend)

- **Sitzungen sind Zugangsgeheimnisse**: jede Zeile in `sitzungen` ist ein
  gueltiger, nie ablaufender Zugang (`ablauf` NULL, wegen des Kiosk so
  gewollt). Wer welche hat, steht seit Wunsch #154 unter
  `/a/admin/<token>/geraete`; dort laesst sich auch eine EINZELNE abmelden,
  ohne die Token des Nutzers anzufassen. `gesehen` wird von
  `sitzung_nutzer_id()` fortgeschrieben, gedrosselt auf
  `GESEHEN_TAKT_MINUTEN` (60) - die Drosselung steht in der WHERE-Klausel,
  nicht in Python.
- **Live-Prüfung**: immer `scripts/live_pruefung.py`, **nie ad hoc mit `curl`
  über Pfad-Tokens**. Jede Anfrage ohne Cookie stellt eine Sitzung aus, und
  die läuft nie ab (`ablauf` NULL, wegen des Kiosk so gewollt). Am 08.08.2026
  waren dadurch 808 von 817 Sitzungen Prüfrückstände. Das Skript legt genau
  eine an (`geraet='PRUEFUNG'`) und entfernt sie auch bei Abbruch.
- **Ganzzahlen**: immer `to_int()` aus `teile.kern` – nie `int()` direkt auf Nutzereingaben
- **Datum/Uhrzeit**: immer `heute_lokal()` aus `teile.kern` – **nie `date.today()`**.
  Der Container läuft auf UTC, die Familie auf Europe/Berlin: zwischen
  Mitternacht und 2 Uhr liefert `date.today()` den VORTAG. Im Kassenbuch
  landete ein nächtlicher Eintrag dadurch stumm auf gestern, weil die
  "kein Nachtragen in die Zukunft"-Regel den korrekt gewählten Tag
  zurückschob (gefunden bei Wunsch #153). Gespeicherte Zeitstempel
  (`datetime('now')` in SQLite) sind ebenfalls UTC und gehören für die
  Anzeige durch `utc_zu_lokal()`, zum Vergleichen durch
  `utc_zu_lokal_datum()`. Ein eigener `_TZ`-Konstante je Modul ist Altbestand
  (`13_kinderplan.py`, `14_sportschau.py`, `18_tvb.py`) – neuer Code nimmt
  die Helfer aus dem Kern.
- **Farben**: immer `_clean_farbe()` aus `03_admin.py` (Regex `^#[0-9a-fA-F]{6}$`)
- **DOM**: `textContent` / `createElement` statt `innerHTML` für Nutzerdaten in JS
- **Logs**: Gunicorn RedactingLogger scrubbt Tokens aus Access-Logs
- **Headers**: Caddy setzt Security-Headers auf alle Antworten
- **Zugriffsreihenfolge in `grant()`** (Wunsch #140, Stufe 3), verbindlich:
  1. Pfad-Token zuerst - solange er gilt, kann kein Cookie-Fehler jemanden
     aussperren, und auf geteilten Geraeten gewinnt der gerade geoeffnete Link.
  2. Ein angegebener, aber unguelltiger Token faellt **nicht** aufs Cookie
     zurueck - sonst liefe ein widerrufener Zugang stillschweigend weiter.
  3. Nur ohne Token in der Adresse zaehlt das Cookie, und auch dann muss ein
     Grant fuer die App existieren. Das Cookie ersetzt den Nachweis, es weitet
     keine Rechte aus.
  `sitzung_nutzer_id()` liegt im Kern, nicht im Sitzungsmodul - sonst
  Ringschluss, weil `grant()` es braucht.
- **Niemals automatisch auf eine Anmeldeseite umleiten.** Fehlende
  Autorisierung fuehrt zu `denied.html` bzw. `abort(403)`. Der
  Esszimmer-Bildschirm laeuft im `--kiosk`-Modus ohne Adresszeile; ein
  Anmeldebildschirm waere dort nicht bedienbar.
- **Zugangstokens** (Wunsch #129): In der DB steht **nie** der Klartext.
  Gesucht wird über `token_lookup(token)` (HMAC), zurückgewonnen über
  `token_entschluesseln(row["token_enc"])` – beides aus `teile.kern`. Neue
  Grants immer über `grant_werte(new_token())`, das liefert das Paar. Wer
  eine neue Stelle mit Grants baut: `WHERE g.token = ?` gibt es nicht mehr.
- **`TOKEN_KEY` aus der `.env` ist betriebskritisch**: ohne ihn ist kein
  Zugang möglich, und das `/data`-Backup enthält ihn absichtlich nicht.
  Zweitkopie im Passwortmanager. Bei einem Restore auf neuer Hardware
  zuerst die `.env` zurückspielen, dann `/data`.
- **Neue Wege nach außen** (Wunsch #127): Jeder Abruf einer vom Nutzer
  gelieferten URL muss durch `_ist_oeffentliche_url()` UND darf
  Weiterleitungen nur mit erneuter Prüfung je Station folgen; die geprüfte
  IP wird für die Verbindung festgenagelt (Muster in `11_rezepte.py`).
  Ein blankes `urllib.request.urlopen(nutzer_url)` ist ein SSRF-Loch.
- **Ein Zugangstoken ist nur EINMAL sichtbar** (Wunsch #140, Stufe 6). In der
  DB steht nur `token_lookup` (HMAC). Wer einen Grant anlegt, muss den
  Klartext im selben Request anzeigen oder verwerfen - `grant_anlegen()` in
  `00_kern.py` gibt ihn genau einmal zurueck (und `None`, wenn der Grant schon
  bestand: dann gilt der ALTE Token, den niemand mehr kennt). Eine Route, die
  einen Link "nachschlagen" will, kann es nicht geben - genau deshalb ist
  `/qr.svg` entfallen und der QR-Code eine `data:`-URI.
- **Keine Inline-Handler** (Wunsch #142). `onclick=`/`onsubmit=`/`onchange=`/
  `oninput=` im Markup sind verboten – sie erzwängen `script-src
  'unsafe-inline'`, und damit liefe eingeschleuster Code so selbstverständlich
  wie eigener. Stattdessen der Verteiler aus `base.html`:
  `data-klick="fnName" data-args='[1, "text"]'` (analog `data-aendern`,
  `data-eingabe`; für Formulare `data-bestaetigen` und `data-absenden`).
  Aufrufkonvention: `fn.apply(element, [...args, element, ereignis])` – das
  Element kommt als `this` UND als vorletztes Argument, das Ereignis als
  letztes; ein Rückgabewert `false` unterdrückt die Standardaktion.
  `tests/test_csp.py::test_keine_inline_handler_mehr` wacht darüber.
- **Eine KI-Auswahl aus vorgegebenen Werten wird gegen die Vorgabe geprueft**
  (Wunsch #143, `_kategorie_per_ki()` in `10_einkauf.py`): Die Kategorien
  kommen aus der Datenbank, und die Antwort muss einer davon entsprechen. Ein
  frei erfundener Name wuerde sonst still zu einer falschen Einsortierung
  fuehren. Bei Unsicherheit lieber KEIN Ergebnis - der Aufrufer faellt dann
  auf 'Sonstiges' zurueck.
- **Nutzereingaben, die in eine URL eingesetzt werden, mit `\A…\Z` pruefen,
  nicht mit `^…$`** (Wunsch #143): In Python passt `$` auch VOR einem
  abschliessenden Zeilenumbruch - `"4008400401621\n"` rutschte durch eine
  `^[0-9]+$`-Pruefung und landete mitsamt Umbruch in der Adresse.
- **KI-Antworten (Rezept-Import, Wunsch #137) laufen durch ein striktes
  Schema** (`_ki_rezept_validieren()` in `11_rezepte.py`), nicht durch
  blindes `json.loads()`. Nur bekannte Felder, Listen-Einträge müssen
  Zeichenkette/Zahl sein, feste Längen-/Mengenobergrenzen. Beide
  KI-Extraktionspfade (URL- und Foto-Import) nutzen dieselbe Funktion - eine
  neue KI-gestützte Extraktion sollte das auch tun, statt eigenes Parsing zu
  schreiben.
- **Wer eine Ressource ueber `blob:` oder `data:` laedt, muss die CSP
  mitziehen.** `default-src 'self'` deckt beides NICHT ab. Die
  Vokabel-Aussprache lief zwei Wochen lang ins Leere, weil `media-src` fehlte:
  Datei erzeugt, HTTP 200 ausgeliefert, vom <audio>-Element mit Fehlercode 4
  abgelehnt - ohne Server-Fehler, ohne sichtbare Meldung, auf allen Geraeten.
  Der Fehler tritt NUR bei scharfer CSP auf; beim Entwickeln steht
  `CSP_MODUS=aus`, dort faellt er nicht auf.
- **Sichtbarkeit und Eigentum sind in der Vokabeln-App zwei verschiedene
  Fragen** (Wunsch #150). `_VOKABEL_SICHTBAR` / `_kapitel_zugaenglich()` /
  `_sprache_zugaenglich()` beantworten "darf sehen, ueben, anhoeren" (eigene
  ODER geteilt). `_kapitel_gehoert_nutzer()` beantwortet "darf aendern"
  (bearbeiten, loeschen, umbenennen, weiterteilen) - dort NIE die
  Sichtbarkeitsregel verwenden, sonst koennte ein Empfaenger fremde Vokabeln
  aendern oder die Freigabe weiterreichen. Die Regel steht bewusst an einer
  Stelle; vorher war sie an sieben Stellen als `user_id=?` ausgeschrieben.
- **TTS bekommt IMMER die Sprache mitgeteilt** (Wunsch #149,
  `tts_eingabe()` in `00_kern.py`): Ohne Angabe raet das Modell und liegt bei
  kleinen Sprachen daneben - gemeldet als "Daenisch funktioniert nicht",
  tatsaechlich war es englisch ausgesprochenes Daenisch. Die Anweisung steht
  VOR einem Doppelpunkt (`Sprich auf Daenisch: ...`) und wird von Gemini-TTS
  als Stilvorgabe verstanden, nicht mitgesprochen (nachgemessen: 13 Woerter
  Anweisung = +0,16 s). Der Sprachname kommt aus `vokabel_sprachen`, damit
  spaeter angelegte Sprachen ohne Code-Aenderung funktionieren. Gezaehlt wird
  weiter der reine Text, nicht die Anweisung.
- **Aendert sich, WIE eine gecachte Datei erzeugt wird, muss der Cache-
  Schluessel mitwandern** (Wunsch #149): `_audio_pfad()` traegt seither ein
  `v2:`. Sonst blieben die alten, falsch klingenden Dateien fuer immer in
  Benutzung - der Fehler waere behoben und trotzdem hoerbar.
- **KI-Kontingente sind pro EINHEIT eine eigene Tabelle** (Wunsch #136):
  `ki_nutzung.tokens` (LLM-Text, `ki_anfrage()`) und `ki_tts_nutzung.zeichen`
  (Sprachausgabe, `ki_text_zu_sprache()`) dürfen nie in derselben Spalte
  landen - `ki_anfrage()`s Limit-Prüfung summiert `SUM(tokens)` OHNE
  Feature-Filter, eine vermischte Einheit würde das Kontingent unbemerkt
  verfälschen.
- **Jeder Inline-`<script>`-Block braucht `<script{{ '{{' }} csp_nonce {{ '}}' }}>`.**
  Ohne Nonce läuft er im Modus `scharf` nicht mehr – und das fällt beim
  Entwickeln nicht auf, weil dort `CSP_MODUS=aus` steht.
- **Löschen-Sicherheitsabfrage** (app-übergreifend verpflichtend, seit Wunsch
  „Einkauf löschen"): jedes echte (nicht reversible) Löschen fragt nach.
  Reversible Toggles (aktiv/inaktiv, Grant-Entzug) brauchen keine Abfrage.

  **Seit Wunsch #142 (Stufe 5) so, NICHT mehr per `onsubmit`:**
  ```html
  <form method="post" action="…"
        data-bestaetigen="{{ '{{' }} '„' ~ text|truncate(40) ~ '“ löschen?' {{ '}}' }}">
  ```
  Den Rest erledigt der Verteiler in `base.html`. Damit entfällt die alte
  `|tojson|forceescape`-Regel an dieser Stelle vollständig: Der Wert ist jetzt
  schlichter Attributtext, um dessen Maskierung Jinjas Autoescaping von selbst
  kümmert. Ein `onsubmit` würde ausserdem im Modus `CSP_MODUS=scharf` gar
  nicht mehr ausgeführt – `tests/test_csp.py` lässt deshalb keines mehr zu.
- **`|tojson` in `<script>`-Blöcken NIE mit `|forceescape` kombinieren.**
  (Seit #142 gibt es keine `onsubmit`-Attribute mehr, in denen `forceescape`
  nötig wäre – die Regel steht hier weiter, weil `tojson` in Skriptblöcken
  häufig vorkommt und die Verwechslung nahe liegt.) Innerhalb von `<script>...</script>` liefert
  Flasks `tojson` bereits scriptsicheres JSON (z. B. `let queue =
  {{ daten|tojson }};` in `vokabel_training.html`) – `forceescape`
  HTML-entity-escaped dann zusätzlich Anführungszeichen zu `&#34;` etc.,
  was der JS-Parser als Syntaxfehler liest, da `<script>`-Inhalt nicht
  HTML-dekodiert wird. Referenz für die korrekte Variante ohne
  `forceescape`: `admin_user_form.html`.

## Nutzer (Stand 2026-07-27)

| ID | Name | Rolle | Admin | Startseiten-URL |
|----|------|-------|-------|-----------------|
| 1 | Andi | eltern | ✅ | über Admin-App abrufbar (QR-Code) |
| 2 | Simone | eltern | – | über Admin-App abrufbar (QR-Code) |
| 3 | Friederike | kind | – | über Admin-App abrufbar (QR-Code) |
| 4 | Johannes | kind | – | über Admin-App abrufbar (QR-Code) |

Alle 4 Nutzer haben Grants für: home, geholfen, todo, werkstatt, einkauf, hilfe, rezepte, essensplan, kinderplan.
Andi + Simone haben Rolle 'eltern' → sehen "Als wer?"-Selektor in Geholfen.

## util-Aufgaben

| Aufgabe | Zeitplan | Details |
|---------|----------|---------|
| SQLite-Snapshot | stündlich | 24 Slots in `/data/snapshots/`. `_prune()` raeumt seit Wunsch #215 auch **verwaiste `-wal`/`-shm`** weg (Begleiter ohne zugehoerige `.db`) – das alte Muster endete auf `.db` und sah sie nie, wodurch am 11.08.2026 56 Altlasten vom 07./08.08. herumlagen und jede Nacht mitgesichert wurden. Reihenfolge zaehlt: erst die alten `.db` loeschen, dann die Verwaisten – sonst blieben die Begleiter der gerade entfernten Snapshots eine Runde zu lang liegen. |
| Zertifikats-Watcher | täglich 04:00 + einmalig beim Start | prüft mtime, löst Caddy-Reload aus |
| NAS-Backup | täglich 03:00 | tar+ssh-Pipe → Ugreen NAS 10.60.0.4:2222, User `familienportal`, Pfad `/volume2/portal.16schwaben.de_Backup/`, 7 Generationen |

SSH-Key für Backup: `/srv/familienportal/ssh/id_ed25519` (bind-mount als `/ssh/id_ed25519` im Container, read-only). Public Key auf NAS in `/home/familienportal/.ssh/authorized_keys`.

**Hostschlüssel des NAS** (Wunsch #211, Audit F-03): `/srv/familienportal/ssh/known_hosts`, aufgenommen am 12.08.2026, ed25519 **und** rsa. `backup.py` fährt seitdem mit `StrictHostKeyChecking=yes` und `UserKnownHostsFile=/ssh/known_hosts`; fehlt die Datei, bricht der Lauf mit einer Fehlermeldung ab statt auf „nimm jeden Host" zurückzufallen. Fingerabdrücke: ED25519 `SHA256:EN7z/iS9NwYwrKDpo7Rka7lCl8gLWj3Sf6zZFGuBCCw`, RSA `SHA256:3OROAGW+Rk5oeMnEB1hTR+UDVOkdVPr42z2ykzeT9Ps`.

> **Bei einem NAS-Umzug oder neu aufgesetztem SSH-Dienst schlägt das Backup fehl** – mit Absicht, Meldung `Host key verification failed`. Dann den neuen Schlüssel am NAS selbst ablesen, vergleichen und erst danach neu aufnehmen (`ssh-keyscan -p 2222 -t ed25519,rsa <ip> > /srv/familienportal/ssh/known_hosts`). Blindes Überschreiben stellt genau die Lücke wieder her, die #211 geschlossen hat.

Der Datenstrom selbst geht **weiterhin unverschlüsselt** aufs NAS (zweiter Teil von #211 und ganz #130) – offen, weil die Wahl zwischen symmetrisch (Schlüssel aus der `.env`) und asymmetrisch (age, privater Schlüssel ausserhalb von home02 und NAS) über die Wiederherstellbarkeit entscheidet und deshalb Andi gehört. Entlastend: in der DB stehen seit Stufe 6 nur HMACs der Zugangstokens, ein erbeutetes Backup gibt also **keinen** Portalzugang.

## Bekannte Issues

- **Der Container läuft in UTC, nicht in deutscher Zeit** (`docker exec
  portal python3 -c "import time; print(time.tzname)"` → `('UTC','UTC')`).
  `datetime.now()` ohne `tzinfo` liefert also UTC, nicht Europe/Berlin -
  jeder Code, der eine BESTIMMTE UHRZEIT DES TAGES prüft ("ab 20 Uhr",
  "ist es schon Mitternacht"), braucht `datetime.now(ZoneInfo("Europe/
  Berlin"))`, sonst verschiebt sich die Prüfung um 1-2 Stunden (je nach
  Sommer-/Winterzeit). Betraf `13_kinderplan.py`s 20-Uhr-Sperre (v87→v88-
  Fix, Wunsch #92): live nachgewiesen, dass die Sperre um 01:13 Uhr
  deutscher Zeit fälschlich ausgelöst hätte (UTC-Stunde war noch 23 vom
  Vortag). `14_sportschau.py` hatte das Problem schon vorher richtig gelöst
  (`_TZ = ZoneInfo("Europe/Berlin")`) - **dieses Muster für jeden neuen
  Zeit-Vergleich wiederverwenden, nie nacktes `datetime.now()` für
  Uhrzeit-Schwellwerte.** Reine Zeitspannen-/Differenzberechnungen sind
  davon NICHT betroffen - z. B. `serie_verfuegbar_am()` in `04_todo.py`
  (seit Wunsch #113, vorher `_serie_ist_im_pool()`) vergleicht ausschließlich
  reine Kalendertage (`date.fromisoformat()` auf `plan_tag`-ISO-Daten ohne
  Uhrzeitanteil), keine Zeitzone im Spiel - nur bei echten
  Wanduhr-Schwellwerten wie "20 Uhr abends" ist die Zeitzone relevant.

- **Service Worker unter `/static/sw.js` registriert hat per Default nur
  den Scope `/static/`, nicht die ganze Seite.** Betraf die Offline-
  Grundinfrastruktur (v79→v80-Fix, 2026-07-31): `navigator.serviceWorker
  .register('/static/sw.js')` (ohne `scope`-Option) gibt dem Worker
  maximal den Scope seines eigenen Verzeichnisses - er hätte NIE `fetch`-
  Events für `/p/...` oder `/a/.../...` bekommen, egal wie der Handler
  selbst aussieht. Kein Fehler, keine Warnung - der Worker registriert und
  aktiviert sich ganz normal, kontrolliert einfach nur die falschen (bzw.
  gar keine echten) Seiten. Fix: Registrierung mit `{ scope: '/' }` PLUS
  einen `Service-Worker-Allowed: /`-Response-Header beim Ausliefern von
  `sw.js` selbst (sonst lehnt der Browser den erweiterten Scope mit einem
  SecurityError ab) - `@app.after_request`-Hook in `00_kern.py`, nur für
  genau diese eine Route. **Gilt allgemein: bei jedem Service Worker, der
  mehr als sein eigenes Verzeichnis kontrollieren soll, IMMER explizit
  `scope` bei der Registrierung UND den `Service-Worker-Allowed`-Header
  serverseitig prüfen** - per `navigator.serviceWorker.getRegistrations()`
  und `.scope` nachsehen, ein Test allein über "registriert sich ohne
  Fehler" reicht nicht.

- **Ein reiner Toggle-Endpunkt ist gefährlich für Offline-Warteschlangen
  mit Wiederholung.** Betraf Einkauf offline-fähig (v81-Fix, 2026-07-31):
  `/erledigt/<eid>` drehte bisher den aktuellen Zustand einfach um. Landet
  ein technisch schon erfolgreicher, aber dessen Antwort verlorener Request
  in einer Offline-Warteschlange und wird später nochmal geschickt, würde
  ein reiner Toggle den Zustand ein zweites Mal umdrehen - falsches
  Endergebnis, ohne dass irgendetwas einen Fehler zeigt. Fix: die Route
  nimmt jetzt ein explizites `ziel` (0/1) entgegen und SETZT darauf statt
  zu toggeln - macht sie idempotent, beliebig oft sicher wiederholbar.
  **Gilt allgemein: jeder Endpunkt, der Teil einer Offline-Warteschlange
  oder sonst wiederholbaren Anfrage werden könnte, muss idempotent sein**
  (Ziel-Zustand explizit statt reinem Toggle/Inkrement) - sonst führt eine
  harmlos gemeinte Wiederholung zu einem stillen Datenfehler.

- **hae-Server parst ein bare-date `endDate` als Mitternacht UTC jenes
  Tages, nicht als Ende des Tages.** Betraf Wunsch #88 (v78-Fix,
  Sportschau): `_hae_workouts()` (`14_sportschau.py`) schickte
  `endDate=heute.isoformat()` (z. B. "2026-07-31", ohne Uhrzeit) - der
  hae-Server parst das zu `2026-07-31T00:00:00.000Z` (per eigener
  Server-Log-Zeile bestätigt) und schließt damit JEDES Training aus, das
  nach Mitternacht am aktuellen Tag beginnt. Kein Rand-/Sonderfall,
  sondern strukturell: "heute" wäre ohne Fix jeden Tag aufs Neue nie
  sichtbar gewesen. Fix: `end_date` bekommt einen Tag aufgeschlagen, bevor
  die Anfrage rausgeht - ein dadurch zusätzlich mitgeholter "morgen"-Tag
  ist unschädlich, da `sportschau.html` nur über die feste `tage`-Liste
  iteriert, die nie über heute hinausreicht. **Gilt allgemein: bei jeder
  Integration mit dem hae-Server (oder ähnlichen Fremd-APIs) ein bare-date
  als oberes Zeitfenster-Ende vermeiden** - entweder mit Uhrzeit
  (`T23:59:59`) oder auf den nächsten Tag aufrunden. Die Schritte-Abfrage
  (`_hae_steps`) hat dieses Problem nicht, da sie von vornherein exakte
  Unix-Millisekunden statt eines Datums verwendet.

- **SVG `<use href="#id">`/`clipPath` gegen eine nicht existierende ID
  resolved zu einem leeren Clip-Bereich, ohne Fehler.** Betraf Wunsch #83
  (v70-Fix, Tierbaukasten-Galerie): `figur_vorschau()` (`tierbaukasten.html`)
  baut pro Galerie-Eintrag einen eigenen `clipPath` mit suffixierter ID
  (`clip-katze-5` → `<use href="#body-vorne-katze-5"/>`), damit mehrere
  gespeicherte Tiere derselben Art nicht dieselbe SVG-ID teilen. Das
  wiederverwendete Macro `koerper_vorne(typ)` kannte diesen `suffix`-
  Parameter aber nicht und vergab immer nur die feste, unsuffixierte ID –
  der `<use>`-Verweis lief ins Leere, die `clipPath` blieb leer, die
  Mustergruppe wurde komplett weggeclippt (unsichtbar), während der direkt
  gerenderte Körper normal sichtbar blieb. Kein Fehler, keine Warnung, in
  keinem Browser. Fix: `koerper_vorne(typ, suffix='')` wie das
  Schwester-Macro `koerper_seite` schon lange hat, IDs konsequent
  `{{ typ }}{{ suffix }}`. **Gilt allgemein: bei jeder SVG-Vorlage mit
  wiederverwendbaren Elementen und `<use>`/`clip-path`-Referenzen sicherstellen,
  dass ALLE beteiligten Macros denselben Suffix-Mechanismus kennen und
  konsequent anwenden** – sonst zeigt curl (sieht nur Attribute) UND ein
  Screenshot (Körper bleibt ja sichtbar) den Fehler nicht zuverlässig; per
  `javascript_tool` `getBBox()` auf das `<use>`-Ziel prüfen (0×0 = tote
  Referenz).

- **OpenRouter-TTS: `response_format` ist modellabhängig, nicht generisch
  mp3/pcm wählbar.** Betraf Wunsch #81 (v67→v68-Fix): Die OpenRouter-Doku für
  `/api/v1/audio/speech` nennt "mp3 oder pcm" als Optionen, aber
  `google/gemini-3.1-flash-tts-preview` akzeptiert ausschließlich `pcm` und
  lehnt `mp3` mit `400 "Gemini TTS only supports response_format=\"pcm\""` ab
  – live erst beim tatsächlichen Testen aufgefallen, nicht aus der Doku
  ablesbar. `ki_text_zu_sprache()` (`00_kern.py`) versucht deshalb erst mp3,
  weicht bei genau dieser Fehlermeldung auf PCM aus und verpackt das Ergebnis
  selbst in einen WAV-Container (`wave`-Modul aus der Standardbibliothek,
  24 kHz/16-bit/Mono laut Google-Doku für Gemini TTS) – **künftige TTS-Modelle
  in `ki_stimmen` können andere Formatgrenzen und andere PCM-Parameter haben**,
  bei einem Modellwechsel per `manage.py ki_stimme` diesen Fallback-Pfad neu
  gegenprüfen.

- **iOS/Safari verlässt sich beim Erkennen des Audioformats zusätzlich auf
  die Dateiendung im `Content-Disposition`-Header, nicht nur auf
  `Content-Type`.** Betraf Wunsch #81 (v68→v69-Fix): `send_file()` lieferte
  den internen Cache-Dateinamen mit generischer `.audio`-Endung aus (das
  tatsächliche Format steht erst nach dem ersten KI-Aufruf fest, siehe
  `_audio_pfad` in `16_vokabeln.py`) – trotz korrektem `Content-Type:
  audio/wav` spielte iOS die Datei stumm nicht ab, andere Browser hatten
  kein Problem. Fix: `send_file(..., download_name="aussprache.wav")` –
  die Cache-Datei selbst bleibt `.audio`, nur der ausgelieferte Name bekommt
  die zum tatsächlichen Inhalt passende Endung. **Gilt allgemein für jede
  künftige Route, die Mediendateien mit uneinheitlicher/generischer
  Cache-Dateiendung ausliefert** – `download_name` immer explizit setzen,
  nicht auf `Content-Type` allein verlassen.

- **CSS-Falle: Prozent-Höhe gegen eine `auto`-Höhe resolved zu nichts, ohne
  Fehler.** Betraf das Schritte-Balkendiagramm (Wunsch #77, v65→v66-Fix):
  `.steps-bar-stack` hatte `height:X%`, sein Elternelement `.steps-bar-col`
  aber keine eigene definite Höhe (nur `display:flex`, kein `height`) – die
  Kette war unterbrochen, alle Balken kollabierten lautlos auf 0px. Kein
  Konsolenfehler, kein 500er, curl zeigt die (korrekten!) HTML-Attribute
  weiterhin an – nur das gerenderte Layout ist kaputt. **Jede Prozent-Höhe
  braucht eine lückenlose Kette definiter Höhen bis zur Wurzel** (hier:
  `.steps-chart` mit `height:150px` fix → `.steps-bars` mit `height:100%` →
  `.steps-bar-col` mit `height:100%` → erst dann darf `.steps-bar-stack`
  sinnvoll `height:X%` haben). Verifiziert wurde der Fix nicht per
  Screenshot (Chrome-Erweiterung hing fest), sondern über
  `mcp__claude-in-chrome__javascript_tool` mit `getBoundingClientRect()` im
  echten Tab – bei ähnlichen Layout-Bugs künftig bevorzugt so prüfen, wenn
  Playwright/Screenshots gerade nicht verfügbar sind, da curl allein
  Rendering-Fehler dieser Art nicht aufdeckt.

- **SVG-Falle: gemeinsam genutzte Overlay-Gruppe an nur EINER DOM-Position.**
  SVG malt strikt in Dokumentreihenfolge – eine später im DOM stehende Form
  übermalt eine früher stehende vollständig, auch wenn beide über
  `display:none`/`block` unabhängig ein-/ausgeblendet werden. Betraf den
  Tierbaukasten (Wunsch #68): ein einzelner `muster-container` stand im DOM
  vor den "hinten"-Körperformen, wodurch die Rückansicht ihn beim Umschalten
  vollständig verdeckte (bei "vorne" zufällig unsichtbar-unauffällig, weil er
  dort zufällig richtig positioniert war). Lösung: pro Ansicht eine eigene,
  an der richtigen DOM-Stelle liegende Instanz der Overlay-Gruppe, nicht eine
  gemeinsam wiederverwendete. Gilt für jede künftige SVG-Vorschau mit
  mehreren umschaltbaren Ansichten/Zuständen im selben Dokument.

- **twemoji.js: `folder: ''` wird NICHT als "kein Unterordner" verstanden.**
  Die Option wird intern per `how.folder || <Standard>` ausgewertet - ein
  leerer String ist in JavaScript falsy, die Bibliothek fällt dann still
  (ohne Fehlermeldung) auf ihren `72x72`-PNG-Standardordner zurück. Live
  bei Wunsch #119 gefunden: erzeugte URLs wie `/static/twemoji72x72/....svg`
  statt der gewünschten `/static/twemoji/svg/....svg`. Fix: einen echten,
  nicht-leeren Ordnernamen angeben (`folder: 'svg'`) und die Dateien
  entsprechend in einen `svg/`-Unterordner legen, statt zu versuchen, den
  Unterordner ganz wegzulassen. **Generelle Lehre: bei Bibliotheks-Optionen,
  die per `||`-Fallback ausgewertet werden, ist ein leerer String KEIN
  gültiger Weg, um "nichts"/"Standardverhalten deaktivieren" auszudrücken -
  im Zweifel die Bibliotheksquelle prüfen statt der Dokumentation zu
  vertrauen.**

- **SQLite `ALTER TABLE ADD COLUMN` erlaubt keinen nicht-konstanten Default.**
  `DEFAULT (datetime('now'))` und auch `DEFAULT CURRENT_TIMESTAMP` schlagen mit
  "Cannot add a column with non-constant default" fehl (live mit SQLite 3.50
  geprüft), obwohl `CURRENT_TIMESTAMP` beim Erzeugen der Tabelle selbst (`CREATE
  TABLE`) völlig normal funktioniert. Betraf `einkauf_eintraege.geaendert`
  (Wunsch #100, 2026-08-01). Fix: Spalte per `ALTER TABLE` nullable ohne Default
  anlegen, bestehende Zeilen per separatem `UPDATE ... WHERE spalte IS NULL`
  backfüllen, künftige INSERT/UPDATE-Statements setzen den Wert immer explizit
  (kein Verlass auf einen Spalten-Default). Neue Installationen bekommen den
  "sauberen" `NOT NULL DEFAULT (datetime('now'))` direkt aus `SCHEMA`, da dort
  nur `CREATE TABLE` läuft, nie `ALTER TABLE ADD COLUMN`.

- **`<input type="file" capture="environment">` verhindert auf iOS Safari die
  Mediathek-Auswahl.** Das `capture`-Attribut zwingt mobile Browser (allen
  voran iOS Safari), beim Antippen des Datei-Inputs DIREKT die Kamera zu
  öffnen, ohne die native "Foto aufnehmen ODER aus Mediathek wählen"-Auswahl
  zu zeigen - für Andi äußerte sich das als "kann kein Bild auswählen"
  (Wunsch #106, betraf sowohl `rezept_bild_importieren.html` als auch das
  baugleiche `vokabel_foto_import.html`). Fix: `capture` einfach weglassen,
  `accept="image/..."` reicht für die Typ-Einschränkung völlig aus und lässt
  iOS die normale Auswahl anzeigen. **Für jeden künftigen Foto-Upload:
  `capture` nur setzen, wenn wirklich AUSSCHLIESSLICH live fotografiert
  werden soll (z. B. ein Barcode-Scanner) - nie als Standard für "Foto
  hochladen"-Formulare.**

- **CSS-Klassennamen aus base.html können von `{% block extra_styles %}` eines
  Kindtemplates lautlos überschrieben werden.** `{% block extra_styles %}`
  landet im selben `<style>`-Block wie base.html, aber NACH dessen Regeln -
  bei gleicher Spezifität gewinnt also immer das Kindtemplate, ganz ohne
  Fehlermeldung. Betraf Wunsch #105: base.html definiert `.wunsch-card`/
  `.wunsch-actions` fürs globale ✨-Formular, `werkstatt_app.html` definierte
  dieselben Namen für seine Wunschlisten-Karten und überschrieb damit
  unbeabsichtigt das Formular - sichtbar nur auf der Werkstatt-Seite selbst,
  überall sonst sah das Formular normal aus. **Global/gemeinsam genutzte
  Klassen aus base.html (Modals, Overlays u. ä.) brauchen deshalb eindeutige,
  kollisionsresistente Namen** (hier: `.wunsch-modal-card`/
  `.wunsch-modal-actions` statt der generischen `.wunsch-card`/
  `.wunsch-actions`) - einzelne App-Templates dürfen dagegen frei generische
  Namen für ihre eigenen, lokalen Elemente verwenden.

- **Gunicorn 26 Control Socket**: `[Errno 13] Permission denied: '/.gunicorn'` beim Start.
  Nicht-fatal (1 Worker, App läuft stabil). Ursache: Gunicorn 26 hardcoded `os.sep + '.gunicorn'`
  als Control-Socket-Verzeichnis, `GUNICORN_RUN_DIR` wird ignoriert.
  Workaround: bleibt bis zu einem Gunicorn-Fix oder Downgrade auf 21.x.

- **`rezepte.anleitung`**: totes Altfeld, seit dem Rezept-Schritte-Umbau (2026-07-28)
  ungenutzt. Zubereitung liegt jetzt in `rezept_schritte`. Die Spalte konnte nicht per
  `ALTER TABLE ... DROP COLUMN` entfernt werden, ohne das unten beschriebene
  FK-Problem zu riskieren – bleibt daher absichtlich als Leiche liegen.

- **Migrations-Falle: RENAME+Neubau einer Tabelle, auf die andere per Foreign Key
  verweisen.** SQLite schreibt beim `ALTER TABLE x RENAME TO x_alt` automatisch die
  FK-Klauseln ALLER anderen Tabellen, die `REFERENCES x(...)` haben, auf `x_alt` um.
  Wird `x_alt` danach gedroppt, zeigen diese FKs ins Leere (`no such table: x_alt`
  bei jedem betroffenen INSERT/UPDATE) – ohne dass am eigentlichen Migrations-Code
  für `x` selbst etwas falsch aussieht. Passiert am 2026-07-28 mit `rezepte`
  (referenziert von `rezept_zutaten`, `rezept_schritte`, `essensplan_eintraege`),
  live repariert. **Vor jedem RENAME+Neubau-Umbau prüfen, ob die Tabelle von
  irgendeiner anderen per FK referenziert wird** (`grep "REFERENCES <tabelle>"` über
  `SCHEMA` in `00_kern.py`) – wenn ja, entweder nur `ALTER TABLE ADD COLUMN`
  verwenden (keine FK-Auswirkung) oder alle referenzierenden Tabellen im selben
  Zug mit korrigierter FK-Klausel neu aufbauen.

- **`manage.py wunsch_erledigt` setzte `erledigt_am` nicht** (bis portal-v46):
  Die Erledigt-Liste in der Werkstatt-App sortiert nach
  `COALESCE(w.erledigt_am, w.erstellt) DESC`. Ohne `erledigt_am` fiel das auf das
  ursprüngliche Erstellungsdatum zurück – wirkte wie ein Layout-/Sortierfehler
  (Wunsch #59), war aber ein reiner CLI-Bug. Seit portal-v46 setzt der Befehl
  `erledigt_am=CURRENT_TIMESTAMP` mit. Wünsche #48–55, die vor dem Fix per CLI
  abgeschlossen wurden, haben `erledigt_am=erstellt` als Näherung (bestehende
  `00_kern.py`-Migration), keine echten Abschlusszeitpunkte.

- **Single-File-Bind-Mount + `tar xzf` = verwaistes Inode.** Wenn eine
  bind-gemountete Einzeldatei (z. B. `Caddyfile:/etc/caddy/Caddyfile`) per
  `tar xzf` überschrieben wird, entsteht dabei ein NEUES Inode am selben
  Pfad (tar ersetzt die Datei, statt sie in-place zu beschreiben) – der
  bereits laufende Container bleibt an das alte, jetzt verwaiste Inode
  gebunden und sieht die Änderung nicht, auch nicht nach `caddy reload`
  (das reload liest zwar erneut von der Pfadangabe, aber innerhalb des
  Containers zeigt der Bind-Mount weiterhin auf das alte Inode). Betraf
  am 2026-07-29 eine Caddyfile-Änderung, die trotz erfolgreichem Reload
  ohne Fehlermeldung wirkungslos blieb. **Nach jeder Änderung an einer
  bind-gemounteten Einzeldatei den betroffenen Service mit
  `docker compose up -d --force-recreate <service>` neu aufsetzen**, ein
  reines `restart` oder `reload` genügt nicht.

## Tests

`tests/` enthaelt seit Wunsch #140 eine kleine pytest-Suite. Sie laeuft auf
dem Entwicklungsrechner, nicht im Container.

```bash
python -m venv .venv                                   # einmalig
.venv/Scripts/pip install -r requirements-dev.txt      # Windows
.venv/Scripts/python -m pytest tests/ -q
```

- `conftest.py` – Wegwerf-Datenbank je Test (DB_PATH/TOKEN_KEY kommen aus der
  Umgebung), Testfamilie aus Admin/Kind/Eltern. **`sys.path` auf `src/` wird
  beim Laden von conftest gesetzt, nicht erst im Fixture** – sonst scheitern
  Testmodule mit `from teile.kern import …` auf Modulebene schon beim
  Einsammeln.
- `test_grant.py` – Zugangsaufloesung, Rollen, Navigations-Token,
  Verschluesselung. Beschreibt den Ist-Zustand und muss nach jeder Umbaustufe
  wieder gruen sein.
- `test_routen_inventar.py` – misst am **Endpunkt**, nicht an der einzelnen
  Regel: jede aendernde Route braucht `<token>` im Pfad, eine Schwesterregel
  mit `<token>`, oder einen begruendeten Eintrag in `BEKANNTE_AUSNAHMEN`.
  Verlangt zusaetzlich, dass jede `<token>`-Route ihren token-freien Zwilling
  hat - eine beim Umbau vergessene Route faellt damit auf, auch wenn sie ein
  POST-Endpunkt ist, den niemand durchklickt.
- `test_sitzung.py` – Stufe 1 von #140, inklusive der Negativtests, die
  belegen, dass das Cookie noch KEINE Wirkung hat.
- `test_sitzung_gilt.py` – Stufe 3: Vorrang des Pfad-Tokens, Widerruf wirkt,
  ungueltiger Token faellt NICHT aufs Cookie zurueck. Dazu die
  Geraeteuebernahme aus Stufe 4 (wer seinen Link oeffnet, uebernimmt das
  Geraet - und hinterlaesst keine verwaiste Sitzung).
- `test_csrf.py` – Stufe 2: `Sec-Fetch-Site` vor `Origin`, `same-site` wird
  abgelehnt, die drei Modi.
- `test_vokabeln_teilen.py` – Wunsch #150. Die Haelfte der Tests prueft die
  ABGRENZUNG (Empfaenger kann nicht aendern/loeschen/umbenennen/weiterteilen,
  Dritte sehen nichts, Aufheben wirkt sofort) - eine zu weite Freigabe faellt
  im Alltag nicht auf, eine zu enge sofort.
- `test_geburtstage_bearbeiten.py` – Wunsch #158. Prueft die Berechtigung in
  beide Richtungen und drei Dinge, die beim Bearbeiten leicht kippen:
  `erstellt_von` bleibt, andere Eintraege bleiben, und die Erinnerungssperre
  unterdrueckt nach einer Datumskorrektur nichts. Der Vergleich "Anlegen und
  Bearbeiten lehnen dasselbe ab" laeuft ueber das VERHALTEN beider Endpunkte -
  die erste Fassung fragte nur ab, ob es einen gemeinsamen Helfer GIBT, und
  waere gruen geblieben, waehrend eine zweite Kopie abweicht.
- `test_push_geraetewechsel.py` – Wunsch #209 (Audit F-01). Prueft die
  Uebernahme UND dass hinterher nur EINE Zeile dasteht - der Test allein auf
  die Uebernahme bliebe gruen, wenn jemand das UNIQUE auf `endpoint` aufhebt,
  und dann bekaeme das Tablet die Nachrichten beider Personen. Braucht ein
  autouse-Fixture, das `socket.getaddrinfo` stubbt: die Suite laeuft offline,
  ohne Aufloesung faellt schon `ist_oeffentliche_url()` (#203) durch und jeder
  Aufruf endet in 400 statt beim Abo-Besitz.
- `test_backup_hostkey.py` – Wunsch #211, erster Teil. Liest die
  SSH-Optionsliste, statt eine Verbindung aufzubauen (das NAS ist von der
  Testmaschine aus nicht erreichbar; die echte Verbindung wurde nach dem
  Ausrollen von Hand gefahren). Der wichtigste Test ist der Rueckfall, den es
  NICHT geben darf: fehlt `known_hosts`, muss der Lauf ausfallen und es sagen.
- `test_log_grenzen.py` – Wunsch #210, zweiter Teil. Liest `docker-compose.yml`
  zeilenweise statt per PyYAML (eine Abhaengigkeit nur fuer diesen Waechter
  waere zu teuer) und verlangt fuer JEDEN Dienst eine `logging:`-Grenze - der
  Fehler, der hier wirklich passiert, ist ein neuer Dienst ohne. Ein erster
  Test sichert ab, dass die Datei ueberhaupt verstanden wird; sonst waeren die
  Pruefungen leer und gruen.
- `test_kassenbuch_aufsicht.py` – Wunsch #212 (Audit F-04). Haelt DREI Einstiege
  gleichzeitig fest (Uebersicht, fremdes Buch, Pruefprotokoll) - der Befund
  nannte nur die letzten beiden, die Uebersicht listet aber ebenfalls jedes
  Kind mit Kontostand und waere offen geblieben. Der Gast bekommt ausdruecklich
  einen Grant, sonst pruefte der Test nur, dass ein fehlender Grant sperrt.
  Enthaelt eine Gegenprobe per monkeypatch: mit der ALTEN, negativen Regel
  kommt der Gast ueberall mit 200 durch - damit ist bewiesen, dass die 403
  an `_darf_aufsicht` haengen und nicht an etwas anderem. Bewusst per
  monkeypatch statt durch kurzzeitiges Aufweichen des Quelltextes.
- `test_kassenbuch_startkorrektur.py` – Wunsch #216. Der Schwerpunkt ist NICHT
  "kann man den Betrag aendern", sondern dass dabei nichts ueberschrieben wird:
  nach der Korrektur stehen ZWEI Zeilen da (alte storniert, neue gueltig) und
  beide Betraege im Pruefprotokoll. Dazu die Grenze in beide Richtungen und der
  Fall aus #202 (stornierte Buchung haelt das Fenster offen).
- `test_barcode_bildbombe.py` – Wunsch #213 (Audit F-05). Die Testbombe ist ein
  handgebauter PNG-Kopf, der 20000x20000 BEHAUPTET, mit einem Byte Bilddaten -
  waere die Pruefung hinter dem Entpacken, traefe der Test die Testmaschine
  statt den Fehler zu finden. Ein Test prueft ausdruecklich die REIHENFOLGE im
  Quelltext (nach `Image.open`, vor `convert`/`read_barcodes`), und zwar ohne
  Kommentarzeilen - die erwaehnen beide Namen erklaerend und lagen sonst vorne.
- `test_todo_privat_rollenziel.py` – Wunsch #214 (Audit F-06). Prueft Sehen und
  Aendern am SELBEN Datensatz; getrennt geprueft waere der Befund wieder
  moeglich, sobald jemand nur eine der beiden Funktionen anfasst. Auch hier
  eine monkeypatch-Gegenprobe mit der alten Fassung.
- `test_snapshot_aufraeumen.py` – Wunsch #215. Erster Test im Repo, der `util/`
  anfasst; laedt `db_snapshot.py` per `importlib.util.spec_from_file_location`
  und biegt `DB`/`SNAP_DIR` auf ein tmp_path um. Ein Test haelt die Reihenfolge
  in `_prune()` fest (erst alte `.db`, dann Verwaiste).
- `test_tierbaukasten_bearbeiten.py` – Wunsch #201. Derselbe Aufbau wie bei den
  Geburtstagen, plus der Fall, den nur diese App hat: der Kategoriewechsel muss
  die Spalten der alten Kategorie raeumen. Beim Gegenprobieren (Spalte
  `dicebear_optionen` aus `_SPALTEN` entfernt) schlagen genau die zwei
  Wechsel-Tests an - der Rest bliebe gruen, weil eine Tier-Figur die Spalte
  ohnehin nie anfasst. Die Grenzpruefung laeuft auch hier ueber das VERHALTEN
  beider Endpunkte, nicht ueber die Existenz eines gemeinsamen Helfers.
- `test_kassenbuch_unveraenderlich.py` – Wunsch #156. Erzwingt die Zusage, auf
  der die Vollstaendigkeit des Pruefprotokolls beruht: genau DREI schreibende
  Routen (ueber url_map), kein DELETE, und das einzige UPDATE fasst nur die
  Storno-Spalten an. Wer eine Bearbeiten-Route ergaenzt, bekommt im
  Fehlertext gesagt, dass das Protokoll dann eine dritte Ereignisart braucht.
- `test_rezept_portionen.py` – Wunsch #164. Prueft NICHT das Umrechnen (das
  passiert im Browser und ist dort live geprueft), sondern die Stelle, an der
  es den Server beruehrt: der Einkaufen-Knopf muss die ANGEZEIGTE Menge
  uebernehmen. Ohne das saehe man "750 g Mehl" und bekaeme "500 g Mehl" -
  ohne jeden Hinweis.
- `test_essensplan_gekocht.py` – Wunsch #162. Schwerpunkt ist, was die
  Aufzeichnung UEBERLEBT: Planeintrag ueberschrieben, Planeintrag geloescht -
  Historie bleibt; Rezept geloescht - Historie geht per CASCADE mit.
- `test_werkstatt_ticket.py` – Wuensche #161 und #166. Zu #166: die Meldung
  geht NUR bei art='frage' raus und NIE an den Verfasser - beides eigene
  Tests, weil beides im Alltag nicht auffiele (zu viele Meldungen entwerten
  sich langsam, eine Selbstmeldung nervt nur den Admin).
  Zu #161: Schwerpunkt ist, dass ein
  KI-Ausfall NUR den Titel kostet und nie den Wunsch, dazu der Vorrang eines
  von Hand gesetzten Titels und die Schreibberechtigung (Admin ODER Urheber).
  Enthaelt `SofortThread` statt eines Wegwerf-Typs - `type("S", (), {"start":
  target})()` macht die Funktion zur METHODE und wirft TypeError, der Test
  war dann rot ohne echten Fehler.
- `test_tippflaeche.py` – Wunsch #169. Waechtert die 44px-Regel in base.html
  (beide Achsen einzeln - die erste Gegenprobe brach nur width, und der Test
  blieb gruen, weil height die Zeichenkette noch enthielt) und dass keine
  Vorlage ein eigenes button::before/after definiert.
- `test_loeschen_symbol.py` – Wunsch #160. Waechter ueber alle Vorlagen: jeder
  Knopf in einem Formular mit `/loeschen`-Route muss den Muelleimer tragen.
  Enthaelt einen Test, der prueft, dass ueberhaupt >= 10 solcher Knoepfe
  gefunden wurden (sonst waere die Pruefung leer und gruen), und einen, der die
  Kassenbuch-Ausnahme als BEABSICHTIGT festhaelt.
- `test_kopfleiste.py` – Wunsch #155. Waechter ueber ALLE Vorlagen: kein
  `header_extra`, keine Schaltflaeche zwischen `</header>` und `<main>`.
  Kommentare werden vorher entfernt, sonst loesten die Hinweistexte in
  base.html/admin.html den Test selbst aus. Enthaelt einen Test, der prueft,
  dass ueberhaupt Vorlagen gefunden wurden - sonst waere die Parametrisierung
  leer und alles gruen.
- `test_geraete.py` – Wunsch #154. Kern sind zwei Tests, die die Wirklichkeit
  treffen sollen statt einer bequemen Naeherung: `..._ueberlebt_die_kuerzung`
  kuerzt eine ECHTE User-Agent-Kennung erst auf `_GERAET_MAX` und parst dann
  (bei 80 faellt er - so wurde die Kuerzung ueberhaupt entdeckt), und die
  Drosselungs-Tests setzen `gesehen` gezielt auf -5 Minuten bzw. -2 Stunden.
  Die erste Fassung rief nur zweimal auf, beide Aufrufe fielen in dieselbe
  Sekunde, und der Test bestand auch OHNE Drosselung.
- `test_wunsch_prioritaet.py` – Wunsch #152. Prueft den ENDPUNKT, nicht die
  Seite: die Auswahl steht im Template hinter `user.is_admin`, aber `/wunsch`
  nimmt JSON und ein selbstgebauter POST umgeht jedes Template. Enthaelt
  bewusst Positiv-Faelle (Admin DARF) - die erste Fassung der Fixture legte
  ungueltige Tokens an, wodurch fuenf Verbots-Tests aus dem falschen Grund
  gruen waren; nur die Admin-Tests haben es aufgedeckt.
- `test_kassenbuch_pruefung.py` – Wunsch #153. Zugriffsgrenze in beide
  Richtungen (Eltern/Admin 200, Kind 403 auch aufs EIGENE Protokoll), das
  Storno als eigenes Ereignis, die Sortierung nach Erfassungszeit statt nach
  Buchungsdatum, "nachgetragen" mit Gegenprobe (zeitnaher Eintrag darf NICHT
  markiert werden) und die Zeitzonen-Umrechnung. Zwei Tests wurden durch
  absichtliches Kaputtmachen gegengeprueft.
- `test_tvb_wettbewerbe.py` – Wunsch #151. Der erste Test haelt bewusst den
  IST-Zustand fest (der exakte ID-Vergleich uebersieht das Pokalspiel): geht er
  eines Tages durch, hat handball.net die IDs vereinheitlicht und die
  Erweiterung ist ueberfluessig - besser ein roter Test als eine still
  ueberfluessige Sonderbehandlung. Dazu die Gegenrichtung (fremde Vereine mit
  Praefix 62721) und dass die Wettbewerbsspalte die Speicherung ueberlebt -
  der Spielplan liest aus tvb_spiele, nicht aus der API-Antwort.
- `test_tts_sprache.py` – Wunsch #149/#148: Sprachangabe geht ans Modell,
  Kontingent zaehlt nur das Wort, Cache-Schluessel ist versioniert, gleiches
  Wort teilt sich die Datei, verschiedene Sprachen nicht. Dazu die
  Audio-Kennzeichnung aus #148.
- `test_barcode.py` – Wunsch #143. Schwerpunkt ist die Ziffern-Pruefung (der
  Code geht in eine URL) - dieser Test hat den `$`/`\Z`-Fehler gefunden. Dazu
  die Produktabfrage mit vorgetaeuschten Antworten, die Pruefung der
  KI-Kategorie gegen die vorhandenen Kategorien und ein echtes Dekodieren
  eines erzeugten EAN-13.
- `test_emoji.py` – Wunsch #147: jedes in Vorlagen/Code verwendete Emoji und
  jedes App-Emoji aus der Datenbank muss eine lokale Twemoji-Grafik haben.
  Fehlt sie, bleibt unter Linux/Chrome eine leere Kachel, waehrend iOS/macOS
  oft System-Emoji einspringen laesst - der Fehler zeigt sich also nur auf
  einem Teil der Geraete. `server.md` warnte davor schon seit Wunsch #122;
  eine Warnung in der Doku ist kein Waechter, deshalb jetzt ein Test.
- `test_push.py` – haelt `PUSH_TTL > 0` fest. Ohne `ttl` schickt `pywebpush`
  TTL 0, und Microsofts WNS (Windows/Edge) verwirft die Nachricht mit HTTP 400
  ("Ttl value conflicts with X-WNS-Cache-Policy"). Apple/Google stoert das
  nicht - der Fehler betraf jahrelang nur ein Geraet und aeusserte sich als
  "da kommt halt nichts". Gegengeprueft: ohne ttl schlaegt der Test an.
- `test_zugang_einmalig.py` – Wunsch #140 Stufe 6. Der wichtigste Test ist
  `test_der_angezeigte_link_funktioniert_wirklich`: Ein Link, der zwar
  angezeigt wird, aber nicht traegt, waere der schlimmste Fehler dieser Stufe -
  er fiele erst auf, wenn jemand ausgesperrt ist. Dazu: Verwaltung zeigt keine
  fremden Zugaenge (token-frei ueberhaupt keine), `/qr.svg` existiert nicht
  mehr, der alte Link ist nach dem Neuerzeugen tot.
- `test_csp.py` – Wunsch #142. Wichtigster Test: `test_keine_inline_handler_mehr`
  liest die Vorlagen im Quelltext und laesst kein neues `onclick=` zu. Ohne
  ihn waere der Umbau in ein paar Wochen still wieder zunichte, denn beim
  Entwickeln steht `CSP_MODUS=aus` - ein neues Inline-Attribut faellt dort
  nicht auf, im Betrieb reagiert der Knopf dann einfach nicht. Prueft
  ausserdem: Nonce in Kopfzeile und Seite identisch, Nonce je Anfrage
  verschieden, `frame-ancestors` in jedem Modus vorhanden (sonst ist der
  Kiosk schwarz), Meldeendpunkt nimmt auch Muell an.
  **Beide Waechter-Tests wurden gegengeprueft** (absichtlicher Fehler
  eingebaut, Test schlaegt an) - ein Waechter, der nicht ausloesen kann, ist
  schlimmer als keiner.
- `test_seiten_erreichbar.py` – Rauchtest ueber alle 36 parameterlosen Seiten,
  **zweimal**: mit Token und token-frei ueber das Cookie. Sucht ausserdem in
  jeder ausgelieferten Seite nach ALLEN Tokens des Nutzers (nicht nur dem der
  offenen App) und prueft den Notausstieg `TOKENFREIE_URLS=0`.
  Ein fehlender Grant ist hier ein FEHLER, kein stilles Ueberspringen - das
  hatte einmal verdeckt, dass 14 der 36 Seiten gar nicht geprueft wurden.

`pytest` steht bewusst in `requirements-dev.txt`, nicht in
`src/requirements.txt` – die beschreibt die Laufzeit und ist seit Wunsch #135
exakt gepinnt.

Ergaenzend die Handpruefung durch Andi: `pruefplan.md` im Projektwurzel-
verzeichnis, je Umbaustufe eine Tabelle mit nummerierten Testfaellen. Deckt
ab, was ein Skript nicht sehen kann: echtes Geraet, echter Browser, echter
iFrame, installierte PWA.

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

# Caddyfile geaendert? Dann zusaetzlich (bind-gemountete Einzeldatei,
# siehe Bekannte Issues - ein reload/restart greift NICHT):
ssh -p 2222 claude@10.0.0.100 "cd /srv/familienportal && docker compose up -d --force-recreate caddy"

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
docker exec portal python manage.py wunsch_erledigt <id> ["Beschreibung der Umsetzung"]
docker exec portal python manage.py backlog
```

## Stündlicher Wunsch-Durchlauf (#157)

Ein wiederkehrender Claude-Auftrag, jede Stunde um **:23**. Er **lebt nur in
der Claude-Sitzung**, in der er angelegt wurde, und läuft spätestens nach
sieben Tagen ab – wenn nichts mehr passiert, ist das die erste Erklärung.
Neu einschalten: Auftrag mit demselben Text wieder anlegen (Fassung im
Journal, 12.08.2026).

Was ansteht, beantwortet ein reines Leseskript – **kein SQL im Auftragstext**,
das musste sonst durch PowerShell, SSH und `docker exec` hindurch:

```bash
ssh -p 2222 claude@10.0.0.100 "docker exec -i portal python -" < scripts/wunsch_lauf_check.py
```

Erste Zeile ist `ARBEIT: n`; bei 0 antwortet der Lauf mit einer Zeile und tut
sonst nichts. Danach drei getrennte Listen: **ANTWORTEN** (Andi hat auf eine
Rückfrage geantwortet – Vorrang), **FREIGEGEBEN** (offen, Priorität gesetzt und
nicht `zurueckgestellt`), **WARTET** (Rückfrage offen – nicht anfassen und
nicht nochmal fragen, jede Frage löst einen Push aus).

Ohne Priorität (NULL) heisst **nicht** freigegeben, `zurueckgestellt` ist
unantastbar (#61/#152) – die Priorität setzt ausschliesslich ein Mensch.
