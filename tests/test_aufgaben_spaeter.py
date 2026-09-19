"""Aufgaben (neu), Schritt 3 (Wunsch #299) - Spaeter, Parken, Hervorholen, Verlegen.

Spezifikation 5.3 und 6.5: Parken nimmt den Tag weg und haengt den Termin ans
Ende der Spaeter-Liste, die Person bleibt; Hervorholen kennt Heute / Diese
Woche (flexibel) / Tag; "Morgen" verlegt; Rechte wie darf_parken (Eltern
alles Sichtbare, Kinder nur selbst angelegte eigene). Jede Antwort traegt den
Rueckweg fuer die Rueckgaengig-Meldung.
"""
from datetime import date, timedelta

import pytest
from teile.aufgaben import aufgabe_neu, seit_text
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


def _termin(v, tid):
    return v.execute("SELECT * FROM termine WHERE id=?", (tid,)).fetchone()


def test_parken_und_hervorholen_mit_rueckweg(app, client, fam):
    kind = fam["TestKind"]
    heute = date.fromisoformat(heute_lokal())
    with app.app_context():
        a = aufgabe_neu(fam["v"], kind["row"], "Fahrrad putzen", wann=(heute - timedelta(days=2)).isoformat(), push=False)
    text = client.get(_url(kind)).get_data(as_text=True)
    assert "Seit 2 Tagen offen" in text and ">Morgen<" in text and ">Parken<" in text
    r = client.post(_url(kind, f"termin/{a['termin_id']}/parken"), headers=JSON)
    d = r.get_json()
    assert r.status_code == 200 and d["ok"]
    assert "geparkt" in d["text"] and d["zurueck"]["url"].endswith(f"/termin/{a['termin_id']}/hervorholen")
    assert d["zurueck"]["daten"]["ziel"] == (heute - timedelta(days=2)).isoformat()
    t = _termin(fam["v"], a["termin_id"])
    assert t["status"] == "geparkt" and t["tag"] is None and t["user_id"] == kind["id"] and t["geparkt_am"]
    # weg von Heute, da auf Spaeter
    assert "Fahrrad putzen" not in client.get(_url(kind)).get_data(as_text=True)
    spaeter = client.get(_url(kind, "spaeter")).get_data(as_text=True)
    assert "Fahrrad putzen" in spaeter and "Geparkt seit heute" in spaeter and "Hervorholen" in spaeter
    assert '<span id="geparkt-zahl">1</span>' in spaeter
    # Rueckweg = hervorholen auf den alten Tag
    d = client.post(_url(kind, f"termin/{a['termin_id']}/hervorholen"),
                    data=d["zurueck"]["daten"], headers=JSON).get_json()
    assert d["ok"] and d["tag"] == (heute - timedelta(days=2)).isoformat()
    assert _termin(fam["v"], a["termin_id"])["status"] == "offen"


def test_hervorholen_drei_ziele(app, client, fam):
    eltern = fam["TestEltern"]
    heute = date.fromisoformat(heute_lokal())
    with app.app_context():
        ids = [aufgabe_neu(fam["v"], eltern["row"], f"Geparkt {i}", wann="geparkt", push=False)["termin_id"]
               for i in range(3)]
    for tid, ziel, erwartet in (
        (ids[0], "heute", (heute.isoformat(), 0)),
        (ids[1], "woche", ((heute + timedelta(days=6 - heute.weekday())).isoformat(), 1)),
        (ids[2], (heute + timedelta(days=3)).isoformat(), ((heute + timedelta(days=3)).isoformat(), 0)),
    ):
        d = client.post(_url(eltern, f"termin/{tid}/hervorholen"), data={"ziel": ziel}, headers=JSON).get_json()
        assert d["ok"], (ziel, d)
        t = _termin(fam["v"], tid)
        assert (t["tag"], t["flexibel"], t["status"]) == (*erwartet, "offen")
    # ungueltiges Ziel: JSON-Fehler, nichts geaendert
    with app.app_context():
        tid = aufgabe_neu(fam["v"], eltern["row"], "Bleibt", wann="geparkt", push=False)["termin_id"]
    r = client.post(_url(eltern, f"termin/{tid}/hervorholen"), data={"ziel": "2031-01-01"}, headers=JSON)
    assert r.status_code == 400 and _termin(fam["v"], tid)["status"] == "geparkt"
    # flexibler Termin steht auf Heute als "Diese Woche"
    assert "Diese Woche" in client.get(_url(eltern)).get_data(as_text=True)


def test_morgen_verlegt_und_rueckweg(app, client, fam):
    eltern = fam["TestEltern"]
    heute = date.fromisoformat(heute_lokal())
    gestern = (heute - timedelta(days=1)).isoformat()
    with app.app_context():
        a = aufgabe_neu(fam["v"], eltern["row"], "Dachrinne", wann=gestern, push=False)
    d = client.post(_url(eltern, f"termin/{a['termin_id']}/verlegen"), data={"morgen": "1"}, headers=JSON).get_json()
    assert d["ok"] and d["tag"] == (heute + timedelta(days=1)).isoformat() and "Morgen" in d["text"]
    assert d["zurueck"]["daten"]["tag"] == gestern
    d = client.post(_url(eltern, f"termin/{a['termin_id']}/verlegen"), data=d["zurueck"]["daten"], headers=JSON).get_json()
    assert d["ok"] and _termin(fam["v"], a["termin_id"])["tag"] == gestern
    # ohne JSON: Weiterleitung mit Anker
    r = client.post(_url(eltern, f"termin/{a['termin_id']}/verlegen"), data={"morgen": "1"})
    assert r.status_code == 302 and f"#termin-{a['termin_id']}" in r.headers["Location"]


