"""
Tägliches Backup: /data → NAS per SSH (tar über SSH, kein rsync-Daemon nötig).

Drei Dinge, die hier anders sind als man zunächst erwartet – alle aus dem
Sicherheitsaudit vom 11.08.2026, alle mit echtem Schaden davor:

**1. Die Live-Datenbank wird NICHT eingepackt.**
`tar` las bis dahin `/data/portal.db`, während Gunicorn hineinschrieb. Ändert
sich eine Datei während des Lesens, bricht GNU tar mit Exit 1 ab – im August
2026 an drei von sechs Nächten (07., 08., 10.08.), nachweisbar in den
util-Logs. Schlimmer als der sichtbare Fehlschlag war der unsichtbare Teil:
Auch an den „OK"-Nächten war die mitgesicherte `portal.db` nicht garantiert
konsistent, denn Exit 0 heißt nur „während des Lesens hat sich nichts
geändert", nicht „die Datei ist in sich stimmig".

Deshalb: vorher einen frischen Snapshot über `sqlite3.Connection.backup()`
ziehen (`db_snapshot.take()`, WAL-korrekt und in sich konsistent) und die
Live-DB samt `-wal`/`-shm` aus dem Archiv ausschließen. Im Tarball liegen
damit ausschließlich konsistente Stände.

>>> WIEDERHERSTELLUNG: Die Datenbank liegt im Tarball unter
>>> `./snapshots/portal-<zeitstempel>.db` – den NEUESTEN davon nach
>>> `/data/portal.db` kopieren. Eine `./portal.db` gibt es im Archiv
>>> bewusst nicht mehr.

**2. Schreiben und Aufräumen laufen in EINEM Remote-Befehl.**
Früher waren es zwei SSH-Aufrufe: einer zum Übertragen, ein zweiter mit
`ls -t … | xargs rm -f` für die 7er-Rotation. Der zweite ist entfallen, denn
sobald der NAS-Schlüssel per `command="…",restrict` festgelegt ist, wird jeder
mitgeschickte Befehl ignoriert und stattdessen der erzwungene ausgeführt – die
zweite Verbindung hätte also nichts gelöscht, sondern bei jedem Lauf ein
weiteres, leeres Archiv angelegt und damit die Rotation aufgefressen. Und weil
`cat` sich mit 0 beendet, wäre das ohne eine einzige Warnung im Log passiert.

Der Befehl wird aber **weiterhin mitgeschickt** (`_REMOTE_CMD`), obwohl er bei
aktiver Härtung wirkungslos ist. Die Begründung steht dort – kurz: Diese Datei
darf sich nicht darauf verlassen, dass eine Einstellung auf einem fremden
Gerät vorhanden und korrekt ist. Ist sie es, gewinnt der erzwungene Befehl;
ist sie es nicht, trägt dieser hier das Backup allein.

**3. Der Datenstrom wird verschlüsselt, bevor er das Haus verlässt.**
Bis v211 lag auf dem NAS die komplette Familiendatenbank im Klartext – alle
Kassenbuchbeträge, privaten Aufgaben, Geburtstage, Wünsche und Vokabeln. Wer
Zugriff aufs NAS-Volume hatte oder auf ein Backup des NAS, hatte alles.
(Entlastend, aber nur dafür: seit Stufe 6 stehen in der DB nur noch HMACs der
Zugangstokens – ein erbeutetes Backup gibt also KEINEN Portalzugang.)

Verschlüsselt wird **asymmetrisch mit `age`** gegen einen öffentlichen
Schlüssel aus `BACKUP_AGE_RECIPIENT`. Andis Entscheidung vom 13.08.2026
(Wunsch #130/#211); die Alternative wäre ein symmetrischer Schlüssel aus der
`.env` gewesen. Der Unterschied ist nicht akademisch: symmetrisch schützt nur
die Kopie auf dem NAS, denn wer `home02` hat, hat auch den Schlüssel.
Asymmetrisch schützt auch dagegen – **der private Schlüssel liegt weder auf
home02 noch auf dem NAS**, sondern nur bei Andi.

Der Preis dafür steht hier, damit ihn niemand später übersieht: **Ist der
private Schlüssel weg, sind alle Backups Datenmüll.** Es gibt keine
Hintertür, das ist der Sinn der Sache.

>>> WIEDERHERSTELLUNG einer `portal-*.tar.gz.age`:
>>>     age -d -i <privater-schluessel> -o portal.tar.gz portal-….tar.gz.age
>>>     tar xzf portal.tar.gz
>>> Danach wie unten: den neuesten `./snapshots/portal-*.db` nach
>>> `/data/portal.db`. Ausführlich in server.md, „Wiederherstellung".

Fehlt `BACKUP_AGE_RECIPIENT`, läuft das Backup **unverschlüsselt** weiter und
sagt das bei jedem Lauf als Warnung ins Log. Steht dort ein unbrauchbarer
Wert, fällt das Backup aus – absichtlich, denn ein stiller Rückfall auf
Klartext wäre genau die Sorte Fehler, die hier zweimal Schaden gemacht hat.

Konfiguration via .env:
  BACKUP_NAS_HOST        IP des NAS         (default: 10.60.0.4)
  BACKUP_NAS_USER        SSH-User auf NAS   (default: familienportal)
  BACKUP_NAS_PATH        Zielpfad auf NAS   (default: /volume2/portal.16schwaben.de_Backup)
  BACKUP_NAS_PORT        SSH-Port           (default: 2222)
  BACKUP_AGE_RECIPIENT   öffentlicher age-Schlüssel (age1…), leer = unverschlüsselt
"""
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path

