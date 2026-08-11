"""Wunsch #206 (Sicherheitsaudit 11.08.2026): KI-Kontingentprüfung war nicht
atomar.

`ki_anfrage()`/`ki_text_zu_sprache()` prüften das Monatskontingent VOR dem
kostenpflichtigen Aufruf und schrieben den Verbrauch erst NACH einer
erfolgreichen Antwort. Zwischen beidem liegt ein Netzwerk-Roundtrip von bis
zu 30 Sekunden – ein klassisches Time-of-Check-to-Time-of-Use-Problem, ohne
Transaktion oder Sperre. Der Container läuft mit mehreren Threads: parallele
Anfragen desselben Nutzers sahen alle denselben, noch niedrigen Stand,
bestanden alle die Prüfung, und erst danach schrieb jede ihren Verbrauch –
das Kontingent liess sich damit um ein Vielfaches überschreiten. Da alle
KI-Funktionen dasselbe OpenRouter-Konto teilen (Wunsch #183), ist das echtes
Geld.

Die Lösung reserviert atomar (`_kontingent_reservieren()`, `BEGIN IMMEDIATE`
auf einer eigenen Verbindung) VOR dem Netzwerkaufruf und korrigiert bzw. gibt
danach frei. Der wichtigste Test hier simuliert die Race mit ECHTEN Threads,
nicht nur sequenziellen Aufrufen – ein rein sequenzieller Test hätte auch die
ALTE, verwundbare Reihenfolge nicht von der neuen unterschieden.
"""
import threading

import pytest


@pytest.fixture()
def kern():
    import teile.kern as k
    return k


# --- Die Reservierung für sich -----------------------------------------

def test_reservierung_schlaegt_fehl_wenn_das_kontingent_nicht_reicht(app, kern, admin, db):
    v = db["verbindung"]
    v.execute("UPDATE users SET ki_token_limit=100 WHERE id=?", (admin["id"],))
    v.commit()
    with app.app_context():
        with pytest.raises(kern.KiLimitError):
            kern._kontingent_reservieren(
                "ki_nutzung", "tokens", admin["id"], "ki_token_limit", 100000,
                150, "test")


def test_reservierung_legt_bei_erfolg_eine_zeile_an(app, kern, admin, db):
    with app.app_context():
        zid = kern._kontingent_reservieren(
            "ki_nutzung", "tokens", admin["id"], "ki_token_limit", 100000,
            500, "test")
    zeile = db["verbindung"].execute(
        "SELECT tokens FROM ki_nutzung WHERE id=?", (zid,)).fetchone()
    assert zeile["tokens"] == 500


def test_freigeben_entfernt_die_zeile_restlos(app, kern, admin, db):
    """Kein Verwaisen: eine zurückgezogene Reservierung darf keine Spur im
    Kontingent hinterlassen."""
    with app.app_context():
        zid = kern._kontingent_reservieren(
            "ki_nutzung", "tokens", admin["id"], "ki_token_limit", 100000,
            500, "test")
        kern._kontingent_freigeben("ki_nutzung", zid)
    assert db["verbindung"].execute(
        "SELECT COUNT(*) FROM ki_nutzung WHERE id=?", (zid,)).fetchone()[0] == 0


def test_korrigieren_ersetzt_den_vorlaeufigen_wert(app, kern, admin, db):
    with app.app_context():
        zid = kern._kontingent_reservieren(
            "ki_nutzung", "tokens", admin["id"], "ki_token_limit", 100000,
            1500, "test")   # max_tokens als Obergrenze
        kern._kontingent_korrigieren("ki_nutzung", "tokens", zid, 42)  # echter Verbrauch
    zeile = db["verbindung"].execute(
        "SELECT tokens FROM ki_nutzung WHERE id=?", (zid,)).fetchone()
    assert zeile["tokens"] == 42


# --- Die eigentliche Race -------------------------------------------------

