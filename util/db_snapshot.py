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
