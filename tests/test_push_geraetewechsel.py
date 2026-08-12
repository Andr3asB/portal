"""Wunsch #209 (Sicherheitsaudit, Befund F-01): geteiltes Gerät, ein Push-Abo.

Kein Angreifer nötig – das passiert im Alltag. `push_abos.endpoint` ist UNIQUE
und identifiziert den **Browser**, nicht die Person. Auf dem Familien-Tablet
heisst das:

1. Andi meldet sich an und erlaubt Push → Zeile (user_id=Andi, endpoint=E).
2. Simone öffnet später im selben Browser ihren Link. Der Browser liefert
   denselben Endpunkt E, das `ON CONFLICT` greift.
3. `user_id` stand **nicht** in der UPDATE-Liste und blieb bei Andi.

Ab da bekam Simones Gerät Andis Benachrichtigungen – inklusive Aufgabentexten
und Werkstatt-Rückfragen – und sie selbst gar keine.

Dieselbe Frage stellt sich bei den Sitzungen (19_sitzung.py), und dort war sie
schon richtig beantwortet: **wer sich zuletzt ausgewiesen hat, besitzt das
Gerät.** Beim Push war es vergessen worden.

Der Test prüft deshalb beide Hälften: die Übernahme UND dass hinterher nur
noch eine Zeile dasteht. Prüfte er nur die Übernahme, bliebe er grün, wenn
jemand das UNIQUE aufhebt und daraus zwei Abos macht – dann bekäme das Tablet
die Nachrichten beider Personen.
"""
import socket

import pytest


ENDPUNKT = "https://fcm.googleapis.com/fcm/send/gemeinsames-tablet"


@pytest.fixture(autouse=True)
def _dns(monkeypatch):
    """Die Suite laeuft offline, `ist_oeffentliche_url()` (Wunsch #203) loest
    den Endpunkt aber auf. Ohne diese Aufloesung faellt schon die
    URL-Pruefung durch und JEDER Aufruf endet in 400 - die Tests unten
    haetten dann gar nichts mit dem Abo-Besitz zu tun."""
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))])


def _abo(client, token, endpoint=ENDPUNKT, geraet="Familien-Tablet"):
    return client.post("/push/subscribe", json={
        "token": token, "geraet": geraet,
        "subscription": {
            "endpoint": endpoint,
            "keys": {"p256dh": "schluessel-" + geraet, "auth": "auth-" + geraet},
        },
    })


def _zeilen(db, endpoint=ENDPUNKT):
    return db["verbindung"].execute(
        "SELECT * FROM push_abos WHERE endpoint=?", (endpoint,)).fetchall()


def test_wer_sich_zuletzt_ausweist_bekommt_das_geraet(client, db, admin, eltern):
    _abo(client, admin["tokens"]["hilfe"])
    _abo(client, eltern["tokens"]["hilfe"])

    zeilen = _zeilen(db)
    assert len(zeilen) == 1, "endpoint ist UNIQUE - es darf nur eine Zeile geben"
    assert zeilen[0]["user_id"] == eltern["id"], (
        "Das Abo haengt noch am Erstbesitzer - das zweite Konto bekommt dessen "
        "Benachrichtigungen und selbst keine."
    )


def test_der_erste_bekommt_hier_nichts_mehr(client, db, admin, eltern):
    """Die andere Hälfte desselben Fehlers: Nach dem Wechsel darf an DIESEM
    Gerät nichts mehr für den Erstbesitzer liegen."""
    _abo(client, admin["tokens"]["hilfe"])
    _abo(client, eltern["tokens"]["hilfe"])

    fuer_admin = db["verbindung"].execute(
        "SELECT COUNT(*) c FROM push_abos WHERE user_id=?", (admin["id"],)).fetchone()["c"]
    assert fuer_admin == 0


def test_geraetename_und_schluessel_wandern_mit(client, db, admin, eltern):
    """Sonst bliebe die Zeile halb beim alten Besitzer: neue Person, alte
    Schlüssel - und die Zustellung schlüge fehl."""
    _abo(client, admin["tokens"]["hilfe"], geraet="Andis Handy")
    _abo(client, eltern["tokens"]["hilfe"], geraet="Simones Handy")

    zeile = _zeilen(db)[0]
    assert zeile["geraet"] == "Simones Handy"
    assert zeile["p256dh"] == "schluessel-Simones Handy"
    assert zeile["auth"] == "auth-Simones Handy"


def test_eigene_geraete_bleiben_getrennt(client, db, admin, eltern):
    """Gegenprobe: Der Fix darf nicht dazu führen, dass zwei verschiedene
    Geräte zusammenfallen. Getrennte Endpunkte bleiben getrennte Abos."""
    _abo(client, admin["tokens"]["hilfe"], endpoint=ENDPUNKT + "-a")
    _abo(client, eltern["tokens"]["hilfe"], endpoint=ENDPUNKT + "-b")

    alle = db["verbindung"].execute(
        "SELECT user_id, endpoint FROM push_abos ORDER BY endpoint").fetchall()
    assert len(alle) == 2
    assert {z["user_id"] for z in alle} == {admin["id"], eltern["id"]}


def test_erneutes_abo_derselben_person_aendert_nichts_am_besitz(client, db, admin):
    """Der Normalfall - der Browser meldet sein Abo bei jedem Start neu an."""
    _abo(client, admin["tokens"]["hilfe"])
    _abo(client, admin["tokens"]["hilfe"])

    zeilen = _zeilen(db)
    assert len(zeilen) == 1 and zeilen[0]["user_id"] == admin["id"]


def test_ohne_ausweis_wird_gar_nichts_uebernommen(client, db, admin):
    """Ein fremder Aufruf ohne gueltigen Token darf das Geraet nicht an sich
    ziehen - sonst waere aus dem Alltagsfehler ein Angriffsweg geworden."""
    _abo(client, admin["tokens"]["hilfe"])
    antwort = _abo(client, "unsinn")

    assert antwort.status_code == 403
    assert _zeilen(db)[0]["user_id"] == admin["id"]
