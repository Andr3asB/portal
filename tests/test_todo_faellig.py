"""Wunsch #260: Aufgaben mit Faelligkeit (Datum UND Uhrzeit) - und die Anzeige.

Das Heikle ist die Zeitzone: Das Formular spricht Ortszeit (datetime-local
ohne Zone), gespeichert wird UTC wie ueberall im Portal, angezeigt wieder
Ortszeit. Ein Fehler in einer der drei Stufen faellt im Sommer als zwei
Stunden auf - genau der Fehler, der in #264 beim TVB gerade erst gefunden
wurde. Deshalb pruefen die Tests mit einem Sommer- UND einem Winterdatum.
"""
import importlib
from datetime import datetime

import pytest
from teile.kern import new_token, token_lookup


@pytest.fixture()
def modul(app):
    return importlib.import_module("teile.04_todo")


@pytest.fixture()
def todo(app, db):
    v = db["verbindung"]
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='todo'").fetchone()["id"]
        tokens = {}
        for name, daten in db["familie"].items():
            if "todo" in daten["tokens"]:
                tokens[name] = daten["tokens"]["todo"]
                continue
            klartext = new_token()
            v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                      (daten["id"], app_id, token_lookup(klartext)))
            tokens[name] = klartext
        v.commit()
    return {"tokens": tokens, "v": v, "familie": db["familie"]}


# --- Umrechnung ---------------------------------------------------------------------

def test_sommerzeit_wird_zu_utc(modul):
    assert modul.faellig_aus_formular("2026-09-08T16:00") == "2026-09-08 14:00:00"


def test_winterzeit_wird_zu_utc(modul):
    assert modul.faellig_aus_formular("2026-12-08T16:00") == "2026-12-08 15:00:00"


def test_datum_ohne_uhrzeit_gilt_ab_mitternacht(modul):
    assert modul.faellig_aus_formular("2026-09-08") == "2026-09-07 22:00:00"


def test_leer_und_unsinn_ergeben_none(modul):
    for wert in ("", "   ", None, "morgen", "2026-13-40T10:00", "08.09.2026"):
        assert modul.faellig_aus_formular(wert) is None, wert


def test_zurueck_ins_formular_und_in_die_anzeige(modul):
    assert modul.faellig_fuer_formular("2026-09-08 14:00:00") == "2026-09-08T16:00"
    assert modul.faellig_anzeige("2026-09-08 14:00:00", heute=datetime(2026, 9, 6).date()) == "Di 08.09., 16:00"
    # Januar = Winterzeit: 15:30 UTC ist 16:30 in Berlin.
    assert modul.faellig_anzeige("2027-01-04 15:30:00", heute=datetime(2026, 9, 6).date()) == "Mo 04.01.2027, 16:30"
    assert modul.faellig_anzeige(None) is None
    assert modul.faellig_fuer_formular(None) == ""


def test_status_ueberfaellig_heute_offen(modul):
    from zoneinfo import ZoneInfo
    jetzt = datetime(2026, 9, 8, 12, 0, tzinfo=ZoneInfo("Europe/Berlin"))
    assert modul.faellig_status("2026-09-08 08:00:00", 0, jetzt) == "ueberfaellig"   # 10:00 Ortszeit
    assert modul.faellig_status("2026-09-08 14:00:00", 0, jetzt) == "heute"          # 16:00 Ortszeit
    assert modul.faellig_status("2026-09-09 06:00:00", 0, jetzt) == "offen"
    assert modul.faellig_status("2026-09-08 08:00:00", 1, jetzt) is None, "erledigt ist nie ueberfaellig"
    assert modul.faellig_status(None, 0, jetzt) is None


# --- Anlegen, Bearbeiten, Anzeigen ---------------------------------------------------

