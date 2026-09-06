"""Wunsch #263 und #264: Endstaende der Profis - nachladen und nicht raten.

Andis Frage vom 06.09.2026, ob alte Bundesliga-Ergebnisse wirklich nicht
nachladbar sind, hat zwei Dinge ans Licht gebracht:

1. **#263** - Sportradar hat einen Einzelspiel-Endpunkt (`fixture_detail`),
   der zu JEDER Kennung den Endstand liefert, egal wie alt das Spiel ist.
   Die Aussage "verpasst man das Spieltagswochenende, ist das Ergebnis weg"
   war falsch. `_profi_nachladen()` zieht vergangene Spiele ohne
   bestaetigten Endstand darueber nach.
2. **#264** - der Ribbon liefert waehrend des Spiels Zwischenstaende
   (isLive=true, isFinal=false). Der Code hielt "beide Tore da" fuer
   "beendet" und speicherte 33:31 als Endstand eines Spiels, das 34:34
   endete. Dazu las er `date` (Ortszeit) als UTC: Anwurf zwei Stunden zu spaet.

Die Spalte `tvb_spiele.bestaetigt` haelt fest, ob der gespeicherte Stand von
der Quelle als Endstand bestaetigt ist. Nur dann ist er unantastbar; alles
andere darf fixture_detail korrigieren.
"""
import importlib

import pytest


@pytest.fixture()
def modul(app):
    return importlib.import_module("teile.18_tvb")


def _ribbon_eintrag(heim="Handball Club Hamburg", gast="TVB Stuttgart", tore=(33, 31),
                    final=False, live=True, kennung="hh1"):
    return {"data": {"fixtures": [{
        "competitors": [
            {"name": heim, "isHome": True, "score": tore[0]},
            {"name": gast, "isHome": False, "score": tore[1]},
        ],
        "fixture": {"date": "2026-09-02T19:00:00", "startTimeUTC": "2026-09-02T17:00:00",
                    "isFinal": final, "isLive": live, "fixtureId": kennung,
                    "status": {"value": "CONFIRMED" if final else "LIVE"}},
    }]}}


def _detail(heim="Handball Club Hamburg", gast="TVB Stuttgart", tore=("34", "34"),
            status="CONFIRMED", kennung="hh1"):
    """Die Form von fixture_detail: competitors IM fixture, Tore als Text,
    Status als Zeichenkette."""
    return {"data": {"fixture": {
        "fixtureId": kennung, "startTimeUTC": "2026-09-02T17:00:00", "status": status,
        "competitors": [
            {"name": heim, "isHome": True, "score": tore[0], "resultStatus": status},
            {"name": gast, "isHome": False, "score": tore[1], "resultStatus": status},
        ],
    }}}


# --- #264: Zwischenstand ist kein Endstand -----------------------------------

def test_laufendes_spiel_ist_live_und_unbestaetigt(modul, monkeypatch):
    """Der Hamburg-Fall: Tore da, isLive=true, isFinal=false."""
    monkeypatch.setattr(modul, "_sr_get", lambda pfad, embed=248: _ribbon_eintrag())
    s = modul._profi_spiele()[0]
    assert s["status"] == "Live"
    assert s["bestaetigt"] == 0
    assert (s["heim_tore"], s["gast_tore"]) == (33, 31)
    assert s["anstoss"].startswith("2026-09-02T19:00"), "date (Ortszeit) als UTC gelesen"


def test_beendetes_spiel_ist_bestaetigt(modul, monkeypatch):
    monkeypatch.setattr(modul, "_sr_get",
                        lambda pfad, embed=248: _ribbon_eintrag(final=True, live=False, tore=(34, 34)))
    s = modul._profi_spiele()[0]
    assert s["status"] == "Ended" and s["bestaetigt"] == 1