def test_parallele_reservierungen_koennen_das_kontingent_nicht_ueberschreiten(app, kern, admin, db):
    """Der Kern des Befunds, mit echten Threads statt nur sequenziellen
    Aufrufen: Ohne die Transaktion in _kontingent_reservieren() (BEGIN
    IMMEDIATE) sähen mehrere gleichzeitige Aufrufe denselben Stand VOR
    irgendeiner Reservierung und bestünden alle die Prüfung - genau das ist
    im vorherigen Code passiert.

    20 Threads versuchen gleichzeitig, je 30 Tokens gegen ein Limit von 100
    zu reservieren (Platz für genau 3 erfolgreiche). Ohne Atomarität hätten
    deutlich mehr als 3 die Prüfung bestanden - mit ihr höchstens 3."""
    v = db["verbindung"]
    v.execute("UPDATE users SET ki_token_limit=100 WHERE id=?", (admin["id"],))
    v.commit()

    erfolge = []
    fehler = []
    los = threading.Barrier(20)

    def versuchen():
        los.wait()   # alle Threads starten so gleichzeitig wie möglich
        with app.app_context():
            try:
                zid = kern._kontingent_reservieren(
                    "ki_nutzung", "tokens", admin["id"], "ki_token_limit",
                    100000, 30, "race-test")
                erfolge.append(zid)
            except kern.KiLimitError:
                fehler.append(1)

    threads = [threading.Thread(target=versuchen) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(erfolge) == 3, (
        f"{len(erfolge)} von 20 gleichzeitigen Anfragen sind durchgekommen - "
        f"bei einem Limit von 100 und 30 je Anfrage dürfen es hoechstens 3 sein."
    )
    assert len(fehler) == 17

    tatsaechlich = v.execute(
        "SELECT COALESCE(SUM(tokens),0) FROM ki_nutzung WHERE user_id=?",
        (admin["id"],)).fetchone()[0]
    assert tatsaechlich <= 100, (
        f"{tatsaechlich} Tokens tatsächlich reserviert - über dem Limit von 100."
    )


# --- Angewendet in ki_anfrage() / ki_text_zu_sprache() ----------------------

def test_ki_anfrage_gibt_reservierung_bei_fehler_frei(app, kern, admin, db, monkeypatch):
    def kaputt(*a, **kw):
        raise RuntimeError("OpenRouter nicht erreichbar")
    monkeypatch.setattr(__import__("urllib.request", fromlist=["urlopen"]),
                        "urlopen", kaputt)
    app.config["OPENROUTER_API_KEY"] = "test-key"
    try:
        with app.app_context():
            with pytest.raises(kern.KiFehler):
                kern.ki_anfrage(admin["id"], "test", "system", "prompt", max_tokens=50)
    finally:
        app.config["OPENROUTER_API_KEY"] = ""
    # Keine verwaiste Zeile - weder als Platzhalter noch sonst irgendeine.
    assert db["verbindung"].execute(
        "SELECT COUNT(*) FROM ki_nutzung WHERE user_id=? AND feature='test'",
        (admin["id"],)).fetchone()[0] == 0


def test_ki_anfrage_gibt_reservierung_bei_http_fehler_frei(app, kern, admin, db, monkeypatch):
    """Derselbe Fall wie oben, aber über den ANDEREN Fehlerpfad
    (urllib.error.HTTPError statt einer allgemeinen Exception) - beide Zweige
    in ki_anfrage() müssen die Reservierung unabhängig voneinander
    zurückgeben. Ein Test, der nur den einen Zweig prüft, deckt den anderen
    nicht ab, wie sich beim Fehler-Einbauen gezeigt hat."""
    import urllib.error

    def http_fehler(*a, **kw):
        raise urllib.error.HTTPError(
            "https://openrouter.ai/x", 500, "Serverfehler",
            {}, __import__("io").BytesIO(b"kaputt"))

    monkeypatch.setattr(__import__("urllib.request", fromlist=["urlopen"]),
                        "urlopen", http_fehler)
    app.config["OPENROUTER_API_KEY"] = "test-key"
    try:
        with app.app_context():
            with pytest.raises(kern.KiFehler):
                kern.ki_anfrage(admin["id"], "test", "system", "prompt", max_tokens=50)
    finally:
        app.config["OPENROUTER_API_KEY"] = ""
    assert db["verbindung"].execute(
        "SELECT COUNT(*) FROM ki_nutzung WHERE user_id=? AND feature='test'",
        (admin["id"],)).fetchone()[0] == 0


def test_ki_anfrage_korrigiert_auf_den_echten_verbrauch(app, kern, admin, db, monkeypatch):
    import json

    class Antwort:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": "Hallo"}}],
                "usage": {"total_tokens": 17},
            }).encode()

    monkeypatch.setattr(__import__("urllib.request", fromlist=["urlopen"]),
                        "urlopen", lambda *a, **kw: Antwort())
    app.config["OPENROUTER_API_KEY"] = "test-key"
    try:
        with app.app_context():
            kern.ki_anfrage(admin["id"], "test", "system", "prompt", max_tokens=1500)
    finally:
        app.config["OPENROUTER_API_KEY"] = ""
    zeile = db["verbindung"].execute(
        "SELECT tokens FROM ki_nutzung WHERE user_id=? AND feature='test'",
        (admin["id"],)).fetchone()
    assert zeile["tokens"] == 17, "die Reservierung (1500) wurde nicht auf den echten Wert korrigiert"
