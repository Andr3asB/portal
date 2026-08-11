"""Wünsche #197/#198/#199: Der Verbmodus verschwand nicht wirklich.

Alle drei Meldungen haben **eine** Ursache. Das Attribut `hidden` setzt in der
Standardformatierung des Browsers `display:none` – eine Klassenregel mit
eigenem `display` schlägt das mühelos:

```
.verb-liste { display:flex; … }   /* gewinnt gegen [hidden] */
.form-label { … }                 /* kein display -> hidden greift */
```

Ergebnis bei Dänisch: Die Überschrift und der Hinweis verschwanden, die
Auswahlliste blieb stehen. Also eine Liste ohne Überschrift, direkt an der
Kapitelwahl klebend – „kein Abstand" (#197/#198) und „Abfragemodus für
Englisch noch sichtbar" (#199) sind derselbe Fehler aus zwei Blickwinkeln.

**Dieselbe Spezifitätsfalle wie bei der Schriftgröße in #170.** Die Lösung
gehört deshalb nach `base.html` und gilt portalweit: `[hidden]` mit
`!important`.
"""
import pathlib
import re

import pytest

TPL  = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"
BASE = (TPL / "base.html").read_text(encoding="utf-8")


def _regel(css: str, selektor: str):
    m = re.search(re.escape(selektor) + r"\s*\{([^}]*)\}", css)
    return m.group(1).replace(" ", "") if m else None


# --- Die Ursache ------------------------------------------------------------

def test_hidden_schlaegt_jede_klassenregel():
    regel = _regel(BASE, "[hidden]")
    assert regel, "die globale [hidden]-Regel fehlt"
    assert "display:none!important" in regel, (
        "Ohne !important gewinnt jede Klasse mit eigenem display - genau so "
        "blieb der Verbmodus bei Dänisch stehen."
    )


def test_die_regel_steht_in_base_und_nicht_je_vorlage():
    """Sie betrifft jede Vorlage, die je etwas per `hidden` ausblendet."""
    treffer = [f.name for f in TPL.glob("*.html")
               if f.name != "base.html" and "[hidden]" in
               re.sub(r"/\*.*?\*/", "", f.read_text(encoding="utf-8"), flags=re.S)]
    assert not treffer, f"{treffer} regeln [hidden] selbst - das gehoert in base.html"


@pytest.mark.parametrize("datei,selektor", [
    ("vokabel_lernen.html", ".verb-liste"),
    ("vokabel_foto_import.html", ".verb-schalter"),
])
def test_die_betroffenen_regeln_haben_wirklich_ein_display(datei, selektor):
    """Der Test darüber wäre sonst eine Vorsichtsmaßnahme gegen nichts.
    Diese beiden Regeln sind die, an denen es aufgefallen ist."""
    regel = _regel((TPL / datei).read_text(encoding="utf-8"), selektor)
    assert regel and "display:" in regel, (
        f"{datei}: {selektor} hat kein eigenes display mehr - dann prueft "
        f"test_hidden_schlaegt_jede_klassenregel keinen echten Fall mehr."
    )


# --- Der sichtbare Abstand --------------------------------------------------

def test_die_verbauswahl_ist_abgesetzt():
    """Sie schaltet den ganzen Trainingsmodus um und ist keine weitere Zeile
    wie „Sprache" oder „Kapitel"."""
    inhalt = (TPL / "vokabel_lernen.html").read_text(encoding="utf-8")
    assert 'class="form-label abschnitt"' in inhalt
    regel = _regel(inhalt, ".form-label.abschnitt")
    assert regel and "border-top" in regel and "margin-top" in regel


def test_der_fotoschalter_ist_abgesetzt():
    regel = _regel((TPL / "vokabel_foto_import.html").read_text(encoding="utf-8"),
                   ".verb-schalter")
    assert "border-top" in regel and "margin-top" in regel


# --- Und das Verhalten, das dahinter steht ---------------------------------

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
        ids = {r["name"]: r["id"] for r in v.execute("SELECT id, name FROM vokabel_sprachen")}
        for sid in ids.values():
            v.execute("INSERT OR IGNORE INTO vokabel_sprachen_nutzer(user_id, sprache_id) "
                      "VALUES(?,?)", (db["familie"]["TestAdmin"]["id"], sid))
        v.commit()
    return {"token": klartext, "ids": ids, "v": v}


def test_ohne_verbsprache_kommt_kein_verbtraining_zustande(client, vok):
    """Der Kern von #199, serverseitig: Selbst wenn ein Häkchen doch
    mitkommt, darf bei Latein kein Verbtraining starten - dort gibt es keine
    Verben, die Auswahl liefe ins Leere."""
    v = vok["v"]
    v.execute("INSERT INTO vokabeln(user_id, sprache_id, fremd, deutsch) "
              "VALUES((SELECT id FROM users WHERE name='TestAdmin'),?,'amare','lieben')",
              (vok["ids"]["Latein"],))
    v.commit()
    seite = client.post(f"/a/vokabeln/{vok['token']}/lernen/start", data={
        "sprache_id": vok["ids"]["Latein"], "verb_formen": "infinitiv_formen",
    }).get_data(as_text=True)
    assert "Keine Vokabeln für diese Auswahl" in seite
    assert "amare" not in seite
