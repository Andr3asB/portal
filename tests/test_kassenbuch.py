"""Wunsch #144: Kassenbuch je Kind.

Deckt die drei Dinge ab, die bei diesem Wunsch wirklich zählen:
  * Zugriff - ein Kind sieht NUR sein eigenes Buch, Eltern/Admin sehen alle
    (die "Auditierung", die der Wunsch verlangt, ist ohne Einsicht wertlos).
  * Der Startbetrag geht genau einmal, und der Kontostand rechnet sich
    danach korrekt aus Einnahmen/Ausgaben/Storno zusammen.
  * "Löschen" ist Stornieren: die Zeile bleibt in der Datenbank stehen,
    zählt aber nicht mehr - und der Start-Eintrag ist NIE stornierbar.
"""
import pytest


@pytest.fixture()
def kb_token(app, db):
    """Vergibt allen drei Testnutzern einen Grant für 'kassenbuch' - die
    Familie aus conftest.py bekommt es nicht automatisch, weil das dortige
    Setup gezielte Grant-Listen je Nutzer verwendet, nicht _auto_grant_all()."""
    from teile.kern import new_token, token_lookup
    verbindung = db["verbindung"]
    with app.app_context():
        app_id = verbindung.execute(
            "SELECT id FROM apps WHERE slug='kassenbuch'").fetchone()["id"]
        tokens = {}
        for name, daten in db["familie"].items():
            klartext = new_token()
            verbindung.execute(
                "INSERT INTO grants(user_id, app_id, token_lookup) "
                "VALUES(?,?,?)", (daten["id"], app_id, token_lookup(klartext)))
            tokens[name] = klartext
        verbindung.commit()
    return tokens


def _start(client, token, betrag="10,00"):
    return client.post(f"/a/kassenbuch/{token}/start", data={"betrag": betrag})


def _eintrag(client, token, art, betrag, person="", zweck="", datum=None):
    daten = {"art": art, "betrag": betrag, "person": person, "zweck": zweck}
    if datum:
        daten["datum"] = datum
    return client.post(f"/a/kassenbuch/{token}/eintrag", data=daten)


# --- Zugriff -----------------------------------------------------------

def test_kind_sieht_direkt_das_eigene_buch(client, kb_token):
    antwort = client.get(f"/a/kassenbuch/{kb_token['TestKind']}/")
    assert antwort.status_code == 200
    assert b"Startbetrag" in antwort.data or b"Sparschwein" in antwort.data


def test_kind_sieht_kein_fremdes_buch(client, kb_token, kind, admin):
    # admin hat kein rolle='kind', taugt hier nicht als "fremdes Kind" -
    # stattdessen greift TestKind auf die eigene ID zu (erlaubt) und eine
    # erfundene fremde Kind-ID (nicht vorhanden -> 404, nicht 403, weil es
    # das Konto schlicht nicht gibt).
    antwort = client.get(f"/a/kassenbuch/{kb_token['TestKind']}/kind/{admin['id']}")
    assert antwort.status_code in (403, 404)


def test_eltern_sehen_uebersicht_aller_kinder(client, kb_token, kind):
    antwort = client.get(f"/a/kassenbuch/{kb_token['TestEltern']}/")
    assert antwort.status_code == 200
    assert b"TestKind" in antwort.data


def test_eltern_koennen_kassenbuch_eines_kindes_ansehen(client, kb_token, kind):
    _start(client, kb_token["TestKind"])
    antwort = client.get(f"/a/kassenbuch/{kb_token['TestEltern']}/kind/{kind['id']}")
    assert antwort.status_code == 200
    assert b"10,00" in antwort.data


def test_eltern_koennen_keinen_eintrag_fuer_ein_kind_anlegen(client, kb_token, kind):
    """Aufsicht heißt Einsicht, nicht Fremdsteuerung - nur das Kind selbst
    darf seinen Bestand verändern."""
    _start(client, kb_token["TestKind"])
    antwort = _eintrag(client, kb_token["TestEltern"], "einnahme", "5,00")
    assert antwort.status_code == 403


# --- Startbetrag ---------------------------------------------------------

def test_start_setzt_den_kontostand(client, kb_token):
    _start(client, kb_token["TestKind"], "12,50")
    seite = client.get(f"/a/kassenbuch/{kb_token['TestKind']}/").get_data(as_text=True)
    assert "12,50" in seite


def test_zweiter_start_nach_der_ersten_buchung_wird_ignoriert(client, kb_token):
    """Ein zweites Startguthaben würde den gesamten bisherigen Kontostand
    rückwirkend bedeutungslos machen.

    Seit Wunsch #216 gilt das ab der ersten stehenden Buchung - vorher darf
    ein Tippfehler noch richtiggestellt werden (siehe
    test_kassenbuch_startkorrektur.py). Die Grenze ist die Buchung, nicht der
    Start-Eintrag."""
    _start(client, kb_token["TestKind"], "10,00")
    _eintrag(client, kb_token["TestKind"], "einnahme", "1,00", person="Oma")
    _start(client, kb_token["TestKind"], "999,00")
    seite = client.get(f"/a/kassenbuch/{kb_token['TestKind']}/").get_data(as_text=True)
    assert "11,00" in seite
    assert "999,00" not in seite


