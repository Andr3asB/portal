"""Wunsch #287 (Sicherheitsaudit 16.09.2026, Befund N-08): /push/subscribe
löste DNS auf, bevor es wusste, mit wem es spricht.

`ist_oeffentliche_url()` - also `socket.getaddrinfo()` - lief VOR
`aktueller_nutzer()`. Jeder Unbekannte konnte das Portal beliebige Namen
auflösen lassen; ein träger Nameserver hält einen der vier Gunicorn-Threads
sekundenlang fest, vier parallele Anfragen halten das Portal an. Dazu gab es
weder eine Ratenbremse noch eine Längengrenze für den Endpunkt noch eine
Obergrenze an Abos je Nutzer.

Der erste Test ist der wichtigste: DNS darf für einen Unbekannten gar nicht
erst passieren - `getaddrinfo` wirft hier AssertionError, sobald es gerufen
wird.
"""
import socket

import pytest


def _addrinfo(ip: str):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]


def _subscribe(client, token, endpoint):
    return client.post("/push/subscribe", json={
        "token": token,
        "subscription": {"endpoint": endpoint,
                         "keys": {"p256dh": "p256dh-wert", "auth": "auth-wert"}},
        "geraet": "Testgerät",
    })


@pytest.fixture()
def push_token(db):
    return db["familie"]["TestAdmin"]["tokens"]["home"]


def test_unbekannter_loest_keine_dns_aufloesung_aus(client, monkeypatch):
    def darf_nicht(*a, **k):
        raise AssertionError("DNS-Aufloesung vor der Identitaetspruefung")
    monkeypatch.setattr(socket, "getaddrinfo", darf_nicht)
    antwort = _subscribe(client, "kein-gueltiger-token", "https://fcm.googleapis.com/fcm/send/x")
    assert antwort.status_code == 403


def test_ratenbremse_greift_nach_zehn(client, push_token, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo("93.184.216.34"))
    for i in range(10):
        assert _subscribe(client, push_token, f"https://fcm.googleapis.com/fcm/send/{i}").status_code == 200
    antwort = _subscribe(client, push_token, "https://fcm.googleapis.com/fcm/send/elf")
    assert antwort.status_code == 429


def test_ueberlanger_endpunkt_wird_abgelehnt(client, push_token, monkeypatch):
    def darf_nicht(*a, **k):
        raise AssertionError("DNS fuer einen Endpunkt, der ohnehin zu lang ist")
    monkeypatch.setattr(socket, "getaddrinfo", darf_nicht)
    antwort = _subscribe(client, push_token, "https://fcm.googleapis.com/" + "x" * 2000)
    assert antwort.status_code == 400


def test_hoechstens_zwanzig_abos_je_nutzer(client, db, admin, push_token, monkeypatch):
    v = db["verbindung"]
    for i in range(20):
        v.execute("INSERT INTO push_abos(user_id, endpoint, p256dh, auth, geraet) "
                  "VALUES(?,?,?,?,?)", (admin["id"], f"https://push.example/alt-{i}", "p", "a", "G"))
    v.commit()
    aeltestes = v.execute("SELECT MIN(id) FROM push_abos WHERE user_id=?", (admin["id"],)).fetchone()[0]

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo("93.184.216.34"))
    assert _subscribe(client, push_token, "https://fcm.googleapis.com/fcm/send/neu").status_code == 200

    anzahl = v.execute("SELECT COUNT(*) FROM push_abos WHERE user_id=?", (admin["id"],)).fetchone()[0]
    assert anzahl == 20
    assert v.execute("SELECT 1 FROM push_abos WHERE id=?", (aeltestes,)).fetchone() is None
    assert v.execute("SELECT 1 FROM push_abos WHERE endpoint=?",
                     ("https://fcm.googleapis.com/fcm/send/neu",)).fetchone() is not None
