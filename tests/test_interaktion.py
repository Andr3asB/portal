"""Wunsch #248: Die Interaktions-Ebene – Dialoge, aria-expanded, Tastatur-Sortieren, Emoji.

Vier Konventionen aus dem vierten Review-Durchgang (01.09.2026), alle in
base.html zentral umgesetzt und hier gewächtert:

1. **Overlays sind Dialoge.** Hamburger-Menü und ✨-Wunsch tragen
   `role="dialog"` + `aria-modal`, `dialogFuehrung()` liefert Fokus-Falle,
   Escape und Fokus-Rückgabe. Ein neues Overlay ohne diese Semantik wäre für
   die Tastatur unsichtbar.
2. **Auf/Zu-Knöpfe melden ihren Zustand.** Ein Knopf, der ein Panel öffnet,
   trägt `data-panel="<id>"` – `aufzuSync()` in base.html hält daraus
   `aria-expanded` aktuell. Ohne das Attribut erfährt ein Screenreader nie,
   ob das Panel offen ist.
3. **Wer ziehen kann, kann auch tippen.** `ziehSortierung()` bringt die
   Pfeiltasten-Bedienung selbst mit; Vorlagen mit EIGENER Zieh-Fassung
   (`initKatDrag`) müssen `tastaturSortierung()` einzeln aufrufen.
4. **Emoji: Schmuck ist stumm, Inhalt spricht.** Nach `twemoji.parse()`
   versteckt base.html jedes Emoji-Bild (alt="" + aria-hidden), außer es
   steht in einem Element mit `data-emoji-alt` – App-Kacheln und Nutzertext.
"""
import pathlib
import re

import pytest

TPL = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"
BASE = (TPL / "base.html").read_text(encoding="utf-8")

# data-klick-Funktionen, die ein Panel auf-/zuklappen. Wer eine neue
# toggle*-Funktion an einen Knopf hängt, hängt auch data-panel daran.
TOGGLE_KLICKS = ("toggle", "gbEditUmschalten", "gbPanelUmschalten",
                 "gbFormularUmschalten")
# Knöpfe, die über eine feste id ein Panel öffnen (addEventListener statt
# data-klick) - dieselbe Pflicht.
TOGGLE_IDS = ("filter-toggle-btn", "neu-toggle-btn", "einkauf-start-btn")


def _knoepfe(inhalt):
    return [m.group(0) for m in re.finditer(r"<button[^>]*>", inhalt)]


def _ist_toggle(tag):
    if any(f'id="{i}"' in tag for i in TOGGLE_IDS):
        return True
    m = re.search(r'data-klick="(\w+)"', tag)
    return bool(m and m.group(1).startswith(TOGGLE_KLICKS))


# --- 1. Dialog-Semantik ----------------------------------------------------

def test_beide_overlays_sind_dialoge():
    assert BASE.count('role="dialog"') == 2, (
        "base.html hat zwei Overlays (Menü, ✨-Wunsch) - beide brauchen "
        'role="dialog" am Panel (Wunsch #248).')
    assert BASE.count('aria-modal="true"') == 2


def test_dialoge_haben_fuehrung():
    """Rolle ohne Verhalten wäre eine leere Zusage: Escape, Fokus-Falle und
    Fokus-Rückgabe stecken in dialogFuehrung() - beide Overlays laufen
    darüber."""
    assert "function dialogFuehrung" in BASE
    assert "'Escape'" in BASE
    assert "menueDialog" in BASE and "wunschDialog" in BASE


def test_menueknopf_meldet_zustand():
    tag = re.search(r'<button[^>]*id="menu-btn"[^>]*>', BASE)
    assert tag and "data-panel=" in tag.group(0), (
        "Der ☰-Knopf braucht data-panel, damit aufzuSync() sein "
        "aria-expanded pflegt (Wunsch #248).")


# --- 2. aria-expanded über data-panel --------------------------------------

def test_aufzusync_existiert():
    assert "aufzuSync" in BASE and "aria-expanded" in BASE


def test_es_gibt_ueberhaupt_toggle_knoepfe():
    """Fände das Muster nichts, wären die Prüfungen unten leer und grün."""
    alle = [t for f in TPL.glob("*.html")
            for t in _knoepfe(f.read_text(encoding="utf-8")) if _ist_toggle(t)]
    assert len(alle) >= 15, f"nur {len(alle)} gefunden - Muster kaputt?"


@pytest.mark.parametrize("datei", sorted(TPL.glob("*.html")), ids=lambda p: p.name)
def test_jeder_toggle_knopf_traegt_data_panel(datei):
    for tag in _knoepfe(datei.read_text(encoding="utf-8")):
        if _ist_toggle(tag):
            assert "data-panel=" in tag, (
                f"{datei.name}: Auf/Zu-Knopf ohne data-panel - Screenreader "
                f"erfahren nie, ob das Panel offen ist (Wunsch #248): {tag}")


# --- 3. Tastatur-Sortieren -------------------------------------------------

def test_zentraler_helfer_vorhanden():
    assert "window.tastaturSortierung" in BASE
    # ziehSortierung bringt die Tastatur selbst mit - eine neue Zieh-Liste
    # über den zentralen Helfer kann sie nicht vergessen.
    assert "window.tastaturSortierung(opt)" in BASE


@pytest.mark.parametrize("datei", sorted(TPL.glob("*.html")), ids=lambda p: p.name)
def test_eigene_zieh_fassungen_rufen_tastatur(datei):
    inhalt = datei.read_text(encoding="utf-8")
    if "initKatDrag" in inhalt:
        assert "tastaturSortierung(" in inhalt, (
            f"{datei.name}: eigene Zieh-Fassung ohne Tastatur-Alternative "
            f"(Wunsch #248) - tastaturSortierung() mit denselben Optionen "
            f"aufrufen.")


# --- 4. Emoji: Schmuck stumm, Inhalt spricht -------------------------------

def test_emoji_nachlauf_in_base():
    assert re.search(r"closest\('\[data-emoji-alt\]'\)", BASE), (
        "base.html muss nach twemoji.parse() Schmuck-Emoji verstecken "
        "(alt='' + aria-hidden) - Ausnahme data-emoji-alt (Wunsch #248).")
    assert "aria-hidden" in BASE


def test_app_kacheln_behalten_ihr_emoji():
    """Die Kacheln sind laut Wunsch ausdrücklich bedeutungstragend."""
    inhalt = (TPL / "startseite.html").read_text(encoding="utf-8")
    kacheln = re.findall(r'<span class="tile-emoji"[^>]*>', inhalt)
    assert kacheln, "Muster kaputt? Keine tile-emoji-Spans gefunden."
    for tag in kacheln:
        assert "data-emoji-alt" in tag, f"Kachel-Emoji ohne data-emoji-alt: {tag}"
