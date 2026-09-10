"""Wunsch #279: Badge auf der Werkstatt-Kachel mit der Zahl der offenen
Wuensche ohne Prioritaet (1-9, sonst 9+). Nur fuer Admins - nur ein Mensch
vergibt Prioritaeten (#152), und das ist der Admin."""
import pytest


@pytest.fixture()
def werkstatt(app, db):
    from teile.kern import new_token, token_lookup
    v = db["verbindung"]
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='werkstatt'").fetchone()["id"]
        for name in ("TestAdmin", "TestKind"):
            v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                      (db["familie"][name]["id"], app_id, token_lookup(new_token())))
        v.commit()
    return v


def _wunsch(v, prioritaet=None, erledigt=0):
    v.execute("INSERT INTO wuensche(text, app_slug, prioritaet, erledigt) VALUES('x', 'home', ?, ?)",
              (prioritaet, erledigt))
    v.commit()


def test_kein_badge_ohne_unpriorisierte(client, werkstatt, admin):
    _wunsch(werkstatt, "hoch")
    _wunsch(werkstatt, None, erledigt=1)
    seite = client.get(f"/p/{admin['tokens']['home']}").get_data(as_text=True)
    assert 'class="tile-badge"' not in seite


def test_badge_zaehlt_nur_offene_ohne_prioritaet(client, werkstatt, admin):
    _wunsch(werkstatt, None)
    _wunsch(werkstatt, "")
    _wunsch(werkstatt, "mittel")
    _wunsch(werkstatt, None, erledigt=1)
    seite = client.get(f"/p/{admin['tokens']['home']}").get_data(as_text=True)
    assert seite.count('class="tile-badge"') == 1
    assert 'aria-label="2 Wünsche ohne Priorität">2</span>' in seite


def test_ab_zehn_steht_neun_plus(client, werkstatt, admin):
    for _ in range(10):
        _wunsch(werkstatt, None)
    seite = client.get(f"/p/{admin['tokens']['home']}").get_data(as_text=True)
    assert 'aria-label="10 Wünsche ohne Priorität">9+</span>' in seite


def test_kinder_sehen_kein_badge(client, werkstatt, kind):
    _wunsch(werkstatt, None)
    seite = client.get(f"/p/{kind['tokens']['home']}").get_data(as_text=True)
    assert "Werkstatt" in seite and 'class="tile-badge"' not in seite
