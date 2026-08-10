"""Wunsch #194: Spezialmodus für unregelmäßige englische Verben.

Drei Teile: die vier Felder erfassen, im Training wählbare Kombinationen
abfragen, und beides auch per Foto importieren.

**Die Grundentscheidung:** zwei Spalten an `vokabeln` statt einer eigenen
Tabelle. Kapitel, Freigaben, Sessions, Versuche, Aussprache und Statistik
hängen alle an `vokabeln` – eine zweite Tabelle hätte das alles verdoppelt.
Ein Eintrag *ist* ein unregelmäßiges Verb, wenn `simple_past` **und**
`perfect` gefüllt sind; `fremd` trägt dann den Infinitiv. Bewusst kein
eigener Typ-Merker: Der wäre eine zweite Wahrheit neben den Feldern und
könnte von ihnen abweichen.

Daraus folgt die Regel, die hier am häufigsten geprüft wird: **beide Formen
oder keine.** Ein halb ausgefülltes Paar würde im Verbtraining eine Frage
mit leerer Antwort erzeugen.
"""
import pytest

from teile.vokabeln import (VERB_ABFRAGEN, VERB_ABFRAGEN_STANDARD,
                            verb_aufgaben)


@pytest.fixture()
def vok(app, db):
    """Token für die Vokabel-App + die Sprach-ID von Englisch."""
    from teile.kern import token_lookup, new_token
    v = db["verbindung"]
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='vokabeln'").fetchone()["id"]
        klartext = new_token()
        v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) "
                  "VALUES(?,?,?)",
                  (db["familie"]["TestAdmin"]["id"], app_id, token_lookup(klartext)))
        sid = v.execute("SELECT id FROM vokabel_sprachen WHERE name='Englisch'").fetchone()["id"]
        v.execute("INSERT OR IGNORE INTO vokabel_sprachen_nutzer(user_id, sprache_id) "
                  "VALUES(?,?)", (db["familie"]["TestAdmin"]["id"], sid))
        v.commit()
    return {"token": klartext, "sprache_id": sid,
            "uid": db["familie"]["TestAdmin"]["id"], "v": v}


def _verb(vok, fremd, past, perfect, deutsch):
    vid = vok["v"].execute(
        "INSERT INTO vokabeln(user_id, sprache_id, fremd, deutsch, simple_past, perfect) "
        "VALUES(?,?,?,?,?,?) RETURNING id",
        (vok["uid"], vok["sprache_id"], fremd, deutsch, past, perfect)).fetchone()["id"]
    vok["v"].commit()
    return vid


# --- Die Aufgaben ----------------------------------------------------------

def _zeile(**kwargs):
    basis = {"id": 1, "fremd": "go", "simple_past": "went",
             "perfect": "gone", "deutsch": "gehen"}
    basis.update(kwargs)
    return basis


def test_infinitiv_zu_beiden_formen():
    a = verb_aufgaben([_zeile()], ["infinitiv_formen"])
    assert len(a) == 1
    assert a[0]["frage"] == "go"
    assert [f["erwartet"] for f in a[0]["felder"]] == ["went", "gone"]
    assert [f["label"] for f in a[0]["felder"]] == ["simple past", "Perfect"]


def test_deutsch_zu_allen_drei_formen():
    a = verb_aufgaben([_zeile()], ["deutsch_alle"])
    assert a[0]["frage"] == "gehen"
    assert [f["erwartet"] for f in a[0]["felder"]] == ["go", "went", "gone"]


def test_rueckrichtungen():
    a = {x["form"]: x for x in verb_aufgaben(
        [_zeile()], ["past_infinitiv", "perfect_infinitiv", "infinitiv_deutsch"])}
    assert a["past_infinitiv"]["frage"] == "went"
    assert a["past_infinitiv"]["felder"][0]["erwartet"] == "go"
    assert a["perfect_infinitiv"]["frage"] == "gone"
    assert a["infinitiv_deutsch"]["felder"][0]["erwartet"] == "gehen"


