"""Wunsch #285 (Sicherheitsaudit 16.09.2026, Befund N-06): Log-Injection über
`request.path`, Zugangstoken im Anwendungs-Log.

Gunicorn dekodiert `%0a` im Pfad zu einem echten Zeilenumbruch, Werkzeug
reicht ihn durch, und der CSRF-Hook in 20_csrf.py läuft auch für Pfade, die
es gar nicht gibt. Ein unauthentifiziertes POST auf `/x%0aCSP-Verstoss:…`
erzeugte im Container-Log eine zweite, gefälschte Zeile – dasselbe Muster,
das Wunsch #205 am CSP-Endpunkt bereits geschlossen hatte, eine Datei
weiter. Und auf Token-Pfaden stand der Token ungekürzt im Log: der
Access-Logger (glogging_redact.py) kürzt nur seine eigenen Zeilen.

Die Regel liegt jetzt einmal in `redaktion.py` und wird von beiden Loggern
benutzt. Getestet wird nicht nur die Funktion, sondern der Weg durch den
echten Request-Hook mit abgehörtem Logger.
"""
import logging

TOKEN = "AbCdEfGhIjKlMnOpQrStUvWx"


def test_log_sicher_kuerzt_token_und_entfernt_zeilenumbrueche():
    from teile.kern import log_sicher, token_kuerzen
    assert token_kuerzen(f"/a/todo/{TOKEN}/status/1") == "/a/todo/<redacted>/status/1"
    assert token_kuerzen(f"/p/{TOKEN}") == "/p/<redacted>"
    assert token_kuerzen("/a/todo/status/1") == "/a/todo/status/1"
    text = log_sicher(f"/a/todo/{TOKEN}/x\nCSP-Verstoss: gefaelscht\r\n ende", 200)
    assert "\n" not in text and "\r" not in text and " " not in text
    assert TOKEN not in text and "<redacted>" in text
    assert log_sicher(None) == "?"
    assert len(log_sicher("x" * 500, 60)) == 60


def test_access_logger_benutzt_dieselbe_regel():
    """gunicorn lässt sich unter Windows nicht importieren (fcntl) - deshalb
    der Quelltext: der Access-Logger muss die Regel aus redaktion.py holen,
    nicht eine eigene Kopie halten, sonst laufen beide wieder auseinander."""
    import pathlib
    quelle = (pathlib.Path(__file__).resolve().parents[1] / "src" / "glogging_redact.py"
              ).read_text(encoding="utf-8")
    assert "from redaktion import token_kuerzen" in quelle
    assert "token_kuerzen(val)" in quelle
    assert "re.compile" not in quelle, "eigene Regex im Access-Logger - Duplikat der Regel"
    from redaktion import token_kuerzen
    assert token_kuerzen(f"GET /a/einkauf/{TOKEN}/ HTTP/1.1") == "GET /a/einkauf/<redacted>/ HTTP/1.1"


def test_csrf_verdacht_landet_als_eine_zeile_ohne_token_im_log(app, client, monkeypatch, caplog):
    monkeypatch.setitem(app.config, "CSRF_MODUS", "scharf")
    app.logger.propagate = True
    with caplog.at_level(logging.WARNING):
        # Der Zeilenumbruch sitzt im PFAD - Header mit Umbruch weist schon
        # Werkzeugs Test-Client ab, und Gunicorn tut es im Betrieb ebenso.
        r = client.post(f"/a/todo/{TOKEN}/status/1%0aCSP-Verstoss:%20gefaelscht",
                        data={"status": "1"},
                        headers={"User-Agent": "Test-UA"})
    assert r.status_code == 403
    zeilen = [rec.getMessage() for rec in caplog.records if "CSRF-Verdacht" in rec.getMessage()]
    assert zeilen, "kein CSRF-Verdacht protokolliert"
    for zeile in zeilen:
        assert "\n" not in zeile, zeile
        assert TOKEN not in zeile, "Zugangstoken im Anwendungs-Log"
        assert "<redacted>" in zeile
        assert "CSP-Verstoss: gefaelscht" in zeile   # als Text in DERSELBEN Zeile, nicht als eigene


def test_csp_bericht_kuerzt_token_in_document_uri(app, client, caplog):
    app.logger.propagate = True
    with caplog.at_level(logging.WARNING):
        r = client.post("/csp-bericht", json={"csp-report": {
            "blocked-uri": "inline",
            "document-uri": f"https://portal.16schwaben.de/p/{TOKEN}",
            "line-number": 3, "violated-directive": "script-src"}})
    assert r.status_code == 204
    zeilen = [rec.getMessage() for rec in caplog.records if "CSP-Verstoss" in rec.getMessage()]
    assert zeilen and all(TOKEN not in z and "<redacted>" in z for z in zeilen)
