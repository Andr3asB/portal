"""Wunsch #204 (Sicherheitsaudit 11.08.2026): POST /wunsch verlangt jetzt
eine erkennbare Identität.

Vorher führte ein fehlendes oder ungültiges Token NICHT zu 403, sondern zu
einem anonym gespeicherten Wunsch (user_id NULL) - laut Docstring bewusst so
gebaut ("ein anonymer Wunsch ist besser als ein verlorener"), aber ohne jede
Grant-Prüfung. Erreichbar war die Route ohne jede Anmeldung: "/" liefert
öffentlich (Status 200) denied.html aus - jeder, der die Adresse kennt,
konnte von dort `fetch('/wunsch', ...)` aufrufen, ganz ohne je ein gültiges
Token gehabt zu haben.

Die eigentliche Aussage dieser Datei: Wer schon einmal erfolgreich EINE App
geöffnet hat (also ein Sitzungs-Cookie besitzt), kann weiterhin Wünsche
einreichen - für sie ändert sich nichts, weil `aktueller_nutzer()` sie
findet. Blockiert wird nur, wer weder Token noch Cookie mitbringt.
"""
import pytest


def test_ohne_token_und_ohne_cookie_gibt_es_403(client, db):
    """Der eigentliche Befund: nichts, was auf eine Identität hindeutet."""
    antwort = client.post("/wunsch", json={"text": "Spam-Versuch"})
    assert antwort.status_code == 403
    assert db["verbindung"].execute(
        "SELECT COUNT(*) FROM wuensche WHERE text='Spam-Versuch'"
    ).fetchone()[0] == 0


def test_ungueltiges_token_gibt_ebenfalls_403(client, db):
    """Ein erfundenes Token ist keine Identität, egal wie lang."""
    antwort = client.post("/wunsch", json={
        "text": "Erfundenes Token", "token": "x" * 24})
    assert antwort.status_code == 403
    assert db["verbindung"].execute(
        "SELECT COUNT(*) FROM wuensche WHERE text='Erfundenes Token'"
    ).fetchone()[0] == 0


def test_gueltiges_token_funktioniert_weiterhin(client, db):
    """Für die eigentliche Zielgruppe - Familienmitglieder mit Zugang zu
    irgendeiner App - darf sich nichts ändern."""
    token = db["familie"]["TestKind"]["tokens"]["hilfe"]
    antwort = client.post("/wunsch", json={"text": "Echter Wunsch", "token": token})
    assert antwort.status_code == 200
    zeile = db["verbindung"].execute(
        "SELECT user_id FROM wuensche WHERE text='Echter Wunsch'").fetchone()
    assert zeile is not None
    assert zeile["user_id"] == db["familie"]["TestKind"]["id"]


def test_jeder_gespeicherte_wunsch_hat_jetzt_einen_urheber(client, db):
    """Die Kehrseite der Reparatur: eine echte Anonymität (user_id NULL)
    gibt es nicht mehr - wer speichert, ist immer bekannt."""
    token = db["familie"]["TestAdmin"]["tokens"]["hilfe"]
    client.post("/wunsch", json={"text": "Mit Urheber", "token": token})
    zeile = db["verbindung"].execute(
        "SELECT user_id FROM wuensche WHERE text='Mit Urheber'").fetchone()
    assert zeile["user_id"] is not None
