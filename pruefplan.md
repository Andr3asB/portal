# Prüfplan – Umbau Sitzungsmodell (Wunsch #140) und CSP (Wunsch #142)

Handprüfung durch Andi nach jeder ausgelieferten Stufe. Was ein Skript sehen
kann, steht hier **nicht** drin – nach jeder Stufe läuft automatisch eine
Regression, die alle 50 Zugänge über ihre echten App-URLs aufruft. Hier steht
nur, was ein Skript prinzipiell nicht sehen kann: echtes Gerät, echter
Browser, echter iFrame, echte Installation.

## So arbeitest du damit

1. Ich sage Bescheid, wenn eine Stufe ausgeliefert ist.
2. Du gehst die Tabelle der Stufe durch und trägst in **OK?** ein: `ok` oder
   `FEHLER`.
3. Bei `FEHLER`: kurze Notiz dazu (was hast du gesehen?) und mir Bescheid
   geben – gern einfach „S3-05 FEHLER".
4. Ich schalte die Stufe dann per `.env` zurück (Sekunden, kein Rebuild),
   **bevor** ich den Fehler suche. Der letzte funktionierende Stand gilt
   sofort wieder.

Du musst nicht alles auf einmal machen. Wenn eine Stufe halb geprüft ist,
lass die Zeilen leer – ich warte.

## Geräte-Legende

Bitte einmal anpassen, falls etwas nicht stimmt:

| Kürzel | Gerät |
|---|---|
| **A-Handy** | Andis Handy (Browser) |
| **A-PC** | Andis Rechner |
| **A-PWA** | Portal als App vom Homescreen (Andi) |
| **Kiosk** | Esszimmer-Bildschirm, Portal im Home-Assistant-iFrame |
| **Kind** | Gerät von Friederike oder Johannes (Nicht-Admin-Konto) |
| **Simone** | Simones Gerät |
| **beliebig** | egal welches |

„Je Browser-Typ" heißt: ein Vertreter jeder Kombination, die es bei euch gibt
(z. B. einmal iPhone/Safari, einmal Android/Chrome, einmal Linux/Chrome am
Kiosk). Nicht je Person – siehe Erklärung bei Stufe 2.

---

## Stufe 1 – Sitzungs-Cookie wird ausgestellt

**Was passiert:** Das Portal legt beim Öffnen zusätzlich ein Cookie an. **Es
wird von nichts ausgewertet** – die Anmeldung läuft weiter ausschließlich über
den Token in der Adresse.

**Was diese Stufe gefährlich macht:** Praktisch nichts. Niemand liest das
Cookie. Der einzige wirklich wichtige Test ist S1-04 (Kiosk), weil davon
Stufe 3 abhängt.

**Merke für alle Stufen:** „Sieht unverändert aus" ist kein Testergebnis,
wenn die Frage lautet, ob etwas ankommt. Ein Kiosk zeigt eine Seite oft
stundenlang, ohne sie neu zu holen – hinsehen erzeugt keinen Zugriff. Wenn
ein Test etwas messen soll, muss er eine Aktion auslösen.

**Notausstieg:** `SITZUNG_AUSSTELLEN=0`

| ID | Test | Gerät | Erwartet | OK? | Notiz |
|---|---|---|---|---|---|
| S1-01 | Deinen normalen Portal-Link öffnen | A-Handy | Startseite wie immer, nichts sieht anders aus | ok | |
| S1-02 | Dieselbe Seite neu laden, ein paar Apps öffnen | A-Handy | Alles wie gewohnt, keine Fehlermeldung | ok | |
| S1-03 | Etwas eintragen (z. B. Artikel auf die Einkaufsliste) | A-Handy | Wird gespeichert wie bisher | ok | |
| S1-04 | **Esszimmer-Bildschirm: Seite zweimal neu laden** (nicht nur ansehen!) | Kiosk | Portal läuft weiter, kein Anmeldebildschirm. Ich messe danach serverseitig: zwei Neuladungen dürfen **zusammen nur eine** Sitzung erzeugen – sonst wird das Cookie im iFrame verworfen | ok | Gemessen: 134 Anfragen vom Kiosk → **1** Sitzung. Cookie überlebt im HA-iFrame. Damit ist die Grundannahme für Stufe 3 bestätigt. |
| S1-05 | Portal als App vom Homescreen starten | A-PWA | Startet wie gewohnt | ok | |
| S1-06 | Ein Gerät eines Kindes kurz öffnen | Kind | Unverändert | ok | |