import db_snapshot

log = logging.getLogger("util.backup")

NAS_HOST = os.environ.get("BACKUP_NAS_HOST", "10.60.0.4")
NAS_USER = os.environ.get("BACKUP_NAS_USER", "familienportal")
NAS_PATH = os.environ.get("BACKUP_NAS_PATH", "/volume2/portal.16schwaben.de_Backup")
NAS_PORT = os.environ.get("BACKUP_NAS_PORT", "2222")
SSH_KEY  = "/ssh/id_ed25519"
DATA_DIR = os.environ.get("DATA_DIR", "/data")

KNOWN_HOSTS = "/ssh/known_hosts"

# Wunsch #130/#211: oeffentlicher age-Schluessel. Nur der oeffentliche Teil
# steht hier - der private liegt bei Andi und kommt weder in dieses Repo noch
# auf home02 oder das NAS.
AGE_RECIPIENT = os.environ.get("BACKUP_AGE_RECIPIENT", "").strip()

# age1 + bech32 (ohne 1, b, i, o). Die Laenge steht bewusst als Bereich da und
# nicht exakt: geprueft wird "sieht aus wie ein age-Schluessel", damit ein
# Tippfehler VOR dem Anfassen des NAS auffaellt. Die echte Pruefung macht age
# selbst - diese hier soll nur verhindern, dass ein halber Schluessel erst
# nachts um drei als Fehlschlag sichtbar wird.
_RECIPIENT_MUSTER = re.compile(r"^age1[02-9ac-hj-np-z]{50,70}$")

# Erst unter diesem Namen hochladen, dann umbenennen. Der Name faengt bewusst
# NICHT mit "portal-" an: die Rotation unten zaehlt "portal-*", und ein
# liegengebliebener Teil-Upload wuerde dort sonst als vollwertiges Backup
# mitzaehlen und ein echtes aus den sieben herausdraengen.
_UPLOAD_TEIL = ".upload.part"

