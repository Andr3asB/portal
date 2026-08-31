"""Wunsch #203 (Sicherheitsaudit 11.08.2026): SSRF über den Web-Push-Endpunkt.

POST /push/subscribe übernahm `subscription.endpoint` bisher ungeprüft aus
dem JSON-Body. `push_send()` (00_kern.py) ruft später `pywebpush.webpush()`
mit genau dieser Adresse auf – der Server macht also einen serverseitigen
HTTP-POST an eine Adresse, die vollständig vom Client vorgegeben wurde. Wer
dort `http://172.30.0.10:2020/` oder eine beliebige externe Adresse einträgt,
bekommt bei jedem künftigen Push-Ereignis (neue Aufgabe, Rückfrage, ...)
einen serverseitig ausgelösten Request dorthin.

Dieselbe Fehlerklasse wie Wunsch #127 (Rezept-Import) – `ist_oeffentliche_url()`
ist deshalb von 11_rezepte.py nach teile/00_kern.py umgezogen, damit beide
Module dieselbe Prüfung nutzen, statt einer zweiten, möglicherweise
abweichenden Kopie.

Die Tests hier mocken `socket.getaddrinfo`, statt auf echte DNS-Auflösung zu
vertrauen – deterministisch und ohne Netzabhängigkeit im Testlauf.
"""
import socket

import pytest


def _addrinfo(ip: str):
    """Minimal-Rückgabe im Format von socket.getaddrinfo()."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]


@pytest.fixture()
def push_token(db):
    # TestAdmin hat laut conftest bereits einen 'home'-Grant - ein zweiter
    # Grant fuer dieselbe App wuerde an UNIQUE(user_id, app_id) scheitern
    # (INSERT OR IGNORE liefe dann still ins Leere und der NEUE Token bliebe
    # unbenutzbar). aktueller_nutzer() haengt ohnehin an keiner bestimmten
    # App - irgendein gueltiger Grant reicht.
    return db["familie"]["TestAdmin"]["tokens"]["home"]


def _subscribe(client, token, endpoint):
    return client.post("/push/subscribe", json={
        "token": token,
        "subscription": {"endpoint": endpoint,
                         "keys": {"p256dh": "p256dh-wert", "auth": "auth-wert"}},
        "geraet": "Testgerät",
    })


# --- ist_oeffentliche_url() selbst ------------------------------------------

def test_liegt_jetzt_im_kern_und_bleibt_in_rezepte_importierbar():
    """Der Umzug darf 11_rezepte.py nicht kaputt machen - der alte Name
    bleibt dort als Import erhalten."""
    import importlib

    from teile.kern import ist_oeffentliche_url
    rezepte = importlib.import_module("teile.11_rezepte")
    assert rezepte._ist_oeffentliche_url is ist_oeffentliche_url


def test_private_ip_wird_abgelehnt(monkeypatch):
    from teile.kern import ist_oeffentliche_url
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo("172.30.0.10"))
    assert ist_oeffentliche_url("https://intern.example/x") is False


def test_loopback_wird_abgelehnt(monkeypatch):
    from teile.kern import ist_oeffentliche_url
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo("127.0.0.1"))
    assert ist_oeffentliche_url("https://localhost/x") is False


def test_oeffentliche_ip_wird_akzeptiert(monkeypatch):
    from teile.kern import ist_oeffentliche_url
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo("93.184.216.34"))
    assert ist_oeffentliche_url("https://example.com/x") is True


def test_multicast_wird_abgelehnt(monkeypatch):
    """Python's `ipaddress` stuft Multicast-Adressen als `is_global=True`
    ein (nachgemessen: 224.0.0.1 UND ff05::1) - ohne den zusätzlichen
    `is_multicast`-Ausschluss käme eine Multicast-Adresse durch die Prüfung."""
    from teile.kern import ist_oeffentliche_url
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo("224.0.0.1"))
    assert ist_oeffentliche_url("https://irgendwas.example/x") is False


def test_falsches_schema_wird_abgelehnt():
    """file:// oder javascript: haben nichts an dieser Stelle verloren -
    ohne diese Pruefung wuerde nicht einmal die DNS-Aufloesung greifen."""
    from teile.kern import ist_oeffentliche_url
    assert ist_oeffentliche_url("file:///etc/passwd") is False
    assert ist_oeffentliche_url("ftp://example.com/x") is False


# --- POST /push/subscribe ---------------------------------------------------

def test_subscribe_lehnt_interne_adresse_ab(client, push_token, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo("172.30.0.10"))
    antwort = _subscribe(client, push_token, "http://172.30.0.10:2020/")
    assert antwort.status_code == 400
    assert antwort.get_json()["ok"] is False


def test_subscribe_speichert_interne_adresse_nicht(client, db, push_token, monkeypatch):
    """Die eigentliche Aussage: Es reicht nicht, nur 400 zu antworten - die
    Zeile darf gar nicht erst in der Datenbank landen, sonst holt sie der
    naechste Push-Thread trotzdem."""
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo("10.0.0.5"))
    _subscribe(client, push_token, "http://10.0.0.5/hook")
    anzahl = db["verbindung"].execute(
        "SELECT COUNT(*) FROM push_abos WHERE endpoint=?", ("http://10.0.0.5/hook",)
    ).fetchone()[0]
    assert anzahl == 0


def test_subscribe_akzeptiert_oeffentliche_adresse(client, db, push_token, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo("93.184.216.34"))
    antwort = _subscribe(client, push_token, "https://fcm.googleapis.com/fcm/send/xyz")
    assert antwort.status_code == 200
    assert antwort.get_json()["ok"] is True
    anzahl = db["verbindung"].execute(
        "SELECT COUNT(*) FROM push_abos WHERE endpoint=?",
        ("https://fcm.googleapis.com/fcm/send/xyz",)
    ).fetchone()[0]
    assert anzahl == 1


def test_nicht_aufloesbarer_name_wird_abgelehnt(client, push_token, monkeypatch):
    def wirft(*a, **k):
        raise socket.gaierror("nicht aufloesbar")
    monkeypatch.setattr(socket, "getaddrinfo", wirft)
    antwort = _subscribe(client, push_token, "https://gibtsnicht.invalid/x")
    assert antwort.status_code == 400
