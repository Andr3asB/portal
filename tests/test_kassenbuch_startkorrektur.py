"""Wunsch #216: Der Startbetrag darf einmal richtiggestellt werden – aber nur,
solange das Kassenbuch faktisch noch nicht in Benutzung ist.

Entstanden aus #202: Friederike hatte 57,00 € eingetragen, 30 Sekunden später
eine Ausgabe über exakt 57,00 € gebucht, um ihn auszugleichen, die wieder
storniert – und dann um Hilfe gebeten. Die App hatte für diesen Fall keinen
Weg; es brauchte einen Erwachsenen mit Datenbankzugriff.

Die beiden Dinge, die dabei nicht kaputtgehen dürfen:

* **Die Unveränderlichkeits-Zusage.** Es wird kein Betrag überschrieben. Der
  alte Start-Eintrag wird storniert, ein neuer angelegt – die Richtigstellung
  steht damit vollständig im Prüfprotokoll, ohne dass es dafür eine neue
  Ereignisart bräuchte (#153/#156).
* **Der Nullpunkt.** Ab der ersten stehenden Buchung ist Schluss, sonst liesse
  sich jeder spätere Kontostand rückwirkend verschieben.
"""
import pytest
from teile.kern import new_token, token_lookup


@pytest.fixture()
def kb(app, db):
    v = db["verbindung"]
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='kassenbuch'").fetchone()["id"]
        tokens = {}
        for name, daten in db["familie"].items():
            klartext = new_token()
            v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) "
                      "VALUES(?,?,?)", (daten["id"], app_id, token_lookup(klartext)))
            tokens[name] = klartext
        v.commit()
    return {"tokens": tokens, "kind": db["familie"]["TestKind"]["id"], "v": v}


def _start(client, token, betrag):
    return client.post(f"/a/kassenbuch/{token}/start", data={"betrag": betrag})


def _eintrag(client, token, art, betrag):
    return client.post(f"/a/kassenbuch/{token}/eintrag",
                       data={"art": art, "betrag": betrag, "person": "", "zweck": ""})


def _storniere_letzten(client, token, kb, art="ausgabe"):
    eid = kb["v"].execute(
        "SELECT id FROM kassenbuch_eintraege WHERE user_id=? AND art=? "
        "ORDER BY id DESC LIMIT 1", (kb["kind"], art)).fetchone()["id"]
    return client.post(f"/a/kassenbuch/{token}/eintrag/{eid}/stornieren")


def _zeilen(kb):
    return kb["v"].execute(
        "SELECT * FROM kassenbuch_eintraege WHERE user_id=? ORDER BY id",
        (kb["kind"],)).fetchall()


def _seite(client, token):
    return client.get(f"/a/kassenbuch/{token}/").get_data(as_text=True)


# --- Das Fenster ist offen --------------------------------------------------

def test_frisch_eingerichtet_laesst_sich_richtigstellen(client, kb):
    t = kb["tokens"]["TestKind"]
    _start(client, t, "57,00")
    _start(client, t, "7,00")
    assert "7,00" in _seite(client, t)
    assert "57,00" not in _seite(client, t).split("Startbetrag stimmt nicht")[0]


def test_der_alte_betrag_wird_storniert_statt_ueberschrieben(client, kb):
    """Der Kern der Zusage: nichts wird ueberschrieben."""
    t = kb["tokens"]["TestKind"]
    _start(client, t, "57,00")
    _start(client, t, "7,00")

    zeilen = _zeilen(kb)
    assert len(zeilen) == 2, "Es müssen ZWEI Zeilen dastehen, nicht eine geänderte"
    alt, neu = zeilen
    assert alt["betrag_cent"] == 5700 and alt["storniert"] == 1
    assert alt["storniert_von"] == kb["kind"] and alt["storniert_am"]
    assert neu["betrag_cent"] == 700 and neu["storniert"] == 0
    assert neu["art"] == "start"


