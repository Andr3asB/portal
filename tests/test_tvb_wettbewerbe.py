"""Wunsch #151: Spiele ausserhalb der Bundesliga sichtbar machen.

Ausloeser war die Frage nach Testspielen. Die gibt es bei handball.net nicht –
gefehlt hat stattdessen der DHB-Pokal, und zwar aus einem Grund, den man dem
Code nicht ansieht: handball.net vergibt je Wettbewerb eine EIGENE Team-ID
(`sr.competitor.6272-143352` in der HBL, `sr.competitor.6272-143228` im Pokal).
Ein exakter Vergleich auf die HBL-ID laesst das Pokalspiel also lautlos liegen –
kein Fehler, kein Log, es fehlt einfach.

Genau dieses lautlose Fehlen prueft die erste Testgruppe. Die zweite prueft die
Gegenrichtung: der Praefix-Vergleich darf nicht plötzlich fremde Vereine
einsammeln, deren Nummer zufaellig mit 6272 beginnt.
"""
import importlib

import pytest


@pytest.fixture()
def modul(app):
    return importlib.import_module("teile.18_tvb")


def _spiel(heim_id, gast_id, turnier="DAIKIN HBL", spiel_id="g1"):
    return {
        "id": spiel_id,
        "startsAt": 1787335200000,
        "homeTeam": {"id": heim_id, "name": "Heim"},
        "awayTeam": {"id": gast_id, "name": "Gast"},
        "tournament": {"name": turnier},
        "round": {"name": "1. Runde"},
        "state": "Pre",
    }


# --- Der Fund: der Pokal faellt beim exakten Vergleich heraus --------------

def test_pokalspiel_wird_vom_exakten_vergleich_uebersehen(modul):
    """Dokumentiert die Ursache. Ginge das hier durch, waere die ganze
    Erweiterung ueberfluessig – und wenn handball.net die IDs eines Tages
    vereinheitlicht, sagt uns dieser Test Bescheid."""
    pokal = _spiel("sr.competitor.6272-143228", "sr.competitor.99-1",
                   turnier="DHB-Pokal - Männer")
    assert not modul._ist_eigenes_spiel(pokal, modul._TEAM_ID)


def test_pokalspiel_wird_ueber_die_vereins_id_gefunden(modul):
    pokal = _spiel("sr.competitor.6272-143228", "sr.competitor.99-1",
                   turnier="DHB-Pokal - Männer")
    assert modul._ist_vereins_spiel(pokal, modul._CLUB_ID)


def test_ligaspiel_wird_weiterhin_gefunden(modul):
    liga = _spiel("sr.competitor.99-1", modul._TEAM_ID)
    assert modul._ist_vereins_spiel(liga, modul._CLUB_ID)


# --- Aber nicht mehr als das ----------------------------------------------

def test_fremder_verein_wird_nicht_eingesammelt(modul):
    """Ohne den Bindestrich im Praefix wuerde `sr.competitor.62721` mitmatchen –
    ein fremder Verein im TVB-Spielplan faellt erst auf, wenn jemand genau
    hinsieht."""
    fremd = _spiel("sr.competitor.62721-1", "sr.competitor.99-1")
    assert not modul._ist_vereins_spiel(fremd, modul._CLUB_ID)


def test_voellig_fremdes_spiel_wird_nicht_eingesammelt(modul):
    fremd = _spiel("sr.competitor.11-1", "sr.competitor.99-1")
    assert not modul._ist_vereins_spiel(fremd, modul._CLUB_ID)


# --- Der Wettbewerbsname kommt mit und bleibt erhalten ---------------------

def test_wettbewerb_wird_uebernommen(modul):
    aufbereitet = modul._spiel_aus_roh(
        _spiel(modul._TEAM_ID, "sr.competitor.99-1", turnier="DHB-Pokal - Männer"),
        modul._TEAM_ID)
    assert aufbereitet["wettbewerb"] == "DHB-Pokal - Männer"


def test_wettbewerb_ueberlebt_die_speicherung(app, modul):
    """Der Spielplan liest aus tvb_spiele, nicht aus der API-Antwort – ginge
    die Spalte beim Schreiben verloren, waere die Anzeige wieder blind."""
    from teile.kern import get_db
    with app.test_request_context():
        db = get_db()
        aufbereitet = modul._spiel_aus_roh(
            _spiel(modul._TEAM_ID, "sr.competitor.99-1",
                   turnier="DHB-Pokal - Männer", spiel_id="pokal-1"),
            modul._TEAM_ID)
        modul._tvb_spiele_aktualisieren(db, [aufbereitet])
        zeile = db.execute(
            "SELECT wettbewerb FROM tvb_spiele WHERE id='pokal-1'").fetchone()
    assert zeile["wettbewerb"] == "DHB-Pokal - Männer"


def test_haupt_wettbewerb_kommt_aus_der_antwort(modul):
    """Er wird bewusst nicht konstant hinterlegt – der Ligenname enthaelt den
    Sponsor ("DAIKIN HBL") und aendert sich damit planbar."""
    antwort = {"schedule": {"data": [_spiel("a-1", "b-1", turnier="DAIKIN HBL")]}}
    assert modul._haupt_wettbewerb(antwort) == "DAIKIN HBL"


def test_haupt_wettbewerb_ohne_daten(modul):
    """Sommerpause: der Liga-Spielplan ist leer. Dann darf nichts gekennzeichnet
    werden, aber auch nichts krachen."""
    assert modul._haupt_wettbewerb({"schedule": {"data": []}}) is None
    assert modul._haupt_wettbewerb(None) is None
