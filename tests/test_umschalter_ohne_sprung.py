"""Wunsch #171: Kleine Umschalter ohne Seitensprung.

Vier Umschalter luden die ganze Seite neu und sprangen an den Anfang – mitten
in einer Zwei-Wochen-Liste oder 170 Wünschen ärgerlich.

**Zwei Lösungen, nach einem Kriterium getrennt: Ändert der Umschalter die
Reihenfolge oder Gruppierung der Liste?**

| Umschalter | Weg | warum |
|---|---|---|
| gekocht (Essensplan) | fetch | ändert nur diesen einen Knopf |
| storniert (Kassenbuch) | fetch | Zeile bleibt stehen, nur Saldo ändert sich |
| erledigt / Priorität (Werkstatt) | Anker | verschiebt den Wunsch zwischen Listen |
| Erinnerung (Geburtstage) | Anker | „ausblenden" verschiebt in den anderen Abschnitt |

Eine Karte, die an Ort und Stelle umspringt, während die Sortierung veraltet,
ist schlimmer als ein Sprung – man handelt dann auf einer Liste, die nicht
mehr stimmt. Der Wunsch nennt den Anker selbst als zulässige Alternative.
"""
import pathlib
import re

import pytest

TPL = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"
QUELLE = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile"
BASE = (TPL / "base.html").read_text(encoding="utf-8")


# --- Der Verteiler ---------------------------------------------------------

def test_verteiler_kennt_data_fetch():
    assert "f.dataset.fetch" in BASE
    block = BASE[BASE.index("if (f.dataset.fetch)"):]
    block = block[:block.index("if (f.dataset.arbeitet)")]
    assert "e.preventDefault()" in block
    assert "'Accept': 'application/json'" in block


def test_fehlschlag_ist_nicht_still():
    """Wer nicht sieht, dass sein Tipp verpufft ist, tippt nicht nochmal –
    er glaubt, es sei gespeichert."""
    block = BASE[BASE.index("if (f.dataset.fetch)"):]
    block = block[:block.index("if (f.dataset.arbeitet)")]
    assert ".catch(" in block and "alert(" in block


def test_knopf_wird_wieder_freigegeben():
    """`finally`, nicht `then`: Nach einem Fehler muss der Knopf ebenfalls
    wieder benutzbar sein, sonst ist die Zeile tot."""
    block = BASE[BASE.index("if (f.dataset.fetch)"):]
    block = block[:block.index("if (f.dataset.arbeitet)")]
    assert ".finally(" in block and "disabled = false" in block


# --- Die fetch-Umschalter --------------------------------------------------

@pytest.mark.parametrize("datei,funktion", [
    ("essensplan.html", "gekochtAktualisiert"),
    ("kassenbuch.html", "stornoAktualisiert"),
])
def test_fetch_umschalter_haben_ihre_funktion(datei, funktion):
    """Ein `data-fetch` auf einen Namen, den es nicht gibt, wäre ein Knopf,
    der nichts tut – der Verteiler meldet das zwar in der Konsole, aber die
    sieht im Alltag niemand."""
    inhalt = (TPL / datei).read_text(encoding="utf-8")
    assert f'data-fetch="{funktion}"' in inhalt
    assert f"function {funktion}(" in inhalt


@pytest.mark.parametrize("datei", sorted(TPL.glob("*.html")), ids=lambda p: p.name)
def test_jedes_data_fetch_hat_eine_funktion(datei):
    inhalt = datei.read_text(encoding="utf-8")
    # Erklaerkommentare herausschneiden: der Verteiler in base.html nennt
    # `data-fetch="funktionsname"` als Beispiel, und der Test biss sich beim
    # ersten Lauf genau daran fest. Dritter Fall dieser Art im Projekt
    # (vgl. header_extra in test_kopfleiste.py, button::before in
    # test_tippflaeche.py) - Beispiele in Kommentaren sind kein Code.
    ohne_kommentar = re.sub(r"/\*.*?\*/", "", inhalt, flags=re.S)
    ohne_kommentar = re.sub(r"\{#.*?#\}", "", ohne_kommentar, flags=re.S)
    ohne_kommentar = re.sub(r"//.*", "", ohne_kommentar)
    for m in re.finditer(r'data-fetch="(\w+)"', ohne_kommentar):
        assert f"function {m.group(1)}(" in ohne_kommentar, (
            f"{datei.name}: data-fetch verweist auf {m.group(1)}(), das es "
            f"in dieser Vorlage nicht gibt."
        )


# --- Die Anker-Umschalter --------------------------------------------------

@pytest.mark.parametrize("modul,funktion,anker", [
    ("05_werkstatt_app.py", "toggle_erledigt", "#wunsch-"),
    ("05_werkstatt_app.py", "prioritaet",      "#wunsch-"),
    ("23_geburtstage.py",   "einstellung",     "#gb-"),
])
def test_anker_statt_seitenanfang(modul, funktion, anker):
    quelle = (QUELLE / modul).read_text(encoding="utf-8")
    block = quelle[quelle.index(f"def {funktion}("):]
    # bis zur naechsten Route bzw. Funktion auf oberster Ebene
    ende = block.find("\n@bp.route")
    block = block[:ende if ende > 0 else len(block)]
    assert anker in block, (
        f"{modul}:{funktion} leitet ohne Anker weiter - die Seite springt "
        f"dann an den Anfang (Wunsch #171)."
    )


@pytest.mark.parametrize("datei,muster", [
    ("werkstatt_app.html", 'id="wunsch-{{ w.id }}"'),
    ("geburtstage.html",   'id="gb-{{ e.id }}"'),
])
def test_die_sprungziele_existieren(datei, muster):
    """Ein Anker ohne Ziel scrollt an den Anfang – also genau dorthin, wo
    er nicht hin soll, und niemand merkt den Unterschied zum alten Zustand."""
    assert muster in (TPL / datei).read_text(encoding="utf-8")


# --- Der Formularweg bleibt bestehen ---------------------------------------

def test_ohne_accept_kopf_wird_weitergeleitet(client, db):
    """`antwort_oder_weiter` darf nicht zu einem reinen JSON-Endpunkt werden -
    ohne Javascript (und bei der Zurueck-Taste) zaehlt die Weiterleitung."""
    from teile.kern import token_lookup, new_token
    v = db["verbindung"]
    with client.application.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='essensplan'").fetchone()["id"]
        klartext = new_token()
        v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) "
                  "VALUES(?,?,?)",
                  (db["familie"]["TestAdmin"]["id"], app_id, token_lookup(klartext)))
    rid = v.execute("INSERT INTO rezepte(name) VALUES('X') RETURNING id").fetchone()["id"]
    v.execute("INSERT INTO essensplan_eintraege(tag, mahlzeit, rezept_id) "
              "VALUES('2026-08-05','abend',?)", (rid,))
    v.commit()

    ohne = client.post(f"/a/essensplan/{klartext}/gekocht",
                       data={"tag": "2026-08-05", "mahlzeit": "abend"})
    assert ohne.status_code == 302, "ohne Accept-Kopf muss weitergeleitet werden"

    mit = client.post(f"/a/essensplan/{klartext}/gekocht",
                      data={"tag": "2026-08-05", "mahlzeit": "abend"},
                      headers={"Accept": "application/json"})
    assert mit.status_code == 200
    assert mit.get_json()["ok"] is True
    assert mit.get_json()["gekocht"] is False   # zweiter Aufruf nimmt zurueck
