"""Wunsch #294 (Sicherheitsaudit 16.09.2026, Befund N-16), zweiter Teil:
`Cache-Control: no-store` auf allem, was personalisiert ist.

HTML und JSON kamen ohne Cache-Header. Ohne Last-Modified/ETag cached der
HTTP-Cache zwar nicht heuristisch, aber Back/Forward-Cache und der
Erstbesuch mit Token-URL blieben im Browser; auf dem geteilten Gerät sah der
nächste Nutzer per Zurück-Taste Seiten des vorigen.

Statische Dateien behalten Flasks `no-cache` (sie sind nicht personalisiert
und die Gegenprobe, dass nichts Vorhandenes überschrieben wird).
"""


def test_html_seiten_kommen_mit_no_store(client, admin):
    antwort = client.get(f"/p/{admin['tokens']['home']}", follow_redirects=True)
    assert antwort.status_code == 200
    assert antwort.mimetype == "text/html"
    assert antwort.headers["Cache-Control"] == "no-store"
    assert client.get("/").headers["Cache-Control"] == "no-store"      # denied.html


def test_json_antworten_kommen_mit_no_store(client):
    antwort = client.get("/health")
    assert antwort.mimetype == "application/json"
    assert antwort.headers["Cache-Control"] == "no-store"


def test_statische_dateien_behalten_ihren_header(client):
    antwort = client.get("/static/sw.js")
    assert antwort.status_code == 200
    assert antwort.headers["Cache-Control"] != "no-store"
