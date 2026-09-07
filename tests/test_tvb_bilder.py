"""Wunsch #271: Spielerbilder im Kader und im Profil.

Die Bilder liegen auf Sportradars Bild-CDN. Regel #119: der Browser laedt
nichts von fremden Hosts. Also holt der Server das Bild einmal, legt es unter
DATA_DIR/tvb_bilder ab und liefert es von dort; nach einer Woche holt er es
neu. Ohne Bild-Adresse oder wenn das CDN nicht liefert, kommt ein SVG mit den
Initialen - ein Bild, das sicher da ist, statt eines kaputten Bildsymbols.

Die Bild-Adresse kommt aus der HPI-Antwort und geht in einen Fremdabruf -
deshalb die Allowlist auf genau einen Host.
"""
import importlib
import os
import time

import pytest

DC = "8a8c7344-3954-11ef-a3f0-a919af319ee5"
CDN = "https://images.dc.connect.sportradar.com/h1s44/abc?size=800&format=webp"
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 40


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
        v.execute("INSERT INTO tvb_kader(spieler_id, vorname, nachname, position, saison_name, dc_id, bild_url) "
                  "VALUES (1, 'Philipp', 'Meyer', 'Pivot', 'Opel HBL 2026/27', ?, ?)", (DC, CDN))
        v.execute("INSERT INTO tvb_kader(spieler_id, vorname, nachname, position, saison_name, dc_id, bild_url) "
                  "VALUES (2, 'Ohne', 'Bild', 'Pivot', 'Opel HBL 2026/27', '11111111-1111-1111-1111-111111111111', NULL)")
        v.commit()
    pfad = os.path.join(app.config["DATA_DIR"], "tvb_bilder", f"{DC}.webp")
    if os.path.exists(pfad):
        os.remove(pfad)
    return {"token": token, "v": v, "pfad": pfad}


def test_nur_der_erlaubte_host(modul):
    assert modul._bild_url_erlaubt(CDN) == CDN
    for boese in ("http://images.dc.connect.sportradar.com/x", "https://boese.example/x",
                  "https://images.dc.connect.sportradar.com.evil.example/x", "ftp://images.dc.connect.sportradar.com/x",
                  "", None, 42, "https://images.dc.connect.sportradar.com"):
        assert modul._bild_url_erlaubt(boese) is None, boese


def test_kader_speichert_nur_erlaubte_adressen(app, tvb, modul):
    with app.app_context():
        from teile.kern import get_db
        modul._kader_speichern(get_db(), "S", [
            {"id": 1, "firstname": "A", "lastname": "B", "position": "Pivot", "dc_id": DC, "image": CDN, "index": {}},
            {"id": 2, "firstname": "C", "lastname": "D", "position": "Pivot", "image": "https://boese.example/x.png", "index": {}},
        ])
    zeilen = {z["spieler_id"]: z["bild_url"] for z in tvb["v"].execute("SELECT spieler_id, bild_url FROM tvb_kader")}
    assert zeilen == {1: CDN, 2: None}


def test_bild_wird_einmal_geholt_und_dann_von_hier_geliefert(client, tvb, modul, monkeypatch):
    geholt = []

    def holen(url):
        geholt.append(url)
        return WEBP, "image/webp"
    monkeypatch.setattr(modul, "_bild_holen", holen)
    r = client.get(f"/a/tvb/{tvb['token']}/bild/{DC}")
    assert r.status_code == 200 and r.mimetype == "image/webp" and r.data == WEBP
    assert "max-age=86400" in r.headers.get("Cache-Control", "")
    r = client.get(f"/a/tvb/{tvb['token']}/bild/{DC}")
    assert r.status_code == 200
    assert geholt == [CDN], "der zweite Aufruf kommt aus dem Zwischenspeicher"
    assert os.path.exists(tvb["pfad"])


def test_altes_bild_wird_erneuert(client, tvb, modul, monkeypatch):
    os.makedirs(os.path.dirname(tvb["pfad"]), exist_ok=True)
    with open(tvb["pfad"], "wb") as f:
        f.write(b"alt")
    alt = time.time() - 8 * 86400
    os.utime(tvb["pfad"], (alt, alt))
    monkeypatch.setattr(modul, "_bild_holen", lambda url: (WEBP, "image/webp"))
    r = client.get(f"/a/tvb/{tvb['token']}/bild/{DC}")
    assert r.data == WEBP


