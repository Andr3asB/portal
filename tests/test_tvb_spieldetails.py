"""Wunsch #267/#268: Spieldetails - kommend und gespielt.

Zwei Quellen mit voellig verschiedenen Formaten (Sportradar fixture_detail
+ pbp + preview fuer die Profis, handball.net events + lineups fuer die
Amateurmannschaften) werden auf EIN Detailformat gebracht. Die Tests bauen
beide Rohformate nach und pruefen das Ergebnis - und die Seite, die es
zeigt: Anzeigetafel mit Halbzeit, Ticker, Statistik, Aufstellung, dazu die
Notnaegel (Quelle weg, Cache alt, unbekannte Kennung).
"""
import importlib
import json

import pytest

SR = "sre502f0cb-79f2-11f1-8212-55a849a4570e"
HH = "0045fbc4-3953-11ef-a217-af5c55c3771d"    # Hamburg
TVB = "febb3114-3952-11ef-b6f7-af5c55c3771d"   # TVB


@pytest.fixture()
def modul(app):
    return importlib.import_module("teile.18_tvb")


@pytest.fixture()
def tvb(app, db):
    from teile.kern import new_token, token_lookup
    v = db["verbindung"]
    uid = db["familie"]["TestAdmin"]["id"]
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='tvb'").fetchone()["id"]
        token = new_token()
        v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                  (uid, app_id, token_lookup(token)))
        v.execute("""INSERT INTO tvb_spiele(id, team_id, spieltag, heim, gast, heim_tore, gast_tore, anstoss, ort, status, wettbewerb, bestaetigt)
                     VALUES (?, 'profis', '2. Spieltag', 'Handball Club Hamburg', 'TVB Stuttgart', 34, 34,
                             '2026-09-02T19:00:00+02:00', NULL, 'Ended', 'Opel HBL', 1)""", (SR,))
        v.execute("""INSERT INTO tvb_spiele(id, team_id, spieltag, heim, gast, heim_tore, gast_tore, anstoss, ort, status, wettbewerb, bestaetigt)
                     VALUES ('srf1adac8a-79f2-11f1-be57-55a849a4570e', 'profis', '4. Spieltag', 'MT Melsungen', 'TVB Stuttgart', NULL, NULL,
                             '2099-09-13T18:00:00+02:00', 'Rothenbach-Halle', 'Pre', 'Opel HBL', 0)""")
        v.execute("""INSERT INTO tvb_spiele(id, team_id, spieltag, heim, gast, heim_tore, gast_tore, anstoss, ort, status, wettbewerb, bestaetigt)
                     VALUES ('n414837', '87353', '2. Spieltag', 'TV BITTENFELD II', 'TSV NEUHAUSEN/Filder', 26, 28,
                             '2026-09-05T21:30:00+02:00', 'Sporthalle', 'Ended', '3. Liga Männer', 1)""")
        v.execute("INSERT OR IGNORE INTO tvb_mannschaften(team_id, name, ist_profi) VALUES ('87353', 'TV Bittenfeld II', 0)")
        v.commit()
    return {"token": token, "v": v}


# --- Sportradar-Rohdaten -------------------------------------------------------------

def _sr_basis(status="CONFIRMED", tore=("34", "34"), statistik=True):
    def comp(eid, name, code, home, tore_):
        return {"entityId": eid, "name": name, "code": code, "isHome": home, "score": tore_,
                "draw": tore[0] == tore[1], "resultPlace": 1, "resultStatus": status}
    daten = {
        "fixture": {"fixtureId": SR[2:], "competitionName": "1. Handball-Bundesliga", "venue": "Barclays Arena",
                    "attendance": 3546, "status": status, "startTimeUTC": "2026-09-02T17:00:00",
                    "competitors": [comp(HH, "Handball Club Hamburg", "HCH", True, tore[0]),
                                    comp(TVB, "TVB Stuttgart", "TVB", False, tore[1])]},
        "periodData": {"teamScores": {HH: [{"periodId": 1, "score": 12}, {"periodId": 2, "score": 22}],
                                      TVB: [{"periodId": 1, "score": 14}, {"periodId": 2, "score": 20}]}},
        "statistics": {"data": {"base": {
            "home": {"persons": [{"label": "Spieler", "rows": [
                {"bib": "7", "personName": "Heimspieler", "position": "LW", "starter": True, "participated": True,
                 "statistics": {"goalsScored:shots": "5/7", "shootingAccuracy": 71.43, "handballPerformanceIndex": 88.2,
                                "sevenMetreGoalsScored:sevenMetreShots": "0/0", "assists": 2, "blocks": 0, "steals": 1,
                                "twoMinuteSuspensions": 1, "technicalFaults": 0, "redCards": 0, "timeOnPlayingField": "PT48M12S"}},
                {"bib": "99", "personName": "Nicht dabei", "position": "GK", "starter": False, "participated": False, "statistics": {}},
            ]}]},
            "away": {"persons": [{"label": "Spieler", "rows": [
                {"bib": "34", "personName": "Kai Häfner", "position": "RB", "starter": True, "participated": True,
                 "statistics": {"goalsScored:shots": "8/10", "shootingAccuracy": 80.0, "handballPerformanceIndex": 120.5,
                                "sevenMetreGoalsScored:sevenMetreShots": "4/4", "assists": 3, "blocks": 1, "steals": 0,
                                "twoMinuteSuspensions": 0, "technicalFaults": 2, "redCards": 0, "timeOnPlayingField": "PT27M44S"}},
            ]}]},
        }}} if statistik else {},
    }
    return {"data": daten}


