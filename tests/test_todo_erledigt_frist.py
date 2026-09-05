"""Wunsch #243: Laenger als 7 Tage Erledigtes verschwindet aus beiden
Aufgaben-Ansichten (Liste und Brett).

Dieselbe Frist wie bei der Packliste (#234), damit sich das Portal ueberall
gleich verhaelt. Geloescht wird nichts: `?erledigt=alle` (und der Zaehl-Link)
holt alles zurueck. Altbestand ohne erledigt_am bleibt bewusst sichtbar.
"""
import pytest
from teile.kern import new_token, token_lookup


@pytest.fixture()
def todo_token(app, db):
    daten = db["familie"]["TestAdmin"]
    if "todo" in daten["tokens"]:
        return daten["tokens"]["todo"]
    v = db["verbindung"]
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='todo'").fetchone()["id"]
        klartext = new_token()
        v.execute("INSERT INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                  (daten["id"], app_id, token_lookup(klartext)))
        v.commit()
    return klartext


def _aufgabe(db, inhalt, erledigt_vor_tagen=None):
    v = db["verbindung"]
    if erledigt_vor_tagen is None:
        v.execute("INSERT INTO todos(inhalt, erstellt_von, status) VALUES(?,?, 'offen')",
                  (inhalt, db["familie"]["TestAdmin"]["id"]))
    else:
        v.execute(
            "INSERT INTO todos(inhalt, erstellt_von, status, erledigt, erledigt_am) "
            f"VALUES(?,?, 'erledigt', 1, datetime('now', '-{erledigt_vor_tagen} days'))",
            (inhalt, db["familie"]["TestAdmin"]["id"]))
    v.commit()


@pytest.mark.parametrize("pfad", ["", "kanban"])
def test_alt_erledigtes_ist_in_beiden_ansichten_ausgeblendet(client, db, todo_token, pfad):
    _aufgabe(db, "Uralt erledigt", erledigt_vor_tagen=10)
    _aufgabe(db, "Frisch erledigt", erledigt_vor_tagen=2)
    seite = client.get(f"/a/todo/{todo_token}/{pfad}").get_data(as_text=True)
    assert "Uralt erledigt" not in seite
    assert "Frisch erledigt" in seite
    assert "ältere" in seite or "erledigte anzeigen" in seite, (
        "Ohne Hinweis-Link sieht die ausgeblendete Aufgabe aus wie geloescht."
    )


@pytest.mark.parametrize("pfad", ["?erledigt=alle", "kanban?erledigt=alle"])
def test_erledigt_alle_holt_alles_zurueck(client, db, todo_token, pfad):
    _aufgabe(db, "Uralt erledigt", erledigt_vor_tagen=10)
    seite = client.get(f"/a/todo/{todo_token}/{pfad}").get_data(as_text=True)
    assert "Uralt erledigt" in seite


def test_offene_aufgaben_kennen_keine_frist(client, db, todo_token):
    """Eine seit Wochen offene Aufgabe ist eine Erinnerung, kein Ballast."""
    _aufgabe(db, "Ewig offen")
    db["verbindung"].execute(
        "UPDATE todos SET erstellt=datetime('now', '-60 days') WHERE inhalt='Ewig offen'")
    db["verbindung"].commit()
    assert "Ewig offen" in client.get(f"/a/todo/{todo_token}/").get_data(as_text=True)


def test_altbestand_ohne_zeitstempel_bleibt_sichtbar(client, db, todo_token):
    """Aufgaben, die vor der erledigt_am-Spalte abgehakt wurden, duerfen beim
    Ausrollen nicht kommentarlos verschwinden."""
    v = db["verbindung"]
    v.execute("INSERT INTO todos(inhalt, erstellt_von, status, erledigt) "
              "VALUES('Alt ohne Stempel', ?, 'erledigt', 1)",
              (db["familie"]["TestAdmin"]["id"],))
    v.commit()
    assert "Alt ohne Stempel" in client.get(f"/a/todo/{todo_token}/").get_data(as_text=True)


def test_die_brett_weiterleitung_verliert_den_parameter_nicht(client, db, todo_token):
    """Wer das Brett gemerkt hat und in der Liste 'alle anzeigen' tippt, wird
    auf /kanban weitergeleitet - ?erledigt=alle muss mitkommen."""
    v = db["verbindung"]
    v.execute("INSERT OR REPLACE INTO todo_nutzer_ansicht(user_id, ansicht) VALUES(?, 'brett')",
              (db["familie"]["TestAdmin"]["id"],))
    v.commit()
    antwort = client.get(f"/a/todo/{todo_token}/?erledigt=alle")
    assert antwort.status_code == 302
    assert "erledigt=alle" in antwort.headers["Location"]
