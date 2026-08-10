"""
CLI zur Ersteinrichtung und Verwaltung des Portals.

Aufruf im Container:
  docker exec portal python manage.py createadmin "Andi" "#3498db"
  docker exec portal python manage.py adduser "Mama" "#e74c3c"
  docker exec portal python manage.py addapp todo "Todos" "✅"
  docker exec portal python manage.py grant 1 todo
  docker exec portal python manage.py listusers
  docker exec portal python manage.py listwuensche
  docker exec portal python manage.py wunsch_erledigt 101 "Beschreibung der Umsetzung" 35000
  docker exec portal python manage.py titel_nachtragen 5
  docker exec portal python manage.py wunsch_aktion 188 frage "Woher kommen die Zahlen?"
  docker exec portal python manage.py wunsch_neu tvb "Kurzer Titel" "Der ganze Wunschtext"
  docker exec portal python manage.py ki_modell rezepte_import "anthropic/claude-haiku-4.5"
  docker exec portal python manage.py ki_stimme Latein "google/gemini-3.1-flash-tts-preview" "Kore"
  docker exec portal python manage.py listki
  docker exec portal python manage.py listpush
  docker exec portal python manage.py testpush 1 "Test von Andi"
"""
import os, sys, sqlite3, secrets, base64, hashlib, hmac
from pathlib import Path

DB = Path(os.environ.get("DB_PATH", "/data/portal.db"))


# Wunsch #129: manage.py laeuft ohne Flask-Kontext, holt den Schluessel also
# direkt aus der Umgebung (kommt per env_file aus derselben .env wie fuer die
# App). Gleiche Verfahren wie in teile/00_kern.py - bewusst dupliziert, weil
# manage.py absichtlich ohne die App-Module auskommt.
def _key() -> bytes:
    k = os.environ.get("TOKEN_KEY", "")
    if not k:
        sys.exit("TOKEN_KEY fehlt in der Umgebung (.env) - ohne Schluessel "
                 "sind die Zugangstokens nicht lesbar.")
    return base64.urlsafe_b64decode(k)


def _lookup(token: str) -> str:
    return hmac.new(_key(), token.encode(), hashlib.sha256).hexdigest()


