"""Wunsch #220: Vokabelliste nach Sprache, Kapitel und „ohne Kapitel" filtern.

Der Auslöser steht nicht im Wunschtext, sondern in den echten Daten: Andi hat
64 eigene Vokabeln, und die 8, die Friederike ihm geteilt hat, stehen wegen
`ORDER BY (v.user_id = :uid) DESC` **ganz unten**. Sichtbar waren sie schon
immer (Wunsch #150) – auffindbar nicht.

Deshalb ist der wichtigste Test hier
`test_geteilte_kapitel_stehen_im_filter`: Ein Kapitelfilter, der nur die
eigenen Kapitel kennt, lässt genau das nicht filtern, was man am ehesten
sucht. Er wäre nicht falsch, sondern unbrauchbar – und das fiele erst auf,
wenn jemand danach sucht.

Der zweite Fund steckt in `test_ohne_eigene_sprache_bleiben_geteilte_sichtbar`:
Die Startseite hing an den EIGENEN aktiven Sprachen. Wer keine hatte, sah nur
„Noch keine Sprache aktiv" – auch wenn ihm jemand ein Kapitel geteilt hatte.
Die Freigabe stand, die Vokabeln waren trotzdem unerreichbar.
"""
import pathlib
import re

import pytest

TPL = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"
VOKABELN = TPL / "vokabeln.html"


