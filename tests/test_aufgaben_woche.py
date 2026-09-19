"""Aufgaben (neu), Schritt 5 (Wunsch #301) - Woche.

Spezifikation 6.3: Tag bestaetigen; Sammelbestaetigung respektiert den
Filter (bestaetigt wird immer nur das Sichtbare); verlegen; "Faellt aus"
einzeln und fuer die Woche; Person setzen; Kinder lesen nur, ohne
Vorschlaege; Bearbeiten "Nur dieser Termin / Alle kuenftigen" (5.5); das
Formular kennt "Regelmaessig".
"""
from datetime import date, timedelta

import pytest
from teile.aufgaben import aufgabe_neu, montag_von, vorschlaege_sicherstellen
from teile.kern import heute_lokal, new_token, token_lookup

JSON = {"Accept": "application/json"}


@pytest.fixture()
def fam(app, db):
    v = db["verbindung"]
    app_id = v.execute("SELECT id FROM apps WHERE slug='aufgaben'").fetchone()["id"]
    f = {}
    with app.app_context():
        alle = dict(db["familie"])
        k2 = v.execute("INSERT INTO users(name, farbe, is_admin, rolle) VALUES('Kind2','#444444',0,'kind') RETURNING id").fetchone()["id"]
        alle["Kind2"] = {"id": k2}
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


def _naechster_montag():
    return montag_von(date.fromisoformat(heute_lokal())) + timedelta(days=7)


@pytest.fixture()
def regeln(app, fam):
    """Zwei taegliche Regeln: eine fuer TestKind, eine fuer Kind2; Vorschlaege bis Ende naechster Woche."""
    v, eltern = fam["v"], fam["TestEltern"]["row"]
    with app.app_context():
        a = aufgabe_neu(v, eltern, "Tisch decken", ziel_user=fam["TestKind"]["id"], regel_typ="wochentage",
                        regel_wochentage="0,1,2,3,4,5,6", punkte=1, push=False)["aufgabe_id"]
        b = aufgabe_neu(v, eltern, "Müll raus", ziel_user=fam["Kind2"]["id"], regel_typ="wochentage",
                        regel_wochentage="0,1,2,3,4,5,6", push=False)["aufgabe_id"]
        vorschlaege_sicherstellen(v)
    return {"a": a, "b": b}


def _vorschlaege(v, montag):
    return v.execute("SELECT * FROM termine WHERE status='vorschlag' AND tag BETWEEN ? AND ? ORDER BY tag, id",
                     (montag.isoformat(), (montag + timedelta(days=6)).isoformat())).fetchall()


def test_woche_seite_und_sammelbestaetigung_mit_filter(app, client, fam, regeln):
    eltern, kind = fam["TestEltern"], fam["TestKind"]
    montag = _naechster_montag()
    text = client.get(_url(eltern, f"woche?ab={montag}")).get_data(as_text=True)
    assert "Nächste Woche" in text and "14 Vorschläge" in text and "Alle 14 ok" in text
    assert "Gestrichelt heißt" in text and "Tisch decken" in text and "Müll raus" in text
    assert "Jeden Tag · bestätigt" not in text
    # mit Filter: nur die 7 von TestKind
    text = client.get(_url(eltern, f"woche?ab={montag}&wer={kind['id']}")).get_data(as_text=True)
    assert "7 Vorschläge für TestKind" in text and "Diese 7 ok" in text and "Müll raus" not in text
    d = client.post(_url(eltern, "woche/ok"), data={"ab": montag.isoformat(), "wer": str(kind["id"])}, headers=JSON).get_json()
    assert d["ok"] and d["bestaetigt"] == 7
    rest = _vorschlaege(fam["v"], montag)
    assert len(rest) == 7 and all(t["user_id"] == fam["Kind2"]["id"] for t in rest)
    # ein Tag: "Mo ok"
    d = client.post(_url(eltern, "woche/ok"), data={"ab": montag.isoformat(), "tag": montag.isoformat()}, headers=JSON).get_json()
    assert d["bestaetigt"] == 1
    # alles Uebrige
    d = client.post(_url(eltern, "woche/ok"), data={"ab": montag.isoformat()}, headers=JSON).get_json()
    assert d["bestaetigt"] == 6 and not _vorschlaege(fam["v"], montag)
    text = client.get(_url(eltern, f"woche?ab={montag}")).get_data(as_text=True)
    assert "Die Woche steht. Alles bestätigt." in text and "Jeden Tag · bestätigt" in text
    # Kinder: nur lesend, ohne Vorschlaege, eigene Termine
    text = client.get(_url(kind, f"woche?ab={montag}")).get_data(as_text=True)
    assert "Tisch decken" in text and "Müll raus" not in text and "ok</button>" not in text
    assert client.post(_url(kind, "woche/ok"), data={"ab": montag.isoformat()}, headers=JSON).status_code == 403


