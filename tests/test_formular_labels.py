"""Wunsch #246: Jedes Formularfeld hat eine programmatische Beschriftung.

Ein Platzhalter ist keine: Er verschwindet beim Tippen, und ein daneben-
stehendes div ist fuer Screenreader nicht mit dem Feld verknuepft. Erlaubt
sind drei Wege - ein `<label for>` auf die id des Feldes, ein umschliessendes
`<label>`, oder `aria-label`/`aria-labelledby` direkt am Feld.
"""
import pathlib
import re

import pytest

TPL = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"

_FELD = re.compile(r"<(input|textarea|select)\b[^>]*>")


def _beschriftet(tag, text, start):
    if 'type="hidden"' in tag:
        return True
    if "aria-label" in tag or "aria-labelledby" in tag:
        return True
    m = re.search(r'id="([^"{]+)"', tag)
    if m and f'for="{m.group(1)}"' in text:
        return True
    # von einem <label> umschlossen?
    vor = text[:start]
    return vor.rfind("<label") > vor.rfind("</label>")


@pytest.mark.parametrize("datei", sorted(TPL.glob("*.html")), ids=lambda p: p.name)
def test_jedes_feld_hat_eine_beschriftung(datei):
    text = datei.read_text(encoding="utf-8")
    fehler = []
    for m in _FELD.finditer(text):
        if not _beschriftet(m.group(0), text, m.start()):
            zeile = text[: m.start()].count("\n") + 1
            fehler.append(f"Zeile {zeile}: {' '.join(m.group(0).split())[:70]}")
    assert not fehler, (
        f"{datei.name}: Felder ohne label/aria-label (Wunsch #246):\n  "
        + "\n  ".join(fehler)
    )


def test_der_waechter_findet_ueberhaupt_felder():
    """Sonst waere die Pruefung leer und still gruen."""
    gesamt = sum(len(_FELD.findall(p.read_text(encoding="utf-8")))
                 for p in TPL.glob("*.html"))
    assert gesamt >= 50, f"nur {gesamt} Felder gefunden - Muster kaputt?"
