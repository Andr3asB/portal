"""Wunsch #274: Gewicht und BMI als Liniendiagramm in der Sportschau.

Die Waage meldet einmal am Tag (Withings ueber Health Auto Export), die
Zeitstempel liegen in UTC kurz vor Mitternacht - der lokale Kalendertag ist
also nicht der UTC-Tag. Die Geometrie wird ohne Browser geprueft: Prozent-
koordinaten, Polsterung der Spanne, Gitterlinien, letzter Wert und Delta.
"""
import importlib
from datetime import date, timedelta

import pytest


@pytest.fixture()
def modul(app):
    return importlib.import_module("teile.14_sportschau")


def _tage(bis="2026-09-07", n=14):
    ende = date.fromisoformat(bis)
    return [(ende - timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]


def test_tages_werte_lokaler_tag_und_letzter_wert(modul):
    roh = [
        {"date": "2026-09-05T21:00:00.000Z", "qty": 96.9, "units": "kg"},   # 23:00 lokal am 5.9.
        {"date": "2026-09-05T05:00:00.000Z", "qty": 97.4, "units": "kg"},   # frueher am selben Tag
        {"date": "2026-09-06T22:30:00.000Z", "qty": 96.5, "units": "kg"},   # 00:30 lokal am 7.9.
        {"date": "2026-08-01T21:00:00.000Z", "qty": 99.0},                  # ausserhalb
        {"date": "kaputt", "qty": 1}, {"qty": 2}, {"date": "2026-09-04T21:00:00.000Z", "qty": None},
    ]
    werte = modul._tages_werte(roh, _tage())
    assert werte == {"2026-09-05": 96.9, "2026-09-07": 96.5}


def test_linien_chart_geometrie(modul):
    tage = _tage(n=5)   # 3.9. bis 7.9.
    chart = modul._linien_chart(tage, {"2026-09-03": 97.0, "2026-09-05": 96.0, "2026-09-07": 96.5}, "kg")
    assert [round(p["x"]) for p in chart["punkte"]] == [0, 50, 100]
    assert chart["punkte"][1]["y"] == 0 + (96.0 - (96.0 - 0.5)) / 2.0 * 100   # Polster 0.5 -> Spanne 95,5..97,5
    assert chart["punkte"][0]["y"] > chart["punkte"][2]["y"] > chart["punkte"][1]["y"]
    assert chart["pfad"].startswith("M 0.00,") and chart["pfad"].count("L ") == 2
    assert [g["wert"] for g in chart["gitter"]] == ["95,5", "96,5", "97,5"]
    assert [g["pct"] for g in chart["gitter"]] == [0, 50, 100]
    assert chart["aktuell"] == "96,5" and chart["delta"] == "-0,5" and chart["delta_vorzeichen"] == ""
    assert chart["punkte"][2]["text"] == "07.09.: 96,5 kg"
    assert [a["label"] for a in chart["achse"]] == ["03.09.", "05.09.", "heute"]


def test_linien_chart_ohne_werte_und_mit_einem_wert(modul):
    tage = _tage(n=5)
    assert modul._linien_chart(tage, {}) is None
    chart = modul._linien_chart(tage, {"2026-09-07": 29.6})
    assert chart["delta"] is None and chart["aktuell"] == "29,6"
    assert chart["punkte"][0]["y"] == 50, "ein Wert sitzt in der Mitte der gepolsterten Spanne"
    assert chart["punkte"][0]["text"] == "07.09.: 29,6"


def test_polster_waechst_mit_der_spanne(modul):
    tage = _tage(n=3)
    chart = modul._linien_chart(tage, {"2026-09-05": 90.0, "2026-09-07": 100.0})
    assert [g["wert"] for g in chart["gitter"]] == ["88,5", "95,0", "101,5"]


@pytest.fixture()
def sport_token(app, db):
    from teile.kern import new_token, token_lookup
    v = db["verbindung"]
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='sportschau'").fetchone()["id"]
        t = new_token()
        v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                  (db["familie"]["TestAdmin"]["id"], app_id, token_lookup(t)))
        v.commit()
    return t


def test_seite_zeigt_beide_linien(client, modul, sport_token, monkeypatch):
    # date.today() laesst sich nicht patchen (eingebauter Typ) - die Messungen
    # liegen deshalb relativ zu heute, mittags UTC, damit der lokale Tag
    # unabhaengig von Sommer-/Winterzeit derselbe bleibt.
    vorgestern, gestern = date.today() - timedelta(days=2), date.today() - timedelta(days=1)
    daten = {
        "step_count": [],
        "weight_body_mass": [{"date": f"{vorgestern}T10:00:00.000Z", "qty": 96.9},
                             {"date": f"{gestern}T10:00:00.000Z", "qty": 96.4}],
        "body_mass_index": [{"date": f"{vorgestern}T10:00:00.000Z", "qty": 29.6},
                            {"date": f"{gestern}T10:00:00.000Z", "qty": 29.4}],
    }
    monkeypatch.setattr(modul, "_hae_workouts", lambda a, b: [])
    monkeypatch.setattr(modul, "_hae_metrik", lambda name, a, b: daten[name])
    seite = client.get(f"/a/sportschau/{sport_token}/").get_data(as_text=True)
    assert "⚖️ Gewicht &amp; BMI" in seite
    assert 'id="linie-gewicht"' in seite and 'id="linie-bmi"' in seite
    assert seite.count('class="linie-punkt "') == 2 and seite.count('class="linie-punkt bmi"') == 2
    assert "96,4 kg" in seite and "-0,5 kg im Zeitraum" in seite
    assert f'title="{gestern.strftime("%d.%m.")}: 29,4"' in seite
    assert 'preserveAspectRatio="none"' in seite


def test_seite_ohne_hae_server(client, modul, sport_token, monkeypatch):
    monkeypatch.setattr(modul, "_hae_workouts", lambda a, b: None)
    monkeypatch.setattr(modul, "_hae_metrik", lambda name, a, b: None)
    seite = client.get(f"/a/sportschau/{sport_token}/").get_data(as_text=True)
    assert "Gewichtsdaten gerade nicht abrufbar." in seite
    assert "Schrittdaten gerade nicht abrufbar." in seite


def test_seite_ohne_messungen(client, modul, sport_token, monkeypatch):
    monkeypatch.setattr(modul, "_hae_workouts", lambda a, b: [])
    monkeypatch.setattr(modul, "_hae_metrik", lambda name, a, b: [])
    seite = client.get(f"/a/sportschau/{sport_token}/").get_data(as_text=True)
    assert "Keine Messungen in den letzten 14 Tagen." in seite
