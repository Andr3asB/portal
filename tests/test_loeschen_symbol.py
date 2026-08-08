"""Wunsch #160: Löschen sieht überall gleich aus – 🗑️.

> „Ich suche alle Seiten in allen Apps und ändere den Link, um einen Datensatz
> zu löschen in einen Mülleimer Symbol. […] Verankert diese Entscheidung für
> die grafische Oberfläche so, dass alle zukünftigen Apps auf die gleiche
> Weise gebaut werden."

Der zweite Satz ist der wichtigere. Ein einmaliger Umbau hält, bis jemand die
nächste App baut und wieder ein ✕ nimmt, weil es in der Nachbardatei so
aussah – genau so ist die Uneinheitlichkeit ja entstanden. Deshalb ein
Wächter statt einer Fleissarbeit.

**Die Abgrenzung, die dieser Test zieht:** Er greift nur bei Bedienelementen,
die wirklich einen Datensatz ENTFERNEN – erkennbar an einer Route auf
`/loeschen`. Das Kassenbuch hat bewusst kein Löschen: sein ✕ ist ein
*Storno*, die Zeile bleibt für immer stehen (Wünsche #144, #153, #156). Ein
Mülleimer wäre dort schlicht gelogen.
"""
import pathlib
import re

import pytest

MUELLEIMER = "\U0001F5D1"          # 🗑 – ohne Variantenselektor vergleichen
VORLAGEN = sorted((pathlib.Path(__file__).resolve().parents[1]
                   / "src" / "teile" / "templates").glob("*.html"))


def _loeschen_knoepfe(inhalt):
    """(Beschriftung, Aktion) je Bedienelement, das einen Datensatz entfernt.

    Gesucht wird über die ROUTE, nicht über die Beschriftung – sonst fände der
    Test nur, was ohnehin schon richtig heisst."""
    gefunden = []
    for m in re.finditer(r'<form[^>]*action="([^"]*loeschen[^"]*)"[^>]*>(.*?)</form>',
                         inhalt, re.S):
        aktion, rumpf = m.group(1), m.group(2)
        for b in re.finditer(r"<button[^>]*>(.*?)</button>", rumpf, re.S):
            gefunden.append((re.sub(r"\s+", " ", b.group(1)).strip(), aktion))
    return gefunden


def test_es_gibt_ueberhaupt_loeschen_knoepfe():
    """Fände das Muster nichts, wäre die Prüfung unten leer und grün."""
    alle = [k for f in VORLAGEN for k in _loeschen_knoepfe(f.read_text(encoding="utf-8"))]
    assert len(alle) >= 10, f"Nur {len(alle)} gefunden – Muster kaputt?"


@pytest.mark.parametrize("datei", VORLAGEN, ids=lambda p: p.name)
def test_loeschen_traegt_den_muelleimer(datei):
    inhalt = datei.read_text(encoding="utf-8")
    for beschriftung, aktion in _loeschen_knoepfe(inhalt):
        assert MUELLEIMER in beschriftung, (
            f"{datei.name}: Der Knopf zu {aktion!r} ist mit {beschriftung!r} "
            f"beschriftet. Löschen trägt im ganzen Portal 🗑️ – siehe CLAUDE.md, "
            f"UI-Konventionen."
        )


@pytest.mark.parametrize("datei", VORLAGEN, ids=lambda p: p.name)
def test_kein_x_mehr_als_loeschsymbol(datei):
    """Das ✕ war die häufigste Abweichung (Aufgaben, Werkstatt,
    Tierbaukasten). Es soll auch nicht durch die Hintertür zurückkommen."""
    for beschriftung, aktion in _loeschen_knoepfe(datei.read_text(encoding="utf-8")):
        assert beschriftung.strip() not in ("×", "✕", "✖", "x", "X"), (
            f"{datei.name}: {aktion!r} benutzt wieder ein ✕ statt 🗑️."
        )


def test_das_kassenbuch_bleibt_ausgenommen():
    """Die Ausnahme ist beabsichtigt und wird hier festgehalten, damit sie
    niemand aus Versehen „korrigiert": Im Kassenbuch wird nichts gelöscht,
    sondern storniert – die Zeile bleibt für immer stehen. Ein Mülleimer
    würde etwas anderes versprechen, als die App tut."""
    inhalt = (pathlib.Path(__file__).resolve().parents[1] / "src" / "teile"
              / "templates" / "kassenbuch.html").read_text(encoding="utf-8")
    assert "stornieren" in inhalt
    assert not _loeschen_knoepfe(inhalt), (
        "Das Kassenbuch hat plötzlich eine Löschen-Route. Dann gilt die "
        "Ausnahme nicht mehr – siehe test_kassenbuch_unveraenderlich.py."
    )