def test_cdn_weg_liefert_initialen_oder_das_alte_bild(client, tvb, modul, monkeypatch):
    monkeypatch.setattr(modul, "_bild_holen", lambda url: None)
    r = client.get(f"/a/tvb/{tvb['token']}/bild/{DC}")
    assert r.status_code == 200 and r.mimetype == "image/svg+xml"
    assert ">PM<" in r.get_data(as_text=True), "Initialen von Philipp Meyer"
    # Liegt ein altes Bild da, ist es besser als Initialen.
    os.makedirs(os.path.dirname(tvb["pfad"]), exist_ok=True)
    with open(tvb["pfad"], "wb") as f:
        f.write(WEBP)
    alt = time.time() - 8 * 86400
    os.utime(tvb["pfad"], (alt, alt))
    r = client.get(f"/a/tvb/{tvb['token']}/bild/{DC}")
    assert r.mimetype == "image/webp" and r.data == WEBP


def test_spieler_ohne_adresse_bekommt_initialen_ohne_fremdabruf(client, tvb, modul, monkeypatch):
    aufrufe = []
    monkeypatch.setattr(modul, "_bild_holen", lambda url: aufrufe.append(url))
    r = client.get(f"/a/tvb/{tvb['token']}/bild/11111111-1111-1111-1111-111111111111")
    assert r.mimetype == "image/svg+xml" and ">OB<" in r.get_data(as_text=True)
    assert aufrufe == []


def test_bild_holen_prueft_typ_und_groesse(modul, monkeypatch):
    import io

    class Antwort(io.BytesIO):
        def __init__(self, daten, typ):
            super().__init__(daten)
            self.headers = {"Content-Type": typ}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    faelle = {"gut": (WEBP, "image/webp; charset=binary"), "text": (b"<html>", "text/html"),
              "gross": (b"x" * (modul._BILD_MAX_BYTES + 1), "image/webp")}
    for name, (daten, typ) in faelle.items():
        gesehen = {}

        def urlopen(req, timeout=None, _d=daten, _t=typ, _g=gesehen):
            _g["url"] = req.full_url
            return Antwort(_d, _t)
        monkeypatch.setattr(modul.urllib.request, "urlopen", urlopen)
        ergebnis = modul._bild_holen(CDN)
        if name == "gut":
            assert ergebnis == (WEBP, "image/webp")
            assert "size=400" in gesehen["url"] and "format=webp" in gesehen["url"]
        else:
            assert ergebnis is None, name


def test_unbekannte_kennungen_und_fehlender_grant(client, tvb, modul, monkeypatch):
    monkeypatch.setattr(modul, "_bild_holen", lambda url: (WEBP, "image/webp"))
    assert client.get(f"/a/tvb/{tvb['token']}/bild/../x").status_code == 404
    assert client.get(f"/a/tvb/{tvb['token']}/bild/99999999-9999-9999-9999-999999999999").status_code == 404
    assert client.get(f"/a/tvb/falsch/bild/{DC}").status_code == 403


def test_kader_und_profil_zeigen_das_bild_von_hier(client, tvb, modul, monkeypatch):
    monkeypatch.setattr(modul, "_kader_ist_frisch", lambda db: True)
    monkeypatch.setattr(modul, "_profil_html_holen", lambda dc: None)
    kader = client.get(f"/a/tvb/{tvb['token']}/kader").get_data(as_text=True)
    assert f'src="/a/tvb/{tvb["token"]}/bild/{DC}"' in kader
    assert 'loading="lazy"' in kader
    assert "images.dc.connect.sportradar.com" not in kader
    profil = client.get(f"/a/tvb/{tvb['token']}/kader/{DC}").get_data(as_text=True)
    assert f'class="sp-bild" src="/a/tvb/{tvb["token"]}/bild/{DC}"' in profil
    assert "images.dc.connect.sportradar.com" not in profil
