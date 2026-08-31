"""Wunsch #156: „Werden im Protokoll auch Änderungen dokumentiert (z.B. wenn
der Betreff editiert oder der Betrag verändert wird)? Das soll auch
dokumentiert sein."

Die Antwort ist: Es gibt keine Änderungen. Ein Eintrag ist nach dem Speichern
unveränderlich – so verlangt es schon Wunsch #144 („ein bisschen wie bei einem
Buchhaltungssystem"). Betrag, Zweck, Person und Datum lassen sich von
niemandem nachträglich anfassen, auch nicht von Eltern oder Admin. Einem
Eintrag kann genau zweierlei widerfahren: angelegt und storniert – und beides
steht im Prüfprotokoll.

Damit hängt aber die Vollständigkeit des Protokolls an einer Eigenschaft des
Codes, die nirgends erzwungen wird. Genau das holen diese Tests nach: Sobald
jemand eine Bearbeiten-Route ergänzt, fällt hier etwas um – zusammen mit dem
Hinweis, dass das Protokoll dann eine dritte Ereignisart braucht.

Ein Prüfer kann sonst nämlich nicht unterscheiden, ob keine Änderungen
stattgefunden haben oder ob Änderungen nicht protokolliert werden.
"""
import pathlib
import re

import pytest

QUELLE = (pathlib.Path(__file__).resolve().parents[1]
          / "src" / "teile" / "22_kassenbuch.py").read_text(encoding="utf-8")


def test_es_gibt_genau_drei_schreibende_routen(app):
    """Anlegen, Startbetrag, Stornieren – mehr darf es nicht geben.

    Über `url_map` statt über den Quelltext: eine Route, die versehentlich
    doppelt registriert oder aus einem anderen Modul ergänzt wird, taucht
    hier trotzdem auf."""
    erlaubt = {"kassenbuch_app.start", "kassenbuch_app.eintrag_neu",
               "kassenbuch_app.stornieren"}
    gefunden = {
        regel.endpoint
        for regel in app.url_map.iter_rules()
        if str(regel).startswith("/a/kassenbuch")
        and regel.methods & {"POST", "PUT", "PATCH", "DELETE"}
    }
    assert gefunden == erlaubt, (
        f"Neue schreibende Route(n) im Kassenbuch: {gefunden - erlaubt}. "
        f"Wenn damit ein Eintrag geändert werden kann, braucht das "
        f"Prüfprotokoll (#153) eine dritte Ereignisart 'geändert'."
    )


def test_kein_loeschen_im_quelltext():
    """Ein Ledger löscht nicht. Das Aufräumen meiner Testbuchungen am
    08.08.2026 lief bewusst auf DB-Ebene und ausserhalb der App."""
    assert "DELETE FROM kassenbuch_eintraege" not in QUELLE


def test_jedes_update_betrifft_nur_das_storno():
    """Der Kern: JEDE ändernde Anweisung fasst ausschliesslich die
    Storno-Spalten an. Würde eine davon eines Tages auch `betrag_cent` oder
    `zweck` setzen, wäre das Prüfprotokoll unvollständig, ohne dass es jemand
    merkt.

    Bis Wunsch #216 stand hier „genau EIN UPDATE". Die Richtigstellung des
    Startbetrags hat ein zweites hinzugefügt - bewusst als Storno des alten
    und Neuanlage statt als Überschreiben des Betrags, damit die Zusage
    unangetastet bleibt und die Korrektur im Protokoll von selbst als
    angelegt / storniert / angelegt erscheint. Die Zahl der Anweisungen ist
    also nicht der Massstab; ihr Inhalt ist es.
    """
    anweisungen = re.findall(
        r"UPDATE\s+kassenbuch_eintraege\s+SET\s+(.*?)\s+WHERE",
        QUELLE, re.DOTALL | re.IGNORECASE)
    assert anweisungen, "Kein UPDATE gefunden - greift das Muster noch?"

    for anweisung in anweisungen:
        spalten = {t.split("=")[0].strip().lower() for t in anweisung.split(",")}
        assert spalten == {"storniert", "storniert_von", "storniert_am"}, (
            f"Dieses UPDATE fasst mehr als das Storno an: {sorted(spalten)}. "
            f"Wenn ein Eintrag wirklich änderbar werden soll, braucht das "
            f"Prüfprotokoll (#153) eine dritte Ereignisart 'geändert'."
        )


# --- Und dasselbe am laufenden Objekt --------------------------------------

@pytest.fixture()
def eintrag(app, db):
    """Ein Kind mit Kassenbuch-Zugang und einer Ausgabe.

    conftest schaltet `kassenbuch` nicht frei (die Testfamilie bekommt nur
    home/hilfe/einkauf), deshalb hier ein eigener Grant."""
    from teile.kern import new_token, token_lookup
    v = db["verbindung"]
    kind = db["familie"]["TestKind"]["id"]

    with app.app_context():
        app_id = v.execute(
            "SELECT id FROM apps WHERE slug='kassenbuch'").fetchone()["id"]
        klartext = new_token()
        v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) "
                  "VALUES(?,?,?)", (kind, app_id, token_lookup(klartext)))

    eid = v.execute("""
        INSERT INTO kassenbuch_eintraege
            (user_id, art, betrag_cent, person, zweck, datum, erstellt_von)
        VALUES (?, 'ausgabe', 250, 'Kiosk', 'Comicheft', '2026-08-02', ?)
        RETURNING id
    """, (kind, kind)).fetchone()["id"]
    v.commit()
    return {"id": eid, "token": klartext}


def test_storno_laesst_die_inhalte_unangetastet(client, db, eintrag):
    """Nach einem Storno müssen Betrag, Zweck, Person und Datum exakt
    dieselben sein – sonst wäre „storniert" in Wahrheit eine Änderung."""
    v = db["verbindung"]
    vorher = dict(v.execute(
        "SELECT betrag_cent, person, zweck, datum, art FROM kassenbuch_eintraege "
        "WHERE id=?", (eintrag["id"],)).fetchone())

    client.post(f"/a/kassenbuch/{eintrag['token']}/eintrag/{eintrag['id']}/stornieren")

    zeile = v.execute("SELECT * FROM kassenbuch_eintraege WHERE id=?",
                      (eintrag["id"],)).fetchone()
    assert zeile["storniert"] == 1, "Voraussetzung: das Storno muss gegriffen haben"
    for feld, wert in vorher.items():
        assert zeile[feld] == wert, f"{feld} wurde beim Stornieren verändert"
