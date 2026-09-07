"""Wunsch #272: Morning Briefing auf der Startseite.

Drei Dinge, die hier schiefgehen koennen und die man erst Tage spaeter
merkt: der falsche Tag (UTC-Container), ein Geburtstag, der "morgen" ist,
aber ueber den Jahreswechsel liegt, und ein Push, der zu oft oder gar nicht
kommt. Deshalb ist die Auswahl (`faellige_pushes`) mit fester Uhrzeit
testbar, ganz ohne Thread.
"""
import importlib
from datetime import date, datetime

import pytest
from teile.kern import LOKAL_TZ


@pytest.fixture()
def modul(app):
    return importlib.import_module("teile.27_briefing")


def _zeit(jahr, monat, tag, stunde, minute=0):
    return datetime(jahr, monat, tag, stunde, minute, tzinfo=LOKAL_TZ)


def _essen(db, tag, mahlzeit, text=None, rezept=None):
    v = db["verbindung"]
    rezept_id = None
    if rezept:
        rezept_id = v.execute(
            "INSERT INTO rezepte (name, kategorie, erstellt_von) VALUES (?, 'nudeln', ?)",
            (rezept, db["familie"]["TestAdmin"]["id"])).lastrowid
    v.execute("INSERT INTO essensplan_eintraege (tag, mahlzeit, rezept_id, text) VALUES (?,?,?,?)",
              (tag, mahlzeit, rezept_id, text))
    v.commit()


def _geburtstag(db, name, tag, monat, jahr=None, ausgeblendet_fuer=None):
    v = db["verbindung"]
    gid = v.execute(
        "INSERT INTO geburtstage (name, tag, monat, jahr, erstellt_von) VALUES (?,?,?,?,?)",
        (name, tag, monat, jahr, db["familie"]["TestAdmin"]["id"])).lastrowid
    if ausgeblendet_fuer:
        v.execute("INSERT INTO geburtstag_einstellungen (user_id, geburtstag_id, ausgeblendet) VALUES (?,?,1)",
                  (ausgeblendet_fuer, gid))
    v.commit()
    return gid


def _abo(db, user_id):
    v = db["verbindung"]
    v.execute("INSERT INTO push_abos (user_id, endpoint, p256dh, auth, geraet) VALUES (?,?,?,?,?)",
              (user_id, f"https://push.example/{user_id}", "k", "a", "Test"))
    v.commit()


# --- Inhalt --------------------------------------------------------------------

def test_mahlzeiten_immer_beide_slots(app, modul, db, admin):
    _essen(db, "2026-09-07", "mittag", rezept="Spaghetti")
    with app.app_context():
        b = modul.briefing_fuer(db["verbindung"], admin["id"], _zeit(2026, 9, 7, 8))
    assert b["tag"] == "2026-09-07"
    assert b["datum_text"] == "Montag, 7. September"
    assert [m["label"] for m in b["mahlzeiten"]] == ["Mittag", "Abend"]
    assert b["mahlzeiten"][0]["text"] == "Spaghetti" and b["mahlzeiten"][0]["symbol"]
    assert b["mahlzeiten"][1]["text"] == "", "leerer Slot bleibt sichtbar leer"


def test_freitext_statt_rezept(app, modul, db, admin):
    _essen(db, "2026-09-07", "abend", text="Reste")
    with app.app_context():
        b = modul.briefing_fuer(db["verbindung"], admin["id"], _zeit(2026, 9, 7, 8))
    assert b["mahlzeiten"][1] == {"slot": "abend", "label": "Abend", "text": "Reste", "symbol": ""}


def test_geburtstage_heute_und_morgen_nicht_uebermorgen(app, modul, db, admin):
    _geburtstag(db, "Heute", 7, 9, 2016)
    _geburtstag(db, "Morgen", 8, 9)
    _geburtstag(db, "Uebermorgen", 9, 9)
    with app.app_context():
        b = modul.briefing_fuer(db["verbindung"], admin["id"], _zeit(2026, 9, 7, 8))
    assert [(g["name"], g["wann"], g["wird_alt"]) for g in b["geburtstage"]] == [
        ("Heute", "heute", 10), ("Morgen", "morgen", None)]


