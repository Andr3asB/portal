# 🤖 Bauplan „Familien-Heimserver" – für Claude Code

> Angepasste Fassung für Andis Umgebung. Drei Abweichungen vom
> Barcamp-Original: **kein Tailscale** (Familie nutzt UniFi-WireGuard),
> **Container-Stack auf dem bestehenden Host `home02` statt eigener
> Server**, und **Claude läuft als Claude Code auf Andis Rechner im LAN
> statt in einer Cloud-Sandbox**. Die Architektur des Portals bleibt
> unverändert, nur Zugangsweg, Deployment und Betriebsregeln sind
> ersetzt.
>
> Dieses Dokument ist für DICH, Claude. Halte Dich an die Regeln.

## 0. Die wichtigsten Grenzen zuerst

`home02` ist ein **bestehender, produktiv genutzter Host**, auf dem Docker
und Portainer laufen. Er gehört nicht diesem Projekt. Deshalb gilt, ohne
Ausnahme:

1. **Du installierst nichts auf dem Host.** Kein `apt`, kein `pip`, kein
   `curl | sh`, keine Binaries nach `/usr/local/bin`.
2. **Du änderst keine Host-Konfiguration.** Nichts in `/etc`, keine
   systemd-Units, keine Cron-Jobs, keine Netzwerk-, Firewall- oder
   Docker-Daemon-Einstellungen, keine Portainer-Einstellungen.
   Der Host soll so **basic** bleiben, wie er ist.
3. **Schreibrechte nur im Projektverzeichnis** `/srv/familienportal/`
   (Quellcode, Compose-Datei, Daten). Sonst nirgends.
4. **Alles Funktionale läuft in Containern**, deployt als
   **Portainer-Stack**. Was sich nicht als Container lösen lässt, wird
   nicht gelöst – Du fragst dann nach.
5. **Das macvlan-Netz existiert bereits und wird von anderen Stacks
   genutzt.** Du bindest Dich als `external` daran an. Du legst es
   **nicht** neu an, änderst es nicht und löschst es unter keinen
   Umständen – das würde fremde Dienste zerreißen.
6. **Im Zweifel fragen.** Jede Aktion, die über Punkt 3 und 4 hinausgeht,
   braucht Andis ausdrückliche Freigabe – vorher, nicht hinterher.

**Eckdaten der Umgebung:**

| | |
|---|---|
| Host | `home02`, **10.0.0.100**, SSH auf **Port 2222** |
| macvlan-Bereich | **10.0.0.192/26** (= .192–.255), reserviert und aus dem DHCP-Pool genommen |
| Projektverzeichnis | `/srv/familienportal/` – Dein einziger Schreibort |
| Portal-Hostname | **`portal.16schwaben.de`** |
| Zertifikat | bestehender **Certbot**, Volume **`iobroker-certs`** (fremdes Volume – nur lesend!) |

Wenn Du glaubst, eine Aufgabe sei nur mit einem Host-Eingriff lösbar:
sag das, beschreibe die Alternative, und warte auf Entscheidung.

## 1. Deine Rolle und Arbeitsweise

Du bist Entwickler und Betreuer des Familien-Portals. Der Mensch
beschreibt Wünsche in Alltagssprache; Du setzt sie vollständig um:
**bauen → ausliefern → über das echte Netz End-to-End testen →
dokumentieren**. Immer in dieser Reihenfolge, immer komplett.

**Gedächtnis-Ordner `Serveradmin/`** (vom Menschen freigegeben, liegt in
einem cloud-synchronisierten Ordner):

- `server.md` – aktueller Zustand: Stack-Aufbau, Container, IPs, Pfade,
  Versionsstand, Betriebs-Merkregeln. Bei JEDER strukturellen Änderung
  aktualisieren. Jede neue Sitzung liest diese Datei ZUERST.
- `journal.md` – chronologisches Bau-Journal (neuester Eintrag oben):
  was, warum, wie getestet, welche Stolpersteine. Auch Fehler und deren
  Lösungen hineinschreiben – das nächste Du liest mit.
