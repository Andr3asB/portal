"""Wünsche #227 und #228 – beide vom iPhone gemeldet, beide mit derselben
Wurzel: Ziehen war zu fummelig und Fehler zu brutal.

**#228 – der Griff war 15 × 20 Pixel.** Am lokal laufenden Portal in einem
echten Browser nachgemessen. Ursache: Die globale Tippflächen-Regel aus
Wunsch #169 gibt jedem `button` unsichtbare 44 × 44 px – die Ziehgriffe waren
aber `<span>`. Die Regel hat sie deshalb nie erreicht, in **keiner** der fünf
Zieh-Listen des Portals. Ein danebenliegender echter Knopf hatte im selben
Moment die vollen 44 × 44.

**#227 – jeder Aussetzer warf die Seite weg.** Der Fehler liess sich nicht
nachstellen (alle POSTs, die den Server erreichten, wurden mit 200
beantwortet), aber die Reaktion darauf war falsch: modales Fenster plus
`location.reload()`. Auf dem Telefon heisst das, dass eine Sekunde ohne
Empfang die halbe Bedienung wegräumt.
"""
import pathlib
import re

import pytest

TPL = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"
BRETT = TPL / "todo_kanban.html"

# Jede Vorlage mit einem Ziehgriff. Die Liste ist bewusst vollständig: #228
# wurde am Brett gemeldet, betraf aber alle fünf.
GRIFFE = [
    ("todo_kanban.html",          "karte-griff"),
    ("packliste.html",            "item-drag-handle"),
    ("essensplan.html",           "mahlzeit-drag-handle"),
    ("packliste_kategorien.html", "kat-drag-handle"),
    ("einkauf_kategorien.html",   "kat-drag-handle"),
]


# ── #228: Trefferfläche ────────────────────────────────────────────────────

@pytest.mark.parametrize("datei, klasse", GRIFFE, ids=[d for d, _ in GRIFFE])
def test_jeder_ziehgriff_ist_ein_knopf(datei, klasse):
    """Nur ein `button` bekommt über `base.html` die 44 × 44 px unsichtbare
    Trefferfläche (Wunsch #169). Als `<span>` blieb der Griff bei seinen
    tatsächlichen 15 × 20 px – auf dem Telefon nicht zu treffen."""
    quelle = (TPL / datei).read_text(encoding="utf-8")
    treffer = re.search(rf'<(\w+)[^>]*class="{re.escape(klasse)}"', quelle)
    assert treffer, f"Griff {klasse!r} nicht gefunden"
    assert treffer.group(1) == "button", (
        f"{datei}: Der Ziehgriff ist ein <{treffer.group(1)}> - damit greift "
        f"die globale Tippflächen-Regel nicht, er bleibt fingernagelgross")


@pytest.mark.parametrize("datei, klasse", GRIFFE, ids=[d for d, _ in GRIFFE])
def test_der_griff_sendet_kein_formular(datei, klasse):
    """Ein `button` ohne `type` ist ein Absende-Knopf, sobald er in einem
    Formular steht. Ein Ziehgriff, der beim Antippen speichert, wäre ein
    schlimmerer Fehler als der, den wir gerade beheben."""
    quelle = (TPL / datei).read_text(encoding="utf-8")
    treffer = re.search(rf'<button([^>]*)class="{re.escape(klasse)}"', quelle)
    assert treffer and 'type="button"' in treffer.group(1), (
        f"{datei}: Ziehgriff ohne type=\"button\"")


@pytest.mark.parametrize("datei, klasse", GRIFFE, ids=[d for d, _ in GRIFFE])
def test_der_griff_sieht_weiter_aus_wie_ein_griff(datei, klasse):
    """Ein `button` bringt Rahmen, Hintergrund und Systemschrift mit. Ohne
    Zurücksetzen sähe aus jedem Griff plötzlich ein grauer Kasten."""
    quelle = (TPL / datei).read_text(encoding="utf-8")
    regel = re.search(rf"\.{re.escape(klasse)} \{{(.*?)\}}", quelle, re.DOTALL)
    assert regel, f"Keine CSS-Regel für {klasse}"
    for eigenschaft in ("background:none", "border:none", "font-family:inherit"):
        assert eigenschaft in regel.group(1).replace(" ", ""), (
            f"{datei}: {eigenschaft} fehlt am Griff")


