"""Wunsch #276: Punktmatrix und Personenstreifen in der Geholfen-App.

Die Spezifikation hat harte Akzeptanzkriterien - genau die stehen hier:
Zeilen nach Haeufigkeit sortiert (Gleichstand alphabetisch), leere Tage
bleiben Spalten, ab fuenf Erledigungen vier Punkte plus "+n", Wochenende
markiert, beide Komponenten auf denselben Spalten, Personen-Chips als echte
Knoepfe mit aria-pressed. Die Aggregation ist eine reine Funktion und wird
ohne Datenbank geprueft; der Rest ueber die gerenderte Seite.
"""
import importlib
from datetime import date, timedelta

import pytest

TAGE = [date(2026, 8, 29) + timedelta(days=i) for i in range(10)]   # Sa 29.8. bis Mo 7.9.
AUFGABEN = [
    {"id": 1, "name": "Tisch decken", "emoji": "🍽️", "aktiv": 1},
    {"id": 2, "name": "Spülmaschine", "emoji": "🍳", "aktiv": 1},
    {"id": 3, "name": "Rasen mähen", "emoji": "🌿", "aktiv": 0},
    {"id": 4, "name": "Aufräumen", "emoji": "🧹", "aktiv": 1},
    {"id": 5, "name": "Alt und aus", "emoji": "🧺", "aktiv": 0},
]
PERSONEN = [
    {"id": 10, "name": "Anna", "farbe": "#ff3b30"},
    {"id": 11, "name": "Ben", "farbe": "#007aff"},
]


@pytest.fixture()
def modul(app):
    return importlib.import_module("teile.06_geholfen")


def _ereignisse():
    e = []
    # Spuelmaschine: 6x am 7.9. (Anna 4, Ben 2), 1x am 1.9.
    e += [("2026-09-07", 10, 2)] * 4 + [("2026-09-07", 11, 2)] * 2 + [("2026-09-01", 11, 2)]
    # Tisch decken: 2x, Aufraeumen: 2x -> Gleichstand, alphabetisch
    e += [("2026-09-05", 10, 1), ("2026-09-06", 11, 1)]
    e += [("2026-09-05", 11, 4), ("2026-09-05", 10, 4)]
    # Rasen (inaktiv) hat einen Eintrag im Zeitraum, "Alt und aus" nicht
    e += [("2026-08-30", 10, 3)]
    # Ausserhalb des Fensters und unbekannte Aufgabe/Person
    e += [("2026-08-28", 10, 1), ("2026-09-08", 10, 1), ("2026-09-07", 99, 1), ("2026-09-07", 10, 42)]
    return e


def test_spalten_wochentag_plus_tag_und_wochenende(modul):
    d = modul.matrix_daten([], TAGE, AUFGABEN, PERSONEN)
    labels = [s["label"] for s in d["spalten"]]
    assert labels == ["Sa 29.", "So 30.", "Mo 31.", "Di 1.", "Mi 2.", "Do 3.", "Fr 4.", "Sa 5.", "So 6.", "Mo 7."]
    assert (d["spalten"][3]["wt"], d["spalten"][3]["tz"]) == ("Di", "1.")
    assert d["spalten"][9]["datum_lang"] == "Montag, 7. September"
    assert [s["wochenende"] for s in d["spalten"]] == [True, True, False, False, False, False, False, True, True, False]
    assert [s["heute"] for s in d["spalten"]].index(True) == 9


def test_zeilen_nach_haeufigkeit_dann_alphabetisch(modul):
    d = modul.matrix_daten(_ereignisse(), TAGE, AUFGABEN, PERSONEN)
    assert [(z["name"], z["gesamt"]) for z in d["zeilen"]] == [
        ("Spülmaschine", 7), ("Aufräumen", 2), ("Tisch decken", 2), ("Rasen mähen", 1)]
    assert all(len(z["zellen"]) == 10 for z in d["zeilen"]), "leere Tage bleiben Spalten"


def test_inaktive_aufgabe_ohne_eintrag_fehlt(modul):
    d = modul.matrix_daten(_ereignisse(), TAGE, AUFGABEN, PERSONEN)
    assert "Alt und aus" not in [z["name"] for z in d["zeilen"]]
    d_leer = modul.matrix_daten([], TAGE, AUFGABEN, PERSONEN)
    assert [z["name"] for z in d_leer["zeilen"]] == ["Aufräumen", "Spülmaschine", "Tisch decken"]


def test_ab_fuenf_vier_punkte_plus_zaehler(modul):
    d = modul.matrix_daten(_ereignisse(), TAGE, AUFGABEN, PERSONEN)
    zelle = d["zeilen"][0]["zellen"][9]
    assert zelle["anzahl"] == 6 and len(zelle["punkte"]) == 4 and zelle["mehr"] == 2
    assert [p["uid"] for p in zelle["punkte"]] == [10, 10, 10, 10]
    assert zelle["tooltip"] == "Spülmaschine, Mo 7. – Anna 4x, Ben 2x"
    assert zelle["anteile"] == ["Anna 4x", "Ben 2x"] and zelle["datum_lang"] == "Montag, 7. September"
    assert zelle["punkte"][0]["dunkel"] and zelle["punkte"][0]["hell"], "beide Kontrastfarben"
    leer = d["zeilen"][0]["zellen"][0]
    assert leer["anzahl"] == 0 and leer["punkte"] == [] and leer["mehr"] == 0 and leer["tooltip"] == ""


