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

`SECURITY_REVIEW.md` liegt ebenfalls im Root, steht aber **in `.gitignore`**
und fehlt deshalb nach einem frischen Klon – er ist eine Anleitung, solange
Findings offen sind (Entscheidung von Andi, 11.08.2026). Wenn er da ist:
vor Sicherheitsarbeiten hineinsehen.

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

**Ein Branch: `main`. Keine Worktrees, keine Feature-Branches, keine Pull
Requests** (Andi, 05.09.2026). Es entwickelt immer nur eine Session, nicht
mehrere Agents nebeneinander – Isolation bringt hier nichts, sie erzeugt nur
Branches, die Andi selbst pullen und mergen muss. Das gilt ausdrücklich auch
für Hintergrund- und Cron-Läufe (#157): Am 31.08. und 01.09.2026 hatten zwei
Läufe von sich aus `EnterWorktree` aufgerufen („Pflicht für Edits in diesem
Hintergrund-Job") und je einen `worktree-*`-Branch samt PR hinterlassen.
Deshalb ist `EnterWorktree` in `.claude/settings.json` gesperrt; wer eine
solche Vorgabe im Auftragstext sieht, ignoriert sie und arbeitet direkt auf
`main`. Releases wären später Tags auf `main`, kein zweiter Branch.

„Implementiere alle Wünsche" heißt: **alle außer den mit Priorität
`zurueckgestellt` markierten** (siehe Docstring in `05_werkstatt_app.py`).
Deren Priorität ändert ausschließlich ein Admin manuell – nie automatisiert,
auch nicht im Rahmen eines Sammel-Auftrags.

## Sitzungsstart: Stundenlauf (#157) prüfen und ggf. neu anlegen

Der stündliche Wunsch-Durchlauf läuft als **session-gebundener** Cron-Job
(CronCreate, stündlich um :23, max. 7 Tage) und stirbt mit jedem
Sitzungsende bzw. Rechner-Neustart. Deshalb am Anfang jeder neuen Session
**ohne Aufforderung**:

1. Mit `CronList` prüfen, ob der Lauf existiert.
2. Fehlt er: neu anlegen mit dem **wörtlichen Auftragstext** aus
   `journal.md`, Eintrag vom 13.08.2026 („Stundenlauf wieder an") – nicht
   aus der Beschreibung rekonstruieren.
3. Danach sofort einen Testlauf von `scripts/wunsch_lauf_check.py` machen
   (siehe „Prüfung gegen das laufende Portal"), ob Arbeit ansteht.

Achtung: `CronList` sieht nur die **eigene** Session. Laufen absichtlich
mehrere Claude-Sessions parallel, darf nur die Haupt-Session den Lauf
halten – sonst arbeiten zwei Läufe dieselben Wünsche doppelt ab. Im
Zweifel Andi fragen.

Konkret nachsehen, bevor ein zweiter Lauf entsteht: `git worktree list`
zeigt liegengebliebene Worktrees, `.git/worktrees/<name>/locked` nennt die
PID der Session, die ihn hält, und `tasklist //FI "PID eq <n>"` (Git Bash)
sagt, ob die noch lebt. Lebt sie, hält sie vermutlich auch den Stundenlauf –
dann **nicht** neu anlegen, sondern Andi bitten, die alte Session zu beenden
(05.09.2026: Session 20164 im Worktree `stundenlauf-doku`).

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

`manage.py` kennt 18 Befehle (u. a. `createadmin`, `adduser`, `addapp`,
`grant`, `listapps`, `listki`, `ki_modell`, `ki_stimme`, `listpush`,
`testpush`, dazu die Wunsch-Befehle weiter unten). Ein Aufruf ohne Argumente
listet sie; die kommentierte Fassung steht in `server.md`, Abschnitt
„manage.py – Wichtige Befehle".

Auslieferung ist ein Dreischritt (Paket bauen → hochladen → entpacken +
`--build`), die vollständige Fassung mit allen `--exclude` steht in
`server.md`, Abschnitt „Deployment-Ablauf". **Zu jedem Deploy gehört danach
das Aufräumen** – jeder `--build` lässt das vorherige Image ungetaggt zurück
(Andi, 31.08.2026: 151 Stück in Portainer):

```bash
ssh -p 2222 claude@10.0.0.100 "docker image prune -f --filter 'until=72h' && docker builder prune -f --filter 'until=72h'"
```

Bewusst ohne `-a` (nur ungetaggte, fremde Stacks bleiben unberührt); `system`/
`volume`/`network prune` bleiben tabu, der Guardrail blockiert sie ohnehin. Zwei Punkte, die dort leicht
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

# Alles (2068 Tests, gut eine Minute)
.venv/Scripts/python -m pytest tests/ -q

# Eine Datei, ein einzelner Test, ein Muster über alle Dateien
.venv/Scripts/python -m pytest tests/test_grant.py -q
.venv/Scripts/python -m pytest tests/test_grant.py::test_token_gilt_nur_fuer_seine_app -q
.venv/Scripts/python -m pytest tests/ -k kontingent -q
```

Werkzeug steht bewusst nur in `requirements-dev.txt` (`pytest`, `pip-audit`,
`ruff`, `python-barcode` – letzteres nur zum *Erzeugen* eines Testbarcodes,
gelesen wird im Betrieb mit `zxing-cpp`); `src/requirements.txt` beschreibt
die Laufzeit und ist exakt gepinnt (Wunsch #135) – dort nichts Test-Werkzeug
hineinschreiben.

**Lint** (ruff, eingeführt 31.08.2026 – journal.md: damals 242 Funde behoben):

```bash
.venv/Scripts/python -m ruff check src/ util/ tests/ scripts/
```

Konfiguration in `ruff.toml` im Repo-Root. Die dortigen `ignore`-Einträge
sind bewusst und jeweils begründet – sie decken dokumentierte
Projektkonventionen ab (nummerierte Modulnamen, breite excepts in
Migrationen/Threads, die eigene Zeit-Konvention). Nichts davon „aufräumen",
und neue Regeln nur ignorieren, wenn eine dokumentierte Konvention
dagegensteht, nicht weil sie lästig sind.

**CVE-Abgleich gegen den echten Produktionsstand**, nicht gegen die lokale
`.venv` – die kann abweichen:

```bash
ssh -p 2222 claude@10.0.0.100 "docker exec portal pip freeze" > freeze.txt
.venv/Scripts/python -m pip_audit -r freeze.txt
```

**Zwei Fallen, die einen Test nicht rot machen, sondern unzuverlässig:**

- **Neue Tabelle?** `tests/conftest.py` leert vor jedem Test alles außer der
  Menge `BLEIBT`. Eine neue **Seed**-Tabelle (Stammdaten aus `_init_db()`)
  muss dort eingetragen werden – sonst fehlen die Stammdaten, und das schlägt
  sofort und laut fehl, was die richtige Fehlerrichtung ist. Eine normale
  Tabelle darf dort **nicht** stehen: sonst läuft ihr Bestand still über alle
  Tests hinweg mit. Genau dieser Fehler ist dreimal passiert (#145 Geburtstage,
  #161 Zählung je Wunsch, #162 `UNIQUE(tag, mahlzeit)` im Essensplan), immer
  weil die Tabelle nicht per `ON DELETE CASCADE` am Nutzer hängt.
- **Neuer Hintergrund-Thread?** Er braucht einen eigenen Schalter in
  `app.py`, und `conftest.py` muss ihn auf `0` setzen – wie
  `GEBURTSTAGS_ERINNERUNGEN` (#145) und `KI_GUTHABEN_WACHT` (#183). Ein Thread,
  der nebenher in dieselbe SQLite-Datei schreibt, lässt die Fixtures mit
  „database is locked" auflaufen. Dasselbe gilt für Modul-globalen Zustand:
  `rate_ueberschritten()` hält seine Treffer in einem Dict in `teile.kern`,
  das über die **ganze** Testsitzung bestehen bliebe – `conftest.py` setzt es
  darum per `autouse`-Fixture zurück (#207).

**Ein großer Teil der Suite sind Konventions-Wächter, keine Funktionstests.**
`test_tippflaeche.py`, `test_aria_labels.py`, `test_loeschen_symbol.py`,
`test_kopfleiste.py`, `test_emoji.py`, `test_csp.py`,
`test_formular_labels.py`, `test_ueberschriften.py`, `test_farbkontrast.py`,
`test_interaktion.py`, `test_arbeitet_anzeige.py`,
`test_verteiler_argumente.py`, `test_darkmode.py`, `test_hilfe_kapitel.py`
und `test_kopfzeile_bleibt.py` lesen die Vorlagen im Quelltext und schlagen
an, wenn eine neue Vorlage gegen eine der UI-Konventionen weiter unten
verstößt. Drei weitere wächtern nicht Vorlagen, sondern Struktur:
`test_routen_inventar.py` (jede ändernde Route braucht eine Regel mit
`<token>` im Pfad, siehe „Zugangsmodell"), `test_seiten_erreichbar.py`
(Rauchtest, ruft jede GET-Seite mit `<token>` als einziger Variable auf)
und `test_log_grenzen.py` (jeder Dienst in `docker-compose.yml` braucht
`logging:` mit Obergrenze). Schlägt einer davon an, ist die Vorlage bzw. der
Code falsch, nicht der Test. Wer einen neuen Wächter schreibt: vorher
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

Das zweite Werkzeug beantwortet die Frage „hat der stündliche Lauf (#157)
gerade etwas zu tun?". Es läuft **nicht hier**, sondern im Container, und wird
per stdin dorthin geschoben, damit keine Zeile SQL durch zwei
Anführungszeichen-Ebenen muss:

```bash
ssh -p 2222 claude@10.0.0.100 "docker exec -i portal python -" < scripts/wunsch_lauf_check.py
```

Nur lesend, drei Listen: **ANTWORTEN** (Andi hat auf eine Rückfrage geantwortet
– hat Vorrang, hier wartet jemand), **FREIGEGEBEN** (offen, Priorität gesetzt
und nicht `zurueckgestellt`; Wünsche ohne Priorität sind *nicht* freigegeben),
**WARTET** (Rückfrage gestellt, noch keine Antwort – nur zur Information, damit
dieselbe Frage nicht zweimal gestellt wird). Sind alle drei Zähler 0, ist der
Lauf fertig und darf nichts weiter tun – ohne diese Regel kämen 24
Fortschrittsberichte am Tag heraus (journal.md, 08.08.2026).

## Architektur (Überblick)

Stack `familienportal` mit drei Containern auf `home02`:

| Container | Rolle |
|-----------|-------|
| `portal`  | Python 3.12 + Flask + Gunicorn (1 Worker, Threads), SQLite unter `/srv/familienportal/data` |
| `caddy`   | TLS-Terminierung, Zertifikat aus Volume `iobroker-certs` (read-only), kein ACME |
| `util`    | `util/scheduler.py` – schlichte Python-Schleife im Minutentakt, kein cron/supercronic: stündlicher SQLite-Snapshot, 03:00 Backup aufs NAS (tar über SSH-Pipe), 04:00 Zertifikats-Watcher |

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
freier Nummer, kein Umbau von `app.py`.

**Modulübergreifende Importe brauchen einen Alias in `teile/__init__.py`.**
Ein führendes `0N_` ist kein gültiger Python-Modulname, `from teile.16_vokabeln
import …` geht schlicht nicht. Darum registriert `teile/__init__.py` die
Module, die andere brauchen, zusätzlich unter einem sprechenden Namen in
`sys.modules`: `teile.kern`, `teile.todo` (#90), `teile.rezepte` (#184),
`teile.werkstatt` (#187), `teile.werkstatt_app`, `teile.vokabeln` (#194). Wer
aus Modul A eine Funktion von Modul B braucht, trägt B dort ein – und zwar
**statt** die Funktion zu kopieren: jeder dieser Aliase existiert, weil ein
Duplikat sonst irgendwann auseinandergelaufen wäre.

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
- **Zeit:** `heute_lokal()`, `utc_zu_lokal()`, `utc_zu_lokal_datum()` –
  gespeichert wird UTC, angezeigt `Europe/Berlin`. Nie ein nacktes
  `datetime.now()` in eine Vorlage.
- **Netz:** `client_ip()` (wertet `X-Forwarded-For` so aus, dass die Ratenbremse
  nicht darüber umgangen werden kann – Wunsch #210),
  `ist_oeffentliche_url()`/`ip_ist_oeffentlich()` (SSRF-Riegel, u. a. beim
  Push-Abo), `rate_ueberschritten()` für jede neue Ratenbremse.

**Zugangsmodell.** Adressen tragen den Token im Pfad: `/p/<token>` für die
persönliche Startseite, `/a/<slug>/<token>/` für eine App. In der Datenbank
steht der Token **verschlüsselt** (`TOKEN_KEY`, Wunsch #129); gefunden wird er
über `token_lookup()`, aufgelöst über `grant(token, slug)`. Daraus folgt der
Satz, der in `.env.example` steht und sonst niemand liest: **ohne `TOKEN_KEY`
kommt niemand mehr ins Portal – auch ein wiederhergestelltes `/data`-Backup
nützt dann nichts**, denn das NAS-Backup sichert nur `/data`, die `.env` liegt
bewusst nicht darin. Seit #140 Stufe 4 hat **jede Route zwei Regeln** am
selben Endpunkt: eine mit `<token>` im Pfad und eine token-freie
Zwillingsregel, die über das Sitzungs-Cookie autorisiert (`19_sitzung.py`).
Eine neue ändernde Route (POST/PUT/PATCH/DELETE) ohne Token-Regel lässt
`tests/test_routen_inventar.py` anschlagen; die Ausnahmen dort sind
abschließend.

**KI-Schicht.** Jede KI-Nutzung läuft über `ki_anfrage()` bzw.
`ki_text_zu_sprache()` in `00_kern.py` – nie ein eigener HTTP-Aufruf an
OpenRouter. Dort hängt das Nutzer-Kontingent daran, und zwar **atomar
reserviert**: `_kontingent_reservieren()` vor der Anfrage,
`_kontingent_freigeben()` bei Fehlschlag, `_kontingent_korrigieren()` auf den
echten Verbrauch danach (`tests/test_ki_kontingent_atomar.py`). Modell und
Stimme kommen je Zweck aus der Datenbank (`ki_modell_fuer()`,
`ki_stimme_fuer()`, gesetzt per `manage.py ki_modell` / `ki_stimme`), nicht aus
dem Code. `ki_anfrage()` nimmt neben `bilder` auch `audio=(format, b64)`
(#258); steht für den Zweck ein Anbieter in `ki_konfiguration.anbieter`, geht
die Anfrage ohne Fallback nur dorthin (`ki_anbieter_fuer()`) – so ist die
Aussprache-Bewertung auf Mistrals EU-Endpunkt festgenagelt. `24_ki_budget.py`
sieht stündlich aufs OpenRouter-Guthaben und legt bei ≤ 1,00 USD **eine**
Aufgabe samt Push für den Admin an (#183).

**Umbauten laufen in Stufen, jede Stufe ist eine Zeile in der `.env`.**
`SITZUNG_AUSSTELLEN`, `CSRF_MODUS`, `SITZUNG_KONSUMIEREN`, `TOKENFREIE_URLS`
(alle #140) und `CSP_MODUS` (#142). Die Riegel kennen `aus | beobachten |
scharf` – „beobachten" protokolliert nur und blockiert nichts, damit sich vor
dem Scharfschalten prüfen lässt, ob echte Anfragen fälschlich auffallen
(`docker compose logs portal | grep CSRF-Verdacht` bzw. `CSP-Verstoss`).
Zurücknehmen einer Stufe ist damit **eine Zeile plus `docker compose up -d
portal` – kein Rebuild, kein Paket, keine entfernte Route**. Implementiert in
`19_sitzung.py`, `20_csrf.py`, `21_csp.py`; Vollreferenz mit allen
Abhängigkeiten in `.env.example`, der aktuell auf dem Server gesetzte Stand in
`server.md` („Umgebungsvariablen").

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
- **Jedes Formularfeld braucht eine programmatische Beschriftung** – `<label
  for>`, umschließendes `<label>` oder `aria-label`/`aria-labelledby`; ein
  Platzhalter zählt nicht, er verschwindet beim Tippen (Wunsch #246,
  `tests/test_formular_labels.py`).
- **Überschriften sind echte `h1`/`h2`**: der Seitentitel ist ein `h1` (Klasse
  `nav-title`, Optik unverändert), Inhalts-Abschnitte sind `h2` – kein neues
  `<div class="nav-title">` (Wunsch #247, `tests/test_ueberschriften.py`).
  Filter-Etiketten in Filterkarten bleiben bewusst `div`s.
- **Umschalter ohne Seitensprung** (Wunsch #171): `data-fetch="fn"` am
  Formular, serverseitig `antwort_oder_weiter()`. Aber nur, wenn der
  Umschalter die Listen-Reihenfolge NICHT ändert – sonst Weiterleitung mit
  `#anker` auf die eigene Karte.
- **Lange Vorgänge:** Formulare, deren Absenden spürbar dauert (KI-Anfrage),
  tragen `data-arbeitet="Wird gelesen …"` – der Verteiler in `base.html`
  deaktiviert und beschriftet den Knopf um (Wunsch #176).
- **Klick-Verteiler** (Wunsch #200, `tests/test_verteiler_argumente.py`):
  Knöpfe rufen ihre Funktion über `data-klick="fn"` auf, Werte kommen aus
  `data-args='[…]'` (JSON). Die Funktion bekommt **erst die Werte aus
  `data-args`, dann das Element, dann das Ereignis** – ein erster Parameter,
  der wie ein Element benutzt wird, ist falsch, wenn `data-args` gesetzt ist.
- **Interaktions-Ebene** (Wunsch #248, `tests/test_interaktion.py`), alles
  zentral in `base.html`: Ein Knopf, der ein Panel auf- und zuklappt, trägt
  `data-panel="<id>"` (`aufzuSync()` hält daraus `aria-expanded` aktuell).
  Ein neues Overlay läuft über `dialogFuehrung()` (Fokus-Falle, Escape,
  Fokus-Rückgabe), nie über nacktes `classList.toggle`. Ziehbare Listen über
  `ziehSortierung()`, das die Tastaturbedienung mitbringt – eine eigene
  Zieh-Fassung muss `tastaturSortierung()` selbst aufrufen. Emoji sind nach
  `twemoji.parse()` stumm (`alt=""`), außer unter einem Element mit
  `data-emoji-alt` (App-Kacheln, Nutzertext).
- **Dunkelmodus** (Wunsch #172, `tests/test_darkmode.py`): die dunklen
  Farbwerte stehen in `base.html` **einmal** in der Jinja-Variablen
  `dunkle_werte` und werden für `body.dark` und für `body.auto` (nur innerhalb
  `@media (prefers-color-scheme: dark)`) ausgegeben. Keinen zweiten,
  getippten Block anlegen – zwei Blöcke laufen unbemerkt auseinander.
- **Vier globale Regeln in `base.html`** (Tippfläche #169, Feldschrift ≥16px
  #170, `.main` max-width 720px #173, `:focus-visible`-Ring #174) – keine
  Vorlage darf sie überschreiben, `tests/test_tippflaeche.py` wächtert alle
  vier. Merke zur Spezifität: eine Klassenregel in einer Vorlage schlägt die
  globale Element-Regel immer, unabhängig von der Reihenfolge.
- **Tippfläche:** jeder `button` hat via `base.html` mindestens 44×44 px
  unsichtbare Trefferfläche (Wunsch #169). Nie ein eigenes
  `button::before`/`::after` in einer Vorlage definieren –
  `tests/test_tippflaeche.py` wächtert das. **Als Link gebaute Knöpfe**
  (Pills, Bearbeiten-Links) bekommen zusätzlich die Klasse `knopf` –
  dieselbe Regel, gleicher Wächter (Wunsch #239).
- **Farben mit Kontrastgarantie** (Wunsch #237, `tests/test_farbkontrast.py`):
  Text nie in `var(--farbe)` – immer `var(--farbe-kontrast)` (im Dunkelmodus
  automatisch aufgehellt). Weiße Schrift nie auf `var(--farbe)` – immer auf
  `var(--farbe-band)`. Grün/Rot als Text über `var(--gruen-text)`/
  `var(--rot-text)`, nie roh `#34c759`/`#ff3b30`. Text in der Farbe einer
  PERSON über die Klasse `farbtext` mit `--ft-dunkel`/`--ft-hell` am Element
  (Inline-Farben können den Dunkelmodus nicht mitmachen). Serverseitig
  rechnen `farbe_kontrast()`/`farbe_kontrast_hell()` (00_kern, in jeder
  Vorlage verfügbar) beliebige Nutzerfarben kontrastfest.
- **Schrift nie unter 12px** (Wunsch #238) – auch für Badges, Etiketten und
  Achsenbeschriftungen; `tests/test_farbkontrast.py` wächtert alle Vorlagen.
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
  Ein Kapitel ist seit Wunsch #242 ein `<details class="section"
  id="kapitel-N">` (eingeklappt, das Inhaltsverzeichnis klappt per Skript
  auf; `tests/test_hilfe_kapitel.py` wächtert das Muster). Gehört zum
  „dokumentieren"-Schritt der Arbeitsweise oben, genauso verbindlich wie
  `journal.md`/`server.md`.

**Templates:** liegen in `src/teile/templates/` (nicht `src/templates/` –
`app.py` setzt `template_folder="teile/templates"`), je App eine eigene
`.html`-Datei mit Inline-CSS/JS. `base.html` liefert das gemeinsame
Grundlayout (⌂-Include, Hamburger-Menü mit Dark Mode/Hilfe/✨,
Service-Worker-Registrierung). Statische Dateien unter `src/static/`
(`sw.js`, `manifest.json`, lokal gebündeltes `twemoji`). Kein Build-Schritt,
kein gemeinsames Frontend-Framework – JS-Bibliotheken werden lokal
gebündelt, nie von einem CDN geladen. Die Konventions-Wächter in `tests/`
lesen genau diesen Ordner per Glob – eine Vorlage an anderer Stelle würde
von keinem Wächter geprüft.

Den aktuellen Stand von DB-Schema, App-Slugs und Modulen (mit Kurzbeschreibung
je Datei) pflegt `server.md` – dort nachsehen statt hier zu duplizieren,
da sich das mit jeder Auslieferung ändert.

## Guardrails und Berechtigungen

`settings.json` und `guardrails.sh` liegen im Projekt-Root als Quelle und
zusätzlich als **aktive Kopie in `.claude/`** – erst dort greifen sie:

- `settings.json`: deny-Liste für gefährliche lokale Befehle (sudo, apt,
  docker network rm etc.) und für das Werkzeug `EnterWorktree` (siehe
  „Arbeitsweise"), eine ask-Liste (`docker compose down`, `docker rm/stop`,
  `docker network create`) und eine allow-Liste für häufige Befehle. `git
  push` steht seit 05.09.2026 in der allow-Liste: ask-Regeln fragen auch im
  Auto-Modus immer nach, und CLAUDE.md verlangt den Push nach jeder Session.
- `guardrails.sh`: PreToolUse-Hook auf `Bash`. Er liest die Nutzlast aus dem
  JSON und setzt dieselben Verbote durch – **auch wenn der Befehl erst per SSH
  auf `home02` landet**, denn präfixbasierte deny-Regeln greifen dort nicht,
  weil die Zeile mit `ssh` beginnt. Rückgabe: `0` = erlaubt, `2` = blockiert,
  stderr geht an Claude.

Werden die Vorlagen im Root geändert, müssen beide Kopien nachgezogen werden
(`.claude/guardrails.sh` zusätzlich `chmod +x`). `.claude/settings.local.json`
enthält nur eine gewachsene allow-Liste, keine Verbote – die Verbote stehen
ausschließlich in `.claude/settings.json`.

**Nicht ändern** – außer nach expliziter Absprache mit Andi.

## Verzeichnisse

- `src/` – Quellcode des Portals (wird nach `/srv/familienportal/src` ausgeliefert)
- `util/` – Quellcode des **zweiten Containers** mit eigenem `Dockerfile` und
  eigener `requirements.txt`: `scheduler.py` (Takt), `db_snapshot.py`
  (stündlicher SQLite-Snapshot), `backup.py` (tägliches Backup aufs NAS per
  tar+ssh), `cert_watcher.py`. Läuft im Bridge-Netz, ohne macvlan-IP.
- `deploy/` – versionierte Auslieferungspakete (`portal-v1.tar.gz`, …), nie überschreiben
- `tests/` – pytest-Suite, läuft offline gegen eine Wegwerf-DB (siehe „Tests")
- `scripts/` – Werkzeuge gegen das LAUFENDE Portal, ebenfalls von diesem
  Rechner aus. `live_pruefung.py` ruft jede App eines Nutzers über HTTPS auf
  und legt dafür **eine** Sitzung an, die es im `finally` wieder löscht –
  nie wieder ad hoc mit `curl` prüfen, das hat 808 nie ablaufende Zugänge
  in der Datenbank hinterlassen (siehe `journal.md`, 08.08.2026).
  `wunsch_lauf_check.py` beantwortet nur lesend, ob der stündliche Lauf gerade
  Arbeit hat (siehe „Prüfung gegen das laufende Portal").
- `docs/a11y/` – eingefrorene Kopien der AccessLint-Methodik (WCAG-EM,
  Prüf-Checkpoints; MIT) als Referenz für Hand-Reviews. Bewusst NUR die
  Dokumente übernommen – der zugehörige MCP-Server (`npx @latest`,
  ungepinnter Fremdcode) wurde nach Review verworfen (Andi, 31.08.2026).
- `.claude/` – aktive Berechtigungen und Guardrail-Hook (Kopien der
  Root-Vorlagen), **nicht ändern**. Ausnahme nach Absprache 31.08.2026:
  `.claude/skills/web-design-guidelines/` – UI-Review-Checkliste (Vercel,
  Regeln lokal eingefroren statt Laufzeit-Fetch; Details in dessen SKILL.md).
  Findings daraus werden Wünsche, nie Direktumbauten.

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
