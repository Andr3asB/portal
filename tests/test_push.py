"""Push-Benachrichtigungen.

Anlass: Beim Prüfen von S6-06 (Wunsch #140, Stufe 6) stellte sich heraus, dass
Push an Windows/Edge **seit jeher** still fehlschlug. `pywebpush` schickt ohne
`ttl`-Argument TTL 0, und Microsofts WNS lehnt das mit HTTP 400 ab
("Ttl value conflicts with X-WNS-Cache-Policy"). Apple und Google stört TTL 0
nicht - deshalb kamen die Meldungen auf den iPhones an, auf dem Windows-Rechner
nie, und niemand wusste davon: `push_send()` protokolliert den Fehlschlag nur.

Dieser Test hält den Wert fest. Er prüft nicht, ob eine echte Nachricht
ankommt - das geht nur auf einem echten Gerät (`manage.py testpush`).
"""
import threading


def _webpush_abfangen(monkeypatch):
    """Ersetzt pywebpush.webpush und sammelt die Aufrufe ein."""
    aufrufe = []
    import pywebpush

    def falscher_webpush(**kwargs):
        aufrufe.append(kwargs)

    monkeypatch.setattr(pywebpush, "webpush", falscher_webpush)
    return aufrufe


def _warte_auf_threads():
    """push_send() verschickt in einem Thread - der Test muss ihn abwarten."""
    for t in threading.enumerate():
        if t is not threading.current_thread() and t.daemon:
            t.join(timeout=5)


def test_push_setzt_eine_ttz_groesser_null(app, db, admin, monkeypatch):
    """Der eigentliche Fund: ohne TTL verwirft Windows die Nachricht."""
    aufrufe = _webpush_abfangen(monkeypatch)
    db["verbindung"].execute(
        "INSERT INTO push_abos(user_id, endpoint, p256dh, auth, geraet) "
        "VALUES(?,?,?,?,?)",
        (admin["id"], "https://wns2-am3p.notify.windows.com/w/?token=xyz",
         "p256dh-wert", "auth-wert", "Windows-Testgeraet"))
    db["verbindung"].commit()

    from teile.kern import push_send
    app.config["VAPID_PRIVATE_KEY"] = "test-key"
    try:
        with app.app_context():
            push_send(admin["id"], "Titel", "Text", "todo",
                      "https://portal.16schwaben.de/a/todo/")
        _warte_auf_threads()
    finally:
        app.config["VAPID_PRIVATE_KEY"] = ""

    assert aufrufe, "webpush wurde gar nicht aufgerufen"
    ttl = aufrufe[0].get("ttl")
    assert ttl is not None, "kein ttl übergeben - Windows/Edge verwirft die Nachricht"
    assert ttl > 0, f"ttl={ttl} - Windows/Edge verwirft die Nachricht"


def test_push_ohne_vapid_key_versendet_nichts(app, db, admin, monkeypatch):
    """Ohne Schlüssel darf nichts rausgehen (und nichts krachen) - so läuft
    die Testumgebung, und so lief das Portal vor der Push-Einführung."""
    aufrufe = _webpush_abfangen(monkeypatch)
    from teile.kern import push_send
    app.config["VAPID_PRIVATE_KEY"] = ""
    with app.app_context():
        push_send(admin["id"], "Titel", "Text")
    _warte_auf_threads()
    assert not aufrufe


def test_push_zieladresse_ist_tokenfrei(app, db, admin, monkeypatch):
    """Wunsch #140, Stufe 6: Die Adresse in der Benachrichtigung kam früher
    aus dem entschlüsselten Token des Empfängers. Stünde dort wieder einer,
    landete er über die Benachrichtigung erneut außerhalb des Portals."""
    import json
    aufrufe = _webpush_abfangen(monkeypatch)
    db["verbindung"].execute(
        "INSERT INTO push_abos(user_id, endpoint, p256dh, auth, geraet) "
        "VALUES(?,?,?,?,?)",
        (admin["id"], "https://web.push.apple.com/test", "p", "a", "iPhone"))
    db["verbindung"].commit()

    from teile.todo import _todo_url
    from teile.kern import push_send, get_db
    app.config["VAPID_PRIVATE_KEY"] = "test-key"
    try:
        with app.app_context():
            ziel = _todo_url(get_db(), admin["id"])
            push_send(admin["id"], "Neue Aufgabe", "Text", "todo", ziel)
        _warte_auf_threads()
    finally:
        app.config["VAPID_PRIVATE_KEY"] = ""

    assert ziel == "https://portal.16schwaben.de/a/todo/"
    nutzlast = json.loads(aufrufe[0]["data"])
    for name, token in admin["tokens"].items():
        assert token not in nutzlast["url"], f"Token '{name}' in der Push-Adresse"
