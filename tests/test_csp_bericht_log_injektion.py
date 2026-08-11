"""Wunsch #205 (Sicherheitsaudit 11.08.2026): CSP-Meldeendpunkt protokollierte
ungefilterten Text.

POST /csp-bericht ist absichtlich ohne Autorisierung und ohne CSRF-Prüfung
(echte Browser-Meldungen tragen weder Cookie noch Origin) - das ist richtig
so. Die Werte aus dem JSON-Body wurden aber nur auf Länge gekürzt, nicht auf
Steuerzeichen geprüft, bevor sie per %-Formatierung in eine Log-Zeile
geschrieben wurden. Jeder konnte also Text mit eingebetteten Zeilenumbrüchen
einschicken und damit eine zusätzliche, frei erfundene Log-Zeile einschleusen
- z. B. eine gefälschte "CSRF-Verdacht:"-Zeile, die wie ein ECHTER, anderer
Vorfall aussieht.

**Die Prüfung, auf die es ankommt:** nicht nur, dass `_log_sicher()` als
Funktion Steuerzeichen entfernt (das wäre ein Test, der lügt, wenn die
Funktion irgendwo im Aufruf vergessen wird) - sondern dass die tatsächlich
GESCHRIEBENE Log-Zeile sauber ist. Dafür wird hier der Log-Handler selbst
abgehört, nicht nur `_log_sicher()` isoliert aufgerufen.
"""
import logging

import pytest


@pytest.fixture()
def log_erfassen():
    """Sammelt die vollständig formatierten Log-Zeilen des CSP-Loggers."""
    logger = logging.getLogger("app")   # current_app.logger-Name (Flask(__name__))
    zeilen = []

    class Sammler(logging.Handler):
        def emit(self, record):
            zeilen.append(record.getMessage())

    handler = Sammler()
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    yield zeilen
    logger.removeHandler(handler)


def _melden(client, **felder):
    return client.post("/csp-bericht", json=felder)


def test_zeilenumbruch_im_blocked_uri_landet_nicht_roh_im_log(client, app, log_erfassen):
    with app.app_context():
        _melden(client, **{"blocked-uri": "https://boese.example/\nCSRF-Verdacht: gefaelscht"})
    voll = "\n".join(log_erfassen)
    assert "\nCSRF-Verdacht: gefaelscht" not in voll, (
        "eine eingeschleuste Zeile sieht aus wie eine echte, eigenstaendige Log-Meldung"
    )


def test_wagenruecklauf_wird_ebenfalls_entfernt(client, app, log_erfassen):
    with app.app_context():
        _melden(client, **{"document-uri": "https://x\r\nGefaelscht: ja"})
    voll = "\n".join(log_erfassen)
    assert "\r" not in voll


def test_normale_meldung_bleibt_lesbar(client, app, log_erfassen):
    """Die Saeuberung darf harmlose Meldungen nicht verstuemmeln."""
    with app.app_context():
        _melden(client, **{"blocked-uri": "https://fremd.example/skript.js",
                           "document-uri": "https://portal.16schwaben.de/a/todo/",
                           "violated-directive": "script-src"})
    voll = "\n".join(log_erfassen)
    assert "https://fremd.example/skript.js" in voll
    assert "script-src" in voll


def test_fehlende_felder_stuerzen_nichts_ab(client, app, log_erfassen):
    with app.app_context():
        antwort = _melden(client)
    assert antwort.status_code == 204
    assert log_erfassen  # trotzdem protokolliert, nur mit "?"
