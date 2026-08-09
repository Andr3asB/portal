"""Wunsch #182: Die Werkstatt-Karte neu aufgeteilt.

Ausloeser war meine eigene Aenderung aus #180: Der Prio-Picker wurde breit
genug fuer „Zurueckgestellt" – und stand NEBEN dem Wunschtext, ohne zu
schrumpfen (`flex-shrink:0`). Auf dem iPhone blieb damit kaum Platz fuer den
Wunsch selbst.

Zwei Aenderungen, beide hier gewaechtert:

1. **Aktionen in eine eigene Zeile.** `flex-basis:100%` statt einer Spalte
   daneben – kein Breakpoint noetig, die Karte bricht ohnehin um.
2. **Vier Zeilen Vorschau.** Lange Wuensche fuellten sonst die halbe Liste.
   Der vollstaendige Text steht in der Detailansicht, die beim Antippen
   aufklappt – und dort MUSS der Deckel weg, sonst staende er zweimal
   gekuerzt da.
"""
import pathlib
import re

TPL = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"
INHALT = (TPL / "werkstatt_app.html").read_text(encoding="utf-8")


def _regel(name):
    block = INHALT[INHALT.index(name + " {"):]
    return " ".join(block[:block.index("}")].split())


def test_aktionen_stehen_in_eigener_zeile():
    """`flex-shrink:0` neben dem Text war die Ursache: Die Spalte gab keinen
    Platz her, egal wie schmal das Geraet war."""
    regel = _regel(".wunsch-actions")
    assert "flex-basis:100%" in regel.replace(" ", ""), (
        "Die Aktionen stehen wieder neben dem Text - auf dem iPhone bleibt "
        "dann kaum Platz fuer den Wunsch (Wunsch #182)."
    )
    assert "flex-direction:row" in regel.replace(" ", "")


def test_vorschau_ist_gedeckelt():
    regel = _regel(".wunsch-text")
    assert "-webkit-line-clamp:4" in regel.replace(" ", "")
    assert "overflow:hidden" in regel.replace(" ", "")


def test_aufgeklappt_faellt_der_deckel_weg():
    """Ohne diese Regel waere der Wunsch auch im aufgeklappten Zustand nach
    vier Zeilen abgeschnitten - das Aufklappen brächte dann gar nichts."""
    regel = _regel(".wunsch-card.offen .wunsch-text")
    assert "overflow:visible" in regel.replace(" ", "")


def test_die_karte_bekommt_den_zustand():
    """Der Deckel haengt an `.wunsch-card.offen`. Setzt das Javascript die
    Klasse nur am Detail-Panel, bleibt der Text gekuerzt - und niemand
    versteht, warum das Aufklappen nichts bewirkt."""
    block = INHALT[INHALT.index("function toggleWunschDetail"):]
    block = block[:block.index("\n}")]
    assert "wunsch-" in block and "offen" in block
    assert "detail.classList.contains('open')" in block, (
        "Der Kartenzustand muss dem Panel folgen, nicht unabhaengig "
        "umschalten - sonst laufen beide auseinander."
    )


def test_es_gibt_ein_sichtbares_zeichen_zum_aufklappen():
    """Vorher musste man raten, dass die Karte aufklappt."""
    assert "wunsch-pfeil" in INHALT
    assert INHALT.count('<span class="wunsch-pfeil">') == 2, (
        "Der Pfeil muss in BEIDEN Kartenarten stehen (offen und erledigt)."
    )


def test_prio_picker_hat_jetzt_platz():
    """Gegenprobe zu #180: Der Picker darf breit sein, WEIL er in einer
    eigenen Zeile steht. Beides zusammen ergibt erst das Layout."""
    picker = _regel(".prio-select").replace(" ", "")
    aktionen = _regel(".wunsch-actions").replace(" ", "")
    assert "width:185px" in picker
    assert "flex-basis:100%" in aktionen
