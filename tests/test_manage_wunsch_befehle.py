"""Die beiden Kommandozeilen-Wege in die Werkstatt.

`manage.py wunsch_neu` und `manage.py wunsch_aktion` sind entstanden, weil
beim Arbeiten Wünsche und Rückfragen anfallen, für die es sonst nur die
Weboberfläche gäbe – und was von der Kommandozeile aus nicht geht, landet am
Ende gar nicht im System (die Rückfrage zu #188 stand zwei Läufe lang nur im
Chat).

**Der eine Test, auf den es hier wirklich ankommt:** `wunsch_neu` darf
*niemals* eine Priorität setzen. Der stündliche Lauf (#157) arbeitet alles
ab, was eine Priorität ausser `zurueckgestellt` trägt. Ein Befehl, der
Wünsche anlegen *und* priorisieren könnte, wäre eine Maschine, die sich
selbst Arbeit aufträgt und sie eine Stunde später ausführt. Deshalb gibt es
dafür bewusst nicht einmal einen Schalter.

Die Befehle laufen im Container gegen dieselbe Datenbank wie die App; hier
werden sie als Funktion aufgerufen, mit `DB_PATH` auf die Testdatenbank.
"""
import importlib
import sys

import pytest


@pytest.fixture()
def manage(app, monkeypatch):
    """manage.py gegen die Testdatenbank."""
    monkeypatch.setenv("DB_PATH", app.config["DB_PATH"])
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve()
                           .parents[1] / "src"))
    modul = importlib.import_module("manage")
    importlib.reload(modul)
    return modul


# --- wunsch_neu -------------------------------------------------------------

def test_neuer_wunsch_hat_keine_prioritaet(manage, db, capsys):
    """Die Sicherheitsaussage dieser Datei. Mit Priorität würde der
    stündliche Lauf ihn in der nächsten Stunde selbst umsetzen."""
    manage.cmd_wunsch_neu(["tvb", "Ein Titel", "Ein Wunschtext"])
    zeile = db["verbindung"].execute(
        "SELECT titel, text, app_slug, prioritaet, erledigt FROM wuensche"
    ).fetchone()
    assert zeile["prioritaet"] is None
    assert zeile["titel"] == "Ein Titel"
    assert zeile["text"] == "Ein Wunschtext"
    assert zeile["app_slug"] == "tvb"
    assert zeile["erledigt"] == 0


def test_zusaetzliche_argumente_setzen_keine_prioritaet(manage, db):
    """Weder ein viertes Argument noch ein --prio darf durchrutschen."""
    manage.cmd_wunsch_neu(["tvb", "Titel", "Text", "sehr_hoch"])
    manage.cmd_wunsch_neu(["tvb", "Titel2", "Text2", "--prio", "hoch"])
    prios = [r["prioritaet"] for r in
             db["verbindung"].execute("SELECT prioritaet FROM wuensche")]
    assert prios == [None, None], prios


def test_die_quelle_kennt_ueberhaupt_keine_prioritaet():
    """Der Test darueber prueft das Ergebnis. Dieser prueft, dass es dafuer
    gar keinen Weg gibt: In der Funktion steht die Spalte nur als NULL. Kaeme
    jemand spaeter auf die Idee, einen Schalter nachzuruesten, faellt es hier
    auf - und nicht erst, wenn der stuendliche Lauf sich selbst beauftragt.

    Die erste Fassung dieses Tests war ein Blindgaenger: ein
    `pytest.raises(SystemExit)` um ein `raise SystemExit` herum, das der Test
    selbst ausloeste. Er war gruen, egal was manage.py tat.
    """
    import pathlib as _p
    quelle = (_p.Path(__file__).resolve().parents[1] / "src" / "manage.py"
              ).read_text(encoding="utf-8")
    block = quelle[quelle.index("def cmd_wunsch_neu("):]
    block = block[:block.index("def cmd_wunsch_aktion(")]
    # Die Anweisung steht ueber zwei Zeilen und ist zusammengesetzt - erst
    # zusammensetzen, dann pruefen. Zeilenweise zu suchen hiesse, die Zeile
    # mit der Spaltenliste anzumeckern, in der das NULL gar nicht stehen kann.
    import re as _re
    code = _re.sub(r"\s+", " ", block)
    code = code.replace('" "', "")            # Zeichenketten-Naht schliessen
    assert "prioritaet" in code, "Muster kaputt - Spalte kommt gar nicht mehr vor."
    assert "prioritaet) VALUES(?,?,?,NULL)" in code, (
        "wunsch_neu schreibt die Prioritaet nicht mehr fest als NULL - damit "
        "koennte der Befehl Wuensche anlegen, die der stuendliche Lauf eine "
        "Stunde spaeter selbst umsetzt."
    )


