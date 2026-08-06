"""Tests der Zugangsauflösung – der Kern, an dem der Umbau für Wunsch #140
ansetzt.

Diese Tests beschreiben den IST-Zustand vor dem Umbau. Sie müssen vor der
ersten Änderung grün sein und nach jeder Stufe wieder grün sein. Wenn eine
Stufe sie rot macht, ist entweder die Stufe falsch oder der Test muss bewusst
angepasst werden – beides soll auffallen.
"""
import pytest


# --- grant(): Token + App-Slug -> Nutzer ------------------------------------

def test_gueltiger_token_loest_auf(app, admin):
    from teile.kern import grant
    with app.test_request_context():
        user = grant(admin["tokens"]["einkauf"], "einkauf")
    assert user is not None
    assert user["name"] == "TestAdmin"
    assert user["id"] == admin["id"]


def test_unbekannter_token_wird_abgelehnt(app, admin):
    from teile.kern import grant
    with app.test_request_context():
        assert grant("gibtesnicht", "einkauf") is None


def test_leerer_token_wird_abgelehnt(app):
    from teile.kern import grant
    with app.test_request_context():
        assert grant("", "einkauf") is None


def test_token_gilt_nur_fuer_seine_app(app, admin):
    """Der Einkaufs-Token darf die Aufgaben-App nicht öffnen."""
    from teile.kern import grant
    with app.test_request_context():
        assert grant(admin["tokens"]["einkauf"], "todo") is None


def test_fremder_token_oeffnet_nicht_die_eigene_app(app, admin, kind):
    """Das Kind hat keinen Aufgaben-Zugang – sein Token darf ihn nicht öffnen."""
    from teile.kern import grant
    with app.test_request_context():
        assert grant(kind["tokens"]["einkauf"], "todo") is None


def test_app_ohne_grant_bleibt_zu(app, kind):
    from teile.kern import grant
    with app.test_request_context():
        assert grant(kind["tokens"]["einkauf"], "admin") is None


# --- Rollen und Rechte ------------------------------------------------------

def test_admin_flag_kommt_durch(app, admin):
    from teile.kern import grant
    with app.test_request_context():
        user = grant(admin["tokens"]["einkauf"], "einkauf")
    assert user["is_admin"] == 1


def test_kind_ist_kein_admin(app, kind):
    from teile.kern import grant
    with app.test_request_context():
        user = grant(kind["tokens"]["einkauf"], "einkauf")
    assert user["is_admin"] == 0
    assert user["rolle"] == "kind"


def test_rolle_eltern_kommt_durch(app, eltern):
    from teile.kern import grant
    with app.test_request_context():
        user = grant(eltern["tokens"]["einkauf"], "einkauf")
    assert user["rolle"] == "eltern"
    assert user["is_admin"] == 0


# --- Navigations-Tokens (der Grund, warum #129 nicht hashen konnte) ---------

def test_home_und_hilfe_token_werden_mitgeliefert(app, admin):
    """base.html baut daraus auf JEDER Seite den Heim-Knopf und den
    Hilfe-Link. Fallen sie weg, ist die Navigation tot."""
    from teile.kern import grant
    with app.test_request_context():
        user = grant(admin["tokens"]["einkauf"], "einkauf")
    assert user["home_token"] == admin["tokens"]["home"]
    assert user["hilfe_token"] == admin["tokens"]["hilfe"]


def test_navigations_tokens_sind_nutzereigen(app, admin, kind):
    """Das Kind darf nicht Andis Heim-Token bekommen."""
    from teile.kern import grant
    with app.test_request_context():
        user = grant(kind["tokens"]["einkauf"], "einkauf")
    assert user["home_token"] == kind["tokens"]["home"]
    assert user["home_token"] != admin["tokens"]["home"]


# --- Verschlüsselung (Wunsch #129) -----------------------------------------

def test_klartext_token_steht_nicht_in_der_datenbank(app, db, admin):
    klartext = admin["tokens"]["einkauf"]
    treffer = db["verbindung"].execute(
        "SELECT COUNT(*) c FROM grants WHERE token_enc = ? OR token_lookup = ?",
        (klartext, klartext),
    ).fetchone()["c"]
    assert treffer == 0


def test_lookup_ist_deterministisch_und_enc_nicht(app):
    """Suchen muss reproduzierbar sein, Verschlüsseln darf es nicht –
    sonst wäre der Geheimtext ein Wiedererkennungsmerkmal."""
    from teile.kern import token_lookup, token_verschluesseln
    with app.test_request_context():
        assert token_lookup("abc") == token_lookup("abc")
        assert token_verschluesseln("abc") != token_verschluesseln("abc")


def test_entschluesseln_kehrt_verschluesseln_um(app):
    from teile.kern import token_verschluesseln, token_entschluesseln
    with app.test_request_context():
        assert token_entschluesseln(token_verschluesseln("hallo-welt")) == "hallo-welt"


def test_kaputter_geheimtext_wirft_nicht(app):
    """Ein einzelner defekter Grant darf nicht die ganze Seite zerlegen."""
    from teile.kern import token_entschluesseln
    with app.test_request_context():
        assert token_entschluesseln("kein-gueltiger-geheimtext") == ""
        assert token_entschluesseln("") == ""


# --- Zugriff über HTTP ------------------------------------------------------

def test_startseite_mit_gueltigem_token(client, admin):
    antwort = client.get(f"/p/{admin['tokens']['home']}")
    assert antwort.status_code == 200
    assert b"TestAdmin" in antwort.data


def test_startseite_mit_ungueltigem_token(client):
    antwort = client.get("/p/gibtesnicht")
    assert antwort.status_code == 403


def test_app_mit_fremdem_token_verweigert(client, kind):
    """Der Kind-Token darf die Verwaltung nicht öffnen."""
    antwort = client.get(f"/a/admin/{kind['tokens']['einkauf']}/")
    assert antwort.status_code == 403


def test_health_braucht_keinen_token(client):
    antwort = client.get("/health")
    assert antwort.status_code == 200
