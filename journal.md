# journal.md – Bau-Journal

---

## 2026-08-02 – portal-v101: Wunsch #106 – Foto-Upload: Mediathek auf iPhone fehlte

"Auf dem iPhone kann ich kein Bild auswählen, um ein Rezept hochzuladen.
Das scheint ein Bug zu sein."

Ursache: `<input type="file" ... capture="environment">` in
`rezept_bild_importieren.html` (Wunsch #97). Das `capture`-Attribut zwingt
iOS Safari, beim Antippen direkt die Kamera zu öffnen - ohne die native
Auswahl "Foto aufnehmen ODER aus Mediathek wählen" anzuzeigen. Für Andi
sah das aus wie "ich kann kein Bild auswählen", weil die Mediathek-Option
schlicht nicht angeboten wurde. `capture` einfach entfernt,
`accept="image/jpeg,image/png,image/heic"` schränkt den Dateityp weiter
korrekt ein.

Derselbe Bug steckte auch im baugleichen `vokabel_foto_import.html`
(Wunsch #80, exakt dieselbe Input-Zeile kopiert) - obwohl nicht explizit
im Wunsch genannt, gleich mitkorrigiert, statt denselben Fehler in einer
zweiten App auf die nächste Werkstatt-Runde zu vertagen. Neuer Eintrag in
server.md "Bekannte Issues" mit der allgemeinen Regel für künftige
Foto-Upload-Formulare.

### Verifiziert

Datei-Input in beiden Templates geprüft: `capture`-Attribut vollständig
entfernt, `accept` unverändert vorhanden. Da `capture`s Auswirkung nur auf
echten iOS-Geräten sichtbar ist (Desktop-Chrome zeigt ohnehin immer den
normalen Datei-Dialog, ignoriert `capture`), lässt sich der eigentliche
Effekt von hier aus nicht per Browser-Tool nachstellen - die Fehlerursache
ist aber ein dokumentiertes, eindeutiges iOS-Safari-Verhalten, das exakt
zu Andis Beschreibung passt. Von Andi live auf dem iPhone bestätigt -
sowohl Bilder als auch Dateien lassen sich jetzt auswählen.

### Auslieferungspaket

`deploy/portal-v101.tar.gz`

---

## 2026-08-02 – portal-v100: Wünsche #103 + #104 + #105 – Scroll-Bug, Werkstatt-Layout, Formular-Kollision

### Wunsch #103 – Scrollen blockiert, wenn der Finger auf einer App-Kachel aufsetzt

"Wenn ich auf der Seite scrollen will, dann muss ich eine Stelle ohne
Kachel antippen. Tippe ich eine App-Kachel an, kann ich nicht scrollen."
Ursache: `.tile { touch-action: none; }` in `startseite.html` galt
IMMER, nicht nur im Bearbeiten-Modus - dabei ist `touch-action:none` nur
für den Pointer-Drag beim Verschieben der Kacheln nötig (`onDown()`
prüft ohnehin `if (!editMode) return`). Fix: `touch-action:none` nur noch
unter `.edit-mode .tile`, ausserhalb des Bearbeiten-Modus verhält sich
eine Kachel touch-technisch wie ein normaler Link und blockiert kein
Scrollen mehr.

### Wunsch #104 – Detailansicht in der Werkstatt auf dem iPhone "durcheinander"

Ursache: `.wunsch-card` (Wunsch-Listenkarte) fehlte `flex-wrap:wrap`. Das
neue Detail-Panel aus Wunsch #101 nutzt `flex:1 0 100%`, um unter der
Karte in eine eigene Zeile umzubrechen (gleicher Trick wie die
Edit-Panels in `einkauf.html`/`geholfen_aufgaben.html`) - der Trick
funktioniert aber nur, wenn der Flex-Container `flex-wrap:wrap` hat.
Ohne das blieb `.wunsch-card` bei `nowrap` (Default) und das Detail-Panel
quetschte sich stattdessen mit `.wunsch-body`/`.wunsch-actions` in eine
einzige Zeile - auf breiten Bildschirmen kaum auffällig, auf dem iPhone
deutlich als zerschossenes Layout sichtbar. Fix: `flex-wrap:wrap`
ergänzt.

### Wunsch #105 – Verbesserungswunsch-Formular sieht in der Werkstatt anders aus

Ursache: Klassennamen-Kollision. base.html definiert `.wunsch-card`/
`.wunsch-actions` fürs globale ✨-Formular (Overlay, von jeder Seite aus
erreichbar). `werkstatt_app.html` verwendete für seine eigenen
Wunschlisten-Karten zufällig dieselben Namen - deren `extra_styles`
landen im selben `<style>`-Block wie base.html, aber danach, gewinnen bei
gleicher Spezifität also automatisch. Nur auf der Werkstatt-Seite selbst
sah das ✨-Formular deshalb anders aus als überall sonst im Portal. Fix:
base.html nutzt jetzt eindeutige `.wunsch-modal-card`/
`.wunsch-modal-actions` statt der generischen Namen - siehe auch neuer
Eintrag in server.md "Bekannte Issues" mit der allgemeinen Regel dazu
(globale base.html-Klassen brauchen kollisionsresistente Namen).

### Verifiziert

- Wunsch #103: `getComputedStyle('.tile').touchAction` liefert `auto`
  ausserhalb, `none` innerhalb `.edit-mode` - geprüft per `javascript_tool`.
- Wunsch #104: `getComputedStyle('.wunsch-card').flexWrap` liefert jetzt
  `wrap` statt `nowrap` (vorher live als Bug bestätigt, DAS war die Wurzel
  des von Andi beschriebenen Layout-Durcheinanders).
- Wunsch #105: `grep` bestätigt keine verbleibenden `.wunsch-card`/
  `.wunsch-actions`-Referenzen in base.html, nur noch `.wunsch-modal-*`;
  JS in base.html selektiert diese Klassen ohnehin nur über IDs, keine
  Anpassung dort nötig.

### Auslieferungspaket

`deploy/portal-v100.tar.gz`

---

## 2026-08-01 – portal-v99: Wunsch #102 – Sportschau: Trainingsdaten grün statt blau

"Ich will die Trainingsdaten jetzt in grün anzeigen statt in blau."

Der Trainingsanteil im Schritte-Balkendiagramm (`.steps-bar-training`) und
sein Legenden-Punkt färbten sich bisher über `var(--farbe)` - Andis
persönliche Nutzerfarbe, zufällig Blau (#3498db). Auf ein festes Grün
(`#34c759`, derselbe Wert wie die bereits grüne Trainings-Heatmap oben)
umgestellt, damit "Training" unabhängig von der persönlichen Farbwahl
immer als Grün erkennbar ist und zur Heatmap passt. Reine CSS-Änderung
in `sportschau.html`, keine Python-Logik betroffen.

### Verifiziert

Per `javascript_tool`: `getComputedStyle()` auf `.steps-bar-training`
und dem Legenden-Punkt liefert `rgb(52, 199, 89)` (= #34c759), nicht mehr
Andis blaue Nutzerfarbe. Heatmap-Zellen unverändert grün, Zeitraum-Buttons
(die weiterhin `var(--farbe)` nutzen, sind kein "Trainingsdaten"-Element)
unverändert blau.

### Auslieferungspaket

`deploy/portal-v99.tar.gz`

---

## 2026-08-01 – portal-v98: Wunsch #101 – Werkstatt: Umsetzung dokumentieren

"Zu jedem Wunsch soll am Ende der Implementierung auch dokumentiert
werden, was genau umgesetzt wurde. Klickt man auf einen Wunsch, dann
wird Wunsch, Benutzer, Wunschdatum und Implementierungsdatum sowie die
Umsetzung gut lesbar angezeigt."

Neue Spalte `wuensche.umsetzung` (TEXT, nullable). Gesetzt wird sie NICHT
über die Web-UI, sondern über ein neues optionales zweites Argument von
`manage.py wunsch_erledigt <id> ["Beschreibung"]` - passt zum bisherigen
Arbeitsablauf (dieser Befehl markiert ohnehin jeden fertigen Wunsch als
erledigt) und macht die Dokumentation zu einem festen Teil davon, statt
einem zusätzlichen manuellen Schritt. Ab sofort bekommt jeder künftige
`wunsch_erledigt`-Aufruf eine kurze Beschreibung der Umsetzung mit.

In der Werkstatt-App klappt ein Antippen der Wunsch-Karte (offen wie
erledigt) eine Detailansicht auf: voller Wunschtext, Benutzer,
Wunschdatum, bei erledigten zusätzlich Implementierungsdatum und die
Umsetzung ("Noch nicht dokumentiert." als Platzhalter, wo sie fehlt -
z. B. bei alten, vor Wunsch #101 abgeschlossenen Wünschen). Neuer
`de_datum`-Jinja-Filter formatiert die rohen SQLite-Zeitstempel
("YYYY-MM-DD HH:MM:SS") lesbar als "DD.MM.YYYY, HH:MM Uhr". Die Aktions-
Buttons (Prio, Erledigt, Löschen) liegen bewusst als Geschwister
außerhalb des antippbaren Bereichs, damit ihre Klicks den Detail-Toggle
nicht versehentlich mit auslösen.

### Verifiziert

Migration auf der bestehenden DB geprüft: `umsetzung`-Spalte angelegt,
bestehende Wünsche zeigen korrekt "Noch nicht dokumentiert." in der
Detailansicht. `manage.py wunsch_erledigt 101 "..."` gesetzt und per
`javascript_tool` in der Werkstatt-App geprüft: Karte antippen öffnet
die Detailansicht mit allen fünf Feldern korrekt befüllt und lesbar
formatiertem Datum; erneutes Antippen klappt sie wieder zu; Klick auf
die Prio-/Erledigt-/Löschen-Buttons löst den Toggle nicht mit aus.

### Auslieferungspaket

`deploy/portal-v98.tar.gz`

---

## 2026-08-01 – portal-v97: Wunsch #100 – Einkauf: automatische Synchronisierung

"Die Einträge sollten regelmäßig und bei jedem Öffnen synchronisiert
werden, damit parallele Einträge von anderen Benutzern angezeigt werden."
Bisher lud die Einkaufsliste die Daten nur beim ersten Aufruf/Reload -
blieb die Seite (PWA) länger offen, während jemand anders etwas einträgt
oder abhakt, sah man das nicht von selbst.

Neuer Sync-Fingerabdruck statt einer vollen Datenübertragung: Spalte
`einkauf_eintraege.geaendert` (bei jedem INSERT/UPDATE explizit gesetzt -
SQLite erlaubt keinen nicht-konstanten `ALTER TABLE ADD COLUMN`-Default,
siehe Bekannte Issues in server.md), `_stand(db)` in `10_einkauf.py`
kombiniert `COUNT(*)` + `MAX(geaendert)` zu einem kompakten String, der
Einfügen/Löschen/Ändern/Abhaken gleichermaßen abdeckt. Neue Route
`/a/einkauf/<token>/stand` (JSON) liefert diesen Fingerabdruck.

Frontend (`einkauf.html`) pollt `/stand` alle 30 Sekunden UND sofort bei
`visibilitychange`/`pageshow` (App kommt aus dem Hintergrund zurück - die
tatsächliche "bei jedem Öffnen"-Anforderung, ein normaler Seitenaufruf
liefert ja ohnehin schon frische Daten). Weicht der Fingerabdruck vom
beim Laden eingebetteten Wert ab, lädt die Seite neu - außer gerade ist
etwas Ungespeichertes im Weg (Name-Feld im "+ Neu"-Formular hat Text,
oder ein Bearbeiten-Panel ist offen) oder der Einkaufsmodus läuft gerade
(bewusst nicht mitten im Laden-Trip stören) - dann greift der nächste
Sync-Versuch.

### Verifiziert

`curl` gegen `/stand`: Fingerabdruck ändert sich korrekt bei Hinzufügen,
Abhaken und Bearbeiten, bleibt gleich bei reinem erneuten Abruf ohne
Änderung. Migration auf einer bestehenden DB mit vorhandenen Einträgen
geprüft: `geaendert` wird per Backfill auf `erstellt` gesetzt, keine
NULL-Werte übrig. Zwei-Browser-Test: Artikel in Tab A hinzugefügt,
Tab B zeigt ihn nach spätestens 30s automatisch, ohne dass dort manuell
neu geladen wurde; Tab B mit offenem "+ Neu"-Formular und eingetipptem
Text lädt währenddessen NICHT automatisch neu (Eingabe bleibt erhalten).

### Auslieferungspaket

`deploy/portal-v97.tar.gz`

---

## 2026-08-01 – portal-v96: Wünsche #98 + #99 – Sportschau: Schritte-Durchschnitt, Y-Achsen-Beschriftung

### Wunsch #98 – Durchschnittswert bei den Schritten

"Neben der Überschrift 'Schritte je Tag' soll rechts der Durchschnittswert
für den ausgewählten Zeitraum angezeigt werden. Dabei sollte der heutige
Tag nicht einberechnet werden, da er das Ergebnis verfälscht." Neues Feld
`schritte_schnitt` in `14_sportschau.py::index()`: Durchschnitt über
`schritte_balken` ohne den Eintrag für `heute`. Im Template rechts neben
der Überschrift ("Ø X ohne heute"), neuer `.steps-header`-Flex-Wrapper.

### Wunsch #99 – Y-Achsen-Beschriftung überlagert die interessanten Tage

"Die Beschriftung der Y-Achse bei den Schritten überlagert die Balken von
vorgestern, gestern und heute. Entweder links ausgerichtet, damit sie
weniger interessante Tage überlagert, oder eine andere Darstellung – aber
die Balkenwerte sollen weiterhin in Linie mit den Trainings aus dem Chart
darüber dargestellt sein." Die Tage-Liste ist älteste-zuerst sortiert
(heute steht immer ganz rechts), die Gridline-Beschriftung saß bei
`right:0` und lag deshalb genau über den jüngsten (interessantesten)
Balken. Einfacher CSS-Fix: `right:0` → `left:0` (+ `padding-right` statt
`padding-left`, damit der Hintergrund weiterhin die gestrichelte Linie
maskiert) – überlagert jetzt die ältesten Tage links, keine Änderung an
Balkenreihenfolge/-ausrichtung nötig.

### Verifiziert

`curl` gegen `/a/sportschau/<token>/?tage=14/30/60/90`: Durchschnittswert
erscheint neben der Überschrift, ändert sich korrekt mit dem Zeitraum
und schließt den heutigen Tag rechnerisch aus (manuell nachgerechnet
gegen die Rohwerte aus `schritte_balken`). CSS-Änderung der Gridline-
Beschriftung visuell per `javascript_tool` geprüft: Label sitzt jetzt
über den ältesten Balken, keine Überlappung mehr mit den letzten drei
Tagen.

### Auslieferungspaket

`deploy/portal-v96.tar.gz`

---

## 2026-08-01 – portal-v94: Wünsche #96 + #97 – Geholfen-Aufgaben umbenennen/ergänzen, Rezept-Foto-Import

### Wunsch #96 – Geholfen-Aufgaben umbenennen und ergänzen

Friederikes Wunsch: "Spülmaschine ein" → "Spülmaschine einräumen",
"Wäsche falten" → "Wäsche zusammenlegen", neu dazu "Spülmaschine
ausräumen". Umbenennen war bisher nur per Code-Migration möglich (feste
`_DEFAULT_AUFGABEN`-Liste in `00_kern.py`) – jetzt zusätzlich direkt in
der Aufgabenverwaltung (`/a/geholfen/<token>/aufgaben`, admin-only) über
ein neues ✏️-Panel je Aufgabe, damit künftige Umbenennungen ohne Deploy
möglich sind. Migration in `00_kern.py` benennt bestehende Zeilen per
`UPDATE ... WHERE name='...'` um (idempotent) und seedet die neue
Aufgabe nur, falls sie noch nicht existiert.

### Wunsch #97 – Rezept-Import per Foto

"Neben URL importieren soll es einen neuen Button geben: Bild
importieren. Dann soll man per Kamera oder Mediathek ein Foto von einem
Rezept machen können und es wird per OCR und KI in ein Rezept
gewandelt." Neuer Button "📷 Bild importieren" neben "🔗 Aus URL
importieren" auf der Rezepte-Übersicht, führt zu
`/a/rezepte/<token>/importieren-bild` (neues Template
`rezept_bild_importieren.html`, Datei-Upload mit
`capture="environment"`). `_rezept_per_ki_bild()` in `11_rezepte.py`
ruft `ki_anfrage()` mit Bildeingabe auf – gleiches Muster wie
`_vokabeln_per_ki()` (Wunsch #80), eigener KI-Zweck
`"rezepte_foto_import"`, unabhängig vom URL-Import-Zweck
`"rezepte_import"` konfigurierbar (`manage.py ki_modell`). Ergebnis
landet wie beim URL-Import nur vorausgefüllt in `rezept_neu.html`, nie
direkt gespeichert – keine eigene Prüf-Ansicht nötig, anders als beim
Vokabeln-Foto-Import (dort liefert ein Foto mehrere Vokabelpaare
gleichzeitig, hier immer genau ein Rezept). Datei-Validierung
(Größe, MIME) identisch zu `foto_import()` in `16_vokabeln.py`.

### Verifiziert

- `curl` gegen `/a/geholfen/<token>/aufgaben`: umbenannte Aufgaben
  ("Wäsche zusammenlegen", "Spülmaschine einräumen") und die neue
  Aufgabe ("Spülmaschine ausräumen") korrekt gerendert.
- Umbenennen-Roundtrip per `curl -X POST action=umbenennen`: Name
  geändert, dann zurückgesetzt – Route funktioniert, Daten unverändert
  hinterlassen.
- `/a/rezepte/<token>/importieren-bild`: neuer Button auf der Übersicht
  verlinkt korrekt, Formularseite lädt (HTTP 200).
- Echtes Foto-OCR getestet: synthetisches Testbild eines Apfelkuchen-
  Rezepts (Name, Portionen, 6 Zutaten, 5 Zubereitungsschritte) hochgeladen
  – alle Felder korrekt im Formular vorausgefüllt, Formular postet wie
  beim URL-Import an die bestehende `/neu`-Route.
- Fehlerfälle geprüft: falscher Dateityp ("Nur JPG, PNG oder HEIC werden
  unterstützt."), fehlende Datei ("Bitte ein Foto auswählen.").

### Auslieferungspaket

`deploy/portal-v94.tar.gz` (Code), `deploy/portal-v95.tar.gz` (Hilfe-App-
Kapitel für #96/#97 nachgezogen, gleicher Änderungssatz)

---

## 2026-08-01 – portal-v92: Wunsch #95 – Sportschau: wählbarer Zeitraum

"Im Standard werden heute 14 Tage angezeigt. Über einen Button sollen
zusätzlich 30, 60 und 90 Tage auswählbar sein. Die Grafiken verändern
sich dann."

`_TAGE_ANZAHL` (feste Konstante) wurde zu `_TAGE_STANDARD` (Default) +
`_TAGE_OPTIONEN = [14, 30, 60, 90]`. Neue Query-Param `?tage=X` in
`index()`, validiert gegen die Optionsliste (ungültiger/fehlender Wert
fällt sicher auf 14 zurück, kein Crash-Risiko durch `to_int()`). Im
Template eine Button-Reihe (`?tage=14/30/60/90`, aktueller Wert
hervorgehoben). Heatmap-Zellen und Schritte-Balken brauchten keine
Sonderbehandlung für größere Zeiträume - beide nutzen bereits `flex:1`
pro Zelle/Balken, schrumpfen also einfach automatisch bei mehr Tagen
(genau das von Andi erwartete "Die Grafiken verändern sich dann").

### Verifiziert

`curl` gegen alle vier Optionen plus einen ungültigen Wert (`?tage=999`):
korrekte Zellenzahl je Zeitraum (33/96/369/549 für 14/30/60/90 Tage),
ungültiger Wert fällt korrekt auf 14 zurück. Per `javascript_tool` bei
90 Tagen: aktiver Button korrekt markiert, 90 Heatmap-Zellen und 90
Balken gerendert, kein horizontaler Overflow (`scrollWidth ==
clientWidth`) - Layout passt sich sauber an, keine abgeschnittenen
Elemente.

### Auslieferungspaket

`deploy/portal-v92.tar.gz`

---

## 2026-08-01 – portal-v90: Wünsche #93 + #94 – Todo-App: Formular einklappbar, Filtern

### Wunsch #93 – "+ Neue Aufgabe" als Knopf statt offenem Formular

Gleiches Muster wie Einkauf (Wunsch #85): Eingabeformular ist jetzt hinter
einem "+ Neue Aufgabe"-Knopf eingeklappt, bleibt nach dem Öffnen über
mehrere Einträge/Reloads offen (sessionStorage `todo_formular_offen`,
1:1 aus `einkauf.html` übernommen).

### Wunsch #94 – Filtern nach Benutzer und Status

Wunsch-Text sagte ursprünglich "nach Benutzer und ohne Status" - auf
Rückfrage bestätigt: Tippfehler, gemeint war "und Status" (zwei
unabhängige Filter-Dimensionen, keine Status-Ausschluss-Logik).

„🔍 Filtern" öffnet ein Panel mit Chip-Auswahl für Benutzer (erstellt_von
ODER zugewiesen_an passt) und Status (Backlog/Offen/In Arbeit/Erledigt),
beide gleichzeitig nutzbar. Rein clientseitig über `data-status`/
`data-nutzer`-Attribute an jeder Aufgabenkarte. **Anders als bei Einkaufs
Filtern (Wunsch #87, das sich bei jedem Reload zurücksetzt)**: hier
ausdrücklich `sessionStorage` (`todo_filter`) genutzt, damit der Filter
über Reloads hinweg bestehen bleibt, bis er per "Filter zurücksetzen"
explizit aufgehoben wird - exakt wie im Wunsch beschrieben. Status-
Überschriften (Backlog/Offen/...) blenden sich mit aus, wenn darunter
kein sichtbares Element mehr steht (gleiches "durch Geschwister-Elemente
laufen, bis zur nächsten Überschrift"-Muster wie beim Kategorie-Ausblenden
in `einkauf.html`).

### Verifiziert

Per `javascript_tool` gegen die echte Seite: Formular startet eingeklappt,
bleibt nach Öffnen über einen Reload offen. Status-Filter "Offen" zeigt
korrekt nur passende Karten, mit zusätzlichem Benutzer-Filter kombiniert
korrekt beide Kriterien gleichzeitig erfüllt. Filter übersteht einen
Reload unverändert (Chip-Auswahl, aktiv-Markierung am Filter-Knopf,
sichtbarer "Filter zurücksetzen"-Knopf). "Filter zurücksetzen" stellt
alle 6 Aufgaben wieder her, leert den gespeicherten Filter. Status-
Überschriften blenden sich korrekt aus, wenn nur noch eine Gruppe (hier:
Backlog) sichtbare Einträge hat. Leere Kombination (Status+Benutzer ohne
Treffer) zeigt korrekt "Keine Aufgabe passt zum Filter".

### Auslieferungspaket

`deploy/portal-v90.tar.gz`

---

## 2026-08-01 – portal-v87/v88: Wunsch #92 – Aufgabenplan als rollierende 14-Tage-Liste

Direkter Folgewunsch zu #89-#91, kam waehrend deren Umsetzung rein: "Der
Aufgabenplaner muss wie der Essensplaner eine rolierende 14 Tageliste
sein, mit den gleichen Funktionen, nur dass hier Aufgaben aus Geholfen und
aus dem Aufgabenpool je Familienmitglied gezogen werden."

**Vorab geklaert (echte Familiendaten betroffen - Friederikes/Johannes'
bestehende Wochenroutine):** Sollen die bestehenden woechentlich
wiederkehrenden Geholfen-Zuweisungen automatisch erhalten bleiben, oder
komplett auf Pool-Prinzip umgestellt werden? Antwort: automatisch
erhalten - nur die Darstellung wird zur Datumsliste, an der Speicherung
der Wochenregel aendert sich nichts.

### Umsetzung

`13_kinderplan.py` komplett neu geschrieben, Struktur an `12_essensplan.py`
angelehnt: `montag = heute - timedelta(days=heute.weekday())`,
`tage_daten = [montag + timedelta(days=i) for i in range(14)]`, Aufteilung
in `vergangene_tage`/`aktuelle_rest`/`naechste_woche` genau wie beim
Essensplan. Fuer jeden der 14 echten Kalendertage:
- **Geholfen-Aufgaben**: weiterhin ueber `kinderplan_eintraege.wochentag`
  (unveraendert, bewusst NICHT umgestellt) - pro Tag wird per `d.weekday()`
  nachgeschaut, welche Regeln passen. Erledigt-Status jetzt ueber den
  ganzen 14-Tage-Bereich abgefragt (`geholfen_eintraege` gruppiert nach
  Datum), nicht mehr nur "heute".
- **Todo-Pool-Instanzen** (Wunsch #90): `todos.wochentag` (0-6) durch
  `todos.plan_tag` (ISO-Datum) ersetzt - eine Einsortierung ist jetzt an
  einen echten Kalendertag gebunden, kein abstraktes Wochentag-Muster.
  `wochentag` bleibt als totes Altfeld liegen (SQLite droppt keine Spalten
  gefahrlos), betrifft aber keine echten Daten - die Spalte existierte erst
  seit derselben Sitzung (#90) und wurde nie mit Produktivdaten befuellt.
  `04_todo.py`s `serie_einsortieren()` entsprechend angepasst.
- **Sperre**: `_gesperrter_wochentag()` (Wochentag-Zahl) wurde zu
  `_gesperrter_tag_datum()` (echtes Datum) - sonst waere z. B. IMMER
  "naechsten Montag" gesperrt gewesen, nicht nur der eine konkrete
  kommende Montag.

**Bewusst nicht gebaut:** Drag & Drop zwischen Tagen (anders als beim
Essensplan) - fuer Geholfen-Aufgaben ergibt das keinen Sinn (eine Karte
verschieben wuerde die GANZE Wochenregel verschieben, nicht nur diesen
einen Tag), fuer Todo-Pool-Instanzen waere es technisch moeglich, aber
fuer diesen ersten Wurf zurueckgestellt.

### Ein zweiter Bug nebenbei gefunden und gefixt: Server-Zeitzone

Beim Testen der 20-Uhr-Sperre aufgefallen: der Container laeuft in UTC
(`docker exec portal python3 -c "import time; print(time.tzname)"` ->
`('UTC','UTC')`), aber `datetime.now()` (naiv, ohne Zeitzone) wurde direkt
mit "ab 20 Uhr" verglichen - das meint aber deutsche Ortszeit, nicht UTC.
Live nachgewiesen: um 01:13 Uhr deutscher Zeit war die UTC-Stunde noch 23
(Vortag) - der ALTE Code haette den Plan faelschlich gesperrt (23 >= 20),
obwohl es faktisch kurz nach Mitternacht war, weit weg von "20 Uhr
abends". Fix: `ZoneInfo("Europe/Berlin")` (gleiches Muster wie in
`14_sportschau.py`) fuer sowohl die Sperre als auch die "heute"-Bestimmung
(letzteres war bisher nur in einem schmalen 1-2-Stunden-Fenster um
UTC-Mitternacht falsch, aber ebenfalls ein echter Fehler).

### Verifiziert

Live an Friederikes echtem Plan (user_id=3, "Tisch decken" an Mittwochen):
"Tisch decken" erscheint nach dem Umbau exakt an BEIDEN Mittwochen im
14-Tage-Fenster (29.07. und 05.08.), keine Daten verloren oder verfaelscht.
Neue Testvorlage im Pool angelegt, fuer "heute" eingesetzt -> `todos`-Row
mit korrektem `plan_tag` (echtes ISO-Datum) und `wochentag=NULL` bestaetigt
per DB-Abfrage; Abhaken funktioniert. Zeitzonen-Fix verifiziert: vor dem
Fix haette "heute" faelschlich den Vortag gezeigt und der Plan waere
gesperrt gewesen, nach dem Fix zeigt "heute" korrekt das deutsche Datum,
0 Karten gesperrt (passend zur echten Uhrzeit kurz nach Mitternacht).
Johannes' (bisher leerer) Plan und Andis eigener Plan (Wunsch #91) beide
fehlerfrei mit "Nichts geplant" bzw. eigenen Eintraegen geladen. Testdaten
danach entfernt.

### Auslieferungspaket

`deploy/portal-v87.tar.gz` (Grundumbau) → `v88.tar.gz` (Zeitzonen-Fix)

---

## 2026-08-01 – portal-v85: Wünsche #89 (Sportschau-Stacking), #90 (Wiederkehrende Aufgaben/Pool), #91 (Aufgabenplan für Eltern)

### Wunsch #89 – Sonstige Schritte als Basis, Training oben

Andi: "Sonstige Schritte sind Alltägliche Schritte. Diese sollten bei
stacked bars unten dargestellt werden, weil sie die Basis sind. Trainings
kommen 'on Top'." Reiner DOM-Reihenfolge-Fix in `sportschau.html`: in
einem `flex-direction:column`-Stack bestimmt die Reihenfolge der Kind-
Elemente, welches oben/unten landet. `.steps-bar-training` steht jetzt
VOR `.steps-bar-nontraining` im Markup - Training (fixe Höhe) füllt den
oberen Teil des Stacks, Sonstige (flex:1, füllt den Rest) bildet die
Basis gegen die Grundlinie. Verifiziert per `getBoundingClientRect()`:
`trainRect.top < nontrainRect.top` (Training liegt oben).

### Wunsch #91 – Aufgabenplan auch für Eltern

Bisher konnten Eltern in `kinderplan.py` nur fremde (Kinder-)Pläne
verwalten, hatten aber keinen eigenen. Alle `rolle='kind'`-Filter auf
`rolle IN ('kind','eltern')` erweitert (Personen-Auswahl, Ziel-Validierung
in `zuweisen`/`abhaken`), Eltern landen jetzt standardmäßig auf ihrem
eigenen Plan (vorher nur bei Kindern der Fall). Die 20-Uhr-Sperre bleibt
für Eltern/Admin ohnehin ausgenommen (`_darf_verwalten()`), auch am
eigenen Plan - unverändert. Grants für `kinderplan` waren bei Andi/Simone
bereits vorhanden (nötig fürs Verwalten fremder Pläne), keine neuen Grants
nötig. Verifiziert: Andi sieht jetzt standardmäßig seinen eigenen Plan,
Picker zeigt alle vier Familienmitglieder, alle 7 Tage editierbar.

### Wunsch #90 – Wiederkehrende Aufgaben-Vorlagen mit Pool

Größter der drei Wünsche, zwei echte Architekturfragen vorab geklärt:
Einsortieren in Wochentage passiert in der bestehenden Aufgabenplanung
(kinderplan), nicht in einer neuen eigenen Ansicht; die Wiederkehr-Regel
ist pro Vorlage wählbar - entweder "Intervall nach Erledigung" (z. B.
alle 7 Tage) oder "fester Wochentag" (z. B. jeden Montag).

**Datenmodell:** Neue Tabelle `todo_serien` (Vorlage: Inhalt + Wiederkehr-
Regel + aktiv-Flag), `todos` bekommt `serie_id`+`wochentag`. Eine aus dem
Pool eingesetzte Instanz ist ein ganz normales `todos`-Row mit gesetztem
`serie_id` - nutzt die komplette bestehende Todo-Mechanik (Status,
Historie, Löschen, Anzeige in der Todo-App mit neuem 🔁-Chip) unverändert
mit, kein separates Tracking.

**Pool-Logik** (`04_todo.py`): `_serie_ist_im_pool()` prüft: keine offene
Instanz vorhanden, und - falls schon mal erledigt - die Wiederkehr-
Schwelle erreicht. Bei "wochentag" ist die Schwelle immer der NÄCHSTE
passende Wochentag NACH dem Erledigungsdatum, nie derselbe Tag (sonst
würde eine am eigenen Zieltag erledigte Aufgabe sofort wieder auftauchen).
Rein lazy berechnet bei jedem Seitenaufruf, kein neuer Scheduler-Job.

**Cross-App-Zugriff:** `teile/__init__.py` bekam einen zweiten Alias
(`teile.todo` für `04_todo.py`, analog zum bestehenden `teile.kern`),
damit `kinderplan.py` sauber `from teile.todo import serien_pool_liste,
serie_einsortieren` schreiben kann - `todos_neu()`s Docstring versprach
das schon länger für andere Module, aber niemand hatte bisher einen
Alias dafür angelegt.

**Neue Oberflächen:** `/a/todo/<token>/serien` (neues Template
`todo_serien.html`, verlinkt im Hamburger-Menü der Todo-App) zum Anlegen/
Pausieren/Löschen von Vorlagen. In `kinderplan.html` erscheint im
Bearbeiten-Modus jeder Tageskarte ein neuer "🔁 Aus Pool holen"-Bereich
mit den gerade verfügbaren Vorlagen als Chips; eingesetzte Instanzen
zeigen sich als normale Aufgaben-Zeile mit eigenem Abhaken-Knopf
(`serie_erledigen`-Route, schreibt direkt in `todos`, kein Umweg über
`geholfen_eintraege` wie beim bestehenden Kinderplan-Mechanismus).

**Bewusst nicht gebaut:** Bearbeiten/Löschen einer bereits eingesetzten
Instanz direkt aus der Aufgabenplanung heraus - dafür einfach in die
Todo-App wechseln, ist ja ein ganz normales Todo.

### Verifiziert

Per `javascript_tool` gegen die echte Seite, kompletter Kreislauf:
Vorlage "alle 7 Tage" angelegt → erscheint korrekt im Pool → als Chip in
kinderplan sichtbar → eingesetzt für Montag/Andi → erzeugt nachweislich
ein `todos`-Row mit `serie_id`+`wochentag` (per DB-Abfrage bestätigt) →
verschwindet korrekt aus dem Pool → erscheint in der Todo-App mit
🔁-Chip → über kinderplan abgehakt → `erledigt_am` korrekt gesetzt →
`erledigt_am` künstlich 8 Tage zurückdatiert → taucht korrekt wieder im
Pool auf. Zweite Vorlage mit "fester Wochentag = Montag" angelegt,
Wiederkehr-Schwelle direkt gegen `_serie_ist_im_pool()` mit drei
verschiedenen historischen Erledigungsdaten getestet - Schwelle lag in
allen drei Fällen exakt auf dem erwarteten "nächsten Montag danach".
Alle Testdaten (Vorlagen + Todos) danach wieder entfernt.

### Auslieferungspaket

`deploy/portal-v85.tar.gz`

---

## 2026-07-31 – portal-v83: Einkauf – freundlicher Hinweis statt Browser-Fehler bei Bearbeiten/Löschen offline

Anschlussfrage nach dem Offline-Umbau: "Die Beiden Fälle Bearbeiten und
Löschen sind dann auch offline nicht aufrufbar, oder werden die geänderten
daten dann einfach verworfen?" Antwort war ehrlich: keins von beidem -
beide sind weiterhin ganz normale native Formulare (kein `fetch()`, keine
Warteschlange), also technisch anklickbar, scheitern aber offline hart mit
der **Browser-eigenen** "Keine Verbindung"-Fehlerseite statt einer
App-Meldung, und die Eingabe ist in dem Moment weg. Andi wollte das
abgefangen haben - explizit wegen der Sorge, dass ein eigentlich gelöschter
Artikel offline scheinbar verschwindet, dann aber (weil serverseitig nie
angekommen) wieder auftaucht und für Verwirrung/Ärger sorgt.

**Fix:** Vor dem eigentlichen Absenden wird jetzt `navigator.onLine`
geprüft (`pruefeVerbindungOderZeigeHinweis()` in `einkauf.html`) - ist kein
Netz da, erscheint ein Toast ("📡 Bearbeiten/Löschen braucht eine
Verbindung") und das Formular wird gar nicht erst abgeschickt. Beim
Löschen-Formular läuft die Prüfung VOR dem `confirm()`-Dialog
(`pruefeLoeschenOnline()`) - macht keinen Sinn, erst "wirklich löschen?"
zu fragen und danach zu sagen, dass es sowieso nicht geht. Toast-Element
und -Funktion sind bewusst 1:1 nach dem bereits bestehenden Muster aus
`geholfen.html` gebaut, keine neue UI-Komponente erfunden.

**Bewusst weiterhin keine Warteschlange für Bearbeiten/Löschen** - nur der
harte Fehlschlag wurde durch eine freundliche, unmissverständliche Meldung
ersetzt. Die Änderung selbst ist nach wie vor weg, wenn offline versucht
wird - das war explizit gewünscht (siehe Andis Formulierung), nicht als
Kompromiss zu verstehen.

### Verifiziert

Per `javascript_tool` gegen die echte Seite (`navigator.onLine` künstlich
auf `false`): Löschen-Formular abgeschickt → `confirm()` wird nachweislich
NIE aufgerufen (überschriebene Test-Version blieb ungenutzt), Toast zeigt
"📡 Löschen braucht eine Verbindung"; Bearbeiten-Formular abgeschickt →
`event.defaultPrevented === true`, Toast zeigt "📡 Bearbeiten braucht eine
Verbindung". Danach `navigator.onLine` zurück auf `true`: Löschen zeigt
den `confirm()`-Dialog wieder ganz normal mit der korrekten Artikel-
Nachricht, Abbrechen verhindert das Absenden wie schon immer - keine
Regression am bestehenden Online-Verhalten.

### Auslieferungspaket

`deploy/portal-v83.tar.gz`

---

## 2026-07-31 – portal-v81/v82: Einkauf offline-fähig (per Chat-Anfrage, kein ✨-Wunsch)

Direkter Anschluss an die Offline-Grundinfrastruktur: "Die Einkaufen App
jetzt offline fähig werden! Das brauchen wir für die Akzeptanz!" - Abhaken
und Neu-Eintragen sollen im Supermarkt ohne Empfang funktionieren, nicht
nur die Ansicht selbst.

### Backend-Änderung: Toggle-Endpunkt idempotent gemacht

`POST /a/einkauf/<token>/erledigt/<eid>` war bisher ein reiner Toggle
(dreht den aktuellen Zustand um). Für eine Offline-Warteschlange ist das
gefährlich: würde ein technisch schon erfolgreicher, aber dessen Antwort
verlorener Request später nochmal wiederholt, würde ein reiner Toggle den
Zustand ein zweites Mal umdrehen - falsch. Fix: die Route nimmt jetzt ein
explizites `ziel` (0/1) entgegen und SETZT darauf, statt zu toggeln (Fallback
auf den alten Toggle nur falls `ziel` mal fehlt, z. B. bei sehr altem
gecachtem Frontend). Macht die Route idempotent - beliebig oft wiederholbar,
ohne den Endzustand zu verändern.

### Frontend: lokale Offline-Warteschlange (`einkauf.html`)

- **`toggleErledigt`**: wendet den neuen Zustand jetzt sofort optimistisch
  an (Checkbox + `.erledigt`-Klasse) und macht das bei einem Fehlschlag
  NICHT mehr rückgängig (früher: `cb.checked = !cb.checked`). Stattdessen
  landet die Aktion (`{type:'toggle', id, ziel}`) in einer Warteschlange
  in `localStorage` (nicht `sessionStorage` - muss auch einen App-Neustart
  überstehen, iOS pausiert/killt Hintergrund-Tabs), der Artikel bekommt ein
  "⏳ wartet"-Abzeichen.
- **Neu-Formular**: läuft jetzt über `fetch()` statt eines nativen POST,
  damit ein Netzwerkfehler abgefangen werden kann. Bei Erfolg: Reload wie
  vorher. Bei Fehlschlag: Eintrag in die Warteschlange (`{type:'add', ...}`
  mit einer lokalen `temp-`-ID), eine Platzhalter-Karte wird direkt
  angezeigt (Checkbox deaktiviert, "⏳ wartet"), das Formular bleibt offen
  und wird für den nächsten Eintrag geleert - kein Reload nötig, Wunsch #85
  greift dadurch automatisch weiter.
- **`synchronisiereWarteschlange()`**: spielt die Warteschlange der Reihe
  nach ab, bricht beim ersten weiterhin scheiternden Request ab (Rest bleibt
  liegen), lädt bei mindestens einem Erfolg die Seite neu - holt so den
  echten Serverstand und ersetzt jede Platzhalter-Karte durch den echten
  Artikel mit echter ID, statt die IDs manuell abzugleichen. Läuft beim
  Laden der Seite UND bei jedem `online`-Event.
- **`wendeWarteschlangeAufUiAn()`**: reconciled beim Laden sofort alle noch
  offenen Warteschlangen-Einträge in die Oberfläche (abgehakte Artikel +
  Platzhalter), bevor überhaupt versucht wird zu synchronisieren - sonst
  würde man kurz den alten, noch nicht synchronisierten Stand sehen.

**Bewusst NICHT offline-sicher:** Bearbeiten und Löschen - geringere
Priorität für den Anwendungsfall "im Laden abhaken/eintragen", zusätzliche
Komplexität durch Konfliktpotential (z. B. ein offline gelöschter, aber
noch nicht synchronisierter Artikel).

`apps.offline_faehig` für `einkauf` jetzt auf 1 gesetzt.

### Verifiziert

Per `javascript_tool` gegen die echte Seite - `window.fetch` temporär durch
eine immer scheiternde Funktion ersetzt, um einen echten Netzwerkfehler
zu simulieren (nicht nur `navigator.onLine`, sondern der tatsächliche
Request-Pfad):
- Artikel abgehakt während "offline": bleibt angehakt, bekommt "⏳ wartet",
  Aktion landet korrekt in der Warteschlange (`{type:'toggle', id, ziel:true}`).
- Neuer Artikel "offline" eingetragen: Platzhalter-Karte erscheint sofort
  (Checkbox deaktiviert, "⏳ wartet"), Formular bleibt offen und geleert,
  Aktion korrekt in der Warteschlange.
- Echtes `fetch` wiederhergestellt + Seite neu geladen: Warteschlange wird
  automatisch abgearbeitet, beide Aktionen erfolgreich, Seite lädt sich
  danach selbst neu - Warteschlange leer, abgehakter Artikel korrekt
  synchronisiert, neuer Artikel jetzt mit echter Server-ID statt Platzhalter-ID.
- `online`-Event ohne vorherigen Reload getestet: löst dieselbe
  Synchronisierung korrekt aus.
- Startseite: Einkauf-Kachel bleibt bei simuliertem Offline-Zustand
  anklickbar (nicht mehr grau), da `offline_faehig=1`.

Test-Artikel danach über die App selbst wieder entfernt (nicht per Raw-SQL,
damit `ON DELETE CASCADE` für die Angebot-Markt-Zuordnung sauber greift).

### Auslieferungspaket

`deploy/portal-v81.tar.gz` (Grundgerüst) → `v82.tar.gz` (Hilfe-Text ergänzt,
aktueller Stand)

---

## 2026-07-31 – portal-v79/v80: Offline-Grundinfrastruktur (per Chat-Anfrage, kein ✨-Wunsch)

Nach der Sportschau-Diagnose kam die Anschlussfrage auf, ob das Portal
selbst offline funktioniert (z. B. kein Empfang im Supermarkt). Antwort
war: nein, aktuell nicht - kein `fetch`-Handler im Service Worker, keine
Seiten-/Asset-Caches, und die Einkauf-App schreibt jeden Haken live per
`fetch()` zum Server (schlägt offline fehl, Checkbox macht sich selbst
rückgängig). Andi wollte daraufhin einen ersten, kleinen Schritt:

- Die App soll offline zumindest **starten** können.
- Ein Hinweis-Banner zeigt den Offline-Zustand an.
- Nicht offline-fähige Apps werden auf der Startseite grau + nicht anklickbar.
- Offline-Fähigkeit ist ein Flag pro App, das separat definiert wird.

### Architektur

- **`apps.offline_faehig`** (neue Spalte, Default 0): bewusst nicht per
  `manage.py` frei umschaltbar, sondern in `00_kern.py` per Migration
  gesetzt - ob eine App offline sicher ist (keine live-schreibenden
  Interaktionen ohne eigene Warteschlange), ist eine Entwicklerentscheidung,
  die ohnehin einen Deploy braucht. `manage.py listapps` (rein lesend) zum
  Nachschauen. Erste (und bisher einzige) offline-fähige App: **"hilfe"**
  (rein statischer Text, keine Formulare).
- **Service Worker (`sw.js`)**: bekam einen echten `fetch`-Handler -
  Network-first mit Cache-Fallback für eigene GET-Requests. Cached
  grundsätzlich jede besuchte Seite (auch nicht offline-fähige - technisch
  harmlos, zeigt höchstens einen alten Stand), POST-Requests werden nie
  abgefangen. Die eigentliche Sperre passiert nicht im Service Worker,
  sondern als Kachel-Gating auf der Startseite.
- **Startseite**: Kacheln bekommen `data-offline`, JS grau + sperrt Klick
  (per `e.preventDefault()`, live gegen `navigator.onLine` geprüft, nicht
  nur beim letzten Event) für alles ohne Flag, sobald offline.
- **`base.html`**: neues Offline-Banner ("📡 Offline – manche Funktionen
  sind eingeschränkt") auf jeder Seite, nicht nur der Startseite - reagiert
  auf `online`/`offline`-Events.

### Ein Bug unterwegs gefunden und gefixt

`navigator.serviceWorker.register('/static/sw.js')` gibt dem Worker per
Default nur den Scope `/static/` - er hätte `/p/...` und `/a/.../...`
NIE kontrolliert, egal wie gut der fetch-Handler ist. Fix: Registrierung
mit `{ scope: '/' }`, dafür braucht es zusätzlich den Response-Header
`Service-Worker-Allowed: /` beim Ausliefern von `sw.js` (sonst lehnt der
Browser den erweiterten Scope als SecurityError ab) - neuer
`@app.after_request`-Hook in `00_kern.py`, nur für genau diese eine Route.
Ohne diesen zweiten Teil hätte die ganze Funktion silent nichts getan.

### Verifiziert

Per `javascript_tool` gegen die echte Seite: Service Worker registriert
sich jetzt mit Scope `/` (vorher fälschlich `/static/`), kontrolliert die
Seite nach einem Reload; Startseite und "Hilfe"-Seite landen nachweislich
im Cache (`caches.open('portal-cache-v1')` zeigt die eigenen URLs);
`navigator.onLine` künstlich auf `false` gesetzt + `offline`-Event
gefeuert: Banner erscheint, alle 11 Kacheln (keine davon "hilfe" - die
taucht als Kachel gar nicht auf der Startseite auf) werden grau,
ein simulierter Klick wird nachweislich per `preventDefault()` blockiert;
zurück auf online: alles setzt sich sauber zurück, Klick geht wieder durch.

**Nicht testbar mit den verfügbaren Tools:** eine echte Netz-Unterbrechung
zu simulieren, um den `fetch`-Handler-Catch-Pfad (Cache-Fallback bei
echtem Netzwerkfehler) end-to-end zu verifizieren - das Browser-Tool bietet
keine Netzwerk-Emulation. Die Logik selbst folgt dem Standard-Pattern
(Network-first, Catch → `caches.match()`) und wurde per Syntax-Check
gegengeprüft, aber nicht live unter echtem Empfangsverlust getestet.

### Auslieferungspaket

`deploy/portal-v79.tar.gz` (Grundgerüst) → `v80.tar.gz`
(Service-Worker-Allowed-Fix, aktueller Stand)

---

## 2026-07-31 – portal-v78: Wunsch #88 – Fix Sportschau zeigt "heute" nie an

Andi: "Es ist der 31. Juli 20:24 Uhr, ich habe heute bereits ein Training
auf den Server übertragen und circa 9000 Schritte gelaufen und ebenfalls
übertragen. Aber die Daten werden nicht in der Grafik angezeigt."

### Root Cause (per hae-Server-eigenen Logs bestätigt)

`_hae_workouts()` schickte `endDate=heute.isoformat()` als bare Datum
(z. B. "2026-07-31", ohne Uhrzeit). Der hae-Server parst das offenbar als
Mitternacht UTC jenes Tages – bestätigt durch eine eigene Log-Zeile des
hae-Servers, die das geparste Start/Ende als vollen Zeitstempel ausgibt:
`2026-07-31T00:00:00.000Z` für ein übergebenes `endDate=2026-07-31`.
Ergebnis: JEDES Training, das nach Mitternacht am aktuellen Tag beginnt,
fällt aus dem Zeitfenster – nicht nur ein Rand-/Sonderfall, sondern ein
strukturelles Problem, das "heute" grundsätzlich jeden Tag aufs Neue
ausschließt.

**Fix:** `_hae_workouts()` schlägt jetzt einen Tag auf `end_date` auf,
bevor die Anfrage rausgeht. Ein dadurch zusätzlich mitgeholter "morgen"-Tag
ist unschädlich, da das Template nur über die feste `tage`-Liste iteriert,
die nie über "heute" hinausreicht (geprüft: `sportschau.html` rendert
Zellen ausschließlich für `tag in tage`).

Live gegen die echte hae-Server-API verifiziert: mit `endDate=heute+1`
liefert die gleiche Anfrage weiterhin korrekt die erwarteten 10 Trainings
zurück (kein Regressions-Bruch), und würde ein Training von heute jetzt
tatsächlich mitnehmen, sobald es ankommt.

### Ein zweiter, getrennter Befund: heutige Daten fehlen noch komplett beim hae-Server

Direkte Testabfragen mit einem sehr weiten `endDate`/`to` (bis weit in die
Zukunft, 2026-08-15) zeigen: weder ein Training noch Schritte vom 31. Juli
sind über die API überhaupt abrufbar – der letzte Datenpunkt (Training wie
Schritte) stammt vom 30. Juli, ca. 20:00 UTC / 22:00 Uhr Ortszeit. Das ist
**kein Portal-Bug** (die Schritte-Abfrage nutzt ohnehin schon exakte
Unix-Millisekunden statt eines bare Datums, hat also die Mitternacht-Falle
gar nicht) – die Daten von heute sind schlicht noch nicht beim hae-Server
angekommen (Sync von Andis Handy/Uhr offenbar noch nicht durchgelaufen,
trotz gegenteiliger Annahme). Sobald der Sync nachzieht, sollte die Grafik
dank des obigen Fixes korrekt reagieren – falls nicht: dann läge das
Problem auf der hae-Server-Seite selbst (geteilte Infrastruktur, siehe
`bauplan.md` Abschnitt 0), nicht im Portal-Code.

### Auslieferungspaket

`deploy/portal-v78.tar.gz`

---

## 2026-07-31 – portal-v76: Wunsch #87 Teil 2 (Einkaufsmodus)

Rückfrage an Andi zu "Einkauf starten" beantwortet: **Einkaufsmodus mit
Marktwahl** – Markt auswählen, dann Vollbild-Checkliste nur mit den dort
relevanten Artikeln (Angebote genau bei diesem Markt + alle Artikel ohne
Marktbindung), größere Abhak-Flächen für die Bedienung unterwegs im Laden.

**Design-Entscheidung:** Angebote bei einem ANDEREN Markt werden im
Einkaufsmodus bewusst ausgeblendet, nicht nur die eigenen gezeigt – die
Logik dahinter: eine Angebot+Markt-Zuordnung heißt "dafür extra zu diesem
Markt gehen", ist man gerade wo anders, ist der Artikel für einen anderen
Trip vorgemerkt und soll die aktuelle Einkaufsrunde nicht überladen.

**Umsetzung:** Dritter Knopf "🛒 Einkauf starten" neben "+ Neu"/"🔍 Filtern"
öffnet eine Marktauswahl (Single-Select, ein Einkauf = ein Markt), "Los
geht's" schaltet `body.einkaufsmodus` scharf: blendet Eingabeformular,
Filter und die Knopfleiste selbst aus (CSS `!important`, damit auch ein
zuvor offen gebliebenes Filter-Panel verschwindet), vergrößert Häkchen
(32px) und Artikelnamen (18px), zeigt oben eine sticky Leiste mit "Beenden".
Rein clientseitig über dieselben `data-angebot`/`data-laeden`-Attribute wie
Wunsch #87 Teil 1, kein Server-Roundtrip, kein sessionStorage (Zustand ist
für die aktuelle Einkaufsrunde gedacht, nicht zum Fortsetzen nach einem
Reload).

**Verifiziert:** Per `javascript_tool` gegen die echte Seite – Markt "Edeka"
gewählt, "Dosentomaten" (Angebot nur bei Netto) korrekt ausgeblendet, alle
anderen 31 Artikel sichtbar; Knopfleiste/Formulare per `getComputedStyle`
bestätigt ausgeblendet, Häkchen-Breite 32px, Artikelname-Schriftgröße 18px;
"Beenden" stellt alle 32 Artikel und die normale Ansicht sauber wieder her.

### Auslieferungspaket

`deploy/portal-v76.tar.gz`

---

## 2026-07-31 – portal-v73/v74: Wunsch #86 (mehrere Märkte pro Angebot) + #87 Filtern (Teil 1)

### Wunsch #86 – mehrere Märkte gleichzeitig im Angebot

Bisher war `einkauf_eintraege.laden_id` ein einzelner Markt. Neue n:m-Tabelle
`einkauf_eintrag_laeden(eintrag_id, laden_id)`, Migration übernimmt bestehende
Einzelwerte einmalig und idempotent (`INSERT OR IGNORE ... SELECT id, laden_id
FROM einkauf_eintraege WHERE laden_id IS NOT NULL`). `laden_id` bleibt als
totes Altfeld liegen (SQLite kann Spalten nicht gefahrlos droppen, gleiche
Begründung wie bei `rezepte.anleitung`) – neuer Code liest/schreibt nur noch
die Join-Tabelle.

`_clean_angebot` wurde zu `_clean_angebot_laeden` (validiert eine Liste statt
eines einzelnen Werts). Formular: Markt-Chips im Neu-Formular und im
Bearbeiten-Panel toggeln jetzt unabhängig voneinander (statt sich gegenseitig
auszuschliessen wie bei der Kategorie), Auswahl landet als kommagetrennte
Liste in einem versteckten `laden_ids`-Feld. Badge zeigt alle Märkte
(„% Edeka, Rewe").

**Verifiziert:** Migration lief sauber (bestehende echte Daten wie
„Dosentomaten" bei Netto 1:1 übernommen). Per `javascript_tool` gegen die
echte Seite: Artikel mit zwei Märkten anlegen, Badge zeigt beide; im
Bearbeiten-Panel einen Markt entfernen und einen anderen hinzufügen,
Badge aktualisiert korrekt; echtes Löschen über den App-eigenen Button
kaskadiert die Join-Tabelle sauber (`PRAGMA foreign_keys=ON`, von `get_db()`/
`new_db()` gesetzt – ein manueller Raw-SQL-Test ohne dieses Pragma hinterliess
zunächst verwaiste Zeilen, das war ein Artefakt des Testaufbaus, kein
App-Bug, danach manuell bereinigt).

### Wunsch #87 (Teil 1) – Filtern nach Markt/Angebot

Neben „+ Neu" jetzt auch „🔍 Filtern": öffnet ein Panel mit „% Nur Angebote"-
Chip und Markt-Mehrfachauswahl. Rein clientseitig (die komplette Liste ist
ohnehin schon gerendert) über `data-angebot`/`data-laeden`-Attribute an jeder
Artikelkarte, kein Server-Roundtrip, kein sessionStorage (setzt sich bei
jedem Neuladen zurück, wie die Vokabel-Suche). Kategorie-Überschriften
verschwinden mit, wenn kein offener Artikel der Kategorie mehr sichtbar ist;
"Kein Artikel passt zum Filter" erscheint bei leerem Ergebnis.

**"Einkauf starten" (zweiter Teil von #87) ist noch offen** – der Wunsch-Text
lässt mehrere sehr unterschiedliche Interpretationen zu (reiner Filter-
Shortcut vs. eigener "Einkaufsmodus" mit größeren Tap-Zielen vs. etwas
anderes), deshalb erst Rückfrage an Andi, bevor da etwas Falsches gebaut
wird (siehe `bauplan.md`/`CLAUDE.md`: "Im Zweifel fragen – vorher, nicht
hinterher").

### Auslieferungspaket

`deploy/portal-v73.tar.gz` (#86) → `v74.tar.gz` (#87 Filtern)

---

## 2026-07-31 – portal-v71/v72: Wunsch #85 (Einkauf: Formular bleibt offen)

Andi: "Wenn man die App öffnet, dann soll neben der Liste nur ein Neu
Button sichtbar sein. Das Formular zum eintragen öffnet sich dann auf der
Seite und bleibt offen bis man die App verlässt, damit man mehrere
Einträge nacheinander erfassen kann."

**Umsetzung (`einkauf.html`):** Das Eintragen-Formular (`.add-card`) ist
jetzt standardmäßig `display:none`, stattdessen steht oben ein einzelner
"+ Neu"-Knopf (`.btn-neu-toggle`, gleiche Optik wie das Pendant in
`vokabeln.html`). Klick öffnet das Formular und setzt ein Flag in
`sessionStorage` (`einkauf_formular_offen`) – dasselbe Prinzip wie das
schon bestehende `einkauf_letzte_auswahl` für Kategorie/Angebot/Markt:
übersteht den Seiten-Reload nach jedem Absenden (Formular bleibt über
mehrere Einträge hinweg offen, genau wie gewünscht), wird aber beim
echten Schließen des Tabs/Browsers verworfen – dann startet die App
wieder mit eingeklapptem Formular.

**Verifiziert:** Per `javascript_tool` gegen die echte Seite geprüft –
frischer Zustand (kein sessionStorage-Flag) zeigt nur den Knopf
(`display:none` auf `.add-card`); Klick öffnet das Formular und
fokussiert das Namensfeld; ein echtes Absenden eines Testeintrags
("Testeintrag-Wunsch85") plus anschließendem Seiten-Reload zeigt sowohl
den neuen Artikel in der Liste als auch das weiterhin offene Formular –
Testeintrag danach wieder aus der DB entfernt. Hilfe-Kapitel „🛒
Einkaufsliste" entsprechend ergänzt.

### Auslieferungspaket

`deploy/portal-v71.tar.gz` (Fix) → `v72.tar.gz` (Hilfe-Text ergänzt,
aktueller Stand)

---

## 2026-07-30 – portal-v70: Wunsch #83 (Fix Tierbaukasten-Galerie) + #84 (Anhören auf Übersichtsseite)

### Wunsch #83 – Muster in der Galerie verschwunden

Andi meldete: "Bei den gespeicherten Tieren verschwinden die Muster. Sind
die nicht gespeichert oder nur nicht angezeigt?" Antwort: nur nicht
angezeigt, kein Datenverlust – `muster`/`muster_farbe` waren in der DB
korrekt gespeichert.

**Ursache:** Die Galerie rendert jede Figur über das eigene Macro
`figur_vorschau(einzel_typ, suffix, muster_wert, koerperbau)`
(`tierbaukasten.html`), dessen `clipPath` auf
`#body-vorne-{{ einzel_typ }}{{ suffix }}` verweist (`suffix = '-' ~ k.id`,
z. B. `-5`, damit mehrere gespeicherte Tiere derselben Art keine doppelten
IDs erzeugen). Das zugrunde liegende Macro `koerper_vorne(typ)` – das
sowohl der interaktive Baukasten als auch die Galerie zur Körperform
nutzen – kannte diesen `suffix`-Parameter aber gar nicht und vergab immer
nur die feste ID (z. B. `id="body-vorne-katze"`, nie `-5`). Das
Schwester-Macro `koerper_seite(typ, suffix='')` hatte diesen Parameter
schon lange, `koerper_vorne` war beim Bau der Galerie (später als der
Baukasten selbst) offenbar übersehen worden. Damit lief `<use
href="#body-vorne-katze-5"/>` ins Leere, die `clipPath` blieb leer, und
die Mustergruppe (`<g clip-path="...">`) wurde komplett weggeclippt – der
Körper selbst wird direkt gerendert, nicht über den Clip, blieb also
sichtbar. Passt exakt zum gemeldeten Symptom.

**Fix:** `koerper_vorne` bekam ebenfalls `suffix=''` als Parameter, jede
der sechs Tierart-IDs wurde auf `id="body-vorne-{typ}{{ suffix }}"`
umgestellt, `figur_vorschau` reicht `suffix` jetzt an `koerper_vorne`
durch. Der Baukasten selbst ruft `koerper_vorne(k)` weiterhin ohne Suffix
auf (Standardwert `''`) – unverändertes Verhalten dort, sein eigener
`clip-{{ k }}`/`#body-vorne-{{ k }}` erwartete nie einen Suffix.

**Verifiziert:** Playwright/Screenshot weiterhin nicht nutzbar (siehe
unten), stattdessen per `javascript_tool` gegen die echte Seite geprüft:
alle fünf Galerie-`clipPath`s mit numerischem Suffix (`clip-katze-1`,
`clip-baer-10`, …) lösen jetzt zu existierenden Zielen mit realer BBox
auf (z. B. 84×100px statt vorher unauffindbar), die zugehörige
Mustergruppe hat eine reale BBox (~95×99px) mit `fill:var(--muster-farbe)`
– das Muster ist tatsächlich sichtbar, nicht nur die ID vorhanden.

### Wunsch #84 – Anhören auch auf der Übersichtsseite

Wunsch #81 brachte den "🔊 Anhören"-Knopf nur in den Trainer. Jetzt hat
auch jede Zeile in der Vokabelliste (`vokabeln.html`) einen 🔊-Knopf
neben dem ✏️-Bearbeiten-Knopf, der denselben Endpunkt
`/a/vokabeln/<token>/wort/<vid>/audio` abspielt (`wortAnhoeren(id)`,
identisches Prinzip wie im Trainer: einzelnes wiederverwendetes
`Audio`-Objekt, vorheriges wird pausiert, bevor ein neues startet).
Hilfe-Kapitel „📚 Vokabeln" entsprechend ergänzt.

**Verifiziert:** Alle 6 Vokabel-Zeilen der Testseite haben einen
funktionierenden Knopf (`onclick="wortAnhoeren(10)"` etc.); der
Audio-Endpunkt liefert per curl ein gültiges WAV
(`RIFF...WAVE`-Header, `Content-Type: audio/wav`,
`Content-Disposition: ...filename=aussprache.wav` – der iOS-Fix aus
Wunsch #81 greift auch hier, da derselbe Endpunkt).

### Auslieferungspaket

`deploy/portal-v70.tar.gz`

---

## 2026-07-30 – portal-v67 bis v69: Wünsche #80 (Foto-Import) + #81 (Aussprache), Grundprinzip KI-Modellwahl

### Was gebaut wurde

- **Grundprinzip (Wunsch #81, ausdrücklich für ALLE KI-Anwendungen gefordert):**
  Neue Tabellen `ki_konfiguration` (Modell je Verwendungszweck, z. B.
  "rezepte_import") und `ki_stimmen` (Modell+Stimme je Vokabeln-Sprache) in
  `00_kern.py`. `ki_anfrage()` liest das Modell jetzt über `ki_modell_fuer(feature)`
  aus der DB statt der festen Konstante `KI_MODELL` zu verwenden – die bleibt
  nur noch Fallback, falls keine Zeile existiert. Neu: `manage.py ki_modell`/
  `ki_stimme`/`listki` zum Ändern ohne Deploy, falls sich die Modell-Landschaft
  weiterentwickelt. `ki_anfrage()` bekam außerdem einen optionalen `bilder`-
  Parameter für Bildeingabe (Vision), den Wunsch #80 braucht.

- **Wunsch #80 (Foto-Import):** `/a/vokabeln/<token>/foto-import` – Foto
  hochladen (max. 8 MB, JPG/PNG/HEIC), Sprache wählen, KI (`vokabeln_ocr`-
  Zweck, aktuell dasselbe `anthropic/claude-haiku-4.5` wie beim Rezept-Import,
  da bereits vision-fähig und günstig) extrahiert Vokabelpaare als JSON.
  Ergebnis landet zur Kontrolle in `vokabel_foto_pruefen.html` (jede Zeile
  editierbar/abwählbar, ein gemeinsames Kapitel für den ganzen Stapel) –
  gleiches Prinzip wie der Rezept-URL-Import, nie direkt speichern.

- **Wunsch #81 (Aussprache):** Im Trainer erscheint nach jeder Antwort ein
  "🔊 Anhören"-Knopf (`vokabel_training.html`), der `/a/vokabeln/<token>/wort/
  <vid>/audio` abspielt. Erster Aufruf pro (Sprache, Wort) erzeugt die Datei
  per `ki_text_zu_sprache()` (OpenRouter-Endpoint `/api/v1/audio/speech`,
  Standardmodell `google/gemini-3.1-flash-tts-preview` mit Stimme "Kore" –
  deckt alle 5 Vokabeln-Sprachen inkl. Latein/Dänisch ab, die günstigere
  Modelle wie Kokoro nicht abdecken; bei kurzen Einzelwörtern ist der
  Preisunterschied ohnehin vernachlässigbar) und cacht sie dauerhaft unter
  `DATA_DIR/vokabel_audio/<sprache_id>/<hash>.audio` (Schlüssel: normalisierter
  Text, nicht vokabel_id – identische Wörter teilen sich die Datei). Zählt
  bewusst NICHT gegen das tokenbasierte KI-Kontingent (TTS wird pro Zeichen
  abgerechnet, anderes Maß).

### Zwei Bugs, beide erst live gefunden

1. **Gemini TTS akzeptiert kein `response_format=mp3`**, nur `pcm` – die
   generische OpenRouter-Doku nennt beide Formate als Option, das konkrete
   Modell aber nur eins. `ki_text_zu_sprache()` versucht jetzt erst mp3,
   weicht bei genau dieser Fehlermeldung auf PCM aus und packt das Ergebnis
   selbst in einen WAV-Container (Python-`wave`-Modul, keine neue
   Abhängigkeit) – 24 kHz/16-bit/Mono laut Google-Doku für Gemini TTS.
   Live gegen die echte API verifiziert, bevor deployt wurde.

2. **iOS/Safari spielte die WAV-Datei trotz korrektem `Content-Type: audio/wav`
   nicht ab** – Andi meldete "Audiofile wird auf iOS nicht abgespielt".
   Ursache: `send_file()` lieferte den `Content-Disposition`-Header mit dem
   internen Cache-Dateinamen (Endung `.audio`, generisch gewählt, weil das
   Format erst nach dem ersten KI-Aufruf feststeht). iOS' Medienpipeline
   verlässt sich beim Erkennen des Formats teils zusätzlich auf die
   Dateiendung im Namen, nicht nur auf `Content-Type`. Fix: `send_file(...,
   download_name="aussprache.wav")` – die Cache-Datei selbst bleibt
   `.audio`, nur der ausgelieferte Name bekommt die passende Endung. Von
   Andi auf dem echten iPhone bestätigt.

### Testergebnisse

Playwright/Chromium weiterhin nicht per Screenshot nutzbar. OCR-Pipeline per
curl mit einem winzigen 1×1-Test-PNG geprüft (Multipart-Upload, Vision-Aufruf,
JSON-Parsing, Fehlerpfad bei „keine Vokabeln erkannt" – alles korrekt
durchlaufen; echte Erkennungsqualität an einem realen Foto steht noch aus).
TTS live gegen die echte OpenRouter-API getestet (mp3 schlägt wie erwartet
fehl, pcm liefert 46080 Bytes, WAV-Verpackung ergibt gültigen RIFF-Header),
danach von Andi auf dem iPhone bestätigt – dabei zufällig entdeckt, dass
Friederike bereits aktiv mit der App arbeitet (eigene Latein-Vokabel "Ave =
Hallo" real angelegt, keine Testdaten). Erzeugte Audiodatei für "Run"
(Englisch) ist eine echte, dauerhaft nützliche Cache-Datei, keine Testdaten –
nicht gelöscht.

### Auslieferungspaket

`deploy/portal-v67.tar.gz` (Grundgerüst #80/#81) → `v68.tar.gz` (PCM/WAV-Fix)
→ `v69.tar.gz` (iOS-Dateiname-Fix, aktueller Stand)

---

## 2026-07-30 – portal-v66: Fix – Schritte-Balken in v65 unsichtbar

### Was kaputt war

Andi meldete: keine Schritte im neuen Balkendiagramm (Wunsch #77, v65)
sichtbar, obwohl curl-Tests zuvor plausible Werte in den `title`-Attributen
zeigten. Ursache: klassische CSS-Falle bei Prozent-Höhen. `.steps-bar-stack`
bekam seine Höhe per `style="height:X%"`, aber sein Elternelement
`.steps-bar-col` hatte KEINE eigene definite Höhe (nur `display:flex;
align-items:center` ohne `height`) – Kette der Höhenvererbung war
unterbrochen. CSS ignoriert Prozent-Höhen, deren Bezugsbox selbst nur
`auto` (inhaltsbestimmt) ist, komplett; die Balken kollabierten auf 0,
ohne Fehler, ohne Warnung. curl sieht nur das HTML/die Attribute, nicht das
gerenderte Layout – deshalb ist dieser Bug-Typ mit curl allein unsichtbar.

**Lektion:** Bei jedem Prozent-Höhen-Layout die komplette Elternkette bis
zu einer definiten Höhe durchgehen, sonst rendert nichts, ohne dass
irgendein Fehler auftaucht.

### Fix

`.steps-bar-col` bekommt jetzt explizit `height:100%` (relativ zu
`.steps-bars`, das wiederum `height:100%` von `.steps-chart` mit fixer
`height:150px` erbt – jede Stufe der Kette ist jetzt definite). Zusätzlich
Tageslabels aus den Balkenspalten in eine eigene `.steps-labels`-Zeile
unterhalb des Charts verschoben (vermeidet denselben Fallstrick für
zukünftige Anpassungen) und Gridlines von `.steps-chart` nach `.steps-bars`
verschoben, damit ihre Prozent-Position exakt zur Balkenfläche passt statt
zur äußeren, um das Padding größeren Box.

### Testergebnisse

Playwright/Chromium weiterhin nicht per Screenshot nutzbar (Chrome-
Erweiterung hängt fest, auch in frisch erstelltem Tab). Stattdessen
`javascript_tool` direkt im echten Tab genutzt, um `getBoundingClientRect()`
der gerenderten Elemente auszulesen - objektiver und in diesem Fall
aussagekräftiger als ein Screenshot: `.steps-chart` 150px, `.steps-bars`
134px, alle 14 `.steps-bar-stack`-Elemente mit korrekten, unterschiedlichen
Pixel-Höhen (0-134px) statt überall 0. Trainings-Anteil exakt geprüft (z. B.
18.07.: 5746/12081 Schritte = 47,6% - gerenderte `trainingH` 63.8px von
134px Stack-Höhe = exakt 47,6%). Farben per `getComputedStyle` bestätigt
(Training = var(--farbe) = rgb(52,152,219), Sonstige = var(--text-2) =
rgb(142,142,147)). Gridlines gleichmäßig verteilt (alle ~22px Abstand bei
2000er-Schritten). Diese Art von Bug künftig eher über `javascript_tool`/
`getBoundingClientRect()` statt nur curl absichern, wenn Playwright/
Screenshots gerade nicht verfügbar sind.

### Auslieferungspaket

`deploy/portal-v66.tar.gz`

---

## 2026-07-30 – portal-v65: Wunsch #77 (Sportschau-Schritte-Balkendiagramm)

### Was gebaut wurde

Neue Section unter der Heatmap: gestapeltes Balkendiagramm der Schritte je
Tag (14 Tage, dieselbe Konstante wie die Heatmap), Trainings-Schritte
(var(--farbe)) vs. sonstige Schritte (var(--text-2)) gestapelt, Hilfslinien
alle 2000 Schritte.

Datenquelle war zunächst unklar (`/api/workouts` liefert keine Schritte) –
Andi nannte den Endpoint `/api/metrics/step_count?from=${__from}&to=${__to}`
(aus einer Grafana-Panel-Query kopiert). Live geprüft: anders als
`/api/workouts` (ISO-Datum) erwartet dieser Endpoint `from`/`to` als
Unix-Millisekunden – funktioniert nicht mit ISO-Strings, keine
Fehlermeldung, einfach leeres/falsches Ergebnis. Antwort: stündliche
Buckets `{"date": ISO-UTC, "qty": Schrittzahl, "source": "..."}`, teils zwei
Quellen (Watch + iPhone) fürs selbe Fenster, dann aufsummiert.

Zuordnung "Trainings-Schritte": keine feinere Verknüpfung zwischen
Schritt-Bucket und Workout verfügbar, deshalb Näherung auf Stundenbasis –
eine Stunde zählt als Training, wenn ihr Zeitfenster ein Workout-Fenster aus
`/api/workouts` berührt (Intervall-Überlappungstest). Bei kurzen Workouts
innerhalb einer Stunde mit sonst wenig Bewegung kann das die
Trainings-Schritte leicht überschätzen – genauere Daten liefert die API
nicht, für eine grobe visuelle Einordnung ausreichend.

Farben (var(--farbe) für Training, var(--text-2) für sonstige Schritte)
bewusst als "Akzent vs. neutral" gewählt statt zwei konkurrierende
Kategorie-Farben – dataviz-Skill-Prinzip "categorical hues nur bei echten
gleichrangigen Kategorien, sonst Akzent/neutral" angewendet, keine neue
Palette nötig.

### Testergebnisse

Playwright/Chromium weiterhin nicht verfügbar (Chrome-Erweiterung hängt
fest, auch nach mehreren Stunden noch). Per curl gegen die echte Domain:
14 Balken vorhanden, Tooltip-Werte plausibel (z. B. "2026-07-18: 12081
Schritte (5746 beim Training)"), Trainings-Anteil überall ≤ Gesamt,
Hilfslinien korrekt bei 2000/4000/.../12000.

### Auslieferungspaket

`deploy/portal-v65.tar.gz`

---

## 2026-07-30 – portal-v64: Wünsche #76, #78, #79

### Was gebaut wurde

- **Wunsch #76 (Vokabeln):** Drei neue Standardsprachen (Dänisch, Italienisch,
  Französisch) zu `_DEFAULT_SPRACHEN` ergänzt. Dabei einen latenten Bug in der
  Seed-Logik gefixt: Sie fügte Sprachen bisher nur ein, wenn `vokabel_sprachen`
  komplett leer war (`if COUNT==0`) – da die Tabelle längst Zeilen hatte
  (Englisch/Latein), wären die drei neuen nie angelegt worden. Jetzt
  unconditionell `INSERT OR IGNORE` je Sprache, idempotent über
  `UNIQUE(name)`. Neue Sprachen aktivieren sich Nutzer selbst auf der
  Sprachen-Unterseite (kein Auto-Grant für Bestandsnutzer, die schon eine
  Auswahl getroffen haben).

- **Wunsch #78 (Sportschau):** Heatmap von 10 auf 14 Tage erweitert
  (`_TAGE_ANZAHL`-Konstante in `14_sportschau.py`, Template-Texte nutzen
  `tage|length` statt hartkodierter Zahl).

- **Wunsch #79 (Vokabeln, neue Unterseite "Auswertung"):** Trainingszeit je
  Sprache (Balken, Minuten aus `vokabel_sessions.beendet - gestartet`, nur
  Sessions mit mindestens einem `vokabel_versuche`-Eintrag zählen) sowie
  richtig/falsch-Auswertung je Kapitel (gestapelter Balken, Wortlisten
  "✅ Gelernt"/"⚠️ Noch schwierig"/"○ Noch nicht geübt" nach letztem Versuch
  pro Vokabel). Kinder sehen nur die eigene Auswertung, Eltern/Admin können
  per Pill-Auswahl (`?fuer=<user_id>`) jeden Nutzer ansehen – serverseitig
  durchgesetzt, nicht nur UI-Versteckung (getestet: Kind kann `?fuer=` nicht
  umgehen). **Datenmodell-Hinweis:** `vokabel_sessions` speichert nur
  `sprache_id`, kein Kapitel (eine Session kann mehrere/alle Kapitel
  umfassen) – Trainingsdauer ist deshalb nur je Sprache sauber aggregierbar,
  nicht je Kapitel. Richtig/Falsch-Zählung hängt dagegen an der Vokabel
  selbst (über `vokabel_kapitel_zuordnung`) und ist je Kapitel exakt.
  Farben (Grün/Rot für richtig/falsch) 1:1 aus `vokabel_training.html`
  übernommen statt neu erfunden – dataviz-Skill vor dem Bau geladen,
  Formwahl dokumentiert im Code-Kommentar der Route.

- **Zurückgestellt (kein Wunsch, sondern offene Rückfrage):** Wunsch #77
  (Schritte-Balkendiagramm) braucht Schrittdaten, die `/api/workouts` vom
  hae-Server nicht liefert (nur workout_type/start_time/end_time/
  duration_minutes/calories_burned, live geprüft). Kein Endpoint dafür
  bekannt oder dokumentiert – Rückfrage an Andi nötig, ob es einen
  Schritte-Endpoint gibt oder der hae-Server das liefern könnte.

### Testergebnisse

Per curl gegen die echte Domain (Playwright/Chromium weiterhin nicht
verfügbar). Dabei zufällig entdeckt: Andi und Friederike nutzen die
Vokabeln-App bereits produktiv (echte Sessions/Vokabeln in der DB, keine
Testdaten von mir) – vor jeder Prüfung Zeitstempel kontrolliert, um echte
Nutzerdaten nicht mit Testresten zu verwechseln, nichts gelöscht.
Auswertungsseite mit dieser echten Datenlage geprüft: Trainingszeit-Balken,
richtig/falsch-Stacked-Bar (75%/25% bei 3 richtig/1 falsch, "letzter
Versuch zählt"-Logik korrekt), Sprachen-Filterung korrekt, Zugriffsschutz
für Kind-Rolle bestätigt (eigener Token + `?fuer=1` liefert trotzdem nur
eigene Daten). 14-Tage-Heatmap: 28 Zellen (2 Zeilen × 14 Tage) bestätigt.

### Auslieferungspaket

`deploy/portal-v64.tar.gz`

---

## 2026-07-30 – portal-v63: Wunsch #75 (Sportschau-Übersetzung)

### Was gebaut wurde

Der hae-Server liefert `workout_type` bereits deutsch lokalisiert, aber mit
schlechter Wortwahl: "Ausführen" statt "Laufen" für Run, "Spaziergang" statt
"Gehen" für Walk (vermutlich eine generische HealthKit-Übersetzung, die
"Run" als Verb liest). Da der hae-Server ein fremdes System ist (bauplan.md),
wird das im Portal selbst korrigiert: `_ART_KORREKTUREN`-Dict in
`14_sportschau.py`, ersetzt bekannte Fehlübersetzungen per Substring
("Ausführen"→"Laufen", "Spaziergang"→"Gehen"), unbekannte Werte (z. B.
"Wandern") bleiben unangetastet. Neue Fehlübersetzungen kommen bei Bedarf
per Wunsch in dieselbe Tabelle.

### Testergebnisse

Live gegen die echte hae-API geprüft (`docker exec portal python` von
diesem Rechner aus, ruft die letzten 30 Tage ab): tatsächliche Rohwerte
waren "Outdoor Ausführen", "Outdoor Spaziergang", "Wandern". Nach Deploy
zeigt `/a/sportschau/` korrekt "Outdoor Laufen" und "Outdoor Gehen".
Playwright/Chromium weiterhin nicht verfügbar (Chrome-Erweiterung hängt seit
vorheriger Sitzung fest) – wie zuvor per curl gegen die echte Domain
verifiziert, visueller Check steht weiterhin aus.

### Auslieferungspaket

`deploy/portal-v63.tar.gz`

---

## 2026-07-30 – portal-v62: Wunsch #74 (Sportschau-Namen abgeschnitten)

### Was gebaut wurde

`sportschau.html`: `.heatmap-name` hatte eine feste Breite (120px) mit
`text-overflow:ellipsis` – 1:1 aus `geholfen.html` übernommen, wo Namen
kurz sind (z. B. "Andi"). Trainingsarten vom hae-Server sind aber deutlich
länger ("Outdoor Ausführen", "Outdoor Spaziergang") und wurden abgeschnitten.
Fix: Name steht jetzt in einer eigenen Zeile über der Heatmap-Zellenreihe
(umbricht frei, kein Abschneiden), Zeilen durch `border-bottom` getrennt.
`geholfen.html` selbst unverändert, da dort kein Problem besteht.

### Testergebnisse

Playwright/Chromium stand weiterhin nicht zur Verfügung (Chrome-Erweiterung
hängt seit der letzten Sitzung fest, auch `example.com` liefert keinen
Screenshot). Stattdessen per `curl` gegen die echte Domain geprüft: neues
CSS ausgeliefert, beide echten Trainingsarten ("Outdoor Ausführen",
"Outdoor Spaziergang") erscheinen vollständig im HTML. Visueller Check
steht weiterhin aus, sobald das Browser-Tool wieder reagiert.

### Auslieferungspaket

`deploy/portal-v62.tar.gz`

---

## 2026-07-30 – portal-v61: Wünsche #72 (Rezepte) + #73 (Vokabeln-Neubau)

### Was gebaut wurde

Auf Zuruf "implementiere alle Wünsche" beide offenen, nicht zurückgestellten
App-Wünsche umgesetzt (Wunsch #51 bleibt bewusst liegen – Priorität
`zurueckgestellt`, siehe Regel in Wunsch #61/`05_werkstatt_app.py`).

- **Wunsch #72 (Rezepte):** Der 🌟-Stern für "wünsch ich mir" kollidierte
  optisch und logisch mit der ⭐-Sterne-Bewertung. Umgebaut zu einem klaren
  Ja/Nein-Knopf ("Wünschen?" / "✓ Gewünscht") in `rezepte.html` und
  `rezept_detail.html`, Filter-Chip von "🌟 Gewünscht" auf "📌 Gewünscht".
  Backend (`/wunsch/toggle`) unverändert.

- **Wunsch #73 (Vokabeln, kompletter Neubau):** Wunsch #67 war laut Andi
  ein Fehlversuch (zu viele Features in einem Wunsch, Friederike fand die
  Such-Übung verwirrend). Neues Schema in `00_kern.py`: `vokabel_sprachen`
  (global, Standard Englisch/Latein, neue kommen per Wunsch dazu),
  `vokabel_sprachen_nutzer` (Aktivierung pro Nutzer), `vokabel_kapitel`
  (pro Nutzer, anlegen/umbenennen/deaktivieren), `vokabeln` (fremd/deutsch/
  sprache_id statt der alten liste_id/quelle/ziel-Struktur),
  `vokabel_kapitel_zuordnung` (m:n), `vokabel_sessions` + `vokabel_versuche`
  (Start/Ende-Zeitstempel je Lerndurchgang, jeder Versuch protokolliert).
  `16_vokabeln.py` komplett neu geschrieben, alte Templates
  `vokabel_liste_form.html`/`vokabel_uebung.html` entfernt, neu:
  `vokabel_sprachen.html`, `vokabel_kapitel.html`, `vokabel_lernen.html`
  (Auswahl Sprache + Kapitel/Alle/Ohne-Kapitel), `vokabel_training.html`
  (Trainer: zufällige Richtung Deutsch↔Fremdsprache, falsche Antworten
  wandern ans Ende der Warteschlange, `pagehide` + `sendBeacon` schließen
  die Sitzung beim Verlassen sauber ab). Menüpunkte "Sprachen"/"Kapitel
  verwalten" in `base.html` ergänzt.

### Migration

`vokabeln`/`vokabellisten` (altes Schema) werden von keiner anderen
Tabelle per FK referenziert – Umbau per RENAME vor `executescript(SCHEMA)`
war daher gefahrlos (siehe Bekannte Issues zur FK-Falle bei `rezepte`).
Friederikes 3 echte Vokabelpaare (Run/Jump/Food, Liste "…englishvokabeln…")
wurden NICHT verworfen, sondern automatisch der Sprache Englisch
zugeordnet in die neue `vokabeln`-Tabelle übernommen – Migration lief beim
Deploy fehlerfrei durch (per SSH direkt in der DB verifiziert).

### Testergebnisse

Playwright/Chromium stand diese Sitzung nicht zur Verfügung (Chrome-
Erweiterung hing fest, auch auf `example.com` kein Screenshot möglich) –
stattdessen ausführlich über `curl` direkt gegen `https://portal.16schwaben.de`
getestet (von diesem Rechner, nicht vom Host):

- Rezepte: Toggle-Endpoint hin und zurück getestet (`markiert:true` →
  `markiert:false`), Detail- und Übersichtsseite zeigen den neuen Knopf.
- Vokabeln: Sprachen-Auto-Aktivierung beim ersten Aufruf, Kapitel anlegen/
  umbenennen/deaktivieren, Vokabel anlegen/bearbeiten/löschen (inkl.
  Kapitel-Zuordnung), Sprachen aktivieren/deaktivieren wirkt sich auf
  Auswahl in "Lernen" aus, Trainer-Start mit leerem Ergebnis (Meldung +
  Session sofort geschlossen), Trainer-Start mit Treffern (Warteschlange
  korrekt befüllt), `/versuch` protokolliert korrekt und wird nach
  Sitzungsende mit 400 abgelehnt, offene Sitzung wird beim nächsten
  Trainer-Start automatisch geschlossen (kein Leck bei Tab-Schließen ohne
  "Training beenden"). Alle Testdaten (TEST-Kapitel, Testword-Vokabel,
  Test-Sessions/-Versuche) danach restlos entfernt, Sprachen-Aktivierung
  für Andi zurückgesetzt.
- **Offen:** echter visueller/mobiler Check (Screenshot, Handy-Viewport)
  konnte wegen der hängenden Chrome-Erweiterung nicht durchgeführt werden –
  sollte nachgeholt werden, sobald das Tool wieder reagiert.

### Auslieferungspaket

`deploy/portal-v61.tar.gz`

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

---

## 2026-07-27 – Wunsch #12: App-Logo + Favicon (portal-v16)

Andi: PWA-Logo und Favicon fehlten noch (bisher nur ein einfarbig blaues
Quadrat als Platzhalter). Idee: „16 Schwaben" (Schwabenstr. 16) als Motiv.

### Umsetzung

`generate_icons.py` komplett neu: statt eines flächigen Blaus wird jetzt
eine weiße „16" auf Marken-Blau gezeichnet – ein handgeschriebenes
5x7-Pixelraster pro Ziffer, per Nearest-Neighbor-Skalierung auf jede
Icon-Größe gebracht. Weiterhin **kein Pillow** nötig, gleiche
Bauart (`struct`/`zlib`) wie vorher, nur mit echtem Motiv statt Flächenfüllung.

- `icon-512.png` / `icon-192.png` (PWA-Manifest, unverändert referenziert)
- neu: `favicon-32.png` / `favicon-16.png`
- `base.html`: `<link rel="icon" sizes="32x32">` + `sizes="16x16"` ergänzt
  (gab es vorher gar nicht – Browser bekamen bisher nur den impliziten
  `/favicon.ico`-404).

### Testergebnisse

- Icons lokal generiert und angesehen: „16" gut lesbar bei 512px, noch
  klar erkennbar bei 32px, bei 16px erwartungsgemäß sehr klein aber
  akzeptabel für einen Favicon: ✅
- Live von diesem Rechner abgerufen: alle vier Dateien 200 OK,
  `Content-Type: image/png`, Dateigrößen wie lokal erzeugt: ✅
- Playwright: `<link rel="icon"|"apple-touch-icon">`-Tags auf einer echten
  App-Seite korrekt vorhanden und verlinkt: ✅
- (Die Landing-/Denied-Seite `denied.html` nutzt bewusst kein `base.html`
  und hat daher keine Icon-Links – kein Bug, eigenständiges Minimal-Template.)

### Auslieferungspaket

`deploy/portal-v16.tar.gz` – nur `portal` neu gebaut/gestartet.

---

## 2026-07-27 – Alle "mittel"-priorisierten Wünsche: #13, #15, #19, #22 (portal-v17)

Auf Zuruf „Wünsche mit mittlerer Priorität jetzt alle umsetzen" – Backlog
nach `prioritaet='mittel' AND erledigt=0` gefiltert, ergab genau vier:

### Wunsch #13: Einkauf – 5s-Verzögerung + Sortierung

- Backend (`10_einkauf.py`): zwei getrennte Queries statt einer kombinierten
  – offene Artikel `ORDER BY name COLLATE NOCASE` (alphabetisch innerhalb
  der bestehenden Kategorie-Gruppierung), erledigte Artikel
  `ORDER BY erledigt_am DESC` (zuletzt abgehakt zuerst). Vorher sortierten
  erledigte Artikel fälschlich nach Erstellungs- statt Erledigungszeit.
- Frontend: Abhaken dimmt die Karte sofort (optimistisches UI, wie bisher),
  verschiebt sie aber erst nach 5 Sekunden physisch zu „Erledigt" (ganz
  oben). Wird innerhalb der 5s wieder abgewählt, wird der Umzug einfach
  abgebrochen – die Karte war nie woanders. Wird ein bereits einsortierter
  Erledigt-Eintrag abgewählt, wird neu geladen (korrekte Kategorie-/Alpha-
  Einordnung ist clientseitig nicht praktikabel nachzubilden).
- Nebenbei entdeckt und mitbehoben: Wird die letzte offene Karte einer
  Kategorie verschoben, bliebe sonst ein Kategorie-Titel ohne Inhalt
  stehen – wird jetzt mit entfernt.

### Wunsch #15: Hilfe nur noch über Hamburger-Menü

Eine Zeile in `01_start_token.py`: Kachel-Query schließt jetzt neben
`home` auch `slug='hilfe'` aus (`a.slug NOT IN ('home', 'hilfe')`). Grant
und Token bleiben unverändert bestehen – der Hamburger-Menüpunkt (kommt
aus `user.hilfe_token`, unabhängig von der Kachel-Query) funktioniert
weiter wie gehabt.

### Wunsch #19: Todos editierbar mit Historie

- Neue Tabelle `todo_historie` (todo_id, alter_inhalt, geaendert_von,
  geaendert_am).
- Neue Route `/a/todo/<token>/bearbeiten/<id>`: Berechtigung wiederverwendet
  die bestehende `_darf_erledigen()`-Regel (Eltern/Admin: jede Aufgabe;
  Kind/Gast: nur eigene, d. h. erstellt oder zugewiesen) – exakt die vom
  Wunsch geforderte Regel, kein neuer Berechtigungscode nötig. Vor jedem
  inhaltlichen Update wird der alte Text in `todo_historie` protokolliert.
- `todo.html`: die zwei fast identischen Blöcke (offen/erledigt) zu einem
  gemeinsamen Makro `todo_item()` zusammengefasst (gleiche Lehre wie bei
  Einkauf zuvor – Duplikate sind, wie sich zeigt, die Hauptursache für
  „Feature nur in einer Hälfte" -Bugs in diesem Projekt). ✏️-Button öffnet
  ein Panel mit Textfeld + „Speichern" sowie einer einklappbaren
  „🕘 Verlauf (N)"-Liste, wenn frühere Fassungen existieren.

### Wunsch #22: Einkauf – Artikeltext editierbar

- Neue Route `/a/einkauf/<token>/bearbeiten/<id>` (Name aktualisieren).
- Der bisherige „%"-Button wird zum „✏️"-Button und öffnet jetzt ein
  Panel mit: Namensfeld + Speichern, der bestehenden Angebot-Auswahl
  (unverändert übernommen) und dem Löschen-Button (jetzt hier drin statt
  als eigenes „×" in der Hauptzeile – „Löschen wandert in den Edit-Modus").

### Testergebnisse (Playwright, Wegwerf-Eltern-/Kind-Nutzer, danach restlos entfernt)

- #13: Items alphabetisch je Kategorie: ✅. Abhaken dimmt sofort, Karte
  bleibt < 5s an Ort und Stelle: ✅. Abwählen innerhalb 5s → nie
  umgezogen, nicht mehr gedimmt: ✅. Nach vollen 5s → physisch bei
  Erledigt, ganz oben: ✅.
- #15: Keine Hilfe-Kachel auf der Startseite: ✅. Hamburger-Menüpunkt
  weiterhin vorhanden und funktionsfähig: ✅.
- #19: Kind sieht fremde (Eltern-)Aufgabe, aber ohne ✏️-Button: ✅. Kind
  editiert eigene Aufgabe: ✅. Eltern editiert fremde (Kind-)Aufgabe: ✅.
  Verlauf zeigt die vorherigen Fassungen korrekt: ✅. Direkter POST eines
  Kindes auf eine fremde Aufgabe → 403 (Backend-Absicherung, nicht nur
  UI-Verstecken): ✅.
- #22: Alter „%"-Button verschwunden, ✏️ öffnet Panel: ✅. Name-Änderung
  übernommen: ✅. Kein eigenständiger Löschen-Button mehr in der
  Hauptzeile: ✅. Löschen aus dem Panel mit Sicherheitsabfrage
  funktioniert: ✅.
- Stolperstein beim Aufräumen: eigene Cleanup-Skripte ohne
  `PRAGMA foreign_keys=ON` lassen `ON DELETE CASCADE` nicht greifen –
  verwaiste `todo_historie`-Zeilen blieben hängen und wurden durch
  SQLite-Rowid-Wiederverwendung dem nächsten Test-Todo mit derselben ID
  zugeordnet (falsch hohe Verlauf-Anzahl in einem Testlauf). Immer
  `PRAGMA foreign_keys=ON` setzen, wenn per Rohzugriff aufgeräumt wird.

### Auslieferungspaket

`deploy/portal-v17.tar.gz` – nur `portal` neu gebaut/gestartet.

---

## 2026-07-27 – Alle offenen Geholfen-Wünsche: #27, #28, #29, #30 (portal-v18)

Auf Zuruf „alle Wünsche zur Geholfen-App umsetzen" – Backlog nach
`app_slug='geholfen' AND erledigt=0` gefiltert, ergab vier zusammenhängende
Wünsche (alle ohne Titel, direkt über ✨ eingetragen). Zusammen ergeben sie
ein Redesign der Hauptseite: Ticker und Statistik-Link raus, dafür Platz
für eine neue Heatmap.

### Wunsch #27 + #30: Kacheln verkleinern, Statistik ins Menü

- `.aufgabe-btn`: Padding/Mindesthöhe/Emoji-Größe deutlich reduziert
  (vorher `min-height:100px`, Emoji 40px → jetzt `min-height:64px`, Emoji
  26px), Grid-Spalten auf Mobile von 2 auf 3 erhöht (Tablet-Stufen
  entsprechend auf 4/5 verschoben).
- Der 📊-Button im Header (nur für Admins) ist weg, dafür ein
  „📊 Statistik"-Eintrag im Hamburger-Menü – nur sichtbar, wenn
  `app_slug == 'geholfen'` **und** `user.is_admin`. Route/Berechtigung
  (`uebersicht()`, weiterhin admin-only serverseitig geprüft) unverändert.

### Wunsch #28: Zuletzt-Liste auf eigene Seite

- Der Live-Ticker auf der Hauptseite ist komplett entfernt (Template +
  die dazugehörige AJAX-Update-Logik in `tippen()`/JS).
- Neue Route `/a/geholfen/<token>/verlauf` + Template
  `geholfen_verlauf.html` (mit Zurück-Link, zeigt die letzten 50
  Einträge). Erreichbar über „📜 Zuletzt geholfen" im Hamburger-Menü,
  für alle Nutzer mit Geholfen-Zugriff (nicht nur Admins).

### Wunsch #29: Heatmap unter den Kacheln

- `06_geholfen.py`: `index()` liefert jetzt zusätzlich `heatmap_nutzer`
  (Nutzer mit Rolle `eltern` oder `kind`, `gast` bewusst ausgeschlossen –
  genau wie im Wunsch beschrieben) sowie `tage`/`geholfen_tage` für die
  letzten 10 Tage.
- Je Nutzer eine Zeile mit 10 Feldern (grün = an dem Tag geholfen, grau =
  nicht). Nach erfolgreichem Antippen einer Kachel wird das heutige Feld
  der aktiven Person **sofort** grün (`tippen()` liefert jetzt
  `fuer_user_id` + `tag` statt der alten Ticker-Liste im JSON) – kein
  Reload nötig, passend zum bisherigen „live"-Charakter der App.

### Testergebnisse (Playwright, Wegwerf-Eltern-/Kind-Nutzer, danach restlos entfernt)

- Kein Ticker mehr auf der Hauptseite, Kachelhöhe jetzt 64px (vorher
  ~100px): ✅
- Kein 📊 im Header, aber „Statistik" und „Zuletzt geholfen" korrekt im
  Menü: ✅
- Verlauf-Seite lädt mit korrektem Titel und Zurück-Link: ✅
- Heatmap zeigt alle sechs Nutzer (4 echte + 2 Test) mit je 10 Zellen:
  ✅. Vor dem Antippen grau, direkt danach grün (optimistisches Update),
  nach Reload weiterhin grün (serverseitig korrekt gespeichert): ✅
- Kind sieht „Zuletzt geholfen" im Menü, aber nicht „Statistik": ✅.
  Direkter URL-Zugriff eines Kindes auf `/uebersicht` → 403 (serverseitig
  abgesichert, nicht nur im Menü versteckt): ✅
- Screenshot angesehen: kompakte Kacheln + Heatmap sehen aufgeräumt aus,
  echte Familien-Heatmap-Daten (Andi/Simone/Friederike/Johannes) korrekt
  und unangetastet neben den Testnutzern sichtbar.

### Auslieferungspaket

`deploy/portal-v18.tar.gz` – nur `portal` neu gebaut/gestartet.

---

## 2026-07-27 – Alle offenen "hoch"-priorisierten Wünsche: #23, #24, #25, #26, #31, #32 (portal-v19)

Auf Zuruf „alle Wünsche mit Priorität hoch umsetzen" – Backlog gefiltert
nach `prioritaet='hoch' AND erledigt=0`, ergab sechs (die schon
erledigten #12/#14 waren ebenfalls hoch, aber logischerweise ausgenommen).
Vier davon (#23-#26) sind ein zusammenhängendes Redesign des
Einkaufslisten-Edit-Panels, dazu #31 (Geholfen-Verlauf editierbar) und
#32 (Menüstruktur global).

### Wunsch #23 + #24 + #25: Einkauf Edit-Panel konsolidiert

- **#23**: Kategorie ist im Edit-Panel jetzt genauso wählbar wie im
  Neu-Formular (Button-Reihe, aktueller Wert vorausgewählt).
- **#24**: Der Angebot-Bereich im Edit-Panel funktioniert jetzt exakt wie
  beim Neuanlegen – erst der „% Angebot"-Button (gleiche Beschriftung an
  beiden Stellen, vorher inkonsistent „Angebot"/„Entfernen"), dann
  erscheinen die Markt-Buttons.
- **#25**: Name, Kategorie und Angebot sind jetzt EIN Formular mit einem
  einzigen „Speichern"-Button statt drei getrennter Teil-Formulare mit
  einem verwirrenden „Entfernen"-Button. Backend: `/bearbeiten/<id>`
  übernimmt jetzt alle drei Felder zusammen; die alte separate
  `/angebot/<id>`-Route (`set_angebot()`) ist komplett entfallen.
- Beim Konsolidieren gleich einen Nebenbug behoben: `add()` und
  `bearbeiten()` teilten sich vorher zwei fast identische, aber leicht
  unterschiedliche Validierungen für „Angebot ohne gültigen Markt" –
  jetzt ein gemeinsamer Helfer `_clean_angebot()`, der bei fehlendem
  Markt konsequent **beides** zurücksetzt (nicht nur den Markt), damit
  der „Angebot=1 aber kein Markt"-Zustand aus einem früheren Bugfix gar
  nicht erst wieder auftreten kann.
- Frontend: die drei separaten JS-Wiring-Funktionen (Neu-Formular,
  Angebot-Teilformular) sind zu einer gemeinsamen
  `wireKategorieAngebotForm()` zusammengefasst, die sowohl das
  Neu-Formular als auch jedes einzelne Edit-Panel bedient – gleiches
  Verhalten an beiden Stellen ist damit strukturell erzwungen statt nur
  per Konvention.

### Wunsch #26 + #32: Hamburger-Menü global umstrukturiert

- **#32**: Neue, für das ganze Portal geltende Menü-Reihenfolge:
  Startseite (immer oben) → Trennstrich → Einträge der aktuell
  geöffneten App → Trennstrich → allgemeine Einträge (Dark Mode, Hilfe,
  Verbesserungsvorschlag). Neue CSS-Klasse `.menu-divider`.
- **#26**: „Märkte verwalten" (bisher 🏪-Button im Einkauf-Header, nur
  Admins) ist jetzt Teil des App-spezifischen Menüblocks, wenn
  `app_slug == 'einkauf'` und der Nutzer Admin ist – gleiches Muster wie
  Geholfens „Statistik"/„Zuletzt geholfen".

### Wunsch #31: Geholfen-Verlauf editierbar für Eltern

- `geholfen_verlauf.html`: Eltern/Admin (`_kann_fuer_andere()`,
  wiederverwendet) bekommen je Eintrag ein ✏️, das ein Panel mit
  Datum/Uhrzeit (`datetime-local`), Nutzer- und Aufgaben-Auswahl (Selects
  – hier bewusst keine Button-Reihen, da seltene Admin-Aktion, nicht die
  Haupt-Interaktion wie bei Einkauf) sowie „Speichern" öffnet. Löschen
  des ganzen Eintrags mit der Standard-Sicherheitsabfrage.
- Neue Routen `/eintrag/<id>/bearbeiten` und `/eintrag/<id>/loeschen` in
  `06_geholfen.py`, beide serverseitig auf `_kann_fuer_andere()` geprüft.

### Testergebnisse (Playwright, Wegwerf-Eltern-/Kind-Nutzer, danach restlos entfernt)

- Einkauf: kein 🏪 im Header, aber im Menü. Kategorie-Reihe im Panel
  vorhanden, aktueller Wert vorausgewählt. Markt-Reihe anfangs
  versteckt, erscheint nach Toggle-Klick; Beschriftung „% Angebot"
  identisch zu Neu-Formular. Kein „Entfernen"-Button mehr, genau ein
  Speichern-Button. Kategorie- und Angebot-Änderung zusammen gespeichert
  → Artikel korrekt in neuer Kategorie mit Angebot-Badge: ✅
- Menü-Struktur exakt wie gefordert (Startseite, Trenner, App-Einträge,
  Trenner, Allgemein) per DOM-Reihenfolge geprüft: ✅
- Geholfen-Verlauf: Eltern sieht ✏️ und kann Nutzer+Aufgabe+Zeit ändern
  (Redirect zurück auf Verlauf bestätigt Erfolg). Kind sieht weder
  ✏️-Button noch darf es per direktem POST löschen (403, serverseitig
  abgesichert): ✅
- Alle Testartikel/-nutzer restlos entfernt (inkl. `PRAGMA
  foreign_keys=ON` beim Aufräumen, keine verwaisten Zeilen).

### Auslieferungspaket

`deploy/portal-v19.tar.gz` – nur `portal` neu gebaut/gestartet.

---

## 2026-07-27 – Letzte drei offene Wünsche: #18, #20, #21 (portal-v20)

Auf Zuruf „alle offenen Einträge jetzt umsetzen" – Backlog komplett
durchgesehen (`erledigt=0`, egal welche Priorität), nur noch drei
übrig, alle „niedrig". Danach ist der Backlog leer.

### Wunsch #18: Todos zeigen Erstellt- und Erledigt-Datum

Kleine Änderung in `todo_item()`: Meta-Zeile zeigt jetzt immer
„Erstellt: …", zusätzlich „· Erledigt: …" sobald der Status `erledigt`
ist. Kein Backend-Wechsel nötig (Felder gab es schon).

### Wunsch #20: Todos mit 4 Status-Stufen

- Neue Spalte `todos.status` (`backlog`/`offen`/`in_arbeit`/`erledigt`,
  Default `offen`); bestehende Zeilen einmalig aus dem alten
  `erledigt`-Flag befüllt.
- Der runde Abhaken-Kreis ist einem Status-Picker gewichen: vier kleine
  Chip-Buttons (Backlog/Offen/In Arbeit/Erledigt) in einem einzigen
  Formular mit vier benannten Submit-Werten – ein Tap wechselt direkt in
  die gewählte Stufe. `erledigt`/`erledigt_am` bleiben dabei bewusst mit
  `status` synchron gehalten, damit die bestehende Sortierung und die
  `#18`-Datumsanzeige unverändert weiterfunktionieren.
- Route `/check/<id>` durch `/status/<id>` ersetzt (Berechtigung
  unverändert: `_darf_erledigen()`, Eltern/Admin alle, Kind/Gast nur
  eigene). Die Seite zeigt jetzt bis zu vier Abschnitte statt zwei,
  leere Stufen werden wie gehabt ausgeblendet.

### Wunsch #21: App-Gruppen selbst verschiebbar

- Neue Route `/p/<token>/gruppe/reorder` (analog zur bestehenden
  App-`/reorder`, nur auf `home_gruppen.position` statt `grants`).
- Frontend: neuer Drag-Handle „⠿" im Gruppen-Header, eigener
  Pointer-Drag (gleiche Technik wie das bestehende Kachel-Ziehen, aber
  auf ganze `.gruppe-section`-Blöcke statt einzelne Kacheln angewendet,
  vertikal statt horizontal einsortiert). Bewusst über einen separaten
  Handle statt den ganzen Abschnitt ausgelöst, damit es nicht mit dem
  Ziehen der Kacheln *innerhalb* der Gruppe kollidiert. „Allgemein"
  bleibt strukturell ausgeschlossen (kein Handle, keine echte
  `home_gruppen`-Zeile) und damit immer die letzte Sektion.

### Testergebnisse (Playwright, Wegwerf-Eltern-/Kind-Nutzer, danach restlos entfernt)

- #18/#20: Neue Aufgabe landet unter „Offen" mit Erstellt-Datum, kein
  Erledigt-Datum. Wechsel zu „In Arbeit" korrekt aktiv markiert. Wechsel
  zu „Erledigt" zeigt danach beide Daten und Karte wandert sichtbar in
  den Erledigt-Bereich: ✅
- #21: Zwei Testgruppen angelegt, zweite per Drag am ⠿-Handle vor die
  erste gezogen → Reihenfolge sofort geändert, nach Reload weiterhin
  korrekt (serverseitig gespeichert), „Allgemein" bleibt letzte Sektion: ✅
- Alle Testdaten restlos entfernt (`PRAGMA foreign_keys=ON`, keine
  verwaisten Zeilen in `home_gruppen`/`todos`).

### Auslieferungspaket

`deploy/portal-v20.tar.gz` – nur `portal` neu gebaut/gestartet.

**Backlog ist damit vollständig abgearbeitet** – keine offenen Wünsche
mehr in `wuensche` (Stand 2026-07-27).

---

## 2026-07-27 – Drei neue Wünsche während der Arbeit: #33, #34, #35 (portal-v21)

Kamen rein, während an #18/#20/#21 gearbeitet wurde – auf Zuruf gleich
mit umgesetzt.

### Wunsch #33: Hamburger-Menü – Icons ohne Beschriftung, eine Zeile

Dark Mode, Hilfe und Verbesserungsvorschlag (die drei „allgemeinen"
Menüpunkte aus Wunsch #32) zeigen jetzt nur noch das Emoji, ohne
Textlabel, alle drei nebeneinander in einer Reihe (`.menu-icon-row`)
statt drei volle Zeilen untereinander – verkürzt das Menü deutlich,
besonders wenn eine App noch eigene Menüpunkte dazwischen hat. Die
Dark-Mode-Umschaltung selbst ist unverändert; nur das jetzt entfallene
`#dm-label`-Element musste aus dem zugehörigen JS entfernt werden.

### Wunsch #34: Titelleiste – Icon-Abstand oben/unten angleichen

`.app-header` hatte `padding-top: calc(var(--st) + 6px)` aber kein
`padding-bottom` – dadurch saßen ⌂/☰ oben sichtbar abgesetzt, unten aber
bündig mit dem Ende des farbigen Balkens. Einfach `padding-bottom: 6px`
ergänzt, für alle Apps einheitlich (betrifft auch `admin.html`, die
einzige verbliebene Nutzung von `header_extra`).

### Wunsch #35: Neue App „Essensplan" 🍽️

Wochenübersicht (Montag–Sonntag) mit ←/→ zum Blättern zu anderen Wochen
(`?start=YYYY-MM-DD`, Montag der Zielwoche). Pro Tag entweder ein
bestehendes Rezept aus der Rezepte-App auswählen oder frei eintragen –
nie beides gleichzeitig (Select und Textfeld leeren sich beim Ausfüllen
des jeweils anderen gegenseitig, per kleinem JS). Beide Felder leer
speichern entfernt die Planung für den Tag wieder.

- Neue Tabelle `essensplan_eintraege` (`tag` TEXT UNIQUE als Datum,
  `rezept_id` FK auf `rezepte`, `text`) – `UNIQUE` auf `tag` plus
  `INSERT … ON CONFLICT DO UPDATE` ergibt ein sauberes Upsert pro Tag,
  ohne erst nachschauen zu müssen ob für den Tag schon was existiert.
- Neues Modul `teile/12_essensplan.py`, Template `essensplan.html`.
  Heutiger Tag optisch hervorgehoben (Farbrahmen).
  Kein Cross-App-Feature zur Einkaufsliste eingebaut (anders als bei
  Rezepte selbst) – der Wunsch war dafür zu knapp formuliert, das käme
  erst mit einem eigenen Wunsch dazu.
- In `hilfe.html` dokumentiert, bei allen 4 echten Nutzern
  freigeschaltet (gleiches Vorgehen wie bei Rezepte).

### Testergebnisse (Playwright, Wegwerf-Nutzer, danach restlos entfernt)

- #33: genau 3 Icon-Buttons ohne Textlabel, alle auf gleicher
  Bildschirmhöhe (eine Zeile): ✅
- #34: `padding-bottom` des Headers berechnet zu `6px`: ✅
- #35: Woche zeigt 7 Tage Montag–Sonntag; Rezept-Verknüpfung zeigt
  „🍲 Name"; Freitext-Eintrag zeigt reinen Text; nächste Woche leer,
  vorherige Woche zeigt die Planung weiterhin korrekt; beide Felder
  leeren + Speichern entfernt die Planung wieder: ✅
- Testrezept, Test-Essensplan-Einträge und Test-Nutzer restlos entfernt
  (ein Eintrag wurde beim ersten Aufräumen übersehen und in einem
  zweiten Schritt nachgeholt).

### Auslieferungspaket

`deploy/portal-v21.tar.gz` – nur `portal` neu gebaut/gestartet.

---

## 2026-07-27 – Wunsch #36: Neue App „Aufgabenplan" (portal-v22)

Neuer Wunsch, direkt umgesetzt: Kinder ordnen wiederkehrende Aufgaben
Wochentagen zu, können ihren eigenen und die Pläne der Geschwister
einsehen, aber nur den eigenen editieren; Abhaken zählt in Geholfen mit;
ab 20 Uhr ist der Plan für den nächsten Tag nur noch für Eltern
änderbar.

### Design-Entscheidungen

- **Kein separater Aufgaben-Katalog** – der Plan referenziert direkt
  `geholfen_aufgaben` (dieselbe Tabelle wie die Geholfen-App), damit
  „Tisch decken" im Plan und in Geholfen garantiert dieselbe Aufgabe
  meint, nicht zwei gepflegte Kopien.
- **Kein eigener „erledigt"-Zustand** – Abhaken schreibt direkt einen
  neuen `geholfen_eintraege`-Datensatz (dieselbe Route/Tabelle, die auch
  die Geholfen-Kacheln benutzen). „Heute schon erledigt?" wird beim
  Anzeigen aus genau dieser Tabelle abgeleitet (Datum = heute), nicht
  separat gespeichert – kein doppelter, potenziell widersprüchlicher
  Zustand zwischen den beiden Apps.
- **Wochentag-Vorlage statt Datums-Instanzen** – `kinderplan_eintraege`
  speichert (Nutzer, Aufgabe, Wochentag) als dauerhafte wöchentliche
  Zuordnung (z. B. „montags Tisch decken"), kein Ablaufdatum. Die
  20-Uhr-Sperre wird rein zur Anzeige-/Bearbeitungszeit berechnet
  (`_gesperrter_wochentag()`: ab 20 Uhr ist der Wochentag von „morgen"
  gesperrt) – kein Sperr-Zustand wird gespeichert, er ergibt sich immer
  frisch aus der aktuellen Uhrzeit relativ zum Zieltag.
- **Kein Drag & Drop** – der Wunsch nannte das ausdrücklich als „wäre
  schön", nicht als Muss. Stattdessen: Tippen auf einen Aufgaben-Chip
  weist zu, nochmal tippen entfernt wieder (Toggle) – genauso
  „kinderleicht" bedienbar, ohne die Komplexität eines neuen
  Drag-Mechanismus für eine dritte Interaktion im Portal.
- Zuweisen/Editieren-Berechtigung reicht `_darf_verwalten()` (gleiche
  Regel wie Geholfens `_kann_fuer_andere()`: Eltern/Admin dürfen jeden
  Plan bearbeiten, Kinder nur den eigenen) – sowohl im UI ausgeblendet
  als auch serverseitig in `zuweisen()`/`abhaken()` durchgesetzt.

### Testergebnisse (Playwright, zwei Kind- + ein Eltern-Testnutzer, danach restlos entfernt)

- Kind A weist sich selbst eine Aufgabe für heute zu, hakt sie ab →
  Zeile dimmt sich, Button deaktiviert: ✅
- Kind B sieht Kind A's Plan (über den „Wessen Plan?"-Umschalter), aber
  rein lesend – kein Bearbeiten-Button, abgehakte Aufgabe nur als
  Ghost-Häkchen sichtbar: ✅. Direkter POST von Kind B auf Kind A's Plan
  → 403 (serverseitig abgesichert, nicht nur im UI versteckt): ✅
- Der Abhak-Eintrag von Kind A taucht unverändert in Geholfens
  „Zuletzt geholfen" auf – bestätigt die gemeinsame Datenquelle: ✅
- **20-Uhr-Sperre live gegen die echte Serverzeit getestet** (Test lief
  zufällig nach 20 Uhr): beim Kind war exakt der Wochentag von morgen
  gesperrt (🔒-Badge, kein Bearbeiten-Button), alle anderen Tage frei;
  bei Eltern war jeder Tag weiterhin bearbeitbar, auch der gesperrte: ✅
- Beim Aufräumen festgestellt: Friederike hatte in der kurzen Zeit seit
  dem Deploy bereits selbst reale Einträge angelegt – beim Löschen der
  Testnutzer sorgfältig nur deren IDs kaskadieren lassen, Friederikes
  echte `kinderplan_eintraege`/`geholfen_eintraege` blieben unangetastet.

### Auslieferungspaket

`deploy/portal-v22.tar.gz` – nur `portal` neu gebaut/gestartet, bei allen
4 echten Nutzern freigeschaltet.

---

## 2026-07-27 – Essensplan-Rework (vollständiger Wunsch #35) + Wunsch #37 (portal-v23)

Andi wies darauf hin, dass Wunsch #35 von Anfang an einen deutlich
umfangreicheren Text hatte, als beim ersten Umsetzen (portal-v21)
berücksichtigt wurde. Der Essensplan wurde daher komplett neu gebaut,
diesmal nach dem vollständigen Wunschtext: aktuelle **und** folgende
Woche gleichzeitig sichtbar (14 Tage), **zwei** Mahlzeiten-Slots pro Tag
(Mittag/Abend), Einträge per Drag & Drop zwischen Tagen verschiebbar,
vergangene Tage abgedunkelt, der heutige Tag mit der Akzentfarbe
umrandet, zukünftige Tage normal. Zusätzlich Wunsch #37: Einkaufs-
Kategorien sollen editierbar sein, mit eigener Unterseite im
Hamburger-Menü.

**Lehre für künftige Wunsch-Umsetzungen:** Wunschtexte immer vollständig
lesen, nicht nach dem ersten augenscheinlich vollständigen Absatz
aufhören – ein abgeschnittener Wunsch führt zu einer Implementierung,
die zwar funktioniert, aber am eigentlichen Bedarf vorbeigeht.

### Design-Entscheidungen – Essensplan

- **`essensplan_eintraege` von `UNIQUE(tag)` auf `UNIQUE(tag, mahlzeit)`
  umgestellt.** SQLite kann Tabellen-Constraints nicht per `ALTER TABLE`
  ändern – Migration daher als Rename-alt/Create-neu/Copy/Drop-alt,
  abgesichert über `PRAGMA table_info` (läuft nur einmal). Die 2 echten
  Bestandseinträge (Andi, Simone) wurden dabei automatisch auf
  `mahlzeit='abend'` gesetzt (bisheriges Verhalten war ohnehin nur ein
  Slot pro Tag) und blieben inhaltlich unverändert.
- **14 Tage als durchgehender Zeitraum ab Wochenmontag**, nicht als zwei
  separate Wochenblöcke mit eigener Navigation – entspricht dem
  Wunschtext („aktuelle und folgende Woche") und ist einfacher zu bauen
  als eine zusätzliche `?start=`-Wochennavigation nur für zwei Wochen.
- **Tages-Status (`vergangen`/`heute`/`zukunft`) wird bei jedem Aufruf
  frisch aus `date.today()` berechnet**, nicht gespeichert – ändert sich
  automatisch von Tag zu Tag ohne eigenen Cronjob.
- **Drag & Drop wieder mit Pointer Events** (nicht HTML5 DnD), exakt das
  gleiche bewährte Muster wie bei den Startseiten-Kacheln – Ghost-Element,
  `setPointerCapture`, 8px-Schwellwert vor Drag-Start, `drop-target`-
  Hervorhebung nur auf Slots mit gleicher Mahlzeit. Ein Tausch zwischen
  zwei belegten Slots braucht einen Platzhalter-Tag (`__tausch__`) für
  den Zwischenschritt, sonst verletzt die `UNIQUE(tag,mahlzeit)`-Regel
  kurzzeitig sich selbst.

### Design-Entscheidungen – Wunsch #37 (Einkauf-Kategorien editierbar)

- **Kategorien in eigene Tabelle `einkauf_kategorien`** (bisher
  hartkodierte Python-Liste). Migration befüllt sie einmalig mit den
  bisherigen 7 Standardkategorien, verknüpft bestehende
  `einkauf_eintraege` über eine neue `kategorie_id`-Spalte anhand des
  bisherigen Textfelds `kategorie`, mit Fallback auf „Sonstiges" falls
  kein Treffer.
- **Deaktivieren statt Löschen** (gleiches Muster wie Läden): Artikel mit
  einer inzwischen deaktivierten Kategorie verschwinden nicht, sondern
  fallen in einen neuen Sammelabschnitt „Ohne Kategorie" – kein
  Datenverlust durch eine spätere Kategorie-Änderung.
- Unterseite `/a/einkauf/<token>/kategorien` (admin-only) im
  Hamburger-Menü neben „Märkte verwalten", gleiches Editier-Panel-Muster
  (✏️-Toggle, ein Speichern-Button) wie überall sonst im Portal.

### Testergebnisse (Playwright, Wegwerf-Testdaten, danach restlos entfernt)

- Essensplan zeigt 14 Tage / 28 Mahlzeit-Slots, Labels „Mittag"/„Abend"
  korrekt: ✅
- Heute-Karte per `.heute`-Klasse hervorgehoben, keine `.vergangen`-Karte
  vor dem heutigen Tag (Woche beginnt am Testtag selbst, ein Montag): ✅
- Rezept-Verknüpfung und Freitext unabhängig je Slot speicherbar und
  löschbar: ✅
- Drag & Drop: Mittagessen von heute per ⠿-Handle auf den Mittag-Slot
  des Folgetags gezogen → `POST /verschieben` mit 200 beantwortet, nach
  Reload liegt der Eintrag korrekt im Zielslot, Quellslot leer: ✅
  (Ein erster Testlauf zeigte scheinbar keine Änderung – das war ein
  Timing-Fehler im Testskript, das den DOM-Zustand vor Abschluss des
  `location.reload()` geprüft hat, kein Produktbug.)
- Wunsch #37: Menüeintrag „Kategorien verwalten" vorhanden, Seite mit
  Zurück-Link; Kategorie anlegen/umbenennen funktioniert; neue Kategorie
  sofort im Einkaufs-Formular als Chip verfügbar; Artikel mit dieser
  Kategorie angelegt; Kategorie deaktiviert → verschwindet aus dem
  Formular, Artikel bleibt erhalten und landet unter „Ohne Kategorie": ✅
- Testrezept, Test-Essensplan-Einträge, Test-Kategorie und Test-Nutzer
  restlos aus der Datenbank entfernt (inkl. Cascade auf `grants`/
  `push_abos`).

### Auslieferungspaket

`deploy/portal-v23.tar.gz` – nur `portal` neu gebaut/gestartet.

---

## 2026-07-27 – Fix: Essensplan Drag & Drop nur zwischen gleicher Mahlzeit (portal-v24)

Andi meldete direkt nach dem Ausliefern von portal-v23: Ziehen funktioniert,
aber Loslassen auf einem anderen Tag oder zu einer anderen Zeit speichert
nichts. Ursache gefunden: sowohl das Frontend
(`targetSlot.dataset.mahlzeit === slot.dataset.mahlzeit`) als auch der
`/verschieben`-Endpunkt akzeptierten als Ziel ausschließlich denselben
Mahlzeit-Typ (Mittag→Mittag oder Abend→Abend) – ein Drop auf die jeweils
andere Mahlzeit wurde stillschweigend verworfen, ohne jede Rückmeldung.
Das automatisierte Playwright-Testen zuvor hatte zufällig nur den
funktionierenden Fall (gleiche Mahlzeit, anderer Tag) abgedeckt.

### Fix

- `12_essensplan.py`: `verschieben()` nimmt jetzt `von_mahlzeit` und
  `nach_mahlzeit` getrennt entgegen (statt eines gemeinsamen `mahlzeit`)
  und erlaubt jede Kombination außer identischem Quell-/Zielslot. Die
  Tausch-Logik (Platzhalter-Tag `__tausch__`) verschiebt jetzt sowohl
  `tag` als auch `mahlzeit` in beiden Schritten.
- `essensplan.html`: Drop-Highlight und Fetch-Aufruf akzeptieren jeden
  `.mahlzeit-slot` außer dem Quellslot selbst.
- `hilfe.html` entsprechend präzisiert („anderer Tag, andere Mahlzeit
  oder beides").

### Testergebnisse

Playwright gegen den Live-Server, drei Szenarien mit einem frischen
Wegwerf-Testnutzer (der vorherige Testnutzer war bereits aus M26
aufgeräumt und musste neu angelegt werden):
- Gleiche Mahlzeit, anderer Tag (Mittag heute → Mittag morgen): ✅
- Gleicher Tag, andere Mahlzeit (Abend heute → Mittag heute): ✅
- Anderer Tag UND andere Mahlzeit (Mittag heute → Abend übermorgen): ✅

Während des Testlaufs hat Andi selbst parallel auf seinem Handy den
reparierten Drag & Drop gegen dieselbe Live-Datenbank ausprobiert –
sichtbar an neuen echten Einträgen (u. a. „Vesper" für Mittwoch-Mittag),
die während des Testlaufs dazukamen. Kein Datenverlust: nur der eigene
Test-Datensatz (erstellt_von = Test-Nutzer-ID) und der Test-Nutzer selbst
wurden anschließend entfernt, alle echten Einträge blieben unangetastet.

### Auslieferungspaket

`deploy/portal-v24.tar.gz` – nur `portal` neu gebaut/gestartet.

---

## 2026-07-28 (Nacht-Session, automatisch) – Wunsch #38: Einkauf-Kategorien Sortierreihenfolge (portal-v25)

Andi hatte für die Nacht (via Cron-Job um 2 Uhr, da er keine Tokens mehr
übrig hatte) darum gebeten, alle offenen Wünsche selbstständig
umzusetzen. Diese und die folgenden Abschnitte entstanden dabei
autonom, ohne Rückfragen – Entscheidungen sind jeweils begründet.

Wunsch #38: Die Kategorien-Verwaltung der Einkaufsliste sollte nicht nur
editieren/deaktivieren, sondern auch die Sortierreihenfolge ändern
können.

### Design-Entscheidungen

- **Gleiches Pointer-Events-Drag-Muster wie beim Umsortieren der
  Startseiten-Gruppen** (`gruppe/reorder`) – ein-dimensionale Liste,
  ⠿-Handle, Ghost + Platzhalter, Fetch mit der neuen Reihenfolge als
  ID-Array. Kein neuer Mechanismus, sondern Wiederverwendung eines
  bewährten Musters.
- **`aktiv DESC` aus der Sortierung entfernt** – vorher wurden inaktive
  Kategorien immer ans Ende sortiert, unabhängig von `position`. Da der
  Wunsch ausdrücklich freie Sortierbarkeit verlangt, bestimmt jetzt
  ausschließlich `position` die Reihenfolge (auch für inaktive
  Kategorien) – konsistent mit `_kategorien_aktiv()`, die schon vorher
  nur nach `position` sortiert hat.
- Reorder-Route admin-only (wie alle Kategorien-Aktionen).

### Testergebnisse (Playwright, Wegwerf-Admin-Testnutzer, danach restlos entfernt)

- Erste zwei Kategorien per Drag vertauscht (Obst & Gemüse ↔ Kühlregal):
  DOM-Reihenfolge sofort korrekt: ✅
- Nach vollem Seiten-Reload weiterhin in der vertauschten Reihenfolge
  (persistiert in der DB, nicht nur clientseitig): ✅
- Zurückgetauscht und geprüft, dass die ursprüngliche (echte) Reihenfolge
  der Familie exakt wiederhergestellt ist: ✅

### Auslieferungspaket

`deploy/portal-v25.tar.gz` – nur `portal` neu gebaut/gestartet.

---

## 2026-07-28 (Nacht-Session, automatisch) – Wünsche #40, #41, #42: Essensplan-Feinschliff (portal-v27)

Drei kleine, zusammenhängende Essensplan-Wünsche in einem Rutsch
umgesetzt, weil sie dieselbe Datei/denselben Bildschirmbereich
betreffen und einzeln je einen eigenen Deploy-Zyklus für triviale
Änderungen bedeutet hätten:

- #41: Überschrift „Aktuelle Woche" über der ersten Wochenhälfte.
- #40: Überschrift „Nächste Woche" über der zweiten Wochenhälfte, mit
  größerem Abstand zur vorherigen Woche (Übergang Sonntag → Montag).
- #42: Vergangene Tage zu einem Block zusammengeklappt, der sich
  ausklappen lässt; die Tage selbst bleiben wie gehabt hell/grau
  dargestellt (nur die `opacity:.45`-Regel, die schon vorher existierte).

### Design-Entscheidungen

- **Aufteilung serverseitig statt im Template**: `12_essensplan.py`
  liefert jetzt `vergangene_tage`, `aktuelle_rest` und `naechste_woche`
  als getrennte Listen statt einer einzigen `tage`-Liste (die volle
  Liste bleibt zusätzlich für die Datumsspanne im Titel erhalten). So
  bleibt das Template simpel – kein Jinja-`namespace`-Gefrickel, um
  zusammenhängende vergangene Tage innerhalb einer Schleife zu erkennen.
- **Day-Card-Markup in ein Jinja-Macro (`tag_karte`) ausgelagert** –
  wird jetzt an drei Stellen (vergangen/rest/nächste Woche) aufgerufen,
  sonst wäre der große Block dreifach dupliziert gewesen (genau das
  Muster, das in dieser Session schon bei `item_card`/`todo_item`
  etabliert wurde). Variablen (`token`, `rezepte`, `mahlzeiten`,
  `mahlzeit_labels`) werden wie bei den anderen Macros in diesem Projekt
  explizit als Parameter übergeben, nicht implizit aus dem Kontext
  gelesen.
- **Natives `<details>`/`<summary>` statt eigenem JS-Toggle** für den
  Klapp-Block – braucht keinen zusätzlichen Code, ist von Haus aus
  zugänglich, und der native Zustand (offen/zu) kollidiert nicht mit dem
  bestehenden Pointer-Events-Drag&Drop (das weiterhin unverändert auf
  den `.mahlzeit-slot`-Elementen arbeitet, unabhängig davon, ob sie
  gerade sichtbar sind).
- **Rein CSS-Variablen für die Zusammenfassungs-Zeile** (`var(--text-2)`,
  `var(--surface)`, `var(--shadow)`) statt hartcodierter Farben – der
  Wunsch verlangte ausdrücklich Lesbarkeit in Dark- und Hell-Modus, und
  alle bestehenden Farb-Variablen sind bereits themefest.
- **Grammatik-Detail**: Singular/Plural in der Zusammenfassung
  unterschieden ("1 vergangener Tag" vs. "N vergangene Tage") – beim
  ersten Testlauf (mit nur einem vergangenen Tag, da heute Dienstag ist)
  wäre sonst "1 vergangene Tag" grammatisch falsch gewesen. Vor dem
  eigentlichen Test bemerkt und noch vor der Auslieferung an echte
  Nutzer korrigiert (daher direkt v27 statt v26 – v26 wurde gebaut, aber
  nie an einen echten Nutzer ausgeliefert bzw. getestet, `deploy/`-Regel
  "nie überschreiben" also nicht verletzt, stattdessen einfach die
  nächste Nummer verwendet).

### Testergebnisse (Playwright, Wegwerf-Testnutzer, danach restlos entfernt)

- Überschriften „Aktuelle Woche" / „Nächste Woche" vorhanden, in dieser
  Reihenfolge: ✅
- Block „1 vergangener Tag" (heute ist Dienstag, genau 1 vergangener
  Tag in der aktuellen Woche) vorhanden, standardmäßig zugeklappt: ✅
- Vergangener Tag vor dem Aufklappen nicht sichtbar, nach Antippen der
  Zusammenfassung sichtbar und weiterhin grau (`.vergangen`-Klasse): ✅
- Weiterhin exakt 14 Tageskarten insgesamt (nichts verloren gegangen
  durch die Aufteilung in drei Listen): ✅
- Visuell per Screenshot geprüft: klare Lücke vor „Nächste Woche",
  heutiger Tag weiterhin mit Profilfarbe umrandet.

### Auslieferungspaket

`deploy/portal-v26.tar.gz` – gebaut, aber durch den Grammatik-Fix vor
dem ersten Test verworfen (kein echter Nutzer hat diesen Stand gesehen).
`deploy/portal-v27.tar.gz` – tatsächlich ausgeliefert, nur `portal` neu
gebaut/gestartet.

---

## 2026-07-28 (Nacht-Session, automatisch) – Wunsch #39: Todo Rollen-/Alle-Zuweisung (portal-v28)

Letzter offener Wunsch der Nacht-Session, zugleich der größte:
„Neue Aufgaben in der Aufgabenliste sei nicht nur direkt für eine
Person erstellt werden können, sondern auch für eine oder mehrere
Rollen, oder für alle. Wird eine Aufgabe nicht direkt für eine Person
erstellt, dann landet sie nicht unter offen, sondern im Backlog."

### Design-Entscheidungen (Annahmen, da autonom ohne Rückfrage getroffen)

- **Bestehendes „Für mich"/Leerwert-Verhalten bewusst NICHT angetastet.**
  Der Wunsch sagt „nicht direkt für eine Person erstellt" landet im
  Backlog – die bisherige Leerauswahl ("Für mich", `zugewiesen_an` NULL)
  wurde vor dieser Nacht schon als Personen-Zuweisung behandelt (nur
  Ersteller/Eltern dürfen sie abschließen, sie landete in Offen). Diese
  Interpretation beibehalten und NICHT rückwirkend zu "keine Person" =
  Backlog umgedeutet, um bestehendes Verhalten nicht zu brechen – neu
  ist ausschließlich die zusätzliche Möglichkeit, explizit Rolle(n) oder
  "Alle" als Ziel zu wählen. Nur dieser neue Zweig landet im Backlog.
- **Neue Spalte `todos.zugewiesen_rollen`** (TEXT, kommagetrennt, z. B.
  "eltern,kind"; Sentinel-Wert `"alle"` für "alle Rollen") statt einer
  neuen Zwischentabelle – Rollen sind eine feste, kleine Menge
  (eltern/kind/gast), eine N:M-Tabelle wäre hier Überengineering.
  `zugewiesen_an` bleibt NULL, wenn eine Rolle/Alle gewählt wird – die
  beiden Zuweisungsarten schließen sich gegenseitig aus.
- **Sichtbarkeit für Rollen-Zuweisungen wird in Python nachgefiltert**,
  nicht rein in SQL: eine kommagetrennte Spalte lässt sich nicht sauber
  mit einem einzelnen `LIKE` gegen alle Rollen-Kombinationen matchen,
  ohne fragile String-Klimmzüge. Die Kind/Gast-Sichtbarkeitsabfrage in
  `_visible_todos()` lädt deshalb zusätzlich alle Rollen-/Alle-Zeilen,
  filtert sie per `_rolle_passt()` in Python und mischt sie in die
  Ergebnisliste, mit zwei stabilen Sortierungen (erst erstellt absteigend,
  dann erledigt aufsteigend), um `ORDER BY erledigt ASC, erstellt DESC`
  nachzubilden.
- **`_darf_erledigen()` erweitert**: Kind/Gast dürfen den Status jetzt
  auch ändern, wenn `zugewiesen_an` NULL ist und ihre eigene Rolle zur
  `zugewiesen_rollen`-Spalte passt (oder diese "alle" ist) – sonst hätte
  die neue Zuweisungsart für die Zielgruppe gar nichts gebracht (sie
  hätten die Aufgabe nur sehen, aber nie abschließen können).
- **UI**: Radio-Auswahl Person/Rolle(n)/Alle über dem bestehenden
  Zuweisungs-Bereich; bei "Person" bleibt exakt die alte Auswahlbox
  (inkl. "Für mich"), bei "Rolle(n)" erscheinen Checkboxen für
  Eltern/Kind/Gast, bei "Alle" keine weitere Eingabe nötig.

### Testergebnisse (Playwright, 3 Wegwerf-Testnutzer mit echten Rollen eltern/kind/gast, danach restlos entfernt)

- Regressionstest: Aufgabe mit Ziel "Person" + Leerauswahl ("Für mich")
  landet weiterhin in "Offen", nicht in Backlog – Altverhalten
  unverändert: ✅
- Ziel "Rolle(n): Kind" → landet beim Ersteller in Backlog, ist für den
  Kind-Testnutzer sichtbar, für den Gast-Testnutzer NICHT sichtbar: ✅
- Kind-Testnutzer darf den Status ändern (Button nicht deaktiviert),
  nach Klick auf "Offen" korrekt aktualisiert: ✅
- Ziel "Alle" → landet in Backlog, ist auch für den Gast-Testnutzer
  sichtbar und ihm erlaubt, den Status zu ändern (Button aktiv): ✅
- Ungültige Todo-ID beim Status-POST ergibt weiterhin sauber 404, kein
  500er: ✅
- Bestehende echte Familien-Todos (Häkeln → Friederike, Speiseplan →
  Simone, Badarmatur bestellen) vor und nach dem Test unverändert
  (`zugewiesen_rollen` NULL, Status/Zuweisung identisch).

### Auslieferungspaket

`deploy/portal-v28.tar.gz` – nur `portal` neu gebaut/gestartet.

---

## 2026-07-28 (Nacht-Session, automatisch) – Abschluss

Alle zu Sitzungsbeginn offenen Wünsche (#38, #39, #40, #41, #42)
umgesetzt, ausgeliefert, getestet und dokumentiert; Backlog danach
leer. Kein Wunsch musste offen gelassen werden. Kein `git commit`
durchgeführt (Andi sieht sich den Code selbst an, wenn er wach ist).

---

## 2026-07-28 – Wunsch #43: Todo-Bearbeiten mit allen Feldern (portal-v29)

Direkt nach dem Aufwachen kam ein neuer Wunsch: „wenn man einen Eintrag
mit dem Stift editiert, dann sollen alle Felder des Eintrags editierbar
sein, mit der gleichen UX wie auch beim Erstellen des neuen Eintrags."
Bisher konnte das ✏️-Panel nur den Text ändern – Ziel (Person/Rolle(n)/
Alle, seit Wunsch #39) und Privat-Flag waren nach dem Anlegen fix.

### Design-Entscheidungen

- **Gemeinsames Macro `ziel_auswahl()`** für Neu-Anlegen UND
  Bearbeiten-Panel, statt die Ziel-Typ-Auswahl zweimal zu pflegen –
  genau das Duplizierungs-Risiko, das in dieser Session schon mehrfach
  vermieden wurde. Nimmt optionale Vorbelegungs-Parameter
  (`vorbelegt_zugewiesen_an`, `vorbelegte_rollen`, `vorbelegt_privat`);
  ohne sie (Neu-Formular) ist alles auf dem alten Standard (Person/
  Für mich, nichts angehakt).
- **JS über `closest('.ziel-wrap')` statt IDs**: da jetzt dieselbe
  Radio-Gruppen-Markup (`name="ziel_typ"`) sowohl im Neu-Formular als
  auch in JEDEM Bearbeiten-Panel gleichzeitig auf der Seite existiert,
  hätten IDs kollidiert. Radiogruppen sind ohnehin pro `<form>`
  unabhängig (jedes Todo hat sein eigenes `<form>`), daher keine
  eindeutigen `name`-Suffixe nötig – nur das JS musste umgestellt
  werden, um im Kontext des jeweils angeklickten Radios zu bleiben.
- **Status bleibt beim Bearbeiten unangetastet**, auch wenn das Ziel von
  "Person" auf "Rolle(n)"/"Alle" wechselt oder umgekehrt. Die
  Backlog-Regel aus Wunsch #39 gilt ausdrücklich nur beim *Anlegen*
  ("nicht direkt für eine Person **erstellt**") – ein nachträglicher
  Zielwechsel per Edit soll eine bereits in Arbeit befindliche Aufgabe
  nicht überraschend zurück in den Backlog werfen. Bewusste Annahme,
  da ohne Rückfrage getroffen.
- **Keine Push-Benachrichtigung beim Bearbeiten**, auch wenn sich die
  Personen-Zuweisung ändert – nur beim Neu-Anlegen (wie bisher). Sonst
  würde jede Text- oder Privat-Änderung potenziell erneut benachrichtigen,
  was nicht verlangt war.
- Berechtigung fürs gesamte Panel bleibt `_darf_erledigen()` (wie schon
  für den reinen Text-Edit) – wer den Text ändern durfte, darf jetzt
  auch das Ziel ändern. Das ist eine Erweiterung der bisherigen
  Möglichkeiten für Kinder bei eigenen/passend zugewiesenen Aufgaben,
  aber genau das verlangt der Wunsch ("gleiche UX wie beim Erstellen").

### Testergebnisse (Playwright, Wegwerf-Admin-Testnutzer, danach restlos entfernt)

- Bearbeiten-Panel zeigt beim Öffnen korrekt den aktuellen Zustand
  vorbelegt (Ziel "Person" angehakt, Privat nicht angehakt): ✅
- Text geändert, Ziel auf "Rolle(n): Kind" umgestellt, Privat aktiviert,
  gespeichert → neuer Text sichtbar, Chip "→ Kind", 🔒-Icon: ✅
- Panel erneut geöffnet: zeigt jetzt korrekt "Rolle(n)" + "Kind" +
  Privat vorbelegt, Rollen-Checkboxen sichtbar, Personen-Auswahl
  versteckt: ✅
- Aufräumen (Löschen) erfolgreich, echte Familien-Todos vorher/nachher
  unverändert.

### Auslieferungspaket

`deploy/portal-v29.tar.gz` – nur `portal` neu gebaut/gestartet.

---

## 2026-07-28 – Wunsch #44: Geholfen-Heatmap Eltern vor Kindern (portal-v30)

Kleiner, gezielter Wunsch: in der 10-Tage-Heatmap der Geholfen-App
sollen erst die Eltern, dann die Kinder aufgelistet werden (bisher rein
alphabetisch über alle Rollen hinweg gemischt).

### Design-Entscheidung

- Reine SQL-Änderung in `06_geholfen.py`: `ORDER BY CASE rolle WHEN
  'eltern' THEN 0 ELSE 1 END, name COLLATE NOCASE` statt nur `ORDER BY
  name`. Innerhalb der beiden Gruppen bleibt es alphabetisch, wie zuvor
  bei der Gesamtliste. Keine Änderung an `geholfen.html` nötig, da das
  Template die übergebene Reihenfolge einfach durchschleift.

### Testergebnisse

- Direkte SQL-Abfrage gegen die Live-DB bestätigt: Andi, Simone (Eltern,
  alphabetisch), dann Friederike, Johannes (Kinder, alphabetisch): ✅
- Zusätzlich mit Wegwerf-Testnutzer die tatsächlich gerenderte Seite
  geprüft (Playwright) – exakt dieselbe Reihenfolge im HTML: ✅
- Testnutzer restlos entfernt.

### Auslieferungspaket

`deploy/portal-v30.tar.gz` – nur `portal` neu gebaut/gestartet.

---

## 2026-07-28 – Wunsch #45: Essensplan Speichern-Button UX (portal-v32)

„Beim Eintragen im Essensplan ist der Speichern-Button sehr nah am
Textfeld und kann daher manchmal schlecht erreicht werden."

### Root Cause statt Pflaster

Der erste Versuch (`margin-top:6px` auf `.tag-save`, ausgeliefert als
**portal-v31**) brachte beim Test nur 6px zusätzlichen Abstand statt
der erwarteten ~14px. Ursache: `.tag-edit-panel` ist zwar als
Flex-Column mit `gap:8px` deklariert, hat aber nur EIN direktes Kind –
das `<form>` – nicht die einzelnen Select/Input/Button-Elemente
(die stecken alle im Formular). Der `gap` griff also nie zwischen den
sichtbaren Feldern; die bisherige optische Stapelung kam nur daher,
dass `.tag-select`/`.tag-input` per `width:100%` einen Zeilenumbruch vor
dem Button erzwungen haben – ohne definierten Abstand. Genau das war
vermutlich die eigentliche Ursache der "sehr nah"-Beschwerde.

Statt eines zweiten Pflasters oben drauf wurde die Struktur korrigiert:
`.tag-edit-panel form { display:flex; flex-direction:column; gap:10px }`
sorgt jetzt für einen echten, funktionierenden Abstand zwischen Select,
Textfeld und Button. Der Button selbst bekam zusätzlich `margin-top:6px`
obendrauf (macht in Summe 16px), volle Breite (`width:100%` statt
`align-self:flex-start`) und mehr Innenabstand (`padding:12px 14px`
statt `8px 14px`) – ein größerer, leichter zu treffender Tap-Target,
nicht nur mehr Abstand.

### Testergebnisse (Playwright, Wegwerf-Testnutzer, danach restlos entfernt)

- v31 (verworfen): gemessener Abstand nur 6.0px – nicht ausreichend,
  Ursache wie oben analysiert.
- v32: gemessener Abstand 16.0px, Button-Höhe 40px (über der
  40px-Mindestgröße für Tap-Targets), Button-Breite ~326px (nahezu
  volle Panel-Breite): ✅
- Speichern-Funktion weiterhin unverändert korrekt: ✅
- Echte Essensplan-Einträge der Familie vor/nach dem Test unverändert
  (u. a. neue reale Einträge wie „Essen bei Chris&Julian" beobachtet,
  nicht angetastet).

### Auslieferungspaket

`deploy/portal-v31.tar.gz` – ausgeliefert, aber unzureichend (nur 6px
Abstand statt der beabsichtigten Verbesserung), direkt durch v32 ersetzt.
`deploy/portal-v32.tar.gz` – tatsächlicher, getesteter Fix.

---

## 2026-07-28 – Wunsch #46: Kategorien-Drag-Handle vergrößert (portal-v34)

„Das Sortieren von Kategorieeinträgen (Einkaufsliste) funktioniert
nicht gut. Die Einträge sind schlecht zu 'greifen'." Bezog sich fast
sicher auf die frisch (letzte Nacht, Wunsch #38) gebaute
Kategorien-Sortierung – Andi hat sie ausprobiert und den Handle als zu
klein empfunden.

### Design-Entscheidung

- `.kat-drag-handle` hatte nur `font-size:15px` ohne jedes Padding –
  ein winziger Tap-Target, der mit einem präzisen Maus-Klick in
  automatisierten Tests klaglos funktioniert, mit einem echten Finger
  auf einem Handy-Bildschirm aber knapp unter jeder Griffigkeits-
  Empfehlung liegt. Font-Size auf 22px erhöht, dazu `padding:10px 6px`
  mit kompensierendem `margin:-10px -6px` – vergrößert die tatsächliche
  Tastfläche (jetzt ~29×42px gemessen), ohne das Flex-Layout der Zeile
  (Handle/Name/Bearbeiten/Aktivieren-Button) zu verschieben. Vertikal
  großzügiger als horizontal, damit die vergrößerte Fläche nicht in den
  Namenstext oder die Buttons daneben hineinragt.

### Testergebnisse (Playwright, Wegwerf-Admin-Testnutzer, danach restlos entfernt)

- Handle-Maße gemessen: 28.6×42.0px (vorher rechnerisch ~15×15px): ✅
- Drag-Funktion weiterhin unverändert korrekt (zwei Kategorien
  vertauscht und zurückgetauscht, exakt ursprüngliche Reihenfolge
  wiederhergestellt): ✅

### Auslieferungspaket

`deploy/portal-v33.tar.gz` – zusammen mit Wunsch #47 gebaut, aber durch
einen beim Testen gefundenen Regressions-Bug in #47 (siehe unten) direkt
durch v34 ersetzt.
`deploy/portal-v34.tar.gz` – tatsächlich ausgeliefert.

---

## 2026-07-28 – Wunsch #47: Wunsch merkt sich Ansicht/Screen (portal-v34)

„Wenn ein Verbesserungsvorschlag gemacht wird, merke dir in welcher
Ansicht er eingegeben wurde. Falls nichts anderes angegeben ist, dann
bezieht sich der Vorschlag auf den aktuellen Screen/die aktuelle App."

### Design-Entscheidungen (Annahmen, da autonom ohne Rückfrage getroffen)

- **Interpretation als zwei Teile**: (1) technisch speichern, aus
  welcher Ansicht ein Wunsch kam – bisher wurde nur der App-Slug
  gespeichert (z. B. "einkauf"), nicht aber, ob er von der Haupt-Liste
  oder einer Unterseite wie "Kategorien verwalten" kam. (2) die
  Default-Interpretationsregel selbst ("bezieht sich auf den aktuellen
  Screen, falls nichts anderes angegeben") ergibt sich automatisch,
  sobald (1) sichtbar gemacht wird – kein separater Mechanismus nötig,
  das ist Lese-Hinweis für Andi/mich beim späteren Abarbeiten von
  Wünschen, keine App-Funktion.
- **`window.location.pathname` statt manueller Pro-Template-Annotation**:
  Erste Überlegung war ein zusätzliches `{% set ansicht = "..." %}` in
  jedem Unterseiten-Template (nach demselben Muster wie `app_slug`) –
  hätte aber bedeutet, jede bestehende und künftige Unterseite manuell
  zu pflegen. Stattdessen sendet das JS im Wunsch-Overlay den kompletten
  Pfad mit, der Server verdichtet ihn per Regex zu `"app_slug/unterseite"`
  (z. B. „einkauf/kategorien"). Automatisch für jede aktuelle und
  künftige Unterseite korrekt, ohne dass ein Template angefasst werden
  muss.
- **Token wird aus dem gespeicherten Pfad entfernt**, bevor er in die
  für alle Admins sichtbare Werkstatt-Liste geschrieben wird
  (`/a/einkauf/<token>/kategorien` → `einkauf/kategorien`) – Tokens
  sind in diesem Projekt durchgängig wie Passwörter behandelt (siehe
  `glogging_redact.py`, das sie sogar aus Server-Logs entfernt); sie
  hätten in einer für alle Admins einsehbaren Tabelle nichts verloren.
- **Fallback auf `app_slug`, wenn der Pfad nicht geparst werden kann**
  (z. B. von der Startseite `/p/<token>` aus, die nicht dem
  `/a/<slug>/<token>/...`-Muster folgt) – kein Funktionsverlust
  gegenüber vorher.
- **Regressions-Falle beim ersten Versuch (v33) gefunden und in v34
  behoben, bevor sie live ging**: Das Werkstatt-Template zeigte den
  neuen `ansicht`-Chip OHNE Fallback auf das bestehende `app_slug` an –
  alle 47 bereits bestehenden Wünsche (die naturgemäß kein `ansicht`
  haben, weil sie vor dieser Änderung entstanden) hätten dadurch beim
  nächsten Öffnen der Werkstatt-Seite plötzlich ihren App-Chip verloren.
  Beim eigenen Test bemerkt (Regressionscheck über die ersten 5
  bestehenden Wünsche), noch vor der Auslieferung an Andi behoben:
  Template zeigt jetzt `w.ansicht or w.app_slug`.

### Technische Umsetzung

- Neue Spalte `wuensche.ansicht` (TEXT, nullable).
- `02_werkstatt.py`: `_ansicht_aus_pfad()` – Regex
  `^/a/([a-z0-9_-]+)/[^/]+(/.*)?$`, extrahiert App-Slug + Unterseite,
  verwirft den Token-Teil.
- `base.html`: Wunsch-POST sendet zusätzlich `pfad: window.location.pathname`.
- `werkstatt_app.html`: Chip zeigt `ansicht` mit Fallback auf `app_slug`.
- `manage.py` (`backlog`, `listwuensche`): zeigen ebenfalls `ansicht`
  statt nur `app_slug`, damit ich selbst beim Lesen des Backlogs sofort
  die genaue Herkunft sehe.

### Testergebnisse (Playwright, Wegwerf-Admin-Testnutzer, danach restlos entfernt)

- Wunsch von der Einkauf-Hauptseite → Chip „einkauf": ✅
- Wunsch von der Kategorien-Unterseite → Chip „einkauf/kategorien": ✅
- Regressionscheck: die ersten 5 (alten, `ansicht=NULL`) Wünsche zeigen
  weiterhin ihren App-Chip (Fallback funktioniert): ✅
- Aufräumen erfolgreich, keine echten Wünsche/Nutzer betroffen.

### Auslieferungspaket

`deploy/portal-v33.tar.gz` – verworfen (Regressions-Bug, siehe oben).
`deploy/portal-v34.tar.gz` – tatsächlich ausgeliefert und getestet.

---

## 2026-07-28 – Wunsch #48: Rezepte-Eingabemaske als eigene Unterseite (portal-v35)

„Die Eingabemaske soll nur erscheinen, wenn ein neues Rezept
eingetragen werden soll. Die weitere Unterseite soll über einen neuen
Button erreichbar sein." Bisher stand das komplette Neu-Anlegen-
Formular (Name/Zutaten/Zubereitung) dauerhaft ganz oben auf der
Rezepte-Übersicht, unabhängig davon, ob man gerade etwas anlegen wollte.

### Design-Entscheidung

- Wörtlich genommen: „weitere Unterseite … über einen neuen Button" –
  keine Toggle-Lösung auf derselben Seite, sondern eine echte eigene
  Route `GET/POST /a/rezepte/<token>/neu` (GET rendert das Formular auf
  `rezept_neu.html`, POST verarbeitet wie bisher), erreichbar über einen
  neuen `+ Neues Rezept`-Button auf der Übersicht. Gleiches Muster wie
  `einkauf_kategorien.html`/`einkauf_laeden.html`/`admin_user_form.html`
  (Verwaltungsformular als eigene Unterseite mit „← Zurück", nicht
  inline auf der Listenseite).
- Bei fehlendem Namen springt die Route jetzt zurück zum Formular selbst
  (`rezepte_app.neu`) statt zur Übersicht – vorher wäre man bei einem
  Validierungsfehler ungewollt aus dem gerade begonnenen Formular
  herausgeflogen.
- Leerer-Zustand-Hinweistext ("Trag oben dein erstes Rezept ein")
  angepasst, da "oben" sich vorher auf das jetzt entfernte Inline-
  Formular bezog.

### Testergebnisse (Playwright, Wegwerf-Testnutzer, danach restlos entfernt)

- Übersicht zeigt kein eingebettetes Formular mehr, nur den Button: ✅
- Klick auf „+ Neues Rezept" führt auf die neue Unterseite mit
  Zurück-Link und dem vollständigen Formular: ✅
- Speichern funktioniert unverändert (Weiterleitung zur Detailseite,
  Rezept erscheint korrekt in der Liste): ✅
- Echtes Bestandsrezept „Rührkuchen" vor/nach dem Test unverändert.

### Auslieferungspaket

`deploy/portal-v35.tar.gz` – nur `portal` neu gebaut/gestartet.

---

## 2026-07-28 – Wunsch #49: Rezepte-Suche über Titel + Zutaten (portal-v36)

„Die Liste der Rezepte soll über eine Suche filterbar sein. Ab 3
Buchstaben im Suchfeld soll dynamisch gefiltert werden. Der Suchtext
soll im Rezepttitel als auch in den Zutaten suchen."

### Design-Entscheidung

- **Rein clientseitig gefiltert**, kein AJAX-Roundtrip pro Tastenanschlag
  – bei der überschaubaren Rezeptmenge einer Familie unnötig, und "ab 3
  Buchstaben dynamisch" liest sich klar als sofortige Reaktion beim
  Tippen, nicht als Server-Suche mit Debounce.
- Damit die Zutaten überhaupt clientseitig durchsuchbar sind, liefert
  `index()` jetzt zusätzlich `GROUP_CONCAT` der Zutatennamen je Rezept
  mit aus; das Template schreibt Name+Zutaten kleingeschrieben in ein
  `data-suche`-Attribut auf jede `.rezept-card`, das JS vergleicht nur
  noch gegen dieses Attribut – kein erneutes DOM-Parsen nötig.
- Unter 3 Zeichen wird nicht gefiltert (alle Karten bleiben sichtbar,
  exakt wie im Wunsch beschrieben), "Keine Rezepte gefunden"-Hinweis
  erscheint nur, wenn nach einer Filterung tatsächlich 0 Karten übrig
  bleiben.

### Testergebnisse (Playwright, Wegwerf-Testnutzer, danach restlos entfernt)

- Zwei Testrezepte angelegt (eins mit eindeutigem Titel, eins mit
  eindeutiger Zutat).
- Unter 3 Zeichen: keine Filterung, beide weiterhin sichtbar: ✅
- Suche nach Titel-Fragment: nur das passende Rezept sichtbar: ✅
- Suche nach Zutat-Fragment: nur das Rezept mit dieser Zutat sichtbar,
  obwohl der Suchtext nicht im Titel vorkommt: ✅
- Suche ohne Treffer: „Keine Rezepte gefunden"-Hinweis erscheint: ✅
- Suchfeld geleert: alle Rezepte wieder sichtbar: ✅
- Echte Bestandsrezepte („Rührkuchen", „Rührei") vor/nach dem Test
  unverändert.

### Auslieferungspaket

`deploy/portal-v36.tar.gz` – nur `portal` neu gebaut/gestartet.

---

## 2026-07-28 – Wunsch #50: Admin "Neues Mitglied"-Button (portal-v37)

„Der Button 'Neues Mitglied' ist zu nah an der Headline. Ich wünschte,
das wäre etwas hübscher."

### Design-Entscheidung

- `.nav-extra` (base.html, ausschließlich von admin.html über
  `header_extra` genutzt – Grep bestätigt keine anderen Verwender, also
  gefahrlos direkt anpassbar) hatte nur `padding-top:6px` zur Headline.
  Auf 14px erhöht.
- Button selbst dezent aufgewertet, nicht neu designt: Rand
  (`border:1.5px solid rgba(255,255,255,.4)`) für Kontur gegen den
  farbigen Header, leichter Schatten (`box-shadow`) für etwas Tiefe,
  etwas mehr horizontales Padding. Bewusst zurückhaltend – "etwas
  hübscher" ist subjektiv, keine Rechtfertigung für einen großen
  Redesign-Umbau einer einzelnen Seite.

### Testergebnisse (Playwright, Wegwerf-Admin-Testnutzer, danach restlos entfernt)

- Gemessener Abstand Headline→Button: 14.5px (vorher ~6px): ✅
- Button-Link weiterhin korrekt auf `/user/neu`: ✅
- Visuell per Screenshot geprüft: klar erkennbare Kontur, echte
  Familienmitglieder-Karten unverändert.

### Auslieferungspaket

`deploy/portal-v37.tar.gz` – nur `portal` neu gebaut/gestartet.

---

## 2026-07-28 – Neues Feature: Rezept-Import per URL mit KI-Extraktion (portal-v39)

Andi wollte ein größeres neues Feature, das erst ausführlich in einem
Architektur-Gespräch geklärt wurde, bevor Code entstand: von einer
Rezept-Webseite die URL kopieren und in der Rezepte-App importieren
lassen – die Seite wird gelesen, das Rezept erkannt und automatisch
angelegt.

### Architektur-Entscheidungen (im Gespräch mit Andi geklärt, nicht selbst entschieden)

- **KI-Anbieter: OpenRouter**, nach Abwägung gegen direkte Anbieter
  (Anthropic/OpenAI/Google, alle USA), echte EU-Anbieter (Mistral AI aus
  Frankreich, Aleph Alpha aus Heidelberg, IONOS AI Model Hub) und
  Azure OpenAI mit EU-Region. OpenRouter selbst ist **kein** deutscher/
  europäischer Anbieter (US-Firma, San Francisco) – Andi hat sich trotz
  dieses Wissens bewusst dafür entschieden, mit der Option, bei Bedarf
  (z. B. wenn Spracherfassung als Feature dazukommt) auf einen anderen
  Anbieter zu wechseln, ohne die Architektur anzufassen.
- **Ein gemeinsamer Server-Key statt echter Unterkeys pro Nutzer**: Andis
  eigentliches Ziel war Kontingent-Isolation ("ein Kind lädt viele
  Rezepte hoch, soll nicht das Limit der anderen aufbrauchen") plus
  Sichtbarkeit. Echte OpenRouter-Unterkeys pro Nutzer (via deren
  Provisioning-API) hätten das hart auf Plattformebene erzwungen, aber
  bedeutet, dass 4 echte Billing-Secrets in der SQLite-DB liegen müssten
  – die stündlich gesnapshottet und täglich aufs NAS gesichert wird.
  Stattdessen: ein Key in `.env`, Kontingent-Durchsetzung in eigener
  App-Logik (siehe unten) – kein zusätzliches Secret-Management, das
  Backup-Risiko bleibt aus.
- **Token-basiertes statt Feature-spezifisches Kontingent**: Andis Idee,
  nicht "10 Importe/Monat" zu zählen, sondern die tatsächlich
  verbrauchten Tokens – damit künftige KI-Features (welche auch immer
  kommen) automatisch gegen dasselbe geteilte Monats-Budget zählen,
  ohne dass für jedes Feature ein eigenes Limit definiert werden muss.
- **Vorschau statt Blind-Speichern**: sowohl JSON-LD- als auch
  KI-Extraktion können daneben liegen – das Ergebnis landet immer nur
  vorausgefüllt im bestehenden Neu-Formular, gespeichert wird erst nach
  Bestätigen/Bearbeiten durch den Nutzer.

### Design/Implementierung

- **Neue Tabelle `ki_nutzung`** (user_id, feature, tokens, erstellt) +
  `users.ki_token_limit` (Default 100000, im Admin-Formular editierbar).
- **Genereller Helfer `ki_anfrage()` in `00_kern.py`** (gleiches Muster
  wie `push_send()`): prüft vor dem Aufruf die Tokensumme des Nutzers
  seit Monatsbeginn gegen `ki_token_limit` (wirft `KiLimitError`, wenn
  aufgebraucht), ruft OpenRouter auf (`KI_MODELL = "anthropic/claude-haiku-4.5"`,
  günstig/schnell wie besprochen), schreibt den tatsächlichen
  Verbrauch aus der Antwort in `ki_nutzung`. Jedes künftige KI-Feature
  ruft dieselbe Funktion mit eigenem `feature`-Namen auf.
- **`OPENROUTER_API_KEY` in `.env`** (nicht in Git, wie VAPID-Keys),
  geladen in `app.py` nach demselben Muster.
- **Zweistufige Extraktion in `11_rezepte.py`**:
  1. JSON-LD (`schema.org/Recipe`) im HTML suchen – kostenlos,
     zuverlässig, kein KI-Aufruf nötig. Behandelt `@graph`-Wrapper,
     `recipeInstructions` als String/Liste/verschachtelte
     `HowToSection` mit `itemListElement` (siehe Fehlerkorrektur unten).
  2. Nur wenn kein JSON-LD gefunden wird: sichtbarer Seitentext (simple
     Extraktion über `html.parser.HTMLParser`, Script/Style/Nav
     ausgeblendet, auf 6000 Zeichen gekappt) geht an `ki_anfrage()` mit
     der Bitte um ein JSON-Objekt {name, zutaten, anleitung}.
- **SSRF-Schutz** (`_ist_oeffentliche_url()`): nur http/https, Zielhost
  wird aufgelöst und alle IPs gegen private/loopback/link-local/
  reserved/multicast geprüft, bevor überhaupt ein Abruf versucht wird
  – verhindert, dass die URL-Eingabe zum Zugriff auf interne Adressen
  (z. B. 10.0.0.x) missbraucht werden kann.
- **Neue Unterseite** `/a/rezepte/<token>/importieren` (URL einfügen),
  Ergebnis landet im bestehenden `rezept_neu.html` mit Hinweis-Banner
  "aus Webseite vorausgefüllt, bitte prüfen" – kein neues Formular für
  den Speicher-Schritt, volle Wiederverwendung.
- **Kein Python-Paket zusätzlich installiert** – Fetch über
  `urllib.request`, JSON-LD-Suche über Regex, Textextraktion über das
  eingebaute `html.parser` – passt zur bisherigen Linie des Projekts
  (keine schweren Abhängigkeiten für Dinge, die die Standardbibliothek
  bereits kann).

### Fehler gefunden und behoben, bevor Andi es gesehen hat

- **`recipeInstructions`-Verschachtelung**: chefkoch.de (Testseite)
  verschachtelt die Zubereitungsschritte in einer `HowToSection` mit
  `itemListElement` statt einer flachen Liste von `HowToStep`. Erste
  Version fiel in diesem Fall auf den Abschnittsnamen ("Zubereitung",
  11 Zeichen) zurück statt die eigentlichen Schritte zu lesen – beim
  Live-Test gegen eine echte Rezeptseite aufgefallen (Anleitungslänge
  von nur 11 Zeichen war der Hinweis), durch echte Rekursion über
  `itemListElement` behoben. Ausgeliefert als v39, v38 hat diesen Bug
  noch enthalten und wurde nie von einem Nutzer gesehen.

### Testergebnisse

- **Extraktionslogik isoliert getestet** (synthetisches JSON-LD):
  Name/Zutaten/mehrstufige Anleitung korrekt zusammengeführt: ✅
- **SSRF-Schutz isoliert getestet**: localhost, interne IP (10.0.0.100),
  `ftp://`-Schema korrekt abgelehnt; echte öffentliche Domain korrekt
  akzeptiert: ✅
- **Live-Test gegen eine echte chefkoch.de-Rezeptseite** (JSON-LD-Pfad,
  kein KI-Aufruf nötig): Name, 13 Zutaten, vollständige mehrschrittige
  Anleitung (1215 Zeichen) korrekt erkannt, im Formular vorausgefüllt,
  erfolgreich gespeichert, auf der Detailseite sichtbar: ✅
- **KI-Kontingent-Sperre getestet** (Testnutzer-Limit künstlich auf 0
  gesetzt, Import einer Seite ohne Rezept-Markup erzwingt den
  KI-Fallback-Pfad): korrekte freundliche Fehlermeldung statt Absturz,
  kein Tokenverbrauch geloggt (Sperre griff vor dem API-Call): ✅
- **SSRF/Fetch-Fehler über das echte Formular**: interne URL und
  nicht existierende Domain liefern beide dieselbe Meldung "Diese URL
  kann nicht abgerufen werden" statt eines 500ers – bewusst nicht
  unterschieden, damit ein Angreifer nicht erfährt, ob eine URL aus
  Sicherheits- oder aus Erreichbarkeitsgründen abgelehnt wurde: ✅
- **Admin-UI fürs KI-Token-Limit**: neuer Nutzer zeigt Default 100000,
  abweichender Wert (25000) wird korrekt gespeichert und beim erneuten
  Öffnen angezeigt: ✅
- Echte KI-Extraktion (OpenRouter-Aufruf) konnte noch nicht live
  getestet werden – das OpenRouter-Konto hat noch kein Guthaben. Der
  JSON-LD-Pfad (deckt vermutlich den Großteil gängiger Rezeptseiten ab)
  ist vollständig getestet; der KI-Fallback-Pfad ist bis auf den
  eigentlichen API-Aufruf getestet (Limit-Prüfung, Fehlerbehandlung,
  JSON-Parsing der erwarteten Antwortform).
- Alle Testnutzer und Testdaten restlos entfernt, echte Rezepte
  ("Rührkuchen", "Rührei") unangetastet.

### Auslieferungspaket

`deploy/portal-v38.tar.gz` – enthielt den `HowToSection`-Bug, nie von
einem Nutzer gesehen.
`deploy/portal-v39.tar.gz` – tatsächlich ausgeliefert und getestet.

---

## 2026-07-28 – Nachtrag: KI-Fallback-Pfad live getestet (OpenRouter-Guthaben aufgeladen)

Andi hat das OpenRouter-Konto aufgeladen, danach den echten KI-Aufruf
nachgetestet (bei der ersten Auslieferung von portal-v39 war das mangels
Guthaben nur bis zur Kontingent-Prüfung möglich, nicht der eigentliche
API-Call).

### Testergebnisse

- **Direkter Aufruf von `_rezept_per_ki()`** mit echtem Fließtext
  (Kartoffelsalat-Rezept in Prosa, kein JSON-LD): Name, alle 9 Zutaten
  und die Zubereitung korrekt als JSON extrahiert; Verbrauch (511
  Tokens) korrekt in `ki_nutzung` protokolliert: ✅
- **Voller Browser-Durchlauf gegen eine echte, live erreichbare Seite
  ohne JSON-LD** (`de.wikibooks.org/wiki/Kochbuch/_Kartoffelsalat` –
  bewusst gewählt, weil Wikibooks anders als die meisten kommerziellen
  Rezeptseiten kein `schema.org/Recipe`-Markup einbettet): Route
  erkennt korrekt "kein JSON-LD", ruft die KI auf, zeigt das Ergebnis
  vorausgefüllt mit Hinweis-Banner im Formular; zweiter Verbrauchs-
  Eintrag (1641 Tokens) korrekt geloggt: ✅
- Damit sind jetzt beide Pfade (JSON-LD direkt UND KI-Fallback) einmal
  vollständig live gegen echte, unterschiedliche Webseiten verifiziert.
- Testnutzer und alle Testdaten (inkl. `ki_nutzung`-Einträge) restlos
  entfernt, echte Rezepte unangetastet.

Das Feature ist damit vollständig einsatzbereit, keine offenen Punkte mehr.

---

## 2026-07-28 – Rezepte: Portionen + Zubereitungsschritte einzeln speichern (portal-v41)

Andi fragte, ob es Sinn ergibt, die Rezeptdaten näher an JSON-LD zu
speichern, um möglichst wenig Information zu verlieren (Portionen,
getrennte Zubereitungsschritte). Wichtige Klarstellung vorab: bei den
Zutaten verliert unser Schema gegenüber JSON-LD nichts – `recipeIngredient`
ist im Standard selbst nur eine flache Liste von Strings wie „200g Mehl",
keine getrennte Mengenangabe/Zutat. Nur bei Portionen (`recipeYield`,
fehlte komplett) und Zubereitungsschritten (`recipeInstructions` ist im
Standard eine Liste einzelner `HowToStep`, wir haben sie zu einem
Textblock zusammengefasst) gab es echten Informationsverlust.

Andi wollte Portionen + Schritte sofort umgesetzt haben; eine dritte
Idee (Zutaten in Menge/Einheit/Name aufsplitten – geht über JSON-LD
hinaus, bräuchte Regex- oder KI-Parsing pro Zutat) als Wunsch #51 mit
niedriger Priorität in die Werkstatt eingetragen, nicht umgesetzt.

### Umsetzung

- `rezepte.portionen` (TEXT, nicht INTEGER – reale Werte sind oft
  „4-6 Portionen" oder „1 Blech", keine reine Zahl).
- Neue Tabelle `rezept_schritte` (id, rezept_id, text, position), analog
  zu `rezept_zutaten` – Zubereitung ist jetzt eine Liste einzelner
  Schritte statt eines Textblocks.
- JSON-LD-Extraktion: `_anleitung_zu_liste()` liefert jetzt eine Liste
  statt eines zusammengefügten Strings; `_portionen_aus_jsonld()` liest
  `recipeYield` (String/Zahl/Liste/`{"value":...}`-Objekt).
- KI-Fallback-Prompt liefert jetzt `{"name","portionen","zutaten",
  "schritte"}` statt `{"name","zutaten","anleitung"}`.
- Rezept-Detailseite zeigt Portionen im Untertitel und die Zubereitung
  als nummerierte Liste statt Fließtext.

### Schwerer Bug bei der Migration gefunden und live repariert

Die erste Version der Migration hat `rezepte` per RENAME+Neubau
umgestellt (dasselbe Muster, das beim Essensplan letzte Nacht
funktioniert hat) – das ist diesmal aber schiefgegangen: `rezepte` wird
von `rezept_zutaten`, `rezept_schritte` UND `essensplan_eintraege` per
Foreign Key referenziert. SQLite schreibt beim Umbenennen einer
referenzierten Tabelle automatisch die FK-Klauseln der referenzierenden
Tabellen auf den Zwischennamen um (`rezepte` → `rezepte_alt`) – nach dem
`DROP TABLE rezepte_alt` zeigten alle drei FKs dann ins Leere. Beim
ersten Test (neues Rezept mit Zutat anlegen) sofort als 500er
aufgefallen (`sqlite3.OperationalError: no such table: main.rezepte_alt`).

Sofort auf der Live-DB repariert: alle drei betroffenen Tabellen (die
selbst von NIEMANDEM per FK referenziert werden, ihr eigenes Umbenennen
also unbedenklich ist) einzeln per Rename+Neubau mit korrekter
FK-Klausel neu aufgebaut, Daten 1:1 über explizite Spaltenlisten
kopiert. Migrations-Code in `00_kern.py` danach korrigiert: `rezepte`
wird jetzt NICHT mehr umgebaut, nur per `ALTER TABLE ADD COLUMN
portionen` erweitert (unbedenklich, keine FK-Auswirkung); die alte
`anleitung`-Spalte bleibt als totes Altfeld liegen (SQLite kann Spalten
nicht gefahrlos entfernen, wenn andere Tabellen per FK darauf verweisen),
nur ihr Inhalt wird einmalig nach `rezept_schritte` übernommen.

**Lehre für künftige Migrationen:** Rename+Neubau einer Tabelle ist nur
sicher, wenn diese Tabelle selbst von KEINER anderen per Foreign Key
referenziert wird. Vor einem solchen Umbau immer prüfen (`grep
"REFERENCES <tabelle>"` über das Schema), welche Tabellen betroffen
wären.

### Testergebnisse (Playwright, Wegwerf-Testnutzer, danach restlos entfernt)

- Migration der beiden echten Bestandsrezepte („Rührkuchen" 3 Schritte,
  „Rührei" 5 Schritte) korrekt in `rezept_schritte` aufgeteilt, Zutaten
  unverändert, `PRAGMA foreign_key_check` leer: ✅ (nach der Reparatur)
- Detailseite eines echten migrierten Rezepts zeigt die Schritte korrekt
  nummeriert, kein Portionen-Untertitel (da nie erfasst): ✅
- Neues Rezept mit Portionen + mehreren Zutaten/Schritten anlegen,
  Speichern, Detailseite korrekt: ✅ (schlug vor der Reparatur mit 500
  fehl, danach erfolgreich)
- Import-Flow erneut gegen eine echte chefkoch.de-Seite: Portionen ("2")
  korrekt aus `recipeYield` gelesen, 13 Zutaten, 3 Zubereitungsschritte
  (aus der `HowToSection`-Verschachtelung korrekt aufgelöst), gespeichert,
  auf der Detailseite korrekt angezeigt: ✅
- Wunsch #51 (Zutaten strukturiert aufsplitten) mit niedriger Priorität
  in der Werkstatt angelegt, nicht umgesetzt.
- Alle Testdaten restlos entfernt, echte Rezepte (inkl. Migrationsergebnis)
  unangetastet.

### Auslieferungspaket

`deploy/portal-v40.tar.gz` – enthielt den FK-Rename-Bug, live aufgetreten
und sofort auf der Datenbank repariert.
`deploy/portal-v41.tar.gz` – korrigierter Migrations-Code, tatsächlich
getestet.

---

## 2026-07-28 – Rezepte: nachträglich bearbeiten (portal-v42)

Andi wollte Rezepte auch nachträglich ändern können – bisher gab es nur
Anlegen und Löschen, keine Bearbeitung.

### Design-Entscheidung

- Neue Route `/a/rezepte/<token>/<rid>/bearbeiten` (GET+POST) nutzt
  **dasselbe Formular** wie Neuanlegen und Import-Vorschau
  (`rezept_neu.html`), unterschieden nur über einen `bearbeiten`-Parameter
  (Ziel-Route, Titel, Speichern-Button-Text, "← Zurück" führt zur
  Detailseite statt zur Liste) – kein zweites Formular zu pflegen.
  Gleiches Wiederverwendungs-Muster wie `admin_user_form.html`
  (Neu/Bearbeiten in einer Vorlage).
- Der Import-Hinweis-Banner ("aus Webseite vorausgefüllt") erscheint
  jetzt nur noch, wenn `vorbelegt` gesetzt ist **und nicht** `bearbeiten`
  – sonst hätte er beim Bearbeiten fälschlich mit angezeigt, weil beide
  Modi dieselbe `vorbelegt`-Datenstruktur nutzen.
- Zutaten/Schritte werden beim Speichern komplett ersetzt (alle
  löschen, neu einfügen) statt zeilenweise abzugleichen – deutlich
  einfacher, und die Positions-Nummerierung ergibt sich dabei
  automatisch neu.
- "✏️ Bearbeiten" und "🗑️ Löschen" jetzt nebeneinander auf der
  Detailseite statt nur der Löschen-Button.

### Testergebnisse (Playwright, Wegwerf-Testnutzer, danach restlos entfernt)

- Bearbeiten-Link vorhanden, führt zum vorausgefüllten Formular (Name,
  Portionen, Zutaten, Schritte korrekt übernommen), kein Import-Hinweis
  fälschlich sichtbar: ✅
- Name, Portionen, Zutaten und Schritte geändert und gespeichert – alle
  Änderungen korrekt auf der Detailseite, alte Zutaten vollständig
  ersetzt (nicht nur ergänzt): ✅
- Aufräumen erfolgreich, `PRAGMA foreign_key_check` weiterhin leer,
  echte Rezepte (inkl. eines während des Tests von der Familie live
  importierten) unangetastet.

### Auslieferungspaket

`deploy/portal-v42.tar.gz` – nur `portal` neu gebaut/gestartet.

---

## 2026-07-28 – Wünsche #52+#53: Rezept-Sterne-Bewertung + prominente Anzeige (portal-v43)

Zwei zusammenhängende, mit "mittel" priorisierte Wünsche in einem Zug
umgesetzt, da #53 auf der Durchschnittsbewertung aus #52 aufbaut:

- #52: Jeder Nutzer soll jedes Rezept einmal mit 1-5 Sternen bewerten
  können, editierbar; Durchschnitt über alle Bewertungen je Rezept.
- #53: Portionen und Durchschnittsbewertung sollen auf der Rezept-Seite
  sichtbarer sein, z. B. in einem Abschnitt über der Zutatenliste.

### Design-Entscheidungen

- Neue Tabelle `rezept_bewertungen` (rezept_id, user_id, sterne,
  `UNIQUE(rezept_id, user_id)`) – die UNIQUE-Regel erzwingt "eine
  Bewertung pro Nutzer und Rezept" direkt auf DB-Ebene; Ändern der
  eigenen Bewertung ist ein `INSERT ... ON CONFLICT DO UPDATE`
  (gleiches Upsert-Muster wie bei den Essensplan-Einträgen), kein
  Duplikat-Handling im Anwendungscode nötig.
- Sterne-Klick löst sofort einen Fetch-Aufruf aus (kein Seiten-Reload,
  gleiches Muster wie der bestehende "🛒 Fehlt"-Knopf) – Route gibt den
  neuen Durchschnitt direkt als JSON zurück, damit die Anzeige ohne
  Neuladen aktualisiert werden kann.
- #53 direkt mitgelöst statt separat: neuer kombinierter Info-Abschnitt
  (Portionen + Durchschnittsbewertung + eigener Sterne-Picker) jetzt
  ganz oben auf der Detailseite, oberhalb der Zutatenliste – die kleine
  Portionen-Subline im Header-Titel wurde dafür entfernt (Wunsch #53
  wollte ausdrücklich bessere Sichtbarkeit, nicht zusätzlich zur
  bisherigen kleinen Anzeige).

### Testergebnisse (Playwright, zwei Wegwerf-Testnutzer, danach restlos entfernt)

- Ohne Bewertungen: "Noch keine Bewertung" statt eines Fehlers oder
  falscher Zahl: ✅
- Testnutzer 1 bewertet mit 4 Sternen → Durchschnitt "4.0 (1)", eigene
  4 Sterne korrekt markiert: ✅
- Testnutzer 2 (eigene Session) sieht den korrekten Durchschnitt,
  eigene Bewertung korrekt leer (nicht fälschlich mit der Bewertung von
  Nutzer 1 vorbelegt), bewertet mit 2 Sternen → Durchschnitt korrekt neu
  berechnet auf "3.0 (2)": ✅
- Testnutzer 1 ändert die eigene Bewertung auf 5 Sterne (kein neuer
  Datensatz, echtes Update) → Durchschnitt korrekt auf "3.5 (2)" statt
  fälschlich "3" aus drei Werten: ✅
- Aufräumen erfolgreich, `PRAGMA foreign_key_check` weiterhin leer.
- Bei der Verifikation aufgefallen: die Familie hat zwischenzeitlich
  selbst weiter mit der App gearbeitet (ein Rezept bearbeitet, eins
  gelöscht, zwei neue importiert) – nichts davon durch meinen Test
  verursacht, nur beobachtet und unangetastet gelassen.

### Auslieferungspaket

`deploy/portal-v43.tar.gz` – nur `portal` neu gebaut/gestartet.

---

## 2026-07-28 – Wünsche #54+#55: Bewertung in Übersicht + Kategorien Kochen/Backen (portal-v44)

Zwei weitere, ebenfalls mit "mittel" priorisierte Wünsche direkt im
Anschluss umgesetzt:

- #54: Durchschnittsbewertung soll schon in der Rezeptübersicht zu
  sehen sein, nicht erst auf der Detailseite.
- #55: Rezepte sollen in "Kochen" und "Backen" kategorisiert werden
  können.

### Design-Entscheidungen

- `rezepte.kategorie` (TEXT, nullable) – bewusst nur zwei feste Werte
  (`kochen`/`backen`) statt eines offenen Kategoriesystems, weil der
  Wunsch explizit nur diese zwei nennt; `KATEGORIEN`-Dict in
  `11_rezepte.py` als einzige Quelle der Wahrheit für Werte+Label+Emoji.
  `_clean_kategorie()` validiert wie `_clean_farbe()`/`_clean_ki_limit()`
  gegen die erlaubte Menge, sonst `None`.
- Kategorie-Auswahl im Formular als Chip-Buttons (Keine/Kochen/Backen),
  gleiches Muster wie die Kategorie-Chips in `einkauf.html` (Klasse
  `.chip-btn`/`.active`, verstecktes Feld + JS-Toggle) statt eines neuen
  UI-Vokabulars.
- #54 direkt mit der `index()`-Abfrage kombiniert (gleiche Subquery wie
  auf der Detailseite, nur pro Listenzeile), damit keine zweite Abfrage
  über alle Rezepte nötig ist, wenn man ohnehin schon durch die Liste
  iteriert.
- Kategorie-Filter auf der Übersicht als Chips ("Alle"/"Kochen"/"Backen"),
  kombiniert mit der bestehenden Textsuche (Wunsch #49) über dieselbe
  Filterfunktion – beide Bedingungen (Text + Kategorie) müssen erfüllt
  sein, keine zwei getrennten Filter-Mechanismen.
- Kein Versuch, die Kategorie beim Import automatisch zu erkennen
  (weder JSON-LD noch KI) – das ist eine subjektive Zuordnung, die der
  Nutzer selbst trifft, wenn er das vorausgefüllte Formular vor dem
  Speichern prüft.

### Testergebnisse (Playwright, Wegwerf-Testnutzer, danach restlos entfernt)

- Zwei Testrezepte mit je einer Kategorie angelegt, Kategorie korrekt
  auf der Detailseite im Info-Abschnitt sichtbar: ✅
- Nach Bewertung eines Rezepts: Durchschnitt korrekt in der
  Übersichts-Kachel sichtbar ("⭐ 5.0 (1)"): ✅
- Kategorie-Filter: "Kochen" zeigt nur das Kochen-Rezept, "Backen"
  korrekt ausgeblendet; "Alle" stellt beide wieder her: ✅
- Beim Verifizieren aufgefallen: die Familie hat inzwischen selbst
  mehrere echte Rezepte bewertet (4.0/5.0 sichtbar) – das neue
  Bewertungsfeature aus #52 wird bereits aktiv genutzt.
- Aufräumen erfolgreich, `PRAGMA foreign_key_check` weiterhin leer,
  echte Rezepte unangetastet.

### Auslieferungspaket

`deploy/portal-v44.tar.gz` – nur `portal` neu gebaut/gestartet.

---

## 2026-07-28 – Wünsche #56+#57: Hilfe-Seite Inhaltsverzeichnis + Nach-oben-Button (portal-v45)

Letzte beiden "mittel"-Wünsche dieser Runde, beide zur selben Seite und
klar zusammengehörig:

- #56: Nach-oben-Button, da die Hilfe-Seite lang geworden ist.
- #57: Inhaltsverzeichnis am Anfang mit Sprunglinks zu jedem Kapitel.

### Design-Entscheidungen

- Jedem der 13 `.section`-Blöcke eine `id="kapitel-N"` gegeben, in
  fester Reihenfolge; das Inhaltsverzeichnis ist eine Jinja-Liste
  `[(anchor, label), ...]` am Anfang von `{% block body %}`, aus der
  sowohl die Sprunglinks als auch (implizit, weil in derselben
  Reihenfolge wie die Sections) die IDs gepflegt werden. Kein
  automatisches Nummerieren über eine Schleife – die Hilfe-Seite ist
  handgeschriebener Inhalt mit sehr unterschiedlicher Struktur pro
  Abschnitt (Listen, Tipps, Schritte), eine generische
  Datenstruktur dafür wäre für eine einzelne statische Hilfeseite
  Überengineering gewesen. Stattdessen ein Kommentar-Hinweis im Kopf,
  dass Liste und Section-IDs synchron bleiben müssen.
- Nach-oben-Button als einfacher `position:fixed`-Kreis unten rechts,
  immer sichtbar (kein Ein-/Ausblenden je nach Scroll-Position) –
  bewusst simpel gehalten, kein zusätzlicher Scroll-Listener nötig.
  `z-index:50`, unterhalb des Hamburger-Menüs (200/300) angesiedelt.

### Testergebnisse (Playwright, Wegwerf-Testnutzer, danach restlos entfernt)

- 13 Inhaltsverzeichnis-Links vorhanden, Klick auf "Rezepte" springt
  korrekt zu `#kapitel-9` (Kapitel exakt am oberen Bildschirmrand): ✅
- Nach-oben-Button vorhanden, sichtbar, klickbar; nach Klick landet die
  Seite wieder bei `scrollY=0` (glatte Scroll-Animation, im ersten
  Testlauf mit zu kurzer Wartezeit gemessen – nach Anpassung der
  Wartezeit im Test bestätigt, kein echter Bug): ✅

### Auslieferungspaket

`deploy/portal-v45.tar.gz` – nur `portal` neu gebaut/gestartet.

---

## 2026-07-28 – Wünsche #58–#61: sehr_hoch/hoch-Batch (portal-v46)

Auf Anweisung "Implementiere alle Wünsche, die sehr hoch oder hoch
priorisiert sind" alle vier zu diesem Zeitpunkt so eingestuften Wünsche
umgesetzt.

- #59 (sehr_hoch): "Wird der Verbesserungswunsch in der Werkstatt
  ausgeführt, dann stimmt das Layout nicht."
- #58 (hoch): Einkaufsliste – Kategorie/Angebot/Markt sollen über
  mehrere Einträge hinweg markiert bleiben, aber beim erneuten Öffnen
  der App wieder zurückgesetzt sein.
- #60 (hoch): Werkstatt-Seite soll neu laden, wenn dort gerade ein
  neuer Wunsch eingetragen wird.
- #61 (hoch): Neue Priorität "Zurückgestellt" – zurückgestellte
  Wünsche dürfen nie automatisiert umgesetzt werden, auch nicht unter
  einer pauschalen "implementiere alle Wünsche"-Anweisung.

### Root-Cause-Recherche #59

Vermutet wurde zunächst ein CSS-/Layout-Fehler auf der Wunsch-Karte;
Screenshots von offenen und erledigten Karten zeigten aber keinen
visuellen Defekt. Direkter SQL-Vergleich zeigte den eigentlichen Fehler:
`manage.py wunsch_erledigt` setzte nur `erledigt=1`, nie `erledigt_am`.
Die Erledigt-Liste sortiert nach
`COALESCE(w.erledigt_am, w.erstellt) DESC` – bei NULL fällt das auf das
ursprüngliche Erstellungsdatum zurück, wodurch die Erledigt-Liste in
falscher Reihenfolge erschien. Das war gemeint mit "das Layout stimmt
nicht", wenn ein Wunsch "ausgeführt" wird. Betraf jeden Wunsch, der in
dieser gesamten Session per CLI abgeschlossen wurde.

**Fix**: `manage.py cmd_wunsch_erledigt` setzt jetzt zusätzlich
`erledigt_am=CURRENT_TIMESTAMP`. Live-Reparatur der zwei zu dem
Zeitpunkt betroffenen Zeilen (#56, #57) direkt in der DB; ältere Wünsche
(#48–55) waren bereits durch die bestehende `00_kern.py`-Migration
(`erledigt_am=erstellt` als Näherung) nicht-NULL.

### Design-Entscheidungen

- #58: `sessionStorage` statt Serverfeld oder AJAX-Umbau des
  Hinzufügen-Formulars – erfüllt beide Hälften der Anforderung von
  selbst (übersteht den Seiten-Reload nach dem Hinzufügen im selben
  Tab, wird aber beim echten Schließen des Tabs/Browsers verworfen).
  Serverseitige Gruppierungs-/Sortierlogik beim Hinzufügen blieb
  unangetastet, keine Duplizierung dieser Logik in JS nötig – die
  bereits vorhandenen Klick-Handler der Chip-Buttons übernehmen das
  Setzen von verstecktem Feld/`.active`-Klasse, das Wiederherstellen
  simuliert nur einen Klick auf den passenden Chip.
- #60: Bewusst eng gefasst auf "aktueller Nutzer trägt einen neuen
  Wunsch ein, während er selbst auf der Werkstatt-Seite ist"
  (`app_slug === 'werkstatt'`-Check im gemeinsamen ✨-Handler in
  `base.html`), nicht als geräteübergreifendes Live-Update – Letzteres
  hätte Polling oder Websockets erfordert, was der bisherigen
  Architektur (kein Polling, keine Websockets) widerspräche.
  Kein Reload, wenn die Server-Antwort `ok:false` liefert.
- #61: Neue Priorität `zurueckgestellt` in `_PRIORITAETEN` und
  `_PRIO_ORDER` (Sortierwert 6, hinter `niedrig`=4 und dem
  NULL-Catchall=5 – landet also ganz unten in der Offen-Liste), Label
  "Zurückgestellt" mit neutralem Grau (`#8e8e93`) in
  `werkstatt_app.html`. Die eigentliche Verhaltensregel ("nie
  automatisiert umsetzen") ist keine Code-Logik, sondern eine
  verbindliche Vorgabe für jede KI, die an diesem Projekt arbeitet –
  als Docstring in `05_werkstatt_app.py` UND als Memory-Eintrag
  festgehalten, damit sie über Sitzungsgrenzen hinweg gilt.

### Testergebnisse (Playwright, Wegwerf-Testnutzer, danach restlos entfernt)

- #59: `manage.py wunsch_erledigt` gegen einen Test-Wunsch ausgeführt,
  `erledigt_am` korrekt mit aktuellem Zeitstempel gefüllt (vorher
  `None`): ✅
- #61: "Zurückgestellt" erscheint als Option im Prioritäts-Dropdown,
  auswählbar; per SQL-Nachvollzug bestätigt, dass `zurueckgestellt`
  (Sortierwert 6) tatsächlich hinter allen anderen Prioritäten
  einsortiert: ✅. **Stolperstein im eigenen Testlauf**: das
  Playwright-Skript hat versehentlich die erste (weil `sehr_hoch`,
  somit oben sortierte) Karte der Offen-Liste umgestellt – das war
  zufällig der echte Wunsch #59 selbst, nicht ein Test-Wunsch. Sofort
  bemerkt (Badge zeigte "Zurückgestellt" bei #59), Priorität wieder auf
  `sehr_hoch` zurückgesetzt, kein Schaden entstanden, da #59 ohnehin im
  selben Zug als erledigt markiert wurde.
- #60: Neuen Wunsch über das ✨-Menü auf der Werkstatt-Seite
  abgeschickt, Seite lädt automatisch neu, neuer Wunsch sofort in der
  Liste sichtbar: ✅
- #58: Artikel mit gewählter Kategorie + aktiviertem Angebot/Markt
  eingetragen; nach dem Reload nach dem Hinzufügen blieb dieselbe
  Kategorie und der Angebot-Status markiert: ✅. Frischer
  Browser-Kontext (kein `sessionStorage`) zeigte danach korrekt keine
  aktive Kategorie: ✅

### Aufräumen

Test-Wünsche (#62, #63), Test-Artikel, Test-User `ZZZ_TestFinal`
(inkl. Grants) vollständig aus der Live-DB entfernt.

### Auslieferungspaket

`deploy/portal-v46.tar.gz` – nur `portal` neu gebaut/gestartet.

---

## 2026-07-29 – Wunsch #62: neue App "Sportschau" (portal-v49)

Auf Anweisung "Setze alle Wünsche um" den nächsten offenen Wunsch umgesetzt:
eine neue App, die Andis Trainings vom hae-Server (Health Auto Export,
selbst gehostet auf demselben Docker-Host) als 10-Tage-Heatmap zeigt –
eine Zeile pro Trainingsart, analog zur Geholfen-Heatmap.

### API-Recherche

Der Wunsch nannte nur `POST /api/data` (Write-Token, für die iPhone-
Automation) und eine "api-key"-Auth. Im GitHub-Repo
(`HealthyApps/health-auto-export-server`, `server/src/`) gefunden: es gibt
einen separaten `GET /api/workouts?startDate&endDate` mit eigenem
Read-Token (`READ_TOKEN`, anderer Wert als `WRITE_TOKEN`, beide über
denselben Header `api-key`). Antwortformat pro Workout:
`{id, workout_type, start_time (ISO/UTC), end_time, duration_minutes,
calories_burned}`. Der von Andi gegebene Schlüssel funktionierte nicht auf
`/api/data` ("Invalid write token"), aber korrekt auf `/api/workouts` –
war also der Read-Token, nicht der Write-Token. Live gegen
`https://health-api.16schwaben.de/api/workouts` verifiziert (echte
Trainingsdaten von Andi kamen zurück), bevor überhaupt Code geschrieben
wurde.

### Netzwerk-Stolperstein: portal kann den hae-Server nicht direkt erreichen

`health-api.16schwaben.de` löst nur über Pi-hole (10.0.0.194, LAN-lokal) zu
einer macvlan-IP auf demselben Docker-Host auf (10.0.0.199) – home02 selbst
nutzt einen anderen DNS-Server und kann den Namen nicht auflösen (weder der
Host noch `portal`, das nur im internen Bridge-Netz hängt). `caddy` hat als
einziger Container eine macvlan-IP (10.0.0.200) und kann 10.0.0.199 direkt
per IP erreichen (gleiches L2-Segment). Lösung: ein zusätzlicher, rein
interner Caddy-Site-Block auf `172.30.0.10:2021` (nur im Bridge-Netz
erreichbar, nie über 10.0.0.200 oder von außen), der 1:1 zu `10.0.0.199:443`
weiterreicht (`transport http { tls; tls_server_name health-api.16schwaben.de }`,
`header_up Host health-api.16schwaben.de` – IP-Dial mit korrektem SNI/Host,
da der Zielserver anhand des Hostnamens routet/sein Zertifikat wählt).
`portal` ruft `http://caddy:2021/api/workouts` statt der öffentlichen
Domain auf. Kein Eingriff auf dem Host nötig (kein `/etc/hosts`, keine neue
macvlan-IP für `portal`) – alles bleibt innerhalb von `/srv/familienportal/`.

**Zusätzlicher Stolperstein dabei**: Nach dem ersten `tar xzf` auf dem
bereits laufenden `caddy`-Container blieb die neue Caddyfile-Zeile
unsichtbar (`caddy reload` griff auf den alten Inhalt zu) – `tar` ersetzt
eine Datei beim Überschreiben durch Unlink+Neuanlage (neues Inode), der
laufende Container war aber per Single-File-Bind-Mount noch an das alte,
jetzt verwaiste Inode gebunden. Ein `docker compose up -d --force-recreate
caddy` (statt nur `reload`) hat den Mount aufgefrischt. Gilt für jede
zukünftige Caddyfile-Änderung, die am selben Tag ausgeliefert wird wie ein
`tar xzf`-Refresh.

### Design-Entscheidungen

- Kein Speichern in `portal.db` (explizit im Wunsch gefordert) – jeder
  Seitenaufruf ruft live die letzten 10 Tage ab. Bei Nichterreichbarkeit
  des hae-Servers zeigt die Seite einen Hinweis statt eines Fehlers.
- `HAE_API_URL`/`HAE_API_KEY` in `.env` (Konfigurationsmuster identisch zu
  `OPENROUTER_API_KEY`: `app.config` in `app.py`, ausgelesen in
  `teile/14_sportschau.py`), Aufruf über `urllib.request` statt einer neuen
  `requests`-Abhängigkeit – gleiche Konvention wie `ki_anfrage()`.
- UTC→Europe/Berlin-Umrechnung der `start_time` per `zoneinfo`
  (`tzdata`-Paket zu `requirements.txt` hinzugefügt, da `python:3.12-slim`
  keine System-Tzdata mitbringt), damit späte Abendtrainings nicht dem
  falschen Kalendertag zugeordnet werden.
- Zugriff vorerst nur für Andi selbst (`grant 1 sportschau`) – es sind
  seine persönlichen Fitnessdaten, kein Auto-Grant für alle wie bei
  hilfe/einkauf.
- Heatmap-CSS 1:1 aus `geholfen.html` übernommen (gleiche Klassennamen),
  nur die Zeilen sind Trainingsarten statt Nutzer.

### Testergebnisse

- Relay `caddy:2021` → `10.0.0.199:443` liefert echte Workout-Daten an
  `portal` (curl-Test von innerhalb des `portal`-Containers): ✅
- Sportschau-Seite zeigt 2 Trainingsarten ("Outdoor Ausführen",
  "Outdoor Spaziergang") mit korrekter Anzahl grüner Zellen, 10 Zellen
  pro Zeile: ✅
- Hilfe-Seite: neues Kapitel 13 "🏃 Sportschau" vorhanden (Kapitel "Link
  verloren" auf 14 verschoben): ✅

### Auslieferungspaket

`deploy/portal-v49.tar.gz` – `portal` neu gebaut, `caddy` force-recreated
(Caddyfile-Änderung).

---

## 2026-07-29 – Wunsch #63: Link zum Originalrezept (portal-v50)

Direkt im Anschluss der nächste offene ("hoch"), zwischenzeitlich neu
eingetragene Wunsch: Rezepte, die per URL importiert werden, sollen einen
Link zur Originalseite behalten – dort stehen oft Nährwerte oder Fotos,
die das Portal selbst nicht speichert.

### Design-Entscheidungen

- Neue Spalte `rezepte.quelle_url` (TEXT, nullable) per `ALTER TABLE ADD
  COLUMN` in `00_kern.py` – nicht per RENAME/Neubau, siehe die
  dokumentierte FK-Falle bei `rezepte` weiter oben in dieser Datei bzw. in
  `server.md`.
  `importieren()` setzt `rezept["quelle_url"] = url` nach erfolgreicher
  JSON-LD- oder KI-Extraktion, bevor das vorausgefüllte Formular gerendert
  wird; ein verstecktes Formularfeld trägt den Wert bis zum Speichern in
  `neu()`. Beim manuellen Anlegen (kein Import) bleibt das Feld leer.
- Erneute `_ist_oeffentliche_url()`-Prüfung beim Speichern in `neu()`
  (nicht nur beim Abrufen in `importieren()`), da das versteckte
  Formularfeld clientseitig manipulierbar ist – dieselbe SSRF-Prüfung wird
  hier als reine URL-Plausibilitätsprüfung vor dem Speichern
  wiederverwendet.
  `bearbeiten()` fasst die Spalte nicht an (UPDATE ohne `quelle_url` im
  SET), Bearbeiten eines Rezepts löscht den Link also nicht.
- Link auf der Detailseite als schlichter Text-Link "🔗 Zum
  Originalrezept" unterhalb der Zubereitung, nur sichtbar wenn
  `quelle_url` gesetzt ist.

### Testergebnisse (Playwright, Wegwerf-Testnutzer, danach restlos entfernt)

- Formular mit gesetztem `quelle_url`-Feld gespeichert, Link auf der
  Detailseite korrekt mit Text "🔗 Zum Originalrezept" und richtigem
  `href` sichtbar: ✅
- Direkter DB-Check bestätigt den gespeicherten Wert: ✅

### Auslieferungspaket

`deploy/portal-v50.tar.gz` – nur `portal` neu gebaut/gestartet.

---

## 2026-07-29 – Wunsch #64: neue App "Tierbaukasten" (portal-v52)

Auf erneute Anweisung "Setze alle Wünsche um" den nächsten offenen Wunsch
umgesetzt – von Friederike: "Ich brauche eine App, mit der ich Z.B. Tiere
selber entwerfen kann." (hoch priorisiert). Der Wunsch war offen genug
formuliert (freies Zeichnen? Bausteine? KI-Generierung?), dass vorab bei
Andi nachgefragt wurde: Ergebnis war ein Baukasten-Ansatz (Tierart +
Körperfarbe + Muster + Accessoire kombinieren, kein freies Zeichnen), und
jeder Nutzer sieht nur seine eigene Galerie, keine gemeinsame Pinnwand.

### Design-Entscheidungen

- Reines SVG statt Canvas – sechs Tierarten (Katze, Hund, Hase, Bär, Vogel,
  Fisch) als handgezeichnete Formen in Jinja-Macros
  (`teile/templates/tierbaukasten.html`), Körperfarbe und Musterfarbe über
  CSS Custom Properties (`--koerper-farbe`/`--muster-farbe`) auf dem
  `<svg>`-Wurzelelement gesetzt – Formen selbst referenzieren sie per
  `style="fill:var(--koerper-farbe)"`. Dieselben Macros erzeugen sowohl die
  interaktive Bau-Vorschau (alle 6 Tierarten im DOM, nur eine sichtbar,
  JS schaltet um) als auch die statischen Galerie-Kacheln (ein Tier pro
  Karte, Farben direkt aus der DB) – kein doppelter Formen-Code.
  Jede Tierart hat einen fixen Kopf/Augen-Bereich (immer an derselben
  Position), damit Accessoires (Hut/Schleife/Brille) unabhängig von der
  gewählten Tierart an der richtigen Stelle sitzen.
- Muster (Streifen/Punkte/Flecken) werden per SVG `clip-path` auf die
  Körperform der jeweiligen Tierart begrenzt (`<clipPath><use href="#body-…">`),
  damit sie nicht über Ohren/Schwanz hinausmalen.
- Neue Tabelle `tierbaukasten_kreationen` (user_id, tier_typ, koerper_farbe,
  muster, muster_farbe, accessoire, name, erstellt) – kein Editieren
  nachträglich, nur Anlegen/Löschen (Wunsch nannte kein Bearbeiten).
  Löschen mit Sicherheitsabfrage wie überall sonst im Portal.
- Zugriff zunächst nur für Friederike als Wunsch-Urheberin freigeschaltet
  (`grant 3 tierbaukasten`) – Andi hat während der Sitzung selbst über den
  Admin-Bereich allen vier Nutzern Zugriff gegeben und bereits eigene Tiere
  angelegt ("Test", "Huhu", "Wuffi").

### Stolperstein: Nase/Schnabel unsichtbar (Z-Order)

Erster Screenshot-Test zeigte bei allen vier Säugetieren (Katze, Hund,
Hase, Bär) keine Nase und beim Vogel keinen Schnabel – Ursache: diese
Formen lagen exakt im Bereich des gemeinsamen Kopf-Kreises, wurden aber
VOR dem Kopf gezeichnet und damit vollständig von der deckenden
Kopf-Füllfarbe übermalt. Behoben durch eine eigene Macro `gesicht_teile()`,
die separat NACH `kopf_und_augen()` gerendert wird (Malreihenfolge, nicht
Position, war das Problem). Der Fisch wirkte zusätzlich kaum als Fisch
erkennbar (Rückenflosse ebenfalls hinterm Kopf versteckt, Seitenflossen
farblich im Körper verschwunden) – Rückenflosse über den Kopf hinaus nach
oben verschoben, Seitenflossen weiter nach außen versetzt, damit sie klar
als eigene Form sichtbar werden.

### Testergebnisse (Playwright, Wegwerf-Testnutzer bzw. echter Friederike-Token, Testdaten danach entfernt)

- Alle 6 Tierarten-Chips vorhanden, Umschalten zeigt jeweils korrekte
  Vorschau (Bär+Punkte+Brille visuell per Screenshot geprüft, nach dem
  Z-Order-Fix Nase/Schnabel/Flügel/Flossen bei allen Arten sichtbar): ✅
- Speichern legt Eintrag in "Meine Tiere" mit korrektem Namen und
  korrekten Farb-Variablen auf dem Galerie-SVG an: ✅
- Löschen (mit Bestätigungsdialog) entfernt den Eintrag wieder: ✅

### Auslieferungspaket

`deploy/portal-v52.tar.gz` – nur `portal` neu gebaut/gestartet
(zwei Deploys: v51 Erstversion, v52 Z-Order-/Fisch-Fix).

### Nebenbei: erster Wunsch #65 gelöscht

Ein weiterer, offenbar versehentlich abgeschickter Wunsch (Text nur "M",
keine Priorität) wurde nach Rückfrage bei Andi gelöscht statt umgesetzt.
Da `wuensche.id` kein `AUTOINCREMENT` hat, wurde die Nummer #65 beim
nächsten neuen Wunsch direkt wiederverwendet (siehe nächster Abschnitt).

---

## 2026-07-29 – Wunsch #65 (neu): Rezept-Wunschliste "Wünsch ich mir" (portal-v53)

Explizite Anweisung "Setze den Wunschnummer 65 um" – zu diesem Zeitpunkt
war unter derselben ID ein neuer, vollständiger Wunsch entstanden (die
zuvor gelöschte "M"-Notiz hatte dieselbe Nummer freigegeben): "Jeder
Benutzer soll bis zu fünf Rezepte mit einer „wünsch ich mir" Markierung
markieren können, um den Rezept Wunsch auf eine Wunschliste zu schreiben,
damit er demnächst auf dem Essensplan aufgenommen werden kann. Nachdem das
Rezept dann auf dem Essensplan war und der Tag abgeschlossen ist, soll die
Markierung wieder entfernt werden. Haben mehrere Benutzer das gleiche
Rezept gewünscht, wird dies auch in der Übersicht dargestellt, wie häufig
es gewünscht wurde." (hoch priorisiert)

### Design-Entscheidungen

- Neue Tabelle `rezept_wuensche` (rezept_id, user_id, erstellt;
  UNIQUE(rezept_id,user_id)) – ein Toggle-Endpunkt
  (`POST /a/rezepte/<token>/<rid>/wunsch/toggle`) markiert/entmarkiert und
  gibt den neuen Zustand + die Gesamtanzahl als JSON zurück (Fetch statt
  Reload, gleiches Muster wie die Sterne-Bewertung). Serverseitiges Limit
  von 5 aktiven Wünschen pro Nutzer (`MAX_REZEPT_WUENSCHE`), bei
  Überschreiten HTTP 400 mit `grund:"limit"`, im Frontend als `alert()`
  abgefangen.
- Automatisches Entfernen erfüllter Wünsche:
  `bereinige_erfuellte_rezeptwuensche()` (neu in `00_kern.py`, da sie sowohl
  `rezept_wuensche` als auch `essensplan_eintraege` anfasst – zwei
  verschiedene App-Module) löscht einen Wunsch, sobald es einen
  Essensplan-Eintrag für dasselbe Rezept mit `tag < heute` UND
  `wunsch.erstellt <= tag` gibt – die zweite Bedingung ist wichtig: nur
  Wünsche, die VOR der (inzwischen vergangenen) Essensplan-Eintragung
  entstanden sind, gelten als „durch dieses Servieren erfüllt". Ein neuer
  Wunsch fürs selbe Rezept NACH einem vergangenen Servier-Termin bleibt
  unangetastet, bis es erneut serviert wird – sonst hätte jedes Rezept, das
  irgendwann einmal auf dem Plan stand, nie wieder dauerhaft gewünscht
  werden können. Aufruf lazy bei jedem Aufruf von `index()`/`detail()` in
  `11_rezepte.py`, kein Hintergrund-Job nötig (gleiches Prinzip wie
  `_gesperrter_wochentag()` in `06_geholfen.py`).
- UI: Stern-Button + Anzahl-Badge sowohl auf der Übersichtskarte
  (`rezepte.html`, `event.preventDefault()/stopPropagation()` verhindert
  Navigation der umschließenden `<a>`) als auch auf der Detailseite
  (`rezept_detail.html`, neben der Bewertung im Info-Bereich). Zusätzlich
  ein eigener Filter-Chip "🌟 Gewünscht" in der Übersicht (unabhängig von
  der Kategorie-Auswahl kombinierbar), damit die Wunschliste beim
  Essensplan-Planen schnell auffindbar ist – volle Nutzung von "damit er
  demnächst auf dem Essensplan aufgenommen werden kann".

### Testergebnisse (Playwright + direkte SQL-Manipulation, zwei Wegwerf-Testnutzer, 6 Test-Rezepte, danach restlos entfernt inkl. `PRAGMA foreign_key_check`)

- 5 Rezepte wünschen: alle 5 Sterne aktiv: ✅
- 6. Wunsch: serverseitig abgelehnt (Limit), Alert-Text korrekt, weiterhin
  nur 5 aktive Sterne: ✅
- Filter-Chip "Gewünscht": zeigt korrekt genau die 5 markierten Karten: ✅
- Zweiter Testnutzer wünscht dasselbe Rezept: Badge zeigt korrekt "2": ✅
- Cleanup: Wunsch mit zurückdatiertem `erstellt` + Essensplan-Eintrag mit
  vergangenem Datum für dasselbe Rezept → nach Seitenaufruf automatisch
  entfernt: ✅. Neuer Wunsch fürs selbe (bereits „erfüllte") Rezept danach
  angelegt → bleibt beim nächsten Seitenaufruf unangetastet bestehen: ✅

### Auslieferungspaket

`deploy/portal-v53.tar.gz` – nur `portal` neu gebaut/gestartet.

### Nebenbei: noch ein neuer Wunsch #66 eingegangen

Friederike hat direkt im Anschluss einen größeren Ausbauwunsch für den
Tierbaukasten eingereicht (Mensch/Tier-Auswahl, realistischeres Aussehen,
Körperform/Dicke einstellbar, seitliches Drehen/Bearbeiten per
Pfeiltasten) – noch nicht umgesetzt, da die aktuelle Anweisung sich
explizit nur auf Wunsch #65 bezog.

---

## 2026-07-29 – Wunsch #66: Tierbaukasten-Ausbau – Assistent, Mensch-Figur, Detail-Upgrade (portal-v56)

Anweisung "Setze den Wunsch von Friederike um" – zu diesem Zeitpunkt war
das Wunsch #66 (siehe oben). Deutlich größerer Umbau als der ursprüngliche
Tierbaukasten (Wunsch #64): "Die Tiere ... sollen echter aussehen und es
soll mehr Möglichkeiten geben" – mehrstufiger Assistent (Pfeil oben rechts
= weiter), Kategorie Mensch/Tier, bei Tier die Tierart, dann Form/Farbe/
Dicke/Art des Körpers anpassen, dabei mit zwei Pfeiltasten den kompletten
Körper von verschiedenen Seiten sehen und bearbeiten können.

### Vorab-Rückfrage (4 Weichenstellungen)

Wunsch beschrieb einen mehrstufigen Assistenten, aber die Interpretation
mehrerer Details war zu unklar, um blind zu raten – vorab bei Andi
nachgefragt:
1. Echter Schritt-für-Schritt-Assistent (wie im Wunsch beschrieben) statt
   nur die bestehende Ein-Seiten-Ansicht zu erweitern.
2. Mensch-Figur sofort mit bauen, nicht nur die Tier-Seite verbessern.
3. Zeichenstil "deutlich detaillierter" (nicht "möglichst fotorealistisch") –
   klarer Sprung gegenüber vorher, aber weiterhin flaches Illustrations-SVG.
4. Die "zwei Pfeiltasten links/rechts" = Ansicht drehen (vorne/seite/hinten
   als vorgezeichnete Blickwinkel), nicht zwischen Körperteilen wechseln.

### Design-Entscheidungen

- **Assistent**: 3 Schritte in einem einzigen Formular (`baukasten-form`),
  nur per JS umgeschaltete `<div class="schritt">`-Blöcke – kein
  Server-Roundtrip zwischen den Schritten. Schritt 1 (Mensch/Tier) hat
  keine Vorauswahl, "Weiter"-Pfeil bleibt deaktiviert bis eine Kategorie
  gewählt ist. Bei Kategorie "Mensch" wird Schritt 2 (Tierart) komplett
  übersprungen (vor UND zurück), da es dort nichts auszuwählen gibt –
  `tier_typ='mensch'` wird automatisch gesetzt.
- **Kein neues Schema für Mensch/Tier**: `tier_typ` akzeptiert jetzt auch
  den Wert `'mensch'` (`ALLE_TYPEN = set(TIERE) | {'mensch'}` in
  `15_tierbaukasten.py`) – die Kategorie Mensch/Tier ist daraus ableitbar,
  kein zusätzliches DB-Feld nötig. Einzige neue Spalte:
  `tierbaukasten_kreationen.koerperbau` (INTEGER, 0-100, Default 50).
- **"Form/Dicke" + "Art des Körpers" bewusst konsolidiert**: statt vier
  eigenständiger, teils redundanter Achsen (Form, Farbe, Dicke, Art) nur
  EIN neuer Körperbau-Regler (schlank↔kräftig, wirkt als horizontale
  Skalierung `scaleX` auf die komplette Figur inkl. Kopf über
  `--koerperbau-scale` als CSS Custom Property) zusätzlich zur
  bestehenden Farbe – "Art des Körpers" wird vom bereits vorhandenen
  Muster-System (Streifen/Punkte/Flecken) abgedeckt, keine neue,
  eigentlich redundante Dimension erfunden.
- **Ansichten-Rotation (vorne/seite/hinten)**: nur eine Ansicht ist
  jeweils sichtbar (`data-ansicht`/`data-typ`-Attribute + JS-Filterung
  über alle `.ansicht-gruppe`-Elemente). Bewusste Aufwands-Abstufung:
  "vorne" ist die vollständig editierbare Hauptansicht (Farbe, Muster,
  Accessoire); "hinten" nutzt exakt dieselben Körper-Formen wie "vorne"
  (nur ohne Gesicht – `kopf_hinten()` statt `kopf_und_augen()`+
  `gesicht_teile()`), zeigt also weiterhin Muster, aber keine Accessoires
  (deren feste Positionen nur zur Vorderansicht passen); "seite" ist eine
  eigene, bewusst einfachere Silhouette pro Typ (gemeinsames Körper-Kopf-
  Bein-Grundgerüst mit kleinen typspezifischen Ergänzungen wie Ohren/
  Schwanz/Flügel) und zeigt nur die Grundfarbe, kein Muster/Accessoire.
  Diese Abstufung hält den Aufwand für 7 Figuren × 3 Ansichten
  handhabbar, ohne die Kernfunktion ("den kompletten Körper von
  verschiedenen Seiten sehen") zu verfehlen.
- **"Deutlich detaillierter"-Upgrade** für alle 6 Tiere: gemeinsamer
  Boden-Schatten (`boden_schatten()`), Glanzlicht auf Kopf und Körper
  (halbtransparente helle Ellipsen), 2-3 Fell-/Feder-/Schuppen-
  Strichtexturen pro Art, Pfoten/Flossen-Details am Körperansatz statt
  abrupt endender Grundform.
- **Mensch-Figur**: nutzt denselben gemeinsamen Kopf/Augen wie die Tiere
  (Wiederverwendung von `kopf_und_augen()`), zusätzlich Haare (Form fix,
  Farbe einstellbar), Körper/Arme/Schuhe. Farbfelder für den Menschen
  umbenannt (JS aktualisiert die Labels dynamisch): "Hautfarbe" statt
  "Farbe", "Kleidungsmuster" statt "Muster", "Haarfarbe" statt
  "Musterfarbe" – dieselben Formularfelder/DB-Spalten, nur andere
  Bedeutung, kein separates Mensch-Schema nötig.
- **Bugfix während der Entwicklung**: Die "Musterfarbe"-Zeile war
  ursprünglich nur sichtbar, wenn ein Muster ungleich "Keins" gewählt war
  (übernommen aus Wunsch #64) – das hätte bei der Mensch-Figur die
  Haarfarbe unerreichbar gemacht, solange kein Kleidungsmuster gewählt
  ist. Farbfeld jetzt immer sichtbar, unabhängig von der Musterwahl.
  Zweiter Fund: die Kopf-Position der seitlichen Mensch-Ansicht saß zu
  weit vom Körper entfernt (wirkte wie ein schwebender Kopf) – Kopf
  näher an den Körper herangerückt, analog zur Position bei den anderen
  Figuren mit ausreichender Überlappung.

### Testergebnisse (Playwright, echter Friederike-Token, Testdaten danach entfernt)

- Schritt 1→2→3 und zurück funktioniert, "Weiter" bleibt bis zur Auswahl
  deaktiviert: ✅
- Ansichten-Rotation (vorne→seite→hinten→vorne) zeigt jeweils korrekte
  Gruppen, per Screenshot geprüft (Bär mit Hut, Muster, Körperbau=90): ✅
- Kategorie "Mensch" überspringt Schritt 2 in beide Richtungen korrekt: ✅
- Speichern funktioniert, Galerie zeigt neue Figur korrekt inkl.
  Körperbau-Skalierung: ✅
- **Rückwärtskompatibilität**: Andis vier bereits vorher gespeicherte
  Tiere ("Test", "Huhu", "Wuffi", "Blubbi") rendern nach dem Update
  weiterhin fehlerfrei im neuen, detaillierteren Stil (per Screenshot
  geprüft), `koerperbau` wurde bei der Migration korrekt mit 50
  vorbelegt: ✅. `PRAGMA foreign_key_check` weiterhin leer.

### Auslieferungspaket

`deploy/portal-v56.tar.gz` – nur `portal` neu gebaut/gestartet
(drei Deploys während der Entwicklung: v54 Erstversion, v55 Musterfarbe-
Sichtbarkeits-Fix, v56 Mensch-Seitenansicht-Positionsfix).

### Nebenbei: noch ein neuer Wunsch #67 eingegangen

Friederike hat direkt im Anschluss eine Vokabel-Lern-App gewünscht
(Vokabeln mit Übersetzung eintragen, Lernziel als Freitext, Übungen wie
"Vokabeln in zwei Texten finden und anklicken", max. 4-5 Aufgaben pro
Aufgabenfolge) – noch nicht umgesetzt, da die aktuelle Anweisung sich auf
den zu dem Zeitpunkt einzigen offenen Friederike-Wunsch (#66) bezog.

---

## 2026-07-29 – Wünsche #68-#71: Tierbaukasten-Bugfixes + Rendering-Frage (portal-v58)

Anweisung "Setze die Wünsche um" – zu diesem Zeitpunkt waren vier neue
Wünsche offen, alle als direktes Feedback von Andi zur gerade gebauten
Tierbaukasten-Erweiterung (Wunsch #66):

- **#68** (mittel, Bug): Kleidungsmuster wurde nur in der Frontansicht
  angezeigt, nicht in Seiten-/Rückansicht.
- **#69** (mittel): mehrere Accessoires gleichzeitig kombinierbar statt
  nur eins.
- **#70** (mittel, Bug): Körperbau-Regler zeigte keine sichtbare
  Veränderung.
- **#71** (mittel, Frage): ob eine fertige Spiele-Rendering-Engine für
  realistischere Tierbilder eingesetzt werden kann.

### Root-Cause #70: Transform nie angewendet

Der Körperbau-Regler aktualisierte korrekt die CSS-Variable
`--koerperbau-scale`, aber die umschließende Gruppe `#figur-skalierung`
im Bau-Assistenten setzte zwar `transform-box`/`transform-origin`, aber
**nie tatsächlich `transform: scaleX(...)`** – ein schlicht vergessenes
Style-Attribut beim ersten Bau (die Galerie-Vorschau hatte den Transform
korrekt, weil sie ihn direkt serverseitig mit berechnetem Wert setzt statt
über die CSS-Variable). Ergänzt: `transform:scaleX(var(--koerperbau-scale))`.

### Root-Cause #68: Muster-Container an falscher DOM-Position

SVG malt in Dokumentreihenfolge. Der (einzige) `muster-container` lag im
DOM VOR den "hinten"-Körperformen – dadurch übermalte die undurchsichtige
Rückansicht-Körperform das darunterliegende Muster vollständig, sobald auf
"hinten" umgeschaltet wurde (bei "vorne" stand er zufällig an der
richtigen Stelle, deshalb dort sichtbar). Behoben durch drei eigene
Muster-Container (`muster-container-vorne/-hinten/-seite`), jeweils direkt
nach den zugehörigen Körperformen positioniert; JS blendet nur den zur
aktuellen Ansicht passenden ein und setzt dessen Clip-Pfad. Die
Seitenansicht bekam dafür eigene Body-IDs (`body-seite-<typ>`) und
Clip-Pfade (`clip-seite-<typ>`), die vorher gar nicht existierten.

### Design #69: mehrere Accessoires

`ACCESSOIRES`-Dict verliert den "Keins"-Eintrag (überflüssig bei
Mehrfachauswahl – leere Auswahl ist implizit "keins"). Die Chips schalten
jetzt unabhängig voneinander um (kein gegenseitiges Deaktivieren mehr),
das versteckte Feld speichert eine kommagetrennte Liste
(z. B. `"hut,brille"`) – **kein Schema-Umbau nötig**, `accessoire` blieb
immer schon eine simple TEXT-Spalte. Galerie und Bau-Vorschau rendern
jetzt alle in der Liste enthaltenen Accessoires statt nur eines.

### Antwort #71 (keine Code-Änderung)

Direkt an Andi beantwortet statt implementiert: eine Spiele-Engine würde
nicht helfen, weil der eigentliche Engpass die Illustrationsarbeit ist
(von Hand codierte SVG-Koordinaten), nicht die Rendering-Technologie –
eine 3D-Engine bräuchte zusätzlich echte 3D-Modelle, die für einfärbbare
Cartoon-Tiere nicht existieren, und würde außerdem gegen die
CDN-Bibliotheks-Regel aus `CLAUDE.md` verstoßen.

### Testergebnisse (Playwright, echter Friederike-Token, Testdaten danach entfernt)

- Körperbau-Regler: `getComputedStyle(...).transform` liefert jetzt
  unterschiedliche Matrix-Werte für schlank (5) vs. kräftig (95): ✅
- Muster sichtbar mit korrektem Clip-Pfad in allen drei Ansichten
  (vorne/seite/hinten), per Screenshot bestätigt: ✅
- Hut + Brille gleichzeitig aktivierbar, `accessoire-hidden` enthält
  `"hut,brille"`, Galerie zeigt nach dem Speichern beide: ✅

### Auslieferungspaket

`deploy/portal-v58.tar.gz` – nur `portal` neu gebaut/gestartet.

---

## 2026-07-29 – Wunsch #67: neue App "Vokabeln" (portal-v59)

Direkt im Anschluss Friederikes Vokabel-Lern-Wunsch umgesetzt (Text siehe
oben). Vorab vier Rückfragen zu Kernentscheidungen geklärt:

1. Übungstexte schreibt/fügt Friederike selbst ein (keine KI-Generierung).
2. Eine Aufgabe = passendes Wort in BEIDEN Texten (Quelle + Ziel) anklicken.
3. Falscher Klick: sofort nochmal versuchen, kein Abbruch, keine Strafe.
4. Listen sind privat pro Nutzer, wie beim Tierbaukasten.

### Design-Entscheidungen

- Zwei neue Tabellen: `vokabellisten` (user_id, lernziel als Freitext-Ziel
  statt separatem Namensfeld – deckt genau das ab, was der Wunsch mit
  "was ich genau lernen möchte" meinte, plus die zwei Übungstexte
  text_quelle/text_ziel) und `vokabeln` (liste_id, quelle, ziel, position).
- Vokabel-Eingabe als Textarea, eine Zeile pro Wortpaar im Format
  `quelle = ziel` (gleiches "ein Eintrag pro Zeile"-Muster wie
  Zutaten/Zubereitungsschritte bei Rezepten), serverseitig geparst.
- Übungsmechanik komplett clientseitig (kein Server-Roundtrip pro Klick,
  gleiches Prinzip wie der Tierbaukasten-Assistent): Server wählt beim
  Aufruf von `/uebung` bis zu 5 zufällige Vokabelpaare
  (`random.shuffle` + Slice) und tokenisiert beide gespeicherten Texte in
  Wort-/Nicht-Wort-Abschnitte (`\w+|[^\w]+`, Unicode-fähig für Umlaute).
  Wörter werden als klickbare `<span data-wort="...">` gerendert,
  Nicht-Wort-Abschnitte (Leerzeichen, Satzzeichen) unverändert als Text -
  damit bleibt die Original-Formatierung des eingefügten Texts erhalten.
- Prompt-Text (Vokabel + Übersetzung) wird über `textContent`-Zuweisungen
  gesetzt, nie über `innerHTML` mit Nutzerdaten (Konvention aus
  `CLAUDE.md`) - `aufgaben`-Liste selbst geht sicher über Jinjas
  `tojson`-Filter in einen `<script>`-Block.
- Kein serverseitiger Abgleich/keine Fehlerprüfung, ob eine gewählte
  Vokabel überhaupt in den Übungstexten vorkommt – Friederike schreibt
  beides selbst, das ist bewusst ihre eigene Verantwortung (z. B. exakte
  Wortform muss zur Vokabel passen, kein Abgleich über Wortstämme/
  Flexionsformen).

### Testergebnisse (Playwright, echter Friederike-Token, Testdaten danach entfernt)

- Liste mit 3 Vokabelpaaren + zwei Übungstexten angelegt: ✅
- Übung zeigt "Aufgabe 1 von 3", korrekten Prompt (Vokabel + Übersetzung): ✅
- Falscher Klick zeigt Fehlermeldung, keine Aufgaben-Blockade: ✅
- Alle 3 Aufgaben korrekt gelöst → "🎉 Geschafft"-Bildschirm: ✅
- **Im eigenen Testlauf bemerkt**: ein Wort in meinem eigenen Testtext
  stand in einer anderen grammatikalischen Form ("Hauses" statt "Haus")
  als die eingetragene Vokabel – genau der oben beschriebene, bewusst
  nicht abgefangene Grenzfall, kein App-Fehler, nur mein eigener
  Test-Text musste korrigiert werden.

### Auslieferungspaket

`deploy/portal-v59.tar.gz` – nur `portal` neu gebaut/gestartet.

---

## 2026-07-29 – Tierbaukasten: Mensch-Figur per DiceBear/Avataaars (portal-v60)

Direktes Feedback von Andi (im Gespräch, nicht über die Werkstatt-App):
Friederike (11) fand den Tierbaukasten "wie eine Strichzeichnung aus dem
Kindergarten" – gewünscht war ein "Memoji-artiger" Baukasten, evtl.
orientiert an Mario Kart. Vorschlag: eine fertige Bibliothek nutzen statt
alles selbst zu zeichnen, falls es sowas gibt.

### Recherche

- Memoji (Apple) und Mario-Kart-Assets (Nintendo) sind proprietär, nicht
  nutzbar.
- Für **Menschen** gibt es eine ausgezeichnete freie Alternative:
  **DiceBear** (MIT-Engine) mit dem Stil **Avataaars** von Pablo Stanley
  ("Free for personal and commercial use", avataaars.com) – genau der
  gesuchte "Memoji-artige" Look: Frisur, Hautton, Augen, Mund, Bart,
  Kleidung, Accessoires als echte Bausteine.
- Für **Tiere** gibt es kein Äquivalent. Einzig gefundenes Tier-Avatar-Tool
  (`animal-avatar-generator`) erzeugt nur zufällige Avatare aus einem
  Text-Seed (wie ein Identicon), keine gezielte Bauteil-Auswahl.
- Wichtig für die Selbst-Hosting-Anforderung: der `dicebear`-Python-Wrapper
  auf PyPI (von jvherck) ruft nur die öffentliche `api.dicebear.com`-API
  auf – **nicht verwendet**. Stattdessen die offiziellen Pakete
  `dicebear-core` + `dicebear-styles` (dicebear/dicebear-Monorepo,
  `src/python`), die komplett lokal/offline rendern, keine Netzwerkanfrage
  zur Laufzeit. Vorab lokal mit einer Test-venv verifiziert (Rendering,
  Optionsschema, Lizenz) – siehe "Design-Entscheidungen".

Rückfrage an Andi vor der Umsetzung: Menschen mit DiceBear + Tiere weiter
handgezeichnet (aber detaillierter) statt der Tier-Option ganz zu
streichen oder nach vorgefertigten Icon-Sets zu suchen – bestätigt.
Avataaars als Stil bestätigt (statt "Adventurer").

### Design-Entscheidungen

- Neue Abhängigkeit `dicebear-core`+`dicebear-styles` (requirements.txt).
  Rendering läuft **serverseitig** in Flask (`_mensch_svg_rendern()` in
  `15_tierbaukasten.py`), da DiceBear keine im Projekt bereits gebündelte
  JS-Variante hat – der Vorschau-Mechanismus für die Mensch-Figur ist
  deshalb bewusst anders als bei Tieren: ein kleiner Server-Roundtrip pro
  Änderung (`POST .../vorschau-mensch`, JSON mit fertigem SVG), statt der
  rein clientseitigen CSS-Variablen-Logik der Tiere. Auch gibt es für
  Menschen keine Seiten-/Rückansicht (Avataaars liefert nur eine
  Frontalansicht) – ehrlich so kommuniziert, keine vorgetäuschte Funktion.
- Alle Avataaars-Auswahlwerte (Hautfarbe, Frisur, Haarfarbe, Augen,
  Augenbrauen, Mund, Bart, Kleidung+Farbe, Accessoire+Farbe) landen
  gesammelt als JSON in einer einzigen neuen Spalte
  `tierbaukasten_kreationen.dicebear_optionen`, statt das Tier-Schema
  (koerper_farbe/muster/accessoire/koerperbau) mit fachfremden Feldern zu
  überladen – `tier_typ='mensch'` bleibt weiterhin kein eigenes
  Kategorie-Feld.
  Farben sind als anklickbare Schwatch-Kreise (DiceBear akzeptiert nur
  seine feste Farbpalette, kein freier Hex-Farbwähler wie bei Tieren)
  umgesetzt, Frisur/Augen/Augenbrauen/Mund als `<select>`-Dropdowns
  (12-32 Werte je Kategorie), Bart/Kleidung/Accessoire als Chips.
  Bart/Accessoire nutzen `facialHairProbability`/`accessoriesProbability`
  auf 0, um "Keins" deterministisch abzubilden – Avataaars kennt dafür
  keinen eigenen Aufzählungswert.
- Die komplette Mensch-Verdrahtung im handgezeichneten Tier-SVG
  (`koerper_vorne('mensch')`, `koerper_seite('mensch')`,
  `clip-mensch`/`clip-seite-mensch`, die `vorne-mensch`/`hinten-mensch`/
  `seite-mensch`-Gruppen) wurde ersatzlos entfernt, da sie durch DiceBear
  überflüssig geworden ist – kein toter Code liegen gelassen.
- Galerie: für `tier_typ='mensch'` wird das serverseitig aus den
  gespeicherten `dicebear_optionen` gerenderte SVG direkt eingebettet
  (`| safe`), für Tiere weiterhin die Jinja-Macro-Vorschau.

### Testergebnisse (Playwright, echter Friederike-Token, Testdaten danach entfernt)

- Lokale Testinstallation (`dicebear-core`+`dicebear-styles` in einer
  Wegwerf-venv) vor dem Einbau verifiziert: Rendering funktioniert exakt
  wie erwartet, keine Netzwerkanfrage nötig, Lizenz passt (Screenshot
  eines Testrenders geprüft, sah spürbar "Memoji-artiger" aus als die
  Tiere).
- Assistent: Kategorie "Mensch" überspringt weiterhin Schritt 2, zeigt
  korrekt Mensch-Vorschau/-Anpassung statt der Tier-Bereiche: ✅
- Live-Vorschau reagiert korrekt auf Frisur-, Hautfarbe-, Bart- und
  Accessoire-Änderungen (Server-Roundtrip), Screenshot bestätigt
  gewählte Kombination (große Locken, dunkler Hautton, Bart, runde
  Brille): ✅
- Speichern + Galerie zeigt exakt dieselbe Figur wie zuletzt in der
  Vorschau: ✅
- Regressionstest Tier-Pfad (Körperbau-Skalierung, Muster in allen drei
  Ansichten, Mehrfach-Accessoires) nach dem Umbau erneut erfolgreich: ✅
- Andis vier bereits gespeicherte Tiere rendern nach dem Update weiterhin
  fehlerfrei.

### Auslieferungspaket

`deploy/portal-v60.tar.gz` – `portal` neu gebaut (neue Python-
Abhängigkeiten `dicebear-core`/`dicebear-styles`, saubere Installation
auch im Linux-Image bestätigt).