def _sr_pbp():
    """Die echten Typnamen (07.09.2026): ein Wurf ist immer "goal", `success`
    entscheidet; Zeitstrafe "suspension", Auszeit "timeOut"."""
    def ev(periode, clock, typ, desc, eid, name, bib, h, g, sub=None, success=None):
        return {"periodId": periode, "clock": clock, "eventType": typ, "eventSubType": sub, "desc": desc,
                "entityId": eid, "name": name, "bib": bib, "scores": {HH: h, TVB: g}, "success": success}
    return {"data": {"pbp": {
        "1": {"durationMinutes": 30, "ended": True, "events": [
            ev(1, "PT0M0S", "goalKeeperChange", "Torwartwechsel", TVB, "El-Tayar", "12", 0, 0),
            ev(1, "PT0M44S", "goal", "Tor aus dem Rückraum", TVB, "Mohamed Amine Darmoul", "70", 0, 1, "nineMetre", True),
            ev(1, "PT3M1S", "goal", "Fehlwurf aus der Nahwurfzone", HH, "Jemand", "3", 0, 1, "sixMetre", False),
            ev(1, "PT5M2S", "suspension", "Zwei-Minuten Strafe", HH, "Jemand", "3", 2, 3, "twoMinutes"),
        ]},
        "2": {"durationMinutes": 30, "ended": True, "events": [
            ev(2, "PT12M5S", "goal", "7-Meter Strafwurf erfolgreich", HH, "Heimspieler", "7", 20, 22, "sevenMetrePenalty", True),
            ev(2, "PT29M50S", "timeOut", "Auszeit eines Teams", TVB, None, None, 34, 34, "team"),
        ]},
    }}}


def _sr_preview():
    return {"data": {"preview": {"persons": {
        HH: {"starters": [{"bib": "7", "name": "Heimspieler", "position": "Linksaußen", "age": 25}],
             "substitutes": [], "staff": [{"name": "Trainer H", "roleLabel": "Offizieller A"}]},
        TVB: {"starters": [{"bib": "34", "name": "Kai Häfner", "position": "Rückraum Rechts", "age": 37}],
              "substitutes": [{"bib": "99", "name": "Bankspieler", "position": "Tor", "age": 20}],
              "staff": [{"name": "Daniel Sdunek", "roleLabel": "Offizieller A"}]},
        "matchOfficials": [{"name": "Marvin Cesnik", "roleLabel": "Schiedsrichter"}],
    }}}}


def _sr_get_fake(basis=None, pbp=None, preview=None, embed_ok=248):
    aufrufe = []

    def sr(pfad, embed=248):
        aufrufe.append((embed, pfad))
        if embed != embed_ok:
            return None
        if "sub=pbp" in pfad:
            return pbp
        if "sub=preview" in pfad:
            return preview
        return basis
    return sr, aufrufe