---

**Ergebnis Stufe 1 (2026-08-06): bestanden.** Gemessen wurde zusätzlich das
Verhältnis Anfragen zu Sitzungen – würde ein Cookie verworfen, entstünde je
Anfrage eine neue Sitzung: iPhone 622→3, ChromeOS/Kiosk 134→1, Windows 107→1.
Das Cookie wird also auf allen Plattformen gespeichert und zurückgeschickt,
**auch im Home-Assistant-iFrame**.

## Stufe 2 – CSRF-Riegel

**Was passiert:** Das Portal prüft bei jeder ändernden Aktion, ob sie wirklich
von einer Portal-Seite kommt. Erst im Beobachtungsmodus (protokolliert nur),
dann scharf.

**Was diese Stufe gefährlich macht:** Wenn ein Browser die erwarteten
Kennzeichen nicht mitschickt, würde eine Aktion abgelehnt. Genau deshalb erst
beobachten – im Beobachtungsmodus wird **nichts** blockiert.

**Notausstieg:** `CSRF_MODUS=aus`

Es genügt **ein Vertreter je Browser-Typ**, nicht jede Person: Die geprüften
Kennzeichen setzt der Browser, unabhängig davon, wer angemeldet ist.
Entscheidend sind die vier verschiedenen Arten, wie das Portal Daten schickt –
die decken S2-01 bis S2-04 ab.

### 2a – Beobachtungsmodus

| ID | Test | Gerät | Erwartet | OK? | Notiz |
|---|---|---|---|---|---|
| S2-01 | Normales Formular: in der Verwaltung oder bei Rezepten etwas speichern | je Browser-Typ | Speichert normal | ok | |
| S2-02 | Antippen ohne Formular: Einkaufsartikel abhaken, Dark Mode umschalten | je Browser-Typ | Reagiert sofort wie bisher | ok | |
| S2-03 | **Flugmodus an**, 2 Artikel abhaken, Flugmodus aus, kurz warten | A-Handy | Beide Häkchen sind nach dem Wiederverbinden auch auf einem anderen Gerät zu sehen | ok (nach Behebung) | Erst FEHLER: Häkchen blieben auf „wartet". Ursache war ein vorbestehender Fehler, **nicht** der Umbau: ein Häkchen für einen inzwischen gelöschten Artikel (Antwort 404) blockierte die ganze Warteschlange dauerhaft. Behoben in portal-v118, danach erneut geprüft und bestanden. |
| S2-04 | **Vokabeltrainer eine Runde bis zum Ende** durchspielen | A-Handy oder Kind | Ergebnis erscheint in der Auswertung | ok | |
| S2-05 | Am Esszimmer-Bildschirm etwas antippen (z. B. Geholfen) | Kiosk | Wird gezählt wie bisher | ok | |

Danach melde ich dir, ob im Protokoll etwas aufgetaucht ist.

### 2b – Scharf geschaltet

| ID | Test | Gerät | Erwartet | OK? | Notiz |
|---|---|---|---|---|---|
| S2-06 | Je ein Formular abschicken | je Browser-Typ | Speichert normal | ok | |
| S2-07 | Einkaufsliste abhaken | je Browser-Typ | Reagiert normal | ok | |
| S2-08 | Am Esszimmer-Bildschirm etwas antippen | Kiosk | Funktioniert | ok | |
| S2-09 | Nochmal Flugmodus-Test wie S2-03 | A-Handy | Häkchen kommen an | ok | |