# Wunsch #211 (Audit-Befund F-03): Vorher stand hier StrictHostKeyChecking=no
# und es gab gar keine known_hosts - der Container nahm JEDEN Host an, der
# unter der NAS-Adresse antwortete. Wer im Netzsegment des NAS dessen IP
# uebernimmt (ARP-Spoofing, abgepasste DHCP-Neuvergabe), bekam nachts die
# vollstaendige Familiendatenbank zugestellt.
#
# Die Schluessel sind am 12.08.2026 per ssh-keyscan aufgenommen und liegen in
# /srv/familienportal/ssh/known_hosts (read-only in den Container gemountet).
# Beide Verfahren sind drin (ed25519 und rsa), damit eine Aenderung der
# Server-Vorliebe das Backup nicht ueber Nacht abreissen laesst.
#
# ACHTUNG bei einem NAS-Umzug oder einem Neuaufsetzen des SSH-Dienstes: Dann
# schlaegt das Backup fehl, und zwar mit Absicht. Die Meldung lautet
# "Host key verification failed" - in dem Fall den neuen Schluessel PRUEFEN
# (Fingerabdruck am NAS selbst ablesen) und erst dann neu aufnehmen. Ein
# blindes Ueberschreiben waere genau die Luecke, die hier geschlossen wurde.
SSH_OPTS = [
    "ssh", "-i", SSH_KEY, "-p", NAS_PORT,
    "-o", "StrictHostKeyChecking=yes",
    "-o", f"UserKnownHostsFile={KNOWN_HOSTS}",
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=20",
    f"{NAS_USER}@{NAS_HOST}",
]

# EIN Remote-Befehl, der schreibt UND rotiert - und der bewusst mitgeschickt
# wird, obwohl der NAS-Schluessel per `command="…"` festgelegt sein soll.
#
# Warum trotzdem: Ist der erzwungene Befehl aktiv, wird dieser hier schlicht
# ignoriert und die Gegenseite macht dasselbe. Ist er NICHT aktiv - weil die
# Zeile in authorized_keys fehlt, doppelt ist oder ein Update sie
# ueberschrieben hat -, dann traegt dieser Befehl das Backup allein.
#
# Ohne ihn passiert genau das, was am 11.08.2026 im Test geschah: ssh oeffnet
# mangels Kommando eine normale Login-Shell, und der tar-Datenstrom wird von
# der Gegenseite als Shell-Eingabe gelesen ("syntax error near unexpected
# token", tar stirbt an SIGPIPE). Das Backup faellt dann komplett aus - und
# zwar abhaengig von einer Einstellung auf einem fremden Geraet, das dieses
# Repo weder sehen noch pruefen kann. Diese Abhaengigkeit darf es nicht geben.
#
# Die Rotation haengt mit dranm statt in einer zweiten SSH-Verbindung: Bei
# aktivem `command=` wuerde eine zweite Verbindung nur ein weiteres, leeres
# Archiv anlegen (der erzwungene Befehl laeuft ja erneut) - und genau das
# wuerde die 7er-Rotation auffressen.
# Seit v212 zusaetzlich zweistufig: erst nach _UPLOAD_TEIL schreiben, auf
# "nicht leer" pruefen, dann umbenennen. Bricht die Uebertragung ab, liegt
# danach ein .part herum statt eines abgeschnittenen Archivs, das aussieht wie
# ein gutes - und die Rotation laeuft gar nicht erst an. Frueher konnte ein
# halber Datenstrom ein vollstaendiges Backup aus den sieben verdraengen.
#
# Die Rotation zaehlt "portal-*.tar.gz*" mit Stern am Ende, damit sie
# verschluesselte (.tar.gz.age) und alte unverschluesselte Archive GEMEINSAM
# rotiert. Ohne den Stern waeren es nach der Umstellung zwei getrennte
# Bestaende zu je sieben.
def _remote_cmd(endung: str) -> str:
    return (
        "umask 077; "
        f"cd {NAS_PATH} && "
        f"cat > {_UPLOAD_TEIL} && [ -s {_UPLOAD_TEIL} ] && "
        f"mv {_UPLOAD_TEIL} portal-$(date +%Y%m%d-%H%M%S){endung} && "
        "ls -t portal-*.tar.gz* | tail -n +8 | xargs -r rm -f"
    )


