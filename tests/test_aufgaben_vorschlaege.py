"""Aufgaben (neu), Schritt 5 (Wunsch #301) - Regeln und Vorschlaege.

Spezifikation 5.1 und Entscheidung 15.1: Wochentage; Intervall ab Erledigung;
kein neuer Vorschlag bei offenem Vorgaenger; Abwechseln setzt fort;
gestrichen wird nicht neu erzeugt; idempotent bei Doppelaufruf; pausiert
erzeugt nichts; Freigabe nur fuer heute (auto_bestaetigt); vergangene
Vorschlaege verfallen zu 'aus'; gruppenlose landen in "Noch zu haben";
Tageswechsel mit gepatchter Uhr (23:30 / 00:30 Ortszeit).
"""
from datetime import date

import pytest
import teile.aufgaben as modul
from teile.aufgaben import aufgabe_neu, noch_zu_haben, vorschlaege_sicherstellen

HEUTE = date(2026, 9, 19)          # Samstag
H = HEUTE.isoformat()


@pytest.fixture()
def fam(app, db):
    v = db["verbindung"]
    f = {name: v.execute("SELECT * FROM users WHERE id=?", (d["id"],)).fetchone()
         for name, d in db["familie"].items()}
    k2 = v.execute("INSERT INTO users(name, farbe, is_admin, rolle) VALUES('Kind2','#444444',0,'kind') RETURNING id").fetchone()["id"]
    v.commit()
    f["Kind2"] = v.execute("SELECT * FROM users WHERE id=?", (k2,)).fetchone()
    return {"v": v, **f}


def _termine(v, aid):
    return v.execute("SELECT * FROM termine WHERE aufgabe_id=? ORDER BY tag, id", (aid,)).fetchall()


def test_wochentage_erzeugen_je_tag_bis_ende_naechster_woche(app, fam):
    v, eltern, kind = fam["v"], fam["TestEltern"], fam["TestKind"]
    with app.app_context():
        a = aufgabe_neu(v, eltern, "Tisch decken", ziel_user=kind["id"], regel_typ="wochentage",
                        regel_wochentage="0,2,4", push=False, heute=H)["aufgabe_id"]
        assert _termine(v, a) == []
        e = vorschlaege_sicherstellen(v, H)
    tage = [t["tag"] for t in _termine(v, a)]
    # Sa 19.9. bis So 27.9. (Ende naechster Woche): Mo 21., Mi 23., Fr 25.
    assert tage == ["2026-09-21", "2026-09-23", "2026-09-25"] and e["erzeugt"] == 3
    assert all(t["status"] == "vorschlag" and t["user_id"] == kind["id"] for t in _termine(v, a))
    # Doppelaufruf aendert nichts
    with app.app_context():
        e = vorschlaege_sicherstellen(v, H)
    assert e["erzeugt"] == 0 and len(_termine(v, a)) == 3


def test_kind_eigene_regel_direkt_offen_und_pausiert_erzeugt_nichts(app, fam):
    v, kind = fam["v"], fam["TestKind"]
    with app.app_context():
        a = aufgabe_neu(v, kind, "Vokabeln", regel_typ="wochentage", regel_wochentage="0,1,2,3,4,5,6",
                        push=False, heute=H)["aufgabe_id"]
        vorschlaege_sicherstellen(v, H)
    zeilen = _termine(v, a)
    assert len(zeilen) == 9 and all(t["status"] == "offen" for t in zeilen)
    assert zeilen[0]["tag"] == H and zeilen[0]["auto_bestaetigt"] == 0    # war nie Vorschlag
    v.execute("UPDATE aufgaben SET pausiert=1 WHERE id=?", (a,))
    v.execute("DELETE FROM termine WHERE aufgabe_id=?", (a,))
    v.commit()
    with app.app_context():
        assert vorschlaege_sicherstellen(v, H)["erzeugt"] == 0


