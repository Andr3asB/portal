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

# E2E-Tests
pytest tests/ -v
# oder mit Playwright direkt:
python -m playwright test tests/
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
- `.claude/` – aktive Berechtigungen und Guardrail-Hook, **nicht ändern**

## Gitignore

Die Datei `gitignore` im Repo-Root muss als `.gitignore` im
Arbeitsverzeichnis aktiv sein. Falls noch nicht geschehen:
`cp gitignore .gitignore` (oder entsprechend unter Windows).