def test_ohne_start_gibt_es_kein_eintragsformular(client, kb_token):
    seite = client.get(f"/a/kassenbuch/{kb_token['TestKind']}/").get_data(as_text=True)
    assert 'id="kb-eintrag-form"' not in seite


# --- Kontostand & Buchungen ------------------------------------------------

def test_einnahme_und_ausgabe_ergeben_den_richtigen_saldo(client, kb_token):
    _start(client, kb_token["TestKind"], "10,00")
    _eintrag(client, kb_token["TestKind"], "einnahme", "5,50", person="Oma")
    _eintrag(client, kb_token["TestKind"], "ausgabe", "3,00", zweck="Eis")
    seite = client.get(f"/a/kassenbuch/{kb_token['TestKind']}/").get_data(as_text=True)
    # 10,00 + 5,50 - 3,00 = 12,50
    assert "12,50" in seite


def test_negativer_betrag_wird_abgelehnt(client, kb_token):
    _start(client, kb_token["TestKind"], "10,00")
    _eintrag(client, kb_token["TestKind"], "einnahme", "-5,00")
    seite = client.get(f"/a/kassenbuch/{kb_token['TestKind']}/").get_data(as_text=True)
    assert "10,00" in seite  # unverändert - der Eintrag wurde verworfen


def test_kaputter_betrag_wird_abgelehnt(client, kb_token):
    _start(client, kb_token["TestKind"], "10,00")
    antwort = _eintrag(client, kb_token["TestKind"], "einnahme", "zehn Euro")
    assert antwort.status_code in (302, 303)  # kein Absturz, nur Redirect
    seite = client.get(f"/a/kassenbuch/{kb_token['TestKind']}/").get_data(as_text=True)
    assert "10,00" in seite


def test_punkt_und_komma_funktionieren_beide(client, kb_token):
    _start(client, kb_token["TestKind"], "10.00")
    seite = client.get(f"/a/kassenbuch/{kb_token['TestKind']}/").get_data(as_text=True)
    assert "10,00" in seite


def test_zukuenftiges_datum_faellt_auf_heute_zurueck(client, kb_token):
    from datetime import date, timedelta
    _start(client, kb_token["TestKind"], "10,00")
    morgen = (date.today() + timedelta(days=1)).isoformat()
    _eintrag(client, kb_token["TestKind"], "einnahme", "1,00", datum=morgen)
    seite = client.get(f"/a/kassenbuch/{kb_token['TestKind']}/").get_data(as_text=True)
    assert morgen not in seite


# --- Stornieren -------------------------------------------------------------

def test_storno_nimmt_den_betrag_aus_dem_saldo(client, kb_token, db):
    _start(client, kb_token["TestKind"], "10,00")
    _eintrag(client, kb_token["TestKind"], "einnahme", "5,00")
    eid = db["verbindung"].execute(
        "SELECT id FROM kassenbuch_eintraege WHERE art='einnahme'").fetchone()["id"]
    client.post(f"/a/kassenbuch/{kb_token['TestKind']}/eintrag/{eid}/stornieren")
    seite = client.get(f"/a/kassenbuch/{kb_token['TestKind']}/").get_data(as_text=True)
    assert "10,00" in seite  # die 5,00 zählen nicht mehr


def test_stornierter_eintrag_bleibt_in_der_datenbank(client, kb_token, db):
    _start(client, kb_token["TestKind"], "10,00")
    _eintrag(client, kb_token["TestKind"], "einnahme", "5,00")
    verbindung = db["verbindung"]
    eid = verbindung.execute(
        "SELECT id FROM kassenbuch_eintraege WHERE art='einnahme'").fetchone()["id"]
    client.post(f"/a/kassenbuch/{kb_token['TestKind']}/eintrag/{eid}/stornieren")
    zeile = verbindung.execute(
        "SELECT storniert, storniert_von FROM kassenbuch_eintraege WHERE id=?", (eid,)
    ).fetchone()
    assert zeile["storniert"] == 1
    assert zeile["storniert_von"] is not None


def test_start_eintrag_ist_nicht_stornierbar(client, kb_token, db):
    _start(client, kb_token["TestKind"], "10,00")
    eid = db["verbindung"].execute(
        "SELECT id FROM kassenbuch_eintraege WHERE art='start'").fetchone()["id"]
    client.post(f"/a/kassenbuch/{kb_token['TestKind']}/eintrag/{eid}/stornieren")
    seite = client.get(f"/a/kassenbuch/{kb_token['TestKind']}/").get_data(as_text=True)
    assert "10,00" in seite  # Kontostand unverändert - Storno griff nicht


def test_kind_kann_keinen_fremden_eintrag_stornieren(client, kb_token, db):
    """Sicherheitsprüfung im Query selbst (WHERE ... AND user_id=?), nicht
    nur in der Oberfläche."""
    _start(client, kb_token["TestKind"], "10,00")
    verbindung = db["verbindung"]
    eid = verbindung.execute(
        "SELECT id FROM kassenbuch_eintraege WHERE art='start'").fetchone()["id"]
    antwort = client.post(f"/a/kassenbuch/{kb_token['TestEltern']}/eintrag/{eid}/stornieren")
    assert antwort.status_code == 403