def test_intervall_ab_erledigung_und_kein_neuer_bei_offenem(app, fam):
    v, eltern, kind = fam["v"], fam["TestEltern"], fam["TestKind"]
    with app.app_context():
        a = aufgabe_neu(v, eltern, "Blumen gießen", ziel_user=kind["id"], regel_typ="intervall",
                        regel_intervall=3, push=False, heute=H)["aufgabe_id"]
        vorschlaege_sicherstellen(v, H)
    zeilen = _termine(v, a)
    assert [t["tag"] for t in zeilen] == ["2026-09-20"]          # ohne Vorgeschichte: morgen
    # solange der offen/vorschlag ist, kein weiterer
    with app.app_context():
        vorschlaege_sicherstellen(v, H)
    assert len(_termine(v, a)) == 1
    # erledigt am 20. -> naechster am 23.
    v.execute("UPDATE termine SET status='erledigt', erledigt_tag='2026-09-20' WHERE id=?", (zeilen[0]["id"],))
    v.commit()
    with app.app_context():
        vorschlaege_sicherstellen(v, "2026-09-21")
    assert [t["tag"] for t in _termine(v, a)] == ["2026-09-20", "2026-09-23"]
    # lange nicht erledigt: naechster liegt in der Vergangenheit -> heute
    v.execute("DELETE FROM termine WHERE tag='2026-09-23'")
    v.commit()
    with app.app_context():
        vorschlaege_sicherstellen(v, "2026-10-05")
    assert [t["tag"] for t in _termine(v, a)][-1] == "2026-10-05"


def test_abwechseln_setzt_fort(app, fam):
    v, eltern, kind, kind2 = fam["v"], fam["TestEltern"], fam["TestKind"], fam["Kind2"]
    with app.app_context():
        a = aufgabe_neu(v, eltern, "Spülmaschine", ziel_gruppe="kinder", regel_typ="wochentage",
                        regel_wochentage="0,1,2,3,4", push=False, heute=H)["aufgabe_id"]
        vorschlaege_sicherstellen(v, H)
    personen = [t["user_id"] for t in _termine(v, a)]
    assert personen == [kind["id"], kind2["id"], kind["id"], kind2["id"], kind["id"]]
    # Weiter in der Folgewoche: setzt beim naechsten fort (Fr war Kind -> Mo Kind2)
    with app.app_context():
        vorschlaege_sicherstellen(v, "2026-09-28")
    personen = [t["user_id"] for t in _termine(v, a) if t["tag"] >= "2026-09-28"]
    assert personen[:2] == [kind2["id"], kind["id"]]
    # Gruppe alle: ohne Person
    with app.app_context():
        b = aufgabe_neu(v, eltern, "Altglas", ziel_gruppe="alle", regel_typ="wochentage",
                        regel_wochentage="5", push=False, heute=H)["aufgabe_id"]
        vorschlaege_sicherstellen(v, H)
    assert all(t["user_id"] is None for t in _termine(v, b))


def test_gestrichen_wird_nicht_neu_erzeugt(app, fam):
    v, eltern, kind = fam["v"], fam["TestEltern"], fam["TestKind"]
    with app.app_context():
        a = aufgabe_neu(v, eltern, "Tisch decken", ziel_user=kind["id"], regel_typ="wochentage",
                        regel_wochentage="0", push=False, heute=H)["aufgabe_id"]
        vorschlaege_sicherstellen(v, H)
    t = _termine(v, a)[0]
    v.execute("UPDATE termine SET status='aus' WHERE id=?", (t["id"],))
    v.commit()
    with app.app_context():
        assert vorschlaege_sicherstellen(v, H)["erzeugt"] == 0
    assert [z["status"] for z in _termine(v, a)] == ["aus"]


