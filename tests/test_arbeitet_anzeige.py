"""Wunsch #176: Formulare, die spürbar dauern, sagen das.

Rezept-aus-URL, Rezept-aus-Bild und der Vokabel-Foto-Import warten mehrere
Sekunden auf eine KI-Antwort. Der Absende-Knopf gab in dieser Zeit kein
Signal – man hält es für kaputt oder tippt ein zweites Mal und importiert
doppelt.

Gelöst als **eine** Regel im vorhandenen Absende-Verteiler in `base.html`:
Ein Formular mit `data-arbeitet="…"` bekommt beim Absenden einen
deaktivierten, umbeschrifteten Knopf. Die Tests hier sichern die zwei Stellen,
an denen so etwas erfahrungsgemäß kippt.
"""
import pathlib
import re

import pytest

TPL = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"
BASE = (TPL / "base.html").read_text(encoding="utf-8")

# Die drei Formulare, die auf eine KI-Antwort warten.
WARTENDE = ["rezept_importieren.html", "rezept_bild_importieren.html",
            "vokabel_foto_import.html"]


@pytest.mark.parametrize("datei", WARTENDE)
def test_wartende_formulare_sind_markiert(datei):
    inhalt = (TPL / datei).read_text(encoding="utf-8")
    assert "data-arbeitet=" in inhalt, (
        f"{datei} wartet auf eine KI-Antwort, sagt es aber nicht - der Knopf "
        f"bliebe stumm (Wunsch #176)."
    )


def test_der_verteiler_kennt_data_arbeitet():
    assert "f.dataset.arbeitet" in BASE
    assert "knopf.disabled = true" in BASE.replace("  ", " ")


def test_signal_kommt_erst_nach_allen_abbruchgruenden():
    """Die Reihenfolge ist der ganze Punkt: Lehnt jemand die Löschabfrage ab
    oder verwirft eine Prüffunktion das Formular, darf der Knopf NICHT
    deaktiviert zurückbleiben - sonst ist die Seite tot und sieht aus, als
    arbeite sie."""
    handler = BASE[BASE.index("document.addEventListener('submit'"):]
    handler = handler[:handler.index("window.addEventListener('pageshow'")]
    assert handler.index("dataset.bestaetigen") < handler.index("dataset.arbeitet")
    assert handler.index("dataset.absenden") < handler.index("dataset.arbeitet")
    # ... und der Abbruch muss auch wirklich abbrechen
    absenden_block = handler[handler.index("dataset.absenden"):handler.index("dataset.arbeitet")]
    assert "return" in absenden_block, (
        "Ohne `return` liefe der Code nach dem preventDefault weiter und "
        "deaktivierte den Knopf trotzdem."
    )


def test_zurueck_navigation_macht_den_knopf_wieder_frei():
    """Holt der Browser die Seite aus seinem Vor-/Zurück-Speicher, stünde der
    Knopf sonst für immer deaktiviert da - und niemand käme auf die Idee,
    dass ein Neuladen hilft."""
    assert "pageshow" in BASE
    block = BASE[BASE.index("window.addEventListener('pageshow'"):]
    block = block[:block.index("});") + 3]
    assert "e.persisted" in block
    assert "disabled = false" in block


@pytest.mark.parametrize("datei", sorted(TPL.glob("*.html")), ids=lambda p: p.name)
def test_markierte_formulare_haben_einen_absendeknopf(datei):
    """`data-arbeitet` an einem Formular ohne Submit-Knopf wäre wirkungslos -
    und zwar lautlos."""
    inhalt = datei.read_text(encoding="utf-8")
    for m in re.finditer(r"<form[^>]*data-arbeitet[^>]*>(.*?)</form>", inhalt, re.DOTALL):
        assert re.search(r'<button[^>]*type="submit"', m.group(1)), (
            f"{datei.name}: Formular mit data-arbeitet hat keinen "
            f"Submit-Knopf - die Anzeige liefe ins Leere."
        )
