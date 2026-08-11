# journal.md – Bau-Journal

---

## 2026-08-11 – portal-v200: Wünsche #204, #207, #205 – drei Befunde, eine Auslieferung

Zweiter Block aus dem eigenen Sicherheitsaudit vom 11.08. Alle drei hängen
zusammen: #204 und #205 sind beide unauthentifizierte, öffentlich erreichbare
Schreib-/Log-Endpunkte, #207 (Ratenbegrenzung) ist die gemeinsame Ergänzung
für beide - deshalb in einem Paket.

### #204 – POST /wunsch verlangt jetzt eine erkennbare Identität

Ein fehlendes oder ungültiges Token führte bisher NICHT zu 403, sondern zu
einem anonym gespeicherten Wunsch (`user_id NULL`) – bewusst so gebaut ("ein
anonymer Wunsch ist besser als ein verlorener"), aber ohne jede Prüfung, ob
der Aufrufer überhaupt schon einmal irgendeine App geöffnet hat. Erreichbar
war die Route ohne jede Anmeldung: `/` liefert öffentlich (Status 200)
`denied.html` aus.

Jetzt: ohne Token UND ohne Sitzungs-Cookie → 403, nichts wird gespeichert.
Für die eigentliche Zielgruppe ändert sich nichts – wer die ✨-Schaltfläche
überhaupt sieht, hat grant() für irgendeine App bereits durchlaufen und damit
spätestens seit Wunsch #140 (Stufe 1) ein Sitzungs-Cookie. Nebeneffekt, der im
Code jetzt auch so benannt ist: eine echte Anonymität (`user_id NULL`) gibt es
seither gar nicht mehr – jeder gespeicherte Wunsch hat einen Urheber.

**Ein bestehender Test testete plötzlich das Falsche.**
`test_anonymer_wunsch_bekommt_keine_prioritaet` schickte bewusst `token=None`
und erwartete: gespeichert, nur ohne Priorität. Das ist jetzt der Fall, den es
nicht mehr geben soll – umbenannt und umgeschrieben auf die neue Erwartung
(403, nichts gespeichert). Die Umbenennung sagt sofort, warum sich der Test
geändert hat, nicht nur, dass er es tat.

### #207 – ein gemeinsamer Rate-Limiter, gezielt eingesetzt

`rate_ueberschritten()` in `00_kern.py`: gleitendes Fenster im Speicher, kein
externer Dienst (ein Worker, siehe server.md). Bewusst NICHT global
angewendet – eine pauschale Bremse hätte die Offline-Warteschlange der
Einkaufsliste treffen können, die POSTs stundenlang aufhebt und dann in einer
Salve nachspielt (dieselbe Überlegung wie beim CSRF-Riegel). Eingesetzt nur an
den zwei konkret betroffenen, unauthentifizierten Routen: `/wunsch`
(8/Minute) und `/csp-bericht` (30/Minute – großzügiger, weil eine Seite mit
mehreren blockierten Ressourcen mehrere ECHTE Meldungen auf einmal schickt).

**Die Falle beim "je Adresse":** portal hängt nur im internen Bridge-Netz,
jede Anfrage kommt technisch von Caddys eigener Bridge-IP. Ohne
`X-Forwarded-For` auszuwerten, wäre die Bremse "je Adresse" in Wahrheit
"insgesamt" gewesen – ein einzelner Angreifer hätte das Kontingent der ganzen
Familie mitverbraucht. `client_ip()` liest den Header, mit derselben
Begründung wie `X-Forwarded-Proto` im CSRF-Riegel (Caddy ist der einzig
mögliche Absender).

**Geteilter Zustand über die ganze Testsitzung hinweg** – der eigentliche
Stolperstein beim Bauen. `_RATE_TREFFER` ist ein Modul-Dict; ohne Reset hätte
das Kontingent für die ersten paar hundert Tests, die `/wunsch` oder
`/csp-bericht` aufrufen, für ALLE späteren Tests im selben Lauf schon
verbraucht ausgesehen – vier Tests in bestehenden Dateien scheiterten genau
so, bevor eine autouse-Fixture in `conftest.py` das Kontingent vor jedem Test
zurücksetzt (dieselbe Lehre wie bei der Datenbank, die `db` aus demselben
Grund vor jedem Test leert).

### #205 – keine gefälschten Log-Zeilen mehr

`/csp-bericht` ist absichtlich unauthentifiziert (Browser-Meldungen tragen
weder Cookie noch Origin) – das bleibt so. Die drei gemeldeten Felder wurden
bisher nur auf Länge gekürzt, nicht auf Steuerzeichen geprüft, bevor sie in
eine Log-Zeile geschrieben wurden. Ein eingebetteter Zeilenumbruch konnte
damit eine zusätzliche, frei erfundene Zeile einschleusen, die wie eine ECHTE
Meldung aussieht – z. B. eine gefälschte `CSRF-Verdacht:`-Zeile.
`_log_sicher()` ersetzt Steuerzeichen jetzt durch ein Leerzeichen.

**Getestet wurde der Log-Handler, nicht die Funktion isoliert** – ein Test,
der nur `_log_sicher()` direkt aufruft, wäre grün geblieben, selbst wenn der
Aufruf in `bericht()` sie vergessen hätte. Die Tests hören stattdessen den
echten Logger ab und prüfen die tatsächlich geschriebene Zeile.

### 15 Injektionen über drei Befunde, alle rot

Darunter zwei, die beim ersten Durchlauf tatsächlich grün blieben und
korrigiert werden mussten – nicht bei diesem Befund, sondern als
Bestandsaufnahme: kein einziger der neuen Tests blieb am Ende unentdeckt
blind.

### Live geprüft, mit Wegwerf-Daten

Ohne Identität → 403, nichts gespeichert. Mit echter Sitzung → 200,
gespeichert und wieder gelöscht. Eine `/csp-bericht`-Meldung mit
eingebettetem `CSRF-Verdacht:`-Zeilenumbruch → im echten Container-Log landet
alles in EINER Zeile, keine gefälschte zweite. 1204 Tests grün.

---

## 2026-08-11 – portal-v198: Wunsch #203 – SSRF über Web-Push geschlossen

Erster von sechs Befunden aus dem eigenen Sicherheitsaudit vom 11.08. (#203-208,
alle priorisiert). `POST /push/subscribe` übernahm `subscription.endpoint`
ungeprüft aus dem JSON-Body; `push_send()` ruft später `pywebpush.webpush()`
mit genau dieser Adresse auf – ein serverseitiger POST an eine Adresse, die
vollständig vom Client vorgegeben war. Dieselbe Fehlerklasse wie Wunsch #127
(Rezept-Import), nur an einer zweiten Stelle, die die dortige Prüfung nie
durchlief.

### Die Prüfung ist umgezogen, nicht verdoppelt

`_ist_oeffentliche_url()`/`_ip_ist_oeffentlich()` standen bisher nur in
`11_rezepte.py`. Eine zweite, eigene Kopie in `07_push.py` hätte irgendwann
auseinanderlaufen können – stattdessen liegen beide jetzt (ohne führenden
Unterstrich, weil jetzt öffentlich genutzt) in `00_kern.py` als
`ist_oeffentliche_url()`/`ip_ist_oeffentlich()`. `11_rezepte.py` importiert sie
unter dem alten Namen zurück – an der Datei selbst ändert sich sonst nichts.

### Eine ehrliche Lücke bleibt

Der Rezept-Import pinnt zusätzlich die IP-Adresse der eigentlichen Verbindung
gegen DNS-Rebinding (Wunsch #127, zweite Lücke). Das lässt sich hier nicht
übernehmen: Push-Zustellungen laufen über `pywebpush`, das die Adresse selbst
zum Zeitpunkt des Versands auflöst – ein Pinning würde ein Nachbauen der
gesamten HTTP-Schicht von `pywebpush` bedeuten. Die Prüfung beim Registrieren
schließt trotzdem den eigentlichen Weg: Eine interne Adresse kommt gar nicht
erst in die Datenbank. Das steht als Kommentar im Code, damit es niemand für
vollständig geschlossen hält.

### Zehn Tests, drei bewusste Fehler

Multicast-Adressen sind in Pythons `ipaddress`-Modul `is_global=True`
(nachgemessen: `224.0.0.1` UND `ff05::1`) – ohne den zusätzlichen
`is_multicast`-Ausschluss kämen sie durch. Ein erster Testlauf ließ genau
diesen Fehler grün durch, weil kein Test ihn gezielt prüfte; nachgetragen.
Alle drei Injektionen (Prüfung im Endpunkt entfernt, Multicast durchgelassen,
Schema-Prüfung entfernt) schlagen jetzt an.

### Live geprüft, mit Wegwerf-Daten

Zwei Registrierungsversuche über die echte Herkunfts-Prüfung (Origin-Header,
wie im CSRF-Riegel verlangt): `http://172.30.0.10:2020/...` → 400, verworfen;
`https://fcm.googleapis.com/...` (echte DNS-Auflösung) → 200, gespeichert und
danach wieder gelöscht. 1186 Tests grün.

---

## 2026-08-11 – portal-v197: Wünsche #200, #197, #198, #199

Vier Meldungen aus einer Nacht, alle Vokabeln – und nur **zwei** Ursachen.

### #200 – der Sprach-Chip tat gar nichts

> „Beim Vokabeln eintragen kann ich nicht mehr auf Englisch umschalten"

Der Verteiler in `base.html` ruft `fn.apply(el, args.concat([el, ereignis]))`:
**erst die Werte aus `data-args`, dann das Element.** Der Chip trug
`data-args='["neu"]'`, die Funktion hiess `spracheWaehlen(btn, gruppe)`. Damit
landete der String `"neu"` in `btn` und das Element in `gruppe`, und die erste
Zeile warf `gruppe.split is not a function`.

**Der Fehler war älter als die Meldung.** Das Formular wählt die zuletzt
benutzte Sprache selbst vor – über einen direkten Aufruf, der die richtige
Reihenfolge hatte. Wer immer dieselbe Sprache nahm, brauchte den Chip nie.
Erst als mit #195 die Voreinstellung eine andere wurde (Dänisch steht
alphabetisch vorn), wurde das Umschalten nötig – und ging nicht.

Das ist die unangenehme Sorte Fehler: nicht neu eingebaut, sondern durch eine
harmlose Änderung *erreichbar* geworden.

Der neue Wächter prüft die Klasse, nicht den Einzelfall: Wird eine Funktion
mit `data-args` aufgerufen, darf ihr erster Parameter kein Element sein –
erkennbar an `.classList`, `.dataset`, `.closest()`, `.value`. Ein Name oder
eine Zahl aus `data-args` hat das alles nicht.

### #197, #198, #199 – eine Ursache, drei Blickwinkel

> „Da ist kein Abstand zwischen der Sprachwahl und den Abfragemodi."
> „Da ist kein Abstand zwischen der Kapitelwahl und dem Abfragemodus."
> „Bei Dänisch ist der Abfragemodus für Englisch noch sichtbar."

`hidden` setzt in der Standardformatierung des Browsers `display:none` – und
**eine Klassenregel mit eigenem `display` schlägt das mühelos**:

| Element | Regel | `hidden` wirkt? |
|---|---|---|
| Überschrift | `.form-label` (kein `display`) | ja, verschwindet |
| Hinweis | `.verb-hinweis` (kein `display`) | ja |
| Auswahlliste | `.verb-liste { display:flex }` | **nein** |
| Foto-Schalter | `.verb-schalter { display:flex }` | **nein** |

Bei Dänisch verschwanden also Überschrift und Hinweis, die Liste blieb – eine
Auswahl ohne Titel, direkt an der Kapitelwahl klebend. „Kein Abstand" und
„noch sichtbar" sind derselbe Fehler von zwei Seiten.

**Dieselbe Spezifitätsfalle wie bei der Schriftgröße in #170**, und dieselbe
Lehre: Die Lösung gehört nach `base.html` und gilt portalweit —
`[hidden] { display: none !important; }`. Die Einzelregel, die ich bei #195
in `vokabeln.html` geschrieben hatte, ist damit weg; ein Wächter verlangt,
dass keine Vorlage `[hidden]` selbst regelt.

Dazu der Abstand, den Andi zweimal angemahnt hat: Die Verbauswahl ist keine
weitere Zeile wie „Sprache" oder „Kapitel" – sie schaltet den ganzen
Trainingsmodus um. Sie bekommt jetzt eine Trennlinie und mehr Luft, ebenso
der Schalter im Foto-Import.

### Zehn Injektionen, zehn rot

Darunter die beiden, die man beim Reparieren übersieht: die Signatur drehen
und den direkten Aufruf vergessen – und `!important` weglassen, was genau den
Ausgangszustand wiederherstellt.

1176 Tests grün.

---

## 2026-08-10 – portal-v194/v195: Wünsche #196 und #195

### #196 – nach unten ziehen lädt neu

> „Nach unten ziehen der Seite soll die Daten der aktuellen Seite neu laden,
> ohne den Fokus zu verlieren."

Vier Zeilen CSS, ein Skriptblock in `base.html`, damit sofort in allen 19
Apps.

**Ein echtes Neuladen, kein Nachladen per fetch.** Das wäre die elegantere
Lösung gewesen und die falsche: Jede App bringt eigene Skripte mit, die beim
Laden ihre Listener setzen – Suchfelder, Filter, Sortierung. Tauschte man nur
das `<main>` aus, wären die danach still tot. In 19 Apps, ohne dass irgendwo
etwas rot wird.

**„Ohne den Fokus zu verlieren"** heisst hier: die Blätterstelle bleibt. Sie
wird vor dem Neuladen weggeschrieben und danach wiederhergestellt – und der
Merker sofort gelöscht, sonst spränge auch der nächste normale Aufruf an
dieselbe Stelle. Der Tastaturfokus in einem Eingabefeld überlebt ein
Neuladen prinzipbedingt nicht; das ginge nur über den fetch-Weg oben.

`overscroll-behavior-y: contain` schaltet die browsereigene Geste ab. Sonst
gäbe es im Browser zwei übereinander – und in der installierten PWA, wo der
Anlass liegt, gar keine.

**Was ich nicht prüfen konnte: die Geste selbst.** Dafür braucht es einen
Finger auf einem Touchgerät. Geprüft ist, dass die Bausteine überall
ankommen und die Regeln stimmen, die man beim Nachbauen falsch macht.

### #195 – Verbfelder nur dort, wo es sie gibt

> „Unregelmäßige Verben gibt es nur im englischen (afaik), dann könnte man
> den Teil doch in anderen Sprachen ausblenden oder sogar in Englisch
> einklappen."

Beides gemacht: ausblenden bei anderen Sprachen, einklappen bei Englisch.
An drei Stellen – Vokabelformular, Lernseite, Foto-Import.

**Das Ausblenden im Browser ist Bequemlichkeit, keine Regel.** Ein POST mit
`simple_past` an einer lateinischen Vokabel wird auf dem Server verworfen –
sonst hätte eine lateinische Vokabel ein „simple past", sobald jemand eine
alte Seite im Speicher hat. Dasselbe beim Sprachwechsel im Bearbeiten-
Formular: Die Formen gehörten zur alten Sprache und gehen mit.

**Versteckte Häkchen werden entfernt, nicht nur unsichtbar gemacht.** Ein
gesetztes, unsichtbares `verb_formen` würde beim Absenden mitgeschickt – das
Training liefe im Verbmodus, und niemand sähe warum.

**Eine Annahme von mir war falsch.** Im Kommentar stand „es gibt heute genau
zwei Sprachen". Live sind es **fünf**: Englisch, Latein, Dänisch,
Italienisch, Französisch. Bei vieren davon sind die Felder jetzt weg – und
weil Dänisch alphabetisch vorn steht, ist die Voreinstellung im Formular
eine Sprache *ohne* Verbfelder. Der Wunsch wirkt also deutlich stärker als
ich beim Bauen dachte. Kommentar korrigiert.

### Zwei Wächter waren blind – einer seit Monaten

- **`test_ziehen_neuladen`**: Mein Test auf `overscroll-behavior-y` fand die
  Zeichenkette auch in meinem eigenen Erklärkommentar darüber. Prüft jetzt
  die CSS-Regel.
- **`test_kopfleiste`**: `test_kein_knopf_zwischen_header_und_main` hat
  **nie etwas geprüft**, seit die Kopfzeile nur noch in `base.html` steht:
  Die Vorlagen haben `<main`, aber kein `</header>`; `base.html` umgekehrt.
  Der Test kehrte immer sofort zurück. Aufgefallen erst, als eine absichtlich
  eingebaute Verletzung grün blieb. Er prüft jetzt den Bereich zwischen
  `{% block body %}` und `<main>` – in der heutigen Struktur dieselbe
  Aussage.

Ausserdem hat zum **vierten Mal** ein Erklärkommentar von mir einen Wächter
ausgelöst (`<main>` im JS-Kommentar). Diesmal habe ich den Wächter
abgedichtet statt den Kommentar umzuschreiben.

26 Injektionen über beide Wünsche, alle rot. 1119 Tests grün.

---

## 2026-08-10 – portal-v192: Wunsch #194 – unregelmäßige Verben

> „Es soll einen Spezialmodus geben für unregelmäßige Verben im Englischen:
> Infinitiv, simple past, Perfect und Deutsch. Beim Lernen soll man auswählen
> können, welche Kombinationen man lernen will. Der Bildupload für neue
> unregelmäßige Verben soll auch möglich sein."

Ausser der Reihe gebaut, auf Zuruf.

### Zwei Spalten statt einer eigenen Tabelle

`vokabeln.simple_past` und `vokabeln.perfect`, beide optional. Ein Eintrag
**ist** ein unregelmäßiges Verb, wenn beide gefüllt sind; `fremd` trägt dann
den Infinitiv.

Eine eigene Verbtabelle wäre die naheliegende Modellierung gewesen und die
teurere: Kapitel, Freigaben (#150), Sessions, Versuche, Aussprache und
Statistik hängen alle an `vokabeln` – das hätte sich alles verdoppelt.

**Kein Typ-Merker.** Eine Spalte „ist_verb" wäre eine zweite Wahrheit neben
den Feldern und könnte von ihnen abweichen. Stattdessen gilt: **beide Formen
oder keine.** Ein halb ausgefülltes Paar wird verworfen – beim Anlegen, beim
Bearbeiten und beim Foto-Import. Sonst gäbe es Einträge, die als Verb gelten
und im Training eine leere Antwort erwarten.

### Die Kombinationen sind der Modus

Sechs Abfrageformen zur Auswahl. Mindestens ein Kreuz schaltet das Training
auf Verben um – **es braucht deshalb keinen zusätzlichen Hauptschalter**, der
dieselbe Aussage ein zweites Mal trifft. Ohne Kreuz bleibt alles wie bisher.

Mehrere Kreuze heissen: jedes Verb mehrfach, aus jeder gewählten Richtung.
Genau das ist der Sinn der Auswahl.

### Der Trainer kann jetzt mehrere Felder

Bisher: ein Eingabefeld, Richtung gewürfelt. Jetzt bringt jede Aufgabe ihre
Felder selbst mit. `felderBauen()` vereinheitlicht beide Fälle – danach hat
jede Aufgabe eine Liste erwarteter Antworten, und die Prüfung kennt nur noch
diesen einen Fall. Ohne diese Vereinheitlichung stünden zwei Prüfpfade
nebeneinander, von denen einer irgendwann vergessen wird.

**Nur ganz richtig zählt.** Wer zwei von drei Formen kann, kann das Verb noch
nicht – es geht zurück in die Warteschlange. Falsche Felder bekommen ihre
Lösung einzeln darunter.

Der Fortschritt zählt **verschiedene Vokabeln**, nicht Aufgaben: Bei zwei
angekreuzten Richtungen stünde sonst „0 von 20", obwohl es zehn Verben sind.

### Zwei bestehende Wächter haben mich korrigiert

- **`test_emoji`**: 🔤 hatte keine lokale Twemoji-Grafik und wäre unter
  Linux/Chrome leer geblieben. Nachgeholt.
- **`test_tippflaeche`**: Meine Klasse `.verb-feldlabel` enthielt „feld" und
  wurde als Eingabefeld unter 16px gemeldet. Der Wächter hatte recht in der
  Sache – die Klasse *heisst* wie ein Feld, ist aber die Beschriftung
  darüber. Umbenannt in `.verb-formlabel`.

### 16 Fehler eingebaut, 15 rot – und der eine grüne war lehrreich

Blind waren drei Tests: Der Filter für unbekannte Abfrageformen wurde nur
über `verb_aufgaben` geprüft, das ein zweites Mal siebt; die Formenzeile in
der Liste wurde am Wort statt am Element gesucht (die Wörter stehen auch im
Bearbeiten-Formular); und die beiden neuen Formularfelder wurden nie
angesehen, weil der Test seinen POST selbst schickt.

Der 16. blieb grün und **das ist richtig so**: Den SQL-Filter zu entfernen
ändert nichts Beobachtbares, weil `verb_aufgaben()` Nicht-Verben ohnehin
überspringt. Er ist eine Abkürzung, keine Sicherung – das steht jetzt als
Kommentar daneben, damit ihn niemand für eine hält.

### Live geprüft, mit Wegwerf-Daten

Drei Einträge unter eigener Marke angelegt, geprüft, gelöscht: 2 Formenzeilen
in der Liste (die normale Vokabel hat keine), 4 Aufgaben aus 2 Verben × 2
Richtungen, Feldbeschriftungen Infinitiv/simple past/Perfect, keine normale
Vokabel im Verbtraining – und ohne Kreuz umgekehrt: normale Vokabel da, null
Verbaufgaben. Danach 0 Rückstände.

**Nebenbei gelernt:** Mein Live-Skript bekam auf jeden POST ein 403. Der
CSRF-Riegel (#140, Stufe 2) steht auf „scharf" und will eine eigene Herkunft
sehen – `live_pruefung.py` macht nur GETs und ist deshalb nie darüber
gestolpert.

1045 Tests grün.

---

## 2026-08-10 – portal-v190: Wunsch #188 – Tokenverbrauch am Wunsch

> „Die zusätzlich erhobenen Daten, wie der Tokenverbrauch geschätzt und/oder
> real sollen in den Details der Wünsche sichtbar sein."

Der Wunsch lag zwei Läufe lang liegen, weil er von Daten sprach, die es nicht
gab: Je Wunsch misst das Portal nur die KI-Überschrift (160–320 Tokens), und
die war offensichtlich nicht gemeint. Rückfrage am Wunsch, Andis Antwort:

> „Ok, dann sollte nur der Tokenverbrauch nach der Umsetzung dokumentiert
> sein"

Damit fällt die Hälfte des ursprünglichen Wortlauts weg – kein „geschätzt",
kein Wert vorab. Genau deshalb war die Rückfrage richtig: Geraten hätte ich
vermutlich beides gebaut, und die Vorab-Schätzung wäre eine Zahl gewesen, die
niemand braucht und die dauerhaft danebenliegt.

### Eine Spalte, ein Argument, eine Zeile

`wuensche.tokens` (INTEGER, NULL), gesetzt als drittes Argument von
`manage.py wunsch_erledigt <id> "<umsetzung>" <tokens>`, angezeigt in der
Detailansicht.

**NULL heisst „nicht erfasst", 0 heisst null.** Der Unterschied ist der
ganze Punkt: An ~190 Wünschen von vor heute gibt es keine Zahl, und dort
bleibt die Zeile weg. Hätte ich `{% if w.tokens %}` geschrieben, wäre eine
echte 0 (etwa bei einer reinen Doku-Änderung) wie „nicht erfasst" behandelt
worden – ein eigener Test hält beides auseinander.

**COALESCE beim Schreiben:** Wer einen Wunsch später noch einmal abhakt, um
die Umsetzung zu ergänzen, soll die Zahl nicht verlieren.

**Unsinn bricht ab, statt still zu verschwinden.** „vielleicht 35k" als
`tokens` würde sonst als „nicht erfasst" durchgehen, und niemand wüsste
warum. Tausenderpunkte sind dagegen erlaubt – „35.000" ist die Schreibweise,
in der die Zahl im Bericht steht.

Zehn Injektionen, zehn Treffer.

### Ehrlich zur Herkunft der Zahl

Das Portal misst sie nicht. Sie kommt von mir, nach getaner Arbeit, und ist
gut begründet, aber keine Messung. Die Hilfe sagt das so.

**Dieser Wunsch ist der erste mit einer Zahl** – 38.000 Tokens.

---

## 2026-08-10 – portal-v189: Wunsch #189 – handball.net-Relaunch, und was daraus folgt

> „Es soll geprüft werden, was sich aus dieser Newsinfo von Handball.net
> ableiten lässt und welche Aufgaben zur Anpassung der TVB App entstehen.
> Alle Anpassungen sollen als unpriorisierte Wünsche in der Werkstatt landen."

### Zuerst gemessen, dann abgeleitet

Die Ankündigung ist vage („Mitte August", „neues Design und zahlreiche neue
Funktionen", Grundlage Handball360). Bevor ich daraus Aufgaben ableite, habe
ich den Ist-Zustand geprüft – **alle vier Datenquellen der App sind heute
intakt**:

| Quelle | Art | Stand 10.08. |
|---|---|---|
| `/a/sportdata/1/widgets/…` | undokumentiertes JSON | antwortet vollständig |
| Vereinsseite (HTML) | Auslesen über CSS-Klassen | 18 Mannschaften, erneuert 09.08. |
| Mannschafts-Tabellenseite (HTML) | Auslesen der Liga-ID | trägt |
| `hpi.handball-bundesliga.de` | undokumentiertes JSON | antwortet |

**Mein erster Probelauf war falsch gebaut** und meldete alle vier als leer:
Ich habe auf einen `data`-Schlüssel geprüft, den die Antworten gar nicht
haben. Beinahe hätte ich einen Ausfall gemeldet, den es nicht gibt. Erst der
Blick in die Rohantwort zeigte: `table` steht auf 18 Mannschaften mit 0:0 –
die Saison hat schlicht noch nicht begonnen.

### Vier Wünsche, unpriorisiert

- **#190** – Das Veralten der Mannschaftsliste sichtbar machen. Das ist die
  brüchigste Stelle: Die Regex hängt an CSS-Klassennamen (`list-item-title`),
  und „neues Design" heisst neues Markup. Heute fängt der Code den Ausfall ab
  und lässt den alten Stand stehen – richtig, aber völlig still.
- **#191** – Nach dem Relaunch alle vier Quellen nachprüfen; dabei die Frage,
  ob Handball360 die heute **zwei getrennten Vereinsobjekte** zusammenführt.
- **#192** – Spielerstatistiken direkt statt über die HPI-Umleitung (die nur
  Spieler mit Einsatz kennt, nur die 1. Bundesliga, und 400 KB für 22 Spieler
  lädt).
- **#193** – Mannschaftsliste per API statt HTML.

**Bewusst nicht eingetragen:** Live-Ticker. Die Ankündigung nennt sie, aber
als Bestand, nicht als Neuerung.

### Ein neuer Weg, der vorher fehlte

Wünsche liessen sich nur über die Weboberfläche anlegen – von hier aus gar
nicht. Also `manage.py wunsch_neu <app> "<titel>" "<text>"`, Geschwister von
`wunsch_aktion` aus der letzten Sitzung.

**Der Befehl kann keine Priorität setzen, und zwar bewusst ohne Schalter
dafür.** Der stündliche Lauf (#157) arbeitet alles ab, was eine Priorität
ausser `zurueckgestellt` trägt. Ein Befehl, der Wünsche anlegen *und*
priorisieren könnte, wäre eine Maschine, die sich selbst Arbeit aufträgt und
sie eine Stunde später ausführt. Zwei Tests wachen darüber: einer über das
Ergebnis, einer über die Quelle.

### Ein Test war ein Blindgänger

Meine erste Fassung von „es gibt keinen Weg, doch zu priorisieren" enthielt
ein `pytest.raises(SystemExit)` um ein `raise SystemExit` herum, das der Test
selbst auslöste – grün, egal was `manage.py` tut. Ersetzt durch eine Prüfung
der zusammengesetzten SQL-Anweisung. Acht Injektionen, acht Treffer.

Keine Hilfe-Änderung: `wunsch_neu` ist Werkzeug für mich, keine Funktion für
die Familie.

---

## 2026-08-10 – portal-v187: Der Verlauf war unsichtbar, und meine Rückfrage stand am falschen Ort

> „Die Rückfragen sollen doch als Aktion am Wunsch sichtbar dokumentiert sein.
> Ich sehe die Rückfrage aber nicht und ich kann auch nicht erkennen, ob es
> eine eingeklappte Aktion gibt, bis ich drauf klicke."

Zwei Fehler auf einmal, und der erste ist meiner.

### Mein Fehler: die Rückfrage stand nur im Chat

Wunsch #161 hat die Werkstatt zum Ticketsystem gemacht, damit genau das nicht
passiert: Plan, Rückfrage, Antwort und Umsetzung stehen **am Wunsch**, nicht
in einem Verlauf, den ausser mir niemand hat. Meine Rückfrage zu #188 habe
ich trotzdem nur im Chat gestellt – zweimal, in zwei Läufen.

Der Grund ist banal und deshalb wichtig: Es gab von der Kommandozeile aus
keinen Weg, eine Aktion einzutragen. Die Weboberfläche kann es, ich nicht.
Also `manage.py wunsch_aktion <id> <art> "<text>"`, mit derselben
Push-Benachrichtigung wie über die Oberfläche (#166) – eine Rückfrage, die
niemanden erreicht, ist so gut wie nicht gestellt.

Die Rückfrage zu #188 steht jetzt dort, wo sie hingehört, und hat einen Push
ausgelöst.

### Der Fehler im Portal: ein Verlauf, den man nur durch Antippen findet

Der Verlauf steckte vollständig in der aufklappbaren Detailansicht. Bei 190
Karten heisst „man kann nachsehen" praktisch „niemand sieht es". Jetzt trägt
die eingeklappte Karte ein Abzeichen:

| Zustand | Abzeichen |
|---|---|
| nichts im Verlauf | keins |
| Einträge vorhanden | `💬 3`, grau |
| Rückfrage wartet | `❓ Rückfrage offen`, orange |

Ein Abzeichen an *jeder* Karte wäre so nutzlos wie gar keins – deshalb bleibt
die Karte ohne Verlauf leer. Und die wartende Rückfrage ist kein Zählwert,
sondern eine Aufforderung; sie trägt als Einzige Farbe.

### Die Regel, die man leicht falsch baut

„Offen" ist eine Rückfrage, auf die **keine Antwort mehr folgt** – es zählt
die Reihenfolge, nicht die blosse Anwesenheit einer Antwort irgendwo im
Verlauf. Wer auf eine alte Frage geantwortet hat und danach eine neue stellt,
hat wieder eine offene. Und eine Notiz oder ein Plan beendet nichts: Sonst
gälte jede Frage als beantwortet, sobald irgendjemand irgendetwas
dazuschreibt.

Beide Fehlformen habe ich absichtlich eingebaut, beide werden rot. Sieben
Injektionen, sieben Treffer – darunter der Fall, der sonst unbemerkt bliebe:
das Abzeichen des falschen Wunsches auf allen Karten.

### Live geprüft

Alle 19 Seiten 200. Genau eine Karte zeigt „Rückfrage offen" (#188), 24
Wünsche tragen ein Abzeichen. 998 Tests grün.

**Live verändert:** ein echter Datensatz, absichtlich – die Rückfrage an
Wunsch #188. Das ist kein Testeintrag, sondern der eigentliche Zweck; sie
bleibt stehen.

---

## 2026-08-10 – portal-v184/v185: Wünsche #187 und #186

### #187 – keine Wunsch-Karte ohne Überschrift

Erst nachgezählt, dann gebaut. Von 187 Wünschen hatten **140 keine
Überschrift – und alle 140 sind älter als Wunsch #161**, der die KI-Über-
schrift eingeführt hat. Seit #162 hat ausnahmslos jeder Wunsch eine. Die
Vergabe war also nie kaputt; es war eine Lücke im Bestand.

Trotzdem ist „bekommt beim Anlegen eine Überschrift" **keine Zusage**: Der
Titel entsteht in einem Hintergrund-Thread, braucht ein bekanntes Konto
(anonyme Wünsche haben keins), ein Kontingent und eine erreichbare
Gegenstelle. Fällt davon etwas aus, stand die Karte bisher nackt da.

Zwei Teile:

**`ersatz_titel()`** leitet eine Überschrift aus dem ersten Satz ab –
bewusst als **Anzeigewert, nicht gespeichert**. Trägt die KI später doch
etwas nach, gewinnt es sofort; es gibt kein Provisorium in der Datenbank,
das jemand später für einen echten Titel hält. Blasser dargestellt, damit man
den abgeschnittenen Satz nicht für eine Formulierung hält.

**`manage.py titel_nachtragen`** holt echte KI-Titel für den Altbestand,
offene Wünsche zuerst. Ohne Zahl passiert nichts ausser Zählen: Der Befehl
kostet echte Tokens aus dem Kontingent des Urhebers, und einer, der beim
ersten Aufruf ein Drittel des Monatsbudgets verbraucht, wäre eine Falle.

Nachgetragen habe ich nur die **drei offenen** Alt-Wünsche (#51, #130, #139)
– 951 Tokens. Die restlichen 137 sind alle längst erledigt; ~34k Tokens für
Überschriften an Wünschen, die niemand mehr liest, ist Andis Entscheidung,
nicht meine.

**Ein Testfehler, der ein echter Entwurfsfehler war:** Die erste Fassung
trennte auch am Doppelpunkt. Aus „UI: Die Knöpfe hängen am Header" (so
beginnt Wunsch #155 wörtlich) wurde damit die Überschrift „UI" – schlechter
als gar keine. Wünsche fangen oft mit einer Einordnung an; die Aussage steht
dahinter.

### #186 – die Kopfzeile bleibt stehen

Zur Wahl standen ein „Nach oben"-Knopf und eine mitlaufende Leiste. Gewählt:
**sticky**. Ein Knopf unten rechts bringt einen nach oben – die Leiste hält
ausserdem ⌂, den Seitentitel und das ☰-Menü dauerhaft erreichbar, kostet
keinen zusätzlichen Tipp und zeigt nebenbei durchgehend, in welcher App man
ist. Ein schwebender Pfeil ist die Lösung aus der Zeit, als `position:
sticky` noch nicht überall trug.

Vier Zeilen in `base.html` – und damit sofort in allen 19 Apps.

**Der Teil, den man dabei übersieht: Sprungziele.** Die Werkstatt springt auf
`#wunsch-<id>` (#171), die Geburtstage auf `#gb-<id>`, die Hilfe auf ihre
Kapitel. Ohne `scroll-padding-top` landet jedes davon **unter** der stehenden
Leiste: Navigation erreichbar, Ziel unsichtbar. Ein eigener Test verlangt
deshalb nicht nur, dass der Abstand da ist, sondern dass er mindestens so
hoch ist wie der Kopf – ein zu kleiner Wert ist schlimmer als keiner, weil
es dann fast richtig aussieht.

`z-index: 100` liegt bewusst unter dem Hamburger-Overlay (200) und dem
✨-Dialog (300).

### Elf Fehler eingebaut, zwei Tests waren blind

- **„Schnitt mitten im Wort" blieb grün.** Der Test riet an konkreten
  Wortenden herum („endet nicht auf 'ab' oder 'dar'") statt die Eigenschaft
  zu prüfen: hinter dem behaltenen Stück muss im Original ein Leerzeichen
  stehen.
- **„Wunschtext verschwindet" blieb grün.** Der Satz steht auch in der
  aufklappbaren Detailansicht – gesucht wurde nur der Satz, nicht das
  Element.

Beide nachgeschärft, danach schlagen alle elf an.

### #188 nicht angefasst

„Die zusätzlich erhobenen Daten, wie der Tokenverbrauch geschätzt und/oder
real sollen in den Details der Wünsche sichtbar sein." Der Portal-Verbrauch
je Wunsch wäre die Titelgenerierung – 160 bis 320 Tokens, offensichtlich
nicht gemeint. Gemeint ist vermutlich der Aufwand der Umsetzung, und den
erhebt heute nichts: weder die Schätzung noch der tatsächliche Verbrauch
einer Arbeitssitzung liegen irgendwo. Rückfrage gestellt statt geraten.

### Live geprüft

Alle 19 Seiten 200. Werkstatt: 187 Karten, 187 Überschriften, 140 davon
abgeleitet, **keine ohne**. 985 Tests grün.

---

## 2026-08-10 – portal-v182: Wünsche #185 und #184 – Rezeptliste

Beide betreffen den Kopf derselben Seite, deshalb ein Paket – abgehakt wurde
jeder für sich.

### Vorher: fünf Tests waren über Nacht rot geworden

Ohne dass jemand etwas geändert hätte. `test_essensplan_gekocht.py` legte
seine Planeinträge auf die festen Tage 05./06.08.2026. Der Essensplan zeigt
laufende plus kommende Woche – am 10.08. fiel der 05.08. aus dem Fenster, die
Einträge standen nicht mehr auf der Seite, fünf Prüfungen fanden nichts mehr.

Der Test wurde dabei nicht *falsch*, er prüfte **nichts mehr**. Das ist der
unangenehmere Fall: Zwischen dem 05.08. und heute hätte jede Regression im
Abhaken unbemerkt durchgehen können, solange die Assertions noch zufällig
zutrafen. Die Tage werden jetzt aus `heute_lokal()` gerechnet. Gegenprobe: ein
Datum weit ausserhalb des Fensters eingesetzt – genau diese fünf werden rot.

### #185 – drei Anlegewege in eine Zeile

„+ Neues Rezept", „🔗 Aus URL importieren" und „📷 Bild importieren" standen
als drei volle Blockzeilen übereinander, zusammen rund 130px, bevor das erste
Rezept kam.

Der Wunsch stellte frei, die beiden Importe hinter dem Neu-Knopf zu
verstecken. Dagegen entschieden: Das kostete einen zusätzlichen Tipp und
würde zwei bisher sichtbare Wege unsichtbar machen. Wer selten importiert,
findet den Weg dann gar nicht mehr – Platz gespart, Funktion verloren.
Stattdessen eine Flex-Zeile: der Hauptknopf `flex:1`, die beiden Importe
`flex:0 0 auto` mit kurzen Beschriftungen („🔗 URL", „📷 Bild"). Eine Zeile
statt drei, alles sichtbar, kein Zustand.

Die Knöpfe sind `<a>`, keine `<button>` – die globale 44px-Tippfläche aus
`base.html` (#169) greift bei ihnen **nicht**. `min-height:44px` steht
deshalb an der Klasse, und ein Test wacht darüber.

### #184 – das Symbol folgt der Kategorie

Kein neues Datenfeld nötig: `rezepte.kategorie` ist seit #55 genau `kochen`
oder `backen`. Es fehlte nur die Zuordnung – 🍳 bzw. 🍰, dieselben Zeichen wie
auf den Filter-Chips. Zwei verschiedene Symbole für dieselbe Sache müsste man
erst lernen; ein Test hält beide zusammen.

Ohne Kategorie bleibt der neutrale Topf 🍲. Bewusst nicht „im Zweifel
kochen": Dann sähe man der Liste nicht mehr an, wo die Einordnung fehlt.

**Der Essensplan zeigt dieselben Rezepte** und musste mit – sonst trüge
derselbe Kirschkuchen auf der einen Seite 🍰 und auf der anderen 🍲. Die
Zuordnung liegt in `11_rezepte.py`, `12_essensplan.py` importiert sie über
`teile.rezepte` (neuer Alias in `teile/__init__.py`, wie `teile.kern` und
`teile.todo`). Eine zweite Kopie wäre genau das Duplikat, das irgendwann
auseinanderläuft.

### Neun Fehler eingebaut, neun wurden rot

Diesmal ohne blinden Fleck – anders als gestern. Der Test, der am ehesten
selbstzufrieden geworden wäre, prüft nicht „steht 🍰 irgendwo auf der Seite"
(bei drei Rezepten stehen alle drei Zeichen dort), sondern sammelt die Paare
*(Symbol, Name)* ein und vergleicht die Zuordnung.

Ein eigener Test hält ausserdem fest, dass die **Kopfzeile** der App weiter
🍲 Rezepte heisst – das ist das Symbol der App, nicht das eines Rezepts. Ohne
diese Abgrenzung hätte ein späterer Aufräumer beides für denselben Fehler
gehalten.

### Live geprüft

Alle 19 Seiten 200. Die Rezeptliste zeigt echte Zahlen: 5 Rezepte mit 🍳,
4 mit 🍰, keines ohne Kategorie. Anlegezeile: drei Links in einer Zeile.
Im Essensplan steht in diesen zwei Wochen gerade kein Rezept, der Fall ist
dort nur durch den Test belegt. 921 Tests grün, keine echten Daten angefasst.

---

## 2026-08-09 – portal-v180/v181: Wunsch #183 – KI-Verbrauch und Guthaben sichtbar

> „Es soll eine Übersicht geben, in der man pro Benutzer die verbrauchten
> Token von OpenRouter sieht. Außerdem soll das Guthaben bei OpenRouter
> dargestellt werden. Fällt das Guthaben auf ein Euro oder niedriger, bekommt
> Andi eine Aufgabe eingestellt, damit er das Guthaben wieder auflädt. Die
> Aufgabe soll so eingestellt sein, dass eine Push-Benachrichtigung ausgelöst
> wird.“

Neues Modul `24_ki_budget.py`, Seite unter „Verwaltung › 🤖 KI-Verbrauch“.
Die Zahlen lagen seit #81 bzw. #136 in `ki_nutzung` und `ki_tts_nutzung` –
sichtbar waren sie nirgends.

### Zwei Dinge, die beide „Guthaben“ heißen

OpenRouter liefert sie an zwei Endpunkten, und sie sind nicht dasselbe:

| Endpunkt | Bedeutung | heute |
|---|---|---|
| `/api/v1/credits` | gekaufte Credits minus **Gesamt**verbrauch | 9,92 USD |
| `/api/v1/key` | Limit **dieses Schlüssels**, setzt sich monatlich zurück | 9,95 USD von 10 |

Ausschlaggebend ist der **kleinere** von beiden: Ist eines von beiden leer,
geht keine Anfrage mehr durch. Würde die Warnung nur aufs Konto-Guthaben
schauen, liefe ein aufgebrauchtes Monatslimit still in 402er-Fehler – mit
einem Konto, das laut Anzeige voll ist. Beide Werte stehen deshalb auf der
Seite, die große Zahl oben ist der kleinere.

### Euro steht im Wunsch, USD steht auf der Seite

OpenRouter rechnet in US-Dollar. Bei einer Schwelle von 1,00 ist der
Unterschied belanglos – aber eine Zahl, die anders heißt als sie ist, führt
irgendwann in die Irre. Die Schwelle ist deshalb `1.00 USD` und die Einheit
steht überall dran, auch in der Aufgabe und in der Push-Nachricht.

### Eine Aufgabe je Ebbe, nicht eine je Prüfung

Der Wächter läuft stündlich als Hintergrund-Thread (Muster wie die
Geburtstage in `23_geburtstage.py`, Schalter `KI_GUTHABEN_WACHT`). Ohne
Deduplizierung stünden nach einer Woche 168 gleichlautende Aufgaben in der
Liste – und die würde man sammelweise wegwischen, die 169. dann auch. Es
entsteht deshalb nur eine Aufgabe, solange keine offene dieser Art existiert;
nach dem Abhaken darf wieder gewarnt werden.

Ein Netzwerkfehler ist ausdrücklich **kein** Alarm: Antwortet OpenRouter
nicht, passiert nichts. Sonst stünde nach dem ersten Aussetzer eine Aufgabe
da, die nichts bedeutet – und die nächste echte würde geglaubt wie diese.

### Zehn Fehler eingebaut, zwei Tests waren blind

Nach der stehenden Regel jeden Wächter einmal absichtlich gebrochen. Acht
wurden sofort rot, zwei nicht:

- **`test_nur_admins`** prüfte mit dem *Home*-Token des Kindes. Das scheitert
  schon am fehlenden Grant – der `is_admin`-Zweig wurde nie erreicht. Ohne
  ihn blieb der Test grün. Jetzt bekommt das Kind im Test einen echten
  Admin-Grant und muss trotzdem 403 sehen.
- **`test_seite_zeigt_verbrauch_je_nutzer`** suchte `1.234`. Diese Zahl steht
  aber auch in der Aufstellung je Funktion weiter unten – als die Nutzerzeile
  ihre Zahl gar nicht mehr ausgab, fand der Test sie trotzdem. Jetzt sucht er
  `1.234 von`.

Beides derselbe Fehlertyp wie schon mehrfach: Der Test findet, wonach er
sucht, nur woanders.

### `live_pruefung.py` kennt jetzt Unterseiten

Das Skript prüfte bisher nur die Startseite jeder App. Eine Unterseite, die
man von Hand aufsuchen muss, hätte still 500 werfen können, bis jemand sie
braucht. `UNTERSEITEN` listet sie jetzt – heute `› Geräte` und
`› KI-Verbrauch`.

### Live geprüft

Alle 19 Seiten 200, Guthaben aus dem laufenden Container gelesen (9,92 USD),
Seite mit echten Zahlen gerendert: Andi 9.124 Tokens, Friederike 4.663,
Simone 2.071, Johannes 0 – jeweils von 100.000 im Monat. 911 Tests grün.

**v181 direkt hinterher**, weil die Seite „setzt sich monthly zurück“
schrieb. Auf einer deutschen Seite steht kein `monthly`.

### Was offen ist

Die Push-Nachricht des Wächters ist **nicht** live ausgelöst worden – das
Guthaben liegt bei 9,92 USD, und ein künstlich herbeigeführter Alarm hätte
eine echte Aufgabe in Andis Liste hinterlassen. Der Weg ist derselbe wie bei
jeder anderen Aufgaben-Push (`push_send(…, "todo", …)`), im Test geprüft;
bestätigt ist er erst, wenn das Guthaben tatsächlich zur Neige geht.

---

## 2026-08-09 – portal-v179: Wunsch #182 – Werkstatt-Karte neu aufgeteilt

> „Die Ansicht sieht nach der Feldanpassung für Prio noch schräger aus als
> davor. Mach die Ansicht neu."

Wieder eine Folge meiner eigenen Änderung, und diesmal eine, die ich hätte
kommen sehen müssen: `#180` machte den Prio-Picker breit genug für
„Zurückgestellt" (185px). Er stand aber **neben** dem Wunschtext, in einer
Spalte mit `flex-shrink:0` – also gab er keinen Platz her. Auf einem 375er
iPhone blieben für den Wunsch selbst rund 120px.

Ich habe bei #180 die Breite korrigiert und nicht gefragt, **wohin** diese
Breite geht. Der Wächter dort prüft seither, dass der Picker breit genug ist –
er sagt nichts darüber, ob daneben noch etwas Platz hat.

### Zwei Änderungen, kein Breakpoint

**Aktionen in eine eigene Zeile** (`flex-basis:100%`). Die Karte ist ohnehin
`flex-wrap`, es braucht also keine Medienabfrage: Der Text bekommt die volle
Breite, die Aktionen sitzen rechtsbündig darunter. Auf dem PC sieht das
genauso ordentlich aus.

**Vier Zeilen Vorschau** per `line-clamp`. Lange Wünsche – wie dieser hier –
füllten sonst die halbe Liste. Der vollständige Text steht in der
Detailansicht, die beim Antippen ohnehin aufklappt.

Der Deckel muss beim Aufklappen **weg**, sonst stünde der Text auch dort
gekürzt und das Aufklappen brächte nichts. Dafür trägt jetzt die Karte selbst
die Klasse `offen`, nicht nur das Detail-Panel – und ein Test verlangt, dass
beide Zustände synchron laufen statt unabhängig umzuschalten.

Dazu ein sichtbarer Pfeil in der Kopfzeile. Dass die Karte aufklappt, musste
man vorher raten.

### Was ich nicht messen konnte

Das Chrome-Fenster ist weiterhin minimiert, Chrome legt dann kein Layout an –
Breiten und Höhen sind nicht prüfbar. Verifiziert ist, was ohne Layout geht:
Pfeil vorhanden, Aktionen stehen im DOM hinter dem Text, Karte und Panel
schalten synchron auf und zu. Die eigentliche Probe ist dein iPhone.

6 neue Tests, 880 grün.

---

## 2026-08-09 – portal-v178: Wunsch #181 – mein Fehler von gestern in der Packliste

> „Es gibt einen Fehler, wenn man einen Eintrag ans Ende der liste verschieben
> will, dann springt er in die nachfolgende Kategorie."

Genau beschrieben, und die Ursache saß in `ziehSortierung()` aus #178 – meinem
eigenen Code von gestern. **Zwei Fehler in einer Funktion**, die zusammen
genau dieses Bild ergeben:

1. **Kein Gruppenfilter.** Die Suche nach der Einfügestelle lief über *alle*
   Einträge der Seite. Zieht man unter die letzte Zeile einer Kategorie, ist
   der nächste Kandidat der erste Eintrag der *folgenden* – und der steht
   hinter deren Überschrift. Der Eintrag landete sichtbar drüben.
2. **Der Rückfall hängte ans Ende von allem.** `platzhalter.parentNode
   .appendChild(...)` schiebt an das Ende des gesamten Behälters, nicht an
   das Ende der eigenen Gruppe. „Ans Listenende ziehen" bedeutete also: quer
   durch alle Kategorien nach ganz unten.

Behoben über ein optionales `gruppe:`-Kriterium; die Packliste gruppiert nach
`data-kategorie`. Ohne Angabe verhält sich der Helfer wie vorher (flache
Liste) – die Kategorien-Seite bleibt damit unberührt.

Sortiert wird bewusst nur **innerhalb** einer Kategorie. Ein Eintrag in eine
andere zu ziehen würde seine `kategorie_id` nicht mitändern – er spränge beim
nächsten Laden zurück, weil die Gruppierung serverseitig aus dieser Spalte
kommt. Die Kategorie ändert man über den Stift.

### Der Wächter überlebte die erste Gegenprobe

Er prüfte, ob `opt.gruppe` im Code vorkommt. Beim absichtlichen Kaputtmachen
blieb die Zeile `const schluessel = opt.gruppe ? …` stehen, während der Filter
selbst ausgehebelt war – der Test blieb grün. Jetzt prüft er den **Vergleich**
(`opt.gruppe(el) === schluessel`), und die Gegenprobe fällt.

Fünfter Test dieser Art in zwei Tagen. Das Muster hat sich geschärft: **Ein
Wächter, der nur auf einen Namen prüft, überlebt fast jede Sabotage.** Er muss
auf die Stelle zielen, an der die Wirkung entsteht.

### Serverseitig festgenagelt

Der wichtigste Test ist nicht der über den JavaScript-Text, sondern der über
das Verhalten: Ein `reorder` quer durch zwei Kategorien darf **keine einzige**
`kategorie_id` ändern. Das ist die Zusage, auf die es ankommt – und sie gilt
unabhängig davon, was das Frontend schickt.

Live an einem **Wegwerf-Ziel** geprüft (vier Einträge in zwei Kategorien),
danach entfernt: Der erste Eintrag wandert ans Ende und behält seine
Kategorie. Keine echten Packlisten angefasst – die Lehre von gestern hat
gehalten.

4 neue Tests, 874 grün.

---

## 2026-08-09 – portal-v177: Wünsche #179 und #180 – zwei kleine, einer davon meiner

### #180: ein Folgefehler meiner eigenen Änderung

> „Der Picker für die Prio ist jetzt mit der Großen schriftart zu schmal.
> ‚Zurückgestellt' wird nicht mehr sauber dargestellt (am PC)."

Genau richtig beobachtet, und die Ursache steht ein paar Stunden vorher in
diesem Journal: `#170` hob die Schrift aller Eingabefelder auf 16px, damit iOS
beim Antippen nicht hineinzoomt. Der Prio-Picker stand bei 12px und hatte ein
`max-width:100px` – bemessen für 12px. Ich habe die Schrift angehoben und die
Breite nicht mitgedacht.

Das ist die unangenehme Sorte Fehler: Er entsteht nicht dort, wo man arbeitet,
sondern eine Datei weiter. Und aufgefallen ist er nicht mir, sondern Andi.

**Der Test bindet die Breite jetzt an die längste Beschriftung**, nicht an
eine Zahl: Er misst die Schriftgröße aus der Regel, sucht die längste
Option aus dem Markup und rechnet nach. Wer die Schrift erneut vergrößert
oder eine längere Priorität einführt, kommt hier zwangsläufig vorbei.

Bei der ersten Rechnung sagte er mir: 170px reichen nicht, es braucht 179.
Mein Augenmaß hatte 170 geschätzt. Ich bin der Rechnung gefolgt – 185px.

### #179: Zubereitungsfeld

5 Zeilen zeigten zwei bis drei Schritte gleichzeitig; beim Tippen einer
Anleitung verliert man so den Zusammenhang. Jetzt 14 – etwa ein halber
Handybildschirm. Größer wäre auf dem Telefon unhandlich, und `resize:vertical`
war ohnehin schon gesetzt, am PC lässt sich also weiterhin jede Größe
einstellen.

870 Tests grün.

---

## 2026-08-09 – portal-v175: Wunsch #178 – Packliste filtern und umsortieren

Zwei Teile, die nur die Liste gemeinsam haben.

### Filter: der Knopf, der leicht gefehlt hätte

Eine Knopfreihe mit allen Personen, mehrere gleichzeitig wählbar – dasselbe
Muster wie in den Aufgaben. Der wichtige Knopf ist **„🌐 Allgemein"**: Sachen
ohne Person (Reiseapotheke, Ladekabel) verschwänden sonst spurlos, sobald
jemand filtert – und ausgerechnet die müssen fast immer mit.

Bewusst getrennt vom vorhandenen **Packmodus**: Der blendet alles andere aus
und führt durch *einen* Packvorgang. Der Filter dient dem Ansehen.

### Umsortieren: der Fallstrick liegt beim Anlegen

Nicht das Sortieren ist heikel, sondern was mit **neuen** Einträgen passiert.
Landen sie auf Position 0, schiebt jeder neue Eintrag die von Hand sortierte
Liste durcheinander – jedes Mal aufs Neue. Sie landen deshalb am Ende, und ein
Test hält genau das fest.

Die 76 bestehenden Einträge haben bei der Migration einmalig Positionen in
ihrer bisherigen (alphabetischen) Reihenfolge bekommen – sonst hätten nach dem
Deploy alle auf 0 gestanden und die Liste wäre willkürlich umgeordnet
erschienen.

### Keine dritte Kopie der Zieh-Logik

Die Packlisten-Kategorien und die Einkaufsläden haben je eine eigene, fast
wortgleiche Fassung derselben ~120 Zeilen Drag-Code. Statt einer dritten steht
jetzt `ziehSortierung()` in `base.html`, parametrisiert über Griff, Eintrag,
Platzhalter und Speicherfunktion.

**Die beiden bestehenden habe ich bewusst nicht migriert.** Sie funktionieren,
und ein Umbau wäre ohne sichtbaren Browser nicht prüfbar – das Chrome-Fenster
ist seit Stunden minimiert. Das ist keine Vorliebe für Duplikate, sondern die
Abwägung, ein funktionierendes Feature nicht blind anzufassen; die Notiz dazu
steht im Helfer selbst.

### Zwei Fehler beim Bauen, beide von derselben Sorte

**Einen Klassennamen geraten.** Der Filter suchte `.kategorie-titel` – die
Klasse heisst `.kat-label`. Ein solcher Fehler fällt nie auf: Der Filter läuft
fehlerfrei durch und blendet einfach nichts aus.

**Und der Test dagegen bestätigte sich selbst.** Er suchte den Klassennamen in
der Datei ab `{% block body %}` – der Skriptblock steht dahinter, also fand
jeder gesuchte Name sich selbst. Auch mit einem frei erfundenen Namen blieb er
grün. Jetzt sammelt er die Klassennamen aus den `class`-Attributen ausserhalb
des Skripts; die Gegenprobe fällt.

Das ist heute der vierte Test dieser Art (nach den Kassenbuch-Ereignissen, dem
Löschen-Panel und der Trefferfläche). Das Muster ist immer dasselbe: **Wenn
Prüfling und Prüfmassstab aus derselben Datei kommen, muss man sie sauber
trennen** – sonst misst der Test sich selbst.

13 neue Tests, 868 grün.

---

## 2026-08-09 – portal-v174: Wunsch #171 – Umschalter ohne Seitensprung

Vier Umschalter luden die ganze Seite neu und sprangen an den Anfang. Die
Lösung ist **nicht überall dieselbe**, und das Kriterium dafür ist die
eigentliche Arbeit an diesem Wunsch:

> Ändert der Umschalter die Reihenfolge oder Gruppierung der Liste?

| Umschalter | Weg |
|---|---|
| gekocht (Essensplan) | fetch – ändert nur diesen einen Knopf |
| storniert (Kassenbuch) | fetch – Zeile bleibt, nur der Saldo ändert sich |
| erledigt / Priorität (Werkstatt) | Anker – verschiebt zwischen den Listen |
| Erinnerung (Geburtstage) | Anker – „ausblenden" wechselt den Abschnitt |

Eine Karte, die an Ort und Stelle umspringt, während die Sortierung veraltet,
ist **schlimmer** als ein Sprung: Man handelt dann auf einer Liste, die nicht
mehr stimmt. Andis Wunsch nennt den Anker selbst als zulässige Alternative –
gut, dass er das getan hat, sonst hätte ich hier etwas Falsches gebaut.

### Mechanik: ein Attribut, kein viertes Skript

`data-fetch="funktionsname"` am Formular, ausgewertet im vorhandenen
Absende-Verteiler – dieselbe Bauart wie `data-bestaetigen` und
`data-arbeitet`. Serverseitig entscheidet der gemeinsame Helfer
`antwort_oder_weiter()`: JSON, wenn `Accept: application/json` mitkommt, sonst
Weiterleitung wie bisher. Der Formularweg bleibt damit **funktionsfähig**, und
ein Test hält beide Wege fest.

Zwei Details, die sonst still danebengehen: Der Fehlerfall bekommt ein
sichtbares `alert` – wer nicht merkt, dass sein Tipp verpufft ist, tippt nicht
nochmal, sondern glaubt, es sei gespeichert. Und der Knopf wird im `finally`
freigegeben, nicht im `then`; sonst bliebe er nach einem Fehler tot.

### Zum dritten Mal: mein Erklärkommentar hat den Wächter ausgelöst

Der Verteiler nennt `data-fetch="funktionsname"` als Beispiel, und der Test
suchte danach eine Funktion dieses Namens. Nach `header_extra` (#155) und
`button::before` (#169) der dritte Fall – Kommentare werden jetzt vor der
Prüfung herausgeschnitten, und der Test sagt das auch.

### Beim Live-Test zwei echte Datensätze angefasst

**Wunsch #178** stand auf „hoch". Mein Test schickte eine leere Priorität an
die Route – damit war sie NULL, der Wunsch also aus der Freigabe gefallen.
Sofort zurückgesetzt.

**Der gekocht-Vermerk vom 09.08. mittags** existierte bereits. Mein erster
Aufruf löschte ihn, der zweite legte ihn neu an: gleiches Rezept, gleicher
Tag, gleiche Person – aber mit **meinem** Zeitstempel statt dem
ursprünglichen. Der ist nicht wiederherstellbar. Für die Anzeige folgenlos
(#165 sortiert nach dem Tag des Essens), aber es ist eine Änderung, die ich
verursacht habe, und sie gehört benannt.

Beides dieselbe Ursache: **Ich habe echte Datensätze als Testziel benutzt.**
Beim Kassenbuch (06.08.) war die Lehre schon einmal fällig, beim Geburtstag
und beim Werkstatt-Wunsch habe ich extra Wegwerf-Einträge angelegt – hier
nicht, weil es „nur ein Umschalter" war. Genau da rutscht es durch.

8 neue Tests, 856 grün.

---

## 2026-08-09 – portal-v173: Wunsch #175 – Icon-Knöpfe haben jetzt Namen

Ein Knopf mit der Aufschrift ✏️ oder 🗑️ liest sich für VoiceOver als
„Schaltfläche" – mehr nicht. `title` hilft dabei nicht verlässlich und
erscheint bei Touch ohnehin nie.

Erhoben statt geschätzt: **45 Knöpfe**, deren Beschriftung kein Wort ist.
Genau einer hatte einen `aria-label` (das Hamburger-Menü). 31 davon trugen
einen `title`, aus dem sich der Name mechanisch übernehmen liess; die
restlichen 13 haben von Hand einen bekommen – sieben Pfeile im
Tierbaukasten, die fünf Sterne der Bewertung („Mit 3 von 5 Sternen
bewerten"), der Erledigt-Haken der Werkstatt.

### Die Konvention: title und aria-label sagen dasselbe

Wo beides steht, ist der Text identisch. Zwei verschiedene Texte am selben
Knopf wären eine Einladung, den einen zu pflegen und den anderen zu
vergessen – **und vergessen wird immer der, den niemand sieht.** Ein Wächter
prüft die Gleichheit, ein zweiter das blosse Vorhandensein, ein dritter, dass
niemand mit „Knopf" oder „…" die Prüfung erfüllt und dabei nichts sagt.

Bei der Gelegenheit ein paar Namen verbessert, weil sie als Vorlesetext zu
knapp waren: Aus „Weniger"/„Mehr" wurde „Eine Stufe weniger/mehr Portionen",
aus „1"/„0,25"/„0,1" wurde „Schrittweite: ganze/viertel/Zehntel Portion".
Da `title` mitgeändert wurde, ist auch der Mauszeiger-Hinweis besser.

Das betrifft heute niemanden in der Familie akut – es kostet fast nichts und
gehört zu einer Oberfläche, die man ernst meint.

3 neue Wächter (je Vorlage), 800 Tests grün.

---

## 2026-08-09 – portal-v171: Wunsch #176 – das Warten sichtbar machen

Drei Formulare warten mehrere Sekunden auf eine KI-Antwort und gaben dabei
kein Signal: Rezept-aus-URL, Rezept-aus-Bild, Vokabel-Foto-Import. Man hält
es für kaputt oder tippt ein zweites Mal – und importiert doppelt.

Gelöst im **vorhandenen** Absende-Verteiler in `base.html`: Ein Formular mit
`data-arbeitet="Wird gelesen …"` bekommt beim Absenden einen deaktivierten,
umbeschrifteten Knopf. Drei Attribute statt drei Skriptblöcke, und der
nächste lange Vorgang braucht nur dasselbe Attribut.

### Zwei Stellen, an denen so etwas kippt

**Die Reihenfolge.** Das Signal kommt erst, nachdem alle Abbruchgründe
durch sind – Löschabfrage abgelehnt, Prüffunktion verweigert. Ein Knopf, der
nach einem *abgebrochenen* Absenden deaktiviert stehen bleibt, ist schlimmer
als gar kein Signal: Die Seite sieht aus, als arbeite sie, und tut nichts.
Dafür musste das bestehende `preventDefault` ein `return` bekommen; ohne das
lief der Code danach weiter. Ein Test prüft beide Reihenfolgen und das
`return` – gegengeprobt, er fällt.

**Die Zurück-Navigation.** Holt der Browser die Seite aus seinem
Vor-/Zurück-Speicher, ist der Knopf noch deaktiviert – für immer, und niemand
käme auf die Idee, dass Neuladen hilft. Ein `pageshow`-Handler stellt ihn
wieder her.

Dazu ein Wächter, der über alle Vorlagen prüft, dass ein `data-arbeitet` auch
wirklich an einem Formular mit Absende-Knopf hängt – sonst liefe die Anzeige
lautlos ins Leere.

Live bestätigt: Das Attribut kommt in beiden Rezept-Importseiten an.

6 neue Tests (davon einer je Vorlage), 708 grün.

---

## 2026-08-09 – portal-v169: Wunsch #172 – Darstellung folgt dem Gerät

Drei Zustände statt zwei: ☀️ Hell → 🌙 Dunkel → 🌗 Wie das Gerät, im Kreis.
Die Automatik steht am Anfang des Kreises, weil sie der Normalfall ist; die
anderen beiden sind bewusste Übersteuerungen.

### Die dunklen Farben stehen weiterhin nur an einer Stelle

Der naheliegende Weg wäre gewesen, den `body.dark`-Block zu kopieren und die
Kopie in `@media (prefers-color-scheme: dark)` unter `body.auto` zu stellen.
Zwölf Farbwerte, zweimal getippt – und beim nächsten Mal zieht jemand einen
davon nur an einer Stelle nach. Auffallen würde es nie, weil kaum jemand beide
Modi nebeneinander sieht.

Stattdessen stehen die Werte in einer Jinja-Variablen (`{% set %}`) und werden
zweimal ausgegeben. Ein Test prüft beides: in der **Vorlage** genau einmal, im
**gerenderten HTML** zweimal.

### Niemand wird migriert

`dark_mode` bekommt als Spalten-Default die 2 (Automatik) – neue Konten
starten damit. Bestehende Konten fasse ich **nicht** an: Simone und Johannes
stehen auf 0, und ob das eine bewusste Wahl war oder nie berührt wurde, lässt
sich nicht unterscheiden. Ihre Darstellung ohne Rückfrage umzustellen wäre
dieselbe Anmaßung wie damals, Andis entfernte Tierbaukasten-App
wiederherzustellen. Ein Tipp im Menü genügt.

Nach der Auslieferung nachgesehen: alle vier Werte unverändert.

### Der Knopf zeigt jetzt den Zustand, nicht das Ziel

Vorher stand dort die Sonne, wenn Dunkelmodus aktiv war – gemeint als „hier
tippen für hell", gelesen als „es ist hell". Bei drei Zuständen wäre das
vollends unlesbar geworden. Jetzt zeigt der Knopf, was gilt, und der
Titel nennt es im Klartext.

### Beim Testen Andis Einstellung verstellt – und zurückgesetzt

Der Live-Durchlauf schaltete zweimal und ließ sein Konto auf „immer hell"
stehen. Zurückgesetzt auf den Ausgangswert 1. Dass mir das auffiel, liegt nur
daran, dass ich den Zustand vorher und nachher ausgelesen habe – ohne diese
Angewohnheit hätte er morgen ein helles Portal gehabt und sich gewundert.

`dark` bleibt in der Antwort erhalten für ältere PWA-Stände im Cache; für sie
sieht „wie das Gerät" wie „hell" aus – der harmlosere der beiden Irrtümer.

11 neue Tests, 657 grün.

---

## 2026-08-09 – portal-v168: Wünsche #170, #173, #174 – drei globale Regeln

Alle drei sind dieselbe Bauart wie #169: **eine Regel in `base.html` statt 44
Einzelkorrekturen.** Getrennt auszuliefern wäre dreimal derselbe Weg gewesen.

| Wunsch | Regel |
|---|---|
| #170 | `input, select, textarea { font-size: max(16px, 1em) }` |
| #173 | `.main { max-width: 720px; margin: 0 auto }` |
| #174 | `:focus-visible` Ring + `:focus:not(:focus-visible) { outline: none }` |

### Der Wächter fand sofort, dass meine erste Lösung nicht wirkt

`input, select, textarea { … }` ist ein **Element**-Selektor (Spezifität
0,0,1). `.add-input { font-size: 15px }` ist ein **Klassen**-Selektor
(0,1,0) – und Klassen schlagen Elemente, **unabhängig von der Reihenfolge**.
Die globale Regel hätte also keinen einzigen der 24 Fälle erreicht, die sie
beheben sollte.

Ohne den Test wäre das durchgegangen: Die Regel steht sichtbar im Quelltext,
sie sieht richtig aus, und der Beweis des Gegenteils wäre ein iPhone gewesen,
das weiterhin zoomt – das hätte niemand mir zugeordnet.

Behoben, indem die 23 Werte in 20 Vorlagen auf 16px angehoben wurden; die
globale Regel bleibt als Untergrenze für alles, was keine eigene Klasse hat.
`max(16px, 1em)` statt `16px`, damit absichtlich größere Felder groß bleiben.

**Und `base.html` war selbst betroffen:** `.wunsch-prio-select` stand auf
15px. Mein Wächter nahm base.html anfangs aus – die Datei mit der Regel schien
über jeden Verdacht erhaben. Sie ist es nicht: Ein Klassenselektor gewinnt
auch dort. Die Ausnahme ist entfernt, der Wert korrigiert.

### #174: Warum die zweite Hälfte der Regel wichtig ist

`:focus-visible` allein hätte gereicht, um den Ring zu bekommen. Die Zeile
`:focus:not(:focus-visible) { outline: none }` stellt ausdrücklich den
**bisherigen Zustand für Mausklicks** wieder her – ohne sie sähen alle, die
mit der Maus in ein Feld klicken, plötzlich überall Rahmen, wo vorher keine
waren. Die 24 `outline:none` aus 21 Vorlagen sind entfernt, weil sie den
Ring sonst überschrieben hätten.

### #173: bewusst nur Schritt 1

720px zentriert, sonst nichts. Der zweite Teil des Vorschlags (Essensplan mit
zwei Wochen nebeneinander, Rezepte als Raster) ist ein eigener Umbau je Seite
und gehört nicht in eine Zeile CSS.

Live bestätigt: alle vier Regeln kommen in den ausgelieferten Seiten an.
Die Wirkungsmessung im Browser steht weiterhin aus (Fenster minimiert).

5 neue Wächter (davon 2 je Vorlage), 646 Tests grün.

---

## 2026-08-09 – portal-v167: Wunsch #169 – Tippziele auf Fingergröße

Erster freigegebener Wunsch aus dem UX-Review. Andi hat sechs der acht
Vorschläge freigegeben (#169–#173, #176); #174 und #175 warten noch.

### Eine Regel statt 44 Korrekturen

Jeder `button` bekommt in `base.html` ein unsichtbares, zentriertes
Pseudo-Element von mindestens 44×44 px, das Tipps an den Knopf weiterreicht.
Die Optik ändert sich um kein Pixel; der 17 px hohe „gekocht?"-Knopf bleibt
zierlich, trifft sich aber wie ein großer.

Vorab geprüft statt gehofft: **keine** Vorlage definiert ein eigenes
`button::before`/`::after` (das würde die Fläche ersetzen), und das einzige
`position:absolute` in einem knopfartigen Element sitzt in einem `label`,
dem ein relativer Bezugsrahmen sogar entgegenkommt. Bewusst nur `button` –
Links im Fließtext mit Riesen-Trefferzone würden Absätze überdecken, und die
kleinen Bedienelemente sind fast ausnahmslos Buttons.

In der Lücke zwischen zwei Knöpfen gewinnt jetzt der im DOM spätere – dort
landete ein Tipp vorher **ins Leere**, das ist kein Rückschritt.

### Der Wächter biss zweimal daneben, bevor er sass

1. Er sprang auf die erste Erwähnung von „button::before" an – die steht in
   meinem eigenen Erklärkommentar. Der Slice begann im Kommentar und enthielt
   die Regel nie. → Auf den Selektor (`button::before {`) anspringen.
2. Die Gegenprobe entfernte nur die width-Untergrenze – und der Test blieb
   grün, weil height die gesuchte Zeichenkette weiterhin enthielt. → Beide
   Achsen einzeln prüfen.

Beides Varianten desselben Musters aus dieser Woche: ein Test, der zufällig
grün ist, prüft nichts. Ohne die Gegenproben wären beide unbemerkt geblieben.

### Verifikation mit einer offenen Flanke

Live ausgeliefert und bestätigt, dass die Regel in den Seiten ankommt. Die
**Wirkungsmessung** (elementFromPoint 8 px neben einem kleinen Knopf muss den
Knopf treffen) steht noch aus: Das Chrome-Fenster ist minimiert, Chrome legt
dann kein Layout an. Der Test dafür liegt bereit; nachholen, sobald das
Fenster offen ist – oder Andi tippt schlicht am iPhone, das ist ohnehin die
echte Probe.

Kein Hilfe-Kapitel: Es gibt nichts zu erklären, die Knöpfe treffen sich
einfach besser.

2 neue Wächter-Tests (+1 je Vorlage), 553 grün.

---

## 2026-08-09 – UX-Review aller Seiten: acht Vorschläge in der Werkstatt (#169–#176)

Andis Auftrag: alle Seiten nach modernen UI/UX-Gesichtspunkten für iPhone und
PC bewerten, Vorschläge in die Werkstatt, gemeinsame Durchsicht, dann Freigabe.

**Eingetragen mit `prioritaet=NULL`** – der stündliche Durchlauf fasst sie
damit nicht an, bis Andi sie freigibt. Genau dafür wurde die Freigabe-Logik
gebaut. `user_id=NULL`, weil die Vorschläge von der KI stammen, nicht von
einem Familienmitglied.

### Methode – und eine Grenze, die dazugehört

Das Chrome-Fenster war während des Reviews **minimiert**; Chrome liefert dann
Viewport 0×0 und keine brauchbaren Layout-Maße. Statt darauf zu warten, lief
das Review als statische Analyse aller 44 Vorlagen (CSS-Regeln, Formulare,
fetch-Muster) plus der Live-Messungen aus den früheren Sitzungen desselben
Tages (🗑️ 31×23 px, gekocht-Knopf usw. – damals bei sichtbarem Fenster
gemessen). Ein visueller Durchgang auf echtem iPhone bleibt Andis Part bei
der gemeinsamen Durchsicht – das ist ohnehin der Plan.

Ein Verdacht hat sich dabei **nicht** bestätigt und wurde deshalb nicht
eingetragen: Das 10-Sekunden-Polling der Einkaufsliste pausiert bereits bei
verstecktem Tab (visibilitychange ist implementiert).

### Die acht Vorschläge

| # | Vorschlag | Betrifft |
|---|---|---|
| 169 | Tippziele auf 44 px (viele Knöpfe sind 17–33 px hoch) | iPhone |
| 170 | Eingabefelder auf 16 px – iOS zoomt sonst beim Fokus (24 Klassen in 22 Vorlagen) | iPhone |
| 171 | Kleine Umschalter ohne Seitensprung (gekocht?, ✓/Prio, Storno, Glocke machen vollen Redirect) | beide |
| 172 | Dark Mode folgt prefers-color-scheme, Schalter bleibt als Override | beide |
| 173 | Desktop: max-width statt voller Fensterbreite (.main hat keins) | PC |
| 174 | :focus-visible-Ring; 21 Vorlagen setzen outline:none ersatzlos | PC |
| 175 | aria-label für Icon-Knöpfe (3 aria-Attribute im ganzen Portal) | beide |
| 176 | KI-Importe: Knopf deaktivieren + „Wird gelesen…" während der Wartezeit | beide |

Auffällig: 169/170/174 sind dieselbe Sorte Befund wie #155 und #160 –
**Konsistenzfragen, die entstehen, wenn jede Vorlage ihre eigenen Regeln
mitbringt.** Die Vorschläge zielen deshalb jeweils auf EINE globale Regel in
`base.html` plus Wächter-Test, nicht auf 44 Einzelkorrekturen.

### Nebenbei: der leere-Datei-Fehler

Der erste Einfüge-Versuch scheiterte an meinem eigenen Shell-Konstrukt
(`cat > a || cat > b <<HEREDOC` – der Heredoc hing am **zweiten** cat, das
erste wartete auf stdin und schrieb eine leere Datei). Die leere Datei lief
dann kommentarlos als No-op durch. Der zweite Versuch prüft deshalb zuerst,
ob schon UX-Wünsche da sind, und bricht sonst ab – nach dem Kassenbuch- und
dem Sitzungs-Fund die Erinnerung in klein: **ein leeres Ergebnis ist kein
Beleg, dass nichts zu tun war.**

Kein Code geändert, keine Auslieferung – die Wünsche sind Daten.

---

## 2026-08-09 – portal-v166: Wunsch #167 – feinere Schritte beim Umrechnen

> „0,1 und 0,25 Schritte müssen irgendwie sinnvoll möglich sein."

Nachschlag zu #164. Der Wunsch nennt zwei ganz verschiedene Anlässe: ein Kind
isst mit (halbe Portion), und der Rührkuchen soll in eine etwas grössere Form
(Faktor 1,25 statt 2). Beides braucht dieselbe Fähigkeit.

### Schrittweite wählen statt sechs Knöpfe

Naheliegend wäre eine Reihe aus −0,25 −0,1 +0,1 +0,25 gewesen. Zusammen mit
den vorhandenen ± wären das sechs Knöpfe nebeneinander – auf einem Handy zu
voll, und man muss jedesmal den richtigen treffen. Stattdessen bleiben die
zwei grossen ± und darunter steht die Schrittweite: **1 · 0,25 · 0,1**.

### Der Fliesskomma-Test war der eigentliche Punkt

`4 + 0.1 + 0.1` ergibt in Javascript `4.200000000000001`. Ohne Gegenmassnahme
stünde nach ein paar Klicks eine solche Zahl auf dem Bildschirm – und weil
sie *fast* richtig ist, würde man es beim flüchtigen Hinsehen übersehen.

Deshalb wird nach **jedem** Schritt gerundet, nicht erst bei der Anzeige.
Live geprüft: zehn 0,1er-Schritte ab 4 ergeben exakt `5`, nicht
`5,000000000000001`.

### Untergrenze hängt an der Schrittweite

Bei ganzen Schritten ist 1 das Minimum – 0 Portionen ergeben keinen Sinn. Bei
0,1er-Schritten sind 0,5 Portionen aber durchaus sinnvoll (ein halber Kuchen),
also ist dort die Schrittweite selbst die Grenze. Eine feste Untergrenze von 1
hätte die feinen Schritte nach unten gerade dort blockiert, wo sie gebraucht
werden.

### Live an beiden genannten Fällen

| Fall | Rezept | Ergebnis |
|---|---|---|
| Kind isst mit | Gnocchi-Pfanne, 4 → 4,5 | Lauch 2 → 2,25 Stangen |
| grössere Form | Rührkuchen, 1 → 1,25 | 500 g → 625 g Butter, 8 → 10 Eier |

Zurücksetzen liefert in beiden Fällen exakt die Originalwerte.

506 Tests grün (unverändert – die Änderung ist reines Frontend, geprüft im
Browser).

---

## 2026-08-09 – portal-v165: Wunsch #165 – „wann gab es das zuletzt?"

> „Unterhalb der Bewertung soll ein Bereich aufklappbar sein, in dem dann die
> Liste der Einträge steht, wann das Gericht auf dem Essensplan als ‚gekocht'
> markiert wurde."

Der Abschluss der Vierer-Reihe #162–#165. Die Daten legt #162 an, hier werden
sie nur gelesen – der Grund, warum sie damals in einer eigenen Tabelle am
Rezept landeten statt als Häkchen am Planeintrag, zahlt sich jetzt aus.

### Sortiert nach dem Tag des Essens, nicht nach dem Anhaken

Die naheliegende Sortierung wäre `markiert_am` gewesen – der Zeitpunkt, zu dem
jemand den Haken gesetzt hat. Falsch: Gefragt ist „wann gab es das", nicht
„wann hat es jemand vermerkt". Wer eine Woche später nachträgt, würde den
Verlauf sonst durcheinanderbringen und stünde fälschlich ganz oben.

Ein Test hat genau diesen Fall: ein Eintrag vom 20.07., abgehakt erst am
08.08. Nach Vermerkzeit stünde er vorn, nach Essenstag ganz hinten – wo er
hingehört.

### Zugeklappt steht schon die Antwort da

„🍳 Gekocht — 3×, zuletzt am 05.08.2026". Die häufigste Frage ist „wann
zuletzt?", und dafür soll man nicht erst aufklappen müssen. Die vollständige
Liste mit Datum, Mahlzeit und Namen kommt erst auf Tippen.

Ohne Einträge steht dort nicht einfach nichts, sondern der Hinweis, wie die
Liste sich füllt – eine leere Liste ohne Erklärung liesse offen, ob die
Funktion kaputt ist.

### Live über beide Apps hinweg

Im Essensplan das heutige Abendessen abgehakt, dann ins Rezept: „1×, zuletzt
am 09.08.2026" und in der Liste „09.08.2026 abends · Andi". Auf- und
zuklappen geprüft, Platzierung nachgemessen (Bewertung bei y=422, Verlauf bei
y=464, gleicher Abschnitt). Vermerk danach wieder entfernt.

Beim Messen hatte ich zuerst `!!x & y` geschrieben – Operator-Rangfolge
verdreht, das Ergebnis war `0` und damit wertlos. Sauber nachgemessen statt
die falsche Zahl stehen zu lassen.

Gegengeprobt durch Verdrehen der Sortierung und Entfernen der WHERE-Klausel:
drei Tests fallen.

7 neue Tests, 506 grün. Damit sind #162–#165 komplett.

---

## 2026-08-09 – portal-v164: Wunsch #164 – Portionen umrechnen

> „Die Portionen sollen anpassbar sein, da man manchmal ein Rezept für 4 hat,
> aber 5, 3 oder 10 Portionen braucht."

### Abgrenzung zu einem zurückgestellten Wunsch

Naheliegend wäre gewesen, dafür die Zutaten strukturiert in Menge / Einheit /
Name zu zerlegen. Genau das ist aber **Wunsch #51 – und der ist
`zurueckgestellt`.** Also nicht angefasst: Hier wird nichts gespeichert und
nichts geparst, was über die erste Zahl einer Zeile hinausgeht. Der Regler
ändert die Anzeige, das Rezept behält seine Originalangabe.

### Erst den echten Bestand ansehen

Statt einen Parser für alle denkbaren Schreibweisen zu bauen, habe ich die 56
vorhandenen Zutaten ausgezählt:

| Form | Anzahl |
|---|---|
| führende Ganzzahl („500 ml Milch") | 45 |
| Kommazahl („0,5 Zitrone") | 1 |
| ohne Zahl („Pfeffer") | 10 |
| Brüche, Bereiche, Punktzahlen | **0** |

Damit deckt ein sehr einfacher Ausdruck den kompletten Bestand ab, und Zeilen
ohne Zahl bleiben unverändert – was richtig ist, „Salz" skaliert man nach
Geschmack.

Auch `portionen` ist Freitext: `'4'`, `'8-10'`, `'12'`, `NULL`. Gelesen wird
die erste Zahl; ohne Zahl erscheint der Regler **gar nicht**. Ein Regler, der
nichts bewirkt, wäre schlimmer als keiner.

### Der Fund, der den Wunsch erst richtig macht

Der 🛒-Knopf setzt eine Zutat auf die Einkaufsliste – und der Server nahm
dafür immer den **gespeicherten** Text. Hätte ich nur die Anzeige skaliert,
sähe man „750 g Mehl" und bekäme „500 g Mehl" auf die Liste. Ohne Hinweis,
ohne Fehlermeldung, und man merkt es erst im Laden.

Das Frontend schickt deshalb die angezeigte Zeile mit; fehlt sie (alte PWA im
Cache), gilt weiter die Originalmenge. Der Text wird nur als Anzeigetext
übernommen und **nicht ausgewertet** – auch hier bleibt #51 unberührt.

Gegengeprobt durch Ignorieren des mitgeschickten Textes: zwei Tests fallen.

### Live an einem echten Rezept

Gnocchi-Pfanne, Basis 4 Portionen:

| | Lauch | Champignons | Rapsöl | Gnocchi |
|---|---|---|---|---|
| 4 (Original) | 2 Stangen | 400 g | 7 EL | 1 kg |
| 6 | 3 | 600 g | 10,5 EL | 1,5 kg |
| 3 | 1,5 | 300 g | 5,25 EL | 0,75 kg |
| zurück | 2 | 400 g | 7 EL | 1 kg |

Kein Drift über mehrere Schritte: Gerechnet wird immer aus `data-original`,
nie aus dem zuletzt angezeigten Wert. Sonst summierten sich Rundungsfehler
über jeden Klick auf.

Krumme Ergebnisse bleiben krumm (4,5 Eier). Das Portal rechnet ehrlich; runden
soll der Mensch – das steht so auch in der Hilfe.

9 neue Tests, 500 grün.

---

## 2026-08-09 – portal-v163: Wunsch #163 – vom Plan direkt ins Rezept

> „Ist ein Rezept aus der DB ausgewählt, dann soll man auch direkt dorthin
> abspringen können."

Ein kleiner Wunsch mit spürbarer Wirkung: Bisher hiess „was war nochmal in der
Gnocchi-Pfanne?" App wechseln und das Rezept in der Liste suchen. Jetzt ist der
Name im Essensplan ein Link.

Zwei Dinge vorher geprüft statt angenommen:

**Kollidiert der Link mit dem Ziehen?** Nein – der Zieh-Anfänger (⠿) ist ein
eigenes Element, das Drag & Drop hängt nicht am Inhalt der Zelle. Hätte ich
das nicht nachgesehen, wäre jeder Verschiebeversuch womöglich als Klick auf
den Link geendet.

**Freitext bekommt keinen Link.** Zu „Pizza vom Lieferdienst" gibt es kein
Rezept; ein Link dorthin führte ins Leere.

### Der Test geht den Link wirklich

Ein Link, der ins Leere zeigt, fällt im Alltag erst auf, wenn ihn jemand
antippt. Der Test liest deshalb die Adresse aus der gerenderten Seite und
**ruft sie auf** – gegengeprobt mit einer erfundenen Rezept-ID: der Test
fällt.

Dabei noch einmal derselbe Zählfehler wie neulich bei den Kassenbuch-
Ereignissen: `seite.count("mahlzeit-rezept-link")` ergab 4 statt 1, weil der
Klassenname auch dreimal im CSS-Block der Seite steht. Gezählt wird jetzt auf
`class="…"` – also auf das Attribut, nicht auf den Namen.

Live bestätigt: Der Link im Plan zeigt auf `/a/rezepte/8`, und dort steht
„Gnocchi-Pfanne mit Lauch".

3 neue Tests, 491 grün.

---

## 2026-08-09 – portal-v162: Wunsch #162 – gekocht abhaken

> „Gekochte Rezepte sollen abgehakt werden können, um zu erfassen wann ein
> Rezept aus der DB gekocht wurde."

### Die Entscheidung, die alles andere bestimmt

Ein Häkchen auf `essensplan_eintraege` wäre der naheliegende Weg gewesen – und
falsch. Ein Planeintrag wird überschrieben, per Drag & Drop verschoben (#35)
und irgendwann gelöscht. Hinge die Aufzeichnung daran, wäre sie genau dann
weg, wenn sie interessant wird: „Wann hatten wir zuletzt Linsen?" fragt man
Monate später, nicht in derselben Woche.

Deshalb eine eigene Tabelle `rezept_gekocht`, die am **Rezept** hängt. Der
Wunsch sagt es selbst: „wann ein **Rezept aus der DB** gekocht wurde". Drei
Tests halten fest, dass die Aufzeichnung ein Überschreiben und ein Löschen des
Planeintrags übersteht – und einer, dass sie beim Löschen des *Rezepts* sehr
wohl mitgeht, sonst blieben Waisen zurück.

Freitext-Einträge („Pizza vom Lieferdienst") bekommen keinen Haken. Es gäbe
kein Rezept, an dem sich etwas merken liesse; ein Haken, der nichts festhält,
wäre schlimmer als keiner.

### Zum dritten Mal dieselbe Undichtigkeit – jetzt umgedreht

Die Tests fielen sofort über `UNIQUE(tag, mahlzeit)`: `essensplan_eintraege`
und `rezepte` überlebten das Leeren der Testdatenbank, weil sie nicht per
CASCADE am Nutzer hängen. Dasselbe Muster wie bei den Geburtstagen (#145) und
den Wünschen (#161).

Dreimal derselbe Fehler heisst, die Bauart ist schuld: `conftest.py` zählte
auf, **was geleert wird**. Jede neue Tabelle musste man nachtragen, und vergass
man es, lief der Bestand still mit. Jetzt zählt es auf, **was stehen bleibt**
(die Seed-Tabellen) und leert alles andere. Vergisst man dort etwas, fehlen
Stammdaten und die Tests schlagen sofort und laut fehl – die richtige
Fehlerrichtung.

### Ein Test, der von der Undichtigkeit lebte

Nach der Umstellung fiel `test_jede_aktion_zeigt_auf_eine_vorhandene_funktion`
mit `assert 20 > 20`. Er zählt geprüfte `data-klick`-Attribute und verlangte
mehr als 20 – erreicht hatte er das nur, weil die Seiten **Datenreste anderer
Tests** mitrenderten und dadurch ein paar Handler mehr zeigten.

Die Schwelle war also von genau dem Leck abhängig, das ich gerade geschlossen
hatte. Auf sauberer Datenbank sind es deterministisch 20; die Schwelle steht
jetzt bei 15 (sie soll nur ein kaputtes Suchmuster abfangen, das 0–2 fände)
mitsamt der Erklärung, warum sie gesenkt wurde.

Live an einem echten Planeintrag geprüft (09.08. abends, Rezept 8): Klick
setzt den Vermerk mit Zeitstempel, zweiter Klick nimmt ihn zurück. Endzustand
unverändert.

13 neue Tests, 488 grün.

---

## 2026-08-09 – portal-v161: Wunsch #166 – Rückfragen melden sich

> „Wird eine Rückfrageaktion eingetragen, dann soll eine Pushbenachrichtigung
> an den Admin erfolgen."

Die Ergänzung, die #161 erst nützlich macht: Eine Rückfrage, die niemand
bemerkt, ist keine Rückfrage.

**Nur bei `art='frage'`.** Würde jede Antwort und jede Notiz melden, wären die
Meldungen schnell nichts mehr wert – und dann schaut niemand mehr hin. Das ist
kein Sparen an Funktion, sondern die Funktion selbst.

**Nicht an den Verfasser.** Sonst meldet sich Andis Handy bei jeder Rückfrage,
die er selbst stellt – und er stellt die meisten.

**An alle Admins, nicht an „den Admin".** Der Wunsch sagt Singular, aber ein
fest verdrahteter Empfänger wäre still kaputt, sobald es einen zweiten Admin
gibt. Heute ist es genau einer, und genau deshalb fällt so ein Fehler erst
Jahre später auf.

Die Meldung verlinkt direkt auf `#wunsch-<id>` – ohne Sprungziel müsste man
die Rückfrage in 165 Wünschen suchen.

### Live geprüft, aber bewusst ohne Zustellung

Es war 01:51 Uhr. Eine Testmeldung auf die Familienhandys wäre unhöflich
gewesen, also habe ich den Pfad so geprüft, dass garantiert nichts zugestellt
wird: Rückfrage **als Admin selbst** eingetragen. Ergebnis: Aktion angelegt,
**null** Push-Versuche im Log – das ist zugleich der Live-Beleg für die
Selbst-Ausschluss-Regel. Die Zustellung selbst ist durch die Tests abgedeckt
und der Kanal ohnehin erprobt (heute kamen Meldungen auf dem iPhone an).

Gegengeprobt durch zwei absichtliche Fehler (Beschränkung auf `frage`
entfernt, Selbst-Ausschluss entfernt): zwei Tests fallen.

5 neue Tests, 476 grün. Testwunsch wieder entfernt.

### Nebenbei bestätigt

In `wunsch_aktionen` steht jetzt genau eine echte Zeile: der Abschluss von
#161, den `manage.py wunsch_erledigt` seit gestern mitschreibt. Der
Mechanismus greift also im Alltag, ohne dass jemand daran denken muss.

---

## 2026-08-08 – portal-v160: Wunsch #161 – die Werkstatt wird zum Ticketsystem

Drei Teile: KI-Überschrift für titellose Wünsche, ein Verlauf je Wunsch, und
ein Knopf zum Antworten.

### Die Überschrift darf nichts kaputtmachen dürfen

Die KI-Anfrage läuft in einem Hintergrund-Thread und startet **erst nach dem
Commit**. Das ist die ganze Konstruktion: Fällt OpenRouter aus, ist das
Kontingent leer oder antwortet das Modell Unsinn, bleibt der Wunsch einfach
ohne Titel – exakt wie vorher. Der Wunsch ist das Wertvolle, der Titel ist
Beiwerk, und Beiwerk darf das Wertvolle nie mitreissen.

Zwei Feinheiten, die sonst später weh tun:

- Der Thread benutzt `new_db()`. `g.db` aus einem Thread gäbe „Cannot operate
  on a closed database" – dieselbe Lehre wie bei `push_send()`.
- Das `UPDATE` setzt den Titel nur `WHERE titel IS NULL OR titel=''`.
  Zwischen Absenden und Antwort kann ein Admin von Hand einen Titel vergeben
  haben, und **der Mensch hat Vorrang vor der Maschine**.

Live bestätigt: „Beim Kochen wäre es praktisch, wenn die Zutatenliste …" wurde
zu **„Zutaten mit einem Tipp zur Einkaufsliste hinzufügen"** – 160 Tokens.

### Der Verlauf, und wer hineinschreiben darf

`wunsch_aktionen` hält Plan, Rückfrage, Antwort, Umsetzung und Notiz je mit
Zeitpunkt und Urheber. Anlegen darf **Admin oder der Urheber des Wunsches** –
genau darum geht es im Wunsch: Wer etwas eingetragen hat, soll auf eine
Rückfrage antworten können, ohne Admin zu sein. Alle übrigen lesen mit.

`manage.py wunsch_erledigt` schreibt den Umsetzungstext ab jetzt zusätzlich
als Aktion. Die Spalte `wuensche.umsetzung` bleibt trotzdem: Sie trägt die
Abschlüsse von rund 150 alten Wünschen, die es als Aktion nie geben wird –
sie wegzuwerfen, um die Datenhaltung hübsch zu machen, wäre ein schlechter
Tausch.

Geladen werden die Aktionen in **einer** Abfrage für alle Wünsche. Die
Werkstatt zeigt 160 Wünsche auf einer Seite; eine Abfrage je Wunsch wären 160
Abfragen für eine Liste, in der die meisten gar keine Aktionen haben.

### Zwei Funde, die nichts mit dem Wunsch zu tun hatten

**Meine Thread-Attrappe war falsch, nicht der Code.** `type("S", (), {"start":
target})()` macht die Funktion zum Klassenattribut – und damit zur Methode,
die `self` bekommt. Der Test war rot, obwohl nichts kaputt war. Ersetzt durch
eine richtige kleine Klasse.

**Die Testdatenbank wird zwischen Tests nicht vollständig geleert.**
`conftest.py` löscht `grants`, `geburtstage` und `users` und verlässt sich
sonst auf `ON DELETE CASCADE`. `wuensche.user_id` ist aber `ON DELETE SET
NULL` – Wünsche überleben das Leeren also und sammelten sich **seit jeher**
über alle Tests hinweg an. Aufgefallen ist es erst, weil ein Test die
Aktionen GLOBAL zählte statt je Wunsch: dort standen 4 statt 0.

Das ist genau die Sorte Leck, die keinen Test rot macht, sondern Tests
unzuverlässig – ein späterer Test sieht Daten eines früheren. `DELETE FROM
wuensche` ergänzt; die Aktionen gehen per CASCADE mit.

Gegengeprobt durch drei absichtliche Fehler (Rechteregel raus, Art-Prüfung
raus, Titel-Vorrang raus): drei Tests fallen.

13 neue Tests, 471 grün. Der Testwunsch samt Verlauf ist wieder entfernt.

---

## 2026-08-08 – portal-v159: Wunsch #160 – Löschen sieht überall gleich aus

> „[…] Verankert diese Entscheidung für die grafische Oberfläche so, dass alle
> zukünftigen Apps auf die gleiche Weise gebaut werden."

Der zweite Satz war der eigentliche Auftrag. Ein Umbau hält bis zur nächsten
App – und genau so ist die Uneinheitlichkeit ja entstanden.

### Erst erheben, dann ändern

Statt zu schätzen, alle Vorlagen durchsucht. 14 Bedienelemente zum Entfernen:

| Symbol | Anzahl | Wo |
|---|---|---|
| 🗑️ | 8 | Einkauf, Geholfen-Verlauf, Packliste, Rezept, Startseite (2×), Todo-Serien, Vokabeln |
| ✕ | 5 | Aufgaben, Werkstatt (2×), Tierbaukasten, Kassenbuch |
| nur Text | 1 | Geburtstage („Für alle löschen") |

Die Mehrheit war also schon richtig. Entstanden ist der Rest nicht durch eine
Entscheidung, sondern durch Abschreiben von der jeweils benachbarten Datei –
dieselbe Mechanik wie bei #155, wo ich selbst einen Knopf an die falsche
Stelle gehängt hatte, weil er dort so aussah.

### Das Kassenbuch bleibt beim ✕ – mit Absicht

Sein ✕ ist **kein Löschen, sondern ein Storno**: Die Zeile bleibt für immer
stehen und zählt nur nicht mehr zum Kontostand (#144, #153, #156). Ein
Mülleimer würde etwas versprechen, das die App nicht tut – und das ausgerechnet
in der einen App, deren ganzer Zweck die Unveränderlichkeit ist.

Ein eigener Test hält fest, dass diese Ausnahme **beabsichtigt** ist, damit
sie niemand später „korrigiert". Er schlägt an, sobald das Kassenbuch
tatsächlich eine Löschen-Route bekäme.

### Der Wächter sucht über die Route, nicht über die Beschriftung

`tests/test_loeschen_symbol.py` findet Löschknöpfe über
`action="...loeschen..."`. Über die Beschriftung zu suchen wäre zirkulär: Der
Test fände dann nur, was ohnehin schon richtig heisst, und übersähe genau die
Fälle, um die es geht. Dazu ein Test, der prüft, dass überhaupt mindestens
zehn Knöpfe gefunden wurden – ein kaputtes Muster wäre sonst leer und grün.

Gegengeprobt: `todo.html` auf ✕ zurückgedreht → zwei Tests fallen.

Live nachgemessen statt angeschaut: Auf `/a/todo/` lädt die Grafik
`1f5d1.svg`, der Knopf ist 31×23 gross und sichtbar.

Verankert in `CLAUDE.md` (UI-Konventionen) und `server.md` (eigener Abschnitt
mit dem Muster zum Abschreiben) – plus ein Absatz in der Hilfe, der den
Unterschied zwischen Löschen, Ausblenden und Stornieren erklärt.

458 Tests grün.

---

## 2026-08-08 – portal-v158: Wunsch #159 – Löschen nur noch im Bearbeiten-Modus

> „Der Link für alle löschen soll nur noch im editieren Modus erscheinen"

„Für alle löschen" stand bisher dauerhaft unter jeder Karte – in einer Liste,
in der man normalerweise nichts löschen will, war es damit der auffälligste
Knopf der Seite. Jetzt steckt es im Panel, das der Stift aufklappt.

Ein kleiner Umbau mit einem Haken: Das Bearbeiten-Panel war selbst ein
`<form>`. Da Formulare nicht ineinander dürfen, ist daraus ein `<div>`
geworden, das beide Formulare nebeneinander aufnimmt. Die Umschalt-Funktion
greift weiterhin über die id, also blieb das JavaScript unverändert.

### Ein Test, der zweimal nichts geprüft hat

**Erste Fassung:** Sie verglich Positionen im HTML – Löschen muss nach dem
Panel-Anfang und vor der nächsten Karte stehen. Beim absichtlichen
Kaputtmachen blieb sie grün, und das zu Recht: Schiebt man das Formular aus
dem Panel heraus, landet es unmittelbar dahinter – immer noch vor der
nächsten Karte. Die Grenze war die falsche.

**Zweite Fassung:** Tiefenzählung über die `div`-Ebenen, um die echte
Panel-Grenze zu finden. Diesmal war der Test rot, obwohl der Code stimmte –
und die Ursache lag in meinem Werkzeug, nicht in der App: Beim Schreiben der
Testdatei wurde `` im regulären Ausdruck zu einem echten
**Backspace-Zeichen** (0x08). Das Muster `</?div` trifft nie etwas, die
Schleife lief leer, und der Helfer meldete „Panel wird nie geschlossen".

Sichtbar wurde es erst über `cat -A`, das Steuerzeichen als `^H` anzeigt. Im
Editor sah die Zeile völlig normal aus. Ersetzt durch `</?div[ >]` – ohne
Escape, damit die Frage gar nicht mehr aufkommt.

Beide Male hätte ich den Test ohne die Gegenprobe für gut befunden: einmal
grün ohne zu prüfen, einmal rot ohne echten Fehler.

Live nachgemessen statt angeschaut: Löschen liegt im Panel, ist zugeklappt
unsichtbar (Höhe 0), nach dem Stiftklick sichtbar, und die Formulare sind
nicht verschachtelt.

3 neue Tests, 366 grün.

---

## 2026-08-08 – portal-v157: Wunsch #158 – Geburtstage bearbeiten

Erster Wunsch, der über den stündlichen Durchlauf (#157) hereinkam.

> „Die Einträge sollen editierbar sein"

Ein Stift neben jedem Eintrag öffnet Name, Tag, Monat, Jahr und Notiz. Wer
ändern darf, ist **dieselbe Regel wie beim Löschen** – Urheber, Eltern oder
Admin: Der Eintrag gilt für die ganze Familie, das macht Bearbeiten zu einer
Berechtigungsfrage und nicht bloss zu einem Formular. Beide Wege benutzen
jetzt denselben Helfer `_darf_aendern()`, statt die Bedingung zweimal
auszuschreiben.

### Drei Dinge, die man beim Bearbeiten leicht kaputtmacht

**Die Prüfung.** Anlegen und Bearbeiten teilen sich `_eingaben_lesen()`. Zwei
Kopien wären die Bauart, bei der man eine Grenze nur an einer Stelle nachzieht
– und dann liesse sich per Bearbeiten eintragen, was beim Anlegen abgelehnt
wird. Ein Monat 13 käme so bis in `_tage_bis()`.

**Die Urheberschaft.** `erstellt_von` bleibt unangetastet. Wanderte sie mit
jeder Korrektur mit, könnte das Kind seinen eigenen Eintrag plötzlich nicht
mehr anfassen, nachdem ein Elternteil einen Tippfehler behoben hat.

**Die Erinnerungssperre.** Vorab geprüft statt angenommen: `geburtstag_gesendet`
schlüsselt auf den **Versandtag**, nicht auf das Geburtsdatum. Eine Korrektur
kann deshalb keine künftige Erinnerung unterdrücken – auch dann nicht, wenn
für denselben Eintrag am selben Tag schon eine Vorlauf-Meldung rausging. Kein
Aufräumen nötig, aber ein Test hält es fest.

### Ein Test, der nichts prüfte

Die erste Fassung fragte `hasattr(modul, "_eingaben_lesen")` ab – der wäre
grün geblieben, während eine zweite Kopie längst abweicht. Ersetzt durch fünf
parametrisierte Fälle, die **beide Wege** mit demselben Unsinn füttern
(Monat 13, Monat 0, Tag 32, Tag 0, leerer Name) und verlangen, dass beide
ablehnen.

Gegengeprobt durch Ausbau der Rechteregel und Aufweichen der Monatsgrenze:
vier Tests fallen.

### Live: der CSRF-Riegel hat mich erwischt

Der erste Live-Versuch bekam **403**. Kein Fehler im neuen Code – mein
`curl`-POST hatte weder `Origin` noch `Sec-Fetch-Site`, und `CSRF_MODUS` steht
seit Stufe 2 auf `scharf`. Mit den Headern dann: gültige Änderung greift,
Monat 13 wird verworfen, `erstellt_von` bleibt. Ein unfreiwilliger, aber
willkommener Beleg, dass Stufe 2 im Alltag wirklich beisst.

Geprüft wurde an einem eigens angelegten Testeintrag, der danach wieder
entfernt wurde – nicht an einem echten Geburtstag der Familie.

16 neue Tests, 363 grün.

---

## 2026-08-08 – Wunsch #157: stündlicher Wunsch-Durchlauf, mit ehrlichen Grenzen

> „In Zukunft sollst du alle 60 Minuten prüfen, ob Wünsche priorisiert und zur
> Umsetzung freigegeben sind […] dann beginne mit der Implementierung
> automatisch."

Eingerichtet: ein wiederkehrender Auftrag, jede Stunde um :23 (bewusst nicht
:00 – dort landen die Anfragen der halben Welt gleichzeitig). Er holt die
freigegebenen Wünsche, und wenn keine da sind, antwortet er mit **einer Zeile**
und tut sonst nichts. Ohne diese Regel wären 24 Fortschrittsberichte am Tag
das Ergebnis, und die Automatik würde zur Belästigung.

### Was „freigegeben" heisst

**Ausdrücklich gesetzte Priorität, die nicht `zurueckgestellt` ist.** Wünsche
ohne Priorität (NULL) fasst der Lauf nicht an – „noch nicht priorisiert" ist
nicht dasselbe wie „freigegeben". Damit greift genau das Tor, das Andi sich
mit #152 gebaut hat: Sein eigener Wunsch startet auf `zurueckgestellt`, und
erst sein Hochstufen gibt ihn frei.

### Drei Grenzen, die ich nicht wegdiskutieren kann

Der erste Versuch, den Auftrag anzulegen, wurde vom Berechtigungs-Wächter
**blockiert** – ein wiederkehrender, unbeaufsichtigter Job, der Code schreibt,
auf den Familienserver ausliefert und nach GitHub pusht. Ich habe bewusst
keinen Umweg gebaut, sondern es Andi vorgelegt; er hat zugestimmt.

Wichtiger sind aber die Grenzen des Werkzeugs selbst:

| Gewünscht | Tatsächlich |
|---|---|
| „In Zukunft" | Der Auftrag lebt **nur in dieser Sitzung**. Nichts auf Platte, weg beim Schliessen. |
| dauerhaft | Wiederkehrende Aufträge **laufen nach 7 Tagen ab**. |
| „wenn ausreichend Kontingent, dann beginne" | **Ich kann mein Kontingent nicht abfragen.** Ich kann nur aufhören, wenn es endet – der nächste Lauf macht weiter. |

Das Ergebnis ist also nicht „ab jetzt automatisch", sondern „solange dieses
Fenster offen ist, höchstens sieben Tage". Das steht hier, damit es in vier
Tagen niemanden überrascht, wenn nichts mehr passiert – ein Automatismus, der
still aufhört, ist schlimmer als keiner.

Der dauerhafte Weg wäre eine geplante Aufgabe ausserhalb von Claude, die Claude
Code stündlich mit diesem Auftrag startet. Andi wollte es „erstmal nur ganz
einfach"; das bleibt offen.

---

## 2026-08-08 – portal-v156: Wunsch #156 – es gibt keine Änderungen zu protokollieren

> „Werden im Protokoll auch Änderungen dokumentiert (z.B. wenn der Betreff
> editiert oder der Betrag verändert wird)? Das soll auch dokumentiert sein."

Wieder eine Frage, und nach #151 habe ich sie nachgesehen statt beantwortet.
Im ganzen Projekt gibt es **genau eine** ändernde Anweisung auf
`kassenbuch_eintraege` – das Storno – und **kein** `DELETE`. Eine
Bearbeiten-Route existiert nicht; die App hat für Betrag, Zweck, Person und
Datum schlicht keinen Knopf. Das ist so seit #144 („ein bisschen wie bei
einem Buchhaltungssystem") und war nie ein Versäumnis.

Einem Eintrag kann also genau zweierlei widerfahren: angelegt und storniert.
Beides steht seit #153 im Prüfprotokoll. Es fehlt nichts.

### Trotzdem war die Frage berechtigt

**Ein Prüfer kann nicht unterscheiden, ob keine Änderungen stattgefunden haben
oder ob Änderungen nicht protokolliert werden.** Beides sieht auf der Seite
identisch aus. Genau das ist der Grund, warum Andi gefragt hat – und deshalb
war „passt schon" die falsche Antwort.

Zwei Dinge nachgeholt:

**Die Zusage steht jetzt auf der Seite.** Ein abgesetzter Absatz erklärt, dass
Betrag, Zweck, Person und Datum von niemandem mehr angefasst werden können,
auch nicht vom Admin, und dass das Fehlen von „geändert" damit eine Zusage ist
und keine Lücke.

**Die Zusage ist jetzt erzwungen, nicht nur eingehalten.** Vier neue Tests:
die schreibenden Routen des Kassenbuchs sind genau drei (über `url_map`, nicht
über den Quelltext – eine anderswo registrierte Route fiele sonst durch); es
gibt kein `DELETE`; das einzige `UPDATE` fasst ausschliesslich die drei
Storno-Spalten an; und ein Storno lässt am laufenden Objekt Betrag, Zweck,
Person, Datum und Art unverändert.

Der erste Test nennt im Fehlerfall gleich die Konsequenz: Wer eine
Bearbeiten-Route ergänzt, muss das Prüfprotokoll um eine dritte Ereignisart
erweitern. Damit hängt die Vollständigkeit des Protokolls nicht mehr daran,
dass jemand daran denkt.

347 Tests grün.

---

## 2026-08-08 – portal-v155: Wunsch #155 – die Verwaltung war die letzte

> „Die Buttons sind noch mit dem Header des Portals verbunden. das haben wir
> doch in allen Apps geändert. scheint hier zurückgeblieben zu sein."

Stimmte auf's Wort. `base.html` hatte einen Block `header_extra`, über den man
Knöpfe direkt auf das farbige Kopfband kleben konnte – und genau **eine**
Vorlage benutzte ihn noch: `admin.html`. Überall sonst stehen Aktionen oben im
`<main>`, abgesetzt auf dem normalen Hintergrund.

Pikant daran: Ich habe heute Nachmittag den Geräte-Knopf für #154 genau dort
eingehängt, weil das in dieser Datei so aussah wie die richtige Stelle. Ich
habe den Bestand nachgeahmt, statt zu prüfen, ob der Bestand noch dem Muster
entspricht – und damit eine Altlast frisch verstärkt.

### Nicht nur verschoben, sondern die Möglichkeit entfernt

Die beiden Knöpfe sitzen jetzt als `.top-aktionen`-Zeile oben im Inhalt, in
derselben Bauart wie `todo.html`. Dazu geflogen sind:

- der Block `header_extra` in `base.html` – sein einziger Nutzer war weg, und
  ein Erweiterungspunkt, der nur das falsche Muster ermöglicht, lädt zur
  Wiederholung ein;
- die Regel `.nav-extra`, die nur für ihn da war;
- `.btn-add` in `admin.html` (weiß auf farbigem Grund) – außerhalb des Headers
  unsichtbar. Sie stehen zu lassen hätte geheißen, beim nächsten Knopf
  versehentlich wieder danach zu greifen.

### Gemessen statt angeschaut

Screenshots liefen wieder in einen Timeout, also über `getBoundingClientRect()`
– dieselbe Methode wie beim CSS-Prozenthöhen-Fall:

| | Verwaltung | todo (Referenz) |
|---|---|---|
| Abstand Header → Leiste | 16 px | 16 px |
| Leiste liegt in | `<main>` | `<main>` |
| Hintergrund dahinter | rgb(245,245,247) | – |
| Knopf: Rahmen / Grund | var(--farbe) / transparent | dito |
| Radius / Padding / Schrift | 12px / 12px 10px / 14px 600 | identisch |

Bleibt ein Unterschied von 3 px in der Höhe. Nachgemessen: `line-height` ist in
beiden `normal`, die Differenz kommt vom Emoji im Text. Kein Layoutfehler,
also stehen gelassen – den hätte ich sonst „repariert", ohne dass etwas kaputt
war.

### Wächter statt einmaligem Umbau

`tests/test_kopfleiste.py` geht alle Vorlagen durch: keine darf `header_extra`
benutzen, und zwischen `</header>` und `<main>` darf keine Schaltfläche
stehen. Kommentare werden vorher herausgeschnitten, sonst hätten die
Hinweistexte in `base.html` und `admin.html` den Test selbst ausgelöst.
Gegengeprüft durch Wiedereinbau des Blocks: fällt.

Solche Abweichungen entstehen nicht durch eine falsche Entscheidung, sondern
dadurch, dass eine Datei beim Umbau übersehen wird. Ein Test findet die
nächste, ein aufgeräumtes `admin.html` nicht.

343 Tests grün.

---

## 2026-08-08 – portal-v154: Wunsch #154 – Geräteübersicht

Der Wunsch stammt aus dem Aufräumen vom selben Tag: 817 Sitzungen für vier
Menschen, unbemerkt, weil die Tabelle für niemanden einsehbar war.

Die Seite (`⚙️ Verwaltung → 📱 Geräte`) listet jede angemeldete Sitzung mit
Person, Gerät, Anmeldezeitpunkt und letzter Benutzung – und erlaubt, **ein
einzelnes** Gerät abzumelden. Das ist der eigentliche Zugewinn: Bis hierher
gab es nur „Neuer Zugang + QR", das alle Token neu erzeugt. Wer sein Handy
verlor, sperrte damit auch Tablet und Kiosk aus und brauchte einen neuen
QR-Code. Jetzt verliert genau ein Gerät seinen Nachweis, der Link bleibt
gültig.

### Zwei Sachen, die vorher nur so aussahen, als gäbe es sie

**`gesehen` wurde nie fortgeschrieben.** Die Spalte existiert seit Stufe 1 und
wurde ausschließlich beim Anlegen gesetzt. Eine Liste mit „zuletzt benutzt"
hätte also dauerhaft den Anmeldezeitpunkt gezeigt – und zwar überzeugend, denn
die Zahl sieht ja plausibel aus. Jetzt schreibt `sitzung_nutzer_id()` mit,
gedrosselt auf einmal je Stunde. Die Drosselung steckt in der WHERE-Klausel
statt in Python: eine Anweisung, kein Lesen-Ändern-Schreiben.

**`_GERAET_MAX = 80` schnitt jeden Browsernamen ab.** „Mozilla/5.0 (Windows NT
10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)" ist auf's Zeichen
genau 80 lang – „Chrome/141.0" kam nie in der Datenbank an. Die Liste hätte
für immer nur Betriebssysteme gezeigt. Jetzt 200.

Beides fiel erst beim Hinsehen auf, nicht beim Testen – und das ist die
Pointe: **Meine Tests benutzten künstlich kurze User-Agents.** Sie prüften
eine Zeichenkette, die in der Wirklichkeit nie vorkommt. Deshalb gibt es
jetzt einen Test, der die echte Kennung erst auf `_GERAET_MAX` kürzt und
dann parst; bei 80 fällt er.

### Und ein Test, der gar nichts prüfen konnte

Die erste Fassung der Drosselungs-Prüfung rief zweimal auf und verglich
`gesehen`. Beide Aufrufe fielen in dieselbe Sekunde, `datetime('now')` lieferte
zweimal denselben Wert – der Test bestand auch nach **entfernter** Drosselung.
Aufgefallen ist es nur, weil ich die Drosselung testweise ausgebaut und
erwartet habe, dass etwas rot wird. Es wurde nichts rot.

Neu geschrieben mit gesetztem Versatz (−5 Minuten: darf nicht schreiben;
−2 Stunden: muss schreiben). Jetzt fällt er ohne Drosselung.

`_geraet_lesbar()` prüft übrigens von speziell nach allgemein: Edge und Opera
nennen sich beide zusätzlich „Chrome", und jeder Chrome nennt sich zusätzlich
„Safari". Wer der Reihe nach von hinten sucht, hält am Ende jedes Gerät für
ein Safari – auch dafür ein eigener Test.

16 neue Tests, 250 grün. Live bestätigt: zehn Geräte mit Person und Zeiten,
eine neue Sitzung zeigt „Windows · Chrome", die alten weiterhin nur
„Windows" (deren gekürzte Kennung lässt sich nicht rekonstruieren).

---

## 2026-08-08 – portal-v152: Wunsch #152 – Priorität schon beim Eintragen

> „Als Admin will ich neue Wünsche direkt bei der Eingabe priorisieren können.
> Default ist zurückgestellt."

Die Voreinstellung ist der eigentliche Inhalt des Wunsches, nicht die
Bequemlichkeit. `zurueckgestellt` ist die einzige Priorität, die ein
Sammelauftrag („implementiere alle Wünsche") **nie** anfasst. Ein frisch
notierter Einfall bleibt damit liegen, bis Andi ihn ausdrücklich hochstuft –
der Dialog wird zum Notizzettel, ohne dass daraus versehentlich ein Auftrag
wird.

### Wer darf, wird auf dem Server entschieden

Die Auswahl steht im Template hinter `user.is_admin`. Darauf darf man sich
nicht verlassen: `/wunsch` nimmt JSON entgegen, ein selbstgebauter POST
umgeht jedes Template. Die Prüfung sitzt deshalb im Endpunkt – und zwar so,
dass ein unerlaubter Wert **den Wunsch nicht mitreisst**: verworfen wird die
Priorität, gespeichert wird der Vorschlag. Ein still weggeworfener Wunsch
wäre der schlechtere Ausgang.

Die Prioritätsliste steht jetzt im Kern (`WUNSCH_PRIORITAETEN`) statt lokal in
`05_werkstatt_app.py`. Gebraucht wird sie ab sofort an zwei Stellen – beim
Anlegen und beim Ändern –, und zwei getrennte Listen wären genau die Bauart,
deren Auseinanderlaufen niemandem auffällt: Ein Wert, den nur eine Seite
kennt, wird von der anderen wortlos verworfen. Ein Test hält fest, dass beide
Module dasselbe Objekt benutzen.

Die Auswahl setzt sich nach dem Senden zurück. Bliebe die letzte Wahl stehen,
bekäme der nächste Wunsch unbemerkt dieselbe Priorität – und „unbemerkt" ist
bei einer Einstufung, die über automatische Umsetzung entscheidet, das
Gegenteil von harmlos.

### Ein Test, der aus dem falschen Grund grün war

Meine erste Fixture legte eigene Grants per `INSERT OR IGNORE` an. Wegen
`UNIQUE(user_id, app_id)` lief das wortlos ins Leere, die Tokens waren
ungültig – und fünf Tests bestanden trotzdem: kein Nutzer → keine Priorität →
Erwartung erfüllt. Aufgefallen ist es nur, weil die beiden **Admin**-Tests
rot waren; wären sie nicht dabei gewesen, hätte ich zehn grüne Haken für eine
Prüfung gehabt, die nichts prüft.

Genau dafür sind die Positiv-Fälle da: Ein Test, der nur Verbote prüft,
bestätigt sich selbst, wenn gar nichts funktioniert.

10 neue Tests, 234 grün. Live bestätigt: Admin sieht die Auswahl, das Kind
nicht.

---

## 2026-08-08 – Stufe 6 bestätigt: der Umbau ist durch. Und: 808 Sitzungen von mir

Andi hat S6-01 bis S6-06 abgehakt. Damit sind alle sechs Stufen aus
`quiet-enchanting-shore.md` ausgeliefert **und** von echten Geräten bestätigt.
Alle Schalter stehen auf dem Endwert, `grants` trägt nur noch `token_lookup`.
Offen ist allein S6-07 (Windows-Push), was nicht am Umbau hängt.

### Beim Nachsehen: die Sitzungstabelle ist zu 99 % meine

817 Zeilen für vier Menschen. Aufgeschlüsselt nach `geraet`:

| Gerät | Sitzungen |
|---|---|
| `curl/8.19.0` | 688 |
| `Python-urllib/3.14` | 120 |
| echte Browser (iPhone, Windows, Mac, CrOS) | 9 |

**808 von 817 stammen aus meinen eigenen Regressionsläufen.** Jeder Aufruf
eines Pfad-Tokens ohne Cookie stellt eine Sitzung aus – und mein
Regressionsskript ruft alle Grants einzeln auf, ohne Cookie-Jar, mehrmals
täglich. Jede dieser Zeilen ist ein **gültiger, nie ablaufender Zugang**
(`ablauf` ist NULL, bewusst so wegen des Kiosk).

Das ist dasselbe Muster wie beim Kassenbuch, nur in der Authentifizierung:
Mein Testen hinterlässt dauerhafte Spuren im Produktivsystem, und weil es
lautlos passiert, fällt es erst auf, wenn jemand nachzählt. Bitter ist die
Ironie: Der ganze sechsstufige Umbau hatte zum Ziel, die Zahl langlebiger
Zugangsgeheimnisse zu senken – und mein Prüfen hat sie verhundertfacht.

Zwei Dinge folgen daraus:

1. **Das Regressionsskript braucht einen Cookie-Jar.** Dann entsteht **eine**
   Sitzung statt fünfzig, und die lässt sich am Ende gezielt wieder löschen.
2. **Es fehlt eine Geräteübersicht.** Der Plan hatte sie vorgesehen („die
   Geräteübersicht macht es sichtbar"), gebaut wurde sie nie. `sitzungen`
   wird heute nur bei „Neuer Zugang + QR" geleert und ist sonst für niemanden
   einsehbar – 817 Zeilen konnten deshalb unbemerkt auflaufen.

### Aufgeräumt (Andi zugestimmt)

**808 Sitzungen gelöscht**, Prädikat strikt auf
`geraet IN ('curl/8.19.0','Python-urllib/3.14')` – Kennungen, die kein echtes
Gerät trägt. Vorher 817, nachher 9, und diese neun sind genau die Browser der
Familie. Niemand musste sich neu anmelden.

**`/data/portal-vor-stufe6.db` entfernt** – der Notausstieg für Stufe 6 wird
nach der Bestätigung nicht mehr gebraucht.

**`scripts/live_pruefung.py` angelegt.** Das ist der eigentliche Fix, denn die
808 Zeilen waren ein Verfahrensfehler, kein Programmierfehler: Geprüft wurde
ad hoc mit `curl`, ein Aufruf je Grant, ohne Cookie-Jar. Jeder davon stellte
eine Sitzung aus. Das Skript legt jetzt **eine** an und löscht sie im
`finally` wieder – auch wenn der Lauf mittendrin abbricht.

Dass es im Repo liegt, ist der zweite Teil des Fixes. Ein Befehl, der nur in
einer Chat-Historie steht, trägt seine Fehler in die nächste Sitzung; dieser
lässt sich reparieren. Zweimal live gelaufen (Andi 16 Apps, Friederike),
jeweils alles 200, danach wieder exakt 9 Sitzungen. Als verbindliche
Konvention in `server.md` und `CLAUDE.md` aufgenommen.

**Wunsch #154 angelegt:** Geräteübersicht in der Verwaltung. Der eigentliche
Grund, warum das auflaufen konnte – die Tabelle ist für niemanden einsehbar
und wird nur bei „Neuer Zugang + QR" geleert, dann aber gleich komplett.
Ein verlorenes Handy lässt sich derzeit nur abmelden, indem man alle anderen
Geräte mit aussperrt.

### `portal.db.vor-129` – die letzte Klartext-Kopie, jetzt weg

Beim Aufräumen im selben Verzeichnis gefunden, 360 KB vom 05.08. Die Kopie
stammt von **vor** Wunsch #129 und hatte in `grants` noch eine Spalte `token` –
also die Zugangsschlüssel der ganzen Familie **im Klartext**. Genau das, was
sechs Stufen Umbau beseitigen sollten, lag dort unverändert daneben.

Erst gemeldet statt gelöscht, weil Andis Zustimmung einer anderen Datei galt;
auf Rückfrage beide entfernt – zusammen mit `familienportal.db` (0 Bytes,
30.07., leere Altlast) und zwei verwaisten WAL-Dateien, die beim Hineinsehen
entstanden waren. Auch das wieder meine Spur: Ein `PRAGMA table_info` im
Lesemodus legt `-wal`/`-shm` an, und die überleben die Hauptdatei.

Danach das ganze Datenverzeichnis durchgezählt – Livedatenbank plus alle 24
Snapshots:

| Form der Tokens | Dateien |
|---|---|
| nur Prüfsumme (`token_lookup`) | 17 |
| verschlüsselt (`token_enc`) | 8 |
| **Klartext** | **0** |

Die acht verschlüsselten sind Stundensnapshots vom 07.08. zwischen 09:00 und
16:00, also von vor der Umstellung; sie rollen im Laufe des Tages von selbst
heraus. Klartext gibt es nirgends mehr.

Übrig im Verzeichnis: `portal.db`, `snapshots/`, `vokabel_audio/`,
`.cert_mtime` – sonst nichts.

---

## 2026-08-08 – portal-v151: Wunsch #153 – Prüfprotokoll fürs Kassenbuch

> „Wie Wirtschaftsprüfer brauchen die Eltern Zugriff auf das Audit Log des
> Kassenbuchs."

Die Daten dafür gab es seit #144 vollständig – `erstellt_von`, `erstellt`,
`storniert_von`, `storniert_am` stehen auf jeder Zeile. Sichtbar waren sie
nirgends: `_eintraege_laden()` hat die Urheber-Spalten nicht einmal
mitgelesen. Es fehlte also keine Erfassung, sondern die Ansicht.

### Der Unterschied, der die Seite ausmacht

Ein Kassenbuch sortiert nach `datum` – dem Tag, an dem das Geld geflossen ist.
Ein Prüfer will die andere Reihenfolge: **wann wurde was erfasst.** Erst darin
fällt auf, dass ein Eintrag vier Tage später nachgetragen oder zwanzig Minuten
nach dem Anlegen wieder storniert wurde. Im Kontoauszug sieht beides völlig
unauffällig aus – deshalb ist die Prüfsicht kein anderes Layout derselben
Liste, sondern eine andere Sortierung derselben Tatsachen.

Daraus folgt der Rest fast von selbst:

- **Eine Zeile erzeugt bis zu zwei Ereignisse.** Anlegen und Stornieren sind
  zwei Handlungen, zu verschiedenen Zeiten, potenziell von verschiedenen
  Personen. Als eine Zeile mit Storno-Häkchen wäre die interessantere der
  beiden unsichtbar.
- **„nachgetragen"** markiert Einträge, deren Buchungstag vor dem Erfassungstag
  liegt. Erlaubt und meistens harmlos – aber genau das, wonach man sucht.
- **„nicht von … selbst"** ist heute unmöglich (nur das Kind darf buchen).
  Es wird trotzdem geprüft statt angenommen: Fände sich hier je ein fremder
  Urheber, wäre das der wichtigste Befund der ganzen Seite.
- **Rechenprobe** mit den Summanden einzeln. Ein Protokoll, das den Saldo nur
  behauptet, ist wertlos; hier lässt er sich nachzählen. Die Probe kann
  sichtbar scheitern – sonst würde sie nichts beweisen.

Kinder sehen ihr eigenes Prüfprotokoll **nicht**. Sie haben in ihrem
Kassenbuch bereits alles, auch die stornierten Zeilen; die Prüfsicht fügt
nichts hinzu ausser der Perspektive der Aufsicht, und die gehört laut Wunsch
den Eltern.

### Dabei gefunden: das Kassenbuch datierte nachts falsch

Der Container läuft auf UTC, die Familie lebt in Europe/Berlin. `date.today()`
liefert deshalb zwischen Mitternacht und 2 Uhr morgens den **Vortag** – und
die Regel „kein Nachtragen in die Zukunft" schob einen korrekt gewählten
Tag danach **stumm zurück**. Ein Eintrag um 00:30 landete also auf gestern,
ohne Hinweis.

Für ein Prüfprotokoll wäre das doppelt schlimm gewesen: Es hätte jeden
nächtlichen Eintrag als „nachgetragen" markiert und damit genau die
Markierung entwertet, um derentwillen es die Seite gibt.

Neu in `00_kern.py`: `heute_lokal()`, `utc_zu_lokal()`, `utc_zu_lokal_datum()`
und `LOKAL_TZ` – der eine Ort, an dem umgerechnet wird. Bisher hatte jedes
Modul, das die Zeitzone brauchte, seine eigene `_TZ`-Konstante
(`13_kinderplan.py`, `14_sportschau.py`, `18_tvb.py`); das Kassenbuch hatte
schlicht keine.

### Verifikation

17 neue Tests. Zwei davon habe ich absichtlich kaputtgemacht, um zu sehen,
dass sie beissen: Zugriffsgrenze ausgehängt → `test_kind_darf_das_protokoll_
nicht_sehen` rot; Zeitzonenumrechnung durch die Identität ersetzt → zwei
weitere rot. Ohne diese Gegenprobe wäre „alles grün" nur eine Behauptung.

Live geprüft – **diesmal mit einem Wegwerf-Konto**, nicht wie beim letzten Mal
gegen ein echtes Kinderkonto (siehe Eintrag darüber). Fünf Ereignisse in
Erfassungsreihenfolge, Storno 20 Minuten nach dem Anlegen als eigene Zeile,
„nachgetragen" an genau der einen Zeile, die es verdient, 09:00 UTC korrekt
als 11:00 angezeigt, Rechenprobe 10,00 + 7,00 − 2,50 = 14,50 mit den
stornierten 4,00 € ausserhalb. Zugriff: Kind 403 (auch aufs eigene), Admin
200, ohne Zugang 403. Konto danach restlos entfernt – keine Einträge, keine
verwaisten Grants.

224 Tests grün.

---

## 2026-08-08 – Aufräumen: mein Testmüll in Friederikes Kassenbuch

Andi fragte, ob die drei Einträge in Friederikes Kassenbuch von ihr oder von
mir stammen. Von mir. `journal.md` hält es selbst fest – „Live gegen den
echten Server verifiziert (**Friederikes echtes Konto**)", mit exakt diesen
Beträgen: Start 15,00 €, Einnahme 5,00 € (Oma), Ausgabe 3,00 € (Eis),
storniert. In der Datenbank steht als Urheber sie, weil ich über ihren Zugang
gebucht habe; unterscheiden lässt sich das dort nicht mehr.

Zwei Fehler, nicht einer: **live gegen ein echtes Kinderkonto getestet**
statt gegen ein Wegwerf-Konto, und den Testmüll danach **stehen gelassen**.
Ihr Kontostand zeigte zwei Tage lang 20,00 €, die sie nie hatte.

### Die Löschung ist eine bewusste Ausnahme von der Ledger-Regel

Andi wies zu Recht auf das Audit-Log hin. Wunsch #144 sagt ausdrücklich:

> „Es soll auch möglich sein, einen Eintrag wieder zu löschen, aber auch
> diese Einträge bleiben in der Datenbank stehen – ein bisschen wie bei
> einem Buchhaltungssystem."

Genau deshalb hat die App **keinen** Löschpfad, nur Stornieren. Ich musste
also auf DB-Ebene löschen, und das ist ein Bruch mit dem Prinzip – auf
Andis ausdrückliche Anweisung („sauber löschen, es soll nichts zurück
bleiben"). Vertretbar, weil es keine Buchführung war, sondern meine
Verunreinigung derselben: Ein Ledger soll echte Vorgänge unveränderlich
festhalten, nicht die Spuren meines Testlaufs. Festgehalten wird es hier,
weil es im Ledger selbst nicht stehen kann, ohne genau das zu hinterlassen,
was weg sollte.

Der Wächter in `settings.json` hat übrigens das erste `DELETE` ohne
`WHERE`-Klausel blockiert. Richtig so – der zweite Versuch nannte die drei
IDs explizit.

### Was wirklich weg ist und was nicht

| Ort | Zustand |
|---|---|
| Live-Datenbank | 0 Zeilen, `VACUUM` gelaufen, Rohsuche in der Datei ohne Treffer |
| 24 Stundensnapshots | enthalten sie noch, rollen von selbst binnen 24 h heraus |
| `data/portal-vor-stufe6.db` | enthält sie – bleibt bis Stufe 6 abgehakt ist, das ist der Rückfall |
| Tages-Backup auf dem NAS | enthält sie; ausserhalb von `/srv/familienportal/`, wird nicht angefasst |

„Nichts zurück bleiben" gilt also für alles, was im Alltag sichtbar ist, und
für die Datei selbst. Die Sicherungen absichtlich zu durchlöchern wäre der
falsche Preis dafür – sie laufen ohnehin aus.

### Nebenbei gefunden: Wunsch #153

> „Wie Wirtschaftsprüfer brauchen die Eltern Zugriff auf das Audit Log des
> Kassenbuchs."

Steht offen, `app_slug=kassenbuch`, Priorität mittel. Passt inhaltlich
unmittelbar an diese Sitzung an: Heute ist das Audit-Log nur in den Spalten
`erstellt_von`/`storniert_von`/`storniert_am` vorhanden und nirgends
sichtbar. Als nächstes dran.

---

## 2026-08-08 – portal-v149: Nachtrag zu #151 – meine Begründung war falsch

Andi schickte mir am selben Tag einen Artikel: Der TVB spielt gerade den
Sparkassen-Cup in Altensteig, 37:34 gegen Elbflorenz, Halbfinale gegen
Erlangen. Es gibt also sehr wohl Testspiele.

Mein Fehler war nicht die Messung, sondern der Schluss daraus. Geprüft hatte
ich, dass **handball.net** keine Testspiele führt – das stimmt und stimmt
weiterhin. Geschrieben hatte ich sinngemäß, dass es sie **nicht gibt**. Das
ist der Sprung von „meine Quelle kennt es nicht" auf „es existiert nicht",
und er ist besonders verführerisch, wenn die Messung selbst sauber war: Ich
hatte ein negatives Ergebnis in der Hand und habe seine Reichweite überdehnt.

Bemerkenswert daran ist, dass ich im selben Wunsch den umgekehrten Fehler
richtig behandelt hatte – beim Pokal war mir klar, dass ein leeres Ergebnis
an der Abfrage liegen kann und nicht an der Wirklichkeit. Genau diese
Skepsis habe ich zwei Absätze später nicht mehr angewendet.

### Was die Nachrecherche ergab

| Quelle | Testspiele |
|---|---|
| handball.net API + Vereinsseite | nein, auch kein S-Cup (Suche „Altensteig" leer) |
| tvbstuttgart.de/sportszone/spielplan | nein – dasselbe handball.net-Widget, gleiche Lücke |
| handball-world.news „Freundschaftsspiele", Saison 2026/27, alle Spieltage | Liste existiert, TVB kommt darin **null mal** vor |
| Nachrichtenartikel | ja – aber als Fließtext |

Die Spiele existieren also und sind nirgends maschinenlesbar. Die
Vereinsseite hilft ausgerechnet deshalb nicht, weil sie dasselbe Widget
einbindet wie wir – zwei Quellen, eine Lücke.

### Entscheidung: nichts bauen

Ich habe drei Wege vorgelegt (Handeintrag durch den Admin, KI-Auswertung der
Vereins-News, KI-Vorschlag mit Bestätigung). Andis Antwort:

> „Wenn es nicht automatisch geht dann brauche ich die Daten nicht."

Damit ist der Fall erledigt, und zwar ohne Code. Festgehalten, weil die
Neigung sonst gross ist, so etwas beim nächsten Anlass erneut vorzuschlagen:
**Ein Formular, in das jemand von Hand abtippt, was anderswo schon steht, ist
für dieses Portal keine Lösung.** Der Aufwand landet bei der Familie, und
genau das soll das Portal abnehmen.

Geändert wurde deshalb nur der Hilfetext, der die falsche Begründung
weitergetragen hätte („weil es sie an der Quelle schlicht nicht gibt"). Jetzt
steht dort, was zutrifft: Die Spiele gibt es, veröffentlicht sie aber niemand
in einer Form, die sich abrufen lässt.

Das Kennzeichen aus v147 bleibt selbstverständlich – der DHB-Pokal fehlte
wirklich und ist jetzt drin.

---

## 2026-08-08 – portal-v147: Wunsch #151 – Testspiele? Nein. Aber der Pokal fehlte.

Der Wunsch fragt, ob es bei den Profis Testspiele gibt, die im Spielplan nicht
auftauchen. Ich habe die Frage zuerst als Frage behandelt, nicht als Auftrag –
und die Antwort ist zweigeteilt.

### Testspiele gibt es nicht – bei handball.net

Weder die API noch die Vereinsseite kennen sie: kein einziger Treffer für
„Testspiel", „Freundschaft" oder „Vorbereitung", und im Spiel-Objekt existiert
kein Feld, das eine Freundschaftsbegegnung ausweisen würde. handball.net führt
ausschließlich Pflichtspiele. Da ist nichts zu holen und nichts freizuschalten –
das ist keine Einstellung, die man umlegt, sondern eine Lücke der Quelle.

### Gefehlt hat etwas anderes: der DHB-Pokal

Beim Nachsehen kam heraus, dass tatsächlich ein Spiel fehlte, nur eben ein
anderes als vermutet:

    21.08.2026  TSB Heilbronn-Horkheim – TVB Stuttgart   [DHB-Pokal]

Die Ursache ist unauffällig und deshalb erwähnenswert: **handball.net vergibt
je Wettbewerb eine eigene Team-ID.** Derselbe TVB heißt in der Bundesliga
`sr.competitor.6272-143352` und im Pokal `sr.competitor.6272-143228`. Die App
fragte den Liga-Spielplan (kennt naturgemäß nur Ligaspiele) und
`team/<id>/team-schedule` (hängt an der wettbewerbsgebundenen ID) – **beide
konnten den Pokal gar nicht liefern.** Kein Fehler, kein Log, keine leere
Liste: das Spiel war einfach nicht da.

Genau deshalb fällt so etwas nur auf, wenn jemand von außen fragt. Ein Test
hätte es nicht gefunden – es gab nichts, was falsch war, nur etwas, das nicht
gefragt wurde.

Der Vereins-Endpunkt `club/sr.competitor.6272/schedule` führt alle Wettbewerbe
zusammen und ist jetzt die dritte Quelle für die Profis. Bei den Amateur- und
Jugendmannschaften entfällt er – die hängen an einem anderen Vereinsobjekt
(handball4all), für das es ihn nicht gibt.

### Warum die Spiele nicht in einen eigenen Umschalter-Eintrag wandern

Sie liegen unter derselben `team_id` wie die Ligaspiele. Für die Familie sind
das „die Profis", keine zweite Mannschaft; ein Eintrag „TVB Stuttgart
(DHB-Pokal)" neben „Profis" wäre technisch korrekt und im Alltag unsinnig.
Die neue Spalte `wettbewerb` macht den Unterschied stattdessen dort sichtbar,
wo er interessiert: als kleines Kennzeichen am einzelnen Spiel.

Gekennzeichnet wird nur, was **vom Liga-Wettbewerb abweicht** – ein „DAIKIN
HBL" an jeder der neun Ligabegegnungen wäre reines Rauschen. Der Ligenname
wird dafür aus der Antwort gelesen statt konstant hinterlegt: er enthält den
Sponsor und ändert sich planbar.

Bestehende Zeilen bleiben bei `wettbewerb = NULL`. Welcher Wettbewerb es war,
lässt sich nachträglich nicht rekonstruieren, und ein geratenes „DAIKIN HBL"
wäre schlechter als keine Angabe – es sähe richtig aus.

### Verifikation

Neun neue Tests. Der erste hält bewusst den **Ist-Zustand** fest: der exakte
ID-Vergleich übersieht das Pokalspiel. Ginge er eines Tages durch, hätte
handball.net die IDs vereinheitlicht – dann sagt der Test Bescheid, statt dass
die Erweiterung stillschweigend überflüssig weiterläuft. Die Gegenrichtung ist
genauso abgedeckt: der Präfix darf keine fremden Vereine einsammeln, deren
Nummer zufällig mit 6272 beginnt (`sr.competitor.62721` – der Bindestrich im
Präfix ist die ganze Absicherung).

Live von hier aus geprüft: 10 Spiele auf der Seite, genau **ein** Kennzeichen –
das Pokalspiel. 207 Tests grün.

---

## 2026-08-07 – portal-v145: Wunsch #150 – Vokabel-Kapitel teilen

Geteilt wird das **Kapitel**, nicht die einzelne Vokabel: Eine später
hinzugefügte Vokabel wandert damit automatisch mit, und das Aufheben ist ein
Häkchen statt einer Liste.

### Die Zugriffsregel steht jetzt an einer Stelle

Vorher war „gehört mir" an sieben Stellen einzeln als `user_id=?`
ausgeschrieben – Liste, Trainer-Auswahl, Trainingsstart, Versuch, Audio,
Auswertung, Sprachwahl. Genau die Bauart, bei der eine Erweiterung eine Stelle
übersieht und dann entweder zu viel preisgibt oder eine Funktion still nicht
mitzieht.

Jetzt gibt es ein gemeinsames SQL-Fragment `_VOKABEL_SICHTBAR` (eigene ODER in
einem mit mir geteilten Kapitel) plus `_kapitel_zugaenglich()` und
`_sprache_zugaenglich()`. Was **ändernd** ist – bearbeiten, löschen,
umbenennen, weiterteilen – prüft weiterhin `_kapitel_gehoert_nutzer()`, also
echtes Eigentum. Diese Trennung ist der ganze Kern:

> Ein geteiltes Kapitel darf der Empfänger benutzen, aber nicht verändern.

### Zwei Dinge, die das Teilen sonst stillschweigend nutzlos gemacht hätten

**1. Die Sprache.** Der Empfänger hat die Sprache des geteilten Kapitels oft
gar nicht aktiviert. Ohne Sonderregel hätte `_sprache_erlaubt()` den
Trainingsstart abgewiesen – und zwar mit einer Weiterleitung ohne Begründung.
`_sprache_zugaenglich()` lässt eine Sprache deshalb auch dann zu, wenn sie in
einem geteilten Kapitel vorkommt. Live bestätigt: Friederike hat nur Englisch
und Latein aktiviert und konnte Andis dänisches Kapitel trotzdem trainieren.

**2. Die Auswertung.** Sie aggregierte über `v.user_id = ziel` – Trainings mit
fremden Vokabeln wären in keiner Statistik aufgetaucht. Der Wunsch verlangt
aber ausdrücklich, dass **alle** Trainings wie gehabt dokumentiert werden.

### Oberfläche

Auf der Kapitel-Seite je Kapitel ein 👥-Knopf (voll sichtbar, sobald geteilt)
mit Personen-Häkchen. Darunter ein eigener Abschnitt „Mit mir geteilt" – ohne
den wären fremde Kapitel im Trainer zwar auswählbar, aber nirgends erklärt.
Im Trainer steht bei fremden Kapiteln „· von <Name>", sonst wäre unklar,
wessen Vokabeln man übt. In der Vokabelliste haben fremde Einträge kein
Bearbeiten-Symbol, sondern 👥 mit dem Namen des Eigentümers.

### Verifikation

16 neue Tests, die Hälfte davon Abgrenzung: Der Empfänger kann fremde
Vokabeln **nicht** ändern, **nicht** löschen, das Kapitel **nicht** umbenennen
und **nicht weiterteilen** (sonst wanderte eine Freigabe unbemerkt weiter und
der Eigentümer wüsste nicht mehr, wer sein Kapitel sieht). Ein unbeteiligter
Dritter sieht nichts. Nach dem Aufheben ist der Zugriff sofort weg – auch für
die Audiodateien.

Live durchgespielt: Andi teilt sein dänisches Kapitel mit Friederike, sie sieht
die Vokabeln und die Herkunft, der Trainer liefert sie, danach wieder
aufgehoben. Die Testfreigabe habe ich anschliessend entfernt – ob wirklich
geteilt wird, ist Andis Entscheidung.

198 Tests grün.

---

## 2026-08-07 – portal-v143: Mein Fehler – die CSP blockierte JEDE Audiowiedergabe

Andi meldete: „es wird kein Audio ausgegeben, weder am PC noch auf dem iPhone".
Das war kein Nebeneffekt der Sprachangabe von eben, sondern ein Fehler, den ich
**zwei Auslieferungen vorher** eingebaut hatte.

### Was passiert ist

- **v125** (Wunsch #142, Stufe 5) schaltete die strenge CSP scharf.
- **v126** (Wunsch #136) stellte die Wiedergabe von `new Audio(url)` auf
  `fetch()` + `URL.createObjectURL(blob)` um – nötig, um ein aufgebrauchtes
  Kontingent als HTTP 429 sauber melden zu können.

Die CSP hatte kein eigenes `media-src`, also griff `default-src 'self'`. Eine
`blob:`-Adresse ist davon **nicht** gedeckt. Ergebnis: Die Datei wurde erzeugt,
korrekt ausgeliefert – und vom `<audio>`-Element mit Fehlercode 4 abgelehnt.
Ohne sichtbare Meldung, auf **allen** Geräten, seit zwei Wochen.

Behoben mit `media-src 'self' blob:`.

### Was das über meine Diagnose von #149 sagt

Andis Meldung „Dänisch funktioniert nicht" war mit hoher Wahrscheinlichkeit
**genau dieser Fehler** – und nicht das, was ich untersucht habe. Er hatte an
dem Tag Dänisch getestet; die Audiodateien entstanden dabei auch brav im
Cache. Nur zu hören war nichts.

Die fehlende Sprachangabe, die ich stattdessen gefunden und behoben habe, war
trotzdem ein echter Defekt – aber sie war nicht sein Problem. Ich habe die
Meldung zu schnell auf die interessantere Erklärung geschoben, statt zuerst
die banale zu prüfen: *kommt überhaupt Ton heraus?* Der Server-seitige Test
(„Datei wird erzeugt, ist gültiges WAV") hat mich darin bestätigt, obwohl er
über die Wiedergabe nichts aussagt.

### Warum es so lange unsichtbar blieb

Drei Dinge kamen zusammen:

1. Der Fehler tritt **nur bei scharfer CSP** auf – beim Entwickeln steht
   `CSP_MODUS=aus`, dort funktioniert alles.
2. Er erzeugt **keine Server-Fehlermeldung**: Aus Sicht des Portals wurde die
   Datei erfolgreich ausgeliefert (HTTP 200).
3. Die Wiedergabe scheitert **stumm** – `play()` lehnt ab, das Ergebnis landet
   in einem `console.warn`, das niemand liest.

Genau das Muster, das in dieser Sitzung schon dreimal Thema war. Diesmal habe
ich es selbst gebaut.

### Was daraus folgt

Zwei Regressionstests: `media-src` muss existieren und `blob:` enthalten – in
**jedem** Modus, auch im Beobachtungsmodus (sonst meldete die Report-Only-Regel
jeden Abspielversuch als Verstoss und verdeckte echte Funde).

Nachgeprüft, ob noch etwas anderes über `blob:`/`data:` läuft: nur die zwei
Audio-Stellen (`vokabeln.html`, `vokabel_training.html`), beide jetzt gedeckt.
`data:` für Bilder war schon erlaubt (QR-Code aus Stufe 6).

Im Browser gegengeprüft: vorher sofort Fehlercode 4, jetzt kein Fehler mehr und
`networkState: 2` (lädt normal). Dass es hörbar ist, kann nur ein sichtbares
Fenster zeigen – das Chrome hier meldet sich als verborgen.

182 Tests grün.

---

## 2026-08-07 – portal-v141: Wünsche #149 (Dänisch klang falsch) und #148 (Audio erkennbar)

### #149 – die Meldung stimmte, die Vermutung nicht

Gemeldet war: „Kann es sein, dass Dänisch für die Audio-Wiedergabe nicht
funktioniert?" Die Prüfung ergab: **technisch funktionierte alles.** Für
Dänisch lagen fünf Dateien im Cache, erzeugt am selben Tag, gültiges WAV,
24 kHz mono, rund eine Sekunde – dieselben Werte wie bei Englisch. Auch
Modell und Stimme waren identisch konfiguriert.

Falsch war die **Aussprache**. Ans Modell ging bis dahin nur der nackte Text:

```
{"model": "...", "input": "God morgen", "voice": "Kore"}
```

Kein Wort über die Sprache. Bei „Hej", „ja" oder „God morgen" muss das Modell
raten – und rät bei einer kleinen Sprache naheliegenderweise auf Englisch.
Bei Englisch fiel das nie auf, weil die Vermutung dort zufällig stimmt.

**Behoben** durch eine vorangestellte Sprachangabe: `Sprich auf Dänisch: God
morgen`. Gemini-TTS versteht eine Anweisung vor dem Doppelpunkt als Stil- bzw.
Sprachvorgabe und spricht sie nicht mit.

Das habe ich nicht geglaubt, sondern gemessen: Eine Anweisung aus **13
Wörtern** verlängerte das Ergebnis um **0,16 Sekunden**. Mitgesprochen wären
es rund fünf gewesen. Vorher hatte ich noch geprüft, ob es einen sauberen
Parameter gibt – `language: "da"` wird zwar ohne Fehler angenommen, ist aber
im OpenAI-kompatiblen Sprach-Endpunkt gar nicht vorgesehen und wird
höchstwahrscheinlich still verworfen. Deshalb der dokumentierte Weg über die
Eingabe.

Der Sprachname kommt aus der Datenbank, **nicht** aus einer Zuordnungstabelle
im Code: So funktioniert es auch für Sprachen, die später jemand selbst
anlegt, ohne dass hier etwas nachgepflegt werden muss.

**Der Cache musste entwertet werden.** Die vorhandenen Dateien sind technisch
einwandfrei und klingen trotzdem falsch – ohne Änderung am Schlüssel wären sie
ewig weiterverwendet worden und der Fehler wäre behoben, aber weiter hörbar
gewesen. Der Schlüssel trägt jetzt ein `v2:`. Die alten Dateien werden nicht
gelöscht; sie fallen einfach heraus und kosten etwas Plattenplatz.

Das Kontingent zählt weiterhin den **reinen** Text, nicht die Anweisung – sonst
würde jede Vokabel plötzlich das Dreifache kosten, nur weil wir dem Modell
etwas dazusagen.

Live nachgemessen: Abruf liefert 200 und legt eine neue Datei unter dem
v2-Schlüssel an; der Verbrauch stieg um 10 Zeichen („God morgen"), nicht um
die Länge der Anweisung.

**Was ich nicht prüfen kann:** wie es klingt. Das muss ein Ohr beurteilen.

### #148 – erkennbar, wo die Aussprache schon bereitliegt

Der 🔊-Knopf ist jetzt blass, solange es die Datei nicht gibt, und voll
sichtbar, sobald sie vorliegt. Nach dem ersten Anhören schlägt er sofort um,
ohne Neuladen – sonst bliebe er blass, obwohl die Aussprache längst da ist.

Die Auskunft kommt aus dem **Dateisystem**, nicht aus einem Merker in der
Datenbank: Der Cache ist die Wahrheit. Ein Merker könnte davon abweichen –
etwa nach der gerade beschriebenen Entwertung – und würde dann zuverlässig das
Falsche anzeigen.

Bewusst über die Deckkraft statt über ein zweites Symbol: Die Zeile bleibt
ruhig, der Unterschied ist trotzdem auf einen Blick da.

180 Tests grün (10 neu).

---

## 2026-08-07 – portal-v139: Wunsch #143 – Barcode scannen

Kamera aufs Produkt, Name und Kategorie erscheinen, Nutzer prüft und speichert.

### Erst gemessen, dann gebaut

Zwei Unbekannte standen am Anfang, und beide haben den Entwurf verändert:

**1. Die Browser-Schnittstelle `BarcodeDetector` ist unbrauchbar.** Sie fehlt
nicht nur auf iOS (den Geräten, mit denen tatsächlich eingekauft wird) –
nachgemessen fehlt sie **auch in Chrome unter Windows**. Damit schied der
naheliegende Weg aus. Die Alternative wäre eine mitgelieferte
JavaScript-Bibliothek von einigen hundert Kilobyte gewesen.

Stattdessen wird **serverseitig aus einem Foto gelesen** (`zxing-cpp`). Das
nutzt das im Projekt längst etablierte Muster – Rezept- und
Vokabel-Foto-Import verwenden dasselbe `<input type="file" accept="image/*">` –
funktioniert auf jedem Gerät und braucht keinen Fremdcode im Browser.
Bewusst **ohne** `capture="environment"`: Das Attribut zwingt iOS Safari
direkt in die Kamera und unterschlägt die Auswahl „Mediathek" (Wunsch #106,
dort schon einmal zurückgebaut).

**2. Die Produktdatenbank taugt.** Mein erster Test mit fünf aus dem Gedächtnis
geratenen EANs fand nur eines von fünf – das sagte aber nichts über die
Abdeckung, sondern nur über meine erfundenen Nummern. Mit **echten** Codes aus
Open Food Facts: alle gefunden, mit Name, Marke, Menge und Kategorien.
Deutschland allein hat dort rund **420.000 Produkte**.

Zwei neue Abhängigkeiten, exakt gepinnt (Regel aus #135): `zxing-cpp==3.1.1`
und `pillow==12.3.0`, zusammen rund 9 MB, reine Wheels ohne System-Pakete.
Der Container liegt danach bei 53 MB von 256 MB.

### Ein echter Fund beim Testschreiben

Der Barcode landet in der Adresse der Produktabfrage, wird also gegen
`^[0-9]{6,14}$` geprüft. Der Test mit einer Liste böser Eingaben fiel durch:

> **In Python passt `$` auch VOR einem abschließenden Zeilenumbruch.**

`"4008400401621\n"` wäre also durch die Prüfung gerutscht und mitsamt Umbruch
in die URL geraten. Behoben mit `\A…\Z`. Aufgefallen beim Schreiben des
Tests, nicht beim Schreiben des Codes – genau dafür schreibt man sie.

### Wenn etwas fehlt, bricht nicht alles ab

Die KI-Kategorie ist eine **Zutat, keine Voraussetzung**: Ist das Kontingent
aufgebraucht oder die KI nicht erreichbar, kommt der Produktname trotzdem, und
der Nutzer wählt die Kategorie selbst. Ebenso bei einem unbekannten Produkt –
dann wird der erkannte Code zurückgegeben und der Name von Hand eingetippt,
statt die Erfassung ganz abzubrechen.

Die KI bekommt die **vorhandenen** Kategorien vorgegeben, und die Antwort wird
gegen diese Liste geprüft. Ein frei erfundener Name wäre wertlos – er passt zu
keiner Zeile in `einkauf_kategorien` – und würde still zu einer falschen
Einsortierung führen. Bei Unsicherheit bleibt es bei „Sonstiges".

Gespeichert wird **nichts** von allein: Das Ergebnis füllt nur das bestehende
Formular vor, genau wie beim Rezept-Import und wie im Wunsch beschrieben.

### Verifikation am echten Server

- Echtes EAN-13-Bild → `4008400401621` → „Nutella (750g)" → **Trockenvorrat**
- Zweites Produkt → **Tiefkühl** (Hähnchen-Schnitzel) – die Einsortierung
  trifft also nicht bloß zufällig
- Unbekannter Code → Code kommt zurück, mit dem Hinweis, den Namen einzutippen
- Bild ohne Barcode → „Nochmal näher und gerader fotografieren?"
- Falscher Dateityp und fehlendes Foto → 400, ohne Zugang → 403

170 Tests grün (14 neu). `python-barcode` steht nur in `requirements-dev.txt`:
im Betrieb wird gelesen, nicht erzeugt.

**Offen für Andi:** einmal im Laden ausprobieren. Der Weg über ein Foto ist
etwas anderes als ein Live-Sucher – das ist der Preis dafür, dass es auf dem
iPhone überhaupt geht.

---

## 2026-08-07 – portal-v137: Wunsch #145 – neue App „Geburtstage"

Gemeinsame Liste, persönliche Einstellungen. Slug `geburtstage`, Modul
`23_geburtstage.py`, Auto-Grant für alle (wie hilfe/einkauf) – Geburtstage
sind Familiensache.

### Was pro Nutzer gilt und was nicht

Der Wunsch trennt das ausdrücklich: **Eingetragen wird für alle, eingestellt
für sich.** Ausblenden, Erinnerung am Tag und Vorlauf-Erinnerung stehen
deshalb in `geburtstag_einstellungen` mit `(user_id, geburtstag_id)` als
Schlüssel. Eine fehlende Zeile heißt schlicht „Standard" – sichtbar, keine
Erinnerung.

Die beiden Erinnerungen sind **unabhängig** voneinander, wie verlangt: nur der
Tag, nur der Vorlauf, beides oder nichts. Der Vorlauf ist eine freie Zahl
(1–60 Tage), damit „drei Tage vorher, um zu backen" genauso geht wie „vier
Wochen vorher, um etwas zu bestellen".

Löschen betrifft alle und ist deshalb auf Urheber, Eltern und Admin begrenzt.
Wer einen Eintrag nur selbst nicht sehen will, blendet ihn aus – die
Sicherheitsabfrage sagt das auch so.

### Tag und Monat als Zahlen, Jahr freiwillig

Ein Geburtstag wiederholt sich jährlich, und das Geburtsjahr ist oft unbekannt
(Nachbarn, Bekannte). Deshalb `tag`/`monat` als Zahlen und `jahr` als
optionales Feld statt eines Datums. Mit Jahr wird angezeigt, welchen
Geburtstag die Person feiert; ohne Jahr eben nicht.

**Der 29. Februar** ist der Fall, den man vergisst: In drei von vier Jahren
gibt es ihn nicht. `_tage_bis()` weicht dann auf den 1. März aus – die in
Deutschland übliche Handhabung, und deutlich besser als „fällt dieses Jahr
aus". Vier Tests decken das ab, dazu der Jahreswechsel (am 30.12. ist der 2.1.
in drei Tagen, nicht in minus 362).

### Wo der tägliche Lauf sitzt – und warum nicht in `util`

`util` ist eigentlich der Ort für Zeitgesteuertes. Die Erinnerungen laufen
trotzdem im Portal, in einem Hintergrund-Thread. Grund: `push_send()` und die
VAPID-Schlüssel liegen im Portal. In `util` müssten entweder die Schlüssel
dupliziert werden (zwei Orte für dasselbe Geheimnis) oder es bräuchte einen
zusätzlichen, abgesicherten HTTP-Endpunkt zwischen den Containern. Beides sind
mehr bewegliche Teile – und bewegliche Teile fallen still aus, was in dieser
Sitzung schon dreimal das Thema war.

Der Thread ist unkritisch, weil Gunicorn hier mit **einem** Worker läuft: genau
ein Thread, keine Doppelversendung. Gegen Wiederholung nach einem Neustart
schützt zusätzlich `geburtstag_gesendet` – verschickt wird nur, was für heute
noch nicht vermerkt ist. Live gegengeprüft: zweiter Lauf am selben Tag
verschickte 0.

Schalter `GEBURTSTAGS_ERINNERUNGEN` (Default 1), im Test immer 0.

### Zwei Fehler beim Bauen – beide von den Tests gefunden

**1. `database is locked`.** Der Hintergrund-Thread schrieb während der Tests
nebenher in dieselbe SQLite-Datei. Ein Test, der zufällig gegen einen Thread
läuft, ist kein Test, sondern ein Würfelspiel – daher der Schalter.

**2. Die eigentliche Ursache war eine andere**, und der erste Befund hätte
mich fast in die Irre geführt: `DELETE FROM users` scheiterte an einer
FOREIGN-KEY-Verletzung, weil `geburtstage.erstellt_von` auf `users` zeigte
**ohne** Löschregel. Das „locked" war nur die Folgeerscheinung. Behoben mit
`ON DELETE SET NULL`, nicht CASCADE: Der Geburtstag von Oma gehört der
Familie, nicht demjenigen, der ihn zufällig eingetippt hat. Verlässt jemand
das Portal, bleibt der Eintrag und nur die Urheberschaft wird vergessen –
dasselbe Muster wie bei `wuensche`.

### Der Emoji-Wächter hat sich sofort bezahlt gemacht

Beim Schreiben des Hilfe-Kapitels schlug `test_emoji.py` an: 🙈 fehlte im
Bündel. Wenige Stunden nach seiner Einführung hat der Test also genau den
Fehler verhindert, für den er gebaut wurde – diesmal, bevor er jemandem
auffiel. (Ebenso vorab: 🎂 🎈 🎁 für die neue App.)

### Verifikation

Live gegen den Server: zwei Einträge angelegt (einer mit Jahr → „wird 76",
einer heute → 🎉-Markierung), von einem zweiten Konto gesehen; Andi setzte
Erinnerung + 7 Tage Vorlauf, Simone blendete denselben Eintrag aus – beides
wirkte nur beim jeweiligen Nutzer. Erinnerung tatsächlich verschickt (Push kam
an), zweiter Lauf 0. Testdaten entfernt, Kaskaden räumten Einstellungen und
Vermerke mit ab. Regression 53/53.

156 Tests grün (19 neu).

---

## 2026-08-07 – portal-v135/v136: Wünsche #146 (Live-Liste) und #147 (fehlende Icons)

### #147 – neun fehlende Icons, nicht eines

Gemeldet war: „Das Icon vom Kassenbuch lädt nicht unter Linux." Die Prüfung
über alle Vorlagen und alle App-Emoji ergab **neun** fehlende
Twemoji-Grafiken – acht davon aus den Änderungen der Tage davor, alle
unbemerkt: 🆘 🏁 🐷 👀 📥 📲 🔑 🔖 🧾.

`twemoji.parse()` ersetzt jedes Emoji durch ein lokal gebündeltes SVG. Fehlt
die Datei, bleibt unter Linux/Chrome eine leere Kachel – unter iOS/macOS
springen dagegen oft die System-Emoji ein, weshalb es dort nicht auffällt.
Genau deshalb konnte sich das ansammeln.

`server.md` warnte bereits ausdrücklich davor (Stolperfalle aus Wunsch #122,
◀ ▶). Die Warnung hat es nicht verhindert – **eine Warnung in der
Dokumentation ist kein Wächter.** Der eigentliche Auftrag des Wunsches
(„merk dir das für die Zukunft") ist deshalb als Test umgesetzt:
`tests/test_emoji.py` prüft jedes in Vorlagen und Code verwendete Emoji sowie
jedes App-Emoji aus der Datenbank gegen das Bündel. Gegengeprüft: ohne die
Datei schlägt er an.

Zwei Sicherungen gegen einen Test, der stillschweigend nichts prüft: das
SVG-Verzeichnis muss existieren und mehr als 50 Dateien haben, und es müssen
mehr als 100 Emoji gefunden werden.

### #146 – die Liste aktualisiert sich jetzt wirklich live

Vorher gab es den Mechanismus schon (Wunsch #100), aber mit genau den zwei
Lücken, die der neue Wunsch benennt: Takt **30 Sekunden** statt 10, und der
**Einkaufsmodus war ausdrücklich ausgenommen** – aus gutem Grund, denn ein
`location.reload()` mitten im Laden hätte Scrollposition, Modus und die
5-Sekunden-Rücknahme zerrissen.

Die Lösung ist deshalb nicht „Guard entfernen und Takt runter", sondern: **es
wird gar nicht mehr neu geladen.** Die Seite wird erneut vom Server geholt und
nur der Container `#einkauf-liste` ersetzt.

Warum so und nicht per JSON + Neuaufbau im Javascript:
- Die Darstellung bleibt an **einer** Stelle (den Jinja-Vorlagen). Eine zweite
  Render-Logik im Frontend würde früher oder später auseinanderlaufen.
- Die Knöpfe in den frischen Karten funktionieren **sofort**, weil sie seit
  Wunsch #142 am delegierten Verteiler in `base.html` hängen und nicht an
  eigenen Listenern. Der CSP-Umbau zahlt sich hier unerwartet aus.

Nach dem Austausch werden Marktfilter (Einkaufsmodus) bzw. der normale Filter
wieder angewandt – die frischen Karten wissen davon nichts.

Es wird bewusst **nicht** ausgetauscht, solange etwas Eigenes in der Schwebe
ist: offene Eingabe, laufende 5-Sekunden-Rücknahme (`PENDING_MOVE`), oder eine
noch nicht übertragene Offline-Aktion. Sonst verschwände die eigene Arbeit
unter dem Finger.

**Live im Browser nachgemessen**, im aktiven Einkaufsmodus: Kartenzahl 11 → 12,
Einkaufsmodus weiter aktiv, Leiste sichtbar, Scrollposition unverändert
(300 px), kein Neuladen (`performance.now()` lief durch).

**Beinahe-Fehler:** Ich hatte die Funktion zum Auslesen der Offline-Warte-
schlange aus dem Gedächtnis `ladeWarteschlange()` genannt – sie heißt
`holeWarteschlange()`. Das wäre ein `ReferenceError` im 10-Sekunden-Takt
gewesen, der die Synchronisierung still lahmgelegt hätte. Beim Nachsehen im
Quelltext aufgefallen, nicht beim Testen.

### Nebenbei: ein verschwundener Zugang

Die Regression nach der Auslieferung meldete 49/50 statt 50/50 – Andis
Tierbaukasten-Zugang fehlte. Nachgeprüft: Nur `revoke_app` löscht Grants, also
ein bewusster Klick auf einen Grant-Chip in der Verwaltung. Das passt zu
**S5-11** („Verwaltung: App freischalten"): Ein Klick auf einen *aktiven* Chip
entzieht die App. Beim Durchprobieren der Chips ist der Zugang wohl abgeschaltet
und nicht wieder eingeschaltet worden. Kein Code-Fehler; wiederhergestellt.

Erwähnenswert ist es trotzdem: Genau dafür läuft die Regression nach jeder
Auslieferung. Ohne sie wäre der fehlende Zugang erst aufgefallen, wenn jemand
den Tierbaukasten gesucht hätte.

137 Tests grün.

---

## 2026-08-07 – portal-v133/v134: Push-Test-Werkzeug – und ein jahrelang unbemerkter Fehler

Andi fragte, wie sich prüfen lässt, ob Push-Benachrichtigungen ankommen (S6-06
im Prüfplan). Ein Werkzeug dafür gab es nicht – man hätte jemandem eine echte
Aufgabe zuweisen müssen. Jetzt gibt es zwei Befehle:

```
docker exec portal python manage.py listpush            # welche Geräte sind angemeldet
docker exec portal python manage.py testpush 1 "Text"   # Testmeldung an einen Nutzer
```

`testpush` verschickt bewusst **dieselbe Ziel-Adresse** wie eine echte
Aufgaben-Benachrichtigung (`/a/todo/`, token-frei) – sonst prüfte der Test
etwas anderes als den Ernstfall. Und es meldet die Zustellung **je Gerät
einzeln**. Genau das hat den Fehler unten sichtbar gemacht.

### Push an Windows/Edge ist seit jeher still gescheitert

Der erste Testlauf: zwei iPhones zugestellt, das Windows-Gerät **HTTP 400**.
Die Antwort von Microsofts Push-Dienst war eindeutig:

```
X-WNS-ERROR-DESCRIPTION: Ttl value conflicts with X-WNS-Cache-Policy.
X-WNS-STATUS: dropped
```

`pywebpush` schickt ohne `ttl`-Argument **TTL 0**. Apple und Google stört das
nicht, Microsofts WNS lehnt es ab und verwirft die Nachricht. Gegengeprüft:
derselbe Aufruf mit `ttl=86400` wurde sofort zugestellt.

Behoben mit `PUSH_TTL = 86400` (ein Tag – eine zugewiesene Aufgabe ist auch am
Abend noch interessant, länger nicht) in `push_send()` und in `testpush`.

**Warum das niemandem aufgefallen ist:** Auf den vier iPhones der Familie kamen
die Meldungen an. Nur der Windows-Rechner bekam nie eine – und `push_send()`
protokolliert einen Fehlschlag lediglich per `log.warning`, ohne dass ihn
jemand liest. Ein Fehler, der nur ein Gerät betrifft und sich als "da kommt halt
nichts" äußert, wird nicht gemeldet, sondern hingenommen.

Das ist derselbe Fehlertyp wie schon zweimal in diesem Umbau: etwas scheitert
still. Deshalb gibt `testpush` die Zustellung je Gerät aus, statt nur "fertig"
zu melden.

### Der Windows-Zugang muss neu angemeldet werden

Nach dem Fix kam vom Windows-Gerät **HTTP 410 (Gone)** – der Push-Kanal selbst
ist inzwischen abgelaufen (WNS-Kanäle verfallen, wenn sie länger nicht
erneuert werden). Der Code hat das Abo daraufhin korrekt entfernt, wie
`push_send()` es auch tut.

Für Andi heißt das: Auf dem Windows-Rechner das Portal öffnen und
Benachrichtigungen einmal neu aktivieren. Erst dann lässt sich belegen, dass
Windows-Push jetzt wirklich funktioniert – der Fehler ist behoben, das Gerät
aber noch nicht wieder angemeldet.

### Drei neue Tests

- `test_push_setzt_eine_ttz_groesser_null` – der eigentliche Wächter.
  Gegengeprüft: ohne `ttl` schlägt er an.
- `test_push_ohne_vapid_key_versendet_nichts` – die Testumgebung hat keinen
  Schlüssel, da darf nichts rausgehen und nichts krachen.
- `test_push_zieladresse_ist_tokenfrei` – Stufe 6: Stünde in der
  Benachrichtigung wieder ein Token, landete er über diesen Weg erneut
  außerhalb des Portals.

132 Tests grün. Ausgeliefert als v133/v134.

---

## 2026-08-07 – portal-v131: Wunsch #140, Stufe 6 – Tokens nur noch als Prüfsumme

Letzte der sechs Stufen. `token_enc` ist aus `grants` verschwunden; in der
Datenbank steht jetzt **nur noch der HMAC**. Damit ist eingelöst, was Wunsch
#129 eigentlich wollte und damals nicht konnte – die Navigation brauchte den
Klartext zurück, weil `base.html` den ⌂-Knopf und den Hilfe-Link daraus baute
und die Startseite jede Kachel. Seit Stufe 4 sind alle Adressen token-frei,
also wird er nirgends mehr gebraucht.

**Die Zusage steht:** alle 54 Grants übernommen, alle `token_lookup`
unverändert – jeder bereits verteilte Link funktioniert weiter. Nachgemessen:
50/50 alte Token-Adressen liefern 200.

### Was jetzt anders ist

Ein Zugangslink ist **nur im Moment seiner Erzeugung sichtbar**. Danach kann
ihn niemand mehr nachschlagen, auch kein Admin. Die Verwaltungsseite rendete
bisher die Zugangsadressen der ganzen Familie im Klartext – und der Service
Worker cachte sie mit. Das war ein eigener Befund aus der Sicherheitsanalyse
und ist damit erledigt; live gegengeprüft: kein einziger Token mehr in der
ausgelieferten Seite.

Neu ist `admin_zugang.html`: eine Seite, die genau einen frisch erzeugten
Zugang zeigt – Link, QR-Code, Kopierknopf, mit deutlichem Hinweis „Nur jetzt
sichtbar". Sie erscheint beim Anlegen eines Nutzers und bei „Neuer Zugang +
QR" (vormals „Zugänge neu", Wunsch #131).

**Der QR-Code steckt als `data:`-URI in der Seite.** Die alte Route
`/a/admin/.../qr.svg` musste den Token aus der Datenbank holen – genau das
geht nicht mehr; sie ist ersatzlos entfallen (jetzt 404). Dass das Bild trägt,
verdankt sich `img-src 'self' data:` aus Stufe 5.

Bewusst **kein Redirect** nach dem Erzeugen: Ein Redirect müsste den Token
weiterreichen – über die Adresszeile (landet im Verlauf, das wollten wir
gerade abschaffen) oder über die Flask-Session (schriebe ihn in ein Cookie).
Die Antwort auf den POST selbst ist der einzige Ort, an dem er sonst niemandem
begegnet.

### Zwei Abhängigkeiten, die beinahe untergegangen wären

**Push-Benachrichtigungen.** `04_todo.py` baute die Ziel-Adresse einer
Push-Nachricht aus dem entschlüsselten Token des Empfängers. Ohne Anpassung
hätte jede Aufgaben-Benachrichtigung ins Leere gezeigt. Jetzt zeigt sie auf
`/a/todo/` – token-frei, das Gerät weist sich über sein Cookie aus. Das ist
sogar richtiger als vorher: Eine Push-Nachricht wird auf genau dem Gerät
geöffnet, das die Anmeldung ohnehin besitzt.

**`manage.py`.** `listusers` druckte die Zugangsadresse jedes Nutzers, und
`_make_grant()` holte bei einem bereits bestehenden Grant den alten Token
zurück. Beides geht nicht mehr. `listusers` zeigt jetzt die Zahl der
App-Zugänge, und `_make_grant()` gibt `None` zurück, wenn der Grant schon
existierte – `grant` sagt das dann auch, statt eine Adresse zu drucken, die
gar nicht gilt.

### Ehrlich: Stufe 6 verbrennt den Notausstieg von Stufe 4

`TOKENFREIE_URLS=0` stellte bis gestern den Zustand von vorher vollständig
wieder her. Das kann der Schalter nicht mehr – es gibt keine Klartext-Tokens,
die man in Links einsetzen könnte. Was er weiterhin tut: `/p/<token>` leitet
nicht mehr auf `/start` um. Als Rückfallebene genügt das, weil ein Pfad-Token
unverändert Vorrang hat und jede token-freie Adresse über das Cookie trägt.

Der Test dazu wurde nicht stillschweigend gelockert, sondern umbenannt und mit
dieser Begründung versehen (`test_notausstieg_leitet_nicht_mehr_um_aber_
verlinkt_token_frei`). Wer eine echte Rücknahme von Stufe 4 braucht, muss die
Datenbanksicherung von vor Stufe 6 einspielen:
`/data/portal-vor-stufe6.db`.

### Vorgehen: erst messen, dann anfassen

Die Stufe ist als einzige nicht per Schalter rückrollbar, deshalb in dieser
Reihenfolge:

1. **Sicherung** der Produktionsdatenbank über die SQLite-Backup-API (nicht
   per Dateikopie – bei aktivem WAL wäre die inkonsistent).
2. **Probelauf** auf einer Kopie mit einem eigenen Skript: 54/54 Grants
   übernommen, **54/54 alte Klartext-Tokens lösten danach weiterhin auf**,
   keine FK-Verletzungen, nach `VACUUM` kein Geheimtext-Rest mehr in der Datei.
3. **Zweiter Probelauf mit dem echten Code** (nicht dem Skript) gegen eine
   frische Kopie – inklusive echter Anmeldungen von Andi und Friederike über
   ihre bestehenden Links. Erst danach ausgeliefert.
4. Nach der Auslieferung: Regression, Verwaltungsseite auf Token-Reste
   geprüft, einen Zugang tatsächlich neu erzeugt und den angezeigten Link
   ausprobiert (an einem eigens angelegten Testnutzer, nicht an einem echten
   Konto – danach wieder entfernt).

Die `.env`-Kopie, die der Probelauf im Container brauchte, wurde anschliessend
gelöscht; sie enthält den TOKEN_KEY.

### Testnetz: 118 → 129

Neu `test_zugang_einmalig.py` (11 Tests): Verwaltung zeigt keine fremden
Zugänge, token-frei überhaupt keine; die QR-Route existiert nicht mehr; der
einmalig angezeigte Link **funktioniert wirklich** (der schlimmste denkbare
Fehler dieser Stufe wäre ein Link, der angezeigt wird, aber nicht trägt – er
fiele erst auf, wenn jemand ausgesperrt ist); der alte Link ist danach tot.

Mehrere bestehende Tests prüften bis gestern das GEGENTEIL des neuen
Verhaltens (`grant()` liefert `home_token`/`hilfe_token`). Sie wurden
umgedreht, nicht gelöscht – mit Begründung im Docstring, damit erkennbar
bleibt, dass die Kehrtwende Absicht war.

**Offen für Andi:** `pruefplan.md`, Stufe 6 – S6-01 bis S6-05.

---

## 2026-08-06 – portal-v129: Wunsch #144 – neue App „Kassenbuch"

Dritter der drei nicht zurückgestellten Wünsche aus diesem Durchgang. Neue
App: Taschengeld-Buchführung je Kind, Slug `kassenbuch`, Modul
`22_kassenbuch.py`.

### Buchhaltungsprinzip statt CRUD

Der Wunsch verlangte wörtlich "ein bisschen wie bei einem Buchhaltungssystem"
- ein Eintrag ist nach dem Speichern UNVERÄNDERLICH, keine Editier-Funktion.
"Löschen" heißt Stornieren: `kassenbuch_eintraege.storniert=1`, die Zeile
bleibt für immer stehen, zählt aber nicht mehr zum Kontostand. Damit sind
"wer hat's angelegt" und "wer hat's storniert" bereits auf der Zeile selbst
protokolliert (`erstellt_von`/`erstellt`, `storniert_von`/`storniert_am`) -
bewusst KEINE separate Änderungs-Historien-Tabelle, die bräuchte es erst,
wenn Einträge auch bearbeitbar wären, was hier nicht verlangt ist.

Der Startbetrag ("beim ersten Starten einen Startbetrag eintragen") ist
selbst ein Eintrag mit `art='start'`, kein Sonderfeld - genau EINER pro Kind,
niemals stornierbar (sonst wäre der gesamte folgende Kontostand rückwirkend
bedeutungslos). Ein zweiter Versuch wird serverseitig ignoriert.

### "Empfänger/Absender (finde da bessere Begriffe)"

Der Wunsch bat wörtlich um einen besseren Begriff. Lösung: EIN Feld `person`
statt zwei Fachbegriffen - die Formular-Beschriftung wechselt clientseitig
zwischen "Von wem?" (Einnahme) und "An wen?" (Ausgabe), abhängig von der
gewählten Art (`kbArtGewaehlt()`).

### Zugriff: Kinder nur ihr eigenes, Eltern/Admin alle - read-only

Jedes Kind sieht ausschließlich sein eigenes Buch; `kind_buch()` lehnt eine
fremde `kid_id` mit 403 ab, geprüft direkt im SQL-`WHERE` (nicht nur in der
Oberfläche versteckt). Eltern/Admin bekommen den App-Grant automatisch (wie
`hilfe`/`einkauf`, über `_auto_grant_all`) und sehen über die Startseite eine
Übersicht aller Kinder mit Kontostand - der Wunsch verlangt ausdrücklich
"auditiert", das setzt eine Aufsichtsmöglichkeit voraus. Sie können jedes Buch
öffnen, aber NICHTS eintragen oder stornieren; live verifiziert: Andi bekommt
403, wenn er versucht, für Friederike zu buchen.

### Live gegen den echten Server verifiziert (Friederikes echtes Konto)

1. Erster Aufruf → nur das Setup-Formular, kein Kontostand
2. Start 15,00 € → Kontostand 15,00 €
3. Einnahme 5,00 € (Oma) + Ausgabe 3,00 € (Eis) → 17,00 €
4. Ausgabe storniert → zurück auf 20,00 €, der Eintrag bleibt sichtbar
   (Badge „storniert"), zählt aber nicht mehr
5. Andi sieht in der Übersicht sofort 20,00 € bei Friederike
6. Andi kann keinen Eintrag für Friederike anlegen (403)
7. Johannes (noch kein Startbetrag) zeigt „noch nicht eingerichtet"

### Testnetz: 100 → 117

17 neue Tests (`test_kassenbuch.py`): Zugriffskontrolle in beide Richtungen,
Start-einmalig-Regel, Saldo-Berechnung, negative/kaputte Beträge werden
verworfen (kein Absturz), Komma UND Punkt als Dezimaltrennzeichen, kein
Nachtragen in die Zukunft, Storno nimmt den Betrag aus dem Saldo, der
stornierte Eintrag bleibt in der Datenbank stehen, der Start-Eintrag ist
NICHT stornierbar, ein Kind kann keinen fremden Eintrag stornieren (auch das
im SQL geprüft, nicht nur clientseitig).

Die bestehenden Wächter-Tests aus den vorigen Stufen liefen ohne Anpassung
mit: der Routen-Zwilling-Test bestätigt, dass jede neue Route ihre
token-freie Form hat, der CSP-Test bestätigt, dass `kbArtGewaehlt` eine
echte Funktion ist und keine Inline-Handler eingeschlichen sind.

Regression: 50/50 alte Token-Links, 0 CSRF-/CSP-Auffälligkeiten im Log.

**Offen für Andi:** Kassenbuch einmal selbst ausprobieren - ist unter dem
Menüpunkt in der App-Übersicht zu finden, kein eigener Prüfplan-Eintrag
nötig (kein Sicherheitswunsch, aber gerne kurz gegenprüfen, ob die
Beschriftungen für die Kinder verständlich sind).

---

## 2026-08-06 – portal-v126/v127: Wünsche #136, #137 und ein CSRF-Fund aus Stufe 2

„Implementiere die Wünsche" – drei offene, nicht zurückgestellte Wünsche
umgesetzt (#136, #137, dazu unten #144 als eigener Eintrag). Zurückgestellt
blieben unangetastet: #51, #130, #138, #139, #143.

### #136 – eigenes Kontingent für die Sprachausgabe

Die TTS-Aussprache der Vokabel-App zählte bisher gar nicht gegen ein Limit -
jedes neu angelegte Wort löste einen kostenpflichtigen Aufruf aus, ohne
Obergrenze. Neu: `users.ki_tts_zeichen_limit` (Default 50000 Zeichen/Monat,
admin-einstellbar wie das bestehende KI-Token-Limit) und eine **eigene**
Tabelle `ki_tts_nutzung`.

Eigene Tabelle statt einer weiteren Zeile in der bestehenden `ki_nutzung`, mit
Absicht: `ki_anfrage()` summiert dort `SUM(tokens)` **ohne** Filter nach
`feature` – das ist genau der Zweck, ein gemeinsames Kontingent über alle
LLM-Funktionen hinweg. TTS-Zeichen in dieselbe Spalte zu schreiben hätte das
Token-Kontingent stillschweigend mit Zeichenzahlen verfälscht. Am echten
Server nachgemessen: nach einem TTS-Aufruf steht der Verbrauch in
`ki_tts_nutzung`, `ki_nutzung` bleibt bei 0.

Protokolliert wird erst NACH einem erfolgreichen Aufruf, auf beiden
Erfolgspfaden (mp3 direkt oder der pcm/wav-Rückfall) - ein Fehlversuch beim
Anbieter darf das Kontingent nicht schmälern (eigener Test dafür).

Frontend: `wortAnhoeren()` in `vokabeln.html`/`vokabel_training.html` holt das
Audio jetzt per `fetch()` statt `new Audio(url).play()` direkt - ein
aufgebrauchtes Kontingent (429) kam vorher lautlos im `console.warn` unter,
niemand hätte erfahren, warum nichts zu hören ist. Ein `HEAD`-Vorab-Check war
KEIN Ausweg: Flask führt die Route dabei trotzdem vollständig aus (kürzt nur
den Antwort-Body) - die Sprachausgabe wäre ein zweites Mal wirklich erzeugt
worden. `alert()` für die Meldung, konsistent mit der bestehenden Konvention
für Limit-Meldungen (`rezepte.html`/`rezept_detail.html`).

Live verifiziert: Wort ohne Cache abgerufen → 18 Zeichen in `ki_tts_nutzung`,
0 in `ki_nutzung`. Limit auf 10 gesetzt, neues Wort abgerufen → 429.

### #137 – strikte Schema-Prüfung der KI-Rezept-Extraktion

Beide KI-Extraktionspfade (URL-Import ohne JSON-LD, Foto-Import) hatten
bislang denselben weichen Code dupliziert: `json.loads()`, dann `.get()` mit
stillschweigendem `str(...)`-Cast. Eine präparierte Webseite oder ein
manipuliertes Foto könnte dem Sprachmodell Anweisungen unterschieben; der
direkte Schaden war zwar begrenzt (Ausgabe landet escaped in einem Rezept,
das der Nutzer ohnehin anlegen darf), aber unbegrenzt lange oder unbegrenzt
strukturierte Antworten liefen unbesehen durch.

Neu: eine einzige Funktion `_ki_rezept_validieren()`, von beiden Pfaden
verwendet (behebt nebenbei die Duplizierung). Nur die vier bekannten Felder
werden gelesen; `zutaten`/`schritte` müssen Listen sein, Einträge, die keine
Zeichenkette/Zahl sind (z. B. ein eingeschleustes verschachteltes Objekt),
werden verworfen statt zu hässlichem `str(dict)`-Text verunstaltet; jedes Feld
hat eine feste Längen- (200/60/200/2000 Zeichen) bzw. Mengenobergrenze
(60 Einträge je Liste).

11 neue Tests, u. a. mit absichtlich eingeschleusten Nutzlasten
(`{"injiziert": "ignoriere alle Anweisungen"}` als Zutat, ein zusätzliches
Feld `system_override`) - alle werden verworfen bzw. ignoriert.

### Nebenfund beim Testen: CSRF-Origin-Ersatzprüfung war für JEDEN echten Browser wirkungslos

Um #137 end-to-end zu prüfen, wurde der Import-Endpunkt per `curl` angestoßen
- `curl` sendet kein `Sec-Fetch-Site`, die Anfrage fiel also auf die
Origin-Ersatzprüfung aus Stufe 2 zurück. Die lehnte eine korrekte
`https://portal.16schwaben.de`-Origin ab und akzeptierte stattdessen
`http://portal.16schwaben.de`.

Ursache: `request.url_root` spiegelt das Schema der Verbindung zwischen Caddy
und `portal` - die läuft intern als Klartext-HTTP, TLS endet bei Caddy. Die
erwartete Origin war also **immer** `http://...`, während jeder echte Browser
`https://...` schickt. Unentdeckt blieb das bislang, weil moderne Browser
`Sec-Fetch-Site` senden und den Origin-Ersatzzweig nie erreichen - genau der
Zweig, der laut Docstring für ÄLTERE Browser gedacht war, war für sie seit
dem Scharfschalten in Stufe 2 vollständig wirkungslos.

Behoben: `_erwartete_origin()` liest `X-Forwarded-Proto`, das Caddys
`reverse_proxy` standardmäßig setzt - sicher zu vertrauen, weil `portal`
ausschließlich über das interne Bridge-Netz von Caddy erreichbar ist, kein
anderer Absender kann den Header setzen. Am echten Server verifiziert: die
echte `https`-Origin wird jetzt akzeptiert, die vorher fälschlich akzeptierte
`http`-Origin jetzt abgelehnt, eine fremde Origin weiterhin abgelehnt. Ein
Regressionstest hält den Fehlerfall fest.

**Praktische Tragweite:** In der Handprüfung von Stufe 2/5 ist das nirgends
aufgefallen, weil alle geprüften Geräte moderne Browser mit `Sec-Fetch-Site`
sind. Betroffen wäre nur ein Browser ohne diesen Header gewesen - am ehesten
ein älteres Safari. `S5-14` (iPhone/Safari) im Prüfplan deckt das ab.

100 Tests grün. Regression: 50/50 alte Token-Links.

**Offen für Andi:** nichts Neues zu prüfen über die laufenden Stufen-5-Tests
hinaus - #136/#137 sind reines Backend bzw. eine kleine, bereits verifizierte
Frontend-Änderung, und der CSRF-Fix stellt nur wieder her, was Stufe 2 schon
versprochen hatte.

---

## 2026-08-06 – portal-v125: Wunsch #142, Stufe 5 – CSP ohne `unsafe-inline`

Fünfte von sechs Stufen. `script-src` erlaubt kein `'unsafe-inline'` mehr;
unsere eigenen Skriptblöcke weisen sich über ein Nonce aus. **Eingeschleuster
Code läuft damit nicht mehr** – vorher lief er so selbstverständlich wie
unserer.

Nachgemessen im Browser, nicht behauptet: ein zur Laufzeit eingefügtes
Inline-Skript ohne Nonce wird blockiert, während alle eigenen Skripte laufen.

### Ein Verteiler statt 59 Einzellösungen

59 `onclick`/`onsubmit`/`onchange`/`oninput`-Attribute in 27 Vorlagen mussten
weg. Statt 59 einzelner `addEventListener`-Blöcke steht in `base.html` **ein**
delegierter Verteiler je Ereignisart:

```html
<button data-klick="toggleKat" data-args='[17]'>
```

Aufrufkonvention: `fn.apply(element, [...args, element, ereignis])`. Damit
passen **alle** bisherigen Signaturen ohne Änderung – `toggleKat(id)` ignoriert
die Zusatzargumente, `spracheWaehlen(this)` bekommt das Element als erstes
Argument, `zutatEinkaufen(id, this)` beides in der richtigen Reihenfolge. Gibt
eine Funktion `false` zurück, wird die Standardaktion unterdrückt – genau wie
beim alten `onsubmit="return …"`.

Das geht nur auf, weil ein Inline-Handler seinen Namen ohnehin nur im globalen
Bereich auflösen kann: **jede Funktion, die heute in einem `onclick` steht, ist
zwangsläufig global.** Deshalb musste keine einzige Funktion umgeschrieben
werden.

Die 11 Löschabfragen wurden zu `data-bestaetigen="…"`, das der Verteiler
auswertet. Damit entfällt die alte `|tojson|forceescape`-Regel an dieser Stelle
vollständig: Der Wert ist jetzt schlichter Attributtext, um dessen Maskierung
Jinjas Autoescaping von selbst kümmert. `server.md` ist entsprechend korrigiert
– sonst widerspräche die Doku dem Code.

Sechs Fälle standen als Ausdruck statt als Aufruf im Attribut
(`window.scrollTo(…)`, `this.form.submit()`, eine `preventDefault`-Kette) und
haben jetzt einen Namen. Einer wurde dabei besser: Die Prüf-Ansicht des
Vokabel-Foto-Imports suchte ihre Zeile über eine hineingerenderte Nummer – über
`closest()` braucht es die gar nicht.

### Warum die CSP jetzt in Flask liegt

Das Nonce muss je Anfrage neu erzeugt und in dieselbe Antwort geschrieben
werden, in der es auch in den `<script>`-Tags steht. Caddy sieht die Vorlage
nicht; ein festes Nonce im Caddyfile wäre wertlos, weil es sich abschreiben
liesse. Die CSP-Zeile im Caddyfile ist deshalb ersatzlos weg – bewusst **keine**
zweite Regel dort, denn zwei CSPs gelten gleichzeitig und im Schnitt, was die
Fehlersuche nur unübersichtlich machte.

`style-src` behält `'unsafe-inline'`. Rund 200 `style="…"`-Attribute umzubauen
wäre ein Vielfaches des Aufwands bei einem Bruchteil des Nutzens: Über
Style-Injektion lässt sich Layout verunstalten, über Script-Injektion alles
tun, was der angemeldete Nutzer darf.

### Beobachtungsmodus – und warum die Null etwas wert ist

Ausgeliefert wurde zuerst mit `CSP_MODUS=beobachten`: die alte Regel gilt
weiter, die strenge geht nur als `Report-Only` mit, Verstösse landen über
`/csp-bericht` im Log. Nach einem Durchgang durch alle Apps: **null Verstösse.**

Eine Null ist aber nur so viel wert wie der Beweis, dass die Messung
funktioniert – dieselbe Falle wie beim Rauchtest, der still übersprang. Also
absichtlich ein Inline-Skript eingeschleust: prompt im Log. Erst danach auf
`scharf`.

### Zwei Wächter, beide gegengeprüft

- `test_keine_inline_handler_mehr` lässt kein neues `onclick=` in die Vorlagen.
- `test_jede_aktion_zeigt_auf_eine_vorhandene_funktion` rendert jede Seite und
  prüft, dass jedes `data-klick` eine Funktion trifft, die es wirklich gibt.
  Ein Tippfehler dort ist sonst kein Ladefehler, sondern ein Knopf, der beim
  Drücken nichts tut – der unangenehmste Fehler, weil ihn niemand meldet.

Beide mussten korrigiert werden, weil sie **Fehlalarme** meldeten:
`btn.onclick = fn` in JavaScript ist völlig in Ordnung (eine aus einem Skript
gesetzte DOM-Eigenschaft blockiert die CSP nicht), und der Erklärkommentar des
Verteilers enthält selbst ein Beispiel-`data-klick`. Beide filtern jetzt
Skriptblöcke heraus. Ein Test, dem man nicht glaubt, wird abgeschaltet.

Anschliessend wurde beiden ein echter Fehler untergeschoben, um zu sehen, dass
sie noch anschlagen. Sie tun es.

83 Tests grün. Regression: 50/50 alte Token-Links, alle vier Nutzer token-frei
durch jede ihrer Apps, null CSRF-Verdachtsfälle.

**Missgeschick am Rande:** `git checkout src/teile/templates/todo.html`, um eine
Testmanipulation zurückzunehmen – und damit den noch nicht committeten Umbau
dieser Datei mit verworfen. Sofort neu erzeugt, aber die Lehre steht: Zum
Zurücknehmen einer Änderung in einer Datei mit ungesicherter Arbeit gehört eine
Kopie, kein `git checkout`.

**Offen für Andi:** `pruefplan.md`, Stufe 5.

---

## 2026-08-06 – portal-v123: Offline-Rückfall auf die Startseite (Nachtrag zu Stufe 4)

Andi meldete nach der Prüfung von S4-10/S4-11: offline kommt **immer** „Keine
Verbindung – diese Seite wurde noch nie geladen". Zwei Ursachen, eine davon
dauerhaft.

**Die dauerhafte:** `/p/<token>` antwortet seit Stufe 4 mit einer 302 auf
`/start`. Eine Navigation hat `redirect: 'manual'`, die Weiterleitung kommt im
Service Worker als *opaqueredirect* an – `resp.ok` ist `false`, sie landet also
**nie** im Cache. Die installierte PWA und jedes alte Lesezeichen starten aber
genau dort. Offline lief damit jeder Start in die Sackgasse, und Benutzen
heilte das nicht: eine 302 wird nie cachebar.

Behoben: Findet der Worker offline nichts zur angefragten Adresse und ist es
eine **Navigation**, liefert er die gecachte `/start`. Nur für Navigationen –
`fetch()`-Aufrufe aus einer Seite erwarten JSON und kämen mit einer
HTML-Startseite nicht klar.

**Die einmalige:** Der Cache-Name wurde in v122 von `portal-cache-v1` auf `v2`
gezogen, um die alten, token-behafteten Einträge loszuwerden. Das war richtig –
gecachte Seiten mit Token in den Links hätten den ganzen Umbau unterlaufen –,
kostet aber je Seite einen Online-Besuch. Genau das sah wie ein Dauerfehler
aus. `v2` bleibt jetzt stehen, ein zweiter Umzug findet nicht statt.

### Wie es gefunden wurde

Nicht durch Nachdenken, sondern durch Messen im Browser: `caches.keys()` war
zunächst komplett leer, die Cache-API selbst funktionierte aber (Probe-Eintrag
liess sich schreiben). Nach einem Reload lagen `/start`, `/a/einkauf/` und der
Nutzer-Merker drin – die Speicherung war also intakt. Erst der Blick auf die
Liste der gecachten Pfade zeigte: **kein einziger `/p/`-Eintrag**, obwohl
genau diese Adresse der Einstiegspunkt ist.

Die erste Vermutung (`Vary: Cookie` verhindert das Cache-Matching) war falsch
und liess sich in einem Zug widerlegen: die Antworten tragen weder `Vary` noch
ein störendes `Cache-Control`.

**Was von hier aus nicht prüfbar war:** ein echter Offline-Zustand. Eine
fehlgeschlagene Anfrage lässt sich nicht erzeugen, ohne die eigene Verbindung
zu kappen; ein gestoppter Container liefert 502, also eine *Antwort*, und
durchläuft den Fehlerzweig gar nicht. Verifiziert sind die beiden Tatsachen,
aus denen sich das Verhalten ergibt: `/p/<token>` ist nie im Cache,
`caches.match('/start')` liefert 200. Der eigentliche Offline-Test ist S4-12.

---

## 2026-08-06 – portal-v120/v121: Wunsch #140, Stufe 4 – der Token ist aus der Adresse verschwunden

Vierte von sechs Stufen und die grösste: 90 Routen, 87 Vorlagen-Links, 26
JS-Pfade. Seit dieser Auslieferung steht in keiner ausgelieferten Seite mehr
ein Zugangstoken – weder in der Adresszeile noch in einem Link.

**Die Zusage bleibt:** Jeder alte Link mit Token funktioniert unverändert.
Nachgemessen, nicht behauptet: alle 50 Zugänge über ihre echte App-Adresse,
50 × HTTP 200.

### Wie es gebaut ist

Jede Route hat jetzt zwei Regeln – die alte mit `<token>` und eine
token-freie Zwillingsregel über `defaults={"token": None}`. Beide landen in
derselben View-Funktion; `grant()` entscheidet wie seit Stufe 3, ob der Pfad-
Token oder das Cookie zählt. **Keine einzige View-Funktion musste angefasst
werden.**

Die Adressen bauen die Vorlagen aus vier Bausteinen im Kern, und nur daraus:

| Baustein | wofür |
|---|---|
| `tp` | das Wegstück in der *gerade offenen* App: `/a/todo{{ tp }}neu` |
| `app_pfad(slug, token)` | Links in eine *andere* App (Startseite-Kacheln, Hilfe-Knopf) |
| `start_pfad(home_token)` | der ⌂-Knopf |
| `manifest_pfad(home_token)` | das PWA-Manifest |

`tp` kommt aus `request.view_args`, **nicht** aus der Template-Variablen
`token`. Das ist wichtig: Die Links sollen der Adresszeile folgen, und
`view_args` sagt genau, was dort steht.

Alle vier liefern die alte Form mit Token zurück, sobald `TOKENFREIE_URLS=0`
steht. Das ist der Notausstieg – und er ist getestet
(`test_notausstieg_stellt_token_links_wieder_her`), weil ein ungeprüfter
Schalter keine Rückfallebene ist, sondern ein Versprechen.

### Vier Dinge, die beinahe still kaputtgegangen wären

**1. Das halbe Menü wäre verschwunden.** `base.html` blendete Hamburger-Knopf
und Menü über `{% if token %}` ein. Token-frei ist `token` leer. Die
Bedingung meinte nie den Token, sondern „wir wissen, wer da ist" – jetzt
steht dort `{% if user %}`.

**2. `const TOKEN` wäre wörtlich `'None'` geworden.** Jinja rendert `None` als
die Zeichenkette „None". Die vier Endpunkte, die den Token im JSON-Body
erwarten (`/wunsch`, `/push/subscribe`, `/push/unsubscribe`,
`/settings/darkmode`), hätten „None" als Token bekommen, nicht aufgelöst –
und weil ein *angegebener* Token bewusst nicht aufs Cookie zurückfällt, wäre
die Folge ein stilles 403 gewesen. Der Dark-Mode-Schalter hätte einfach
nichts mehr getan, ohne Fehlermeldung. Diese vier Endpunkte laufen jetzt über
den neuen Helfer `aktueller_nutzer()`, der wie `grant()` aufs Cookie
zurückfällt. Der Helfer stand schon im Plan für Stufe 2 und war dort
untergegangen.

**3. Der Offline-Cache hätte Nutzer vermischt.** Bisher trennten die Token die
Cache-Schlüssel von selbst. Token-frei ist `/a/einkauf/` für alle dieselbe
Adresse – auf dem Familien-iPad hätte der nächste Nutzer offline die Liste
des vorigen gesehen. `sw.js` merkt sich jetzt in einem eigenen Cache-Eintrag,
wessen Seiten drinliegen, und wirft beim Wechsel alles weg. Jede Seite meldet
dem Worker nach dem Laden, wer zusieht.

**4. Fünf Apps fehlten in der Seed-Liste.** `_CORE_APPS` endete bei
`kinderplan` – Sportschau, Tierbaukasten, Vokabeln, Packliste und TVB wurden
seinerzeit von Hand über `manage.py` angelegt und nie nachgetragen. Auf dem
laufenden Server unsichtbar, auf einer frischen Datenbank hätten die Module
Routen registriert, für die es keine App zum Freischalten gibt. Aufgefallen,
weil der neue Rauchtest eine leere Test-DB aufbaut. Nachgetragen mit exakt
den Werten der Produktivdatenbank.

### Der Fehler, den erst der echte Server gezeigt hat

Der Vorrang des Pfad-Tokens hielt nur **eine Seite lang**.

Cookie gehört Andi, Simone öffnet auf demselben Gerät ihren Link: Die
Startseite zeigte korrekt Simone – aber das Cookie blieb Andis, weil das
Sitzungsmodul nur dann eines ausstellte, wenn *gar keines* mitkam. Bis Stufe 3
war das harmlos, denn jede Kachel trug Simones Token. Token-frei ist
`/a/einkauf/` für alle dieselbe Adresse: Simone hätte beim ersten Tippen
Andis Einkaufsliste gesehen.

Das ist nur im Zusammenspiel von Cookie-Ausstellung und Link-Aufbau sichtbar
und wäre in keinem der bestehenden Tests aufgefallen – gefunden hat es der
End-to-End-Durchlauf gegen den echten Server (v120). Behoben in v121: Gehört
die vorhandene Sitzung einem anderen Nutzer, wird sie gelöscht und durch eine
neue ersetzt. **Wer seinen Link öffnet, übernimmt das Gerät.** Die alte Zeile
wird dabei gelöscht und nicht überschrieben, sonst bliebe für jeden Wechsel
eine verwaiste, gültige Sitzung zurück – und „Zugänge neu erzeugen" räumt nur
die des eigenen Nutzers weg.

Zwei neue Tests halten das fest (`test_link_oeffnen_uebernimmt_das_geraet`,
`test_geraetuebernahme_laesst_keine_verwaiste_sitzung_zurueck`).

### Kein Aussperr-Fenster bei der Weiterleitung

`/p/<token>` leitet **nicht** sofort auf `/start` um. Der naheliegende Weg
hätte eine Falle: Nimmt ein Browser das Cookie nicht an – Privatmodus, voller
Speicher, strenge Einstellungen –, landet man auf `/start` ohne Sitzung,
bekommt „Zugang verweigert", und der erneute Scan des QR-Codes führt in
dieselbe Weiterleitung. Der Link wäre für dieses Gerät dauerhaft tot, obwohl
der Token gilt.

Deshalb: Beim **ersten** Besuch wird die Seite ganz normal ausgeliefert und
das Cookie gesetzt. Kommt es beim nächsten Aufruf zurück und zeigt auf
denselben Nutzer, ist bewiesen, dass Cookies auf diesem Gerät tragen – dann
erst wird umgeleitet. Ein Gerät ohne funktionierende Cookies behält für immer
seinen Token-Link.

### PWA-Manifest – der Posten, der im Plan als „am schlechtesten schätzbar" stand

War es nicht. `/manifest/<token>.json` ergibt nach derselben mechanischen
Regel wie alle anderen Routen exakt `/manifest.json`. Nötig war nur
`crossorigin="use-credentials"` am `<link>`: Ohne das holt der Browser das
Manifest ohne Cookies und bekäme 404. `start_url` folgt demselben Schalter wie
alle anderen Adressen.

### Testnetz

Von 65 auf **72 Tests**. Der Rauchtest ruft jetzt jede der 36 parameterlosen
Seiten **zweimal** auf – einmal mit Token, einmal token-frei über das Cookie –
und sucht in jeder ausgelieferten Seite nach *allen* Tokens des Nutzers, nicht
nur dem der offenen App. Genau die Verwechslung wäre der wahrscheinliche
Fehler gewesen.

Der Routen-Wächter misst jetzt am **Endpunkt** statt an der einzelnen Regel
und verlangt zusätzlich, dass jede `<token>`-Route ihren token-freien Zwilling
hat – eine beim Umbau vergessene Route fällt damit auf, auch wenn sie ein
POST-Endpunkt ist, den niemand durchklickt.

Nebenbei fiel auf, dass der Rauchtest bisher **still übersprang**, was er
nicht prüfen konnte: 14 der 36 Seiten liefen gar nicht (siehe Punkt 4 oben).
Er meldet das jetzt als Fehler. Ein Test, der schweigt, wenn er nichts tut,
ist schlimmer als keiner.

### Verifikation (von diesem Rechner, über das UniFi-Gateway)

- 50 Zugänge über die alten Token-Adressen → 50 × 200
- alle vier Nutzer token-frei durch jede ihrer Apps → 46 × 200
- ohne Cookie: `/start`, `/a/einkauf/` → 403, `/manifest.json` → 404
- Vorrangtest: Cookie A + Link B → B, und B bleibt auch nach dem Klick
- `CSRF_MODUS=scharf`: 0 Verdachtsfälle
- 72 Tests grün

**Offen für Andi:** `pruefplan.md`, Stufe 4 – S4-01 bis S4-11. S4-10
(geteiltes Gerät) und S4-11 (Offline-Cache nach Nutzerwechsel) sind neu und
prüfen genau die beiden Fehler oben.

---

## 2026-08-06 – portal-v119: Wunsch #140, Stufe 3 – das Sitzungs-Cookie gilt

Dritte von sechs Stufen, und die erste, bei der ein Fehler jemanden aussperren
könnte. Neue Route `/start`: derselbe Einstieg wie `/p/<token>`, nur ohne
Token in der Adresse – der Nutzer kommt dann aus dem Cookie.

### Die Reihenfolge in `grant()` ist die Sicherheitszusage

1. **Pfad-Token, immer zuerst.** Solange er gilt, kann kein Fehler in der
   Cookie-Logik jemanden aussperren. Auf einem geteilten Gerät gewinnt damit
   der Link, den man gerade geöffnet hat, gegen das Cookie des zuletzt
   Angemeldeten.
2. Ein **angegebener, aber ungültiger** Token fällt bewusst **nicht** aufs
   Cookie zurück – sonst funktionierte ein widerrufener Zugang stillschweigend
   weiter, solange das Cookie noch lebt.
3. Nur wenn **gar kein** Token in der Adresse steht, zählt das Cookie. Auch
   dann muss der Nutzer einen Grant für die App haben: das Cookie ersetzt den
   Nachweis, es weitet keine Rechte aus.

`_home_user()` in `01_start_token.py` bekam dieselbe Logik. Die 41
`check_grant()`-Aufrufe und alle 91 Routen blieben unverändert.

**Ringschluss vermieden:** Das Lesen des Cookies (`sitzung_nutzer_id()`) liegt
jetzt im Kern, nicht im Sitzungsmodul – `grant()` braucht es, und ein Import
in die andere Richtung wäre zirkulär. Das Sitzungsmodul holt sich den
Cookie-Namen umgekehrt von dort.

### Ein Test, der erst falsch war

`test_widerruf_macht_cookie_ungueltig` schlug zunächst fehl. Ursache war der
Test, nicht der Code: Er ließ **einen** Client gleichzeitig Admin und Kind
sein. Beim Widerrufs-Request löst `grant()` den Admin auf, die Route löscht
die Sitzungen des Kindes, und das `after_request` stellt danach für denselben
Browser eine frische Admin-Sitzung aus – der Test prüfte also einen Fall, den
es im Betrieb nicht gibt. Jetzt mit zwei getrennten Clients, wie es zwei
Geräte auch sind. Dazu eine Gegenprobe, dass sich der auslösende Admin nicht
selbst aussperrt – sonst wäre der Notfallknopf im Notfall unbenutzbar.

**Nebenbei aufgefallen:** In `19_sitzung.py` behauptete ein Kommentar,
Weiterleitungen bekämen kein Cookie; der Code prüfte aber nur auf
Fehlerantworten. Kommentar an den Code angeglichen (Weiterleitungen bekommen
eines, das spart nach einem POST einen Umlauf).

### Verifiziert

Erst mit Schalter aus ausgeliefert: `/start` liefert 403, `/p/<token>` 200.
Dann eingeschaltet: `/start` mit Cookie 200, ohne Cookie 403. **Vorrangtest**
live – Andis Cookie plus Friederikes Link zeigt Friederike. **Ungültiger
Token** mit gültigem Cookie: 403. `/start` rendert vollständig (14 Kacheln,
Heim-Knopf, Hilfe-Link, `const TOKEN`). Gegengeprüft, dass es nirgends einen
automatischen Redirect auf eine Anmeldeseite gibt – die Kiosk-Zusage.
63 Tests grün, Regression 50 × HTTP 200.

### Auslieferungspaket

`deploy/portal-v119.tar.gz`

---

## 2026-08-06 – Wunsch #140, Stufe 2: CSRF-Riegel scharf geschaltet

Nach der Beobachtungsphase auf `CSRF_MODUS=scharf` umgestellt. Reine
`.env`-Änderung, kein neues Paket.

### Warum die Beobachtungsphase kurz bleiben durfte

Ursprünglich war eine Woche vorgesehen. Das war zu vorsichtig gegriffen:
`Sec-Fetch-Site` hängt an der Beziehung zwischen Absender und Ziel, **nicht
an der Route**. Geht ein Formular auf einem Gerät durch, gehen alle Formulare
auf diesem Gerät durch. Zeit im Alltag deckt weitere Routen ab, aber keine
weiteren Fälle. Was variiert, ist Gerät/Browser und Anfrageart – und davon
gibt es genau vier: normales Formular, `fetch()` aus der Seite, die
nachgespielte Offline-Warteschlange und `navigator.sendBeacon` im
Vokabeltrainer. Der Service Worker scheidet aus, weil `sw.js` nicht-GET nie
abfängt.

Alle vier wurden über iPhone, Windows und den ChromeOS-Kiosk durchgespielt
(Prüfplan S2-01 bis S2-05). Ergebnis: **null Verdachtsfälle** bei echten
Geräten über die gesamte Beobachtungszeit.

### Verifiziert nach dem Scharfschalten

`same-origin` → 200, `same-site` → **403**, `cross-site` → **403**, lesende
Anfragen unberührt. Echtes Einkaufs-Formular über HTTPS: same-origin legt an
(302), cross-site wird abgewiesen (403) – gegengeprüft, dass der abgewiesene
Artikel tatsächlich nie in der Datenbank landete. Regression über alle 50
Grants: 50 × HTTP 200.

Der `same-site`-Fall ist der wichtigste: Home Assistant läuft unter derselben
Domain, ein POST von dort wäre same-site aber nicht same-origin. Der Kiosk ist
davon nicht betroffen, weil die Seite **im** iFrame Portal-Origin hat – live
bestätigt durch S2-05.

### Nebenbefund aus der Prüfung

Testfall S2-03 deckte einen vorbestehenden Fehler in der Offline-Warteschlange
auf, der nichts mit diesem Umbau zu tun hatte (siehe portal-v118 weiter unten).
Ohne diesen Testfall wäre er weiter unentdeckt geblieben.

---

## 2026-08-06 – portal-v118: Offline-Warteschlange der Einkaufsliste hing dauerhaft fest

Beim Prüfen von Stufe 2 (Testfall S2-03) gefunden: Nach dem Wiederverbinden
blieben abgehakte Artikel dauerhaft auf „⏳ wartet". **Kein Zusammenhang mit
dem Sitzungs-/CSRF-Umbau** – der Riegel stand auf `beobachten` und hat
nachweislich keinen einzigen Verdachtsfall protokolliert. Der Fehler war
vorher schon da und wäre ohne diesen Testfall weiter unentdeckt geblieben.

### Ursache

Im Log fiel auf: `POST /a/einkauf/<token>/erledigt/23` antwortete immer wieder
mit **404**, während andere Artikel sauber 200 lieferten. Artikel 23 gab es
nicht mehr – gelöscht, während das Häkchen noch in der Warteschlange lag.

`synchronisiereWarteschlange()` konnte „keine Verbindung" nicht von „der
Server sagt endgültig nein" unterscheiden. Ein 404 landete über den
`resp.json()`-Aufruf im `catch`, galt damit als Netzfehler, und die Schleife
brach mit `break` ab. Der tote Eintrag blieb vorn in der Schlange liegen und
**blockierte alles dahinter dauerhaft** – jeder weitere Sync scheiterte
wieder an derselben Leiche.

### Behebung

Die Antwort wird jetzt ausgewertet statt pauschal als Fehlschlag behandelt:

- **400 / 404 / 410** – wird auch beim hundertsten Versuch nicht klappen:
  Eintrag verwerfen und mit dem Rest **weitermachen** statt abzubrechen.
- **403 und 5xx** – bleiben bewusst liegen: ein erneuerter Zugang oder ein
  kurzer Serverfehler kann sich wieder einrenken.
- **Netzfehler** – wie bisher liegen lassen.
- `resp.json()` darf nicht mehr werfen dürfen, sonst gilt eine gültige
  Antwort fälschlich als Netzfehler.

Verworfene Änderungen werden nicht stillschweigend geschluckt, sondern
gemeldet. **Stolperstein dabei:** Ein Toast direkt nach dem Verwerfen ist
unsichtbar, weil unmittelbar danach `location.reload()` folgt, sobald auch
nur eine Aktion erfolgreich war. Der Hinweis wird deshalb in `sessionStorage`
gemerkt und nach dem Neuladen gezeigt; lief gar nichts erfolgreich durch (kein
Reload), erscheint er sofort.

### Verifiziert

Beide Fälle im Browser mit künstlich gesetzter Warteschlange nachgestellt:
**A** – toter Eintrag vor gültigem: Schlange geleert, gültige Aktion
durchgelaufen, Hinweis hat das Neuladen überlebt. **B** – nur ein toter
Eintrag: kein Neuladen, Hinweis erscheint sofort. Danach gegengeprüft, dass
an der echten Einkaufsliste nichts verändert wurde (52 Artikel, Artikel 19
unverändert offen) und die Testreste aus dem Browser entfernt.

### Auslieferungspaket

`deploy/portal-v118.tar.gz`

---

## 2026-08-06 – portal-v117: Wunsch #140, Stufe 2 – CSRF-Riegel (Beobachtungsmodus)

Zweite von sechs Stufen. Neues Modul `src/teile/20_csrf.py`, ausgeliefert mit
`CSRF_MODUS=beobachten` – es wird protokolliert, aber **nichts blockiert**.

### Warum das Portal bisher keinen CSRF-Schutz brauchte

Das war kein Versäumnis: Jede ändernde Anfrage muss den Zugangstoken
mittragen (im Pfad oder im JSON-Body). Ein fremder Server kennt ihn nicht und
kann die Anfrage gar nicht bilden – das ist exakt das
Synchronizer-Token-Muster, nur im Pfad statt im Formularfeld. Erst wenn ab
Stufe 3 ein Cookie autorisiert, entsteht „ambient authority", und ab dann ist
der Schutz Pflicht.

**Reihenfolge mit Absicht:** Der Riegel geht scharf, BEVOR das Cookie
autorisiert. In diesem Moment kann er nichts kaputtmachen, was nicht ohnehin
kaputt wäre – jede Anfrage trägt noch ihren Pfad-Token. Falsch-Positive
fallen dadurch im Protokoll auf und nicht später im Betrieb.

### Header-Prüfung statt verstecktem Formularfeld

Ein Synchronizer-Token müsste in 57 Formulare und 27 `fetch()`-Aufrufe
eingebaut werden; jedes vergessene bricht still. Der Header-Riegel ist eine
einzige Funktion und braucht null Template-Änderungen. Dazu käme ein zweites
Problem: die Offline-Warteschlange der Einkaufsliste hebt POSTs stundenlang
auf und spielt sie später nach – ein rotierendes Token wäre dann abgelaufen.

Zwei Fallen bestimmen den Aufbau:

1. **`Referrer-Policy: no-referrer` kann `Origin` auf `null` setzen.** Wer nur
   `Origin` prüft, lehnt womöglich alles ab. Deshalb steht `Sec-Fetch-Site`
   an erster Stelle – der Header ist von der Referrer-Policy unberührt.
2. **`Sec-Fetch-Site: same-site` muss abgelehnt werden.** Home Assistant läuft
   unter derselben Domain; ein POST von dort wäre same-site, aber nicht
   same-origin. Der Kiosk ist nicht betroffen: die Seite IM iFrame hat
   Portal-Origin, ihre Formulare sind same-origin. Dafür gibt es einen
   eigenen Test.

Passende `Origin` rettet eine als cross-site markierte Anfrage bewusst NICHT –
sonst käme man über einen gefälschten Origin-Header durch.

### Verifiziert

15 neue Tests (52 gesamt, alle grün), darunter die Negativfälle same-site,
cross-site, `none` und „gar keine Kopfzeile". Live: cross-site-POST → 200 mit
Protokolleintrag `CSRF-Verdacht`, same-origin-POST → 200, echtes
Einkaufs-Formular über HTTPS → 302 (Testartikel danach entfernt). Regression
über alle 50 Grants: 50 × HTTP 200.

Offen bis zur Rückmeldung von Andi: ob echte Geräte im Beobachtungsmodus
auffallen. Erst bei null Treffern wird auf `scharf` gestellt (`pruefplan.md`,
S2-01 bis S2-05).

### Auslieferungspaket

`deploy/portal-v117.tar.gz`

---

## 2026-08-06 – portal-v116: Wunsch #140, Stufe 1 – Sitzungs-Cookie wird ausgestellt

Erste von sechs Stufen auf dem Weg, den Zugangstoken aus der Adresszeile zu
bekommen. Der vollständige Stufenplan steht in
`~/.claude/plans/quiet-enchanting-shore.md`, die Handprüfung in `pruefplan.md`.

### Was diese Stufe tut – und vor allem, was nicht

Das Portal legt beim Auflösen eines Pfad-Tokens zusätzlich eine Sitzung an und
gibt ein Cookie mit. **Ausgewertet wird es von nichts.** Die Anmeldung läuft
weiterhin ausschließlich über den Token in der Adresse. Damit kann diese Stufe
per Definition niemanden aussperren, und der Mechanismus lässt sich im echten
Betrieb beobachten, bevor in Stufe 3 etwas davon abhängt.

Zwei Tests halten genau das fest: `test_cookie_allein_authentifiziert_noch_nicht`
und `test_cookie_oeffnet_keine_fremde_app`. Werden sie später rot, ist
versehentlich Stufe 3 aktiv.

### Entscheidungen

**Eigene Tabelle statt Flasks signiertem Cookie.** Ein signiertes Cookie ist
nicht widerrufbar – „Zugänge neu erzeugen" (#131) wäre wirkungslos, und das
fiele erst auf, wenn ein Gerät verloren ist. Mit `sitzungen` lässt sich jede
Sitzung einzeln beenden, und man sieht, welche Geräte angemeldet sind.

**Der Cookie-Wert steht nicht im Klartext in der DB**, gespeichert wird
`token_lookup(wert)` – derselbe HMAC wie bei den Zugangstokens seit #129. Ein
`_enc`-Gegenstück ist unnötig, weil der Wert nie zurückgelesen werden muss.
Das ist nebenbei genau das echte Hashing, das bei #129 an der Navigation
gescheitert war.

**`SameSite=Lax`, kein `Domain`.** `wir4` und `portal` sind Subdomains von
`16schwaben.de`, also same-site – das Cookie geht damit auch im
Home-Assistant-iFrame auf dem Esszimmerbildschirm mit. `Strict` würde beim
Aufruf über einen Link von außen cookielos ankommen. Ein `Domain`-Attribut
würde das Cookie an Home Assistant mitschicken; das soll es nie.

**Max-Age ein Jahr.** Der heutige Link läuft nie ab; eine kurze Sitzung wäre
ein Komfortrückschritt ohne Sicherheitsgewinn.

**`DELETE FROM sitzungen` bei „Zugänge neu erzeugen"** ist schon jetzt drin,
obwohl es erst ab Stufe 3 wirkt – genau so eine Zeile vergisst man sonst bis
zu dem Moment, in dem sie zählt.

### Testnetz zuerst

`tests/` war leer. Vor der ersten Änderung angelegt: `conftest.py` (Wegwerf-DB
je Test, Testfamilie aus Admin/Kind/Eltern), `test_grant.py` (19 Tests gegen
den **Ist-Zustand** – Auflösung, Rollen, Navigations-Token, Verschlüsselung),
`test_routen_inventar.py` (verlangt für jede ändernde Route entweder
`<token>` oder einen begründeten Eintrag in einer Ausnahmeliste – fängt
künftige ungeschützte Routen automatisch ab). Dazu `test_sitzung.py` für diese
Stufe. **36 Tests, alle grün.**

`pytest` liegt in `requirements-dev.txt`, nicht in `src/requirements.txt` –
die beschreibt die Laufzeit und ist seit #135 exakt gepinnt. Testumgebung ist
ein lokales `.venv` (bereits in `.gitignore`).

**Stolperstein:** `sys.path` auf `src/` muss beim Laden von `conftest.py`
gesetzt werden, nicht erst im Fixture – sonst scheitern Testmodule, die
`from teile.kern import …` auf Modulebene schreiben, schon beim Einsammeln.

### Verifiziert

Erst mit Schalter **aus** ausgeliefert: keine `Set-Cookie`-Kopfzeile, Tabelle
angelegt, Verhalten unverändert. Dann eingeschaltet: Cookie mit allen
erwarteten Attributen und ohne `Domain`, zweiter Aufruf mit Cookie erzeugt
**kein** zweites, Zeile in der DB mit HMAC statt Klartext. Regression über
alle 50 Grants: 50 × HTTP 200. Testzeilen danach wieder entfernt, damit Andis
Geräteprüfung auf einer leeren Tabelle beginnt.

Offen und nur von Andis Geräten prüfbar: ob das Cookie im
Home-Assistant-iFrame ankommt (`pruefplan.md`, S1-04). Davon hängt Stufe 3 ab.

### Auslieferungspaket

`deploy/portal-v116.tar.gz`

---

## 2026-08-05 – portal-v113/114/115: Sicherheitspaket (Wünsche #126–#135, #141)

Umsetzung der priorisierten Punkte aus der Sicherheitsanalyse. Die sieben mit
`zurueckgestellt` markierten Wünsche (#130, #136–#140, #51) blieben
unangetastet. In drei Stufen ausgeliefert, damit ein Fehler nicht alles auf
einmal umwirft: v113 Infrastruktur + SSRF, v114 Token-Verschlüsselung,
v115 CSP + Werkstatt-Filter.

### #128 – Dateirechte (sehr hoch)

`.env` und `portal.db` lagen mit 0644 auf der Platte, also für jeden lokalen
Benutzer von home02 lesbar – und in der DB standen alle 50 Zugangstokens im
Klartext. Jetzt 0600 für beide, 0700 für `data/` und die Snapshots, und in
beiden Containern `umask 077`, damit neu erzeugte Snapshots/Backups nicht
wieder mit 0644 entstehen. Der `umask`-Teil musste als `sh -c "umask 077 &&
exec …"` ins CMD, weil `umask` ein Shell-Builtin ist und eine reine
CMD-Liste gar keine Shell startet.

### #126 – Caddy-Admin-API abgeschaltet (sehr hoch)

War auf 172.30.0.10:2019 erreichbar, ohne Authentifizierung, aus demselben
Bridge-Netz wie der portal-Container – live nachgewiesen. Jetzt `admin off`.
Der Healthcheck hing genau an dieser API; Ersatz ist ein Klartext-Listener
auf `127.0.0.1:2020` **innerhalb** des caddy-Containers.

**Stolperstein:** Der erste Ersatz war ein Pfad `/caddy-up` in der
öffentlichen Site, abgefragt per `wget --header="Host: …" https://127.0.0.1/`.
Das scheitert – busybox-wget setzt kein SNI, und ohne SNI kann Caddy die Site
nicht zuordnen: `tlsv1 alert internal error`, Container dauerhaft
"unhealthy". Der eigene Loopback-Listener ohne TLS umgeht das und ist
nebenbei von außen gar nicht erreichbar.

### #127 – SSRF beim Rezept-Import (sehr hoch)

Zwei Lücken in `_ist_oeffentliche_url`, beide geschlossen:

1. **Weiterleitungen** wurden von urllib automatisch verfolgt, ohne das Ziel
   erneut zu prüfen – eine öffentliche URL mit 302 auf die Caddy-Admin-API
   landete direkt dort. Jetzt folgt `_seite_abrufen()` selbst, prüft **jede**
   Station erneut und bricht bei Schleifen bzw. nach 5 Sprüngen ab.
   Weiterleitungen ganz zu verbieten wäre einfacher gewesen, hätte den Import
   aber für die halbe Welt kaputtgemacht (http→https, www, Trailing-Slash).
2. **DNS-Rebinding**: zwischen Prüfung und Abruf wurde der Name ein zweites
   Mal aufgelöst. Jetzt wird einmal aufgelöst, geprüft und genau diese IP
   verbunden – Hostname bleibt für Host-Header, SNI und Zertifikatsprüfung
   erhalten.

Nebenbei deckt `_ip_ist_oeffentlich()` jetzt über `is_global` auch
100.64.0.0/10 und 0.0.0.0/8 ab, die die alte Aufzählung durchgelassen hatte.

**Stolperstein:** Ein `HTTPRedirectHandler`, dessen `redirect_request` `None`
zurückgibt, bringt keine 3xx-Antwort zurück – urllib wertet das als „nicht
behandelt" und lässt den Standard-Fehlerhandler einen `HTTPError` werfen.
Richtig ist ein eigener `HTTPErrorProcessor`, der Antworten roh durchreicht.
Danach muss man Fehlerstatus allerdings selbst prüfen, sonst wird eine
404-Seite als Rezept interpretiert.

### #129 – Tokens nicht mehr im Klartext (sehr hoch)

Der Wunsch verlangte wörtlich einen **Hash**. Das geht hier nicht: `base.html`
baut auf *jeder* Seite den ⌂-Knopf aus `home_token` und den Hilfe-Link aus
`hilfe_token`, und die Startseite erzeugt jede Kachel aus dem Token des
jeweiligen Grants. Ein Einweg-Hash ließe sich nicht zurücklesen – die
komplette Navigation wäre tot. (Mit dem Cookie-Modell aus #140 wäre echtes
Hashing möglich; das ist zurückgestellt.)

Umgesetzt ist deshalb das, worum es dem Wunsch inhaltlich ging – „ein
geleaktes Backup darf keinen Vollzugriff geben": die Tokens liegen
**verschlüsselt** in der DB (AES-GCM), gesucht wird über einen HMAC-Suchwert.
Der Schlüssel steht in der `.env`, und das tägliche Backup sichert nur
`/data` – die `.env` liegt eine Ebene darüber und ist damit **nicht** im
Backup. Genau das macht ein abhandengekommenes Backup wertlos.

Migration auf einer Kopie der Produktions-DB vorab durchgespielt: 50 von 50
übernommen, alle Tokens exakt wiederherstellbar, kein Klartext mehr in den
Rohbytes. Dabei aufgefallen: ohne `VACUUM` bleiben die alten Werte in
freigegebenen Seiten stehen – `strings portal.db` hätte sie weiterhin
gefunden und das nächste Backup mitgenommen. Steht jetzt in der Migration.

**Betriebshinweis, wichtig:** Ohne `TOKEN_KEY` kommt niemand mehr rein. Die
`.env` gehört an einen zweiten sicheren Ort (Passwortmanager) – ein
wiederhergestelltes `/data`-Backup allein reicht nicht mehr. Sicherungen
liegen als `.env.vor-129` und `portal.db.vor-129` auf home02.

### #131 – Notfallknopf „Zugänge neu" (hoch)

Pro Mitglied ein Knopf in der Verwaltung, der alle Grants dieses Nutzers in
einem Schritt neu vergibt. Durch #129 ist das keine Bequemlichkeit mehr,
sondern notwendig: einen verlorenen Zugang kann man nicht mehr nachschlagen,
man erzeugt ihn neu. Sonderfall mitgetestet: erneuert der Admin seine
**eigenen** Zugänge, wird der Token in der Adresszeile mit erneuert – die
Weiterleitung zeigt deshalb auf die neue Admin-Adresse, sonst liefe sie in
ein 403.

### #132 – CSP gehärtet (hoch)

Statt nur `frame-ancestors` jetzt `default-src 'self'` plus
`connect-src`/`img-src`/`form-action` auf `'self'`, `object-src 'none'`,
`base-uri 'self'`. Damit sind die üblichen Abflusswege für einen erbeuteten
Token abgeschnitten (fetch/XHR, Bild-Beacon, Formular-POST) und externe
Skripte lassen sich nicht nachladen.

**Bewusst nicht umgesetzt:** `'unsafe-inline'` bleibt bei `script-src`
stehen. Die Templates enthalten 59 Inline-Handler in 27 Dateien, 30
Inline-`<script>`-Blöcke und 199 `style="…"`-Attribute – ein echtes Nonce
würde all das auf einen Schlag lahmlegen. Der Umbau auf `addEventListener`
ist als eigener Wunsch erfasst. Ebenfalls offen bleibt Abfluss per
Navigation (`location.href = …`); dafür gibt es in CSP kein Mittel mehr,
seit `navigate-to` aus dem Standard gefallen ist.

### #133 / #134 / #135 (hoch bzw. mittel)

- **#133**: `MAX_CONTENT_LENGTH` = 10 MB in Flask, `request_body max_size`
  = 12 MB in Caddy. Vorher wurde die Datei erst komplett in den Speicher
  gelesen und *danach* auf 8 MB geprüft – bei 256 MB Container-Limit ein
  offenes Scheunentor. Beide Schichten live gegengeprüft (11 MB → 413 von
  Flask, 15 MB → 413 von Caddy, Container überlebt beides).
- **#134**: HSTS mit `max-age=31536000`, bewusst **ohne**
  `includeSubDomains` – das würde für alle `*.16schwaben.de` gelten, auch
  für Dienste, die hier gar nicht konfiguriert sind.
- **#135**: `requirements.txt` von `>=` auf `==` mit den Versionen, die
  tatsächlich liefen.

### #141 – Filter in der Werkstatt (hoch)

Bei 140 Wünschen war die Liste unbenutzbar. Filter nach Priorität, Status,
App und Urheber; innerhalb einer Zeile „oder", zwischen den Zeilen „und".
Aufbau und Bedienung bewusst identisch zur Aufgaben-App (Chips,
sessionStorage), damit man sich nicht zwei Logiken merken muss. Die
Kriterien werden nur aus tatsächlich vorkommenden Werten gebaut – sonst gäbe
es Knöpfe, die nie etwas treffen.

### Verifiziert

Nach der Token-Umstellung **jeder einzelne der 50 Grants** über seine echte
App-URL aufgerufen: 50 × HTTP 200, keine Ausnahme. Zusätzlich: Admin-API aus
dem portal-Container nicht mehr erreichbar (ConnectionRefused), interner
Health-Listener weder von außen noch aus dem intern-Netz erreichbar, alle
Header gesetzt, SSRF-Angriffsfälle abgewiesen und echte Rezepte weiterhin
importierbar (JSON-LD mit Zutaten und Schritten), Filter über alle Fälle
inklusive Null-Treffer und Persistenz nach Neuladen, keine CSP-Verstöße in
der Browser-Konsole.

### Auslieferungspakete

`deploy/portal-v113.tar.gz`, `portal-v114.tar.gz`, `portal-v115.tar.gz`

---

## 2026-08-04 – portal-v112: Wünsche #123 + #124 + #125 – Kopfzeile, Mannschaftsfilter, Scroll-Hinweis

Drei Nachbesserungen am Mannschafts-Umschalter aus Wunsch #122.

### #123 – Kopfzeile richtet sich nach der Mannschaft

"Der App Header soll Entweder TVB Stuttgart oder TV Bittenfeld zeigen.
'Handball-Bundesliga' ist auch nur bei der 1. Mannschaft korrekt."

Stimmt – beides war fest verdrahtet und damit bei 17 von 18 Mannschaften
falsch. Jetzt zeigt der Kopf den Verein der **gewählten** Mannschaft:
„TVB Stuttgart / Handball-Bundesliga" nur bei den Profis, sonst
„TV Bittenfeld" plus die ausgeschriebene Liga (ohne den Verbandspräfix,
also „männliche A-Jugend Oberliga Staffel 1" statt „Baden-
Württembergischer Handball-Verband - männliche A-Jugend …"). Der
Browser-Tab-Titel zieht mit.

### #124 – Altersklassen pro Nutzer ausblenden

"DA alle Jugendligen enthalten sind, und das sehr umfangreich ist, soll es
eine Seite geben, mit der z.B. die C, D, F Jugend ausgeblendet werden kann.
Das soll jeder Nutzer machen können."

Neue Seite `/a/tvb/<token>/mannschaften` (Menü ☰ → „Mannschaften
anzeigen"): eine Checkbox je Altersklasse mit der Anzahl Mannschaften
dahinter, plus „Alle an"/„Alle aus". Bewusst **ohne** Admin-Prüfung – der
Wunsch sagt ausdrücklich „jeder Nutzer", und es ändert nur die eigene
Ansicht (`tvb_ausgeblendet` je `user_id`).

Drei Entscheidungen dabei:
- **Gespeichert wird das Ausgeblendete, nicht das Sichtbare.** Kommt
  nächste Saison eine neue Altersklasse dazu, ist sie damit automatisch
  sichtbar statt stillschweigend versteckt.
- **Die Profis lassen sich nicht abwählen** (Haken fest, „immer sichtbar").
  Sonst könnte der Umschalter komplett leer werden und die App hätte keinen
  Einstieg mehr. Blendet jemand alles andere aus, verschwindet die Leiste
  ganz – es gibt dann ja nichts zu wechseln –, die Profiseite funktioniert
  weiter und der Weg zurück steht im Menü. Live durchgespielt.
- **Ein Direktlink auf eine ausgeblendete Mannschaft funktioniert weiter**,
  sie taucht nur nicht im Umschalter auf. Ein gespeicherter Link soll nicht
  wegen einer Anzeigeeinstellung ins Leere laufen.

Der Schlüssel je Klasse ist das Kürzel aus `_ALTERSKLASSEN` (mA, gE, …),
nicht die Liga-Bezeichnung: „gemischte Jugend E" und „gemischte E-Jugend"
sind zwei Schreibweisen derselben Klasse und müssen auf denselben Haken
fallen, sonst stünde dieselbe Altersklasse zweimal in der Liste.

### #125 – Sichtbarer Hinweis aufs Weiterscrollen

"Wenn mehr Mannschaftsicons auswählbar sind, als in der App-Seite oben quer
passen, dann soll ein grafisches Element zeigen, dass man hier links/rechts
scrollen kann."

Am jeweiligen Rand blendet sich ein weicher Verlauf in die Seitenfarbe mit
einem ‹ bzw. › ein – aber nur, wenn es dort tatsächlich weitergeht: ganz
links nur ›, in der Mitte beide, ganz rechts nur ‹, und auf einem breiten
Bildschirm, auf dem alles passt, gar keiner. `pointer-events:none`, damit
die Chips darunter antippbar bleiben; der Hinweis zeigt nur an, er ist kein
Bedienelement. Zusätzlich scrollt die Leiste beim Laden die aktive
Mannschaft in den sichtbaren Bereich – bei 18 Chips lag sie sonst oft
außerhalb und man sah nicht, wo man gerade ist.

### Verifiziert

Kopfzeile für vier Mannschaften quer durch die Altersklassen geprüft
(Verein, Liga und `<title>` jeweils korrekt). Filter: Einstellungsseite
listet alle 7 Klassen mit richtigen Zahlen (2+1+1+2+3+6+2 = 17); nach dem
Ausblenden von C/D/E/F-Jugend blieben genau Profis + 2× Herren + mA + mB
übrig; Grenzfall „alles aus" und Direktlink auf eine ausgeblendete
Mannschaft ebenfalls geprüft. Scroll-Hinweis an drei Scrollpositionen und
auf breitem Bildschirm gemessen, Chip-Zentrierung auch für die 18. von 18
Mannschaften.

**Messfalle dabei:** `getComputedStyle(el).opacity` liefert während eines
laufenden CSS-Übergangs den *momentanen* Zwischenwert, nicht das Ziel – der
erste Messversuch zeigte deshalb überall 0 und sah nach einem kaputten
Feature aus, obwohl die Klassen längst korrekt gesetzt waren. Für solche
Messungen entweder die Klassen selbst prüfen oder `transition:none` setzen.

### Auslieferungspaket

`deploy/portal-v112.tar.gz`

---

## 2026-08-04 – portal-v111: Wunsch #122 – Umschalter für alle Mannschaften

"Falls es auch zu den 2. und 3. Mannschaften und der Jugend Spieldaten etc.
im Internet gibt, dann sollen oben in der App Button Umschalter für jede
Mannschaft erscheinen und je nach Auswahl soll man die Informationen der
jeweiligen Mannschaft sehen. Die Seiten der Mannschaften sollen darüber
hinaus immer gleich aufgebaut sein."

### Ja, die Daten gibt es – aber unter einem zweiten Verein

Der Wunsch war ausdrücklich konditional formuliert. Ergebnis der Recherche:
Die Daten existieren, liegen auf handball.net aber unter einem **anderen
Vereinsobjekt** als die Profis. `sr.competitor.6272` ("TVB Stuttgart")
kennt nur zwei Teams – die Bundesligamannschaft und dieselbe Mannschaft im
DHB-Pokal. Der komplette Unterbau hängt an
`handball4all.wuerttemberg.131` ("TV Bittenfeld"): 17 Mannschaften, also
2./3./4. Herren plus die gesamte Jugend von der A- bis zur F-Jugend. Der
Umschalter führt beides zu 18 Einträgen zusammen.

### Die Mannschaftsliste gibt es nicht als API

`club/<id>/teams` und `.../mannschaften` liefern 404; es existiert nur
`club/<id>/schedule`, und das zeigt lediglich Mannschaften mit Spielen in
den nächsten 14 Tagen – in der Sommerpause also gar keine. Deshalb wird
die Vereinsseite geparst (Team-ID, Name und Liga stehen dort im HTML) und
das Ergebnis in `tvb_mannschaften` abgelegt, erneuert nur alle 24 h. Schlägt
das Parsen fehl, bleibt der letzte Stand stehen, statt dass der Umschalter
verschwindet.

Für die Tabelle braucht es zusätzlich die Liga-ID. Normalerweise kommt die
gratis mit den Spieldaten (`tournament.id`) – die sind aber gerade leer.
Fallback ist die /tabelle-Seite der Mannschaft; die eigene Liga ist dort
immer die `handball4all.*` (die `sportradar.dhbdata.*` sind die überall
gleichen Navigationslinks zu den Bundesligen), an fünf Mannschaften quer
durch alle Altersklassen gegengeprüft. Dieser Abruf passiert **faul**:
erst wenn eine Mannschaft tatsächlich geöffnet wird, dann dauerhaft
gemerkt. Alle 17 auf einmal zu holen hätte denjenigen, der zufällig die
24-h-Aktualisierung auslöst, rund 17 Sekunden warten lassen; so bleibt der
Seitenaufbau bei 0,1–0,5 s.

### Zwei bewusste Abweichungen von "immer gleich aufgebaut"

- Der Kader-Knopf (Wunsch #121) erscheint nur bei den Profis. Der HPI ist
  eine reine Bundesliga-Kennzahl; für Amateur- und Jugendmannschaften gibt
  es ihn nicht, ein Knopf auf eine garantiert leere Seite wäre schlechter
  als keiner.
- `tvb_spiele` hat eine `team_id` bekommen, sonst hätten sich die Spiele
  aller Mannschaften vermischt. Bestehende Zeilen sind per Definition
  Profispiele und wurden einmalig entsprechend gesetzt.

### Wichtig: Sommerpause

Die Amateur- und Jugendligen veröffentlichen Spielplan und Tabelle erst
kurz vor dem Saisonstart im September (die Profis starten am 28.08.).
Aktuell liefern deshalb **alle 17** Mannschaften null Spiele, und die
Tabellen-Antwort ist `table: null` – nicht etwa eine leere Liste. Das hätte
den bestehenden Code zum Absturz gebracht (`tabelle_antwort["table"]["rows"]`
auf `None`); jetzt abgefangen und als „Für diese Liga gibt es noch keine
Tabelle" angezeigt. Heißt aber auch: gegen echte Spiel- und Tabellendaten
einer Amateurmannschaft ist die Anzeige erst ab September prüfbar. Die
Logik selbst wurde gegen die echte HBL-Tabelle (18 Zeilen, Hervorhebung
korrekt) sowie gegen `null`/leer/fehlend getestet.

### Nebenbefund: zwei kaputte Icons aus Wunsch #119 repariert

Beim systematischen Gegenprüfen aller Templates gegen die lokalen
Twemoji-Grafiken fielen die Drehknöpfe ◀ ▶ im Tierbaukasten auf: anders als
★ ☰ ✎ ✓ ✕ führt Twemoji diese beiden sehr wohl als Emoji, wandelt sie also
in `<img>` um – die zugehörigen SVGs fehlten aber, Ergebnis waren zwei
404er und zwei leere Knöpfe. Live bestätigt und behoben. Bei der
Gelegenheit alle 38 Templates geprüft: 👩 ↔ ↩ ⏳ fehlten ebenfalls, die
übrigen 15 Zeichen (← ↑ → ⋮ ⌂ ▲ ▸ ▼ ○ ★ ☰ ✎ ✓ ✕ ⠿) sind einzeln
gegengeprüft reine Textzeichen ohne Twemoji-Grafik und damit korrekt so.
Jetzt 84 statt 78 SVG-Dateien.

### Auslieferungspaket

`deploy/portal-v111.tar.gz`

---

## 2026-08-04 – portal-v110: Wunsch #121 – TVB-Kader mit Spielerwerten

"es soll ein Button geben, über den eine Unterseite aufgerufen wird, auf
der der Kader des TVB Stuttgart mit statistischen Werten zu jedem Spieler
dargestellt wird."

### Datenquelle: HPI statt handball.net

handball.net (die Quelle für Spiele/Tabelle aus Wunsch #120) hat dafür
**keinen** Endpunkt – alle Widget-Typen durchprobiert, es existieren nur
`table`, `schedule` und `team-schedule`; `kader`/`squad`/`roster`/
`players`/`statistics` liefern alle 404, und die Kaderseite auf
handball.net selbst enthält im HTML keine Spielerdaten.

Stattdessen: die **HPI-API der Handball-Bundesliga**
(`hpi.handball-bundesliga.de/api/…`, ebenfalls unauthentifiziert). Der
Handball Performance Index ist die offizielle Leistungskennzahl der HBL.
Gefunden über das Statistik-Dashboard auf opel-hbl.de, das den HPI per
`hpi.handball-bundesliga.de/js/widget.js` mit `data-tournament="1"`
einbindet. Zwei Aufrufe: `/api/tournament/1` → Saisonliste,
`/api/index/season/<id>` → alle ~390 Liga-Spieler mit HPI-Werten. TVB wird
über `team.sportradar_id == 6272` gefiltert – dieselbe Sportradar-ID, die
schon in `_TEAM_ID` steckt, also kein zweites Vereins-Mapping.

### Drei Entwurfsentscheidungen

**Saisonwahl.** Die HPI-Liste enthält nur Spieler, die auch gespielt
haben – eine frisch begonnene Saison ist schlicht leer (26/27 hat aktuell
0 Einträge, Saisonstart ist der 28.08.). `_kader_saison_waehlen()` nimmt
deshalb die *neueste Saison, die überhaupt TVB-Spieler liefert*, aktuell
also noch 25/26. Der Saisonname steht sichtbar über der Tabelle, damit nie
unklar ist, worauf sich die Werte beziehen. Die Kehrseite ist ehrlich
dokumentiert (auch in der Hilfe): Neuzugänge fehlen bis zu ihrem ersten
Spiel, Abgänge stehen noch drin. Ohne echte Kaderquelle nicht besser
lösbar – ein reiner Kader ohne Statistik wäre für diesen Wunsch aber
nutzlos gewesen.

**Cache.** `/api/index/season/<id>` liefert ~400 KB für alle Liga-Spieler,
von denen 22 gebraucht werden. Anders als bei den Spielen (Wunsch #120,
5–10 KB pro Abruf) wäre das pro Seitenaufruf verschwenderisch. Neue
Tabelle `tvb_kader`, Neuladen nur, wenn älter als 6 Stunden. Beim Neuladen
wird die Tabelle geleert und neu gefüllt – ein Kader ist eine
Momentaufnahme, wer weg ist soll verschwinden (kein UPSERT wie bei
`tvb_spiele`, wo alte Zeilen ja gerade erhalten bleiben sollen).
Messung live: erster Aufruf 2,15 s, jeder weitere 0,04 s.

**Keine Spielerfotos.** Die API liefert Foto-URLs mit, die aber auf ein
fremdes CDN zeigen (`images.dc.prod.cloud.atriumsports.com`). Bewusst
nicht eingebunden: das Portal lädt grundsätzlich nichts von fremden Hosts
(siehe Wunsch #119), und jedes Foto würde die IP-Adressen der Familie an
einen Dritt-Server melden. Live gegengeprüft – die Kaderseite macht
0 Requests an externe Hosts.

### Verifiziert

Logik **vor** dem Deploy isoliert gegen die echte API getestet
(Saison-Fallback 26/27 → 25/26, Gruppierung verliert keinen Spieler,
Frische-Prüfung greift bei 6 h/7 h korrekt). Danach live: Kaderseite 200,
22 Spieler in 7 Positionsgruppen (Tor → Kreisläufer), Umlaute korrekt
(Rückraum, Linksaußen, Häfner, Pribetić, Röthlisberger), Trendpfeile
eingefärbt (10 ▲ / 12 ▼ = 22), `tvb_kader` in der Produktions-DB mit 22
Zeilen befüllt. Zugriffsschutz: ungültiger Token und Token einer anderen
App liefern beide 403. Layout per `getBoundingClientRect()` geprüft (der
Screenshot-Dienst fiel in dieser Sitzung erneut aus): bis hinunter zu
320 px Breite keine Überlappung von Name und Werten und kein
Horizontal-Overflow, erst bei 280 px bricht die Zeile sauber um. Alle 22
Netzwerk-Requests der Seite mit Status 200, kein 404 – diesmal vorab
geprüft, ob jedes neue Emoji (👥) auch als lokale Twemoji-SVG vorliegt.

### Auslieferungspaket

`deploy/portal-v110.tar.gz`

---

## 2026-08-03 – portal-v109: Wunsch #120 – Neue App "TVB" (Handball-Bundesliga)

"Ich wünsche mir eine neue App 'TVB' im Portal. Die App soll alle Spiele
und Spielergebnisse des TVB Stuttgart anzeigen und die Tabelle der
Handball Bundesliga immer aktuell haben."

### Datenquelle

Es gibt keine offizielle, dokumentierte Public API für Handball-Bundesliga-
Daten (OpenLigaDB hat nur Fußball/Eishockey, kein Handball). Gefunden über
Analyse von `https://www.handball.net/widgets/embed/v1.js` (dem JS-Loader,
den auch TVB Stuttgarts eigene Website für ihre "Spielplan"/"Tabelle"-
Widgets nutzt): ein unauthentifizierter JSON-Endpunkt unter
`https://www.handball.net/a/sportdata/1/widgets/...`, den handball.net -
das offizielle Datenportal des Deutschen Handballbunds - selbst für seine
einbettbaren Vereins-Widgets verwendet. Zwei Endpunkte werden genutzt:
`tournament/sr.competition.149/table` (komplette, immer aktuelle
HBL-Tabelle) und `team/sr.competitor.6272-143352/team-schedule` +
`tournament/.../schedule` (TVB Stuttgarts Spiele).

### Einschränkung: nur ein kleines Zeitfenster

Das Team-Spielplan-Widget liefert laut handball.net-eigener Doku nur die
nächsten ca. 3 Spiele, keinen kompletten Saisonkalender - und vermutlich
(zum Zeitpunkt der Umsetzung noch nicht mit echten Spielergebnissen
testbar, da die Saison 2026/27 gerade erst beginnt) auch keine vergangenen
Ergebnisse mehr, sobald ein Spieltag aus dem Fenster gerutscht ist. Neue
Tabelle `tvb_spiele`: jedes TVB-Spiel, das beim Seitenaufruf im Team- oder
Liga-Spielplan-Widget gesehen wird, wird per UPSERT gespeichert (inkl.
Tore/Status). So bleiben einmal gesehene Ergebnisse dauerhaft sichtbar,
auch wenn handball.net sie später aus dem Widget-Fenster herausrollt.
Bewusst kein Cron-Job dafür eingerichtet (keine Extra-Infrastruktur für den
Randfall "niemand öffnet die App während genau dieses Spieltags") - für
eine Familien-App ausreichend, gleiches Muster wie `_hae_workouts()` in
`14_sportschau.py` (On-the-fly-Abruf mit Timeout, "fehler"-Flag statt
Crash bei Nichterreichbarkeit).

### Stolperstein: zwei neue Emoji vergessen (Regression zu Wunsch #119)

Erster Deploy: 📅 und 🏐 (neu in `tvb.html`, noch nicht Teil der 74
Emoji-SVGs aus Wunsch #119) luden mit 404 - live per
`read_network_requests` im Browser gefunden, nicht per Screenshot (der
Screenshot-Tool selbst hing in dieser Session unabhängig fest). Fix:
beide SVGs nachträglich heruntergeladen, erneut deployed, Requests erneut
geprüft (jetzt alle 200). Lehre: jede neue App mit neuen Emoji muss deren
SVGs mit ausliefern, sonst wiederholt sich das Wunsch-#119-Problem lokal
für die neue Seite.

### Verifiziert

Live: `/a/tvb/<token>/` lädt (200), nächste zwei TVB-Spiele korrekt
angezeigt (TVB Stuttgart fett hervorgehoben, Heim/Auswärts korrekt),
Tabelle mit allen 18 Teams inkl. Umlauten (Göppingen, Füchse Berlin)
korrekt gerendert, TVB-Zeile in der Tabelle hervorgehoben. `tvb_spiele`
in der Produktions-DB bestätigt befüllt (2 Zeilen, korrekte IDs/Termine).
Leerer "Ergebnisse"-Zustand ("Noch keine Ergebnisse.") korrekt, da die
Saison 2026/27 noch nicht begonnen hat - Verifikation echter Ergebnis-
Anzeige erst nach dem ersten gespielten Spieltag möglich.

### Auslieferungspaket

`deploy/portal-v109.tar.gz`

---

## 2026-08-03 – portal-v108: Wunsch #119 – App-Icons unter Linux/Chrome unsichtbar

"Die Bilder der Apps werden unter Linux im Chrome nicht dargestellt. Kann
das an einem Kiosk-Modus des Chrome liegen, oder an etwas anderem. Wäre
schön, wenn die Bilder dort auch funktionieren."

### Ursache

Die "Bilder der Apps" sind keine echten Bilddateien, sondern rohe
Unicode-Emoji-Zeichen (`{{ app.emoji }}` in `startseite.html`, ebenso an
über 300 weiteren Stellen im ganzen Portal). Emoji-Zeichen brauchen eine
vom Betriebssystem bereitgestellte Color-Emoji-Schriftart, um sichtbar zu
sein - Windows und macOS bringen das serienmäßig mit, viele minimale
Linux-Installationen (insbesondere schlanke Kiosk-Images, wie sie für
Home-Assistant-Wandtablets typisch sind) NICHT. Ohne passende Schriftart
zeigt der Browser gar nichts oder ein leeres Rechteck an - kein
Chrome-Kiosk-Modus-Bug im eigentlichen Sinne, sondern ein fehlendes
System-Font-Paket auf genau dieser Maschine, das das Portal selbst nicht
beheben kann (kein Zugriff auf fremde Systeme, siehe bauplan.md).

### Lösung

`twemoji.js` (Twitter/Twemoji, MIT-Code + CC-BY-4.0-Grafiken) lokal
gebündelt statt von einem CDN geladen (Projekt-Konvention) - ersetzt jedes
im DOM erkannte Emoji-Zeichen durch ein `<img class="emoji">` mit lokal
gehostetem SVG. Dadurch hängt die Darstellung nicht mehr vom Font-Angebot
des Betrachter-Systems ab, funktioniert identisch auf jedem Gerät/Browser.
Nur die im Portal tatsächlich vorkommenden ca. 74 Emoji-Grafiken
heruntergeladen (kein kompletter Font, ~240 KB statt zig MB) - Liste
automatisiert aus allen `.py`/`.html`-Dateien extrahiert. `base.html` ruft
`twemoji.parse()` einmalig nach dem initialen Seitenaufbau auf.

### Stolperstein: `folder: ''` wird von twemoji.js ignoriert

Erster Deploy-Versuch: `twemoji.parse()` lief zwar, erzeugte aber URLs wie
`/static/twemoji72x72/2705.svg` statt `/static/twemoji/svg/2705.svg` -
`{folder: ''}` sollte "kein Unterordner" bedeuten, wird intern aber per
`how.folder || <Standard>` ausgewertet und ein leerer String ist in JS
falsy, fällt also still auf twemojis PNG-72x72-Standardordner zurück (der
in dieser Bereitstellung gar nicht existiert - 404, Bild bleibt leer).
Fix: `folder: 'svg'` (echter, nicht-leerer Ordnername) + eigene SVG-Dateien
entsprechend nach `src/static/twemoji/svg/` verschoben, neuer Eintrag in
server.md "Bekannte Issues" mit der allgemeinen Lehre dazu.

### Verifiziert

Live im Browser: nach dem Laden sind alle App-Kachel-Emoji als
`<img class="emoji" src="/static/twemoji/svg/....svg">` im DOM vorhanden
statt als reiner Unicode-Text, Größe skaliert korrekt mit der jeweiligen
`font-size` der Umgebung (Kacheln 40px, Fließtext kleiner). Die eigentliche
Symptomursache (fehlende Emoji-Schriftart auf einer bestimmten Linux-
Maschine) lässt sich von hier aus nicht direkt nachstellen/gegentesten -
das Ergebnis sollte aber unabhängig vom Betrachter-System identisch
aussehen, da es keine Systemschriftart mehr benötigt.

### Auslieferungspaket

`deploy/portal-v108.tar.gz`

---

## 2026-08-03 – portal-v107: Wünsche #116 + #117 + #118 – Packliste: zuletzt geöffnetes Ziel merken, Eltern-Rechte

### Wunsch #116 – Zuletzt geöffnete Packliste merken

"Die zuletzt von einem Benutzer geöffnete Packliste soll beim Öffnen der
App geladen werden." Neue Tabelle `packlisten_nutzer_ziel` (user_id PK,
ziel_id) - bewusst server-seitig statt sessionStorage (wie sonst in
diesem Portal üblich, z. B. Einkaufs Wunsch #58), weil "von einem
Benutzer" gemeint ist, nicht "in diesem Browser-Tab" - soll also über
Geräte/Sitzungen hinweg gelten. `_aktives_ziel_fuer_index()`: ohne
explizites `?ziel=` wird die Merkung geladen (falls das Ziel noch aktiv
ist, sonst Fallback aufs erste aktive Ziel); mit explizitem `?ziel=`
(Ziel-Umschalter angeklickt) wird die Merkung per UPSERT aktualisiert.

### Wunsch #117 + #118 – Eltern dürfen Ziele/Kategorien verwalten

"Nur Eltern sollen neue Packlisten anlegen und deaktivieren können" /
"Nur Eltern sollen Kategorien anlegen/ändern und deaktivieren können."
Neue `_darf_verwalten()`-Prüfung (Admin ODER Rolle 'eltern', gleiches
Muster wie `13_kinderplan.py`) ersetzt die bisherige reine
Admin-Prüfung in `ziele_verwalten()`, `kategorien_verwalten()` und
`kategorien_reorder()`. Menü-Sichtbarkeit in `base.html`
(`zeigt_packliste_items`) entsprechend erweitert, sonst hätten Eltern
die Verwaltungslinks gar nicht gesehen, obwohl sie jetzt Zugriff haben.

### Verifiziert

UPSERT-Syntax (`ON CONFLICT(user_id) DO UPDATE`) isoliert gegen
In-Memory-SQLite getestet - zweiter Aufruf für denselben Nutzer
aktualisiert korrekt statt einen Konflikt zu werfen.

### Auslieferungspaket

`deploy/portal-v107.tar.gz`

---

## 2026-08-02 – portal-v106: Wünsche #114 + #115 – Pool-Aufgaben zurücklegen, Geholfen-Zuweisungen als Einzeltermine

### Wunsch #114 – Pool-Aufgaben zurücklegen

"Aufgaben, die aus dem Pool geplant wurden, sollen dorthin auch wieder
zurückgelegt werden können." Neue Route `/serie_zuruecklegen/<id>` +
↩️-Button neben jedem eingeplanten Pool-Eintrag: löscht die todos-Zeile
echt (kein Status-Toggle wie beim Abhaken), macht die Vorlage für
betroffene Tage sofort wieder gemäß `serie_verfuegbar_am()` verfügbar.

### Wunsch #115 – Geholfen-Zuweisungen als Einzeltermine statt Wochenregel

"Aufgaben der Geholfen Kategorie sollen immer nur für den einen Tag
gelten, wenn sie geplant werden." Kehrt eine bewusste frühere Entscheidung
(Wunsch #92: "bestehende Routine bleibt automatisch bestehen") um - vorab
per Rückfrage bestätigt, inklusive der Frage, was mit bereits bestehenden
Wochenroutinen passieren soll. Andi hat sich für die radikalere Variante
entschieden: ALLE Zuweisungen (auch bestehende) werden zu Einzelterminen,
keine Regel bleibt als fortlaufendes Muster erhalten.

`kinderplan_eintraege` bekommt eine neue Spalte `plan_tag` (echtes Datum),
`wochentag` bleibt als zusätzliche, nicht mehr für die Anzeige genutzte
Spalte bestehen (weiterhin NOT NULL, wird bei jeder Zuweisung mitgeschrieben).
Die UNIQUE-Constraint ändert sich von `(user_id,aufgabe_id,wochentag)` zu
`(user_id,aufgabe_id,plan_tag)` - SQLite kann das nicht per ALTER TABLE,
deshalb Tabellen-Neubau wie beim Essensplan-Umbau. Migration materialisiert
jede bestehende Wochenregel zu Einzelterminen für jeden zu ihrem Wochentag
passenden Tag im beim Deploy aktuell sichtbaren 14-Tage-Fenster (aktuelle +
nächste Woche) - Wochen danach haben keine automatische Fortsetzung mehr.
`/zuweisen` schreibt jetzt nur noch für den angeklickten Tag statt für
jeden Tag mit demselben Wochentag.

### Stolperstein: `_init_db()`-Verbindung hat kein `row_factory=Row`

Erster Deploy-Versuch stürzte beim Start ab: `TypeError: tuple indices
must be integers or slices, not str` bei `regel["wochentag"]`. Ursache:
`_init_db()` verbindet sich mit einer rohen `sqlite3.connect(...)` OHNE
`row_factory=sqlite3.Row` (anders als `get_db()` zur Laufzeit) -
`fetchall()` liefert dort nur nackte Tupel, Zugriff ausschließlich per
Index. Der erste, fehlgeschlagene Versuch hatte bereits `ALTER TABLE
RENAME` + `CREATE TABLE` ausgeführt, bevor er beim Kopieren der Daten
abstürzte - die neue Tabelle existierte danach schon (mit `plan_tag`),
aber leer, während `kinderplan_eintraege_alt` mit Friederikes echter
"Tisch decken"-Regel unangetastet liegen blieb (kein Datenverlust, nur
unvollständige Migration). Fix: Code auf Tupel-Indizes umgestellt UND die
Bedingung von "Spalte fehlt" auf "Alt-Tabelle existiert noch" geändert,
damit ein zweiter Durchlauf eine unterbrochene Migration sauber fortsetzt
statt sie (weil die neue Spalte ja schon da ist) fälschlich zu überspringen.
**Für jede künftige `_init_db()`-Migration mit Python-seitiger
Datenverarbeitung: Tupel-Indizes verwenden, nie `row["spalte"]` - diese
Verbindung hat keine Row-Factory.**

### Verifiziert

Vor dem Deploy: Produktivstand geprüft (genau eine echte Regel -
Friederike, "Tisch decken", Mittwochs). Nach dem (korrigierten) Deploy:
`kinderplan_eintraege_alt` korrekt gelöscht, neue Tabelle enthält genau
zwei Zeilen (2026-07-29 und 2026-08-05 - die beiden Mittwoche im
14-Tage-Fenster), exakt wie erwartet. Live im Browser (Friederikes echter
Plan): "Tisch decken" erscheint nur an diesen zwei Tagen, sonst nirgends.
Neue Testzuweisung ("Zimmer aufräumen" am 30.07., einem Donnerstag)
bestätigt: erscheint NICHT am nächsten Donnerstag (06.08.) - echtes
Einzeltermin-Verhalten, danach wieder entfernt. Wunsch #114 end-to-end
getestet: "Müll rausbringen" für den 28.07. eingeplant, per ↩️ wieder
zurückgelegt - Eintrag verschwindet, Tag zeigt den Pool-Kandidaten
sofort wieder an.

### Auslieferungspaket

`deploy/portal-v106.tar.gz`

---

## 2026-08-02 – portal-v105: Wünsche #112 + #113 – Serienaufgaben: mehrere Wochentage, periodische Wiederkehr

### Wunsch #112 – Mehrere Wochentage je Serie

"Serienaufgaben sollen auch an mehreren Wochentagen möglich sein." Neue
Spalte `todo_serien.feste_wochentage` (kommagetrennt, z. B. "1,3,5"),
ersetzt das alte `fester_wochentag` (Einzelwert, bleibt als totes
Altfeld liegen, per Migration in die neue Spalte übernommen). Die
Wochentag-Chips im Anlegen-Formular (`todo_serien.html`) sind jetzt
Mehrfachauswahl (togglen unabhängig statt sich gegenseitig
auszuschließen, gleiches Muster wie Einkaufs Markt-Mehrfachauswahl).

### Wunsch #113 – Periodische Wiederkehr statt "einmal fällig, für immer verfügbar"

"Serienaufgaben sollen auch dann zur Planung vorgeschlagen werden, wenn
die Wiederholungsfrist noch nicht abgelaufen ist. Beispiel: 'Blumen
gießen' alle 2 Tage - ist am Montag eingeplant, dann wird es am Dienstag
nicht vorgeschlagen, aber am Mittwoch kann ich es schon auf den Plan
nehmen, ebenso am Freitag, aber nicht am Donnerstag & Samstag."

Vorab per Rückfrage geklärt, da der Wunsch strukturell zwei
Verhaltensänderungen brauchte: (a) mehrere gleichzeitig offene Instanzen
derselben Serie an verschiedenen Tagen (statt einer einzigen, die den
ganzen Pool blockiert, bis sie erledigt ist), UND (b) eine periodische
Wiederkehr ab dem letzten EINGEPLANTEN Tag statt ab dem letzten
ERLEDIGT-Zeitpunkt.

Alte Logik (`_serie_ist_im_pool()`): blockierte den kompletten Pool,
solange irgendeine offene Instanz existierte; nach Erledigung war die
Vorlage ab Erreichen der Schwelle (`erledigt_am + intervall_tage`) FÜR
IMMER verfügbar (`datetime.now() >= schwelle`), nicht nur am
periodischen Zieltag.

Neue Logik: `serie_verfuegbar_am(db, serie, tag_iso)` prüft PRO
KALENDERTAG (nicht mehr global), zwei Regeln: (1) für GENAU diesen Tag
existiert noch keine eigene Instanz - kein Doppel-Eintrag am selben Tag,
andere Tage bleiben aber frei einplanbar; (2) bei "wochentag" muss der
Tag zu einem der konfigurierten Wochentage passen (unabhängig von
irgendeinem Anker); bei "intervall" muss die Differenz zum zuletzt
EINGEPLANTEN Tag (`MAX(plan_tag)` über alle Instanzen dieser Serie) ein
POSITIVES VIELFACHES von `intervall_tage` sein - periodisch statt
monoton. `serien_pool_liste()` (einmal global) wurde zu
`serien_pool_fuer_tag()` (einmal je sichtbarem Kalendertag in
kinderplan.py, `alle_serien` einmal vorab geladen und wiederverwendet,
um nicht 14x dieselbe Tabelle abzufragen).

### Verifiziert

Isolierter Test der reinen Logikfunktionen (ohne Flask-Abhängigkeit,
gegen eine In-Memory-SQLite-DB) mit genau Andis Beispiel: Serie "alle 2
Tage" - zuletzt Montag eingeplant → Di `False`, Mi `True`, Do
`False`, Fr `True`, Sa `False` - exakte Übereinstimmung mit der
Wunschbeschreibung. Zusätzlich getestet: Wochentag-Serie mit Di+Do
liefert an beiden Tagen `True`, an allen anderen `False`; ein Tag mit
bereits existierender eigener Instanz liefert unabhängig von
Intervall/Wochentag `False` (kein Doppel-Eintrag).

### Auslieferungspaket

`deploy/portal-v105.tar.gz`

---

## 2026-08-02 – portal-v104: Wunsch #111 – Neue App: Packliste

"Wir brauchen eine neue App: Packliste. Sehr ähnlich zur Einkaufsliste.
Es gibt Ziele (Urlaube, Ausflüge), die wie ein Markt angelegt/deaktiviert
werden können. Es gibt Kategorien (Anreise, Kleidung, Bad&Hygiene,
FeWo-Küche, Reiseapotheke, Technik, Freizeit, Sonstiges), die auch
sortiert werden können sollen. Und es gibt die Einträge, die aber
jeweils noch an eine Person verknüpft werden können sollen. Dann gibt es
den 'Packmodus' wie den 'Einkaufs starten', und man kann je Person oder
allgemein zu packen beginnen. Denke die Oberfläche sorgfältig durch,
bevor du die App entwickelst!"

### Vorab geklärte Design-Entscheidungen (per Rückfrage, 2026-08-02)

Drei architektonisch wichtige Fragen vor dem Bauen geklärt, da der Wunsch
selbst mehrdeutig ließ, wie eng die Analogie zur Einkaufsliste gemeint
war:

1. **Ziel-Scope:** Die Übersicht zeigt immer nur EIN aktives Ziel
   gleichzeitig (wie ein eigener "Ordner" pro Reise), nicht alle Ziele
   gemeinsam mit Ziel-Badge wie bei Einkaufs Mehrfach-Märkten - eine
   Packliste ist anders als die Einkaufsliste zeitlich an eine Reise
   gebunden, kein Dauer-Zustand.
2. **Ziel-Zuordnung:** Ein Eintrag gehört zu GENAU EINEM Ziel, nicht
   mehreren gleichzeitig (anders als Angebote bei mehreren Märkten).
3. **Personen-Zuordnung:** Ein Eintrag ist entweder einer Person
   zugeordnet ODER "allgemein" (niemandem) - nicht mehreren Personen
   gleichzeitig. Packmodus je Person zeigt: deren Einträge + alle
   allgemeinen; "Allgemein" zeigt NUR die allgemeinen.

### Architektur

Neues Modul `17_packliste.py`, bewusst sehr eng an `10_einkauf.py`
angelehnt (Code für Kategorien-Verwaltung inkl. Drag&Drop-Reorder ist
praktisch 1:1 übernommen, nur Tabellennamen getauscht). Drei neue
Tabellen: `packlisten_ziele` (wie `einkauf_laeden`, aber bewusst OHNE
Umbenennen - Andi nannte es explizit "wie ein Markt", Läden unterstützen
ebenfalls kein Umbenennen), `packlisten_kategorien` (identisch zu
`einkauf_kategorien`, vorbelegt mit Andis acht genannten Kategorien),
`packlisten_eintraege` (`ziel_id` FK cascade, `kategorie_id` FK,
`person_id` FK auf `users`, SET NULL = "allgemein").

`?ziel=<id>` in der URL bestimmt das aktive Ziel (`_aktives_ziel()`,
Default: erstes aktives Ziel), analog zu Sportschaus `?tage=`-Muster.
"🧳 Packen starten" (Packmodus) übernimmt Einkaufs Wunsch-#87-Teil-2-
Muster fast unverändert: Person statt Markt wählen, dann body.packmodus
+ reine Client-Filterung über `data-person`-Attribute, kein Server-
Roundtrip. Kategorie/Person-Auswahl merkt sich die letzte Wahl übers
Hinzufügen-Formular hinweg (sessionStorage, wie Einkaufs Wunsch #58).

Bewusst NICHT Teil dieser ersten Version (keine Anforderung des
Wunsches, bei Einkauf jeweils spätere separate Wünsche): Offline-
Fähigkeit, automatische Synchronisierung (Wunsch #100), ein eigener
"Filtern"-Knopf (Wunsch #87 Teil 1). Zugriff zunächst nur für Andi als
Urheber (`grant 1 packliste`) - wie bei jeder neuen App dieser Session,
Andi kann anderen selbst über den Admin-Bereich Zugriff geben.

### Verifiziert

Vollständiger Durchlauf im Browser (echte Formular-Interaktionen, keine
direkten SQL-Einträge): Leer-Zustand ohne Ziel zeigt korrekten Hinweis;
Ziel "Sommerurlaub Ostsee" angelegt, wird automatisch als aktives Ziel
ausgewählt; Eintrag "T-Shirts" (Kategorie Kleidung, Person Friederike)
und "Reiseapotheke" (Kategorie Reiseapotheke) angelegt - dabei einen
eigenen Testfehler gemacht (die "letzte Auswahl merken"-Funktion hatte
Friederike noch aktiv, per Edit-Panel auf "Allgemein" korrigiert - kein
App-Bug, sondern derselbe Effekt wie Einkaufs Markt-Erinnerung, die
sichtbar aktive Auswahl muss vor dem Speichern geprüft werden).
Packmodus für "Friederike" zeigt korrekt beide Einträge (eigener +
allgemeiner), Packmodus für "Allgemein" zeigt korrekt NUR den
allgemeinen Eintrag, T-Shirts bleibt versteckt. Gepackt-Toggle verschiebt
die Karte korrekt in den "Gepackt"-Abschnitt. Kategorien-Verwaltung:
Umbenennen und Drag&Drop-Reorder (`/kategorien/reorder`) beide korrekt
getestet und wieder zurückgesetzt. Alle Testdaten (Einträge, Test-Ziel)
anschließend bereinigt.

### Auslieferungspaket

`deploy/portal-v104.tar.gz`

---

## 2026-08-02 – portal-v103: Wünsche #108 + #109 + #110 – Sportschau: 0-Linie, Ausrichtung, Wochenansicht

### Wunsch #108 – Fehlende 0-Linie bei den Schritten

"Bei den Schritten fehlt eine '0' Linie. Füge die noch hinzu." Die
Gridline-Berechnung erzeugte bisher nur ab 2000 Schritten überhaupt eine
Linie (`if max_schritte >= 2000`). Neuer gemeinsamer Helper
`_gridlines(max_wert, schritt)` liefert jetzt immer eine 0-Linie zusätzlich
zu den `schritt`-Abstands-Linien.

### Wunsch #109 – Heatmap soll wie das Schritte-Chart gestreckt sein

"Die 14-Tage-Trainingsheatmap soll ebenso wie das Schritte-Barchart
gestreckt sein, sodass unabhängig von der Bildschirmbreite die Tage
beider Charts immer übereinanderliegen." Ursache: `.heatmap-cell` trug
selbst `max-width:22px` - dadurch füllte die ganze Zeile auf breiten
Bildschirmen nicht die volle Breite aus (blieb bei `14 * 22px + gaps`
stehen), während die Schritte-Balken über `.steps-bar-col { flex:1 }`
(Spalte streckt, Balken selbst begrenzt+zentriert) immer die volle Breite
ausfüllten. Fix: gleiches Muster übernommen - neue `.heatmap-cell-col`
streckt sich, `.heatmap-cell` selbst ist begrenzt+zentriert. Zusätzlich
`gap` in `.heatmap-cells` von 4px auf 3px vereinheitlicht (identisch zu
`.steps-bars`), für pixelgenaue Ausrichtung über beliebig viele Tage.

### Wunsch #110 – Wochenansicht für schmale Bildschirme

"Wenn die Bildschirmbreite unter ein gewisses Maß fällt und die Heatmap
zu klein wird, soll von einer Tages- auf eine Wochenansicht gewechselt
werden. Die Heatmap soll wie die Nutzeraktivität bei GitHub mit 7 Zeilen
(eine je Wochentag) dargestellt werden. Die Schritte werden je Woche
addiert und als gemeinsamer, aggregierter Balken dargestellt."

Neue Funktion `_wochen_ansicht(tage, schritte_balken)`: gruppiert nach
ISO-Kalenderwoche (`date.isocalendar()`), liefert pro Woche ein 7-Slot-
Array (Mo-So, `None` für Tage außerhalb des angefragten Zeitraums - z. B.
eine angeschnittene erste Woche) plus aufsummierte Schritte
(gesamt/training). Zweiter Gridline-Satz `wochen_gridlines` mit größerem
Abstand (10000 statt 2000 - Wochensummen sind ca. 7x höher als Tages-
werte, sonst viel zu viele Linien).

Template rendert JETZT IMMER BEIDE Ansichten (Tages- und Wochenansicht,
Klassen `.tagesansicht`/`.wochenansicht`), umgeschaltet rein per CSS
Media Query - kein Server-Roundtrip beim Umschalten, reagiert live auf
Fenstergrößenänderung. Umschaltpunkt hängt von `tage_anzahl` ab
(`tage_anzahl * 25 + 80` Pixel) - bei mehr Tagen (30/60/90) braucht die
Tagesansicht mehr Platz, bevor sie noch lesbar ist.

Die Wochenansicht der Heatmap nutzt CSS Grid statt der verschachtelten
Flexbox-Struktur der Tagesansicht: `grid-auto-flow:column` + `grid-
template-rows:repeat(7,1fr)` ordnet die in Dokumentreihenfolge
gerenderten Zellen (Woche 1 Mo..So, Woche 2 Mo..So, ...) automatisch
spaltenweise an - keine Wrapper-Divs pro Woche nötig. Eine separate
`.woche-labels`-Grid-Spalte (ebenfalls `repeat(7,1fr)`) zeigt die
Wochentags-Kürzel (Mo-So) und bleibt dank Flexbox-`stretch` (Standard-
verhalten, kein expliziter Code nötig) exakt auf gleicher Höhe wie die
Zellen-Spalten - robuster als ein Ansatz mit fest codierten Pixel-Höhen,
die bei schrumpfenden Zellen (schmale Bildschirme, viele Wochen) nicht
mehr gepasst hätten. Die Schritte-Wochenansicht nutzt exakt dieselben
CSS-Klassen wie die Tagesansicht (`.steps-bar-col`/`.steps-bar-stack`),
nur mit `wochen` statt `schritte_balken` als Datenquelle - dadurch
automatisch weniger, breitere Balken statt eng gequetschter Tagesbalken.

### Verifiziert

- Wunsch #108: Live im Browser geprüft - 0-Linie mit Label "0" immer
  vorhanden (auch bei niedrigen Schrittzahlen), weitere Linien wie bisher
  ab dem gewählten `schritt`.
- Wunsch #109: Isolierter Python-Test der `_wochen_ansicht()`-Gruppierungs-
  logik mit synthetischen Daten (14 Tage → exakt 2 volle ISO-Wochen mit
  korrekten Summen; 10 Tage → eine angeschnittene erste Woche mit
  `None`-Slots und korrekt reduzierter Summe) - beide Fälle bestanden.
  Ausrichtung per `javascript_tool`/`getBoundingClientRect()` auf
  `.heatmap-cell-col` vs. `.steps-bar-col` verglichen: 0px Abweichung über
  alle 14 Tages-Spalten.
- Wunsch #110: `resize_window` verändert in dieser Browser-Umgebung nicht
  die tatsächliche Viewport-Breite (`window.innerWidth` blieb konstant,
  unabhängig vom angeforderten Fenstermaß) - deshalb die Ansicht direkt per
  `style.setProperty('display', ..., 'important')` erzwungen, um Inhalt und
  Layout unabhängig vom Umschalt-Mechanismus zu prüfen. Dabei zunächst
  einen eigenen Messfehler gefunden und korrigiert: die zentrierte Heatmap-
  ZELLE wurde gegen die äußere Schritte-SPALTE (statt gegen den ebenfalls
  zentrierten Schritte-BALKEN) verglichen, was einen scheinbaren
  400px-Versatz zeigte - nach Korrektur des Vergleichspunkts (Zellen-
  mittelpunkt vs. Balkenmittelpunkt) 0px Abweichung über beide Wochen-
  spalten. Grüne Zellen in Tages- und Wochenansicht stimmen exakt überein
  (identische Trainingstage). Mit `?tage=90` zusätzlich geprüft: 13
  korrekt gebildete Wochen, eigener (gröberer) Gridline-Abstand für die
  Wochenansicht, und der Umschaltpunkt skaliert korrekt mit `tage_anzahl`
  (`90*25+80=2330px` im gerenderten CSS wiedergefunden). Die tatsächliche
  visuelle Reaktion auf eine echte Fenster-Größenänderung konnte in dieser
  Browser-Umgebung nicht getestet werden (Tool-Einschränkung) - die CSS-
  Media-Query-Mechanik selbst ist aber Standardverhalten und wurde korrekt
  geparst (im Stylesheet wiedergefunden).

### Auslieferungspaket

`deploy/portal-v103.tar.gz`

---

## 2026-08-02 – portal-v102: Wunsch #107 – Einbettung in Home Assistant (iFrame)

"Prüfe, ob die App/das Familienportal auch in einem iFrame unter
HomeAssistant lauffähig ist, damit die Apps auch auf dem Home Dashboard
(24" Portrait-Bildschirm unter Linux/Chrome, nur Kiosk-Ansicht, keine
Android Kiosk-App!) im Esszimmer lauffähig sind. Dokumentiere die
Anpassungen, die notwendig sind." Home Assistant läuft unter
`https://wir4.16schwaben.de` (auf Nachfrage von Andi bestätigt).

Untersucht: kein Frame-Busting-JS im Portal, PWA-Manifest irrelevant fürs
iFrame, Service Worker/Sync-Polling funktionieren unverändert innerhalb
eines iFrames (first-party, gleicher Origin). Einziger echter Blocker:
`X-Frame-Options: DENY` in der Caddyfile - verbietet kategorisch JEDES
Einbetten, unabhängig von der Quelle.

Fix: `X-Frame-Options: DENY` ersetzt durch
`Content-Security-Policy: frame-ancestors https://wir4.16schwaben.de` -
erlaubt Einbetten gezielt NUR von dieser einen Quelle (kein pauschales
`frame-ancestors *`, das wäre ein Sicherheitsrückschritt). `frame-ancestors`
ersetzt `X-Frame-Options` auf modernen Browsern vollständig, beide
gleichzeitig zu setzen wäre widersprüchlich. Ausführliche Dokumentation
inkl. noch offener, bewusst nicht automatisch entschiedener Punkte (welche
Nutzer-URL eingebettet wird, Layout auf breitem Portrait-Bildschirm,
Push-Banner beim ersten Öffnen) jetzt in server.md unter "Security-Headers
(Caddy)".

### Verifiziert

Header per `curl -I https://portal.16schwaben.de/health`: `X-Frame-Options`
verschwunden, `Content-Security-Policy: frame-ancestors
https://wir4.16schwaben.de` vorhanden. Zusätzlich mit einer lokalen
Testseite auf einer NICHT erlaubten Quelle (`http://localhost:8899`)
geprüft: das Einbetten wird dort weiterhin blockiert (Netzwerk-Log zeigt
die geblockte iFrame-Anfrage, derselbe URL-Abruf direkt liefert sauber
200) - die eigentliche Freigabe für `wir4.16schwaben.de` selbst konnte von
hier aus nicht getestet werden (kein Zugriff auf dieses System).

**Deployment-Besonderheit:** Caddyfile ist ein Single-File-Bind-Mount
(`./Caddyfile:/etc/caddy/Caddyfile:ro`) - ein einfaches `tar xzf` ersetzt
die Datei mit neuem Inode, der laufende Container bleibt aber am alten
Inode hängen (bekanntes Problem, siehe "Bekannte Issues"). Deshalb gezielt
`docker compose up -d --force-recreate caddy` statt nur `--build`.

### Auslieferungspaket

`deploy/portal-v102.tar.gz`

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
