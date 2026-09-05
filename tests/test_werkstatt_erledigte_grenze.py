"""Wunsch #240: Die Werkstatt rendert nicht mehr alle erledigten Wuensche.

Live gemessen am 31.08.2026: 230 erledigte Wuensche ergaben eine 51.781px
hohe Seite mit 1.214 interaktiven Elementen. Standard sind jetzt die letzten
15, `?erledigt=alle` holt weiterhin bewusst alles (Browsersuche, Filter).
"""
import pytest
from teile.kern import new_token, token_lookup


@pytest.fixture()
def werkstatt_token(app, db):
    v = db["verbindung"]
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='werkstatt'").fetchone()["id"]
        klartext = new_token()
        v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) "
                  "VALUES(?,?,?)",
                  (db["familie"]["TestAdmin"]["id"], app_id, token_lookup(klartext)))
        v.commit()
    return klartext


def _erledigte(v, anzahl):
    for i in range(anzahl):
        v.execute(
            "INSERT INTO wuensche(text, erledigt, erledigt_am) VALUES(?, 1, ?)",
            (f"Erledigter Wunsch {i}", f"2026-01-{(i % 28) + 1:02d} 10:00:00"))
    v.commit()


def test_standard_zeigt_hoechstens_15_erledigte(client, db, werkstatt_token):
    _erledigte(db["verbindung"], 20)
    text = client.get(f"/a/werkstatt/{werkstatt_token}/").get_data(as_text=True)
    assert text.count('class="wunsch-card done"') == 15
    assert "Alle 20 erledigten Wünsche anzeigen" in text


def test_kopfzeile_nennt_trotzdem_die_gesamtzahl(client, db, werkstatt_token):
    """Sonst saehe es aus, als waeren Wuensche verschwunden."""
    _erledigte(db["verbindung"], 20)
    text = client.get(f"/a/werkstatt/{werkstatt_token}/").get_data(as_text=True)
    assert "20 erledigt" in text


def test_erledigt_alle_holt_wirklich_alle(client, db, werkstatt_token):
    _erledigte(db["verbindung"], 20)
    text = client.get(
        f"/a/werkstatt/{werkstatt_token}/?erledigt=alle").get_data(as_text=True)
    assert text.count('class="wunsch-card done"') == 20
    assert "erledigten Wünsche anzeigen" not in text


def test_unter_der_grenze_gibt_es_keinen_nachlade_link(client, db, werkstatt_token):
    """Ein Link, der dieselbe Seite nochmal laedt, waere nur verwirrend."""
    _erledigte(db["verbindung"], 3)
    text = client.get(f"/a/werkstatt/{werkstatt_token}/").get_data(as_text=True)
    assert text.count('class="wunsch-card done"') == 3
    assert "erledigten Wünsche anzeigen" not in text
