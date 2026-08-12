"""
Stündlicher SQLite-Snapshot (hält die letzten 24 Slots).
Nutzt sqlite3.Connection.backup() – korrekt auch im WAL-Modus.
"""
import logging, sqlite3
from datetime import datetime
from pathlib import Path

DB       = Path("/data/portal.db")
SNAP_DIR = Path("/data/snapshots")
KEEP     = 24

log = logging.getLogger("util.db_snapshot")


def take():
    if not DB.exists():
        log.debug("Keine DB vorhanden, überspringe Snapshot")
        return
    try:
        SNAP_DIR.mkdir(exist_ok=True)
        dst = SNAP_DIR / f"portal-{datetime.now():%Y%m%d-%H%M}.db"

        src = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        tgt = sqlite3.connect(dst)
        src.backup(tgt)
        tgt.close()
        src.close()

        log.info("Snapshot: %s", dst.name)
        _prune()
    except Exception:
        log.exception("Snapshot fehlgeschlagen")


def _prune():
    snaps = sorted(SNAP_DIR.glob("portal-*.db"))
    for old in snaps[:-KEEP]:
        old.unlink(missing_ok=True)
        log.debug("Alten Snapshot gelöscht: %s", old.name)
    _verwaiste_begleiter_loeschen()


def _verwaiste_begleiter_loeschen():
    """Wunsch #215: `-wal`/`-shm` ohne zugehörige `.db` wegräumen.

    `sqlite3.Connection.backup()` legt das Ziel im WAL-Modus an; normalerweise
    räumt `tgt.close()` die beiden Begleitdateien wieder weg. Bricht ein Lauf
    ab - Container-Neustart mitten im Snapshot -, bleiben sie liegen.

    Und dann bleiben sie FÜR IMMER liegen: das Muster oben endet auf `.db` und
    trifft weder `.db-wal` noch `.db-shm`. Am 11.08.2026 lagen so 56 Dateien
    vom 07. und 08.08. im Ordner, deren `.db` längst weg war - jede Nacht
    sinnlos mitgesichert, und Datenbankinhalt ist es allemal.

    Der Reihenfolge wegen steht der Aufruf am ENDE von `_prune()`: Erst fallen
    die alten `.db`, dann sind deren Begleiter verwaist und gehen im selben
    Lauf mit.
    """
    for endung in ("-wal", "-shm"):
        for begleiter in SNAP_DIR.glob(f"portal-*.db{endung}"):
            haupt = begleiter.with_name(begleiter.name[: -len(endung)])
            if haupt.exists():
                continue                       # gehört zu einem gültigen Snapshot
            begleiter.unlink(missing_ok=True)
            log.debug("Verwaiste Begleitdatei gelöscht: %s", begleiter.name)