def test_personenstreifen_stufen(modul):
    e = [("2026-09-07", 10, 2)] * 5 + [("2026-09-06", 10, 1)] * 3 + [("2026-09-05", 10, 1)] * 2 + [("2026-09-04", 10, 4)]
    d = modul.matrix_daten(e, TAGE, AUFGABEN, PERSONEN)
    anna = d["personen"][0]
    assert anna["name"] == "Anna" and anna["vorname"] == "Anna"
    assert modul.matrix_daten([], TAGE, AUFGABEN, [{"id": 1, "name": "Max Muster", "farbe": "#000000"}])["personen"][0]["vorname"] == "Max"
    assert [z["stufe"] for z in anna["zellen"]] == [0, 0, 0, 0, 0, 0, 1, 2, 3, 4]
    assert anna["zellen"][9]["anzahl"] == 5, "Deckel nur bei der Stufe, die Zahl bleibt"
    assert anna["zellen"][6]["tooltip"] == "Anna, Fr 4.: 1 Aufgabe"
    assert anna["zellen"][9]["tooltip"] == "Anna, Mo 7.: 5 Aufgaben"
    assert [z["stufe"] for z in d["personen"][1]["zellen"]] == [0] * 10


# --- Seite -----------------------------------------------------------------------

@pytest.fixture()
def geholfen(app, db):
    from teile.kern import new_token, token_lookup
    v = db["verbindung"]
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='geholfen'").fetchone()["id"]
        tokens = {}
        for name, daten in db["familie"].items():
            t = new_token()
            v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                      (daten["id"], app_id, token_lookup(t)))
            tokens[name] = t
        v.commit()
    return tokens


def test_seite_zeigt_matrix_und_streifen(client, db, geholfen, admin, kind):
    v = db["verbindung"]
    aid = v.execute("SELECT id FROM geholfen_aufgaben WHERE aktiv=1 ORDER BY id LIMIT 1").fetchone()["id"]
    for _ in range(5):
        v.execute("INSERT INTO geholfen_eintraege(aufgabe_id, user_id) VALUES(?,?)", (aid, kind["id"]))
    v.commit()
    seite = client.get(f"/a/geholfen/{geholfen['TestAdmin']}/").get_data(as_text=True)
    assert seite.count('class="mx-zelle mx-kopfzelle') == 10
    assert '<span class="wt">' in seite and '<span class="tz">' in seite, "zweizeiliger Kopf (#278)"
    assert seite.count('aria-pressed="true"') >= 3, "Chip 'alle' plus je Person"
    assert 'data-klick="matrixFilter" data-args=\'["alle"]\'' in seite
    assert seite.count('class="punkt farbflaeche"') == 4 and '<span class="mx-mehr">+1</span>' in seite
    assert 'class="quadrat farbflaeche g4"' in seite
    assert "Kantenlänge = Anzahl erledigter Aufgaben" in seite
    assert 'id="matrix-erklaerung"' in seite
    # Wunsch #278: Tap statt Hover - volle Zellen sind Knoepfe mit den
    # Einzelheiten in data-args, leere Zellen keine; kein title-Tooltip mehr.
    assert seite.count('data-klick="zelleDetails"') == 1
    assert '["TestKind 5x"]]\'' in seite, "Einzelheiten in data-args (tojson, einfach gequotet)"
    assert '– TestKind 5x"' in seite, "aria-label der Zelle nennt Person und Anzahl"
    assert 'title="' not in seite.split('class="matrix-section"')[1].split('mx-overlay')[0]
    assert 'role="dialog"' in seite and 'aria-modal="true"' in seite
    # Wunsch #277: eigener Titel mit Abstand vor dem Personenstreifen.
    assert 'class="heatmap-title ps-titel"' in seite
    assert 'class="name-kurz">TestKind<' in seite


def test_tippen_meldet_den_familientag(client, db, geholfen, admin, modul, monkeypatch):
    monkeypatch.setattr(modul, "heute_lokal", lambda: "2026-09-07")
    v = db["verbindung"]
    aid = v.execute("SELECT id FROM geholfen_aufgaben WHERE aktiv=1 ORDER BY id LIMIT 1").fetchone()["id"]
    r = client.post(f"/a/geholfen/{geholfen['TestAdmin']}/tippen/{aid}",
                    headers={"X-Requested-With": "fetch"}, json={})
    assert r.status_code == 200 and r.get_json()["tag"] == "2026-09-07"


def test_eintrag_kurz_vor_mitternacht_zaehlt_zum_familientag(app, db, geholfen, modul, monkeypatch):
    """23:30 Ortszeit im Sommer ist 21:30 UTC - der Eintrag gehoert zu HEUTE,
    nicht zu gestern (die alte Heatmap rechnete in UTC)."""
    monkeypatch.setattr(modul, "heute_lokal", lambda: "2026-09-07")
    v = db["verbindung"]
    aid = v.execute("SELECT id FROM geholfen_aufgaben WHERE aktiv=1 ORDER BY id LIMIT 1").fetchone()["id"]
    uid = db["familie"]["TestKind"]["id"]
    v.execute("INSERT INTO geholfen_eintraege(aufgabe_id, user_id, zeitstempel) VALUES(?,?,'2026-09-06 21:30:00')", (aid, uid))
    v.commit()
    with app.app_context():
        from teile.kern import get_db
        d = modul._matrix_fuer(get_db())
    kind = next(p for p in d["personen"] if p["id"] == uid)
    assert kind["zellen"][8]["anzahl"] == 1 and kind["zellen"][9]["anzahl"] == 0
    assert kind["zellen"][8]["iso"] == "2026-09-06"