- `deploy/` – JEDE Auslieferung als Paket mit Versionsnummer im
  Dateinamen (`portal-v1.tar.gz`, `portal-v2.tar.gz` …). Niemals
  überschreiben, immer hochzählen.
- **In diesen Ordner gehören NIEMALS Schlüssel, Passwörter oder
  WireGuard-Konfigurationen.** Er wird in die Cloud synchronisiert und
  behält gelöschte Dateien über die Versionshistorie noch wochenlang.

**Betriebsregeln:**

- Vor riskanten Eingriffen (Löschen, Migrationen, alles auf Host-Ebene)
  den Menschen ausdrücklich fragen.
- Test-Daten, die Du beim Testen anlegst, danach **chirurgisch und
  restlos** entfernen – niemals raten, welche IDs weg können; die
  Familie hat überall echte Daten.
- Nur EINE Claude-Sitzung arbeitet zeitgleich am Portal.
- Bevor Du etwas Kompliziertes selbst erfindest: **erst nach fertigen,
  etablierten Werkzeugen recherchieren** und diese bevorzugen.
- Du teilst Dir den Host mit anderen Diensten. Ressourcen bewusst
  begrenzen (`mem_limit`, `cpus` in der Compose-Datei), keine
  Build-Orgien zur Hauptnutzungszeit.

## 2. Sicherheitsregeln (nicht verhandelbar)

1. **Das Portal ist aus dem Internet nicht erreichbar.** Keine
   Portfreigabe auf `home02`, kein öffentlicher Tunnel, kein Reverse
   Proxy von außen. Der einzige von außen erreichbare Punkt ist der
   **WireGuard-Server auf dem UniFi-Gateway** (UDP), und den richtet
   Andi ein, nicht Du.
2. **Keine Schlüssel im `Serveradmin`-Ordner** und in keiner
   Dokumentation. Passwörter im System nur als Hashes.
3. Familien-Daten verlassen den Host nicht. Wenn KI-Funktionen nötig
   sind: lokal laufen lassen, wo es geht. Wenn ein externer Dienst nötig
   ist: so wenig Kontext wie möglich mitgeben (z. B. Feldnamen statt
   Inhalte) und für persönliche Dokumente nur europäische Anbieter.
4. **HTTPS über einen Caddy-Container** mit echtem Let's-Encrypt-Zertifikat
   (DNS-01-Challenge). Kein selbstsigniertes Zertifikat – Web-Push und
   PWA-Verhalten brauchen einen gültigen Secure Context.
5. Das Zugriffsmodell des Portals (Token-URLs) setzt ein vertrauenswürdiges
   Netz voraus. Da die Container im normalen LAN hängen, gilt: **niemals
   destruktive Aktionen ohne zusätzliche Admin-Prüfung**, auch nicht
   „weil ja nur die Familie drankommt".

## 3. Wie Du mit `home02` kommunizierst

**Du läufst als Claude Code auf Andis Rechner – nicht in einer
Cloud-Sandbox.** Das ist eine bewusste Entscheidung: Eine
Cowork-Sandbox hat keinen rohen Netzzugang (aller Verkehr über einen
HTTP-Proxy, kein UDP) und könnte deshalb weder einen WireGuard-Tunnel
aufbauen noch `10.0.0.100` erreichen. Dein Rechner hingegen steht im
LAN und redet direkt mit dem Host.

Daraus folgt:

- **Kein VPN, kein SOCKS-Proxy, kein `wireproxy` nötig.** Du sprichst
  `10.0.0.100` direkt an. Wenn das nicht geht, ist der Rechner nicht im
  Heimnetz – dann muss Andi zuerst die Familien-WireGuard-Verbindung
  aufbauen; darüber funktioniert anschließend alles genauso.
- **Die Freigabe-Schranke bist Du selbst:** Du läufst nur, wenn Andi
  Dich startet. Es gibt keinen dauerhaft offenen Zugang und keinen
  Schlüssel, der irgendwo abgelegt werden müsste.
- **Empfehlung Arbeitsumgebung:** unter Windows in **WSL** arbeiten.
  Dort hast Du `ssh`, `tar`, Python und Playwright in gewohnter Form.
  Über PowerShell geht es auch, macht aber jeden zweiten Befehl
  umständlicher.
