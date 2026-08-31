"""Wuensche #244/#245: System-Integration und Desktop-/Tastatur-Feinschliff.

Alles Zusagen in base.html, die unsichtbar sind, solange sie funktionieren -
und deren Fehlen nie auffiele (dieselbe Lage wie bei der Tippflaeche #169):

- prefers-reduced-motion schaltet Zier-Animationen ab (#244)
- color-scheme haengt am WURZEL-Element, je Theme (#244)
- touch-action: manipulation auf Bedienelementen (#244)
- Skip-Link als erster Tab-Stopp, Ziel <main id="main"> (#245)
- Hover-Feedback nur bei echter Maus (#245)
"""
import pathlib
import re

import pytest

TPL = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"
BASE = (TPL / "base.html").read_text(encoding="utf-8")


def test_reduced_motion_wird_beachtet():
    assert "@media (prefers-reduced-motion: reduce)" in BASE
    block = BASE[BASE.index("@media (prefers-reduced-motion: reduce)"):]
    block = block[:block.index("}\n    }") + 6] if "}\n    }" in block else block[:600]
    glatt = " ".join(block.split())
    # 0.01ms statt none: transitionend-Ereignisse muessen weiter feuern.
    assert "transition-duration: 0.01ms !important" in glatt
    assert "animation-duration: 0.01ms !important" in glatt


def test_smooth_scroll_prueft_die_systemeinstellung():
    """scrollTo({behavior:'smooth'}) ignoriert CSS scroll-behavior - das
    Skript muss selbst nachsehen."""
    assert "prefers-reduced-motion: reduce" in BASE.split("nachObenScrollen")[1][:400]


def test_color_scheme_haengt_an_der_wurzel():
    """Nur an Eingabefeldern gesetzt blieben Scrollbalken und native
    Bedienelemente im Dunkelmodus hell."""
    glatt = " ".join(BASE.split())
    # In der ERSTEN html-Regel (mit scroll-padding-top) - eine eigene zweite
    # wuerde test_kopfzeile_bleibt die falsche Regel unterschieben.
    assert re.search(r"html \{ scroll-padding-top:[^}]*color-scheme: light", glatt)
    assert "html:has(body.dark) { color-scheme: dark; }" in glatt
    assert "html:has(body.auto) { color-scheme: dark; }" in glatt, (
        "Der Wie-das-Geraet-Modus (body.auto) braucht die Regel im "
        "prefers-color-scheme-Block."
    )


def test_bedienelemente_ohne_doppeltipp_verzoegerung():
    glatt = " ".join(BASE.split())
    assert "touch-action: manipulation" in glatt


def test_skip_link_ist_der_erste_tab_stopp():
    assert 'class="skip-link" href="#main"' in BASE
    body_start = BASE.index("<body")
    assert BASE.index("skip-link", body_start) < BASE.index("app-header", body_start), (
        "Der Skip-Link muss VOR der Kopfleiste stehen, sonst ueberspringt "
        "er nichts."
    )
    assert ".skip-link:focus-visible" in BASE


@pytest.mark.parametrize("datei", sorted(TPL.glob("*.html")), ids=lambda p: p.name)
def test_jede_vorlage_hat_das_skip_ziel(datei):
    """Der Skip-Link zeigt auf #main - eine Vorlage ohne id waere eine Seite,
    auf der der Link kommentarlos nichts tut."""
    inhalt = datei.read_text(encoding="utf-8")
    # Nur echte Tags am Zeilenanfang - "<main>" kommt auch in Kommentaren vor.
    for m in re.finditer(r"^<main\b[^>]*>", inhalt, re.MULTILINE):
        assert 'id="main"' in m.group(0), (
            f"{datei.name}: <main> ohne id=\"main\" - Skip-Link-Ziel fehlt "
            f"(Wunsch #245)."
        )


def test_hover_feedback_nur_bei_echter_maus():
    """Ohne das Media-Query klebte der Hover-Zustand auf Touch-Geraeten nach
    jedem Tipp fest."""
    assert "@media (hover: hover)" in BASE
    block = BASE[BASE.index("@media (hover: hover)"):]
    assert "button:hover" in block[:300] and "a.knopf:hover" in block[:300]


def test_offline_banner_meldet_sich_bei_screenreadern():
    assert re.search(r'id="offline-banner"[^>]*aria-live="polite"', BASE)
