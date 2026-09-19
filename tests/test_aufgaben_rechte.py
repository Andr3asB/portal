"""Aufgaben (neu), Schritt 1 - Rechte (Spezifikation 3.2) und aufgabe_neu().

Die Matrix aus 3.2, Zeile fuer Zeile, als Funktionen ohne Oberflaeche:
Kinder duerfen an Eigenem viel und an Zugewiesenem wenig; Eltern alles
Sichtbare; `is_admin` gibt nichts dazu; Gaeste nur lesen. Dazu die
Validierung beim Anlegen: Kinder-POSTs mit Punkten, Kachel oder Symbol werden
still ignoriert, Regeln geprueft, Tage im Fenster gehalten.
"""
import pytest
from teile.aufgaben import (
    AufgabenFehler,
    aufgabe_neu,
    darf_bearbeiten,
    darf_freigeben,
    darf_haken,
    darf_kachel_zurueck,
    darf_loeschen,
    darf_nehmen,
    darf_parken,
    darf_punkte_setzen,
    darf_vorschlaege,
    punkte_runden,
    termin_sichtbar,
    wochentage_lesen,
)


@pytest.fixture()
def n(db):
    v = db["verbindung"]
    return {name: v.execute("SELECT * FROM users WHERE id=?", (d["id"],)).fetchone()
            for name, d in db["familie"].items()}


def _aufgabe(v, aid):
    return v.execute("SELECT * FROM aufgaben WHERE id=?", (aid,)).fetchone()


def test_kind_darf_eigenes_nicht_aber_zugewiesenes(app, db, n):
    v = db["verbindung"]
    kind, eltern = n["TestKind"], n["TestEltern"]
    with app.app_context():
        eigen = aufgabe_neu(v, kind, "Selbst angelegt", push=False)
        fremd = aufgabe_neu(v, eltern, "Von Eltern zugewiesen", ziel_user=kind["id"], push=False)
    t_eigen = termin_sichtbar(v, kind, eigen["termin_id"])
    t_fremd = termin_sichtbar(v, kind, fremd["termin_id"])
    a_eigen, a_fremd = _aufgabe(v, eigen["aufgabe_id"]), _aufgabe(v, fremd["aufgabe_id"])

    assert darf_haken(kind, t_eigen) and darf_haken(kind, t_fremd)          # eigene Termine
    assert darf_bearbeiten(kind, a_eigen) and not darf_bearbeiten(kind, a_fremd)
    assert darf_parken(kind, t_eigen) and not darf_parken(kind, t_fremd)
    assert darf_loeschen(kind, a_eigen) and not darf_loeschen(kind, a_fremd)
    assert not darf_punkte_setzen(kind) and not darf_vorschlaege(kind)


def test_eltern_duerfen_alles_sichtbare_admin_nichts_extra(app, db, n):
    v = db["verbindung"]
    kind, eltern, admin = n["TestKind"], n["TestEltern"], n["TestAdmin"]
    with app.app_context():
        eigen = aufgabe_neu(v, kind, "Kindersache", sicht="alle", push=False)
        privat = aufgabe_neu(v, kind, "Geheim", sicht="ich", push=False)
    t = termin_sichtbar(v, eltern, eigen["termin_id"])
    a = _aufgabe(v, eigen["aufgabe_id"])
    for e in (eltern, admin):
        assert darf_haken(e, t) and darf_bearbeiten(e, a) and darf_parken(e, t)
        assert darf_loeschen(e, a) and darf_punkte_setzen(e) and darf_vorschlaege(e)
    # Das Private des Kindes sieht auch der Admin nicht - das Recht kommt nie
    # zum Zug, weil die Sichtbarkeit vorher None liefert (404).
    assert termin_sichtbar(v, admin, privat["termin_id"]) is None


def test_kind_kann_selbst_angelegtes_mit_punkten_nicht_loeschen(app, db, n):
    """Kinder bekommen keine Punkte gesetzt - aber wenn Eltern einer vom Kind
    angelegten Aufgabe spaeter Punkte geben, ist Loeschen Elternsache."""
    v = db["verbindung"]
    kind = n["TestKind"]
    with app.app_context():
        r = aufgabe_neu(v, kind, "Rasen", push=False)
    v.execute("UPDATE aufgaben SET punkte = 2 WHERE id=?", (r["aufgabe_id"],)); v.commit()
    assert not darf_loeschen(kind, _aufgabe(v, r["aufgabe_id"]))


