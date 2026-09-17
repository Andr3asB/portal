"""
Prüft täglich die mtime von /certs/fullchain.pem.
Bei Änderung: Caddy-Konfiguration über die Admin-API neu laden,
damit das erneuerte Zertifikat sofort gilt.

Wunsch #280 (Sicherheitsaudit 16.09.2026, Befund N-01): Die Admin-API lag
bis dahin auf 172.30.0.10:2019 und war seit Wunsch #126 (05.08.2026) per
`admin off` abgeschaltet - dieser Watcher lief also sechs Wochen lang gegen
eine Wand, ohne dass es auffiel: Der Fehler tritt erst auf, wenn sich das
Zertifikat ändert, und das war seit dem 26.07. nicht der Fall. Nach der
nächsten certbot-Erneuerung hätte Caddy still das alte Zertifikat
weitergeliefert, bis es abläuft.

Jetzt spricht der Watcher die API über einen Unix-Socket an, der in einem
Volume liegt, das nur caddy und util mounten (docker-compose.yml). Der
portal-Container sieht ihn nicht - der Grund für `admin off` (#126: SSRF aus
dem Portal auf die unauthentifizierte API) bleibt damit erledigt.

Kein `requests` mehr: http.client über AF_UNIX reicht, und damit ist util
ohne ein einziges Fremdpaket unterwegs.
"""
import http.client
import json
import logging
import socket
from pathlib import Path

CERT   = Path("/certs/fullchain.pem")
SOCKET = "/run/caddy-admin/admin.sock"
STATE  = Path("/data/.cert_mtime")

log = logging.getLogger("util.cert_watcher")


class _UnixHTTP(http.client.HTTPConnection):
    """HTTP über einen Unix-Socket. Host bleibt `localhost` - Caddy prüft
    den Host-Header auch am Socket (`origins localhost` im Caddyfile)."""

    def __init__(self, pfad: str, timeout: float):
        super().__init__("localhost", timeout=timeout)
        self._pfad = pfad

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(self._pfad)
        self.sock = s


def _anfrage(methode: str, pfad: str, body=None, headers=None, timeout=30):
    """Ein Aufruf gegen die Admin-API. Wirft bei Status >= 400."""
    verbindung = _UnixHTTP(SOCKET, timeout)
    try:
        verbindung.request(methode, pfad, body=body, headers=headers or {})
        antwort = verbindung.getresponse()
        daten = antwort.read()
        if antwort.status >= 400:
            raise RuntimeError(
                f"Caddy-Admin-API {methode} {pfad}: HTTP {antwort.status} "
                f"{daten[:200]!r}")
        return antwort.status, daten
    finally:
        verbindung.close()


def _reload_caddy():
    """Lädt die aktuelle Konfiguration aus der Caddy-API und postet sie zurück -
    das zwingt Caddy, die Zertifikatsdateien neu einzulesen.

    `Cache-Control: must-revalidate` ist Pflicht: Caddy vergleicht die neue
    Konfiguration mit der laufenden und tut bei Gleichheit NICHTS - und die
    Konfiguration IST gleich, nur die Dateien dahinter haben sich geändert
    (Caddy-Doku, POST /load)."""
    _, roh = _anfrage("GET", "/config/", timeout=10)
    cfg = json.loads(roh)
    status, _ = _anfrage(
        "POST", "/load",
        body=json.dumps(cfg).encode(),
        headers={"Content-Type": "application/json",
                 "Cache-Control": "must-revalidate"},
        timeout=30,
    )
    log.info("Caddy-Reload erfolgreich (Status %s)", status)


def check():
    if not CERT.exists():
        log.warning("Zertifikat nicht gefunden: %s", CERT)
        return

    try:
        current = CERT.stat().st_mtime
        last    = float(STATE.read_text()) if STATE.exists() else 0.0

        if current != last:
            log.info("Zertifikat geändert (mtime %.0f → %.0f) – Reload…", last, current)
            _reload_caddy()
            STATE.write_text(str(current))
        else:
            log.debug("Zertifikat unverändert")
    except Exception:
        # Bewusst ERROR statt eines stillen Tracebacks im Debug-Level: Wenn
        # das hier fehlschlägt, liefert Caddy bald ein abgelaufenes
        # Zertifikat - das muss im Log auffallen.
        log.exception("Fehler im cert_watcher - Caddy hat das neue Zertifikat "
                      "NICHT geladen; notfalls caddy-Container neu erzeugen")
