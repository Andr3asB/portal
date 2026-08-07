"""Wunsch #143: Barcode vom Foto in die Einkaufsliste.

Schwerpunkte:
  * Der Code landet in einer URL – ein "Barcode", der keine reine Ziffernfolge
    ist, darf die Abfrage nicht verbiegen können.
  * Die KI-Kategorie muss eine der VORHANDENEN Kategorien sein; ein frei
    erfundener Name wäre wertlos (er passt zu keiner Zeile in der Datenbank)
    und würde stillschweigend zu einer falschen Einsortierung führen.
  * Fällt die Produktdatenbank oder die KI aus, darf die Erfassung nicht
    komplett scheitern – der Nutzer soll den Rest von Hand ergänzen können.
"""
import importlib
import io
import json

import pytest


@pytest.fixture()
def modul(app):
    return importlib.import_module("teile.10_einkauf")


@pytest.fixture()
def ek_token(admin):
    return admin["tokens"]["einkauf"]


# --- Der Code geht in eine URL ---------------------------------------------

def test_nur_ziffern_werden_akzeptiert(modul):
    gueltig = ["4008400401621", "12345678", "123456789012"]
    for code in gueltig:
        assert modul._NUR_ZIFFERN.match(code), code


def test_alles_andere_wird_abgelehnt(modul):
    """Der Code wird in die Adresse der Produktabfrage eingesetzt. Ohne diese
    Prüfung könnte ein präparierter Code den Pfad verlassen."""
    boese = [
        "../../etc/passwd",
        "4008400401621/../../admin",
        "4008400401621?fields=all",
        "40084 00401621",
        "4008400401621\n",
        "javascript:alert(1)",
        "",
        "123",              # zu kurz für einen Produktcode
        "123456789012345",  # zu lang
    ]
    for code in boese:
        assert not modul._NUR_ZIFFERN.match(code), code


def test_produktabfrage_lehnt_unsauberen_code_ab(app, modul):
    """Zweite Sicherung an der Funktion selbst, nicht nur am Regex: Wer sie
    künftig von anderer Stelle aufruft, ist ebenfalls geschützt."""
    with app.app_context():
        assert modul._produkt_zu_barcode("../boese") is None
        assert modul._produkt_zu_barcode("") is None


# --- Produktabfrage --------------------------------------------------------

def _falsche_antwort(nutzlast):
    class Antwort:
        def read(self):
            return json.dumps(nutzlast).encode()
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
    return lambda *a, **kw: Antwort()


def test_produkt_wird_uebernommen(app, modul, monkeypatch):
    monkeypatch.setattr(modul.urllib.request, "urlopen", _falsche_antwort({
        "status": 1,
        "product": {"product_name_de": "Nutella", "brands": "Ferrero, Nutella",
                    "quantity": "750g"},
    }))
    with app.app_context():
        p = modul._produkt_zu_barcode("4008400401621")
    assert p["name"] == "Nutella"
    assert p["marke"] == "Ferrero"      # nur die erste Marke, nicht die Liste
    assert p["menge"] == "750g"


def test_produkt_ohne_namen_gilt_als_nicht_gefunden(app, modul, monkeypatch):
    """Ein Datensatz ohne Namen nützt nichts - dann lieber ehrlich 'nicht
    gefunden' melden, statt ein leeres Feld vorzublenden."""
    monkeypatch.setattr(modul.urllib.request, "urlopen", _falsche_antwort({
        "status": 1, "product": {"brands": "Irgendwas"},
    }))
    with app.app_context():
        assert modul._produkt_zu_barcode("4008400401621") is None


def test_unbekannter_code_ist_kein_fehler(app, modul, monkeypatch):
    """Open Food Facts antwortet auf unbekannte Codes mit HTTP 404. Das ist
    der Normalfall bei Nicht-Lebensmitteln und darf nicht als Absturz
    durchschlagen."""
    def wirft_404(*a, **kw):
        raise modul.urllib.error.HTTPError("u", 404, "Not Found", {}, None)
    monkeypatch.setattr(modul.urllib.request, "urlopen", wirft_404)
    with app.app_context():
        assert modul._produkt_zu_barcode("4008400401621") is None


