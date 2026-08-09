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

Wenn `server.md` und `journal.md` noch nicht existieren: erste Sitzung.
Am Ende von Meilenstein 1 anlegen.

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

# Paket ausliefern (von diesem Rechner aus)
scp -P 2222 deploy/portal-vN.tar.gz claude@10.0.0.100:/srv/familienportal/

# Zertifikat prüfen
openssl s_client -connect portal.16schwaben.de:443 -servername portal.16schwaben.de </dev/null 2>/dev/null | openssl x509 -noout -dates

# E2E-Tests (ad hoc mit Playwright, von diesem Rechner aus – tests/ ist aktuell
# nur ein leeres Verzeichnis, es existiert noch keine feste Suite)
python -m playwright test tests/

# manage.py im Container – Nutzer/Apps/Grants anlegen, Backlog einsehen
docker exec portal python manage.py listusers
docker exec portal python manage.py backlog
```

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
- Jedes echte (nicht reversible) Löschen fragt vorher per `confirm()` nach
  (`|tojson|forceescape` im `onsubmit`-Attribut, siehe `server.md`
  „Sicherheitskonventionen"); reversible Toggles (aktiv/inaktiv, Grant-Entzug)
  brauchen keine Abfrage.

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
- `tests/` – Playwright/pytest-Tests, laufen von diesem Rechner aus
- `scripts/` – Werkzeuge gegen das LAUFENDE Portal, ebenfalls von diesem
  Rechner aus. `live_pruefung.py` ruft jede App eines Nutzers über HTTPS auf
  und legt dafür **eine** Sitzung an, die es im `finally` wieder löscht –
  nie wieder ad hoc mit `curl` prüfen, das hat 808 nie ablaufende Zugänge
  in der Datenbank hinterlassen (siehe `journal.md`, 08.08.2026)
- `.claude/` – aktive Berechtigungen und Guardrail-Hook, **nicht ändern**

## Gitignore

`.gitignore` ist bereits aktiv (aus `gitignore` im Repo-Root übernommen).
Bei Änderungen an den Ausschlussregeln beide Dateien synchron halten.