def test_status_confirmed_ohne_isfinal_reicht(modul, monkeypatch):
    eintrag = _ribbon_eintrag(final=False, live=False)
    eintrag["data"]["fixtures"][0]["fixture"]["status"] = {"value": "CONFIRMED"}
    monkeypatch.setattr(modul, "_sr_get", lambda pfad, embed=248: eintrag)
    s = modul._profi_spiele()[0]
    assert s["status"] == "Ended" and s["bestaetigt"] == 1


def test_tore_ohne_jede_statusangabe_gelten_als_gespielt_aber_unbestaetigt(modul, monkeypatch):
    """Der Pokal-Spielplan fuehrt Ergebnisse ohne isFinal/isLive (#231). Sie
    bleiben sichtbar - aber fixture_detail darf sie noch korrigieren."""
    eintrag = _ribbon_eintrag(final=False, live=False, tore=(26, 39))
    del eintrag["data"]["fixtures"][0]["fixture"]["status"]
    del eintrag["data"]["fixtures"][0]["fixture"]["isLive"]
    monkeypatch.setattr(modul, "_sr_get", lambda pfad, embed=248: eintrag)
    s = modul._profi_spiele()[0]
    assert s["status"] == "Ended" and s["bestaetigt"] == 0


def test_neue_api_bestaetigt_ueber_is_finished(modul):
    roh = {"id": 1, "date": "2026-08-30T17:00:00+00:00", "status": {"is_finished": True},
           "result": {"local": 35, "visitor": 26}, "local": {"name": "A"}, "visitor": {"name": "B"}}
    assert modul._spiel_aus_neu(roh, "x")["bestaetigt"] == 1
    roh["status"] = {"is_finished": False, "is_live": True}
    assert modul._spiel_aus_neu(roh, "x")["bestaetigt"] == 0


# --- #263: fixture_detail --------------------------------------------------------

def test_detail_wird_verstanden(modul):
    s = modul._sr_spiel_aus_detail(_detail(), "Opel HBL")
    assert s["id"] == "srhh1"
    assert (s["heim_tore"], s["gast_tore"]) == (34, 34), "Tore kommen dort als Text"
    assert s["status"] == "Ended" and s["bestaetigt"] == 1
    assert s["wettbewerb"] == "Opel HBL"
    assert modul._sr_spiel_aus_detail(None, "Opel HBL") is None
    assert modul._sr_spiel_aus_detail({"data": {}}, "Opel HBL") is None


def _zeile(db, kennung="srhh1", tore=(33, 31), status="Ended", bestaetigt=0,
           anstoss="2026-09-02T21:00:00+02:00", wettbewerb="Opel HBL",
           aktualisiert="2026-09-02 18:52:50"):
    v = db["verbindung"]
    v.execute("""
        INSERT INTO tvb_spiele(id, team_id, heim, gast, heim_tore, gast_tore, anstoss, status,
                               wettbewerb, bestaetigt, aktualisiert_am)
        VALUES (?, 'profis', 'Handball Club Hamburg', 'TVB Stuttgart', ?, ?, ?, ?, ?, ?, ?)
    """, (kennung, tore[0], tore[1], anstoss, status, wettbewerb, bestaetigt, aktualisiert))
    v.commit()


def _gelesen(db, kennung="srhh1"):
    return db["verbindung"].execute(
        "SELECT heim_tore, gast_tore, status, bestaetigt, anstoss, wettbewerb FROM tvb_spiele WHERE id=?",
        (kennung,)).fetchone()


def test_nachladen_korrigiert_den_hamburg_stand(app, modul, db, monkeypatch):
    """33:31 (Zwischenstand, vor #264 als Endstand gespeichert) wird 34:34,
    bestaetigt, und der Anwurf steht danach richtig (19:00 statt 21:00)."""
    _zeile(db)
    aufrufe = []

    def sr(pfad, embed=248):
        aufrufe.append((pfad, embed))
        return _detail() if "fixture_detail" in pfad and "hh1" in pfad else None

    monkeypatch.setattr(modul, "_sr_get", sr)
    with app.app_context():
        from teile.kern import get_db
        uebernommen = modul._profi_nachladen(get_db())
    assert len(uebernommen) == 1
    z = _gelesen(db)
    assert (z["heim_tore"], z["gast_tore"], z["status"], z["bestaetigt"]) == (34, 34, "Ended", 1)
    assert z["anstoss"].startswith("2026-09-02T19:00")
    assert aufrufe == [("fixture_detail?locale=de-DE&fixtureId=hh1", 248)]


