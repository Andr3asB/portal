# Status quo: Aufgaben, Geholfen, Aufgabenplan

**Stand:** 19.09.2026, Repo `main` nach v262. Erstellt als Bestandsaufnahme für
eine geplante Überarbeitung der drei Apps. Dieses Dokument beschreibt **nur,
was ist** – keine Bewertung, keine Vorschläge. Wer die Überarbeitung übernimmt,
liest zuerst `CLAUDE.md` (Arbeitsweise, Konventionen, Wächter-Tests), dann
dieses Dokument, dann den Code.

## 1. Die drei Apps auf einen Blick

| App | Slug | Modul | Vorlagen | Kachel | Kurzbeschreibung (aus `apps`) |
|-----|------|-------|----------|--------|-------------------------------|
| Aufgaben | `todo` | `src/teile/04_todo.py` (807 Zeilen) | `todo.html`, `todo_teile.html`, `todo_kanban.html`, `todo_serien.html` | ✅ | Aufgabenliste |
| Geholfen | `geholfen` | `src/teile/06_geholfen.py` (417 Zeilen) | `geholfen.html`, `geholfen_aufgaben.html`, `geholfen_uebersicht.html`, `geholfen_verlauf.html` | 🙋 | Geholfen-Protokoll |
| Aufgabenplan | `kinderplan` | `src/teile/13_kinderplan.py` (388 Zeilen) | `kinderplan.html` | 🗓️ | Wiederkehrende Aufgaben wochentagsweise planen |

Alle drei sind in der `apps`-Tabelle als **nicht offline-fähig** eingetragen
(`offline_faehig=0`; der Service Worker cached besuchte Seiten trotzdem, zeigt
offline also höchstens einen alten Stand). Keine der drei wird per
`_auto_grant_all()` automatisch vergeben – der Zugang wird je Nutzer in der
Verwaltung erteilt. Live-Stand (aggregiert, 19.09.2026): 4 Nutzer (1 Admin mit
Rolle `eltern`, 1 `eltern`, 2 `kind`), jede der drei Apps hat 4 Grants;
28 Todos (18 erledigt), 2 Serien, 28 Geholfen-Einträge bei 9 aktiven
Geholfen-Aufgaben, 2 Aufgabenplan-Einträge.

