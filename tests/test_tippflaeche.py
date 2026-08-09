"""Wunsch #169: Jeder Knopf hat mindestens 44x44 px Trefferfläche.

Die Lösung ist EINE Regel in base.html: ein unsichtbares Pseudo-Element, das
über kleine Knöpfe hinausragt und Tipps an sie weiterreicht. Damit hängt die
Zusage an zwei Bedingungen, und genau die stehen hier unter Wache:

1. Die Regel existiert (und niemand „räumt sie auf", weil sie unsichtbar ist
   und ihr Fehlen nie auffiele – ein Tipp daneben fühlt sich an wie eigenes
   Zittern, nicht wie ein Fehler).
2. Keine Vorlage definiert ein eigenes `button::before` – das würde die
   Trefferfläche genau dort ersetzen, wo jemand dem Knopf etwas Hübsches
   verpassen will, und der Knopf würde still wieder klein.

Die tatsächliche Wirkung (elementFromPoint neben dem Knopf trifft den Knopf)
ist Layout und wird im Browser geprüft, nicht hier – pytest rendert nicht.
"""
import pathlib
import re

import pytest

TPL = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"
BASE = (TPL / "base.html").read_text(encoding="utf-8")


def test_die_trefferflaechen_regel_existiert():
    # Auf den SELEKTOR anspringen ("button::before {"), nicht auf die erste
    # Erwaehnung - der Erklaerkommentar in base.html nennt den Namen ebenfalls,
    # und die erste Fassung dieses Tests biss sich daran fest: Slice begann im
    # Kommentar, endete an der naechsten Klammer und enthielt nie die Regel.
    assert "button::before {" in BASE
    regel = BASE[BASE.index("button::before {"):]
    regel = regel[:regel.index("}")]
    glatt = " ".join(regel.split())
    # BEIDE Achsen einzeln pruefen: die erste Gegenprobe entfernte nur die
    # width-Untergrenze, und der Test blieb gruen, weil height die gesuchte
    # Zeichenkette weiterhin enthielt.
    assert "width: max(100%, 44px)" in glatt, "44px-Untergrenze fuer die BREITE fehlt."
    assert "height: max(100%, 44px)" in glatt, "44px-Untergrenze fuer die HOEHE fehlt."
    assert 'content: ""' in regel or "content:''" in regel, (
        "Ohne content rendert das Pseudo-Element nicht und faengt keine Tipps."
    )


def test_buttons_sind_bezugsrahmen():
    """`button { position: relative; }` gehört zur Regel: Ohne sie hängt sich
    das absolute Pseudo-Element an den nächsten positionierten VORFAHREN und
    die Trefferfläche läge irgendwo, nur nicht auf dem Knopf."""
    assert re.search(r"button\s*\{\s*position:\s*relative", BASE)


@pytest.mark.parametrize("datei", sorted(TPL.glob("*.html")), ids=lambda p: p.name)
def test_keine_vorlage_ersetzt_die_trefferflaeche(datei):
    """Ein template-eigenes `button::before` (oder auf einer Button-Klasse)
    überschriebe die globale Regel – der Knopf würde still wieder klein."""
    if datei.name == "base.html":
        return
    inhalt = datei.read_text(encoding="utf-8")
    treffer = re.findall(r"[\w.-]*(?:button|btn)[\w-]*::(?:before|after)", inhalt)
    assert not treffer, (
        f"{datei.name} definiert {treffer} - das ersetzt die 44px-Trefferflaeche "
        f"aus base.html. Anderes Pseudo-Element nehmen oder die Flaeche im "
        f"eigenen ::before mit uebernehmen (siehe Wunsch #169)."
    )
