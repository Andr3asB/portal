"""Wunsch #175: Knöpfe, die nur aus einem Zeichen bestehen, brauchen einen Namen.

Ein Knopf mit der Aufschrift ✏️ oder 🗑️ liest sich für eine Vorlesefunktion
(VoiceOver am iPhone) als „Schaltfläche" – mehr nicht. `title` hilft dabei
nicht verlässlich und erscheint bei Touch ohnehin nie.

**Die Konvention:** Wo beides vorhanden ist, sind `title` und `aria-label`
identisch. Zwei verschiedene Texte am selben Knopf wären eine Einladung, den
einen zu pflegen und den anderen vergessen – und der vergessene ist immer der,
den niemand sieht.

Betrifft heute niemanden akut; die Familie nutzt VoiceOver nicht. Es kostet
fast nichts und gehört zu einer Oberfläche, die man ernst meint.
"""
import pathlib
import re

import pytest

TPL = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"

# Beschriftung besteht ausschliesslich aus Zeichen/Ziffern (Emoji, Pfeile, ✓)
NUR_ZEICHEN = re.compile(r"^[\W\d_]{1,4}$")


def _icon_knoepfe(inhalt):
    """(Attribute, Beschriftung) je Knopf, dessen Aufschrift kein Wort ist."""
    aus = []
    for m in re.finditer(r"<button([^>]*)>(.*?)</button>", inhalt, re.DOTALL):
        attrs, label = m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()
        if "{" in label or not label:      # Jinja-Ausdruck: Text kommt erst zur Laufzeit
            continue
        if NUR_ZEICHEN.match(label):
            aus.append((attrs, label))
    return aus


def test_es_gibt_ueberhaupt_icon_knoepfe():
    """Fände das Muster nichts, wären die Prüfungen unten leer und grün."""
    alle = [k for f in TPL.glob("*.html")
            for k in _icon_knoepfe(f.read_text(encoding="utf-8"))]
    assert len(alle) >= 40, f"nur {len(alle)} gefunden - Muster kaputt?"


@pytest.mark.parametrize("datei", sorted(TPL.glob("*.html")), ids=lambda p: p.name)
def test_jeder_icon_knopf_hat_einen_namen(datei):
    for attrs, label in _icon_knoepfe(datei.read_text(encoding="utf-8")):
        assert "aria-label" in attrs, (
            f"{datei.name}: Knopf {label!r} hat keinen aria-label - eine "
            f"Vorlesefunktion sagt dazu nur 'Schaltflaeche' (Wunsch #175)."
        )


@pytest.mark.parametrize("datei", sorted(TPL.glob("*.html")), ids=lambda p: p.name)
def test_title_und_aria_label_sagen_dasselbe(datei):
    """Sonst pflegt jemand den einen und vergisst den anderen - und vergessen
    wird immer der, den niemand sieht."""
    for attrs, label in _icon_knoepfe(datei.read_text(encoding="utf-8")):
        t = re.search(r'title="([^"]*)"', attrs)
        a = re.search(r'aria-label="([^"]*)"', attrs)
        if t and a:
            assert t.group(1) == a.group(1), (
                f"{datei.name}: Knopf {label!r} hat title={t.group(1)!r}, aber "
                f"aria-label={a.group(1)!r}."
            )


def test_namen_sind_keine_platzhalter():
    """Ein aria-label wie 'Knopf' oder '...' erfuellt die Pruefung und hilft
    niemandem."""
    schlecht = {"knopf", "button", "aktion", "...", "-", "x"}
    for f in sorted(TPL.glob("*.html")):
        for attrs, label in _icon_knoepfe(f.read_text(encoding="utf-8")):
            a = re.search(r'aria-label="([^"]*)"', attrs)
            if a:
                assert a.group(1).strip().lower() not in schlecht, (
                    f"{f.name}: aria-label={a.group(1)!r} sagt nichts."
                )