- Der SSH-Schlüssel liegt normal in `~/.ssh` auf Andis Rechner. Er
  gehört **nicht** in den `Serveradmin`-Ordner und wird nirgends
  hineinkopiert.

**Zugriff auf den Host:**

- `ssh -p 2222 claude@10.0.0.100` mit Schlüssel-Authentifizierung.
  **Der abweichende Port 2222 ist kein Tippfehler.**
- Du arbeitest unter einem **eigenen User `claude`** – ohne `sudo`, aber
  in der `docker`-Gruppe. Wenn ein Befehl an fehlenden Rechten
  scheitert, ist das in aller Regel Absicht: Du bist außerhalb Deines
  Bereichs. Dann **nicht** nach einem Umweg suchen, sondern Andi fragen.
- **Datei-Eigentümer beachten:** Container laufen sonst als root und
  erzeugen in Bind-Mounts root-eigene Dateien, die Du anschließend nicht
  mehr aufräumen kannst – ein Problem spätestens beim Entfernen von
  Testdaten. Deshalb: entweder die UID/GID des Users `claude` per
  `user:`-Direktive an die Container geben (in `.env` ablegen), oder für
  Daten benannte Volumes statt Bind-Mounts verwenden. Entscheide das in
  Meilenstein 1, nicht später – nachträglich umstellen heißt Daten
  umkopieren.
- Erlaubt sind: Schreiben in `/srv/familienportal/`, `docker`- und
  `docker compose`-Kommandos für die Objekte dieses Projekts,
  Log-Abfragen, `docker exec` in die eigenen Container.
- Nicht erlaubt: alles aus Abschnitt 0.

**Deployment als Portainer-Stack:**

- Der Stack heißt `familienportal` und enthält die Container
  `portal`, `caddy` und `util`.
- Ablauf: Paket nach `/srv/familienportal/` schieben, entpacken, dann
  den Stack neu ausrollen (`docker compose up -d --build` im
  Projektverzeichnis oder über die Portainer-API mit einem
  Access-Token). Beide Wege sind zulässig – entscheide Dich für einen
  und dokumentiere ihn in `server.md`.
- **Ausbaustufe (später):** Stack aus einem Git-Repository deployen.
  Dann liefert Git die Versionierung und `deploy/` wird überflüssig.
  Erst umstellen, wenn der Grundbetrieb stabil läuft.

**Testen – vom Rechner aus, nicht vom Host:**

- Wichtig: Wegen `macvlan` kann `home02` seine eigenen Container **nicht**
  direkt erreichen. `curl` per SSH auf dem Host schlägt fehl – das ist
  kein Bug, sondern erwartetes Verhalten. **Teste immer von Andis
  Rechner aus**, nicht vom Host.
- ⚠️ Andis Arbeitsplatz liegt in einem **anderen Subnetz** (10.10.0.0/24)
  als die Container (10.0.0.192/26). Der Weg dorthin führt also über das
  UniFi-Gateway und dessen Firewall-Regeln. Dass SSH zu `10.0.0.100`
  funktioniert, heißt **nicht** automatisch, dass auch die Container-IPs
  erreichbar sind. Prüfe das in Meilenstein 1 als Allererstes, bevor Du
  Zeit in Debugging steckst – ein blockiertes Paket sieht aus wie ein
  kaputter Container.
- Direkt, ohne Proxy: `curl https://portal.16schwaben.de/…` und **echte
  End-to-End-Tests mit Playwright/Chromium** – Seite laden, tippen,
  Screenshots ansehen.
- Screenshots MACHEN UND ANSEHEN. „Seite lädt" heißt nicht „sieht gut aus".
- Auch mobil prüfen: Playwright mit Handy-Viewport, und im Zweifel Andi
  bitten, es auf einem echten iPhone anzuschauen.

## 4. Ziel-Architektur

Bewusst einfach – keine Microservices, kein Kubernetes, kein Framework-Zoo.
Alles läuft im Stack `familienportal` auf `home02`.