def test_morgen_ueber_den_jahreswechsel(app, modul, db, admin):
    _geburtstag(db, "Neujahr", 1, 1)
    with app.app_context():
        b = modul.briefing_fuer(db["verbindung"], admin["id"], _zeit(2026, 12, 31, 8))
    assert [g["wann"] for g in b["geburtstage"]] == ["morgen"]


def test_ausgeblendete_geburtstage_fehlen_nur_dem_der_sie_ausblendet(app, modul, db, admin, kind):
    _geburtstag(db, "Versteckt", 7, 9, ausgeblendet_fuer=admin["id"])
    with app.app_context():
        fuer_admin = modul.briefing_fuer(db["verbindung"], admin["id"], _zeit(2026, 9, 7, 8))
        fuer_kind = modul.briefing_fuer(db["verbindung"], kind["id"], _zeit(2026, 9, 7, 8))
    assert fuer_admin["geburtstage"] == []
    assert [g["name"] for g in fuer_kind["geburtstage"]] == ["Versteckt"]


def test_gruss_passt_zur_tageszeit(modul):
    assert modul.gruss(_zeit(2026, 9, 7, 7)) == "Guten Morgen"
    assert modul.gruss(_zeit(2026, 9, 7, 14)) == "Hallo"
    assert modul.gruss(_zeit(2026, 9, 7, 20)) == "Guten Abend"


def test_push_text_fasst_zusammen(app, modul, db, admin):
    with app.app_context():
        leer = modul.push_text(modul.briefing_fuer(db["verbindung"], admin["id"], _zeit(2026, 9, 7, 8)))
    assert leer == "Dein Briefing für heute wartet auf dich."
    _essen(db, "2026-09-07", "mittag", text="Pizza")
    _geburtstag(db, "Oma", 7, 9)
    with app.app_context():
        voll = modul.push_text(modul.briefing_fuer(db["verbindung"], admin["id"], _zeit(2026, 9, 7, 8)))
    assert voll == "Mittag: Pizza · 🎂 Oma hat heute Geburtstag"


# --- Startseite und Bestaetigung ------------------------------------------------

def test_karte_steht_bis_zur_bestaetigung(client, modul, db, admin, monkeypatch):
    monkeypatch.setattr(modul, "jetzt_lokal", lambda: _zeit(2026, 9, 7, 8))
    _essen(db, "2026-09-07", "mittag", text="Pizza")
    home = admin["tokens"]["home"]
    seite = client.get(f"/p/{home}").get_data(as_text=True)
    assert '<section class="briefing-karte" id="briefing">' in seite
    assert "Guten Morgen, TestAdmin!" in seite and "Pizza" in seite
    assert 'id="briefing-wieder" hidden' in seite

    r = client.post(f"/p/{home}/briefing/bestaetigen")
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/p/{home}")
    assert modul.ist_bestaetigt(db["verbindung"], admin["id"], date(2026, 9, 7))

    seite = client.get(f"/p/{home}").get_data(as_text=True)
    assert 'id="briefing" hidden' in seite
    assert 'id="briefing-wieder">' in seite and f'href="/p/{home}/briefing"' in seite


def test_bestaetigen_per_fetch_antwortet_json(client, modul, db, admin, monkeypatch):
    monkeypatch.setattr(modul, "jetzt_lokal", lambda: _zeit(2026, 9, 7, 8))
    home = admin["tokens"]["home"]
    r = client.post(f"/p/{home}/briefing/bestaetigen", headers={"Accept": "application/json"})
    assert r.status_code == 200 and r.get_json() == {"ok": True, "bestaetigt": True}


def test_bestaetigung_gilt_nur_fuer_den_tag(client, modul, db, admin, monkeypatch):
    monkeypatch.setattr(modul, "jetzt_lokal", lambda: _zeit(2026, 9, 7, 8))
    home = admin["tokens"]["home"]
    client.post(f"/p/{home}/briefing/bestaetigen")
    monkeypatch.setattr(modul, "jetzt_lokal", lambda: _zeit(2026, 9, 8, 8))
    seite = client.get(f"/p/{home}").get_data(as_text=True)
    assert '<section class="briefing-karte" id="briefing">' in seite, "am naechsten Tag wieder da"