def test_bestaetigtes_spiel_wird_nicht_erneut_angefragt(app, modul, db, monkeypatch):
    _zeile(db, bestaetigt=1)
    aufrufe = []
    monkeypatch.setattr(modul, "_sr_get", lambda pfad, embed=248: aufrufe.append(pfad))
    with app.app_context():
        from teile.kern import get_db
        assert modul._profi_nachladen(get_db()) == []
    assert aufrufe == []


def test_unbekanntes_spiel_wird_hoechstens_stuendlich_versucht(app, modul, db, monkeypatch):
    """Kennt die Quelle das Spiel nicht (404 -> None), bleibt der Stand, aber
    aktualisiert_am rueckt vor - der naechste Seitenaufruf fragt nicht gleich
    wieder. Ohne Bremse hinge an jedem Aufruf ein toter Roundtrip."""
    _zeile(db)
    aufrufe = []
    monkeypatch.setattr(modul, "_sr_get", lambda pfad, embed=248: aufrufe.append(embed))
    with app.app_context():
        from teile.kern import get_db
        assert modul._profi_nachladen(get_db()) == []
        assert aufrufe == [248, 255], "beide Embeds probiert"
        assert modul._profi_nachladen(get_db()) == []
    assert aufrufe == [248, 255], "innerhalb einer Stunde kein zweiter Versuch"
    z = _gelesen(db)
    assert (z["heim_tore"], z["gast_tore"], z["bestaetigt"]) == (33, 31, 0)


def test_pokalspiel_fragt_zuerst_das_pokal_embed(app, modul, db, monkeypatch):
    _zeile(db, kennung="srpokal1", wettbewerb="DHB-Pokal", tore=(None, None), status="Pre",
           anstoss="2026-08-21T20:00:00+02:00")
    aufrufe = []

    def sr(pfad, embed=248):
        aufrufe.append(embed)
        return _detail(heim="TSB Heilbronn-Horkheim", tore=("26", "39"), kennung="pokal1") if embed == 255 else None

    monkeypatch.setattr(modul, "_sr_get", sr)
    with app.app_context():
        from teile.kern import get_db
        modul._profi_nachladen(get_db())
    assert aufrufe == [255]
    z = _gelesen(db, "srpokal1")
    assert (z["heim_tore"], z["gast_tore"], z["status"], z["bestaetigt"]) == (26, 39, "Ended", 1)


def test_noch_laufendes_spiel_wird_nicht_als_endstand_uebernommen(app, modul, db, monkeypatch):
    _zeile(db, tore=(None, None), status="Pre")
    monkeypatch.setattr(modul, "_sr_get",
                        lambda pfad, embed=248: _detail(status="LIVE", tore=("10", "9")))
    with app.app_context():
        from teile.kern import get_db
        assert modul._profi_nachladen(get_db()) == []
    z = _gelesen(db)
    assert z["heim_tore"] is None and z["bestaetigt"] == 0


def test_kuenftige_spiele_und_fremde_quellen_bleiben_aussen_vor(app, modul, db, monkeypatch):
    _zeile(db, kennung="srzukunft", tore=(None, None), status="Pre", anstoss="2099-01-01T20:00:00+01:00")
    _zeile(db, kennung="n12345", tore=(None, None), status="Pre")
    aufrufe = []
    monkeypatch.setattr(modul, "_sr_get", lambda pfad, embed=248: aufrufe.append(pfad))
    with app.app_context():
        from teile.kern import get_db
        modul._profi_nachladen(get_db())
    assert aufrufe == []


