"""Wunsch #252: lecker.de liefert gzip, ohne dass jemand danach gefragt hat.

Der Import schickt bewusst kein Accept-Encoding - trotzdem antwortet
lecker.de (bzw. dessen CDN) seit 09/2026 mit `Content-Encoding: gzip`.
urllib entpackt nichts von selbst: Der JSON-LD-Parser bekam Binärbrei,
der Nutzer sah „kein Rezept erkannt", obwohl die Seite ein sauberes
schema.org/Recipe trägt (nachgemessen: Block 7 der Live-Seite, 20 Zutaten).

Der Fix ist `_entpacken()` in `_seite_abrufen` - inklusive des zweiten
Größen-Checks NACH dem Entpacken, denn das Lese-Limit zählt nur die
komprimierten Bytes (Zip-Bombe).
"""
import gzip
import zlib

import pytest


@pytest.fixture()
def rezepte(app):
    # Der Alias aus teile/__init__.py liegt in sys.modules, haengt aber
    # nicht als Attribut am Paket - `import teile.rezepte` scheitert daran.
    import sys
    return sys.modules["teile.rezepte"]


class _FakeAntwort:
    def __init__(self, body: bytes, encoding=None, status=200):
        self.status = status
        self._body = body
        self._encoding = encoding

    class _Kopf(dict):
        def get_content_charset(self):
            return "utf-8"

    @property
    def headers(self):
        k = self._Kopf()
        if self._encoding:
            k["Content-Encoding"] = self._encoding
        return k

    def read(self, n=-1):
        return self._body[:n] if n and n > 0 else self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_entpacken_gzip_und_deflate(rezepte):
    assert rezepte._entpacken(gzip.compress(b"<html>Rezept</html>"), "gzip") == b"<html>Rezept</html>"
    assert rezepte._entpacken(zlib.compress(b"abc"), "deflate") == b"abc"
    # "raw deflate" ohne zlib-Kopf - schicken manche Server so.
    roh = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    assert rezepte._entpacken(roh.compress(b"abc") + roh.flush(), "deflate") == b"abc"
    assert rezepte._entpacken(b"unveraendert", None) == b"unveraendert"
    assert rezepte._entpacken(b"unveraendert", "identity") == b"unveraendert"


def test_unbekannte_komprimierung_ist_ein_klarer_fehler(rezepte):
    """Lieber eine Meldung als stiller Binärbrei - genau der Zustand, den
    dieser Wunsch gemeldet hat."""
    with pytest.raises(ValueError):
        rezepte._entpacken(b"\x00\x01", "br")
    with pytest.raises(ValueError):
        rezepte._entpacken(b"kein gzip", "gzip")


def test_seite_abrufen_entpackt_erzwungenes_gzip(rezepte, monkeypatch):
    """Der Kern von #252 im Zusammenspiel: gzip-Antwort ohne Anfrage ->
    lesbares HTML samt erkennbarem Rezept."""
    html = ('<html><script type="application/ld+json">'
            '{"@type": "Recipe", "name": "Gnocchi", "recipeIngredient": ["Ricotta"],'
            ' "recipeInstructions": "Alles verkneten."}'
            "</script></html>")
    monkeypatch.setattr(rezepte, "_einmal_abrufen",
                        lambda url: _FakeAntwort(gzip.compress(html.encode()), "gzip"))
    text = rezepte._seite_abrufen("https://example.org/rezept")
    rezept = rezepte._rezept_aus_jsonld(text)
    assert rezept and rezept["name"] == "Gnocchi"
    assert rezept["zutaten"] == ["Ricotta"]


def test_zip_bombe_wird_abgewiesen(rezepte, monkeypatch):
    """1 GB Nullen komprimieren auf ~1 MB - das Lese-Limit sieht nur die
    komprimierten Bytes, der zweite Check nach dem Entpacken muss greifen."""
    bombe = gzip.compress(b"\x00" * (rezepte._MAX_FETCH_BYTES + 100))
    assert len(bombe) <= rezepte._MAX_FETCH_BYTES
    monkeypatch.setattr(rezepte, "_einmal_abrufen",
                        lambda url: _FakeAntwort(bombe, "gzip"))
    with pytest.raises(ValueError, match="zu groß"):
        rezepte._seite_abrufen("https://example.org/rezept")