def test_neu_speichert_die_frist_in_utc(client, todo):
    token = todo["tokens"]["TestAdmin"]
    client.post(f"/a/todo/{token}/neu", data={"inhalt": "Muell raus", "ziel_typ": "person",
                                              "zugewiesen_an": "", "faellig": "2026-09-08T16:00"})
    client.post(f"/a/todo/{token}/neu", data={"inhalt": "Ohne Frist", "ziel_typ": "person",
                                              "zugewiesen_an": "", "faellig": ""})
    zeilen = {z["inhalt"]: z["faellig"] for z in todo["v"].execute("SELECT inhalt, faellig FROM todos")}
    assert zeilen == {"Muell raus": "2026-09-08 14:00:00", "Ohne Frist": None}


def test_bearbeiten_setzt_und_loescht_die_frist(client, todo):
    token = todo["tokens"]["TestAdmin"]
    v = todo["v"]
    admin = todo["familie"]["TestAdmin"]["id"]
    tid = v.execute("INSERT INTO todos(inhalt, erstellt_von, status) VALUES('Rasen', ?, 'offen') RETURNING id",
                    (admin,)).fetchone()["id"]
    v.commit()
    client.post(f"/a/todo/{token}/bearbeiten/{tid}", data={"inhalt": "Rasen", "ziel_typ": "person",
                                                            "zugewiesen_an": "", "faellig": "2026-12-08T16:00"})
    assert v.execute("SELECT faellig FROM todos WHERE id=?", (tid,)).fetchone()["faellig"] == "2026-12-08 15:00:00"
    client.post(f"/a/todo/{token}/bearbeiten/{tid}", data={"inhalt": "Rasen", "ziel_typ": "person",
                                                            "zugewiesen_an": "", "faellig": ""})
    assert v.execute("SELECT faellig FROM todos WHERE id=?", (tid,)).fetchone()["faellig"] is None


def _anlegen(todo, inhalt, faellig, erledigt=0, status="offen"):
    admin = todo["familie"]["TestAdmin"]["id"]
    todo["v"].execute(
        "INSERT INTO todos(inhalt, erstellt_von, status, erledigt, faellig) VALUES(?,?,?,?,?)",
        (inhalt, admin, status, erledigt, faellig))
    todo["v"].commit()


def test_liste_und_brett_zeigen_die_frist_in_ortszeit(client, todo):
    _anlegen(todo, "Fern", "2030-06-10 14:00:00")         # 16:00 Sommerzeit
    _anlegen(todo, "Vorbei", "2020-01-10 15:00:00")       # 16:00 Winterzeit, laengst vorbei
    _anlegen(todo, "Erledigt", "2020-01-10 15:00:00", erledigt=1, status="erledigt")
    token = todo["tokens"]["TestAdmin"]
    liste = client.get(f"/a/todo/{token}/?erledigt=alle").get_data(as_text=True)
    assert "📅 Mo 10.06.2030, 16:00" in liste
    assert "📅 Fr 10.01.2020, 16:00 · überfällig" in liste
    assert 'class="chip faellig ueberfaellig"' in liste
    assert liste.count("überfällig") == 1, "Erledigtes ist nicht ueberfaellig"
    brett = client.get(f"/a/todo/{token}/kanban?erledigt=alle").get_data(as_text=True)
    assert "Mo 10.06.2030, 16:00" in brett
    assert 'class="karte-faellig ueberfaellig"' in brett


def test_bearbeiten_panel_ist_vorbelegt(client, todo):
    _anlegen(todo, "Vorbelegt", "2030-06-10 14:00:00")
    seite = client.get(f"/a/todo/{todo['tokens']['TestAdmin']}/").get_data(as_text=True)
    assert 'name="faellig" value="2030-06-10T16:00"' in seite
    # Das Neu-Formular ist leer vorbelegt.
    assert 'name="faellig" value=""' in seite


def test_todos_neu_schnittstelle_nimmt_die_frist(app, modul, todo):
    with app.app_context():
        modul.todos_neu("Programmatisch", todo["familie"]["TestAdmin"]["id"], faellig="2026-09-08 14:00:00")
        modul.todos_neu("Ohne", todo["familie"]["TestAdmin"]["id"])
    zeilen = {z["inhalt"]: z["faellig"] for z in todo["v"].execute("SELECT inhalt, faellig FROM todos")}
    assert zeilen == {"Programmatisch": "2026-09-08 14:00:00", "Ohne": None}
