"""Wunsch #261: Das Ziel einer Aufgabe ist EIN Chip-Band.

Vorher: eine Radio-Zeile (Person/Rolle(n)/Alle), darunter je nach Wahl eine
Auswahlliste oder Kaestchen, daneben "Privat" - drei Bauarten in einer Karte.
Und in der Auswahlliste stand "Fuer mich" UND die eigene Person noch einmal
mit Namen: als Andi hatte man "Fuer mich" und "-> Andi" zur Wahl, dasselbe
Ziel zweimal. Genau das meinte der Wunsch mit "macht keinen Sinn".

Jetzt: ein Band aus Chips (Ich, die anderen Personen, die Rollen, Alle,
Privat), die Formularfelder heissen weiter wie bisher - die Routen `neu` und
`bearbeiten` und alle ihre Tests bleiben unveraendert.
"""
import pytest
from teile.kern import new_token, token_lookup


@pytest.fixture()
def todo(app, db):
    v = db["verbindung"]
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='todo'").fetchone()["id"]
        tokens = {}
        for name, daten in db["familie"].items():
            # TestAdmin hat den Grant schon aus conftest - ein zweiter wuerde
            # per OR IGNORE verworfen, und der neue Token gaelte nicht.
            if "todo" in daten["tokens"]:
                tokens[name] = daten["tokens"]["todo"]
                continue
            klartext = new_token()
            v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                      (daten["id"], app_id, token_lookup(klartext)))
            tokens[name] = klartext
        v.commit()
    return {"tokens": tokens, "v": v, "familie": db["familie"]}


def _formular(seite):
    """Nur das Neu-Formular, ohne Filterkarte und Bearbeiten-Panels."""
    anfang = seite.index('id="new-todo-card"')
    ende = seite.index("</form>", anfang)
    return seite[anfang:ende]


def test_eigene_person_steht_nur_einmal_im_band(client, todo):
    seite = client.get(f"/a/todo/{todo['tokens']['TestAdmin']}/").get_data(as_text=True)
    form = _formular(seite)
    assert form.count(">Ich</label>") == 1
    assert "TestAdmin" not in form, "die eigene Person nicht noch einmal mit Namen"
    assert "TestKind" in form and "TestEltern" in form
    assert "<select" not in form, "keine Auswahlliste mehr"
    assert 'name="ziel_typ"' in form and 'type="hidden"' in form


def test_rollen_und_alle_sind_chips_mit_echten_feldern(client, todo):
    form = _formular(client.get(f"/a/todo/{todo['tokens']['TestAdmin']}/").get_data(as_text=True))
    for rolle in ("eltern", "kind", "gast"):
        assert f'type="checkbox" name="rollen" value="{rolle}"' in form
    assert ">Kinder</label>" in form and ">Gäste</label>" in form, "Mehrzahl auf den Chips"
    assert 'name="ziel_alle" value="alle"' in form
    assert 'name="privat"' in form and "Privat</label>" in form
    # Alle Felder sitzen IN ihrem Label - programmatische Beschriftung (#246).
    assert form.count("<label class=\"chip-btn ziel-chip") >= 7


def test_ich_ist_vorausgewaehlt(client, todo):
    form = _formular(client.get(f"/a/todo/{todo['tokens']['TestKind']}/").get_data(as_text=True))
    assert 'value="" data-ziel-typ="person" data-aendern="zielGewaehlt" checked>Ich' in form


