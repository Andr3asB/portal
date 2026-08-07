"""Wunsch #140, Stufe 6: Zugangslinks sind nur EINMAL sichtbar.

Der Kern dieser Stufe: In der Datenbank steht nur noch der HMAC. Ein Link
lässt sich deshalb nicht mehr nachschlagen - er existiert im Klartext genau
in der Antwort, die ihn erzeugt hat. Diese Tests halten beide Hälften fest:
dass er dort tatsächlich steht UND funktioniert, und dass er sonst nirgends
mehr auftaucht.
"""
import re

import pytest


@pytest.fixture()
def scharf(app):
    """CSRF scharf, damit die POSTs realistisch laufen."""
    vorher = app.config.get("CSRF_MODUS")
    app.config["CSRF_MODUS"] = "scharf"
    yield
    app.config["CSRF_MODUS"] = vorher


def _neuer_zugang(client, admin, ziel_id):
    return client.post(
        f"/a/admin/{admin['tokens']['admin']}/user/{ziel_id}/neue_tokens",
        headers={"Sec-Fetch-Site": "same-origin"})


def _token_aus_seite(text):
    treffer = re.search(r"https://portal\.16schwaben\.de/p/([A-Za-z0-9_-]+)", text)
    return treffer.group(1) if treffer else None


# --- Die Verwaltungsseite zeigt keine Zugänge mehr -------------------------

def test_verwaltung_zeigt_keine_fremden_zugaenge(client, admin, kind, eltern):
    """Der Befund aus der Sicherheitsanalyse: Diese Seite rendete bisher die
    Zugangsadressen der GANZEN Familie im Klartext - und der Service Worker
    cachte sie mit.

    Geprüft wird über den Token-Aufruf, denn dort ist die Versuchung am
    grössten, etwas durchzureichen. Der eigene Admin-Token steckt dabei
    zwangsläufig in den Links der Seite - er steht ja in der Adresszeile, über
    die sie aufgerufen wurde (`tp`, Stufe 4). Alles ANDERE darf nicht
    auftauchen."""
    seite = client.get(f"/a/admin/{admin['tokens']['admin']}/").get_data(as_text=True)
    eigener_admin_token = admin["tokens"]["admin"]
    for person, wer in ((admin, "Admin"), (kind, "Kind"), (eltern, "Eltern")):
        for name, token in person["tokens"].items():
            if token == eigener_admin_token:
                continue          # steht in der aufgerufenen Adresse selbst
            assert token not in seite, f"Token '{wer}/{name}' steht in der Verwaltung"


def test_verwaltung_tokenfrei_zeigt_ueberhaupt_keinen_token(app, client, admin, kind, eltern):
    """Der Normalfall im Betrieb (Stufe 4): Aufruf über das Cookie, ohne Token
    in der Adresse. Dann darf auf der Seite kein einziger Token stehen."""
    vorher = (app.config.get("SITZUNG_AUSSTELLEN"), app.config.get("SITZUNG_KONSUMIEREN"))
    app.config["SITZUNG_AUSSTELLEN"] = "1"
    app.config["SITZUNG_KONSUMIEREN"] = "1"
    try:
        client.get(f"/p/{admin['tokens']['home']}")      # Cookie einsammeln
        seite = client.get("/a/admin/").get_data(as_text=True)
        assert "TestKind" in seite, "Verwaltung nicht geladen"
        for person, wer in ((admin, "Admin"), (kind, "Kind"), (eltern, "Eltern")):
            for name, token in person["tokens"].items():
                assert token not in seite, f"Token '{wer}/{name}' steht in der Verwaltung"
    finally:
        app.config["SITZUNG_AUSSTELLEN"], app.config["SITZUNG_KONSUMIEREN"] = vorher


def test_qr_route_gibt_es_nicht_mehr(app):
    """Die alte `/qr.svg`-Route musste den Token aus der Datenbank holen -
    das geht nicht mehr. Sie darf nicht als toter Endpunkt zurückbleiben."""
    pfade = {str(r) for r in app.url_map.iter_rules()}
    assert not [p for p in pfade if "qr.svg" in p]


# --- Neuer Zugang: einmal sichtbar, und er trägt --------------------------

