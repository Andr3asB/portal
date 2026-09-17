"""Wunsch #288 (Sicherheitsaudit 16.09.2026, Befund N-09): 403 gegen 404
verriet, wie viele fremde private Aufgaben es gibt.

`set_status` und `bearbeiten` antworteten 404 für eine ID, die es nicht gibt,
und 403 für eine, die es gibt, aber unsichtbar ist. Ein Kind konnte die IDs
durchzählen. `kanban_verschieben` machte es schon richtig: Wer eine Aufgabe
nicht sehen darf, soll auch nicht erfahren, dass es sie gibt.

Drei Fälle, damit die Unterscheidung stimmt: nicht vorhanden → 404,
unsichtbar → 404 (das ist der Fix), sichtbar aber nicht änderbar → 403
(das darf so bleiben, die Aufgabe ist ja auf der Liste zu sehen).
"""
import pytest


@pytest.fixture()
def todo_token(app, db):
    from teile.kern import new_token, token_lookup
    v = db["verbindung"]
    tokens = {}
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='todo'").fetchone()["id"]
        for name, daten in db["familie"].items():
            klartext = new_token()
            v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) "
                      "VALUES(?,?,?)", (daten["id"], app_id, token_lookup(klartext)))
            tokens[name] = klartext
    v.commit()
    return tokens


def _todo(db, von, an, privat):
    v = db["verbindung"]
    tid = v.execute(
        "INSERT INTO todos(inhalt, erstellt_von, zugewiesen_an, privat, status) "
        "VALUES(?,?,?,?,'offen') RETURNING id", ("Geheimes", von, an, privat)).fetchone()["id"]
    v.commit()
    return tid


@pytest.mark.parametrize("route, daten", [
    ("status", {"status": "erledigt"}),
    ("bearbeiten", {"inhalt": "umgeschrieben"}),
])
def test_unsichtbare_aufgabe_ist_nicht_vorhanden(client, db, eltern, kind, todo_token, route, daten):
    privat = _todo(db, eltern["id"], eltern["id"], 1)      # privat, nur Eltern
    tok = todo_token["TestKind"]
    assert client.post(f"/a/todo/{tok}/{route}/{privat}", data=daten).status_code == 404
    assert client.post(f"/a/todo/{tok}/{route}/999999", data=daten).status_code == 404
    # und die Aufgabe ist unveraendert
    row = db["verbindung"].execute("SELECT inhalt, status FROM todos WHERE id=?", (privat,)).fetchone()
    assert (row["inhalt"], row["status"]) == ("Geheimes", "offen")


def test_fremde_aufgabe_ist_fuer_ein_kind_ebenfalls_unsichtbar(client, db, eltern, kind, todo_token):
    """Auch eine NICHT private Aufgabe, die jemand anderem zugewiesen ist,
    steht nicht auf der Liste des Kindes (`_visible_todos`) - also 404, nicht
    403. Fuer ein Kind fallen "sichtbar" und "aenderbar" praktisch zusammen;
    der 403-Zweig bleibt als zweiter Riegel fuer den Fall, dass die
    Sichtbarkeit einmal weiter gefasst wird als das Aendern."""
    offen = _todo(db, eltern["id"], eltern["id"], 0)
    tok = todo_token["TestKind"]
    assert client.post(f"/a/todo/{tok}/status/{offen}", data={"status": "erledigt"}).status_code == 404


def test_eltern_sehen_alles_und_bekommen_403_nie(client, db, eltern, kind, todo_token):
    """Eltern sehen jede Aufgabe und duerfen jede aendern - fuer sie gibt es
    weder 404 noch 403 auf vorhandene IDs."""
    privat = _todo(db, kind["id"], kind["id"], 1)
    tok = todo_token["TestEltern"]
    assert client.post(f"/a/todo/{tok}/status/{privat}", data={"status": "erledigt"}).status_code == 302


def test_eigene_aufgabe_geht_weiterhin(client, db, kind, todo_token):
    eigene = _todo(db, kind["id"], kind["id"], 1)
    tok = todo_token["TestKind"]
    assert client.post(f"/a/todo/{tok}/status/{eigene}", data={"status": "erledigt"}).status_code == 302