**Verflechtung:** Der Aufgabenplan importiert `serie_einsortieren` und
`serien_pool_fuer_tag` aus der Todo-App über den Alias `teile.todo`
(`src/teile/__init__.py`, Wunsch #90) – wiederkehrende Aufgaben werden EINMAL
in der Todo-App als Serie definiert und erscheinen daraus sowohl in der
Aufgabenliste als auch im Aufgabenplan. Geholfen ist datenseitig unabhängig
von beiden. Details in den App-Abschnitten.

## 2. Gemeinsamer Rahmen, auf dem alle drei Apps aufsetzen

Diese Dinge stehen nicht in den App-Modulen, bestimmen aber ihr Verhalten.
Vollständig in `CLAUDE.md` und `server.md` („Sicherheitskonventionen",
„Globale UI-Regeln in base.html").

### 2.1 Zugang und Rollen

- Jede Route beginnt mit `grant(token, APP)` bzw. dem modullokalen
  `_user(token)`; ohne Grant für genau diese App gibt es 403. Jede Route hat
  zwei Regeln: `/a/<slug>/<token>/…` und die token-freie Zwillingsregel, die
  über das Sitzungs-Cookie autorisiert (`19_sitzung.py`).
- Nutzer haben eine Rolle (`users.rolle`: `eltern`, `kind`, `gast`) und ein
  `is_admin`-Flag. Die Apps prüfen Aufsichtsrechte **positiv**
  (`is_admin or rolle == 'eltern'`); `gast` bekommt nirgends implizit Rechte.
- Jeder Nutzer hat eine Farbe (`users.farbe`); Personen werden in allen drei
  Apps über diese Farbe dargestellt (Chips, Streifen, Punkte), im Dunkelmodus
  über `farbe_kontrast()`/`farbtext`-Klasse kontrastsicher.
- Ändernde Anfragen laufen durch den CSRF-Riegel (`20_csrf.py`, Modus
  `scharf`), die CSP ist scharf mit Nonce (`21_csp.py`) – Inline-Skripte
  brauchen `{{ csp_nonce }}`, Inline-Handler (`onclick` …) sind verboten.

### 2.2 UI-Konventionen aus `base.html` (verbindlich, von Tests gewächtert)

- **Verteiler:** Knöpfe rufen ihre Funktion über `data-klick="fn"` mit
  Argumenten aus `data-args='[…]'` (JSON) auf; die Funktion bekommt erst die
  Argumente, dann das Element, dann das Ereignis. Formulare mit
  `data-fetch="fn"` senden ohne Seitensprung, serverseitig antwortet
  `antwort_oder_weiter()` je nach Anfrage mit JSON oder Redirect. Echte
  Löschungen fragen per `data-bestaetigen="…"` nach; reversible Toggles nicht.
  Lange Vorgänge tragen `data-arbeitet="…"`.
- **Interaktions-Ebene:** auf-/zuklappbare Panels über `data-panel="<id>"`
  (`aufzuSync()` pflegt `aria-expanded`), Overlays über `dialogFuehrung()`
  (Fokusfalle, Escape), ziehbare Listen über `ziehSortierung()` inklusive
  Tastaturbedienung.
- **Layout-Regeln:** Aktionsknöpfe oben im `<main>` als `.top-aktionen`, nie
  im farbigen Kopfband; jede Unterseite hat einen eigenen Zurück-Link; `h1`
  ist der Seitentitel (`nav-title`), Abschnitte sind `h2`; Tippfläche mindestens
  44×44 px; Schrift nie unter 12 px; Feldschrift ≥ 16 px; `.main` max. 720 px;
  Löschen trägt 🗑️; Icon-Knöpfe haben `aria-label`; jedes Formularfeld eine
  programmatische Beschriftung; Emoji werden per Twemoji gerendert und sind
  stumm, außer unter `data-emoji-alt`.
- **Dunkelmodus:** Farbwerte einmal in `base.html` (`dunkle_werte`), Text nie
  in `var(--farbe)`, sondern `var(--farbe-kontrast)`; Grün/Rot als Text über
  `var(--gruen-text)`/`var(--rot-text)`.
- **Umschalter ohne Seitensprung** nur, wenn die Listenreihenfolge gleich
  bleibt; sonst Redirect mit `#anker` auf die eigene Karte.

### 2.3 Zeit, Push, Daten

- Gespeichert wird UTC (`datetime('now')` in SQLite), gerechnet und angezeigt
  wird Familienzeit `Europe/Berlin` über `heute_lokal()`, `utc_zu_lokal()`,
  `utc_zu_lokal_datum()` aus `00_kern.py`. Der Container läuft in UTC; zwischen
  Mitternacht und 02:00 liefert ein nacktes `date.today()` den Vortag –
  deshalb die Helfer. `13_kinderplan.py` hält noch eine eigene `_TZ`-Konstante
  (Altbestand, in `server.md` als solcher benannt).
- Push-Benachrichtigungen gehen ausschließlich über `push_send(user_id, titel,
  text, app_slug, url)` aus `00_kern.py`: eigener Thread, eigene DB-Verbindung,
  VAPID, `timeout=10`, an alle Push-Abos des Nutzers. Tabelle `push_abos`.
- Ganzzahlen aus Nutzereingaben nur über `to_int()`; Farben nur über
  `_clean_farbe()`; im JS `textContent`/`createElement` statt `innerHTML` für
  Nutzerdaten.
- Datenbank: SQLite im WAL-Modus, Schema und Migrationen zentral in
  `00_kern.py` (`SCHEMA` + `_init_db()` mit idempotenten `ALTER TABLE`).
  Tabellen, die nicht per `ON DELETE CASCADE` am Nutzer hängen, müssen in
  `tests/conftest.py` beachtet werden (Menge `BLEIBT` nur für Seed-Tabellen).

### 2.4 Arbeitsweise für die Überarbeitung (aus `CLAUDE.md`, nur zur Orientierung)

Bauen → ausliefern (`python scripts/paket_bauen.py`, `scp`, `tar xzf`,
`docker compose up -d --build`) → von diesem Rechner aus end-to-end testen
(`scripts/live_pruefung.py`) → dokumentieren (`journal.md`, `server.md`,
Hilfe-App). Ein Branch `main`, keine Worktrees. Neue Funktionen bekommen ein
Hilfe-Kapitel (`<details class="section" id="kapitel-N">`). Die Test-Suite
(2.590 Tests, `pytest tests/ -q`) enthält viele Konventions-Wächter, die bei
neuen Vorlagen anschlagen; `ruff check src/ util/ tests/ scripts/` ist
Pflicht. Wünsche werden über die Werkstatt-App bzw. `manage.py wunsch_neu`
erfasst; die Priorität setzt nur ein Mensch.

---
## App „Aufgaben" (todo)

Stand: 19.09.2026, Quelltext `src/teile/04_todo.py` (807 Zeilen, Blueprint `todo_app`), Vorlagen `todo.html`, `todo_teile.html`, `todo_kanban.html`, `todo_serien.html` in `src/teile/templates/`, Schema in `src/teile/00_kern.py`. App-Slug `todo`, Anzeigename „Aufgaben", Emoji ✅, Beschreibung „Aufgabenliste" (Seed `_CORE_APPS` in `00_kern.py`; ursprünglich hieß die App „Todos", Wunsch #11 benannte sie um – die Migration `UPDATE apps SET name='Aufgaben' WHERE slug='todo' AND name='Todos'` zieht das nach). `offline_faehig` steht für `todo` auf dem Default 0.

### 1. Zweck und Zielgruppe

Laut Modul-Docstring: „Todo-App – Aufgaben anlegen, zuweisen, abhaken. URL-Präfix: `/a/todo/<token>/`. Andere Module können `todos_neu()` aufrufen, um programmatisch Todos zu erstellen." Die App ist eine gemeinsame Aufgabenliste der Familie. Zielgruppe sind alle Nutzerrollen des Portals (`eltern`, `kind`, `gast`, dazu das `is_admin`-Flag): jeder mit einem Grant für `todo` darf Aufgaben anlegen; Erledigen ist je nach Rolle und Zuweisung eingeschränkt, Löschen ist Eltern/Admin vorbehalten (Wunsch #10). Laut Hilfe-App (Kapitel „Die Apps" → Aufgaben) umfasst die App: Anlegen hinter „+ Neue Aufgabe", vier Status-Stufen Backlog/Offen/In Arbeit/Erledigt, Zielwahl „Für wen?" als Chip-Band (Ich, andere Personen mit Push-Benachrichtigung, Rollen Eltern/Kinder/Gäste, Alle, 🔒 Privat), Fälligkeit mit Uhrzeit, Bearbeiten aller Felder mit Verlauf früherer Textfassungen, wiederkehrende Vorlagen unter „🔁 Wiederkehrende Aufgaben" im ☰-Menü, Filter nach Benutzer/Status, und das Kanban-„Brett" als vollwertige Zweitansicht (eigenes Hilfe-Kapitel „📋 Aufgaben als Brett", `id="kapitel-24"`). Im Produktivbestand haben laut `server.md` alle vier Nutzer einen Grant auf `todo`.

### 2. Datenmodell

Alle Tabellen liegen in `SCHEMA` von `00_kern.py`; Zeitstempel sind UTC im SQLite-Format `YYYY-MM-DD HH:MM:SS` (`datetime('now')`).

**Tabelle `todos`** (Basis-Schema plus Migrationen)

| Spalte | Typ / Default | Bedeutung |
|---|---|---|
| `id` | INTEGER PRIMARY KEY | Kennung |
| `inhalt` | TEXT NOT NULL | Aufgabentext |
| `erstellt_von` | INTEGER NOT NULL, FK `users(id)` ON DELETE CASCADE | Ersteller; wird der Nutzer gelöscht, verschwinden seine Aufgaben |
| `zugewiesen_an` | INTEGER, FK `users(id)` ON DELETE SET NULL | Zielperson; NULL = „für mich"/niemand Bestimmtes bzw. Rollenziel |
| `privat` | INTEGER NOT NULL DEFAULT 0 | 1 = nur Ersteller, Zugewiesener sowie Eltern/Admin sehen die Aufgabe |
| `erledigt` | INTEGER NOT NULL DEFAULT 0 | Abhak-Flag; wird mit `status` synchron gehalten (1 genau bei `status='erledigt'`) |
| `erledigt_am` | TEXT | UTC-Zeitpunkt des Abhakens; NULL, sobald wieder zurückgesetzt |
| `erstellt` | TEXT NOT NULL DEFAULT datetime('now') | Anlagezeit UTC |
| `status` | TEXT NOT NULL DEFAULT 'offen' (Migration, Wunsch #20) | einer aus `STATUS_ORDER` |
| `zugewiesen_rollen` | TEXT (Migration, Wunsch #39) | kommagetrennte, sortierte Rollen (`eltern,kind`) oder Sentinel `alle`; exklusiv zu `zugewiesen_an` |
| `serie_id` | INTEGER, FK `todo_serien(id)` ON DELETE SET NULL (Migration, Wunsch #90) | gesetzt bei einer aus einer Vorlage erzeugten Instanz |
| `wochentag` | INTEGER (Migration, Wunsch #90) | totes Altfeld (0=Mo..6=So), nie mit Produktivdaten gefüllt, durch `plan_tag` ersetzt |
| `plan_tag` | TEXT (Migration, Wunsch #92) | ISO-Datum des Kalendertags, für den eine Serien-Instanz eingeplant ist; nur bei `serie_id` gesetzt |
| `position` | INTEGER NOT NULL DEFAULT 0 (Migration, Wunsch #224) | Reihenfolge innerhalb der Status-Spalte (= Priorität von Hand); je Status vergeben, nicht lückenlos |
| `faellig` | TEXT (Migration, Wunsch #260) | Fälligkeit als UTC `YYYY-MM-DD HH:MM:SS`; NULL = keine Frist |

Migrations-Nachlauf in `_init_db()`: `UPDATE todos SET status='erledigt' WHERE erledigt=1 AND status='offen'` (Ableitung des Status aus dem alten Flag, Wunsch #20). Alle `ALTER TABLE todos ADD COLUMN` laufen idempotent per try/except in einer Schleife.

**Statuswerte (`STATUS_ORDER`)**: `backlog` („Backlog"), `offen` („Offen"), `in_arbeit` („In Arbeit"), `erledigt` („Erledigt"). Neue Aufgaben mit direkter Personenzuweisung oder Leerwert starten in `offen`; neue Aufgaben mit Rollen- oder Alle-Ziel starten in `backlog` (Wunsch #39). Ein unbekannter Statuswert (Altbestand) wird auf dem Brett in der Spalte „Offen" gezeigt.

**Zielarten**: (a) Person – `zugewiesen_an` gesetzt, `zugewiesen_rollen` NULL; (b) Leerwert „Ich" – beide NULL (Formular schickt `zugewiesen_an=""`); (c) Rolle(n) – `zugewiesen_an` NULL, `zugewiesen_rollen` z. B. `kind` oder `eltern,gast`; (d) Alle – `zugewiesen_rollen='alle'`. Eine Aufgabe hat genau ein Ziel; Neu- und Bearbeiten-Route setzen jeweils beide Spalten neu.

**Tabelle `todo_serien`** (Wunsch #90)

| Spalte | Typ / Default | Bedeutung |
|---|---|---|
| `id` | INTEGER PRIMARY KEY | |
| `inhalt` | TEXT NOT NULL | Text der Vorlage, wird in jede Instanz kopiert |
| `wiederkehr_typ` | TEXT NOT NULL DEFAULT 'intervall' | `intervall` oder `wochentag` |
| `intervall_tage` | INTEGER | bei `intervall`: Abstand in Tagen (>0) |
| `fester_wochentag` | INTEGER | totes Altfeld (ein Wochentag 0–6), seit Wunsch #112 durch `feste_wochentage` ersetzt; `_wochentage_menge()` fällt noch darauf zurück |
| `feste_wochentage` | TEXT (Migration, Wunsch #112) | kommagetrennt, z. B. `1,3,5` (0=Mo..6=So) |
| `aktiv` | INTEGER NOT NULL DEFAULT 1 | 0 = pausiert, taucht in keinem Pool auf |
| `erstellt_von` | INTEGER, FK `users(id)` ON DELETE SET NULL | |
| `erstellt` | TEXT NOT NULL DEFAULT datetime('now') | |

Migration: `ALTER TABLE todo_serien ADD COLUMN feste_wochentage TEXT` plus Backfill `UPDATE todo_serien SET feste_wochentage = CAST(fester_wochentag AS TEXT) WHERE fester_wochentag IS NOT NULL AND feste_wochentage IS NULL`.

**Tabelle `todo_historie`** (Wunsch #19)

| Spalte | Typ / Default | Bedeutung |
|---|---|---|
| `id` | INTEGER PRIMARY KEY | |
| `todo_id` | INTEGER NOT NULL, FK `todos(id)` ON DELETE CASCADE | |
| `alter_inhalt` | TEXT NOT NULL | Text VOR der Änderung |
| `geaendert_von` | INTEGER, FK `users(id)` ON DELETE SET NULL | |
| `geaendert_am` | TEXT NOT NULL DEFAULT datetime('now') | |

Nur Textänderungen erzeugen einen Eintrag (in `bearbeiten()`, wenn `neuer_inhalt` nicht leer und ungleich `row["inhalt"]`); Änderungen an Ziel, Privat-Flag oder Fälligkeit werden nicht historisiert.

**Tabelle `todo_nutzer_ansicht`** (Wunsch #225): `user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE`, `ansicht TEXT NOT NULL` (`liste` oder `brett`). Fehlende Zeile bedeutet „Liste". Upsert per `ON CONFLICT(user_id) DO UPDATE`.

Im Test-Setup (`tests/conftest.py`) steht keine dieser Tabellen in `BLEIBT`; sie werden vor jedem Test geleert.

### 3. Rollen und Rechte

**Sehen (`_visible_todos(db, user)`)**: Admin (`is_admin`) oder Rolle `eltern` sehen alle Zeilen (auch fremde private), sortiert `erledigt ASC, erstellt DESC`. Alle anderen (kind, gast) bekommen zwei Abfragen: (1) SQL – Zeilen, bei denen `zugewiesen_an = uid` ODER `erstellt_von = uid` ODER (`zugewiesen_an IS NULL AND zugewiesen_rollen IS NULL AND privat = 0`, also unzugewiesene, nicht-private „Ich"-Aufgaben anderer), zusätzlich mit der Bedingung `privat = 0 OR erstellt_von = uid OR zugewiesen_an = uid`; (2) SQL – alle Rollen-/Alle-Zeilen anderer Ersteller (`zugewiesen_an IS NULL AND zugewiesen_rollen IS NOT NULL AND privat = 0 AND erstellt_von != uid`), die in Python per `_rolle_passt()` gefiltert und ohne Duplikate angehängt werden. Anschließend zwei stabile Python-Sortierungen: erst `erstellt` absteigend, dann `erledigt` aufsteigend. Der Kommentar begründet die Python-Filterung damit, dass die kommagetrennte Spalte nicht sauber in SQL zu matchen ist. Jede Zeile trägt zusätzlich `von_name`/`von_farbe` (Ersteller) und `fuer_name`/`fuer_farbe` (Zugewiesener) per LEFT JOIN auf `users`.

Folge für Kind/Gast: Eine an eine andere Person zugewiesene, nicht-private Aufgabe eines Dritten ist unsichtbar (Test `test_fremde_aufgabe_ist_fuer_ein_kind_ebenfalls_unsichtbar`). Ein privates Todo mit Rollenziel ist für Rollenmitglieder unsichtbar (`privat = 0` in der Rollenabfrage).

**`_rolle_passt(row, user)`**: True, wenn `zugewiesen_rollen == 'alle'` oder die Rolle des Nutzers in der kommagetrennten Liste steht; False bei leerem Feld.

**Erledigen/Status/Bearbeiten/Verschieben (`_darf_erledigen(user, row)`)**: True für Admin oder `eltern`; True für Ersteller oder Zugewiesenen; sonst True nur, wenn `zugewiesen_an IS NULL` UND `privat = 0` UND `_rolle_passt`. Die `privat`-Bedingung kam mit Wunsch #214 (Audit F-06): vorher war ein privates Todo mit Rollenziel unsichtbar, aber per geratener ID änderbar.

**Löschen (`_darf_loeschen(user)`)**: `is_admin` oder Rolle `eltern`. Gilt für Aufgaben und für Serien-Vorlagen (Aktion `loeschen` in `serien()`). Serien anlegen und pausieren darf jeder mit Grant.

**Sichtbarkeits-IDs (`_sichtbare_ids(db, user)`)**: Menge der IDs aus `_visible_todos` – bewusst keine zweite Abfrage, um Auseinanderlaufen zu vermeiden.

**404/403-Regel (Wunsch #288, Audit N-09)**: `set_status`, `bearbeiten` und `kanban_verschieben` antworten in dieser Reihenfolge: ID nicht vorhanden → 404; ID vorhanden, aber nicht in `_sichtbare_ids` → 404 (Unsichtbares bestätigt seine Existenz nicht); sichtbar, aber `_darf_erledigen` falsch → 403; ungültiger Status → 400. `loeschen()` prüft nur `_darf_loeschen` (403) und Existenz (404), keine Sichtbarkeit – Eltern/Admin sehen ohnehin alles.

**Umsortieren im Brett** ist ausdrücklich von `_darf_erledigen` entkoppelt: Positionen darf jeder setzen, der das Brett sieht; nur IDs aus `_sichtbare_ids` werden angefasst. Ein Spaltenwechsel (Statusänderung) verlangt `_darf_erledigen`.

**Vorlagen-Seite (Jinja)**: `todo.html` berechnet `ich_darf_erledigen` im Makro `todo_item` nach eigener Formel: `darf_loeschen or erstellt_von == user.id or zugewiesen_an == user.id or (not zugewiesen_an and rolle_passt)` – ohne `privat`-Prüfung, was aber nur Aufgaben betrifft, die der Nutzer ohnehin sieht. Das Brett bekommt `darf_bewegen` serverseitig aus `_darf_erledigen`. Status-Chips, ✏️-Knopf und Bearbeiten-Panel erscheinen nur bei `ich_darf_erledigen`/`darf_bewegen`; 🗑️ nur bei `darf_loeschen`.

### 4. Routen

Jede Route hat zwei Regeln am selben Endpunkt: mit `<token>` im Pfad und token-frei (`defaults={"token": None}`, Autorisierung über Sitzungs-Cookie, `19_sitzung.py`). Alle beginnen mit `check_grant(token, "todo")`; GET-Seiten rendern bei Fehlschlag `denied.html` mit 403, POST-Routen `abort(403)`. Formulare in den Vorlagen bauen die Adresse als `/a/todo{{ tp }}…` (`tp` = `token_pfad()`, `/tok/` oder `/`).

| Methode | Pfad (Token-Variante) | Funktion | Zweck | Eingaben und Validierung | Antwort |
|---|---|---|---|---|---|
| GET | `/a/todo/<token>/` | `index` | Listenansicht | Query `ansicht=liste` merkt „liste"; ohne `ansicht` und gemerktem „brett" → Redirect aufs Brett (Query `erledigt` wird mitgegeben). Query `erledigt=alle` zeigt auch >7 Tage Erledigtes | `todo.html` mit `todos`, `users` (id, name, farbe, sortiert nach Name), `erledigt_versteckt`, `darf_loeschen`, `historie`, `status_order/labels`, `rollen/rollen_labels` |
| POST | `/a/todo/<token>/neu` | `neu` | Aufgabe anlegen | `inhalt` (strip, leer → Redirect ohne Anlage), `ziel_typ` (`person` Default / `rollen` / `alle`), `zugewiesen_an` (`to_int`, muss in `users` existieren, sonst NULL), `rollen` (getlist, nur Werte aus `ROLLEN`, sortiert und dedupliziert; keine gültige → Ziel bleibt NULL/NULL, Status dann `offen`), `privat` (Checkbox), `faellig` (`faellig_aus_formular`) | Redirect `index` (folgt der gemerkten Ansicht) |
| POST | `/a/todo/<token>/status/<int:tid>` | `set_status` | Status setzen (Wunsch #20) | `status` ∈ `STATUS_ORDER` sonst 400; 404/403-Regel | Redirect `index` |
| POST | `/a/todo/<token>/bearbeiten/<int:tid>` | `bearbeiten` | alle Felder ändern (Wunsch #43) | `inhalt` (leer → Text bleibt; geändert → Historie-Eintrag), `ziel_typ`/`zugewiesen_an`/`rollen`/`privat` wie bei `neu`, `faellig` (leer = Frist entfernen); Status bleibt unangetastet; 404/403-Regel | Redirect `index` |
| POST | `/a/todo/<token>/loeschen/<int:tid>` | `loeschen` | endgültig löschen | nur `_darf_loeschen` (403), sonst 404 bei fehlender ID | Redirect `index` |
| GET | `/a/todo/<token>/kanban` | `kanban` | Brettansicht (Wunsch #224) | Query `ansicht=brett` merkt „brett" (nur dann); `erledigt=alle` wie oben | `todo_kanban.html` mit `spalten` (dict Status → Liste, je Eintrag `darf_bewegen`), sonst dieselben Zutaten wie `index` |
| POST (JSON) | `/a/todo/<token>/kanban/verschieben` | `kanban_verschieben` | Zug auf dem Brett | JSON `{id, status, order}`: `id` per `to_int`, `status` ∈ `STATUS_ORDER`, `order` muss Liste sein, sonst 400; 404 bei unbekannter/unsichtbarer ID; Statuswechsel nur mit `_darf_erledigen` (403); `order` wird als Zielspalten-Reihenfolge durchnummeriert (`position` = Index), fremde/unsichtbare IDs still übergangen | `{"ok": true}` |
| GET, POST | `/a/todo/<token>/serien` | `serien` | Vorlagen verwalten (Wunsch #90) | POST-Feld `action`: `neu` (`inhalt`, `wiederkehr_typ` ∈ intervall/wochentag, `intervall_tage` `to_int` > 0 bzw. `feste_wochentage` kommagetrennt, nur 0–6, sortiert, dedupliziert; ungültig → still verworfen), `toggle` (`id`, kippt `aktiv`), `loeschen` (`id`, nur `_darf_loeschen`, sonst still ignoriert) | POST → Redirect `serien`; GET → `todo_serien.html` mit `serien` (aktiv zuerst, dann `inhalt` NOCASE), `im_pool` (IDs, die heute verfügbar wären), `darf_loeschen`, `wochentage` |

Keine Route benutzt `antwort_oder_weiter()`/`data-fetch`; der einzige Nicht-Redirect-Endpunkt ist `kanban_verschieben` (JSON). Redirect-Ziele tragen keinen `#anker`.

### 5. UI je Vorlage

Gemeinsames aus `base.html`, worauf die Vorlagen bauen: Klick-Verteiler (`data-klick="fn"` + `data-args='[…]'`, Aufruf `fn(...args, element, ereignis)`), Änderungs-Verteiler `data-aendern` (Ereignis `change`), `data-panel="<id>"` (base hält `aria-expanded` per `aufzuSync()` nach jedem Klick aktuell), `data-bestaetigen` am Formular (globaler `submit`-Listener ruft `confirm()`), `ziehSortierung(opt)` mit Option `spalten` (nur mit dieser Option darf ein Eintrag die Gruppe wechseln) und die daran gekoppelte `tastaturSortierung(opt)` (Pfeiltasten am fokussierten Griff, Speichern 600 ms nach dem letzten Tastendruck, Ansage über `#sr-live`), CSS `body.zieht` (setzt `user-select:none` während eines Zuges, Wunsch #226), `.karte-griff` in der Griff-Regel von base, `a.knopf` (44-px-Tippfläche für Link-Knöpfe), Twemoji mit `data-emoji-alt` für Nutzertext. `dialogFuehrung()` wird von der Aufgaben-App nicht verwendet (kein Overlay). `data-arbeitet` kommt nicht vor.

#### `todo_teile.html` – geteilte Bausteine (Wunsch #225)

Wird von `todo.html` und `todo_kanban.html` mit `{% import "todo_teile.html" as teile with context %}` eingebunden (ohne `with context` fehlt `tp`). Enthält sechs Makros:

- `stile()` – gemeinsames CSS für Neu-Karte (`.new-todo-card`, `display:none`, `.open` blendet ein), Filterkarte (`.filter-card`), Chips (`.chip-btn`, `.active` in `var(--farbe-band)` mit weißer Schrift), Ziel-Band (`.ziel-chip` mit unsichtbarem Radio/Checkbox im Label, Färbung über `:has(input:checked)`, Fokusring über `:has(input:focus-visible)`, Rollen-Chips gestrichelt), Fälligkeitszeile (`.faellig-eingabe`, 16px), Bearbeiten-Panel (`.todo-edit-panel`, `display:none`, per JS auf `flex`), Verlauf (`.todo-verlauf`, Einträge mit Alttext und Meta).
- `ziel_auswahl(users, rollen, rollen_labels, aktueller_user_id, vorbelegt_zugewiesen_an, vorbelegte_rollen, vorbelegt_privat)` – Hidden-Feld `ziel_typ` (Startwert aus Vorbelegung: `alle`/`rollen`/`person`), Etikett „Für wen?", Chip-Reihe: Radio „Ich" (`zugewiesen_an=""`, vorausgewählt, wenn Person-Typ und keine fremde Person), ein Radio je anderem Nutzer (`zugewiesen_an=<id>`; die eigene Person erscheint nicht ein zweites Mal, Wunsch #261), Trenner, je Rolle eine Checkbox `rollen=<r>` mit Mehrzahl-Beschriftung (Eltern/Kinder/Gäste), Radio `ziel_alle=alle` („Alle"), Checkbox `privat` („🔒 Privat", rechtsbündig). Alle Ziel-Felder tragen `data-aendern="zielGewaehlt"` und `data-ziel-typ` (person/rolle/alle).
- `faellig_feld(vorbelegt)` – `<label>📅 Fällig <input type="datetime-local" name="faellig">`.
- `neu_karte(users, rollen, rollen_labels, aktueller_user_id)` – `#new-todo-card` mit Formular POST `/a/todo{{tp}}neu`: Textfeld `inhalt` (required, aria-label „Neue Aufgabe", Platzhalter „Neue Aufgabe…"), Knopf „+" (aria-label „Hinzufügen"), darunter `ziel_auswahl` und `faellig_feld`.
- `filter_karte(user, users, status_order, status_labels, mit_status=true)` – `#filter-card`: Etikett „Benutzer" mit Chip-Knöpfen (`data-value=<user id>`, der eigene zuerst als „Name (ich)"), optional Etikett „Status" mit vier Chips (`data-value=<status>`), Knopf „Filter zurücksetzen" (`#filter-zuruecksetzen-btn`, nur sichtbar bei aktivem Filter). Beide Ansichten rufen es mit `mit_status=true` auf (das Docstring-Argument beschreibt den Brett-Fall ohne Status-Filter, seit Wunsch #229 ist der Status-Filter aber auch dort an).
- `bearbeiten_panel(t, user, users, rollen, rollen_labels, historie)` – `#todo-edit-<id>` mit Formular POST `/a/todo{{tp}}bearbeiten/<id>`: Textfeld `inhalt` (Vorbelegung, required, aria-label „Aufgabentext"), Knopf „Speichern", `ziel_auswahl` vorbelegt (Person/Rollen/Alle/Privat), `faellig_feld(t.faellig_feld)`. Wenn Historie vorhanden: Knopf „🕘 Verlauf (n)" (`data-klick="toggleVerlauf"`, `data-panel="todo-verlauf-<id>"`) und Liste `todo-verlauf-<id>` mit je „„alter Text"" und „Name · Zeitstempel[:16]" (UTC-Rohwert, nicht in Ortszeit umgerechnet).
- `gemeinsame_skripte(eintrag_auswahl, gruppen_label)` – JS-Text (ohne eigenes `<script>`, damit das Nonce der Seite gilt): 
  - Neu-Formular: `#neu-toggle-btn` klappt `#new-todo-card` per Klasse `open` auf/zu und fokussiert das Textfeld; Zustand in `sessionStorage['todo_formular_offen']` (`1`/`0`), beim Laden wiederhergestellt (Wunsch #93).
  - Filter (Wunsch #94, #225): `sessionStorage['todo_filter']` = `{nutzer: [ids], status: [status]}`; `wendeTodoFilterAn()` blendet alle Elemente des Wählers `FILTER_EINTRAG` (`.todo-item` bzw. `.karte`) per `style.display` aus, wenn kein gewählter Nutzer in `data-nutzer` (Werte „erstellt_von,zugewiesen_an") vorkommt bzw. `data-status` nicht gewählt ist; blendet bei `FILTER_GRUPPEN_LABEL` leere `.section-label`-Gruppen aus; färbt `#filter-toggle-btn` (`aktiv`), zeigt `#filter-zuruecksetzen-btn` und `#todo-keine-treffer`; speichert; ruft `window.nachDemFiltern?.()` (Haken des Bretts). Chip-Klick toggelt `active` und wendet an; „Filter zurücksetzen" entfernt alle `active`. Beim Laden werden gespeicherte Chips reaktiviert (per `CSS.escape`).
  - `toggleTodoEdit(id)` / `toggleVerlauf(id)` – schalten `style.display` zwischen `flex` und `none`.
  - `zielGewaehlt(feld)` – pflegt `ziel_typ` je `.ziel-wrap`: Person-Radio löscht Rollen und Alle (`person`); Alle-Radio löscht Rollen und Personen (`alle`); Rollen-Checkbox löscht Personen und Alle, `rollen` wenn mindestens eine Rolle gewählt, sonst Rückfall auf „Ich" (`person`, Radio mit Wert „" wird gesetzt).

#### `todo.html` – Listenansicht

Von oben nach unten: Kopfzeile mit `h1.nav-title` „✅ Aufgaben" und `nav-sub` „N offen" (zählt Einträge mit `status == 'offen'` unter den gelieferten Todos). `<main>` beginnt mit `.top-aktionen`: Knopf „+ Neue Aufgabe" (`#neu-toggle-btn`, `data-panel="new-todo-card"`), Knopf „🔍 Filtern" (`#filter-toggle-btn`, `data-panel="filter-card"`, Klasse `aktiv` bei aktivem Filter), Link „📋 Brett" nach `/a/todo{{tp}}kanban?ansicht=brett`. Dann Filterkarte, Hinweis `#todo-keine-treffer` („Keine Aufgabe passt zum Filter 🔍"), Neu-Karte. Danach je Status in `STATUS_ORDER` eine `h2.section-label` (nur wenn die Gruppe nicht leer ist) mit den Aufgaben-Karten (Makro `todo_item`). Unten: Link „N vor mehr als 7 Tagen erledigte anzeigen" (`?erledigt=alle`, Klasse `mehr-erledigte knopf`) bei `erledigt_versteckt > 0`; bei völlig leerer Liste „🎉 Alles erledigt!".

Aufgaben-Karte (`.todo-item`, `id="todo-<id>"`, `data-status`, `data-nutzer`): Text (`.todo-text`, `data-emoji-alt`), Meta-Zeile mit Chips: 🔁 (grau `#8e8e93`, title „Wiederkehrende Aufgabe") bei `serie_id`; 🔒 (grau) bei `privat`; „→ Alle" oder „→ Eltern, Kind" (grau `#747479`) bei Rollenziel; „→ Name" in `farbe_kontrast(fuer_farbe)` bei Zuweisung an einen anderen; „von Name" in `farbe_kontrast(von_farbe)`, wenn die Aufgabe dem Betrachter zugewiesen ist; Fälligkeits-Chip „📅 Di 08.09., 16:00" (Klasse `faellig` plus `heute` in Akzentfarbe oder `ueberfaellig` in `var(--rot-text)` mit Zusatz „· überfällig"); Text „Erstellt: YYYY-MM-DD" und bei erledigt „· Erledigt: YYYY-MM-DD" (jeweils `[:10]` des UTC-Werts). Darunter der Status-Picker: Formular POST `status/<id>` mit vier Submit-Knöpfen `name=status` (Klasse `status-chip`, aktiver Status hervorgehoben; alle `disabled`, wenn `ich_darf_erledigen` falsch). Bei Berechtigung folgt das Bearbeiten-Panel (eingeklappt) und rechts der ✏️-Knopf (`data-klick="toggleTodoEdit"`, `data-args='[id]'`, `data-panel="todo-edit-<id>"`). Bei `darf_loeschen` ein Formular POST `loeschen/<id>` mit `data-bestaetigen="„<Text, 40 Zeichen>" löschen?"` und 🗑️-Knopf (aria-label „Löschen"). Erledigte Karten: Klasse `done` (Opazität .5, Text durchgestrichen). Sortierung innerhalb einer Statusgruppe: wie `_visible_todos` liefert (neueste zuerst); `position` spielt in der Liste keine Rolle.

Ohne Seitensprung passieren nur Auf-/Zuklappen und Filtern; jede Statusänderung, Anlage, Bearbeitung und Löschung ist ein klassisches POST mit Redirect. Skriptaufruf: `teile.gemeinsame_skripte('.todo-item', gruppen_label=true)`.

#### `todo_kanban.html` – Brett (Wunsch #224, #225)

Kopf: `h1` „✅ Aufgaben", `nav-sub` „Brett". `.top-aktionen`: „+ Neue Aufgabe", „🔍 Filtern", Link „☰ Liste" nach `/a/todo{{tp}}?ansicht=liste` (der Parameter ist Pflicht, sonst leitet die Merkung sofort zurück aufs Brett). Danach Filterkarte (mit Status), Neu-Karte, `#todo-keine-treffer`, Meldebalken `#brett-meldung` (`role="status" aria-live="polite"`, Wunsch #227), Hinweistext „Am Griff ⠿ ziehen: nach oben oder unten setzt die Reihenfolge (= Priorität), in eine andere Spalte den Status. Beides wird sofort gespeichert."

`#brett`: vier `.spalte[data-status]` in `STATUS_ORDER`, je mit Kopf (Label + Zähler `[data-zahl-fuer]`), Ablage `[data-ablage]` mit Karten, Platzhalter „nichts hier" (`[data-leer-fuer]`) bei leerer Spalte, und in der Erledigt-Spalte bei `erledigt_versteckt` ein Link „N ältere anzeigen" (`?erledigt=alle`, Klasse `aeltere-erledigte knopf`). Layout: auf dem Telefon scrollt das Brett waagerecht mit `scroll-snap-type:x proximity`, Spalten 78 % breit (max 280px); ab 700px tritt das Brett per Full-Bleed (`margin-left/right: calc(50% - 50vw)`) aus den 720px von `.main` heraus, Spalten `flex:1 0 240px`, max 380px (Wunsch #236); ab 1120px zentriert.

Karte (`.karte`, `id="karte-<id>"`, `data-id`, `data-status`, `data-nutzer`): links entweder der Griff-Knopf ⠿ (`.karte-griff`, `touch-action:none`, aria-label „Verschieben (Ziehen oder Pfeiltasten)") bei `darf_bewegen` oder ein 🔒-Span „Nur ansehen"; Text mit `data-emoji-alt`; Meta: Personen-Badge in `farbe_kontrast(fuer_farbe)` bei Zuweisung, sonst bei Rollenziel roher Text „für <zugewiesen_rollen>" (Rohwert wie `kind` oder `alle`, kein Label), „· 🔁" bei Serie, „· 🔒 privat", Fälligkeitszeile (`.karte-faellig heute|ueberfaellig`); rechts ✏️ (`data-klick="toggleTodoEdit"`) bei `darf_bewegen` und 🗑️-Formular mit `data-bestaetigen` bei `darf_loeschen`; darunter das Bearbeiten-Panel bei `darf_bewegen`. Sortierung je Spalte: serverseitig erst `erstellt` absteigend, dann `position` aufsteigend (stabil), weil nach der Migration überall `position=0` steht.

Skript: `const TP = tp`; `ziehSortierung({griff:'.karte-griff', eintrag:'.karte', platzhalter:'karte-drag-platzhalter', spalten:'.spalte', ablage:'[data-ablage]', idAus: el => parseInt(el.dataset.id), speichern: (reihenfolge, spalte, eintrag) => verschiebenSpeichern(id, spalte.dataset.status, reihenfolge)})`. `verschiebenSpeichern(id, status, reihenfolge, versuch=1)` schickt `fetch POST /a/todo${TP}kanban/verschieben` mit JSON `{id, status, order}`; bei Erfolg setzt es `karte.dataset.status`, ruft `zaehlerAuffrischen()` und `wendeTodoFilterAn()`; bei Fehler wird nach 1200 ms genau einmal wiederholt (Meldung „Verbindung stockt – wird nochmal versucht …"), beim zweiten Fehlschlag wandert die Karte per `appendChild` ans Ende der Herkunftsspalte zurück und der Balken zeigt dauerhaft „Nicht gespeichert (<Fehler>). Die Aufgabe steht wieder, wo sie war – bitte nochmal versuchen." (Wunsch #227; kein `location.reload()`). `meldung(text, dauerhaft)` blendet den Balken ein, nicht-dauerhafte Meldungen verschwinden nach 4 s. `zaehlerAuffrischen()` blendet ganze Spalten aus, deren Status im Filter abgewählt ist (Wunsch #229), zählt nur sichtbare Karten in den Kopfzähler und schaltet „nichts hier". `window.nachDemFiltern = zaehlerAuffrischen`. Dann `teile.gemeinsame_skripte('.karte', gruppen_label=false)` und ein erstes `zaehlerAuffrischen()`.

Drag & Drop (in `base.html`, für das Brett relevant): Pointer-Events am Griff, Zug beginnt ab 8 px Abstand in beliebiger Richtung (Wunsch #262), Schatten-Klon folgt in beiden Achsen, Platzhalter mit Karten-Höhe, Zielspalte bestimmt allein die X-Position des Fingers (auch unterhalb kurzer Spalten), Ablageposition nach Y-Mitte der Kandidaten, Brett rollt am Rand mit (bis 24 px je Frame, Randzone min(56px, Breite/5)) und `scroll-snap` ist währenddessen ausgeschaltet; `body.zieht` verhindert Textmarkierung; Speichern nur bei `ende` (nicht bei `pointercancel`). Tastatur: ↑/↓ verschiebt innerhalb der Spalte, ←/→ hängt die Karte ans Ende der Nachbarspalte; Speichern nach 600 ms Ruhe mit derselben `speichern`-Signatur.

#### `todo_serien.html` – Wiederkehrende Aufgaben

Erreichbar über den Menüeintrag „🔁 Wiederkehrende Aufgaben" im ☰-Menü (nur in der Aufgaben-App eingeblendet, `base.html`), Zurück-Link ← (`nav_left`) nach `/a/todo{{tp}}`. `h1` „🔁 Wiederkehrende Aufgaben". Formularkarte (POST auf dieselbe Adresse, `action=neu`): Textfeld `inhalt` (aria-label „Aufgabentext", Platzhalter „z.B. Blumen gießen", required); Etikett „Wiederkehr" mit zwei Chip-Knöpfen `data-typ=intervall` („Intervall (X Tage nach Erledigung)") und `data-typ=wochentag` („Fester Wochentag"), Hidden `wiederkehr_typ`; Block `#intervall-feld` mit Zahlfeld `intervall_tage` (min 1, Platzhalter „z.B. 7"); Block `#wochentag-feld` mit sieben Chip-Knöpfen Montag…Sonntag (`data-value` 0–6, Mehrfachauswahl, Wunsch #112) und Hidden `feste_wochentage` (kommagetrennt); Absende-Knopf „+ Vorlage anlegen" (`disabled`, bis ein Typ gewählt und Intervall ≥ 1 bzw. mindestens ein Wochentag gesetzt ist – `pruefeAbsendbar()`). Liste der Vorlagen (`.serie-item`, inaktive mit Opazität .4): Name, Badge „🔁 im Pool" (grün, wenn `serie_verfuegbar_am` für heute True und aktiv), Regeltext „Alle N Tage" bzw. „Jeden Montag, Mittwoch", Knopf „Pausieren"/„Aktivieren" (Formular `action=toggle`, ohne Rückfrage), bei `darf_loeschen` Knopf „🗑️ Löschen" (Formular `action=loeschen`, `data-bestaetigen="„…" dauerhaft löschen?"`). Leerzustand „Noch keine wiederkehrenden Aufgaben angelegt." Kein Bearbeiten bestehender Vorlagen. Das Skript dieser Seite hängt eigene `addEventListener` an die Chips (kein `data-klick`).

#### Offline-Verhalten

Kein app-eigener Offline-Code. Der Service Worker (`static/sw.js`) cached besuchte eigene GET-Seiten network-first; `offline_faehig` ist für `todo` 0. Schreibende Aufrufe brauchen Netz; das Brett behandelt einen fehlgeschlagenen Zug wie oben beschrieben. Formular-Zustand und Filter liegen in `sessionStorage` (pro Tab, geht beim Schließen verloren); die Ansichts-Vorliebe liegt serverseitig.

### 6. Wiederkehrende Aufgaben (Serien)

**Regeln**: Eine `todo_serien`-Zeile ist eine Vorlage mit `wiederkehr_typ` `intervall` (alle `intervall_tage` Tage) oder `wochentag` (an den Wochentagen aus `feste_wochentage`, 0=Mo..6=So, mehrere möglich). Eine Zielperson ist nicht Teil der Vorlage – sie wird beim Einsortieren gewählt. Vorlagen werden in der Aufgaben-App unter `/serien` angelegt, pausiert (`aktiv`) und gelöscht; ein Bearbeiten gibt es nicht.

**`_wochentage_menge(serie)`** parst `feste_wochentage` (Fallback `fester_wochentag`) zu einer Menge von ints; leer → leere Menge.

**`serie_verfuegbar_am(db, serie, tag_iso) -> bool`** (Wunsch #113): False, wenn bereits eine Instanz (`todos.serie_id = serie.id AND plan_tag = tag_iso`) existiert – unabhängig vom Status. Bei `wochentag`: True, wenn `date.fromisoformat(tag_iso).weekday()` in der Menge liegt. Bei `intervall`: Anker ist `MAX(plan_tag)` aller Instanzen; ohne Anker True für jeden Tag; sonst True, wenn die Differenz in Tagen > 0 und ein Vielfaches von `intervall_tage or 1` ist (periodisch, nicht „ab Schwelle immer"). Der Anker ist also der zuletzt eingeplante Tag, nicht der Erledigt-Zeitpunkt; Erledigung spielt für die Verfügbarkeit keine Rolle. Reine Kalendertag-Vergleiche, keine Zeitzone beteiligt (server.md, Bekannte Issues).

**`serien_pool_fuer_tag(db, tag_iso, alle_serien=None) -> list`**: filtert die aktiven Vorlagen (Default-Abfrage `WHERE aktiv=1 ORDER BY inhalt COLLATE NOCASE`, oder die übergebene Liste) auf die für genau diesen Tag verfügbaren.

**`serie_einsortieren(db, serie_id, ziel_user_id, plan_tag, erstellt_von_user_id) -> bool`**: lädt die aktive Vorlage, prüft `serie_verfuegbar_am`, legt bei Erfolg ein `todos`-Row an mit `inhalt` der Vorlage, `erstellt_von`, `zugewiesen_an`, `serie_id`, `plan_tag`, `status='offen'`; committet; True/False. Nicht über `todos_neu()` – daher keine Push-Nachricht, kein `position`-Ende (bleibt Default 0), kein `faellig`, `privat` 0.

**Wo Instanzen entstehen**: ausschließlich in `13_kinderplan.py` (Aufgabenplan, rollierende 14-Tage-Liste ab Montag der laufenden Woche). Dort lädt `index()` einmal alle aktiven Serien (nur wenn ein Ziel gewählt und `darf_editieren`) und ruft `serien_pool_fuer_tag(db, iso, alle_serien)` je Tag; die Vorlage `kinderplan.html` bietet je Tag „Aus Pool holen"-Formulare (POST `/a/kinderplan/<token>/serie_einsortieren` mit `ziel_id`, `serie_id`, `tag`), Route `serie_einsortieren_route` prüft Datum, Zielrolle (`kind`/`eltern`), Recht (eigener Plan oder `_darf_verwalten`) und die 20-Uhr-Sperre für den Folgetag, dann `serie_einsortieren(db, serie_id, ziel_id, tag_iso, user["id"])`. Der Kinderplan zeigt die Instanzen einer Person im 14-Tage-Fenster (`SELECT … FROM todos WHERE zugewiesen_an=? AND serie_id IS NOT NULL AND plan_tag BETWEEN …`).

**Erledigen/Zurücklegen einer Instanz**: (a) in der Aufgaben-App wie jede Aufgabe (Status-Chips, Brett, Bearbeiten, Löschen durch Eltern; erkennbar am 🔁-Chip); (b) im Kinderplan `POST /a/kinderplan/<token>/serie_erledigen/<tid>` (Toggle: `status` `erledigt`/`offen`, `erledigt`, `erledigt_am`, direkt in `todos`; nur Zugewiesener oder `_darf_verwalten`; JSON bei Header `X-Requested-With: fetch`) und `POST …/serie_zuruecklegen/<tid>` (Wunsch #114: echtes `DELETE FROM todos`, wodurch der Tag laut `serie_verfuegbar_am` wieder frei wird).

**Löschen einer Serie**: `DELETE FROM todo_serien` – Instanzen bleiben bestehen, ihr `serie_id` wird per `ON DELETE SET NULL` gelöscht (sie verlieren den 🔁-Chip). Pausieren (`aktiv=0`) lässt vorhandene Instanzen unberührt, die Vorlage erscheint in keinem Pool mehr.

**Exportierte Schnittstelle über den Alias `teile.todo`** (registriert in `teile/__init__.py` direkt nach `teile.kern`): `serien_pool_fuer_tag`, `serie_einsortieren`, `serie_verfuegbar_am`, `todos_neu`, `faellig_aus_formular`, `faellig_fuer_formular`, `faellig_anzeige`, `faellig_status` sowie die Konstanten; `13_kinderplan.py` importiert `serie_einsortieren, serien_pool_fuer_tag`, `tests/test_push.py` importiert `_todo_url`.

### 7. Fristen, Fälligkeit, Erledigt-Logik

**Fälligkeit (Wunsch #260)**: `faellig_aus_formular(text)` nimmt `YYYY-MM-DDTHH:MM` (auch mit Leerzeichen statt T) oder `YYYY-MM-DD` (gilt als 00:00 Ortszeit), interpretiert als `LOKAL_TZ` (Europe/Berlin, aus `teile.kern`), speichert UTC `YYYY-MM-DD HH:MM:SS`; Unlesbares → None. `_faellig_lokal(text)` rechnet zurück in Ortszeit. `faellig_fuer_formular(text)` → `YYYY-MM-DDTHH:MM` für das `datetime-local`-Feld. `faellig_anzeige(text, heute)` → `Di 08.09., 16:00`, Jahr nur, wenn es nicht das laufende ist (dann `08.09.2027`). `faellig_status(text, erledigt, jetzt)` → None (keine Frist oder erledigt), `ueberfaellig` (Zeitpunkt < jetzt), `heute` (gleiches Ortsdatum), sonst `offen`. `_mit_faelligkeit(zeilen)` hängt `faellig_anzeige`, `faellig_status`, `faellig_feld` an jede Zeile (einmal `datetime.now(LOKAL_TZ)` je Aufruf). Die Fälligkeit beeinflusst keine Sortierung und löst keine Benachrichtigung aus. Beim Bearbeiten heißt ein leeres Feld „keine Frist mehr".

**Erledigt (`erledigt`, `erledigt_am`)**: `set_status` und `kanban_verschieben` setzen `erledigt = 1` genau bei `status='erledigt'` und `erledigt_am = datetime('now')` (UTC), sonst `erledigt = 0` und `erledigt_am = NULL`. Ein Rückzug aus „Erledigt" löscht den Zeitstempel. `13_kinderplan.serie_erledigen` macht dasselbe per Toggle.

**7-Tage-Frist (Wunsch #243, `_ohne_alte_erledigte(todos)`)**: Grenze = `datetime.now(UTC) - 7 Tage`; Einträge mit `erledigt = 1` UND `erledigt_am` gesetzt UND `erledigt_am < grenze` werden aus Liste und Brett herausgefiltert (String-Vergleich im SQLite-Format). Altbestand mit `erledigt = 1` ohne `erledigt_am` bleibt sichtbar. Rückgabe `(sichtbare, anzahl_versteckter)`; `?erledigt=alle` schaltet den Filter ab, der Parameter überlebt die Weiterleitung von `index` auf das Brett. Gelöscht wird nichts. Dieselbe Frist wie beim „Gepackt"-Abschnitt der Packliste (#234).

**Backlog-Regel**: Nur beim Anlegen (`todos_neu`) landet ein Ziel ohne Person, aber mit `zugewiesen_rollen` (Rollen oder `alle`) im Status `backlog`; alles andere in `offen`. Beim Bearbeiten bleibt der Status unverändert, auch wenn das Ziel auf Rollen wechselt.

**Zeitzonen**: Anzeige der Fälligkeit in Ortszeit; `Erstellt:`/`Erledigt:` in den Karten sowie die Verlaufs-Zeitstempel zeigen den rohen UTC-Wert (`[:10]` bzw. `[:16]`), nicht `utc_zu_lokal`. `serien()` benutzt `date.today()` (Systemdatum des Containers, UTC) als „heute" für das Pool-Badge. `13_kinderplan` rechnet „heute" in Europe/Berlin.

### 8. Push-Benachrichtigungen und Hintergrund

Das Modul startet keinen eigenen Thread. Es gibt genau eine `push_send`-Stelle in `04_todo.py`, in `todos_neu()`: Auslöser ist das Anlegen einer Aufgabe mit `zugewiesen_an` gesetzt und ungleich `erstellt_von` (also nur bei direkter Zuweisung an eine andere Person; nicht bei Rollen/Alle, nicht bei Bearbeiten/Umzuweisung, nicht bei Serien-Instanzen aus dem Kinderplan). Empfänger: der Zugewiesene. Titel „Neue Aufgabe 📋", Text = `inhalt[:80]`, `app_slug='todo'`, URL aus `_todo_url(db, user_id)`: `https://portal.16schwaben.de/a/todo/` (token-frei, Wunsch #140 Stufe 6), oder leerer String, wenn der Empfänger keinen `todo`-Grant hat. `push_send` selbst läuft nicht-blockierend im Thread mit eigener DB-Verbindung (`00_kern.py`).

Externer Erzeuger `24_ki_budget.py` (Wunsch #183): stündlicher Hintergrund-Thread (`PRUEFTAKT_SEKUNDEN=3600`, Schalter `KI_GUTHABEN_WACHT`) legt bei OpenRouter-Guthaben ≤ `SCHWELLE_USD=1.00` eine Aufgabe direkt per `INSERT INTO todos(inhalt, erstellt_von, zugewiesen_an, status) VALUES(…, 'offen')` an (nicht über `todos_neu`; daher `position` 0, kein Push aus der Todo-Schicht) – Text „🤖 OpenRouter-Guthaben aufladen – nur noch X,XX USD übrig", Ersteller und Ziel = erster Admin (`is_admin=1 ORDER BY id`). Vorher prüft `_aufgabe_schon_offen()` per `status <> 'erledigt' AND inhalt LIKE '🤖 OpenRouter-Guthaben aufladen%'`, dass keine offene existiert. Dazu ein eigener `push_send(ziel, "🤖 KI-Guthaben fast leer", "Nur noch X,XX USD. Ohne Guthaben fallen Rezept-Import, Vorlesen und Foto-Import aus.", "todo", TODO_URL)` mit `TODO_URL = "https://portal.16schwaben.de/a/todo/"`.

`23_geburtstage.py` und `27_briefing.py` legen keine Todos an und lesen die Tabelle nicht (grep ohne Treffer).

### 9. Verflechtungen

- **Alias `teile.todo`** in `teile/__init__.py` (zweiter Eintrag nach `teile.kern`; Kommentar nennt es den ersten Cross-Modul-Import außerhalb von kern). `server.md` nennt in der `__init__`-Zeile noch `serien_pool_liste()` – der tatsächliche Name ist `serien_pool_fuer_tag()`.
- **`13_kinderplan.py`** (Aufgabenplan): importiert `serie_einsortieren, serien_pool_fuer_tag`; liest `todo_serien` und `todos` direkt (Instanzen im 14-Tage-Fenster), schreibt `todos` direkt (Toggle erledigt, DELETE beim Zurücklegen). Der Kinderplan ist damit die einzige Stelle, an der Serien-Instanzen entstehen und `plan_tag` gesetzt wird.
- **`24_ki_budget.py`**: schreibt und liest `todos` direkt (siehe Abschnitt 8).
- **`00_kern.py`**: Schema, Migrationen, Seed der App-Zeile, `token_pfad()` (Docstring nennt `/a/todo{{ tp }}neu` als Beispiel), `push_send`, `grant`, `to_int`, `LOKAL_TZ`, `farbe_kontrast()` (in den Vorlagen für Chips/Badges).
- **`base.html`**: Menüeintrag „🔁 Wiederkehrende Aufgaben" (`zeigt_todo_items`, wenn `app_slug == 'todo'` und Nutzer vorhanden); Verteiler und Zieh-Helfer (siehe Abschnitt 5); `.karte-griff` ist in base explizit in der `user-select`-Griff-Regel genannt.
- **Startseite**: keine Aufgaben-Kachel-Badge und kein Zähler; `01_start_token.py` und `27_briefing.py` enthalten keinen Todo-Bezug. Die App erscheint als normale Kachel über die `apps`-Tabelle.
- **`manage.py listtodos`**: listet alle Todos (Status ✅/⏳ nach `erledigt`, Datum, Ersteller, Zielperson, Text); kennt weder `status` noch Rollenziele.
- **Tests anderer Bereiche**, die `todo` verwenden: `test_push.py` (Deep-Link ohne Token via `_todo_url`), `test_grant.py` (Token gilt nur für seine App), `test_seiten_erreichbar.py` (`/a/todo/` im Rauchtest), `test_routen_inventar.py` (Blueprint `todo_app`), `test_ki_budget.py` (Aufgabe bei Ebbe), `test_log_redaktion.py`, `test_sitzung_gilt.py`, `test_zugang_einmalig.py`, `test_admin_app_zugriff.py`, `test_lese_grenzen.py`, `test_csp_bericht_log_injektion.py`, `test_kopfleiste.py`, `test_kopfzeile_bleibt.py`; `conftest.py` gibt `TestAdmin` standardmäßig einen `todo`-Grant.
- **Hilfe-App**: Abschnitt in „Die Apps" (Aufgaben), Kapitel 24 „📋 Aufgaben als Brett", Erwähnung im Tastatur-Tipp (⠿-Griff, Pfeiltasten) und im Kapitel „🗓️ Aufgabenplan" (Pool-Vorlagen). Der Hilfetext zum Brett sagt „Nur den Status-Filter gibt es hier nicht" und „Angelegt werden sie wie bisher in der Liste" – der Code hat seit #229 den Status-Filter auf dem Brett und seit #225 die Neu-Karte dort.

### 10. Konstanten und Konfiguration

| Name | Wert | Bedeutung |
|---|---|---|
| `bp` | `Blueprint("todo_app", __name__)` | Blueprint-Name, Endpunkte `todo_app.index` usw. |
| `APP` | `"todo"` | Slug für `check_grant` |
| `STATUS_ORDER` | `["backlog", "offen", "in_arbeit", "erledigt"]` | Reihenfolge der Stufen (Liste-Gruppen, Brett-Spalten, Status-Chips, Validierung) |
| `STATUS_LABELS` | Backlog / Offen / In Arbeit / Erledigt | Anzeigenamen |
| `ROLLEN` | `["eltern", "kind", "gast"]` | zulässige Rollen im Rollenziel |
| `ROLLEN_LABELS` | Eltern / Kind / Gast | Chip-Text in der Liste; das Ziel-Band nutzt eigene Mehrzahl-Labels Eltern/Kinder/Gäste |
| `WOCHENTAGE` | Montag…Sonntag | Chips und Anzeige der Serien-Seite |
| `WOCHENTAGE_KURZ` | Mo…So | Fälligkeitsanzeige |
| `ANSICHTEN` | `("liste", "brett")` | zulässige Werte in `todo_nutzer_ansicht`; Unbekanntes fällt auf „liste" |
| Frist in `_ohne_alte_erledigte` | 7 Tage | fest im Code |
| Push-Textlänge in `todos_neu` | `inhalt[:80]` | |
| Bestätigungstext | `inhalt|truncate(40)` | in `data-bestaetigen` |
| Brett-Retry | 1 Wiederholung nach 1200 ms; Meldung 4000 ms | in `todo_kanban.html` |
| sessionStorage-Schlüssel | `todo_formular_offen`, `todo_filter` | in `todo_teile.html` |
| Breakpoints Brett | 700px (Full-Bleed, Spalte min 240px/max 380px), 1120px (zentriert) | |
| Deep-Link | `https://portal.16schwaben.de/a/todo/` | in `_todo_url` (fest kodiert) und `24_ki_budget.TODO_URL` |

Keine eigene Umgebungsvariable; die Stufenriegel (`TOKENFREIE_URLS`, `CSRF_MODUS`, `CSP_MODUS`) wirken wie bei jeder App.

### 11. Wunsch-Historie

Aus `wuensche_todo.txt` (22 Wünsche, alle erledigt; kein offener Wunsch mit `[todo]`):

- #10 – Nur Eltern löschen; alle erstellen und erledigen (erledigt)
- #18 – Erstelldatum und Erledigungsdatum anzeigen (erledigt)
- #19 – Bearbeiten für Eltern, Kinder nur eigene; Editierhistorie (erledigt)
- #20 – Vier Status Backlog/Offen/In Arbeit/Erledigt (erledigt)
- #39 – Ziel Rolle(n)/Alle, landet im Backlog (erledigt)
- #43 – Beim Bearbeiten alle Felder, gleiche UX wie Anlegen (erledigt)
- #90 – Pool wiederkehrender Aufgaben, Wochentage im Aufgabenplan (erledigt)
- #93 – Neu-Formular hinter Knopf, wie Einkaufsliste (erledigt)
- #94 – Filter nach Benutzer und Status, bleibt bis Rücksetzen (erledigt)
- #214 – Audit F-06: `privat` auch in `_darf_erledigen` (erledigt)
- #224 – Kanban-Ansicht mit Prioritätsreihenfolge (erledigt)
- #225 – Brett als vollwertige Alternative, Ansicht je Nutzer gemerkt (erledigt)
- #226 – Keine Textmarkierung beim Ziehen (erledigt)
- #227 – Fehlermeldung „Verschieben konnte nicht gespeichert werden" auf dem iPhone (erledigt)
- #228 – Verschiebe-Knopf auf dem iPhone zu klein (erledigt)
- #229 – Status-Filter auch auf dem Brett (erledigt)
- #236 – Brett-Spalten auf dem Desktop breiter (erledigt)
- #243 – Erledigte nach 7 Tagen ausblenden (erledigt)
- #260 – Fälligkeitsdatum mit Uhrzeit, in der Übersicht sichtbar (erledigt)
- #261 – UI für neue Aufgaben vereinheitlichen (Chip-Band) (erledigt)
- #262 – Drag & Drop auf kleinem Bildschirm (erledigt)
- #288 – Audit N-09: 404 statt 403 für Unsichtbares (erledigt)

Im Code zusätzlich referenzierte Wünsche anderer Apps, die die Aufgaben-App mitbetreffen: #11 (Umbenennung Todos→Aufgaben), #92 (`plan_tag` statt Wochentag), #112 (mehrere Wochentage je Serie), #113 (Pool je Kalendertag, periodisch), #114 (Zurücklegen), #140 (token-freie Adressen, Deep-Link), #142 (CSP, `data-bestaetigen`), #178/#181 (Zieh-Helfer), #183 (KI-Budget-Aufgabe), #237 (Kontrastfarben), #248 (Interaktions-Ebene, Tastatur am Griff).

### 12. Bekannte Eigenheiten und offene Punkte

- **Tote Altfelder**: `todos.wochentag` (nie mit Produktivdaten gefüllt) und `todo_serien.fester_wochentag` (Backfill nach `feste_wochentage`) bleiben im Schema; `_wochentage_menge()` fällt auf `fester_wochentag` zurück „als zusätzliche Absicherung".
- **Ansicht merken nur bei ausdrücklicher Wahl**: Kommentar in `index()`/`kanban()` – sonst würde `live_pruefung.py`, das beide Ansichten abruft, die Vorliebe verstellen. Der Zurück-Link vom Brett muss `?ansicht=liste` tragen, sonst ist die Liste unerreichbar (`test_der_rueckweg_in_die_liste_bleibt_offen`).
- **Position nach Migration überall 0**: deshalb die doppelte stabile Sortierung in `kanban()`; „sobald einmal gezogen wurde, entscheidet ohnehin nur noch position". Neue Aufgaben gehen ans Ende ihrer Spalte (Lehre aus #178). Beim Spaltenwechsel wird nur die Zielspalte neu nummeriert, Lücken in der Herkunftsspalte sind beabsichtigt.
- **Unbekannter Status** auf dem Brett landet in „Offen" (Kommentar: sonst wäre die Aufgabe „schlicht weg"); in der Liste erscheint er in keiner Gruppe.
- **Rollenfilter in Python statt SQL** wegen kommagetrennter Spalte; daher zwei stabile Sortierläufe.
- **`_sichtbare_ids` bewusst über `_visible_todos`**, weil Doppelungen im Projekt „schon zweimal auseinandergelaufen" sind (F-06).
- **`_darf_erledigen` mit `privat`** (Wunsch #214): der Rollenweg war der einzige, der an der Sichtbarkeit vorbeiführte.
- **404 vor 403** (Wunsch #288) gilt als Muster für jede Route mit ID (server.md, Sicherheitskonventionen).
- **`todos_neu` vs. direkte INSERTs**: `serie_einsortieren` und `24_ki_budget` schreiben an `todos_neu()` vorbei (keine `position`-Endstellung, kein Push aus der Todo-Schicht, `status` fest 'offen').
- **Brett-Fehler nicht nachstellbar** (Wunsch #227): Kommentar vermutet den Service Worker (`skipWaiting()`+`clients.claim()` mitten im Betrieb); Antwort ist Retry + Zurücklegen statt Reload.
- **Serien-Anker ist der zuletzt eingeplante Tag**, nicht die Erledigung – Docstring beschreibt die Verhaltensänderung gegenüber #90 ausdrücklich (Wunsch #113).
- **„im Pool"-Badge** auf `/serien` bezieht sich auf „heute" laut `date.today()` (Container-UTC), „reine Anzeige-Vereinfachung".
- **Hilfe-Text zum Brett** nennt noch „kein Status-Filter" und „Angelegt werden sie wie bisher in der Liste"; Code seit #229/#225 anders. `filter_karte`-Docstring beschreibt ebenfalls den Zustand vor #229.
- **`server.md` Code-Struktur** nennt in der `__init__`-Zeile `serien_pool_liste()` (tatsächlich `serien_pool_fuer_tag()`).
- **Zeitstempel in Karten/Verlauf** (`erstellt[:10]`, `erledigt_am[:10]`, `geaendert_am[:16]`) sind UTC-Rohwerte; nur die Fälligkeit wird in Ortszeit gezeigt.
- **Brett-Meta bei Rollenziel** zeigt den Rohwert (`für kind`, `für alle`), die Liste zeigt Labels.
- **Filter „Benutzer"** matcht gegen `erstellt_von` ODER `zugewiesen_an`; Rollenziele sind nicht filterbar.
- **`test_csp.py`** hat laut Kommentar in `todo_teile.html` beim Schreiben angeschlagen, weil das Wort „script" als Beispiel im Kommentar stand.
- **server.md „Bekannte Issues"**: einziger Todo-Bezug ist der Zeitzonen-Hinweis, dass `serie_verfuegbar_am()` reine Kalendertage vergleicht und deshalb nicht betroffen ist. `SECURITY_REVIEW.md` liegt nicht im Klon vor (gitignore); die Audit-Befunde F-06 und N-09 sind über die Wünsche #214/#288 abgeschlossen.
- Keine `TODO:`-Kommentare im Modul oder in den vier Vorlagen.

### 13. Tests

- `tests/test_todo_ansicht.py` – Wunsch #225: gemerkte Ansicht je Nutzer (ohne Vorgeschichte Liste, Brett merkt sich nur bei `?ansicht=brett`, bloßer Aufruf ändert nichts, Rückweg per `?ansicht=liste`, Merkung je Nutzer, nach Anlegen bleibt man im Brett, Unsinn fällt auf Liste zurück), Brett kann dasselbe wie die Liste (Neu, Filter mit Status, Karten mit Filtermerkmalen), und `todo_teile.html` ist die einzige Fassung der Formulare (`test_keine_zweite_fassung_der_formulare`, beide Vorlagen importieren die Bausteine, derselbe Filter-Speicher).
- `tests/test_todo_kanban.py` – Wunsch #224: vier Spalten, Verlinkung hin und zurück, Zuordnung und Reihenfolge nach `position` (bei Gleichstand Neueres oben), fremde Private fehlen, Verschieben setzt Status/erledigt/erledigt_am und hebt es beim Zurückziehen auf, ungültiger Status 400, Umsortieren wird gespeichert und darf jeder Sichtberechtigte, fremde IDs in `order` bewirken nichts, Kind darf fremde nicht verschieben, unsichtbar → 404, ohne Grant kein Brett, neue Aufgabe ans Spaltenende, `ziehSortierung` wechselt Gruppen nur mit `spalten` (geprüft an `folge()` und `ende()` einzeln), Griff nur mit Recht, jede `data-klick`-Aktion existiert, Desktop-Mindestbreite und Full-Bleed (#236).
- `tests/test_todo_erledigt_frist.py` – Wunsch #243: über 7 Tage Erledigtes ist in Liste und Brett ausgeblendet, `?erledigt=alle` holt es zurück, Offenes kennt keine Frist, Altbestand ohne `erledigt_am` bleibt sichtbar, die Brett-Weiterleitung verliert den Parameter nicht.
- `tests/test_todo_faellig.py` – Wunsch #260: Umrechnung Sommer- und Winterzeit nach UTC und zurück, Datum ohne Uhrzeit ab Mitternacht, Leeres/Unsinn → None, Anzeige mit Wochentag und Jahr nur bei Fremdjahr, Status überfällig/heute/offen (erledigt nie überfällig), `neu` speichert UTC, `bearbeiten` setzt und löscht, Liste und Brett zeigen Ortszeit, Panel vorbelegt, `todos_neu()` nimmt `faellig`.
- `tests/test_todo_orakel.py` – Wunsch #288: unsichtbare fremde private Aufgabe antwortet auf `status` und `bearbeiten` mit 404 wie eine nicht vorhandene, fremde nicht-private Aufgabe ist für ein Kind ebenfalls 404, Eltern bekommen nie 403, eigene Aufgabe geht weiterhin.
- `tests/test_todo_privat_rollenziel.py` – Wunsch #214: privates Todo mit Rollenziel ist für ein Kind unsichtbar UND unveränderbar (Status, Inhalt, Privat-Flag), nicht-privates Rollenziel bleibt änderbar, wer es sieht darf es ändern, Eltern kommen an alles; Gegenprobe per monkeypatch der alten Fassung (inkl. `_sichtbare_ids`).
- `tests/test_todo_ziel_chips.py` – Wunsch #261: eigene Person nur einmal („Ich"), Rollen/Alle/Privat als Chips mit echten Feldern, „Ich" vorausgewählt, Bearbeiten-Panel zeigt das gesetzte Ziel, Brett nutzt dasselbe Band, Skript pflegt `ziel_typ` und kennt die alte Funktion nicht mehr, Routen verstehen die Felder unverändert.
- `tests/test_brett_ziehen_klein.py` – Wunsch #262: liest `ziehSortierung` in `base.html` – Zug beginnt auch bei seitlicher Bewegung, Schatten folgt seitlich, Brett rollt am Rand mit, Einrasten während des Zuges aus und danach an, Spalte zählt über die ganze Höhe, Brett scrollt weiterhin waagerecht, Listen ohne Spalten bleiben unberührt.
- `tests/test_ziehgriff_und_ausfall.py` – Wünsche #227/#228: jeder Ziehgriff im Portal (auch `.karte-griff`) ist ein `<button type="button">` mit Griff-Optik und `touch-action:none`, keine eigene Trefferfläche; ein Fehlschlag lädt die Seite nicht neu, es wird einmal wiederholt, bei endgültigem Fehlschlag geht die Karte zurück, die Meldung nennt die Ursache, `data-status` wandert mit.
- `tests/test_ziehen_ohne_markierung.py` – Wunsch #226: `body.zieht`-Sperre existiert, greift beim Start, hängt nur am Ziehen (in `ende` und `abbruch` wieder weg), wird vor der Prüfung gelöst, außerhalb bleibt alles markierbar, bestehende Auswahl wird aufgehoben.
- `tests/test_ki_budget.py` – Wunsch #183 (externer Erzeuger): bei Ebbe entsteht genau eine Aufgabe mit Push, ein zweiter Durchlauf legt keine zweite an, nach dem Abhaken darf wieder gewarnt werden.
- `tests/test_push.py` – Wunsch #140: `_todo_url` liefert den token-freien Deep-Link, kein Token in der Push-Nutzlast.
- Konventions-Wächter über alle Vorlagen (`test_tippflaeche`, `test_aria_labels`, `test_loeschen_symbol`, `test_kopfleiste`, `test_csp`, `test_formular_labels`, `test_ueberschriften`, `test_farbkontrast`, `test_interaktion`, `test_verteiler_argumente`, `test_darkmode`, `test_hilfe_kapitel`) und die Strukturwächter `test_routen_inventar` (Blueprint `todo_app` in der Liste) und `test_seiten_erreichbar` (`/a/todo/`) decken die vier Todo-Vorlagen und Routen mit ab.

---

## App „Geholfen" (geholfen)

Stand: 19.09.2026, Code-Stand v262 (Commit e9bf6a0). Quellen: `src/teile/06_geholfen.py` (417 Zeilen), die vier Vorlagen `geholfen.html`, `geholfen_aufgaben.html`, `geholfen_uebersicht.html`, `geholfen_verlauf.html` in `src/teile/templates/`, Schema/Seeds in `src/teile/00_kern.py`, `base.html` (Verteiler, `farbflaeche`, `dialogFuehrung`, Hamburger-Menü), `hilfe.html` (Kapitel 5 und 7, „Die Apps"), `server.md`, `journal.md`, `tests/test_geholfen_matrix.py`, `tests/test_emoji_grafik.py`, `tests/conftest.py`, die Wunsch-Liste `wuensche_geholfen.txt`.

### 1. Zweck und Zielgruppe

Modul-Docstring: „Kinder tippen auf Kacheln wenn sie geholfen haben. Design: große Kacheln, auch als Küchen-Tablet-Daueranzeige geeignet." Die Hilfe („Die Apps") beschreibt sie so: „Wenn du zu Hause geholfen hast, hier kurz antippen. Unter den Kacheln zeigt eine Punktmatrix, wer in den letzten 10 Tagen was erledigt hat."

Zielgruppen laut Hilfe-Kapitel 5 und 7:

- **Kinder (und alle mit Zugang):** tippen eine Kachel je Erledigung an; sehen darunter die Punktmatrix und den Personenstreifen der letzten zehn Tage sowie im Hamburger-Menü „📜 Zuletzt geholfen".
- **Eltern:** sehen zusätzlich den „Als wer?"-Selektor (Einträge für andere Familienmitglieder) und können im Verlauf Einträge mit ✏️ korrigieren oder löschen.
- **Admins:** haben zusätzlich „📊 Statistik" im Menü (7-Tage-Punkte, Details je Aufgabe, 10/30-Tage-Kalender) und darunter „⚙️ Aufgaben verwalten".

Die App ist außerdem die Datenquelle des Aufgabenplans (`13_kinderplan.py`): dessen Abhaken schreibt in dieselbe Tabelle `geholfen_eintraege`, seine Aufgabenliste ist `geholfen_aufgaben` (siehe Abschnitt 8). Die App wird laut `pruefplan.md` (S2-05, S5-15) auch auf dem Esszimmer-Kiosk-Bildschirm im iFrame bedient.

Slug `geholfen`, Name „Geholfen", Emoji 🙋, Beschreibung „Geholfen-Protokoll" (Seed `_CORE_APPS` in `00_kern.py`). Kein Auto-Grant – jeder Nutzer braucht einen Grant; live haben alle vier Nutzer einen (`server.md`, „Nutzer").

### 2. Datenmodell

Beide Tabellen stehen im `SCHEMA` von `00_kern.py`; es gibt keine `ALTER TABLE`-Migrationen für sie, nur Daten-Migrationen (siehe Seeds).

**`geholfen_aufgaben`** – der Aufgabenkatalog (Kacheln).

| Spalte | Typ | Default | Bedeutung |
|---|---|---|---|
| `id` | INTEGER PRIMARY KEY | – | Kennung; zugleich die Anzeigereihenfolge (alle Abfragen sortieren `ORDER BY id`, es gibt keine Positionsspalte) |
| `name` | TEXT NOT NULL | – | Anzeigename; kein UNIQUE (deshalb Existenz-Check statt `INSERT OR IGNORE` in der Migration) |
| `emoji` | TEXT NOT NULL | `'👍'` | Kachel-Symbol; Nutzereingabe, seit #275 nur mit lokaler Twemoji-Grafik anlegbar |
| `gewichtung` | REAL NOT NULL | `1.0` | Punktwert je Erledigung, nur in der Übersicht (7-Tage-Punkte) verwendet |
| `aktiv` | INTEGER NOT NULL | `1` | 0 = deaktiviert: keine Kachel, kein Tippen möglich, keine Zuweisung im Aufgabenplan; alte Einträge bleiben |

**`geholfen_eintraege`** – das Ereignis-Log, ein Datensatz je Erledigung („nichts wird vorberechnet gespeichert", Docstring).

| Spalte | Typ | Default | Bedeutung |
|---|---|---|---|
| `id` | INTEGER PRIMARY KEY | – | Kennung |
| `aufgabe_id` | INTEGER NOT NULL, FK `geholfen_aufgaben(id)` ON DELETE CASCADE | – | welche Aufgabe |
| `user_id` | INTEGER NOT NULL, FK `users(id)` ON DELETE CASCADE | – | für wen der Eintrag zählt (nicht: wer ihn getippt hat – das wird nicht gespeichert) |
| `zeitstempel` | TEXT NOT NULL | `datetime('now')` | Zeitpunkt in **UTC**, Format `YYYY-MM-DD HH:MM:SS` |

Fremdtabelle mit Bezug: `kinderplan_eintraege.aufgabe_id` → `geholfen_aufgaben(id)` ON DELETE CASCADE (Aufgabenplan, `UNIQUE(user_id, aufgabe_id, plan_tag)`).

**Seed-Aufgaben** (`_DEFAULT_AUFGABEN` in `00_kern.py`, eingespielt nur wenn die Tabelle leer ist, Reihenfolge = spätere `id`-Reihenfolge, alle `aktiv=1`):

| Reihenfolge | Name | Emoji | Gewichtung |
|---|---|---|---|
| 1 | Tisch decken | 🍽️ | 1.0 |
| 2 | Tisch abräumen | 🥣 | 1.0 |
| 3 | Wäsche zusammenlegen | 🧺 | 1.5 |
| 4 | Rasen mähen | 🌿 | 3.0 |
| 5 | Zimmer aufräumen | 🧹 | 2.0 |
| 6 | Einkaufen helfen | 🛒 | 1.5 |
| 7 | Beim Kochen helfen | 🍳 | 2.0 |
| 8 | Spülmaschine einräumen | 🍳 | 1.0 |
| 9 | Spülmaschine ausräumen | 🍳 | 1.0 |

Daten-Migration Wunsch #96 in `_init_db()`, läuft bei jedem Start idempotent: `UPDATE … SET name='Spülmaschine einräumen' WHERE name='Spülmaschine ein'`, `UPDATE … SET name='Wäsche zusammenlegen' WHERE name='Wäsche falten'`, und `INSERT` von „Spülmaschine ausräumen" (🍳, 1.0), falls kein Datensatz dieses Namens existiert. Live existiert zusätzlich die per Verwaltung angelegte Aufgabe „Staubwischen" mit 🪄 (U+1FA84, Anlass für #275).

**Zeitstempel-Konvention.** Gespeichert wird UTC (`datetime('now')` der SQLite-Verbindung im UTC-Container). Drei verschiedene Tagesbegriffe kommen im Code vor:

- **Familientag** (Kalendertag in `Europe/Berlin`, `LOKAL_TZ`): Punktmatrix und Personenstreifen (`utc_zu_lokal_datum(zeitstempel)`, `heute_lokal()`), JSON-Antwort von `tippen` (`tag=heute_lokal()`).
- **UTC-Tag** (`date(zeitstempel)` in SQL, `date.today()` in Python): Übersichtsseite (7-Tage-Fenster, 30-Tage-Kalender) sowie der Erledigt-Status im Aufgabenplan (`13_kinderplan.py`).
- **Roh-Anzeige**: Der Verlauf zeigt `zeitstempel[:16]` unverändert (also UTC, ohne Umrechnung) und befüllt damit auch das `datetime-local`-Feld; beim Speichern wird der Feldwert unverändert (nur `T`→Leerzeichen, ggf. `:00` angehängt) zurückgeschrieben.

`tests/conftest.py` führt `geholfen_aufgaben` in `BLEIBT` (Seed-Tabelle, wird zwischen Tests nicht geleert); `geholfen_eintraege` wird je Test geleert.

### 3. Rollen und Rechte

Grundlage überall: `check_grant(token, "geholfen")` (Alias von `teile.kern.grant`) – ohne gültigen Grant 403 (`denied.html` bei GET-Seiten, `abort(403)` bei POST/`aufgaben`). Jede Route hat zwei Regeln: mit `<token>` im Pfad und token-frei (Sitzungs-Cookie, `defaults={"token": None}`).

Zentrale Hilfsfunktion: `_kann_fuer_andere(user)` = `user["is_admin"] or user["rolle"] == "eltern"`.

| Handlung | wer | Prüfung |
|---|---|---|
| Startseite sehen, Kachel für sich selbst tippen | jeder mit Grant (auch Rolle `gast`) | nur Grant |
| „Als wer?"-Selektor sehen, für andere tippen | Eltern oder Admin | `_kann_fuer_andere`; `fuer_user_id` anderer Nutzer wird sonst still ignoriert (Eintrag landet beim Tipper) |
| Zielperson beim Tippen für andere | jeder Datensatz in `users` (jede Rolle, auch `gast`, auch Admins) | `SELECT id FROM users WHERE id=?` |
| Verlauf sehen („📜 Zuletzt geholfen") | jeder mit Grant | nur Grant |
| Eintrag bearbeiten/löschen | Eltern oder Admin | `_kann_fuer_andere`, sonst 403; auch fremde und eigene Einträge, kein Owner-Check |
| Übersicht/Statistik (`/uebersicht`) | nur Admin | `user["is_admin"]`, sonst 403 `denied.html`; Menüpunkt nur für Admin |
| Aufgaben verwalten (`/aufgaben`, GET+POST) | nur Admin | `user["is_admin"]`, sonst `abort(403)` |

Rollen `eltern`/`kind`/`gast` und die Admin-Berechtigung stammen aus Wunsch #5. In Matrix und Personenstreifen erscheinen nur Nutzer mit Rolle `eltern` oder `kind` (Gäste bewusst ausgeschlossen, #29), der „Als wer?"-Selektor und die Übersicht listen dagegen **alle** `users`.

### 4. Routen

Blueprint `geholfen_app`, alle Pfade zusätzlich ohne `<token>/`-Segment als Cookie-Zwilling. `TP` bzw. `tp` (aus dem Kontextprozessor in `00_kern.py`, `token_pfad()`) ist im Template `/<token>/` oder `/`.

| Methode | Pfad | Funktion | Zweck | Eingaben und Validierung | Antwort |
|---|---|---|---|---|---|
| GET | `/a/geholfen/<token>/` | `index` | Hauptseite: Kacheln, ggf. Selektor, Matrix + Streifen | – | `geholfen.html` mit `aufgaben` (aktiv, `ORDER BY id`), `alle_nutzer` (nur wenn `_kann_fuer_andere`, alle users `ORDER BY name`), `matrix` (`_matrix_fuer`), `personen_js`, `quadrat_stufen`; 403 `denied.html` |
| POST | `/a/geholfen/<token>/tippen/<int:aufgabe_id>` | `tippen` | Erledigung eintragen | `aufgabe_id` muss aktiv existieren (sonst 404). Für Eltern/Admin: `fuer_user_id` aus JSON-Body (`request.get_json(silent=True)`) oder Formularfeld, per `to_int()`; nur übernommen, wenn der Nutzer existiert, sonst bleibt der Tipper selbst Ziel | `INSERT INTO geholfen_eintraege(aufgabe_id, user_id)`; bei Header `X-Requested-With: fetch` JSON `{ok, aufgabe, emoji, fuer_user_id, tag=heute_lokal()}`, sonst Redirect auf `index` |
| GET | `/a/geholfen/<token>/verlauf` | `verlauf` | letzte 50 Einträge | – | `geholfen_verlauf.html`; JOIN users + aufgaben, `ORDER BY zeitstempel DESC LIMIT 50`; `darf_bearbeiten`, `alle_nutzer` (id, name), `alle_aufgaben` (alle, auch inaktive, `ORDER BY id`) nur für Eltern/Admin |
| POST | `/a/geholfen/<token>/eintrag/<int:eid>/bearbeiten` | `eintrag_bearbeiten` | Eintrag ändern | 403 wenn nicht `_kann_fuer_andere`; 404 wenn `eid` fehlt. Formular: `user_id`, `aufgabe_id` (beide `to_int`, müssen existieren – Aufgabe darf inaktiv sein), `zeitstempel` (nicht leer; `T`→Leerzeichen, bei 16 Zeichen `:00` angehängt; kein Formatcheck darüber hinaus). Bei ungültigen Werten stiller Redirect ohne Änderung | `UPDATE` aller drei Felder; Redirect auf `verlauf` (kein Anker) |
| POST | `/a/geholfen/<token>/eintrag/<int:eid>/loeschen` | `eintrag_loeschen` | Eintrag endgültig löschen | 403 wenn nicht `_kann_fuer_andere`; kein 404 bei unbekannter `eid` (DELETE ohne Wirkung) | Redirect auf `verlauf` |
| GET | `/a/geholfen/<token>/uebersicht` | `uebersicht` | Statistik (Admin) | – | `geholfen_uebersicht.html` mit `users` (alle), `aufgaben` (aktiv), `counts`, `punkte`, `tage` (30 ISO-Tage), `kalender`; 403 `denied.html` für Nicht-Admins |
| GET, POST | `/a/geholfen/<token>/aufgaben` | `aufgaben_verwalten` | Aufgabenkatalog pflegen (Admin) | POST-Feld `action`: **`neu`** – `name` (strip, Pflicht, sonst nichts), `emoji` (strip, leer → 👍), `gewichtung` (`float()`, Fehler → 1.0; keine Bereichsprüfung serverseitig); Emoji ohne lokale Grafik (`emoji_grafik_vorhanden`) → Redirect `?fehler=emoji&emoji=…&name=…`, nichts angelegt. **`toggle`** – `id` (`to_int`, Default 0), kippt `aktiv`. **`umbenennen`** – `id`, `name` (strip, Pflicht); `UPDATE name` ohne Existenzprüfung der id | POST: Redirect auf `aufgaben_verwalten`. GET: Vorlage mit `aufgaben` (`ORDER BY aktiv DESC, id`), `ohne_grafik` (Menge der ids ohne Grafik), `fehler`, `vorbelegt` (emoji, name aus Query) |

Es gibt keine Route zum Löschen einer Aufgabe, zum Ändern von Emoji oder Gewichtung, zum Umsortieren, und keine JSON-Leseroute. Die einzige JSON-Antwort ist `tippen` bei `X-Requested-With: fetch`. Die Routen-Wächter erwarten den Endpunkt `geholfen_app` (`tests/test_routen_inventar.py`); keine Geholfen-Route steht in dessen Ausnahmen.

CSRF (`20_csrf.py`, live `scharf`): Der fetch-POST aus `geholfen.html` läuft same-origin und trägt `Sec-Fetch-Site: same-origin`; eine gesonderte Token-Behandlung gibt es nicht.

### 5. UI je Vorlage

Alle vier Vorlagen erben von `base.html` und setzen `app_slug = "geholfen"`, wodurch das Hamburger-Menü den App-Block „📜 Zuletzt geholfen" (alle) und „📊 Statistik" (nur `user.is_admin`) einblendet (`base.html`, Zeilen 530–546). Emoji werden nach dem Laden durch `twemoji.parse()` zu `<img class="emoji">` aus `/static/twemoji/svg/`; ein Bild, das nicht lädt, ersetzt `base.html` per `error`-Listener durch das Zeichen selbst (#275).

#### 5.1 `geholfen.html` – Hauptseite

Kopfleiste: `h1.nav-title` „🙋 Geholfen!", darunter `nav-sub` „Hallo, {{ user.name }} 👋". Kein Zurück-Link (ist die App-Startseite), kein `nav_left`.

Von oben nach unten im `<main class="main">`:

1. **Nutzer-Picker „Als wer?"** (`div.nutzer-picker`, nur wenn `alle_nutzer` gesetzt, also Eltern/Admin). Eine Pille (`button.nutzer-pill`) je Nutzer, alphabetisch, mit `data-uid`, `data-farbe`, `data-klick="waehleNutzer"`, `data-args='[id, "farbe_kontrast(farbe)"]'`. Die eigene Pille startet als `.aktiv` mit Inline-Hintergrund in der Kontrastfarbe. `waehleNutzer(uid, farbe, btn)` setzt die JS-Variable `fuerUserId`, entfernt `.aktiv`/Inline-Stile von allen Pillen und färbt die getippte (Hintergrund `farbe`, Schrift `#fff`). Die Auswahl gilt für alle folgenden Kachel-Taps bis zum Neuladen; sie wird nirgends gespeichert.

2. **Tipp-Kacheln** (`div.aufgaben-grid#aufgaben-grid`): je aktiver Aufgabe ein `button.aufgabe-btn[data-id]` mit `span.aufgabe-emoji` (26 px, Twemoji-Bild, `alt=""` da kein `data-emoji-alt` am Emoji-Span) und `span.aufgabe-name[data-emoji-alt]` (12 px, `--text-3`). Raster: 3 Spalten, ab 500 px 4, ab 700 px 5 (#27); `min-height:64px`, `border-radius:14px`, Schatten, `:active` skaliert auf 0,94. Klick-Handler (direkt per `addEventListener`, nicht über `data-klick`): Klasse `flash` für 600 ms (Hintergrund `var(--farbe)`, Name weiß), dann `fetch POST /a/geholfen{TP}tippen/{id}` mit Header `X-Requested-With: fetch`, JSON-Body `{fuer_user_id}`. Bei `ok`: Toast `"{emoji} {aufgabe} ✓"` (`showToast`, 2000 ms, grüner Balken `#217f39` oben mitten, `z-index:300`) und `matrixPunkt(id, fuer_user_id, tag, aufgabe)`. Wirft `fetch` (Netzfehler/kein JSON), baut das Skript ein leeres `<form method=post>` auf dieselbe URL und schickt es ab – dann ohne `fuer_user_id`, Antwort ist ein Redirect auf die Seite.

3. **Matrix-Abschnitt** (`section.matrix-section`, nur wenn `matrix.personen` nicht leer, `aria-describedby="matrix-erklaerung"`):
   - `h2.heatmap-title` „📊 Letzte 10 Tage" und ein visuell verborgener Erklärtext `p#matrix-erklaerung.mx-sr`.
   - **Personen-Chips** (`div.mx-chips[role=group][aria-label="Personen filtern"]`): Knopf „alle" (`#mx-chip-alle`) plus je Person ein `button.mx-chip[aria-pressed=true][data-uid]` mit farbigem Punkt (`span.mx-chip-punkt.farbflaeche`, `--ft-dunkel`/`--ft-hell`) und Name. Ab mehr als 5 Personen Klasse `schieben` (eine Zeile, seitlich scrollbar, `padding-right:28px`). `matrixFilter(uid, btn)`: „alle" setzt alle Chips auf `aria-pressed=true`; ein Personen-Chip kippt sein `aria-pressed`; anschließend bekommen alle `.punkt[data-uid]` der abgewählten Personen die Klasse `gedimmt` (Opazität 0,15). Der „alle"-Chip zeigt `aria-pressed=false`, sobald mindestens eine Person abgewählt ist. Chips mit `aria-pressed=false` werden auf Opazität 0,45 gedimmt. Der Filter wirkt nur auf Punkte (Punktmatrix), nicht auf die Quadrate des Personenstreifens, und ändert weder Reihenfolge noch „+n"-Zähler.
   - **Kopfzeile** (`div.mx-raster.mx-kopf`, `position:sticky; top:calc(var(--st) + 62px)`): leere Label-Zelle plus je Tag `div.mx-zelle.mx-kopfzelle` mit `span.wt` (Mo…So) und `span.tz` („1."); Klassen `we` (Wochenende, grauer Streifen `rgba(127,127,127,.09)`) und `heute` (Schrift `--farbe-kontrast`). Kopfschrift 12 px (Regel #238).
   - **Punktmatrix**: je Zeile aus `matrix.zeilen` ein `div.mx-raster.mx-aufgabe[data-aufgabe=id]`, jede gerade Zeile zusätzlich `.alt` (Hintergrund `--surface-2`). Label `div.mx-label` „{emoji} {name}". Je Tag: bei `anzahl > 0` ein `button.mx-zelle#mx-{aufgabe}-{iso}` mit `data-klick="zelleDetails"`, `data-args` = `[name, datum_lang, anteile]` (per `|tojson`), `aria-label` = Tooltip-Text; darin bis zu vier `span.punkt.farbflaeche[data-uid]` (9 px Kreise, Reihenfolge des Eintreffens) und ggf. `span.mx-mehr` „+n". Bei `anzahl == 0` ein stummes `div.mx-zelle` mit `data-datum`. Keine `title`-Attribute (#278). Desktop-Raster: `150px repeat(10, minmax(0,1fr))`, Zellhöhe 44 px.
   - **Detail-Blatt** (`div.mx-overlay#mx-overlay` → `div.mx-sheet[role=dialog][aria-modal=true][aria-labelledby=mx-sheet-titel]`): `h3#mx-sheet-titel`, Knopf „Schließen" (`data-klick="zelleSchliessen"`), `div#mx-sheet-datum`, `ul#mx-sheet-liste`. Geführt über `window.dialogFuehrung(overlay, sheet)` aus `base.html` (Fokus-Falle, Escape, Fokus-Rückgabe); Klick auf den Overlay-Hintergrund schließt. `zelleDetails(aufgabe, datum, anteile)` füllt Titel/Datum per `textContent` und je Anteil („Anna 4x") ein `li` mit Farbpunkt (Person per Namensvergleich aus `PERSONEN` gesucht) und Text. Handy: unten angedockt, `border-radius 16px 16px 0 0`, Safe-Area-Padding; ab 600 px mittig, max. 380 px.
   - **Personenstreifen**: `h2.heatmap-title.ps-titel` „👤 Je Person" (22 px Abstand, Trennlinie – #277). Je Person `div.mx-raster.ps-raster.ps-zeile`: Label `div.mx-label.farbtext` mit `span.name-voll` (voller Name) und `span.name-kurz` (Vorname, nur unter 600 px sichtbar); je Tag `div.mx-zelle#ps-{uid}-{iso}[data-anzahl]` mit `span.quadrat.farbflaeche.g{stufe}`; `g0` ist `display:none`, `g1`–`g4` = 18/26/34/40 px, bei `anzahl > 0` `role="img"` + `aria-label`. Zellhöhe 48 px. Legende `div.ps-legende`: „Kantenlänge = Anzahl erledigter Aufgaben an diesem Tag, leer = nichts erledigt".
   - **Sofort-Aktualisierung nach dem Tippen** (`matrixPunkt(aufgabeId, uid, tag, aufgabeName)`): sucht `#mx-{aufgabe}-{tag}`; ist es noch ein `div`, wird es durch einen gleichnamigen `button` mit `data-klick="zelleDetails"` und `data-args=[name, data-datum||tag, []]` ersetzt; `anteileErhoehen()` zählt den Namen in `args[2]` hoch („Name 1x" → „Name 2x"), `aria-label` wird neu gesetzt; unter `PUNKTE_MAX` (JS-Konstante 4) wird ein Punkt eingefügt, sonst `.mx-mehr` angelegt bzw. hochgezählt. Danach `#ps-{uid}-{tag}`: `data-anzahl` +1, Quadrat-Klasse `g{min(n,4)}`, `aria-label` „{Name}, heute: n Aufgabe(n)". Existiert die Spalte `tag` nicht (Datumswechsel seit dem Laden) oder ist die Zielperson nicht in `PERSONEN` (Rolle weder `eltern` noch `kind`, z. B. ein Gast), passiert nichts sichtbar außer dem Toast. Da `matrix.zeilen` jede aktive Aufgabe enthält, existiert die Zeile für die getippte Kachel immer. Die Zeilenreihenfolge wird clientseitig nicht neu sortiert.

4. **Mobile-Layout** (`@media (max-width:599px)`, #278): Raster `repeat(10, minmax(0,1fr))` ohne Label-Spalte; das Aufgabenlabel wird eigene Zeile über dem Raster (`grid-column:1/-1`, max. 2 Zeilen per `-webkit-line-clamp`); Kopf-Label ausgeblendet, Kopfzellen zweizeilig (wt über tz); keine `.alt`-Hintergründe, stattdessen `border-top` 0,5 px und 12 px Abstand zwischen Aufgaben; Zellen 28 px hoch, Punkte 7 px; Personenstreifen `56px repeat(10, …)` mit Vorname (Ellipse), Quadrate 12/18/24/24 px, zusätzlich auf `calc(100% - 2px)` Spaltenbreite gedeckelt (`aspect-ratio:1`); Kartenrand plus `env(safe-area-inset-*)`. Kein waagerechtes Scrollen an irgendeiner Stelle („was gescrollt werden muss, wird nicht verglichen").

Skript-Variablen: `TP` (Tokenpfad), `PERSONEN` (`{uid: {name, dunkel, hell}}` aus `personen_js`), `PUNKTE_MAX = 4`, `fuerUserId = user.id`.

#### 5.2 `geholfen_verlauf.html` – „📜 Zuletzt geholfen"

Kopfleiste: `nav_left` Zurück-Link `←` auf `/a/geholfen{tp}` (title „Zurück"), `h1` „📜 Zuletzt geholfen". Inhalt: je Eintrag (max. 50, neueste zuerst) ein `div.verlauf-item#verlauf-{id}` mit Zeile: Emoji (22 px), `<strong class="farbtext">Name</strong>: Aufgabe`, Zeit `zeitstempel[:16]` (12 px, roh „YYYY-MM-DD HH:MM", UTC), und – nur für Eltern/Admin – ein ✏️-Knopf (`data-klick="toggleVerlaufEdit"`, `data-args='[id]'`, `data-panel="verlauf-edit-{id}"`, `title`=`aria-label`=„Bearbeiten"). Ohne Einträge: „Noch keine Einträge."

Bearbeiten-Panel (`div.verlauf-edit-panel#verlauf-edit-{id}`, `display:none`, `toggleVerlaufEdit(id)` kippt `style.display` zwischen `flex` und `none`; `aufzuSync()` aus `base.html` pflegt `aria-expanded` am Knopf):
- Formular POST `…/eintrag/{id}/bearbeiten`: `input[type=datetime-local][name=zeitstempel]` (vorbelegt mit `zeitstempel[:16]` mit `T`, `aria-label` „Zeitpunkt", required), `select[name=user_id]` (alle Nutzer, aktueller vorausgewählt, `aria-label` „Person"), `select[name=aufgabe_id]` (alle Aufgaben inkl. inaktive, „{emoji} {name}", `aria-label` „Hilfsleistung"), Knopf „Speichern".
- Zweites Formular POST `…/eintrag/{id}/loeschen` mit `data-bestaetigen="„Name: Aufgabe“ löschen?"` (der Submit-Verteiler in `base.html` ruft `confirm()`), Knopf „🗑️ Eintrag löschen" (rot, `--rot-text`).

Keine Filter, keine Zeitraumwahl, keine Seitenweiterschaltung, kein Anker nach dem Redirect.

#### 5.3 `geholfen_uebersicht.html` – „📊 Übersicht" (Admin)

Kopfleiste: Zurück `←` auf `/a/geholfen{tp}`, `h1` „📊 Übersicht", `nav-sub` „Letzte 7 Tage · Kalender".

1. **`h2` „Punkte"** – `div.stats-grid` (auto-fill, min 140 px): je Nutzer (alle `users`, alphabetisch) eine Karte mit rundem Avatar (Initiale `name[0]`, Hintergrund `farbe_kontrast(farbe)`), Name, Punktzahl (`farbtext`, 28 px) und Etikett „Punkte". Punktzahl = Summe der `gewichtung` aller Einträge der letzten 7 Tage (UTC, `datetime('now','-7 days')`). Der Jinja-Ausdruck lautet `(punkte.get(u.id, 0) * 10 | round | int) / 10`; Filter binden an die `10`, der Ausdruck ergibt also `punkte * 10 / 10`.
2. **`h2` „Details"** – `table.detail-table`: Zeile je aktiver Aufgabe („{emoji} {name}"), Spalte je Nutzer, Zelle `span.count-badge` mit Anzahl der Einträge in 7 Tagen; bei > 0 Klasse `has` (weiß auf `--farbe-band`).
3. **„Kalender"** (Etikett als `span.section-label` in einer `div.section-label-row`) mit zwei Umschaltern `button.cal-toggle#btn-10`/`#btn-30` (`data-klick="showDays"`, `data-args='[10]'`/`'[30]'`). `table.cal-table`: Kopf „Tag" plus je Nutzer die Initiale (`title` voller Name); eine `tr.cal-row` je Tag der letzten 30 Tage, neueste oben (`tage|reverse`), erste Spalte `tag[5:]` („MM-DD"); je Nutzer ein `span.cal-dot` (16 px Kreis, Hintergrund **roh** `u.farbe`, nicht kontrastgerechnet), wenn der Nutzer an diesem UTC-Tag mindestens einen Eintrag hat. `showDays(n)` blendet Zeilen ab Index `n` aus und setzt `.active` am passenden Knopf; beim Laden `showDays(10)`. Der Tabellen-Container hat `overflow-x:auto`.
4. Link-Knopf „⚙️ Aufgaben verwalten" (`a.btn.btn-secondary`, ganze Breite) auf `/a/geholfen{tp}aufgaben`, innerhalb `{% if user.is_admin %}` (auf dieser Seite immer wahr).

Keine Diagramme, keine Zeitraumwahl außer 10/30 Tage im Kalender; die Matrix der Hauptseite kommt hier nicht vor.

#### 5.4 `geholfen_aufgaben.html` – „⚙️ Aufgaben" (Admin)

Kopfleiste: Zurück `←` auf `/a/geholfen{tp}uebersicht` (nicht auf die Hauptseite), `h1` „⚙️ Aufgaben".

1. **Formular-Karte „neu"**: bei `fehler == 'emoji'` zuerst ein `div.emoji-hinweis[role=alert]` („Für {emoji} gibt es im Portal keine Grafik – … Bitte ein anderes Emoji wählen; die Aufgabe wurde noch nicht angelegt.", Emoji mit `data-emoji-alt`). Felder: `emoji` (Text, max-width 70 px, `aria-label` „Emoji", nicht vorbelegt – auch nach dem Fehler nicht), `name` (required, vorbelegt mit `vorbelegt.name`), `gewichtung` (`type=number`, value 1.0, min 0.5, max 10, step 0.5, `aria-label` „Punkte"), Knopf „+ Hinzufügen".
2. **Liste** (`div.aufg-item`, inaktive mit `.inaktiv` = Opazität 0,4, Sortierung aktiv zuerst, dann `id`): Emoji (28 px), Name, Zeile „{gewichtung} Punkte" plus bei fehlender Grafik „⚠️ Emoji ohne Grafik – am PC unsichtbar" (rot); ✏️-Knopf (`data-klick="toggleAufgEdit"`, `data-args='[id]'`, `data-panel="aufg-edit-{id}"`, `title`=`aria-label`=„Umbenennen"); Formular `action=toggle` mit Knopf „Deaktivieren"/„Aktivieren" (kein `confirm`, reversibel); Panel `div.aufg-edit-panel#aufg-edit-{id}` mit Formular `action=umbenennen` (`name`, `aria-label` „Aufgabenname", required) und Knopf „Speichern". `toggleAufgEdit(id)` kippt `style.display` flex/none.

Nicht vorhanden: Emoji oder Gewichtung ändern, Aufgabe löschen, Sortieren per Ziehen (`ziehSortierung()` wird nicht verwendet; es gibt keine Positionsspalte), Zurück-Link zur Hauptseite.

#### 5.5 Abhängigkeiten von `base.html`

- **Klick-Verteiler**: `document.addEventListener('click')` sucht `[data-klick]`, `rufeAuf(el, name, e)` ruft `window[name]` mit `args.concat([el, e])` – erst die Werte aus `data-args` (JSON), dann das Element, dann das Ereignis. Genutzt von `waehleNutzer`, `matrixFilter`, `zelleDetails`, `zelleSchliessen`, `toggleVerlaufEdit`, `toggleAufgEdit`, `showDays`. Die Kacheln selbst hängen **nicht** am Verteiler (eigener Listener).
- **Submit-Verteiler**: `data-bestaetigen` → `confirm()` (Verlauf-Löschen). `data-fetch` und `data-arbeitet` werden in Geholfen nicht verwendet.
- **`aufzuSync()`**: setzt nach jedem Klick `aria-expanded` an allen `[data-panel]`-Knöpfen nach der Sichtbarkeit des Panels.
- **`window.dialogFuehrung(overlay, panel)`**: seit #278 global, für das Detail-Blatt.
- **`farbflaeche`/`farbtext`**: Klassen mit `--ft-dunkel`/`--ft-hell`, wechseln in `body.dark` bzw. `body.auto` unter `prefers-color-scheme: dark` (#276 hat `farbflaeche` eingeführt).
- **`--st`** (Safe-Area oben) für Toast und Sticky-Kopf; `csp_nonce` an jedem Inline-Skript; `tp` im Kontext.

### 6. Zähl- und Zeitlogik

**`_spalten(tage)`**: Aus einer Liste von `date`-Objekten (älteste zuerst) je Tag ein Dict mit `iso`, `label` („Mo 1."), `wt`, `tz` („1."), `datum_lang` („Montag, 7. September", ohne Jahr), `wochenende` (`weekday() >= 5`), `heute` (`t == tage[-1]` – „heute" ist per Definition der letzte Tag der Liste).

**`matrix_daten(ereignisse, tage, aufgaben, personen)`** – reine Funktion, ohne Datenbank:
- `ereignisse`: Iterable `(tag_iso, user_id, aufgabe_id)`; Ereignisse außerhalb der zehn `tag_isos`, mit unbekannter Aufgabe oder unbekannter Person werden übersprungen.
- `zellen[(aufgabe_id, tag)]` = Liste der `user_id`s in Eintreff-Reihenfolge; `person_tag[(uid, tag)]` = Anzahl; `gesamt[aufgabe_id]` = Summe über alle Tage im Fenster.
- Zeilen: je Aufgabe (Eingabereihenfolge `ORDER BY id`); **inaktive Aufgaben nur, wenn `gesamt > 0`**, aktive immer (auch leer). Je Zelle: `punkte` = die ersten `PUNKTE_MAX` (4) uids mit Name und Farben (`farbe_kontrast`, `farbe_kontrast_hell`), `mehr = max(0, anzahl-4)`, `anzahl`, `anteile` = `["Name Nx", …]` in Reihenfolge des ersten Auftretens, `tooltip` = „{Aufgabe}, {label} – {anteile}" (leer bei 0), `datum_lang`, `wochenende`.
- Sortierung der Zeilen: `(-gesamt, name.casefold())`, stabil; berechnet aus dem **ungefilterten** Datensatz (der Personenfilter ist rein clientseitig).
- Personenzeilen: in der übergebenen Reihenfolge; je Tag `anzahl`, `stufe = min(anzahl, 4)`, `tooltip` „{Name}, {label}: n Aufgabe(n)"; `vorname` = erstes Wort des Namens.
- Rückgabe `{"spalten", "zeilen", "personen"}`.

**`_matrix_fuer(db)`**:
- `heute = date.fromisoformat(heute_lokal())` (Familientag), `tage` = die 10 Tage bis einschließlich heute (`MATRIX_TAGE - 1` zurück).
- Personen: `users` mit Rolle `eltern` oder `kind`, `ORDER BY CASE rolle WHEN 'eltern' THEN 0 ELSE 1 END, name COLLATE NOCASE` (#44).
- Aufgaben: alle (`aktiv` mitgeliefert, `ORDER BY id`).
- Einträge: `WHERE zeitstempel >= datetime('now', '-11 days')` (`MATRIX_TAGE + 1`, Kommentar: „Einen Tag mehr holen als nötig: die Grenze liegt in UTC, der Tag in Familienzeit"), `ORDER BY zeitstempel`; jeder Zeitstempel wird per `utc_zu_lokal_datum()` auf den Familientag abgebildet. Der Filter hängt an der echten SQLite-Uhr (`datetime('now')`), die Spalten an `heute_lokal()` – zwei Kalenderquellen (siehe Abschnitt 11, #296).

**`heute_lokal()`** (00_kern): `datetime.now(LOKAL_TZ).date().isoformat()`, `LOKAL_TZ = ZoneInfo("Europe/Berlin")`. **`utc_zu_lokal_datum(text)`**: parst `YYYY-MM-DD HH:MM:SS` (nach `T`→Leerzeichen, nur die ersten 19 Zeichen), hängt UTC an, rechnet nach Berlin, gibt `date().isoformat()`; bei Parse-Fehler die ersten 10 Zeichen des Rohtexts. Sommer-/Winterzeit kommt allein aus `ZoneInfo`; eigene DST-Logik gibt es nicht. Ein Eintrag um 21:30 UTC im Sommer (23:30 Ortszeit) zählt zum selben lokalen Tag, um 22:30 UTC (00:30 Ortszeit) zum nächsten.

**`tippen`** liefert `tag = heute_lokal()` – der Spaltenschlüssel, unter dem `matrixPunkt()` den neuen Punkt einträgt. Der Eintrag selbst bekommt `datetime('now')` (UTC) als Zeitstempel.

**`uebersicht`** rechnet anders: 7-Tage-Fenster `datetime('now','-7 days')` (rollierend, nicht kalendertagsgenau), Kalender `date.today()` (Containerzeit UTC) für die 30 Tageszeilen und `GROUP BY date(zeitstempel), user_id` (UTC-Tag) für die Punkte; Zuordnung Tag→Menge der Nutzer-IDs.

Streaks, Serien, Wochenfenster oder Monatsgrenzen gibt es nicht. Es wird nichts vorberechnet oder gecacht; jede Seitenanfrage aggregiert neu.

### 7. Push-Benachrichtigungen und Hintergrund

`06_geholfen.py` importiert `push_send` nicht und enthält keinen Aufruf; es gibt keine Push-Benachrichtigung beim Tippen, Bearbeiten, Löschen oder bei Aufgabenänderungen. Es gibt keinen Hintergrund-Thread, keinen Schalter in `app.py`/`conftest.py` und keinen Eintrag im `util`-Scheduler. Das Morning-Briefing (`27_briefing.py`) bezieht keine Geholfen-Daten ein (kein Vorkommen von „geholfen" in der Datei).

### 8. Verflechtungen

- **Startseite:** Die Kachel kommt generisch aus `apps` × `grants` (`01_start_token.py`), Emoji 🙋, Beschreibung „Geholfen-Protokoll". Kein Auto-Grant, keine Sonderbehandlung, keine Kennzahl auf der Kachel.
- **Hamburger-Menü (`base.html`):** App-Block mit „📜 Zuletzt geholfen" (jeder mit Grant) und „📊 Statistik" (Admin), eingeführt mit #28/#30/#32; verbindliche Menüstruktur in `server.md` „Hamburger-Menü".
- **Aufgabenplan (`13_kinderplan.py`, Wünsche #36, #91, #92, #115):** liest `geholfen_aufgaben WHERE aktiv=1` als Aufgabenkatalog; `kinderplan_eintraege.aufgabe_id` ist FK darauf (CASCADE); `/abhaken` schreibt `INSERT INTO geholfen_eintraege(aufgabe_id, user_id)` – dieselbe Tabelle, kein eigener Erledigt-Zustand; der Erledigt-Status je Tag wird per `date(zeitstempel)` (UTC) aus `geholfen_eintraege` abgeleitet; `/zuweisen` und `/abhaken` prüfen, dass die Aufgabe aktiv ist. Ein Abhaken im Plan erscheint also in Verlauf, Matrix und Übersicht der Geholfen-App; umgekehrt kennt die Geholfen-App den Plan nicht.
- **Todo (`04_todo.py`):** Docstring von `todos_neu()` nennt Geholfen als möglichen Aufrufer; `06_geholfen.py` importiert `teile.todo` nicht und legt keine Todos an. Kein Alias `teile.geholfen` in `teile/__init__.py`; kein anderes Modul importiert aus `06_geholfen.py`.
- **Kassenbuch (`22_kassenbuch.py`):** kein Bezug (keine Umrechnung von Punkten oder Gewichtung in Taschengeld; `gewichtung` wird nur in der Übersicht summiert).
- **Briefing, Geburtstage, Push:** kein Bezug.
- **Twemoji/Emoji-Prüfung (`00_kern.py`, #275):** `TWEMOJI_SVG_DIR = src/static/twemoji/svg/`, `twemoji_datei(zeichen)` (Codepoints mit `-`, `fe0f` fällt weg, solange kein `200d` in der Folge), `emoji_grafik_vorhanden(text)` (ganze Folge oder jedes einzelne Zeichen ≥ U+2190 muss als Datei liegen; leerer Text gilt als vorhanden). `aufgaben_verwalten` nutzt beides; `base.html` ersetzt nicht ladbare Emoji-Bilder durch das Zeichen. `tests/test_emoji.py` prüft nur Vorlagen/Quelltext, deshalb die Laufzeitprüfung.
- **Sportschau (`14_sportschau.py`, #62):** hat die CSS-Klassen der alten Geholfen-Heatmap übernommen (journal 2026-07-29); seit #276 hat Geholfen selbst keine Heatmap-Klassen mehr.
- **Kontrastfarben (`farbe_kontrast`, `farbe_kontrast_hell`, #237):** in `matrix_daten` serverseitig je Person gerechnet (Ziel 4,5:1 gegen `#f5f5f7` bzw. `#2c2c2e`); in den Vorlagen zusätzlich direkt als Jinja-Funktionen (Nutzer-Pillen, Avatare, Verlauf-Namen).
- **Live-Prüfung (`scripts/live_pruefung.py`):** ruft die App-Seite je Nutzer auf (journal: „Geholfen 74 ms"); `pruefplan.md` S2-05/S5-03/S5-15 enthalten Handprüfungen (Kiosk-Antippen, Verlauf bearbeiten/löschen).

### 9. Konstanten und Konfiguration

Modul `06_geholfen.py`:

| Name | Wert | Bedeutung |
|---|---|---|
| `APP` | `"geholfen"` | Slug für `check_grant` |
| `MATRIX_TAGE` | `10` | Tage in Matrix und Personenstreifen; SQL-Fenster `MATRIX_TAGE + 1` |
| `WOCHENTAG_KURZ` | `["Mo", …, "So"]` | Kopfzeile |
| `WOCHENTAG_LANG` | `["Montag", …, "Sonntag"]` | `datum_lang` im Detail-Blatt |
| `MONAT_LANG` | `["Januar", …, "Dezember"]` | `datum_lang` |
| `PUNKTE_MAX` | `4` | Punkte je Zelle, Rest als „+n" (#276) |
| `QUADRAT_STUFEN` | `{1: 18, 2: 26, 3: 34, 4: 40}` | Kantenlängen px; wird an die Vorlage übergeben (`quadrat_stufen`), dort aber nicht verwendet – die Vorlage hat die Werte in CSS (`.quadrat.g1`–`.g4`) fest kodiert |

In den Vorlagen fest verdrahtet: JS `PUNKTE_MAX = 4` (Duplikat), Stufen-Deckel `Math.min(n, 4)`, Toast 2000 ms, Flash 600 ms, Kachelraster 3/4/5 Spalten bei 500/700 px, Mobile-Breakpoint 599 px, Chips ab > 5 Personen schiebbar, Sticky-Kopf `top: var(--st) + 62px`, Punkt 9 px (Handy 7 px), Zellhöhen 44/48 px (Handy 28 px), Handy-Quadrate 12/18/24 px, Verlauf `LIMIT 50`, Übersicht 7 Tage/30 Tage/Kalender-Umschalter 10|30, Gewichtungsfeld min 0,5 / max 10 / Schritt 0,5, Emoji-Default 👍, Gewichtungs-Default 1.0.

Es gibt keine `.env`-Variable und keinen Stufenschalter für diese App.

### 10. Wunsch-Historie

Aus `wuensche_geholfen.txt` (App-Tag `geholfen`), chronologisch aufsteigend; Umsetzungsversion aus `journal.md`, wo genannt:

- #2 – Nach neuem Eintrag soll sich die „Zuletzt"-Liste aktualisieren (erledigt; Ticker später mit #28 entfernt)
- #3 – Übersicht, welcher Nutzer in den letzten 10 bzw. 30 Tagen an welchem Tag geholfen hat → 30-Tage-Kalender in der Übersicht (erledigt)
- #5 – Eltern können Einträge für andere machen; Rollen `eltern`/`kind`/`gast`, Admin als Zusatzrecht (erledigt)
- #27 – Kacheln kleiner, mehr Platz für Statistik darunter (erledigt, v18)
- #28 – Liste der letzten Einträge auf eigene Seite, erreichbar über Hamburger-Menü (erledigt, v18)
- #29 – 10-Tage-Heatmap je Nutzer (Eltern/Kind) unter den Kacheln, grün/grau (erledigt, v18; seit #276 durch Personenstreifen ersetzt)
- #30 – Statistik-Knopf ins Hamburger-Menü (erledigt, v18)
- #31 – Verlauf: Eltern dürfen Einträge editieren (✏️), Löschen mit Abfrage (erledigt, v19)
- #32 – Hamburger-Menü: Startseite immer ganz oben, App-Block, allgemeiner Block (erledigt, v19; portalweit)
- #44 – Heatmap: erst Eltern, dann Kinder (erledigt, v30; Sortierung gilt weiter für den Personenstreifen)
- #64 – „App, mit der ich Tiere selber entwerfen kann" (erledigt; unter `geholfen` eingetragen, umgesetzt als Tierbaukasten)
- #96 – Aufgaben umbenennen/ergänzen: „Spülmaschine einräumen", „Wäsche zusammenlegen", neu „Spülmaschine ausräumen"; Umbenennen-Panel in der Verwaltung (erledigt, v94)
- #275 – Icon von „Staubwischen" (🪄) am PC nicht sichtbar → lokale Grafik nachgeholt, Laufzeitprüfung `emoji_grafik_vorhanden`, Ablehnung/Warnung in der Verwaltung, Fallback in `base.html` (erledigt, v253)
- #276 – Spezifikation „Visualisierung erledigter Aufgaben": Punktmatrix + Personenstreifen, CSS Grid ohne Bibliothek, Familientag statt UTC, `farbflaeche` (erledigt, v253)
- #277 – Sichtbarer Abstand zwischen den beiden Grafiken (erledigt; eigener Titel „👤 Je Person", 22 px, Trennlinie)
- #278 – Korrektur Mobile-Layout: kein waagerechtes Scrollen, Label über dem Raster, zweizeiliger Sticky-Kopf, Tap statt Hover (Detail-Blatt über `dialogFuehrung`) (erledigt)
- #296 – `test_eintrag_kurz_vor_mitternacht_zaehlt_zum_familientag` ist datumsabhängig rot (18.09. rot, 17.09. grün, auch auf unverändertem Stand) (offen, ohne Priorität, angelegt 18.09.2026)

Nicht als eigener Wunsch geführt, aber im Journal: Erstbau am 2026-07-27 mit 8 Seed-Aufgaben, 7-Tage-Statistik und Aufgabenverwaltung; Sicherheitshärtung gleichen Tags (`to_int()` für `fuer_user_id`, DOM-API statt `innerHTML`); #36 Aufgabenplan schreibt in `geholfen_eintraege`; #115 Plan-Zuweisungen als Einzeltermine.

### 11. Bekannte Eigenheiten und offene Punkte

Aus Code, Kommentaren, `server.md` und `journal.md`, ohne Bewertung:

- **#296 (offen):** `test_eintrag_kurz_vor_mitternacht_zaehlt_zum_familientag` patcht `heute_lokal` auf 2026-09-07 und fügt einen Eintrag mit Zeitstempel `2026-09-06 21:30:00` ein; `_matrix_fuer` filtert aber zusätzlich mit `datetime('now', '-11 days')` gegen die echte Uhr. Journal 18.09.: „der Test hängt offenbar an einer zweiten Stelle am echten Kalender". Nur genannt, nicht umgesetzt.
- **Zwei Kalenderquellen in `_matrix_fuer`:** Spalten aus `heute_lokal()` (Berlin), SQL-Fenster aus `datetime('now')` (UTC), ein Tag Puffer.
- **Übersicht rechnet in UTC:** `date.today()` und `date(zeitstempel)`; die Hauptseite in Familienzeit. Dasselbe UTC-Muster im Aufgabenplan (`date(zeitstempel)`).
- **Verlauf zeigt und bearbeitet Rohzeit:** `zeitstempel[:16]` ohne `utc_zu_lokal()`; das `datetime-local`-Feld wird mit dem UTC-Wert vorbelegt und der eingegebene Wert unverändert als neuer Zeitstempel gespeichert.
- **Deaktivierte Aufgaben** bleiben im Verlauf-Select wählbar, in der Matrix nur mit Einträgen im Fenster; per `tippen` (404) und im Aufgabenplan nicht nutzbar.
- **„Als wer?" listet alle Nutzer** (auch `gast`, auch Admins); Matrix und Streifen zeigen nur `eltern`/`kind`. Ein Eintrag für einen Gast ist im Verlauf und in der Übersicht sichtbar, nicht in der Matrix; `matrixPunkt()` findet dann keine Person in `PERSONEN` und tut nichts.
- **`quadrat_stufen`** wird an die Vorlage übergeben, dort aber nicht verwendet (CSS-Werte fest kodiert); `PUNKTE_MAX` existiert in Python und JS getrennt.
- **`umbenennen`** prüft die Existenz der `id` nicht; `toggle` schon. `neu` prüft `gewichtung` nur auf `float`-Parsbarkeit, die Grenzen 0,5–10 stehen nur im HTML.
- **Emoji-Feld** ist nach der Ablehnung (#275) leer, der Name bleibt stehen (`vorbelegt.emoji` wird nur im Hinweis gezeigt).
- **Zurück-Link der Aufgabenverwaltung** führt zur Übersicht, nicht zur Hauptseite (journal 2026-07-27: „geholfen_aufgaben.html → ← Übersicht").
- **Fetch-Fallback:** Bei Netzfehler schickt das Skript ein Formular ohne `fuer_user_id` ab – der Eintrag landet dann beim Tipper, nicht bei der gewählten Person.
- **Sticky-Kopf:** Spezifikation #276 verlangte einen klebenden Spaltenkopf; v253 hatte ihn nicht (Scroll-Container), seit #278 gibt es keinen Scroll-Container mehr und `.mx-kopf` klebt mit `top: calc(var(--st) + 62px)` (fester Wert für die Höhe der App-Leiste).
- **Kopfschrift 12 px** statt der im Wunsch #276 genannten 11 px (Regel #238, `server.md`).
- **Kein `title`** in der Matrix (#278, vom Test geprüft); Tooltip-Text nur als `aria-label`.
- **Sortierung der Kacheln** ist `ORDER BY id`; es gibt keine Positionsspalte und kein Umsortieren.
- **Docstring-Hinweis:** „ein Eintrag um 23:30 gehört zum heutigen Tag, nicht zu morgen" – bezieht sich auf die alte UTC-Heatmap (#29), die einen 23:30-Eintrag (21:30 UTC) am Vortag bzw. – je nach Perspektive – am falschen Tag zeigte.
- **`server.md` „Bekannte Issues"** enthält keinen Eintrag zu Geholfen; die Beschreibung der Vorlagen dort (Zeile 1723) nennt noch „10-Tage-Heatmap je Nutzer".
- **`_gesperrter_wochentag()` in `06_geholfen.py`** wird im Journal (2026-07-29, Rezepte) erwähnt; die Funktion existiert im aktuellen Modul nicht (sie gehört zum Aufgabenplan).
- **`todos_neu()`-Docstring** nennt Geholfen als Aufrufer; es gibt keinen solchen Aufruf.

### 12. Tests

- `tests/test_geholfen_matrix.py` (Wunsch #276–#278, 8 Tests): prüft `matrix_daten()` ohne Datenbank (Spaltenköpfe „Sa 29." … „Mo 7.", `wt`/`tz`, `datum_lang`, Wochenende/Heute; Zeilen nach Häufigkeit dann alphabetisch; inaktive Aufgabe nur mit Eintrag; ab fünf vier Punkte plus „+2" mit Tooltip/Anteilen; Stufen 0–4 des Personenstreifens bei erhaltener Anzahl; Ereignisse außerhalb/unbekannt fallen weg), die gerenderte Seite (zehn Kopfzellen zweizeilig, Chips mit `aria-pressed`, vier Punkte + „+1", `g4`-Quadrat, Legende, genau eine Zelle als `zelleDetails`-Knopf mit `data-args`/`aria-label`, kein `title` in der Matrix, `role=dialog`, `ps-titel`, `name-kurz`), dass `tippen` per fetch `tag=heute_lokal()` liefert, und – derzeit datumsabhängig rot (#296) – dass ein Eintrag 21:30 UTC zum lokalen Vortag zählt.
- `tests/test_emoji_grafik.py` (Wunsch #275): Dateinamen-Regel `twemoji_datei` (fe0f mit/ohne ZWJ), `1fa84.svg` liegt lokal, `/aufgaben` lehnt ein Emoji ohne Grafik mit 302 `?fehler=emoji` ab (Name bleibt im Formular, nichts angelegt), legt mit Grafik an, markiert bestehende Aufgaben ohne Grafik genau einmal.
- `tests/conftest.py`: führt `geholfen_aufgaben` in `BLEIBT` (Seeds bleiben), die Testfamilie (TestAdmin eltern+admin, TestKind, TestEltern) hat standardmäßig keinen Geholfen-Grant – die Geholfen-Tests legen ihn per Fixture selbst an.
- `tests/test_routen_inventar.py`: erwartet den Endpunkt `geholfen_app` und verlangt für jede ändernde Route eine `<token>`-Regel (alle fünf POST-Routen erfüllen das).
- Portalweite Wächter, die die vier Vorlagen mitlesen: `test_seiten_erreichbar.py` (Rauchtest aller GET-Seiten), `test_tippflaeche.py`, `test_aria_labels.py`, `test_loeschen_symbol.py` (🗑️ im Verlauf), `test_kopfleiste.py`, `test_emoji.py`, `test_csp.py` (keine Inline-Handler), `test_formular_labels.py`, `test_ueberschriften.py`, `test_farbkontrast.py`, `test_interaktion.py`, `test_verteiler_argumente.py`, `test_darkmode.py`, `test_hilfe_kapitel.py` (Kapitel 5 und 7 als `<details class="section" id="kapitel-N">`).

---

## App „Aufgabenplan" (kinderplan)

Stand: 2026-09-19, gelesen aus `src/teile/13_kinderplan.py` (388 Zeilen), `src/teile/templates/kinderplan.html` (277 Zeilen), `src/teile/04_todo.py` (Serien-Schnittstelle), `src/teile/00_kern.py` (Schema, Migrationen, Seed), `src/teile/__init__.py`, `src/teile/templates/base.html` (Verteiler), `src/teile/templates/hilfe.html` (Kapitel 11, „Die Apps"), `server.md`, `journal.md` und `tests/`.

### 1. Zweck und Zielgruppe

Der Aufgabenplan (Slug `kinderplan`, Anzeigename „Aufgabenplan", Emoji 🗓️, Blueprint `kinderplan_app`, URL-Präfix `/a/kinderplan/<token>/`) ist eine **rollierende 14-Tage-Liste** (aktuelle Kalenderwoche ab Montag plus die folgende Woche), analog zum Essensplan (`12_essensplan.py`). Je Kalendertag zeigt er für **eine Person** (ein Kind oder ein Elternteil) zwei Arten von Einträgen:

- **Geholfen-Aufgaben** als Einzeltermine – Aufgaben aus dem Katalog der Geholfen-App (`geholfen_aufgaben`), die für genau diesen einen Tag zugewiesen wurden (Tabelle `kinderplan_eintraege`, Spalte `plan_tag`).
- **Pool-Instanzen** – wiederkehrende Aufgaben-Vorlagen der Todo-App (`todo_serien`), die für genau diesen Tag „aus dem Pool geholt" wurden; jede ist eine normale `todos`-Zeile mit gesetztem `serie_id` und `plan_tag`.

Am heutigen Tag lassen sich Geholfen-Aufgaben abhaken; das schreibt direkt einen Datensatz in `geholfen_eintraege` und zählt damit in der Geholfen-App und deren Statistik mit. Pool-Instanzen lassen sich an jedem sichtbaren Tag abhaken (Status-Toggle in `todos`) oder per ↩️ „zurück in den Pool legen" (Löschen der `todos`-Zeile).

Zielgruppe laut Modul-Docstring und Hilfe: Kinder und Eltern (seit Wunsch #91 haben auch Eltern einen eigenen Plan; ursprünglich, Wunsch #36, nur Kinder). Jedes Familienmitglied mit Grant sieht alle Kind-/Eltern-Pläne, bearbeiten darf man den eigenen; Eltern und Admin dürfen jeden Plan bearbeiten. Ab 20 Uhr deutscher Zeit ist der jeweils nächste Kalendertag für Kinder gesperrt.

Der Seed-Text der App in `00_kern.py` (`_CORE_APPS`, Zeile 577) lautet „Wiederkehrende Aufgaben wochentagsweise planen"; der Text unter „Die Apps" in `hilfe.html` lautet „Kinder ordnen wiederkehrende Aufgaben Wochentagen zu und haken sie ab – das zählt direkt in der Geholfen-App. Jedes Kind sieht auch die Pläne der Geschwister, editieren kann es nur den eigenen. Ab 20 Uhr ist der Plan für den nächsten Tag nur noch für Eltern änderbar." Beide Texte stammen aus der Zeit vor #91/#92/#115 (Wochentag-Raster, nur Kinder). Die App ist **nicht** in einer `_auto_grant_all()`-Liste; Grants werden per `manage.py grant` vergeben (server.md: alle 4 Nutzer haben den Grant).

Es gibt keine Hintergrund-Threads, keine Push-Nachrichten und keine KI-Nutzung in diesem Modul.

### 2. Datenmodell

#### Tabelle `kinderplan_eintraege` (SCHEMA in `00_kern.py`, Zeile 264 ff.)

| Spalte | Typ | Bedeutung | Default / Constraint |
|---|---|---|---|
| `id` | INTEGER PRIMARY KEY | Laufende Nummer | – |
| `user_id` | INTEGER NOT NULL | Person, deren Plan der Eintrag ist | `REFERENCES users(id) ON DELETE CASCADE` |
| `aufgabe_id` | INTEGER NOT NULL | Geholfen-Aufgabe aus `geholfen_aufgaben` | `REFERENCES geholfen_aufgaben(id) ON DELETE CASCADE` |
| `wochentag` | INTEGER NOT NULL | 0 = Montag … 6 = Sonntag. Seit #115 **nur noch informativ**, wird bei jedem `zuweisen` aus `tag_datum.weekday()` mitgeschrieben, aber für die Anzeige nicht mehr ausgewertet | kein Default (muss gesetzt werden) |
| `plan_tag` | TEXT | ISO-Datum `YYYY-MM-DD` – der eigentliche Einzeltermin (Wunsch #115) | NULL erlaubt laut Schema; der Code schreibt immer einen Wert |
| `position` | INTEGER NOT NULL | Sortierreihenfolge innerhalb eines Tages (`ORDER BY k.plan_tag, k.position`); wird vom Code nie gesetzt, bleibt 0 | `DEFAULT 0` |
| `erstellt` | TEXT NOT NULL | UTC-Zeitstempel | `DEFAULT (datetime('now'))` |
| – | UNIQUE | `UNIQUE(user_id, aufgabe_id, plan_tag)` – dieselbe Aufgabe kann derselben Person am selben Tag nur einmal zugewiesen sein | – |

Kein Fremdschlüssel zeigt **auf** `kinderplan_eintraege` (Migrations-Kommentar in `00_kern.py`: darum war der RENAME+Neubau gefahrlos).

#### Bezug zu `todos` / `todo_serien` (Pool-Instanzen)

Die zweite Eintragsart lebt **nicht** in `kinderplan_eintraege`, sondern in `todos`. Relevante Spalten von `todos` (Schema Zeile 99 ff. plus Migrationen Zeile 2249 ff.):

| Spalte | Bedeutung im Aufgabenplan |
|---|---|
| `inhalt` | Text der Instanz, beim Einsortieren aus `todo_serien.inhalt` kopiert |
| `erstellt_von` | Nutzer, der eingeplant hat (`user["id"]` des Aufrufers, nicht die Zielperson) |
| `zugewiesen_an` | Zielperson; Filter für die Plan-Anzeige (`ON DELETE SET NULL`) |
| `serie_id` | `REFERENCES todo_serien(id) ON DELETE SET NULL` – nur Zeilen mit `serie_id IS NOT NULL` erscheinen im Plan |
| `plan_tag` | ISO-Datum des Kalendertags (Wunsch #92) |
| `wochentag` | totes Altfeld aus #90 (nie mit Produktivdaten gefüllt), bleibt NULL |
| `status` | `'offen'` beim Einsortieren; `serie_erledigen` setzt `'erledigt'`/`'offen'` |
| `erledigt`, `erledigt_am` | Häkchen-Zustand; `serie_erledigen` setzt `erledigt_am = datetime('now')` (UTC) bzw. NULL |

`todo_serien` (Schema Zeile 109 ff.): `id`, `inhalt`, `wiederkehr_typ` (`'intervall'` Default oder `'wochentag'`), `intervall_tage`, `fester_wochentag` (totes Altfeld seit #112), `feste_wochentage` (TEXT, kommagetrennt, z. B. `"1,3,5"`), `aktiv` (Default 1), `erstellt_von` (`ON DELETE SET NULL`), `erstellt`. Verwaltet ausschließlich in der Todo-App unter `/a/todo/<token>/serien`.

**„Eigene" vs. „aus Serie":** Im Plan sind „eigene" Einträge die Geholfen-Zuweisungen aus `kinderplan_eintraege` (Template-Liste `tag.eintraege`, Zeile mit Emoji + Name der Aufgabe); „aus Serie" sind `todos`-Zeilen mit `serie_id IS NOT NULL` und `plan_tag` im Fenster (Template-Liste `tag.serien_eintraege`, mit 🔁-Präfix). Ein normales Todo ohne `serie_id` erscheint im Plan nie, auch wenn es `plan_tag` hätte.

**Erledigt-Status der Geholfen-Einträge** wird nicht gespeichert, sondern je Anzeige aus `geholfen_eintraege` abgeleitet: `(aufgabe_id, date(zeitstempel))` im 14-Tage-Fenster für die Zielperson; ein Eintrag gilt als erledigt, wenn das Paar `(aufgabe_id, plan_tag)` darin vorkommt. `date(zeitstempel)` arbeitet auf dem UTC-Zeitstempel von SQLite (siehe Abschnitt 7).

#### Migrationen (in `_init_db()`, `00_kern.py`)

1. **#90/#92 – `todos`:** `ALTER TABLE ADD COLUMN` für `status`, `serie_id`, `wochentag` (tot), `plan_tag` (Zeile 2249–2265, idempotent per try/except).
2. **#112 – `todo_serien.feste_wochentage`:** neue Spalte, Backfill `feste_wochentage = CAST(fester_wochentag AS TEXT)` (Zeile 2437–2443).
3. **#115 – `kinderplan_eintraege` Neubau** (Zeile 2535–2597): Da SQLite den UNIQUE-Constraint nicht per ALTER ändern kann (`(user_id,aufgabe_id,wochentag)` → `(user_id,aufgabe_id,plan_tag)`), wird die Tabelle nach `kinderplan_eintraege_alt` umbenannt, neu angelegt, und jede alte Wochentag-Regel wird für jeden passenden Tag des **beim Deploy sichtbaren** 14-Tage-Fensters (Montag der aktuellen Woche + 13 Tage, berechnet mit `date.today()`, nicht mit Zeitzone) per `INSERT OR IGNORE` zu einem Einzeltermin materialisiert; danach `DROP TABLE kinderplan_eintraege_alt`. Wiederaufsetz-Signal ist die Existenz der Alt-Tabelle, nicht das Fehlen der Spalte (ein erster Deploy-Versuch war nach RENAME+CREATE abgestürzt, weil die Migrationsverbindung keine `row_factory=Row` hat – Zugriff nur per Tupel-Index). Produktiv migriert wurde genau eine Regel (Friederike, „Tisch decken", mittwochs → 2026-07-29 und 2026-08-05). Wochen nach dem Fenster haben keine automatische Fortsetzung.

### 3. Rollen und Rechte

- **Zugang:** `_user(token)` ruft `grant(token, "kinderplan")`; ohne Grant → 403. Gilt für jede Route. Jede Route hat zusätzlich die token-freie Zwillingsregel (`defaults={"token": None}`), die über das Sitzungs-Cookie autorisiert (#140).
- **Sicht (familienweit):** `index` lädt `kinder = users WHERE rolle IN ('kind','eltern') ORDER BY rolle='eltern', name` (Kinder zuerst, dann Eltern, jeweils alphabetisch). Die Zielperson kommt aus `?fuer=<id>` (per `to_int`); ist sie nicht gesetzt oder keine Kind/Eltern-Rolle, fällt der Code auf den **eigenen** Nutzer zurück, wenn dieser selbst `kind` oder `eltern` ist, sonst (z. B. Admin ohne Rolle, Gast) auf den ersten Eintrag von `kinder`. Gibt es niemanden, ist `ziel = None` („Noch niemand angelegt"). Jeder Nutzer mit Grant – auch ein Gast – kann alle Pläne **ansehen**.
- **Bearbeiten:** `_darf_verwalten(user)` = `is_admin` oder `rolle == 'eltern'`. `darf_editieren = ziel and (user.id == ziel.id or _darf_verwalten(user))`. Ein Kind darf nur den eigenen Plan ändern; Eltern/Admin jeden. Dieselbe Prüfung serverseitig in `zuweisen`, `abhaken`, `serie_einsortieren_route` (gegen `ziel_id`) und in `serie_zuruecklegen`/`serie_erledigen` (gegen `todos.zugewiesen_an`).
- **Ziel-Nutzer-Prüfung:** `zuweisen`, `abhaken`, `serie_einsortieren_route` prüfen `SELECT 1 FROM users WHERE id=? AND rolle IN ('kind','eltern')` → sonst 404. Ein Admin ohne Rolle `kind`/`eltern` und ein Gast können also kein Ziel sein, auch nicht für sich selbst. `serie_zuruecklegen`/`serie_erledigen` prüfen nur die Existenz der `todos`-Zeile mit `serie_id IS NOT NULL` (404), nicht die Rolle von `zugewiesen_an`; ist `zugewiesen_an` NULL, kommt nur `_darf_verwalten` durch.
- **20-Uhr-Sperre:** `_gesperrter_tag_datum()` liefert ab 20:00 Uhr Europe/Berlin das Datum von morgen, sonst `None`. Wirkung: in `index` ist `tag.gesperrt = (d == gesperrter_tag) and not _darf_verwalten(user)`; im Template fallen dann ✏️-Knopf und Bearbeiten-Panel weg, ein 🔒-Badge „nur Eltern" erscheint. Serverseitig lehnen `zuweisen` und `serie_einsortieren_route` mit 403 ab, wenn `tag_datum == _gesperrter_tag_datum()` und der Aufrufer nicht verwalten darf. **Nicht** von der Sperre betroffen: `abhaken` (nur „heute" im UI, serverseitig ohne Datumsprüfung), `serie_erledigen` und `serie_zuruecklegen` (keine Datumsprüfung). Eltern/Admin sind immer ausgenommen, auch am eigenen Plan.
- **Sonderfälle:** Die Sperre hängt am Nutzer (`_darf_verwalten`), nicht am Ziel – ein Kind, das seinen eigenen Plan bearbeitet, ist gesperrt; ein Elternteil auf einem Kinderplan nicht. Vergangene Tage sind serverseitig **nicht** gesperrt; `zuweisen` und `serie_einsortieren_route` nehmen jedes gültige ISO-Datum an, auch außerhalb des 14-Tage-Fensters (die UI bietet dafür nur keine Knöpfe). `abhaken` prüft nicht, ob die Aufgabe für heute zugewiesen ist – jeder gültige `aufgabe_id` mit `aktiv=1` wird als Geholfen-Eintrag mit `datetime('now')` angelegt.

### 4. Routen

Alle Pfade existieren doppelt: `/a/kinderplan/<token>/…` und token-frei `/a/kinderplan/…` (Cookie-Sitzung). Redirects gehen an `url_for("kinderplan_app.index", token=token, fuer=<ziel_id>)`; ohne Anker.

| Methode | Pfad (nach `/a/kinderplan[/<token>]/`) | Funktion | Zweck | Eingaben und Validierung | Antwort |
|---|---|---|---|---|---|
| GET | `` (leer) | `index` | 14-Tage-Plan einer Person | Query `fuer` (via `to_int`; unbekannte/ungültige ID → Fallback wie in Abschnitt 3) | HTML `kinderplan.html` |
| POST | `zuweisen` | `zuweisen` | Geholfen-Aufgabe für einen Tag zuweisen bzw. wieder entfernen (Toggle) | Form: `ziel_id`, `aufgabe_id` (beide `to_int`, fehlend → 400), `tag` (ISO; `date.fromisoformat` schlägt fehl → 400). Ziel muss `kind`/`eltern` (404), Aufrufer eigener Plan oder `_darf_verwalten` (403), Sperrtag ohne Verwaltungsrecht (403), Aufgabe muss `aktiv=1` (404) | Redirect auf `index?fuer=ziel_id` |
| POST | `abhaken` | `abhaken` | Geholfen-Aufgabe als erledigt registrieren | **JSON-Body** `{ziel_id, aufgabe_id}` (`request.get_json(silent=True)`, `to_int`; fehlend → 400). Ziel `kind`/`eltern` (404), Rechte (403), Aufgabe `aktiv=1` (404). Kein Datum, keine Sperrprüfung, kein Duplikat-Check | JSON `{ok: true, aufgabe: <name>, emoji: <emoji>}` |
| POST | `serie_einsortieren` | `serie_einsortieren_route` | Pool-Vorlage für Person + Tag einsortieren | Form: `ziel_id`, `serie_id` (`to_int`, fehlend → 400), `tag` (ISO, sonst 400). Ziel `kind`/`eltern` (404), Rechte (403), Sperrtag (403). Danach `serie_einsortieren(db, serie_id, ziel_id, tag_iso, user.id)`; dessen Rückgabe `False` (Serie inaktiv/unbekannt/nicht verfügbar) wird **nicht** ausgewertet | Redirect auf `index?fuer=ziel_id` (auch wenn nichts eingefügt wurde) |
| POST | `serie_zuruecklegen/<int:tid>` | `serie_zuruecklegen` | Pool-Instanz löschen („zurück in den Pool") | `tid` aus Pfad; Zeile muss in `todos` mit `serie_id IS NOT NULL` existieren (404); Aufrufer = `zugewiesen_an` oder `_darf_verwalten` (403). `DELETE FROM todos WHERE id=?` | Header `X-Requested-With: fetch` → JSON `{ok: true}`; sonst Redirect auf `index?fuer=zugewiesen_an` |
| POST | `serie_erledigen/<int:tid>` | `serie_erledigen` | Pool-Instanz abhaken / zurücknehmen (Toggle) | wie oben (404/403). `neu = 0 if erledigt else 1`; `UPDATE todos SET status='erledigt'|'offen', erledigt=neu, erledigt_am=datetime('now')|NULL` | Header `X-Requested-With: fetch` → JSON `{ok: true, erledigt: bool}`; sonst Redirect |

Keine Route nutzt `antwort_oder_weiter()` oder `data-fetch`; die JSON-Fälle sind von Hand über den Header `X-Requested-With` (bzw. bei `abhaken` immer JSON) gelöst. CSRF-Schutz kommt zentral aus `20_csrf.py` (Sec-Fetch-Site/Origin-Prüfung), nicht aus dem Modul.

### 5. UI (`kinderplan.html`)

Erweitert `base.html`; `app_slug = "kinderplan"`, Titel „Aufgabenplan". Kopfzeile: `<h1 class="nav-title">🗓️ Aufgabenplan</h1>` plus `nav-sub` mit dem Namen der Zielperson (oder „Noch niemand angelegt"). Die Vorlage nutzt die Kontext-Variable `tp` (aus `token_pfad()` in `00_kern.py`: `/<token>/` oder `/` bei token-freien URLs) für alle Formular-Actions und Fetch-Pfade.

Aufbau von oben nach unten innerhalb `<main class="main" id="main">`:

1. **Personenwahl „Wessen Plan?"** (`.nutzer-picker`) – nur wenn `kinder|length > 1`. Eine Reihe von `<a class="nutzer-pill knopf">`-Links mit `href="?fuer=<id>"`; die aktive Pill trägt Klasse `aktiv` (weiße Schrift) und als Inline-Hintergrund `farbe_kontrast(k.farbe)` (Nutzerfarbe, kontrastfest). Ein Wechsel ist ein normaler Seitenaufruf.
2. **Leerzustand** – ohne `ziel`: zentrierter Text „Noch niemand angelegt."
3. **„Aktuelle Woche"** (`.woche-header`) – wenn es vergangene Tage gibt, ein `<details class="vergangene-block">` mit `<summary>` „N vergangene(r) Tag(e)" (▸ dreht sich beim Öffnen); darin die vergangenen Tageskarten. Danach die restlichen Karten der aktuellen Woche (heute und Zukunft).
4. **„Nächste Woche"** (`.woche-header.naechste`) – sieben weitere Tageskarten.

**Tageskarte** (Makro `tag_karte(tag, token, ziel, aufgaben, darf_editieren)`), `.tag-card` mit Statusklasse `vergangen` (Opazität 0,6), `heute` (2-px-Ring in `var(--farbe)`) oder `zukunft`, zusätzlich `gesperrt` (Opazität 0,7):

- Kopfzeile: Wochentagsname (`WOCHENTAGE[wd]`), Datum `dd.mm.`, bei Sperre `🔒 nur Eltern`; bei `darf_editieren and not tag.gesperrt` ein ✏️-Knopf (`.tag-edit-toggle`, `data-klick="togglePlan"`, `data-args='["<iso>"]'`, `data-panel="plan-edit-<iso>"`, `title`/`aria-label` „Bearbeiten"). Der ✏️-Knopf erscheint auf **allen** Karten, auch vergangenen.
- Einträge, sonst „Nichts geplant" (`.tag-leer`):
  - **Geholfen-Zeile** (`.aufgabe-row`, `done` wenn erledigt): Nur am Tag mit `status == 'heute'` und `darf_editieren` ein echter Knopf `.aufgabe-check` (`data-klick="abhaken"`, `data-args='[ziel.id, e.aufgabe_id]'`, `disabled` wenn schon erledigt, Inhalt ✓ bei erledigt); an allen anderen Tagen oder ohne Recht ein `.aufgabe-check-ghost`-Kreis (✓ falls erledigt, sonst leer). Danach `emoji name`. Abhaken eines vergangenen oder künftigen Tages ist in der UI nicht möglich; ein Häkchen kann nicht zurückgenommen werden.
  - **Serien-Zeile** (`.aufgabe-row`): bei `darf_editieren` Knopf `.aufgabe-check` mit `data-klick="serieErledigen"`, `data-args='[e.id]'` (`disabled` wenn erledigt) – **an jedem** der 14 Tage, nicht nur heute; sonst Ghost-Kreis. Text `🔁 inhalt` (flex:1). Bei `darf_editieren` rechts ↩️-Knopf `.btn-zuruecklegen` mit `data-klick="serieZuruecklegen"`, `data-args='[e.id]'`, `title`/`aria-label` „Zurück in den Pool legen" – auch bei erledigten Instanzen und auf gesperrten/vergangenen Karten sichtbar. Kein `data-bestaetigen`, obwohl es ein echtes Löschen ist.
- **Bearbeiten-Panel** `#plan-edit-<iso>` (`.tag-edit-panel`, initial `display:none`), nur bei `darf_editieren and not tag.gesperrt`:
  - Etikett „Aufgaben für <Wochentag>, <dd.mm.>"
  - `.btn-row` mit je einem **Formular pro aktiver Geholfen-Aufgabe** (`method=post`, `action="/a/kinderplan{{ tp }}zuweisen"`, `style="display:contents"`): Hidden `ziel_id`, `aufgabe_id`, `tag`; Submit-Knopf `.chip-btn` mit `emoji name`, Klasse `active` (Hintergrund `var(--farbe-band)`, weiße Schrift), wenn die Aufgabe an diesem Tag bereits zugewiesen ist (Jinja `selectattr('aufgabe_id','eq',a.id)`). Tippen = Toggle über einen vollen Seitensprung (Redirect, ohne Anker; das Panel ist danach wieder zu).
  - Wenn `tag.serien_pool` nicht leer: Etikett „🔁 Aus Pool holen" und `.btn-row` mit je einem Formular pro verfügbarer Vorlage (`action="/a/kinderplan{{ tp }}serie_einsortieren"`, Hidden `ziel_id`, `serie_id`, `tag`; Chip mit `s.inhalt`). Ebenfalls Seitensprung.

**Farben/Chips/Badges:** Chips `.chip-btn` (Rand `var(--border)`, aktiv `var(--farbe-band)`), Häkchen-Kreis `.aufgabe-check` bei `done` in `var(--farbe)`; Lock-Badge `.lock-badge`; alle Schriftgrößen ≥ 12 px; Pills der Personenwahl mit `knopf`-Klasse (Tippfläche #239).

**JavaScript** (`extra_scripts`, mit `csp_nonce`), Konstanten `TOKEN` und `TP`; alle Funktionen werden über den zentralen `data-klick`-Verteiler in `base.html` aufgerufen (Argumente aus `data-args`, dann Element, dann Ereignis):

- `togglePlan(iso)` – schaltet `#plan-edit-<iso>` zwischen `display:flex` und `none` um; `aria-expanded` pflegt `aufzuSync()` aus `base.html` über `data-panel`.
- `abhaken(zielId, aufgabeId, btn)` – deaktiviert den Knopf, `fetch POST /a/kinderplan${TP}abhaken` mit JSON-Body; bei `ok` Knopftext ✓ und Zeile `done`; bei Fehler Knopf wieder aktiv. Kein Seitensprung.
- `serieErledigen(tid, btn)` – `fetch POST …serie_erledigen/<tid>` mit Header `X-Requested-With: fetch`; bei `ok` ✓ und `done`. Kein Seitensprung. Der Knopf wird nie wieder aktiv, obwohl die Route ein Toggle ist – Zurücknehmen geht nur über die Todo-App.
- `serieZuruecklegen(tid, btn)` – `fetch POST …serie_zuruecklegen/<tid>` mit `X-Requested-With: fetch`; bei `ok` **`location.reload()`** (Kommentar: Pool-Kandidaten müssen neu berechnet werden).

Nicht verwendet: `data-fetch`, `data-bestaetigen`, `data-arbeitet`, `dialogFuehrung()`, `ziehSortierung()`. Kein Drag & Drop (bewusst nicht gebaut, siehe Abschnitt 12).

### 6. Wiederkehrende Aufgaben im Aufgabenplan

Die Vorlagen (`todo_serien`) werden in der Todo-App verwaltet; der Aufgabenplan importiert nur zwei Funktionen über den Alias `teile.todo` (`src/teile/__init__.py`, #90):

**`serien_pool_fuer_tag(db, tag_iso, alle_serien=None)`** – gibt die Liste aller aktiven Vorlagen zurück, die für **genau** diesen Kalendertag als Kandidat infrage kommen. Ohne `alle_serien` lädt sie selbst `SELECT * FROM todo_serien WHERE aktiv=1 ORDER BY inhalt COLLATE NOCASE`; `index` lädt die Liste einmal (nur wenn `ziel and darf_editieren`) und ruft die Funktion **je sichtbarem Kalendertag** (14×) auf – „einmal je sichtbarem Kalendertag statt einmal global" (#113, vorher `serien_pool_liste()`). Ändert nichts, liest nur. Intern filtert sie über `serie_verfuegbar_am`.

**`serie_verfuegbar_am(db, serie, tag_iso) -> bool`** (nicht importiert, aber das eigentliche Regelwerk):
1. Existiert bereits **irgendeine** `todos`-Zeile mit `serie_id = serie.id AND plan_tag = tag_iso` (unabhängig von Person und Status) → `False`. Eine Serie kann pro Tag also nur **einmal familienweit** eingeplant werden, nicht je Person.
2. Typ `'wochentag'`: `True`, wenn `tag.weekday()` in `_wochentage_menge(serie)` (aus `feste_wochentage`, Fallback `fester_wochentag`) – kein Anker, jede Woche zählt für sich.
3. Typ `'intervall'`: Anker ist `MAX(plan_tag)` über alle Instanzen dieser Serie (der zuletzt **eingeplante** Tag, nicht das Erledigt-Datum); gibt es keinen → `True` (jeder Tag kommt als Start infrage). Sonst `differenz = tag - anker` in Tagen; `True` nur bei `differenz > 0 and differenz % (intervall_tage or 1) == 0`. Periodisch statt „einmal fällig, für immer". Beispiel (Hilfe, #113): „alle 2 Tage", Montag eingeplant → Mi, Fr, So verfügbar, Di/Do/Sa nicht. Tage **vor** dem Anker sind nie verfügbar (Differenz negativ). Ist der Anker eine künftige Instanz, sperrt sie damit alle früheren Tage.

**`serie_einsortieren(db, serie_id, ziel_user_id, plan_tag, erstellt_von_user_id) -> bool`** – lädt die Serie (`aktiv=1`, sonst `False`), prüft `serie_verfuegbar_am` (sonst `False`), dann `INSERT INTO todos(inhalt, erstellt_von, zugewiesen_an, serie_id, plan_tag, status) VALUES(<serie.inhalt>, erstellt_von, ziel, serie_id, plan_tag, 'offen')` und `db.commit()`, Rückgabe `True`. Idempotent im Sinne von Regel 1: ein zweiter Aufruf für denselben Tag legt keine zweite Zeile an (gibt `False` zurück). Die Instanz ist ein vollwertiges Todo (erscheint in der Todo-App mit grauem 🔁-Chip, im Kanban-Brett, mit Historie usw.). `privat` bleibt 0, `zugewiesen_rollen` NULL, keine Fälligkeit (`faellig` bleibt NULL – `plan_tag` ist keine Frist im Sinne von #260).

**Erledigen (`serie_erledigen`)** – Status-Toggle in `todos`: `erledigt` 0↔1, `status` `'offen'`/`'erledigt'`, `erledigt_am` `datetime('now')` (UTC) bzw. NULL. Die Zeile bleibt bestehen, die Serie bleibt für diesen Tag laut Regel 1 „belegt". Die UI ruft es nur in Richtung „erledigt" auf.

**Zurücklegen (`serie_zuruecklegen`)** – „echtes Löschen" der `todos`-Zeile (`DELETE FROM todos WHERE id=?`), kein Status-Toggle. Kaskadiert `todo_historie` (FK `ON DELETE CASCADE`). Danach ist die Serie für diesen Tag wieder verfügbar; bei `'intervall'` verschiebt sich außerdem der Anker `MAX(plan_tag)` auf die nächstältere Instanz, wodurch sich die Verfügbarkeit **anderer** Tage ändern kann (daher der `location.reload()` im JS).

**Wechselwirkungen mit der Todo-App:** Löscht ein Elternteil die Instanz in der Todo-App, verschwindet sie auch aus dem Plan. Wird die **Serie** in der Todo-App gelöscht, setzt der FK `serie_id` auf NULL – die Instanzen bleiben als normale Todos bestehen, fallen aber aus dem Plan heraus (Filter `serie_id IS NOT NULL`). Wird die Serie nur deaktiviert (`aktiv=0`), bleiben eingeplante Instanzen im Plan sichtbar, neue werden nicht mehr angeboten, und `serie_einsortieren` lehnt ab. Ein Abhaken in der Todo-App wird im Plan angezeigt (gemeinsames Feld `erledigt`); ein Verschieben in `'in_arbeit'`/`'backlog'` im Kanban ändert `erledigt` nicht und ist im Plan unsichtbar.

**Fristen/Fälligkeit:** keine – der Plan kennt weder `faellig` noch „überfällig"; vergangene Tage werden nur gedimmt. **Zeitzonen:** `serie_verfuegbar_am` rechnet ausschließlich mit reinen Kalenderdaten (`date.fromisoformat(plan_tag)`), keine Zeitzone im Spiel (server.md, Bekannte Issues). Die Verwaltungsseite der Todo-App berechnet ihr „im Pool"-Badge dagegen mit `date.today()` (UTC-Datum des Containers) als Referenztag.

### 7. Zeitlogik

- **`_TZ = ZoneInfo("Europe/Berlin")`** im Modul (Altbestand, so auch in `14_sportschau.py`, `18_tvb.py`). Der Kern hat seit dem Kassenbuch (#153) `LOKAL_TZ`, `heute_lokal()` (liefert ISO-**String**), `utc_zu_lokal()`, `utc_zu_lokal_datum()`; server.md: „neuer Code nimmt die Helfer aus dem Kern". `13_kinderplan.py` nutzt seine eigene Konstante und importiert keinen Kern-Zeit-Helfer.
- **`_heute()`** = `datetime.now(_TZ).date()` – Tagesgrenze ist deutsche Mitternacht (Fix v88; vorher naives `datetime.now()` = UTC, was „heute" zwischen 0 und 2 Uhr auf den Vortag legte).
- **`_gesperrter_tag_datum()`** = ab `now.hour >= 20` (Europe/Berlin) das Datum von morgen, sonst `None`. Kein gespeicherter Zustand; wird bei jedem Request neu berechnet. Genau ein Tag ist je gesperrt (morgen), nie mehrere; nach Mitternacht ist der frühere Sperrtag „heute" und frei.
- **Fenster:** `montag = heute - timedelta(days=heute.weekday())`, `tage_daten = montag … montag+13`. Status je Tag: `vergangen` (< heute), `heute`, `zukunft`. Es gibt **keine** Datumsnavigation (kein Vor/Zurück, keine Wochenwahl, kein Kalenderwochen-Label); frühere Wochen und Tage nach dem Fenster sind in der UI unerreichbar, serverseitig aber beschreibbar (`zuweisen`/`serie_einsortieren` akzeptieren jedes gültige ISO-Datum). Vergangene Tage der aktuellen Woche sind bearbeitbar (✏️ vorhanden), nur das Abhaken der Geholfen-Zeilen ist auf „heute" beschränkt.
- **Kalenderwoche:** implizit Montag–Sonntag über `weekday()`; die Wochenüberschriften heißen fest „Aktuelle Woche" und „Nächste Woche", ohne KW-Nummer oder Datumsbereich.
- **Erledigt-Ableitung Geholfen:** `date(zeitstempel)` in SQLite auf einem UTC-Zeitstempel; `abhaken` schreibt `datetime('now')` (UTC). Zwischen 0 und 2 Uhr deutscher Zeit fällt ein Häkchen damit auf den UTC-Vortag und erscheint im Plan an der gestrigen Karte, nicht an „heute". Im Modul gibt es dazu keinen Kommentar; die allgemeine Falle steht in server.md („Bekannte Issues", UTC-Container).
- **`erledigt_am`** in `serie_erledigen` ist ebenfalls `datetime('now')` (UTC), wird im Plan nicht angezeigt.
- Migration #115 nutzt `date.today()` (UTC) für das Fenster.

### 8. Push-Benachrichtigungen und Hintergrund

Keine. `13_kinderplan.py` ruft `push_send()` an keiner Stelle auf, startet keinen Thread und hat keinen Schalter in `app.py`/`conftest.py`. Auch die importierten Todo-Funktionen `serie_einsortieren`/`serien_pool_fuer_tag` versenden nichts (im Gegensatz zu `todos_neu()` der Todo-App, das hier nicht verwendet wird – eine eingeplante Instanz löst also keine „Aufgabe für dich"-Benachrichtigung aus). Es gibt keinen Scheduler-Job im `util`-Container für den Plan.

### 9. Verflechtungen

- **`teile.todo` (Alias, #90):** `from teile.todo import serie_einsortieren, serien_pool_fuer_tag`; registriert in `src/teile/__init__.py` (Zeile 9–12) als erster Cross-Modul-Import außerhalb von `kern`. Die dortige Kommentarzeile und server.md („Code-Struktur", `__init__.py`-Eintrag) nennen noch `serien_pool_liste()`, den alten Namen vor #113.
- **Geholfen-App (`06_geholfen.py`):** gemeinsamer Aufgabenkatalog `geholfen_aufgaben` (nur `aktiv=1`, `ORDER BY id`) und gemeinsame Ereignistabelle `geholfen_eintraege`. `abhaken` im Plan ist datentechnisch identisch mit einem Klick auf eine Geholfen-Kachel; „Zuletzt geholfen" und die Matrix/Statistik der Geholfen-App zeigen ihn. Umgekehrt zeigt der Plan Geholfen-Einträge als Häkchen an, **auch wenn** die Aufgabe in der Geholfen-App gemacht wurde – aber nur an Tagen, an denen sie im Plan zugewiesen ist. `_darf_verwalten` ist die Kopie von Geholfens `_kann_fuer_andere` (Admin oder Eltern). Deaktivieren einer Geholfen-Aufgabe (`aktiv=0`) lässt bestehende Zuweisungen im Plan weiter sichtbar (der JOIN filtert nicht auf `aktiv`), entfernt aber den Chip im Panel und lässt `abhaken`/`zuweisen` mit 404 fehlschlagen. Löschen einer Geholfen-Aufgabe kaskadiert in `kinderplan_eintraege`.
- **Todo-App / Kanban:** Instanzen sind normale Todos (🔁-Chip in `todo.html`, Zeile 77); Status/erledigt werden geteilt (Abschnitt 6). Serienverwaltung nur dort (`/a/todo/<token>/serien`, Anlegen/Pausieren/Löschen; Löschen nur Eltern/Admin).
- **Packliste (`17_packliste.py`):** übernimmt das `_darf_verwalten()`-Muster „wie in 13_kinderplan.py" (#117/#118) – reine Code-Vorbildfunktion, keine Datenkopplung.
- **Startseite/Briefing:** Kein Bezug. `27_briefing.py` liest weder `kinderplan_eintraege` noch Plan-Instanzen; die Startseite zeigt die App nur als Kachel über den Grant.
- **Hilfe (`09_hilfe.py`/`hilfe.html`):** Kapitel `kapitel-11` „🗓️ Aufgabenplan" (Inhaltsverzeichnis-Eintrag Zeile 96) und Absatz unter „Die Apps".
- **`base.html`:** `data-klick`-Verteiler (`rufeAuf`), `aufzuSync()` für `data-panel`, `csp_nonce`, `tp`, `farbe_kontrast()`.

### 10. Konstanten und Konfiguration

| Name | Wert | Bedeutung |
|---|---|---|
| `bp` | `Blueprint("kinderplan_app", __name__)` | Blueprint; Endpunkte `kinderplan_app.index` usw. |
| `APP` | `"kinderplan"` | Slug für `grant()` |
| `WOCHENTAGE` | `["Montag", …, "Sonntag"]` | Anzeigenamen, Index = `date.weekday()` |
| `_TZ` | `ZoneInfo("Europe/Berlin")` | Zeitzone für „heute" und 20-Uhr-Schwelle |
| Sperrstunde | fest `20` in `_gesperrter_tag_datum()` (`now.hour >= 20`) | keine Konfiguration, keine `.env`-Variable |
| Fenstergröße | fest `14` in `range(14)` (Montag der aktuellen Woche + 13 Tage), Aufteilung `plan[:7]` / `plan[7:]` | nicht konfigurierbar |
| Seed | `("kinderplan", "Aufgabenplan", "🗓️", "Wiederkehrende Aufgaben wochentagsweise planen")` in `_CORE_APPS` (`00_kern.py`, Zeile 577) | App-Stammdaten |

Keine Umgebungsvariablen, keine `manage.py`-Befehle speziell für den Plan (nur `grant`/`addapp` allgemein). Keine Ratenbremse, keine KI-Zwecke.

### 11. Wunsch-Historie

Chronologisch (Datum = Wunsch-Eintrag bzw. Journal):

- #36 – 2026-07-27 – Neue App „Aufgabenplan" (portal-v22): Wochentag-Raster, nur Kinder, Abhaken → Geholfen, 20-Uhr-Sperre per `_gesperrter_wochentag()`, Chip-Toggle statt Drag & Drop (erledigt)
- #90 – 2026-08-01 – Wiederkehrende Aufgaben-Vorlagen mit Pool (v85): `todo_serien`, `todos.serie_id`, Alias `teile.todo`, „🔁 Aus Pool holen", `serie_erledigen` (erledigt; App-Tag `todo`, deshalb nicht in `wuensche_kinderplan.txt`)
- #91 – 2026-07-31 – Aufgabenplan auch für Eltern (v85): `rolle IN ('kind','eltern')` (erledigt)
- #92 – 2026-07-31 – Rollierende 14-Tage-Liste wie Essensplan (v87/v88): echte Kalendertage, `todos.plan_tag` statt `wochentag`, `_gesperrter_tag_datum()`, Zeitzonen-Fix `_TZ` (erledigt)
- #112 – 2026-08-02 – Mehrere Wochentage je Serie, `feste_wochentage` (v105; App-Tag `todo`) (erledigt)
- #113 – 2026-08-02 – Serien periodisch und pro Tag vorschlagen, `serie_verfuegbar_am()`/`serien_pool_fuer_tag()` (v105) (erledigt)
- #114 – 2026-08-02 – Pool-Instanz zurücklegen, `/serie_zuruecklegen/<id>` + ↩️ (v106) (erledigt)
- #115 – 2026-08-02 – Geholfen-Zuweisungen als Einzeltermine (`plan_tag`, Tabellen-Neubau, Migration bestehender Regeln) (v106) (erledigt)
- #140 (Stufe 4/6) – token-freie Zwillingsrouten, `tp`-Pfadvariable, `test_seiten_erreichbar` (portalweit) (erledigt)
- #142 – CSP: Inline-Handler → `data-klick`, `csp_nonce` (portalweit) (erledigt)
- #153 – Kassenbuch: `heute_lokal()`/`LOKAL_TZ` im Kern; `_TZ` in 13_kinderplan als Altbestand dokumentiert (kein Umbau) (erledigt)
- #169/#175/#200/#239/#248 – portalweite UI-Konventionen (Tippfläche, `aria-label`, `data-args`, `knopf`-Klasse an Pills, `data-panel`), in `kinderplan.html` nachgezogen (erledigt)

Offene Wünsche mit App-Tag `kinderplan`: keine in `wuensche_kinderplan.txt` (alle fünf dort gelisteten sind ✅).

### 12. Bekannte Eigenheiten und offene Punkte

Aus Code-Kommentaren, Docstrings, server.md und journal.md, ohne Bewertung:

- **Bewusst kein Drag & Drop** zwischen Tagen (Docstring, server.md): „für einen ersten Wurf zurückgestellt"; seit #115 sei es „technisch für beide Eintragsarten gleichermaßen möglich, kein struktureller Grund mehr dagegen".
- **Bewusst nicht gebaut** (journal #90): Bearbeiten/Löschen einer eingesetzten Instanz aus dem Plan heraus – „dafür einfach in die Todo-App wechseln"; #114 hat davon das Löschen (↩️) nachgeholt.
- **Kehrtwende #92 → #115:** #92 entschied „bestehende Routine bleibt automatisch bestehen", #115 das Gegenteil (Docstring: „bewusst so gewählt", nach Rückfrage 2026-08-02). Wochenroutinen müssen seither jede Woche neu zugewiesen werden; die Hilfe sagt das ausdrücklich.
- **Tote Spalten:** `kinderplan_eintraege.wochentag` (NOT NULL, wird weiter geschrieben, nicht gelesen), `todos.wochentag`, `todo_serien.fester_wochentag`. `kinderplan_eintraege.position` wird nie gesetzt.
- **`_TZ`-Altbestand** (server.md „Sicherheitskonventionen"/Zeit): eigene Konstante statt `LOKAL_TZ`/`heute_lokal()` aus dem Kern; „neuer Code nimmt die Helfer aus dem Kern". Zugleich ist das Modul das Referenzbeispiel in „Bekannte Issues" für den UTC-Container-Fehler (v87→v88, live um 01:13 Uhr nachgewiesen).
- **UTC in der Erledigt-Ableitung:** `date(zeitstempel)` und `datetime('now')` sind UTC; kein Kommentar im Modul dazu (siehe Abschnitt 7).
- **Migration #115 – Falle** (journal, 00_kern-Kommentar): `_init_db()`-Verbindung ohne `row_factory` (Tupel-Indizes), Wiederaufsetzen über Existenz von `kinderplan_eintraege_alt`; dieses Muster wurde später für #129 (grants) wiederverwendet.
- **Doku-Drift:** `teile/__init__.py` und server.md (`__init__.py`-Eintrag) nennen `serien_pool_liste()` (Name vor #113); server.md-Template-Eintrag beschreibt `kinderplan.html` als „Wochentag-Karten"; App-Seed-Text und „Die Apps"-Absatz in der Hilfe beschreiben noch das Wochentag-Modell und „Kinder".
- **Rückgabewert ignoriert:** `serie_einsortieren_route` wertet `False` von `serie_einsortieren()` nicht aus (Redirect ohne Hinweis).
- **Pool ist familienweit, nicht je Person:** Regel 1 in `serie_verfuegbar_am` prüft `serie_id + plan_tag` ohne `zugewiesen_an`. Der Pool wird nur berechnet, wenn `darf_editieren`; er ist derselbe für jede Zielperson.
- **`abhaken` ohne Tages-/Zuweisungsprüfung** und ohne Sperre; `serie_erledigen`/`serie_zuruecklegen` ohne Sperr-/Datumsprüfung (Abschnitt 3).
- **`serieErledigen` im JS ist Einbahn** (Knopf bleibt `disabled`), die Route ist ein Toggle.
- **↩️ ohne `data-bestaetigen`**, obwohl das Modul es als „echtes Löschen" bezeichnet; das 🗑️-Symbol-Prinzip (#160) wird hier nicht verwendet (↩️ mit Beschriftung „Zurück in den Pool legen").
- **Vergangene Tage editierbar**, ✏️ auf jeder Karte; Redirect nach `zuweisen`/`serie_einsortieren` ohne `#anker`, Panel danach wieder zu.
- **Seed/Grant:** kein `_auto_grant_all`; auf einer frischen DB hat niemand den Grant.
- **pruefplan.md S5-05:** „Essensplan und Aufgabenplan: eintragen und entfernen – ok" (Handprüfung Stufe 5).

### 13. Tests

Es gibt **keine** eigene Testdatei für den Aufgabenplan (`grep kinderplan tests/` trifft nur `test_routen_inventar.py`); die Funktionslogik (Sperre, Rechte, Toggle, Pool-Regeln) ist nicht per pytest abgedeckt – #113 wurde laut Journal nur ad hoc gegen eine In-Memory-DB geprüft.

- `tests/test_routen_inventar.py` – prüft, dass der Endpunkt-Präfix `kinderplan_app` Routen registriert hat, und dass jede ändernde Route eine `<token>`-Regel besitzt (alle fünf POST-Routen erfüllen das).
- `tests/test_seiten_erreichbar.py` – Rauchtest, ruft `/a/kinderplan/<token>/` (einzige GET-Route) mit Admin-Grant auf und erwartet 200, auch token-frei.
- Vorlagen-Wächter über `src/teile/templates/*.html`, die `kinderplan.html` mitlesen: `test_tippflaeche.py`, `test_aria_labels.py` (✏️/↩️ mit `aria-label` = `title`), `test_loeschen_symbol.py`, `test_kopfleiste.py`, `test_emoji.py`, `test_csp.py` (keine Inline-Handler), `test_formular_labels.py`, `test_ueberschriften.py` (`h1.nav-title`), `test_farbkontrast.py` (≥ 12 px, `--farbe-band`), `test_interaktion.py` (`data-panel` am Auf/Zu-Knopf), `test_verteiler_argumente.py` (`data-args`-Reihenfolge), `test_darkmode.py`, `test_kopfzeile_bleibt.py`, `test_umschalter_ohne_sprung.py`, `test_arbeitet_anzeige.py`.
- `tests/test_hilfe_kapitel.py` – wächtert das `<details class="section" id="kapitel-11">`-Muster des Hilfe-Kapitels.
- Zeitzonen-Tests (`test_kassenbuch_pruefung.py`, `test_briefing.py`, `test_todo_faellig.py`) prüfen `LOKAL_TZ`/`heute_lokal()` im Kern, nicht `_TZ` des Aufgabenplans.

---

## Querbezüge zwischen den drei Apps (Fakten, keine Bewertung)

Was ein Überarbeiter über App-Grenzen hinweg wissen muss. Alle Punkte sind am
Code nachgeprüft (Stand v262).

### Gemeinsame Daten

- **`geholfen_eintraege` und `geholfen_aufgaben` sind gemeinsame Tabellen von
  Geholfen und Aufgabenplan.** Das Abhaken einer Geholfen-Aufgabe im
  Aufgabenplan (`13_kinderplan.py`, Route `abhaken`) schreibt direkt eine Zeile
  in `geholfen_eintraege` (Zeitstempel `datetime('now')`, UTC); der
  Aufgabenkatalog des Aufgabenplans ist `geholfen_aufgaben WHERE aktiv=1`;
  `kinderplan_eintraege.aufgabe_id` hängt per `ON DELETE CASCADE` an
  `geholfen_aufgaben`. Jede Änderung an Schema oder Aktiv-Logik der Geholfen-
  Aufgaben wirkt im Aufgabenplan mit.
- **`todos` und `todo_serien` sind gemeinsame Tabellen von Aufgaben und
  Aufgabenplan.** Der Aufgabenplan importiert `serien_pool_fuer_tag()` und
  `serie_einsortieren()` über den Alias `teile.todo`, legt damit `todos`-Zeilen
  mit `serie_id` und `plan_tag` an, toggelt deren Status (`serie_erledigen`)
  und löscht sie (`serie_zuruecklegen`, echtes Löschen). Diese Schreibpfade
  laufen an `todos_neu()` vorbei – ohne Push, ohne `position`-Endstellung,
  ohne `faellig`. Dasselbe gilt für die KI-Budget-Aufgabe aus `24_ki_budget.py`
  (direktes `INSERT INTO todos`).
- Der Docstring von `todos_neu()` nennt „Geholfen" als Aufrufer; einen solchen
  Aufruf gibt es nicht, und einen Alias `teile.geholfen` gibt es nicht.

### Drei Tagesbegriffe nebeneinander

- **Familienzeit** (`heute_lokal()`, `utc_zu_lokal_datum()`): Geholfen-Hauptseite
  und Punktmatrix (`_matrix_fuer`: Spalten aus `heute_lokal()`, Zeitstempel je
  Eintrag auf den Familientag abgebildet).
- **UTC** (`date.today()`, `date(zeitstempel)`, `datetime('now', '-7 days')`):
  Geholfen-Übersicht (7-Tage-Punkte rollierend, 30-Tage-Kalender) und der
  Erledigt-Status im Aufgabenplan (`date(zeitstempel)` gegen `plan_tag`).
- **Rohzeitstempel ohne Umrechnung:** Geholfen-Verlauf zeigt und speichert den
  UTC-Zeitstempel so, wie er in der Tabelle steht.
- **Eigene `_TZ`-Konstante** in `13_kinderplan.py` für „heute" und die 20-Uhr-
  Sperre (Altbestand laut `server.md`), während `abhaken` dort UTC schreibt.
- `_matrix_fuer` filtert die Einträge mit `datetime('now', '-11 days')`
  (`MATRIX_TAGE + 1`) gegen die SQLite-Uhr, die Spalten kommen aus
  `heute_lokal()` – zwei Kalenderquellen in einer Funktion. Das ist der Grund,
  warum `tests/test_geholfen_matrix.py::test_eintrag_kurz_vor_mitternacht_
  zaehlt_zum_familientag` seit dem 18.09.2026 rot ist (Wunsch #296, offen).

### Rechte- und Sperrlogik über die Grenzen hinweg

- Der Serien-Pool im Aufgabenplan ist **familienweit, nicht je Person**:
  eine Serie kann pro Tag nur für eine Person eingeplant werden; der
  Intervall-Anker ist der jüngste `plan_tag` über alle Instanzen. Der
  `False`-Rückgabewert von `serie_einsortieren()` wird in der Route ohne
  Hinweis in einen Redirect umgesetzt.
- Die 20-Uhr-Sperre des Aufgabenplans greift serverseitig in `zuweisen` und
  `serie_einsortieren`; `abhaken`, `serie_erledigen` und `serie_zuruecklegen`
  prüfen weder Sperre noch 14-Tage-Fenster. Per POST ist jedes gültige
  ISO-Datum beschreibbar.
- `serie_zuruecklegen` ist ein echtes Löschen einer `todos`-Zeile ohne
  `data-bestaetigen`.
- In der Todo-App laufen Sichtbarkeit (`_visible_todos` mit Python-Rollenfilter,
  daraus `_sichtbare_ids`) und Änderungsrecht (`_darf_erledigen`) über zwei
  Funktionen; seit den Audits F-06 und N-09 gilt die Reihenfolge: unsichtbar
  → 404, sichtbar aber nicht änderbar → 403.
- Geholfen: der „Als wer?"-Selektor und die Übersicht listen **alle** `users`
  (auch `gast` und Admins), Personenstreifen und Punktmatrix nur `eltern` und
  `kind`. Ein Eintrag für einen Gast ist im Verlauf sichtbar, in der Matrix
  nicht; `matrixPunkt()` im JS tut dann nichts.

### Vorlagen- und Ansichtszustand

- Die Ansichts-Merkung der Todo-App (`todo_nutzer_ansicht`) wird nur bei
  `?ansicht=liste|brett` geschrieben; der Zurück-Link vom Brett braucht
  `?ansicht=liste`, `?erledigt=alle` muss die Weiterleitung `index → kanban`
  überleben – beides testgesichert (`tests/test_todo_ansicht.py`).
- Geholfen hält `PUNKTE_MAX` doppelt (Python und JS) und übergibt
  `QUADRAT_STUFEN`, das CSS hat die Stufen aber fest kodiert; der Fetch-Fallback
  in `geholfen.html` schickt ohne `fuer_user_id` ab.

### Dokumentations-Reste, die einen älteren Stand beschreiben

- `server.md` (Code-Struktur, Zeile 435) nennt `serien_pool_liste()`; die
  Funktion heißt seit #113 `serien_pool_fuer_tag()` (Zeilen 595 und 989 sind
  aktuell).
- Hilfe-Kapitel „Die Apps" (Aufgabenplan) und der Seed-Text der App beschreiben
  noch das Wochentag-/Nur-Kinder-Modell von vor #91/#113; Kapitel 11 ist aktuell.
- Hilfe zum Brett und der Docstring von `filter_karte` sagen „kein Status-Filter
  auf dem Brett", das Brett hat den Filter inzwischen.
- Für den Aufgabenplan gibt es keine eigene Testdatei; er ist nur über
  `test_routen_inventar.py`, `test_seiten_erreichbar.py` und die
  Vorlagen-Wächter abgedeckt.

### Offene Wünsche mit Bezug zu den drei Apps (Stand 19.09.2026)

- #296 – Geholfen: `test_eintrag_kurz_vor_mitternacht` ist datumsabhängig
  (ohne Priorität).
- Die Wunsch-Historien in den App-Abschnitten nennen weitere offene Einträge,
  sofern vorhanden; alles andere zu diesen Apps ist erledigt.
