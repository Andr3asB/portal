"""`scripts/wunsch_lauf_check.py` – die Einteilung, nach der der Stundenlauf
(#157) handelt.

Das Skript ist nur lesend und entscheidet nichts. Es beantwortet genau eine
Frage – gibt es Arbeit? – und teilt dafür in drei Listen ein. Diese Einteilung
ist trotzdem sicherheitsrelevant für den unbeaufsichtigten Lauf:

* Zu viel in **ANTWORTEN**, und derselbe Wunsch wird stündlich neu
  aufgegriffen. Genau das passierte am 13.08.2026 mit #130: umgesetzt, per
  Notiz dokumentiert, aber nicht abhakbar (er wartet auf einen Schlüssel von
  Andi) – und trotzdem stündlich als „neue Antwort" gemeldet.
* Zu wenig in **ANTWORTEN**, und eine Antwort von Andi geht unter. Der
  gefährlichere Fehler von beiden, deshalb steht `test_antwort_nach_der_arbeit_
  zaehlt_wieder` hier: schreibt Andi NACH meiner Notiz noch etwas, muss der
  Wunsch wieder auftauchen.
* Etwas in **FREIGEGEBEN**, das dort nicht hingehört, und die Automatik setzt
  um, was niemand freigegeben hat. Ohne Priorität und `zurueckgestellt` sind
  darum eigene Fälle (#61/#152).

Getestet wird das Skript als eigener Prozess gegen eine Wegwerf-Datenbank –
so, wie es auch im Betrieb läuft (`DB_PATH` aus der Umgebung), nur ohne
Container.
"""
import os
import pathlib
import sqlite3
import subprocess
import sys

import pytest

SKRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "wunsch_lauf_check.py"

SCHEMA = """
CREATE TABLE wuensche(
  id INTEGER PRIMARY KEY, text TEXT, app_slug TEXT, erstellt TEXT,
  erledigt INT DEFAULT 0, titel TEXT, prioritaet TEXT, ansicht TEXT);
CREATE TABLE wunsch_aktionen(
  id INTEGER PRIMARY KEY, wunsch_id INT, art TEXT, text TEXT, erstellt TEXT);
"""

# (id, titel, prioritaet, erledigt, [(art, datum), …])
FAELLE = [
    (1, "Frage offen",             "hoch",            0, [("frage", "2026-08-01")]),
    (2, "Echte neue Antwort",      "hoch",            0, [("frage", "2026-08-01"),
                                                          ("antwort", "2026-08-02")]),
    (3, "Beantwortet, bearbeitet", "hoch",            0, [("frage", "2026-08-01"),
                                                          ("antwort", "2026-08-02"),
                                                          ("notiz", "2026-08-03")]),
    (4, "Antwort nach der Arbeit", "hoch",            0, [("frage", "2026-08-01"),
                                                          ("notiz", "2026-08-02"),
                                                          ("antwort", "2026-08-03")]),
    (5, "Nur Notiz, nie gefragt",  "hoch",            0, [("notiz", "2026-08-02")]),
    (6, "Freigegeben, unberuehrt", "mittel",          0, []),
    (7, "Zurueckgestellt",         "zurueckgestellt", 0, []),
    (8, "Ohne Prioritaet",         None,              0, []),
    (9, "Schon erledigt",          "hoch",            1, []),
]


@pytest.fixture(scope="module")
def ausgabe(tmp_path_factory):
    pfad = tmp_path_factory.mktemp("lauf") / "pruef.db"
    db = sqlite3.connect(pfad)
    db.executescript(SCHEMA)
    for wid, titel, prio, erledigt, aktionen in FAELLE:
        db.execute("INSERT INTO wuensche(id,text,titel,prioritaet,erledigt,erstellt) "
                   "VALUES(?,?,?,?,?,'2026-08-01')", (wid, titel, titel, prio, erledigt))
        for art, wann in aktionen:
            db.execute("INSERT INTO wunsch_aktionen(wunsch_id,art,text,erstellt) "
                       "VALUES(?,?,?,?)", (wid, art, art, wann))
    db.commit()
    db.close()

    umgebung = dict(os.environ, DB_PATH=str(pfad))
    fertig = subprocess.run([sys.executable, str(SKRIPT)], env=umgebung,
                            capture_output=True, text=True, encoding="utf-8",
                            check=False)
    assert fertig.returncode == 0, fertig.stderr
    return fertig.stdout


