"""Wunsch #140, Stufe 2: CSRF-Riegel.

Der wichtigste Test hier ist `test_same_site_wird_abgelehnt`: Home Assistant
läuft unter derselben Domain wie das Portal, ein POST von dort wäre also
`same-site`. Genau der muss abgelehnt werden – sonst hätte eine beliebige
HA-Seite (oder etwas, das dort eingebettet ist) Schreibzugriff aufs Portal.
"""
import pytest


@pytest.fixture()
def scharf(app):
    vorher = app.config.get("CSRF_MODUS")
    app.config["CSRF_MODUS"] = "scharf"
    yield
    app.config["CSRF_MODUS"] = vorher


@pytest.fixture()
def beobachten(app):
    vorher = app.config.get("CSRF_MODUS")
    app.config["CSRF_MODUS"] = "beobachten"
    yield
    app.config["CSRF_MODUS"] = vorher


def _darkmode(client, admin, **kopfzeilen):
    """Ein einfacher POST-Endpunkt, der ohne weitere Voraussetzungen läuft."""
    return client.post(
        "/settings/darkmode",
        json={"token": admin["tokens"]["home"]},
        headers=kopfzeilen,
    )


# --- Ausgangszustand: nichts wird geprüft -----------------------------------

def test_ohne_schalter_wird_nicht_geprueft(client, admin):
    """Standard ist 'aus' – der Riegel darf im Ausgangszustand nichts tun."""
    antwort = _darkmode(client, admin)
    assert antwort.status_code == 200


def test_ohne_schalter_auch_von_fremd(client, admin):
    antwort = _darkmode(client, admin, **{"Sec-Fetch-Site": "cross-site"})
    assert antwort.status_code == 200


# --- Beobachtungsmodus: protokollieren, aber durchlassen --------------------

def test_beobachten_laesst_fremde_anfrage_durch(client, admin, beobachten):
    antwort = _darkmode(client, admin, **{"Sec-Fetch-Site": "cross-site"})
    assert antwort.status_code == 200


def test_beobachten_protokolliert(client, admin, beobachten, caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        _darkmode(client, admin, **{"Sec-Fetch-Site": "cross-site"})
    assert "CSRF-Verdacht" in caplog.text


# --- Scharf: eigene Anfragen durch, fremde raus -----------------------------

def test_eigene_anfrage_geht_durch(client, admin, scharf):
    antwort = _darkmode(client, admin, **{"Sec-Fetch-Site": "same-origin"})
    assert antwort.status_code == 200


def test_cross_site_wird_abgelehnt(client, admin, scharf):
    antwort = _darkmode(client, admin, **{"Sec-Fetch-Site": "cross-site"})
    assert antwort.status_code == 403


def test_same_site_wird_abgelehnt(client, admin, scharf):
    """Der entscheidende Fall: Home Assistant ist same-site, aber nicht
    same-origin. Ein POST von dort darf NICHT durchgehen."""
    antwort = _darkmode(client, admin, **{"Sec-Fetch-Site": "same-site"})
    assert antwort.status_code == 403


def test_none_wird_abgelehnt(client, admin, scharf):
    """'none' heisst: direkt aus der Adresszeile. Bei einer ändernden
    Anfrage sollte das gar nicht vorkommen."""
    antwort = _darkmode(client, admin, **{"Sec-Fetch-Site": "none"})
    assert antwort.status_code == 403


def test_ohne_jede_kopfzeile_wird_abgelehnt(client, admin, scharf):
    """Weder Sec-Fetch-Site noch Origin – nicht beurteilbar, also raus.
    Der Beobachtungsmodus zeigt vorher, ob echte Geräte hier landen."""
    antwort = _darkmode(client, admin)
    assert antwort.status_code == 403


# --- Origin als Ersatz, wenn Sec-Fetch-Site fehlt ---------------------------

def test_passende_origin_genuegt(client, admin, scharf):
    antwort = _darkmode(client, admin, Origin="http://localhost")
    assert antwort.status_code == 200


def test_fremde_origin_wird_abgelehnt(client, admin, scharf):
    antwort = _darkmode(client, admin, Origin="https://boese.example")
    assert antwort.status_code == 403


def test_sec_fetch_site_schlaegt_origin(client, admin, scharf):
    """Passende Origin rettet eine cross-site-Anfrage NICHT – sonst könnte
    ein Angreifer über einen gefälschten Origin-Header durchrutschen."""
    antwort = _darkmode(client, admin, **{
        "Sec-Fetch-Site": "cross-site", "Origin": "http://localhost"})
    assert antwort.status_code == 403


def test_x_forwarded_proto_zaehlt_fuer_die_erwartete_origin(client, admin, scharf):
    """Regressionstest für einen am 2026-08-06 gefundenen Fehler: Hinter Caddy
    läuft die Verbindung zu portal intern als Klartext-HTTP (TLS endet bei
    Caddy) – ohne X-Forwarded-Proto zu berücksichtigen, hätte die erwartete
    Origin IMMER 'http://...' gelautet, während jeder echte Browser
    'https://...' schickt. Der Fehler blieb unentdeckt, weil moderne Browser
    Sec-Fetch-Site senden und diesen Zweig gar nicht erreichen – erst ein
    Client ohne diesen Header (z. B. curl, oder ein alter Browser) deckte ihn
    auf. Origin muss dem WEITERGELEITETEN Schema folgen, nicht dem, das
    Flask an der internen Verbindung sieht."""
    antwort = _darkmode(client, admin, **{
        "Origin": "https://localhost", "X-Forwarded-Proto": "https"})
    assert antwort.status_code == 200

    # Ohne den Kopf muss weiterhin das tatsächliche Anfrage-Schema gelten
    # (hier http, wie der Test-Client es sendet) – sonst würde ein simulierter
    # Vorwärts-Kopf jede Herkunft akzeptieren.
    antwort = _darkmode(client, admin, Origin="https://localhost")
    assert antwort.status_code == 403


# --- Lesende Anfragen bleiben unberührt -------------------------------------

def test_get_wird_nie_geprueft(client, admin, scharf):
    antwort = client.get(f"/p/{admin['tokens']['home']}",
                         headers={"Sec-Fetch-Site": "cross-site"})
    assert antwort.status_code == 200


def test_health_bleibt_erreichbar(client, scharf):
    assert client.get("/health").status_code == 200


# --- Formular-POST einer echten App ----------------------------------------

def test_echtes_formular_geht_durch(client, admin, scharf):
    """Nicht nur der JSON-Endpunkt: ein normales Formular einer App."""
    antwort = client.post(
        f"/a/einkauf/{admin['tokens']['einkauf']}/add",
        data={"name": "Testartikel"},
        headers={"Sec-Fetch-Site": "same-origin"},
    )
    assert antwort.status_code in (200, 302, 303)


def test_echtes_formular_von_fremd_abgelehnt(client, admin, scharf):
    antwort = client.post(
        f"/a/einkauf/{admin['tokens']['einkauf']}/add",
        data={"name": "Boeser Artikel"},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert antwort.status_code == 403
