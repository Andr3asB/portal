"""Wunsch #172: Darstellung folgt auf Wunsch dem Gerät.

Drei Zustände: 0 = immer hell, 1 = immer dunkel, 2 = wie das Gerät.

Der heikle Teil ist nicht das Umschalten, sondern **dass die dunklen Farben
nur an einer Stelle stehen**. Zwei getippte Blöcke (einer für `body.dark`,
einer für die Automatik) wären genau die Bauart, bei der jemand einen Farbwert
nur an einer Stelle nachzieht – und der Unterschied fiele monatelang niemandem
auf, weil kaum jemand beide Modi nebeneinander sieht.

Bestehende Konten werden bewusst NICHT migriert: Das würde die Einstellung
anderer Familienmitglieder ohne Rückfrage ändern. Neue Konten starten auf
Automatik (Spalten-Default), alle anderen tippen einmal.
"""

import pytest


def _seite(client, token):
    return client.get(f"/a/hilfe/{token}/").get_data(as_text=True)


@pytest.fixture()
def hilfe_token(db):
    return db["familie"]["TestAdmin"]["tokens"]["hilfe"]


def _setze(db, modus, name="TestAdmin"):
    v = db["verbindung"]
    v.execute("UPDATE users SET dark_mode=? WHERE id=?",
              (modus, db["familie"][name]["id"]))
    v.commit()


# --- Die drei Zustände landen als Körperklasse ----------------------------

@pytest.mark.parametrize("modus,klasse", [(0, ""), (1, "dark"), (2, "auto")])
def test_koerperklasse_je_modus(client, db, hilfe_token, modus, klasse):
    _setze(db, modus)
    seite = _seite(client, hilfe_token)
    assert f'<body class="{klasse}">' in seite, f"modus={modus}"


def test_automatik_haengt_an_der_medienabfrage(client, db, hilfe_token):
    """`body.auto` darf NUR im Dunkelmodus des Geräts greifen – stünde es
    ausserhalb der Medienabfrage, wäre die Automatik in Wahrheit ein
    Dauer-Dunkelmodus."""
    _setze(db, 2)
    seite = _seite(client, hilfe_token)
    block = seite[seite.index("@media (prefers-color-scheme: dark)"):]
    block = block[:block.index("}\n    }") + 6]
    assert "body.auto" in block


def test_dunkle_farben_stehen_nur_einmal_im_quelltext(client, db, hilfe_token):
    """Der eigentliche Wächter dieser Änderung. Die Werte werden aus EINER
    Jinja-Variablen zweimal ausgegeben; im gerenderten HTML stehen sie
    deshalb zweimal, in der VORLAGE aber nur einmal."""
    import pathlib
    vorlage = (pathlib.Path(__file__).resolve().parents[1] / "src" / "teile"
               / "templates" / "base.html").read_text(encoding="utf-8")
    assert vorlage.count("--bar-bg:        rgba(28,28,30,.92)") == 1, (
        "Die dunklen Farbwerte stehen mehrfach in base.html - sie laufen "
        "auseinander, sobald jemand nur eine Stelle anfasst."
    )
    # ... und im Ergebnis trotzdem fuer beide Faelle
    _setze(db, 2)
    seite = _seite(client, hilfe_token)
    assert seite.count("--bar-bg:        rgba(28,28,30,.92)") == 2


# --- Umschalten ------------------------------------------------------------

@pytest.mark.parametrize("vorher,nachher", [(2, 0), (0, 1), (1, 2)])
def test_schalter_geht_im_kreis(client, db, hilfe_token, vorher, nachher):
    """Automatik -> immer hell -> immer dunkel -> Automatik. Die Automatik
    steht am Anfang des Kreises, weil sie der Normalfall ist."""
    _setze(db, vorher)
    antwort = client.post("/settings/darkmode", json={"token": hilfe_token})
    assert antwort.get_json()["modus"] == nachher
    assert db["verbindung"].execute(
        "SELECT dark_mode FROM users WHERE id=?",
        (db["familie"]["TestAdmin"]["id"],)).fetchone()["dark_mode"] == nachher


def test_altes_dark_feld_bleibt_erhalten(client, db, hilfe_token):
    """Eine ältere PWA im Cache wertet noch `dark` aus. Für sie sieht
    „wie das Gerät" wie „hell" aus – der harmlosere der beiden Irrtümer."""
    _setze(db, 0)
    assert client.post("/settings/darkmode",
                       json={"token": hilfe_token}).get_json()["dark"] is True
    assert client.post("/settings/darkmode",
                       json={"token": hilfe_token}).get_json()["dark"] is False


def test_ohne_zugang_kein_umschalten(client, db):
    assert client.post("/settings/darkmode", json={"token": "unsinn"}).status_code == 403


def test_neue_konten_starten_auf_automatik(app, db):
    """Der Spalten-Default. Bestehende Konten werden bewusst nicht migriert -
    das aendert die Einstellung anderer ohne Rueckfrage."""
    v = db["verbindung"]
    uid = v.execute(
        "INSERT INTO users(name, farbe) VALUES('Neu','#123456') RETURNING id"
    ).fetchone()["id"]
    v.commit()
    assert v.execute("SELECT dark_mode FROM users WHERE id=?",
                     (uid,)).fetchone()["dark_mode"] == 2