def test_freigabe_nur_heute_verfall_und_noch_zu_haben(app, fam):
    v, eltern, kind = fam["v"], fam["TestEltern"], fam["TestKind"]
    with app.app_context():
        a = aufgabe_neu(v, eltern, "Täglich", ziel_user=kind["id"], regel_typ="wochentage",
                        regel_wochentage="0,1,2,3,4,5,6", push=False, heute="2026-09-17")["aufgabe_id"]
        g = aufgabe_neu(v, eltern, "Wer will täglich", ziel_gruppe="alle", regel_typ="wochentage",
                        regel_wochentage="0,1,2,3,4,5,6", push=False, heute="2026-09-17")["aufgabe_id"]
        vorschlaege_sicherstellen(v, "2026-09-17")     # erzeugt ab Do 17.9. als Vorschlag
    assert all(t["status"] == "offen" for t in _termine(v, a) if t["tag"] == "2026-09-17")   # heute -> offen
    assert all(t["status"] == "vorschlag" for t in _termine(v, a) if t["tag"] > "2026-09-17")
    # zwei Tage niemand da: am 19. laeuft es wieder
    with app.app_context():
        e = vorschlaege_sicherstellen(v, H)
    stati = {t["tag"]: (t["status"], t["auto_bestaetigt"]) for t in _termine(v, a)}
    assert stati["2026-09-18"] == ("aus", 0)             # verfallen, nicht ueberfaellig
    assert stati["2026-09-19"] == ("offen", 1)           # heute automatisch freigegeben
    assert stati["2026-09-20"] == ("vorschlag", 0)       # morgen bleibt Vorschlag
    assert e["freigegeben"] >= 2 and e["verfallen"] >= 2
    # gruppenlose landen in "Noch zu haben" des Kindes
    frei = noch_zu_haben(v, kind, kind, H)
    # heute UND der liegengebliebene vom 17. (offen, nie genommen) - beide "noch zu haben"
    assert [z["inhalt"] for z in frei] == ["Wer will täglich", "Wer will täglich"]
    assert v.execute("SELECT status FROM termine WHERE aufgabe_id=? AND tag=?", (g, H)).fetchone()[0] == "offen"
    # Doppelaufruf: nichts aendert sich mehr
    with app.app_context():
        e = vorschlaege_sicherstellen(v, H)
    assert e == {"erzeugt": 0, "verfallen": 0, "freigegeben": 0}


def test_tageswechsel_mit_gepatchter_uhr(app, fam, monkeypatch):
    """23:30 Ortszeit am 19.9. ist noch der 19.; 00:30 am 20.9. ist der 20. -
    heute_lokal() aus dem Kern entscheidet, keine zweite Kalenderquelle."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from teile import kern
    v, eltern, kind = fam["v"], fam["TestEltern"], fam["TestKind"]
    berlin = ZoneInfo("Europe/Berlin")

    class Uhr(datetime):
        _jetzt = datetime(2026, 9, 19, 23, 30, tzinfo=berlin)
        @classmethod
        def now(cls, tz=None):
            return cls._jetzt.astimezone(tz) if tz else cls._jetzt.replace(tzinfo=None)

    monkeypatch.setattr(kern, "datetime", Uhr)
    assert kern.heute_lokal() == "2026-09-19"
    with app.app_context():
        a = aufgabe_neu(v, eltern, "Täglich", ziel_user=kind["id"], regel_typ="wochentage",
                        regel_wochentage="0,1,2,3,4,5,6", push=False)["aufgabe_id"]
        vorschlaege_sicherstellen(v)
    stati = {t["tag"]: t["status"] for t in _termine(v, a)}
    assert stati["2026-09-19"] == "offen" and stati["2026-09-20"] == "vorschlag"
    Uhr._jetzt = datetime(2026, 9, 20, 0, 30, tzinfo=berlin)
    assert kern.heute_lokal() == "2026-09-20"
    with app.app_context():
        vorschlaege_sicherstellen(v)
    stati = {t["tag"]: (t["status"], t["auto_bestaetigt"]) for t in _termine(v, a)}
    assert stati["2026-09-20"] == ("offen", 1) and stati["2026-09-21"] == ("vorschlag", 0)
    assert modul.heute_lokal() == "2026-09-20"