def test_gruppenaufgabe_nehmen_und_freigeben(app, db, n):
    v = db["verbindung"]
    kind, eltern = n["TestKind"], n["TestEltern"]
    with app.app_context():
        kinder = aufgabe_neu(v, eltern, "Tisch abraeumen", ziel_gruppe="kinder", push=False)
        nur_eltern = aufgabe_neu(v, eltern, "Steuer", ziel_gruppe="eltern", sicht="eltern", push=False)
    t_k = termin_sichtbar(v, kind, kinder["termin_id"])
    assert t_k["user_id"] is None and darf_nehmen(kind, t_k)
    assert not darf_nehmen(eltern, termin_sichtbar(v, eltern, kinder["termin_id"]))
    assert darf_nehmen(eltern, termin_sichtbar(v, eltern, nur_eltern["termin_id"]))
    assert termin_sichtbar(v, kind, nur_eltern["termin_id"]) is None
    # nach dem Nehmen: freigeben darf, wer es hat - oder Eltern
    v.execute("UPDATE termine SET user_id=? WHERE id=?", (kind["id"], kinder["termin_id"])); v.commit()
    t_k = termin_sichtbar(v, kind, kinder["termin_id"])
    assert darf_freigeben(kind, t_k) and darf_freigeben(eltern, t_k)
    assert not darf_nehmen(kind, t_k), "schon vergeben"


def test_kachel_zurueck_nur_eigener_tipp_von_heute(app, db, n):
    v = db["verbindung"]
    kind, eltern = n["TestKind"], n["TestEltern"]
    with app.app_context():
        r = aufgabe_neu(v, eltern, "Tisch decken", kachel=1, wann=None, push=False)
    assert r["termin_id"] is None, "reine Kachel hat keinen Termin"
    tid = v.execute("""INSERT INTO termine(aufgabe_id, tag, user_id, status, spontan, erledigt_tag, getippt_von)
                       VALUES(?, '2026-09-19', ?, 'erledigt', 1, '2026-09-19', ?) RETURNING id""",
                    (r["aufgabe_id"], kind["id"], kind["id"])).fetchone()["id"]
    v.commit()
    t = termin_sichtbar(v, kind, tid)
    assert darf_kachel_zurueck(kind, t, "2026-09-19")
    assert not darf_kachel_zurueck(kind, t, "2026-09-20"), "nur heute"
    assert darf_kachel_zurueck(eltern, t, "2026-09-25"), "Eltern jederzeit"
    fremd = dict(t); fremd["getippt_von"] = eltern["id"]
    assert not darf_kachel_zurueck(kind, fremd, "2026-09-19"), "nur eigener Tipp"


def test_kind_post_mit_punkten_kachel_symbol_wird_ignoriert(app, db, n):
    v = db["verbindung"]
    kind = n["TestKind"]
    with app.app_context():
        r = aufgabe_neu(v, kind, "Ich will Punkte", punkte=5, kachel=1, emoji="🍽️",
                        ziel_user=n["TestEltern"]["id"], ziel_gruppe="alle", push=False)
    a = _aufgabe(v, r["aufgabe_id"])
    assert (a["punkte"], a["kachel"], a["emoji"]) == (0, 0, None)
    assert a["ziel_user"] == kind["id"] and a["ziel_gruppe"] is None, "Ziel immer ich"
    with app.app_context(), pytest.raises(AufgabenFehler):
        aufgabe_neu(v, kind, "Nur Eltern", sicht="eltern", push=False)