**Ergebnis Stufe 2 (2026-08-06): bestanden.** Der Riegel steht auf `scharf`.
Null Verdachtsfälle bei echten Geräten während der Beobachtungsphase; nach dem
Scharfschalten geprüft: eigene Seite 200, fremde Seite 403, Home-Assistant-Seite
(same-site) 403, lesende Zugriffe unberührt.

---

## Stufe 3 – Cookie gilt als Anmeldung

**Was passiert:** Ab jetzt kommt man auch ohne Token in der Adresse rein, wenn
das Cookie da ist. Der Token behält aber **immer Vorrang**.

**Was diese Stufe gefährlich macht:** Das ist der kritische Punkt. Hier
entscheidet sich, ob jemand ausgesperrt wird oder – schlimmer – auf einem
geteilten Gerät das falsche Konto sieht.

**Notausstieg:** `SITZUNG_KONSUMIEREN=0`

| ID | Test | Gerät | Erwartet | OK? | Notiz |
|---|---|---|---|---|---|
| S3-01 | Portal öffnen, dann in der Adresszeile alles ab `/p/` löschen und nur `portal.16schwaben.de/start` aufrufen | A-PC | Du bist drin, deine Startseite mit deinem Namen | ok | |
| S3-02 | Dasselbe auf einem Kind-Gerät | Kind | Kommt rein, sieht **seine** Startseite mit **seinem** Namen | ok | |
| S3-03 | Auf dem Kind-Gerät prüfen, welche Apps sichtbar sind | Kind | Nur die freigeschalteten – **keine Verwaltung** | ok | |
| S3-04 | Auf dem Kind-Gerät versuchen, einen fremden Eintrag zu löschen (z. B. Aufgabe) | Kind | Geht weiterhin nicht (Löschen ist Eltern/Admin) | ok | |
| S3-05 | **Vorrangtest:** Auf deinem Gerät (angemeldet als Andi) den Link eines Kindes öffnen | A-Handy | Es erscheint die Seite **des Kindes**, nicht deine | ok | |
| S3-06 | **Widerruf:** In der Verwaltung bei einem Kind „Zugänge neu" klicken. Danach auf dessen Gerät die Seite neu laden | Kind | Kommt **nicht** mehr rein – muss den neuen Link/QR bekommen | ok | |
| S3-07 | Nach S3-06 den neuen QR-Code scannen | Kind | Kommt wieder rein | ok | |
| S3-08 | **Esszimmer-Bildschirm ansehen** | Kiosk | Läuft unverändert. **Auf keinen Fall ein Anmeldebildschirm** | ok | |
| S3-09 | Portal-App vom Homescreen starten | A-PWA | Startet und ist angemeldet | ok | |

**Ergebnis Stufe 3 (2026-08-06): bestanden**, auf echten Geräten inklusive
Vorrangtest, Widerruf und Kiosk.

---

## Stufe 4 – Token verschwindet aus der Adresse

**Was passiert:** Die Adresszeile zeigt keinen Token mehr. Der alte Link mit
Token funktioniert weiterhin – er ist ab jetzt der Ersteinstieg und die
Rückfallebene.

**Was diese Stufe gefährlich macht:** Die Startadresse der installierten App
ändert sich. Wer das Portal auf dem Homescreen hat, muss hier hinsehen. Und:
Auf einem **geteilten Gerät** entscheidet ab jetzt das Cookie, wessen Seiten
man sieht – nicht mehr der Link, auf den man getippt hat.

**Notausstieg:** `TOKENFREIE_URLS=0`

**Nachtrag v123 – der Offline-Fehler, den du gemeldet hast:** Zwei Ursachen.
Die eine war dauerhaft: `/p/<token>` antwortet jetzt mit einer Weiterleitung,
und eine Weiterleitung kann der Offline-Speicher grundsätzlich nicht ablegen –
ausgerechnet die Adresse, mit der die App vom Homescreen und jedes alte
Lesezeichen startet. Behoben: Findet das Portal offline nichts zur
aufgerufenen Adresse, zeigt es die gespeicherte Startseite statt einer
Sackgasse. Die andere Ursache war einmalig: Beim Umbau wurde der gesamte
Offline-Speicher geleert (die alten Seiten enthielten noch Token in ihren
Links). **Jede Seite braucht deshalb einmal einen Besuch mit Empfang, bevor
sie offline verfügbar ist.** Das holt sich von selbst nach. Nachtest: S4-12.

