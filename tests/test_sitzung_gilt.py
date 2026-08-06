"""Wunsch #140, Stufe 3: Das Sitzungs-Cookie gilt als Nachweis.

Die drei Tests, auf die es ankommt:
  * `test_pfad_token_schlaegt_cookie` – auf einem geteilten Gerät muss der
    gerade geöffnete Link gewinnen, nicht das Cookie des zuletzt Angemeldeten.
  * `test_widerruf_macht_cookie_ungueltig` – „Zugänge neu erzeugen" muss
    wirken, sonst ist der Notfallknopf aus Wunsch #131 wertlos.
  * `test_ungueltiger_token_faellt_nicht_aufs_cookie_zurueck` – ein
    widerrufener Link darf nicht stillschweigend weiterfunktionieren.
"""
import pytest


@pytest.fixture()
def stufe3(app):
    """Beide Schalter an: ausstellen und konsumieren."""
    vorher = (app.config.get("SITZUNG_AUSSTELLEN"), app.config.get("SITZUNG_KONSUMIEREN"))
    app.config["SITZUNG_AUSSTELLEN"] = "1"
    app.config["SITZUNG_KONSUMIEREN"] = "1"
    yield
    app.config["SITZUNG_AUSSTELLEN"], app.config["SITZUNG_KONSUMIEREN"] = vorher


@pytest.fixture()
def nur_ausstellen(app):
    """Stand der Stufen 1–2: Cookie wird ausgestellt, gilt aber nicht."""
    vorher = (app.config.get("SITZUNG_AUSSTELLEN"), app.config.get("SITZUNG_KONSUMIEREN"))
    app.config["SITZUNG_AUSSTELLEN"] = "1"
    app.config["SITZUNG_KONSUMIEREN"] = "0"
    yield
    app.config["SITZUNG_AUSSTELLEN"], app.config["SITZUNG_KONSUMIEREN"] = vorher


# --- Schalter -------------------------------------------------------------

def test_ohne_schalter_gilt_das_cookie_nicht(client, admin, nur_ausstellen):
    client.get(f"/p/{admin['tokens']['home']}")      # Cookie einsammeln
    assert client.get("/start").status_code == 403


def test_mit_schalter_kommt_man_ohne_token_rein(client, admin, stufe3):
    client.get(f"/p/{admin['tokens']['home']}")
    antwort = client.get("/start")
    assert antwort.status_code == 200
    assert b"TestAdmin" in antwort.data


def test_ohne_cookie_kein_zutritt(client, stufe3):
    assert client.get("/start").status_code == 403


# --- Vorrang des Pfad-Tokens ----------------------------------------------

def test_pfad_token_schlaegt_cookie(client, admin, kind, stufe3):
    """Geteiltes Gerät: Cookie gehört dem Admin, geöffnet wird der Link des
    Kindes. Es muss das Kind erscheinen."""
    client.get(f"/p/{admin['tokens']['home']}")      # Cookie = Admin
    antwort = client.get(f"/p/{kind['tokens']['home']}")
    assert antwort.status_code == 200
    assert b"TestKind" in antwort.data
    assert b"TestAdmin" not in antwort.data


def test_link_oeffnen_uebernimmt_das_geraet(client, admin, kind, stufe3):
    """Der Vorrang des Pfad-Tokens muss ÜBER die eine Seite hinaus halten.

    Bis Stufe 3 war das automatisch so: Jede Kachel trug den Token des
    geöffneten Links, die Navigation folgte ihm. Token-frei (Stufe 4) ist
    `/a/einkauf/` für alle dieselbe Adresse – ab dem zweiten Klick entscheidet
    allein das Cookie. Öffnet auf dem Familien-iPad also jemand seinen Link,
    während das Cookie noch dem Vorgänger gehört, muss die Sitzung mitwechseln.
    Sonst sähe das Kind seine Startseite und danach die Seiten des Admins.

    Das ist der Fehler, der beim End-to-End-Test auf dem echten Server auffiel:
    `/p/<kind>` zeigte korrekt das Kind, `/start` danach wieder den Admin."""
    client.get(f"/p/{admin['tokens']['home']}")      # Cookie = Admin
    client.get(f"/p/{kind['tokens']['home']}")       # Kind öffnet seinen Link

    antwort = client.get("/start")                   # rein über das Cookie
    assert antwort.status_code == 200
    assert b"TestKind" in antwort.data
    assert b"TestAdmin" not in antwort.data, \
        "Das Cookie gehört noch dem Vorgänger – geteiltes Gerät kaputt"


def test_geraetuebernahme_laesst_keine_verwaiste_sitzung_zurueck(
        client, admin, kind, db, stufe3):
    """Beim Wechsel muss die alte Sitzungszeile verschwinden.

    Bliebe sie stehen, sammelte jedes geteilte Gerät gültige Sitzungen an, die
    niemand mehr kennt – und „Zugänge neu erzeugen" räumt nur die des eigenen
    Nutzers weg, nicht die eines fremden auf demselben Gerät."""
    client.get(f"/p/{admin['tokens']['home']}")
    client.get(f"/p/{kind['tokens']['home']}")

    zeilen = db["verbindung"].execute(
        "SELECT user_id FROM sitzungen").fetchall()
    assert [z["user_id"] for z in zeilen] == [kind["id"]], \
        f"erwartet genau eine Sitzung (Kind), vorhanden: {[dict(z) for z in zeilen]}"


