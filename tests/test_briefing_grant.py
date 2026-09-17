"""Wunsch #292 (Sicherheitsaudit 16.09.2026, Befund N-14): Das Briefing
zeigte den Essensplan unabhängig vom Essensplan-Grant.

`briefing_fuer()` las `essensplan_eintraege` ohne zu fragen, ob der Nutzer die
App überhaupt hat; `_home_user()` verlangt nur den home-Grant. Ein Nutzer, dem
Andi den Essensplan bewusst nicht gegeben hatte, sah Mittag und Abend trotzdem
auf der Startseite. Fachlich harmlos, aber die erste Stelle, an der ein
App-Grant nicht mehr entschied, wer was sieht.
"""
import importlib
from datetime import datetime

import pytest
from teile.kern import LOKAL_TZ


@pytest.fixture()
def modul(app):
    return importlib.import_module("teile.27_briefing")


def _grant(app, db, user_id, slug):
    from teile.kern import new_token, token_lookup
    v = db["verbindung"]
    app_id = v.execute("SELECT id FROM apps WHERE slug=?", (slug,)).fetchone()["id"]
    with app.app_context():                     # token_lookup braucht TOKEN_KEY
        lookup = token_lookup(new_token())
    v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
              (user_id, app_id, lookup))
    v.commit()


def test_ohne_essensplan_grant_kein_essen_im_briefing(app, db, kind, modul):
    v = db["verbindung"]
    jetzt = datetime(2026, 9, 17, 8, 0, tzinfo=LOKAL_TZ)
    v.execute("INSERT INTO essensplan_eintraege (tag, mahlzeit, text) VALUES (?,?,?)",
              (jetzt.date().isoformat(), modul.MAHLZEITEN[0], "Nudeln"))
    v.commit()

    with app.app_context():
        ohne = modul.briefing_fuer(v, kind["id"], jetzt)
    assert ohne["essensplan"] is False
    assert ohne["mahlzeiten"] == []
    assert "Nudeln" not in modul.push_text(ohne)

    _grant(app, db, kind["id"], "essensplan")
    with app.app_context():
        mit = modul.briefing_fuer(v, kind["id"], jetzt)
    assert mit["essensplan"] is True
    assert any(m["text"] == "Nudeln" for m in mit["mahlzeiten"])
    assert "Nudeln" in modul.push_text(mit)


def test_startseite_zeigt_den_essen_block_nur_mit_grant(app, client, db, kind):
    v = db["verbindung"]
    v.execute("INSERT INTO essensplan_eintraege (tag, mahlzeit, text) VALUES (date('now'), 'mittag', 'Nudeln')")
    v.commit()
    tok = kind["tokens"]["home"]
    seite = client.get(f"/p/{tok}", follow_redirects=True).get_data(as_text=True)
    assert "Essen heute" not in seite
    _grant(app, db, kind["id"], "essensplan")
    seite = client.get(f"/p/{tok}", follow_redirects=True).get_data(as_text=True)
    assert "Essen heute" in seite
