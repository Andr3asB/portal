"""Wunsch #247: Echte Ueberschriften statt divs.

Screenreader-Nutzer springen per Ueberschriften-Navigation - vorher gab es
im ganzen Portal ausser der 403-Seite kein einziges h1-h6. Jetzt: der
Seitentitel ist ein h1 (class nav-title, Optik unveraendert), Inhalts-
Abschnitte sind h2. Filter-Etiketten ("Status", "Prioritaet" in
Filterkarten) bleiben bewusst divs - sie gliedern kein Dokument.
"""
import pathlib
import re

import pytest

TPL = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"


@pytest.mark.parametrize("datei", sorted(TPL.glob("*.html")), ids=lambda p: p.name)
def test_der_seitentitel_ist_ein_h1(datei):
    """`<div class="nav-title">` war die alte Form - neue Vorlagen sollen
    nicht dorthin zurueckfallen."""
    inhalt = datei.read_text(encoding="utf-8")
    assert '<div class="nav-title"' not in inhalt, (
        f"{datei.name}: nav-title als div - muss ein h1 sein (Wunsch #247)."
    )
    # base.html definiert den leeren Block nur - gefuellt wird er von den
    # Vorlagen, dort greift die Pruefung.
    if datei.name != "base.html" and "{% block nav_title %}" in inhalt:
        block = inhalt.split("{% block nav_title %}")[1].split("{% endblock %}")[0]
        assert block.count("<h1") == 1, (
            f"{datei.name}: der nav_title-Block braucht genau ein h1."
        )


def test_die_hilfe_kapitel_sind_ueberschriften():
    inhalt = (TPL / "hilfe.html").read_text(encoding="utf-8")
    summaries = re.findall(r"<summary class=\"section-title\">(.*?)</summary>", inhalt)
    assert summaries and all(s.startswith("<h2>") for s in summaries), (
        "Jedes Hilfe-Kapitel traegt sein h2 IM summary (Wunsch #247)."
    )


def test_es_gibt_ueberhaupt_abschnitts_ueberschriften():
    """Sonst waere die Zusage still verschwunden - mindestens die bekannten
    Inhalts-Abschnitte (Werkstatt, Aufgaben, TVB, Rezept-Detail, ...)."""
    anzahl = sum(p.read_text(encoding="utf-8").count("<h2")
                 for p in TPL.glob("*.html"))
    assert anzahl >= 30, f"nur {anzahl} h2 gefunden - Abschnitte wieder divs?"