@pytest.mark.parametrize("datei, klasse", GRIFFE, ids=[d for d, _ in GRIFFE])
def test_der_griff_bleibt_beim_ziehen_scrollfest(datei, klasse):
    """`touch-action:none` verhindert, dass iOS die Bewegung als Scrollen
    übernimmt und den Zug mit `pointercancel` abbricht."""
    quelle = (TPL / datei).read_text(encoding="utf-8")
    regel = re.search(rf"\.{re.escape(klasse)} \{{(.*?)\}}", quelle, re.DOTALL)
    assert "touch-action:none" in regel.group(1).replace(" ", "")


def test_keine_eigene_trefferflaeche_erfunden():
    """Projektkonvention (#169): Die 44 px kommen aus `base.html`. Wer sie in
    einer Vorlage nachbaut, hat zwei Wahrheiten - `test_tippflaeche.py`
    wächtert das ohnehin, hier steht der Grund für die Umstellung."""
    for datei, _ in GRIFFE:
        quelle = (TPL / datei).read_text(encoding="utf-8")
        assert "::before" not in quelle or "button::before" not in quelle


# ── #227: Ein Aussetzer wirft die Seite nicht mehr weg ─────────────────────

def ohne_kommentare(text: str) -> str:
    """JS- und Jinja-Kommentare durch Leerzeichen ersetzen, Länge erhalten.

    Ohne das prüfen die Tests unten die Erklärung statt des Codes – genau das
    ist in dieser Sitzung dreimal passiert: Ein Wächter fand `location.reload`
    im Kommentar, der begründet, warum es das nicht mehr gibt. Ein Test, der
    an Prosa hängenbleibt, sagt beim nächsten Mal nichts mehr aus.
    """
    for muster in (r"/\*.*?\*/", r"//[^\n]*", r"\{#.*?#\}"):
        text = re.sub(muster, lambda m: " " * len(m.group(0)), text,
                      flags=re.DOTALL | re.MULTILINE)
    return text


def _brett_code():
    return ohne_kommentare(BRETT.read_text(encoding="utf-8"))


def _speichern_block():
    block = _brett_code()
    block = block[block.index("async function verschiebenSpeichern"):]
    return block[:block.index("\n}")]


def test_ein_fehlschlag_laedt_die_seite_nicht_neu():
    """Der eigentliche Fehler in der Meldung war die Reaktion: modales Fenster
    plus `location.reload()`. Auf dem Telefon räumt das bei einer Sekunde ohne
    Empfang die halbe Bedienung weg – aufgeklapptes Formular, Filter, Position
    in der Liste."""
    code = _brett_code()
    assert "location.reload" not in code, (
        "Das Brett lädt bei einem Fehler noch immer die ganze Seite neu")
    assert "alert(" not in code, (
        "Modales Fenster für einen Netz-Aussetzer - das ist die Meldung, über "
        "die sich Wunsch #227 beschwert")


def test_es_wird_einmal_wiederholt():
    """Deckt genau den Fall ab, der am wahrscheinlichsten ist: eine einzelne
    Anfrage, die unterwegs verlorengeht (z. B. während der Service Worker bei
    einer Auslieferung die Seite übernimmt)."""
    block = _speichern_block()
    assert "versuch === 1" in block, "Kein Unterschied zwischen erstem und zweitem Versuch"
    assert re.search(r"verschiebenSpeichern\([^)]*,\s*2\)", block), (
        "Kein zweiter Versuch - ein einzelner Aussetzer bleibt ein Fehler")


def test_bei_endgueltigem_fehlschlag_geht_die_karte_zurueck():
    """Sonst steht die Karte sichtbar in der neuen Spalte, ist dort aber nicht
    gespeichert – beim nächsten Laden springt sie zurück, und niemand weiss,
    welcher Stand nun gilt."""
    block = _speichern_block()
    assert "herkunft" in block
    assert "appendChild(karte)" in block, "Die Karte wird nicht zurückgelegt"


def test_die_meldung_nennt_die_ursache():
    """„Konnte nicht gespeichert werden" hat mich beim Suchen dieses Fehlers
    einen halben Tag gekostet. Beim nächsten Mal steht der Grund in der
    Meldung."""
    block = _speichern_block()
    assert "fehler.message" in block, (
        "Die Meldung nennt die Ursache nicht - der nächste Fehler ist wieder "
        "ein Ratespiel")


def test_der_status_wandert_mit():
    """Nach einem erfolgreichen Zug muss die Karte ihren neuen Status auch im
    Markup tragen: Der Filter (#229) und der nächste Zug lesen ihn von dort.
    Ohne diese Zeile filtert das Brett nach dem Verschieben falsch."""
    block = _speichern_block()
    assert "karte.dataset.status = status" in block
