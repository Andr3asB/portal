# server.md – Aktueller Systemzustand

*Letzte Aktualisierung: 2026-08-01 (portal-v92: Wunsch #95 Sportschau-Zeitraum wählbar 14/30/60/90 Tage)*

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
OPENROUTER_API_KEY=<Key von openrouter.ai, mit Ausgabenlimit im OpenRouter-Konto>
HAE_API_URL=http://caddy:2021/api/workouts
HAE_API_KEY=<Read-Token vom hae-Server, NICHT der Write-Token der iPhone-Automation>
```

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
                       zu "app_slug/unterseite", token-frei (Wunsch #47)
  03_admin.py        – /a/admin/<token>/ Admin-Bereich: Nutzer (mit Rolle), Grants,
                       QR-Codes, _clean_farbe() (Hex-Validierung)
  04_todo.py         – /a/todo/<token>/ Aufgabenliste; todos_neu() mit Push-Deep-Link;
                       Ziel: Person (zugewiesen_an, wie bisher) ODER eine/mehrere
                       Rollen bzw. "alle" (zugewiesen_rollen, kommagetrennt,
                       Sentinel "alle" – Wunsch #39); nur Rollen/Alle-Ziel landet
                       initial im Backlog statt Offen; /status/<id> (4 Stufen:
                       backlog/offen/in_arbeit/erledigt) – Kind/Gast dürfen auch bei
                       passender Rolle/"alle" ändern, nicht nur bei eigener Zuweisung;
                       /bearbeiten/<id> (Wunsch #43: alle Felder – Text, Ziel
                       Person/Rolle(n)/Alle, Privat – gleiche UX wie /neu; Eltern
                       alle/Kinder eigene bzw. rollenpassende; Status bleibt beim
                       Bearbeiten unangetastet; nur Textänderungen landen im Verlauf).
                       Wiederkehrende Aufgaben-Vorlagen/Pool (Wunsch #90):
                       /serien (GET+POST, Template todo_serien.html) verwaltet
                       todo_serien (Inhalt + Wiederkehr-Regel: 'intervall' X Tage
                       nach Erledigung ODER 'wochentag' fest, pro Vorlage gewählt).
                       serien_pool_liste()/serie_einsortieren() sind fuer andere
                       Module gedacht (importiert von kinderplan ueber den Alias
                       teile.todo, siehe teile/__init__.py) - eine eingesetzte
                       Instanz ist ein normales todos-Row mit serie_id+plan_tag
                       gesetzt (Wunsch #92, echtes Datum statt Wochentag-Zahl),
                       taucht mit 🔁-Chip in der normalen Todo-Liste auf.
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
                       Markierung; /bearbeiten/<id> speichert Name+Kategorie+Angebot
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
  11_rezepte.py      – /a/rezepte/<token>/ Lieblingsrezepte (Zutaten in
                       rezept_zutaten, Zubereitungsschritte einzeln in
                       rezept_schritte, Portionen als rezepte.portionen,
                       Kategorie 'kochen'/'backen' als rezepte.kategorie –
                       Wunsch #55, KATEGORIEN-Dict + _clean_kategorie() als
                       einzige Quelle der gültigen Werte);
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
                       Geholfen-Aufgaben haengen weiterhin an einer woechentlich
                       wiederkehrenden Regel (kinderplan_eintraege.wochentag,
                       bewusst unveraendert - bestehende Wochenroutinen bleiben
                       automatisch bestehen), fuer jeden der 14 echten Kalender-
                       tage wird per d.weekday() nachgeschaut, welche Regeln
                       passen; /zuweisen schreibt weiter auf diese Regel (gilt
                       fuer JEDEN Tag mit diesem Wochentag, nicht nur den einen
                       angeklickten), /abhaken weiterhin direkt in
                       geholfen_eintraege. Todo-Pool-Instanzen (Wunsch #90)
                       haengen dagegen an einem echten Kalendertag
                       (todos.plan_tag, ISO-Datum - ersetzt das urspruengliche
                       todos.wochentag, das nie mit Produktivdaten gefuellt war
                       und als totes Altfeld liegen bleibt): /serie_einsortieren
                       (Pool-Vorlage aus teile.todo fuer eine Person+Datum
                       einsetzen, einmalig, kein wiederkehrendes Muster) und
                       /serie_erledigen/<id> (schreibt direkt in todos, nicht
                       geholfen_eintraege). _gesperrter_tag_datum() (vorher
                       _gesperrter_wochentag()) sperrt ab 20 Uhr DEUTSCHER Zeit
                       (ZoneInfo("Europe/Berlin"), siehe Bekannte Issues -
                       Container laeuft in UTC) den naechsten echten Kalendertag
                       fuer Kinder, Eltern/Admin ausgenommen. Bewusst KEIN
                       Drag & Drop zwischen Tagen (anders als Essensplan) - fuer
                       die wochentag-basierten Geholfen-Regeln ergibt das keinen
                       Sinn (wuerde die ganze Regel verschieben, nicht nur einen Tag)
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
                       gruenen Heatmap oben. Nur Andi granted (persönliche
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
                       /loeschen/<id> (POST, nur eigene Kreationen). Jeder
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

## Datenbankschema (SQLite, WAL)

| Tabelle | Inhalt |
|---------|--------|
| `users` | id, name, farbe, is_admin, ki_key (ungenutzt), dark_mode, rolle ('eltern'/'kind'/'gast'), ki_token_limit (Monats-Kontingent für ki_anfrage(), Default 100000, im Admin editierbar) |
| `ki_nutzung` | id, user_id, feature (z. B. "rezepte_import"), tokens, erstellt – Verbrauchs-Log für ki_anfrage(), gemeinsames Kontingent über alle KI-Features |
| `apps` | id, slug, name, emoji, beschreibung |
| `grants` | id, user_id, app_id, token (UNIQUE), position (sort), gruppe_id (FK home_gruppen) |
| `home_gruppen` | id, user_id, name, position – per-user app groups |
| `push_abos` | id, user_id, endpoint, p256dh, auth, geraet |
| `wuensche` | id, text, titel, prioritaet, user_id, app_slug, ansicht (app_slug/unterseite, token-frei – Wunsch #47), erstellt, erledigt, erledigt_am, umsetzung (Wunsch #101: was genau implementiert wurde, gesetzt über `manage.py wunsch_erledigt <id> "Text"`) |
| `todos` | id, inhalt, erstellt_von, zugewiesen_an, zugewiesen_rollen (TEXT, kommagetrennt, Sentinel "alle" – Wunsch #39, exklusiv zu zugewiesen_an), privat, erledigt, erledigt_am, erstellt, status ('backlog'/'offen'/'in_arbeit'/'erledigt', mit erledigt synchron gehalten), serie_id (FK todo_serien, NULL bei normalen Todos – Wunsch #90), wochentag (totes Altfeld – urspr. 0=Mo..6=So für Wunsch #90, nie mit Produktivdaten gefüllt, durch plan_tag ersetzt – Wunsch #92), plan_tag (ISO-Datum, nur bei serie_id gesetzt – Wunsch #92) |
| `todo_serien` | id, inhalt, wiederkehr_typ ('intervall'/'wochentag'), intervall_tage, fester_wochentag (0=Mo..6=So), aktiv, erstellt_von, erstellt – Wunsch #90, Pool-Vorlagen fuer wiederkehrende Aufgaben |
| `todo_historie` | id, todo_id (FK todos, cascade), alter_inhalt, geaendert_von, geaendert_am |
| `geholfen_aufgaben` | id, name, emoji, gewichtung, aktiv |
| `geholfen_eintraege` | id, aufgabe_id, user_id, zeitstempel |
| `einkauf_laeden` | id, name, aktiv |
| `einkauf_kategorien` | id, name (UNIQUE), position, aktiv |
| `einkauf_eintraege` | id, name, kategorie (Alttext, historisch), kategorie_id (FK einkauf_kategorien), angebot, laden_id, erledigt, erledigt_am, erstellt, erstellt_von, geaendert (Wunsch #100: bei jedem INSERT/UPDATE explizit gesetzt, Grundlage für den /stand-Sync-Fingerabdruck) |
| `rezepte` | id, name, portionen (Freitext, z. B. "4" oder "4-6 Portionen"), kategorie ('kochen'/'backen'/NULL – Wunsch #55), quelle_url (NULL außer bei URL-Import – Wunsch #63), anleitung (totes Altfeld, siehe Bekannte Issues), erstellt_von, erstellt |
| `rezept_zutaten` | id, rezept_id (FK rezepte, cascade), name, position |
| `rezept_schritte` | id, rezept_id (FK rezepte, cascade), text, position – ein Zubereitungsschritt pro Zeile, analog zu rezept_zutaten |
| `rezept_bewertungen` | id, rezept_id (FK rezepte, cascade), user_id (FK users, cascade), sterne (1-5), erstellt; UNIQUE(rezept_id, user_id) – eine Bewertung pro Nutzer und Rezept, editierbar per Upsert |
| `rezept_wuensche` | id, rezept_id (FK rezepte, cascade), user_id (FK users, cascade), erstellt; UNIQUE(rezept_id, user_id) – "Wünsch ich mir"-Markierung, max. 5 aktive pro Nutzer (Wunsch #65), automatisch entfernt sobald das Rezept nach der Markierung auf dem Essensplan war und der Tag vorbei ist |
| `essensplan_eintraege` | id, tag (ISO-Datum), mahlzeit ('mittag'/'abend'), rezept_id (FK rezepte), text, erstellt_von, erstellt; UNIQUE(tag, mahlzeit) |
| `kinderplan_eintraege` | id, user_id (FK users, cascade), aufgabe_id (FK geholfen_aufgaben, cascade), wochentag (0=Mo..6=So), position, erstellt; UNIQUE(user_id,aufgabe_id,wochentag) |
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
- **`|tojson` in `<script>`-Blöcken NIE mit `|forceescape` kombinieren**
  (Gegenteil der Regel oben): `forceescape` ist nur für HTML-Attribute
  (`onsubmit="..."`) nötig. Innerhalb von `<script>...</script>` liefert
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
| SQLite-Snapshot | stündlich | 24 Slots in `/data/snapshots/` |
| Zertifikats-Watcher | täglich 04:00 + einmalig beim Start | prüft mtime, löst Caddy-Reload aus |
| NAS-Backup | täglich 03:00 | tar+ssh-Pipe → Ugreen NAS 10.60.0.4:2222, User `familienportal`, Pfad `/volume2/portal.16schwaben.de_Backup/`, 7 Generationen |

SSH-Key für Backup: `/srv/familienportal/ssh/id_ed25519` (bind-mount als `/ssh/id_ed25519` im Container, read-only). Public Key auf NAS in `/home/familienportal/.ssh/authorized_keys`.

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
  Uhrzeit-Schwellwerte.** Reine Zeitspannen-/Differenzberechnungen (z. B.
  `_serie_ist_im_pool()` in `04_todo.py`) sind davon NICHT betroffen, da
  dort nur UTC-gegen-UTC verglichen wird (sowohl `datetime.now()` als auch
  SQLites `datetime('now')` liefern konsistent UTC) - nur bei echten
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
docker exec portal python manage.py wunsch_erledigt <id> ["Beschreibung der Umsetzung"]
docker exec portal python manage.py backlog
```
