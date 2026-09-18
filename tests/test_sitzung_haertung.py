"""Wunsch #293 (Sicherheitsaudit 16.09.2026, Befund N-15), erster Teil:
Sitzungen mit Ablauf, Obergrenze, nur für Browser - und Rückfrage, bevor ein
fremder Link von einer fremden Seite aus das Gerät übernimmt.

Vorher: `ablauf` immer NULL (jede Zeile ein nie ablaufender Zugang), keine
Obergrenze je Nutzer, und jeder Aufruf mit Pfad-Token bekam ein Cookie - auch
`curl`. So entstanden am 08.08.2026 die 808 Sitzungen. Und ein Klick auf
einen fremden Zugangslink aus einem Chat übernahm das Gerät ohne Rückfrage
(Login-CSRF innerhalb der Familie).
"""
import pytest


@pytest.fixture()
def an(app):
    vorher = {k: app.config.get(k) for k in ("SITZUNG_AUSSTELLEN", "SITZUNG_KONSUMIEREN")}
    app.config["SITZUNG_AUSSTELLEN"] = "1"
    app.config["SITZUNG_KONSUMIEREN"] = "1"
    yield
    for k, v in vorher.items():
        app.config[k] = v


def _sitzungen(db, uid):
    return db["verbindung"].execute(
        "SELECT * FROM sitzungen WHERE user_id=? ORDER BY id", (uid,)).fetchall()


def _cookie(antwort):
    kopf = antwort.headers.get("Set-Cookie", "")
    return kopf.split("portal_sitzung=")[1].split(";")[0] if "portal_sitzung=" in kopf else None


def test_neue_sitzung_hat_einen_ablauf(client, db, admin, an):
    client.get(f"/p/{admin['tokens']['home']}")
    (zeile,) = _sitzungen(db, admin["id"])
    assert zeile["ablauf"] is not None
    tage = db["verbindung"].execute(
        "SELECT julianday(?) - julianday('now')", (zeile["ablauf"],)).fetchone()[0]
    assert 364 < tage <= 366


def test_abgelaufene_sitzungen_werden_geraeumt(client, db, admin, kind, an):
    v = db["verbindung"]
    v.execute("INSERT INTO sitzungen(user_id, kennung_lookup, ablauf) VALUES(?, 'alt', datetime('now', '-1 day'))",
              (kind["id"],))
    v.execute("INSERT INTO sitzungen(user_id, kennung_lookup, ablauf) VALUES(?, 'kiosk', NULL)",
              (kind["id"],))
    v.commit()
    client.get(f"/p/{admin['tokens']['home']}")          # legt eine neue an -> raeumt
    kennungen = {z["kennung_lookup"] for z in _sitzungen(db, kind["id"])}
    assert "alt" not in kennungen, "abgelaufene Sitzung blieb liegen"
    assert "kiosk" in kennungen, "Sitzungen ohne Ablauf (Kiosk) bleiben"


def test_hoechstens_zwanzig_sitzungen_je_nutzer(client, db, admin, an):
    v = db["verbindung"]
    for i in range(20):
        v.execute("INSERT INTO sitzungen(user_id, kennung_lookup, gesehen) "
                  "VALUES(?, ?, datetime('now', ?))", (admin["id"], f"s{i}", f"-{30 - i} days"))
    v.commit()
    client.get(f"/p/{admin['tokens']['home']}", headers={"Cookie": ""})
    zeilen = _sitzungen(db, admin["id"])
    assert len(zeilen) == 20
    kennungen = {z["kennung_lookup"] for z in zeilen}
    assert "s0" not in kennungen, "die am laengsten unbenutzte muss fallen"
    assert "s19" in kennungen


def test_curl_bekommt_keine_sitzung(client, db, admin, an):
    """Der Fall vom 08.08.2026: Pruef-Aufrufe ohne Browser."""
    antwort = client.get(f"/p/{admin['tokens']['home']}", headers={"Accept": "*/*"})
    assert antwort.status_code == 200
    assert _cookie(antwort) is None
    assert _sitzungen(db, admin["id"]) == []


