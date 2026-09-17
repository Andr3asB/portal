"""Wunsch #289 (Sicherheitsaudit 16.09.2026, Befunde N-10/N-11): Antworten von
Drittquellen ohne Größengrenze, Push-Versand ohne Timeout.

`resp.read()` ohne Argument liest, was auch immer die Gegenstelle schickt,
komplett in den Speicher des 256-MB-Containers. Die Hosts sind Konstanten
und TLS wird geprüft – aber der TVB-Hintergrund-Thread ruft alle fünf
Minuten von selbst an; eine kaputte oder feindliche Antwort hätte ihn
WIEDERHOLT ins OOM geschickt. `_bild_holen()` in 18_tvb.py machte es von
Anfang an richtig; jetzt tun es alle über `begrenzt_lesen()` aus dem Kern.

Der zweite Teil: `pywebpush.webpush()` lässt `timeout` auf None. Ein
Endpunkt, der die Verbindung annimmt und nie antwortet, hielt den
Versand-Thread ewig – und push_send() startet je Aufruf einen.

Der Wächter unten liest den Quelltext: ein neues `resp.read()` ohne Grenze
fällt sofort auf, nicht erst beim nächsten Audit.
"""
import pathlib
import re
import threading

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"


class _FakeAntwort:
    def __init__(self, body):
        self._body = body

    def read(self, n=-1):
        return self._body[:n] if n and n > 0 else self._body


def test_begrenzt_lesen_haelt_die_grenze():
    from teile.kern import begrenzt_lesen
    assert begrenzt_lesen(_FakeAntwort(b"x" * 100), 100) == b"x" * 100
    with pytest.raises(ValueError, match="zu groß"):
        begrenzt_lesen(_FakeAntwort(b"x" * 101), 100)


def test_kein_unbegrenztes_read_auf_netzantworten():
    """Wächter: `resp.read()`, `antwort.read()`, `e.read()` etc. ohne Argument
    in den App-Modulen und manage.py sind verboten. Datei-Uploads
    (`datei.read()`) sind durch MAX_CONTENT_LENGTH gedeckt und ausgenommen."""
    muster = re.compile(r"\b(resp|antwort|response|r|e|fehler)\.read\(\)")
    treffer = []
    for datei in list((SRC / "teile").glob("*.py")) + [SRC / "manage.py"]:
        for nr, zeile in enumerate(datei.read_text(encoding="utf-8").splitlines(), 1):
            if muster.search(zeile) and not zeile.lstrip().startswith("#"):
                treffer.append(f"{datei.name}:{nr}: {zeile.strip()}")
    assert not treffer, "Netzantwort ohne Größengrenze gelesen:\n" + "\n".join(treffer)


def test_push_versand_hat_ein_timeout(app, db, admin, monkeypatch):
    import pywebpush
    aufrufe = []
    monkeypatch.setattr(pywebpush, "webpush", lambda **kw: aufrufe.append(kw))
    db["verbindung"].execute(
        "INSERT INTO push_abos(user_id, endpoint, p256dh, auth, geraet) VALUES(?,?,?,?,?)",
        (admin["id"], "https://push.example/abo-1", "p", "a", "Test"))
    db["verbindung"].commit()

    from teile.kern import PUSH_TIMEOUT, push_send
    monkeypatch.setitem(app.config, "VAPID_PRIVATE_KEY", "test-key")
    with app.app_context():
        push_send(admin["id"], "Titel", "Text", "todo", "https://portal.16schwaben.de/a/todo/")
    for t in threading.enumerate():
        if t is not threading.current_thread() and t.daemon:
            t.join(timeout=5)
    assert aufrufe and aufrufe[0]["timeout"] == PUSH_TIMEOUT == 10


def test_manage_testpush_hat_dasselbe_timeout():
    quelle = (SRC / "manage.py").read_text(encoding="utf-8")
    # Der Aufruf ist mehrzeilig und enthält Kommentare mit Klammern - deshalb
    # nicht bis zur ersten ")" schneiden, sondern im Fenster nach `webpush(`
    # suchen.
    assert re.search(r"webpush\((?:.|\n){0,1500}?timeout\s*=\s*10\b", quelle), \
        "manage.py testpush ohne Timeout"