def test_eltern_felder_werden_normalisiert(app, db, n):
    v = db["verbindung"]
    with app.app_context():
        r = aufgabe_neu(v, n["TestEltern"], "Bad putzen", punkte="3,7", kachel=1,
                        emoji="🧹", uhrzeit="07:30", push=False)
    a = _aufgabe(v, r["aufgabe_id"])
    assert a["punkte"] == 3.5 and a["kachel"] == 1 and a["emoji"] == "🧹"
    t = v.execute("SELECT * FROM termine WHERE id=?", (r["termin_id"],)).fetchone()
    assert t["uhrzeit"] == "07:30" and t["status"] == "offen"
    assert punkte_runden(12) == 10.0 and punkte_runden("x") == 0.0 and punkte_runden(0.26) == 0.5


def test_regeln_werden_geprueft_und_erzeugen_keinen_termin(app, db, n):
    v = db["verbindung"]
    e = n["TestEltern"]
    with app.app_context():
        w = aufgabe_neu(v, e, "Muell", regel_typ="wochentage", regel_wochentage="4,0,2", push=False)
        i = aufgabe_neu(v, e, "Blumen", regel_typ="intervall", regel_intervall="3", push=False)
        with pytest.raises(AufgabenFehler):
            aufgabe_neu(v, e, "x", regel_typ="wochentage", regel_wochentage="7", push=False)
        with pytest.raises(AufgabenFehler):
            aufgabe_neu(v, e, "x", regel_typ="intervall", regel_intervall=1, push=False)
    assert w["termin_id"] is None and i["termin_id"] is None
    assert _aufgabe(v, w["aufgabe_id"])["regel_wochentage"] == "0,2,4"
    assert _aufgabe(v, i["aufgabe_id"])["regel_intervall"] == 3
    assert wochentage_lesen([6, 0]) == "0,6" and wochentage_lesen("") is None


def test_tag_im_fenster_und_geparkt(app, db, n):
    v = db["verbindung"]
    e = n["TestEltern"]
    with app.app_context():
        ok = aufgabe_neu(v, e, "Bald", wann="2026-09-25", heute="2026-09-19", push=False)
        with pytest.raises(AufgabenFehler):
            aufgabe_neu(v, e, "Zu spaet", wann="2027-01-01", heute="2026-09-19", push=False)
        with pytest.raises(AufgabenFehler):
            aufgabe_neu(v, e, "Zu frueh", wann="2026-09-01", heute="2026-09-19", push=False)
        woche = aufgabe_neu(v, e, "Diese Woche", wann="woche", heute="2026-09-16", push=False)
        p1 = aufgabe_neu(v, e, "Parken 1", wann="geparkt", push=False)
        p2 = aufgabe_neu(v, e, "Parken 2", wann="geparkt", push=False)
    t = lambda r: v.execute("SELECT * FROM termine WHERE id=?", (r["termin_id"],)).fetchone()
    assert t(ok)["tag"] == "2026-09-25"
    assert t(woche)["tag"] == "2026-09-20" and t(woche)["flexibel"] == 1
    assert t(p1)["status"] == "geparkt" and t(p1)["tag"] is None and t(p1)["geparkt_am"]
    assert t(p2)["position"] == t(p1)["position"] + 1


def test_keine_dublette_fuer_externe_aufrufer(app, db, n):
    v = db["verbindung"]
    e = n["TestEltern"]
    with app.app_context():
        a = aufgabe_neu(v, e, "Guthaben aufladen", keine_dublette=True, push=False)
        b = aufgabe_neu(v, e, "Guthaben aufladen", keine_dublette=True, push=False)
    assert a["neu"] and not b["neu"] and a["termin_id"] == b["termin_id"]
    assert v.execute("SELECT COUNT(*) FROM aufgaben").fetchone()[0] == 1


def test_push_bei_zuweisung_an_andere(app, db, n, monkeypatch):
    import sys
    modul = sys.modules["teile.aufgaben"]
    aufrufe = []
    monkeypatch.setattr(modul, "push_send", lambda *a, **k: aufrufe.append((a, k)))
    v = db["verbindung"]
    with app.app_context():
        aufgabe_neu(v, n["TestEltern"], "Fuer dich", ziel_user=n["TestKind"]["id"])
        aufgabe_neu(v, n["TestEltern"], "Fuer mich")
        aufgabe_neu(v, n["TestEltern"], "Fuer alle", ziel_gruppe="alle")
    assert len(aufrufe) == 1 and aufrufe[0][0][0] == n["TestKind"]["id"]
