"""Wunsch #265: Spielerprofile - Steckbrief, Statistik und Laufbahn.

Es gibt keinen JSON-Endpunkt fuer Spieler (Sportradar-Embed: keiner, HPI:
nur der Index). Die Spielerseite der Liga liefert ihre Daten aber
serverseitig als devalue-Nutzlast mit - ein flaches Array, in dem Objekte
ihre Kinder ueber Indizes referenzieren. Der Parser hier ist das
Empfindliche daran; die Tests bauen die Nutzlast deshalb GENAU in diesem
Format nach (`_devalue_kodieren`), nicht als bequemes JSON.
"""
import importlib
import json

import pytest

DC = "8a8c7344-3954-11ef-a3f0-a919af319ee5"


@pytest.fixture()
def modul(app):
    return importlib.import_module("teile.18_tvb")


def _devalue_kodieren(wert):
    """Ein normales Python-Objekt in das flache devalue-Array der Nuxt-Seite."""
    arr = []

    def ablegen(w):
        idx = len(arr)
        arr.append(None)
        if isinstance(w, dict):
            arr[idx] = {k: ablegen(v) for k, v in w.items()}
        elif isinstance(w, list) and w and w[0] in ("Date", "Set", "Map"):
            # Sonderform von devalue: Marker UND Inhalt stehen woertlich
            # im Knoten, nicht als Indizes - so wie in der echten Seite.
            arr[idx] = [w[0], w[1]]
        elif isinstance(w, list):
            arr[idx] = [ablegen(v) for v in w]
        else:
            arr[idx] = w
        return idx

    ablegen(wert)
    return arr


def _spielerdaten(**abweichung):
    daten = {
        "context": {"currentTeamId": "team-tvb", "id": DC},
        "header": {"bib": "27", "playerGivenName": "Philipp", "playerFamilyName": "Meyer",
                   "playerFullName": "Philipp Meyer",
                   "photoURL": "https://images.dc.connect.sportradar.com/x?size=RAW",
                   "teamName": "TVB Stuttgart"},
        "overview": {"info": {"birthday": ["Date", "1997-03-25T00:00:00.000Z"], "age": 29,
                              "position": "P", "nationality": "DEU", "height": 200, "weight": 95}},
        "career": {
            "totals": [{"seasonCount": 4, "leagueName": "1. Handball-Bundesliga", "played": 100,
                        "goals": 92, "7mGoals": 0, "yellowCards": 8, "sinBins": 68, "redCards": 3}],
            "perTeam": [
                {"team": {"teamId": "team-tvb", "name": "TVB Stuttgart"},
                 "totals": {"played": 3, "goals": 1, "yellowCards": 1, "sinBins": 1, "redCards": 0},
                 "seasons": [{"seasonName": "Opel HBL 2026/27", "played": 2, "goals": 0},
                             {"seasonName": "DHB-Pokal 2026/27", "played": 1, "goals": 1}]},
                {"team": {"teamId": "team-eis", "name": "ThSV Eisenach"},
                 "totals": {"played": 142, "goals": 106},
                 "seasons": [{"seasonName": "DAIKIN HBL 2025/26", "played": 30, "goals": 33}]},
            ],
        },
    }
    daten.update(abweichung)
    return daten


def _seite(daten=None):
    """Die Nuxt-Seite: Fuellmaterial davor, die Nutzlast im Skript, danach.
    Die Sonderform ["Date", i] wird wie in der echten Seite eingebettet."""
    daten = daten or _spielerdaten()
    # ["Date", "..."] ist bereits eine Liste; nach dem Kodieren zeigt der
    # Eintrag ["Date", <index>] auf die Zeichenkette - genau wie im Original.
    arr = _devalue_kodieren({"data": {"seite": daten}, "state": {}})
    return ("<html><head></head><body><div>Fuellmaterial</div>"
            '<script type="application/json" data-nuxt-data="nuxt-app" data-ssr="true" id="__NUXT_DATA__">'
            + json.dumps(arr) + "</script></body></html>")


# --- Parser ------------------------------------------------------------------