def test_einzeln_bestaetigen_verlegen_streichen(app, client, fam, regeln):
    eltern, kind = fam["TestEltern"], fam["TestKind"]
    montag = _naechster_montag()
    v = fam["v"]
    t = next(x for x in _vorschlaege(v, montag) if x["aufgabe_id"] == regeln["a"])     # Montag, TestKind
    # Kind darf nichts davon
    for rest in ("ok", "aus", "person"):
        assert client.post(_url(kind, f"termin/{t['id']}/{rest}"), data={"user_id": kind["id"]}, headers=JSON).status_code == 403
    d = client.post(_url(eltern, f"termin/{t['id']}/ok"), headers=JSON).get_json()
    assert d["ok"] and d["status"] == "offen"
    assert tuple(v.execute("SELECT status, auto_bestaetigt FROM termine WHERE id=?", (t["id"],)).fetchone()) == ("offen", 0)
    # verlegen auf Mittwoch: dort steht die Aufgabe schon -> 400; auf einen freien Tag (aus loeschen) ok
    mi = (montag + timedelta(days=2)).isoformat()
    assert client.post(_url(eltern, f"termin/{t['id']}/verlegen"), data={"tag": mi}, headers=JSON).status_code == 400
    v.execute("DELETE FROM termine WHERE aufgabe_id=? AND tag=?", (regeln["a"], mi))
    v.commit()
    d = client.post(_url(eltern, f"termin/{t['id']}/verlegen"), data={"tag": mi}, headers=JSON).get_json()
    assert d["ok"] and v.execute("SELECT tag FROM termine WHERE id=?", (t["id"],)).fetchone()[0] == mi
    # Person setzen
    d = client.post(_url(eltern, f"termin/{t['id']}/person"), data={"user_id": fam["Kind2"]["id"]}, headers=JSON).get_json()
    assert d["ok"] and d["person"] == "Kind2"
    assert v.execute("SELECT user_id FROM termine WHERE id=?", (t["id"],)).fetchone()[0] == fam["Kind2"]["id"]
    # Faellt aus -> rest = weitere Termine derselben Aufgabe in der Woche (6 - 1 geloeschter = 5)
    d = client.post(_url(eltern, f"termin/{t['id']}/aus"), headers=JSON).get_json()
    assert d["ok"] and d["status"] == "aus" and d["rest"] == 5 and "fällt aus" in d["text"]
    assert d["zurueck"]["daten"]["wieder"] == "offen"
    # Rueckgaengig
    d = client.post(_url(eltern, f"termin/{t['id']}/aus"), data=d["zurueck"]["daten"], headers=JSON).get_json()
    assert d["ok"] and d["status"] == "offen"
    # Auch die anderen streichen: alle der Aufgabe in dieser Woche
    d = client.post(_url(eltern, f"termin/{t['id']}/aus"), data={"woche": "1"}, headers=JSON).get_json()
    assert d["ok"] and "ganz aus" in d["text"]
    stati = [z[0] for z in v.execute("SELECT status FROM termine WHERE aufgabe_id=? AND tag BETWEEN ? AND ?",
                                      (regeln["a"], montag.isoformat(), (montag + timedelta(days=6)).isoformat()))]
    assert stati and all(s == "aus" for s in stati)
    # gestrichene entstehen nicht neu
    with app.app_context():
        vorschlaege_sicherstellen(v)
    assert v.execute("SELECT COUNT(*) FROM termine WHERE aufgabe_id=? AND status='aus'", (regeln["a"],)).fetchone()[0] == len(stati)