def test_hoechstens_grenze_spiele_je_aufruf(app, modul, db, monkeypatch):
    for i in range(5):
        _zeile(db, kennung=f"sralt{i}", tore=(None, None), status="Pre",
               anstoss=f"2026-08-0{i + 1}T20:00:00+02:00")
    aufrufe = []
    monkeypatch.setattr(modul, "_sr_get", lambda pfad, embed=248: aufrufe.append(pfad))
    with app.app_context():
        from teile.kern import get_db
        modul._profi_nachladen(get_db(), grenze=2)
    # zwei Spiele, je zwei Embeds probiert
    assert len(aufrufe) == 4
    assert "alt0" in aufrufe[0] and "alt1" in aufrufe[2], "aelteste zuerst"


# --- Der UPSERT: bestaetigt ist unantastbar ------------------------------------

def test_bestaetigter_endstand_wird_nicht_ueberschrieben(app, modul, db):
    """Ein spaeter Ribbon-Eintrag ohne Bestaetigung (etwa ein zwischen-
    gespeicherter Stand aus dem Cache) darf 34:34 nicht wieder zu 33:31 machen."""
    _zeile(db, tore=(34, 34), bestaetigt=1)
    with app.app_context():
        from teile.kern import get_db
        modul._tvb_spiele_aktualisieren(get_db(), [{
            "id": "srhh1", "team_id": "profis", "spieltag": None, "heim": "Handball Club Hamburg",
            "gast": "TVB Stuttgart", "heim_tore": 33, "gast_tore": 31,
            "anstoss": "2026-09-02T19:00:00+02:00", "ort": None, "status": "Live",
            "wettbewerb": None, "bestaetigt": 0,
        }])
    z = _gelesen(db)
    assert (z["heim_tore"], z["gast_tore"], z["status"], z["bestaetigt"]) == (34, 34, "Ended", 1)
    assert z["anstoss"].startswith("2026-09-02T19:00"), "der Anwurf wird trotzdem uebernommen"
    assert z["wettbewerb"] == "Opel HBL", "NULL ueberschreibt keinen bekannten Wettbewerb"


def test_unbestaetigter_stand_wird_vom_neueren_ersetzt(app, modul, db):
    _zeile(db, tore=(20, 19), status="Live", bestaetigt=0)
    with app.app_context():
        from teile.kern import get_db
        modul._tvb_spiele_aktualisieren(get_db(), [{
            "id": "srhh1", "team_id": "profis", "spieltag": None, "heim": "Handball Club Hamburg",
            "gast": "TVB Stuttgart", "heim_tore": 34, "gast_tore": 34,
            "anstoss": "2026-09-02T19:00:00+02:00", "ort": None, "status": "Ended",
            "wettbewerb": "Opel HBL", "bestaetigt": 1,
        }])
    z = _gelesen(db)
    assert (z["heim_tore"], z["gast_tore"], z["status"], z["bestaetigt"]) == (34, 34, "Ended", 1)


# --- Die Seite ---------------------------------------------------------------------

def test_seite_zeigt_laufendes_spiel_als_laufend(app, client, db, modul, monkeypatch):
    from teile.kern import new_token, token_lookup
    v = db["verbindung"]
    uid = db["familie"]["TestAdmin"]["id"]
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='tvb'").fetchone()["id"]
        token = new_token()
        v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                  (uid, app_id, token_lookup(token)))
        v.commit()
    _zeile(db, tore=(33, 31), status="Live", anstoss="2026-09-02T19:00:00+02:00")
    monkeypatch.setattr(modul, "_sr_get", lambda pfad, embed=248: None)
    monkeypatch.setattr(modul, "_neu_api_get", lambda *a, **k: None)
    seite = client.get(f"/a/tvb/{token}/").get_data(as_text=True)
    assert "🔴 läuft" in seite
    assert "33:31" in seite
    assert 'class="tvb-erg-score live"' in seite
    assert "sieger" not in seite.split("Handball Club Hamburg")[0][-200:], "kein Sieger beim Zwischenstand"
