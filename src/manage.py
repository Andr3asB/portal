"""
CLI zur Ersteinrichtung und Verwaltung des Portals.

Aufruf im Container:
  docker exec portal python manage.py createadmin "Andi" "#3498db"
  docker exec portal python manage.py adduser "Mama" "#e74c3c"
  docker exec portal python manage.py addapp todo "Todos" "✅"
  docker exec portal python manage.py grant 1 todo
  docker exec portal python manage.py listusers
  docker exec portal python manage.py listwuensche
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
        SELECT w.id, w.text, w.app_slug, w.erstellt, w.erledigt, u.name
        FROM   wuensche w LEFT JOIN users u ON u.id = w.user_id
        ORDER  BY w.erstellt DESC
    """).fetchall()
    db.close()
    for r in rows:
        status = "✅" if r["erledigt"] else "⏳"
        who = r["name"] or "anonym"
        app = f" [{r['app_slug']}]" if r["app_slug"] else ""
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
    db.execute("UPDATE wuensche SET erledigt=1 WHERE id=?", (int(args[0]),))
    db.commit()
    db.close()
    print(f"Wunsch #{args[0]} als erledigt markiert.")


def cmd_backlog(_):
    """Alle offenen Wünsche und Todos – Einblick in den Rückstand."""
    db = connect()
    print("=== Offene Wünsche (✨) ===")
    for r in db.execute("""
        SELECT w.id, w.text, w.app_slug, w.erstellt, u.name
        FROM wuensche w LEFT JOIN users u ON u.id = w.user_id
        WHERE w.erledigt=0 ORDER BY w.erstellt
    """).fetchall():
        app = f"[{r['app_slug']}] " if r["app_slug"] else ""
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
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in CMDS:
        print("Bekannte Befehle:", ", ".join(CMDS))
        sys.exit(1)
    CMDS[sys.argv[1]](sys.argv[2:])
