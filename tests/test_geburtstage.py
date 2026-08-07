"""Wunsch #145: Geburtstage.

Schwerpunkt der Tests ist die Datumslogik, nicht die Oberfläche: Jahreswechsel
und der 29. Februar sind die Stellen, an denen so etwas falsch wird - und ein
Fehler dort zeigt sich erst Monate später am falschen Tag.

Dazu die Auswahl der fälligen Erinnerungen (`faellige_erinnerungen`), weil
"schickt zu oft" und "schickt gar nicht" beide unangenehm sind: Das eine nervt
täglich, das andere merkt niemand.
"""
import importlib
from datetime import date

import pytest


@pytest.fixture()
def modul(app):
    return importlib.import_module("teile.23_geburtstage")


@pytest.fixture()
def gb_token(app, db):
    """Grant für alle Testnutzer (die Familie in conftest bekommt gezielte
    Listen, nicht die Auto-Grants)."""
    from teile.kern import token_lookup, new_token
    verbindung = db["verbindung"]
    with app.app_context():
        app_id = verbindung.execute(
            "SELECT id FROM apps WHERE slug='geburtstage'").fetchone()["id"]
        tokens = {}
        for name, daten in db["familie"].items():
            klartext = new_token()
            verbindung.execute(
                "INSERT INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                (daten["id"], app_id, token_lookup(klartext)))
            tokens[name] = klartext
        verbindung.commit()
    return tokens


# --- Datumslogik -----------------------------------------------------------

def test_heute_ist_null_tage(modul):
    heute = date(2026, 5, 17)
    assert modul._tage_bis(17, 5, heute) == 0


def test_morgen_ist_ein_tag(modul):
    assert modul._tage_bis(18, 5, date(2026, 5, 17)) == 1


def test_ueber_den_jahreswechsel(modul):
    """Am 30.12. ist der 2.1. in drei Tagen - nicht in minus 362."""
    assert modul._tage_bis(2, 1, date(2026, 12, 30)) == 3


def test_gestern_ist_erst_naechstes_jahr(modul):
    """Ein gerade vergangener Geburtstag zählt aufs Folgejahr, sonst stünde
    er dauerhaft mit einer negativen Zahl oben in der Liste."""
    heute = date(2026, 5, 17)
    assert modul._tage_bis(16, 5, heute) == 364


def test_29_februar_im_schaltjahr(modul):
    assert modul._tage_bis(29, 2, date(2028, 2, 29)) == 0


def test_29_februar_im_normaljahr_wird_zum_1_maerz(modul):
    """Den 29.2. gibt es 2026 nicht. Ohne Sonderbehandlung fiele der
    Geburtstag in drei von vier Jahren komplett aus."""
    assert modul._tage_bis(29, 2, date(2026, 2, 28)) == 1   # -> 1. März
    assert modul._tage_bis(29, 2, date(2026, 3, 1)) == 0


def test_alter_wird_richtig_gerechnet(modul):
    """Am nächsten Geburtstag, nicht heute - deshalb kann es das Folgejahr sein."""
    assert modul._alter_am_geburtstag(1980, 17, 5, date(2026, 5, 17)) == 46
    assert modul._alter_am_geburtstag(1980, 16, 5, date(2026, 5, 17)) == 47


def test_ohne_geburtsjahr_kein_alter(modul):
    assert modul._alter_am_geburtstag(None, 1, 1, date(2026, 5, 17)) is None


# --- Eintragen und Sichtbarkeit --------------------------------------------

def _anlegen(client, token, name="Oma Erika", tag=17, monat=5, jahr="", notiz=""):
    return client.post(f"/a/geburtstage/{token}/neu", data={
        "name": name, "tag": tag, "monat": monat, "jahr": jahr, "notiz": notiz})


def test_eintrag_ist_fuer_alle_sichtbar(client, gb_token):
    _anlegen(client, gb_token["TestAdmin"], name="Onkel Otto")
    seite = client.get(f"/a/geburtstage/{gb_token['TestKind']}/").get_data(as_text=True)
    assert "Onkel Otto" in seite


def test_unsinniges_datum_wird_abgelehnt(client, gb_token, db):
    _anlegen(client, gb_token["TestAdmin"], name="Kaputt", tag=45, monat=13)
    anzahl = db["verbindung"].execute(
        "SELECT COUNT(*) c FROM geburtstage WHERE name='Kaputt'").fetchone()["c"]
    assert anzahl == 0


def test_unsinniges_jahr_wird_verworfen_der_eintrag_bleibt(client, gb_token, db):
    """Ein Tippfehler im Jahr darf nicht den ganzen Eintrag kosten - das Jahr
    ist ohnehin freiwillig."""
    _anlegen(client, gb_token["TestAdmin"], name="Jahrfehler", jahr=3026)
    zeile = db["verbindung"].execute(
        "SELECT jahr FROM geburtstage WHERE name='Jahrfehler'").fetchone()
    assert zeile is not None
    assert zeile["jahr"] is None


def test_ausblenden_gilt_nur_fuer_einen_selbst(client, gb_token, db, admin):
    """Der Kern des Wunsches: jeder blendet für sich aus."""
    _anlegen(client, gb_token["TestAdmin"], name="Nur-Fuer-Mich-Weg")
    gid = db["verbindung"].execute(
        "SELECT id FROM geburtstage WHERE name='Nur-Fuer-Mich-Weg'").fetchone()["id"]
    client.post(f"/a/geburtstage/{gb_token['TestAdmin']}/{gid}/einstellung",
                data={"ausgeblendet": "1"})

    beim_admin = client.get(f"/a/geburtstage/{gb_token['TestAdmin']}/").get_data(as_text=True)
    beim_kind  = client.get(f"/a/geburtstage/{gb_token['TestKind']}/").get_data(as_text=True)
    assert "Für mich ausgeblendet" in beim_admin
    assert "Für mich ausgeblendet" not in beim_kind
    assert "Nur-Fuer-Mich-Weg" in beim_kind      # beim Kind ganz normal sichtbar


def test_loeschen_nur_durch_urheber_oder_eltern(client, gb_token, db, kind):
    """Löschen trifft alle - ein Kind darf fremde Einträge nicht entfernen."""
    _anlegen(client, gb_token["TestAdmin"], name="Fremd")
    gid = db["verbindung"].execute(
        "SELECT id FROM geburtstage WHERE name='Fremd'").fetchone()["id"]
    antwort = client.post(f"/a/geburtstage/{gb_token['TestKind']}/{gid}/loeschen")
    assert antwort.status_code == 403
    assert db["verbindung"].execute(
        "SELECT COUNT(*) c FROM geburtstage WHERE id=?", (gid,)).fetchone()["c"] == 1


# --- Erinnerungen ----------------------------------------------------------

def _mit_erinnerung(db, user_id, name, tag, monat, erinnerung=0, vorlauf=None):
    v = db["verbindung"]
    gid = v.execute(
        "INSERT INTO geburtstage(name, tag, monat, erstellt_von) VALUES(?,?,?,?) RETURNING id",
        (name, tag, monat, user_id)).fetchone()["id"]
    v.execute("INSERT INTO geburtstag_einstellungen"
              "(user_id, geburtstag_id, erinnerung, vorlauf_tage) VALUES(?,?,?,?)",
              (user_id, gid, erinnerung, vorlauf))
    v.commit()
    return gid


def test_erinnerung_am_tag_wird_faellig(app, modul, db, admin):
    heute = date(2026, 5, 17)
    _mit_erinnerung(db, admin["id"], "Heute", 17, 5, erinnerung=1)
    with app.app_context():
        from teile.kern import get_db
        faellig = modul.faellige_erinnerungen(db["verbindung"], heute)
    assert [f["art"] for f in faellig] == ["tag"]


def test_vorlauf_wird_am_richtigen_tag_faellig(app, modul, db, admin):
    """Sieben Tage vorher, nicht am Tag selbst - das ist der ganze Sinn der
    getrennten Einstellung (nach Geschenkwünschen fragen)."""
    _mit_erinnerung(db, admin["id"], "In7Tagen", 24, 5, vorlauf=7)
    with app.app_context():
        am_17 = modul.faellige_erinnerungen(db["verbindung"], date(2026, 5, 17))
        am_18 = modul.faellige_erinnerungen(db["verbindung"], date(2026, 5, 18))
    assert [f["art"] for f in am_17] == ["vorlauf"]
    assert am_18 == []


def test_beides_gleichzeitig_moeglich(app, modul, db, admin):
    """Der Wunsch verlangt ausdrücklich, dass beides unabhängig einstellbar
    ist - hier mit Vorlauf 0 Tage wäre es dieselbe Meldung doppelt, deshalb
    prüfen wir einen echten Vorlauf."""
    _mit_erinnerung(db, admin["id"], "Doppelt", 17, 5, erinnerung=1, vorlauf=3)
    with app.app_context():
        am_tag = modul.faellige_erinnerungen(db["verbindung"], date(2026, 5, 17))
        vorher = modul.faellige_erinnerungen(db["verbindung"], date(2026, 5, 14))
    assert [f["art"] for f in am_tag] == ["tag"]
    assert [f["art"] for f in vorher] == ["vorlauf"]


def test_ohne_einstellung_keine_erinnerung(app, modul, db, admin):
    _mit_erinnerung(db, admin["id"], "Stumm", 17, 5)     # weder noch
    with app.app_context():
        assert modul.faellige_erinnerungen(db["verbindung"], date(2026, 5, 17)) == []


def test_bereits_verschicktes_wird_nicht_wiederholt(app, modul, db, admin):
    """Sonst käme nach jedem Container-Neustart dieselbe Erinnerung erneut."""
    gid = _mit_erinnerung(db, admin["id"], "Einmal", 17, 5, erinnerung=1)
    db["verbindung"].execute(
        "INSERT INTO geburtstag_gesendet(user_id, geburtstag_id, art, datum) "
        "VALUES(?,?,?,?)", (admin["id"], gid, "tag", "2026-05-17"))
    db["verbindung"].commit()
    with app.app_context():
        assert modul.faellige_erinnerungen(db["verbindung"], date(2026, 5, 17)) == []


def test_erinnerung_gilt_nur_fuer_den_der_sie_gesetzt_hat(app, modul, db, admin, kind):
    """Zwei Nutzer, ein Geburtstag: Nur wer die Erinnerung gesetzt hat,
    bekommt sie."""
    v = db["verbindung"]
    gid = v.execute(
        "INSERT INTO geburtstage(name, tag, monat, erstellt_von) VALUES('Gemeinsam',17,5,?) "
        "RETURNING id", (admin["id"],)).fetchone()["id"]
    v.execute("INSERT INTO geburtstag_einstellungen"
              "(user_id, geburtstag_id, erinnerung) VALUES(?,?,1)", (kind["id"], gid))
    v.commit()
    with app.app_context():
        faellig = modul.faellige_erinnerungen(v, date(2026, 5, 17))
    assert [f["user_id"] for f in faellig] == [kind["id"]]
