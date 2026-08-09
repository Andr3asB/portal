"""Wunsch #178: Packliste – Filter nach Person und manuelles Umsortieren.

Zwei Teile, die wenig miteinander zu tun haben, ausser dass beide dieselbe
Liste betreffen.

**Umsortieren** braucht eine eigene Spalte. Die Falle dabei ist nicht das
Sortieren selbst, sondern was mit NEUEN Einträgen passiert: Landen sie auf
Position 0, schiebt jeder neue Eintrag die von Hand sortierte Liste
durcheinander – und zwar jedes Mal aufs Neue.

**Filtern** hat eine eigene Falle: Sachen ohne Person („Reiseapotheke") dürfen
nicht spurlos verschwinden, sobald jemand filtert – sie müssen fast immer
mitgepackt werden.
"""
import pathlib
import re

import pytest

TPL = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"


@pytest.fixture()
def liste(app, db):
    from teile.kern import token_lookup, new_token
    v = db["verbindung"]
    familie = db["familie"]
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='packliste'").fetchone()["id"]
        klartext = new_token()
        v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                  (familie["TestAdmin"]["id"], app_id, token_lookup(klartext)))

    zid = v.execute(
        "INSERT INTO packlisten_ziele(name) VALUES('Sommerurlaub') RETURNING id"
    ).fetchone()["id"]
    kid = v.execute("SELECT id FROM packlisten_kategorien LIMIT 1").fetchone()["id"]

    ids = []
    for name, person, pos in [("Zahnbuerste", familie["TestKind"]["id"], 0),
                              ("Reiseapotheke", None, 1),
                              ("Badehose", familie["TestKind"]["id"], 2)]:
        ids.append(v.execute(
            "INSERT INTO packlisten_eintraege(name, ziel_id, kategorie_id, person_id, position) "
            "VALUES(?,?,?,?,?) RETURNING id", (name, zid, kid, person, pos)).fetchone()["id"])
    v.commit()
    return {"token": klartext, "ziel": zid, "kategorie": kid, "ids": ids}


def _namen_in_reihenfolge(client, liste):
    seite = client.get(f"/a/packliste/{liste['token']}/?ziel={liste['ziel']}") \
                  .get_data(as_text=True)
    return re.findall(r'<span class="item-name">([^<]+)</span>', seite)


# --- Umsortieren -----------------------------------------------------------

def test_liste_folgt_der_eigenen_reihenfolge(client, db, liste):
    assert _namen_in_reihenfolge(client, liste) == ["Zahnbuerste", "Reiseapotheke", "Badehose"]


def test_umsortieren_wirkt(client, db, liste):
    a, b, c = liste["ids"]
    antwort = client.post(f"/a/packliste/{liste['token']}/reorder",
                          json={"order": [c, a, b]})
    assert antwort.get_json()["ok"] is True
    assert _namen_in_reihenfolge(client, liste) == ["Badehose", "Zahnbuerste", "Reiseapotheke"]


def test_neuer_eintrag_landet_am_ENDE(client, db, liste):
    """Der eigentliche Fallstrick. Auf Position 0 wuerde jeder neue Eintrag
    die von Hand sortierte Liste durcheinanderschieben - jedes Mal."""
    client.post(f"/a/packliste/{liste['token']}/add",
                data={"name": "Sonnencreme", "ziel_id": liste["ziel"],
                      "kategorie_id": liste["kategorie"]})
    assert _namen_in_reihenfolge(client, liste)[-1] == "Sonnencreme"


def test_reorder_vertraegt_unsinn(client, db, liste):
    """Eine kaputte Liste darf die vorhandene Reihenfolge nicht zerstoeren."""
    vorher = _namen_in_reihenfolge(client, liste)
    client.post(f"/a/packliste/{liste['token']}/reorder",
                json={"order": ["abc", None, 999999]})
    assert _namen_in_reihenfolge(client, liste) == vorher


def test_reorder_braucht_eine_liste(client, db, liste):
    assert client.post(f"/a/packliste/{liste['token']}/reorder",
                       json={"order": "keine Liste"}).status_code == 400


def test_ohne_zugang_kein_umsortieren(client, db, liste):
    a, b, c = liste["ids"]
    assert client.post("/a/packliste/unsinn/reorder",
                       json={"order": [c, b, a]}).status_code == 403


