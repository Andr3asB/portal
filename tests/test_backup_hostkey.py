"""Wunsch #211 (Sicherheitsaudit, Befund F-03), erster Teil: Der Zielrechner
des Backups wird geprüft.

Vorher: `StrictHostKeyChecking=no` und gar keine `known_hosts`. Der
util-Container akzeptierte damit **jeden** Host, der unter der NAS-Adresse
antwortete. Wer im Netzsegment des NAS dessen IP übernimmt – ARP-Spoofing oder
eine abgepasste DHCP-Neuvergabe – bekam nachts die vollständige
Familiendatenbank frei Haus geliefert.

Die Schlüssel wurden am 12.08.2026 aufgenommen. Der zweite Teil des Befunds –
Verschlüsselung des Datenstroms – ist bewusst NICHT hier: dafür braucht es
eine Entscheidung über den Schlüssel, die am Wunsch hängt.

Warum der Test die Optionsliste liest statt eine Verbindung aufzubauen: Das
NAS steht in einem anderen Netz und ist von der Testmaschine aus nicht
erreichbar; die echte Verbindung wurde nach dem Ausrollen einmal von Hand
gefahren (journal.md, 12.08.2026). Was hier gesichert wird, ist die
Eigenschaft, die still zurückfallen könnte, ohne dass es jemand merkt.
"""
import importlib.util
import pathlib

import pytest

UTIL = pathlib.Path(__file__).resolve().parents[1] / "util" / "backup.py"


@pytest.fixture()
def backup(monkeypatch):
    """`backup.py` importiert `db_snapshot` – beide liegen in util/, das nicht
    im sys.path der Tests steht."""
    monkeypatch.syspath_prepend(str(UTIL.parent))
    spec = importlib.util.spec_from_file_location("backup_test", UTIL)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def _opt(optionen, name):
    """Wert einer `-o name=wert`-Option, oder None."""
    for eintrag in optionen:
        if eintrag.startswith(f"{name}="):
            return eintrag.split("=", 1)[1]
    return None


def test_hostkey_pruefung_ist_scharf(backup):
    assert _opt(backup.SSH_OPTS, "StrictHostKeyChecking") == "yes", (
        "Mit 'no' nimmt der Container jeden Host an, der unter der "
        "NAS-Adresse antwortet (Befund F-03)."
    )


def test_es_gibt_eine_eigene_known_hosts(backup):
    """Ohne `UserKnownHostsFile` sucht ssh in ~/.ssh/known_hosts – die gibt es
    im Container nicht, und `yes` würde dann JEDE Verbindung ablehnen. Die
    Sperre wäre scharf, das Backup tot."""
    assert _opt(backup.SSH_OPTS, "UserKnownHostsFile") == backup.KNOWN_HOSTS


def test_ohne_known_hosts_wird_nicht_gesichert(backup, monkeypatch, caplog):
    """Der Rückfall, den es NICHT geben darf: Fehlt die Datei, muss das Backup
    ausfallen und das im Log sagen - nicht heimlich wieder jedem antworten."""
    monkeypatch.setattr(backup, "KNOWN_HOSTS", "/gibt/es/nicht")
    monkeypatch.setattr(backup.os.path, "exists",
                        lambda p: p == backup.SSH_KEY)

    gerufen = []
    monkeypatch.setattr(backup, "_transfer", lambda: gerufen.append(True))

    with caplog.at_level("ERROR"):
        backup.run()

    assert not gerufen, "Es wurde trotz fehlender known_hosts übertragen"
    assert "known_hosts" in caplog.text, caplog.text


def test_batchmode_bleibt(backup):
    """Ohne BatchMode fragt ssh bei einem unbekannten Schlüssel interaktiv
    nach - im Scheduler heisst das: der Lauf haengt, bis der Timeout greift."""
    assert _opt(backup.SSH_OPTS, "BatchMode") == "yes"


def test_der_schluessel_steht_nicht_im_repo():
    """Gegenprobe zur Ablage: known_hosts liegt auf dem Server unter
    /srv/familienportal/ssh/ und wird read-only gemountet. Läge sie im Repo,
    wäre sie bei jedem Deploy überschreibbar - und ein Angreifer mit
    Schreibrechten aufs Repo könnte den Zielrechner austauschen."""
    wurzel = pathlib.Path(__file__).resolve().parents[1]
    assert not (wurzel / "util" / "known_hosts").exists()
    assert not (wurzel / "known_hosts").exists()