@pytest.fixture()
def vok(app, db):
    """Friederike (Kind) teilt ein Kapitel mit dem Admin. Der Admin hat
    ausserdem eigene Vokabeln, eine davon ohne Kapitel."""
    from teile.kern import new_token, token_lookup
    v = db["verbindung"]
    familie = db["familie"]
    besitzer  = familie["TestKind"]["id"]
    empfaenger = familie["TestAdmin"]["id"]

    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='vokabeln'").fetchone()["id"]
        tokens = {}
        for name, daten in familie.items():
            klartext = new_token()
            v.execute("INSERT INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                      (daten["id"], app_id, token_lookup(klartext)))
            tokens[name] = klartext

    sprachen = {}
    for name in ("Englisch", "Dänisch"):
        zeile = v.execute("SELECT id FROM vokabel_sprachen WHERE name=?", (name,)).fetchone()
        sprachen[name] = zeile["id"] if zeile else v.execute(
            "INSERT INTO vokabel_sprachen(name) VALUES(?) RETURNING id", (name,)).fetchone()["id"]
    for uid in (besitzer, empfaenger):
        for sid in sprachen.values():
            v.execute("INSERT OR IGNORE INTO vokabel_sprachen_nutzer(user_id, sprache_id) "
                      "VALUES(?,?)", (uid, sid))

    # Fremdes, geteiltes Kapitel
    fremd_kid = v.execute(
        "INSERT INTO vokabel_kapitel(user_id, name) VALUES(?, 'Dänemark Urlaub') RETURNING id",
        (besitzer,)).fetchone()["id"]
    fremd_vid = v.execute(
        "INSERT INTO vokabeln(user_id, sprache_id, fremd, deutsch) VALUES(?,?,'tak','danke') "
        "RETURNING id", (besitzer, sprachen["Dänisch"])).fetchone()["id"]
    v.execute("INSERT INTO vokabel_kapitel_zuordnung(vokabel_id, kapitel_id) VALUES(?,?)",
              (fremd_vid, fremd_kid))
    v.execute("INSERT INTO vokabel_kapitel_freigabe(kapitel_id, user_id) VALUES(?,?)",
              (fremd_kid, empfaenger))

    # Eigenes Kapitel + eine Vokabel ganz ohne Kapitel
    eigen_kid = v.execute(
        "INSERT INTO vokabel_kapitel(user_id, name) VALUES(?, 'Unit 5') RETURNING id",
        (empfaenger,)).fetchone()["id"]
    eigen_vid = v.execute(
        "INSERT INTO vokabeln(user_id, sprache_id, fremd, deutsch) VALUES(?,?,'house','Haus') "
        "RETURNING id", (empfaenger, sprachen["Englisch"])).fetchone()["id"]
    v.execute("INSERT INTO vokabel_kapitel_zuordnung(vokabel_id, kapitel_id) VALUES(?,?)",
              (eigen_vid, eigen_kid))
    ohne_vid = v.execute(
        "INSERT INTO vokabeln(user_id, sprache_id, fremd, deutsch) VALUES(?,?,'tree','Baum') "
        "RETURNING id", (empfaenger, sprachen["Englisch"])).fetchone()["id"]
    v.commit()

    return {"tokens": tokens, "sprachen": sprachen, "fremd_kid": fremd_kid,
            "eigen_kid": eigen_kid, "fremd_vid": fremd_vid, "eigen_vid": eigen_vid,
            "ohne_vid": ohne_vid, "besitzer": besitzer, "empfaenger": empfaenger}


@pytest.fixture()
def seite(client, vok):
    return client.get(f"/a/vokabeln/{vok['tokens']['TestAdmin']}/").get_data(as_text=True)


def _item(seite, wort):
    treffer = re.search(
        r'<div class="vokabel-item"[^>]*>(?:(?!vokabel-item).)*?'
        r'<span class="vokabel-fremd">' + re.escape(wort) + '</span>',
        seite, re.DOTALL)
    assert treffer, f"{wort!r} steht nicht auf der Seite"
    return re.match(r'<div class="vokabel-item"[^>]*>', treffer.group(0)).group(0)


# ── Der Knopf und sein Platz ───────────────────────────────────────────────

def test_der_filterknopf_steht_zwischen_eintragen_und_lernen(seite):
    """Im Wunsch ausdrücklich so verlangt."""
    zeile = re.search(r'<div class="top-aktionen">.*?</div>', seite, re.DOTALL).group(0)
    eintragen = zeile.index("neu-toggle-btn")
    filtern   = zeile.index("filter-toggle-btn")
    lernen    = zeile.index("btn-lernen")
    assert eintragen < filtern < lernen, (
        "Reihenfolge stimmt nicht: Eintragen → Filtern → Lernen")


# ── Was der Filter anbietet ────────────────────────────────────────────────

def test_alle_zugaenglichen_sprachen_stehen_im_filter(seite, vok):
    zeile = re.search(r'id="filter-sprache-row".*?\n    </div>', seite, re.DOTALL).group(0)
    for sid in vok["sprachen"].values():
        assert f'data-value="{sid}"' in zeile


def test_geteilte_kapitel_stehen_im_filter(seite, vok):
    """Der Kern des Wunsches. Ein Filter aus `_eigene_kapitel` kennt genau das
    nicht, was man am ehesten sucht - die 8 geteilten Vokabeln stehen wegen
    der Sortierung ganz unten und sind sonst praktisch unauffindbar."""
    zeile = re.search(r'id="filter-kapitel-row".*?\n    </div>', seite, re.DOTALL).group(0)
    assert f'data-value="{vok["eigen_kid"]}"' in zeile, "eigenes Kapitel fehlt"
    assert f'data-value="{vok["fremd_kid"]}"' in zeile, (
        "geteiltes Kapitel fehlt im Filter - genau das war der Anlass")


def test_geteilte_kapitel_nennen_ihren_besitzer(seite):
    """Sonst stünden zwei gleichnamige Kapitel ununterscheidbar nebeneinander
    und man wüsste nicht, wessen Vokabeln man da filtert."""
    zeile = re.search(r'id="filter-kapitel-row".*?\n    </div>', seite, re.DOTALL).group(0)
    assert "TestKind" in zeile


def test_ohne_kapitel_ist_filterbar(seite):
    """Ausdrücklich im Wunsch. Ohne diesen Chip sind genau die Vokabeln
    unauffindbar, die noch niemand einsortiert hat."""
    zeile = re.search(r'id="filter-kapitel-row".*?\n    </div>', seite, re.DOTALL).group(0)
    assert 'data-value="ohne"' in zeile


# ── Woran gefiltert wird ───────────────────────────────────────────────────

def test_jede_vokabel_traegt_sprache_und_kapitel(seite):
    for karte in re.findall(r'<div class="vokabel-item"[^>]*>', seite):
        assert "data-sprache=" in karte, karte
        assert "data-kapitel=" in karte, karte


def test_vokabel_ohne_kapitel_hat_leeres_kapitelfeld(seite, vok):
    assert 'data-kapitel=""' in _item(seite, "tree")


def test_vokabel_mit_kapitel_traegt_dessen_id(seite, vok):
    assert f'data-kapitel="{vok["eigen_kid"]}"' in _item(seite, "house")


def test_geteilte_vokabel_traegt_das_geteilte_kapitel(seite, vok):
    """Ohne das griffe der Filter zwar, aber die fremde Vokabel fiele heraus -
    der Chip wäre da und träfe nichts."""
    assert f'data-kapitel="{vok["fremd_kid"]}"' in _item(seite, "tak")


# ── Der Fund: die Sperre versteckte geteilte Vokabeln ──────────────────────
#
# Beim Schreiben dieser Tests kam heraus, dass der Zustand "gar keine eigene
# Sprache" NICHT durch Abwählen entsteht: `_aktive_sprachen_sicherstellen()`
# legt alle Standardsprachen wieder an, sobald keine einzige Zeile mehr da ist
# - auch nach dem Abwählen der letzten. Erreichbar ist er nur über den anderen
# Weg: Ein Admin schaltet eine Sprache GLOBAL ab (`vokabel_sprachen.aktiv=0`),
# und sie war die einzige des Nutzers. Dann greift der Automatismus nicht
# (es gibt ja eine Zeile), und `_eigene_sprachen` liefert trotzdem nichts.
#
# Das ist selten - aber genau deshalb wäre es nie aufgefallen, und die
# Freigabe hätte still ins Leere gezeigt.

def _nur_abgeschaltete_sprache(db, user_id):
    """Dem Nutzer bleibt genau eine Sprache, und die ist global abgeschaltet.

    `vokabel_sprachen` ist eine Seed-Tabelle und steht in `BLEIBT`
    (conftest.py) - sie wird zwischen den Tests NICHT geleert. Daraus folgen
    zwei Dinge, und beide sind hier schon schiefgegangen:

    1. Ein blankes INSERT läuft beim zweiten Aufruf in den UNIQUE-Index.
    2. **Der Name muss dieser Datei gehören.** Die erste Fassung nannte die
       Sprache „Suaheli" – denselben Namen legt `test_tts_sprache.py` an, dort
       aber AKTIV. Läuft es vorher (und alphabetisch tut es das), fand das
       `INSERT OR IGNORE` hier eine aktive Sprache vor, der Nutzer hatte
       plötzlich eine, und beide Tests dieser Gruppe fielen um - allein
       grün, im Gesamtlauf rot.

    Deshalb ein eigener Name und `aktiv` ausdrücklich gesetzt statt auf die
    Voreinstellung vertraut.
    """
    v = db["verbindung"]
    NAME = "Nur-für-Test-220 (inaktiv)"
    v.execute("INSERT OR IGNORE INTO vokabel_sprachen(name, aktiv) VALUES(?, 0)", (NAME,))
    v.execute("UPDATE vokabel_sprachen SET aktiv=0 WHERE name=?", (NAME,))
    sid = v.execute("SELECT id FROM vokabel_sprachen WHERE name=?", (NAME,)).fetchone()["id"]
    v.execute("DELETE FROM vokabel_sprachen_nutzer WHERE user_id=?", (user_id,))
    v.execute("INSERT INTO vokabel_sprachen_nutzer(user_id, sprache_id) VALUES(?,?)",
              (user_id, sid))
    v.commit()


def test_ohne_eigene_sprache_bleiben_geteilte_sichtbar(client, vok, db):
    """Die Startseite hing an den EIGENEN aktiven Sprachen. Wer keine hatte,
    sah nur den Leer-Hinweis - obwohl die Freigabe stand und die Vokabeln
    laut Sichtbarkeitsregel zu sehen sein müssten."""
    _nur_abgeschaltete_sprache(db, vok["empfaenger"])

    seite = client.get(f"/a/vokabeln/{vok['tokens']['TestAdmin']}/").get_data(as_text=True)
    assert "tak" in seite, "geteilte Vokabel fehlt trotz Freigabe"
    assert "Noch keine Sprache aktiv" not in seite


def test_ohne_eigene_sprache_kein_eintragen(client, vok, db):
    """Die Gegenrichtung: ansehen ja, eintragen nein. `_sprache_erlaubt()`
    liesse das Speichern ohnehin nicht durch - ein Knopf, der ins Leere
    führt, wäre schlechte Bedienung."""
    _nur_abgeschaltete_sprache(db, vok["empfaenger"])

    seite = client.get(f"/a/vokabeln/{vok['tokens']['TestAdmin']}/").get_data(as_text=True)
    assert 'id="neu-toggle-btn"' not in seite
    assert "keine eigene Sprache aktiv" in seite, "Hinweis fehlt, warum nichts geht"


def test_wer_gar_nichts_hat_bekommt_weiter_den_hinweis(client, db):
    """Der Leer-Hinweis darf nicht verschwinden - nur nicht mehr im falschen
    Moment kommen. Nichts geteilt, keine eigene Sprache: dann ist er richtig."""
    from teile.kern import new_token, token_lookup
    v = db["verbindung"]
    eltern = db["familie"]["TestEltern"]["id"]
    with client.application.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='vokabeln'").fetchone()["id"]
        klartext = new_token()
        v.execute("INSERT INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                  (eltern, app_id, token_lookup(klartext)))
    v.commit()
    _nur_abgeschaltete_sprache(db, eltern)

    seite = client.get(f"/a/vokabeln/{klartext}/").get_data(as_text=True)
    assert "Noch keine Sprache aktiv" in seite


# ── Verdrahtung im Template ────────────────────────────────────────────────

def test_suche_und_filter_teilen_sich_eine_funktion():
    """Beide setzen `style.display`. Zwei getrennte Funktionen überschreiben
    sich gegenseitig: wer erst filtert und dann sucht, sähe wieder
    herausgefilterte Vokabeln."""
    quelle = VOKABELN.read_text(encoding="utf-8")
    assert quelle.count("function vokabelnAnzeigen") == 1
    treffer = re.search(r"getElementById\('vokabel-suche'\)\?\.addEventListener\("
                        r"'input', (\w+)\)", quelle)
    assert treffer, "Die Suche hängt nicht mehr an einer benannten Funktion"
    assert treffer.group(1) == "vokabelnAnzeigen", (
        f"Die Suche ruft {treffer.group(1)} statt der gemeinsamen Funktion")


def test_der_filter_ueberlebt_das_neuladen_aber_nicht_den_tab():
    """„Der Filter bleibt erhalten, solange der Benutzer die App nicht
    verlässt" - sessionStorage trifft das genau; localStorage bliebe für
    immer, und beim nächsten Öffnen fehlten scheinbar Vokabeln."""
    quelle = VOKABELN.read_text(encoding="utf-8")
    block = quelle[quelle.index("function vokabelnAnzeigen"):]
    block = block[:block.index("\n}")]
    assert "sessionStorage.setItem(FILTER_KEY" in block
    assert "localStorage.setItem(FILTER_KEY" not in quelle


def test_die_suche_wird_nicht_mitgemerkt():
    """Ein gemerkter Suchbegriff, den man beim Zurückkommen nicht im Feld
    sieht, sieht aus wie verschwundene Vokabeln."""
    quelle = VOKABELN.read_text(encoding="utf-8")
    block = quelle[quelle.index("sessionStorage.setItem(FILTER_KEY"):]
    block = block[:block.index("\n")]
    assert "q" not in re.findall(r"\{([^}]*)\}", block)[0] if "{" in block else True
    assert "suche" not in block.lower()
