"""Aufgaben (neu), Kiosk-Konto (Wunsch #300, Entscheidung 15.2 / Abschnitt 5.7).

Ein eigenes Konto mit Rolle `kiosk`. Es sieht nur sicht='alle', beginnt
immer mit der Personenwahl, darf fuer die gewaehlte Person abhaken, "Ich
mach's" und Kacheln tippen ("- zurueck" nur eigene Tipps von heute). Alles
andere existiert fuer dieses Konto nicht: 404, nicht 403. Keine Reiter.
"""
import pytest
from teile.aufgaben import aufgabe_neu
from teile.kern import heute_lokal, new_token, token_lookup

JSON = {"Accept": "application/json"}


@pytest.fixture()
def fam(app, db):
    v = db["verbindung"]
    app_id = v.execute("SELECT id FROM apps WHERE slug='aufgaben'").fetchone()["id"]
    f = {}
    with app.app_context():
        kid = v.execute("INSERT INTO users(name, farbe, is_admin, rolle) VALUES('Esszimmer','#777777',0,'kiosk') RETURNING id").fetchone()["id"]
        alle = dict(db["familie"])
        alle["Kiosk"] = {"id": kid}
        for name, daten in alle.items():
            tok = new_token()
            v.execute("INSERT INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                      (daten["id"], app_id, token_lookup(tok)))
            f[name] = {"row": v.execute("SELECT * FROM users WHERE id=?", (daten["id"],)).fetchone(),
                       "tok": tok, "id": daten["id"]}
    v.commit()
    return {"v": v, **f}


def _url(p, rest=""):
    return f"/a/aufgaben/{p['tok']}/{rest}"


def test_einstieg_ist_die_personenwahl(app, client, fam):
    kiosk, kind = fam["Kiosk"], fam["TestKind"]
    text = client.get(_url(kiosk)).get_data(as_text=True)
    assert "Wer bist du?" in text and f"?fuer={kind['id']}" in text and "TestEltern" in text
    assert "Esszimmer" not in text.split("<main", 1)[1]          # das Kiosk-Konto selbst ist keine Person
    assert '<nav class="reiter"' not in text
    # ungueltige oder fehlende Person -> wieder Personenwahl
    assert "Wer bist du?" in client.get(_url(kiosk, "?fuer=999999")).get_data(as_text=True)


def test_nur_sicht_alle_und_keine_reiter(app, client, fam):
    kiosk, kind, eltern = fam["Kiosk"], fam["TestKind"], fam["TestEltern"]
    with app.app_context():
        aufgabe_neu(fam["v"], eltern["row"], "Für alle sichtbar", ziel_user=kind["id"], sicht="alle", push=False)
        aufgabe_neu(fam["v"], eltern["row"], "Nur Kinder", ziel_user=kind["id"], sicht="kinder", push=False)
        aufgabe_neu(fam["v"], kind["row"], "Nur ich", sicht="ich", push=False)
    text = client.get(_url(kiosk, f"?fuer={kind['id']}")).get_data(as_text=True)
    assert "Hallo TestKind" in text and "Für alle sichtbar" in text
    assert "Nur Kinder" not in text and "Nur ich" not in text
    assert "0 von 1 geschafft" in text
    assert '<nav class="reiter"' not in text and "+ Eigene Aufgabe" not in text and "✏️" not in text
    assert "Person wechseln" in text and "Morgen:" not in text
    assert f'name="fuer" value="{kind["id"]}"' in text


def test_haken_fuer_die_gewaehlte_person(app, client, fam):
    kiosk, kind, eltern = fam["Kiosk"], fam["TestKind"], fam["TestEltern"]
    with app.app_context():
        a = aufgabe_neu(fam["v"], eltern["row"], "Tisch decken", ziel_user=kind["id"], punkte=1, push=False)
        b = aufgabe_neu(fam["v"], eltern["row"], "Elternding", push=False)
    # ohne Person -> 400
    assert client.post(_url(kiosk, f"termin/{a['termin_id']}/haken"), headers=JSON).status_code == 400
    # falsche Person (Termin gehoert dem Kind) -> 403
    assert client.post(_url(kiosk, f"termin/{a['termin_id']}/haken"), data={"fuer": eltern["id"]}, headers=JSON).status_code == 403
    d = client.post(_url(kiosk, f"termin/{a['termin_id']}/haken"), data={"fuer": kind["id"]}, headers=JSON).get_json()
    assert d["ok"] and d["erledigt"] and d["geschafft"] == 1 and d["punkte_woche"] == "1"
    t = fam["v"].execute("SELECT * FROM termine WHERE id=?", (a["termin_id"],)).fetchone()
    assert t["erledigt_von"] == kind["id"] and t["user_id"] == kind["id"]
    # ein Termin der Eltern, fuer die Eltern gewaehlt: erlaubt (sicht alle)
    d = client.post(_url(kiosk, f"termin/{b['termin_id']}/haken"), data={"fuer": eltern["id"]}, headers=JSON).get_json()
    assert d["ok"] and d["erledigt"]


def test_kachel_und_zurueck_nur_eigene_tipps_von_heute(app, client, fam):
    kiosk, kind, eltern = fam["Kiosk"], fam["TestKind"], fam["TestEltern"]
    with app.app_context():
        k = aufgabe_neu(fam["v"], eltern["row"], "Tisch abräumen", wann=None, kachel=1, punkte=1, push=False)["aufgabe_id"]
        privat = aufgabe_neu(fam["v"], eltern["row"], "Geheimkachel", wann=None, kachel=1, punkte=1, sicht="eltern", push=False)["aufgabe_id"]
    text = client.get(_url(kiosk, f"?fuer={kind['id']}")).get_data(as_text=True)
    assert "Tisch abräumen" in text and "Geheimkachel" not in text
    assert client.post(_url(kiosk, f"kachel/{privat}/tippen"), data={"fuer": kind["id"]}, headers=JSON).status_code == 404
    d = client.post(_url(kiosk, f"kachel/{k}/tippen"), data={"fuer": kind["id"]}, headers=JSON).get_json()
    assert d["ok"] and d["heute"] == 1 and d["zurueck"] is True
    t = fam["v"].execute("SELECT * FROM termine WHERE spontan=1").fetchone()
    assert (t["user_id"], t["erledigt_von"], t["getippt_von"]) == (kind["id"], kind["id"], kiosk["id"])
    # Tipp von jemand anderem (Eltern-Geraet): fuer den Kiosk nicht zuruecknehmbar
    fam["v"].execute("UPDATE termine SET getippt_von=? WHERE id=?", (eltern["id"], t["id"]))
    fam["v"].commit()
    assert client.post(_url(kiosk, f"kachel/{k}/zurueck"), data={"fuer": kind["id"]}, headers=JSON).status_code == 403
    # gestriger Kiosk-Tipp: auch nicht (nichts von heute -> 0)
    fam["v"].execute("UPDATE termine SET getippt_von=?, erledigt_tag=date(?, '-1 day') WHERE id=?",
                     (kiosk["id"], heute_lokal(), t["id"]))
    fam["v"].commit()
    d = client.post(_url(kiosk, f"kachel/{k}/zurueck"), data={"fuer": kind["id"]}, headers=JSON).get_json()
    assert d["ok"] and d["heute"] == 0
    assert fam["v"].execute("SELECT COUNT(*) FROM termine WHERE spontan=1").fetchone()[0] == 1


def test_ich_machs_fuer_die_person(app, client, fam):
    kiosk, kind, eltern = fam["Kiosk"], fam["TestKind"], fam["TestEltern"]
    with app.app_context():
        frei = aufgabe_neu(fam["v"], eltern["row"], "Altglas", ziel_gruppe="alle", push=False)
        nur_eltern = aufgabe_neu(fam["v"], eltern["row"], "Elternsache", ziel_gruppe="eltern", push=False)
    text = client.get(_url(kiosk, f"?fuer={kind['id']}")).get_data(as_text=True)
    assert "Noch zu haben" in text and "Altglas" in text and "Elternsache" not in text
    assert client.post(_url(kiosk, f"termin/{nur_eltern['termin_id']}/nehmen"), data={"fuer": kind["id"]}, headers=JSON).status_code == 403
    d = client.post(_url(kiosk, f"termin/{frei['termin_id']}/nehmen"), data={"fuer": kind["id"]}, headers=JSON).get_json()
    assert d["ok"] and d["genommen"] and d["user_id"] == kind["id"]


@pytest.mark.parametrize("methode,pfad", [
    ("GET", "neu"), ("POST", "neu"), ("GET", "aufgabe/1"), ("POST", "aufgabe/1/loeschen"),
    ("GET", "spaeter"), ("POST", "spaeter/reihenfolge"), ("POST", "termin/1/parken"),
    ("POST", "termin/1/hervorholen"), ("POST", "termin/1/verlegen"), ("POST", "termin/1/freigeben"),
    ("GET", "familie"), ("GET", "alle"), ("POST", "aufgabe/1/pausieren"),
])
def test_alles_andere_existiert_nicht(app, client, fam, methode, pfad):
    kiosk, eltern = fam["Kiosk"], fam["TestEltern"]
    with app.app_context():
        aufgabe_neu(fam["v"], eltern["row"], "Existiert", push=False)   # id 1 gibt es wirklich
    r = client.open(_url(kiosk, pfad), method=methode, headers=JSON)
    assert r.status_code == 404, (methode, pfad, r.status_code)


def test_kiosk_bekommt_keine_auto_kachel(app, db):
    """_auto_grant_all() ueberspringt die Rolle kiosk - das Esszimmer-Konto
    soll ausser Aufgaben nichts haben."""
    from teile.kern import _auto_grant_all
    v = db["verbindung"]
    kid = v.execute("INSERT INTO users(name, farbe, is_admin, rolle) VALUES('K','#777777',0,'kiosk') RETURNING id").fetchone()["id"]
    v.commit()
    with app.app_context():
        _auto_grant_all(v, "hilfe")
        _auto_grant_all(v, "geburtstage")
    assert v.execute("SELECT COUNT(*) FROM grants WHERE user_id=?", (kid,)).fetchone()[0] == 0
    assert v.execute("SELECT COUNT(*) FROM grants g JOIN apps a ON a.id=g.app_id WHERE a.slug='geburtstage'").fetchone()[0] >= 3
