"""Wunsch #200: Die Argumente des Klick-Verteilers stehen in einer festen
Reihenfolge – und die Funktion muss dazu passen.

`base.html` ruft `fn.apply(el, args.concat([el, ereignis]))`: **erst die Werte
aus `data-args`, dann das Element, dann das Ereignis.**

In `vokabeln.html` stand `function spracheWaehlen(btn, gruppe)` und der Chip
trug `data-args='["neu"]'`. Damit landete der String `"neu"` in `btn` und das
Element in `gruppe`, und die erste Zeile warf `gruppe.split is not a
function`. Ein Klick auf einen Sprach-Chip tat schlicht nichts.

**Warum das monatelang niemandem auffiel:** Das Formular wählt die zuletzt
benutzte Sprache selbst vor – über einen direkten Aufruf, der die richtige
Reihenfolge hatte. Wer immer dieselbe Sprache nahm, brauchte den Chip nie.
Erst als mit Wunsch #195 eine andere Sprache voreingestellt war, wurde das
Umschalten nötig – und ging nicht.

**Der Wächter:** Wird eine Funktion mit `data-args` aufgerufen, darf ihr
erster Parameter kein Element sein. Elemente erkennt man daran, dass man
`.classList`, `.dataset`, `.closest()` oder `.value` an ihnen benutzt – eine
Zahl oder ein Name aus `data-args` hat das alles nicht.
"""
import json
import pathlib
import re

import pytest

TPL = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"
BASE = (TPL / "base.html").read_text(encoding="utf-8")

# Zugriffe, die es nur an einem DOM-Element gibt.
ELEMENT_ZUGRIFF = re.compile(r"\.(classList|dataset|closest\(|value\b|checked\b|"
                             r"querySelector|form\b|disabled\b)")


def _funktionen(inhalt: str):
    """{name: (parameterliste, rumpf)} fuer alle `function name(...)`."""
    aus = {}
    for m in re.finditer(r"function\s+(\w+)\s*\(([^)]*)\)\s*\{", inhalt):
        name, params = m.group(1), m.group(2)
        tiefe, i = 0, m.end() - 1
        while i < len(inhalt):
            if inhalt[i] == "{":
                tiefe += 1
            elif inhalt[i] == "}":
                tiefe -= 1
                if tiefe == 0:
                    break
            i += 1
        rumpf = inhalt[m.end():i]
        aus[name] = ([p.strip() for p in params.split(",") if p.strip()], rumpf)
    return aus


def _aufrufe_mit_args(inhalt: str):
    """(funktionsname, anzahl_args) fuer jedes data-klick MIT data-args."""
    aus = []
    for m in re.finditer(
            r'data-(?:klick|aendern|eingabe|absenden)="(\w+)"[^>]*?'
            r"data-args='(\[[^']*\])'", inhalt, re.S):
        roh = m.group(2)
        # Jinja-Ausdruecke darin durch eine Zahl ersetzen, damit json sie liest.
        roh = re.sub(r"\{\{.*?\}\}", "0", roh, flags=re.S)
        try:
            aus.append((m.group(1), len(json.loads(roh))))
        except ValueError:
            aus.append((m.group(1), 1))
    return aus


# --- Die Konvention selbst --------------------------------------------------

def test_die_konvention_steht_im_verteiler():
    """Ändert sie sich, muss dieser Wächter mitgeändert werden - dann faellt
    es hier auf und nicht an einem toten Knopf."""
    assert "fn.apply(el, args.concat([el, ereignis]))" in BASE


# --- Jede Vorlage -----------------------------------------------------------

@pytest.mark.parametrize("datei", sorted(TPL.glob("*.html")), ids=lambda p: p.name)
def test_erster_parameter_ist_kein_element_wenn_args_da_sind(datei):
    inhalt = datei.read_text(encoding="utf-8")
    funktionen = _funktionen(inhalt)
    for name, anzahl in _aufrufe_mit_args(inhalt):
        if name not in funktionen:
            continue          # in einer anderen Datei definiert
        params, rumpf = funktionen[name]
        if not params:
            continue
        erster = params[0]
        treffer = ELEMENT_ZUGRIFF.search(
            "".join(re.findall(re.escape(erster) + r"(\.\w+\(?)", rumpf)))
        assert not treffer, (
            f"{datei.name}: {name}() wird mit {anzahl} data-args aufgerufen, "
            f"benutzt seinen ERSTEN Parameter `{erster}` aber wie ein Element "
            f"({treffer.group(0)}). Der Verteiler gibt erst die data-args und "
            f"DANN das Element - siehe Wunsch #200."
        )


def test_es_gibt_ueberhaupt_solche_aufrufe():
    """Faende das Muster nichts, waere der Test oben leer und gruen."""
    gesamt = sum(len(_aufrufe_mit_args(f.read_text(encoding="utf-8")))
                 for f in TPL.glob("*.html"))
    assert gesamt >= 5, f"nur {gesamt} Aufrufe mit data-args gefunden"


# --- Der konkrete Fall ------------------------------------------------------

def test_spracheWaehlen_nimmt_die_gruppe_zuerst():
    inhalt = (TPL / "vokabeln.html").read_text(encoding="utf-8")
    params = _funktionen(inhalt)["spracheWaehlen"][0]
    assert params[:2] == ["gruppe", "btn"], params


def test_der_direkte_aufruf_passt_dazu():
    """Die Funktion wird auch von Hand gerufen (Vorauswahl beim Öffnen des
    Formulars). Dreht man nur die Signatur, ist danach genau dieser Weg
    kaputt - und zwar der, den man beim Testen zuerst benutzt."""
    inhalt = (TPL / "vokabeln.html").read_text(encoding="utf-8")
    assert "spracheWaehlen('neu', ziel)" in inhalt
    assert "spracheWaehlen(ziel, 'neu')" not in inhalt
