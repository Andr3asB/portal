"""Aufgaben (neu), Schritt 2 (Wunsch #298) - Heute, Abhaken, Formular.

Routen-Tests gegen den Test-Client: Was die Seite zeigt, was der Haken tut
(JSON fuer die Seite, Weiterleitung fuer den Browser ohne Skript), und dass
die Rechte aus Schritt 1 an den Routen wirklich greifen - 404 vor 403 fuer
Unsichtbares, 403 fuer Sichtbares ohne Recht, Kinder-POST ohne Punkte.
"""
from datetime import date, timedelta

import pytest
import teile.aufgaben as aufgaben_modul
from teile.aufgaben import aufgabe_neu
from teile.kern import heute_lokal, new_token, token_lookup

JSON = {"Accept": "application/json"}


@pytest.fixture()
def fam(app, db):
    """Familie mit Grant fuer `aufgaben` je Person + Nutzer-Rows."""
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


def _seite(client, p, rest=""):
    r = client.get(_url(p, rest))
    assert r.status_code == 200, r.status_code
    return r.get_data(as_text=True)


def test_heute_zeigt_eigene_termine_balken_und_reiter(app, client, fam):
    kind = fam["TestKind"]
    with app.app_context():
        a = aufgabe_neu(fam["v"], kind["row"], "Zimmer aufräumen", push=False)
        aufgabe_neu(fam["v"], kind["row"], "Vokabeln lernen", push=False)
    text = _seite(client, kind)
    assert "Zimmer aufräumen" in text and "Vokabeln lernen" in text
    assert "0 von 2 geschafft" in text
    assert "Hallo TestKind" in text
    assert '<nav class="reiter" aria-label="Ansichten">' in text
    assert "mit-reiter" in text
    assert "Von mir" in text
    # Kind hat eigene Aufgabe angelegt -> Stift ist da
    assert f"aufgabe/{a['aufgabe_id']}" in text


def test_haken_toggelt_und_liefert_zaehler(app, client, fam):
    kind = fam["TestKind"]
    with app.app_context():
        a = aufgabe_neu(fam["v"], kind["row"], "Tisch decken", push=False)
        aufgabe_neu(fam["v"], kind["row"], "Blumen giessen", push=False)
    r = client.post(_url(kind, f"termin/{a['termin_id']}/haken"), headers=JSON)
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] and d["erledigt"] is True
    assert (d["geschafft"], d["gesamt"]) == (1, 2)
    assert d["balken_text"] == "1 von 2 geschafft" and d["balken_prozent"] == 50
    text = _seite(client, kind)
    assert "1 von 2 geschafft" in text and 'aria-pressed="true"' in text
    # zweiter Tipp nimmt das Haekchen zurueck
    d = client.post(_url(kind, f"termin/{a['termin_id']}/haken"), headers=JSON).get_json()
    assert d["erledigt"] is False and d["geschafft"] == 0
    zeile = fam["v"].execute("SELECT status, punkte, erledigt_tag FROM termine WHERE id=?",
                             (a["termin_id"],)).fetchone()
    assert zeile["status"] == "offen" and zeile["punkte"] is None and zeile["erledigt_tag"] is None


def test_alles_geschafft_und_nichts_dran(app, client, fam):
    kind = fam["TestKind"]
    assert "Heute ist nichts dran" in _seite(client, kind)
    with app.app_context():
        a = aufgabe_neu(fam["v"], kind["row"], "Einzige", push=False)
    client.post(_url(kind, f"termin/{a['termin_id']}/haken"), headers=JSON)
    assert "Alles geschafft" in _seite(client, kind)


def test_ohne_json_kopf_weiterleitung_mit_anker(app, client, fam):
    kind = fam["TestKind"]
    with app.app_context():
        a = aufgabe_neu(fam["v"], kind["row"], "Formular-Weg", push=False)
    r = client.post(_url(kind, f"termin/{a['termin_id']}/haken"))
    assert r.status_code == 302
    assert r.headers["Location"].endswith(f"#termin-{a['termin_id']}")