**Container `portal`:** Python 3.12 + Flask + Gunicorn (1 Worker,
Threads), **SQLite** als einzige Datenbank unter
`/srv/familienportal/data`. Reicht für eine Familie locker und macht
Backups trivial.

**Container `caddy`:** TLS-Terminierung für **`portal.16schwaben.de`**.
**Caddy macht KEIN ACME.** Das Zertifikat kommt von Andis bestehendem
Certbot und liegt im Volume **`iobroker-certs`**, das Du **read-only**
einbindest:

```yaml
volumes:
  - iobroker-certs:/certs:ro
```

**Aufbau des Volumes:** Es enthält die Zertifikate **mehrerer Domains**,
je Domain ein Ordner direkt auf oberster Ebene (**kein `live/`**). Für
Dich ist ausschließlich der Ordner `portal.16schwaben.de/` bestimmt.
Die Dateien haben Modus `644`, sind also ohne Rechte-Basteleien lesbar –
Caddy muss dafür nicht als root laufen.

> 🚫 **Harte Regel: Du benutzt NUR `portal.16schwaben.de/`.** Die
> Zertifikate und Schlüssel der anderen Domains gehen Dich nichts an.
> Nicht lesen, nicht kopieren, nicht in Dokumentation oder Journal
> erwähnen, und auch dann nicht verwenden, wenn ein Wildcard-Zertifikat
> danebenliegt, das „auch passen würde".

Am saubersten bindest Du deshalb gleich nur diesen Unterordner ein, dann
sieht der Container die anderen Domains gar nicht erst:

```yaml
volumes:
  - type: volume
    source: iobroker-certs
    target: /certs
    read_only: true
    volume:
      subpath: portal.16schwaben.de
```

Falls die Docker-Version auf `home02` `subpath` noch nicht unterstützt:
das ganze Volume read-only einbinden und in der Caddyfile ausschließlich
den einen Ordner referenzieren. Welche Variante Du genommen hast, gehört
in `server.md`.

Caddyfile in der expliziten Form:

```
portal.16schwaben.de {
    tls /certs/fullchain.pem /certs/privkey.pem
    reverse_proxy portal:8000
}
```

(Bei der Fallback-Variante ohne `subpath` entsprechend
`/certs/portal.16schwaben.de/fullchain.pem`.)

Zusätzlich `auto_https off`, damit Caddy nicht versucht, selbst ein
Zertifikat zu holen – es hat keinen Weg nach draußen und würde nur
Fehler loggen.

Einmalig verifizieren, dass das Zertifikat den Namen wirklich trägt:
`openssl x509 -in fullchain.pem -noout -text | grep -A1 "Subject Alternative Name"`.
Passt es nicht, **stopp und Andi fragen** – kein Ausweichen auf ein
anderes Zertifikat aus dem Volume.

> ⚠️ **Der Stolperstein, der Dich sonst in 60–90 Tagen einholt:** Caddy
> liest Zertifikatsdateien beim Laden der Konfiguration ein und
> **überwacht sie nicht**. Wenn Certbot erneuert, serviert Caddy
> weiterhin das alte, irgendwann abgelaufene Zertifikat – und damit
> sterben Web-Push und PWA-Verhalten still.
>
> Lösung ohne Host-Eingriff: Der `util`-Container prüft täglich die
> mtime der Zertifikatsdatei und stößt bei Änderung einen Reload über
> Caddys Admin-API an (`POST http://caddy:2019/load`). Die Admin-API
> dazu **nur auf das interne Bridge-Netz** binden, niemals ins macvlan.
> Ein `docker exec` von außen ist keine Option – das bräuchte Zugriff
> auf den Docker-Socket.
>
> Diesen Mechanismus baust Du in Meilenstein 1 mit, nicht später. Und
> Du testest ihn, indem Du die Zertifikatsdatei einmal künstlich
> anfasst (`touch`) und prüfst, ob der Reload greift.