def test_unbekannter_app_slug_bricht_ab(manage, db):
    """Sonst steht der Wunsch unter einer App, die es nicht gibt, und taucht
    in keinem Filter auf."""
    with pytest.raises(SystemExit):
        manage.cmd_wunsch_neu(["gibtsnicht", "Titel", "Text"])
    assert db["verbindung"].execute(
        "SELECT COUNT(*) FROM wuensche").fetchone()[0] == 0


def test_zu_wenige_argumente(manage, db):
    with pytest.raises(SystemExit):
        manage.cmd_wunsch_neu(["tvb", "nur ein Titel"])


def test_langer_titel_wird_gekuerzt(manage, db):
    """`wuensche.titel` ist auf 80 Zeichen ausgelegt (wie beim KI-Titel)."""
    manage.cmd_wunsch_neu(["tvb", "T" * 200, "Text"])
    titel = db["verbindung"].execute("SELECT titel FROM wuensche").fetchone()[0]
    assert len(titel) == 80


# --- wunsch_aktion ----------------------------------------------------------

def test_aktion_haengt_am_richtigen_wunsch(manage, app, db, monkeypatch):
    v = db["verbindung"]
    wid = v.execute("INSERT INTO wuensche(text) VALUES('Ein Wunsch') RETURNING id"
                    ).fetchone()["id"]
    v.commit()
    manage.cmd_wunsch_aktion([str(wid), "notiz", "Eine Notiz"])
    zeile = v.execute("SELECT wunsch_id, art, text FROM wunsch_aktionen").fetchone()
    assert (zeile["wunsch_id"], zeile["art"], zeile["text"]) == (wid, "notiz", "Eine Notiz")


def test_rueckfrage_loest_push_aus(manage, app, db, monkeypatch):
    """Eine Rückfrage, die niemanden erreicht, ist so gut wie nicht gestellt -
    genau der Fehler, aus dem dieser Befehl entstanden ist."""
    import teile.werkstatt_app as wa
    gesendet = []
    monkeypatch.setattr(wa, "push_send", lambda *a, **k: gesendet.append(a))
    v = db["verbindung"]
    wid = v.execute("INSERT INTO wuensche(text) VALUES('Unklar') RETURNING id"
                    ).fetchone()["id"]
    v.commit()
    manage.cmd_wunsch_aktion([str(wid), "frage", "Wie meinst du das?"])
    assert len(gesendet) == 1, "kein Push an den Admin"
    assert f"#{wid}" in gesendet[0][1]


def test_notiz_loest_keinen_push_aus(manage, app, db, monkeypatch):
    """Sonst entwerten die Meldungen sich selbst (Wunsch #166)."""
    import teile.werkstatt_app as wa
    gesendet = []
    monkeypatch.setattr(wa, "push_send", lambda *a, **k: gesendet.append(a))
    v = db["verbindung"]
    wid = v.execute("INSERT INTO wuensche(text) VALUES('X') RETURNING id").fetchone()["id"]
    v.commit()
    manage.cmd_wunsch_aktion([str(wid), "notiz", "Nur eine Notiz"])
    assert gesendet == []


def test_unbekannte_art_bricht_ab(manage, app, db):
    v = db["verbindung"]
    wid = v.execute("INSERT INTO wuensche(text) VALUES('X') RETURNING id").fetchone()["id"]
    v.commit()
    with pytest.raises(SystemExit):
        manage.cmd_wunsch_aktion([str(wid), "quatsch", "Text"])
    assert v.execute("SELECT COUNT(*) FROM wunsch_aktionen").fetchone()[0] == 0


def test_unbekannter_wunsch_bricht_ab(manage, app, db):
    with pytest.raises(SystemExit):
        manage.cmd_wunsch_aktion(["99999", "notiz", "Text"])
    assert db["verbindung"].execute(
        "SELECT COUNT(*) FROM wunsch_aktionen").fetchone()[0] == 0
