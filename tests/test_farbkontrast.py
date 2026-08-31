"""Wunsch #237/#238: Kontrast und Schriftgroesse stehen unter Wache.

Live gemessen am 31.08.2026: Kopfband 3,15:1, Verwaltungs-Chips 2,2:1,
Push-Badge 1,98:1 - und 10-11px-Beschriftungen quer durch die Apps. Die
Nutzerfarbe ist frei waehlbar, deshalb rechnet der Server kontrastfeste
Varianten aus (farbe_kontrast/farbe_kontrast_hell in 00_kern.py), und die
Vorlagen muessen sie auch verwenden. Genau das prueft diese Datei:

1. Die Mathematik der Helfer stimmt fuer beliebige Farben (auch #ffff00).
2. Keine Vorlage nutzt die rohe Nutzerfarbe als Textfarbe.
3. Keine Vorlage legt weissen Text auf die rohe Nutzerfarbe.
4. Keine Vorlage setzt Schrift unter 12px.
"""
import pathlib
import re

import pytest

from teile.kern import farbe_kontrast, farbe_kontrast_hell

TPL = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"


def _lum(hexf):
    r, g, b = (int(hexf[i:i + 2], 16) / 255 for i in (1, 3, 5))
    def f(v):
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _kontrast(a, b):
    l1, l2 = _lum(a), _lum(b)
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)


@pytest.mark.parametrize("farbe", [
    "#4a90d9", "#e8618c", "#5cb85c", "#f0ad4e", "#ffff00", "#ffffff",
    "#7952b3", "#111111", "#d9534f", "#00ff00",
])
def test_abgedunkelte_farbe_erreicht_45_auf_hellem_grund(farbe):
    """Gerechnet wird gegen --bg #f5f5f7 (dort stehen die Aktionsknoepfe) -
    Weiss ist heller, also gilt die Grenze dort automatisch mit."""
    assert _kontrast(farbe_kontrast(farbe), "#f5f5f7") >= 4.5
    assert _kontrast(farbe_kontrast(farbe), "#ffffff") >= 4.5


@pytest.mark.parametrize("farbe", [
    "#4a90d9", "#e8618c", "#5cb85c", "#f0ad4e", "#000000", "#111111",
    "#7952b3", "#d9534f", "#0000ff",
])
def test_aufgehellte_farbe_erreicht_45_auf_dunkler_karte(farbe):
    assert _kontrast(farbe_kontrast_hell(farbe), "#2c2c2e") >= 4.5


def test_kaputte_farbwerte_zerlegen_nichts():
    """Ein defekter Wert in der DB darf keinen 500er ausloesen - die Helfer
    geben die Eingabe unveraendert zurueck."""
    for kaputt in (None, "", "rot", "#12345", "#zzzzzz", 7):
        assert farbe_kontrast(kaputt) == kaputt
        assert farbe_kontrast_hell(kaputt) == kaputt


def test_basis_definiert_die_varianten():
    base = (TPL / "base.html").read_text(encoding="utf-8")
    assert "--farbe-band:" in base
    assert "--farbe-kontrast:" in base
    assert "farbe_kontrast_hell(" in base, (
        "Der Dunkelmodus braucht die AUFGEHELLTE Variante - die abgedunkelte "
        "waere auf dunklem Grund schlechter lesbar als die rohe Farbe."
    )
    assert re.search(r"\.app-header\s*\{[^}]*var\(--farbe-band\)", base), (
        "Das Kopfband muss auf --farbe-band stehen, sonst faellt weisser "
        "Text dort wieder unter 4,5:1."
    )


@pytest.mark.parametrize("datei", sorted(TPL.glob("*.html")), ids=lambda p: p.name)
def test_keine_rohe_farbe_als_textfarbe(datei):
    """`color: var(--farbe)` lag live bei 3,15:1. Textfarbe kommt aus
    var(--farbe-kontrast) - die passt sich auch dem Dunkelmodus an."""
    inhalt = datei.read_text(encoding="utf-8")
    treffer = [z.strip()[:80] for z in inhalt.splitlines()
               if re.search(r"(?<![-\w])color:\s*var\(--farbe\)[^-]", z)]
    assert not treffer, (
        f"{datei.name} nutzt die rohe Nutzerfarbe als Textfarbe: {treffer} "
        f"- var(--farbe-kontrast) verwenden (Wunsch #237)."
    )


@pytest.mark.parametrize("datei", sorted(TPL.glob("*.html")), ids=lambda p: p.name)
def test_kein_weisser_text_auf_roher_farbe(datei):
    """`background:var(--farbe)` + `color:#fff` im selben Regelblock war der
    haeufigste Fund (74 Stellen) - weisser Text gehoert auf --farbe-band."""
    inhalt = datei.read_text(encoding="utf-8")
    schlecht = []
    for m in re.finditer(r"\{([^}]*)\}", inhalt):
        block = m.group(1)
        if (re.search(r"background:\s*var\(--farbe\)\s*;", block)
                and re.search(r"color:\s*#fff", block)):
            schlecht.append(" ".join(block.split())[:80])
    assert not schlecht, (
        f"{datei.name}: weisser Text auf roher Nutzerfarbe: {schlecht} "
        f"- background:var(--farbe-band) verwenden (Wunsch #237)."
    )


@pytest.mark.parametrize("datei", sorted(TPL.glob("*.html")), ids=lambda p: p.name)
def test_keine_schrift_unter_12px(datei):
    """Wunsch #238: 12px ist die Untergrenze fuer alles - die 16px-Regel aus
    #170 deckt nur Eingabefelder. 10px-Beschriftungen (live: Geburtstage,
    Sportschau-Achsen) sind auf dem Handy nicht mehr lesbar."""
    inhalt = datei.read_text(encoding="utf-8")
    treffer = []
    for m in re.finditer(r"font-size:\s*(\d+(?:\.\d+)?)px", inhalt):
        if float(m.group(1)) < 12:
            zeile = inhalt[:m.start()].count("\n") + 1
            treffer.append(f"Zeile {zeile}: {m.group(0)}")
    assert not treffer, (
        f"{datei.name} setzt Schrift unter 12px: {treffer} (Wunsch #238)."
    )
