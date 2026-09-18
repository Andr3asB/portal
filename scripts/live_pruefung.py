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
import time
import urllib.error
import urllib.request

HOST    = "claude@10.0.0.100"
SSH     = ["ssh", "-p", "2222", HOST]
BASIS   = "https://portal.16schwaben.de"
KENNUNG = "PRUEFUNG"

# Unterseiten, die nicht die Startseite ihrer App sind und deshalb sonst nie
# angefasst würden. Jede App-Startseite prüft das Skript ohnehin; hier stehen
# nur Seiten, die man von Hand aufsuchen muss. Wer eine neue baut, trägt sie
# ein - sonst merkt niemand, wenn sie 500 wirft, bis jemand sie braucht.
UNTERSEITEN = {
    "admin": [("/a/admin/geraete", "Verwaltung › Geräte"),
              ("/a/admin/ki",      "Verwaltung › KI-Verbrauch"),
              ("/a/admin/apps",    "Verwaltung › App-Zugriff")],
    "todo":  [("/a/todo/kanban",   "Aufgaben › Brett")],
    # Der Kader fuellt seinen 6-h-Cache beim ersten Aufruf (HPI-API) - seit
    # #271 samt Bild-Adressen; die Zeit dafuer steht dann in der Ausgabe.
    "tvb":   [("/a/tvb/kader",     "TVB › Kader")],
}


def auf_dem_server(python_code: str) -> str:
    """Führt Python IM Container aus und gibt stdout zurück.

    Bewusst über `docker exec`: Die Datenbank liegt im Container, und der
    Host darf laut CLAUDE.md nicht verändert werden."""
    befehl = SSH + ["docker", "exec", "-i", "portal", "python", "-"]
    fertig = subprocess.run(befehl, input=python_code, capture_output=True,
                            text=True, encoding="utf-8", check=False)
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


def hole(pfad: str, cookie: str) -> tuple[int, int]:
    """(Statuscode, Dauer in ms). Die Dauer steht seit Wunsch #270 dabei -
    "das erste Öffnen dauert lange" ist sonst nicht messbar, nur fühlbar."""
    anfrage = urllib.request.Request(BASIS + pfad, headers={
        "Cookie": f"portal_sitzung={cookie}",
        "User-Agent": "portal-live-pruefung",
    })
    start = time.monotonic()
    try:
        with urllib.request.urlopen(anfrage, timeout=20,
                                    context=ssl.create_default_context()) as antwort:
            antwort.read()
            return antwort.status, int((time.monotonic() - start) * 1000)
    except urllib.error.HTTPError as fehler:
        return fehler.code, int((time.monotonic() - start) * 1000)
    except Exception:
        return 0, int((time.monotonic() - start) * 1000)


def stufen_pruefen(cookie: str) -> list[str]:
    """Wunsch #293: Sieht man dem laufenden Portal an, dass die Stufen scharf
    sind? Zwei Dinge lassen sich von aussen ablesen - die CSP traegt ein
    Nonce (CSP_MODUS=scharf) und einen report-uri (#294), und eine
    aendernde Anfrage ohne Herkunft wird mit 403 abgewiesen (CSRF_MODUS=
    scharf). Ein Tippfehler in der .env faellt damit hier auf, nicht erst
    beim naechsten Audit."""
    maengel = []
    anfrage = urllib.request.Request(BASIS + "/start", headers={
        "Cookie": f"portal_sitzung={cookie}", "User-Agent": "portal-live-pruefung"})
    with urllib.request.urlopen(anfrage, timeout=20,
                                context=ssl.create_default_context()) as antwort:
        csp = antwort.headers.get("Content-Security-Policy") or ""
    if "'nonce-" not in csp:
        maengel.append("CSP ohne Nonce - steht CSP_MODUS auf scharf?")
    if "report-uri" not in csp:
        maengel.append("CSP ohne report-uri (#294)")
    # POST ohne Origin/Sec-Fetch-Site auf einen Pfad, der nichts aendert, wenn
    # er durchkaeme (ungueltiger Token) - bei CSRF scharf antwortet der Riegel
    # VOR der Route mit 403; bei aus/beobachten die Route selbst mit 403. Der
    # Unterschied steckt im Log, nicht im Status - darum hier nur die
    # Gegenprobe, dass ueberhaupt 403 kommt und nichts anderes.
    anfrage = urllib.request.Request(BASIS + "/a/todo/status/1", method="POST",
                                     data=b"status=offen",
                                     headers={"Content-Type": "application/x-www-form-urlencoded",
                                              "User-Agent": "portal-live-pruefung"})
    try:
        with urllib.request.urlopen(anfrage, timeout=20, context=ssl.create_default_context()):
            maengel.append("POST ohne Herkunft und ohne Token kam durch")
    except urllib.error.HTTPError as fehler:
        if fehler.code != 403:
            maengel.append(f"POST ohne Herkunft: HTTP {fehler.code} statt 403")
    return maengel


def main() -> int:
    nutzer = sys.argv[1] if len(sys.argv) > 1 else None
    cookie, name, apps = sitzung_anlegen(nutzer)
    print(f"Prüfe als {name} – {len(apps)} Apps, EINE Sitzung\n")
    fehler = []
    try:
        for pfad, beschriftung in [("/health", "health"), ("/start", "Startseite"),
                                   ("/p/briefing", "Startseite › Briefing")]:
            code, ms = hole(pfad, cookie)
            print(f"  {code}  {ms:5d} ms  {beschriftung}")
            if code != 200:
                fehler.append((beschriftung, code))
        for mangel in stufen_pruefen(cookie):
            print(f"  !!!          {mangel}")
            fehler.append((mangel, 0))
        print("  ok           Stufen: CSP-Nonce, report-uri, CSRF-Riegel")
        for app in apps:
            if app["slug"] == "home":
                continue          # die Startseite hängt nicht unter /a/
            code, ms = hole(f"/a/{app['slug']}/", cookie)
            print(f"  {code}  {ms:5d} ms  {app['name']}")
            if code != 200:
                fehler.append((app["name"], code))
            for pfad, beschriftung in UNTERSEITEN.get(app["slug"], []):
                code, ms = hole(pfad, cookie)
                print(f"  {code}  {ms:5d} ms  {beschriftung}")
                if code != 200:
                    fehler.append((beschriftung, code))
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
