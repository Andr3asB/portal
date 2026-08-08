#!/usr/bin/env python3
"""Live-Smoketest gegen das laufende Portal - von DIESEM Rechner aus.

    python scripts/live_pruefung.py            # als erster Admin
    python scripts/live_pruefung.py Friederike

Warum es dieses Skript gibt
---------------------------
Die Prüfung lief bisher ad hoc: für jeden Grant ein `curl` mit seinem
Pfad-Token. Das hatte zwei Fehler, die erst am 08.08.2026 aufgefallen sind,
als jemand die Sitzungstabelle nachgezählt hat.

**Jeder Aufruf ohne Cookie stellt eine Sitzung aus.** 50 Grants × mehrmals
täglich ergaben 808 Zeilen - jede davon ein gültiger, nie ablaufender Zugang.
Ausgerechnet der Umbau, der die Zahl langlebiger Zugangsgeheimnisse senken
sollte, hat sie so verhundertfacht. Deshalb hier: **genau eine** Sitzung, und
die wird im `finally` wieder gelöscht, auch wenn mittendrin etwas schiefgeht.

**Ad-hoc-Befehle lassen sich nicht reparieren.** Ein Skript, das nur in einer
Chat-Historie steht, trägt seine Fehler in die nächste Sitzung. Dieses hier
liegt im Repo und wird mitgeändert, wenn sich etwas ändert.

Seit Wunsch #140 Stufe 6 gibt es keine Klartext-Tokens mehr; die Sitzung ist
der einzige Weg, von aussen als jemand Bestimmtes hineinzukommen. Sie trägt
die Kennung `geraet='PRUEFUNG'` - daran ist sie jederzeit erkennbar und
notfalls von Hand zu entfernen:

    docker exec portal python -c "..."   # DELETE FROM sitzungen WHERE geraet='PRUEFUNG'
"""
import json
import ssl
import subprocess
import sys
import urllib.error
import urllib.request

HOST    = "claude@10.0.0.100"
SSH     = ["ssh", "-p", "2222", HOST]
BASIS   = "https://portal.16schwaben.de"
KENNUNG = "PRUEFUNG"


def auf_dem_server(python_code: str) -> str:
    """Führt Python IM Container aus und gibt stdout zurück.

    Bewusst über `docker exec`: Die Datenbank liegt im Container, und der
    Host darf laut CLAUDE.md nicht verändert werden."""
    befehl = SSH + ["docker", "exec", "-i", "portal", "python", "-"]
    fertig = subprocess.run(befehl, input=python_code, capture_output=True,
                            text=True, encoding="utf-8")
    if fertig.returncode != 0:
        raise RuntimeError(f"Fehler auf dem Server:\n{fertig.stderr.strip()}")
    return fertig.stdout.strip()


def sitzung_anlegen(nutzer):
    """Legt EINE Sitzung an und liefert Cookie, Name und die Apps des Nutzers."""
    wahl = (f"SELECT id, name FROM users WHERE name={nutzer!r}"
            if nutzer else
            "SELECT id, name FROM users WHERE is_admin=1 ORDER BY id LIMIT 1")
    roh = auf_dem_server(f"""
import base64, hashlib, hmac, json, os, secrets, sqlite3
key = base64.urlsafe_b64decode(os.environ["TOKEN_KEY"])
db  = sqlite3.connect(os.environ.get("DB_PATH", "/data/portal.db"))
db.row_factory = sqlite3.Row
u = db.execute({wahl!r}).fetchone()
if not u:
    raise SystemExit("Nutzer nicht gefunden")
kennwert = secrets.token_urlsafe(32)
db.execute("INSERT INTO sitzungen(user_id, kennung_lookup, quelle, geraet) VALUES(?,?,?,?)",
           (u["id"], hmac.new(key, kennwert.encode(), hashlib.sha256).hexdigest(),
            "token", {KENNUNG!r}))
db.commit()
apps = [dict(r) for r in db.execute(
    "SELECT a.slug, a.name FROM grants g JOIN apps a ON a.id=g.app_id "
    "WHERE g.user_id=? ORDER BY a.slug", (u["id"],))]
print(json.dumps({{"cookie": kennwert, "name": u["name"], "apps": apps}}))
""")
    daten = json.loads(roh.splitlines()[-1])
    return daten["cookie"], daten["name"], daten["apps"]


def sitzung_loeschen() -> int:
    """Räumt ALLE Prüfsitzungen ab - auch die eines abgebrochenen Laufs."""
    return int(auf_dem_server(f"""
import os, sqlite3
db = sqlite3.connect(os.environ.get("DB_PATH", "/data/portal.db"))
print(db.execute("DELETE FROM sitzungen WHERE geraet={KENNUNG!r}").rowcount)
db.commit()
""").splitlines()[-1])


def hole(pfad: str, cookie: str) -> int:
    anfrage = urllib.request.Request(BASIS + pfad, headers={
        "Cookie": f"portal_sitzung={cookie}",
        "User-Agent": "portal-live-pruefung",
    })
    try:
        with urllib.request.urlopen(anfrage, timeout=20,
                                    context=ssl.create_default_context()) as antwort:
            return antwort.status
    except urllib.error.HTTPError as fehler:
        return fehler.code
    except Exception:
        return 0


def main() -> int:
    nutzer = sys.argv[1] if len(sys.argv) > 1 else None
    cookie, name, apps = sitzung_anlegen(nutzer)
    print(f"Prüfe als {name} – {len(apps)} Apps, EINE Sitzung\n")
    fehler = []
    try:
        for pfad, beschriftung in [("/health", "health"), ("/start", "Startseite")]:
            code = hole(pfad, cookie)
            print(f"  {code}  {beschriftung}")
            if code != 200:
                fehler.append((beschriftung, code))
        for app in apps:
            if app["slug"] == "home":
                continue          # die Startseite hängt nicht unter /a/
            code = hole(f"/a/{app['slug']}/", cookie)
            print(f"  {code}  {app['name']}")
            if code != 200:
                fehler.append((app["name"], code))
    finally:
        # Auch bei Abbruch: die Sitzung darf nicht stehen bleiben. Genau das
        # Versäumnis hat 808 Zugänge in der Datenbank hinterlassen.
        print(f"\nPrüfsitzungen entfernt: {sitzung_loeschen()}")

    if fehler:
        print("\nFEHLER:")
        for was, code in fehler:
            print(f"  {code}  {was}")
        return 1
    print("Alles grün.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
