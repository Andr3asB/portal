"""Wunsch #226: Beim Ziehen wird kein Text markiert.

> „Beim Ziehen von Aufgaben kommt es immer wieder vor, dass der Text der
> anderen Aufgaben zum Kopieren markiert wird."

Der Browser hält die Zieh-Bewegung für eine Textauswahl und färbt reihenweise
fremde Karten blau ein. Das `preventDefault()` beim Aufsetzen genügt dagegen
nicht – es unterdrückt die Auswahl nur am Griff, nicht auf allem, worüber der
Finger danach hinwegzieht.

Behoben in `ziehSortierung()` und damit für **jede** Zieh-Liste im Portal:
Packliste, Essensplan und Kanban hatten dasselbe Problem, gemeldet wurde es
nur am Brett.

Die zwei Tests, auf die es ankommt, prüfen die beiden Hälften der Zusage:

* `test_die_sperre_haengt_nur_am_ziehen` – die Klasse muss in **beiden**
  Ausgängen wieder verschwinden. Bleibt sie nach einem abgebrochenen Zug
  hängen, ist die halbe Seite dauerhaft nicht mehr markierbar, und niemand
  ahnt, warum.
* `test_ausserhalb_des_ziehens_bleibt_alles_markierbar` – ein dauerhaftes
  `user-select:none` auf den Karten wäre die naheliegende, aber falsche
  Lösung: Einen Aufgabentext kopieren zu können ist eine Funktion, keine
  Nebensache.
"""
import pathlib
import re

import pytest

TPL = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"
BASE = TPL / "base.html"


def _helfer():
    quelle = BASE.read_text(encoding="utf-8")
    block = quelle[quelle.index("window.ziehSortierung"):]
    return block[:block.index("\n  };")]


def _funktion(name):
    block = _helfer()
    block = block[block.index(f"function {name}(e) {{"):]
    return block[:block.index("\n    }")]


def test_es_gibt_ueberhaupt_eine_sperre():
    """Fängt ab, dass die Prüfungen unten ins Leere greifen."""
    quelle = BASE.read_text(encoding="utf-8")
    assert "body.zieht" in quelle
    assert re.search(r"body\.zieht[^{]*\{[^}]*user-select:\s*none", quelle, re.DOTALL), (
        "Die Klasse `zieht` schaltet die Textauswahl gar nicht ab")


def test_die_sperre_greift_beim_start():
    assert "classList.add('zieht')" in _funktion("starte")


@pytest.mark.parametrize("ausgang", ["ende", "abbruch"])
def test_die_sperre_haengt_nur_am_ziehen(ausgang):
    """Beide Ausgänge müssen sie lösen. Bleibt sie nach einem abgebrochenen
    Zug (Finger weggerutscht, Anruf dazwischen) hängen, ist die halbe Seite
    dauerhaft nicht mehr markierbar – bis zum nächsten Neuladen, und niemand
    ahnt, warum."""
    assert "classList.remove('zieht')" in _funktion(ausgang), (
        f"{ausgang}() hebt die Markierungssperre nicht auf")


def test_die_sperre_wird_vor_der_pruefung_geloest():
    """`ende()` verlässt sich früh auf `zustand.laeuft`. Stünde das Lösen
    innerhalb dieses Blocks, bliebe die Sperre bei jedem Zug hängen, der die
    8-Pixel-Schwelle nicht überschritten hat – also bei jedem versehentlichen
    Antippen des Griffs."""
    for ausgang in ("ende", "abbruch"):
        rumpf = _funktion(ausgang)
        assert rumpf.index("classList.remove('zieht')") < rumpf.index("if (zustand.laeuft)"), (
            f"In {ausgang}() haengt das Loesen an `zustand.laeuft`")


def test_ausserhalb_des_ziehens_bleibt_alles_markierbar():
    """Die naheliegende, aber falsche Lösung wäre ein dauerhaftes
    `user-select:none` auf den Karten. Einen Aufgabentext zu kopieren ist
    eine Funktion – man will die Adresse aus einer Aufgabe herausholen."""
    for datei in ("todo_kanban.html", "packliste.html", "todo.html"):
        pfad = TPL / datei
        if not pfad.exists():
            continue
        for zeile in pfad.read_text(encoding="utf-8").split("\n"):
            if "user-select" not in zeile:
                continue
            assert "griff" in zeile.lower() or "handle" in zeile.lower(), (
                f"{datei}: `user-select` ausserhalb eines Ziehgriffs - damit "
                f"laesst sich der Text dauerhaft nicht mehr markieren:\n{zeile}")


def test_eine_bestehende_auswahl_wird_aufgehoben():
    """Wer vorher versehentlich Text markiert hatte, zöge ihn sonst sichtbar
    blau mit sich herum – die Sperre verhindert nur NEUE Auswahl."""
    assert "removeAllRanges" in _funktion("starte")
