"""Wunsch #225: Liste und Brett sind gleichberechtigte Ansichten.

> „Die Brettansicht … soll als vollständige Alternativ Ansicht für die
> Aufgabenliste dienen. Für einen Benutzer sei gespeichert sein, welche
> Ansicht er zuletzt genutzt hat … Außerdem soll die Brettansicht alle
> Funktionen der Hauptansicht erhalten (Neu-Button, Filter, und so weiter)."

Zwei Teile, zwei Schwerpunkte in dieser Datei.

**Die gemerkte Ansicht** hängt serverseitig am Nutzer (`todo_nutzer_ansicht`),
nicht am Browser – „für einen Benutzer" heisst nicht „in diesem Tab"
(dieselbe Überlegung wie bei `packlisten_nutzer_ziel`, #116). Die Falle dabei
ist der Rückweg: Ohne `?ansicht=liste` am Link schickt die Merkung einen
sofort wieder aufs Brett, und die Liste ist nicht mehr erreichbar.
`test_der_rueckweg_in_die_liste_bleibt_offen` hält genau das fest.

**Die geteilten Bausteine** liegen in `todo_teile.html`. Der wichtigste Test
dazu ist `test_keine_zweite_fassung_der_formulare`: Zwei Kopien desselben
Formulars laufen in diesem Projekt erfahrungsgemäss auseinander, und der
Schaden fällt erst auf, wenn jemand über die „falsche" Ansicht speichert und
ein Feld stillschweigend verlorengeht.
"""
import pathlib
import re

import pytest

TPL = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"
LISTE = TPL / "todo.html"
BRETT = TPL / "todo_kanban.html"
TEILE = TPL / "todo_teile.html"


