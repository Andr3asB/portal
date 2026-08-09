"""Gemeinsame Testumgebung.

Baut für jeden Test eine frische, leere Portal-Datenbank in einem
Temporärverzeichnis auf und legt eine kleine, realistische Familie an:
ein Admin, ein Kind, ein Elternteil. Nichts davon berührt die
Produktionsdatenbank – DB_PATH und TOKEN_KEY kommen bei dieser App
vollständig aus der Umgebung (siehe src/app.py), deshalb genügt es, sie zu
setzen, bevor die App importiert wird.

Wichtig: Die App wird EINMAL importiert (Flask-Blueprints lassen sich nicht
mehrfach registrieren), aber die Datenbank pro Test neu aufgebaut. Deshalb
ist `app` ein session-scope-Fixture und `db` ein function-scope-Fixture.
"""
import base64
import importlib
import os
import sys
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
SRC = WURZEL / "src"

# Schon beim Laden von conftest, nicht erst im Fixture: Testmodule sollen
# `from teile.kern import ...` auf Modulebene schreiben können. Der reine
# Import ist harmlos - Konfiguration wird erst beim Aufruf gebraucht.
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(scope="session")
def token_key() -> str:
    """Frischer Schlüssel für die Token-Verschlüsselung (Wunsch #129)."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


@pytest.fixture(scope="session")
def app(tmp_path_factory, token_key):
    """Die echte Flask-App, gegen eine Wegwerf-Datenbank."""
    daten = tmp_path_factory.mktemp("portal-daten")
    os.environ["DB_PATH"] = str(daten / "portal.db")
    os.environ["DATA_DIR"] = str(daten)
    os.environ["TOKEN_KEY"] = token_key
    os.environ["SECRET_KEY"] = "test-secret-key"
    # Wunsch #145: Der Hintergrund-Thread für Geburtstags-Erinnerungen bleibt
    # im Test aus. Er schreibt nebenher in dieselbe SQLite-Datei und liess die
    # Fixtures mit "database is locked" auflaufen - und ein Test, der zufällig
    # gegen einen Thread läuft, ist ohnehin kein Test, sondern ein Würfelspiel.
    os.environ["GEBURTSTAGS_ERINNERUNGEN"] = "0"
    # Wunsch #183: derselbe Grund - und der Guthaben-Wächter würde zusätzlich
    # bei jedem Testlauf OpenRouter anrufen.
    os.environ["KI_GUTHABEN_WACHT"] = "0"
    # Kein OpenRouter/VAPID/hae im Test – die Module müssen ohne auskommen.
    for leer in ("OPENROUTER_API_KEY", "VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY",
                 "HAE_API_URL", "HAE_API_KEY"):
        os.environ.pop(leer, None)

    modul = importlib.import_module("app")
    modul.app.config["TESTING"] = True
    return modul.app


@pytest.fixture()
def db(app):
    """Leert die Datenbank und legt die Testfamilie an. Läuft vor jedem Test."""
    import sqlite3
    from teile.kern import token_lookup, new_token

    verbindung = sqlite3.connect(app.config["DB_PATH"])
    verbindung.row_factory = sqlite3.Row
    verbindung.execute("PRAGMA foreign_keys=ON")

    # Umgekehrte Logik seit Wunsch #162: NICHT aufzaehlen, was geleert wird,
    # sondern was STEHEN BLEIBT. Die alte Liste (grants, geburtstage,
    # wuensche, users) musste bei jeder neuen Tabelle nachgezogen werden, und
    # vergass man es, lief der Bestand still ueber alle Tests hinweg mit:
    # erst fielen Zaehlungen daneben (#145 Geburtstage), dann zaehlte ein Test
    # global statt je Wunsch (#161), dann kollidierte ein UNIQUE(tag, mahlzeit)
    # im Essensplan (#162). Immer derselbe Fehler, dreimal neu gelernt.
    #
    # Der Grund ist jedesmal: die Tabelle haengt nicht per ON DELETE CASCADE
    # am Nutzer. Wer das vergisst, merkt es nicht - Tests werden dadurch nicht
    # rot, sondern unzuverlaessig.
    #
    # Vergisst man umgekehrt eine SEED-Tabelle hier einzutragen, fehlen die
    # Stammdaten und die Tests schlagen sofort und laut fehl. Diese
    # Fehlerrichtung ist die richtige.
    BLEIBT = {
        "apps", "einkauf_kategorien", "einkauf_laeden", "geholfen_aufgaben",
        "ki_konfiguration", "ki_stimmen", "packlisten_kategorien",
        "vokabel_sprachen", "sqlite_sequence",
    }
    tabellen = [r[0] for r in verbindung.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    verbindung.execute("PRAGMA foreign_keys=OFF")
    for name in tabellen:
        if name not in BLEIBT:
            verbindung.execute(f"DELETE FROM {name}")
    verbindung.execute("PRAGMA foreign_keys=ON")
    verbindung.commit()

    with app.app_context():
        def anlegen(name, farbe, is_admin, rolle):
            uid = verbindung.execute(
                "INSERT INTO users(name, farbe, is_admin, rolle) VALUES(?,?,?,?) RETURNING id",
                (name, farbe, is_admin, rolle),
            ).fetchone()["id"]
            verbindung.commit()
            return uid

        def freischalten(uid, slug):
            app_row = verbindung.execute(
                "SELECT id FROM apps WHERE slug=?", (slug,)
            ).fetchone()
            assert app_row is not None, f"App-Slug '{slug}' existiert nicht"
            klartext = new_token()
            verbindung.execute(
                "INSERT INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                (uid, app_row["id"], token_lookup(klartext)),
            )
            verbindung.commit()
            return klartext

        familie = {}
        for name, farbe, is_admin, rolle, apps in [
            ("TestAdmin",  "#111111", 1, "eltern", ["home", "hilfe", "admin", "einkauf", "todo"]),
            ("TestKind",   "#222222", 0, "kind",   ["home", "hilfe", "einkauf"]),
            ("TestEltern", "#333333", 0, "eltern", ["home", "hilfe", "einkauf"]),
        ]:
            uid = anlegen(name, farbe, is_admin, rolle)
            familie[name] = {
                "id": uid, "rolle": rolle, "is_admin": is_admin,
                "tokens": {slug: freischalten(uid, slug) for slug in apps},
            }

    yield {"verbindung": verbindung, "familie": familie}
    verbindung.close()


@pytest.fixture()
def client(app, db):
    """Test-Client mit frisch aufgebauter Familie."""
    return app.test_client()


@pytest.fixture()
def admin(db):
    return db["familie"]["TestAdmin"]


@pytest.fixture()
def kind(db):
    return db["familie"]["TestKind"]


@pytest.fixture()
def eltern(db):
    return db["familie"]["TestEltern"]