def test_rechte_kind_nur_selbst_angelegte(app, client, fam):
    kind, eltern = fam["TestKind"], fam["TestEltern"]
    with app.app_context():
        zug = aufgabe_neu(fam["v"], eltern["row"], "Zugewiesen", ziel_user=kind["id"], push=False)
        privat = aufgabe_neu(fam["v"], kind["row"], "Privat", sicht="ich", push=False)
    for rest in ("parken", "verlegen"):
        r = client.post(_url(kind, f"termin/{zug['termin_id']}/{rest}"), data={"morgen": "1"}, headers=JSON)
        assert r.status_code == 403, rest
    assert client.post(_url(eltern, f"termin/{privat['termin_id']}/parken"), headers=JSON).status_code == 404
    assert client.post(_url(eltern, "termin/999999/parken"), headers=JSON).status_code == 404
    # Eltern-Seite zeigt fuer den zugewiesenen Termin des Kindes keine Morgen/Parken-Knoepfe beim Kind
    text = client.get(_url(kind)).get_data(as_text=True)
    assert ">Parken<" not in text


def test_schnell_parken_und_reihenfolge(app, client, fam):
    kind = fam["TestKind"]
    r = client.post(_url(kind, "neu"), data={"inhalt": "Schreibtisch ausmisten", "wann": "spaeter", "sicht": "alle", "ziel": "ich"})
    assert r.status_code == 302 and "/spaeter#termin-" in r.headers["Location"]
    client.post(_url(kind, "neu"), data={"inhalt": "Zweites", "wann": "spaeter", "sicht": "alle"})
    zeilen = fam["v"].execute("SELECT id, position FROM termine WHERE status='geparkt' ORDER BY position").fetchall()
    assert len(zeilen) == 2 and zeilen[0]["position"] < zeilen[1]["position"]
    ids = [z["id"] for z in zeilen]
    r = client.post(_url(kind, "spaeter/reihenfolge"), json={"order": [ids[1], ids[0], 999999]})
    assert r.status_code == 200 and r.get_json()["gesetzt"] == 2
    neu = [z["id"] for z in fam["v"].execute("SELECT id FROM termine WHERE status='geparkt' ORDER BY position, id")]
    assert neu == [ids[1], ids[0]]
    text = client.get(_url(kind, "spaeter")).get_data(as_text=True)
    assert text.index("Zweites") < text.index("Schreibtisch ausmisten")
    # geparkt zaehlt nirgends als offen
    assert "Heute ist nichts dran" in client.get(_url(kind)).get_data(as_text=True)


def test_formular_spaeter_und_bearbeiten_zurueck_auf_heute(app, client, fam):
    eltern = fam["TestEltern"]
    with app.app_context():
        a = aufgabe_neu(fam["v"], eltern["row"], "Regal aufbauen", wann="geparkt", push=False)
    text = client.get(_url(eltern, f"aufgabe/{a['aufgabe_id']}")).get_data(as_text=True)
    assert 'value="spaeter" data-aendern="wannGewaehlt" data-args=\'["spaeter"]\' checked' in text
    assert ">Parken</button>" in text
    r = client.post(_url(eltern, f"aufgabe/{a['aufgabe_id']}"), data={
        "inhalt": "Regal aufbauen", "ziel": "ich", "wann": "heute", "sicht": "alle", "punkte": "0"})
    assert r.status_code == 302
    t = _termin(fam["v"], a["termin_id"])
    assert t["status"] == "offen" and t["tag"] == heute_lokal() and t["geparkt_am"] is None


def test_seit_text():
    heute = date(2026, 9, 19)
    assert seit_text("2026-09-19 10:00:00", heute) == "Geparkt seit heute"
    assert seit_text("2026-09-18 10:00:00", heute) == "Geparkt seit gestern"
    assert seit_text("2026-09-15 10:00:00", heute) == "Geparkt seit 4 Tagen"
    assert seit_text("2026-09-01 10:00:00", heute) == "Geparkt seit 2 Wochen"
    assert seit_text("2026-07-01 10:00:00", heute) == "Geparkt seit 2 Monaten"
    assert seit_text(None, heute) == "Geparkt"
    # 23:30 UTC am 18. ist in Berlin schon der 19. -> "heute"
    assert seit_text("2026-09-18 23:30:00", heute) == "Geparkt seit heute"


def test_spaeter_fuer_kiosk_und_gast_nicht(app, client, fam, db):
    v = fam["v"]
    app_id = v.execute("SELECT id FROM apps WHERE slug='aufgaben'").fetchone()["id"]
    toks = {}
    with app.app_context():
        for name, rolle in (("Kiosk", "kiosk"), ("Gast", "gast")):
            uid = v.execute("INSERT INTO users(name, farbe, is_admin, rolle) VALUES(?,?,0,?) RETURNING id",
                            (name, "#555555", rolle)).fetchone()["id"]
            toks[rolle] = new_token()
            v.execute("INSERT INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)", (uid, app_id, token_lookup(toks[rolle])))
    v.commit()
    assert client.get(f"/a/aufgaben/{toks['kiosk']}/spaeter").status_code == 404
    assert client.get(f"/a/aufgaben/{toks['gast']}/spaeter").status_code == 200   # lesend, leer
