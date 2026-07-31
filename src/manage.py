"""
CLI zur Ersteinrichtung und Verwaltung des Portals.

Aufruf im Container:
  docker exec portal python manage.py createadmin "Andi" "#3498db"
  docker exec portal python manage.py adduser "Mama" "#e74c3c"
  docker exec portal python manage.py addapp todo "Todos" "✅"
  docker exec portal python manage.py grant 1 todo
  docker exec portal python manage.py listusers
  docker exec portal python manage.py listwuensche
  docker exec portal python manage.py ki_modell rezepte_import "anthropic/claude-haiku-4.5"
  docker exec portal python manage.py ki_stimme Latein "google/gemini-3.1-flash-tts-preview" "Kore"
  docker exec portal python manage.py listki
"""
import os, sys, sqlite3, secrets
from pathlib import Path

DB = Path(os.environ.get("DB_PATH", "/data/portal.db"))

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
  id      INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id)  ON DELETE CASCADE,
  app_id  INTEGER NOT NULL REFERENCES apps(id)   ON DELETE CASCADE,
  token   TEXT    UNIQUE NOT NULL,
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
    token = secrets.token_urlsafe(18)
    db.execute(
        "INSERT OR IGNORE INTO grants(user_id,app_id,token) VALUES(?,?,?)",
        (user_id, app_id, token),
    )
    db.commit()
    return db.execute(
        "SELECT token FROM grants WHERE user_id=? AND app_id=?", (user_id, app_id)
    ).fetchone()["token"]


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
    print(f"Grant erteilt. URL: https://portal.16schwaben.de/a/{app_slug}/{token}/")


def cmd_listusers(_):
    db = connect()
    rows = db.execute("""
        SELECT u.id, u.name, u.farbe, u.is_admin,
               g.token, a.slug
        FROM   users u
        LEFT   JOIN grants g ON g.user_id = u.id
        LEFT   JOIN apps   a ON a.id = g.app_id AND a.slug = 'home'
    """).fetchall()
    db.close()
    for r in rows:
        admin = " [Admin]" if r["is_admin"] else ""
        token = r["token"] or "(kein Token)"
        print(f"  ID {r['id']:3}  {r['name']}{admin}  {r['farbe']}  → /p/{token}")


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
    if not args:
        sys.exit("Verwendung: wunsch_erledigt <id>")
    db = connect()
    db.execute(
        "UPDATE wuensche SET erledigt=1, erledigt_am=CURRENT_TIMESTAMP WHERE id=?", (int(args[0]),)
    )
    db.commit()
    db.close()
    print(f"Wunsch #{args[0]} als erledigt markiert.")


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


CMDS = {
    "createadmin":     cmd_createadmin,
    "adduser":         cmd_adduser,
    "addapp":          cmd_addapp,
    "grant":           cmd_grant,
    "listusers":       cmd_listusers,
    "listwuensche":    cmd_listwuensche,
    "listtodos":       cmd_listtodos,
    "wunsch_erledigt": cmd_wunsch_erledigt,
    "backlog":         cmd_backlog,
    "ki_modell":       cmd_ki_modell,
    "ki_stimme":       cmd_ki_stimme,
    "listki":          cmd_listki,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in CMDS:
        print("Bekannte Befehle:", ", ".join(CMDS))
        sys.exit(1)
    CMDS[sys.argv[1]](sys.argv[2:])
