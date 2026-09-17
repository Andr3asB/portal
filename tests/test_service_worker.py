"""Wunsch #286 (Sicherheitsaudit 16.09.2026, Befund N-07): Der Service-Worker-
Cache überlebte den Widerruf und cachte den Token-Erstbesuch.

`sw.js` legte jede erfolgreiche eigene GET-Seite in den Cache - auch den
Erstbesuch von `/p/<token>` (Token in der Adresse und im Body) und
Admin-Seiten. Geleert wurde nur beim Nutzerwechsel. Nach „Zugänge neu
erzeugen" antwortete das Netz mit 403, das ist nicht `ok`, der alte Eintrag
blieb liegen und war offline weiter lesbar - die Cache-Storage steht in den
DevTools im Klartext.

Ein Service Worker läuft in keinem Testlauf; diese Wächter lesen den
Quelltext und halten die drei Regeln fest, die still zurückfallen könnten.
"""
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
SW = (SRC / "static" / "sw.js").read_text(encoding="utf-8")
DENIED = (SRC / "teile" / "templates" / "denied.html").read_text(encoding="utf-8")


def _ohne_kommentare(js: str) -> str:
    return re.sub(r"//[^\n]*", "", js)


def test_cache_name_wurde_fuer_den_umbau_gewechselt():
    """Nur ein neuer Name räumt auf jedem Gerät weg, was schon unter /p/ liegt."""
    assert re.search(r"CACHE_NAME\s*=\s*'portal-cache-v3'", SW)


def test_seiten_unter_p_werden_nie_gecacht():
    code = _ohne_kommentare(SW)
    put = re.search(r"if\s*\((.*?)\)\s*\{[^}]*cache\.put", code, re.DOTALL)
    assert put, "cache.put ohne Bedingung"
    assert "!url.pathname.startsWith('/p/')" in put.group(1)


def test_widerruf_leert_den_cache():
    code = _ohne_kommentare(SW)
    treffer = re.search(r"req\.mode === 'navigate' && \(resp\.status === 401 \|\| resp\.status === 403\)\)\s*\{"
                        r"\s*caches\.delete\(CACHE_NAME\)", code)
    assert treffer, "401/403 auf eine Navigation muss den Cache löschen"


def test_nutzer_null_wird_wie_ein_wechsel_behandelt():
    """`d.id` allein wäre für 0 falsy - dann käme die Meldung von denied.html
    nie an, und genau die soll den Cache des vorigen Nutzers wegwerfen."""
    code = _ohne_kommentare(SW)
    assert "d.id !== undefined && d.id !== null" in code
    assert not re.search(r"d\.typ === 'nutzer' && d\.id\)", code)


def test_denied_seite_meldet_niemand_mit_nonce():
    assert "postMessage({ typ: 'nutzer', id: 0 })" in DENIED
    assert "<script{{ csp_nonce }}>" in DENIED, "ohne Nonce läuft das Skript unter CSP scharf nicht"