def test_jede_gewaehlte_form_gibt_eine_eigene_aufgabe():
    """Wer zwei Richtungen ankreuzt, bekommt jedes Verb zweimal - genau das
    ist der Sinn der Auswahl."""
    a = verb_aufgaben([_zeile()], ["deutsch_alle", "infinitiv_formen"])
    assert len(a) == 2
    assert {x["form"] for x in a} == {"deutsch_alle", "infinitiv_formen"}
    assert {x["id"] for x in a} == {1}


def test_unbekannte_form_wird_ignoriert():
    """Ein selbstgebauter POST soll keine Aufgabe aus dem Nichts erzeugen."""
    assert verb_aufgaben([_zeile()], ["gibtsnicht"]) == []


def test_leeres_fragefeld_faellt_weg():
    """Sonst stünde im Training eine Frage ohne Wort."""
    assert verb_aufgaben([_zeile(deutsch="")], ["deutsch_alle"]) == []


def test_leere_antwort_faellt_aus_der_aufgabe():
    a = verb_aufgaben([_zeile(perfect="")], ["infinitiv_formen"])
    assert [f["erwartet"] for f in a[0]["felder"]] == ["went"]


def test_die_voreinstellung_gibt_es_wirklich():
    """Eine Voreinstellung, die auf einen entfernten Schlüssel zeigt, wäre
    ein Formular ohne Häkchen - und niemandem fiele auf, warum."""
    for schluessel in VERB_ABFRAGEN_STANDARD:
        assert schluessel in VERB_ABFRAGEN


# --- Erfassen ---------------------------------------------------------------

def test_verb_anlegen(client, vok):
    client.post(f"/a/vokabeln/{vok['token']}/neu", data={
        "fremd": "go", "deutsch": "gehen", "sprache_id": vok["sprache_id"],
        "simple_past": "went", "perfect": "gone"})
    z = vok["v"].execute("SELECT fremd, simple_past, perfect FROM vokabeln").fetchone()
    assert (z["fremd"], z["simple_past"], z["perfect"]) == ("go", "went", "gone")


def test_halbes_paar_wird_verworfen(client, vok):
    """Beide oder keine - sonst gäbe es im Verbtraining eine Frage mit leerer
    Antwort, und das Wort wäre trotzdem als Verb eingestuft."""
    client.post(f"/a/vokabeln/{vok['token']}/neu", data={
        "fremd": "go", "deutsch": "gehen", "sprache_id": vok["sprache_id"],
        "simple_past": "went"})
    z = vok["v"].execute("SELECT simple_past, perfect FROM vokabeln").fetchone()
    assert (z["simple_past"], z["perfect"]) == (None, None)


def test_normale_vokabel_bleibt_ohne_formen(client, vok):
    client.post(f"/a/vokabeln/{vok['token']}/neu", data={
        "fremd": "house", "deutsch": "Haus", "sprache_id": vok["sprache_id"]})
    z = vok["v"].execute("SELECT simple_past, perfect FROM vokabeln").fetchone()
    assert (z["simple_past"], z["perfect"]) == (None, None)


def test_formen_nachtragen_und_entfernen(client, vok):
    vid = _verb(vok, "go", None, None, "gehen")
    client.post(f"/a/vokabeln/{vok['token']}/{vid}/bearbeiten", data={
        "fremd": "go", "deutsch": "gehen", "sprache_id": vok["sprache_id"],
        "simple_past": "went", "perfect": "gone"})
    assert vok["v"].execute(
        "SELECT perfect FROM vokabeln WHERE id=?", (vid,)).fetchone()[0] == "gone"

    # Beide Felder leeren macht wieder eine normale Vokabel daraus.
    client.post(f"/a/vokabeln/{vok['token']}/{vid}/bearbeiten", data={
        "fremd": "go", "deutsch": "gehen", "sprache_id": vok["sprache_id"],
        "simple_past": "", "perfect": ""})
    assert vok["v"].execute(
        "SELECT perfect FROM vokabeln WHERE id=?", (vid,)).fetchone()[0] is None