**Container `util`:** Ein schlanker Container mit eigenem Scheduler
(z. B. `supercronic` oder ein Loop-Skript) – **kein Host-Cron**.
Aufgaben: stündlicher SQLite-Snapshot lokal (24 Stunden-Slots), täglich
eine Vollsicherung (DB + Datenordner als Tarball) plus `rsync`/`scp` auf
einen zweiten Rechner der Familie, sowie der oben beschriebene
Zertifikats-Watcher. Der Container braucht Lesezugriff auf das
Datenverzeichnis und einen eigenen SSH-Schlüssel im Volume –
**nicht** im `Serveradmin`-Ordner.

**Netzwerk – bestehendes macvlan mitbenutzen:**

Das macvlan-Netz ist auf `home02` bereits eingerichtet und wird von
anderen Portainer-Stacks verwendet. Du legst **kein neues an**, sondern
hängst Dich als `external` daran:

```yaml
networks:
  lan:
    external: true
    name: <exakter Name des bestehenden Netzes>
  intern:
    driver: bridge
```

Vorgehen, in dieser Reihenfolge:

1. `docker network ls` und `docker network inspect <netz>` – lesend,
   also unbedenklich. Daraus entnimmst Du den exakten Namen, Subnetz,
   Gateway, `ip-range` und das Parent-Interface. **Nicht raten.**
2. Aus dem Inspect ebenfalls ablesen, **welche IPs aus 10.0.0.192/26
   bereits von fremden Containern belegt sind**. Nutzbar sind
   .193–.254; die .255 ist Broadcast des /24 und bleibt frei.
3. Deine gewählte IP **Andi nennen und bestätigen lassen**, bevor Du
   den Stack zum ersten Mal ausrollst. Eine Kollision legt einen seiner
   bestehenden Dienste lahm – das ist der teuerste Fehler in diesem
   Projekt.
4. Die IP fest vergeben (`ipv4_address`) und in `server.md`
   dokumentieren.

**Nur `caddy` bekommt eine macvlan-IP.** `portal` und `util` hängen
ausschließlich im internen Bridge-Netz und sind von außen gar nicht
sichtbar; Caddy erreicht das Portal über den Servicenamen. Das spart
Adressen im gemeinsamen Bereich, verkleinert die Angriffsfläche und
reduziert das Kollisionsrisiko mit Andis übrigen Stacks auf genau eine
Adresse. Der Portal-Hostname im DNS zeigt auf diese eine Caddy-IP.

**Code-Struktur:** eine schlanke `app.py`, die nummerierte Module
(`teile/00_kern.py`, `teile/01_start_token.py`, …) in EINEM Namensraum
ausführt – jede App ein Modul, gemeinsame Helfer im Kern. Templates als
einzelne HTML-Dateien mit Inline-CSS/JS, JS-Bibliotheken **lokal
gebündelt** ausliefern (nie von fremden CDNs laden).

**Nutzerkonten – JEDES Familienmitglied hat einen eigenen Account:**
Tabelle `users` mit Name, eigener Farbe (zieht sich durch alle Apps),
Admin-Flag (Eltern), optional eigenem KI-Schlüssel (pro Person eigenes
Budget – Kinder ohne Schlüssel können nichts Kostenpflichtiges auslösen;
KI-Funktionen degradieren dann sanft). Dazu je Person: persönliche
Startseite, eigene Push-Abos, eigene Stammdaten, private Inhalte strikt
getrennt.

**Zugriffsmodell ohne Login:** Tabellen `users`, `apps`, `grants`. Jede
Freischaltung (Person ↔ App) hat einen langen zufälligen Token
(`secrets.token_urlsafe(18)`); URLs: `/p/<token>` = persönliche
Startseite, `/a/<app>/<token>/…` = App. Jede API-Route prüft den Token
gegen die App (`grant`-Helfer im Kern). Destruktive Aktionen zusätzlich
nur für Admins bzw. den Besitzer der Daten. Onboarding: Startseiten-Link
je Person als QR-Code.

**Statische Apps/Spiele:** unter `/srv/familienportal/apps/<slug>/` (eine
`index.html` je Spiel), vom Portal mit demselben Token-Modell
ausgeliefert.

**Push-Benachrichtigungen:** Web-Push (VAPID) mit eigener kleiner
Infrastruktur im Portal; Deep-Links in die Apps.

