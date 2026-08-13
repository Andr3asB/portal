"""Wunsch #130/#211, zweiter Teil: Das Backup verlässt das Haus verschlüsselt.

Der erste Teil (Prüfung des Zielrechners) steht in `test_backup_hostkey.py`.
Hier geht es um die Frage, die danach übrig blieb: Auf dem NAS lag die
komplette Familiendatenbank im Klartext – Kassenbuch, private Aufgaben,
Geburtstage, Wünsche, Vokabeln.

Andis Entscheidung vom 13.08.2026: **asymmetrisch**, der private Schlüssel
liegt weder auf home02 noch auf dem NAS. `util/backup.py` kennt deshalb nur
einen öffentlichen Schlüssel (`BACKUP_AGE_RECIPIENT`).

Der wichtigste Test hier ist `test_ohne_age_kopf_geht_nichts_raus`. Alle
anderen prüfen Verdrahtung; dieser prüft die Zusage selbst – dass nämlich
nichts das Haus verlässt, von dem nicht nachgewiesen ist, dass es
verschlüsselt ist. Ein `age`, das mit Exit 0 endet und trotzdem Klartext
hinterlässt (falsches `-o`, volle Platte, künftiger Umbau), wäre sonst
unbemerkt geblieben – und zwar dauerhaft, denn niemand sieht sich ein
Backup an, das funktioniert.
"""
import importlib.util
import pathlib

import pytest

UTIL = pathlib.Path(__file__).resolve().parents[1] / "util" / "backup.py"

# Ein echt aussehender age-Schlüssel (Beispiel aus der age-Dokumentation).
# Nur öffentliches Material – hier ist bewusst nichts geheim.
SCHLUESSEL = "age1ql3z7hjy54pw3hyww5ayyfg7zqgvc7w3j2elw8zmrj2kg5sfn9aqmcac8p"


@pytest.fixture()
def backup(monkeypatch):
    """`backup.py` importiert `db_snapshot` – beide liegen in util/, das nicht
    im sys.path der Tests steht."""
    monkeypatch.syspath_prepend(str(UTIL.parent))
    spec = importlib.util.spec_from_file_location("backup_krypto_test", UTIL)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


# ── Der Schlüssel selbst ────────────────────────────────────────────────────

def test_echter_schluessel_wird_angenommen(backup):
    assert backup._RECIPIENT_MUSTER.match(SCHLUESSEL)


@pytest.mark.parametrize("murks", [
    "age1",                       # nur das Präfix
    SCHLUESSEL[:20],              # abgeschnitten (Copy-Paste-Unfall)
    SCHLUESSEL.upper(),           # falsche Schreibweise
    "AGE-SECRET-KEY-1QQQQQQQ",    # der PRIVATE Schlüssel, versehentlich hier
    "/ssh/backup.key",            # ein Pfad statt eines Schlüssels
    "ja",
])
def test_murks_wird_abgelehnt(backup, murks):
    assert not backup._RECIPIENT_MUSTER.match(murks)


def test_privater_schluessel_in_der_env_faellt_auf(backup, monkeypatch, caplog):
    """Der wahrscheinlichste Bedienfehler: Andi kopiert die falsche Hälfte des
    Schlüsselpaars in die .env. Dann darf NICHT unverschlüsselt gesichert
    werden – und es muss im Log stehen, warum gar nichts passiert ist."""
    monkeypatch.setattr(backup, "AGE_RECIPIENT", "AGE-SECRET-KEY-1QQQQQQQ")
    monkeypatch.setattr(backup.os.path, "exists", lambda p: True)

    gerufen = []
    monkeypatch.setattr(backup, "_transfer", lambda: gerufen.append(True))

    with caplog.at_level("ERROR"):
        backup.run()

    assert not gerufen, "Es wurde trotz unbrauchbarem Schlüssel übertragen"
    assert "age" in caplog.text.lower()
    # Und der Wert selbst darf nicht vollstaendig im Log landen.
    assert "AGE-SECRET-KEY-1QQQQQQQ" not in caplog.text


# ── Die Zusage: kein Klartext nach draussen ─────────────────────────────────

def test_ohne_age_kopf_geht_nichts_raus(backup, monkeypatch, tmp_path):
    """`age` endet mit 0, die Ausgabedatei ist aber Klartext. Genau hier muss
    Schluss sein."""
    quelle = tmp_path / "portal.tar.gz"
    quelle.write_bytes(b"\x1f\x8b" + b"das sind echte Familiendaten")

    def falsches_age(argv, **kwargs):
        pathlib.Path(argv[argv.index("-o") + 1]).write_bytes(b"\x1f\x8bimmer noch Klartext")
        return type("R", (), {"returncode": 0, "stderr": b""})()

    monkeypatch.setattr(backup, "AGE_RECIPIENT", SCHLUESSEL)
    monkeypatch.setattr(backup.subprocess, "run", falsches_age)

    with pytest.raises(RuntimeError, match="Kopf"):
        backup._verschluesseln(quelle)