def test_sportradar_details_vollstaendig(modul, monkeypatch):
    sr, aufrufe = _sr_get_fake(_sr_basis(), _sr_pbp(), _sr_preview())
    monkeypatch.setattr(modul, "_sr_get", sr)
    zeile = {"id": SR, "wettbewerb": "Opel HBL", "spieltag": "2. Spieltag", "anstoss": "2026-09-02T19:00:00+02:00",
             "heim": "Handball Club Hamburg", "gast": "TVB Stuttgart", "heim_tore": 34, "gast_tore": 34, "ort": None, "status": "Ended"}
    d = modul._sr_details(zeile)
    k = d["kopf"]
    assert k["wettbewerb"] == "1. Handball-Bundesliga" and k["halle"] == "Barclays Arena" and k["zuschauer"] == 3546
    assert (k["heim"]["tore"], k["gast"]["tore"]) == (34, 34) and k["status"] == "Ended"
    assert k["halbzeit"] == (12, 14), "Halbzeit = Tore des 1. Abschnitts, nicht kumuliert"
    assert k["heim"]["sieger"] is False and k["gast"]["sieger"] is False, "Unentschieden"
    # Ticker: Minute zaehlt in der 2. Halbzeit weiter, Art aus Typ + success,
    # Abschnittsmarken werden ergaenzt (die Quelle hat keine), Spielende mit
    # dem letzten bekannten Stand.
    arten = [(e["minute"], e["art"], e["stand"], e["seite"]) for e in d["ticker"]]
    assert arten == [("0:00", "abschnitt", None, None),
                     ("0:00", "wechsel", "0:0", "gast"), ("0:44", "tor", "0:1", "gast"),
                     ("3:01", "fehlwurf", "0:1", "heim"), ("5:02", "strafe", "2:3", "heim"),
                     ("30:00", "abschnitt", None, None),
                     ("42:05", "tor", "20:22", "heim"), ("59:50", "auszeit", "34:34", "gast"),
                     ("60:00", "abschnitt", "34:34", None)]
    assert [e["text"] for e in d["ticker"] if e["art"] == "abschnitt"] == ["1. Halbzeit", "2. Halbzeit", "Spielende"]
    # Statistik: nur wer gespielt hat, Spielzeit lesbar, Quote gerundet
    assert [z["name"] for z in d["statistik"]["heim"]] == ["Heimspieler"]
    kh = d["statistik"]["gast"][0]
    assert (kh["nummer"], kh["goalsScored:shots"], kh["timeOnPlayingField"], kh["shootingAccuracy"]) == ("34", "8/10", "27:44", 80.0)
    assert d["statistik"]["heim"][0]["shootingAccuracy"] == 71.4
    # Aufstellung + Offizielle
    assert [p["name"] for p in d["aufstellung"]["gast"]["spieler"]] == ["Kai Häfner", "Bankspieler"]
    assert d["aufstellung"]["gast"]["spieler"][1]["start"] is False
    assert d["aufstellung"]["gast"]["stab"] == [{"name": "Daniel Sdunek", "rolle": "Offizieller A"}]
    assert d["schiedsrichter"] == [{"name": "Marvin Cesnik", "rolle": "Schiedsrichter"}]
    assert [p for e, p in aufrufe] == [f"fixture_detail?locale=de-DE&fixtureId={SR[2:]}",
                                       f"fixture_detail?locale=de-DE&fixtureId={SR[2:]}&sub=pbp",
                                       f"fixture_detail?locale=de-DE&fixtureId={SR[2:]}&sub=preview"]


def test_kommendes_spiel_fragt_keinen_ticker(modul, monkeypatch):
    sr, aufrufe = _sr_get_fake(_sr_basis(status="SCHEDULED", tore=(None, None), statistik=False), None, _sr_preview())
    monkeypatch.setattr(modul, "_sr_get", sr)
    zeile = {"id": SR, "wettbewerb": "Opel HBL", "spieltag": None, "anstoss": "2099-09-13T18:00:00+02:00",
             "heim": "MT Melsungen", "gast": "TVB Stuttgart", "heim_tore": None, "gast_tore": None, "ort": None, "status": "Pre"}
    d = modul._sr_details(zeile)
    assert d["kopf"]["status"] == "Pre" and d["kopf"]["heim"]["tore"] is None
    assert d["ticker"] == [] and d["statistik"] == {}
    assert not any("sub=pbp" in p for _, p in aufrufe)