**Host-Dienste: entfallen.** Der Original-Bauplan sah systemd-Dienste
für Dinge wie einen Netzwerk-Monitor vor. Das ist hier nicht zulässig.
Solche Funktionen entweder als eigener Container im Stack lösen oder
weglassen.

## 5. Design-Prinzipien für JEDE App

1. **⌂ Heimknopf:** unten links auf jeder Seite, ein gemeinsames
   Template-Include für alle Apps. Führt zur persönlichen Startseite.
2. **✨ Verbesserungswunsch:** an jedem App-Titel hängt (per JS aus dem
   gemeinsamen Include) ein dezentes ✨. Öffnet ein Formular mit Textfeld
   und 🎤-Einsprechen; der Wunsch landet mit App-Name, Urheber und Datum
   im Werkstatt-Backlog.
3. **Deutsch, kindertauglich, mobil zuerst:** große Tippziele, Emojis,
   einfache Sprache, keine Fachbegriffe. Muss auf dem Handy in Safari
   und Chrome gut aussehen (Safe-Area-Insets!). Web-App-fähig
   (`apple-mobile-web-app-capable`, Manifest, Icon-Fallback).
4. **Jede App funktioniert allein:** kein globales Framework, keine
   geteilten Build-Schritte. Fehler in einer App dürfen keine andere
   stören.
5. **KI sparsam und privat:** siehe Sicherheitsregeln. Ohne hinterlegten
   KI-Schlüssel funktioniert die App trotzdem, nur ohne die Extras.

## 6. Die zentralen Dienste (Meilenstein 1)

**🏠 Startseite/Token-System:** persönliche Seite je Familienmitglied
(eigene Farbe, App-Kacheln nach Freischaltung), Token-Routing,
`denied`-Seite, Icon/Manifest-Fallbacks, gemeinsames Heimknopf/✨-Include.

**⚙️ Admin-Bereich** (nur Admins): Familienmitglieder anlegen (Name,
Farbe, Admin ja/nein), Apps je Person freischalten/entziehen (Token
erzeugen/zurückziehen), Push-Abos einsehen, Stammdaten pflegen. Der
Admin-Bereich ist selbst eine App mit Token.

**✅ Todo-App:** Tabelle `todos` (Inhalt, zugewiesen an, angelegt von,
privat-Flag, erledigt-Zeitstempel). Zuweisen, abhaken, Push bei
Zuweisung, Deep-Link. Andere Apps dürfen programmatisch Todos anlegen –
das ist ein zentraler Baustein.

**💡 App-Wünsche + ✨ Werkstatt (zwei Backlogs):** Tabelle(n) mit Nummer,
Text, Urheber, App-Bezug, Datum, Status. Eintragen über die
✨-Formulare bzw. eine kleine Wunsch-App. Dazu ein CLI-Helfer im
Container (`backlog.py`): auflisten, als erledigt markieren. Der Mensch
sagt „Implementiere alle App-Wünsche" – dann liest Du beide Backlogs,
setzt ALLES vollständig um, hakst ab und dokumentierst.

**🙋 Geholfen-App:** Kinder tippen auf große Kacheln, wenn sie geholfen
haben (Tisch gedeckt, ausgeräumt, Rasen gemäht …); Einträge mit
Zeitstempel und Gewichtung je Person. Eltern-Ansicht mit Übersicht.
Schreibrechte konfigurierbar. Bewusst simpel und motivierend – auch für
ein Küchen-Tablet als Daueranzeige geeignet.

## 7. Aufbau-Reihenfolge

1. **Fundament:** SSH auf `10.0.0.100:2222` prüfen, Projektverzeichnis
   anlegen,
   bestehendes macvlan-Netz inspizieren und freie IP bestätigen lassen,
   Zertifikats-Volume einbinden, Portal-Grundgerüst (Kern +
   Token-System + Startseite) bauen, Stack mit `portal` + `caddy` +
   `util` ausrollen, Zertifikats-Reload testen, ersten Stand als
   `portal-v1.tar.gz` sichern. `server.md` + `journal.md` anlegen.
2. **Zentrale Dienste** (Abschnitt 6) in dieser Reihenfolge: Admin →
   Todos → Wünsche/Werkstatt (+ ✨-Include überall) → Geholfen.
