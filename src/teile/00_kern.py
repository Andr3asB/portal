import sqlite3, secrets, logging
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


def grant(token: str, app_slug: str):
    """Gibt Row(id, name, farbe, is_admin, home_token, hilfe_token) zurück wenn Token gültig, sonst None."""
    db = get_db()
    return db.execute("""
        SELECT u.id, u.name, u.farbe, u.is_admin, u.dark_mode, u.rolle,
               (SELECT g2.token FROM grants g2
                JOIN apps a2 ON a2.id = g2.app_id
                WHERE g2.user_id = u.id AND a2.slug = 'home') AS home_token,
               (SELECT g3.token FROM grants g3
                JOIN apps a3 ON a3.id = g3.app_id
                WHERE g3.user_id = u.id AND a3.slug = 'hilfe') AS hilfe_token
        FROM   grants g
        JOIN   users u ON u.id = g.user_id
        JOIN   apps  a ON a.id = g.app_id
        WHERE  g.token = ? AND a.slug = ?
    """, (token, app_slug)).fetchone()


def new_token() -> str:
    return secrets.token_urlsafe(18)


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


def ki_text_zu_sprache(text: str, sprache_id: int):
    """Wandelt Text per OpenRouter-TTS-Endpoint in Sprache um. Gibt
    (audio_bytes, mimetype) zurueck (Wunsch #81) - der Aufrufer braucht den
    Mimetype, um die Datei korrekt auszuliefern/zu cachen, statt die Bytes
    selbst erraten zu muessen. Modell/Stimme kommen aus ki_stimme_fuer() -
    je Sprache konfigurierbar. Manche Modelle (z.B. Gemini TTS) unterstuetzen
    nur response_format=pcm statt mp3 - erst mp3 versuchen, bei genau diesem
    Fehler auf PCM ausweichen und selbst in einen WAV-Container packen
    (Python-Standardbibliothek, keine neue Abhaengigkeit noetig), damit
    <audio>-Tags im Browser die Datei ohne Zusatzwissen abspielen koennen.
    Zaehlt bewusst NICHT gegen users.ki_token_limit: das Kontingent ist
    tokenbasiert (LLM-Text), TTS wird pro Zeichen abgerechnet und ist bei
    kurzen Einzelwoertern vernachlaessigbar, zumal jedes Wort nur einmal
    erzeugt und dauerhaft gecacht wird (Aufrufer speichert das Ergebnis
    als Datei, siehe 16_vokabeln.py)."""
    import io, urllib.error, wave
    from flask import current_app

    key = current_app.config.get("OPENROUTER_API_KEY", "")
    if not key:
        raise KiFehler("Kein OPENROUTER_API_KEY konfiguriert.")

    modell, stimme = ki_stimme_fuer(sprache_id)
    try:
        return _tts_anfrage(text, modell, stimme, key, "mp3"), "audio/mpeg"
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
        db.execute("INSERT OR IGNORE INTO grants(user_id,app_id,token) VALUES(?,?,?)",
                   (row[0], app_row[0], secrets.token_urlsafe(18)))


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
        for col, definition in [
            ("dark_mode", "INTEGER NOT NULL DEFAULT 0"),
            ("rolle",     "TEXT    NOT NULL DEFAULT 'gast'"),
            ("ki_token_limit", "INTEGER NOT NULL DEFAULT 100000"),
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
