"""Aufgaben (neu), Schritt 6 (Wunsch #302) - Gruppenaufgaben, Familie, Alle Aufgaben.

Spezifikation 5.2: Einmalige Aufgaben an eine Gruppe haben einen Termin mit
user_id NULL; "Ich mach's" ist atomar (UPDATE ... WHERE user_id IS NULL,
sonst "<Name> war schneller"); Freigeben setzt user_id wieder auf NULL.
Dazu die Screens Familie (6.4) und Alle Aufgaben (6.6) sowie Pausieren.
"""
import pytest
from teile.aufgaben import aufgabe_neu, termin_nehmen, termin_sichtbar
from teile.kern import new_token, token_lookup

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


def test_gruppenaufgabe_erscheint_bei_passenden_und_ich_machs_atomar(app, client, fam):
    kind, kind2, eltern = fam["TestKind"], fam["Kind2"], fam["TestEltern"]
    with app.app_context():
        g = aufgabe_neu(fam["v"], eltern["row"], "Geburtstagstisch schmücken", ziel_gruppe="kinder", sicht="kinder", punkte=2, push=False)
    t = fam["v"].execute("SELECT * FROM termine WHERE id=?", (g["termin_id"],)).fetchone()
    assert t["user_id"] is None
    for p in (kind, kind2):
        text = client.get(_url(p)).get_data(as_text=True)
        assert "Noch zu haben" in text and "Geburtstagstisch" in text and "für die Kinder" in text and "Ich mach’s" in text
    assert "Geburtstagstisch" not in client.get(_url(eltern)).get_data(as_text=True)   # sicht kinder
    # Kind nimmt - Kind2 kommt zu spaet
    d = client.post(_url(kind, f"termin/{g['termin_id']}/nehmen"), headers=JSON).get_json()
    assert d["ok"] and d["genommen"] is True
    d = client.post(_url(kind2, f"termin/{g['termin_id']}/nehmen"), headers=JSON).get_json()
    assert d["ok"] and d["genommen"] is False and d["text"] == "TestKind war schneller"
    text = client.get(_url(kind)).get_data(as_text=True)
    assert "Heute dran" in text and "Geburtstagstisch" in text and "Noch zu haben" not in text
    assert "Wieder freigeben" in text
    # Freigeben: Kind darf (selbst uebernommen), danach wieder frei fuer Kind2
    r = client.post(_url(kind, f"termin/{g['termin_id']}/freigeben"))
    assert r.status_code == 302
    assert fam["v"].execute("SELECT user_id FROM termine WHERE id=?", (g["termin_id"],)).fetchone()[0] is None
    assert "Noch zu haben" in client.get(_url(kind2)).get_data(as_text=True)


def test_nehmen_atomar_auf_funktionsebene(app, fam):
    """Zwei Aufrufe hintereinander: der zweite trifft keine Zeile mehr."""
    kind, kind2, eltern = fam["TestKind"], fam["Kind2"], fam["TestEltern"]
    with app.app_context():
        g = aufgabe_neu(fam["v"], eltern["row"], "Altglas", ziel_gruppe="alle", push=False)
        t = termin_sichtbar(fam["v"], kind["row"], g["termin_id"])
        assert termin_nehmen(fam["v"], kind["row"], t)["genommen"] is True
        t2 = termin_sichtbar(fam["v"], kind2["row"], g["termin_id"])
        assert t2["user_id"] == kind["id"]
        # Zweiter verliert - kein Verbot, sondern die Antwort "war schneller" (5.2)
        assert termin_nehmen(fam["v"], kind2["row"], t2) == {"genommen": False, "text": "TestKind war schneller"}
        from teile.aufgaben import Verboten
        eltern_termin = termin_sichtbar(fam["v"], fam["TestEltern"]["row"], g["termin_id"])
        fam["v"].execute("UPDATE aufgaben SET ziel_gruppe='kinder' WHERE id=?", (g["aufgabe_id"],))
        fam["v"].commit()
        eltern_termin = termin_sichtbar(fam["v"], fam["TestEltern"]["row"], g["termin_id"])
        with pytest.raises(Verboten):          # Gruppe passt nicht
            termin_nehmen(fam["v"], fam["TestEltern"]["row"], eltern_termin)


def test_gruppe_eltern_nicht_fuer_kinder_und_formular_gruppen(app, client, fam):
    kind, eltern = fam["TestKind"], fam["TestEltern"]
    text = client.get(_url(eltern, "neu")).get_data(as_text=True)
    assert 'value="gruppe:eltern"' in text and 'value="gruppe:alle"' in text and "Wer will" in text
    assert 'value="gruppe:' not in client.get(_url(kind, "neu")).get_data(as_text=True)
    r = client.post(_url(eltern, "neu"), data={"inhalt": "Steuer", "ziel": "gruppe:eltern", "wann": "heute", "sicht": "alle"})
    assert r.status_code == 302
    a = fam["v"].execute("SELECT * FROM aufgaben WHERE inhalt='Steuer'").fetchone()
    assert a["ziel_gruppe"] == "eltern" and a["ziel_user"] is None
    assert "Steuer" not in client.get(_url(kind)).get_data(as_text=True)
    assert "Steuer" in client.get(_url(eltern)).get_data(as_text=True)
    # Sicht 'kinder' mit Gruppe 'alle' wird abgelehnt (Ziel muss sehen duerfen)
    r = client.post(_url(eltern, "neu"), data={"inhalt": "Falsch", "ziel": "gruppe:alle", "wann": "heute", "sicht": "kinder"})
    assert r.status_code == 400
    # Bearbeiten: Person -> Gruppe macht den Termin wieder frei
    with app.app_context():
        p = aufgabe_neu(fam["v"], eltern["row"], "Rasen", ziel_user=kind["id"], push=False)
    r = client.post(_url(eltern, f"aufgabe/{p['aufgabe_id']}"), data={"inhalt": "Rasen", "ziel": "gruppe:kinder", "wann": "heute", "sicht": "alle", "punkte": "0"})
    assert r.status_code == 302
    t = fam["v"].execute("SELECT * FROM termine WHERE id=?", (p["termin_id"],)).fetchone()
    assert t["user_id"] is None
    assert fam["v"].execute("SELECT ziel_gruppe FROM aufgaben WHERE id=?", (p["aufgabe_id"],)).fetchone()[0] == "kinder"


