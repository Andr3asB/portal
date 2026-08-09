"""Wunsch #162: Gekochte Rezepte abhaken, um zu erfassen WANN gekocht wurde.

Die Entscheidung, die alles andere bestimmt: Die Historie hängt am **Rezept**,
nicht am Planeintrag. Ein Planeintrag wird überschrieben, per Drag & Drop
verschoben (#35) und irgendwann gelöscht – hinge das „gekocht" daran, wäre die
Aufzeichnung genau dann weg, wenn sie interessant wird. Wunsch #165 will sie
später je Rezept auflisten.

Deshalb prüfen die Tests vor allem, was die Aufzeichnung **überlebt**.
"""
import pytest


@pytest.fixture()
def plan(app, db):
    """Zwei Planeinträge: einer mit Rezept, einer als Freitext."""
    from teile.kern import token_lookup, new_token
    v = db["familie"] and db["verbindung"]
    familie = db["familie"]

    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='essensplan'").fetchone()["id"]
        tokens = {}
        for name, daten in familie.items():
            klartext = new_token()
            v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) "
                      "VALUES(?,?,?)", (daten["id"], app_id, token_lookup(klartext)))
            tokens[name] = klartext

    rid = v.execute(
        "INSERT INTO rezepte(name) VALUES('Linsen mit Spätzle') RETURNING id"
    ).fetchone()["id"]
    v.execute("INSERT INTO essensplan_eintraege(tag, mahlzeit, rezept_id, erstellt_von) "
              "VALUES('2026-08-05','abend',?,?)", (rid, familie["TestAdmin"]["id"]))
    v.execute("INSERT INTO essensplan_eintraege(tag, mahlzeit, text, erstellt_von) "
              "VALUES('2026-08-06','abend','Pizza vom Lieferdienst',?)",
              (familie["TestAdmin"]["id"],))
    v.commit()
    return {"tokens": tokens, "rid": rid}


def _umschalten(client, token, tag="2026-08-05", mahlzeit="abend"):
    return client.post(f"/a/essensplan/{token}/gekocht",
                       data={"tag": tag, "mahlzeit": mahlzeit})


def _eintraege(db, rid=None):
    if rid is None:
        return db["verbindung"].execute(
            "SELECT * FROM rezept_gekocht ORDER BY id").fetchall()
    return db["verbindung"].execute(
        "SELECT * FROM rezept_gekocht WHERE rezept_id=? ORDER BY id", (rid,)).fetchall()


# --- Abhaken und wieder abwählen -------------------------------------------

def test_abhaken_erfasst_den_zeitpunkt(client, db, plan):
    _umschalten(client, plan["tokens"]["TestAdmin"])
    zeilen = _eintraege(db, plan["rid"])
    assert len(zeilen) == 1
    assert zeilen[0]["tag"] == "2026-08-05"
    assert zeilen[0]["markiert_am"], "ohne Zeitstempel waere die ganze Erfassung wertlos"
    assert zeilen[0]["markiert_von"] == db["familie"]["TestAdmin"]["id"]


def test_nochmal_druecken_nimmt_es_zurueck(client, db, plan):
    """Ein Haken, den man nicht mehr wegnimmt, ist bei einem Versehen
    ärgerlich – anders als im Kassenbuch geht es hier um eine Notiz, nicht
    um Buchführung."""
    token = plan["tokens"]["TestAdmin"]
    _umschalten(client, token)
    _umschalten(client, token)
    assert _eintraege(db, plan["rid"]) == []


def test_doppeltes_abhaken_erzeugt_keine_dublette(client, db, plan):
    """Zwei schnelle Klicks (oder ein doppelt gesendetes Formular) dürfen den
    Verlauf nicht mit Dubletten füllen – #165 zeigt ihn später als Liste."""
    token = plan["tokens"]["TestAdmin"]
    _umschalten(client, token)          # an
    _umschalten(client, token)          # aus
    _umschalten(client, token)          # wieder an
    assert len(_eintraege(db, plan["rid"])) == 1


# --- Die Aufzeichnung überlebt den Plan ------------------------------------

def test_geaenderter_planeintrag_loescht_die_historie_nicht(client, db, plan):
    """Der Kern der Sache. Wird der Slot mit etwas anderem überschrieben,
    bleibt „am 05.08. gab es Linsen" trotzdem wahr."""
    token = plan["tokens"]["TestAdmin"]
    _umschalten(client, token)
    db["verbindung"].execute(
        "UPDATE essensplan_eintraege SET rezept_id=NULL, text='Doch Pizza' "
        "WHERE tag='2026-08-05' AND mahlzeit='abend'")
    db["verbindung"].commit()
    assert len(_eintraege(db, plan["rid"])) == 1


def test_geloeschter_planeintrag_loescht_die_historie_nicht(client, db, plan):
    token = plan["tokens"]["TestAdmin"]
    _umschalten(client, token)
    v = db["verbindung"]
    v.execute("PRAGMA foreign_keys=ON")
    v.execute("DELETE FROM essensplan_eintraege WHERE tag='2026-08-05'")
    v.commit()
    assert len(_eintraege(db, plan["rid"])) == 1


def test_geloeschtes_rezept_raeumt_die_historie_ab(client, db, plan):
    """Gegenstück: Ohne Rezept ist der Eintrag sinnlos – dort MUSS es
    kaskadieren, sonst bleiben Waisen zurück."""
    token = plan["tokens"]["TestAdmin"]
    _umschalten(client, token)
    v = db["verbindung"]
    v.execute("PRAGMA foreign_keys=ON")
    v.execute("DELETE FROM rezepte WHERE id=?", (plan["rid"],))
    v.commit()
    assert _eintraege(db) == []


# --- Grenzen ----------------------------------------------------------------

def test_freitext_kann_nicht_abgehakt_werden(client, db, plan):
    """„wann ein Rezept aus der DB gekocht wurde" – für „Pizza vom
    Lieferdienst" gibt es kein Rezept, an dem das hängen könnte."""
    antwort = _umschalten(client, plan["tokens"]["TestAdmin"], tag="2026-08-06")
    assert antwort.status_code == 404
    assert _eintraege(db) == []


def test_leerer_slot_geht_nicht(client, db, plan):
    assert _umschalten(client, plan["tokens"]["TestAdmin"],
                       tag="2026-08-07").status_code == 404


def test_unbekannte_mahlzeit_wird_abgelehnt(client, db, plan):
    assert _umschalten(client, plan["tokens"]["TestAdmin"],
                       mahlzeit="fruehstueck").status_code == 400


def test_ohne_zugang_kein_abhaken(client, db, plan):
    assert _umschalten(client, "unsinn").status_code == 403
    assert _eintraege(db) == []


# --- Oberfläche -------------------------------------------------------------

def test_haken_erscheint_nur_beim_rezept(client, db, plan):
    seite = client.get(f"/a/essensplan/{plan['tokens']['TestAdmin']}/").get_data(as_text=True)
    # Der Slot mit Rezept hat das Formular, der Freitext-Slot nicht.
    assert seite.count('class="gekocht-form"') == 1


def test_zustand_ist_in_der_liste_sichtbar(client, db, plan):
    token = plan["tokens"]["TestAdmin"]
    vorher = client.get(f"/a/essensplan/{token}/").get_data(as_text=True)
    assert "gekocht?" in vorher and "gekocht-btn aktiv" not in vorher

    _umschalten(client, token)
    nachher = client.get(f"/a/essensplan/{token}/").get_data(as_text=True)
    assert "gekocht-btn aktiv" in nachher