# --- Training ---------------------------------------------------------------

def test_ohne_kreuz_bleibt_alles_wie_bisher(client, vok):
    """Der Verbmodus darf sich nicht von selbst einschalten."""
    _verb(vok, "go", "went", "gone", "gehen")
    _verb(vok, "house", None, None, "Haus")
    seite = client.post(f"/a/vokabeln/{vok['token']}/lernen/start",
                        data={"sprache_id": vok["sprache_id"]}).get_data(as_text=True)
    assert "Haus" in seite and "went" not in seite


def test_mit_kreuz_nur_noch_verben(client, vok):
    _verb(vok, "go", "went", "gone", "gehen")
    _verb(vok, "house", None, None, "Haus")
    seite = client.post(f"/a/vokabeln/{vok['token']}/lernen/start", data={
        "sprache_id": vok["sprache_id"], "verb_formen": "infinitiv_formen",
    }).get_data(as_text=True)
    assert "went" in seite
    assert "Haus" not in seite, "normale Vokabel im Verbtraining"


def test_zwei_kreuze_geben_doppelt_so_viele_aufgaben(client, vok):
    _verb(vok, "go", "went", "gone", "gehen")
    seite = client.post(f"/a/vokabeln/{vok['token']}/lernen/start", data={
        "sprache_id": vok["sprache_id"],
        "verb_formen": ["infinitiv_formen", "deutsch_alle"],
    }).get_data(as_text=True)
    assert seite.count('"form"') == 2


def test_ohne_passende_verben_kommt_die_leermeldung(client, vok):
    _verb(vok, "house", None, None, "Haus")
    seite = client.post(f"/a/vokabeln/{vok['token']}/lernen/start", data={
        "sprache_id": vok["sprache_id"], "verb_formen": "infinitiv_formen",
    }).get_data(as_text=True)
    assert "Keine Vokabeln für diese Auswahl" in seite


def test_unsinn_im_formular_schaltet_nicht_in_den_verbmodus(client, vok):
    """Die Route siebt unbekannte Werte aus, BEVOR sie ueber den Modus
    entscheidet. Ohne das Sieben waere `verb_formen` nicht leer, das Training
    liefe in den Verbmodus und zeigte "keine Vokabeln" - statt einfach
    normal zu starten.

    Der Test auf `verb_aufgaben` oben deckt das NICHT ab: Die Funktion siebt
    ein zweites Mal, deshalb blieb er gruen, als der Filter in der Route
    entfernt war."""
    _verb(vok, "house", None, None, "Haus")
    seite = client.post(f"/a/vokabeln/{vok['token']}/lernen/start", data={
        "sprache_id": vok["sprache_id"], "verb_formen": "gibtsnicht",
    }).get_data(as_text=True)
    assert "Haus" in seite
    assert "Keine Vokabeln für diese Auswahl" not in seite


def test_das_formular_hat_die_beiden_verbfelder(client, vok):
    """`test_verb_anlegen` schickt den POST selbst und sieht das Formular nie -
    ohne diesen Test koennten die Felder aus der Vorlage verschwinden, ohne
    dass etwas rot wird."""
    seite = client.get(f"/a/vokabeln/{vok['token']}/").get_data(as_text=True)
    assert seite.count('name="simple_past"') >= 1
    assert seite.count('name="perfect"') >= 1


def test_die_lernseite_bietet_alle_formen_an(client, vok):
    seite = client.get(f"/a/vokabeln/{vok['token']}/lernen").get_data(as_text=True)
    for schluessel, form in VERB_ABFRAGEN.items():
        assert f'value="{schluessel}"' in seite
        assert form[0] in seite