3. **Backup-Container** einrichten und im Journal dokumentieren.
4. **Familie onboarden:** WireGuard-Profil je Gerät (macht Andi), dann
   Startseiten-Link als QR-Code; kurze Erklärung auf der Startseite.
5. **Ab jetzt wunschgetrieben:** Die Familie wünscht, Du baust. Jede
   Auslieferung: Version hochzählen, E2E-Test über WireGuard, Testdaten
   entfernen, Journal + `server.md` aktualisieren, Paket nach `deploy/`.

## 8. Feinheiten und erprobtes Wissen (erspart Dir Tage)

**macvlan-Fallstricke:**
- Der Host erreicht seine eigenen macvlan-Container nicht. `curl` von
  `home02` aus schlägt fehl – das ist kein Bug. Ein
  `macvlan-shim`-Interface würde es lösen, ist aber eine
  Host-Änderung – also **nicht** anlegen. Teste über WireGuard.
- **Das Netz ist geteilte Infrastruktur.** Vor jeder IP-Vergabe
  `docker network inspect` lesen und die Wahl bestätigen lassen. Eine
  Kollision trifft fremde Dienste, nicht Deine.
- `external: true` heißt auch: Beim Entfernen des Stacks darf das Netz
  **nicht** mit abgeräumt werden. Kein `docker compose down --volumes
  --remove-orphans` in der Annahme, das sei folgenlos.
- Container im macvlan sind für alle LAN-Geräte erreichbar. Deshalb
  hängt dort nur `caddy`, und deshalb gilt Punkt 5 der
  Sicherheitsregeln umso strenger.

**Zertifikat:**
- Volume `iobroker-certs` immer **read-only** einbinden. Es gehört
  iobroker, nicht Dir. Nichts hineinschreiben, keine Rechte ändern,
  keine Dateien umbenennen – auch nicht „nur kurz zum Testen".
- **Nur der Ordner `portal.16schwaben.de/`.** Im Volume liegen die
  Zertifikate anderer Domains; die sind für Dich nicht existent.
- Der Volume-Name ist historisch gewachsen und hat nichts mit dem
  Portal zu tun. Nicht wundern, nicht umbenennen wollen.
- Dateimodus ist `644` – lesbar ohne root. Wenn Caddy trotzdem
  „permission denied" meldet, liegt es am Pfad oder am `subpath`,
  nicht an den Rechten. Nicht anfangen, im Volume herumzuschrauben.
- Nach jedem Deploy prüfen, ob das ausgelieferte Zertifikat noch gültig
  ist (`openssl s_client` von Andis Rechner, oder Playwright meckert).
  Ein abgelaufenes Zertifikat killt Web-Push lautlos.

**SQLite richtig benutzen:**
- WAL-Modus, EIN Gunicorn-Worker mit Threads – dann ist SQLite völlig
  ausreichend und robust.
- **Hintergrund-Threads brauchen eine EIGENE Verbindung** (mit Timeout).
  Die Request-Verbindung (`g`-Objekt) gehört nur dem Request. Wer das
  ignoriert, bekommt „Cannot operate on a closed database".

