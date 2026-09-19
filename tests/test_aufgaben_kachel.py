"""Aufgaben (neu), Schritt 4 (Wunsch #300) - Kacheln und "Person wechseln".

Spezifikation 5.4: Tipp = spontaner erledigter Termin mit getippt_von;
"N x heute" und "- zurueck" (Kinder: eigener Tipp, nur heute, der letzte;
Eltern: jeder); ein Tipp hakt einen heute offenen Termin derselben Aufgabe
ab statt eine Dublette zu erzeugen; der Fallback-POST traegt die Zielperson;
Kacheln fuellen den Tagesbalken nicht, zaehlen aber Punkte.
"""
import pytest
from teile.aufgaben import aufgabe_neu, kacheln_daten
from teile.kern import heute_lokal, new_token, token_lookup

JSON = {"Accept": "application/json"}


@pytest.fixture()
def fam(app, db):
    v = db["verbindung"]
    app_id = v.execute("SELECT id FROM apps WHERE slug='aufgaben'").fetchone()["id"]
    f = {}
    with app.app_context():
        for name, daten in db["familie"].items():
            tok = new_token()
            v.execute("INSERT INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                      (daten["id"], app_id, token_lookup(tok)))
            f[name] = {"row": v.execute("SELECT * FROM users WHERE id=?", (daten["id"],)).fetchone(),
                       "tok": tok, "id": daten["id"]}
    v.commit()
    return {"v": v, **f}


def _url(p, rest=""):
    return f"/a/aufgaben/{p['tok']}/{rest}"


@pytest.fixture()
def kachel(app, fam):
    """Eine Kachel 'Tisch abraeumen' (1,5 Punkte) der Eltern, ohne Termin."""
    with app.app_context():
        return aufgabe_neu(fam["v"], fam["TestEltern"]["row"], "Tisch abräumen", wann=None,
                           kachel=1, punkte=1.5, push=False)["aufgabe_id"]


def test_kind_tippt_zaehlt_und_nimmt_zurueck(app, client, fam, kachel):
    kind = fam["TestKind"]
    text = client.get(_url(kind)).get_data(as_text=True)
    assert "Sonst noch geholfen?" in text and "Tisch abräumen" in text and "+1,5" in text
    d = client.post(_url(kind, f"kachel/{kachel}/tippen"), headers=JSON).get_json()
    assert d["ok"] and d["heute"] == 1 and d["zurueck"] is True
    assert d["punkte_woche"] == "1,5" and d["gesamt"] == 0   # Balken bleibt leer (5.4)
    d = client.post(_url(kind, f"kachel/{kachel}/tippen"), headers=JSON).get_json()
    assert d["heute"] == 2 and d["punkte_woche"] == "3"
    text = client.get(_url(kind)).get_data(as_text=True)
    assert "2× heute" in text and "− zurück" in text
    t = fam["v"].execute("SELECT * FROM termine WHERE spontan=1 ORDER BY id DESC LIMIT 1").fetchone()
    assert (t["user_id"], t["erledigt_von"], t["getippt_von"], t["status"], t["punkte"]) == \
           (kind["id"], kind["id"], kind["id"], "erledigt", 1.5)
    assert t["tag"] == t["erledigt_tag"] == heute_lokal()
    d = client.post(_url(kind, f"kachel/{kachel}/zurueck"), headers=JSON).get_json()
    assert d["heute"] == 1 and d["punkte_woche"] == "1,5"
    assert fam["v"].execute("SELECT COUNT(*) FROM termine WHERE spontan=1").fetchone()[0] == 1


def test_zurueck_nur_eigener_tipp_von_heute(app, client, fam, kachel):
    kind, eltern = fam["TestKind"], fam["TestEltern"]
    # Eltern tippen FUER das Kind (Person wechseln) -> getippt_von = Eltern
    d = client.post(_url(eltern, f"kachel/{kachel}/tippen"), data={"fuer": kind["id"]}, headers=JSON).get_json()
    assert d["ok"] and d["heute"] == 1 and d["zurueck"] is True
    t = fam["v"].execute("SELECT * FROM termine WHERE spontan=1").fetchone()
    assert t["user_id"] == kind["id"] and t["getippt_von"] == eltern["id"]
    # Das Kind sieht den Eintrag, darf ihn aber nicht zuruecknehmen (nicht sein Tipp)
    assert kacheln_daten(fam["v"], kind["row"], kind["row"])[0]["zurueck"] is False
    assert client.post(_url(kind, f"kachel/{kachel}/zurueck"), headers=JSON).status_code == 403
    # gestriger eigener Tipp: auch nicht
    fam["v"].execute("UPDATE termine SET getippt_von=?, erledigt_tag=date(?, '-1 day'), tag=date(?, '-1 day') WHERE id=?",
                     (kind["id"], heute_lokal(), heute_lokal(), t["id"]))
    fam["v"].commit()
    d = client.post(_url(kind, f"kachel/{kachel}/zurueck"), headers=JSON).get_json()
    assert d["ok"] and d["heute"] == 0     # nichts von heute -> nichts passiert
    assert fam["v"].execute("SELECT COUNT(*) FROM termine WHERE spontan=1").fetchone()[0] == 1
    # Eltern duerfen jeden - aber nur heutige werden gesucht
    fam["v"].execute("UPDATE termine SET erledigt_tag=?, tag=? WHERE id=?", (heute_lokal(), heute_lokal(), t["id"]))
    fam["v"].commit()
    d = client.post(_url(eltern, f"kachel/{kachel}/zurueck"), data={"fuer": kind["id"]}, headers=JSON).get_json()
    assert d["heute"] == 0
    assert fam["v"].execute("SELECT COUNT(*) FROM termine WHERE spontan=1").fetchone()[0] == 0


def test_tipp_hakt_geplanten_termin_statt_dublette(app, client, fam, kachel):
    kind, eltern = fam["TestKind"], fam["TestEltern"]
    with app.app_context():
        a = aufgabe_neu(fam["v"], eltern["row"], "Ignoriert", push=False)
    # dieselbe Kachel-Aufgabe steht heute als offener Termin des Kindes
    from teile.aufgaben import termin_neu
    with app.app_context():
        tid = termin_neu(fam["v"], kachel, "heute", user_id=kind["id"])
    fam["v"].commit()
    d = client.post(_url(kind, f"kachel/{kachel}/tippen"), headers=JSON).get_json()
    assert d["ok"]
    t = fam["v"].execute("SELECT * FROM termine WHERE id=?", (tid,)).fetchone()
    assert t["status"] == "erledigt" and t["spontan"] == 0 and t["punkte"] == 1.5
    assert fam["v"].execute("SELECT COUNT(*) FROM termine WHERE spontan=1").fetchone()[0] == 0
    assert d["geschafft"] == 1 and d["gesamt"] == 1       # geplanter Termin fuellt den Balken
    del a


def test_sortierung_nach_haeufigkeit_und_pausiert(app, client, fam, kachel):
    kind, eltern = fam["TestKind"], fam["TestEltern"]
    with app.app_context():
        b = aufgabe_neu(fam["v"], eltern["row"], "Wäsche legen", wann=None, kachel=1, punkte=1, push=False)["aufgabe_id"]
        c = aufgabe_neu(fam["v"], eltern["row"], "Alt", wann=None, kachel=1, punkte=1, push=False)["aufgabe_id"]
    fam["v"].execute("UPDATE aufgaben SET pausiert=1 WHERE id=?", (c,))
    fam["v"].commit()
    for _ in range(2):
        client.post(_url(kind, f"kachel/{b}/tippen"), headers=JSON)
    namen = [k["inhalt"] for k in kacheln_daten(fam["v"], kind["row"], kind["row"])]
    assert namen == ["Wäsche legen", "Tisch abräumen"]     # pausiert fehlt, haeufig zuerst


def test_fallback_post_traegt_zielperson(app, client, fam, kachel):
    """Ohne JavaScript: normaler POST mit `fuer`, Weiterleitung zurueck auf
    die Heute-Seite DER PERSON (Fehler des Altbestands nicht wiederholen)."""
    kind, eltern = fam["TestKind"], fam["TestEltern"]
    text = client.get(_url(eltern, f"?fuer={kind['id']}")).get_data(as_text=True)
    assert f'<input type="hidden" name="fuer" value="{kind["id"]}">' in text
    r = client.post(_url(eltern, f"kachel/{kachel}/tippen"), data={"fuer": kind["id"]})
    assert r.status_code == 302 and f"?fuer={kind['id']}" in r.headers["Location"]
    t = fam["v"].execute("SELECT user_id FROM termine WHERE spontan=1").fetchone()
    assert t["user_id"] == kind["id"]


def test_person_wechseln_nur_eltern(app, client, fam):
    kind, eltern = fam["TestKind"], fam["TestEltern"]
    text = client.get(_url(eltern)).get_data(as_text=True)
    assert 'aria-label="Person wechseln"' in text and f"?fuer={kind['id']}" in text
    text = client.get(_url(kind)).get_data(as_text=True)
    assert 'aria-label="Person wechseln"' not in text


def test_gast_darf_keine_kachel_tippen(app, client, fam, kachel):
    v = fam["v"]
    app_id = v.execute("SELECT id FROM apps WHERE slug='aufgaben'").fetchone()["id"]
    tok = new_token()
    with app.app_context():
        gid = v.execute("INSERT INTO users(name, farbe, is_admin, rolle) VALUES('Gast','#555555',0,'gast') RETURNING id").fetchone()["id"]
        v.execute("INSERT INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)", (gid, app_id, token_lookup(tok)))
    v.commit()
    assert client.post(f"/a/aufgaben/{tok}/kachel/{kachel}/tippen", headers=JSON).status_code == 403