def test_profil_wird_vollstaendig_gelesen(modul):
    p = modul._spieler_profil_aus_html(_seite())
    assert p["name"] == "Philipp Meyer" and p["nummer"] == "27"
    assert p["position"] == "Kreisläufer" and p["nation"] == "Deutschland"
    assert p["geburtstag"] == "1997-03-25" and p["alter"] == 29
    assert (p["groesse"], p["gewicht"]) == (200, 95)
    assert p["torwart"] is False
    assert p["ligen"][0]["liga"] == "1. Handball-Bundesliga"
    assert (p["ligen"][0]["spiele"], p["ligen"][0]["tore"], p["ligen"][0]["saisons"]) == (100, 92, 4)
    assert [s["verein"] for s in p["stationen"]] == ["TVB Stuttgart", "ThSV Eisenach"]
    assert p["stationen"][0]["aktuell"] is True and p["stationen"][1]["aktuell"] is False
    assert p["stationen"][0]["saisons"][1] == {
        "name": "DHB-Pokal 2026/27", "spiele": 1, "tore": 1, "siebenmeter": None,
        "gelb": None, "zeitstrafen": None, "rot": None, "paraden": None, "gegentore": None}
    assert p["stationen"][1]["gesamt"]["tore"] == 106


def test_unbekannte_codes_werden_nicht_geraten(modul):
    daten = _spielerdaten()
    daten["overview"]["info"]["position"] = "XY"
    daten["overview"]["info"]["nationality"] = "ZZZ"
    p = modul._spieler_profil_aus_html(_seite(daten))
    assert p["position"] == "XY" and p["nation"] == "ZZZ"


def test_torwart_wird_erkannt(modul):
    daten = _spielerdaten()
    daten["overview"]["info"]["position"] = "GK"
    p = modul._spieler_profil_aus_html(_seite(daten))
    assert p["torwart"] is True and p["position"] == "Tor"


def test_kaputte_oder_fremde_seiten_ergeben_none(modul):
    assert modul._spieler_profil_aus_html(None) is None
    assert modul._spieler_profil_aus_html("<html>ohne Nutzlast</html>") is None
    assert modul._spieler_profil_aus_html(
        '<script id="__NUXT_DATA__">kein json</script>') is None
    assert modul._spieler_profil_aus_html(
        '<script id="__NUXT_DATA__">[{"data":1},{"x":2},3]</script>') is None


def test_zyklen_in_der_nutzlast_kippen_den_parser_nicht(modul):
    daten = _spielerdaten()
    arr = _devalue_kodieren({"data": daten})
    # ein Selbstbezug: das Wurzelobjekt zeigt auf sich selbst
    arr[0]["schleife"] = 0
    html = '<script id="__NUXT_DATA__">' + json.dumps(arr) + "</script>"
    assert modul._spieler_profil_aus_html(html)["name"] == "Philipp Meyer"


# --- Cache und Route ---------------------------------------------------------------

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
        v.execute("""
            INSERT INTO tvb_kader(spieler_id, vorname, nachname, position, hpi_schnitt,
                                  hpi_letzter, hpi_trend, spieltage, aktionen, saison_name, dc_id)
            VALUES (8538, 'Philipp', 'Meyer', 'Pivot', 82.1, 82, 1, 2, 9, 'Opel HBL 2026/27', ?)
        """, (DC,))
        v.execute("""
            INSERT INTO tvb_kader(spieler_id, vorname, nachname, position, saison_name, dc_id)
            VALUES (9999, 'Ohne', 'Kennung', 'Pivot', 'Opel HBL 2026/27', NULL)
        """)
        v.commit()
    return {"token": token, "v": v}


def test_profilseite_zeigt_steckbrief_statistik_und_laufbahn(client, tvb, modul, monkeypatch):
    aufrufe = []
    monkeypatch.setattr(modul, "_profil_html_holen", lambda dc: aufrufe.append(dc) or _seite())
    seite = client.get(f"/a/tvb/{tvb['token']}/kader/{DC}").get_data(as_text=True)
    assert "Philipp Meyer" in seite and "Kreisläufer" in seite
    assert "25.03.1997" in seite and "Deutschland" in seite and "200 cm" in seite
    assert "1. Handball-Bundesliga" in seite
    assert "ThSV Eisenach" in seite and "DAIKIN HBL 2025/26" in seite
    assert "aktuell" in seite
    assert "82.1" in seite, "HPI-Werte aus dem Kader stehen mit auf der Seite"
    assert "images.dc.connect.sportradar.com" not in seite, "kein fremder Host im Frontend (#119)"
    assert 'href="/a/tvb/' in seite and "/kader\"" in seite, "Zurueck-Link zum Kader"
    assert aufrufe == [DC]


