"""
Tägliches Backup: /data → NAS per SSH (tar + pipe, kein rsync-Daemon nötig).

Zwei Dinge, die hier anders sind als man zunächst erwartet – beide aus dem
Sicherheitsaudit vom 11.08.2026, beide mit echtem Schaden davor:

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

Konfiguration via .env:
  BACKUP_NAS_HOST   IP des NAS         (default: 10.60.0.4)
  BACKUP_NAS_USER   SSH-User auf NAS   (default: familienportal)
  BACKUP_NAS_PATH   Zielpfad auf NAS   (default: /volume2/portal.16schwaben.de_Backup)
  BACKUP_NAS_PORT   SSH-Port           (default: 2222)
"""
import logging, os, subprocess
from pathlib import Path

import db_snapshot

log = logging.getLogger("util.backup")

NAS_HOST = os.environ.get("BACKUP_NAS_HOST", "10.60.0.4")
NAS_USER = os.environ.get("BACKUP_NAS_USER", "familienportal")
NAS_PATH = os.environ.get("BACKUP_NAS_PATH", "/volume2/portal.16schwaben.de_Backup")
NAS_PORT = os.environ.get("BACKUP_NAS_PORT", "2222")
SSH_KEY  = "/ssh/id_ed25519"
DATA_DIR = os.environ.get("DATA_DIR", "/data")

SSH_OPTS = [
    "ssh", "-i", SSH_KEY, "-p", NAS_PORT,
    "-o", "StrictHostKeyChecking=no",
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
_REMOTE_CMD = (
    "umask 077; "
    f"f={NAS_PATH}/portal-$(date +%Y%m%d-%H%M%S).tar.gz; "
    f'cat > "$f" && ls -t {NAS_PATH}/portal-*.tar.gz | tail -n +8 | xargs -r rm -f'
)


def run():
    if not os.path.exists(SSH_KEY):
        log.warning("SSH-Key %s fehlt – Backup übersprungen", SSH_KEY)
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
    tar = subprocess.Popen(
        # Die Live-DB (und ihre WAL-/SHM-Begleiter) bleiben draussen, siehe
        # Modul-Docstring. Das Muster trifft nur die oberste Ebene - die
        # Snapshots heissen ./snapshots/portal-*.db und bleiben drin.
        ["tar", "czf", "-", "--exclude=./portal.db*", "-C", DATA_DIR, "."],
        stdout=subprocess.PIPE,
    )
    ssh = subprocess.Popen(
        SSH_OPTS + [_REMOTE_CMD],
        stdin=tar.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    tar.stdout.close()
    _, stderr = ssh.communicate(timeout=600)
    tar.wait()

    if ssh.returncode != 0:
        # errors="replace": Antwortet die Gegenseite mit etwas Binaerem (im
        # Test am 11.08.2026 spiegelte eine Login-Shell den gzip-Strom zurueck),
        # wirft ein blankes .decode() einen UnicodeDecodeError - und der
        # ERSETZT dann die eigentliche Fehlermeldung. Die Diagnose war damit
        # genau in dem Moment weg, in dem man sie am dringendsten braucht.
        text = stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"SSH exit {ssh.returncode}: {text[:200]}")

    # GNU tar unterscheidet: 1 = Warnungen ("some files differ", typisch wenn
    # sich eine Datei waehrend des Lesens aendert), 2 = fataler Fehler.
    # Vorher galt beides als Fehlschlag, und genau das hat im August 2026 drei
    # von sechs Naechten als Totalausfall gemeldet, obwohl der Datenstrom
    # vollstaendig uebertragen war. Seit die Live-DB draussen bleibt, kann eine
    # 1 nur noch von einer nebenher geschriebenen Mediendatei kommen
    # (vokabel_audio) - das Archiv ist dann bis auf diese eine Datei brauchbar,
    # und die Datenbank darin ohnehin ein sauberer Snapshot. Deshalb: sichtbar
    # protokollieren, aber nicht mehr das ganze Backup verwerfen.
    if tar.returncode == 1:
        log.warning("tar meldete Warnungen (Exit 1) - eine Datei hat sich "
                    "waehrend des Lesens geaendert. Datenbank-Snapshot ist "
                    "davon nicht betroffen, Archiv wurde uebertragen.")
    elif tar.returncode != 0:
        raise RuntimeError(f"tar exit {tar.returncode}")