**Schon von hier aus geprüft** (musst du nicht wiederholen): alle 50 Zugänge
über ihre alten Token-Adressen → 50 × OK; alle vier Nutzer token-frei durch
jede ihrer Apps → 46 × OK; ohne Cookie kommt niemand rein (403); in keiner
ausgelieferten Seite steht noch irgendein Token. Was hier **nicht** prüfbar
ist und deshalb unten steht: echte Geräte, die installierte PWA, der
Kiosk-iFrame und der Offline-Cache.

**Beim Testen selbst aufgefallen und schon behoben:** Öffnete jemand seinen
Link auf einem Gerät, dessen Cookie noch einem anderen gehörte, zeigte die
Startseite korrekt die richtige Person – ab dem ersten Tippen aber die Seiten
des Vorgängers. Der Vorrang des Links hielt nur eine Seite lang. Jetzt
übernimmt der geöffnete Link das Gerät vollständig. **S4-10 prüft genau das**
und ist der wichtigste Test dieser Stufe.

| ID | Test | Gerät | Erwartet | OK? | Notiz |
|---|---|---|---|---|---|
| S4-01 | Portal öffnen und durch **alle** deine Apps klicken | A-Handy | Alles erreichbar, Adresse enthält keinen langen Zeichensalat mehr | | |
| S4-02 | Dasselbe | Kind | Alle seine Apps erreichbar | | |
| S4-03 | Dasselbe | Simone | Alle ihre Apps erreichbar | | |
| S4-04 | **Alter Link mit Token** (aus deinem Lesezeichen) öffnen | A-Handy | Funktioniert weiterhin und leitet auf die neue Adresse | | |
| S4-05 | **Portal-App vom Homescreen starten** | A-PWA | Startet und zeigt die Startseite – nicht „Zugang verweigert" | | |
| S4-06 | Portal neu als App installieren (zum Homescreen hinzufügen) | A-Handy | Installiert sich, startet korrekt | | |
| S4-07 | Esszimmer-Bildschirm ansehen | Kiosk | Läuft unverändert | | |
| S4-08 | Flugmodus-Test wie S2-03 | A-Handy | Häkchen kommen an | | |
| S4-09 | Eine Seite als Lesezeichen speichern und später öffnen | A-Handy | Kommt an der richtigen Stelle an | | |
| S4-10 | **Geteiltes Gerät:** Auf einem Gerät, auf dem zuletzt *du* drin warst, den Link eines Kindes öffnen. Dann auf eine Kachel tippen. | ein Gerät, das zwei Leute benutzen (iPad/Kiosk) | Es bleibt beim Kind – auch nach dem Tippen. Nirgends deine Daten. Danach mit deinem Link zurückwechseln: es bleibt bei dir. | ok | |
| S4-11 | Nach S4-10 auf demselben Gerät **im Flugmodus** eine schon besuchte Seite öffnen | dasselbe Gerät | Die Seite des *aktuellen* Nutzers oder die Offline-Meldung – niemals die des Vorgängers | ok | |
| S4-12 | **Nachtest zum Offline-Fehler (v123).** Erst online einmal die Startseite und die Einkaufsliste öffnen. Dann Flugmodus. Dann: (a) die Portal-App vom Homescreen starten, (b) ein altes Lesezeichen mit Token öffnen, (c) die Einkaufsliste öffnen. | A-Handy + A-PWA | (a) und (b) zeigen die Startseite statt „noch nie geladen"; (c) zeigt die Einkaufsliste | ok | Bestätigt 2026-08-06: „jetzt kommt keine Fehlermeldung mehr". |

---

## Stufe 5 – Knöpfe umgebaut, strengere Sicherheitsregel (#142)