def _abschnitt(text, ueberschrift):
    """Die IDs unterhalb einer der drei Überschriften."""
    import re
    teil = text.split(ueberschrift, 1)[1]
    teil = re.split(r"\n=== ", teil)[0]
    return {int(m) for m in re.findall(r"^\s+#(\d+)", teil, re.MULTILINE)}


def test_zaehler_und_listen_sagen_dasselbe(ausgabe):
    """Die erste Zeile ist das, worauf der Lauf reagiert - sie darf nicht von
    dem abweichen, was darunter steht."""
    import re
    kopf = re.match(r"ARBEIT: (\d+)\s+\(antworten=(\d+) freigegeben=(\d+) "
                    r"wartet_auf_andi=(\d+)\)", ausgabe)
    assert kopf, ausgabe.splitlines()[0]
    arbeit, antworten, freigegeben, wartet = map(int, kopf.groups())

    assert arbeit == antworten + freigegeben, "ARBEIT zaehlt Wartende mit"
    assert antworten == len(_abschnitt(ausgabe, "=== NEUE ANTWORTEN"))
    assert freigegeben == len(_abschnitt(ausgabe, "=== FREIGEGEBEN"))
    assert wartet == len(_abschnitt(ausgabe, "=== WARTET AUF ANDI"))


def test_neue_antwort_wird_gemeldet(ausgabe):
    assert 2 in _abschnitt(ausgabe, "=== NEUE ANTWORTEN")


def test_beantwortet_und_bearbeitet_wartet_wieder_auf_andi(ausgabe):
    """Der Fall vom 13.08.2026 (#130). Ohne diese Unterscheidung meldet der
    Lauf denselben Wunsch stuendlich als neue Arbeit."""
    assert 3 not in _abschnitt(ausgabe, "=== NEUE ANTWORTEN")
    assert 3 in _abschnitt(ausgabe, "=== WARTET AUF ANDI")


def test_antwort_nach_der_arbeit_zaehlt_wieder(ausgabe):
    """Die Gegenrichtung, und der gefaehrlichere Fehler: Schreibt Andi NACH
    der Notiz noch etwas, ist das eine echte neue Antwort. Wer nur auf
    'gibt es eine Notiz?' prueft, verschluckt sie."""
    assert 4 in _abschnitt(ausgabe, "=== NEUE ANTWORTEN")
    assert 4 not in _abschnitt(ausgabe, "=== WARTET AUF ANDI")


def test_notiz_ohne_frage_ist_kein_warten(ausgabe):
    """Eine Notiz auf einem Wunsch, den nie jemand gefragt hat, laesst
    niemanden warten - der Wunsch ist schlicht freigegeben."""
    assert 5 not in _abschnitt(ausgabe, "=== WARTET AUF ANDI")
    assert 5 in _abschnitt(ausgabe, "=== FREIGEGEBEN")


def test_freigegeben_ist_freigegeben(ausgabe):
    assert 6 in _abschnitt(ausgabe, "=== FREIGEGEBEN")


@pytest.mark.parametrize("wid, warum", [
    (7, "zurueckgestellt ist unantastbar (#61)"),
    (8, "ohne Prioritaet heisst NICHT freigegeben (#152/#157)"),
    (9, "erledigte Wuensche sind erledigt"),
])
def test_diese_fasst_der_lauf_nicht_an(ausgabe, wid, warum):
    for ueberschrift in ("=== NEUE ANTWORTEN", "=== FREIGEGEBEN", "=== WARTET AUF ANDI"):
        assert wid not in _abschnitt(ausgabe, ueberschrift), warum


def test_bei_null_bleibt_es_bei_einer_zeile(tmp_path):
    """Die Regel, ohne die 24 Fortschrittsberichte am Tag herauskaemen: Ist
    nichts zu tun, muss das an der ERSTEN Zeile ablesbar sein."""
    pfad = tmp_path / "leer.db"
    db = sqlite3.connect(pfad)
    db.executescript(SCHEMA)
    db.commit()
    db.close()

    fertig = subprocess.run([sys.executable, str(SKRIPT)],
                            env=dict(os.environ, DB_PATH=str(pfad)),
                            capture_output=True, text=True, encoding="utf-8",
                            check=False)
    assert fertig.returncode == 0, fertig.stderr
    assert fertig.stdout.startswith("ARBEIT: 0")
