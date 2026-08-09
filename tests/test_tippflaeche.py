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


# --- Wunsch #170/#173/#174: die uebrigen globalen Regeln -------------------

def test_eingabefelder_haben_16px_untergrenze():
    """iOS zoomt beim Fokus in Felder unter 16px hinein. `max(16px, 1em)`
    laesst groessere Schrift unberuehrt – ohne das haetten alle Felder
    portalweit exakt dieselbe Groesse, auch die absichtlich grossen."""
    glatt = " ".join(BASE.split())
    assert "input, select, textarea { font-size: max(16px, 1em); }" in glatt


@pytest.mark.parametrize("datei", sorted(TPL.glob("*.html")), ids=lambda p: p.name)
def test_keine_vorlage_setzt_schrift_unter_16px_auf_felder(datei):
    """Eine Vorlagenregel kaeme NACH base.html und gewaenne. Genau so ist der
    Zustand entstanden, den #170 behebt."""
    # base.html ist NICHT ausgenommen: seine eigene .wunsch-prio-select stand
    # auf 15px und schlug die globale Regel genauso wie jede Vorlage
    # (Klassenselektor gewinnt gegen Element-Selektor). Die globale Regel
    # selbst nutzt `max(16px, 1em)` und wird vom Muster nicht erfasst.
    inhalt = datei.read_text(encoding="utf-8")
    for m in re.finditer(r"\.([\w-]*(?:input|select|textarea|feld)[\w-]*)\s*(?:,[^{]*)?\{([^}]*)\}",
                         inhalt, re.I):
        fs = re.search(r"font-size:\s*(\d+)px", m.group(2))
        assert not (fs and int(fs.group(1)) < 16), (
            f"{datei.name}: .{m.group(1)} setzt {fs.group(1)}px – "
            f"iOS zoomt dann beim Antippen hinein (Wunsch #170)."
        )


def test_inhalt_hat_eine_lesebreite():
    """Ohne max-width laufen Zeilen auf breiten Monitoren ueber die ganze
    Fensterbreite."""
    glatt = " ".join(BASE.split())
    assert "max-width: 720px" in glatt and "margin: 0 auto" in glatt


def test_fokus_ring_nur_fuer_tastatur():
    """Beide Haelften sind noetig: der Ring fuer :focus-visible UND das
    ausdrueckliche Abschalten fuer Mausklicks – sonst saehen Maus-Nutzer
    ploetzlich ueberall Rahmen, wo vorher keine waren."""
    glatt = " ".join(BASE.split())
    assert ":focus:not(:focus-visible) { outline: none; }" in glatt
    assert ":focus-visible {" in glatt
    assert "outline: 2px solid var(--farbe)" in glatt


@pytest.mark.parametrize("datei", sorted(TPL.glob("*.html")), ids=lambda p: p.name)
def test_keine_vorlage_erschlaegt_den_fokus_ring(datei):
    """`outline:none` in einer Vorlage kaeme nach base.html und wuerde den
    Ring wieder abschalten – 21 Vorlagen taten das vor #174."""
    inhalt = datei.read_text(encoding="utf-8")
    if datei.name == "base.html":
        return
    assert "outline:none" not in inhalt.replace(" ", ""), (
        f"{datei.name} setzt outline:none – das erschlaegt den Fokus-Ring aus "
        f"base.html (Wunsch #174). Der Ring gilt ohnehin nur fuer Tastatur."
    )