def test_bearbeiten_panel_zeigt_das_gesetzte_ziel(client, todo):
    v = todo["v"]
    kind = todo["familie"]["TestKind"]["id"]
    admin = todo["familie"]["TestAdmin"]["id"]
    v.execute("INSERT INTO todos(inhalt, erstellt_von, zugewiesen_an, zugewiesen_rollen, privat, status) "
              "VALUES('Rollenziel', ?, NULL, 'kind,gast', 0, 'backlog')", (admin,))
    v.execute("INSERT INTO todos(inhalt, erstellt_von, zugewiesen_an, zugewiesen_rollen, privat, status) "
              "VALUES('Personenziel', ?, ?, NULL, 1, 'offen')", (admin, kind))
    v.execute("INSERT INTO todos(inhalt, erstellt_von, zugewiesen_an, zugewiesen_rollen, privat, status) "
              "VALUES('Alleziel', ?, NULL, 'alle', 0, 'backlog')", (admin,))
    v.commit()
    seite = client.get(f"/a/todo/{todo['tokens']['TestAdmin']}/").get_data(as_text=True)

    def panel(inhalt):
        anfang = seite.index(f'value="{inhalt}"')
        return seite[anfang:seite.index("</form>", anfang)]

    rollen = panel("Rollenziel")
    assert 'name="ziel_typ" value="rollen"' in rollen
    assert 'value="kind" data-ziel-typ="rolle" data-aendern="zielGewaehlt" checked' in rollen
    assert 'value="gast" data-ziel-typ="rolle" data-aendern="zielGewaehlt" checked' in rollen
    assert 'value="eltern" data-ziel-typ="rolle" data-aendern="zielGewaehlt" checked' not in rollen

    person = panel("Personenziel")
    assert 'name="ziel_typ" value="person"' in person
    assert f'value="{kind}" data-ziel-typ="person" data-aendern="zielGewaehlt" checked' in person
    assert 'name="privat" checked' in person

    alle = panel("Alleziel")
    assert 'name="ziel_typ" value="alle"' in alle
    assert 'name="ziel_alle" value="alle" data-ziel-typ="alle" data-aendern="zielGewaehlt" checked' in alle


def test_brett_benutzt_dasselbe_band(client, todo):
    seite = client.get(f"/a/todo/{todo['tokens']['TestAdmin']}/kanban").get_data(as_text=True)
    form = _formular(seite)
    assert ">Ich</label>" in form and "<select" not in form


def test_das_skript_pflegt_ziel_typ_und_kennt_die_alte_funktion_nicht_mehr(client, todo):
    seite = client.get(f"/a/todo/{todo['tokens']['TestAdmin']}/").get_data(as_text=True)
    assert "function zielGewaehlt" in seite
    assert "updateZielTyp" not in seite
    assert "ziel-typ-radio" not in seite and "todo-select" not in seite


def test_die_routen_verstehen_das_band_unveraendert(client, todo):
    """Das Band schickt genau die Felder, die `neu` schon immer erwartet."""
    v = todo["v"]
    token = todo["tokens"]["TestAdmin"]
    kind = todo["familie"]["TestKind"]["id"]
    client.post(f"/a/todo/{token}/neu", data={"inhalt": "An Kind", "ziel_typ": "person",
                                              "zugewiesen_an": str(kind)})
    client.post(f"/a/todo/{token}/neu", data={"inhalt": "An Rollen", "ziel_typ": "rollen",
                                              "rollen": ["kind", "gast"]})
    client.post(f"/a/todo/{token}/neu", data={"inhalt": "An alle", "ziel_typ": "alle",
                                              "ziel_alle": "alle", "privat": "on"})
    client.post(f"/a/todo/{token}/neu", data={"inhalt": "Fuer mich", "ziel_typ": "person",
                                              "zugewiesen_an": ""})
    zeilen = {z["inhalt"]: dict(z) for z in v.execute(
        "SELECT inhalt, zugewiesen_an, zugewiesen_rollen, privat, status FROM todos")}
    assert zeilen["An Kind"]["zugewiesen_an"] == kind and zeilen["An Kind"]["status"] == "offen"
    assert zeilen["An Rollen"]["zugewiesen_rollen"] == "gast,kind" and zeilen["An Rollen"]["status"] == "backlog"
    assert zeilen["An alle"]["zugewiesen_rollen"] == "alle" and zeilen["An alle"]["privat"] == 1
    assert zeilen["Fuer mich"]["zugewiesen_an"] is None and zeilen["Fuer mich"]["zugewiesen_rollen"] is None