def run():
    if not os.path.exists(SSH_KEY):
        log.warning("SSH-Key %s fehlt – Backup übersprungen", SSH_KEY)
        return
    if not os.path.exists(KNOWN_HOSTS):
        # Absichtlich ein Abbruch und kein Rueckfall auf
        # StrictHostKeyChecking=no: Ein Backup, das im Zweifel jedem Host
        # antwortet, ist schlimmer als ein ausgefallenes, das im Log steht.
        log.error("known_hosts %s fehlt – Backup übersprungen. Schlüssel des "
                  "NAS prüfen und aufnehmen, siehe Kommentar in backup.py",
                  KNOWN_HOSTS)
        return
    if AGE_RECIPIENT and not _RECIPIENT_MUSTER.match(AGE_RECIPIENT):
        # Kein Rueckfall auf unverschluesselt. Wer einen Schluessel eintraegt,
        # will Verschluesselung - dann ist ein ausgefallenes Backup im Log das
        # ehrlichere Ergebnis als ein Klartext-Archiv auf dem NAS, das niemand
        # bemerkt.
        log.error("BACKUP_AGE_RECIPIENT ist kein age-Schlüssel (erwartet "
                  "age1…) – Backup übersprungen, es wird NICHT unverschlüsselt "
                  "gesichert. Wert prüfen: %r", AGE_RECIPIENT[:12] + "…")
        return

    log.info("Backup → %s:%s (Dateiname vergibt das NAS)", NAS_HOST, NAS_PATH)
    try:
        snapshot = _frischer_snapshot()
        log.info("Konsistenter Stand im Archiv: snapshots/%s", snapshot.name)
        _transfer()
        log.info("Backup OK")
    except Exception as e:
        log.error("Backup fehlgeschlagen: %s", e)


def _frischer_snapshot() -> Path:
    """Frischen, konsistenten DB-Stand erzeugen und zurückgeben.

    Bewusst mit harter Ausnahme statt stiller Fortsetzung: Da die Live-DB nicht
    mehr mitgesichert wird, wäre ein Backup ohne Snapshot ein Tarball GANZ OHNE
    Datenbank – und das darf niemals unbemerkt durchgehen. `db_snapshot.take()`
    protokolliert eigene Fehler und wirft selbst nicht, deshalb wird das
    Ergebnis hier nachgeprüft statt ihm zu vertrauen."""
    db_snapshot.take()
    snaps = sorted(db_snapshot.SNAP_DIR.glob("portal-*.db"))
    if not snaps:
        raise RuntimeError(
            "kein Snapshot vorhanden – das Backup enthielte keine Datenbank")
    return snaps[-1]


def _transfer():
    """Packen → (verschlüsseln) → senden, jede Stufe einzeln geprüft.

    Bis v211 war das EINE Pipe (`tar | ssh`). Das ist elegant, aber es gibt
    keinen Punkt, an dem man das Ergebnis noch ansehen kann, bevor es beim
    Empfänger liegt – und mit Verschlüsselung wäre genau dort die gefährlichste
    Frage unbeantwortet geblieben: *ist der Strom, der rausgeht, wirklich
    verschlüsselt?* Deshalb jetzt über eine Zwischendatei. Das ist bezahlbar,
    weil `/data` rund 18 MB gross ist; bei Gigabytes wäre die Abwägung eine
    andere."""
    with tempfile.TemporaryDirectory(prefix="backup-") as tmp:
        archiv = _packen(Path(tmp) / "portal.tar.gz")

        if AGE_RECIPIENT:
            archiv = _verschluesseln(archiv)
            endung = ".tar.gz.age"
        else:
            log.warning("BACKUP_AGE_RECIPIENT ist nicht gesetzt – das Backup "
                        "geht UNVERSCHLÜSSELT aufs NAS (Wunsch #130/#211).")
            endung = ".tar.gz"

        _senden(archiv, endung)


