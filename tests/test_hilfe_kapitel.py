"""Wunsch #242: Die Hilfe-Kapitel sind eingeklappt (details/summary).

Die Seite war live 29.943px hoch - ein einziges langes Dokument. Jedes
Kapitel ist jetzt ein <details>; das Inhaltsverzeichnis (und ein direkter
#kapitel-N-Link) klappt das Ziel per Skript auf, sonst spraenge man zu einer
zugeklappten Ueberschrift.
"""
import pathlib
import re

TPL = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"
INHALT = (TPL / "hilfe.html").read_text(encoding="utf-8")


def test_jedes_kapitel_ist_ein_details():
    kapitel_ids = set(re.findall(r"id=\"(kapitel-\d+)\"", INHALT))
    details_ids = set(re.findall(
        r"<details class=\"section\" id=\"(kapitel-\d+)\">", INHALT))
    assert kapitel_ids and kapitel_ids == details_ids, (
        f"Nicht jedes Kapitel ist ein <details>: {sorted(kapitel_ids - details_ids)} "
        f"- neue Kapitel nach demselben Muster bauen (Wunsch #242)."
    )
    assert INHALT.count("<details") == INHALT.count("</details>")


def test_toc_fuehrt_zu_jedem_kapitel():
    """Das Inhaltsverzeichnis (kapitel-Liste oben) muss dieselben Anker
    kennen wie die Kapitel selbst - sonst gibt es unerreichbare Kapitel."""
    toc = re.findall(r"\('(kapitel-\d+)',", INHALT)
    details = re.findall(r"<details class=\"section\" id=\"(kapitel-\d+)\">", INHALT)
    assert sorted(toc) == sorted(details)


def test_sprunglink_oeffnet_das_zielkapitel():
    """Ohne das Skript landet ein #kapitel-N-Link auf einer zugeklappten
    Ueberschrift und der Inhalt bleibt unsichtbar."""
    assert "oeffneKapitel" in INHALT
    assert "location.hash" in INHALT, (
        "Direkte Links (#kapitel-N, z. B. aus Push-Nachrichten) muessen das "
        "Kapitel ebenfalls aufklappen."
    )
