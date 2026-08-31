"""Wunsch #188: Der Tokenverbrauch einer Umsetzung steht am Wunsch.

Die Rückfrage dazu war nötig, weil der Wunsch von „zusätzlich erhobenen
Daten" sprach, die es nicht gab: Das Portal misst je Wunsch nur die
KI-Überschrift (160–320 Tokens), und die war offensichtlich nicht gemeint.
Andis Entscheidung am Wunsch: *„dann sollte nur der Tokenverbrauch nach der
Umsetzung dokumentiert sein"*.

Daraus folgen die beiden Eigenschaften, die hier geprüft werden:

* **Nach der Umsetzung, nicht vorher geschätzt.** Der Wert kommt beim
  Abhaken mit, es gibt keinen Platz für eine Vorab-Schätzung.
* **NULL heisst „nicht erfasst".** Bei allen ~190 Wünschen von vor diesem
  Punkt gibt es keine Zahl, und die Zeile bleibt dann weg. Eine 0 wäre eine
  Behauptung statt eines fehlenden Werts – und 190 Karten mit
  „Tokenverbrauch: 0" wären schlicht falsch.
"""
import importlib
import sys

import pytest


@pytest.fixture()
def manage(app, monkeypatch):
    monkeypatch.setenv("DB_PATH", app.config["DB_PATH"])
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve()
                           .parents[1] / "src"))
    modul = importlib.import_module("manage")
    importlib.reload(modul)
    return modul


@pytest.fixture()
def werkstatt_token(app, db):
    from teile.kern import new_token, token_lookup
    v = db["verbindung"]
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='werkstatt'").fetchone()["id"]
        klartext = new_token()
        v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) "
                  "VALUES(?,?,?)",
                  (db["familie"]["TestAdmin"]["id"], app_id, token_lookup(klartext)))
        v.commit()
    return klartext


def _wunsch(v, text="Ein Wunsch"):
    wid = v.execute("INSERT INTO wuensche(text) VALUES(?) RETURNING id",
                    (text,)).fetchone()["id"]
    v.commit()
    return wid


def _tokens(v, wid):
    return v.execute("SELECT tokens FROM wuensche WHERE id=?", (wid,)).fetchone()[0]


# --- Eintragen --------------------------------------------------------------

def test_tokenverbrauch_wird_beim_abhaken_gespeichert(manage, db):
    v = db["verbindung"]
    wid = _wunsch(v)
    manage.cmd_wunsch_erledigt([str(wid), "So wurde es gemacht", "35000"])
    assert _tokens(v, wid) == 35000
    assert v.execute("SELECT erledigt FROM wuensche WHERE id=?", (wid,)).fetchone()[0] == 1


def test_ohne_angabe_bleibt_die_spalte_leer(manage, db):
    """NULL heisst 'nicht erfasst'. Eine 0 wäre eine Behauptung."""
    v = db["verbindung"]
    wid = _wunsch(v)
    manage.cmd_wunsch_erledigt([str(wid), "Umsetzung ohne Zahl"])
    assert _tokens(v, wid) is None


def test_punkte_als_tausendertrennung_sind_erlaubt(manage, db):
    """„35.000" ist die Schreibweise, in der die Zahl im Bericht steht -
    daran soll der Aufruf nicht scheitern."""
    v = db["verbindung"]
    wid = _wunsch(v)
    manage.cmd_wunsch_erledigt([str(wid), "Umsetzung", "35.000"])
    assert _tokens(v, wid) == 35000


def test_unsinn_bricht_ab_statt_still_zu_verschwinden(manage, db):
    """Ein Tippfehler darf nicht als 'nicht erfasst' durchgehen - sonst
    fehlt die Zahl und niemand weiss, warum."""
    v = db["verbindung"]
    wid = _wunsch(v)
    with pytest.raises(SystemExit):
        manage.cmd_wunsch_erledigt([str(wid), "Umsetzung", "vielleicht 35k"])
    with pytest.raises(SystemExit):
        manage.cmd_wunsch_erledigt([str(wid), "Umsetzung", "-100"])


def test_erneutes_abhaken_ohne_zahl_loescht_die_alte_nicht(manage, db):
    """COALESCE, nicht Überschreiben: Wer den Wunsch später noch einmal
    abhakt (z. B. um die Umsetzung zu ergänzen), soll die Zahl nicht
    verlieren."""
    v = db["verbindung"]
    wid = _wunsch(v)
    manage.cmd_wunsch_erledigt([str(wid), "Erst so", "12000"])
    manage.cmd_wunsch_erledigt([str(wid), "Dann so"])
    assert _tokens(v, wid) == 12000


def test_null_ist_ein_erlaubter_wert(manage, db):
    """0 soll man eintragen KOENNEN (etwa bei einer reinen Doku-Aenderung) -
    nur eben nicht als Ersatz fuer 'nicht erfasst'."""
    v = db["verbindung"]
    wid = _wunsch(v)
    manage.cmd_wunsch_erledigt([str(wid), "Nichts verbraucht", "0"])
    assert _tokens(v, wid) == 0


# --- Anzeigen ---------------------------------------------------------------

def test_die_zahl_steht_in_den_details(client, db, werkstatt_token):
    v = db["verbindung"]
    v.execute(
        "INSERT INTO wuensche(text, erledigt, tokens) VALUES('X', 1, 35000)")
    v.commit()
    text = client.get(f"/a/werkstatt/{werkstatt_token}/").get_data(as_text=True)
    assert "Tokenverbrauch" in text
    assert "35.000" in text, "deutsche Tausenderpunkte"


def test_ohne_zahl_keine_zeile(client, db, werkstatt_token):
    """Sonst stuenden an ~190 alten Wuenschen leere Zeilen."""
    v = db["verbindung"]
    v.execute("INSERT INTO wuensche(text, erledigt) VALUES('Alter Wunsch', 1)")
    v.commit()
    text = client.get(f"/a/werkstatt/{werkstatt_token}/").get_data(as_text=True)
    assert "Tokenverbrauch" not in text


def test_null_wird_angezeigt_und_nicht_verschluckt(client, db, werkstatt_token):
    """0 ist eine erfasste Zahl - `if w.tokens` statt `is not none` haette sie
    wie 'nicht erfasst' behandelt."""
    v = db["verbindung"]
    v.execute("INSERT INTO wuensche(text, erledigt, tokens) VALUES('Doku', 1, 0)")
    v.commit()
    text = client.get(f"/a/werkstatt/{werkstatt_token}/").get_data(as_text=True)
    assert "Tokenverbrauch" in text


def test_die_zahl_haengt_am_richtigen_wunsch(client, db, werkstatt_token):
    v = db["verbindung"]
    v.execute("INSERT INTO wuensche(text, erledigt, tokens) VALUES('Mit Zahl', 1, 7000)")
    v.execute("INSERT INTO wuensche(text, erledigt) VALUES('Ohne Zahl', 1)")
    v.commit()
    text = client.get(f"/a/werkstatt/{werkstatt_token}/").get_data(as_text=True)
    assert text.count("Tokenverbrauch") == 1
