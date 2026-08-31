"""Wunsch #207 (Sicherheitsaudit 11.08.2026): Keine Ratenbegrenzung im
gesamten Portal.

`rate_ueberschritten()` (00_kern.py) ist bewusst schmal: kein externer
Dienst, kein Flask-Limiter (ein Ein-Worker-Setup braucht das nicht), und
bewusst NICHT global angewendet - eine pauschale Bremse hätte die Offline-
Warteschlange der Einkaufsliste treffen können, die POSTs stundenlang
aufhebt und dann in einer Salve nachspielt (dieselbe Überlegung wie beim
CSRF-Riegel, 20_csrf.py). Eingesetzt wird sie gezielt an den zwei Routen,
die konkret betroffen sind: POST /wunsch (#204) und POST /csp-bericht (#205)
– beide unauthentifiziert erreichbar.

**Die Falle beim Client-Adresse ermitteln:** portal hängt nur im internen
Bridge-Netz, jede Anfrage kommt technisch von Caddys Bridge-IP. Ohne
`X-Forwarded-For` auszuwerten, würde ein Ratenlimit "je Adresse" in
Wirklichkeit "insgesamt" heißen – ein einzelner Angreifer würde dann das
Kontingent für die GANZE Familie mitverbrauchen.
"""
import pytest


@pytest.fixture(autouse=True)
def _sauber(app):
    from teile.kern import _RATE_TREFFER
    _RATE_TREFFER.clear()
    yield
    _RATE_TREFFER.clear()


# --- rate_ueberschritten() für sich -----------------------------------------

def test_erste_anfragen_gehen_durch(app):
    from teile.kern import rate_ueberschritten
    with app.test_request_context("/", headers={"X-Forwarded-For": "1.2.3.4"}):
        for _ in range(5):
            assert rate_ueberschritten("t1", max_anfragen=5, fenster_sekunden=60) is False


def test_die_naechste_darueber_wird_gebremst(app):
    from teile.kern import rate_ueberschritten
    with app.test_request_context("/", headers={"X-Forwarded-For": "1.2.3.4"}):
        for _ in range(5):
            rate_ueberschritten("t2", max_anfragen=5, fenster_sekunden=60)
        assert rate_ueberschritten("t2", max_anfragen=5, fenster_sekunden=60) is True


def test_verschiedene_schluessel_teilen_sich_kein_kontingent(app):
    """Sonst würde eine Bremse an EINER Route eine ANDERE mitbremsen."""
    from teile.kern import rate_ueberschritten
    with app.test_request_context("/", headers={"X-Forwarded-For": "1.2.3.4"}):
        for _ in range(5):
            rate_ueberschritten("wunsch-anlegen", max_anfragen=5, fenster_sekunden=60)
        assert rate_ueberschritten("csp-bericht", max_anfragen=5, fenster_sekunden=60) is False


def test_verschiedene_adressen_teilen_sich_kein_kontingent(app):
    """Der eigentliche Punkt: ein Angreifer darf nicht das Kontingent EINER
    anderen, echten Adresse mitverbrauchen."""
    from teile.kern import rate_ueberschritten
    with app.test_request_context("/", headers={"X-Forwarded-For": "9.9.9.9"}):
        for _ in range(5):
            rate_ueberschritten("t3", max_anfragen=5, fenster_sekunden=60)
    with app.test_request_context("/", headers={"X-Forwarded-For": "8.8.8.8"}):
        assert rate_ueberschritten("t3", max_anfragen=5, fenster_sekunden=60) is False


def test_altes_faellt_aus_dem_fenster(app, monkeypatch):
    """Ohne das gleitende Fenster bliebe eine Bremse fuer immer scharf, statt
    sich nach Ablauf der Zeitspanne wieder zu oeffnen."""
    from teile import kern
    jetzt = [1000.0]
    monkeypatch.setattr(kern.time, "monotonic", lambda: jetzt[0])
    with app.test_request_context("/", headers={"X-Forwarded-For": "1.2.3.4"}):
        for _ in range(5):
            kern.rate_ueberschritten("t4", max_anfragen=5, fenster_sekunden=60)
        assert kern.rate_ueberschritten("t4", max_anfragen=5, fenster_sekunden=60) is True
        jetzt[0] += 61
        assert kern.rate_ueberschritten("t4", max_anfragen=5, fenster_sekunden=60) is False


# --- client_ip() -------------------------------------------------------------

def test_client_ip_liest_x_forwarded_for(app):
    """portal steht ausschliesslich hinter Caddy - request.remote_addr zeigt
    sonst immer Caddys eigene Bridge-Adresse, egal wer wirklich anfragt."""
    from teile.kern import client_ip
    with app.test_request_context("/", headers={"X-Forwarded-For": "203.0.113.5"}):
        assert client_ip() == "203.0.113.5"


def test_client_ip_nimmt_die_LETZTE_von_mehreren(app):
    """Wunsch #210 (Audit F-02). Hier stand bis v209 das Gegenteil, und der
    Test hat damit die Luecke zementiert.

    Caddy HAENGT die Adresse seines Gegenuebers an einen vorhandenen Header AN.
    Alles links davon hat der Absender selbst geschrieben; nur der letzte
    Eintrag stammt von Caddy. Die 172.30.0.10 hier ist Caddys Bridge-Adresse -
    in echt steht dort die Adresse des anfragenden Geraets."""
    with app.test_request_context("/", headers={"X-Forwarded-For": "203.0.113.5, 172.30.0.10"}):
        from teile.kern import client_ip
        assert client_ip() == "172.30.0.10"


def test_gefaelschter_header_bekommt_keinen_eigenen_eimer(app):
    """Der Befund in einem Satz: Wenn sich jeder seine eigene Herkunft
    aussuchen kann, hat jede Anfrage einen eigenen Eimer und die Bremse
    greift nie."""
    from teile.kern import client_ip
    gesehen = set()
    for erfunden in ("1.2.3.4", "5.6.7.8", "9.10.11.12"):
        with app.test_request_context(
                "/", headers={"X-Forwarded-For": f"{erfunden}, 172.30.0.10"}):
            gesehen.add(client_ip())
    assert gesehen == {"172.30.0.10"}, (
        f"Drei erfundene Absender ergaben {len(gesehen)} verschiedene Eimer: {gesehen}"
    )


def test_leere_eintraege_stoeren_nicht(app):
    """`X-Forwarded-For: 1.2.3.4, ` endet sonst auf einem leeren Schluessel -
    und ein leerer Schluessel waere fuer alle derselbe Eimer."""
    from teile.kern import client_ip
    with app.test_request_context("/", headers={"X-Forwarded-For": "1.2.3.4, "}):
        assert client_ip() == "1.2.3.4"


def test_client_ip_faellt_ohne_header_zurueck(app):
    from teile.kern import client_ip
    with app.test_request_context("/"):
        assert client_ip()  # irgendein Wert, kein Absturz


# --- Angewendet auf die beiden konkreten Routen -----------------------------

def test_wunsch_route_bremst_ab_der_schwelle(client, db):
    token = db["familie"]["TestAdmin"]["tokens"]["hilfe"]
    letzte = None
    for i in range(9):
        letzte = client.post("/wunsch", json={"text": f"Flut {i}", "token": token})
    assert letzte.status_code == 429


def test_csp_bericht_bremst_ab_der_schwelle(client):
    letzte = None
    for i in range(31):
        letzte = client.post("/csp-bericht", json={"blocked-uri": f"x{i}"})
    assert letzte.status_code == 429