# Wunsch #140, Stufe 6: `_enc`/`_dec` (AES-GCM) sind ersatzlos entfallen. Sie
# dienten allein dazu, einen Zugangstoken wieder im Klartext hervorzuholen -
# das gibt es nicht mehr. Der HMAC oben genuegt, um eine Zeile zu FINDEN.

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id       INTEGER PRIMARY KEY,
  name     TEXT    NOT NULL,
  farbe    TEXT    NOT NULL DEFAULT '#4a90d9',
  is_admin INTEGER NOT NULL DEFAULT 0,
  ki_key   TEXT
);
CREATE TABLE IF NOT EXISTS apps (
  id           INTEGER PRIMARY KEY,
  slug         TEXT    UNIQUE NOT NULL,
  name         TEXT    NOT NULL,
  emoji        TEXT    NOT NULL DEFAULT '📱',
  beschreibung TEXT
);
CREATE TABLE IF NOT EXISTS grants (
  id           INTEGER PRIMARY KEY,
  user_id      INTEGER NOT NULL REFERENCES users(id)  ON DELETE CASCADE,
  app_id       INTEGER NOT NULL REFERENCES apps(id)   ON DELETE CASCADE,
  token_lookup TEXT    UNIQUE NOT NULL,
  UNIQUE(user_id, app_id)
);
CREATE TABLE IF NOT EXISTS push_abos (
  id       INTEGER PRIMARY KEY,
  user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  endpoint TEXT    UNIQUE NOT NULL,
  p256dh   TEXT    NOT NULL,
  auth     TEXT    NOT NULL,
  geraet   TEXT
);
CREATE TABLE IF NOT EXISTS wuensche (
  id        INTEGER PRIMARY KEY,
  text      TEXT    NOT NULL,
  user_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
  app_slug  TEXT,
  erstellt  TEXT    NOT NULL DEFAULT (datetime('now')),
  erledigt  INTEGER NOT NULL DEFAULT 0
);
"""

def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    return db


def _ensure_home_app(db):
    db.execute(
        "INSERT OR IGNORE INTO apps(slug,name,emoji,beschreibung) VALUES('home','Portal','🏠','Persönliche Startseite')"
    )
    db.commit()
    return db.execute("SELECT id FROM apps WHERE slug='home'").fetchone()["id"]


def _make_grant(db, user_id, app_id):
    """Legt einen Grant an. Gibt den Klartext-Token zurueck - oder None, wenn
    der Grant schon existierte.

    Wunsch #140, Stufe 6: In der DB steht nur noch der HMAC. Existierte der
    Grant bereits, gilt weiterhin der ALTE Token, und den kann niemand mehr
    nachschlagen - frueher wurde er hier aus token_enc zurueckgewonnen. Der
    Aufrufer MUSS None unterscheiden, sonst zeigte er eine Adresse an, die
    gar nicht gilt."""
    token = secrets.token_urlsafe(18)
    cur = db.execute(
        "INSERT OR IGNORE INTO grants(user_id,app_id,token_lookup) VALUES(?,?,?)",
        (user_id, app_id, _lookup(token)),
    )
    db.commit()
    return token if cur.rowcount else None


def cmd_createadmin(args):
    if len(args) < 1:
        sys.exit("Verwendung: createadmin <name> [farbe]")
    name  = args[0]
    farbe = args[1].lstrip("#") if len(args) > 1 else "3498db"
    farbe = f"#{farbe}"
    db = connect()
    cur = db.execute(
        "INSERT INTO users(name,farbe,is_admin) VALUES(?,?,1) RETURNING id",
        (name, farbe),
    )
    user_id = cur.fetchone()["id"]
    db.commit()
    home_app_id = _ensure_home_app(db)
    token = _make_grant(db, user_id, home_app_id)
    db.close()
    print(f"Admin '{name}' (ID {user_id}) angelegt.")
    print(f"Startseite: https://portal.16schwaben.de/p/{token}")


def cmd_adduser(args):
    if len(args) < 1:
        sys.exit("Verwendung: adduser <name> [farbe]")
    name  = args[0]
    farbe = args[1].lstrip("#") if len(args) > 1 else "4a90d9"
    farbe = f"#{farbe}"
    db = connect()
    cur = db.execute(
        "INSERT INTO users(name,farbe,is_admin) VALUES(?,?,0) RETURNING id",
        (name, farbe),
    )
    user_id = cur.fetchone()["id"]
    db.commit()
    home_app_id = _ensure_home_app(db)
    token = _make_grant(db, user_id, home_app_id)
    db.close()
    print(f"Nutzer '{name}' (ID {user_id}) angelegt.")
    print(f"Startseite: https://portal.16schwaben.de/p/{token}")


def cmd_addapp(args):
    if len(args) < 3:
        sys.exit("Verwendung: addapp <slug> <name> <emoji>")
    slug, name, emoji = args[0], args[1], args[2]
    db = connect()
    db.execute(
        "INSERT OR IGNORE INTO apps(slug,name,emoji) VALUES(?,?,?)",
        (slug, name, emoji),
    )
    db.commit()
    app_id = db.execute("SELECT id FROM apps WHERE slug=?", (slug,)).fetchone()["id"]
    db.close()
    print(f"App '{slug}' (ID {app_id}) angelegt.")


def cmd_grant(args):
    if len(args) < 2:
        sys.exit("Verwendung: grant <user_id> <app_slug>")
    user_id, app_slug = int(args[0]), args[1]
    db = connect()
    row = db.execute("SELECT id FROM apps WHERE slug=?", (app_slug,)).fetchone()
    if not row:
        sys.exit(f"App '{app_slug}' nicht gefunden.")
    token = _make_grant(db, user_id, row["id"])
    db.close()
    if token is None:
        # Wunsch #140, Stufe 6: Der Grant existierte schon, es gilt weiterhin
        # der alte Token - und der ist nicht mehr nachschlagbar. Eine Adresse
        # zu drucken waere hier schlicht gelogen.
        print(f"Grant fuer '{app_slug}' bestand bereits - unveraendert gelassen.")
        print("Ein neuer Zugang geht ueber die Verwaltung ('Neuer Zugang + QR').")
        return
    print(f"Grant erteilt. URL: https://portal.16schwaben.de/a/{app_slug}/{token}/")


def cmd_listusers(_):
    """Wunsch #140, Stufe 6: zeigt KEINE Zugangsadressen mehr an - sie stehen
    nicht mehr in der Datenbank. Einen neuen Zugang erzeugt (und zeigt einmalig
    an) die Verwaltung über "Neuer Zugang + QR" bzw. hier `grant`."""
    db = connect()
    rows = db.execute("""
        SELECT u.id, u.name, u.farbe, u.is_admin,
               (SELECT COUNT(*) FROM grants g WHERE g.user_id = u.id) AS n_apps
        FROM   users u
        ORDER  BY u.id
    """).fetchall()
    db.close()
    for r in rows:
        admin = " [Admin]" if r["is_admin"] else ""
        print(f"  ID {r['id']:3}  {r['name']}{admin}  {r['farbe']}  "
              f"{r['n_apps']} App-Zugänge")


def cmd_listwuensche(_):
    db = connect()
    rows = db.execute("""
        SELECT w.id, w.text, w.app_slug, w.ansicht, w.erstellt, w.erledigt, u.name
        FROM   wuensche w LEFT JOIN users u ON u.id = w.user_id
        ORDER  BY w.erstellt DESC
    """).fetchall()
    db.close()
    for r in rows:
        status = "✅" if r["erledigt"] else "⏳"
        who = r["name"] or "anonym"
        ort = r["ansicht"] or r["app_slug"]
        app = f" [{ort}]" if ort else ""
        print(f"  {status} #{r['id']} {r['erstellt'][:16]}{app} {who}: {r['text']}")


def cmd_listtodos(_):
    db = connect()
    rows = db.execute("""
        SELECT t.id, t.inhalt, t.erledigt, t.erstellt, u1.name AS von, u2.name AS fuer
        FROM   todos t
        LEFT JOIN users u1 ON u1.id = t.erstellt_von
        LEFT JOIN users u2 ON u2.id = t.zugewiesen_an
        ORDER  BY t.erledigt, t.erstellt DESC
    """).fetchall()
    db.close()
    for r in rows:
        status = "✅" if r["erledigt"] else "⏳"
        fuer = f" → {r['fuer']}" if r["fuer"] else ""
        print(f"  {status} #{r['id']} {r['erstellt'][:10]} {r['von']}{fuer}: {r['inhalt']}")


def cmd_wunsch_erledigt(args):
    """Wunsch #101: die Umsetzung (was genau implementiert wurde) wird als
    zweites Argument mitgegeben und in der Werkstatt-App beim Anklicken des
    Wunsches angezeigt - deshalb ab jetzt bei jedem Abschluss mitgeben.

    Wunsch #188: als drittes Argument der Tokenverbrauch der Umsetzung.
    NACH der Umsetzung, nicht vorher geschaetzt - so hat Andi es entschieden.
    Weggelassen bleibt die Spalte NULL ("nicht erfasst"); eine 0 waere eine
    Behauptung, kein fehlender Wert.

        wunsch_erledigt 188 "Umsetzung ..." 35000
    """
    if not args:
        sys.exit('Verwendung: wunsch_erledigt <id> ["Umsetzung"] [tokens]')
    db = connect()
    wid = int(args[0])
    umsetzung = args[1] if len(args) > 1 else None
    tokens = None
    if len(args) > 2 and args[2].strip():
        try:
            tokens = int(args[2].replace(".", "").replace("_", ""))
        except ValueError:
            sys.exit(f"Tokenzahl '{args[2]}' ist keine Zahl.")
        if tokens < 0:
            sys.exit("Tokenzahl kann nicht negativ sein.")
    db.execute(
        "UPDATE wuensche SET erledigt=1, erledigt_am=CURRENT_TIMESTAMP, "
        "umsetzung=COALESCE(?, umsetzung), tokens=COALESCE(?, tokens) WHERE id=?",
        (umsetzung, tokens, wid),
    )
    # Wunsch #161: derselbe Text zusaetzlich als Aktion, damit der Verlauf
    # eines Wunsches vollstaendig ist. Die Spalte `umsetzung` bleibt daneben
    # bestehen - sie traegt die Abschluesse von ~150 alten Wuenschen, die es
    # als Aktion nie geben wird.
    if umsetzung:
        db.execute(
            "INSERT INTO wunsch_aktionen(wunsch_id, art, text, user_id) "
            "VALUES(?, 'umsetzung', ?, NULL)",
            (wid, umsetzung),
        )
    db.commit()
    db.close()
    print(f"Wunsch #{args[0]} als erledigt markiert."
          + (f" Tokenverbrauch: {tokens}." if tokens is not None else ""))


def cmd_backlog(_):
    """Alle offenen Wünsche und Todos – Einblick in den Rückstand."""
    db = connect()
    print("=== Offene Wünsche (✨) ===")
    for r in db.execute("""
        SELECT w.id, w.text, w.app_slug, w.ansicht, w.erstellt, u.name
        FROM wuensche w LEFT JOIN users u ON u.id = w.user_id
        WHERE w.erledigt=0 ORDER BY w.erstellt
    """).fetchall():
        ort = r["ansicht"] or r["app_slug"]
        app = f"[{ort}] " if ort else ""
        who = r["name"] or "anonym"
        print(f"  #{r['id']} {r['erstellt'][:10]} {app}{who}: {r['text']}")
    print()
    print("=== Offene Todos ===")
    for r in db.execute("""
        SELECT t.id, t.inhalt, t.erstellt, u1.name AS von, u2.name AS fuer
        FROM todos t
        LEFT JOIN users u1 ON u1.id = t.erstellt_von
        LEFT JOIN users u2 ON u2.id = t.zugewiesen_an
        WHERE t.erledigt=0 ORDER BY t.erstellt
    """).fetchall():
        fuer = f" → {r['fuer']}" if r["fuer"] else ""
        print(f"  #{r['id']} {r['erstellt'][:10]} {r['von']}{fuer}: {r['inhalt']}")
    db.close()


def cmd_ki_modell(args):
    """Wunsch #81 (Grundprinzip): Modell je KI-Zweck ohne Deploy aendern.
    ki_konfiguration/ki_stimmen existieren erst, sobald der Portal-Container
    einmal gestartet ist (00_kern.py._init_db legt sie an) - dieses Skript
    hat absichtlich nur ein Mini-Schema fuer die Ersteinrichtung."""
    if len(args) < 2:
        sys.exit("Verwendung: ki_modell <zweck> <modell>")
    zweck, modell = args[0], args[1]
    db = connect()
    db.execute(
        "INSERT INTO ki_konfiguration(zweck, modell) VALUES(?,?) "
        "ON CONFLICT(zweck) DO UPDATE SET modell=excluded.modell",
        (zweck, modell),
    )
    db.commit()
    db.close()
    print(f"KI-Modell fuer '{zweck}': {modell}")


def cmd_ki_stimme(args):
    if len(args) < 3:
        sys.exit("Verwendung: ki_stimme <sprache_name> <modell> <stimme>")
    sprache_name, modell, stimme = args[0], args[1], args[2]
    db = connect()
    row = db.execute("SELECT id FROM vokabel_sprachen WHERE name=?", (sprache_name,)).fetchone()
    if not row:
        sys.exit(f"Sprache '{sprache_name}' nicht gefunden.")
    db.execute(
        "INSERT INTO ki_stimmen(sprache_id, modell, stimme) VALUES(?,?,?) "
        "ON CONFLICT(sprache_id) DO UPDATE SET modell=excluded.modell, stimme=excluded.stimme",
        (row["id"], modell, stimme),
    )
    db.commit()
    db.close()
    print(f"TTS fuer '{sprache_name}': {modell} / {stimme}")


def cmd_listki(_):
    db = connect()
    print("=== KI-Modelle je Zweck ===")
    for r in db.execute("SELECT zweck, modell FROM ki_konfiguration ORDER BY zweck").fetchall():
        print(f"  {r['zweck']}: {r['modell']}")
    print()
    print("=== TTS-Stimmen je Sprache ===")
    for r in db.execute("""
        SELECT s.name, t.modell, t.stimme FROM ki_stimmen t
        JOIN vokabel_sprachen s ON s.id = t.sprache_id ORDER BY s.name
    """).fetchall():
        print(f"  {r['name']}: {r['modell']} / {r['stimme']}")
    db.close()


def cmd_listpush(_):
    """Wer hat welche Geräte für Benachrichtigungen angemeldet?"""
    db = connect()
    rows = db.execute("""
        SELECT u.id, u.name, p.geraet, p.endpoint
        FROM   push_abos p JOIN users u ON u.id = p.user_id
        ORDER  BY u.id, p.id
    """).fetchall()
    db.close()
    if not rows:
        print("  Keine Push-Abos vorhanden.")
        return
    for r in rows:
        # Der Endpunkt ist geraetespezifisch und gehoert nicht vollstaendig
        # ins Protokoll - die ersten Zeichen genuegen zum Unterscheiden.
        dienst = r["endpoint"].split("/")[2] if "//" in r["endpoint"] else "?"
        geraet = (r["geraet"] or "")[:60]
        print(f"  ID {r['id']:3}  {r['name']:12} {dienst:32} {geraet}")


def cmd_testpush(args):
    """Schickt eine Test-Benachrichtigung an alle Geräte eines Nutzers.

    Verwendung: testpush <user_id> [Text]

    Gedacht für S6-06 im Prüfplan: Seit Wunsch #140 Stufe 6 kann die
    Ziel-Adresse einer Push-Nachricht nicht mehr aus einem Klartext-Token
    gebaut werden (den gibt es nicht mehr) - sie ist token-frei und hängt am
    Sitzungs-Cookie des Geräts. Ob das Antippen wirklich in der Aufgabenliste
    landet, lässt sich nur auf einem echten Gerät sehen, und dafür sollte man
    niemandem erst eine echte Aufgabe zuweisen müssen.

    Verschickt wird bewusst dieselbe Ziel-Adresse wie bei einer echten
    Aufgaben-Benachrichtigung, sonst prüfte der Test etwas anderes als den
    Ernstfall.
    """
    if not args:
        sys.exit("Verwendung: testpush <user_id> [Text]")
    try:
        user_id = int(args[0])
    except ValueError:
        sys.exit("user_id muss eine Zahl sein (siehe: listusers)")
    text = " ".join(args[1:]) or "Wenn du das liest, kommen Benachrichtigungen an."

    private_key = os.environ.get("VAPID_PRIVATE_KEY", "")
    if not private_key:
        sys.exit("VAPID_PRIVATE_KEY fehlt in der Umgebung - ohne den Schluessel "
                 "kann keine Benachrichtigung verschickt werden.")
    subject = os.environ.get("VAPID_SUBJECT", "mailto:portal@16schwaben.de")

    db = connect()
    nutzer = db.execute("SELECT name FROM users WHERE id=?", (user_id,)).fetchone()
    if not nutzer:
        db.close()
        sys.exit(f"Kein Nutzer mit ID {user_id} (siehe: listusers)")
    abos = db.execute(
        "SELECT id, endpoint, p256dh, auth, geraet FROM push_abos WHERE user_id=?",
        (user_id,),
    ).fetchall()
    if not abos:
        db.close()
        sys.exit(f"{nutzer['name']} hat kein Geraet fuer Benachrichtigungen "
                 "angemeldet (im Portal ueber das Menue aktivieren).")

    import json
    from pywebpush import webpush, WebPushException

    payload = json.dumps({
        "title": "Test 🔔",
        "body":  text,
        # Dieselbe Adresse, die 04_todo.py fuer echte Aufgaben verwendet.
        "url":   "https://portal.16schwaben.de/a/todo/",
        "app":   "todo",
    })

    ok = fehler = 0
    for abo in abos:
        geraet = (abo["geraet"] or "")[:40]
        try:
            webpush(
                subscription_info={
                    "endpoint": abo["endpoint"],
                    "keys": {"p256dh": abo["p256dh"], "auth": abo["auth"]},
                },
                data=payload,
                vapid_private_key=private_key,
                vapid_claims={"sub": subject},
                # Ohne ttl schickt pywebpush 0 - Microsofts WNS lehnt das mit
                # HTTP 400 ab ("Ttl value conflicts with X-WNS-Cache-Policy").
                # Gleicher Wert wie PUSH_TTL in 00_kern.py.
                ttl=86400,
            )
            print(f"  OK       {geraet}")
            ok += 1
        except WebPushException as e:
            code = e.response.status_code if e.response is not None else "?"
            print(f"  FEHLER   {geraet}  (HTTP {code})")
            if e.response is not None and e.response.status_code in (404, 410):
                # Abgelaufenes Abo - genau wie push_send() es auch aufraeumt,
                # sonst sammeln sich tote Geraete an.
                db.execute("DELETE FROM push_abos WHERE id=?", (abo["id"],))
                db.commit()
                print("           -> abgelaufen, Abo entfernt")
            fehler += 1
    db.close()
    print(f"\n  {ok} zugestellt, {fehler} fehlgeschlagen.")
    if ok:
        print("  Antippen der Meldung muss die Aufgabenliste oeffnen (S6-06).")


def cmd_listapps(_):
    """Nur lesend - offline_faehig ist eine Code-/Deploy-Entscheidung, kein
    per manage.py frei umschaltbares Admin-Setting (siehe 00_kern.py)."""
    db = connect()
    for r in db.execute("SELECT slug, name, offline_faehig FROM apps ORDER BY slug").fetchall():
        status = "offline-faehig" if r["offline_faehig"] else "nur online"
        print(f"  {r['slug']:15} {r['name']:15} {status}")
    db.close()


def cmd_wunsch_neu(args):
    """Einen Wunsch von der Kommandozeile anlegen - IMMER unpriorisiert.

        docker exec portal python manage.py wunsch_neu tvb "Titel" "Text"

    Warum ohne Prioritaet, und zwar ohne Schalter dafuer: Der stuendliche
    Lauf (Wunsch #157) arbeitet alle Wuensche ab, die eine Prioritaet ausser
    'zurueckgestellt' tragen. Ein Befehl, der Wuensche anlegen UND
    priorisieren koennte, waere damit eine Maschine, die sich selbst Arbeit
    auftraegt und sie eine Stunde spaeter ausfuehrt. Prioritaeten vergibt
    ein Mensch, hier und sonst auch (Wunsch #152).

    Der Titel wird mitgegeben statt von der KI geholt: Wer einen Wunsch von
    hier aus anlegt, hat ihn gerade formuliert und weiss besser als ein
    Modell, worum es geht.
    """
    if len(args) < 3:
        sys.exit('Aufruf: wunsch_neu <app-slug> "<titel>" "<text>"')
    app_slug, titel, text = args[0], args[1], args[2]
    db = connect()
    if not db.execute("SELECT 1 FROM apps WHERE slug=?", (app_slug,)).fetchone():
        sys.exit(f"App-Slug '{app_slug}' gibt es nicht.")
    wid = db.execute(
        "INSERT INTO wuensche(text, titel, app_slug, prioritaet) "
        "VALUES(?,?,?,NULL) RETURNING id",
        (text, titel[:80], app_slug)).fetchone()["id"]
    db.commit()
    db.close()
    print(f"#{wid} angelegt (ohne Prioritaet): {titel[:60]}")


def cmd_wunsch_aktion(args):
    """Eine Aktion an einen Wunsch haengen - von der Kommandozeile aus.

        docker exec portal python manage.py wunsch_aktion 188 frage "Woher..."
        docker exec portal python manage.py wunsch_aktion 188 notiz "..." --wer 1

    Warum es das gibt: Rueckfragen sollen laut Wunsch #161 AM WUNSCH stehen,
    nicht in einem Chatverlauf, den ausser mir niemand hat. Ohne diesen Befehl
    landete jede Rueckfrage, die beim Arbeiten entsteht, ausserhalb des
    Systems - genau die Luecke, die #161 schliessen wollte.

    Bei art='frage' geht dieselbe Push-Benachrichtigung raus wie ueber die
    Weboberflaeche (Wunsch #166). Sonst waere eine Rueckfrage von hier aus
    still, und still ist so gut wie gar nicht gestellt.
    """
    if len(args) < 3:
        sys.exit('Aufruf: wunsch_aktion <wunsch-id> <art> "<text>" [--wer <user-id>]')
    wid, art, text = args[0], args[1], args[2]
    wer = None
    if "--wer" in args:
        wer = int(args[args.index("--wer") + 1])

    sys.path.insert(0, str(Path(__file__).parent))
    from app import app
    from teile.kern import get_db, push_send

    with app.app_context():
        db = get_db()
        from teile.werkstatt_app import AKTIONS_ARTEN, _admins_benachrichtigen
        if art not in AKTIONS_ARTEN:
            sys.exit(f"Unbekannte Art '{art}'. Erlaubt: {', '.join(AKTIONS_ARTEN)}")
        if not db.execute("SELECT 1 FROM wuensche WHERE id=?", (wid,)).fetchone():
            sys.exit(f"Wunsch #{wid} gibt es nicht.")
        db.execute(
            "INSERT INTO wunsch_aktionen(wunsch_id, art, text, user_id) VALUES(?,?,?,?)",
            (wid, art, text[:2000], wer))
        db.commit()
        print(f"#{wid}: {AKTIONS_ARTEN[art][0]} {AKTIONS_ARTEN[art][1]} eingetragen.")
        if art == "frage":
            # Absender ist hier niemand aus der Familie - `id` -1 sorgt dafuer,
            # dass die Ausschlussbedingung ("nicht an den Fragesteller selbst")
            # niemanden trifft und ALLE Admins die Frage bekommen.
            _admins_benachrichtigen(db, {"id": -1, "name": "Claude"}, int(wid), text)
            print("  Push an die Admins ausgeloest.")


def cmd_titel_nachtragen(args):
    """Wunsch #187: Ueberschriften fuer Wuensche nachtragen, die keine haben.

    Seit Wunsch #161 bekommt jeder NEUE Wunsch beim Anlegen eine KI-
    Ueberschrift. Aeltere haben keine - das Feature gab es damals nicht.
    Dieser Befehl holt sie nach.

    Aufruf:
        docker exec portal python manage.py titel_nachtragen        # zaehlt nur
        docker exec portal python manage.py titel_nachtragen 5
  docker exec portal python manage.py wunsch_aktion 188 frage "Woher kommen die Zahlen?"
  docker exec portal python manage.py wunsch_neu tvb "Kurzer Titel" "Der ganze Wunschtext"      # die 5 aeltesten
        docker exec portal python manage.py titel_nachtragen alle

    Kostet echte Tokens aus dem Kontingent des jeweiligen Urhebers (rund 160
    je Wunsch, gemessen). Deshalb passiert ohne Zahl NICHTS ausser Zaehlen -
    ein Befehl, der beim ersten Aufruf ein Viertel des Monatskontingents
    verbraucht, waere eine Falle.

    Einzige Stelle, an der manage.py die App-Module benutzt: die KI-Anfrage
    steckt in teile/00_kern.py und braucht einen Flask-Kontext. Sie hier
    nachzubauen hiesse, Modellwahl, Kontingentpruefung und Protokollierung zu
    duplizieren - genau das, was der Rest dieser Datei aus gutem Grund meidet.
    """
    db = connect()
    offen = db.execute(
        "SELECT id, text, user_id, erledigt FROM wuensche "
        "WHERE (titel IS NULL OR titel='') AND user_id IS NOT NULL "
        # Offene zuerst: Wer nur einen Teil nachtraegt, will die Ueberschriften
        # dort, wo er noch liest. Erledigte Wuensche sieht man selten wieder.
        "ORDER BY erledigt ASC, id ASC"
    ).fetchall()
    print(f"Ohne Ueberschrift: {len(offen)} "
          f"({sum(1 for r in offen if not r['erledigt'])} davon offen)")
    if not args:
        print("Zum Nachtragen eine Anzahl angeben, z. B. "
              "'titel_nachtragen 5' oder 'titel_nachtragen alle'.")
        db.close()
        return

    if args[0] == "alle":
        ziel = offen
    else:
        try:
            ziel = offen[:int(args[0])]
        except ValueError:
            sys.exit("Anzahl muss eine Zahl sein oder 'alle'.")
    db.close()

    sys.path.insert(0, str(Path(__file__).parent))
    from app import app
    from teile.kern import ki_anfrage
    from teile.werkstatt import _TITEL_SYSTEM, _TITEL_MAX

    geschafft = 0
    with app.app_context():
        vorher = _tokens_bisher(app)
        for r in ziel:
            try:
                titel = ki_anfrage(r["user_id"], "wunsch_titel", _TITEL_SYSTEM,
                                   r["text"][:2000], max_tokens=40)
            except Exception as fehler:
                print(f"  #{r['id']}: uebersprungen ({fehler})")
                continue
            titel = " ".join((titel or "").split()).strip("\"'„“»« ")[:_TITEL_MAX]
            if not titel:
                continue
            from teile.kern import get_db as _db
            # Nur setzen, wenn immer noch keiner da ist - dieselbe Regel wie im
            # Hintergrund-Thread: ein von Hand vergebener Titel hat Vorrang.
            _db().execute(
                "UPDATE wuensche SET titel=? WHERE id=? AND (titel IS NULL OR titel='')",
                (titel, r["id"]))
            _db().commit()
            geschafft += 1
            print(f"  #{r['id']}: {titel}")
        verbraucht = _tokens_bisher(app) - vorher
    print(f"{geschafft} Ueberschriften nachgetragen, {verbraucht} Tokens verbraucht.")


def _tokens_bisher(app) -> int:
    from teile.kern import get_db as _db
    return _db().execute(
        "SELECT COALESCE(SUM(tokens),0) FROM ki_nutzung WHERE feature='wunsch_titel'"
    ).fetchone()[0]


CMDS = {
    "createadmin":     cmd_createadmin,
    "adduser":         cmd_adduser,
    "addapp":          cmd_addapp,
    "grant":           cmd_grant,
    "listusers":       cmd_listusers,
    "listwuensche":    cmd_listwuensche,
    "listtodos":       cmd_listtodos,
    "wunsch_erledigt": cmd_wunsch_erledigt,
    "titel_nachtragen": cmd_titel_nachtragen,
    "wunsch_aktion":   cmd_wunsch_aktion,
    "wunsch_neu":      cmd_wunsch_neu,
    "backlog":         cmd_backlog,
    "ki_modell":       cmd_ki_modell,
    "ki_stimme":       cmd_ki_stimme,
    "listki":          cmd_listki,
    "listapps":        cmd_listapps,
    "listpush":        cmd_listpush,
    "testpush":        cmd_testpush,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in CMDS:
        print("Bekannte Befehle:", ", ".join(CMDS))
        sys.exit(1)
    CMDS[sys.argv[1]](sys.argv[2:])
