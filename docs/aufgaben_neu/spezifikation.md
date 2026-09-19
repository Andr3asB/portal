# Spezifikation: App „Aufgaben" (neu)

**Stand:** 19.09.2026 · Grundlage: `status_quo_aufgaben_geholfen_aufgabenplan.md` (v262) und der abgestimmte Screen-Entwurf.
**Entwurf:** https://claude.ai/artifact/XWSSCpG4PqNHuCNEAxWQ8R – die Quelltexte der sieben Screens liegen als `entwurf/*.dc.html` bei. Sie sind die verbindliche Vorlage für Aufbau, Wortlaut und Zustände, **nicht** für Farben und Schriften (siehe Abschnitt 12).

Wer das umsetzt, liest zuerst `CLAUDE.md`, dann den Status quo, dann dieses Dokument. Wo diese Spezifikation mit `CLAUDE.md` oder einem Wächter-Test kollidiert, gilt der Wächter; die Abweichung wird als Wunsch erfasst und nicht still umgangen.

---

## 1. Entscheidungen, die feststehen

1. **Harter Schnitt im Datenmodell.** Eine neue App mit eigenen Tabellen ersetzt auf Sicht Aufgaben (`todo`), Geholfen und Aufgabenplan (`kinderplan`). Kein Parallelbetrieb auf gemeinsamen Tabellen, keine Übersetzungsschicht.
2. **Die alten drei Apps bleiben unverändert und eingefroren** als Rückfall bestehen, bis die Familie umzieht. Der Umzug ist eine Familienentscheidung nach einer Testphase, kein Schalter je Nutzer.
3. **Es gibt nur eine Sorte „Aufgabe"** und ein Formular. „Regelmäßig", „Kachel", „geparkt" sind Eigenschaften, keine Typen. Kein Katalog.
4. **Usability hat höchste Priorität.** Im Zweifel gewinnt die einfachere Bedienung gegen Vollständigkeit.
5. **Regelmäßige Aufgaben werden mit Person vorgeschlagen, Eltern bestätigen** mit einem Tipp (je Termin, je Tag oder alles Sichtbare).
6. **Punkte sind reine Rückmeldung.** Kein Wochenziel, keine Kopplung an Taschengeld oder Kassenbuch, kein Vergleich der Kinder untereinander auf Kinder-Screens. Punkte vergeben nur Eltern.
7. **Privat heißt privat.** Sichtbarkeit „Nur ich" und „Nur Kinder" gilt auch gegenüber Eltern und Admin. Das weicht bewusst vom Altbestand ab.
8. **Der Balken auf „Heute" zeigt den Tagesfortschritt**, nicht die Punkte.
9. **Kinder haben einen eigenen Reiter „Später"**; Eltern finden „Später" und „Alle Aufgaben" unter „Familie".
10. **Kein Brett, kein „In Arbeit", kein Backlog-Begriff.** „Später" ersetzt den Backlog. Eine Spaltenansicht kann später als reine Ansicht auf `termine` nachgebaut werden.

## 2. Begriffe