**Was passiert:** Alle Knöpfe werden technisch anders angebunden, damit der
Browser eingeschleusten Code blockieren kann.

**Was diese Stufe gefährlich macht:** Wenig – schlimmstenfalls reagiert ein
Knopf nicht mehr. Kein Datenverlust, keine Aussperrung. Dafür sind es viele
Knöpfe, das Prüfen ist mühsam.

**Notausstieg:** Paket zurückrollen (kein Schalter, weil es reines Frontend ist)

| ID | Test | Gerät | Erwartet | OK? | Notiz |
|---|---|---|---|---|---|
| S5-01 | Einkaufsliste: hinzufügen, abhaken, bearbeiten, löschen | beliebig | Alles reagiert | | |
| S5-02 | Aufgaben: anlegen, Status ändern, bearbeiten, löschen | beliebig | Alles reagiert | | |
| S5-03 | Geholfen: antippen, Verlauf, Eintrag bearbeiten/löschen | beliebig | Alles reagiert | | |
| S5-04 | Rezepte: anlegen, bewerten, wünschen, löschen | beliebig | Alles reagiert | | |
| S5-05 | Essensplan und Aufgabenplan: eintragen und entfernen | beliebig | Alles reagiert | | |
| S5-06 | Packliste: hinzufügen, abhaken, Packmodus | beliebig | Alles reagiert | | |
| S5-07 | Vokabeln: anlegen, trainieren, Auswertung | beliebig | Alles reagiert | | |
| S5-08 | Tierbaukasten: Figur bauen und speichern | beliebig | Vorschau aktualisiert sich, Speichern geht | | |
| S5-09 | TVB: Mannschaft umschalten, Kader öffnen | beliebig | Umschalter reagiert | | |
| S5-10 | Werkstatt: Wunsch aufklappen, Priorität ändern, filtern | beliebig | Alles reagiert | | |
| S5-11 | Verwaltung: Nutzer bearbeiten, App freischalten, QR anzeigen | A-PC | Alles reagiert | | |
| S5-12 | **Löschabfragen:** Irgendwo etwas löschen | beliebig | Die Sicherheitsabfrage „…wirklich löschen?" erscheint weiterhin | | |
| S5-13 | Menü (☰), Dark Mode umschalten, ✨-Wunsch abschicken | beliebig | Alles reagiert | | |

---

## Stufe 6 – Tokens nur noch als Prüfsumme gespeichert

**Was passiert:** Der Klartext-Token verschwindet endgültig aus der Datenbank.
Links und QR-Codes lassen sich danach **nicht mehr nachschlagen**, nur noch
neu erzeugen.

**Was diese Stufe gefährlich macht:** Sie ist nicht ohne Weiteres
rückrollbar – die Klartexte sind danach weg. Ich mache vorher einen Probelauf
auf einer Kopie der Datenbank und eine Sicherung, wie schon bei Wunsch #129.

**Notausstieg:** Datenbanksicherung zurückspielen (langsamer als die anderen
Stufen – deshalb hier besonders sorgfältig prüfen)

| ID | Test | Gerät | Erwartet | OK? | Notiz |
|---|---|---|---|---|---|
| S6-01 | Alle vier Zugänge nacheinander öffnen | alle 4 | Jeder kommt in seine Apps | | |
| S6-02 | Esszimmer-Bildschirm | Kiosk | Läuft unverändert | | |
| S6-03 | In der Verwaltung nachsehen | A-PC | Es werden **keine** Zugangsadressen mehr im Klartext angezeigt | | |
| S6-04 | Bei einem Nutzer „Zugänge neu", QR sofort scannen | Kind | Neuer Zugang funktioniert | | |
| S6-05 | Verwaltung neu laden und denselben QR nochmal suchen | A-PC | Ist nicht mehr abrufbar – nur direkt nach dem Erzeugen (so gewollt) | | |

---

## Rückmeldungen an Claude

Hier ist Platz für Beobachtungen, die in keine Zeile passen:

```
(frei)
```