def test_mit_age_kopf_geht_es_durch(backup, monkeypatch, tmp_path):
    """Gegenprobe – sonst prüft der Test oben nur, dass die Funktion immer
    wirft."""
    quelle = tmp_path / "portal.tar.gz"
    quelle.write_bytes(b"\x1f\x8bnutzdaten")

    def echtes_age(argv, **kwargs):
        assert argv[0] == "age"
        assert argv[1] == "-r" and argv[2] == SCHLUESSEL
        pathlib.Path(argv[argv.index("-o") + 1]).write_bytes(
            b"age-encryption.org/v1\n-> X25519 abc\n...")
        return type("R", (), {"returncode": 0, "stderr": b""})()

    monkeypatch.setattr(backup, "AGE_RECIPIENT", SCHLUESSEL)
    monkeypatch.setattr(backup.subprocess, "run", echtes_age)

    ziel = backup._verschluesseln(quelle)

    assert ziel.name.endswith(".age")
    assert not quelle.exists(), (
        "Der Klartext liegt noch daneben – ein späterer Fehler könnte ihn "
        "hochladen")


def test_age_fehler_bricht_ab(backup, monkeypatch, tmp_path):
    quelle = tmp_path / "portal.tar.gz"
    quelle.write_bytes(b"\x1f\x8bnutzdaten")

    monkeypatch.setattr(backup, "AGE_RECIPIENT", SCHLUESSEL)
    monkeypatch.setattr(backup.subprocess, "run", lambda *a, **k: type(
        "R", (), {"returncode": 1, "stderr": b"age: no recipients"})())

    with pytest.raises(RuntimeError, match="age exit 1"):
        backup._verschluesseln(quelle)


# ── Verdrahtung ────────────────────────────────────────────────────────────

def test_mit_schluessel_wird_verschluesselt_und_umbenannt(backup, monkeypatch):
    monkeypatch.setattr(backup, "AGE_RECIPIENT", SCHLUESSEL)
    monkeypatch.setattr(backup, "_packen", lambda ziel: ziel)
    monkeypatch.setattr(backup, "_verschluesseln",
                        lambda quelle: quelle.with_name(quelle.name + ".age"))

    gesendet = {}
    monkeypatch.setattr(backup, "_senden",
                        lambda datei, endung: gesendet.update(endung=endung))

    backup._transfer()

    assert gesendet["endung"] == ".tar.gz.age"


def test_ohne_schluessel_warnt_es_deutlich(backup, monkeypatch, caplog):
    """Unverschlüsselt ist erlaubt (Übergangszustand), aber nie stillschweigend
    – sonst merkt niemand, dass die Verschlüsselung nie eingeschaltet wurde."""
    monkeypatch.setattr(backup, "AGE_RECIPIENT", "")
    monkeypatch.setattr(backup, "_packen", lambda ziel: ziel)

    gesendet = {}
    monkeypatch.setattr(backup, "_senden",
                        lambda datei, endung: gesendet.update(endung=endung))

    with caplog.at_level("WARNING"):
        backup._transfer()

    assert gesendet["endung"] == ".tar.gz"
    assert "UNVERSCHLÜSSELT" in caplog.text


# ── Der Remote-Befehl ──────────────────────────────────────────────────────

def test_rotation_erfasst_beide_bestaende(backup):
    """Nach der Umstellung liegen `.tar.gz` und `.tar.gz.age` nebeneinander.
    Zählt die Rotation nur eine Sorte, wachsen zwei getrennte Bestände zu je
    sieben – und der alte, unverschlüsselte bleibt ewig liegen."""
    befehl = backup._remote_cmd(".tar.gz.age")
    assert "portal-*.tar.gz*" in befehl


def test_teil_upload_zaehlt_nicht_als_backup(backup):
    """Der Name der Zwischendatei darf nicht auf `portal-` passen, sonst
    verdrängt ein abgebrochener Upload ein echtes Backup aus den sieben."""
    assert not backup._UPLOAD_TEIL.startswith("portal-")
    befehl = backup._remote_cmd(".tar.gz.age")
    assert befehl.index(backup._UPLOAD_TEIL) < befehl.index("ls -t")


def test_erst_pruefen_dann_umbenennen(backup):
    """Ein leerer Teil-Upload darf nie zu einem gültigen Dateinamen werden."""
    befehl = backup._remote_cmd(".tar.gz.age")
    assert f"[ -s {backup._UPLOAD_TEIL} ]" in befehl
    assert befehl.index("[ -s") < befehl.index("mv ")


def test_endung_landet_im_dateinamen(backup):
    assert backup._remote_cmd(".tar.gz.age").endswith(
        "| tail -n +8 | xargs -r rm -f")
    assert ".tar.gz.age" in backup._remote_cmd(".tar.gz.age")
