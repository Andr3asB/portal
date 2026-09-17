"""Wunsch #280 (Sicherheitsaudit 16.09.2026, Befund N-01): Der Zertifikats-
Watcher sprach eine abgeschaltete API an.

`util/cert_watcher.py` lud bei geänderter Zertifikatsdatei die Caddy-
Konfiguration per GET/POST von `172.30.0.10:2019` – und genau diese Admin-API
war seit Wunsch #126 (05.08.2026) per `admin off` abgeschaltet. Sechs Wochen
lang fiel das nicht auf, weil der Reload nur bei geänderter mtime läuft und
das Zertifikat seit dem 26.07. unverändert war. Nach der nächsten certbot-
Erneuerung hätte Caddy still das alte Zertifikat weitergeliefert, bis es
abläuft – mit HSTS ein harter Totalausfall ohne Klickweg im Browser.

Jetzt: Admin-API als Unix-Socket in einem Volume, das nur caddy und util
mounten. Diese Tests halten die drei Eigenschaften fest, die still
zurückfallen könnten:

1. Das Caddyfile schaltet die API nicht ab, sondern legt sie auf den Socket.
2. Das Socket-Volume hängt in caddy und util – und NICHT in portal (sonst
   wäre der SSRF-Weg aus #126 wieder offen).
3. Der Watcher spricht genau diesen Socket an, mit `Cache-Control:
   must-revalidate` (Caddy tut bei gleicher Konfiguration sonst NICHTS – und
   die Konfiguration ist gleich, nur die Dateien dahinter sind neu), und
   merkt sich den Stand erst NACH erfolgreichem Reload.
"""
import importlib.util
import json
import pathlib
import re

import pytest

WURZEL = pathlib.Path(__file__).resolve().parents[1]
WATCHER = WURZEL / "util" / "cert_watcher.py"
SOCKET = "/run/caddy-admin/admin.sock"
MOUNT = "caddy_admin:/run/caddy-admin"


@pytest.fixture()
def watcher():
    spec = importlib.util.spec_from_file_location("cert_watcher_test", WATCHER)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def _ohne_kommentare(text: str) -> str:
    return "\n".join(zeile.split("#", 1)[0] for zeile in text.splitlines())


def test_caddyfile_legt_die_admin_api_auf_den_socket():
    caddyfile = _ohne_kommentare((WURZEL / "Caddyfile").read_text(encoding="utf-8"))
    assert not re.search(r"^\s*admin\s+off\b", caddyfile, re.MULTILINE), \
        "`admin off` würde den Zertifikats-Reload wieder ins Leere laufen lassen (#280)"
    assert re.search(rf"^\s*admin\s+unix/{SOCKET}\|0666\b", caddyfile, re.MULTILINE), \
        f"Admin-API muss auf unix/{SOCKET} mit Modus 0666 liegen"
    assert re.search(r"^\s*origins\s+localhost\b", caddyfile, re.MULTILINE)


def _dienst_block(compose: str, name: str) -> str:
    """Der eingerückte Block eines Dienstes aus docker-compose.yml."""
    treffer = re.search(rf"^  {name}:\n((?:    .*\n|\n)*)", compose, re.MULTILINE)
    assert treffer, f"Dienst {name} nicht gefunden"
    return treffer.group(1)


def test_socket_volume_haengt_in_caddy_und_util_aber_nicht_in_portal():
    compose = _ohne_kommentare((WURZEL / "docker-compose.yml").read_text(encoding="utf-8"))
    assert MOUNT in _dienst_block(compose, "caddy")
    assert MOUNT in _dienst_block(compose, "util")
    assert MOUNT not in _dienst_block(compose, "portal"), \
        "portal darf den Admin-Socket nicht sehen - das war der Grund für #126"
    assert re.search(r"^  caddy_admin:", compose, re.MULTILINE), "Volume caddy_admin fehlt"


def test_watcher_kennt_denselben_socket(watcher):
    assert watcher.SOCKET == SOCKET


class _FakeAntwort:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    def read(self):
        return self._body


def _fake_verbindung(protokoll, antworten):
    class FakeUnixHTTP:
        def __init__(self, pfad, timeout):
            protokoll.append(("connect", pfad))
            self.timeout = timeout

        def request(self, methode, pfad, body=None, headers=None):
            protokoll.append((methode, pfad, body, dict(headers or {})))

        def getresponse(self):
            return antworten.pop(0)

        def close(self):
            pass
    return FakeUnixHTTP


def test_reload_holt_config_und_laedt_sie_mit_must_revalidate(watcher, monkeypatch):
    protokoll, cfg = [], {"apps": {"http": {}}}
    antworten = [_FakeAntwort(200, json.dumps(cfg).encode()), _FakeAntwort(200, b"")]
    monkeypatch.setattr(watcher, "_UnixHTTP", _fake_verbindung(protokoll, antworten))

    watcher._reload_caddy()

    assert protokoll[0] == ("connect", SOCKET)
    assert protokoll[1][:2] == ("GET", "/config/")
    assert protokoll[2] == ("connect", SOCKET)
    methode, pfad, body, headers = protokoll[3]
    assert (methode, pfad) == ("POST", "/load")
    assert json.loads(body) == cfg
    assert headers["Content-Type"] == "application/json"
    assert headers["Cache-Control"] == "must-revalidate"


def test_reload_wirft_bei_fehlerstatus(watcher, monkeypatch):
    """Ein 4xx/5xx darf nicht als Erfolg durchgehen - sonst würde check()
    den Stand wegschreiben und die Erneuerung wäre endgültig verpasst."""
    protokoll = []
    antworten = [_FakeAntwort(500, b"kaputt")]
    monkeypatch.setattr(watcher, "_UnixHTTP", _fake_verbindung(protokoll, antworten))
    with pytest.raises(RuntimeError, match="HTTP 500"):
        watcher._reload_caddy()


def test_check_merkt_sich_den_stand_erst_nach_erfolg(watcher, monkeypatch, tmp_path):
    cert = tmp_path / "fullchain.pem"
    cert.write_text("neu")
    state = tmp_path / ".cert_mtime"
    monkeypatch.setattr(watcher, "CERT", cert)
    monkeypatch.setattr(watcher, "STATE", state)

    def kaputt():
        raise RuntimeError("Socket weg")
    monkeypatch.setattr(watcher, "_reload_caddy", kaputt)
    watcher.check()
    assert not state.exists(), "nach einem Fehlschlag muss der nächste Lauf es erneut versuchen"

    aufrufe = []
    monkeypatch.setattr(watcher, "_reload_caddy", lambda: aufrufe.append(1))
    watcher.check()
    assert aufrufe == [1]
    assert float(state.read_text()) == cert.stat().st_mtime

    watcher.check()
    assert aufrufe == [1], "unverändertes Zertifikat löst keinen Reload aus"


def test_util_kommt_ohne_fremdpaket_aus():
    """requests war der einzige Grund für ein Paket in util - und der
    einzige Nutzer war der Watcher. Ohne Fremdpaket gibt es dort auch keine
    CVE-Pflege mehr."""
    zeilen = [z.strip() for z in (WURZEL / "util" / "requirements.txt").read_text().splitlines()]
    assert not [z for z in zeilen if z and not z.startswith("#")]
    for datei in (WURZEL / "util").glob("*.py"):
        assert not re.search(r"^\s*(import|from)\s+requests\b", datei.read_text(encoding="utf-8"), re.MULTILINE), \
            f"{datei.name} importiert requests"