def test_haken_404_vor_403(app, client, fam):
    kind, eltern = fam["TestKind"], fam["TestEltern"]
    with app.app_context():
        privat = aufgabe_neu(fam["v"], kind["row"], "Tagebuch", sicht="ich", push=False)
        fremd = aufgabe_neu(fam["v"], eltern["row"], "Elternsache", push=False)   # sicht alle, Ziel Eltern
    # unsichtbar -> 404, genau wie nicht vorhanden
    assert client.post(_url(eltern, f"termin/{privat['termin_id']}/haken"), headers=JSON).status_code == 404
    assert client.post(_url(eltern, "termin/999999/haken"), headers=JSON).status_code == 404
    # sichtbar, aber nicht der eigene Termin -> Kind darf nicht haken
    assert client.post(_url(kind, f"termin/{fremd['termin_id']}/haken"), headers=JSON).status_code == 403
    # Eltern duerfen fuer das Kind abhaken
    zug = None
    with app.app_context():
        zug = aufgabe_neu(fam["v"], eltern["row"], "Fuer Kind", ziel_user=kind["id"], push=False)
    d = client.post(_url(eltern, f"termin/{zug['termin_id']}/haken"), headers=JSON).get_json()
    assert d["erledigt"] is True


def test_ueberfaellig_zuerst_mit_text(app, client, fam):
    kind = fam["TestKind"]
    heute = date.fromisoformat(heute_lokal())
    with app.app_context():
        aufgabe_neu(fam["v"], kind["row"], "Heutige Sache", push=False)
        aufgabe_neu(fam["v"], kind["row"], "Alte Sache", wann=(heute - timedelta(days=1)).isoformat(), push=False)
        aufgabe_neu(fam["v"], kind["row"], "Uralte Sache", wann=(heute - timedelta(days=3)).isoformat(), push=False)
        aufgabe_neu(fam["v"], kind["row"], "Morgige Sache", wann=(heute + timedelta(days=1)).isoformat(), push=False)
    text = _seite(client, kind)
    assert "Seit gestern offen" in text and "Seit 3 Tagen offen" in text
    assert text.index("Alte Sache") < text.index("Heutige Sache")
    assert "Morgige Sache" not in text
    assert "Morgen: 1 Aufgabe<" in text
    assert "0 von 3 geschafft" in text


def test_formular_neu_kind_ohne_punkte_und_ohne_nur_eltern(app, client, fam):
    kind = fam["TestKind"]
    text = _seite(client, kind, "neu")
    assert "Wer?" not in text and 'name="punkte"' not in text and 'value="eltern"' not in text
    r = client.post(_url(kind, "neu"), data={"inhalt": "Geheim", "sicht": "eltern", "wann": "heute"})
    assert r.status_code == 400 and "Sichtbarkeit" in r.get_data(as_text=True)
    r = client.post(_url(kind, "neu"), data={"inhalt": "Mit Punkten?", "sicht": "kinder", "wann": "heute",
                                            "punkte": "3", "ziel": str(fam["TestEltern"]["id"])})
    assert r.status_code == 302
    a = fam["v"].execute("SELECT * FROM aufgaben WHERE inhalt='Mit Punkten?'").fetchone()
    assert a["punkte"] == 0 and a["ziel_user"] == kind["id"] and a["sicht"] == "kinder"