# --- Foto-Import ------------------------------------------------------------

def test_verbimport_speichert_alle_vier_felder(client, vok):
    client.post(f"/a/vokabeln/{vok['token']}/foto-import/speichern", data={
        "sprache_id": vok["sprache_id"], "behalten": "0",
        "fremd": "go", "simple_past": "went", "perfect": "gone", "deutsch": "gehen"})
    z = vok["v"].execute("SELECT fremd, simple_past, perfect, deutsch FROM vokabeln").fetchone()
    assert tuple(z) == ("go", "went", "gone", "gehen")


def test_import_ohne_verbspalten_bleibt_moeglich(client, vok):
    """Der normale Vokabelimport darf durch die zwei neuen Listen nicht
    kaputtgehen - sie fehlen dort schlicht."""
    client.post(f"/a/vokabeln/{vok['token']}/foto-import/speichern", data={
        "sprache_id": vok["sprache_id"], "behalten": "0",
        "fremd": "house", "deutsch": "Haus"})
    z = vok["v"].execute("SELECT fremd, simple_past FROM vokabeln").fetchone()
    assert (z["fremd"], z["simple_past"]) == ("house", None)


def test_halbes_paar_auch_beim_import_verworfen(client, vok):
    client.post(f"/a/vokabeln/{vok['token']}/foto-import/speichern", data={
        "sprache_id": vok["sprache_id"], "behalten": "0",
        "fremd": "go", "simple_past": "went", "perfect": "", "deutsch": "gehen"})
    z = vok["v"].execute("SELECT simple_past, perfect FROM vokabeln").fetchone()
    assert (z["simple_past"], z["perfect"]) == (None, None)


def test_die_importseite_kennt_den_verbschalter(client, vok):
    seite = client.get(f"/a/vokabeln/{vok['token']}/foto-import").get_data(as_text=True)
    assert 'name="verbmodus"' in seite


def test_ki_prompt_verlangt_alle_vier_felder():
    """Ein Prompt ohne die dritte Form liefert Zeilen, die als Verb gelten
    und im Training eine leere Antwort erwarten."""
    import pathlib
    quelle = (pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" /
              "16_vokabeln.py").read_text(encoding="utf-8")
    block = quelle[quelle.index("def _verben_per_ki("):]
    block = block[:block.index("@bp.route")]
    for feld in ("fremd", "simple_past", "perfect", "deutsch"):
        assert f'"{feld}"' in block, feld
    assert "all(zeile.values())" in block, (
        "Zeilen mit fehlenden Feldern werden nicht aussortiert."
    )


# --- Liste ------------------------------------------------------------------

def test_die_liste_zeigt_die_formen(client, vok):
    """Auf die Zeile pruefen, nicht auf die Woerter: Die stehen auch im
    Bearbeiten-Formular derselben Seite (`value="went"`). Ohne diese
    Genauigkeit blieb der Test gruen, als die Anzeigezeile ganz fehlte."""
    _verb(vok, "go", "went", "gone", "gehen")
    seite = client.get(f"/a/vokabeln/{vok['token']}/").get_data(as_text=True)
    import re as _re
    zeile = _re.search(r'<div class="vokabel-formen">([^<]*)</div>', seite)
    assert zeile, "keine Formenzeile in der Liste"
    assert "went" in zeile.group(1) and "gone" in zeile.group(1)


def test_normale_vokabel_zeigt_keine_formenzeile(client, vok):
    """Auf das ATTRIBUT prüfen, nicht auf den Klassennamen: Der steht auch im
    CSS-Block derselben Seite. Genau dieser Fehler ist im Projekt schon
    einmal passiert (kbp-ereignis, Wunsch #153)."""
    _verb(vok, "house", None, None, "Haus")
    seite = client.get(f"/a/vokabeln/{vok['token']}/").get_data(as_text=True)
    assert 'class="vokabel-formen"' not in seite