def test_pokal_zuerst_im_pokal_embed_und_quelle_weg(modul, monkeypatch):
    sr, aufrufe = _sr_get_fake(_sr_basis(), _sr_pbp(), _sr_preview(), embed_ok=255)
    monkeypatch.setattr(modul, "_sr_get", sr)
    zeile = {"id": SR, "wettbewerb": "DHB-Pokal", "spieltag": None, "anstoss": "2026-08-21T20:00:00+02:00",
             "heim": "A", "gast": "TVB Stuttgart", "heim_tore": 26, "gast_tore": 39, "ort": None, "status": "Ended"}
    assert modul._sr_details(zeile) is not None
    assert aufrufe[0][0] == 255
    monkeypatch.setattr(modul, "_sr_get", lambda pfad, embed=248: None)
    assert modul._sr_details(zeile) is None


def test_uhr_und_minute(modul):
    assert modul._dauer_lesbar("PT27M44S") == "27:44"
    assert modul._dauer_lesbar("PT1H2M3S") == "62:03"
    assert modul._dauer_lesbar(None) is None and modul._dauer_lesbar("unsinn") is None
    assert modul._spielminute("PT12M5S", 2) == "42:05"
    assert modul._spielminute("PT0M0S", 1) == "0:00"


# --- handball.net-Rohdaten -----------------------------------------------------------

def _neu_events():
    """Wie die echte Antwort (07.09.2026): NICHT chronologisch geliefert, das
    `score`-Feld ausserhalb der Halbzeit-Bloecke unbrauchbar (hier absichtlich
    Unsinn), Zeitstempel sind die Wahrheit."""
    def ev(ts, minute, gmin, block, typ_id, name, goal, spieler, home, h, g):
        return {"id": ts, "timestamp": f"2026-09-05T{ts}+00:00", "minute": minute, "global_minute": gmin, "block": block,
                "event_type": {"id": typ_id, "name": name, "is_goal": goal, "is_sanction": False},
                "player": ({"first_name": spieler.split()[0], "last_name": spieler.split()[1]} if spieler else None),
                "team": {"id": 1, "name": "x"} if spieler else None, "is_home": home,
                "score": {"local": h, "visitor": g}}
    return {"data": [
        ev("20:11:48", "30:00", 30, "Halbzeitpause", 39, "Siebenmeter Tor", True, "Max Gast", False, 0, 1),
        ev("20:35:30", "05:30", 35, "2. Halbzeit", 39, "Siebenmeter Tor", True, "Max Gast", False, 99, 99),
        ev("20:27:22", "00:00", 30, "2. Halbzeit", 10000, "Startseite Teil", False, None, False, 0, 0),
        ev("21:00:00", "30:00", 60, "2. Halbzeit", 10001, "Spielende", False, None, False, 26, 28),
        ev("19:41:10", "01:10", 1, "1. Halbzeit", 15, "Tor", True, "Mika Schweikardt", True, 1, 0),
        ev("19:52:00", "12:00", 12, "1. Halbzeit", 13, "Zwei Minuten", False, "Mika Schweikardt", True, 5, 6),
        ev("18:27:51", "00:00", 0, "1. Halbzeit", 40, "Spieler aufgestellt", False, "Joshua Gantner", True, 0, 0),
    ]}


def _neu_lineups():
    def sp(nr, vor, nach, tore, sm_t, sm_v, zwei, start=True, tw=False):
        return {"player": {"first_name": vor, "last_name": nach}, "number": nr, "is_starter": start,
                "is_goalkeeper": tw, "goals": tore, "seven_meter_goals": sm_t, "seven_meter_attempts": sm_v,
                "two_minutes": zwei}
    return {"data": {
        "local": {"players": [sp(1, "Joshua", "Gantner", 0, 0, 0, 0, False, True), sp(9, "Mika", "Schweikardt", 7, 2, 3, 1)],
                  "staff": [{"player": {"first_name": "Trainer", "last_name": "Heim"}, "role": {"name": "TRAINER"}}], "team": {}},
        "visitor": {"players": [sp(4, "Max", "Gast", 9, 3, 3, 0)], "staff": [], "team": {}},
    }}


