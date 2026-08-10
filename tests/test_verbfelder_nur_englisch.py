"""Wunsch #195: Verbfelder nur dort, wo es unregelmäßige Verben gibt.

> „Unregelmäßige Verben gibt es nur im englischen (afaik), dann könnte man
> den Teil doch in anderen Sprachen ausblenden oder sogar in Englisch
> einklappen, weil es ja nicht immer benötigt wird."

Beides umgesetzt: **ausblenden** bei Sprachen ohne Stammformen, **einklappen**
dort, wo es sie gibt. Betroffen sind drei Stellen – das Vokabelformular, die
Lernseite und der Foto-Import.

**Warum eine Namensliste und keine Datenbankspalte:** Es gibt heute zwei
Sprachen. Eine Spalte ohne Bedienoberfläche wäre genauso unsichtbar wie die
Konstante, nur schwerer zu finden. `test_die_sprache_gibt_es_wirklich` fängt
den einen Fall ab, der dabei gefährlich wäre: dass „Englisch" umbenannt wird
und die Zuordnung still ins Leere zeigt.

**Und die serverseitige Hälfte:** Das Ausblenden im Browser ist Bequemlich-
keit, keine Regel. Ein POST mit `simple_past` an einer lateinischen Vokabel
wird auf dem Server verworfen – sonst hätte eine lateinische Vokabel ein
„simple past", sobald jemand eine alte Seite im Speicher hat.
"""
import pathlib
import re

import pytest

from teile.vokabeln import SPRACHEN_MIT_VERBFORMEN, sprachen_mit_verbformen

TPL = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"


@pytest.fixture()
def vok(app, db):
    from teile.kern import token_lookup, new_token
    v = db["verbindung"]
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='vokabeln'").fetchone()["id"]
        klartext = new_token()
        v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) "
                  "VALUES(?,?,?)",
                  (db["familie"]["TestAdmin"]["id"], app_id, token_lookup(klartext)))
        ids = {r["name"]: r["id"] for r in
               v.execute("SELECT id, name FROM vokabel_sprachen")}
        for sid in ids.values():
            v.execute("INSERT OR IGNORE INTO vokabel_sprachen_nutzer(user_id, sprache_id) "
                      "VALUES(?,?)", (db["familie"]["TestAdmin"]["id"], sid))
        v.commit()
    return {"token": klartext, "ids": ids, "uid": db["familie"]["TestAdmin"]["id"], "v": v}


# --- Die Zuordnung ----------------------------------------------------------

def test_die_sprache_gibt_es_wirklich(app, db):
    """Der eine Fall, der bei einer Namensliste gefährlich ist: Wird die
    Sprache umbenannt, zeigt die Zuordnung ins Leere - und die Verbfelder
    wären überall weg, ohne Fehlermeldung."""
    with app.app_context():
        from teile.kern import get_db
        vorhanden = {r["name"] for r in get_db().execute(
            "SELECT name FROM vokabel_sprachen")}
    fehlend = SPRACHEN_MIT_VERBFORMEN - vorhanden
    assert not fehlend, (
        f"{fehlend} steht in SPRACHEN_MIT_VERBFORMEN, gibt es aber nicht "
        f"(vorhanden: {sorted(vorhanden)})."
    )


def test_englisch_ist_dabei_latein_nicht(app, vok):
    with app.app_context():
        from teile.kern import get_db
        ids = sprachen_mit_verbformen(get_db())
    assert vok["ids"]["Englisch"] in ids
    assert vok["ids"]["Latein"] not in ids


# --- Server: die Regel gilt unabhängig vom Browser -------------------------

def test_verbformen_an_einer_anderen_sprache_werden_verworfen(client, vok):
    """Das Ausblenden im Browser ist Bequemlichkeit. Kommt der Wert trotzdem
    an - alte Seite im Speicher, selbstgebauter POST -, gilt er nicht."""
    client.post(f"/a/vokabeln/{vok['token']}/neu", data={
        "fremd": "amare", "deutsch": "lieben", "sprache_id": vok["ids"]["Latein"],
        "simple_past": "amavi", "perfect": "amatum"})
    z = vok["v"].execute("SELECT simple_past, perfect FROM vokabeln").fetchone()
    assert (z["simple_past"], z["perfect"]) == (None, None)


def test_bei_englisch_gelten_sie_weiterhin(client, vok):
    client.post(f"/a/vokabeln/{vok['token']}/neu", data={
        "fremd": "go", "deutsch": "gehen", "sprache_id": vok["ids"]["Englisch"],
        "simple_past": "went", "perfect": "gone"})
    z = vok["v"].execute("SELECT simple_past, perfect FROM vokabeln").fetchone()
    assert (z["simple_past"], z["perfect"]) == ("went", "gone")


