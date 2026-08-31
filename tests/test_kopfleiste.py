"""Wunsch #155: Aktionsknöpfe gehören ins `<main>`, nicht auf den Header.

Andi: „Die Buttons sind noch mit dem Header des Portals verbunden. das haben
wir doch in allen Apps geändert. scheint hier zurückgeblieben zu sein."

Er hatte recht: `header_extra` war ein Block in `base.html`, über den man
Knöpfe direkt auf das farbige Kopfband kleben konnte, und die Verwaltung war
die letzte App, die ihn noch benutzte.

Solche Abweichungen fallen nur auf, wenn jemand hinsieht – deshalb hier ein
Wächter statt eines einmaligen Umbaus. Er prüft die Vorlagen als Text; das
ist grob, aber es ist die Ebene, auf der der Fehler entsteht.
"""
import pathlib
import re

import pytest

VORLAGEN = sorted(
    (pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates")
    .glob("*.html")
)


def test_es_gibt_vorlagen():
    """Fände der Pfad nichts, wären alle Prüfungen unten leer und grün."""
    assert len(VORLAGEN) > 20


@pytest.mark.parametrize("datei", VORLAGEN, ids=lambda p: p.name)
def test_keine_knoepfe_am_header(datei):
    """`header_extra` ist ersatzlos entfallen. Ein Template, das ihn wieder
    definiert, würde nichts rendern – der Knopf verschwände lautlos."""
    inhalt = datei.read_text(encoding="utf-8")
    # Der Hinweis-Kommentar in base.html/admin.html darf den Namen nennen.
    ohne_kommentare = re.sub(r"\{#.*?#\}", "", inhalt, flags=re.DOTALL)
    assert "header_extra" not in ohne_kommentare, (
        f"{datei.name} benutzt den entfernten Block `header_extra`. "
        f"Aktionen gehören oben ins <main>, siehe .top-aktionen in todo.html."
    )


@pytest.mark.parametrize("datei", VORLAGEN, ids=lambda p: p.name)
def test_kein_knopf_zwischen_header_und_main(datei):
    """Zwischen `</header>` und `<main>` darf keine Schaltfläche stehen –
    dort landete sie optisch wieder am farbigen Band.

    **Dieser Test war lange vacuous.** Seit die Kopfzeile nur noch in
    base.html steht, enthaelt KEINE Vorlage beide Marken: die Vorlagen haben
    `<main`, aber kein `</header>`; base.html umgekehrt. Der Test kehrte
    also immer sofort zurueck, ohne etwas zu pruefen - aufgefallen erst, als
    eine absichtlich eingebaute Verletzung gruen blieb.

    Er prueft jetzt, was in der heutigen Struktur dasselbe bedeutet: In einer
    Vorlage darf zwischen `{% block body %}` und ihrem `<main>` keine
    Schaltflaeche stehen. Genau dort saesse sie optisch am farbigen Band.
    """
    # Auch JS- und CSS-Kommentare herausschneiden, nicht nur Jinja-
    # Kommentare: Ein Erklaerkommentar in base.html, der das Wort `<main>`
    # nennt, liess diesen Waechter sonst anschlagen. VIERTER Fall dieser Art
    # im Projekt (header_extra, button::before, data-fetch) - Beispiele in
    # Kommentaren sind kein Markup.
    inhalt = re.sub(r"\{#.*?#\}", "", datei.read_text(encoding="utf-8"), flags=re.DOTALL)
    inhalt = re.sub(r"/\*.*?\*/", "", inhalt, flags=re.DOTALL)
    inhalt = re.sub(r"^\s*//.*$", "", inhalt, flags=re.MULTILINE)
    if "<main" not in inhalt:
        return
    if "</header>" in inhalt:
        vorher = inhalt.split("</header>", 1)[1]
    elif "{% block body %}" in inhalt:
        vorher = inhalt.split("{% block body %}", 1)[1]
    else:
        return
    dazwischen = vorher.split("<main", 1)[0]
    assert not re.search(r"<(button|a)\b", dazwischen), (
        f"{datei.name} hat eine Schaltfläche zwischen </header> und <main>."
    )


def test_verwaltung_hat_ihre_aktionen_im_inhalt():
    """Der Anlass des Wunsches, festgenagelt: die beiden Knöpfe der
    Verwaltung stehen im <main> und tragen die übliche Klasse."""
    inhalt = (pathlib.Path(__file__).resolve().parents[1]
              / "src" / "teile" / "templates" / "admin.html").read_text(encoding="utf-8")
    hauptteil = inhalt.split("<main", 1)[1]
    assert 'class="top-aktionen"' in hauptteil
    assert "Neues Mitglied" in hauptteil
    assert "Geräte" in hauptteil


def test_toter_kopf_stil_ist_weg():
    """`.btn-add` in admin.html war weiss auf farbigem Grund – ausserhalb des
    Headers unsichtbar. Bliebe die Regel stehen, würde sie beim nächsten Knopf
    versehentlich wiederverwendet."""
    inhalt = (pathlib.Path(__file__).resolve().parents[1]
              / "src" / "teile" / "templates" / "admin.html").read_text(encoding="utf-8")
    assert "btn-add" not in inhalt
