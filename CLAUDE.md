# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

# Familienportal – portal.16schwaben.de

Diese Datei wird von Claude Code bei **jeder** Sitzung automatisch
gelesen. Sie ersetzt das manuelle Übergeben des Bauplans.

## Zuerst lesen, in dieser Reihenfolge

1. `bauplan.md` – die verbindlichen Regeln und die Architektur.
   **Abschnitt 0 ist nicht verhandelbar.**
2. `server.md` – aktueller Zustand des Systems.
3. `journal.md` – was zuletzt passiert ist und warum.

`server.md` und `journal.md` sind beide groß (~2.500 bzw. ~9.000 Zeilen,
neuester Journal-Eintrag oben). Nicht am Stück lesen – `journal.md` von oben
für den letzten Stand, in `server.md` gezielt per Grep in den Abschnitt
springen, der zur Aufgabe passt („Bekannte Issues", „Code-Struktur",
„Deployment-Ablauf", die Test-Liste).

Dazu, wenn ein Umbau in Stufen ausgeliefert wird: `pruefplan.md` – Andis
Handprüfung je Stufe (echtes Gerät, echter Browser, echter iFrame,
installierte PWA). Nur was ein Skript prinzipiell nicht sehen kann.

## Harte Grenzen (Kurzfassung)

- Ziel-Host: `ssh -p 2222 claude@10.0.0.100`
- **Nichts auf dem Host installieren**, keine Host-Konfiguration ändern
- Schreiben ausschließlich in `/srv/familienportal/`
- Das macvlan-Netz ist **geteilte Infrastruktur** – als `external` einbinden,
  niemals anlegen, ändern oder löschen
- Freie IP aus 10.0.0.192/26 vorschlagen und **von Andi bestätigen lassen**,
  bevor der Stack ausgerollt wird
- Zertifikat: nur `portal.16schwaben.de/` aus dem Volume `iobroker-certs`,
  read-only. Andere Domains dort sind tabu.
- Im Zweifel fragen – vorher, nicht hinterher.

## Arbeitsweise

Bauen → ausliefern → **von diesem Rechner aus** end-to-end testen →
dokumentieren. Immer vollständig, immer in dieser Reihenfolge.

Testen nie vom Host aus: `home02` kann seine eigenen macvlan-Container
nicht erreichen. Tests laufen von diesem Rechner (10.10.0.0/24) über das
UniFi-Gateway zu den Containern (10.0.0.192/26).

Nach jeder Auslieferung die Checkliste aus `bauplan.md` Abschnitt 9
abarbeiten.

Nach jeder Entwicklungssession (sobald bauen → ausliefern → testen →
dokumentieren abgeschlossen ist) das Repo **ohne gesonderte Aufforderung**
nach GitHub pushen (`git push`, ggf. vorher committen). Gilt als generelle,
dauerhafte Anweisung – keine Rückfrage nötig, außer bei ungewöhnlichen
Situationen (z. B. Force-Push, fremde Änderungen im Weg, potenzielle
Geheimnisse in den Änderungen).

„Implementiere alle Wünsche" heißt: **alle außer den mit Priorität
`zurueckgestellt` markierten** (siehe Docstring in `05_werkstatt_app.py`).
Deren Priorität ändert ausschließlich ein Admin manuell – nie automatisiert,
auch nicht im Rahmen eines Sammel-Auftrags.

## Wichtige Kommandos

```bash
# Host erreichbar?
ssh -p 2222 claude@10.0.0.100 "echo ok"

# Stack ausrollen (auf home02)
ssh -p 2222 claude@10.0.0.100 "cd /srv/familienportal && docker compose up -d --build"

# Container-Status prüfen
ssh -p 2222 claude@10.0.0.100 "docker compose -p familienportal ps"

# Logs ansehen
ssh -p 2222 claude@10.0.0.100 "docker compose -p familienportal logs --tail=50 portal"

# Zertifikat prüfen
openssl s_client -connect portal.16schwaben.de:443 -servername portal.16schwaben.de </dev/null 2>/dev/null | openssl x509 -noout -dates

# manage.py im Container – Nutzer/Apps/Grants anlegen, Backlog einsehen
docker exec portal python manage.py listusers
docker exec portal python manage.py backlog
```

Auslieferung ist ein Dreischritt (Paket bauen → hochladen → entpacken +
`--build`), die vollständige Fassung mit allen `--exclude` steht in
`server.md`, Abschnitt „Deployment-Ablauf". Zwei Punkte, die dort leicht
untergehen:

- **Code-Änderungen brauchen `--build`, nicht `restart`.** Templates und
  Python-Dateien sind ins Image eingebacken.
- **Caddyfile-Änderungen brauchen `docker compose up -d --force-recreate
  caddy`** – die Datei ist als einzelne Datei bind-gemountet, ein
  Reload/Restart greift dort nicht.

Versionsnummern in `deploy/` zählen hoch und werden nie überschrieben; die
höchste vorhandene `portal-vN.tar.gz` ist der letzte ausgelieferte Stand.

## Tests

Die Suite ist **pytest, nicht Playwright**, und läuft komplett offline gegen
eine Wegwerf-Datenbank – kein laufendes Portal, kein Netz, kein Container
nötig. `tests/conftest.py` baut je Test eine frische DB samt kleiner Familie
(Admin, Kind, Elternteil) und setzt `DB_PATH`/`TOKEN_KEY`/… in der Umgebung,
bevor `app` importiert wird. Die App wird **einmal** importiert
(session-scope – Flask-Blueprints lassen sich nicht zweimal registrieren),
die DB pro Test neu (function-scope).

```bash
# Einrichten (einmalig)
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt     # Windows
.venv/bin/pip install -r requirements-dev.txt         # Linux/macOS

# Alles (dauert wenige Sekunden)
.venv/Scripts/python -m pytest tests/ -q

# Eine Datei, ein einzelner Test, ein Muster über alle Dateien
.venv/Scripts/python -m pytest tests/test_grant.py -q
.venv/Scripts/python -m pytest tests/test_grant.py::test_token_gilt_nur_fuer_seine_app -q
.venv/Scripts/python -m pytest tests/ -k kontingent -q
```

`pytest` steht bewusst nur in `requirements-dev.txt`; `src/requirements.txt`
beschreibt die Laufzeit und ist exakt gepinnt (Wunsch #135) – dort nichts
Test-Werkzeug hineinschreiben.

**Ein großer Teil der Suite sind Konventions-Wächter, keine Funktionstests.**
`test_tippflaeche.py`, `test_aria_labels.py`, `test_loeschen_symbol.py`,
`test_kopfleiste.py`, `test_emoji.py` und `test_csp.py` lesen die Vorlagen im
Quelltext und schlagen an, wenn eine neue Vorlage gegen eine der
UI-Konventionen weiter unten verstößt. Schlägt einer davon an, ist die
Vorlage falsch, nicht der Test. Wer einen neuen Wächter schreibt: vorher
gegenprüfen, dass er auch wirklich auslöst (absichtlichen Fehler einbauen) –
ein Wächter, der nicht anschlagen kann, ist schlimmer als keiner.

`server.md` beschreibt am Ende jede Testdatei einzeln mitsamt dem Fehler, den
sie gefunden hat – dort nachsehen, bevor ein bestehender Test angefasst wird.

## Prüfung gegen das laufende Portal

```bash
python scripts/live_pruefung.py            # als erster Admin
python scripts/live_pruefung.py Friederike
```

Ruft jede App eines Nutzers über HTTPS auf. **Nie wieder ad hoc mit `curl`
prüfen:** Seit dem Sitzungs-Umbau stellt jeder Aufruf ohne Cookie eine neue,
nie ablaufende Sitzung aus – das hatte 808 Zugänge in der Datenbank
hinterlassen (journal.md, 08.08.2026). Das Skript legt genau **eine** Sitzung
an (Kennung `geraet='PRUEFUNG'`) und löscht sie im `finally` wieder.

## Architektur (Überblick)

Stack `familienportal` mit drei Containern auf `home02`:

| Container | Rolle |
|-----------|-------|
| `portal`  | Python 3.12 + Flask + Gunicorn (1 Worker, Threads), SQLite unter `/srv/familienportal/data` |
| `caddy`   | TLS-Terminierung, Zertifikat aus Volume `iobroker-certs` (read-only), kein ACME |
| `util`    | Scheduler (supercronic o. ä.), stündliche SQLite-Snapshots, tägliches Backup, Zertifikats-Watcher |

Netz: nur `caddy` bekommt eine macvlan-IP. `portal` und `util` hängen
ausschließlich im internen Bridge-Netz.

Code-Struktur: `app.py` führt nummerierte Module (`teile/00_kern.py`,
`teile/01_start_token.py`, …) in einem Namensraum aus. Templates als
einzelne HTML-Dateien mit Inline-CSS/JS; JS-Bibliotheken lokal bündeln,
nie von fremden CDNs.

## Code-Architektur (`src/`)

`app.py` ist bewusst dünn: es erzeugt die Flask-App und lädt danach jedes
`teile/NN_name.py`-Modul in aufsteigender Nummernreihenfolge über
`importlib`, ruft dessen `init_app(app)` auf. Alle Module teilen sich
einen Namensraum – neue Funktionalität heißt: neue Datei mit nächster
freier Nummer, kein Umbau von `app.py`. `teile/__init__.py` registriert
`00_kern.py` zusätzlich als `teile.kern` in `sys.modules`, weil ein
führendes `0N_` kein gültiger Python-Modulname für ein reguläres
`from teile.00_kern import …` wäre.

**`teile/00_kern.py` ist die gemeinsame Basis, jedes weitere Modul baut darauf auf:**
- `SCHEMA` (alle `CREATE TABLE IF NOT EXISTS`) + `_init_db()` (idempotente
  `ALTER TABLE`-Migrationen per try/except, Seed-Daten). Schemaänderungen
  gehören hierher, nicht in einzelne App-Module.
- `get_db()` – request-gebundene Verbindung über Flasks `g`; **nur**
  innerhalb eines Requests verwenden.
- `new_db()` – Context-Manager mit eigener Verbindung für Threads/Hintergrundarbeit.
  Wer `g.db` aus einem Thread heraus anfasst, bekommt „Cannot operate on
  a closed database" – deshalb hat `push_send()` z. B. eine eigene Verbindung.
- `grant(token, app_slug)` – der zentrale Zugriffs-Check: löst ein
  Token+App-Slug-Paar zur Nutzer-Row auf oder gibt `None` zurück. Jede
  Route in jedem App-Modul beginnt damit.
- `to_int()`, `push_send()` (Web-Push, VAPID, non-blocking Thread),
  `_auto_grant_all()` (vergibt eine App automatisch an alle Nutzer, z. B.
  `hilfe` und `einkauf`).

**Verbindliche Konventionen (siehe auch `server.md` „Sicherheitskonventionen"):**
- Ganzzahlen aus Nutzereingaben immer über `to_int()`, nie nacktes `int()`.
- Farbwerte immer über `_clean_farbe()` aus `03_admin.py` validieren
  (Regex `^#[0-9a-fA-F]{6}$`).
- Im Frontend-JS `textContent`/`createElement` statt `innerHTML`, wenn
  Nutzerdaten eingesetzt werden.
- Jede Route prüft `grant()` zuerst; destruktive Aktionen zusätzlich
  `is_admin`/Owner-Check.
- Jedes echte (nicht reversible) Löschen fragt vorher per `confirm()` nach –
  seit Wunsch #142 (CSP) über das Attribut `data-bestaetigen="Frage?"` am
  Formular, das ein zentraler Verteiler in `base.html` auswertet. **Kein
  `onsubmit`/`onclick` mehr** (`test_csp.py::test_keine_inline_handler_mehr`
  lässt kein neues Inline-Attribut durch; beim Entwickeln steht
  `CSP_MODUS=aus`, ein neuer Inline-Handler fiele dort sonst nicht auf und
  der Knopf reagierte erst im Betrieb nicht). Reversible Toggles
  (aktiv/inaktiv, Grant-Entzug) brauchen keine Abfrage.

**UI-Konventionen (verbindlich, aus Nutzer-Feedback, nicht in `bauplan.md`):**
- Jede Unterseite braucht einen eigenen Zurück-Link. Der ⌂-Heimknopf führt
  immer zur persönlichen Startseite und ist kein Ersatz dafür – keine
  Sackgassen.
- **Icon-Knöpfe** (Beschriftung nur ein Zeichen) brauchen `aria-label`; steht
  auch ein `title` dran, sind beide Texte identisch (Wunsch #175,
  `tests/test_aria_labels.py`).
- **Umschalter ohne Seitensprung** (Wunsch #171): `data-fetch="fn"` am
  Formular, serverseitig `antwort_oder_weiter()`. Aber nur, wenn der
  Umschalter die Listen-Reihenfolge NICHT ändert – sonst Weiterleitung mit
  `#anker` auf die eigene Karte.
- **Lange Vorgänge:** Formulare, deren Absenden spürbar dauert (KI-Anfrage),
  tragen `data-arbeitet="Wird gelesen …"` – der Verteiler in `base.html`
  deaktiviert und beschriftet den Knopf um (Wunsch #176).
- **Vier globale Regeln in `base.html`** (Tippfläche #169, Feldschrift ≥16px
  #170, `.main` max-width 720px #173, `:focus-visible`-Ring #174) – keine
  Vorlage darf sie überschreiben, `tests/test_tippflaeche.py` wächtert alle
  vier. Merke zur Spezifität: eine Klassenregel in einer Vorlage schlägt die
  globale Element-Regel immer, unabhängig von der Reihenfolge.
- **Tippfläche:** jeder `button` hat via `base.html` mindestens 44×44 px
  unsichtbare Trefferfläche (Wunsch #169). Nie ein eigenes
  `button::before`/`::after` in einer Vorlage definieren –
  `tests/test_tippflaeche.py` wächtert das.
- **Löschen trägt im ganzen Portal 🗑️** – nie ✕, nie nur Text (Wunsch #160).
  Gilt für jedes Bedienelement, das einen Datensatz wirklich entfernt;
  `tests/test_loeschen_symbol.py` wächtert es über alle Vorlagen. Ausgenommen
  ist das Kassenbuch: dort wird **storniert**, nicht gelöscht (die Zeile bleibt
  stehen), ein Mülleimer würde etwas anderes versprechen als die App tut.
- Aktionsknöpfe einer Seite stehen **oben im `<main>`** als `.top-aktionen`-Zeile
  (Vorbild `todo.html`: Rahmen in `var(--farbe)`, transparenter Grund) – nie auf
  dem farbigen Kopfband. Der dafür gedachte Block `header_extra` ist mit
  Wunsch #155 aus `base.html` entfernt; `tests/test_kopfleiste.py` wächtert das.
- Jede neue Funktion gehört in die Hilfe-App (`09_hilfe.py`/`hilfe.html`),
  bei Bedarf als eigenes Kapitel mit Sprunglink im Inhaltsverzeichnis.
  Gehört zum „dokumentieren"-Schritt der Arbeitsweise oben, genauso
  verbindlich wie `journal.md`/`server.md`.

**Templates:** je App eine eigene `.html`-Datei mit Inline-CSS/JS,
`base.html` liefert das gemeinsame Grundlayout (⌂-Include, Hamburger-Menü
mit Dark Mode/Hilfe/✨, Service-Worker-Registrierung). Kein Build-Schritt,
kein gemeinsames Frontend-Framework – JS-Bibliotheken werden lokal
gebündelt, nie von einem CDN geladen.

Den aktuellen Stand von DB-Schema, App-Slugs und Modulen (mit Kurzbeschreibung
je Datei) pflegt `server.md` – dort nachsehen statt hier zu duplizieren,
da sich das mit jeder Auslieferung ändert.

## Guardrails und Berechtigungen

`settings.json` und `guardrails.sh` im Projekt-Root sind die
Konfigurationsvorlagen für `.claude/` auf diesem Rechner.

- `settings.json`: deny-Liste für gefährliche lokale Befehle (sudo, apt,
  docker network rm etc.) und eine allow-Liste für häufige Befehle
- `guardrails.sh`: PreToolUse-Hook, der SSH-Nutzlasten auswertet und
  dieselben Verbote durchsetzt – greift auch, wenn der Befehl erst per SSH
  auf `home02` landet

**Nicht ändern** – außer nach expliziter Absprache mit Andi.

## Verzeichnisse

- `src/` – Quellcode des Portals (wird nach `/srv/familienportal/src` ausgeliefert)
- `deploy/` – versionierte Auslieferungspakete (`portal-v1.tar.gz`, …), nie überschreiben
- `tests/` – pytest-Suite, läuft offline gegen eine Wegwerf-DB (siehe „Tests")
- `scripts/` – Werkzeuge gegen das LAUFENDE Portal, ebenfalls von diesem
  Rechner aus. `live_pruefung.py` ruft jede App eines Nutzers über HTTPS auf
  und legt dafür **eine** Sitzung an, die es im `finally` wieder löscht –
  nie wieder ad hoc mit `curl` prüfen, das hat 808 nie ablaufende Zugänge
  in der Datenbank hinterlassen (siehe `journal.md`, 08.08.2026)
- `.claude/` – aktive Berechtigungen und Guardrail-Hook, **nicht ändern**

## Wünsche abschließen

Das Werkstatt-Backlog ist die Auftragsliste. Ein Wunsch gilt erst als fertig,
wenn er im Container abgehakt ist – nicht schon, wenn der Code läuft:

```bash
docker exec portal python manage.py wunsch_erledigt <id> "was genau umgesetzt wurde" [tokens]
docker exec portal python manage.py wunsch_aktion <id> frage "Rückfrage an Andi"
docker exec portal python manage.py wunsch_neu <app> "<titel>" "<text>"
```

- Das **zweite Argument** (`umsetzung`) ist Pflichtstoff, nicht Kür: es
  landet in der Detailansicht der Werkstatt-App und ist das, was Andi später
  liest. Über die Web-UI lässt es sich nicht setzen.
- Das **dritte Argument** ist der Tokenverbrauch der Umsetzung – **nachher**
  eingetragen, nicht vorab geschätzt. `NULL` heißt „nicht erfasst", `0` heißt
  „wirklich null".
- **Rückfragen gehören an den Wunsch**, nicht nur in den Chat:
  `wunsch_aktion <id> frage "…"` schickt denselben Push wie die Oberfläche.
- `wunsch_neu` legt bewusst **nie** eine Priorität an – der stündliche Lauf
  (#157) arbeitet alles ab, was eine Priorität außer `zurueckgestellt` trägt;
  ein Befehl, der beides könnte, würde sich selbst beauftragen.

## Gitignore

`.gitignore` ist die einzige Ausschlussdatei im Repo und aktiv. (Frühere
Fassungen dieser Datei erwähnten eine zweite Datei `gitignore` im Repo-Root,
die synchron zu halten sei – die gibt es nicht mehr.)