def test_formular_neu_eltern_tag_uhrzeit_und_push(app, client, fam, monkeypatch):
    eltern, kind = fam["TestEltern"], fam["TestKind"]
    gesendet = []
    # Alias aus teile/__init__.py - kein Attribut von `teile`, deshalb das
    # Modulobjekt statt des Punktpfads.
    monkeypatch.setattr(aufgaben_modul, "push_send", lambda *a, **k: gesendet.append((a, k)))
    text = _seite(client, eltern, "neu")
    assert "Wer?" in text and 'name="punkte"' in text and "TestKind" in text
    morgen = (date.fromisoformat(heute_lokal()) + timedelta(days=1)).isoformat()
    r = client.post(_url(eltern, "neu"), data={
        "inhalt": "Zahnarzt", "ziel": str(kind["id"]), "wann": "tag", "tag": morgen,
        "uhrzeit": "16:00", "sicht": "alle", "punkte": "1,5", "emoji": "🦷"})
    assert r.status_code == 302 and f"?fuer={kind['id']}" in r.headers["Location"]
    t = fam["v"].execute("SELECT t.*, a.punkte AS ap FROM termine t JOIN aufgaben a ON a.id=t.aufgabe_id "
                         "WHERE a.inhalt='Zahnarzt'").fetchone()
    assert (t["tag"], t["uhrzeit"], t["user_id"], t["ap"]) == (morgen, "16:00", kind["id"], 1.5)
    assert gesendet and gesendet[0][0][0] == kind["id"]
    # Eltern sehen die Heute-Seite des Kindes (?fuer=), das Kind nicht die der Eltern
    assert "TestKind: Heute" in _seite(client, eltern, f"?fuer={kind['id']}")
    assert "Hallo TestKind" in _seite(client, kind, f"?fuer={eltern['id']}")


def test_formular_fehler_bleibt_auf_der_seite(app, client, fam):
    eltern = fam["TestEltern"]
    r = client.post(_url(eltern, "neu"), data={"inhalt": "   ", "wann": "heute", "sicht": "alle"})
    assert r.status_code == 400 and "Der Text fehlt" in r.get_data(as_text=True)
    r = client.post(_url(eltern, "neu"), data={"inhalt": "Weit weg", "wann": "tag", "tag": "2031-01-01", "sicht": "alle"})
    assert r.status_code == 400 and "planbaren Zeitraums" in r.get_data(as_text=True)
    assert fam["v"].execute("SELECT COUNT(*) FROM aufgaben").fetchone()[0] == 0


def test_bearbeiten_schreibt_verlauf_und_prueft_rechte(app, client, fam):
    eltern, kind = fam["TestEltern"], fam["TestKind"]
    with app.app_context():
        a = aufgabe_neu(fam["v"], eltern["row"], "Tisch decken", ziel_user=kind["id"], punkte=1, push=False)
        privat = aufgabe_neu(fam["v"], kind["row"], "Tagebuch", sicht="ich", push=False)
    aid = a["aufgabe_id"]
    # Kind: sichtbar (zugewiesen), aber nicht selbst angelegt -> 403
    assert client.get(_url(kind, f"aufgabe/{aid}")).status_code == 403
    assert client.post(_url(kind, f"aufgabe/{aid}"), data={"inhalt": "x"}).status_code == 403
    # Eltern: privates des Kindes -> 404 (nicht 403), nicht vorhanden -> 404
    assert client.get(_url(eltern, f"aufgabe/{privat['aufgabe_id']}")).status_code == 404
    assert client.get(_url(eltern, "aufgabe/999999")).status_code == 404
    text = _seite(client, eltern, f"aufgabe/{aid}")
    assert 'value="Tisch decken"' in text and "Frühere Fassungen" not in text and "🗑️" in text
    r = client.post(_url(eltern, f"aufgabe/{aid}"), data={
        "inhalt": "Tisch abräumen", "ziel": str(kind["id"]), "wann": "heute", "sicht": "kinder", "punkte": "2"})
    assert r.status_code == 302
    zeile = fam["v"].execute("SELECT * FROM aufgaben WHERE id=?", (aid,)).fetchone()
    assert (zeile["inhalt"], zeile["sicht"], zeile["punkte"]) == ("Tisch abräumen", "kinder", 2.0)
    hist = fam["v"].execute("SELECT * FROM aufgaben_historie WHERE aufgabe_id=?", (aid,)).fetchall()
    assert len(hist) == 1 and hist[0]["alter_inhalt"] == "Tisch decken" and hist[0]["geaendert_von"] == eltern["id"]
    text = _seite(client, eltern, f"aufgabe/{aid}")
    assert "Frühere Fassungen" in text and "„Tisch decken“" in text
    # gleicher Text nochmal -> kein zweiter Verlaufseintrag
    client.post(_url(eltern, f"aufgabe/{aid}"), data={
        "inhalt": "Tisch abräumen", "ziel": str(kind["id"]), "wann": "heute", "sicht": "kinder", "punkte": "2"})
    assert fam["v"].execute("SELECT COUNT(*) FROM aufgaben_historie").fetchone()[0] == 1


