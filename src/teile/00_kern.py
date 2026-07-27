import sqlite3, secrets, logging
from contextlib import contextmanager
from flask import g, current_app, jsonify

log = logging.getLogger("portal.kern")

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
CREATE TABLE IF NOT EXISTS todos (
  id            INTEGER PRIMARY KEY,
  inhalt        TEXT    NOT NULL,
  erstellt_von  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  zugewiesen_an INTEGER REFERENCES users(id) ON DELETE SET NULL,
  privat        INTEGER NOT NULL DEFAULT 0,
  erledigt      INTEGER NOT NULL DEFAULT 0,
  erledigt_am   TEXT,
  erstellt      TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS geholfen_aufgaben (
  id         INTEGER PRIMARY KEY,
  name       TEXT    NOT NULL,
  emoji      TEXT    NOT NULL DEFAULT '👍',
  gewichtung REAL    NOT NULL DEFAULT 1.0,
  aktiv      INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS geholfen_eintraege (
  id          INTEGER PRIMARY KEY,
  aufgabe_id  INTEGER NOT NULL REFERENCES geholfen_aufgaben(id) ON DELETE CASCADE,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  zeitstempel TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

_CORE_APPS = [
    ("home",      "Portal",       "🏠", "Persönliche Startseite"),
    ("admin",     "Verwaltung",   "⚙️", "Admin-Bereich"),
    ("todo",      "Todos",        "✅", "Aufgabenliste"),
    ("werkstatt", "Werkstatt",    "💡", "Verbesserungswünsche"),
    ("geholfen",  "Geholfen",     "🙋", "Geholfen-Protokoll"),
]

_DEFAULT_AUFGABEN = [
    ("Tisch decken",       "🍽️", 1.0),
    ("Tisch abräumen",     "🥣", 1.0),
    ("Wäsche falten",      "🧺", 1.5),
    ("Rasen mähen",        "🌿", 3.0),
    ("Zimmer aufräumen",   "🧹", 2.0),
    ("Einkaufen helfen",   "🛒", 1.5),
    ("Beim Kochen helfen", "🍳", 2.0),
    ("Spülmaschine ein",   "🍳", 1.0),
]


def get_db():
    """Request-scoped DB-Verbindung (WAL, foreign keys)."""
    if "db" not in g:
        db = sqlite3.connect(
            current_app.config["DB_PATH"],
            detect_types=sqlite3.PARSE_DECLTYPES,
            check_same_thread=False,
        )
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        g.db = db
    return g.db


@contextmanager
def new_db():
    """Eigene Verbindung für Hintergrund-Threads – nie g.db verwenden!"""
    db = sqlite3.connect(
        current_app.config["DB_PATH"],
        detect_types=sqlite3.PARSE_DECLTYPES,
        timeout=10,
    )
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    finally:
        db.close()


def grant(token: str, app_slug: str):
    """Gibt Row(id, name, farbe, is_admin, home_token) zurück wenn Token für app_slug gültig, sonst None."""
    db = get_db()
    return db.execute("""
        SELECT u.id, u.name, u.farbe, u.is_admin,
               (SELECT g2.token FROM grants g2
                JOIN apps a2 ON a2.id = g2.app_id
                WHERE g2.user_id = u.id AND a2.slug = 'home') AS home_token
        FROM   grants g
        JOIN   users u ON u.id = g.user_id
        JOIN   apps  a ON a.id = g.app_id
        WHERE  g.token = ? AND a.slug = ?
    """, (token, app_slug)).fetchone()


def new_token() -> str:
    return secrets.token_urlsafe(18)


def push_send(user_id: int, title: str, body: str,
              app_slug: str = "", url: str = "", dedup_key: str = ""):
    """Push-Benachrichtigung an alle Geräte von user_id. Nicht-blockierend (Thread)."""
    import json, threading, sqlite3
    from flask import current_app

    private_key = current_app.config.get("VAPID_PRIVATE_KEY", "")
    subject     = current_app.config.get("VAPID_SUBJECT", "mailto:portal@16schwaben.de")
    db_path     = current_app.config["DB_PATH"]

    if not private_key:
        log.info("push stub (kein VAPID): user=%d %s", user_id, title)
        return

    payload = json.dumps({"title": title, "body": body, "url": url, "app": app_slug})

    def _send():
        from pywebpush import webpush, WebPushException
        try:
            db = sqlite3.connect(db_path)
            db.row_factory = sqlite3.Row
            abos = db.execute(
                "SELECT endpoint, p256dh, auth FROM push_abos WHERE user_id=?",
                (user_id,),
            ).fetchall()
            expired = []
            for abo in abos:
                try:
                    webpush(
                        subscription_info={
                            "endpoint": abo["endpoint"],
                            "keys": {"p256dh": abo["p256dh"], "auth": abo["auth"]},
                        },
                        data=payload,
                        vapid_private_key=private_key,
                        vapid_claims={"sub": subject},
                    )
                except WebPushException as e:
                    log.warning("push failed user=%d: %s", user_id, e)
                    if e.response is not None and e.response.status_code in (404, 410):
                        expired.append(abo["endpoint"])
            if expired:
                for ep in expired:
                    db.execute("DELETE FROM push_abos WHERE endpoint=?", (ep,))
                db.commit()
        except Exception as e:
            log.error("push thread error: %s", e)
        finally:
            try:
                db.close()
            except Exception:
                pass

    threading.Thread(target=_send, daemon=True).start()


def _init_db(app):
    with app.app_context():
        db = sqlite3.connect(app.config["DB_PATH"])
        db.executescript(SCHEMA)
        db.executemany(
            "INSERT OR IGNORE INTO apps(slug,name,emoji,beschreibung) VALUES(?,?,?,?)",
            _CORE_APPS,
        )
        if db.execute("SELECT COUNT(*) FROM geholfen_aufgaben").fetchone()[0] == 0:
            for name, emoji, gew in _DEFAULT_AUFGABEN:
                db.execute(
                    "INSERT INTO geholfen_aufgaben(name,emoji,gewichtung) VALUES(?,?,?)",
                    (name, emoji, gew),
                )
        db.commit()
        db.close()


def init_app(app):
    @app.teardown_appcontext
    def close_db(exc=None):
        db = g.pop("db", None)
        if db:
            db.close()

    _init_db(app)

    @app.route("/health")
    def health():
        get_db().execute("SELECT 1")
        return jsonify(status="ok")