def test_ungueltiger_token_faellt_nicht_aufs_cookie_zurueck(client, admin, stufe3):
    """Ein widerrufener Link darf nicht dadurch weiterfunktionieren, dass
    zufällig noch ein gültiges Cookie im Browser liegt."""
    client.get(f"/p/{admin['tokens']['home']}")
    assert client.get("/p/gibtesnichtmehr").status_code == 403


# --- Das Cookie weitet keine Rechte aus ------------------------------------

def test_cookie_oeffnet_nur_freigeschaltete_apps(client, kind, stufe3):
    """Das Kind hat keinen Aufgaben-Zugang – auch nicht per Cookie."""
    from teile.kern import grant
    client.get(f"/p/{kind['tokens']['home']}")
    with client.application.test_request_context(
        headers={"Cookie": _cookie_von(client)}
    ):
        assert grant(None, "einkauf") is not None      # freigeschaltet
        assert grant(None, "todo") is None             # nicht freigeschaltet
        assert grant(None, "admin") is None            # erst recht nicht


def test_rollen_bleiben_erhalten(client, kind, stufe3):
    from teile.kern import grant
    client.get(f"/p/{kind['tokens']['home']}")
    with client.application.test_request_context(
        headers={"Cookie": _cookie_von(client)}
    ):
        user = grant(None, "einkauf")
    assert user["rolle"] == "kind"
    assert user["is_admin"] == 0


def test_navigations_tokens_auch_per_cookie(client, admin, stufe3):
    """base.html braucht sie auf jeder Seite – auch ohne Token in der URL."""
    from teile.kern import grant
    client.get(f"/p/{admin['tokens']['home']}")
    with client.application.test_request_context(
        headers={"Cookie": _cookie_von(client)}
    ):
        user = grant(None, "einkauf")
    assert user["home_token"] == admin["tokens"]["home"]
    assert user["hilfe_token"] == admin["tokens"]["hilfe"]


# --- Widerruf --------------------------------------------------------------

def test_widerruf_macht_cookie_ungueltig(app, client, admin, kind, stufe3):
    """Der Notfallknopf aus Wunsch #131 muss auch das Cookie erledigen.

    Zwei getrennte Clients, weil es in Wirklichkeit zwei Geräte sind: Andi
    klickt auf seinem, Friederikes Handy ist ein anderes. Mit nur einem
    Client würde derselbe Browser beides sein – dann bekäme er beim
    Widerrufs-Request selbst eine frische Admin-Sitzung gesetzt und der Test
    prüfte etwas, das es im Betrieb gar nicht gibt."""
    kind_geraet  = client                      # hat gleich das Kind-Cookie
    admin_geraet = app.test_client()

    kind_geraet.get(f"/p/{kind['tokens']['home']}")
    assert kind_geraet.get("/start").status_code == 200

    antwort = admin_geraet.post(
        f"/a/admin/{admin['tokens']['admin']}/user/{kind['id']}/neue_tokens",
        headers={"Sec-Fetch-Site": "same-origin"})
    assert antwort.status_code in (302, 303)

    # Das Kind-Gerät kommt weder per Cookie noch per altem Link wieder rein.
    assert kind_geraet.get("/start").status_code == 403
    assert kind_geraet.get(f"/p/{kind['tokens']['home']}").status_code == 403


def test_widerruf_sperrt_den_ausloesenden_admin_nicht_aus(app, client, admin, stufe3):
    """Gegenprobe: Wer den Knopf drückt, darf sich nicht selbst aussperren –
    sonst wäre der Notfallknopf im Notfall unbenutzbar."""
    client.get(f"/p/{admin['tokens']['home']}")
    antwort = client.post(
        f"/a/admin/{admin['tokens']['admin']}/user/{admin['id']}/neue_tokens",
        headers={"Sec-Fetch-Site": "same-origin"})
    assert antwort.status_code in (302, 303)
    # Die Weiterleitung zeigt auf die NEUE Admin-Adresse (siehe Wunsch #131).
    assert "/a/admin/" in antwort.headers["Location"]
    assert admin["tokens"]["admin"] not in antwort.headers["Location"]


def test_abgelaufene_sitzung_gilt_nicht(client, db, admin, stufe3):
    client.get(f"/p/{admin['tokens']['home']}")
    assert client.get("/start").status_code == 200
    db["verbindung"].execute(
        "UPDATE sitzungen SET ablauf = datetime('now', '-1 day')")
    db["verbindung"].commit()
    assert client.get("/start").status_code == 403


# --- Hilfsfunktion ---------------------------------------------------------

def _cookie_von(client):
    """Baut die Cookie-Kopfzeile aus dem Cookie-Speicher des Test-Clients."""
    from teile.kern import SITZUNG_COOKIE
    for keks in client.cookie_jar if hasattr(client, "cookie_jar") else []:
        if keks.name == SITZUNG_COOKIE:
            return f"{keks.name}={keks.value}"
    # Werkzeug >= 2.3: Cookies hängen am Client selbst
    wert = client.get_cookie(SITZUNG_COOKIE)
    return f"{SITZUNG_COOKIE}={wert.value}" if wert else ""