def test_handballnet_details(modul, monkeypatch):
    monkeypatch.setattr(modul, "_neu_api_get",
                        lambda pfad: _neu_events() if pfad.endswith("/events") else _neu_lineups())
    zeile = {"id": "n414837", "wettbewerb": "3. Liga Männer", "spieltag": "2. Spieltag",
             "anstoss": "2026-09-05T21:30:00+02:00", "heim": "TV BITTENFELD II", "gast": "TSV NEUHAUSEN/Filder",
             "heim_tore": 26, "gast_tore": 28, "ort": "Sporthalle", "status": "Ended"}
    d = modul._neu_details(zeile)
    k = d["kopf"]
    assert k["halle"] == "Sporthalle" and k["gast"]["sieger"] is True and k["heim"]["sieger"] is False
    assert k["halbzeit"] == (1, 1), "Halbzeit = mitgezaehlte Tore beim ersten Ereignis der 2. Halbzeit"
    arten = [(e["minute"], e["art"], e["stand"], e["seite"], e["spieler"]) for e in d["ticker"]]
    assert arten == [("1:10", "tor", "1:0", "heim", "Mika Schweikardt"),
                     ("12:00", "strafe", "1:0", "heim", "Mika Schweikardt"),
                     ("30:00", "tor", "1:1", "gast", "Max Gast"),
                     ("30:00", "abschnitt", "1:1", None, None),
                     ("35:30", "tor", "1:2", "gast", "Max Gast"),
                     ("60:00", "abschnitt", "1:2", None, None)], "chronologisch nach Zeitstempel, Stand mitgezaehlt"
    assert [e["text"] for e in d["ticker"] if e["art"] == "abschnitt"] == ["2. Halbzeit", "Spielende"]
    assert not any(e["text"] == "Spieler aufgestellt" for e in d["ticker"]), "Aufstellungsmeldungen sind kein Verlauf"
    assert [z["name"] for z in d["statistik"]["heim"]] == ["Joshua Gantner", "Mika Schweikardt"]
    assert d["statistik"]["heim"][1]["goalsScored:shots"] == 7
    assert d["statistik"]["heim"][1]["sevenMetreGoalsScored:sevenMetreShots"] == "2/3"
    assert d["aufstellung"]["heim"]["spieler"][0]["position"] == "Tor"
    assert d["aufstellung"]["heim"]["stab"] == [{"name": "Trainer Heim", "rolle": "TRAINER"}]
    assert d["quelle"] == "handball.net"


def test_handballnet_quelle_weg(modul, monkeypatch):
    monkeypatch.setattr(modul, "_neu_api_get", lambda pfad: None)
    zeile = {"id": "n1", "wettbewerb": None, "spieltag": None, "anstoss": "2026-09-05T21:30:00+02:00",
             "heim": "A", "gast": "B", "heim_tore": None, "gast_tore": None, "ort": None, "status": "Pre"}
    assert modul._neu_details(zeile) is None


# --- Cache und Seite -----------------------------------------------------------------

def test_seite_zeigt_tafel_ticker_statistik_aufstellung(client, tvb, modul, monkeypatch):
    sr, _ = _sr_get_fake(_sr_basis(), _sr_pbp(), _sr_preview())
    monkeypatch.setattr(modul, "_sr_get", sr)
    seite = client.get(f"/a/tvb/{tvb['token']}/spiel/{SR}").get_data(as_text=True)
    assert "34:34" in seite and "Halbzeit 12:14" in seite and "3.546 Zuschauer" in seite
    assert "Barclays Arena" in seite and "1. Handball-Bundesliga" in seite
    assert "Spielverlauf" in seite and "Tor aus dem Rückraum" in seite and "42:05" in seite
    assert "Statistik" in seite and "Kai Häfner" in seite and "8/10" in seite and "27:44" in seite
    assert "Aufstellung" in seite and "Bankspieler" in seite and "Marvin Cesnik" in seite
    assert "Beendet" in seite
    assert "images.dc.connect.sportradar.com" not in seite
    assert 'class="sd-team gast tvb"' in seite, "der TVB in der Kontrastfarbe"


def test_kommende_seite_zeigt_spielinfo_ohne_statistik(client, tvb, modul, monkeypatch):
    sr, _ = _sr_get_fake(_sr_basis(status="SCHEDULED", tore=(None, None), statistik=False), None, {"data": {"preview": {"persons": {}}}})
    monkeypatch.setattr(modul, "_sr_get", sr)
    seite = client.get(f"/a/tvb/{tvb['token']}/spiel/srf1adac8a-79f2-11f1-be57-55a849a4570e").get_data(as_text=True)
    assert "Spielinfo" in seite and "Terminiert" in seite
    assert "Statistik</h2>" not in seite and "Spielverlauf" not in seite
    # Die Namen kommen aus der Quelle (hier die Rohdaten des Testhelfers),
    # nicht aus der eigenen Zeile - die Quelle ist die frischere.
    assert "TVB Stuttgart" in seite and "Barclays Arena" in seite


