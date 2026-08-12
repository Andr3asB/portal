"""Wunsch #215: verwaiste `-wal`/`-shm`-Dateien im Snapshot-Ordner.

Gefunden am 11.08.2026 beim Ausrollen von v206: 56 Dateien vom 07. und 08.08.
lagen dort, deren `.db` längst weggeräumt war. Ursache ist ein Muster, das auf
`.db` endet und die Begleiter deshalb nie sieht - sie bleiben für immer liegen
und werden jede Nacht mitgesichert.

Erster Test im Repo, der `util/` anfasst. Der Ordner ist ein eigener Container
mit eigenen Abhängigkeiten; `db_snapshot.py` hängt aber an nichts ausser
`sqlite3` und `pathlib` und lässt sich deshalb direkt laden, ohne die
Testumgebung um util-Kram zu erweitern.

Die Modulkonstanten `DB`/`SNAP_DIR` zeigen fest auf `/data` - im Test werden
sie auf ein tmp_path umgebogen. Deshalb steht hier ein eigenes Fixture statt
`monkeypatch.chdir`: es geht um absolute Pfade, nicht um das Arbeitsverzeichnis.
"""
import importlib.util
import pathlib
import sqlite3

import pytest

UTIL = pathlib.Path(__file__).resolve().parents[1] / "util" / "db_snapshot.py"


@pytest.fixture()
def snapshot(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("db_snapshot_test", UTIL)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)

    daten = tmp_path / "data"
    daten.mkdir()
    snaps = daten / "snapshots"
    snaps.mkdir()

    db_pfad = daten / "portal.db"
    v = sqlite3.connect(db_pfad)
    v.execute("CREATE TABLE t(x)")
    v.execute("INSERT INTO t VALUES(1)")
    v.commit()
    v.close()

    monkeypatch.setattr(modul, "DB", db_pfad)
    monkeypatch.setattr(modul, "SNAP_DIR", snaps)
    return {"modul": modul, "snaps": snaps}


def _anlegen(snaps, stempel, mit_db=True, begleiter=("-wal", "-shm")):
    if mit_db:
        (snaps / f"portal-{stempel}.db").write_bytes(b"x")
    for endung in begleiter:
        (snaps / f"portal-{stempel}.db{endung}").write_bytes(b"x")


def _namen(snaps):
    return sorted(p.name for p in snaps.iterdir())


# --- Der Befund -------------------------------------------------------------

def test_verwaiste_begleiter_verschwinden(snapshot):
    snaps = snapshot["snaps"]
    _anlegen(snaps, "20260807-0700", mit_db=False)
    _anlegen(snaps, "20260808-0900", mit_db=False)

    snapshot["modul"]._prune()

    assert _namen(snaps) == [], f"Übrig geblieben: {_namen(snaps)}"


def test_begleiter_eines_gueltigen_snapshots_bleiben(snapshot):
    """Die Gegenrichtung, und der Grund, warum nicht einfach alles mit `-wal`
    im Namen gelöscht wird: ein laufender Snapshot hat seine Begleiter zu
    Recht neben sich liegen."""
    snaps = snapshot["snaps"]
    _anlegen(snaps, "20260811-2200", mit_db=True)

    snapshot["modul"]._prune()

    assert _namen(snaps) == [
        "portal-20260811-2200.db",
        "portal-20260811-2200.db-shm",
        "portal-20260811-2200.db-wal",
    ]


def test_ein_einzelner_verwaister_begleiter_reicht(snapshot):
    """Es kommt vor, dass nur eine der beiden Dateien übrig ist."""
    snaps = snapshot["snaps"]
    _anlegen(snaps, "20260807-0700", mit_db=False, begleiter=("-wal",))

    snapshot["modul"]._prune()

    assert _namen(snaps) == []


def test_ausgemusterte_snapshots_nehmen_ihre_begleiter_mit(snapshot):
    """Der eigentliche Grund für die Reihenfolge in `_prune()`: Erst fallen
    die ältesten `.db`, DANN sind deren Begleiter verwaist. Liefe das
    Aufräumen vorher, blieben sie genau eine Runde zu lang liegen - und beim
    nächsten Lauf lägen die nächsten daneben."""
    snaps = snapshot["snaps"]
    for i in range(snapshot["modul"].KEEP + 2):
        _anlegen(snaps, f"202608{i // 24 + 1:02d}-{i % 24:02d}00", mit_db=True)
    vorher = len(_namen(snaps))

    snapshot["modul"]._prune()

    uebrig = _namen(snaps)
    dbs = [n for n in uebrig if n.endswith(".db")]
    assert len(dbs) == snapshot["modul"].KEEP, f"{len(dbs)} .db übrig statt KEEP"
    assert len(uebrig) < vorher
    for name in uebrig:
        if not name.endswith(".db"):
            haupt = name.rsplit("-", 1)[0]
            assert haupt in dbs, f"{name} ist verwaist und liegt noch da"


# --- Und der ganze Weg, einmal echt ----------------------------------------

def test_take_legt_einen_snapshot_an_und_raeumt_dabei_auf(snapshot):
    """Gegenprobe, dass `_prune()` überhaupt aus `take()` heraus läuft - ein
    Aufräumen, das nur der Test aufruft, räumt im Betrieb nie etwas weg."""
    snaps = snapshot["snaps"]
    _anlegen(snaps, "20260807-0700", mit_db=False)

    snapshot["modul"].take()

    uebrig = _namen(snaps)
    assert not any(n.startswith("portal-20260807") for n in uebrig), uebrig
    assert any(n.endswith(".db") for n in uebrig), "Kein neuer Snapshot entstanden"
