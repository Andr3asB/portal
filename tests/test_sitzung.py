"""Wunsch #140, Stufe 1: Sitzungs-Cookie wird ausgestellt – und sonst nichts.

Der Kern dieser Stufe ist eine Negativaussage: Das Cookie darf noch KEINE
Wirkung haben. Diese Tests halten beides fest.
"""
import pytest

from teile.kern import token_lookup


@pytest.fixture()
def an(app):
    """Schalter für die Dauer eines Tests einschalten."""
    vorher = app.config.get("SITZUNG_AUSSTELLEN")
    app.config["SITZUNG_AUSSTELLEN"] = "1"
    yield
    app.config["SITZUNG_AUSSTELLEN"] = vorher


def _cookie_kopf(antwort):
    return antwort.headers.get("Set-Cookie", "")


# --- Schalter ---------------------------------------------------------------

def test_ohne_schalter_kein_cookie(client, admin):
    """Standard ist aus. Ohne Schalter darf nichts passieren."""
    antwort = client.get(f"/p/{admin['tokens']['home']}")
    assert antwort.status_code == 200
    assert "portal_sitzung" not in _cookie_kopf(antwort)


def test_ohne_schalter_keine_zeile(client, db, admin):
    client.get(f"/p/{admin['tokens']['home']}")
    anzahl = db["verbindung"].execute("SELECT COUNT(*) c FROM sitzungen").fetchone()["c"]
    assert anzahl == 0


# --- Ausstellen -------------------------------------------------------------

def test_mit_schalter_wird_cookie_gesetzt(client, admin, an):
    antwort = client.get(f"/p/{admin['tokens']['home']}")
    assert antwort.status_code == 200
    assert "portal_sitzung=" in _cookie_kopf(antwort)


def test_cookie_hat_die_richtigen_attribute(client, admin, an):
    kopf = _cookie_kopf(client.get(f"/p/{admin['tokens']['home']}"))
    assert "HttpOnly" in kopf
    assert "Secure" in kopf
    assert "SameSite=Lax" in kopf
    assert "Path=/" in kopf
    # Kein Domain-Attribut - sonst ginge das Cookie an Home Assistant mit.
    assert "Domain=" not in kopf


def test_auch_app_seiten_stellen_aus(client, admin, an):
    """Nicht nur die Startseite, jede token-authentifizierte Seite."""
    kopf = _cookie_kopf(client.get(f"/a/einkauf/{admin['tokens']['einkauf']}/"))
    assert "portal_sitzung=" in kopf


def test_sitzung_landet_in_der_datenbank(client, db, admin, an):
    client.get(f"/p/{admin['tokens']['home']}")
    zeilen = db["verbindung"].execute("SELECT * FROM sitzungen").fetchall()
    assert len(zeilen) == 1
    assert zeilen[0]["user_id"] == admin["id"]
    assert zeilen[0]["quelle"] == "token"


def test_cookiewert_steht_nicht_im_klartext_in_der_db(client, db, admin, an):
    """Konsistent zu Wunsch #129: gespeichert wird nur der HMAC."""
    antwort = client.get(f"/p/{admin['tokens']['home']}")
    wert = antwort.headers["Set-Cookie"].split("portal_sitzung=")[1].split(";")[0]
    zeile = db["verbindung"].execute("SELECT kennung_lookup FROM sitzungen").fetchone()
    assert zeile["kennung_lookup"] != wert
    assert len(zeile["kennung_lookup"]) == 64          # SHA-256 als Hex
    with client.application.test_request_context():
        assert zeile["kennung_lookup"] == token_lookup(wert)


# --- Keine Dubletten --------------------------------------------------------

def test_zweiter_aufruf_erzeugt_keine_zweite_sitzung(client, db, admin, an):
    """Sonst wüchse die Tabelle mit jedem Seitenaufruf."""
    client.get(f"/p/{admin['tokens']['home']}")
    antwort = client.get(f"/p/{admin['tokens']['home']}")   # Client behält das Cookie
    anzahl = db["verbindung"].execute("SELECT COUNT(*) c FROM sitzungen").fetchone()["c"]
    assert anzahl == 1
    assert "portal_sitzung=" not in _cookie_kopf(antwort)


def test_ungueltiger_token_erzeugt_keine_sitzung(client, db, an):
    antwort = client.get("/p/gibtesnicht")
    assert antwort.status_code == 403
    anzahl = db["verbindung"].execute("SELECT COUNT(*) c FROM sitzungen").fetchone()["c"]
    assert anzahl == 0


# --- Das Cookie hat noch KEINE Wirkung (der Kern dieser Stufe) --------------

def test_cookie_allein_authentifiziert_noch_nicht(client, admin, an):
    """Stufe 1 stellt nur aus. Ohne Token in der Adresse muss weiterhin
    Schluss sein - sonst wäre versehentlich schon Stufe 3 aktiv."""
    client.get(f"/p/{admin['tokens']['home']}")            # Cookie einsammeln
    antwort = client.get("/p/gibtesnicht")                 # Cookie geht mit
    assert antwort.status_code == 403


def test_cookie_oeffnet_keine_fremde_app(client, kind, an):
    client.get(f"/p/{kind['tokens']['home']}")
    antwort = client.get(f"/a/admin/{kind['tokens']['einkauf']}/")
    assert antwort.status_code == 403


# --- Widerruf ---------------------------------------------------------------

def test_zugaenge_neu_loescht_die_sitzungen(client, db, admin, kind, an):
    """Ohne das wäre der Widerruf ab Stufe 3 wirkungslos."""
    client.get(f"/p/{kind['tokens']['home']}")
    assert db["verbindung"].execute(
        "SELECT COUNT(*) c FROM sitzungen WHERE user_id=?", (kind["id"],)
    ).fetchone()["c"] == 1

    antwort = client.post(
        f"/a/admin/{admin['tokens']['admin']}/user/{kind['id']}/neue_tokens")
    # Wunsch #140, Stufe 6: antwortet mit der einmaligen Zugangsseite (200)
    # statt mit einer Weiterleitung.
    assert antwort.status_code == 200

    assert db["verbindung"].execute(
        "SELECT COUNT(*) c FROM sitzungen WHERE user_id=?", (kind["id"],)
    ).fetchone()["c"] == 0