def test_zweiter_aufruf_kommt_aus_dem_cache(client, tvb, modul, monkeypatch):
    sr, aufrufe = _sr_get_fake(_sr_basis(), _sr_pbp(), _sr_preview())
    monkeypatch.setattr(modul, "_sr_get", sr)
    client.get(f"/a/tvb/{tvb['token']}/spiel/{SR}")
    client.get(f"/a/tvb/{tvb['token']}/spiel/{SR}")
    assert len(aufrufe) == 3, "beendet: ein Tag Cache"
    zeile = tvb["v"].execute("SELECT daten FROM tvb_spiel_details WHERE id=?", (SR,)).fetchone()
    assert json.loads(zeile["daten"])["kopf"]["halbzeit"] == [12, 14]


def test_quelle_weg_zeigt_alten_stand_oder_die_eigene_zeile(client, tvb, modul, monkeypatch):
    monkeypatch.setattr(modul, "_sr_get", lambda pfad, embed=248: None)
    seite = client.get(f"/a/tvb/{tvb['token']}/spiel/{SR}").get_data(as_text=True)
    assert "34:34" in seite and "Handball Club Hamburg" in seite
    assert "nicht abrufbar" in seite
    tvb["v"].execute("INSERT INTO tvb_spiel_details(id, daten, aktualisiert_am) VALUES (?, ?, datetime('now', '-3 days'))",
                     (SR, json.dumps({"quelle": "Sportradar", "kopf": {"wettbewerb": "Alt", "spieltag": None, "anstoss": "2026-09-02T19:00:00+02:00",
                                      "halle": "Alte Halle", "zuschauer": None, "status": "Ended",
                                      "heim": {"name": "Handball Club Hamburg", "tore": 34, "sieger": False},
                                      "gast": {"name": "TVB Stuttgart", "tore": 34, "sieger": False}, "halbzeit": [12, 14]},
                                      "ticker": [], "statistik": {}, "aufstellung": {}, "schiedsrichter": []})))
    tvb["v"].commit()
    seite = client.get(f"/a/tvb/{tvb['token']}/spiel/{SR}").get_data(as_text=True)
    assert "Alte Halle" in seite and "nicht erreichbar" in seite


def test_handballnet_seite(client, tvb, modul, monkeypatch):
    monkeypatch.setattr(modul, "_neu_api_get",
                        lambda pfad: _neu_events() if pfad.endswith("/events") else _neu_lineups())
    seite = client.get(f"/a/tvb/{tvb['token']}/spiel/n414837").get_data(as_text=True)
    assert "26:28" in seite and "Halbzeit 1:1" in seite and "Mika Schweikardt" in seite
    assert "handball.net" in seite
    assert "?team=87353" in seite, "Zurueck fuehrt zur richtigen Mannschaft"


def test_unbekannte_und_kaputte_kennungen(client, tvb, modul, monkeypatch):
    aufrufe = []
    monkeypatch.setattr(modul, "_sr_get", lambda pfad, embed=248: aufrufe.append(pfad))
    monkeypatch.setattr(modul, "_neu_api_get", lambda pfad: aufrufe.append(pfad))
    for sid in ("srunbekannt", "n../x", "x1", "sr" + "0" * 36, "n999999999"):
        assert client.get(f"/a/tvb/{tvb['token']}/spiel/{sid}").status_code == 404, sid
    assert aufrufe == []


def test_ohne_grant_403(client, tvb):
    assert client.get(f"/a/tvb/falsch/spiel/{SR}").status_code == 403


def test_uebersicht_verlinkt_jedes_spiel(client, tvb, modul, monkeypatch):
    # Quelle erreichbar, aber leer - sonst zeigt die Seite "nicht abrufbar"
    # statt der gespeicherten Spiele.
    monkeypatch.setattr(modul, "_sr_get", lambda pfad, embed=248: {"data": {"fixtures": [], "standings": []}})
    monkeypatch.setattr(modul, "_neu_api_get", lambda *a, **k: None)
    seite = client.get(f"/a/tvb/{tvb['token']}/").get_data(as_text=True)
    assert f'href="/a/tvb/{tvb["token"]}/spiel/{SR}"' in seite
    assert 'href="/a/tvb/' + tvb["token"] + '/spiel/srf1adac8a-79f2-11f1-be57-55a849a4570e"' in seite
