"""
Hauptschleife für den util-Container.
Prüft jede Minute, ob Aufgaben fällig sind.

Aufgaben:
  - Jede volle Stunde:  SQLite-Snapshot
  - Täglich 04:00 Uhr:  Zertifikats-Watcher (Caddy-Reload bei Erneuerung)
"""
import logging, time
from datetime import datetime

import cert_watcher
import db_snapshot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("util.scheduler")


def main():
    log.info("util-Scheduler gestartet")

    last_snapshot_hour = -1
    last_cert_check_day = -1

    # Beim Start sofort einmal beide Aufgaben ausführen
    db_snapshot.take()
    cert_watcher.check()
    last_snapshot_hour  = datetime.now().hour
    last_cert_check_day = datetime.now().day

    while True:
        time.sleep(60)
        now = datetime.now()

        if now.hour != last_snapshot_hour:
            db_snapshot.take()
            last_snapshot_hour = now.hour

        if now.hour == 4 and now.day != last_cert_check_day:
            cert_watcher.check()
            last_cert_check_day = now.day


if __name__ == "__main__":
    main()