def _packen(ziel: Path) -> Path:
    ergebnis = subprocess.run(
        # Die Live-DB (und ihre WAL-/SHM-Begleiter) bleiben draussen, siehe
        # Modul-Docstring. Das Muster trifft nur die oberste Ebene - die
        # Snapshots heissen ./snapshots/portal-*.db und bleiben drin.
        ["tar", "czf", str(ziel), "--exclude=./portal.db*", "-C", DATA_DIR, "."],
        capture_output=True, check=False,
    )

    # GNU tar unterscheidet: 1 = Warnungen ("some files differ", typisch wenn
    # sich eine Datei waehrend des Lesens aendert), 2 = fataler Fehler.
    # Vorher galt beides als Fehlschlag, und genau das hat im August 2026 drei
    # von sechs Naechten als Totalausfall gemeldet, obwohl das Archiv
    # vollstaendig war. Seit die Live-DB draussen bleibt, kann eine 1 nur noch
    # von einer nebenher geschriebenen Mediendatei kommen (vokabel_audio) - das
    # Archiv ist dann bis auf diese eine Datei brauchbar, und die Datenbank
    # darin ohnehin ein sauberer Snapshot. Deshalb: sichtbar protokollieren,
    # aber nicht mehr das ganze Backup verwerfen.
    if ergebnis.returncode == 1:
        log.warning("tar meldete Warnungen (Exit 1) - eine Datei hat sich "
                    "waehrend des Lesens geaendert. Datenbank-Snapshot ist "
                    "davon nicht betroffen, Archiv wurde uebertragen.")
    elif ergebnis.returncode != 0:
        text = ergebnis.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"tar exit {ergebnis.returncode}: {text[:200]}")

    if not ziel.exists() or ziel.stat().st_size == 0:
        raise RuntimeError("Archiv ist leer – nichts zu sichern")
    return ziel


def _verschluesseln(quelle: Path) -> Path:
    """Gegen den öffentlichen Schlüssel verschlüsseln – und nachsehen, ob es
    geklappt hat.

    Die Nachprüfung ist der Kern: `age` würde bei einem Fehler zwar mit != 0
    enden, aber die einzige Frage, auf die es hier wirklich ankommt, ist nicht
    „lief das Programm durch", sondern „steht in der Datei, die gleich das Haus
    verlässt, wirklich kein Klartext mehr". Also wird der age-Kopf gelesen.
    Ohne ihn: Abbruch, nichts geht raus."""
    ziel = quelle.with_name(quelle.name + ".age")
    ergebnis = subprocess.run(
        ["age", "-r", AGE_RECIPIENT, "-o", str(ziel), str(quelle)],
        capture_output=True, check=False,
    )
    if ergebnis.returncode != 0:
        text = ergebnis.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"age exit {ergebnis.returncode}: {text[:200]}")

    kopf = ziel.read_bytes()[:21] if ziel.exists() else b""
    if kopf != b"age-encryption.org/v1":
        raise RuntimeError(
            "age hat keine verschlüsselte Datei erzeugt (Kopf fehlt) – "
            "es wird nichts übertragen")

    # Den Klartext sofort loswerden, nicht erst mit dem Temp-Verzeichnis am
    # Ende: solange er daneben liegt, kann ihn ein spaeterer Fehler in
    # _senden() versehentlich zum Hochladen anbieten.
    quelle.unlink()
    log.info("Archiv verschlüsselt (age, %.1f MB)", ziel.stat().st_size / 1e6)
    return ziel


def _senden(datei: Path, endung: str):
    with datei.open("rb") as strom:
        ssh = subprocess.Popen(
            SSH_OPTS + [_remote_cmd(endung)],
            stdin=strom,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _, stderr = ssh.communicate(timeout=600)

    if ssh.returncode != 0:
        # errors="replace": Antwortet die Gegenseite mit etwas Binaerem (im
        # Test am 11.08.2026 spiegelte eine Login-Shell den gzip-Strom zurueck),
        # wirft ein blankes .decode() einen UnicodeDecodeError - und der
        # ERSETZT dann die eigentliche Fehlermeldung. Die Diagnose war damit
        # genau in dem Moment weg, in dem man sie am dringendsten braucht.
        text = stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"SSH exit {ssh.returncode}: {text[:200]}")