def test_neuer_zugang_wird_einmal_angezeigt(client, admin, kind, scharf):
    antwort = _neuer_zugang(client, admin, kind["id"])
    assert antwort.status_code == 200
    text = antwort.get_data(as_text=True)
    assert "Nur jetzt sichtbar" in text
    assert _token_aus_seite(text), "kein Zugangslink in der Antwort"


def test_der_angezeigte_link_funktioniert_wirklich(app, client, admin, kind, scharf):
    """Ein Link, der zwar angezeigt wird, aber nicht funktioniert, wäre der
    schlimmste denkbare Fehler dieser Stufe: Er fällt erst auf, wenn jemand
    ausgesperrt ist."""
    text = _neuer_zugang(client, admin, kind["id"]).get_data(as_text=True)
    neuer_token = _token_aus_seite(text)

    kind_geraet = app.test_client()
    antwort = kind_geraet.get(f"/p/{neuer_token}")
    assert antwort.status_code == 200
    assert b"TestKind" in antwort.data


def test_der_alte_link_ist_danach_tot(app, client, admin, kind, scharf):
    _neuer_zugang(client, admin, kind["id"])
    fremdes_geraet = app.test_client()
    assert fremdes_geraet.get(f"/p/{kind['tokens']['home']}").status_code == 403


def test_qr_ist_eingebettet_und_nicht_verlinkt(client, admin, kind, scharf):
    """Der QR-Code kann keine eigene Adresse mehr haben (die müsste den Token
    erneut nachschlagen) - er steckt als data:-URI in der Seite. Die CSP
    erlaubt `img-src 'self' data:`, sonst bliebe das Bild leer."""
    text = _neuer_zugang(client, admin, kind["id"]).get_data(as_text=True)
    assert 'src="data:image/svg+xml;base64,' in text


def test_zugang_taucht_danach_nirgends_wieder_auf(client, admin, kind, scharf):
    """Die eigentliche Zusage: einmal - und nie wieder."""
    text = _neuer_zugang(client, admin, kind["id"]).get_data(as_text=True)
    neuer_token = _token_aus_seite(text)

    verwaltung = client.get(f"/a/admin/{admin['tokens']['admin']}/").get_data(as_text=True)
    assert neuer_token not in verwaltung


def test_neuer_nutzer_bekommt_seinen_link_sofort(client, admin, scharf):
    """Ohne Anzeige beim Anlegen wäre ein neuer Nutzer nicht erreichbar -
    man müsste ihm direkt danach schon wieder einen neuen Zugang erzeugen."""
    antwort = client.post(
        f"/a/admin/{admin['tokens']['admin']}/user/neu",
        data={"name": "Neuling", "farbe": "#123456", "rolle": "kind"},
        headers={"Sec-Fetch-Site": "same-origin"})
    assert antwort.status_code == 200
    text = antwort.get_data(as_text=True)
    assert "Neuling" in text
    assert _token_aus_seite(text), "kein Zugangslink für den neuen Nutzer"


def test_link_des_neuen_nutzers_funktioniert(app, client, admin, scharf):
    antwort = client.post(
        f"/a/admin/{admin['tokens']['admin']}/user/neu",
        data={"name": "Neuling", "farbe": "#123456", "rolle": "kind"},
        headers={"Sec-Fetch-Site": "same-origin"})
    token = _token_aus_seite(antwort.get_data(as_text=True))
    geraet = app.test_client()
    seite = geraet.get(f"/p/{token}")
    assert seite.status_code == 200
    assert b"Neuling" in seite.data


# --- Grant-Chips funktionieren weiter --------------------------------------

def test_app_freischalten_geht_weiterhin(client, admin, kind, db, scharf):
    """`grant_anlegen()` verwirft den Klartext hier bewusst - die
    Freischaltung selbst muss trotzdem wirken."""
    vorher = db["verbindung"].execute(
        "SELECT COUNT(*) c FROM grants WHERE user_id=?", (kind["id"],)).fetchone()["c"]
    antwort = client.post(
        f"/a/admin/{admin['tokens']['admin']}/user/{kind['id']}/grant/todo",
        headers={"Sec-Fetch-Site": "same-origin"})
    assert antwort.status_code in (302, 303)
    nachher = db["verbindung"].execute(
        "SELECT COUNT(*) c FROM grants WHERE user_id=?", (kind["id"],)).fetchone()["c"]
    assert nachher == vorher + 1
