"""Wunsch #196: Nach unten ziehen lädt die Seite neu.

Der Anlass ist die installierte PWA: Dort gibt es kein browsereigenes
Pull-to-Refresh, und ohne Adresszeile auch keinen Neu-laden-Knopf. Im Browser
wiederum gibt es die Geste bereits – deshalb schaltet `overscroll-behavior-y:
contain` die eingebaute ab, damit es überall **eine** Geste gibt und nicht
stellenweise zwei übereinander.

**Warum ein echtes Neuladen und kein Nachladen per fetch:** Jede App bringt
eigene Skripte mit, die beim Laden ihre Listener setzen (Suchfelder, Filter,
Sortierung). Tauschte man nur das `<main>` aus, wären die danach still tot –
in 19 Apps, ohne dass irgendwo etwas rot würde.

**„Ohne den Fokus zu verlieren"** heisst hier: die Blätterstelle bleibt. Sie
wird vor dem Neuladen weggeschrieben und danach wiederhergestellt. Der
Tastaturfokus in einem Eingabefeld überlebt ein Neuladen prinzipbedingt
nicht – das ginge nur über den fetch-Weg, und der Preis dafür ist zu hoch.

**Was diese Datei NICHT prüfen kann:** die Geste selbst. Dafür braucht es
einen Finger auf einem Touchgerät. Geprüft wird, dass die Bausteine da sind
und die Regeln stimmen, die man beim Nachbauen falsch macht.
"""
import pathlib
import re

import pytest

TPL  = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"
BASE = (TPL / "base.html").read_text(encoding="utf-8")


def _skript() -> str:
    """Nur der Teil, der die Geste umsetzt - ohne CSS und Markup.

    Abgegrenzt an eindeutigen Marken, nicht an "Wunsch #196": Die Nummer
    steht auch im CSS-Kommentar weiter oben, und der Ausschnitt begann beim
    ersten Versuch genau dort - also im falschen Block."""
    anfang = BASE.index("var PTR_SCHWELLE")
    ende   = BASE.index("// Kleinkram", anfang)
    return BASE[anfang:ende]


# --- Die Bausteine ----------------------------------------------------------

def test_die_anzeige_gibt_es(client, db):
    """Ohne sichtbare Rueckmeldung zieht man ins Leere und weiss nicht, ob
    weit genug."""
    text = client.get(
        f"/a/todo/{db['familie']['TestAdmin']['tokens']['todo']}/"
    ).get_data(as_text=True)
    assert 'id="ptr-anzeige"' in text


def test_sie_steht_auf_jeder_seite(client, db):
    """Sie kommt aus base.html - also ueberall, nicht nur auf der Startseite."""
    andi = db["familie"]["TestAdmin"]["tokens"]
    for slug in ("admin", "todo", "einkauf", "hilfe"):
        assert 'id="ptr-anzeige"' in client.get(
            f"/a/{slug}/{andi[slug]}/").get_data(as_text=True), slug


def test_die_browsereigene_geste_ist_abgeschaltet():
    """Sonst gaebe es im Browser zwei Gesten uebereinander.

    Geprueft wird die REGEL, nicht die Zeichenkette: Der Erklaerkommentar
    darueber nennt sie ebenfalls, und der erste Versuch blieb deshalb gruen,
    als die Regel selbst entfernt war."""
    ohne_kommentar = re.sub(r"/\*.*?\*/", "", BASE, flags=re.S)
    assert re.search(r"body\s*\{[^}]*overscroll-behavior-y:\s*contain",
                     ohne_kommentar), "die CSS-Regel an body fehlt"


# --- Die Regeln, die man beim Nachbauen falsch macht ------------------------

def test_nur_ganz_oben():
    """Ohne diese Bedingung waere jedes Hochwischen in einer langen Liste ein
    Neuladeversuch."""
    assert "window.scrollY <= 0" in _skript()


def test_nur_ein_finger():
    """Zwei Finger sind eine Zoomgeste, keine Ziehgeste."""
    assert "e.touches.length === 1" in _skript()


def test_es_gibt_eine_schwelle():
    """Ein Neuladen bei jedem Millimeter waere unbrauchbar."""
    skript = _skript()
    assert "PTR_SCHWELLE" in skript
    wert = int(re.search(r"PTR_SCHWELLE = (\d+)", BASE).group(1))
    assert 40 <= wert <= 150, f"{wert}px ist keine sinnvolle Schwelle"


def test_hochziehen_loest_nicht_aus():
    """Nach oben ziehen ist normales Blaettern."""
    assert "if (strecke <= 0)" in _skript()


def test_es_wird_wirklich_neu_geladen():
    """Kein Austausch des Inhalts per fetch - siehe Modul-Docstring."""
    skript = _skript()
    assert "location.reload()" in skript
    assert "fetch(" not in skript, (
        "Der Inhalt wird nachgeladen statt die Seite neu zu laden - die "
        "Listener der App-Skripte waeren danach tot."
    )


# --- Die Blätterstelle ------------------------------------------------------

def test_die_stelle_wird_gemerkt_und_zurueckgeholt():
    skript = _skript()
    assert "sessionStorage.setItem(PTR_SPEICHER" in skript
    assert "sessionStorage.getItem(PTR_SPEICHER)" in BASE
    assert "window.scrollTo(0," in BASE


def test_der_merker_gilt_nur_einmal():
    """Bleibt er stehen, springt auch der naechste normale Seitenaufruf an
    dieselbe Stelle - und niemand versteht, warum."""
    assert "sessionStorage.removeItem(PTR_SPEICHER)" in BASE
    holen = BASE.index("sessionStorage.getItem(PTR_SPEICHER)")
    loeschen = BASE.index("sessionStorage.removeItem(PTR_SPEICHER)")
    assert loeschen > holen, "erst lesen, dann loeschen"


def test_speicherfehler_reissen_die_seite_nicht_mit():
    """`sessionStorage` wirft im privaten Modus mancher Browser. Eine Seite,
    die deshalb gar nicht mehr laedt, waere ein schlechter Tausch fuer eine
    Bequemlichkeitsgeste."""
    skript = _skript()
    assert skript.count("try {") >= 2
    assert "catch (e) {}" in skript or "catch (e) { return; }" in skript


# --- Kein Alleingang in einzelnen Vorlagen ---------------------------------

@pytest.mark.parametrize("datei", sorted(TPL.glob("*.html")), ids=lambda p: p.name)
def test_keine_vorlage_baut_die_geste_nach(datei):
    """Sie gehoert nach base.html. Eine zweite Umsetzung in einer Vorlage
    ergaebe auf genau dieser Seite zwei Neuladeversuche je Zug."""
    if datei.name == "base.html":
        return
    inhalt = datei.read_text(encoding="utf-8")
    ohne_kommentar = re.sub(r"/\*.*?\*/", "", inhalt, flags=re.S)
    ohne_kommentar = re.sub(r"\{#.*?#\}", "", ohne_kommentar, flags=re.S)
    assert "ptr-anzeige" not in ohne_kommentar, (
        f"{datei.name} baut die Ziehgeste nach - sie steht in base.html."
    )
