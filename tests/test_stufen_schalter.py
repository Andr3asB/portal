"""Wunsch #293 (Sicherheitsaudit 16.09.2026, Befund N-15), zweiter Teil: Die
Stufenschalter fallen nicht mehr still auf unsicher zurück.

`CSRF_MODUS=scharf` mit einem Tippfehler hiess bisher: kein CSRF-Riegel, und
nichts meldete es - die Defaults in app.py sind `0` bzw. `aus`. Jetzt
verweigert die App den Start, wenn ein Wert ausserhalb der erlaubten Menge
steht, und schreibt den tatsächlichen Stand beim Start ins Log.
"""
import importlib

import pytest


@pytest.fixture()
def app_modul(app):
    return importlib.import_module("app")


def _gueltig(**aenderungen):
    stand = {"SITZUNG_AUSSTELLEN": "1", "SITZUNG_KONSUMIEREN": "1",
             "TOKENFREIE_URLS": "1", "CSRF_MODUS": "scharf", "CSP_MODUS": "scharf"}
    stand.update(aenderungen)
    return stand


def test_produktionsstand_ist_gueltig(app_modul):
    stand = app_modul.stufen_pruefen(_gueltig())
    assert stand["CSRF_MODUS"] == "scharf" and stand["SITZUNG_AUSSTELLEN"] == "1"


def test_voreinstellung_aus_app_py_ist_gueltig(app):
    """Die Voreinstellungen (0 / aus) bleiben erlaubt - der Notausstieg ist
    genau das. Sie sind nur nicht mehr das, was ein Tippfehler bewirkt."""
    import importlib
    app_modul = importlib.import_module("app")
    stand = app_modul.stufen_pruefen(app.config)      # Testumgebung = Voreinstellung
    assert stand["CSRF_MODUS"] in ("aus", "beobachten", "scharf")


def test_leerer_wert_ist_kein_stiller_rueckfall(app_modul):
    """`CSRF_MODUS=` (leer) in der .env hiess bisher: aus, ohne Meldung."""
    with pytest.raises(SystemExit):
        app_modul.stufen_pruefen(_gueltig(CSRF_MODUS=""))
    with pytest.raises(SystemExit):
        app_modul.stufen_pruefen({})


@pytest.mark.parametrize("name, wert", [
    ("CSRF_MODUS", "scharf "),      # wird getrimmt: gueltig
    ("CSP_MODUS", "Scharf"),        # Grossschreibung: gueltig
    ("TOKENFREIE_URLS", "true"),
])
def test_tolerante_schreibweisen(app_modul, name, wert):
    app_modul.stufen_pruefen(_gueltig(**{name: wert}))


@pytest.mark.parametrize("name, wert", [
    ("CSRF_MODUS", "schraf"),
    ("CSP_MODUS", "on"),
    ("SITZUNG_AUSSTELLEN", "yes"),
    ("TOKENFREIE_URLS", "2"),
])
def test_tippfehler_verweigert_den_start(app_modul, name, wert):
    with pytest.raises(SystemExit) as info:
        app_modul.stufen_pruefen(_gueltig(**{name: wert}))
    assert name in str(info.value) and "verweigert" in str(info.value)