def test_gepackte_stehen_nicht_im_zieh_bereich(client, db, liste):
    """Gepackte Eintraege haben einen eigenen Abschnitt nach Packzeitpunkt -
    ein Zieh-Griff dort waere ein Knopf, der nichts bewirkt."""
    v = db["verbindung"]
    v.execute("UPDATE packlisten_eintraege SET gepackt=1, gepackt_am=datetime('now') "
              "WHERE id=?", (liste["ids"][0],))
    v.commit()
    seite = client.get(f"/a/packliste/{liste['token']}/?ziel={liste['ziel']}") \
                  .get_data(as_text=True)
    # Zwei offene Eintraege -> zwei Griffe
    assert seite.count('class="item-drag-handle"') == 2


# --- Filtern ---------------------------------------------------------------

def test_filter_kennt_alle_personen(client, db, liste):
    seite = client.get(f"/a/packliste/{liste['token']}/?ziel={liste['ziel']}") \
                  .get_data(as_text=True)
    block = seite[seite.index('id="filter-person-row"'):]
    block = block[:block.index("</div>")]
    for name in ("TestAdmin", "TestKind", "TestEltern"):
        assert name in block, name


def test_filter_hat_einen_knopf_fuer_allgemein():
    """Sachen ohne Person duerfen beim Filtern nicht spurlos verschwinden -
    die Reiseapotheke wird fast immer mitgepackt."""
    inhalt = (TPL / "packliste.html").read_text(encoding="utf-8")
    assert 'data-value="allgemein"' in inhalt
    assert "karte.dataset.person || 'allgemein'" in inhalt


def test_leere_kategorien_verschwinden_beim_filtern():
    """Sonst stehen leere Ueberschriften da und die Liste sieht kaputt aus."""
    inhalt = (TPL / "packliste.html").read_text(encoding="utf-8")
    block = inhalt[inhalt.index("function packlisteFilter"):]
    block = block[:block.index("\n}")]
    assert ".kat-label" in block, (
        "Der Filter blendet keine leeren Kategorie-Ueberschriften aus - "
        "oder er benutzt einen Klassennamen, den es nicht gibt."
    )


def test_der_klassenname_existiert_wirklich():
    """Ein geratener Klassenname faellt sonst nie auf: Der Filter laeuft
    fehlerfrei durch und blendet einfach nichts aus. Beim Bauen stand hier
    zuerst `.kategorie-titel` - eine Klasse, die es nie gab.

    Gesucht wird ausschliesslich im MARKUP. Die erste Fassung dieses Tests
    durchsuchte die ganze Datei ab `{% block body %}` - und weil der
    Skriptblock dahinter steht, fand jeder gesuchte Name sich selbst. Der
    Test bestaetigte sich damit selbst und blieb auch bei einem erfundenen
    Klassennamen gruen.
    """
    inhalt = (TPL / "packliste.html").read_text(encoding="utf-8")
    ohne_skript, skript = inhalt.split("{% block extra_scripts %}")

    # Klassennamen aus den class-Attributen sammeln, nicht per Textsuche:
    # `.item-card` steht im Jinja-Makro VOR `{% block body %}`, und der
    # CSS-Block nennt Klassen, die es im Markup gar nicht geben muss.
    vorhanden = set()
    for wert in re.findall(r'class="([^"]*)"', ohne_skript):
        vorhanden.update(re.findall(r"[\w-]+", wert))

    gesucht = set(re.findall(r"querySelectorAll\('\.([\w-]+)'\)", skript))
    assert gesucht, "keine Klassensuche im Skript gefunden - Muster kaputt?"
    for klasse in gesucht:
        assert klasse in vorhanden, (
            f"packliste.html sucht .{klasse}, aber die Klasse kommt im Markup "
            f"nicht vor - der Filter laeuft dann fehlerfrei ins Leere."
        )


# --- Der gemeinsame Zieh-Helfer -------------------------------------------

