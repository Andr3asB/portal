"""Wunsch #190: Das stille Veralten der Mannschaftsliste sichtbar machen.

Die Liste entsteht durch HTML-Auslesen der Vereinsseite. Bricht das, laesst
`_mannschaften_aktualisieren()` den alten Stand stehen - das ist richtig, war
aber vollkommen unsichtbar: die Liste konnte monatelang veralten, ohne dass es
jemand merkt. Genau das ist Ende August 2026 eingetreten, als der
handball.net-Relaunch alle HTML-Quellen abraeumte.

Geprueft wird deshalb dreierlei:

1. Der Fehlschlag wird ueberhaupt festgehalten (vorher: verschluckt).
2. Er warnt NICHT sofort - ein einzelner Aussetzer der Gegenstelle ist normal
   und soll die Familie nicht beunruhigen. Erst nach mehreren Tagen.
3. Die Bremse: ohne sie fragt JEDER Seitenaufruf die tote Quelle neu an, mit
   15 s Zeitlimit vor dem Seitenaufbau. Das ist der Teil, der beim Ausfall
   nicht nur unschoen, sondern spuerbar ist.
"""
import importlib

import pytest


@pytest.fixture()
def modul(app):
    return importlib.import_module("teile.18_tvb")


@pytest.fixture()
def verbindung(db):
    return db["verbindung"]


# --- 1) Der Fehlschlag wird festgehalten ----------------------------------

def test_fehlschlag_wird_vermerkt(modul, verbindung, monkeypatch):
    """Vorher gab es hier gar keine Spur - die Funktion kehrte einfach um."""
    monkeypatch.setattr(modul, "_mannschaften_von_handball_net", lambda: [])
    modul._mannschaften_aktualisieren(verbindung)

    z = modul._quelle_status(verbindung, modul._QUELLE_MANNSCHAFTEN)
    assert z is not None, "Fehlschlag wurde verschluckt"
    assert z["letzter_fehler"], "kein Fehlertext hinterlegt"
    assert z["zuletzt_versuch"], "kein Versuchszeitpunkt hinterlegt"
    assert z["zuletzt_ok"] is None, "nie geglueckt, trotzdem als Erfolg vermerkt"


def test_erfolg_loescht_den_fehler(modul, verbindung, monkeypatch):
    monkeypatch.setattr(modul, "_mannschaften_von_handball_net", lambda: [])
    modul._mannschaften_aktualisieren(verbindung)

    monkeypatch.setattr(modul, "_mannschaften_von_handball_net",
                        lambda: [("t1", "TV Bittenfeld 1898 2", "Herren Bezirksliga")])
    modul._mannschaften_aktualisieren(verbindung)

    z = modul._quelle_status(verbindung, modul._QUELLE_MANNSCHAFTEN)
    assert z["letzter_fehler"] is None
    assert z["zuletzt_ok"] is not None


# --- 2) Gewarnt wird erst nach Tagen --------------------------------------

def test_frischer_aussetzer_warnt_nicht(modul, verbindung, monkeypatch):
    """Die Gegenprobe zur Warnung: ein einzelner Fehlschlag ist kein Grund,
    die Familie zu beunruhigen. Ohne diesen Test waere eine Warnung, die
    immer erscheint, ebenfalls 'gruen'."""
    monkeypatch.setattr(modul, "_mannschaften_von_handball_net",
                        lambda: [("t1", "TV Bittenfeld 1898 2", "Herren Bezirksliga")])
    modul._mannschaften_aktualisieren(verbindung)          # Erfolg: heute
    monkeypatch.setattr(modul, "_mannschaften_von_handball_net", lambda: [])
    modul._mannschaften_aktualisieren(verbindung)          # Fehlschlag: heute

    assert modul._quelle_warnung(verbindung, modul._QUELLE_MANNSCHAFTEN) is None


def test_alter_stand_warnt(modul, verbindung, monkeypatch):
    monkeypatch.setattr(modul, "_mannschaften_von_handball_net", lambda: [])
    modul._mannschaften_aktualisieren(verbindung)
    # Letzter Erfolg liegt lange zurueck.
    verbindung.execute(
        "UPDATE tvb_quellen SET zuletzt_ok = datetime('now', '-9 days') WHERE quelle=?",
        (modul._QUELLE_MANNSCHAFTEN,))
    verbindung.commit()

    warnung = modul._quelle_warnung(verbindung, modul._QUELLE_MANNSCHAFTEN)
    assert warnung, "veralteter Stand loest keine Warnung aus"
    assert warnung != "noch nie"


def test_nie_geglueckt_wird_benannt(modul, verbindung, monkeypatch):
    """Ein Datum gibt es dann nicht - die Seite muss trotzdem etwas sagen
    koennen, sonst stuende dort ein leerer Satz."""
    monkeypatch.setattr(modul, "_mannschaften_von_handball_net", lambda: [])
    modul._mannschaften_aktualisieren(verbindung)
    assert modul._quelle_warnung(verbindung, modul._QUELLE_MANNSCHAFTEN) == "noch nie"