| Begriff | Bedeutung |
|---|---|
| Aufgabe | Die Definition: Text, Symbol, Punkte, Ziel, Sichtbarkeit, optional eine Regel |
| Termin | Ein konkretes Vorkommen einer Aufgabe: Tag, Person, Status |
| Vorschlag | Termin im Status `vorschlag`, aus einer Regel erzeugt, für Kinder unsichtbar, bis Eltern bestätigen |
| Geparkt | Termin ohne Tag im Status `geparkt`; erscheint nur unter „Später" |
| Kachel | Aufgabe mit `kachel=1`; ein Tipp erzeugt sofort einen erledigten Termin |
| Gruppe | `eltern`, `kinder`, `alle` („Wer will") als Ziel einer Aufgabe |
| Familientag | Kalendertag in `Europe/Berlin` (`heute_lokal()`), wird gespeichert, nicht abgeleitet |

## 3. Rollen und Rechte

Grundlage wie überall: `grant(token, "aufgaben")`, token-freie Zwillingsroute, CSRF und CSP unverändert. Aufsichtsrecht positiv geprüft: `rolle == 'eltern'`. **`is_admin` gibt in dieser App keine zusätzlichen Sicht- oder Änderungsrechte** (Folge aus Entscheidung 7). `gast` darf nur lesen, und nur Sichtbarkeit `alle`.

### 3.1 Sichtbarkeit

Eine Aufgabe (und jeder ihrer Termine) ist für einen Nutzer sichtbar, wenn mindestens eines gilt:

- er hat sie angelegt,
- ein Termin ist ihm zugewiesen (dann sieht er diesen Termin),
- `sicht = 'alle'`,
- `sicht = 'eltern'` und er hat die Rolle `eltern`,
- `sicht = 'kinder'` und er hat die Rolle `kind`.

`sicht = 'ich'` öffnet nichts über Ersteller und Zugewiesene hinaus. Es gibt genau eine Funktion `sichtbare_termine(db, user, …)`; alle Routen und Zähler bauen darauf auf (Lehre aus F-06). Reihenfolge bei Routen mit ID wie gehabt: unbekannt oder unsichtbar → 404, sichtbar aber nicht erlaubt → 403.

Validierung beim Speichern: Das Ziel muss die Aufgabe sehen dürfen. „Für Johannes" mit „Nur Eltern" wird abgelehnt (Formular bietet die Kombination nicht an, Server prüft trotzdem).

Private Aufgaben anderer zählen in keinem Fortschritt und keiner Summe mit, die der Betrachter sieht.

### 3.2 Handlungen

| Handlung | Kind | Eltern |
|---|---|---|
| Aufgabe anlegen | ja, Ziel immer „ich"; Sicht `alle`/`kinder`/`ich` | ja, alles |
| Punkte, Kachel, Symbol setzen | nein – Server ignoriert die Felder | ja |
| Bearbeiten (Text, Wann, Sicht) | nur selbst angelegte | alle sichtbaren |
| Abhaken / zurücknehmen | eigene Termine | alle sichtbaren, auch „für" andere |
| „Ich mach's" bei Gruppenaufgabe | wenn Gruppe passt | wenn Gruppe passt |
| Wieder freigeben | selbst übernommene | alle sichtbaren |
| „Morgen" / „Parken" | nur selbst angelegte eigene | alle sichtbaren |
| Löschen | selbst angelegte ohne Punkte | alle sichtbaren |
| Vorschläge bestätigen, verschieben, streichen | nein | ja |
| Kachel tippen | für sich | für sich oder eine gewählte Person |
| Kachel-Tipp zurücknehmen | eigener Tipp (`getippt_von`), nur heute, immer der letzte | jeder Eintrag, jederzeit |

Abweichung vom Altbestand (#10): Kinder dürfen selbst Angelegtes löschen. Die 20-Uhr-Sperre des Aufgabenplans entfällt, weil Kinder Zugewiesenes ohnehin nicht mehr verändern können.

## 4. Datenmodell

Schema und Migrationen zentral in `00_kern.py`, idempotent. Alle neuen Tabellen hängen per `ON DELETE CASCADE` am Nutzer oder an `aufgaben`; `tests/conftest.py` braucht keinen `BLEIBT`-Eintrag.

```sql
CREATE TABLE aufgaben (
  id              INTEGER PRIMARY KEY,
  inhalt          TEXT    NOT NULL,
  emoji           TEXT,                          -- nur mit lokaler Twemoji-Grafik (emoji_grafik_vorhanden)
  punkte          REAL    NOT NULL DEFAULT 0,    -- 0..10, Schritt 0,5; nur Eltern
  erstellt_von    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  ziel_user       INTEGER REFERENCES users(id) ON DELETE SET NULL,
  ziel_gruppe     TEXT,                          -- NULL | 'eltern' | 'kinder' | 'alle'; exklusiv zu ziel_user
  sicht           TEXT    NOT NULL DEFAULT 'alle', -- 'alle' | 'eltern' | 'kinder' | 'ich'
  regel_typ       TEXT,                          -- NULL | 'wochentage' | 'intervall'
  regel_wochentage TEXT,                         -- '0,2,4' (0=Mo)
  regel_intervall INTEGER,                       -- Tage, >= 2
  kachel          INTEGER NOT NULL DEFAULT 0,
  pausiert        INTEGER NOT NULL DEFAULT 0,
  erstellt        TEXT    NOT NULL DEFAULT (datetime('now')),
  geaendert       TEXT
);

CREATE TABLE termine (
  id            INTEGER PRIMARY KEY,
  aufgabe_id    INTEGER NOT NULL REFERENCES aufgaben(id) ON DELETE CASCADE,
  tag           TEXT,                            -- Familientag ISO; NULL nur bei status='geparkt'
  flexibel      INTEGER NOT NULL DEFAULT 0,      -- 1 = „diese Woche": tag ist der Sonntag der Woche
  uhrzeit       TEXT,                            -- 'HH:MM' Ortszeit, optional
  user_id       INTEGER REFERENCES users(id) ON DELETE CASCADE, -- NULL = Gruppe, noch frei
  status        TEXT    NOT NULL DEFAULT 'offen',-- 'vorschlag' | 'offen' | 'erledigt' | 'aus' | 'geparkt'
  inhalt        TEXT,                            -- Abweichung „nur dieser Termin", sonst NULL
  spontan       INTEGER NOT NULL DEFAULT 0,      -- 1 = Kachel-Tipp
  punkte        REAL,                            -- Schnappschuss beim Erledigen
  erledigt_am   TEXT,                            -- UTC
  erledigt_tag  TEXT,                            -- Familientag
  erledigt_von  INTEGER REFERENCES users(id) ON DELETE SET NULL,
  getippt_von   INTEGER REFERENCES users(id) ON DELETE SET NULL,
  geparkt_am    TEXT,
  position      INTEGER NOT NULL DEFAULT 0,      -- Reihenfolge in „Später"
  erstellt      TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX termine_regel_tag ON termine(aufgabe_id, tag)
  WHERE spontan = 0 AND tag IS NOT NULL AND flexibel = 0;
CREATE INDEX termine_user_tag ON termine(user_id, tag);

CREATE TABLE aufgaben_historie (               -- wie todo_historie: nur Textänderungen
  id INTEGER PRIMARY KEY,
  aufgabe_id INTEGER NOT NULL REFERENCES aufgaben(id) ON DELETE CASCADE,
  alter_inhalt TEXT NOT NULL,
  geaendert_von INTEGER REFERENCES users(id) ON DELETE SET NULL,
  geaendert_am TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE aufgaben_migration (              -- Herkunft, macht die Migration wiederholbar
  alt_tabelle TEXT NOT NULL, alt_id INTEGER NOT NULL,
  neu_tabelle TEXT NOT NULL, neu_id INTEGER NOT NULL,
  PRIMARY KEY (alt_tabelle, alt_id, neu_tabelle)
);
```

Formen einer Aufgabe: einmalig = Aufgabe + genau ein Termin; regelmäßig = Aufgabe mit Regel + viele Termine; reine Kachel = Aufgabe mit `kachel=1` ohne offenen Termin („Ohne Termin" in „Alle Aufgaben").

Wochenpunkte einer Person = Summe `termine.punkte` mit `status='erledigt'`, `user_id = Person`, `erledigt_tag` in der laufenden Woche (Mo–So, Familientag).

## 5. Regeln

### 5.1 Vorschläge erzeugen

`vorschlaege_sicherstellen(db, montag)` läuft beim Aufruf von Heute, Woche und Familie für die laufende und die nächste Woche. Kein Hintergrund-Thread. Idempotent über den Unique-Index; gestrichene Termine (`aus`) bleiben als Zeile stehen und werden deshalb nicht neu erzeugt.

- **Wochentage:** ein Termin je gewähltem Wochentag.
- **Intervall:** gezählt ab dem `erledigt_tag` des letzten erledigten Termins. Steht der letzte Termin noch offen oder als Vorschlag da, entsteht kein weiterer. Ohne Vorgeschichte ist der erste Termin morgen.
- **Person:** Bei `ziel_user` diese Person. Bei Gruppe `eltern`/`kinder` abwechselnd nach Tagen, fortgesetzt vom letzten Termin derselben Aufgabe. Bei `alle` bleibt `user_id` leer.
- **Status:** `vorschlag`, außer ein Kind hat die regelmäßige Aufgabe für sich selbst angelegt – dann direkt `offen`.
- Pausierte Aufgaben erzeugen nichts.
- **Automatische Freigabe am Tag selbst** (Entscheidung zu 15.1, 19.09.2026): In `vorschlaege_sicherstellen()` werden Termine mit `status='vorschlag'` und `tag = heute_lokal()` auf `offen` gesetzt. Auslöser ist der erste Aufruf des Tages durch irgendein Konto, auch das Kiosk-Konto. Kein Hintergrundjob, idempotent. Nur heute, nie künftige Tage – Vorschläge für morgen und später bleiben `vorschlag` und für Kinder unsichtbar. Status `aus` bleibt unberührt. Vorschläge vergangener Tage, die nie freigegeben wurden (niemand hat die App geöffnet), verfallen zu `aus`, nicht zu überfällig. Termine ohne Person (`ziel_gruppe='alle'`) werden ebenfalls `offen` und erscheinen damit unter „Noch zu haben". Spalte `termine.auto_bestaetigt INTEGER NOT NULL DEFAULT 0` wird dabei auf 1 gesetzt; Woche und Familie zeigen bei solchen Terminen den Zusatz „automatisch freigegeben", Eltern können sie weiterhin verlegen, die Person ändern oder „Fällt aus" setzen. „Familie" zeigt den Hinweis vorab: Gibt es in der laufenden Woche noch Vorschläge, steht im Kasten zusätzlich „N weitere diese Woche, werden am jeweiligen Tag automatisch freigegeben". Kein Push dafür, auch nicht an das Kind.

### 5.2 Gruppenaufgaben und „Ich mach's"

Einmalige Aufgaben an eine Gruppe bekommen einen Termin mit `user_id = NULL`. Er erscheint bei allen passenden, sichtberechtigten Personen auf „Heute" unter „Noch zu haben" und bei Eltern zusätzlich unter „Familie → Noch ohne Person". „Ich mach's" setzt `user_id` per `UPDATE … WHERE user_id IS NULL`; trifft das Update keine Zeile, lautet die Antwort „<Name> war schneller". Freigeben setzt `user_id` wieder auf NULL.

### 5.3 Parken, Verschieben, Überfällig

- „Später" im Formular oder „Parken" in der Zeile: `status='geparkt'`, `tag=NULL`, `geparkt_am=jetzt`, ans Ende der Später-Liste. Die Person bleibt.
- „Hervorholen": Heute (`tag=heute`), Diese Woche (`flexibel=1`, `tag=Sonntag`), Tag wählen.
- Überfällig ist ein offener Termin mit `tag < heute` (bzw. `flexibel=1` nach Ablauf der Woche). Er bleibt auf „Heute" stehen, rot gerahmt, mit „Seit gestern offen" / „Seit N Tagen offen". Wer parken darf, bekommt in der Zeile „Morgen" und „Parken".
- Geparkte Termine zählen nirgends als offen.
- Regelmäßige Aufgaben parkt man nicht: einzelner Termin → verschieben oder „Fällt aus"; alle künftigen → „Pausieren".

### 5.4 Kacheln

Tipp = neuer Termin `spontan=1, status='erledigt'`, `tag = erledigt_tag = heute_lokal()`, `punkte` aus der Aufgabe, `getippt_von` = Tipper. Eltern wählen vorher über „Person wechseln", für wen es zählt. Die Kachel zeigt „N× heute" und darunter „− zurück" für den letzten eigenen Tipp von heute. Kacheln füllen den Tagesbalken nicht. Fällt `fetch` aus, geht der Fallback-POST **mit** Zielperson (Fehler des Altbestands nicht wiederholen).

Steht dieselbe Aufgabe heute als offener Termin im Plan, hakt der Kachel-Tipp diesen Termin ab, statt einen zweiten zu erzeugen.

### 5.5 Bearbeiten regelmäßiger Aufgaben

Das Formular fragt vor dem Speichern „Nur dieser Termin" oder „Alle künftigen". Ersteres schreibt `termine.inhalt`/`tag`/`user_id`, Letzteres die Aufgabe und alle Termine ab heute im Status `vorschlag` oder `offen`. Erledigte Termine bleiben unberührt.

### 5.6 Zeit

Nur die Kern-Helfer (`heute_lokal()`, `utc_zu_lokal()`), keine eigene `_TZ`. Tage werden als Familientag gespeichert; nirgends `date(zeitstempel)` oder `date.today()`. Angezeigte Zeitstempel immer in Ortszeit.

### 5.7 Kiosk im Esszimmer

Entscheidung zu 15.2 (19.09.2026): eigener Kiosk-Modus – **am Konto, nicht per URL-Parameter**.

- Der Kiosk läuft unter einem eigenen Konto mit Rolle `kiosk` (Verwaltung → Rolle „Kiosk"). Ein URL-Parameter ist keine Sicherheitsgrenze. Kein Elternkonto mit „Person wechseln" am Kiosk.
- Einstieg ist immer die Personenwahl (große Flächen, eine je Elternteil/Kind). Nach 60 s ohne Eingabe und bei Wechsel des Familientags zurück zur Personenwahl.
- Gezeigt wird für die gewählte Person nur „Heute dran", „Noch zu haben" und die Kacheln, ausschließlich Termine mit `sicht='alle'`. Alles andere existiert für das Kiosk-Konto nicht (404): anlegen, bearbeiten, parken, verlegen, löschen, Woche, Später, Familie, Alle Aufgaben, Vorschläge. Keine Reiterleiste.
- Erlaubt: abhaken/zurücknehmen, „Ich mach's", Kachel tippen, „− zurück" nur für heutige Tipps mit `getippt_von` = Kiosk-Konto. Jedes Formular trägt die gewählte Person als `fuer`; ohne Person antwortet der Server 400.
- `user_id` und `erledigt_von` = gewählte Person, `getippt_von` = Kiosk-Konto. Kein PIN je Person.
- Das Kiosk-Konto bekommt keine Auto-Grants (`_auto_grant_all()` überspringt die Rolle) – es soll außer „Aufgaben" nichts haben.
- „Person wechseln" auf Heute bleibt Eltern am eigenen Gerät vorbehalten.
- Tests: `test_aufgaben_kiosk.py`.

## 6. Screens

Reiter unten: Kinder **Heute · Woche · Später**, Eltern **Heute · Woche · Familie**. Überall gilt: großer Bereich einer Zeile hakt ab, Stift bzw. Zeile öffnet das Formular, seltene Aktionen liegen eine Ebene tiefer. Jede ändernde Aktion ohne Seitensprung (`data-fetch` / `antwort_oder_weiter()`), mit „Rückgängig"-Meldung statt Rückfrage, wo die Aktion umkehrbar ist. Echte Löschungen mit `data-bestaetigen`.

### 6.1 Heute (`entwurf/Main.dc.html`)

1. Kopf: Datum, „Hallo <Name>", rechts Avatar = „Person wechseln" (nur Eltern; für den Kiosk, siehe Offene Punkte).
2. Tagesbalken: „N von M geschafft" / „Alles geschafft" / „Heute ist nichts dran"; daneben klein „X Punkte diese Woche" (nur eigene).
3. **Heute dran:** offene und heute erledigte Termine der Person, überfällige zuerst. Zeile: Haken-Kreis, Text, Infozeile (Herkunft, Uhrzeit, Schloss-Marke „Nur ich"/„Nur Kinder"/„Nur Eltern"), rechts Punkte, ganz rechts Stift, wenn bearbeitbar. Zweiter Tipp nimmt das Häkchen zurück. Darunter „+ Eigene Aufgabe".
4. **Noch zu haben:** freie Gruppenaufgaben, gestrichelt, mit „Ich mach's". Abschnitt entfällt, wenn leer.
5. **Sonst noch geholfen?:** Kacheln, drei Spalten, nach Häufigkeit der letzten 30 Tage sortiert.
6. „Morgen: N Aufgaben" als Sprung in die Woche.

### 6.2 Aufgabe – ein Formular (`entwurf/NeueAufgabe.dc.html`)

Reihenfolge: **Was?** (Text) · **Wer?** (nur Eltern: Ich, Personen, gestrichelt die Gruppen Eltern/Kinder/Wer will; Hinweiszeile erklärt die Folge, z. B. Push oder Abwechseln) · **Wann?** (vier gleich große Knöpfe: Heute, Tag wählen, Später, Regelmäßig; bei Regelmäßig klappt darunter „An Wochentagen" / „Alle … Tage" mit Klartext-Vorschau auf) · **Mehr einstellen** (zugeklappt mit Zusammenfassung „Alle sehen es · keine Punkte"; darin Sichtbarkeit als vier Knöpfe, für Eltern zusätzlich Punkte, „Auch als Kachel", Symbol).

Kinder: kein „Wer?", kein „Nur Eltern", keine Punkte/Kachel/Symbol. Knopf unten heißt „Speichern", bei Später „Parken". Im Bearbeiten-Modus zusätzlich „Nur dieser Termin / Alle künftigen" (nur bei Regel), „Löschen", Verlauf früherer Textfassungen.

Anlegen direkter Zuweisung an eine andere Person löst wie bisher Push aus.

### 6.3 Woche (`entwurf/Woche.dc.html`)

Kopf mit Wochenwechsel, Datumsbereich und KW; Personenfilter (Alle, je Kind, Eltern). Gelber Kasten „N Vorschläge" mit Sammelknopf, dessen Text den Umfang nennt: „Alle 9 ok" ohne Filter, „Diese 5 ok" mit Filter. **Bestätigt wird immer nur das Sichtbare.** Je Tag: Überschrift, „<Tag> ok" (nur bei offenen Vorschlägen), „+" für eine neue Aufgabe an diesem Tag.

Zeile: Vorschläge gestrichelt, Bestätigtes durchgezogen. Drei Ein-Tipp-Aktionen: Haken bestätigt, Namens-Chip öffnet die Personenwahl, Tipp auf den Text klappt auf. Aufgeklappt: Tagesreihe Mo–So zum Verlegen und „Fällt aus". Nach „Fällt aus" bietet die Meldung „Rückgängig" und, falls vorhanden, „Auch die anderen N streichen". Kein Drag & Drop.

Kinder sehen die Woche nur lesend, ohne Vorschläge, mit ihren eigenen Terminen.

### 6.4 Familie (`entwurf/Familie.dc.html`, nur Eltern)

Vorschlagskasten für die nächste Woche („Alle übernehmen" / „Ansehen"), Fortschritt je Person (Balken = heute erledigt/gesamt, darunter Wochenpunkte; Tipp öffnet deren „Heute"), „Noch ohne Person", Einstiege „Später" und „Alle Aufgaben", „+ Neue Aufgabe".

### 6.5 Später (`entwurf/Spaeter.dc.html`, `SpaeterKind.dc.html`)

„Schnell parken" (Textfeld + Plus), Liste mit Ziehgriff (`ziehSortierung()`, Tastatur inklusive), Alter der Ablage, „Hervorholen" mit den drei Zielen. Hervorgeholtes erscheint oben mit Rückweg „Parken". Kinder-Fassung identisch, als eigener Reiter.

### 6.6 Alle Aufgaben (`entwurf/Katalog.dc.html`, nur Eltern)

Suche, Filter (Alle, Regelmäßig, Einmalig, Geparkt), je Zeile Rhythmus/Termin, Person, Marken für Sichtbarkeit und Kachel, Punkte. Tipp öffnet das Formular. Pausierte Aufgaben gedimmt am Ende.

## 7. Routen (Blueprint `aufgaben_app`, Slug `aufgaben`)

Jede mit Token- und token-freier Regel. Ändernde Routen antworten über `antwort_oder_weiter()`.

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/` | Heute; `?fuer=<id>` nur Eltern |
| GET | `/woche` | `?ab=<montag>`, `?wer=` |
| GET | `/familie`, `/alle`, `/spaeter` | wie benannt |
| GET/POST | `/neu`, `/aufgabe/<id>` | Formular anlegen/bearbeiten; `umfang=termin|kuenftige` |
| POST | `/termin/<id>/haken` | Toggle erledigt |
| POST | `/termin/<id>/nehmen`, `/freigeben` | Gruppenaufgabe |
| POST | `/termin/<id>/verlegen` | `tag` oder `morgen=1` |
| POST | `/termin/<id>/parken`, `/hervorholen` | |
| POST | `/termin/<id>/ok`, `/aus`, `/person` | Vorschlag bestätigen, streichen, Person setzen |
| POST | `/woche/ok` | `ab`, optional `tag`, optional `wer` – bestätigt nur den gefilterten Umfang |
| POST | `/kachel/<aufgabe_id>/tippen`, `/zurueck` | |
| POST | `/spaeter/reihenfolge` | JSON `order` |
| POST | `/aufgabe/<id>/pausieren`, `/loeschen` | |

Alle Ganzzahlen über `to_int()`, Datum über `date.fromisoformat`, Tag nur im Fenster heute−7 … heute+60.

## 8. Push

Über `push_send()`, Deep-Link token-frei. Auslöser: Zuweisung an eine andere Person (neu oder umgehängt); neue Gruppenaufgabe an die Gruppenmitglieder; sonntags 17 Uhr an Eltern „Vorschläge für nächste Woche" (einziger Hintergrundjob, über den `util`-Scheduler, abschaltbar). Kein Push für Vorschläge an Kinder, keiner für Kachel-Tipps.

## 9. Migration

`manage.py aufgaben_migrieren [--frisch]`, wiederholbar: `--frisch` leert die vier neuen Tabellen und importiert neu; ohne den Schalter wird nur ergänzt, was in `aufgaben_migration` noch fehlt. Die alten Tabellen werden nie verändert. Am Ende ein Bericht (Anzahlen je Quelle, Auffälligkeiten).

| Quelle | Ziel |
|---|---|
| `geholfen_aufgaben` | `aufgaben` mit `kachel=1`, `punkte=gewichtung`, `pausiert = 1-aktiv`, `sicht='alle'`, `ziel_gruppe='alle'` |
| `geholfen_eintraege` | `termine` mit `spontan=1`, `status='erledigt'`, `erledigt_tag = utc_zu_lokal_datum(zeitstempel)`, `punkte = gewichtung` |
| `kinderplan_eintraege` | `termine` der migrierten Geholfen-Aufgabe mit `tag=plan_tag`, `user_id`; gibt es am selben Familientag einen passenden Geholfen-Eintrag derselben Person, wird **dieser** Termin auf `spontan=0` gesetzt statt ein zweiter angelegt |
| `todo_serien` | `aufgaben` mit Regel (`intervall` → `regel_intervall`, `wochentag` → `regel_wochentage`), `pausiert = 1-aktiv`. Namensgleichheit mit einer Geholfen-Aufgabe nur im Bericht melden, nicht automatisch zusammenlegen |
| `todos` mit `serie_id` | `termine` der Serien-Aufgabe, `tag=plan_tag` |
| `todos` ohne Serie | je eine `aufgaben`-Zeile + ein Termin. `backlog` → `geparkt`; `offen`/`in_arbeit` → `offen` mit `tag` = Ortsdatum von `faellig`, sonst heute; `erledigt` → `erledigt` mit `erledigt_tag` aus `erledigt_am`. `position` übernehmen |
| Ziel | `zugewiesen_an` → `ziel_user`; Rollen `kind` → `kinder`, `eltern` → `eltern`, alles andere → `alle` |
| `privat` | `privat=1` + Rollenziel `eltern` → `sicht='eltern'`; sonst `privat=1` → `sicht='ich'` |
| `todo_historie` | `aufgaben_historie` |

Hinweis für den Bericht: Durch Entscheidung 7 werden bisher für Eltern sichtbare private Aufgaben der Kinder unsichtbar.

## 10. Berührungspunkte im übrigen Portal

- **KI-Budget (`24_ki_budget.py`)** schreibt weiter in `todos`, bis umgezogen wird. Schalter `AUFGABEN_NEU_PRIMAER` (Default 0): bei 1 legt es über die neue Funktion `aufgabe_neu()` an und prüft dort auf Dubletten. Dieselbe Funktion ist die **einzige** Schreibschnittstelle für andere Module (kein direktes `INSERT`).
- **Startseite:** Kachel „Aufgaben (neu)" während der Testphase, mit Zähler „N heute offen". Nach dem Umzug heißt sie „Aufgaben", die drei alten Kacheln werden den Nutzern entzogen (Grants), nicht gelöscht.
- **Hilfe-App:** ein neues Kapitel; die drei alten Kapitel bekommen nach dem Umzug einen Verweis.
- **`manage.py`:** `aufgaben_migrieren`, `listaufgaben`.
- **Service Worker / offline:** `offline_faehig=0` wie bisher.

## 11. Nicht im Umfang

Brett/Spaltenansicht, „In Arbeit", Wochenziele, Taschengeld-Kopplung, „Punkte beantragen", Rhythmen jenseits von Wochentagen und „alle N Tage" (z. B. 14-tägig im festen Takt, monatlich), Drag & Drop in der Woche, Statistikseiten (Punktmatrix, 30-Tage-Kalender) – Letztere können später als Ansicht auf `termine` folgen.

## 12. Gestaltung

Der Entwurf hat ein eigenes Aussehen (warmer Grund, Personenfarben als Flächen, große Zeilen, Reiterleiste unten). **Für diese Umsetzung gilt das Portal-Design:** `base.html`, `var(--farbe)`/`--farbe-kontrast`, Dunkelmodus über `dunkle_werte`, Twemoji, `.main` 720 px, 44-px-Tippflächen, Feldschrift ≥ 16 px. Übernommen werden aus dem Entwurf Aufbau, Reihenfolge, Wortlaut, Zustände und Größenverhältnisse (Zeilenhöhe ≥ 60 px, ein Hauptknopf je Screen).

Neu für `base.html`, jeweils mit Wächter-Test: eine **Reiterleiste unten** (`nav[aria-label]`, `aria-current="page"`, Safe-Area) und eine **Rückgängig-Meldung** (`role="status"`, verschwindet nach 6 s, ein Knopf). Ob die Reiterleiste mit der Regel „Aktionsknöpfe oben als `.top-aktionen`" vereinbar ist, klärt der erste Arbeitsschritt gegen `CLAUDE.md`; sie ist Navigation, keine Aktion.

Ein optisches Remake des gesamten Portals ist ein eigenes Vorhaben. Der Entwurf kann dafür als Ausgangspunkt für ein Design-System dienen.

## 13. Tests

Eigene Testdateien von Anfang an, keine Abdeckung nur über Wächter:

- `test_aufgaben_sicht.py`: jede Sichtbarkeitsstufe je Rolle; Admin ohne Sonderrecht; 404 vor 403; private Termine fehlen in fremden Zählern; Ziel muss Sicht haben.
- `test_aufgaben_rechte.py`: Matrix aus 3.2; Kind-POST mit `punkte`/`kachel` wird ignoriert; Kind kann Zugewiesenes nicht parken, verlegen, löschen.
- `test_aufgaben_vorschlaege.py`: Wochentage; Intervall ab Erledigung; kein neuer Vorschlag bei offenem Vorgänger; Abwechseln setzt fort; gestrichen wird nicht neu erzeugt; idempotent bei Doppelaufruf; pausiert erzeugt nichts.
- `test_aufgaben_woche.py`: Tag bestätigen; Sammelbestätigung respektiert Filter; verlegen; „Fällt aus" einzeln und für die Woche.
- `test_aufgaben_gruppe.py`: „Ich mach's" atomar (zweiter verliert), freigeben.
- `test_aufgaben_kachel.py`: Tipp, Zurücknehmen nur eigener Tipp von heute; Eltern immer; Tipp hakt geplanten Termin ab statt Dublette; Fallback trägt Zielperson.
- `test_aufgaben_zeit.py`: Eintrag 23:30 und 00:30 Ortszeit, Sommer- und Winterzeit, Wochengrenze – mit gepatchter Uhr, ohne zweite Kalenderquelle (Lehre aus #296).
- `test_aufgaben_migration.py`: jede Zeile der Tabelle in Abschnitt 9; zweimal laufen lassen ergibt denselben Stand; Alt-Tabellen unverändert.
- Aufnahme in `test_routen_inventar.py`, `test_seiten_erreichbar.py`; alle Vorlagen-Wächter grün; `ruff` sauber.

## 14. Reihenfolge der Umsetzung

Jeder Schritt ist ein eigener Wunsch, auslieferbar und end-to-end prüfbar.

1. Schema, `sichtbare_termine()`, Rechtefunktionen, `aufgabe_neu()` – mit Tests, ohne Oberfläche.
2. Heute (lesen, abhaken, zurücknehmen) und Formular für einmalige Aufgaben; Reiterleiste und Rückgängig-Meldung in `base.html`.
3. Später, Parken, „Morgen"/„Parken" bei Überfälligem.
4. Kacheln mit Zurücknehmen; „Person wechseln".
5. Regeln, Vorschläge, Woche mit Bestätigen, Verlegen, Streichen.
6. Gruppenaufgaben und „Noch zu haben"; Familie; Alle Aufgaben.
7. Migration, Bericht, Testphase mit echten Daten.
8. Push, Sonntagsjob, Startseiten-Zähler, Hilfe-Kapitel.
9. Umzug: `AUFGABEN_NEU_PRIMAER=1`, Grants der alten Apps entziehen, Doku in `server.md`/`journal.md`.

## 15. Offene Punkte – alle entschieden (19.09.2026)

1. **Unbestätigte Vorschläge am Tag selbst** – entschieden: Variante A, automatische Freigabe am Tag selbst. Umgesetzt in Abschnitt 5.1 (Wunsch #301).
2. **Kiosk im Esszimmer** – entschieden: eigener Kiosk-Modus am Konto (Rolle `kiosk`), kein URL-Parameter. Umgesetzt in Abschnitt 5.7 (Wunsch #300).
3. **Modul- und Dateinamen** – entschieden: `src/teile/28_aufgaben.py`, Alias `teile.aufgaben`, Slug `aufgaben`, Kachel „Aufgaben (neu)" bis zum Umzug (Wunsch #297/#298).