def test_sprachwechsel_beim_bearbeiten_raeumt_die_formen_weg(client, vok):
    """Wird eine englische Vokabel auf Latein umgestellt, dürfen die
    Stammformen nicht stehen bleiben - sie gehörten zur alten Sprache."""
    vid = vok["v"].execute(
        "INSERT INTO vokabeln(user_id, sprache_id, fremd, deutsch, simple_past, perfect) "
        "VALUES(?,?,'go','gehen','went','gone') RETURNING id",
        (vok["uid"], vok["ids"]["Englisch"])).fetchone()["id"]
    vok["v"].commit()
    client.post(f"/a/vokabeln/{vok['token']}/{vid}/bearbeiten", data={
        "fremd": "ire", "deutsch": "gehen", "sprache_id": vok["ids"]["Latein"],
        "simple_past": "went", "perfect": "gone"})
    z = vok["v"].execute("SELECT simple_past, perfect FROM vokabeln WHERE id=?",
                         (vid,)).fetchone()
    assert (z["simple_past"], z["perfect"]) == (None, None)


def test_auch_der_fotoimport_haelt_sich_daran(client, vok):
    client.post(f"/a/vokabeln/{vok['token']}/foto-import/speichern", data={
        "sprache_id": vok["ids"]["Latein"], "behalten": "0",
        "fremd": "amare", "simple_past": "amavi", "perfect": "amatum",
        "deutsch": "lieben"})
    z = vok["v"].execute("SELECT simple_past FROM vokabeln").fetchone()
    assert z["simple_past"] is None


# --- Browser: die drei Stellen kennen die Liste ----------------------------

@pytest.mark.parametrize("pfad", ["", "lernen", "foto-import"])
def test_jede_seite_bekommt_die_sprachliste(client, vok, pfad):
    """Ohne sie könnte das Skript nicht entscheiden - und würde den Block
    entweder immer oder nie zeigen."""
    seite = client.get(f"/a/vokabeln/{vok['token']}/{pfad}").get_data(as_text=True)
    assert "VERB_SPRACHEN" in seite
    treffer = re.search(r"const VERB_SPRACHEN = (\[[^\]]*\])", seite)
    assert treffer, "die Liste wird nicht gerendert"
    assert str(vok["ids"]["Englisch"]) in treffer.group(1)


def test_der_block_ist_eingeklappt(client, vok):
    """Der zweite Teil des Wunsches: auch in Englisch nicht dauernd im Weg."""
    seite = client.get(f"/a/vokabeln/{vok['token']}/").get_data(as_text=True)
    assert "<details class=\"verb-block\"" in seite
    # Ohne bestehende Formen: zu. Ein `open` an einer leeren Karte hiesse,
    # der Block stuende doch wieder dauernd offen.
    assert 'data-verb-block>' in seite


def test_beim_bearbeiten_eines_verbs_steht_er_offen(client, vok):
    """Sonst sähe es aus, als wären die Formen verschwunden."""
    vok["v"].execute(
        "INSERT INTO vokabeln(user_id, sprache_id, fremd, deutsch, simple_past, perfect) "
        "VALUES(?,?,'go','gehen','went','gone')",
        (vok["uid"], vok["ids"]["Englisch"]))
    vok["v"].commit()
    seite = client.get(f"/a/vokabeln/{vok['token']}/").get_data(as_text=True)
    assert "data-verb-block open>" in seite


@pytest.mark.parametrize("datei,marke", [
    ("vokabeln.html", "verbBlockZeigen"),
    ("vokabel_lernen.html", "verbAbschnittZeigen"),
    ("vokabel_foto_import.html", "verbSchalterZeigen"),
])
def test_die_umschaltung_laeuft_beim_laden_und_beim_wechsel(datei, marke):
    """Nur beim Wechsel umzuschalten reicht nicht: Die zuletzt gewählte
    Sprache kommt aus dem Speicher, und dann stimmte der Block schon beim
    Öffnen nicht."""
    inhalt = (TPL / datei).read_text(encoding="utf-8")
    assert inhalt.count(marke) >= 3, (
        f"{datei}: {marke} muss definiert, beim Sprachwechsel UND beim Laden "
        f"aufgerufen werden."
    )


@pytest.mark.parametrize("datei,feld", [
    ("vokabel_lernen.html", "verb_formen"),
    ("vokabel_foto_import.html", "verbmodus"),
])
def test_versteckte_haken_werden_entfernt(datei, feld):
    """Ein unsichtbares, gesetztes Häkchen würde beim Absenden trotzdem
    mitgeschickt - das Training liefe im Verbmodus, ohne dass man sähe warum."""
    inhalt = (TPL / datei).read_text(encoding="utf-8")
    assert f'input[name="{feld}"]' in inhalt
    block = inhalt[inhalt.index(f'input[name="{feld}"]'):]
    assert "checked = false" in block[:200]


def test_die_verbfelder_werden_beim_wechsel_geleert():
    """Dasselbe für die Textfelder im Vokabelformular."""
    inhalt = (TPL / "vokabeln.html").read_text(encoding="utf-8")
    block = inhalt[inhalt.index("function verbBlockZeigen"):]
    block = block[:block.index("}\n\n")]
    assert "f.value = ''" in block
