"""Wunsch #273: „Manche Figuren haben die falsche Kleidungsfarbe."

Ursache: DiceBear legt jedes Teil als `<g id="clothes-…-<hash>">` in `<defs>`
ab und zeichnet es per `<use href>`. Ohne Seed ist der Hash bei jeder Figur
derselbe - stehen zwei Figuren mit demselben Kleidungsstueck auf einer
Seite, zeigt `<use>` bei beiden auf die ERSTE Definition: die zweite traegt
die Kleidung der ersten. Dieselbe Falle wie bei den Tier-Clip-Pfaden (#83).
Deshalb hier: eigener Seed je Figur, keine doppelten IDs auf der
Galerieseite, und die Muetzenfarbe folgt der Kleidungsfarbe statt dem
Seed-Zufall.
"""
import importlib
import json
import re

import pytest

OPTIONEN = {
    "haut": "#edb98a", "haarfarbe": "#4a312c", "kleidungsfarbe": "#ff488e",
    "accessoirefarbe": "#262e33", "frisur": "bun", "augen": "default",
    "augenbrauen": "default", "mund": "smile", "bart": "keins",
    "kleidung": "shirtVNeck", "accessoire": "keins",
}


@pytest.fixture()
def modul(app):
    return importlib.import_module("teile.15_tierbaukasten")


def _ids(svg):
    return re.findall(r'\bid="([^"]+)"', svg)


def test_zwei_figuren_haben_eigene_ids(modul):
    a = modul._mensch_svg_rendern(OPTIONEN, seed="figur-1")
    b = modul._mensch_svg_rendern(OPTIONEN, seed="figur-2")
    assert _ids(a) and not set(_ids(a)) & set(_ids(b))
    # und jede <use>-Referenz zeigt auf eine eigene Definition
    for svg in (a, b):
        refs = set(re.findall(r'href="#([^"]+)"', svg))
        assert refs and refs <= set(_ids(svg))


def test_auch_ids_innerhalb_eines_teils_sind_eigen(modul):
    """Live gefunden: die Sonnenbrille bringt feste IDs (accessoriesSunglasses-a/-b)
    mit, die DiceBear NICHT mit dem Seed versieht - drei Figuren mit
    Sonnenbrille teilten sie sich."""
    brille = dict(OPTIONEN, accessoire="sunglasses")
    a = modul._mensch_svg_rendern(brille, seed="figur-1")
    b = modul._mensch_svg_rendern(brille, seed="figur-2")
    assert any("Sunglasses" in i for i in _ids(a))
    assert not set(_ids(a)) & set(_ids(b))
    for svg in (a, b):
        refs = set(re.findall(r'href="#([^"]+)"', svg)) | set(re.findall(r'url\(#([^)]+)\)', svg))
        assert refs and refs <= set(_ids(svg)), "jeder Verweis findet seine Definition"


def test_vorschau_kollidiert_nicht_mit_der_galerie(modul):
    vorschau = modul._mensch_svg_rendern(OPTIONEN)
    figur = modul._mensch_svg_rendern(OPTIONEN, seed="figur-1")
    assert not set(_ids(vorschau)) & set(_ids(figur))


def test_muetze_folgt_der_kleidungsfarbe(modul):
    mit_hut = dict(OPTIONEN, frisur="hat", kleidungsfarbe="#25557c")
    a = modul._mensch_svg_rendern(mit_hut, seed="figur-1")
    b = modul._mensch_svg_rendern(mit_hut, seed="figur-2")
    fills = lambda s: sorted(set(re.findall(r'fill="(#[0-9a-fA-F]{6})"', s)))
    assert fills(a) == fills(b), "keine Zufallsfarbe mehr, die am Seed haengt"
    assert "#25557c" in fills(a)


@pytest.fixture()
def galerie(app, db):
    from teile.kern import new_token, token_lookup
    v = db["verbindung"]
    uid = db["familie"]["TestAdmin"]["id"]
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='tierbaukasten'").fetchone()["id"]
        t = new_token()
        v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                  (uid, app_id, token_lookup(t)))
        for farbe in ("#ff488e", "#25557c"):
            v.execute("INSERT INTO tierbaukasten_kreationen(user_id, tier_typ, dicebear_optionen, name) VALUES(?,?,?,?)",
                      (uid, "mensch", json.dumps(dict(OPTIONEN, kleidungsfarbe=farbe)), farbe))
        v.commit()
    return t


def test_galerie_ohne_doppelte_ids(client, galerie):
    seite = client.get(f"/a/tierbaukasten/{galerie}/").get_data(as_text=True)
    galerie_teil = seite.split('class="mensch-galerie-svg"', 1)[1]
    ids = re.findall(r'<(?:g|clipPath|mask)[^>]*\bid="([^"]+)"', galerie_teil)
    assert len(ids) >= 12, "zwei Figuren mit je sechs Teilen plus Clip"
    assert len(ids) == len(set(ids)), f"doppelte IDs: {[i for i in ids if ids.count(i) > 1]}"
    # Jede Figur zeigt ihre eigene Farbe
    assert "#ff488e" in galerie_teil and "#25557c" in galerie_teil