@pytest.fixture()
def tokens(app, db):
    from teile.kern import new_token, token_lookup
    v = db["verbindung"]
    aus = {}
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='todo'").fetchone()["id"]
        for name, daten in db["familie"].items():
            if "todo" in daten["tokens"]:
                aus[name] = daten["tokens"]["todo"]
                continue
            klartext = new_token()
            v.execute("INSERT INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                      (daten["id"], app_id, token_lookup(klartext)))
            aus[name] = klartext
    v.commit()
    return aus


def _gemerkt(db, user_id):
    zeile = db["verbindung"].execute(
        "SELECT ansicht FROM todo_nutzer_ansicht WHERE user_id=?", (user_id,)).fetchone()
    return zeile["ansicht"] if zeile else None


# ── Die gemerkte Ansicht ───────────────────────────────────────────────────

def test_ohne_vorgeschichte_kommt_die_liste(client, tokens, db):
    antwort = client.get(f"/a/todo/{tokens['TestAdmin']}/")
    assert antwort.status_code == 200


def test_das_brett_merkt_sich(client, tokens, db):
    client.get(f"/a/todo/{tokens['TestAdmin']}/kanban?ansicht=brett")
    assert _gemerkt(db, db["familie"]["TestAdmin"]["id"]) == "brett"


def test_ein_blosser_aufruf_aendert_die_vorliebe_nicht(client, tokens, db):
    """Gemerkt wird nur die ausdrückliche Wahl über den Knopf
    (`?ansicht=brett` / `?ansicht=liste`). Ein Aufruf der blossen Adresse –
    Lesezeichen, Weiterleitung, **oder `live_pruefung.py`, das beide Ansichten
    der Reihe nach abruft** – zeigt die Ansicht, verstellt aber nichts.

    Ohne diese Trennung schriebe jeder Prüflauf Andis Vorliebe auf das, was
    zufällig als letztes an der Reihe war. Ein Werkzeug, das nebenbei
    Nutzereinstellungen verändert, ist schlimmer als keines."""
    uid = db["familie"]["TestAdmin"]["id"]
    client.get(f"/a/todo/{tokens['TestAdmin']}/?ansicht=liste")
    assert _gemerkt(db, uid) == "liste"

    client.get(f"/a/todo/{tokens['TestAdmin']}/kanban")          # ohne Angabe
    assert _gemerkt(db, uid) == "liste", (
        "Der blosse Aufruf des Bretts hat die Vorliebe umgeschrieben")


def test_danach_oeffnet_die_app_das_brett(client, tokens, db):
    """Der Kern des Wunsches: Wer zuletzt das Brett gewählt hat, landet beim
    nächsten Öffnen wieder dort."""
    client.get(f"/a/todo/{tokens['TestAdmin']}/kanban?ansicht=brett")
    antwort = client.get(f"/a/todo/{tokens['TestAdmin']}/")
    assert antwort.status_code == 302
    assert antwort.headers["Location"].endswith("/kanban")


def test_der_rueckweg_in_die_liste_bleibt_offen(client, tokens, db):
    """Die Falle: Steht die Merkung auf „Brett", schickt ein Aufruf von
    /a/todo/ einen sofort wieder aufs Brett – auch den Zurück-Link. Ohne
    `?ansicht=liste` wäre die Liste damit unerreichbar."""
    client.get(f"/a/todo/{tokens['TestAdmin']}/kanban?ansicht=brett")
    antwort = client.get(f"/a/todo/{tokens['TestAdmin']}/?ansicht=liste")
    assert antwort.status_code == 200, "Der Rückweg in die Liste ist versperrt"
    assert _gemerkt(db, db["familie"]["TestAdmin"]["id"]) == "liste", (
        "Der ausdrückliche Wechsel wurde nicht gemerkt - beim nächsten Öffnen "
        "käme wieder das Brett")


def test_die_merkung_gilt_je_nutzer(client, tokens, db):
    """Sonst zöge Andis Vorliebe die ganze Familie mit."""
    client.get(f"/a/todo/{tokens['TestAdmin']}/kanban?ansicht=brett")
    antwort = client.get(f"/a/todo/{tokens['TestKind']}/")
    assert antwort.status_code == 200, "Fremde Merkung hat umgeleitet"


def test_nach_dem_anlegen_bleibt_man_im_brett(client, tokens, db):
    """Fällt aus der Merkung von selbst ab und ist trotzdem eine Zusage:
    Alle ändernden Routen leiten auf `index`, und von dort geht es über die
    Merkung zurück aufs Brett. Ohne das landete man nach jeder neuen Aufgabe
    in der Liste."""
    client.get(f"/a/todo/{tokens['TestAdmin']}/kanban?ansicht=brett")
    antwort = client.post(f"/a/todo/{tokens['TestAdmin']}/neu",
                          data={"inhalt": "Frisch", "ziel_typ": "person"})
    assert antwort.status_code == 302
    weiter = client.get(antwort.headers["Location"])
    assert weiter.status_code == 302 and weiter.headers["Location"].endswith("/kanban")


def test_ein_unsinniger_wert_faellt_auf_die_liste_zurueck(client, tokens, db):
    """Steht in der Tabelle etwas Unbekanntes (Altbestand, Tippfehler von
    Hand), darf die App nicht ins Leere leiten."""
    v = db["verbindung"]
    v.execute("INSERT INTO todo_nutzer_ansicht(user_id, ansicht) VALUES(?,?) "
              "ON CONFLICT(user_id) DO UPDATE SET ansicht=excluded.ansicht",
              (db["familie"]["TestAdmin"]["id"], "gibtsnicht"))
    v.commit()
    assert client.get(f"/a/todo/{tokens['TestAdmin']}/").status_code == 200


# ── Alle Funktionen auf dem Brett ──────────────────────────────────────────

@pytest.mark.parametrize("was, muster", [
    ("Neu-Knopf",       r'id="neu-toggle-btn"'),
    ("Neu-Formular",    r'id="new-todo-card"'),
    ("Filter-Knopf",    r'id="filter-toggle-btn"'),
    ("Filter-Karte",    r'id="filter-card"'),
    ("Ziel-Auswahl",    r'name="ziel_typ"'),
    ("Privat-Haken",    r'name="privat"'),
    ("Bearbeiten",      r'data-klick="toggleTodoEdit"'),
    ("Löschen",         r'loeschen/\d+'),
])
def test_das_brett_kann_dasselbe_wie_die_liste(client, tokens, db, was, muster):
    v = db["verbindung"]
    v.execute("INSERT INTO todos(inhalt, status, erstellt_von) VALUES('Testaufgabe','offen',?)",
              (db["familie"]["TestAdmin"]["id"],))
    v.commit()
    seite = client.get(f"/a/todo/{tokens['TestAdmin']}/kanban").get_data(as_text=True)
    assert re.search(muster, seite), f"{was} fehlt auf dem Brett"


def test_der_status_filter_ist_auch_auf_dem_brett(client, tokens):
    """Umgekehrte Zusage seit Wunsch #229 – und der Grund gehört hierher.

    Bei #225 hatte ich den Status-Filter auf dem Brett **weggelassen**, mit dem
    Argument: Die Spalten *sind* der Status, man könnte sonst eine Spalte
    leerfiltern, die man direkt daneben sieht. Andi hat das überstimmt, und
    zwar mit einer anderen Semantik als der von mir angenommenen: Ein
    abgewählter Status blendet **die ganze Spalte** aus, nicht nur ihre Karten.

    So gelesen war mein Einwand gegenstandslos – es entsteht keine leere
    Spalte. Das steht hier, damit niemand (auch ich nicht) den Filter unter
    Berufung auf die alte Begründung wieder entfernt."""
    seite = client.get(f"/a/todo/{tokens['TestAdmin']}/kanban").get_data(as_text=True)
    assert 'id="filter-nutzer-row"' in seite
    assert 'id="filter-status-row"' in seite


def test_ein_abgewaehlter_status_blendet_die_spalte_aus():
    """Andis Beispiel: Filter auf Offen/In Arbeit/Erledigt → Backlog erscheint
    gar nicht mehr. Eine leere Spalte stehen zu lassen wäre die halbe Antwort –
    sie nimmt auf dem Telefon eine ganze Bildschirmbreite ein, obwohl man sie
    gerade weggefiltert hat."""
    quelle = BRETT.read_text(encoding="utf-8")
    block = quelle[quelle.index("function zaehlerAuffrischen"):]
    block = block[:block.index("\n}")]
    assert "#filter-status-row" in block, (
        "Die Spaltensichtbarkeit fragt den Status-Filter gar nicht ab")
    assert "spalte.style.display" in block, (
        "Es wird nur gezählt, aber keine Spalte ausgeblendet")
    assert "!gewaehlt.length ||" in block, (
        "Ohne Auswahl müssen ALLE Spalten stehen bleiben - sonst ist das Brett "
        "leer, bis man etwas antippt")


def test_karten_tragen_die_filtermerkmale(client, tokens, db):
    v = db["verbindung"]
    v.execute("INSERT INTO todos(inhalt, status, erstellt_von) VALUES('Testaufgabe','offen',?)",
              (db["familie"]["TestAdmin"]["id"],))
    v.commit()
    seite = client.get(f"/a/todo/{tokens['TestAdmin']}/kanban").get_data(as_text=True)
    karte = re.search(r'<div class="karte"[^>]*>', seite).group(0)
    assert "data-nutzer=" in karte, "Ohne data-nutzer filtert der Knopf ins Leere"


# ── Geteilt, nicht verdoppelt ──────────────────────────────────────────────

@pytest.mark.parametrize("baustein", [
    'id="new-todo-card"',
    'id="filter-card"',
    'class="ziel-wrap"',
    'class="todo-edit-panel"',
])
def test_keine_zweite_fassung_der_formulare(baustein):
    """Der wichtigste Test dieser Datei.

    Zwei Kopien desselben Formulars laufen auseinander – in diesem Projekt
    mehrfach passiert (jeder Alias in `teile/__init__.py` existiert genau
    deshalb). Der Schaden fällt hier besonders spät auf: Ein Feld, das nur in
    einer Ansicht nachgezogen wurde, verschwindet still, sobald jemand über
    die andere speichert.

    Das Markup darf deshalb NUR in `todo_teile.html` stehen."""
    for datei in (LISTE, BRETT):
        inhalt = datei.read_text(encoding="utf-8")
        assert baustein not in inhalt, (
            f"{datei.name} hat eine eigene Fassung von {baustein!r} - "
            f"gehört nach todo_teile.html")
    assert baustein in TEILE.read_text(encoding="utf-8"), (
        f"{baustein!r} steht auch nicht in den geteilten Bausteinen")


def test_beide_ansichten_benutzen_die_gemeinsamen_bausteine():
    for datei in (LISTE, BRETT):
        inhalt = datei.read_text(encoding="utf-8")
        assert 'import "todo_teile.html"' in inhalt, datei.name
        assert "with context" in inhalt, (
            f"{datei.name}: ohne `with context` kennen die Makros `tp` nicht - "
            f"die Formular-Adressen wären falsch")
        assert "teile.gemeinsame_skripte(" in inhalt, datei.name


def test_der_filter_wirkt_in_beiden_ansichten_auf_dasselbe():
    """Ein zweiter Speicherschlüssel wäre eine Überraschung: Wer in der Liste
    nach einer Person filtert, erwartet das Brett genauso gefiltert."""
    gemeinsam = TEILE.read_text(encoding="utf-8")
    assert gemeinsam.count("const TODO_FILTER_KEY") == 1
    for datei in (LISTE, BRETT):
        assert "TODO_FILTER_KEY =" not in datei.read_text(encoding="utf-8"), datei.name