def test_zweiter_aufruf_kommt_aus_dem_cache(client, tvb, modul, monkeypatch):
    aufrufe = []
    monkeypatch.setattr(modul, "_profil_html_holen", lambda dc: aufrufe.append(dc) or _seite())
    client.get(f"/a/tvb/{tvb['token']}/kader/{DC}")
    client.get(f"/a/tvb/{tvb['token']}/kader/{DC}")
    assert aufrufe == [DC]
    zeile = tvb["v"].execute("SELECT daten FROM tvb_spieler_profile WHERE dc_id=?", (DC,)).fetchone()
    assert json.loads(zeile["daten"])["name"] == "Philipp Meyer"


def test_alter_cache_wird_erneuert(client, tvb, modul, monkeypatch):
    tvb["v"].execute("INSERT INTO tvb_spieler_profile(dc_id, daten, aktualisiert_am) "
                     "VALUES (?, ?, datetime('now', '-2 days'))",
                     (DC, json.dumps({"name": "Alt", "ligen": [], "stationen": []})))
    tvb["v"].commit()
    monkeypatch.setattr(modul, "_profil_html_holen", lambda dc: _seite())
    seite = client.get(f"/a/tvb/{tvb['token']}/kader/{DC}").get_data(as_text=True)
    assert "Philipp Meyer" in seite and ">Alt<" not in seite


def test_quelle_weg_zeigt_alten_stand_mit_hinweis(client, tvb, modul, monkeypatch):
    tvb["v"].execute("INSERT INTO tvb_spieler_profile(dc_id, daten, aktualisiert_am) "
                     "VALUES (?, ?, datetime('now', '-2 days'))",
                     (DC, json.dumps({"name": "Alter Stand", "ligen": [], "stationen": []})))
    tvb["v"].commit()
    monkeypatch.setattr(modul, "_profil_html_holen", lambda dc: None)
    seite = client.get(f"/a/tvb/{tvb['token']}/kader/{DC}").get_data(as_text=True)
    assert "Alter Stand" in seite
    assert "nicht erreichbar" in seite


def test_quelle_weg_ohne_cache_ist_freundlich(client, tvb, modul, monkeypatch):
    monkeypatch.setattr(modul, "_profil_html_holen", lambda dc: None)
    r = client.get(f"/a/tvb/{tvb['token']}/kader/{DC}")
    assert r.status_code == 200
    seite = r.get_data(as_text=True)
    assert "nicht abrufbar" in seite and "Philipp Meyer" in seite


def test_nur_eine_uuid_geht_in_den_fremdpfad(client, tvb, modul, monkeypatch):
    aufrufe = []
    monkeypatch.setattr(modul, "_profil_html_holen", lambda dc: aufrufe.append(dc) or None)
    for boese in ("..", "8a8c7344", "8a8c7344-3954-11ef-a3f0-a919af319ee5/x", "<script>"):
        r = client.get(f"/a/tvb/{tvb['token']}/kader/{boese}")
        assert r.status_code == 404, boese
    assert aufrufe == []


def test_ohne_grant_403(client, tvb):
    assert client.get(f"/a/tvb/falsch/kader/{DC}").status_code == 403


def test_kader_verlinkt_nur_spieler_mit_kennung(client, tvb, modul, monkeypatch):
    monkeypatch.setattr(modul, "_kader_ist_frisch", lambda db: True)
    seite = client.get(f"/a/tvb/{tvb['token']}/kader").get_data(as_text=True)
    assert f'href="/a/tvb/{tvb["token"]}/kader/{DC}"' in seite
    assert "Kennung" in seite
    assert seite.count('class="knopf kader-link"') == 1, "der Spieler ohne dc_id bekommt keinen Link"


def test_kader_speichert_die_kennung_nur_wenn_sie_echt_ist(app, tvb, modul):
    with app.app_context():
        from teile.kern import get_db
        modul._kader_speichern(get_db(), "Opel HBL 2026/27", [
            {"id": 1, "firstname": "A", "lastname": "B", "position": "Pivot", "dc_id": DC, "index": {}},
            {"id": 2, "firstname": "C", "lastname": "D", "position": "Pivot", "dc_id": "../x", "index": {}},
            {"id": 3, "firstname": "E", "lastname": "F", "position": "Pivot", "index": {}},
        ])
    zeilen = {z["spieler_id"]: z["dc_id"] for z in tvb["v"].execute("SELECT spieler_id, dc_id FROM tvb_kader")}
    assert zeilen == {1: DC, 2: None, 3: None}