def test_formular_regel_anlegen_und_bearbeiten(app, client, fam):
    eltern, kind = fam["TestEltern"], fam["TestKind"]
    v = fam["v"]
    text = client.get(_url(eltern, "neu")).get_data(as_text=True)
    assert 'value="regel"' in text and 'name="wochentage"' in text and 'name="intervall"' in text
    r = client.post(_url(eltern, "neu"), data={
        "inhalt": "Blumen gießen", "ziel": str(kind["id"]), "wann": "regel", "regel_typ": "intervall",
        "intervall": "3", "sicht": "alle", "punkte": "1"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/woche")
    a = v.execute("SELECT * FROM aufgaben WHERE inhalt='Blumen gießen'").fetchone()
    assert (a["regel_typ"], a["regel_intervall"], a["ziel_user"]) == ("intervall", 3, kind["id"])
    termine = v.execute("SELECT * FROM termine WHERE aufgabe_id=?", (a["id"],)).fetchall()
    assert len(termine) == 1 and termine[0]["status"] == "vorschlag"     # morgen
    # ohne Wochentag -> Fehler bleibt auf der Seite
    r = client.post(_url(eltern, "neu"), data={"inhalt": "Leer", "ziel": "ich", "wann": "regel", "regel_typ": "wochentage", "sicht": "alle"})
    assert r.status_code == 400 and "Mindestens ein Wochentag" in r.get_data(as_text=True)
    # Bearbeiten "Alle kuenftigen": Regel aendern -> Termine ab heute neu
    r = client.post(_url(eltern, f"aufgabe/{a['id']}"), data={
        "inhalt": "Blumen gießen", "ziel": str(kind["id"]), "wann": "regel", "umfang": "kuenftige",
        "regel_typ": "wochentage", "wochentage": ["0", "2", "4"], "sicht": "alle", "punkte": "1"})
    assert r.status_code == 302
    a = v.execute("SELECT * FROM aufgaben WHERE id=?", (a["id"],)).fetchone()
    assert a["regel_typ"] == "wochentage" and a["regel_wochentage"] == "0,2,4"
    tage = [t["tag"] for t in v.execute("SELECT tag FROM termine WHERE aufgabe_id=? ORDER BY tag", (a["id"],))]
    assert tage and all(date.fromisoformat(t).weekday() in (0, 2, 4) for t in tage)
    # Bearbeiten "Nur dieser Termin": Text-Abweichung und Person, Regel unberuehrt
    t = v.execute("SELECT * FROM termine WHERE aufgabe_id=? ORDER BY tag LIMIT 1", (a["id"],)).fetchone()
    text = client.get(_url(eltern, f"aufgabe/{a['id']}?termin={t['id']}")).get_data(as_text=True)
    assert "Nur dieser Termin" in text and "Alle künftigen" in text
    r = client.post(_url(eltern, f"aufgabe/{a['id']}"), data={
        "inhalt": "Blumen gießen (auch Balkon)", "ziel": str(fam["Kind2"]["id"]), "umfang": "termin",
        "termin": str(t["id"]), "tag": t["tag"], "uhrzeit": "17:00", "wann": "tag", "sicht": "alle", "punkte": "1"})
    assert r.status_code == 302 and "/woche?ab=" in r.headers["Location"]
    t2 = v.execute("SELECT * FROM termine WHERE id=?", (t["id"],)).fetchone()
    assert (t2["inhalt"], t2["user_id"], t2["uhrzeit"]) == ("Blumen gießen (auch Balkon)", fam["Kind2"]["id"], "17:00")
    assert v.execute("SELECT inhalt FROM aufgaben WHERE id=?", (a["id"],)).fetchone()[0] == "Blumen gießen"
    assert v.execute("SELECT COUNT(*) FROM aufgaben_historie").fetchone()[0] == 0
    # Katalog zeigt die Regel
    assert "Jeden Mo, Mi, Fr · TestKind" in client.get(_url(eltern, "alle")).get_data(as_text=True)


def test_familie_kasten_und_heute_morgen_link(app, client, fam, regeln):
    eltern, kind = fam["TestEltern"], fam["TestKind"]
    text = client.get(_url(eltern, "familie")).get_data(as_text=True)
    assert "Nächste Woche: 14 Vorschläge" in text and "Alle übernehmen" in text
    assert "automatisch freigegeben" in text                       # Hinweis auf diese Woche
    r = client.post(_url(eltern, "woche/ok"), data={"ab": _naechster_montag().isoformat(),
                                                      "zurueck": f"/a/aufgaben/{eltern['tok']}/familie"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/familie")
    assert not _vorschlaege(fam["v"], _naechster_montag())
    text = client.get(_url(kind)).get_data(as_text=True)
    assert 'class="morgen knopf"' in text and "/woche" in text
    # heutiger Vorschlag wurde beim Aufruf automatisch freigegeben und steht auf Heute
    assert "Tisch decken" in text and "automatisch freigegeben" in client.get(_url(eltern, "woche")).get_data(as_text=True)
