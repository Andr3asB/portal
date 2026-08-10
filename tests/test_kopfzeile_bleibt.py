"""Wunsch #186: Die Navigation muss immer erreichbar sein.

Zur Wahl standen ein „Nach oben"-Knopf (wie auf der Hilfeseite) und eine
mitlaufende Kopfzeile. Entschieden: **die Kopfzeile bleibt stehen.**

Ein Knopf unten rechts bringt einen nach oben – die Leiste hält ausserdem ⌂,
den Seitentitel und das ☰-Menü dauerhaft erreichbar und kostet keinen
zusätzlichen Tipp. Sie ist ausserdem das, was 2026 überall so aussieht; ein
schwebender Pfeil ist die Lösung aus der Zeit, als `position: sticky` noch
nicht überall trug.

**Der Teil, den man dabei übersieht:** Sprungziele. Die Werkstatt springt auf
`#wunsch-<id>` (Wunsch #171), die Geburtstage auf `#gb-<id>`, die Hilfe auf
ihre Kapitel. Ohne `scroll-padding-top` landet jedes dieser Ziele **unter**
der stehenden Leiste – die Navigation wäre erreichbar und das Ziel dafür
unsichtbar. Deshalb prüft der grösste Teil dieser Datei nicht das Kleben,
sondern seine Nebenwirkung.
"""
import pathlib
import re

import pytest

TPL  = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"
BASE = (TPL / "base.html").read_text(encoding="utf-8")


def _regel(css: str, selektor: str) -> str:
    treffer = re.search(re.escape(selektor) + r"\s*\{([^}]*)\}", css)
    assert treffer, f"Regel {selektor} fehlt."
    return treffer.group(1).replace(" ", "").replace("\n", "")


# --- Die Leiste selbst ------------------------------------------------------

def test_die_kopfzeile_bleibt_stehen():
    regel = _regel(BASE, ".app-header")
    assert "position:sticky" in regel
    assert "top:0" in regel


def test_sie_liegt_ueber_dem_inhalt_aber_unter_den_dialogen():
    """Eine Kopfzeile über dem eigenen Hamburger-Menü wäre ein seltsamer
    Anblick - und der ✨-Dialog liegt noch darüber."""
    kopf = int(re.search(r"z-index:\s*(\d+)", _regel(BASE, ".app-header")
                         .replace("z-index:", "z-index: ")).group(1))
    menue = int(re.search(r"z-index:\s*(\d+)", BASE[BASE.index(".menu-overlay"):]).group(1))
    dialog = int(re.search(r"z-index:\s*(\d+)", BASE[BASE.index("#wunsch-overlay"):]).group(1))
    assert 0 < kopf < menue < dialog, (kopf, menue, dialog)


# --- Die Nebenwirkung: Sprungziele -----------------------------------------

def test_sprungziele_landen_nicht_unter_der_leiste():
    regel = _regel(BASE, "html")
    assert "scroll-padding-top" in regel, (
        "Ohne scroll-padding-top verschwindet jedes #anker-Ziel unter der "
        "stehenden Kopfzeile (Wunsch #186)."
    )


def test_der_abstand_deckt_die_kopfhoehe():
    """Ein zu kleiner Wert ist schlimmer als keiner: Es sieht dann fast
    richtig aus, und die erste Zeile fehlt trotzdem."""
    regel = _regel(BASE, "html")
    wert = re.search(r"scroll-padding-top:calc\(var\(--st\)\+(\d+)px\)", regel)
    assert wert, f"unerwartete Form: {regel}"
    # Kopf = --st + 6 (padding-top) + 46 (nav-bar min-height) + 6 (padding-bottom)
    assert int(wert.group(1)) >= 58, "kleiner als die Kopfzeile selbst"


@pytest.mark.parametrize("datei,anker", [
    ("werkstatt_app.html", 'id="wunsch-{{ w.id }}"'),
    ("geburtstage.html",   'id="gb-{{ e.id }}"'),
])
def test_es_gibt_die_sprungziele_ueberhaupt(datei, anker):
    """Wäre keins mehr da, prüfte der Test darüber eine Regel ohne Anlass."""
    assert anker in (TPL / datei).read_text(encoding="utf-8")


# --- Kein Alleingang in einzelnen Vorlagen ---------------------------------

@pytest.mark.parametrize("datei", sorted(TPL.glob("*.html")), ids=lambda p: p.name)
def test_keine_vorlage_baut_die_kopfzeile_um(datei):
    """`.app-header` gehört base.html. Eine Vorlage, die die Regel
    überschreibt, nähme genau dieser einen Seite das Kleben - und niemandem
    fiele es auf, weil die anderen 18 weiter klebten."""
    if datei.name == "base.html":
        return
    inhalt = datei.read_text(encoding="utf-8")
    ohne_kommentar = re.sub(r"/\*.*?\*/", "", inhalt, flags=re.S)
    ohne_kommentar = re.sub(r"\{#.*?#\}", "", ohne_kommentar, flags=re.S)
    assert ".app-header" not in ohne_kommentar, (
        f"{datei.name} fasst .app-header an - das gehoert in base.html."
    )


def test_die_leiste_steht_auf_jeder_seite(client, db):
    """Sie kommt aus base.html, also auf jeder Seite, die davon erbt - der
    Test hält fest, dass keine Seite ihren eigenen Kopf baut."""
    andi = db["familie"]["TestAdmin"]["tokens"]
    for slug in ("admin", "todo", "einkauf", "hilfe"):
        text = client.get(f"/a/{slug}/{andi[slug]}/").get_data(as_text=True)
        assert '<header class="app-header">' in text, slug
