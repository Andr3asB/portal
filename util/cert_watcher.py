"""
Prüft täglich die mtime von /certs/fullchain.pem.
Bei Änderung: Caddy-Konfiguration über Admin-API neu laden,
damit das erneuerte Zertifikat sofort gilt.

Admin-API liegt auf 172.30.0.10:2019 (internes Bridge-Netz, nicht im macvlan).
"""
import logging, requests
from pathlib import Path

CERT    = Path("/certs/fullchain.pem")
# IP-Adresse statt Hostname – Caddys Admin-API prüft den Host-Header
# und akzeptiert nur Anfragen, die exakt auf die Bind-Adresse lauten.
CADDY   = "http://172.30.0.10:2019"
STATE   = Path("/data/.cert_mtime")

log = logging.getLogger("util.cert_watcher")


def _reload_caddy():
    """Lädt die aktuelle Konfiguration aus der Caddy-API und postet sie zurück –
    das zwingt Caddy, die Zertifikatsdateien neu einzulesen."""
    r = requests.get(f"{CADDY}/config/", timeout=10)
    r.raise_for_status()
    cfg = r.json()
    r = requests.post(
        f"{CADDY}/load",
        json=cfg,
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    r.raise_for_status()
    log.info("Caddy-Reload erfolgreich (Status %s)", r.status_code)


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
        log.exception("Fehler im cert_watcher")