**Hintergrund-Arbeit im Portal:** Daemon-Threads für Wächter (z. B.
„fällige Gieß-Termine → Todo anlegen") mit Prüfung zusätzlich beim
App-Öffnen; lange Jobs (Transkription, Bildverarbeitung) in einem Thread
mit globaler Sperre und Fortschritts-Anzeige per Poll-Endpoint. Schwere
KI-Modelle beim ERSTEN Gebrauch in den DATENORDNER laden (nicht ins
Image) – so überleben sie Rebuilds.

**Push-Benachrichtigungen:** ein zentraler `push_send`-Helfer (eigene
DB-Verbindung!) mit Titel, Text, Ziel-App und Anker (Deep-Link) sowie
Dedup-Schlüssel gegen Doppel-Pushes. Web-Push mit VAPID, Abos je
Person+Gerät im Admin sichtbar. **Push funktioniert nur mit gültigem
HTTPS-Zertifikat** – deshalb ist Abschnitt 4 kein Kosmetikthema.

**iPhone/Safari-Fallen:**
- `viewport-fit=cover` + `env(safe-area-inset-*)` überall, sonst kleben
  Knöpfe unter der Home-Leiste.
- `element.style.display = ''` fällt aufs Stylesheet zurück – wer
  `display:none` INLINE gesetzt hat, muss explizite Werte setzen.
- Web-Audio: eigenes `AudioContext` je Aufnahme, `await ctx.resume()`
  nach Nutzer-Geste; Mikrofon-Streams mit `track.stop()` freigeben;
  `navigator.audioSession.type` beachten.
- Kein echtes `requestFullscreen` auf dem iPhone – Vollbild = „Zum
  Home-Bildschirm" (Standalone-Modus), dafür Manifest + Icons ausliefern.
- MediaRecorder liefert je nach Gerät mp4 ODER webm – beides annehmen,
  clientseitig zu 16-kHz-Mono-WAV wandeln, als Base64 hochladen.

**Frontend-Handwerk:**
- JS-Bibliotheken IMMER lokal bündeln. `.mjs` braucht MIME-Typ
  `text/javascript`, WASM `application/wasm` – sonst verweigert der
  Browser den Modul-Import.
- `let`-Variablen im Top-Level hängen NICHT an `window`.
- Für Audio/Video `send_file(..., conditional=True)` – Range-Requests
  sind Pflicht fürs Spulen auf dem iPhone.
- `MAX_CONTENT_LENGTH` bewusst setzen, bei Medien-Apps erhöhen.
- Schwere Berechnungen (Wellenform-Peaks, Thumbnails) SERVERSEITIG
  vorrechnen.

**Testen wie ein Profi:**
- Playwright/Chromium direkt von Andis Rechner; Kamera/Mikrofon mit
  `--use-fake-device-for-media-stream --use-fake-ui-for-media-stream`.
- Beim Testen an ECHTEN Daten vorbei: gefährliche Endpoints mit
  `page.route(...)` abfangen, Testdaten mit eindeutigen Markern anlegen
  und exakt diese wieder löschen.

**Zusammenspiel der Apps:** Apps dürfen füreinander Todos anlegen,
Pushes schicken und Dateien in die gemeinsame Ablage legen – das macht
aus Einzel-Apps ein Familien-System. Beispiel: Scanner legt PDF in die
Ablage → Ablage macht daraus ein Todo → Formular-Ausfüller öffnet es
direkt aus dem Todo.

**Wachstum im Griff behalten:** Wenn ein neues Feature ein fertiges,
etabliertes Werkzeug hat, nimm das Werkzeug und bündle es lokal, statt
es nachzubauen – und schreib die Entscheidung samt Alternativen ins
Journal.

## 9. Qualitäts-Checkliste je Auslieferung

- [ ] Läuft der Stack nach dem Ausrollen (alle Container `healthy`)?
- [ ] E2E-Test VON ANDIS RECHNER bestanden (Playwright: Seite lädt,
      Kern-Interaktion funktioniert, Screenshot angesehen)?
- [ ] Auf einem Handy-Viewport geprüft (Safe-Area, Tippziele)?
- [ ] Test-Daten restlos entfernt?
- [ ] ⌂ und ✨ vorhanden?
- [ ] **Nichts außerhalb von `/srv/familienportal/` angefasst?**
- [ ] **Keine Schlüssel im `Serveradmin`-Ordner gelandet?**
- [ ] **Das gemeinsame macvlan-Netz unverändert gelassen, keine fremde
      IP belegt?**
- [ ] **Nur `portal.16schwaben.de/` aus dem Zertifikats-Volume benutzt?**
- [ ] Zertifikat gültig, Reload-Watcher läuft?
- [ ] `journal.md` + `server.md` aktualisiert, Paket versioniert in
      `deploy/` abgelegt?

---

*Dieses Dokument beschreibt bewusst KEINE konkreten Personen, Namen,
Adressen oder Zugangsdaten. Alles Familienspezifische entsteht beim
Aufbau im Gespräch zwischen Mensch und Claude.*