# --- 3) Die Bremse --------------------------------------------------------

def test_nach_fehlschlag_wird_nicht_sofort_erneut_gefragt(modul, verbindung, monkeypatch):
    """Der eigentliche Betriebsschaden: 15 s Zeitlimit bei JEDEM Aufruf."""
    versuche = []

    def zaehlen():
        versuche.append(1)
        return []

    monkeypatch.setattr(modul, "_mannschaften_von_handball_net", zaehlen)
    modul._mannschaften_holen(verbindung)
    modul._mannschaften_holen(verbindung)
    modul._mannschaften_holen(verbindung)

    assert len(versuche) == 1, f"tote Quelle {len(versuche)}x abgefragt statt einmal"


def test_bremse_loest_sich_wieder(modul, verbindung, monkeypatch):
    """Gegenprobe: Die Bremse darf die Quelle nicht dauerhaft stilllegen -
    sonst bliebe die Liste auch dann alt, wenn handball.net zurueckkommt."""
    versuche = []
    monkeypatch.setattr(modul, "_mannschaften_von_handball_net",
                        lambda: (versuche.append(1), [])[1])
    modul._mannschaften_holen(verbindung)
    verbindung.execute(
        "UPDATE tvb_quellen SET zuletzt_versuch = datetime('now', '-2 hours') WHERE quelle=?",
        (modul._QUELLE_MANNSCHAFTEN,))
    verbindung.commit()
    modul._mannschaften_holen(verbindung)

    assert len(versuche) == 2


# --- Die zweite HTML-Quelle aus dem Wunsch --------------------------------

def test_liga_id_meldet_fehlschlag(modul, verbindung, monkeypatch):
    """#190 nennt _liga_id_der_mannschaft() ausdruecklich mit."""
    monkeypatch.setattr(modul, "_hb_seite_holen", lambda pfad: None)
    assert modul._liga_id_der_mannschaft("t1", verbindung) is None

    z = modul._quelle_status(verbindung, modul._QUELLE_LIGA_ID)
    assert z and z["letzter_fehler"]


def test_liga_id_erreichbar_aber_leer_zaehlt_als_fehler(modul, verbindung, monkeypatch):
    """Der heimtueckischere Fall: die Seite antwortet, nur steht die Liga-ID
    nicht mehr drin. Ein reiner Erreichbarkeitstest wuerde das gruen melden -
    und genau so sieht der Relaunch aus."""
    monkeypatch.setattr(modul, "_hb_seite_holen",
                        lambda pfad: "<html>neues Design, keine Liga-ID</html>")
    assert modul._liga_id_der_mannschaft("t1", verbindung) is None

    z = modul._quelle_status(verbindung, modul._QUELLE_LIGA_ID)
    assert z and z["letzter_fehler"] == "Liga-ID nicht mehr im HTML"


# --- Der Bestand von VOR dieser Aenderung ---------------------------------

def test_alter_bestand_gilt_als_letzter_erfolg(modul, verbindung, monkeypatch):
    """tvb_quellen gibt es erst seit #190. Beim ersten Ausfall nach der
    Auslieferung stuende sonst "noch nie" auf der Seite, obwohl die Liste
    nachweislich einmal geladen wurde - genau so lag der Fall am 30.08.2026:
    Bestand vom 14.08., Quelle tot, Erfolgsdatum leer.

    `tvb_mannschaften.aktualisiert_am` IST dieses Datum, denn die Tabelle wird
    nur im Erfolgsfall neu geschrieben."""
    verbindung.execute("""
        INSERT INTO tvb_mannschaften(team_id, name, kurz, position, aktualisiert_am)
        VALUES ('t1', 'TV Bittenfeld 1898 2', 'Herren', 1, datetime('now', '-16 days'))
    """)
    verbindung.commit()

    monkeypatch.setattr(modul, "_mannschaften_von_handball_net", lambda: [])
    modul._mannschaften_aktualisieren(verbindung)

    warnung = modul._quelle_warnung(verbindung, modul._QUELLE_MANNSCHAFTEN)
    assert warnung and warnung != "noch nie", \
        "alter Bestand wurde als 'noch nie geladen' gemeldet"


def test_ohne_jeden_bestand_bleibt_es_bei_noch_nie(modul, verbindung, monkeypatch):
    """Gegenprobe: Der Rueckgriff darf kein Datum erfinden, wo nie eines war."""
    verbindung.execute("DELETE FROM tvb_mannschaften")
    verbindung.commit()
    monkeypatch.setattr(modul, "_mannschaften_von_handball_net", lambda: [])
    modul._mannschaften_aktualisieren(verbindung)
    assert modul._quelle_warnung(verbindung, modul._QUELLE_MANNSCHAFTEN) == "noch nie"