def test_kind_bearbeitet_eigenes_ohne_punkte_zu_verlieren(app, client, fam):
    """Ein Elternteil hat der Aufgabe des Kindes Punkte gegeben; das Kind
    aendert den Text - die Punkte bleiben, das Formular des Kindes kennt
    das Feld gar nicht."""
    kind = fam["TestKind"]
    with app.app_context():
        a = aufgabe_neu(fam["v"], kind["row"], "Rasen mähen", push=False)
    fam["v"].execute("UPDATE aufgaben SET punkte=2 WHERE id=?", (a["aufgabe_id"],))
    fam["v"].commit()
    r = client.post(_url(kind, f"aufgabe/{a['aufgabe_id']}"), data={
        "inhalt": "Rasen mähen (hinten)", "wann": "heute", "sicht": "alle", "punkte": "0"})
    assert r.status_code == 302
    zeile = fam["v"].execute("SELECT * FROM aufgaben WHERE id=?", (a["aufgabe_id"],)).fetchone()
    assert zeile["punkte"] == 2 and zeile["inhalt"] == "Rasen mähen (hinten)"


def test_loeschen_rechte(app, client, fam):
    eltern, kind = fam["TestEltern"], fam["TestKind"]
    with app.app_context():
        eigen = aufgabe_neu(fam["v"], kind["row"], "Eigenes", push=False)
        mit_punkten = aufgabe_neu(fam["v"], eltern["row"], "Mit Punkten", ziel_user=kind["id"], punkte=1, push=False)
        privat = aufgabe_neu(fam["v"], kind["row"], "Privat", sicht="ich", push=False)
    assert client.post(_url(kind, f"aufgabe/{mit_punkten['aufgabe_id']}/loeschen")).status_code == 403
    assert client.post(_url(eltern, f"aufgabe/{privat['aufgabe_id']}/loeschen")).status_code == 404
    assert client.post(_url(kind, f"aufgabe/{eigen['aufgabe_id']}/loeschen")).status_code == 302
    assert client.post(_url(eltern, f"aufgabe/{mit_punkten['aufgabe_id']}/loeschen")).status_code == 302
    rest = [z["inhalt"] for z in fam["v"].execute("SELECT inhalt FROM aufgaben")]
    assert rest == ["Privat"]
    assert fam["v"].execute("SELECT COUNT(*) FROM termine").fetchone()[0] == 1   # CASCADE


def test_punkte_diese_woche_nur_eigene(app, client, fam):
    eltern, kind = fam["TestEltern"], fam["TestKind"]
    with app.app_context():
        a = aufgabe_neu(fam["v"], eltern["row"], "Spülmaschine", ziel_user=kind["id"], punkte=2.5, push=False)
        b = aufgabe_neu(fam["v"], eltern["row"], "Eigene Elternsache", punkte=5, push=False)
    client.post(_url(kind, f"termin/{a['termin_id']}/haken"), headers=JSON)
    client.post(_url(eltern, f"termin/{b['termin_id']}/haken"), headers=JSON)
    text = _seite(client, kind)
    assert '<span id="punkte-woche">2,5</span> Punkte diese Woche' in text
    assert '+2,5' in text
    assert '<span id="punkte-woche">5</span>' in _seite(client, eltern)


def test_gast_sieht_nur_lesend(app, client, fam):
    v = fam["v"]
    gid = v.execute("INSERT INTO users(name, farbe, is_admin, rolle) VALUES('Gast','#555555',0,'gast') RETURNING id").fetchone()["id"]
    app_id = v.execute("SELECT id FROM apps WHERE slug='aufgaben'").fetchone()["id"]
    tok = new_token()
    with app.app_context():
        v.execute("INSERT INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)", (gid, app_id, token_lookup(tok)))
    v.commit()
    gast = {"tok": tok, "id": gid}
    text = _seite(client, gast)
    assert "+ Eigene Aufgabe" not in text
    assert client.get(_url(gast, "neu")).status_code == 403