def test_eigene_seite_und_fremder_token(client, modul, db, admin, monkeypatch):
    monkeypatch.setattr(modul, "jetzt_lokal", lambda: _zeit(2026, 9, 7, 8))
    home = admin["tokens"]["home"]
    seite = client.get(f"/p/{home}/briefing")
    assert seite.status_code == 200
    text = seite.get_data(as_text=True)
    assert "Guten Morgen, TestAdmin!" in text and "✓ Gelesen" in text
    assert f'href="/p/{home}"' in text, "Zurueck-Link zur Startseite (keine Sackgasse)"
    assert client.get("/p/falsch/briefing").status_code == 403
    assert client.post("/p/falsch/briefing/bestaetigen").status_code == 403
    assert client.get("/p/briefing").status_code == 403, "ohne Token und ohne Sitzung"


# --- Erinnerung per Push --------------------------------------------------------

def test_werktag_ab_halb_acht(app, modul, db, admin):
    _abo(db, admin["id"])
    v = db["verbindung"]
    with app.app_context():
        assert modul.faellige_pushes(v, _zeit(2026, 9, 7, 7, 29)) == []      # Montag
        assert modul.faellige_pushes(v, _zeit(2026, 9, 7, 7, 30)) == [admin["id"]]
        assert modul.faellige_pushes(v, _zeit(2026, 9, 7, 11, 59)) == [admin["id"]]
        assert modul.faellige_pushes(v, _zeit(2026, 9, 7, 12, 0)) == [], "nach Sendeschluss nicht mehr"


def test_wochenende_ab_neun(app, modul, db, admin):
    _abo(db, admin["id"])
    v = db["verbindung"]
    with app.app_context():
        assert modul.faellige_pushes(v, _zeit(2026, 9, 5, 8, 59)) == []      # Samstag
        assert modul.faellige_pushes(v, _zeit(2026, 9, 5, 9, 0)) == [admin["id"]]
        assert modul.faellige_pushes(v, _zeit(2026, 9, 6, 7, 30)) == []      # Sonntag
        assert modul.faellige_pushes(v, _zeit(2026, 9, 6, 9, 0)) == [admin["id"]]


def test_ohne_abo_kein_push(app, modul, db, admin):
    with app.app_context():
        assert modul.faellige_pushes(db["verbindung"], _zeit(2026, 9, 7, 8)) == []


def test_bestaetigt_heisst_kein_push(app, modul, db, admin):
    _abo(db, admin["id"])
    modul.bestaetigen(db["verbindung"], admin["id"], date(2026, 9, 7))
    with app.app_context():
        assert modul.faellige_pushes(db["verbindung"], _zeit(2026, 9, 7, 8)) == []
        # Gestern bestaetigt zaehlt heute nicht.
        assert modul.faellige_pushes(db["verbindung"], _zeit(2026, 9, 8, 8)) == [admin["id"]]


def test_push_geht_einmal_am_tag(app, modul, db, admin, kind, monkeypatch):
    _abo(db, admin["id"])
    _abo(db, kind["id"])
    verschickt = []
    monkeypatch.setattr(modul, "push_send", lambda uid, titel, text, *a, **kw: verschickt.append((uid, titel, kw.get("dedup_key"))))
    with app.app_context():
        assert modul.pushes_verschicken(app, _zeit(2026, 9, 7, 7, 30)) == 2
        assert modul.pushes_verschicken(app, _zeit(2026, 9, 7, 7, 31)) == 0, "Neustart am selben Morgen"
    assert sorted(verschickt) == sorted([
        (admin["id"], "☀️ Dein Briefing für heute", "briefing-2026-09-07"),
        (kind["id"], "☀️ Dein Briefing für heute", "briefing-2026-09-07")])
    zeilen = db["verbindung"].execute(
        "SELECT user_id, push_am, bestaetigt_am FROM briefing_status ORDER BY user_id").fetchall()
    assert [(z["user_id"], z["push_am"] is not None, z["bestaetigt_am"]) for z in zeilen] == [
        (admin["id"], True, None), (kind["id"], True, None)]
    # Wer danach bestaetigt, ueberschreibt den Push-Vermerk nicht.
    modul.bestaetigen(db["verbindung"], admin["id"], date(2026, 9, 7))
    z = db["verbindung"].execute(
        "SELECT push_am, bestaetigt_am FROM briefing_status WHERE user_id=?", (admin["id"],)).fetchone()
    assert z["push_am"] and z["bestaetigt_am"]


def test_thread_schalter_ist_im_test_aus(app):
    assert str(app.config["BRIEFING_PUSH"]) == "0"