def test_familie_zeigt_fortschritt_und_offene(app, client, fam):
    kind, eltern = fam["TestKind"], fam["TestEltern"]
    with app.app_context():
        a = aufgabe_neu(fam["v"], eltern["row"], "Zimmer", ziel_user=kind["id"], punkte=2, push=False)
        aufgabe_neu(fam["v"], eltern["row"], "Vokabeln", ziel_user=kind["id"], push=False)
        aufgabe_neu(fam["v"], kind["row"], "Tagebuch", sicht="ich", push=False)   # privat, zaehlt nicht mit
        aufgabe_neu(fam["v"], eltern["row"], "Altglas", ziel_gruppe="alle", push=False)
        aufgabe_neu(fam["v"], eltern["row"], "Geparktes", wann="geparkt", push=False)
    client.post(_url(kind, f"termin/{a['termin_id']}/haken"), headers=JSON)
    assert client.get(_url(kind, "familie")).status_code == 403
    text = client.get(_url(eltern, "familie")).get_data(as_text=True)
    assert "Wer ist wie weit?" in text and "1 von 2" in text and "2 Punkte diese Woche" in text
    assert "Kind2" in text and "Heute nichts dran" in text
    assert "TestEltern (ich)" in text
    assert "Noch ohne Person" in text and "Altglas" in text and "wer will" in text.lower()
    assert "Später · 1 geparkt" in text and "Alle Aufgaben · 4" in text    # Tagebuch unsichtbar
    assert f"?fuer={kind['id']}" in text
    # Ich mach's von Familie aus fuehrt zurueck nach Familie
    tid = fam["v"].execute("SELECT t.id FROM termine t JOIN aufgaben a ON a.id=t.aufgabe_id WHERE a.inhalt='Altglas'").fetchone()[0]
    r = client.post(_url(eltern, f"termin/{tid}/nehmen"), data={"zurueck": f"/a/aufgaben/{eltern['tok']}/familie"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/familie")
    r = client.post(_url(eltern, f"termin/{tid}/freigeben"))
    assert r.status_code == 302
    # Fremdes Ziel im zurueck-Feld wird ignoriert
    r = client.post(_url(eltern, f"termin/{tid}/nehmen"), data={"zurueck": "https://boese.example/"})
    assert r.status_code == 302 and "boese" not in r.headers["Location"]


def test_alle_aufgaben_katalog_und_pausieren(app, client, fam):
    kind, eltern = fam["TestKind"], fam["TestEltern"]
    with app.app_context():
        aufgabe_neu(fam["v"], eltern["row"], "Tisch decken", ziel_user=kind["id"], punkte=1, kachel=1, push=False)
        aufgabe_neu(fam["v"], eltern["row"], "Gartentor", wann="geparkt", sicht="ich", push=False)
        aufgabe_neu(fam["v"], eltern["row"], "Altglas", ziel_gruppe="alle", wann="woche", push=False)
        regel = aufgabe_neu(fam["v"], eltern["row"], "Blumen gießen", ziel_user=kind["id"],
                            regel_typ="intervall", regel_intervall=3, push=False)["aufgabe_id"]
    assert client.get(_url(kind, "alle")).status_code == 403
    text = client.get(_url(eltern, "alle")).get_data(as_text=True)
    assert "Alle Aufgaben" in text
    assert 'data-art="einmal"' in text and 'data-art="geparkt"' in text and 'data-art="regel"' in text
    assert "Heute · TestKind" in text and "Geparkt · TestEltern" in text and "Diese Woche · Wer will" in text
    assert "Alle 3 Tage · TestKind" in text and ">Kachel<" in text and "Nur ich" in text
    assert ">Pausieren<" in text
    r = client.post(_url(eltern, f"aufgabe/{regel}/pausieren"))
    assert r.status_code == 302 and fam["v"].execute("SELECT pausiert FROM aufgaben WHERE id=?", (regel,)).fetchone()[0] == 1
    text = client.get(_url(eltern, "alle")).get_data(as_text=True)
    assert ">Fortsetzen<" in text and ">Pausiert<" in text
    # Pausierte stehen am Ende
    assert text.index("Tisch decken") < text.index("Blumen gießen")
    # einmalige lassen sich nicht pausieren; Kind darf nicht
    einmal = fam["v"].execute("SELECT id FROM aufgaben WHERE inhalt='Tisch decken'").fetchone()[0]
    assert client.post(_url(eltern, f"aufgabe/{einmal}/pausieren")).status_code == 400
    assert client.post(_url(kind, f"aufgabe/{regel}/pausieren")).status_code == 403