def test_die_korrektur_steht_im_pruefprotokoll(client, kb):
    """Ohne das wäre die Richtigstellung genau die Lücke, gegen die #156
    angetreten ist: eine Änderung, die man dem Buch nicht ansieht."""
    t = kb["tokens"]["TestKind"]
    _start(client, t, "57,00")
    _start(client, t, "7,00")
    seite = client.get(
        f"/a/kassenbuch/{kb['tokens']['TestEltern']}/kind/{kb['kind']}/pruefung"
    ).get_data(as_text=True)
    assert "57,00" in seite, "Der alte Betrag fehlt im Protokoll"
    assert "7,00" in seite
    assert "storniert" in seite.lower()


def test_stornierte_buchung_haelt_das_fenster_offen(client, kb):
    """Genau der Fall aus #202. Eine zurückgenommene Buchung verändert den
    Kontostand nicht - sie ist ein Versuch, keine Historie."""
    t = kb["tokens"]["TestKind"]
    _start(client, t, "57,00")
    _eintrag(client, t, "ausgabe", "57,00")
    _storniere_letzten(client, t, kb)

    _start(client, t, "7,00")
    aktive = [z for z in _zeilen(kb) if z["art"] == "start" and not z["storniert"]]
    assert len(aktive) == 1 and aktive[0]["betrag_cent"] == 700


def test_das_angebot_steht_auf_der_seite(client, kb):
    t = kb["tokens"]["TestKind"]
    _start(client, t, "57,00")
    assert "Startbetrag stimmt nicht" in _seite(client, t)


# --- Das Fenster ist zu -----------------------------------------------------

def test_nach_einer_buchung_ist_schluss(client, kb):
    t = kb["tokens"]["TestKind"]
    _start(client, t, "10,00")
    _eintrag(client, t, "einnahme", "5,00")
    _start(client, t, "999,00")

    aktive = [z for z in _zeilen(kb) if z["art"] == "start" and not z["storniert"]]
    assert len(aktive) == 1 and aktive[0]["betrag_cent"] == 1000
    assert "999,00" not in _seite(client, t)


def test_das_angebot_verschwindet_nach_der_ersten_buchung(client, kb):
    t = kb["tokens"]["TestKind"]
    _start(client, t, "10,00")
    _eintrag(client, t, "einnahme", "5,00")
    assert "Startbetrag stimmt nicht" not in _seite(client, t)


def test_kaputter_betrag_laesst_den_alten_stehen(client, kb):
    """Sonst wäre ein Tippfehler in der Korrektur schlimmer als der
    ursprüngliche: der alte Start weg, kein neuer da."""
    t = kb["tokens"]["TestKind"]
    _start(client, t, "10,00")
    _start(client, t, "sieben Euro")

    aktive = [z for z in _zeilen(kb) if z["art"] == "start" and not z["storniert"]]
    assert len(aktive) == 1 and aktive[0]["betrag_cent"] == 1000


@pytest.mark.parametrize("betrag", ["0", "-5,00", "", "   "])
def test_unsinnige_betraege_aendern_nichts(client, kb, betrag):
    t = kb["tokens"]["TestKind"]
    _start(client, t, "10,00")
    _start(client, t, betrag)
    aktive = [z for z in _zeilen(kb) if z["art"] == "start" and not z["storniert"]]
    assert len(aktive) == 1 and aktive[0]["betrag_cent"] == 1000


# --- Wer darf ---------------------------------------------------------------

def test_eltern_koennen_den_start_nicht_richtigstellen(client, kb):
    """Der Startbetrag ist die Angabe des Kindes über sein eigenes
    Sparschwein - Aufsicht heisst nachsehen, nicht eintragen."""
    _start(client, kb["tokens"]["TestKind"], "10,00")
    antwort = _start(client, kb["tokens"]["TestEltern"], "999,00")
    assert antwort.status_code == 403
    aktive = [z for z in _zeilen(kb) if z["art"] == "start" and not z["storniert"]]
    assert aktive[0]["betrag_cent"] == 1000


def test_eltern_sehen_das_angebot_nicht(client, kb):
    _start(client, kb["tokens"]["TestKind"], "10,00")
    seite = client.get(
        f"/a/kassenbuch/{kb['tokens']['TestEltern']}/kind/{kb['kind']}"
    ).get_data(as_text=True)
    assert "Startbetrag stimmt nicht" not in seite
