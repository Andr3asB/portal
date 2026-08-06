import sqlite3, secrets, logging, base64, hashlib, hmac
from contextlib import contextmanager
from datetime import date, timedelta
from flask import g, current_app, jsonify, request

log = logging.getLogger("portal.kern")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id        INTEGER PRIMARY KEY,
  name      TEXT    NOT NULL,
  farbe     TEXT    NOT NULL DEFAULT '#4a90d9',
  is_admin  INTEGER NOT NULL DEFAULT 0,
  ki_key    TEXT,
  dark_mode INTEGER NOT NULL DEFAULT 0,
  rolle     TEXT    NOT NULL DEFAULT 'gast'
);
CREATE TABLE IF NOT EXISTS apps (
  id             INTEGER PRIMARY KEY,
  slug           TEXT    UNIQUE NOT NULL,
  name           TEXT    NOT NULL,
  emoji          TEXT    NOT NULL DEFAULT '📱',
  beschreibung   TEXT,
  offline_faehig INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS grants (
  id           INTEGER PRIMARY KEY,
  user_id      INTEGER NOT NULL REFERENCES users(id)  ON DELETE CASCADE,
  app_id       INTEGER NOT NULL REFERENCES apps(id)   ON DELETE CASCADE,
  token_lookup TEXT    UNIQUE NOT NULL,
  token_enc    TEXT    NOT NULL,
  UNIQUE(user_id, app_id)
);
CREATE TABLE IF NOT EXISTS sitzungen (
  id             INTEGER PRIMARY KEY,
  user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kennung_lookup TEXT    UNIQUE NOT NULL,
  erstellt       TEXT    NOT NULL DEFAULT (datetime('now')),
  gesehen        TEXT,
  ablauf         TEXT,
  quelle         TEXT,
  geraet         TEXT
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
CREATE TABLE IF NOT EXISTS todo_serien (
  id               INTEGER PRIMARY KEY,
  inhalt           TEXT    NOT NULL,
  wiederkehr_typ   TEXT    NOT NULL DEFAULT 'intervall',
  intervall_tage   INTEGER,
  fester_wochentag INTEGER,
  feste_wochentage TEXT,
  aktiv            INTEGER NOT NULL DEFAULT 1,
  erstellt_von     INTEGER REFERENCES users(id) ON DELETE SET NULL,
  erstellt         TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS todo_historie (
  id            INTEGER PRIMARY KEY,
  todo_id       INTEGER NOT NULL REFERENCES todos(id) ON DELETE CASCADE,
  alter_inhalt  TEXT    NOT NULL,
  geaendert_von INTEGER REFERENCES users(id) ON DELETE SET NULL,
  geaendert_am  TEXT    NOT NULL DEFAULT (datetime('now'))
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
CREATE TABLE IF NOT EXISTS einkauf_laeden (
  id    INTEGER PRIMARY KEY,
  name  TEXT    NOT NULL UNIQUE,
  aktiv INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS einkauf_eintraege (
  id           INTEGER PRIMARY KEY,
  name         TEXT    NOT NULL,
  kategorie    TEXT    NOT NULL DEFAULT 'Sonstiges',
  angebot      INTEGER NOT NULL DEFAULT 0,
  laden_id     INTEGER REFERENCES einkauf_laeden(id) ON DELETE SET NULL,
  erledigt     INTEGER NOT NULL DEFAULT 0,
  erledigt_am  TEXT,
  erstellt     TEXT    NOT NULL DEFAULT (datetime('now')),
  erstellt_von INTEGER REFERENCES users(id) ON DELETE SET NULL,
  geaendert    TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS einkauf_eintrag_laeden (
  eintrag_id INTEGER NOT NULL REFERENCES einkauf_eintraege(id) ON DELETE CASCADE,
  laden_id   INTEGER NOT NULL REFERENCES einkauf_laeden(id) ON DELETE CASCADE,
  PRIMARY KEY (eintrag_id, laden_id)
);
CREATE TABLE IF NOT EXISTS packlisten_ziele (
  id    INTEGER PRIMARY KEY,
  name  TEXT    NOT NULL UNIQUE,
  aktiv INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS packlisten_kategorien (
  id       INTEGER PRIMARY KEY,
  name     TEXT    NOT NULL UNIQUE,
  position INTEGER NOT NULL DEFAULT 0,
  aktiv    INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS packlisten_eintraege (
  id           INTEGER PRIMARY KEY,
  name         TEXT    NOT NULL,
  ziel_id      INTEGER NOT NULL REFERENCES packlisten_ziele(id) ON DELETE CASCADE,
  kategorie_id INTEGER REFERENCES packlisten_kategorien(id),
  person_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
  gepackt      INTEGER NOT NULL DEFAULT 0,
  gepackt_am   TEXT,
  erstellt     TEXT    NOT NULL DEFAULT (datetime('now')),
  erstellt_von INTEGER REFERENCES users(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS packlisten_nutzer_ziel (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  ziel_id INTEGER NOT NULL REFERENCES packlisten_ziele(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS home_gruppen (
  id       INTEGER PRIMARY KEY,
  user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name     TEXT    NOT NULL,
  position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS rezepte (
  id           INTEGER PRIMARY KEY,
  name         TEXT    NOT NULL,
  portionen    TEXT,
  kategorie    TEXT,
  quelle_url   TEXT,
  erstellt_von INTEGER REFERENCES users(id) ON DELETE SET NULL,
  erstellt     TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS rezept_zutaten (
  id        INTEGER PRIMARY KEY,
  rezept_id INTEGER NOT NULL REFERENCES rezepte(id) ON DELETE CASCADE,
  name      TEXT    NOT NULL,
  position  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS rezept_schritte (
  id        INTEGER PRIMARY KEY,
  rezept_id INTEGER NOT NULL REFERENCES rezepte(id) ON DELETE CASCADE,
  text      TEXT    NOT NULL,
  position  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS rezept_bewertungen (
  id        INTEGER PRIMARY KEY,
  rezept_id INTEGER NOT NULL REFERENCES rezepte(id) ON DELETE CASCADE,
  user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  sterne    INTEGER NOT NULL,
  erstellt  TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE(rezept_id, user_id)
);
CREATE TABLE IF NOT EXISTS rezept_wuensche (
  id        INTEGER PRIMARY KEY,
  rezept_id INTEGER NOT NULL REFERENCES rezepte(id) ON DELETE CASCADE,
  user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  erstellt  TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE(rezept_id, user_id)
);
CREATE TABLE IF NOT EXISTS essensplan_eintraege (
  id           INTEGER PRIMARY KEY,
  tag          TEXT    NOT NULL,
  mahlzeit     TEXT    NOT NULL DEFAULT 'abend',
  rezept_id    INTEGER REFERENCES rezepte(id) ON DELETE SET NULL,
  text         TEXT,
  erstellt_von INTEGER REFERENCES users(id) ON DELETE SET NULL,
  erstellt     TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE(tag, mahlzeit)
);
CREATE TABLE IF NOT EXISTS einkauf_kategorien (
  id       INTEGER PRIMARY KEY,
  name     TEXT    NOT NULL UNIQUE,
  position INTEGER NOT NULL DEFAULT 0,
  aktiv    INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS kinderplan_eintraege (
  id         INTEGER PRIMARY KEY,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  aufgabe_id INTEGER NOT NULL REFERENCES geholfen_aufgaben(id) ON DELETE CASCADE,
  wochentag  INTEGER NOT NULL,
  plan_tag   TEXT,
  position   INTEGER NOT NULL DEFAULT 0,
  erstellt   TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE(user_id, aufgabe_id, plan_tag)
);
CREATE TABLE IF NOT EXISTS ki_nutzung (
  id       INTEGER PRIMARY KEY,
  user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  feature  TEXT    NOT NULL,
  tokens   INTEGER NOT NULL DEFAULT 0,
  erstellt TEXT    NOT NULL DEFAULT (datetime('now'))
);
-- Wunsch #136: eigene, zeichenbasierte Tabelle statt einer weiteren Zeile in
-- ki_nutzung. ki_anfrage() summiert dort SUM(tokens) UEBER ALLE Features
-- hinweg (Absicht: ein gemeinsames Kontingent) - TTS-Zeichen in dieselbe
-- Spalte zu schreiben wuerde das LLM-Token-Kontingent stillschweigend mit
-- Zeichenzahlen verfaelschen.
CREATE TABLE IF NOT EXISTS ki_tts_nutzung (
  id       INTEGER PRIMARY KEY,
  user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  feature  TEXT    NOT NULL,
  zeichen  INTEGER NOT NULL DEFAULT 0,
  erstellt TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS tierbaukasten_kreationen (
  id                INTEGER PRIMARY KEY,
  user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  tier_typ          TEXT    NOT NULL,
  koerper_farbe     TEXT    NOT NULL DEFAULT '#e8b04b',
  muster            TEXT,
  muster_farbe      TEXT,
  accessoire        TEXT,
  koerperbau        INTEGER NOT NULL DEFAULT 50,
  dicebear_optionen TEXT,
  name              TEXT,
  erstellt          TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS vokabel_sprachen (
  id    INTEGER PRIMARY KEY,
  name  TEXT    NOT NULL UNIQUE,
  aktiv INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS vokabel_sprachen_nutzer (
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  sprache_id INTEGER NOT NULL REFERENCES vokabel_sprachen(id) ON DELETE CASCADE,
  UNIQUE(user_id, sprache_id)
);
CREATE TABLE IF NOT EXISTS vokabel_kapitel (
  id       INTEGER PRIMARY KEY,
  user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name     TEXT    NOT NULL,
  aktiv    INTEGER NOT NULL DEFAULT 1,
  erstellt TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS vokabeln (
  id         INTEGER PRIMARY KEY,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  sprache_id INTEGER NOT NULL REFERENCES vokabel_sprachen(id) ON DELETE CASCADE,
  fremd      TEXT    NOT NULL,
  deutsch    TEXT    NOT NULL,
  erstellt   TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS vokabel_kapitel_zuordnung (
  vokabel_id INTEGER NOT NULL REFERENCES vokabeln(id) ON DELETE CASCADE,
  kapitel_id INTEGER NOT NULL REFERENCES vokabel_kapitel(id) ON DELETE CASCADE,
  UNIQUE(vokabel_id, kapitel_id)
);
CREATE TABLE IF NOT EXISTS vokabel_sessions (
  id         INTEGER PRIMARY KEY,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  sprache_id INTEGER NOT NULL REFERENCES vokabel_sprachen(id) ON DELETE CASCADE,
  gestartet  TEXT    NOT NULL DEFAULT (datetime('now')),
  beendet    TEXT
);
CREATE TABLE IF NOT EXISTS vokabel_versuche (
  id          INTEGER PRIMARY KEY,
  session_id  INTEGER NOT NULL REFERENCES vokabel_sessions(id) ON DELETE CASCADE,
  vokabel_id  INTEGER NOT NULL REFERENCES vokabeln(id) ON DELETE CASCADE,
  richtig     INTEGER NOT NULL,
  beantwortet TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS ki_konfiguration (
  zweck  TEXT PRIMARY KEY,
  modell TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ki_stimmen (
  sprache_id INTEGER PRIMARY KEY REFERENCES vokabel_sprachen(id) ON DELETE CASCADE,
  modell     TEXT NOT NULL,
  stimme     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tvb_spiele (
  id              TEXT PRIMARY KEY,
  spieltag        TEXT,
  heim            TEXT    NOT NULL,
  gast            TEXT    NOT NULL,
  heim_tore       INTEGER,
  gast_tore       INTEGER,
  anstoss         TEXT    NOT NULL,
  ort             TEXT,
  status          TEXT    NOT NULL,
  aktualisiert_am TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS tvb_mannschaften (
  team_id         TEXT PRIMARY KEY,
  name            TEXT    NOT NULL,
  liga            TEXT,
  kurz            TEXT    NOT NULL,
  altersklasse    TEXT,
  turnier_id      TEXT,
  position        INTEGER NOT NULL DEFAULT 0,
  ist_profi       INTEGER NOT NULL DEFAULT 0,
  aktualisiert_am TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS tvb_ausgeblendet (
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  altersklasse TEXT    NOT NULL,
  PRIMARY KEY (user_id, altersklasse)
);
CREATE TABLE IF NOT EXISTS tvb_kader (
  spieler_id      INTEGER PRIMARY KEY,
  vorname         TEXT    NOT NULL,
  nachname        TEXT    NOT NULL,
  position        TEXT,
  hpi_schnitt     REAL,
  hpi_bestwert    REAL,
  hpi_letzter     REAL,
  hpi_trend       INTEGER,
  spieltage       INTEGER,
  aktionen        INTEGER,
  saison_name     TEXT    NOT NULL,
  aktualisiert_am TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

_DEFAULT_SPRACHEN = ["Englisch", "Latein", "Dänisch", "Italienisch", "Französisch"]

_CORE_APPS = [
    ("home",        "Portal",       "🏠", "Persönliche Startseite"),
    ("admin",       "Verwaltung",   "⚙️", "Admin-Bereich"),
    ("todo",        "Aufgaben",     "✅", "Aufgabenliste"),
    ("werkstatt",   "Werkstatt",    "💡", "Verbesserungswünsche"),
    ("geholfen",    "Geholfen",     "🙋", "Geholfen-Protokoll"),
    ("einkauf",     "Einkauf",      "🛒", "Gemeinsame Einkaufsliste"),
    ("hilfe",       "Hilfe",        "❓", "Erklärungen und Tipps"),
    ("rezepte",     "Rezepte",      "🍲", "Lieblingsrezepte mit Zutaten und Zubereitung"),
    ("essensplan",  "Essensplan",   "🍽️", "Wochenplan fürs Essen"),
    ("kinderplan",  "Aufgabenplan", "🗓️", "Wiederkehrende Aufgaben wochentagsweise planen"),
    # Die fünf unten fehlten hier bis Wunsch #140, Stufe 4. Auf dem laufenden
    # Server gibt es sie längst - sie wurden seinerzeit von Hand über
    # `manage.py addapp` angelegt und nie nachgetragen. Auf einer FRISCHEN
    # Datenbank hätten die zugehörigen Module deshalb Routen registriert, für
    # die es gar keine App zum Freischalten gibt. Aufgefallen ist das erst,
    # als der Rauchtest aus tests/ eine leere Test-DB aufbaute.
    # `INSERT OR IGNORE` lässt die vorhandenen Zeilen unangetastet; Name und
    # Emoji sind exakt die der Produktivdatenbank.
    ("sportschau",    "Sportschau",    "🏃", None),
    ("tierbaukasten", "Tierbaukasten", "🐾", None),
    ("vokabeln",      "Vokabeln",      "📚", None),
    ("packliste",     "Packliste",     "🧳", None),
    ("tvb",           "TVB",           "🤾", None),
]

_DEFAULT_LAEDEN = ["Edeka", "Rewe", "Lidl", "Kaufland", "Aldi", "DM", "Müller", "Penny"]

_DEFAULT_KATEGORIEN = [
    "Obst & Gemüse", "Kühlregal", "Wurst & Käse", "Trockenvorrat", "TK", "Convenience", "Sonstiges",
]

_DEFAULT_PACKLISTEN_KATEGORIEN = [
    "Anreise", "Kleidung", "Bad & Hygiene", "FeWo-Küche",
    "Reiseapotheke", "Technik", "Freizeit", "Sonstiges",
]

_DEFAULT_AUFGABEN = [
    ("Tisch decken",           "🍽️", 1.0),
    ("Tisch abräumen",         "🥣", 1.0),
    ("Wäsche zusammenlegen",   "🧺", 1.5),
    ("Rasen mähen",            "🌿", 3.0),
    ("Zimmer aufräumen",       "🧹", 2.0),
    ("Einkaufen helfen",       "🛒", 1.5),
    ("Beim Kochen helfen",     "🍳", 2.0),
    ("Spülmaschine einräumen", "🍳", 1.0),
    ("Spülmaschine ausräumen", "🍳", 1.0),
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


# Wunsch #140: Basis-Abfrage für die Nutzerdaten. home_enc/hilfe_enc liefern
# die Navigations-Tokens, die base.html auf jeder Seite braucht.
_NUTZER_SELECT = """
    SELECT u.id, u.name, u.farbe, u.is_admin, u.dark_mode, u.rolle,
           (SELECT g2.token_enc FROM grants g2
            JOIN apps a2 ON a2.id = g2.app_id
            WHERE g2.user_id = u.id AND a2.slug = 'home') AS home_enc,
           (SELECT g3.token_enc FROM grants g3
            JOIN apps a3 ON a3.id = g3.app_id
            WHERE g3.user_id = u.id AND a3.slug = 'hilfe') AS hilfe_enc
    FROM   users u
"""

SITZUNG_COOKIE = "portal_sitzung"
# Bewusst nicht "session": Flasks eigenes Cookie heisst so.


def _nutzer_aufbereiten(row):
    """DB-Zeile -> dict mit entschlüsselten Navigations-Tokens."""
    daten = dict(row)
    daten["home_token"]  = token_entschluesseln(daten.pop("home_enc"))
    daten["hilfe_token"] = token_entschluesseln(daten.pop("hilfe_enc"))
    return daten


def sitzung_nutzer_id(db=None):
    """Wunsch #140: Nutzer-ID zur mitgesendeten Sitzung, sonst None.

    Liegt hier und nicht im Sitzungsmodul, weil `grant()` sie braucht - und
    ein Import in die andere Richtung wäre ein Ringschluss. Das Sitzungsmodul
    holt sich diese Funktion umgekehrt von hier."""
    from flask import request
    wert = request.cookies.get(SITZUNG_COOKIE)
    if not wert:
        return None
    db = db or get_db()
    zeile = db.execute("""
        SELECT user_id FROM sitzungen
        WHERE kennung_lookup = ?
          AND (ablauf IS NULL OR ablauf > datetime('now'))
    """, (token_lookup(wert),)).fetchone()
    return zeile["user_id"] if zeile else None


def grant(token: str, app_slug: str):
    """Gibt dict(id, name, farbe, is_admin, home_token, hilfe_token, ...) zurück
    wenn der Zugriff erlaubt ist, sonst None.

    Zwei Wege, in dieser Reihenfolge:

    1. **Pfad-Token** (wie bisher). Er hat IMMER Vorrang - das ist die
       Sicherheitszusage des ganzen Umbaus: solange der Token gilt, kann kein
       Fehler in der Cookie-Logik jemanden aussperren, und auf einem geteilten
       Gerät gewinnt der Link, den man gerade geöffnet hat, gegen das Cookie
       des zuletzt Angemeldeten.
       Ein ANGEGEBENER, aber ungültiger Token fällt bewusst NICHT aufs Cookie
       zurück - sonst würde ein widerrufener Zugang stillschweigend weiter
       funktionieren, solange das Cookie noch lebt.
    2. **Sitzungs-Cookie** (Wunsch #140, Stufe 3), nur wenn gar kein Token in
       der Adresse steht und der Schalter SITZUNG_KONSUMIEREN an ist. Der
       Nutzer muss auch dann einen Grant für diese App haben - das Cookie
       weitet die Berechtigungen nicht aus, es ersetzt nur den Nachweis.

    Wunsch #129: Gesucht wird über token_lookup (HMAC), die Navigations-Tokens
    kommen verschlüsselt aus der DB. Rückgabe ist ein dict statt einer
    sqlite3.Row, weil diese Felder nachbearbeitet werden; für Aufrufer
    verhält sich beides gleich (user["id"] wie user.home_token in Jinja)."""
    db = get_db()

    if token:
        row = db.execute(_NUTZER_SELECT + """
            JOIN   grants g ON g.user_id = u.id
            JOIN   apps   a ON a.id = g.app_id
            WHERE  g.token_lookup = ? AND a.slug = ?
        """, (token_lookup(token), app_slug)).fetchone()
        if not row:
            return None
        daten = _nutzer_aufbereiten(row)
        sitzung_vormerken(daten["id"])
        return daten

    if not sitzung_konsumieren_an():
        return None
    user_id = sitzung_nutzer_id(db)
    if user_id is None:
        return None
    row = db.execute(_NUTZER_SELECT + """
        WHERE  u.id = ?
          AND  EXISTS (SELECT 1 FROM grants g JOIN apps a ON a.id = g.app_id
                       WHERE g.user_id = u.id AND a.slug = ?)
    """, (user_id, app_slug)).fetchone()
    return _nutzer_aufbereiten(row) if row else None


def sitzung_konsumieren_an() -> bool:
    """Schalter für Stufe 3. Aus = das Cookie autorisiert nicht."""
    return str(current_app.config.get("SITZUNG_KONSUMIEREN", "")).strip() in ("1", "true", "ja")


def sitzung_vormerken(user_id: int):
    """Wunsch #140, Stufe 1: Merkt an, dass in diesem Request ein Pfad-Token
    erfolgreich aufgelöst wurde. `19_sitzung.py` stellt daraufhin am Ende des
    Requests ein Sitzungs-Cookie aus - aber nur, wenn der Schalter an ist und
    noch keines mitkam.

    Bewusst hier und nicht im Sitzungsmodul: `grant()` und `_home_user()` sind
    die einzigen beiden Stellen, an denen ein Pfad-Token zu einer Identität
    wird. Wer eine dritte baut, muss diese Zeile mitnehmen."""
    try:
        g.sitzung_fuer = user_id
    except RuntimeError:
        # Kein Request-Kontext (z. B. Aufruf aus manage.py) - dann gibt es
        # auch keine Antwort, an die sich ein Cookie hängen liesse.
        pass


def aktueller_nutzer(token: str = None):
    """Nutzer für die vier Endpunkte OHNE <token> im Pfad, sonst None.

    Betrifft `/wunsch`, `/push/subscribe`, `/push/unsubscribe` und
    `/settings/darkmode`. Die holen ihren Token seit jeher aus dem JSON-Body
    und prüfen ihn gegen IRGENDEINEN Grant - sie hängen nicht an einer
    bestimmten App, weil sie von jeder Seite aus aufgerufen werden.

    Wunsch #140, Stufe 4: Auf einer token-freien Seite ist `TOKEN` im
    Javascript leer, der Body trägt also keinen Token mehr. Ohne diese
    Zweitchance über das Sitzungs-Cookie wären ausgerechnet Dark Mode,
    Push-Anmeldung und das Wunsch-Formular die einzigen Dinge, die nach dem
    Umbau still nicht mehr funktionieren - und "still" ist hier das Problem:
    ein 403 auf `/settings/darkmode` fällt niemandem auf, bis sich jemand
    wundert, warum der Schalter nichts tut.

    Reihenfolge und Begründung wie in grant(): Pfad- bzw. Body-Token hat
    Vorrang, ein angegebener aber ungültiger Token fällt NICHT aufs Cookie
    zurück."""
    db = get_db()

    if token:
        row = db.execute(
            _NUTZER_SELECT + " JOIN grants g ON g.user_id = u.id"
                             " WHERE g.token_lookup = ?",
            (token_lookup(token),)
        ).fetchone()
        if not row:
            return None
        daten = _nutzer_aufbereiten(row)
        sitzung_vormerken(daten["id"])
        return daten

    if not sitzung_konsumieren_an():
        return None
    user_id = sitzung_nutzer_id(db)
    if user_id is None:
        return None
    row = db.execute(_NUTZER_SELECT + " WHERE u.id = ?", (user_id,)).fetchone()
    return _nutzer_aufbereiten(row) if row else None


# ---------------------------------------------------------------------------
# Wunsch #140, Stufe 4: Adressen ohne Token bauen.
#
# Jede Route hat seit Stufe 4 zwei Regeln - mit und ohne `<token>` im Pfad.
# Welche die Vorlagen verlinken, entscheidet allein der Schalter
# TOKENFREIE_URLS. Das ist der Notausstieg: steht er auf 0, verlinkt das
# Portal wieder wie vorher mit Token in der Adresse, ohne Rebuild.
#
# Die Helfer unten sind bewusst die EINZIGE Stelle, an der dieser Unterschied
# gemacht wird. Wer eine Adresse von Hand zusammensetzt, umgeht den Schalter.

def tokenfreie_urls_an() -> bool:
    """Schalter für Stufe 4. Aus = Adressen tragen den Token wie bisher."""
    return str(current_app.config.get("TOKENFREIE_URLS", "")).strip() in ("1", "true", "ja")


def token_pfad(token) -> str:
    """Das Wegstück zwischen App-Präfix und Unterseite: '/tok/' oder '/'.

    Damit wird aus `/a/todo/{{ token }}/neu` in den Vorlagen einheitlich
    `/a/todo{{ tp }}neu` - beide Formen kommen aus derselben Zeile."""
    if not token or tokenfreie_urls_an():
        return "/"
    return f"/{token}/"


def app_pfad(slug: str, token=None) -> str:
    """Einstieg in eine App - für Links über App-Grenzen hinweg.

    Nötig, weil `tp` immer den Token der GERADE offenen App liefert. Die
    App-Kacheln der Startseite und der Hilfe-Knopf im Menü zeigen aber
    woandershin und brauchen den Token des jeweils anderen Grants."""
    return f"/a/{slug}{token_pfad(token)}"


def start_pfad(home_token=None) -> str:
    """Die persönliche Startseite - Ziel des ⌂-Knopfes auf jeder Seite."""
    if not home_token or tokenfreie_urls_an():
        return "/start"
    return f"/p/{home_token}"


def manifest_pfad(home_token=None) -> str:
    """PWA-Manifest. Token-frei hängt es am Sitzungs-Cookie - dafür braucht
    das <link>-Tag zusätzlich crossorigin="use-credentials", sonst holt der
    Browser das Manifest ohne Cookies und bekäme 404 (siehe base.html)."""
    if not home_token or tokenfreie_urls_an():
        return "/manifest.json"
    return f"/manifest/{home_token}.json"


def grant_werte(token: str):
    """(token_lookup, token_enc) für ein neues Token - zum Einfügen in grants."""
    return token_lookup(token), token_verschluesseln(token)


def new_token() -> str:
    return secrets.token_urlsafe(18)


# ---------------------------------------------------------------------------
# Wunsch #129: Zugangstokens nicht mehr im Klartext in der Datenbank.
#
# Der Wunsch verlangte woertlich einen HASH. Das geht hier NICHT: die
# Navigation braucht die Tokens im Klartext zurueck. base.html baut auf JEDER
# Seite den ⌂-Knopf aus `home_token` und den Hilfe-Link aus `hilfe_token`, und
# die Startseite erzeugt jede App-Kachel aus dem Token des jeweiligen Grants.
# Ein Einweg-Hash liesse sich nicht zuruecklesen - die komplette Navigation
# waere tot. (Mit dem Cookie-Modell aus Wunsch #140 waere echtes Hashing
# moeglich; das ist zurueckgestellt.)
#
# Umgesetzt ist deshalb das, worum es dem Wunsch inhaltlich ging - "ein
# geleaktes Backup darf keinen Vollzugriff geben": die Tokens liegen
# VERSCHLUESSELT in der DB, der Schluessel steht in der .env. Das taegliche
# NAS-Backup sichert nur /data, die .env liegt darueber in
# /srv/familienportal und ist deshalb NICHT im Backup enthalten - ein
# abhandengekommenes Backup ist damit wertlos.
#
# Zwei Spalten je Grant, weil Suchen und Zurueckgewinnen verschiedene Dinge
# sind:
#   token_lookup - HMAC-SHA256(Schluessel, Token), deterministisch. Nur dafuer
#                  da, die Zeile zu FINDEN (WHERE token_lookup = ?). Ohne den
#                  Schluessel nicht nachrechenbar, also auch kein Abgleich
#                  gegen eine Liste geratener Tokens.
#   token_enc    - AES-GCM(Token), zufaelliges Nonce. Nur dafuer da, den
#                  Klartext fuer Links und QR-Codes zurueckzubekommen.
#
# WICHTIG FUER DEN BETRIEB: Ohne TOKEN_KEY aus der .env kommt niemand mehr
# rein. Die .env gehoert deshalb an einen zweiten sicheren Ort (Passwort-
# manager) - ein wiederhergestelltes /data-Backup allein reicht NICHT.
# ---------------------------------------------------------------------------

def _token_key() -> bytes:
    key_b64 = current_app.config.get("TOKEN_KEY", "")
    if not key_b64:
        raise RuntimeError(
            "TOKEN_KEY fehlt in der .env - ohne den Schluessel sind die "
            "Zugangstokens nicht lesbar. Siehe .env.example.")
    return base64.urlsafe_b64decode(key_b64)


def token_lookup(token: str, key: bytes = None) -> str:
    """Deterministischer Suchwert zu einem Token (HMAC, nicht umkehrbar)."""
    key = key if key is not None else _token_key()
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()


def token_verschluesseln(token: str, key: bytes = None) -> str:
    """Token -> base64(Nonce + Geheimtext), AES-GCM."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = key if key is not None else _token_key()
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, token.encode(), None)
    return base64.urlsafe_b64encode(nonce + ct).decode()


def token_entschluesseln(blob: str, key: bytes = None) -> str:
    """Umkehrung von token_verschluesseln. Leerer String bei kaputtem Wert,
    damit ein einzelner defekter Grant nicht die ganze Seite zerlegt."""
    if not blob:
        return ""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = key if key is not None else _token_key()
    try:
        raw = base64.urlsafe_b64decode(blob)
        return AESGCM(key).decrypt(raw[:12], raw[12:], None).decode()
    except Exception:
        log.error("Token konnte nicht entschluesselt werden - falscher TOKEN_KEY?")
        return ""


def to_int(value, default=None):
    """Wandelt value in int um; bei ungültiger Eingabe -> default (kein Crash)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def bereinige_erfuellte_rezeptwuensche(db):
    """Wunsch #65: Wenn ein gewünschtes Rezept inzwischen auf dem Essensplan
    stand UND dieser Tag vorbei ist, gilt der Wunsch als erfüllt und wird
    entfernt. Nur Wünsche, die VOR (oder am selben Tag wie) der Essensplan-
    Eintragung entstanden sind, zählen als „durch dieses Servieren erfüllt“ –
    ein neuer Wunsch fürs selbe Rezept danach bleibt unangetastet, bis es
    erneut serviert wird."""
    db.execute("""
        DELETE FROM rezept_wuensche
        WHERE EXISTS (
            SELECT 1 FROM essensplan_eintraege e
            WHERE e.rezept_id = rezept_wuensche.rezept_id
              AND e.tag < date('now')
              AND rezept_wuensche.erstellt <= e.tag
        )
    """)
    db.commit()


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


# Standard-Modell, falls fuer einen Zweck keine Zeile in ki_konfiguration
# existiert. Wunsch #81 macht das zum Grundprinzip fuer ALLE KI-Anwendungen:
# das tatsaechlich verwendete Modell steht in der DB (ki_konfiguration /
# ki_stimmen), nicht fest im Code - per manage.py aenderbar, ohne Deploy,
# falls sich die Modell-Landschaft weiterentwickelt.
KI_MODELL = "anthropic/claude-haiku-4.5"

# TTS ueber OpenRouters /audio/speech-Endpoint (Wunsch #81). Gemini 3.1 Flash
# TTS deckt 70+ Sprachen ab (u.a. alle aktuellen Vokabeln-Sprachen inkl.
# Latein/Daenisch, die guenstigere Modelle wie Kokoro nicht abdecken) - bei
# kurzen Einzelwoertern ist der Preisunterschied ohnehin vernachlaessigbar,
# da jedes Wort nur einmal erzeugt und dann dauerhaft im Datenordner
# gecacht wird. "Kore" ist eine neutrale Standardstimme.
TTS_STANDARD_MODELL = "google/gemini-3.1-flash-tts-preview"
TTS_STANDARD_STIMME = "Kore"


class KiLimitError(Exception):
    """Monatliches Token-Kontingent des Nutzers ist aufgebraucht."""


class KiFehler(Exception):
    """Allgemeiner Fehler beim KI-Aufruf (kein Key, Netzwerk, ungültige Antwort)."""


def ki_modell_fuer(zweck: str) -> str:
    """Modellwahl je Verwendungszweck (Wunsch #81 - Grundprinzip): schaut in
    ki_konfiguration nach, faellt auf KI_MODELL zurueck, wenn dort nichts
    hinterlegt ist. `zweck` ist dieselbe Zeichenkette wie ki_anfrage()s
    `feature` (z.B. "rezepte_import"), damit kein zweiter Bezeichner noetig ist."""
    db = get_db()
    row = db.execute("SELECT modell FROM ki_konfiguration WHERE zweck=?", (zweck,)).fetchone()
    return row["modell"] if row else KI_MODELL


def ki_stimme_fuer(sprache_id: int):
    """(modell, stimme) fuers TTS einer Vokabel-Sprache (Wunsch #81) - je
    Sprache in ki_stimmen hinterlegt, austauschbar ohne Code-Aenderung."""
    db = get_db()
    row = db.execute(
        "SELECT modell, stimme FROM ki_stimmen WHERE sprache_id=?", (sprache_id,)
    ).fetchone()
    if row:
        return row["modell"], row["stimme"]
    return TTS_STANDARD_MODELL, TTS_STANDARD_STIMME


def ki_anfrage(user_id: int, feature: str, system: str, prompt: str, max_tokens: int = 1500,
               bilder=None) -> str:
    """Generischer KI-Aufruf über OpenRouter – von jedem KI-Feature verwendbar.

    Kontingent ist pro Nutzer und Kalendermonat gemeinsam über alle Features
    hinweg (users.ki_token_limit, Default 100000), nicht pro Feature einzeln,
    damit künftige KI-Funktionen keine eigene Limit-Logik brauchen. Wirft
    KiLimitError bei aufgebrauchtem Kontingent, KiFehler bei anderen Problemen.
    Bei Erfolg wird der tatsächliche Verbrauch aus der Antwort in ki_nutzung
    protokolliert.

    `bilder` (Wunsch #80, OCR-Import): optionale Liste aus (mime_type,
    base64_daten)-Tupeln fuer Bildeingabe (Vision) – OpenRouter/OpenAI-
    kompatibles content-Array statt reinem Text."""
    import json, urllib.request, urllib.error
    from flask import current_app

    db = get_db()
    row = db.execute("SELECT ki_token_limit FROM users WHERE id=?", (user_id,)).fetchone()
    limit = row["ki_token_limit"] if row else 100000
    verbraucht = db.execute("""
        SELECT COALESCE(SUM(tokens), 0) FROM ki_nutzung
        WHERE user_id=? AND erstellt >= date('now', 'start of month')
    """, (user_id,)).fetchone()[0]
    if verbraucht >= limit:
        raise KiLimitError(f"Monatliches KI-Kontingent aufgebraucht ({verbraucht}/{limit} Tokens).")

    key = current_app.config.get("OPENROUTER_API_KEY", "")
    if not key:
        raise KiFehler("Kein OPENROUTER_API_KEY konfiguriert.")

    if bilder:
        user_content = [{"type": "text", "text": prompt}]
        for mime, b64 in bilder:
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            })
    else:
        user_content = prompt

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps({
            "model": ki_modell_fuer(feature),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "max_tokens": max_tokens,
        }).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:200]
        raise KiFehler(f"OpenRouter-Fehler {e.code}: {detail}")
    except Exception as e:
        raise KiFehler(f"KI-Aufruf fehlgeschlagen: {e}")

    antwort = data["choices"][0]["message"]["content"]
    tokens  = data.get("usage", {}).get("total_tokens", 0)
    db.execute(
        "INSERT INTO ki_nutzung(user_id, feature, tokens) VALUES(?,?,?)",
        (user_id, feature, tokens),
    )
    db.commit()
    return antwort


def _tts_anfrage(text, modell, stimme, key, response_format):
    import json, urllib.request

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/audio/speech",
        data=json.dumps({
            "model": modell,
            "input": text,
            "voice": stimme,
            "response_format": response_format,
        }).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def ki_tts_zeichen_uebrig(user_id: int) -> int:
    """Wieviele Zeichen des monatlichen TTS-Kontingents noch da sind.

    Wunsch #136: eigene Abfrage statt Wiederverwendung von ki_anfrage()s
    Limit-Logik - andere Tabelle (ki_tts_nutzung statt ki_nutzung), andere
    Einheit (Zeichen statt Tokens)."""
    db = get_db()
    row = db.execute(
        "SELECT ki_tts_zeichen_limit FROM users WHERE id=?", (user_id,)
    ).fetchone()
    limit = row["ki_tts_zeichen_limit"] if row else 50000
    verbraucht = db.execute("""
        SELECT COALESCE(SUM(zeichen), 0) FROM ki_tts_nutzung
        WHERE user_id=? AND erstellt >= date('now', 'start of month')
    """, (user_id,)).fetchone()[0]
    return max(0, limit - verbraucht)


def _tts_nutzung_protokollieren(user_id: int, zeichen: int):
    db = get_db()
    db.execute(
        "INSERT INTO ki_tts_nutzung(user_id, feature, zeichen) VALUES(?,?,?)",
        (user_id, "vokabeln_tts", zeichen),
    )
    db.commit()


def ki_text_zu_sprache(user_id: int, text: str, sprache_id: int):
    """Wandelt Text per OpenRouter-TTS-Endpoint in Sprache um. Gibt
    (audio_bytes, mimetype) zurueck (Wunsch #81) - der Aufrufer braucht den
    Mimetype, um die Datei korrekt auszuliefern/zu cachen, statt die Bytes
    selbst erraten zu muessen. Modell/Stimme kommen aus ki_stimme_fuer() -
    je Sprache konfigurierbar. Manche Modelle (z.B. Gemini TTS) unterstuetzen
    nur response_format=pcm statt mp3 - erst mp3 versuchen, bei genau diesem
    Fehler auf PCM ausweichen und selbst in einen WAV-Container packen
    (Python-Standardbibliothek, keine neue Abhaengigkeit noetig), damit
    <audio>-Tags im Browser die Datei ohne Zusatzwissen abspielen koennen.

    Wunsch #136: zaehlt gegen ein EIGENES, zeichenbasiertes Kontingent
    (users.ki_tts_zeichen_limit, ki_tts_nutzung) statt gegen
    users.ki_token_limit - das ist tokenbasiert (LLM-Text) und TTS wird pro
    Zeichen abgerechnet, eine gemeinsame Zaehlung wuerde die Einheiten
    vermischen. Wirft KiLimitError bei aufgebrauchtem Kontingent, bevor der
    kostenpflichtige Aufruf ueberhaupt stattfindet. Der Aufrufer speichert
    das Ergebnis dauerhaft als Datei (siehe 16_vokabeln.py) - ein einmal
    erzeugtes Wort zaehlt dadurch kein zweites Mal.

    Protokolliert wird erst NACH einem erfolgreichen Aufruf, auf beiden
    Erfolgspfaden (mp3 direkt oder der pcm/wav-Rueckfall) - ein Fehlversuch
    beim Anbieter soll das Kontingent nicht schmaelern."""
    import io, urllib.error, wave
    from flask import current_app

    if ki_tts_zeichen_uebrig(user_id) < len(text):
        raise KiLimitError("Monatliches Kontingent für Sprachausgabe aufgebraucht.")

    key = current_app.config.get("OPENROUTER_API_KEY", "")
    if not key:
        raise KiFehler("Kein OPENROUTER_API_KEY konfiguriert.")

    modell, stimme = ki_stimme_fuer(sprache_id)
    try:
        audio = _tts_anfrage(text, modell, stimme, key, "mp3")
        _tts_nutzung_protokollieren(user_id, len(text))
        return audio, "audio/mpeg"
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:300]
        if e.code != 400 or "pcm" not in detail.lower():
            raise KiFehler(f"TTS-Fehler {e.code}: {detail}")
    except Exception as e:
        raise KiFehler(f"TTS-Aufruf fehlgeschlagen: {e}")

    try:
        pcm = _tts_anfrage(text, modell, stimme, key, "pcm")
    except urllib.error.HTTPError as e:
        raise KiFehler(f"TTS-Fehler {e.code}: {e.read().decode()[:200]}")
    except Exception as e:
        raise KiFehler(f"TTS-Aufruf fehlgeschlagen: {e}")

    # Gemini TTS liefert 24kHz/16-bit/Mono-PCM ohne Container (Google-Doku).
    puffer = io.BytesIO()
    with wave.open(puffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(pcm)
    _tts_nutzung_protokollieren(user_id, len(text))
    return puffer.getvalue(), "audio/wav"


def _auto_grant_all(db, slug):
    app_row = db.execute("SELECT id FROM apps WHERE slug=?", (slug,)).fetchone()
    if not app_row:
        return
    missing = db.execute(
        "SELECT id FROM users WHERE id NOT IN (SELECT user_id FROM grants WHERE app_id=?)",
        (app_row[0],),
    ).fetchall()
    for row in missing:
        lookup, enc = grant_werte(new_token())
        db.execute(
            "INSERT OR IGNORE INTO grants(user_id,app_id,token_lookup,token_enc) VALUES(?,?,?,?)",
            (row[0], app_row[0], lookup, enc))


def _init_db(app):
    with app.app_context():
        db = sqlite3.connect(app.config["DB_PATH"])

        # Vokabeln-Neubau (Wunsch #73): Wunsch #67 ("freie Lernziel-Liste +
        # zwei Uebungstexte") war laut Andi ein Fehlversuch und wird komplett
        # durch das neue Sprachen/Kapitel/Trainer-Schema ersetzt. `vokabeln`
        # wird von keiner anderen Tabelle per FK referenziert, ein Umbau per
        # RENAME ist hier also gefahrlos (siehe Bekannte Issues in server.md
        # zur FK-Falle bei `rezepte`). Die drei echten Vokabeln, die
        # Friederike bereits eingetragen hatte, werden nicht stillschweigend
        # geloescht, sondern der Sprache Englisch zugeordnet uebernommen.
        alte_vok_cols = [r[1] for r in db.execute("PRAGMA table_info(vokabeln)").fetchall()]
        vokabeln_migrieren = "liste_id" in alte_vok_cols
        if vokabeln_migrieren:
            db.execute("ALTER TABLE vokabeln RENAME TO vokabeln_alt_v67")
            db.execute("ALTER TABLE vokabellisten RENAME TO vokabellisten_alt_v67")
            db.commit()

        db.executescript(SCHEMA)

        # Unconditionell statt nur bei leerer Tabelle (Wunsch #76): neue
        # Sprachen in _DEFAULT_SPRACHEN sollen bei jedem Deploy nachgezogen
        # werden, auch wenn schon aeltere Sprachen existieren. UNIQUE(name)
        # + INSERT OR IGNORE macht das idempotent.
        for name in _DEFAULT_SPRACHEN:
            db.execute("INSERT OR IGNORE INTO vokabel_sprachen(name) VALUES(?)", (name,))
        db.commit()

        # Wunsch #81 (Grundprinzip): Standardmodell je bestehendem KI-Zweck
        # einmalig eintragen, damit `manage.py ki_modell`/`ki_stimme` von
        # Anfang an etwas zum Aendern vorfinden, statt stumm auf KI_MODELL
        # zurueckzufallen. INSERT OR IGNORE - ein von Andi gesetzter Wert
        # wird bei folgenden Deploys nicht ueberschrieben.
        for zweck in ("rezepte_import", "vokabeln_ocr", "rezepte_foto_import"):
            db.execute(
                "INSERT OR IGNORE INTO ki_konfiguration(zweck, modell) VALUES(?,?)",
                (zweck, KI_MODELL),
            )
        for (sprache_id,) in db.execute("SELECT id FROM vokabel_sprachen").fetchall():
            db.execute(
                "INSERT OR IGNORE INTO ki_stimmen(sprache_id, modell, stimme) VALUES(?,?,?)",
                (sprache_id, TTS_STANDARD_MODELL, TTS_STANDARD_STIMME),
            )
        db.commit()

        if vokabeln_migrieren:
            englisch = db.execute(
                "SELECT id FROM vokabel_sprachen WHERE name='Englisch'"
            ).fetchone()[0]
            for liste_id, user_id in db.execute(
                "SELECT id, user_id FROM vokabellisten_alt_v67"
            ).fetchall():
                for quelle, ziel in db.execute(
                    "SELECT quelle, ziel FROM vokabeln_alt_v67 WHERE liste_id=? ORDER BY position",
                    (liste_id,),
                ).fetchall():
                    db.execute(
                        "INSERT INTO vokabeln(user_id, sprache_id, fremd, deutsch) VALUES(?,?,?,?)",
                        (user_id, englisch, quelle, ziel),
                    )
            db.execute("DROP TABLE vokabeln_alt_v67")
            db.execute("DROP TABLE vokabellisten_alt_v67")
            db.commit()
        # Wunsch #129: Klartext-Tokens in grants durch token_lookup (HMAC) +
        # token_enc (AES-GCM) ersetzen. Tabellen-Neubau statt ALTER, weil
        # `token` UNIQUE ist und SQLite eine indizierte Spalte nicht per DROP
        # COLUMN entfernen kann (gleiches Muster wie bei kinderplan_eintraege,
        # Wunsch #115). Der Zwischenzustand mit grants_alt_v129 ist das
        # Wiederaufsetz-Signal: bricht der Lauf mittendrin ab, wird beim
        # naechsten Start dort weitergemacht, statt die Migration zu
        # ueberspringen - genau die Falle aus Wunsch #115.
        grant_cols = [r[1] for r in db.execute("PRAGMA table_info(grants)").fetchall()]
        alt_tabelle_da = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='grants_alt_v129'"
        ).fetchone()
        if "token" in grant_cols or alt_tabelle_da:
            key_b64 = app.config.get("TOKEN_KEY", "")
            if not key_b64:
                raise RuntimeError(
                    "TOKEN_KEY fehlt in der .env - er wird gebraucht, um die "
                    "bestehenden Zugangstokens zu verschluesseln (Wunsch #129). "
                    "Erzeugen mit: python3 -c \"import base64,os; "
                    "print(base64.urlsafe_b64encode(os.urandom(32)).decode())\"")
            key = base64.urlsafe_b64decode(key_b64)

            if not alt_tabelle_da:
                db.execute("ALTER TABLE grants RENAME TO grants_alt_v129")
                db.commit()
            db.execute("""
                CREATE TABLE IF NOT EXISTS grants (
                  id           INTEGER PRIMARY KEY,
                  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                  app_id       INTEGER NOT NULL REFERENCES apps(id)  ON DELETE CASCADE,
                  token_lookup TEXT    UNIQUE NOT NULL,
                  token_enc    TEXT    NOT NULL,
                  UNIQUE(user_id, app_id)
                )
            """)
            db.commit()
            # Positionszugriff statt row["..."]: _init_db arbeitet auf einer
            # rohen Verbindung OHNE row_factory (Wunsch #115, Stolperstein).
            for gid, user_id, app_id, klartext in db.execute(
                "SELECT id, user_id, app_id, token FROM grants_alt_v129"
            ).fetchall():
                db.execute(
                    "INSERT OR IGNORE INTO grants(id, user_id, app_id, token_lookup, token_enc) "
                    "VALUES(?,?,?,?,?)",
                    (gid, user_id, app_id,
                     token_lookup(klartext, key), token_verschluesseln(klartext, key)),
                )
            db.commit()
            anzahl_alt = db.execute("SELECT COUNT(*) FROM grants_alt_v129").fetchone()[0]
            anzahl_neu = db.execute("SELECT COUNT(*) FROM grants").fetchone()[0]
            if anzahl_neu != anzahl_alt:
                raise RuntimeError(
                    f"Token-Migration unvollstaendig: {anzahl_neu} von {anzahl_alt} "
                    "uebernommen - grants_alt_v129 bleibt zur Rettung stehen.")
            db.execute("DROP TABLE grants_alt_v129")
            db.commit()
            # Ohne VACUUM blieben die Klartext-Tokens in freigegebenen Seiten
            # der Datei stehen - die Datenbank waere zwar logisch sauber, ein
            # `strings portal.db` haette sie aber weiterhin gefunden (und das
            # naechste Backup mitgenommen). Live gegengeprueft.
            db.execute("VACUUM")
            db.commit()
            log.warning("Wunsch #129: %d Zugangstokens verschluesselt abgelegt.", anzahl_neu)

        for col, definition in [
            ("dark_mode", "INTEGER NOT NULL DEFAULT 0"),
            ("rolle",     "TEXT    NOT NULL DEFAULT 'gast'"),
            ("ki_token_limit", "INTEGER NOT NULL DEFAULT 100000"),
            # Wunsch #136: eigenes Kontingent fuer die TTS-Sprachausgabe,
            # zeichenbasiert statt tokenbasiert (siehe ki_tts_nutzung oben).
            # 50000 Zeichen/Monat entsprechen bei durchschnittlich acht
            # Zeichen je Vokabelwort rund 6000 neuen Woertern - im
            # Familienalltag praktisch unerreichbar, begrenzt aber den
            # Schaden, falls doch einmal viele Woerter auf einen Schlag
            # angelegt werden (z.B. Foto-Import mehrerer Listen).
            ("ki_tts_zeichen_limit", "INTEGER NOT NULL DEFAULT 50000"),
        ]:
            try:
                db.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
                db.commit()
            except sqlite3.OperationalError:
                pass
        for col, definition in [
            ("position",  "INTEGER NOT NULL DEFAULT 0"),
            ("gruppe_id", "INTEGER"),
        ]:
            try:
                db.execute(f"ALTER TABLE grants ADD COLUMN {col} {definition}")
                db.commit()
            except sqlite3.OperationalError:
                pass
        for col, definition in [
            ("titel",       "TEXT"),
            ("prioritaet",  "TEXT"),
            ("erledigt_am", "DATETIME"),
            ("ansicht",     "TEXT"),
            ("umsetzung",   "TEXT"),  # Wunsch #101: was genau umgesetzt wurde
        ]:
            try:
                db.execute(f"ALTER TABLE wuensche ADD COLUMN {col} {definition}")
                db.commit()
            except sqlite3.OperationalError:
                pass
        db.execute(
            "UPDATE wuensche SET erledigt_am=erstellt WHERE erledigt=1 AND erledigt_am IS NULL"
        )
        db.commit()
        for col, definition in [
            ("status", "TEXT NOT NULL DEFAULT 'offen'"),
            ("zugewiesen_rollen", "TEXT"),
            # Wunsch #90: wiederkehrende Aufgaben-Vorlagen (todo_serien) -
            # eine konkrete, eingesetzte Instanz ist ein ganz normales
            # todos-Row mit serie_id gesetzt, damit alle bestehende Todo-
            # Mechanik (Status, Historie, Löschen, Anzeige in der Todo-App)
            # unveraendert mitgenutzt wird.
            ("serie_id", "INTEGER REFERENCES todo_serien(id) ON DELETE SET NULL"),
            # "wochentag" war der urspruengliche Wunsch-#90-Ansatz (Instanz an
            # einen abstrakten Wochentag 0-6 gebunden, passend zum damaligen
            # Wochentag-Raster der Aufgabenplanung). Wunsch #92 (selbe Sitzung,
            # noch keine echten Daten betroffen) baute die Aufgabenplanung auf
            # eine rollierende 14-Tage-Liste mit echten Datumswerten um (wie
            # der Essensplan) - "wochentag" bleibt als totes Altfeld liegen,
            # "plan_tag" (ISO-Datum) ist die neue, tatsaechlich genutzte Spalte.
            ("wochentag", "INTEGER"),
            ("plan_tag", "TEXT"),
        ]:
            try:
                db.execute(f"ALTER TABLE todos ADD COLUMN {col} {definition}")
                db.commit()
            except sqlite3.OperationalError:
                pass
        # Bestehende Aufgaben hatten noch keinen Status (Wunsch #20) -
        # aus dem alten erledigt-Flag ableiten, alles andere ist "offen".
        db.execute("UPDATE todos SET status='erledigt' WHERE erledigt=1 AND status='offen'")
        db.commit()

        # Wunsch #122: tvb_spiele speicherte bisher nur Spiele der Profis, jetzt
        # auch die aller anderen Mannschaften - ohne team_id wuerden sie sich
        # vermischen. Bestehende Zeilen sind per Definition Profi-Spiele (vorher
        # gab es nichts anderes), deshalb einmalig auf die Profi-Team-ID setzen.
        try:
            db.execute("ALTER TABLE tvb_spiele ADD COLUMN team_id TEXT")
            db.commit()
        except sqlite3.OperationalError:
            pass
        db.execute(
            "UPDATE tvb_spiele SET team_id=? WHERE team_id IS NULL",
            ("sr.competitor.6272-143352",),
        )
        db.commit()

        # Wunsch #124: Altersklasse je Mannschaft, damit sich Jugendklassen
        # pro Nutzer ausblenden lassen. tvb_mannschaften ist ein reiner Cache
        # der Vereinsseite - statt die Spalte muehsam nachzufuellen, wird der
        # Cache einmalig verworfen und beim naechsten Seitenaufruf komplett
        # neu aufgebaut (dann mit Altersklasse).
        try:
            db.execute("ALTER TABLE tvb_mannschaften ADD COLUMN altersklasse TEXT")
            db.commit()
            db.execute("DELETE FROM tvb_mannschaften")
            db.commit()
        except sqlite3.OperationalError:
            pass

        # Wunsch #112: mehrere Wochentage je Serien-Vorlage moeglich, statt nur
        # einem - fester_wochentag (einzelner int) bleibt als totes Altfeld
        # liegen, feste_wochentage (kommagetrennt, z.B. "1,3,5") ist ab jetzt
        # die tatsaechlich genutzte Spalte. Bestehende Ein-Wochentag-Serien
        # einmalig in die neue Spalte uebernehmen.
        try:
            db.execute("ALTER TABLE todo_serien ADD COLUMN feste_wochentage TEXT")
            db.commit()
        except sqlite3.OperationalError:
            pass
        db.execute("""
            UPDATE todo_serien SET feste_wochentage = CAST(fester_wochentag AS TEXT)
            WHERE fester_wochentag IS NOT NULL AND feste_wochentage IS NULL
        """)
        db.commit()
        db.executemany(
            "INSERT OR IGNORE INTO apps(slug,name,emoji,beschreibung) VALUES(?,?,?,?)",
            _CORE_APPS,
        )
        # Umbenennung Todos -> Aufgaben (Wunsch #11): INSERT OR IGNORE oben
        # aktualisiert bestehende Zeilen nicht, deshalb einmalig nachziehen.
        db.execute("UPDATE apps SET name='Aufgaben' WHERE slug='todo' AND name='Todos'")
        try:
            db.execute("ALTER TABLE apps ADD COLUMN offline_faehig INTEGER NOT NULL DEFAULT 0")
            db.commit()
        except sqlite3.OperationalError:
            pass
        # Offline-Faehigkeit ist bewusst hier in Code definiert (per Migration
        # gesetzt), nicht als frei umschaltbare Admin-Einstellung - ob eine
        # App offline sicher funktioniert (keine live-schreibenden Interak-
        # tionen ohne eigene Warteschlange), ist eine Entwicklerentscheidung,
        # die sowieso einen Deploy braucht. "hilfe": rein statischer Text,
        # keine Formulare/Schreibzugriffe. "einkauf": Abhaken + Neu-Eintragen
        # laufen jetzt ueber eine lokale Warteschlange (localStorage), die bei
        # Netzwerkfehler statt sofort zu scheitern optimistisch weiterlaeuft
        # und synchronisiert, sobald wieder Verbindung da ist - Bearbeiten/
        # Loeschen bleiben bewusst NICHT offline-sicher (geringere Prioritaet
        # fuer den Laden-Anwendungsfall, siehe einkauf.html).
        db.execute("UPDATE apps SET offline_faehig=1 WHERE slug IN ('hilfe', 'einkauf')")
        db.commit()
        if db.execute("SELECT COUNT(*) FROM geholfen_aufgaben").fetchone()[0] == 0:
            for name, emoji, gew in _DEFAULT_AUFGABEN:
                db.execute(
                    "INSERT INTO geholfen_aufgaben(name,emoji,gewichtung) VALUES(?,?,?)",
                    (name, emoji, gew),
                )
        # Wunsch #96: zwei Umbenennungen + eine neue Aufgabe. Kein UNIQUE(name)
        # auf geholfen_aufgaben, deshalb Existenz-Check statt INSERT OR IGNORE.
        db.execute("UPDATE geholfen_aufgaben SET name='Spülmaschine einräumen' WHERE name='Spülmaschine ein'")
        db.execute("UPDATE geholfen_aufgaben SET name='Wäsche zusammenlegen' WHERE name='Wäsche falten'")
        if not db.execute("SELECT 1 FROM geholfen_aufgaben WHERE name='Spülmaschine ausräumen'").fetchone():
            db.execute(
                "INSERT INTO geholfen_aufgaben(name,emoji,gewichtung) VALUES(?,?,?)",
                ("Spülmaschine ausräumen", "🍳", 1.0),
            )
        db.commit()
        if db.execute("SELECT COUNT(*) FROM einkauf_laeden").fetchone()[0] == 0:
            for laden in _DEFAULT_LAEDEN:
                db.execute("INSERT OR IGNORE INTO einkauf_laeden(name) VALUES(?)", (laden,))

        # Essensplan: zwei Mahlzeiten pro Tag statt einer (Wunsch #35, überarbeitet).
        # Altes Schema hatte nur `tag TEXT UNIQUE` ohne `mahlzeit` - da SQLite
        # UNIQUE-Constraints nicht per ALTER TABLE ändern kann, wird die Tabelle
        # einmalig neu aufgebaut und bestehende Einträge als "abend" übernommen.
        cols = [r[1] for r in db.execute("PRAGMA table_info(essensplan_eintraege)").fetchall()]
        if "mahlzeit" not in cols:
            db.execute("ALTER TABLE essensplan_eintraege RENAME TO essensplan_eintraege_alt")
            db.execute("""
                CREATE TABLE essensplan_eintraege (
                  id           INTEGER PRIMARY KEY,
                  tag          TEXT    NOT NULL,
                  mahlzeit     TEXT    NOT NULL DEFAULT 'abend',
                  rezept_id    INTEGER REFERENCES rezepte(id) ON DELETE SET NULL,
                  text         TEXT,
                  erstellt_von INTEGER REFERENCES users(id) ON DELETE SET NULL,
                  erstellt     TEXT    NOT NULL DEFAULT (datetime('now')),
                  UNIQUE(tag, mahlzeit)
                )
            """)
            db.execute("""
                INSERT INTO essensplan_eintraege(id, tag, mahlzeit, rezept_id, text, erstellt_von, erstellt)
                SELECT id, tag, 'abend', rezept_id, text, erstellt_von, erstellt
                FROM   essensplan_eintraege_alt
            """)
            db.execute("DROP TABLE essensplan_eintraege_alt")
            db.commit()

        # Wunsch #115: Geholfen-Zuweisungen im Aufgabenplan sind jetzt
        # Einzeltermine (plan_tag, echtes Datum) statt einer fortlaufenden
        # woechentlichen Regel (wochentag) - Andis ausdrueckliche Entscheidung
        # nach Rueckfrage (2026-08-02): ALLE Zuweisungen werden umgestellt,
        # auch bestehende, keine Regel bleibt als Muster erhalten. Die
        # UNIQUE-Constraint aendert sich (...+wochentag -> ...+plan_tag),
        # SQLite kann das nicht per ALTER TABLE, deshalb Neubau wie beim
        # Essensplan oben. Kein FK zeigt AUF kinderplan_eintraege (siehe
        # Bekannte Issues zur RENAME+Neubau-Falle bei referenzierten
        # Tabellen) - hier also gefahrlos.
        # HINWEIS: `db` in dieser Funktion ist eine rohe sqlite3-Verbindung
        # OHNE row_factory=Row (siehe db=sqlite3.connect(...) oben) - fetchall()
        # liefert also nackte Tupel, Zugriff nur per Index, nie per Spaltenname
        # (Live-Fehler beim ersten Deploy-Versuch: "tuple indices must be
        # integers", siehe journal.md 2026-08-02).
        alt_tabelle_vorhanden = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='kinderplan_eintraege_alt'"
        ).fetchone()
        cols = [r[1] for r in db.execute("PRAGMA table_info(kinderplan_eintraege)").fetchall()]
        if "plan_tag" not in cols:
            db.execute("ALTER TABLE kinderplan_eintraege RENAME TO kinderplan_eintraege_alt")
            db.execute("""
                CREATE TABLE kinderplan_eintraege (
                  id         INTEGER PRIMARY KEY,
                  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                  aufgabe_id INTEGER NOT NULL REFERENCES geholfen_aufgaben(id) ON DELETE CASCADE,
                  wochentag  INTEGER NOT NULL,
                  plan_tag   TEXT,
                  position   INTEGER NOT NULL DEFAULT 0,
                  erstellt   TEXT    NOT NULL DEFAULT (datetime('now')),
                  UNIQUE(user_id, aufgabe_id, plan_tag)
                )
            """)
            alt_tabelle_vorhanden = True
        # Eigene Bedingung (nicht nur "gerade eben umbenannt"): falls ein
        # frueherer Deploy-Versuch nach dem Umbenennen/Neuanlegen abgestuerzt
        # ist, existiert kinderplan_eintraege_alt weiterhin mit unmigrierten
        # Daten, obwohl die neue Tabelle schon plan_tag hat - dieser Zweig
        # muss dann trotzdem nochmal laufen, um sauber abzuschliessen.
        if alt_tabelle_vorhanden:
            # Jede bestehende woechentliche Regel wird fuer jeden zu ihrem
            # Wochentag passenden Tag im AKTUELL sichtbaren 14-Tage-Fenster
            # (aktuelle + naechste Woche, gleiche Berechnung wie in
            # 13_kinderplan.py) zu einem eigenen Einzeltermin.
            heute_migration  = date.today()
            montag_migration = heute_migration - timedelta(days=heute_migration.weekday())
            fenster = [montag_migration + timedelta(days=i) for i in range(14)]
            alte_regeln = db.execute(
                "SELECT id, user_id, aufgabe_id, wochentag, position, erstellt FROM kinderplan_eintraege_alt"
            ).fetchall()
            for _id, user_id, aufgabe_id, wochentag, position, erstellt in alte_regeln:
                for tag in fenster:
                    if tag.weekday() != wochentag:
                        continue
                    db.execute(
                        "INSERT OR IGNORE INTO kinderplan_eintraege"
                        "(user_id, aufgabe_id, wochentag, plan_tag, position, erstellt) "
                        "VALUES(?,?,?,?,?,?)",
                        (user_id, aufgabe_id, wochentag, tag.isoformat(), position, erstellt),
                    )
            db.execute("DROP TABLE kinderplan_eintraege_alt")
            db.commit()

        # Einkauf-Kategorien: von hardcodierter Liste in eigene Tabelle (Wunsch #37).
        if db.execute("SELECT COUNT(*) FROM einkauf_kategorien").fetchone()[0] == 0:
            for pos, name in enumerate(_DEFAULT_KATEGORIEN):
                db.execute(
                    "INSERT INTO einkauf_kategorien(name, position) VALUES(?,?)", (name, pos)
                )

        # Packliste (Wunsch #111): Kategorien vorbelegen, analog zu Einkauf.
        if db.execute("SELECT COUNT(*) FROM packlisten_kategorien").fetchone()[0] == 0:
            for pos, name in enumerate(_DEFAULT_PACKLISTEN_KATEGORIEN):
                db.execute(
                    "INSERT INTO packlisten_kategorien(name, position) VALUES(?,?)", (name, pos)
                )
            db.commit()
        for col, definition in [
            ("kategorie_id", "INTEGER REFERENCES einkauf_kategorien(id)"),
        ]:
            try:
                db.execute(f"ALTER TABLE einkauf_eintraege ADD COLUMN {col} {definition}")
                db.commit()
            except sqlite3.OperationalError:
                pass
        db.execute("""
            UPDATE einkauf_eintraege
            SET kategorie_id = (SELECT id FROM einkauf_kategorien WHERE name = einkauf_eintraege.kategorie)
            WHERE kategorie_id IS NULL
        """)
        sonstiges = db.execute("SELECT id FROM einkauf_kategorien WHERE name='Sonstiges'").fetchone()
        if sonstiges:
            db.execute(
                "UPDATE einkauf_eintraege SET kategorie_id=? WHERE kategorie_id IS NULL", (sonstiges[0],)
            )
        db.commit()

        # Einkauf: geaendert-Zeitstempel fuer den Sync-Abgleich (Wunsch #100).
        # SQLite erlaubt bei ALTER TABLE ADD COLUMN keinen nicht-konstanten
        # Default (datetime('now')/CURRENT_TIMESTAMP schlagen fehl - live
        # geprueft) - deshalb hier nullable anlegen und per UPDATE backfuellen;
        # neue Installationen bekommen den NOT NULL DEFAULT direkt aus SCHEMA.
        try:
            db.execute("ALTER TABLE einkauf_eintraege ADD COLUMN geaendert TEXT")
            db.commit()
        except sqlite3.OperationalError:
            pass
        db.execute("UPDATE einkauf_eintraege SET geaendert = erstellt WHERE geaendert IS NULL")
        db.commit()

        # Einkauf: Angebot in mehreren Märkten gleichzeitig möglich (Wunsch #86)
        # - einkauf_eintraege.laden_id war bisher ein einzelner Markt, jetzt
        # einkauf_eintrag_laeden als n:m-Zuordnung. Alte Einzelwerte einmalig
        # übernehmen (idempotent per INSERT OR IGNORE), laden_id selbst bleibt
        # als totes Altfeld liegen (SQLite kann Spalten nicht gefahrlos droppen,
        # siehe Rezepte-Anleitung weiter unten für die gleiche Begründung) - neuer
        # Code liest/schreibt nur noch einkauf_eintrag_laeden.
        db.execute("""
            INSERT OR IGNORE INTO einkauf_eintrag_laeden(eintrag_id, laden_id)
            SELECT id, laden_id FROM einkauf_eintraege WHERE laden_id IS NOT NULL
        """)
        db.commit()

        # Rezepte: Zubereitung in einzelne Schritte splitten (analog zu
        # rezept_zutaten) statt ein Textfeld, dazu Portionen ergaenzen - naeher
        # an schema.org/Recipe (HowToStep-Liste, recipeYield), weniger
        # Informationsverlust beim Import.
        #
        # WICHTIG: rezepte NICHT per RENAME+Neubau umbauen, obwohl SQLite keine
        # Spalte per ALTER TABLE entfernen kann. rezepte wird von rezept_zutaten,
        # rezept_schritte UND essensplan_eintraege per Foreign Key referenziert -
        # SQLite schreibt beim Umbenennen einer referenzierten Tabelle automatisch
        # die FK-Klauseln der referenzierenden Tabellen auf den Zwischennamen um
        # (rezepte -> rezepte_alt), und nach dem DROP TABLE rezepte_alt zeigen
        # diese FKs dann ins Leere ("no such table: rezepte_alt" bei jedem
        # INSERT/UPDATE). Genau das ist einmal live passiert und musste manuell
        # repariert werden (siehe journal.md). Deshalb nur ADD COLUMN (unschaedlich)
        # und die alte anleitung-Spalte bleibt als totes Altfeld liegen - ihr
        # Inhalt wird einmalig nach rezept_schritte uebernommen, mehr nicht.
        for col, definition in [
            ("portionen", "TEXT"),
            ("kategorie", "TEXT"),
            ("quelle_url", "TEXT"),
        ]:
            try:
                db.execute(f"ALTER TABLE rezepte ADD COLUMN {col} {definition}")
                db.commit()
            except sqlite3.OperationalError:
                pass
        cols = [r[1] for r in db.execute("PRAGMA table_info(rezepte)").fetchall()]
        if "anleitung" in cols and db.execute("SELECT COUNT(*) FROM rezept_schritte").fetchone()[0] == 0:
            for alt in db.execute(
                "SELECT id, anleitung FROM rezepte WHERE anleitung IS NOT NULL AND anleitung != ''"
            ).fetchall():
                zeilen = [z.strip() for z in (alt[1] or "").splitlines() if z.strip()]
                for pos, zeile in enumerate(zeilen):
                    db.execute(
                        "INSERT INTO rezept_schritte(rezept_id, text, position) VALUES(?,?,?)",
                        (alt[0], zeile, pos),
                    )
            db.commit()

        # Wunsch #66: Koerperbau-Regler (schlank/kraeftig), ADD COLUMN reicht -
        # tierbaukasten_kreationen wird von keiner anderen Tabelle per FK referenziert.
        try:
            db.execute("ALTER TABLE tierbaukasten_kreationen ADD COLUMN koerperbau INTEGER NOT NULL DEFAULT 50")
            db.commit()
        except sqlite3.OperationalError:
            pass

        # Feedback von Friederike (direkt, nicht ueber die Werkstatt-App):
        # Mensch-Figur per DiceBear/Avataaars statt Handzeichnung - alle
        # Auswahlwerte als JSON in einer Spalte, nur bei tier_typ='mensch' befuellt.
        try:
            db.execute("ALTER TABLE tierbaukasten_kreationen ADD COLUMN dicebear_optionen TEXT")
            db.commit()
        except sqlite3.OperationalError:
            pass

        _auto_grant_all(db, "hilfe")
        _auto_grant_all(db, "einkauf")
        db.commit()
        db.close()


def init_app(app):
    @app.teardown_appcontext
    def close_db(exc=None):
        db = g.pop("db", None)
        if db:
            db.close()

    _init_db(app)

    # Wunsch #140, Stufe 4: Adress-Bausteine für jede Vorlage.
    #
    # `tp` kommt aus request.view_args und NICHT aus der Template-Variablen
    # `token`. Grund: `01_start_token.py` reicht auf `/start` ersatzweise den
    # Home-Token an die Vorlage durch (damit `const TOKEN` gefüllt bleibt).
    # Käme `tp` von dort, stünde auf `/start` plötzlich wieder ein Token in
    # allen Links. view_args sagt dagegen genau das, was in der Adresszeile
    # steht - und die Links sollen der Adresszeile folgen.
    @app.context_processor
    def _adress_bausteine():
        return {
            "tp":            token_pfad((request.view_args or {}).get("token")),
            "app_pfad":      app_pfad,
            "start_pfad":    start_pfad,
            "manifest_pfad": manifest_pfad,
        }

    @app.route("/health")
    def health():
        get_db().execute("SELECT 1")
        return jsonify(status="ok")

    @app.after_request
    def _sw_scope_header(resp):
        # sw.js liegt unter /static/, dessen Verzeichnis waere ohne diesen
        # Header der maximale Scope - der Service Worker muss aber die ganze
        # Seite (/p/..., /a/.../...) kontrollieren koennen, nicht nur /static/.
        if request.path == "/static/sw.js":
            resp.headers["Service-Worker-Allowed"] = "/"
        return resp