def test_browser_navigation_bekommt_eine_sitzung(client, db, admin, an):
    # Sec-Fetch-Mode allein reicht (Accept egal) ...
    a = client.get(f"/p/{admin['tokens']['home']}",
                   headers={"Accept": "*/*", "Sec-Fetch-Mode": "navigate"})
    assert _cookie(a)
    # ... und Accept text/html allein auch (aeltere Safari ohne Sec-Fetch-*).
    # Der Test-Client haelt das Cookie von oben - weg damit, sonst passt die
    # Sitzung schon und es gibt zu Recht kein zweites Cookie.
    client.delete_cookie("portal_sitzung")
    b = client.get(f"/p/{admin['tokens']['home']}", headers={"Accept": "text/html"})
    assert _cookie(b)


def test_cross_site_link_eines_anderen_fragt_nach(client, db, admin, kind, an):
    """Andi ist angemeldet, ein Klick im Chat oeffnet den Link des Kindes."""
    cookie = _cookie(client.get(f"/p/{admin['tokens']['home']}"))
    antwort = client.get(f"/p/{kind['tokens']['home']}",
                         headers={"Cookie": f"portal_sitzung={cookie}",
                                  "Sec-Fetch-Site": "cross-site"})
    assert antwort.status_code == 200
    seite = antwort.get_data(as_text=True)
    assert "als TestKind anmelden?" in seite and "TestAdmin" in seite
    assert _cookie(antwort) is None, "die Rueckfrage darf das Cookie nicht schon tauschen"
    assert 'name="token"' in seite and 'action="/sitzung/uebernehmen"' in seite
    # Andi ist weiterhin angemeldet
    assert len(_sitzungen(db, admin["id"])) == 1 and _sitzungen(db, kind["id"]) == []


@pytest.mark.parametrize("site", ["none", "same-origin", None])
def test_qr_scan_adresszeile_und_eigene_links_uebernehmen_direkt(client, db, admin, kind, an, site):
    cookie = _cookie(client.get(f"/p/{admin['tokens']['home']}"))
    headers = {"Cookie": f"portal_sitzung={cookie}"}
    if site:
        headers["Sec-Fetch-Site"] = site
    antwort = client.get(f"/p/{kind['tokens']['home']}", headers=headers)
    assert antwort.status_code == 200
    assert "anmelden?" not in antwort.get_data(as_text=True)
    assert _cookie(antwort), "geteiltes iPad: der geoeffnete Link uebernimmt"
    assert _sitzungen(db, admin["id"]) == [] and len(_sitzungen(db, kind["id"])) == 1


def test_eigener_link_cross_site_fragt_nicht(client, db, admin, an):
    cookie = _cookie(client.get(f"/p/{admin['tokens']['home']}"))
    antwort = client.get(f"/p/{admin['tokens']['home']}",
                         headers={"Cookie": f"portal_sitzung={cookie}", "Sec-Fetch-Site": "cross-site"})
    assert "anmelden?" not in antwort.get_data(as_text=True)


def test_bestaetigung_tauscht_die_sitzung(client, db, admin, kind, an):
    cookie = _cookie(client.get(f"/p/{admin['tokens']['home']}"))
    antwort = client.post("/sitzung/uebernehmen",
                          data={"token": kind["tokens"]["home"], "ziel": "/start"},
                          headers={"Cookie": f"portal_sitzung={cookie}"})
    assert antwort.status_code == 303 and antwort.headers["Location"].endswith("/start")
    assert _cookie(antwort), "nach der Bestaetigung kommt das neue Cookie"
    assert _sitzungen(db, admin["id"]) == []
    assert len(_sitzungen(db, kind["id"])) == 1


def test_bestaetigung_prueft_token_und_ziel(client, db, admin, an):
    cookie = _cookie(client.get(f"/p/{admin['tokens']['home']}"))
    h = {"Cookie": f"portal_sitzung={cookie}"}
    assert client.post("/sitzung/uebernehmen", data={"token": "falsch", "ziel": "/start"}, headers=h).status_code == 403
    for ziel in ("https://evil.example/", "//evil.example", "/x\\y", "javascript:alert(1)"):
        r = client.post("/sitzung/uebernehmen", data={"token": admin["tokens"]["home"], "ziel": ziel}, headers=h)
        assert r.status_code == 400, ziel
    assert len(_sitzungen(db, admin["id"])) == 1, "nichts davon darf die Sitzung anfassen"