def test_zieh_helfer_liegt_in_base():
    """Dritte Kopie vermieden: Die Packlisten-Kategorien und die Einkaufslaeden
    haben je eine eigene Fassung derselben ~120 Zeilen."""
    base = (TPL / "base.html").read_text(encoding="utf-8")
    assert "window.ziehSortierung" in base
    inhalt = (TPL / "packliste.html").read_text(encoding="utf-8")
    assert "ziehSortierung({" in inhalt
    assert "pointerdown" not in inhalt, (
        "packliste.html bringt eine eigene Zieh-Logik mit statt den Helfer "
        "aus base.html zu nutzen."
    )


# --- Wunsch #181: Umsortieren darf die Kategorie nicht wechseln -----------

def test_umsortieren_aendert_keine_kategorie(client, db, liste):
    """Der Kern des gemeldeten Fehlers, serverseitig festgenagelt.

    Die Anzeige gruppiert nach `kategorie_id`, die Reihenfolge kommt aus
    `position`. Ein Eintrag, der beim Ziehen scheinbar in eine andere
    Kategorie rutscht, springt beim naechsten Laden zurueck - das ist der
    verwirrendste Teil des Fehlers. Sortieren darf die Zuordnung nie
    anfassen."""
    v = db["verbindung"]
    # "Technik" ist bereits Seed-Kategorie (UNIQUE auf name) - eine mit
    # garantiert freiem Namen anlegen.
    zweite = v.execute(
        "INSERT INTO packlisten_kategorien(name, position) VALUES(?, 99) RETURNING id",
        ("PRUEF-Kategorie 181",)).fetchone()["id"]
    fremd = v.execute(
        "INSERT INTO packlisten_eintraege(name, ziel_id, kategorie_id, position) "
        "VALUES('Ladekabel', ?, ?, 9) RETURNING id", (liste["ziel"], zweite)).fetchone()["id"]
    v.commit()

    vorher = {r["id"]: r["kategorie_id"] for r in v.execute(
        "SELECT id, kategorie_id FROM packlisten_eintraege")}

    # Reihenfolge quer durch beide Kategorien schicken - so, wie es das
    # Frontend im Fehlerfall getan haette.
    a, b, c = liste["ids"]
    client.post(f"/a/packliste/{liste['token']}/reorder",
                json={"order": [fremd, a, c, b]})

    nachher = {r["id"]: r["kategorie_id"] for r in v.execute(
        "SELECT id, kategorie_id FROM packlisten_eintraege")}
    assert nachher == vorher, "Umsortieren hat eine Kategorie-Zuordnung geaendert"


def test_zieh_helfer_kennt_gruppengrenzen():
    """Ohne Gruppenfilter war der naechste Kandidat unterhalb der letzten
    Zeile einer Kategorie der erste Eintrag der FOLGENDEN - der Eintrag sprang
    sichtbar hinueber."""
    base = (TPL / "base.html").read_text(encoding="utf-8")
    block = base[base.index("function folge("):]
    block = block[:block.index("\n    }")]
    glatt = " ".join(block.split())
    # Auf den VERGLEICH pruefen, nicht auf das blosse Vorkommen von
    # "opt.gruppe": Die erste Fassung dieses Tests ueberlebte die Gegenprobe,
    # weil die Zuweisung `const schluessel = opt.gruppe ? ...` stehen blieb,
    # waehrend der Filter selbst ausgehebelt war.
    assert "opt.gruppe(el) === schluessel" in glatt, (
        "ziehSortierung() vergleicht die Gruppe nicht - Eintraege koennen "
        "beim Ziehen in die Nachbarkategorie springen (Wunsch #181)."
    )


def test_rueckfall_haengt_an_die_eigene_gruppe():
    """Der zweite Teil des Fehlers: `appendChild` auf den Behaelter setzte den
    Eintrag ans Ende von ALLEM - ans Listenende ziehen landete quer durch
    alle Kategorien ganz unten."""
    base = (TPL / "base.html").read_text(encoding="utf-8")
    block = base[base.index("function folge("):]
    block = block[:block.index("\n    }")]
    assert "andere[andere.length - 1]" in block
    assert "letzter.nextSibling" in block


def test_packliste_gruppiert_nach_kategorie():
    inhalt = (TPL / "packliste.html").read_text(encoding="utf-8")
    block = inhalt[inhalt.index("ziehSortierung({"):]
    block = block[:block.index("});")]
    assert "gruppe:" in block and "dataset.kategorie" in block