# --- KI-Kategorie ----------------------------------------------------------

def test_ki_kategorie_muss_eine_vorhandene_sein(app, modul, monkeypatch):
    monkeypatch.setattr(modul, "ki_anfrage", lambda *a, **kw: "Kühlregal")
    with app.app_context():
        from teile.kern import get_db
        db = get_db()
        kategorien = modul._kategorien_aktiv(db)
        kid = modul._kategorie_per_ki(1, {"name": "Butter", "marke": ""}, kategorien)
        erwartet = [k["id"] for k in kategorien if k["name"] == "Kühlregal"]
    assert kid == erwartet[0]


def test_erfundene_kategorie_wird_verworfen(app, modul, monkeypatch):
    """Die KI könnte etwas antworten, das es nicht gibt. Dann lieber keine
    Kategorie (der Aufrufer setzt 'Sonstiges') als eine falsche ID."""
    monkeypatch.setattr(modul, "ki_anfrage", lambda *a, **kw: "Weltraumnahrung")
    with app.app_context():
        from teile.kern import get_db
        kategorien = modul._kategorien_aktiv(get_db())
        assert modul._kategorie_per_ki(1, {"name": "X", "marke": ""}, kategorien) is None


def test_geschwaetzige_antwort_wird_toleriert(app, modul, monkeypatch):
    """Modelle antworten gern mit Anführungszeichen oder Leerzeichen drumherum."""
    monkeypatch.setattr(modul, "ki_anfrage", lambda *a, **kw: '  "Kühlregal"  ')
    with app.app_context():
        from teile.kern import get_db
        kategorien = modul._kategorien_aktiv(get_db())
        assert modul._kategorie_per_ki(1, {"name": "X", "marke": ""}, kategorien) is not None


# --- Der Endpunkt ----------------------------------------------------------

def test_ohne_foto_400(client, ek_token):
    antwort = client.post(f"/a/einkauf/{ek_token}/barcode")
    assert antwort.status_code == 400


def test_falscher_dateityp_wird_abgelehnt(client, ek_token):
    antwort = client.post(f"/a/einkauf/{ek_token}/barcode", data={
        "foto": (io.BytesIO(b"kein bild"), "liste.pdf")})
    assert antwort.status_code == 400
    assert not antwort.get_json()["ok"]


def test_ohne_zugang_kein_zutritt(client):
    antwort = client.post("/a/einkauf/gibtesnicht/barcode")
    assert antwort.status_code == 403


# --- Echtes Dekodieren -----------------------------------------------------

def _ean13_bild(code12: str) -> bytes:
    """Erzeugt ein echtes EAN-13-Bild. `python-barcode` ist nur hier nötig -
    im Betrieb wird gelesen, nicht erzeugt."""
    barcode = pytest.importorskip("barcode", reason="python-barcode nur für diesen Test")
    from barcode.writer import ImageWriter
    puffer = io.BytesIO()
    barcode.get("ean13", code12, writer=ImageWriter()).write(puffer)
    return puffer.getvalue()


def test_echter_barcode_wird_erkannt(modul):
    """Der Kern des Wunsches: aus einem Foto muss die Ziffernfolge herausfallen."""
    pytest.importorskip("zxingcpp")
    bild = _ean13_bild("400840040162")          # Prüfziffer rechnet die Bibliothek
    assert modul._barcode_aus_bild(bild) == "4008400401621"


def test_bild_ohne_barcode_gibt_none(modul):
    pytest.importorskip("zxingcpp")
    from PIL import Image
    puffer = io.BytesIO()
    Image.new("RGB", (300, 200), "white").save(puffer, format="PNG")
    assert modul._barcode_aus_bild(puffer.getvalue()) is None
