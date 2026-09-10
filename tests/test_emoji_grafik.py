"""Wunsch #275: Emoji aus Nutzereingaben brauchen ebenfalls eine lokale Grafik.

`test_emoji.py` prueft Vorlagen und Quelltext - das Zauberstab-Emoji fuer
"Staubwischen" kam aber ueber das Verwaltungsformular in die Datenbank und
lief daran vorbei: auf dem PC (Linux/Chrome ohne Emoji-Schrift) blieb die
Kachel leer. Jetzt prueft der Server beim Anlegen einer Aufgabe dieselbe
Frage wie der Test, und die Verwaltung markiert bestehende Aufgaben ohne
Grafik.
"""
import os

import pytest
from teile.kern import TWEMOJI_SVG_DIR, emoji_grafik_vorhanden, twemoji_datei


def test_dateiname_wie_twemoji():
    assert twemoji_datei("🪄") == "1fa84.svg"
    assert twemoji_datei("🍽️") == "1f37d.svg", "fe0f faellt ohne ZWJ weg"
    assert twemoji_datei("👨‍👩‍👧") == "1f468-200d-1f469-200d-1f467.svg"
    assert twemoji_datei("❤️‍🔥") == "2764-fe0f-200d-1f525.svg", "mit ZWJ bleibt fe0f"


def test_zauberstab_hat_jetzt_eine_grafik():
    assert os.path.isfile(os.path.join(TWEMOJI_SVG_DIR, "1fa84.svg"))
    assert emoji_grafik_vorhanden("🪄")


def test_vorhanden_und_fehlend():
    assert emoji_grafik_vorhanden("🍽️")
    assert emoji_grafik_vorhanden("")
    assert emoji_grafik_vorhanden("Text ohne Emoji 12")
    assert not emoji_grafik_vorhanden("\U0001FAE0"), "schmelzendes Gesicht ist nicht gebuendelt"
    assert not emoji_grafik_vorhanden("🍽️\U0001FAE0"), "ein fehlendes reicht"


@pytest.fixture()
def admin_token(app, db):
    from teile.kern import new_token, token_lookup
    v = db["verbindung"]
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='geholfen'").fetchone()["id"]
        t = new_token()
        v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                  (db["familie"]["TestAdmin"]["id"], app_id, token_lookup(t)))
        v.commit()
    return t


def test_aufgabe_mit_fehlender_grafik_wird_abgelehnt(client, db, admin_token):
    vorher = db["verbindung"].execute("SELECT COUNT(*) FROM geholfen_aufgaben").fetchone()[0]
    r = client.post(f"/a/geholfen/{admin_token}/aufgaben",
                    data={"action": "neu", "name": "Schmelzen", "emoji": "\U0001FAE0"})
    assert r.status_code == 302 and "fehler=emoji" in r.headers["Location"]
    assert db["verbindung"].execute("SELECT COUNT(*) FROM geholfen_aufgaben").fetchone()[0] == vorher
    seite = client.get(r.headers["Location"]).get_data(as_text=True)
    assert 'role="alert"' in seite and "keine Grafik" in seite
    assert 'value="Schmelzen"' in seite, "der Name bleibt im Formular stehen"


def test_aufgabe_mit_grafik_wird_angelegt(client, db, admin_token):
    r = client.post(f"/a/geholfen/{admin_token}/aufgaben",
                    data={"action": "neu", "name": "Staubwischen", "emoji": "🪄"})
    assert r.status_code == 302 and "fehler" not in r.headers["Location"]
    row = db["verbindung"].execute("SELECT emoji FROM geholfen_aufgaben WHERE name='Staubwischen'").fetchone()
    assert row["emoji"] == "🪄"


def test_verwaltung_markiert_aufgaben_ohne_grafik(client, db, admin_token):
    v = db["verbindung"]
    v.execute("INSERT INTO geholfen_aufgaben(name, emoji, gewichtung) VALUES('Alt', ?, 1)", ("\U0001FAE0",))
    v.commit()
    seite = client.get(f"/a/geholfen/{admin_token}/aufgaben").get_data(as_text=True)
    assert seite.count("Emoji ohne Grafik") == 1
